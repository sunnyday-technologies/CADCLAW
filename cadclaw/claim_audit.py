"""
Claim-audit — text linter for README, docs, and BOM `notes` fields.

Three rule passes:
  1. Forbidden absolutes — case-insensitive substring match against a default
     list ("production-ready", "guaranteed", etc.). Severity: fail.
  2. Numeric claims requiring evidence tags — regex; if a line matches a
     pattern but has no evidence tag like `[analysis]` / `[measured-prototype]`,
     emit warn.
  3. Stale terms — substring, user-supplied (e.g. "JB Weld" if a project
     dropped that adhesive).

Plus the two folded source-lint regex rules in `claim_audit.source_regex_rules`
that operate over `.py` files (protected output paths, silent fallback geometry).

v0.7 / MED-3: forbidden_absolutes and stale_terms passes are
license-aware and negation-aware. License attribution lines (CC BY, MIT,
Apache, GPL, SPDX-License-Identifier, Copyright) and single-line HTML
comments are blanked before scanning so e.g. a CC BY-SA attribution
mentioning "OpenBuilds" doesn't trigger a stale_term flag whose suggested
fix would be a license violation. Negation tokens preceding a term
within 30 chars (bounded by sentence punctuation) suppress the match,
so "// no Supabase" doesn't fire as a stale_term for "Supabase".
Numeric-claim regex scans ignore both — license blocks and code comments
can still cite numbers that need evidence tagging.

v0.7 / MED-4: "validated" was removed from DEFAULT_FORBIDDEN_ABSOLUTES.
The word is too overloaded across third-party-product mentions and
domain-specific phrases ("ASTM-validated"). Projects that want to flag
it can opt in via `forbidden_absolutes_extra: ["validated"]`.

Usage:
    from cadclaw.claim_audit import run_claim_audit
    from cadclaw.rules import load_rules
    rules = load_rules("cadclaw.yaml")
    report = run_claim_audit(rules, repo_root=".")
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .findings import ConfidenceBudget, Finding, Report, Severity
from .rules import RuleSet


# Default forbidden-absolutes list. Keep small and opinionated.
# v0.7 / MED-4: "validated" removed from defaults; opt in via
# forbidden_absolutes_extra if you want it.
DEFAULT_FORBIDDEN_ABSOLUTES: Tuple[str, ...] = (
    "production-ready",
    "production-capable",
    "guaranteed",
    "fully automated",
    "no risk",
    "100% reliable",
    "industry-leading",
    "best-in-class",
    "bulletproof",
    "complete solution",
)

# Suggested rewrites — opinionated mapping per word.
SUGGESTED_REWRITES: Dict[str, str] = {
    "production-ready": (
        "Replace with a specific evidence-backed phrase, e.g. "
        "'tested against the v0.6 fixture suite' or 'used on SN001'."
    ),
    "production-capable": (
        "Replace with a specific evidence-backed phrase or remove."
    ),
    "guaranteed": (
        "Replace with a probabilistic or evidence-tagged statement."
    ),
}

DEFAULT_NUMERIC_PATTERNS: Tuple[str, ...] = (
    r"flex(?:ure)?\s+(?:under|of|=|<=|<)\s*\d+(?:\.\d+)?\s*(?:mm|kg)",
    r"deflect(?:ion|s)?\s+(?:of|=|<=|<|under)\s*\d+(?:\.\d+)?\s*mm",
    r"safety\s+factor\s+(?:of|=)?\s*\d+(?:\.\d+)?",
    r"loads?\s+(?:up\s+to|of|to)\s*\d+(?:\.\d+)?\s*kg",
)


# v0.7 / MED-3 — license-attribution and HTML-comment stripping.
# Lines matching these patterns are blanked (replaced with empty string,
# preserving line numbers) before forbidden_absolutes / stale_terms scanning.
# Same trick as _strip_md_code_fences; the numeric-claim scan still sees the
# original text because numbers in license blocks still want evidence tags.
#
# Patterns are intentionally permissive — a line that strongly signals
# license/attribution context shouldn't trip stale_term flags (the
# field-test "OpenBuilds in CC BY-SA attribution" case is the canonical
# bug; flagging it could lead to a license violation if a user follows
# the suggested fix).
_LICENSE_LINE_PATTERN = re.compile(
    r"(?i)(?:"
    r"CC[-\s]?BY[-\s]|CC0\b|Creative\s+Commons|creativecommons\.org|"
    r"MIT\s+License|Apache\s+License|BSD\s+License|"
    r"\bGPL[v\d-]?|CERN-OHL|"
    r"SPDX-License-Identifier:|"
    r"Copyright\s*\((?:c|C)\)|Copyright\s*\xa9|Copyright\s*©|"
    r"licensed\s+under|License\s+Notice|"
    r"based\s+on\s+\[|derived\s+from\s+\["
    r")"
)
_HTML_COMMENT_LINE_PATTERN = re.compile(r"<!--.*?-->")

# v0.7 / MED-3 — negation-aware substring matching for stale_terms and
# forbidden_absolutes. Mirrors the negation logic in bom_audit.py
# (_NEGATION_PATTERN, _is_negated). Kept duplicated rather than extracted
# so the two gates can evolve independently if the rules diverge.
#
# The lookback is clause-scoped, not character-scoped: the window is clipped at
# the nearest clause or sentence boundary, and the character cap exists only to
# stop a runaway scan. At 30 chars the cap was doing the real work and doing it
# badly. It flagged our own disclaimer "no return, defect-prevention, or
# fabrication outcome is guaranteed" as an overclaim, because the enumerated
# list put "no" 62 characters from "guaranteed". A linter that flags honest
# limitation language teaches people to delete disclaimers, which is the exact
# opposite of what this gate is for.
#
# ";" is now a boundary as well, so a negation cannot leak across independent
# clauses: "we do not use X; the result is guaranteed" still flags.
_NEGATION_PATTERN = re.compile(
    r"\b(?:not|no|never|do not|don't|doesn't|replaces|instead of|rather than|without|excludes)\b",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARIES = (".", "!", "?", ";", "\n")
_NEGATION_LOOKBACK_CHARS = 160


def _is_negated(haystack: str, term_index: int) -> bool:
    start = max(0, term_index - _NEGATION_LOOKBACK_CHARS)
    window = haystack[start:term_index]
    last_boundary = max(
        (window.rfind(b) for b in _SENTENCE_BOUNDARIES),
        default=-1,
    )
    if last_boundary >= 0:
        window = window[last_boundary + 1:]
    return bool(_NEGATION_PATTERN.search(window))


def _find_unnegated(haystack: str, needle: str) -> int:
    """Return index of the first non-negated occurrence of `needle` in
    case-folded `haystack`, or -1 if every occurrence is preceded by a
    negation token.
    """
    h = haystack.lower()
    n = needle.lower()
    if not n:
        return -1
    idx = h.find(n)
    while idx >= 0:
        if not _is_negated(haystack, idx):
            return idx
        idx = h.find(n, idx + 1)
    return -1


def _strip_md_code_fences(text: str) -> str:
    """Drop fenced code blocks so we don't lint sample code."""
    out_lines: List[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out_lines.append("")
            continue
        out_lines.append("" if in_fence else line)
    return "\n".join(out_lines)


def _strip_license_lines(text: str) -> str:
    """Blank lines that look like license attribution or copyright notices.

    Used by the forbidden_absolutes / stale_terms passes so e.g. a CC BY-SA
    block citing "OpenBuilds" doesn't trigger a stale_term — its suggested
    fix would be a license violation. Line numbers are preserved by
    replacing matched lines with empty strings.
    """
    out: List[str] = []
    for line in text.splitlines():
        if _LICENSE_LINE_PATTERN.search(line):
            out.append("")
        else:
            out.append(line)
    return "\n".join(out)


def _strip_html_comments(text: str) -> str:
    """Blank single-line HTML comment content.

    Per-line replacement — multi-line HTML comments are not supported and
    are noted in the report's confidence_budget.not_checked. A `<!-- foo -->`
    line becomes a line with the comment content removed but other content
    preserved.
    """
    out: List[str] = []
    for line in text.splitlines():
        out.append(_HTML_COMMENT_LINE_PATTERN.sub("", line))
    return "\n".join(out)


def _scan_text_for_claims(
    text: str,
    rel_path: str,
    forbidden: List[str],
    numeric_patterns: List[re.Pattern],
    evidence_tags: List[str],
    stale_terms: List[str],
) -> List[Finding]:
    out: List[Finding] = []
    is_md = rel_path.endswith(".md") or rel_path.endswith(".markdown")
    is_html = rel_path.endswith(".html") or rel_path.endswith(".htm")
    if is_md:
        text = _strip_md_code_fences(text)

    # Build a parallel "claim scan" view: license/HTML-comment lines are
    # blanked here only for forbidden_absolutes / stale_terms scanning.
    # Numeric-claim regex still sees the unaltered text — license blocks
    # citing deflection numbers should still warrant evidence tags.
    claim_text = text
    if is_md:
        claim_text = _strip_license_lines(claim_text)
    if is_html:
        claim_text = _strip_html_comments(claim_text)
        claim_text = _strip_license_lines(claim_text)

    claim_lines = claim_text.splitlines()
    numeric_lines = text.splitlines()
    for line_no in range(1, max(len(claim_lines), len(numeric_lines)) + 1):
        claim_line = claim_lines[line_no - 1] if line_no - 1 < len(claim_lines) else ""
        numeric_line = numeric_lines[line_no - 1] if line_no - 1 < len(numeric_lines) else ""

        for rule_ordinal, word in enumerate(forbidden, start=1):
            idx = _find_unnegated(claim_line, word)
            if idx >= 0:
                out.append(Finding(
                    id="claim.forbidden_absolute",
                    category="claim_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"{rel_path}:{line_no}: contains a configured "
                        "forbidden absolute."
                    ),
                    suggested_fix=(
                        "Replace the flagged absolute at this location with "
                        "an evidence-backed phrase or remove it."
                    ),
                    evidence={
                        "path": rel_path,
                        "line": line_no,
                        "kind": "forbidden_absolute",
                        "rule_ordinal": rule_ordinal,
                    },
                ))
        for rule_ordinal, term in enumerate(stale_terms, start=1):
            idx = _find_unnegated(claim_line, term)
            if idx >= 0:
                out.append(Finding(
                    id="claim.stale_term",
                    category="claim_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"{rel_path}:{line_no}: contains a configured stale term."
                    ),
                    suggested_fix=(
                        "Remove or replace the configured stale term at this "
                        "location."
                    ),
                    evidence={
                        "path": rel_path,
                        "line": line_no,
                        "kind": "stale_term",
                        "rule_ordinal": rule_ordinal,
                    },
                ))
        for regex in numeric_patterns:
            if regex.search(numeric_line):
                if not any(tag in numeric_line for tag in evidence_tags):
                    out.append(Finding(
                        id="claim.untagged_numeric",
                        category="claim_audit",
                        severity=Severity.WARN,
                        message=(
                            f"{rel_path}:{line_no}: numeric claim missing evidence tag."
                        ),
                        suggested_fix=(
                            "Append an allowed evidence tag from the rule file "
                            "or rephrase."
                        ),
                        evidence={"path": rel_path, "line": line_no},
                    ))
                    break  # one warning per line is enough
    return out


def _scan_json_notes(
    path: Path,
    rel_path: str,
    forbidden: List[str],
    numeric_patterns: List[re.Pattern],
    evidence_tags: List[str],
    stale_terms: List[str],
) -> tuple[List[Finding], str]:
    """Recursively scan string ``name``/``description``/``notes`` fields.

    Returns ``scanned``, ``unsupported``, or ``error`` so a valid JSON object
    with no claim-bearing fields cannot be counted as evidence.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        return [], "error"

    claim_strings: List[str] = []

    def _collect(value) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in {"name", "description", "notes"} and isinstance(
                    nested, str
                ):
                    claim_strings.append(nested)
                _collect(nested)
        elif isinstance(value, list):
            for nested in value:
                _collect(nested)

    try:
        _collect(data)
    except Exception:
        # A syntactically valid but pathologically nested manifest must not
        # leak a recursion/runtime exception through a CLI or MCP audit.
        return [], "error"
    if not claim_strings:
        return [], "unsupported"

    out: List[Finding] = []
    for ordinal, haystack in enumerate(claim_strings, start=1):
        synth = f"{rel_path} (claim field {ordinal})"
        out.extend(_scan_text_for_claims(
            haystack, synth, forbidden, numeric_patterns, evidence_tags, stale_terms,
        ))
    return out, "scanned"


def _scan_python_for_source_rules(
    path: Path,
    rel_path: str,
    rules_models,
) -> tuple[List[Finding], bool]:
    out: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return out, False
    for ordinal, srule in rules_models:
        try:
            regex = re.compile(srule.pattern)
        except re.error as exc:
            evidence = {"rule_ordinal": ordinal, "status": "error"}
            position = getattr(exc, "pos", None)
            if isinstance(position, int) and position >= 0:
                evidence["position"] = position
            out.append(Finding(
                id="claim.bad_source_pattern",
                category="claim_audit",
                severity=Severity.WARN,
                message="a configured source-regex pattern is invalid",
                evidence=evidence,
            ))
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                sev = {"pass": Severity.PASS, "warn": Severity.WARN, "fail": Severity.FAIL}.get(
                    srule.severity.lower(), Severity.FAIL,
                )
                out.append(Finding(
                    id="claim.source_regex",
                    category="claim_audit",
                    severity=sev,
                    message=(
                        f"{rel_path}:{line_no}: configured source-regex "
                        f"rule {ordinal} matched (value redacted)"
                    ),
                    evidence={
                        "path": rel_path,
                        "line": line_no,
                        "kind": "source_regex",
                        "rule_ordinal": ordinal,
                    },
                ))
    return out, True


def _expand_globs(globs: List[str], repo: Path) -> List[Path]:
    out: List[Path] = []
    for g in globs:
        for p in repo.glob(g):
            if p.is_file():
                out.append(p)
    # Dedup while preserving order
    seen = set()
    unique: List[Path] = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        unique.append(p)
    return unique


def run_claim_audit(rules: RuleSet, repo_root: str = ".") -> Report:
    t0 = time.time()
    findings: List[Finding] = []
    repo = Path(repo_root).resolve()

    forbidden = list(DEFAULT_FORBIDDEN_ABSOLUTES) + list(
        rules.claim_audit.forbidden_absolutes_extra
    )
    numeric = []
    numeric_config_errors = 0
    for ordinal, pattern in enumerate(
        list(DEFAULT_NUMERIC_PATTERNS)
        + list(rules.claim_audit.evidence_tags_required_for),
        start=1,
    ):
        try:
            numeric.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            evidence = {"pattern_ordinal": ordinal, "status": "error"}
            position = getattr(exc, "pos", None)
            if isinstance(position, int) and position >= 0:
                evidence["position"] = position
            findings.append(Finding(
                id="claim.bad_numeric_pattern",
                category="claim_audit",
                severity=Severity.WARN,
                message="a configured numeric-claim pattern is invalid",
                evidence=evidence,
            ))
            numeric_config_errors += 1
    evidence_tags = list(rules.claim_audit.evidence_tags_allowed)
    stale = list(rules.claim_audit.stale_terms)

    # Text + BOM JSON scan
    files = _expand_globs(rules.claim_audit.scan_paths, repo)
    n_text = 0
    n_scan_errors = numeric_config_errors
    for file_ordinal, path in enumerate(files, start=1):
        try:
            rel = str(path.relative_to(repo)).replace("\\", "/")
        except ValueError:
            rel = str(path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            scanned_findings, scan_status = _scan_json_notes(
                path, rel, forbidden, numeric, evidence_tags, stale,
            )
            findings.extend(scanned_findings)
            if scan_status == "scanned":
                n_text += 1
            else:
                n_scan_errors += 1
                findings.append(Finding(
                    id=(
                        "claim.no_scannable_claim_fields"
                        if scan_status == "unsupported"
                        else "claim.scan_error"
                    ),
                    category="claim_audit",
                    severity=Severity.FAIL,
                    message=(
                        "a configured JSON file has no scannable claim fields"
                        if scan_status == "unsupported"
                        else "a configured JSON file could not be read and parsed"
                    ),
                    evidence={
                        "file_ordinal": file_ordinal,
                        "status": "error",
                    },
                ))
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                n_scan_errors += 1
                findings.append(Finding(
                    id="claim.scan_error",
                    category="claim_audit",
                    severity=Severity.FAIL,
                    message="a configured text file could not be read",
                    evidence={
                        "file_ordinal": file_ordinal,
                        "status": "error",
                    },
                ))
                continue
            findings.extend(_scan_text_for_claims(
                text, rel, forbidden, numeric, evidence_tags, stale,
            ))
            n_text += 1

    # Validate source-regex assertions independently of whether their globs
    # happen to match a file.  An invalid configured assertion is an error,
    # not an empty/no-evidence pass or not-checked result.
    valid_source_rules = []
    for ordinal, source_rule in enumerate(
        rules.claim_audit.source_regex_rules,
        start=1,
    ):
        try:
            re.compile(source_rule.pattern)
        except re.error as exc:
            evidence = {"rule_ordinal": ordinal, "status": "error"}
            position = getattr(exc, "pos", None)
            if isinstance(position, int) and position >= 0:
                evidence["position"] = position
            findings.append(Finding(
                id="claim.bad_source_pattern",
                category="claim_audit",
                severity=Severity.WARN,
                message="a configured source-regex pattern is invalid",
                evidence=evidence,
            ))
        else:
            valid_source_rules.append((ordinal, source_rule))

    # Source-regex pass over .py files
    n_source = 0
    if valid_source_rules:
        py_globs = list({
            source_rule.file_glob
            for _ordinal, source_rule in valid_source_rules
        })
        py_files = _expand_globs(py_globs, repo)
        for file_ordinal, path in enumerate(py_files, start=1):
            try:
                rel = str(path.relative_to(repo)).replace("\\", "/")
            except ValueError:
                rel = str(path)
            source_findings, scan_ok = _scan_python_for_source_rules(
                path, rel, valid_source_rules,
            )
            findings.extend(source_findings)
            if scan_ok:
                n_source += 1
            else:
                n_scan_errors += 1
                findings.append(Finding(
                    id="claim.scan_error",
                    category="claim_audit",
                    severity=Severity.FAIL,
                    message="a configured source file could not be read",
                    evidence={
                        "file_ordinal": file_ordinal,
                        "status": "error",
                    },
                ))

    duration_ms = (time.time() - t0) * 1000
    execution_error = bool(n_scan_errors) or any(
        finding.id in {
            "claim.bad_numeric_pattern",
            "claim.bad_source_pattern",
            "claim.no_scannable_claim_fields",
            "claim.scan_error",
        }
        for finding in findings
    )
    meta = {
        "category": "claim_audit",
        "files_scanned": n_text,
        "source_files_scanned": n_source,
        "scan_error_count": n_scan_errors,
        "n_forbidden": len(forbidden),
        "n_numeric_patterns": len(numeric),
        "n_stale_terms": len(stale),
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
                "forbidden absolutes (substring)",
                "numeric claims with evidence-tag requirement (regex)",
                "stale terms (substring)",
                "source-regex rules over .py files",
            ],
            not_checked=[
                "claim correctness (we don't fact-check; we only flag classes of language)",
                "claims in image alt text or PDFs",
                "tone, sentiment, or marketing strength beyond the listed words",
            ],
            assumptions=[
                "evidence tags use the bracket form `[analysis]` / `[measured-*]`",
                "fenced code blocks are not editorial claims",
                "the rule file's `stale_terms` list is up to date for this project",
            ],
        ),
    )
    rep.overall = rep.compute_overall()
    return rep
