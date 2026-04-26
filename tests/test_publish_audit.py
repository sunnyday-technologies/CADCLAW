"""Tests for cadharness/publish_audit.py."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cadharness.publish_audit import run_publish_audit
from cadharness.findings import Severity
from cadharness.rules import RuleSet, PublishAuditModel


def _has_git() -> bool:
    return shutil.which("git") is not None


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _make_repo(td: Path):
    _git(["init", "-q"], td)
    _git(["config", "user.email", "test@example.com"], td)
    _git(["config", "user.name", "Tester"], td)


class TestStateClassification(unittest.TestCase):
    def test_committed_private_file_fails(self):
        if not _has_git():
            self.skipTest("git not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _make_repo(td)
            secret = td / ".env"
            secret.write_text("API_KEY=should-not-be-here\n")
            _git(["add", ".env"], td)
            _git(["commit", "-m", "oops", "-q"], td)

            rules = RuleSet(
                publish_audit=PublishAuditModel(ignore_globs=[".env*"]),
            )
            report = run_publish_audit(rules, repo_root=str(td))
            self.assertTrue(any(f.id == "publish.committed"
                                for f in report.findings))
            self.assertEqual(report.overall, Severity.FAIL)

    def test_committed_finding_presents_both_cases(self):
        """v0.7.1 LOW-7: the suggested_fix must present "file wrong" and "rule wrong"
        symmetrically — not blindly recommend `git rm --cached`."""
        if not _has_git():
            self.skipTest("git not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _make_repo(td)
            (td / ".env").write_text("API_KEY=x\n")
            _git(["add", ".env"], td)
            _git(["commit", "-m", "oops", "-q"], td)

            rules = RuleSet(
                publish_audit=PublishAuditModel(ignore_globs=[".env*"]),
            )
            report = run_publish_audit(rules, repo_root=str(td))
            committed = [f for f in report.findings
                         if f.id == "publish.committed"]
            self.assertEqual(len(committed), 1)
            f = committed[0]
            # Message body must signal "one of the two is wrong" to the user.
            self.assertIn("one of the two is wrong", f.message.lower())
            # Suggested fix must present BOTH cases — not just `git rm --cached`.
            fix = (f.suggested_fix or "").lower()
            self.assertIn("file is wrong", fix)
            self.assertIn("rule is wrong", fix)
            # The dangerous command must still appear (gated by case 1) but
            # the wrapper must not blindly recommend it.
            self.assertIn("git rm --cached", fix)
            self.assertIn("do not blindly", fix)

    def test_staged_private_file_warns(self):
        if not _has_git():
            self.skipTest("git not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _make_repo(td)
            secret = td / ".env"
            secret.write_text("API_KEY=stage-only\n")
            _git(["add", ".env"], td)

            rules = RuleSet(
                publish_audit=PublishAuditModel(ignore_globs=[".env*"]),
            )
            report = run_publish_audit(rules, repo_root=str(td))
            self.assertTrue(any(f.id == "publish.staged"
                                for f in report.findings))

    def test_untracked_private_file_is_pass(self):
        if not _has_git():
            self.skipTest("git not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _make_repo(td)
            (td / ".gitignore").write_text(".env*\n")
            (td / ".env").write_text("API_KEY=local-only\n")

            rules = RuleSet(
                publish_audit=PublishAuditModel(ignore_globs=[".env*"]),
            )
            report = run_publish_audit(rules, repo_root=str(td))
            # No fails, possibly an info-level finding for the untracked file
            self.assertTrue(report.overall in (Severity.PASS, Severity.WARN))
            # Specifically: no `publish.committed` or `publish.staged`
            for f in report.findings:
                self.assertNotEqual(f.id, "publish.committed")


class TestRedactPatternScan(unittest.TestCase):
    def test_api_key_in_committed_md_flagged(self):
        if not _has_git():
            self.skipTest("git not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _make_repo(td)
            doc = td / "README.md"
            doc.write_text(
                "Hello world.\n"
                "Token: sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"
            )
            _git(["add", "README.md"], td)
            _git(["commit", "-m", "doc", "-q"], td)

            rules = RuleSet(
                publish_audit=PublishAuditModel(
                    scan_globs=["README.md"],
                    redact_patterns={"api_key": r"sk-[A-Za-z0-9]{32,}"},
                ),
            )
            report = run_publish_audit(rules, repo_root=str(td))
            self.assertTrue(any(f.id == "publish.scan_api_key"
                                for f in report.findings))

    def test_match_value_never_appears_in_finding(self):
        if not _has_git():
            self.skipTest("git not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _make_repo(td)
            doc = td / "README.md"
            secret = "sk-DEADBEEFCAFEBABE0123456789ABCDEF0123456789"
            doc.write_text(f"Token: {secret}\n")
            _git(["add", "README.md"], td)
            _git(["commit", "-m", "doc", "-q"], td)

            rules = RuleSet(
                publish_audit=PublishAuditModel(
                    scan_globs=["README.md"],
                    redact_patterns={"api_key": r"sk-[A-Za-z0-9]{32,}"},
                ),
            )
            report = run_publish_audit(rules, repo_root=str(td))
            full = str([f.to_dict() for f in report.findings])
            self.assertNotIn(secret, full)
            self.assertNotIn("DEADBEEF", full)

    def test_email_allowlist_suppresses_finding(self):
        if not _has_git():
            self.skipTest("git not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _make_repo(td)
            doc = td / "README.md"
            doc.write_text(
                "Contact info@sunn3d.com for details.\n"
                "Random other: stranger@example.org\n"
            )
            _git(["add", "README.md"], td)
            _git(["commit", "-m", "doc", "-q"], td)

            rules = RuleSet(
                publish_audit=PublishAuditModel(
                    scan_globs=["README.md"],
                    redact_patterns={
                        "email": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
                    },
                    email_allowlist=["info@sunn3d.com"],
                ),
            )
            report = run_publish_audit(rules, repo_root=str(td))
            email_findings = [f for f in report.findings
                              if f.id == "publish.scan_email"]
            # Only the non-allowlisted email should fire
            self.assertEqual(len(email_findings), 1)


class TestEmptyConfig(unittest.TestCase):
    def test_no_globs_no_findings(self):
        if not _has_git():
            self.skipTest("git not on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            _make_repo(td)
            (td / "README.md").write_text("hi\n")
            _git(["add", "README.md"], td)
            _git(["commit", "-m", "init", "-q"], td)

            rules = RuleSet(publish_audit=PublishAuditModel())
            report = run_publish_audit(rules, repo_root=str(td))
            self.assertEqual(report.overall, Severity.PASS)


if __name__ == "__main__":
    unittest.main()
