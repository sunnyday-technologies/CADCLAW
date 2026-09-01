"""Adversarial regressions for the repository pre-publication boundary.

All denied specimens are assembled at runtime.  This tracked source therefore
does not contain a complete denied value, path, ref, or message.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
GATE_SCRIPT = SCRIPTS / "prepublication_gate.py"
HOOK_SOURCE = SCRIPTS / "hooks" / "pre-push"
PUBLIC_POLICY = ROOT / "policy" / "prepublication.v1.json"
ZERO_OID = "0" * 40

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import create_public_pr as public_pr  # noqa: E402
import manage_prepublication_hooks as hook_manager  # noqa: E402
import prepublication_gate as gate  # noqa: E402


class FixtureGitError(RuntimeError):
    """A temporary-repository setup command failed."""


def _protected_content(suffix: str = "SYNTHETIC") -> str:
    return "_".join(("DO", "NOT", "PUBLISH", suffix))


def _protected_segment() -> str:
    return "".join(("in", "ternal"))


def _protected_ref(label: str = "topic") -> str:
    return "/".join(("refs", "heads", _protected_segment(), label))


def _local_overlay_marker() -> str:
    return "_".join(("LOCAL", "PROTECTED", "SYNTHETIC"))


def _git(
    repo: Path,
    *args: str,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input_bytes,
        stdin=None if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        raise FixtureGitError("temporary Git fixture setup failed")
    return result


@contextlib.contextmanager
def _temporary_repo():
    with tempfile.TemporaryDirectory() as temporary:
        repo = Path(temporary).resolve()
        _git(repo, "init", "-q")
        _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
        _git(repo, "config", "user.name", "Synthetic Test")
        _git(repo, "config", "user.email", "synthetic@example.invalid")
        _git(repo, "config", "core.autocrlf", "false")
        _git(repo, "config", "core.filemode", "true")
        _git(repo, "config", "gc.auto", "0")
        yield repo


def _write(repo: Path, relative: str, data: str | bytes) -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8", newline="\n")
    return path


def _commit(
    repo: Path,
    files: dict[str, str | bytes] | None = None,
    *,
    message: str = "synthetic change",
    remove: tuple[str, ...] = (),
) -> str:
    for relative, data in (files or {}).items():
        _write(repo, relative, data)
    for relative in remove:
        path = repo / relative
        if path.exists() or path.is_symlink():
            path.unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _head(repo)


def _head(repo: Path, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.decode("ascii").strip()


def _policy_document() -> dict[str, object]:
    return json.loads(PUBLIC_POLICY.read_text(encoding="utf-8"))


def _policy_copy(repo: Path, *, max_blob_bytes: int | None = None) -> Path:
    document = _policy_document()
    if max_blob_bytes is not None:
        document["max_blob_bytes"] = max_blob_bytes
    path = repo / "test-policy.json"
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return path


def _allow_literal(rule_id: str) -> str:
    document = _policy_document()
    for rule in document["allow"]:
        if rule["id"] == rule_id:
            return rule["pattern"]
    raise AssertionError("expected public allow rule is missing")


def _overlay_document() -> dict[str, object]:
    return {
        "schema": "cadclaw-prepublication-overlay.v1",
        "policy_version": 1,
        "deny": [
            {
                "id": "LOCAL-TEST-001",
                "surfaces": sorted(gate.SURFACES),
                "kind": "literal",
                "pattern": _local_overlay_marker(),
            }
        ],
        "allow": [],
    }


def _write_overlay(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_overlay_document()), encoding="utf-8", newline="\n")
    return path


def _result(returncode: int, stdout: str, stderr: str) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _call_main(function, arguments: list[str]) -> SimpleNamespace:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = function(arguments)
    return _result(code, stdout.getvalue(), stderr.getvalue())


class GateTestCase(unittest.TestCase):
    def assertRedacted(self, result, *values: object) -> None:  # noqa: N802
        rendered = result.stdout + result.stderr
        candidates: list[str] = []
        for value in values:
            if value is None:
                continue
            text = str(value)
            candidates.extend((text, text.replace("\\", "/")))
        if any(candidate and candidate in rendered for candidate in candidates):
            self.fail("diagnostic output disclosed a protected synthetic fixture")

    def assertResult(
        self,
        result,
        expected_code: int,
        *safe_fragments: str,
    ) -> None:  # noqa: N802
        if result.returncode != expected_code:
            self.fail(
                f"unexpected gate exit status: expected {expected_code}, "
                f"received {result.returncode}"
            )
        rendered = result.stdout + result.stderr
        for fragment in safe_fragments:
            if fragment not in rendered:
                self.fail(f"expected value-free diagnostic fragment is missing: {fragment}")

    def run_gate(
        self,
        repo: Path,
        updates: list[tuple[str, str, str, str]],
        *,
        policy: Path = PUBLIC_POLICY,
    ) -> SimpleNamespace:
        updates_path = repo / "push-updates.txt"
        updates_path.write_bytes(
            b"".join(
                f"{local_ref} {local_oid} {remote_ref} {remote_oid}\n".encode("utf-8")
                for local_ref, local_oid, remote_ref, remote_oid in updates
            )
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(GATE_SCRIPT),
                "--policy",
                str(policy),
                "--repo",
                str(repo),
                "--public-only",
                "pre-push",
                "--updates-file",
                str(updates_path),
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return _result(completed.returncode, completed.stdout, completed.stderr)

    def validate_policy(self, repo: Path, policy: Path) -> SimpleNamespace:
        completed = subprocess.run(
            [
                sys.executable,
                str(GATE_SCRIPT),
                "--policy",
                str(policy),
                "--repo",
                str(repo),
                "--public-only",
                "validate",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return _result(completed.returncode, completed.stdout, completed.stderr)

    def run_index(self, repo: Path, *, policy: Path = PUBLIC_POLICY) -> SimpleNamespace:
        completed = subprocess.run(
            [
                sys.executable,
                str(GATE_SCRIPT),
                "--policy",
                str(policy),
                "--repo",
                str(repo),
                "--public-only",
                "index",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return _result(completed.returncode, completed.stdout, completed.stderr)


class TestPushUpdates(GateTestCase):
    def test_new_ref_scans_objects_and_redacts_inputs(self):
        with _temporary_repo() as repo:
            marker = _protected_content("NEW")
            relative = "notes/new.txt"
            head = _commit(repo, {relative: marker})
            remote_ref = "refs/heads/topic-new"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, ZERO_OID)],
            )
            self.assertRedacted(result, marker, relative, remote_ref, head)
            self.assertResult(result, 1, "surface=blob", "pattern=PUBLIC-CONTENT-001")

    def test_update_ref_scans_only_new_history(self):
        with _temporary_repo() as repo:
            base = _commit(repo, {"base.txt": "public"})
            marker = _protected_content("UPDATE")
            relative = "notes/update.txt"
            head = _commit(repo, {relative: marker})
            remote_ref = "refs/heads/topic-update"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, base)],
            )
            self.assertRedacted(result, marker, relative, remote_ref, base, head)
            self.assertResult(result, 1, "surface=blob", "pattern=PUBLIC-CONTENT-001")

    def test_delete_ref_transmits_nothing_and_is_not_blocked(self):
        with _temporary_repo() as repo:
            existing = _commit(repo, {"base.txt": "public"})
            remote_ref = _protected_ref("obsolete")
            result = self.run_gate(
                repo,
                [("(delete)", ZERO_OID, remote_ref, existing)],
            )
            self.assertRedacted(result, remote_ref, existing)
            self.assertResult(result, 0, "status=clean")

    def test_multiple_ref_batch_blocks_if_any_update_is_blocked(self):
        with _temporary_repo() as repo:
            clean = _commit(repo, {"clean.txt": "public"})
            marker = _protected_content("MULTI")
            relative = "notes/multi.txt"
            blocked = _commit(repo, {relative: marker})
            clean_ref = "refs/heads/clean-topic"
            blocked_ref = "refs/heads/blocked-topic"
            result = self.run_gate(
                repo,
                [
                    ("refs/heads/main", clean, clean_ref, ZERO_OID),
                    ("refs/heads/main", blocked, blocked_ref, clean),
                ],
            )
            self.assertRedacted(
                result,
                marker,
                relative,
                clean_ref,
                blocked_ref,
                clean,
                blocked,
            )
            self.assertResult(result, 1, "pattern=PUBLIC-CONTENT-001")

    def test_new_ref_does_not_trust_stale_remote_tracking_refs(self):
        with _temporary_repo() as repo:
            _commit(repo, {"base.txt": "public"})
            marker = _protected_content("STALE")
            relative = "notes/stale-tracking.txt"
            head = _commit(repo, {relative: marker})
            _git(repo, "update-ref", "refs/remotes/origin/stale", head)
            remote_ref = "refs/heads/new-topic"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, ZERO_OID)],
            )
            self.assertRedacted(result, marker, relative, remote_ref, head)
            self.assertResult(result, 1, "surface=blob", "pattern=PUBLIC-CONTENT-001")


class TestHistoryAndIndexBoundaries(GateTestCase):
    def test_index_scan_reads_staged_blob_not_worktree_replacement(self):
        with _temporary_repo() as repo:
            _commit(repo, {"candidate.txt": "public base"})
            marker = _protected_content("STAGED")
            _write(repo, "candidate.txt", marker)
            _git(repo, "add", "candidate.txt")
            _write(repo, "candidate.txt", "public worktree replacement")

            result = self.run_index(repo)
            self.assertRedacted(result, marker, "candidate.txt")
            self.assertResult(result, 1, "surface=blob", "pattern=PUBLIC-CONTENT-001")

    def test_merge_second_parent_is_scanned(self):
        with _temporary_repo() as repo:
            base = _commit(repo, {"base.txt": "public"})
            _git(repo, "switch", "-q", "-c", "side")
            marker = _protected_content("MERGE")
            relative = "side-only.txt"
            _commit(repo, {relative: marker})
            _git(repo, "switch", "-q", "main")
            _commit(repo, {"main-only.txt": "public"})
            _git(repo, "merge", "-q", "--no-ff", "side", "-m", "synthetic merge")
            head = _head(repo)
            remote_ref = "refs/heads/merge-topic"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, base)],
            )
            self.assertRedacted(result, marker, relative, remote_ref, base, head)
            self.assertResult(result, 1, "pattern=PUBLIC-CONTENT-001")

    def test_add_then_remove_stays_blocked_by_history(self):
        with _temporary_repo() as repo:
            base = _commit(repo, {"base.txt": "public"})
            marker = _protected_content("TRANSIENT")
            relative = "transient.txt"
            _commit(repo, {relative: marker})
            head = _commit(repo, remove=(relative,))
            remote_ref = "refs/heads/transient-topic"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, base)],
            )
            self.assertRedacted(result, marker, relative, remote_ref, base, head)
            self.assertResult(result, 1, "pattern=PUBLIC-CONTENT-001")

    def test_staged_and_worktree_state_cannot_replace_outgoing_objects(self):
        with _temporary_repo() as repo:
            base = _commit(repo, {"tracked.txt": "public"})
            marker = _protected_content("INDEX")
            relative = "staged-only.txt"
            _write(repo, relative, marker)
            _git(repo, "add", relative)
            _write(repo, relative, "public working tree replacement")

            clean_result = self.run_gate(
                repo,
                [("refs/heads/main", base, "refs/heads/clean-index", ZERO_OID)],
            )
            self.assertRedacted(clean_result, marker, relative, base)
            self.assertResult(clean_result, 0, "status=clean")

            _git(repo, "checkout-index", "--force", "--", relative)
            _git(repo, "commit", "-q", "-m", "synthetic staged commit")
            blocked = _head(repo)
            _write(repo, relative, "public uncommitted replacement")
            blocked_result = self.run_gate(
                repo,
                [("refs/heads/main", blocked, "refs/heads/blocked-index", base)],
            )
            self.assertRedacted(blocked_result, marker, relative, base, blocked)
            self.assertResult(blocked_result, 1, "pattern=PUBLIC-CONTENT-001")

    def test_newline_filename_is_parsed_without_line_splitting(self):
        with _temporary_repo() as repo:
            segment = _protected_segment()
            relative = "line\nsegment/" + segment + "/item.txt"
            blob = _git(
                repo,
                "hash-object",
                "-w",
                "--stdin",
                input_bytes=b"public",
            ).stdout.decode("ascii").strip()
            leaf_tree = _git(
                repo,
                "mktree",
                "-z",
                input_bytes=f"100644 blob {blob}\titem.txt\0".encode("ascii"),
            ).stdout.decode("ascii").strip()
            protected_tree = _git(
                repo,
                "mktree",
                "-z",
                input_bytes=(
                    f"040000 tree {leaf_tree}\t".encode("ascii")
                    + segment.encode("ascii")
                    + b"\0"
                ),
            ).stdout.decode("ascii").strip()
            root_tree = _git(
                repo,
                "mktree",
                "-z",
                input_bytes=(
                    f"040000 tree {protected_tree}\tline\nsegment\0".encode("ascii")
                ),
            ).stdout.decode("ascii").strip()
            head = _git(
                repo,
                "commit-tree",
                root_tree,
                "-m",
                "synthetic newline tree",
            ).stdout.decode("ascii").strip()
            remote_ref = "refs/heads/newline-topic"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, ZERO_OID)],
            )
            self.assertRedacted(result, relative, segment, remote_ref, head)
            self.assertResult(result, 1, "surface=filename", "pattern=PUBLIC-PATH-001")


class TestBlobFailureModes(GateTestCase):
    def test_invalid_utf8_binary_blob_is_still_scanned(self):
        with _temporary_repo() as repo:
            marker = _protected_content("BINARY")
            relative = "binary.dat"
            payload = b"\x00\xff" + marker.encode("ascii") + b"\xfe\x00"
            head = _commit(repo, {relative: payload})
            remote_ref = "refs/heads/binary-topic"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, ZERO_OID)],
            )
            self.assertRedacted(result, marker, relative, remote_ref, head)
            self.assertResult(result, 1, "surface=blob", "pattern=PUBLIC-CONTENT-001")

    def test_utf16_and_utf32_blobs_are_scanned(self):
        for encoding in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
            with self.subTest(encoding=encoding), _temporary_repo() as repo:
                marker = _protected_content("ENCODED")
                relative = f"encoded-{encoding}.txt"
                head = _commit(repo, {relative: marker.encode(encoding)})
                result = self.run_gate(
                    repo,
                    [("refs/heads/main", head, "refs/heads/encoded", ZERO_OID)],
                )
                self.assertRedacted(result, marker, relative, head)
                self.assertResult(result, 1, "surface=blob", "pattern=PUBLIC-CONTENT-001")

    def test_private_literal_is_scanned_in_utf16_and_utf32_views(self):
        with _temporary_repo() as repo:
            policy_path = _policy_copy(repo)
            overlay_path = _write_overlay(repo / ".prepublication-policy.local.json")
            policy = gate.load_policy(policy_path, overlay_path, require_overlay=True)
            marker = _local_overlay_marker()
            for encoding in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
                with self.subTest(encoding=encoding):
                    scanner = gate.GateScanner(policy, repo)
                    scanner.scan_bytes("blob", marker.encode(encoding))
                    self.assertTrue(
                        any(item.pattern_id == "LOCAL-TEST-001" for item in scanner.reporter.findings)
                    )

    def test_oversized_blob_fails_closed_without_reading_or_echoing_it(self):
        with _temporary_repo() as repo:
            policy = _policy_copy(repo, max_blob_bytes=1024)
            relative = "oversized.bin"
            head = _commit(repo, {relative: b"Z" * 1025})
            remote_ref = "refs/heads/oversized-topic"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, ZERO_OID)],
                policy=policy,
            )
            self.assertRedacted(result, relative, remote_ref, head, policy)
            self.assertResult(result, 1, "pattern=SYSTEM-BLOB-OVERSIZE")

    def test_missing_loose_object_fails_closed_and_redacts_object_identity(self):
        with _temporary_repo() as repo:
            base = _commit(repo, {"base.txt": "public"})
            relative = "missing-object.txt"
            head = _commit(repo, {relative: "public object"})
            blob_oid = _head(repo, f"HEAD:{relative}")
            object_path = repo / ".git" / "objects" / blob_oid[:2] / blob_oid[2:]
            if not object_path.is_file():
                self.skipTest("Git stored the synthetic blob outside the loose object store")
            try:
                os.chmod(object_path, 0o600)
                object_path.unlink()
            except OSError:
                self.skipTest("platform does not permit removing a loose synthetic object")
            remote_ref = "refs/heads/missing-object-topic"
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, remote_ref, base)],
            )
            self.assertRedacted(
                result,
                relative,
                remote_ref,
                base,
                head,
                blob_oid,
                object_path,
            )
            self.assertResult(result, 2, "pattern=SYSTEM-GIT-READ")


class TestPolicyAndAllowRules(GateTestCase):
    def test_malformed_policy_variants_fail_closed_without_echoing_input(self):
        with _temporary_repo() as repo:
            malformed_documents: list[bytes] = [b"{"]
            extra = _policy_document()
            extra["unexpected"] = True
            malformed_documents.append(json.dumps(extra).encode("utf-8"))
            duplicate = _policy_document()
            duplicate["deny"] = list(duplicate["deny"]) + [dict(duplicate["deny"][0])]
            malformed_documents.append(json.dumps(duplicate).encode("utf-8"))

            protected_dir = repo / _protected_segment()
            protected_dir.mkdir()
            for ordinal, raw in enumerate(malformed_documents, start=1):
                with self.subTest(variant=ordinal):
                    policy = protected_dir / f"malformed-{ordinal}.json"
                    policy.write_bytes(raw)
                    result = self.validate_policy(repo, policy)
                    self.assertRedacted(result, raw.decode("utf-8", errors="ignore"), policy)
                    self.assertResult(result, 2, "pattern=SYSTEM-POLICY-INVALID")

    def test_explicit_public_allow_values_remain_publishable(self):
        with _temporary_repo() as repo:
            allowed_content = _allow_literal("PUBLIC-ALLOW-002")
            allowed_filename = _allow_literal("PUBLIC-ALLOW-001")
            head = _commit(repo, {allowed_filename: allowed_content})
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, "refs/heads/public-example", ZERO_OID)],
            )
            self.assertResult(result, 0, "status=clean")

    def test_missing_required_public_rule_fails_closed(self):
        with _temporary_repo() as repo:
            document = _policy_document()
            removed = document["deny"].pop()
            policy = repo / "missing-required-rule.json"
            policy.write_text(json.dumps(document), encoding="utf-8", newline="\n")
            result = self.validate_policy(repo, policy)
            self.assertRedacted(result, removed["id"], policy)
            self.assertResult(result, 2, "pattern=SYSTEM-POLICY-INVALID")

    def test_required_public_rule_behavior_is_canonical(self):
        with _temporary_repo() as repo:
            variants: list[dict[str, object]] = []

            narrowed = _policy_document()
            narrowed["deny"][0]["surfaces"] = ["pr_title"]
            variants.append(narrowed)

            weakened = _policy_document()
            weakened["deny"][0]["pattern"] = "SYNTHETIC_NONMATCHING_RULE"
            variants.append(weakened)

            broad_exception = _policy_document()
            broad_exception["allow"].append({
                "id": "PUBLIC-ALLOW-EXTRA",
                "surfaces": ["blob"],
                "suppresses": ["PUBLIC-CONTENT-001"],
                "kind": "literal",
                "pattern": "public",
            })
            variants.append(broad_exception)

            for ordinal, document in enumerate(variants, start=1):
                with self.subTest(variant=ordinal):
                    policy = repo / f"weakened-required-rule-{ordinal}.json"
                    policy.write_text(json.dumps(document), encoding="utf-8", newline="\n")
                    result = self.validate_policy(repo, policy)
                    self.assertRedacted(result, policy)
                    self.assertResult(result, 2, "pattern=SYSTEM-POLICY-INVALID")


class TestWorkflowSurfaces(GateTestCase):
    def test_workflow_filename_content_and_metadata_are_independent_surfaces(self):
        marker = _protected_content("WORKFLOW")
        segment = _protected_segment()

        with self.subTest(surface="filename"), _temporary_repo() as repo:
            relative = f".github/workflows/{segment}/job.yml"
            head = _commit(repo, {relative: "name: public\n"})
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, "refs/heads/workflow-name", ZERO_OID)],
            )
            self.assertRedacted(result, relative, segment, head)
            self.assertResult(result, 1, "surface=workflow_filename", "pattern=PUBLIC-PATH-001")

        with self.subTest(surface="content"), _temporary_repo() as repo:
            relative = ".github/workflows/content.yml"
            head = _commit(repo, {relative: "name: " + marker + "\n"})
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, "refs/heads/workflow-content", ZERO_OID)],
            )
            self.assertRedacted(result, marker, relative, head)
            self.assertResult(result, 1, "surface=workflow_content", "pattern=PUBLIC-CONTENT-001")

        with self.subTest(surface="metadata"), _temporary_repo() as repo:
            relative = ".github/workflows/link.yml"
            blob_oid = _git(
                repo,
                "hash-object",
                "-w",
                "--stdin",
                input_bytes=b"safe-target",
            ).stdout.decode("ascii").strip()
            _git(
                repo,
                "update-index",
                "--add",
                "--cacheinfo",
                f"120000,{blob_oid},{relative}",
            )
            _git(repo, "commit", "-q", "-m", "synthetic workflow metadata")
            head = _head(repo)
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, "refs/heads/workflow-metadata", ZERO_OID)],
            )
            self.assertRedacted(result, relative, blob_oid, head)
            self.assertResult(
                result,
                1,
                "surface=workflow_metadata",
                "pattern=SYSTEM-WORKFLOW-METADATA",
            )


class TestMessagesAndCiMetadata(GateTestCase):
    def test_commit_and_tag_messages_are_scanned_and_redacted(self):
        with self.subTest(surface="commit_message"), _temporary_repo() as repo:
            message = _protected_content("COMMIT")
            head = _commit(repo, {"safe.txt": "public"}, message=message)
            result = self.run_gate(
                repo,
                [("refs/heads/main", head, "refs/heads/message", ZERO_OID)],
            )
            self.assertRedacted(result, message, head)
            self.assertResult(result, 1, "surface=commit_message", "pattern=PUBLIC-CONTENT-001")

        with self.subTest(surface="tag_message"), _temporary_repo() as repo:
            commit = _commit(repo, {"safe.txt": "public"})
            message = _protected_content("TAG")
            _git(repo, "tag", "-a", "synthetic-release", "-m", message)
            tag_oid = _head(repo, "refs/tags/synthetic-release")
            result = self.run_gate(
                repo,
                [
                    (
                        "refs/tags/synthetic-release",
                        tag_oid,
                        "refs/tags/synthetic-release",
                        ZERO_OID,
                    )
                ],
            )
            self.assertRedacted(result, message, commit, tag_oid)
            self.assertResult(result, 1, "surface=tag_message", "pattern=PUBLIC-CONTENT-001")

    def test_nested_annotated_tag_messages_are_all_scanned(self):
        with _temporary_repo() as repo:
            commit = _commit(repo, {"safe.txt": "public"})
            message = _protected_content("INNER-TAG")
            _git(repo, "tag", "-a", "inner-release", "-m", message)
            _git(repo, "tag", "-a", "outer-release", "inner-release", "-m", "public outer tag")
            outer_oid = _head(repo, "refs/tags/outer-release")
            result = self.run_gate(
                repo,
                [
                    (
                        "refs/tags/outer-release",
                        outer_oid,
                        "refs/tags/outer-release",
                        ZERO_OID,
                    )
                ],
            )
            self.assertRedacted(result, message, commit, outer_oid)
            self.assertResult(result, 1, "surface=tag_message", "pattern=PUBLIC-CONTENT-001")

    def test_pull_request_event_scans_title_body_and_refs_without_echoing_them(self):
        with _temporary_repo() as repo:
            base = _commit(repo, {"base.txt": "public"})
            head = _commit(repo, {"head.txt": "public"})
            title = _protected_content("TITLE")
            body = _protected_content("BODY")
            head_ref = "/".join((_protected_segment(), "pull-head"))
            event = {
                "pull_request": {
                    "title": title,
                    "body": body,
                    "base": {"ref": "main", "sha": base},
                    "head": {"ref": head_ref, "sha": head},
                }
            }
            event_path = repo / "event.json"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--policy",
                    str(PUBLIC_POLICY),
                    "--repo",
                    str(repo),
                    "--public-only",
                    "ci-event",
                    "--event-path",
                    str(event_path),
                    "--event-name",
                    "pull_request",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            result = _result(completed.returncode, completed.stdout, completed.stderr)
            self.assertRedacted(
                result,
                title,
                body,
                head_ref,
                base,
                head,
                event_path,
            )
            self.assertResult(
                result,
                1,
                "surface=pr_title",
                "surface=pr_body",
                "surface=ref",
            )


class TestHookBootstrap(GateTestCase):
    def _prepare_bootstrap_repo(self, repo: Path) -> tuple[Path, Path, Path]:
        policy = repo / "policy" / "prepublication.v1.json"
        policy.parent.mkdir(parents=True)
        shutil.copyfile(PUBLIC_POLICY, policy)
        hook = repo / "scripts" / "hooks" / "pre-push"
        hook.parent.mkdir(parents=True)
        shutil.copyfile(HOOK_SOURCE, hook)
        _write(repo, ".gitignore", ".prepublication-policy.local.json\n")
        _git(repo, "add", "policy/prepublication.v1.json", "scripts/hooks/pre-push", ".gitignore")
        _git(repo, "update-index", "--chmod=+x", "scripts/hooks/pre-push")
        _git(repo, "commit", "-q", "-m", "synthetic bootstrap fixture")
        overlay_source = _write_overlay(repo / "overlay-source.json")
        local_overlay = repo / ".prepublication-policy.local.json"
        return policy, overlay_source, local_overlay

    @contextlib.contextmanager
    def _patched_manager(self, repo: Path, policy: Path, local_overlay: Path):
        hook = repo / "scripts" / "hooks" / "pre-push"
        with (
            mock.patch.object(hook_manager, "ROOT", repo),
            mock.patch.object(hook_manager, "HOOK", hook),
            mock.patch.object(hook_manager, "LOCAL_OVERLAY", local_overlay),
            mock.patch.object(hook_manager.gate, "DEFAULT_POLICY", policy),
        ):
            yield

    def test_install_then_verify_configures_exact_tracked_hook(self):
        with _temporary_repo() as repo:
            policy, overlay_source, local_overlay = self._prepare_bootstrap_repo(repo)
            marker = _local_overlay_marker()
            with self._patched_manager(repo, policy, local_overlay):
                installed = _call_main(
                    hook_manager.main,
                    ["install", "--overlay-source", str(overlay_source)],
                )
                verified = _call_main(hook_manager.main, ["verify"])
            self.assertRedacted(installed, marker, overlay_source, local_overlay)
            self.assertRedacted(verified, marker, overlay_source, local_overlay)
            self.assertResult(installed, 0, "status=clean")
            self.assertResult(verified, 0, "status=clean")
            self.assertEqual(
                _git(repo, "config", "--local", "--get", "core.hooksPath").stdout.strip(),
                b"scripts/hooks",
            )
            self.assertTrue(local_overlay.is_file())

    def test_conflicting_hook_path_fails_without_echoing_config_or_overlay(self):
        with _temporary_repo() as repo:
            policy, overlay_source, local_overlay = self._prepare_bootstrap_repo(repo)
            conflicting = _protected_segment() + "/hooks"
            _git(repo, "config", "--local", "core.hooksPath", conflicting)
            with self._patched_manager(repo, policy, local_overlay):
                result = _call_main(
                    hook_manager.main,
                    ["install", "--overlay-source", str(overlay_source)],
                )
            self.assertRedacted(
                result,
                conflicting,
                _local_overlay_marker(),
                overlay_source,
                local_overlay,
            )
            self.assertResult(result, 2, "pattern=SYSTEM-HOOKS-PATH-CONFLICT")

    def test_verify_rejects_a_different_existing_executable_path(self):
        with _temporary_repo() as repo:
            policy, overlay_source, local_overlay = self._prepare_bootstrap_repo(repo)
            with self._patched_manager(repo, policy, local_overlay):
                installed = _call_main(
                    hook_manager.main,
                    ["install", "--overlay-source", str(overlay_source)],
                )
                _git(
                    repo,
                    "config",
                    "--local",
                    "prepublication.python",
                    str(repo / "scripts" / "hooks" / "pre-push"),
                )
                verified = _call_main(hook_manager.main, ["verify"])
            self.assertResult(installed, 0, "status=clean")
            self.assertRedacted(verified, overlay_source, local_overlay)
            self.assertResult(verified, 2, "pattern=SYSTEM-PYTHON-CONFIG")

    def test_hook_never_forwards_remote_name_or_url_to_scanners(self):
        raw = HOOK_SOURCE.read_bytes()
        self.assertNotIn(b"--remote", raw)
        self.assertNotIn(b"--remotes=", raw)

    def test_direct_repository_path_push_runs_both_prepublication_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            repo = root / "source"
            remote = root / "destination.git"
            repo.mkdir()
            _git(repo, "init", "-q")
            _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
            _git(repo, "config", "user.name", "Synthetic Test")
            _git(repo, "config", "user.email", "synthetic@example.invalid")
            _git(repo, "config", "core.autocrlf", "false")
            _git(repo, "config", "core.hooksPath", "scripts/hooks")
            _git(
                repo,
                "config",
                "prepublication.python",
                Path(sys.executable).resolve().as_posix(),
            )

            (repo / "policy").mkdir()
            (repo / "scripts" / "hooks").mkdir(parents=True)
            shutil.copyfile(PUBLIC_POLICY, repo / "policy" / "prepublication.v1.json")
            shutil.copyfile(GATE_SCRIPT, repo / "scripts" / "prepublication_gate.py")
            shutil.copyfile(
                SCRIPTS / "check_no_answer_keys.py",
                repo / "scripts" / "check_no_answer_keys.py",
            )
            shutil.copyfile(HOOK_SOURCE, repo / "scripts" / "hooks" / "pre-push")
            _write_overlay(repo / ".prepublication-policy.local.json")
            _write(repo, ".gitignore", ".prepublication-policy.local.json\n")
            _write(repo, "public.txt", "public content")
            _git(repo, "add", ".gitignore", "policy", "scripts", "public.txt")
            _git(repo, "update-index", "--chmod=+x", "scripts/hooks/pre-push")
            _git(repo, "commit", "-q", "-m", "synthetic direct path control")
            remote.mkdir()
            _git(remote, "init", "-q", "--bare")

            pushed = _git(
                repo,
                "push",
                remote.as_posix(),
                "HEAD:refs/heads/main",
                check=False,
            )
            self.assertEqual(
                pushed.returncode,
                0,
                pushed.stderr.decode("utf-8", errors="replace"),
            )
            self.assertEqual(
                _head(remote, "refs/heads/main"),
                _head(repo),
            )

            updated = _commit(repo, {"next.txt": "public update"})
            pushed_update = _git(
                repo,
                "push",
                remote.as_posix(),
                "HEAD:refs/heads/main",
                check=False,
            )
            self.assertEqual(
                pushed_update.returncode,
                0,
                pushed_update.stderr.decode("utf-8", errors="replace"),
            )
            self.assertEqual(_head(remote, "refs/heads/main"), updated)


class TestPublicPrWrapper(GateTestCase):
    @contextlib.contextmanager
    def _patched_wrapper(self, repo: Path):
        policy = _policy_copy(repo)
        overlay = _write_overlay(repo / ".prepublication-policy.local.json")
        original_load_policy = gate.load_policy

        def load_test_policy(*_args, **_kwargs):
            return original_load_policy(policy, overlay, require_overlay=True)

        invoke = mock.Mock(return_value="https://github.com/example/example/pull/1")
        with (
            mock.patch.object(public_pr, "ROOT", repo),
            mock.patch.object(public_pr.gate, "load_policy", side_effect=load_test_policy),
            mock.patch.object(public_pr, "_invoke_github", invoke),
        ):
            yield invoke, policy, overlay

    def test_allowlisted_title_and_body_reach_github_without_mutation(self):
        with _temporary_repo() as repo:
            _commit(repo, {"base.txt": "public"})
            allowed = _allow_literal("PUBLIC-ALLOW-002")
            with self._patched_wrapper(repo) as (invoke, _policy, _overlay):
                result = _call_main(
                    public_pr.main,
                    ["--title", allowed, "--body", allowed],
                )
            self.assertResult(result, 0, "/pull/1")
            invoke.assert_called_once()
            self.assertEqual(invoke.call_args.args[1], allowed)

    def test_title_body_ref_and_body_path_are_blocked_without_echo(self):
        with _temporary_repo() as repo:
            _commit(repo, {"base.txt": "public"})
            cases = [
                (
                    "title",
                    ["--title", _protected_content("PRTITLE"), "--body", "public"],
                    _protected_content("PRTITLE"),
                    "surface=pr_title",
                ),
                (
                    "body",
                    ["--title", "public", "--body", _protected_content("PRBODY")],
                    _protected_content("PRBODY"),
                    "surface=pr_body",
                ),
                (
                    "ref",
                    [
                        "--title",
                        "public",
                        "--body",
                        "public",
                        "--head",
                        _protected_ref("pr-head"),
                    ],
                    _protected_ref("pr-head"),
                    "surface=ref",
                ),
            ]
            for label, arguments, protected, expected_surface in cases:
                with self.subTest(case=label), self._patched_wrapper(repo) as (
                    invoke,
                    _policy,
                    _overlay,
                ):
                    result = _call_main(public_pr.main, arguments)
                    self.assertRedacted(result, protected)
                    self.assertResult(result, 1, expected_surface)
                    invoke.assert_not_called()

            missing = repo / _protected_segment() / "missing-body.txt"
            with self.subTest(case="body_path"), self._patched_wrapper(repo) as (
                invoke,
                _policy,
                _overlay,
            ):
                result = _call_main(
                    public_pr.main,
                    ["--title", "public", "--body-file", str(missing)],
                )
                self.assertRedacted(result, missing, _protected_segment())
                self.assertResult(result, 2, "pattern=SYSTEM-PR-BODY-UNREADABLE")
                invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
