"""
Publish-audit — privacy boundary scan before `git push`.

Three-state file model:
  untracked  (in working tree, not in git)        → info
  staged     (in index, not committed)            → warn
  committed  (in HEAD)                            → fail

Two passes:
  1. Glob match against `publish_audit.ignore_globs` — if a file is supposed
     to be private, fail/warn/info depending on its git state.
  2. Regex scan against `publish_audit.scan_globs` — if a public file
     contains an API key, AWS key, or other private pattern, emit a finding
     citing only path and line, never the matched value.

Email-allowlist runs as a pre-emit filter so info@sunn3d.com doesn't trip the
generic email regex.

This module never invokes `git check-ignore`; it uses three batched git
commands instead so it stays fast on large repos.

Usage:
    from cadclaw.publish_audit import run_publish_audit
    from cadclaw.rules import load_rules
    rules = load_rules("cadclaw.yaml")
    report = run_publish_audit(rules, repo_root=".")
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Set, Tuple

from .findings import ConfidenceBudget, Finding, Report, Severity
from .rules import RuleSet


_STATE_TO_SEVERITY = {
    "committed": Severity.FAIL,
    "staged": Severity.WARN,
    "untracked": Severity.PASS,  # info — listed but not flagged
}


def _git(args: List[str], repo: Path) -> List[str]:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if out.returncode != 0:
        return []
    return [line for line in out.stdout.splitlines() if line]


def _classify_files(repo: Path) -> Dict[str, str]:
    """Return {posix-path: state} where state is committed / staged / untracked."""
    state: Dict[str, str] = {}
    for path in _git(["ls-files"], repo):
        state[path] = "committed"
    for path in _git(["diff", "--cached", "--name-only"], repo):
        state[path] = "staged"
    for path in _git(["ls-files", "--others", "--exclude-standard"], repo):
        state[path] = "untracked"
    return state


def _matches_any_glob(path: str, globs: List[str]) -> bool:
    pp = PurePosixPath(path)
    for g in globs:
        if fnmatch.fnmatch(path, g):
            return True
        if pp.match(g):
            return True
    return False


def _email_allowed(value: str, allowlist: List[str]) -> bool:
    for entry in allowlist:
        if "*" in entry:
            if fnmatch.fnmatchcase(value, entry):
                return True
        elif value == entry:
            return True
    return False


def _scan_file_for_patterns(
    path: Path,
    patterns: Dict[str, re.Pattern],
    email_allowlist: List[str],
    rel: str,
) -> List[Finding]:
    out: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, regex in patterns.items():
            for match in regex.finditer(line):
                value = match.group(0)
                if kind == "email" and _email_allowed(value, email_allowlist):
                    continue
                out.append(Finding(
                    id=f"publish.scan_{kind}",
                    category="publish_audit",
                    severity=Severity.FAIL,
                    message=f"{rel}:{line_no}: matched {kind} pattern (value redacted).",
                    suggested_fix=(
                        f"Remove the matched {kind} from {rel} or add it to the "
                        "rule file's allowlist."
                    ),
                    evidence={"path": rel, "line": line_no, "kind": kind},
                ))
    return out


def run_publish_audit(rules: RuleSet, repo_root: str = ".") -> Report:
    """Walk the repo, classify files by git state, glob/regex scan."""
    t0 = time.time()
    findings: List[Finding] = []
    repo = Path(repo_root).resolve()

    state_map = _classify_files(repo)

    # Pass 1: ignore_globs — files that are supposed to be private
    ignore_globs = list(rules.publish_audit.ignore_globs)
    if ignore_globs:
        for path, state in state_map.items():
            if not _matches_any_glob(path, ignore_globs):
                continue
            severity = _STATE_TO_SEVERITY.get(state, Severity.PASS)
            if state == "committed":
                findings.append(Finding(
                    id="publish.committed",
                    category="publish_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"{path} is committed but matches "
                        "publish_audit.ignore_globs — one of the two is wrong."
                    ),
                    suggested_fix=(
                        "Pick the case that applies — do NOT blindly run "
                        "`git rm --cached`:\n"
                        "  (1) The FILE is wrong (sensitive content got "
                        "committed):\n"
                        f"      git rm --cached {path}\n"
                        "      then add a matching pattern to .gitignore so it "
                        "stays out.\n"
                        "  (2) The RULE is wrong (ignore_globs over-matches a "
                        "file that\n"
                        "      is intentionally public — e.g. `blog/**` "
                        "covering live\n"
                        "      GitHub Pages content): narrow the ignore_globs "
                        "pattern in\n"
                        "      cadclaw.yaml so this path no longer matches."
                    ),
                    evidence={"path": path, "state": state},
                ))
            elif state == "staged":
                findings.append(Finding(
                    id="publish.staged",
                    category="publish_audit",
                    severity=Severity.WARN,
                    message=(
                        f"{path} is staged but listed in publish_audit.ignore_globs."
                    ),
                    suggested_fix=f"git restore --staged {path}",
                    evidence={"path": path, "state": state},
                ))
            else:
                findings.append(Finding(
                    id="publish.untracked",
                    category="publish_audit",
                    severity=Severity.PASS,
                    message=f"{path} present locally but correctly ignored.",
                    evidence={"path": path, "state": state},
                ))

    # Pass 2: scan_globs — regex content scan with allowlist
    scan_globs = list(rules.publish_audit.scan_globs)
    if scan_globs:
        compiled: Dict[str, re.Pattern] = {}
        for kind, pattern in rules.publish_audit.redact_patterns.items():
            try:
                compiled[kind] = re.compile(pattern)
            except re.error as e:
                findings.append(Finding(
                    id="publish.bad_pattern",
                    category="publish_audit",
                    severity=Severity.WARN,
                    message=f"redact_pattern {kind!r} is not a valid regex: {e}",
                    evidence={"kind": kind, "pattern": pattern},
                ))

        if compiled:
            for path in state_map:
                if not _matches_any_glob(path, scan_globs):
                    continue
                full = repo / path
                if not full.exists() or not full.is_file():
                    continue
                findings.extend(_scan_file_for_patterns(
                    full, compiled,
                    rules.publish_audit.email_allowlist,
                    path,
                ))

    # Pass 3: large-blob warning
    threshold = rules.publish_audit.blob_size_warn_bytes
    if threshold > 0:
        for path, state in state_map.items():
            if state != "committed":
                continue
            full = repo / path
            try:
                size = full.stat().st_size
            except OSError:
                continue
            if size > threshold:
                findings.append(Finding(
                    id="publish.blob_large",
                    category="publish_audit",
                    severity=Severity.WARN,
                    message=(
                        f"{path} is {size:,} bytes (over {threshold:,} threshold)."
                    ),
                    suggested_fix=(
                        "Consider git-lfs, an out-of-tree download script, or a smaller "
                        "exported version."
                    ),
                    evidence={"path": path, "size_bytes": size},
                ))

    duration_ms = (time.time() - t0) * 1000
    rep = Report(
        findings=findings,
        duration_ms=duration_ms,
        meta={
            "category": "publish_audit",
            "repo": str(repo),
            "n_tracked": sum(1 for s in state_map.values() if s == "committed"),
            "n_staged": sum(1 for s in state_map.values() if s == "staged"),
            "n_untracked": sum(1 for s in state_map.values() if s == "untracked"),
        },
        confidence_budget=ConfidenceBudget(
            checked=[
                "ignore_globs vs git state (committed/staged/untracked)",
                "regex content scan over scan_globs with email allowlist",
                "tracked-file size threshold",
            ],
            not_checked=[
                "git history (only HEAD/index/working tree)",
                "binary file contents",
                "encrypted or encoded secrets",
                "secrets pushed to a remote that have since been redacted locally",
            ],
            assumptions=[
                "git is on PATH and the cwd is inside a working tree",
                "regex patterns reflect the secret formats in use",
                "ignore_globs covers every private filename class",
            ],
        ),
    )
    rep.overall = rep.compute_overall()
    return rep
