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


class GitClassificationError(RuntimeError):
    """A fixed git classification lane could not be evaluated."""

    def __init__(self, lane: str):
        self.lane = lane
        super().__init__("git file classification could not be completed")


def _git(args: List[str], repo: Path) -> List[str]:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, UnicodeError, subprocess.SubprocessError):
        raise GitClassificationError("unknown") from None
    if out.returncode != 0:
        raise GitClassificationError("unknown") from None
    return [line for line in out.stdout.splitlines() if line]


def _classify_files(repo: Path) -> tuple[Dict[str, str], List[str]]:
    """Return classified paths plus every failed fixed git lane."""
    state: Dict[str, str] = {}
    failed_lanes: List[str] = []
    lanes = (
        ("tracked", "committed", ["ls-files"]),
        ("staged", "staged", ["diff", "--cached", "--name-only"]),
        (
            "untracked",
            "untracked",
            ["ls-files", "--others", "--exclude-standard"],
        ),
    )
    for lane, state_name, args in lanes:
        try:
            paths = _git(args, repo)
        except GitClassificationError:
            failed_lanes.append(lane)
            continue
        for path in paths:
            state[path] = state_name
    return state, failed_lanes


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
    patterns: List[Tuple[int, bool, re.Pattern]],
    email_allowlist: List[str],
    rel: str,
) -> tuple[List[Finding], bool]:
    out: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out, False
    for line_no, line in enumerate(text.splitlines(), start=1):
        for ordinal, uses_email_allowlist, regex in patterns:
            for match in regex.finditer(line):
                value = match.group(0)
                if uses_email_allowlist and _email_allowed(
                    value,
                    email_allowlist,
                ):
                    continue
                out.append(Finding(
                    id="publish.scan_match",
                    category="publish_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"{rel}:{line_no}: matched configured redact pattern "
                        f"{ordinal} (value redacted)."
                    ),
                    suggested_fix=(
                        f"Remove the matched value from {rel} or add it to the "
                        "applicable rule-file allowlist."
                    ),
                    evidence={
                        "path": rel,
                        "line": line_no,
                        "kind": "redact_pattern",
                        "pattern_ordinal": ordinal,
                    },
                ))
    return out, True


def run_publish_audit(rules: RuleSet, repo_root: str = ".") -> Report:
    """Walk the repo, classify files by git state, glob/regex scan."""
    t0 = time.time()
    findings: List[Finding] = []
    repo = Path(repo_root).resolve()

    state_map, git_error_lanes = _classify_files(repo)
    n_content_scan_files = 0
    n_content_scan_errors = 0
    n_blob_stat_errors = 0

    for lane in git_error_lanes:
        findings.append(Finding(
            id="publish.git_classification_error",
            category="publish_audit",
            severity=Severity.FAIL,
            message="a repository file-classification lane could not complete",
            evidence={"lane": lane, "status": "error"},
        ))

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
        compiled: List[Tuple[int, bool, re.Pattern]] = []
        for ordinal, (kind, pattern) in enumerate(
            rules.publish_audit.redact_patterns.items(),
            start=1,
        ):
            try:
                compiled.append((ordinal, kind == "email", re.compile(pattern)))
            except re.error as exc:
                evidence = {
                    "pattern_ordinal": ordinal,
                    "status": "error",
                }
                position = getattr(exc, "pos", None)
                if isinstance(position, int) and position >= 0:
                    evidence["position"] = position
                findings.append(Finding(
                    id="publish.bad_pattern",
                    category="publish_audit",
                    severity=Severity.WARN,
                    message="a configured redact pattern is invalid",
                    evidence=evidence,
                ))

        if compiled:
            for file_ordinal, path in enumerate(state_map, start=1):
                if not _matches_any_glob(path, scan_globs):
                    continue
                full = repo / path
                if not full.exists() or not full.is_file():
                    continue
                scan_findings, scan_ok = _scan_file_for_patterns(
                    full, compiled,
                    rules.publish_audit.email_allowlist,
                    path,
                )
                findings.extend(scan_findings)
                if scan_ok:
                    n_content_scan_files += 1
                else:
                    n_content_scan_errors += 1
                    findings.append(Finding(
                        id="publish.scan_error",
                        category="publish_audit",
                        severity=Severity.FAIL,
                        message="configured content could not be read",
                        evidence={
                            "file_ordinal": file_ordinal,
                            "status": "error",
                        },
                    ))

    # Pass 3: large-blob warning
    threshold = rules.publish_audit.blob_size_warn_bytes
    if threshold > 0:
        for file_ordinal, (path, state) in enumerate(
            state_map.items(),
            start=1,
        ):
            if state != "committed":
                continue
            full = repo / path
            try:
                size = full.stat().st_size
            except OSError:
                n_blob_stat_errors += 1
                findings.append(Finding(
                    id="publish.blob_stat_error",
                    category="publish_audit",
                    severity=Severity.FAIL,
                    message="a tracked file size could not be evaluated",
                    evidence={
                        "file_ordinal": file_ordinal,
                        "status": "error",
                    },
                ))
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
    execution_error = bool(
        git_error_lanes or n_content_scan_errors or n_blob_stat_errors
    ) or any(
        finding.id == "publish.bad_pattern" for finding in findings
    )
    meta = {
        "category": "publish_audit",
        "n_tracked": sum(1 for s in state_map.values() if s == "committed"),
        "n_staged": sum(1 for s in state_map.values() if s == "staged"),
        "n_untracked": sum(1 for s in state_map.values() if s == "untracked"),
        "n_content_scan_files": n_content_scan_files,
        "n_content_scan_errors": n_content_scan_errors,
        "n_blob_stat_errors": n_blob_stat_errors,
        "n_git_classification_errors": len(git_error_lanes),
        "git_classification_error_lanes": git_error_lanes,
        "execution_status": "error" if execution_error else "complete",
    }
    if not execution_error:
        meta["repo"] = str(repo)
    rep = Report(
        findings=findings,
        duration_ms=duration_ms,
        meta=meta,
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
