"""
Claim-audit — text linter for README, docs, and BOM `notes` fields.

Three rule passes:
  1. Forbidden absolutes — case-insensitive substring match against a default
     list ("production-ready", "validated", etc.). Severity: fail.
  2. Numeric claims requiring evidence tags — regex; if a line matches a
     pattern but has no evidence tag like `[analysis]` / `[measured-prototype]`,
     emit warn.
  3. Stale terms — substring, user-supplied (e.g. "JB Weld" if a project
     dropped that adhesive).

Plus the two folded source-lint regex rules in `claim_audit.source_regex_rules`
that operate over `.py` files (protected output paths, silent fallback geometry).

Usage:
    from cadharness.claim_audit import run_claim_audit
    from cadharness.rules import load_rules
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
DEFAULT_FORBIDDEN_ABSOLUTES: Tuple[str, ...] = (
    "production-ready",
    "production-capable",
    "validated",
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
    "validated": (
        "Replace with the specific check that was run, "
        "e.g. 'passes cadclaw inventory + interference gates'."
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


def _scan_text_for_claims(
    text: str,
    rel_path: str,
    forbidden: List[str],
    numeric_patterns: List[re.Pattern],
    evidence_tags: List[str],
    stale_terms: List[str],
) -> List[Finding]:
    out: List[Finding] = []
    if rel_path.endswith(".md") or rel_path.endswith(".markdown"):
        text = _strip_md_code_fences(text)
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        lower = line.lower()
        for word in forbidden:
            if word.lower() in lower:
                out.append(Finding(
                    id="claim.forbidden_absolute",
                    category="claim_audit",
                    severity=Severity.FAIL,
                    message=f"{rel_path}:{line_no}: contains forbidden absolute {word!r}.",
                    suggested_fix=SUGGESTED_REWRITES.get(
                        word.lower(),
                        f"Replace {word!r} with an evidence-backed phrase or remove.",
                    ),
                    evidence={"path": rel_path, "line": line_no, "word": word},
                ))
        for term in stale_terms:
            if term.lower() in lower:
                out.append(Finding(
                    id="claim.stale_term",
                    category="claim_audit",
                    severity=Severity.FAIL,
                    message=f"{rel_path}:{line_no}: contains stale term {term!r}.",
                    suggested_fix=f"Remove {term!r} from {rel_path}.",
                    evidence={"path": rel_path, "line": line_no, "term": term},
                ))
        for regex in numeric_patterns:
            if regex.search(line):
                if not any(tag in line for tag in evidence_tags):
                    out.append(Finding(
                        id="claim.untagged_numeric",
                        category="claim_audit",
                        severity=Severity.WARN,
                        message=(
                            f"{rel_path}:{line_no}: numeric claim missing evidence tag."
                        ),
                        suggested_fix=(
                            f"Append an evidence tag from {evidence_tags!r} or rephrase."
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
) -> List[Finding]:
    """For BOM JSON: scan only the `name`, `description`, `notes` fields."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    if not isinstance(items, list):
        return []
    out: List[Finding] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        haystack = " ".join(
            str(item.get(k, "")) for k in ("name", "description", "notes")
        )
        synth = f"{rel_path} (id={item.get('id', i)})"
        out.extend(_scan_text_for_claims(
            haystack, synth, forbidden, numeric_patterns, evidence_tags, stale_terms,
        ))
    return out


def _scan_python_for_source_rules(
    path: Path,
    rel_path: str,
    rules_models,
) -> List[Finding]:
    out: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for srule in rules_models:
        try:
            regex = re.compile(srule.pattern)
        except re.error as e:
            out.append(Finding(
                id="claim.bad_source_pattern",
                category="claim_audit",
                severity=Severity.WARN,
                message=f"source_regex_rule pattern {srule.pattern!r} is not valid: {e}",
                evidence={"pattern": srule.pattern},
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
                    message=f"{rel_path}:{line_no}: {srule.message}",
                    evidence={"path": rel_path, "line": line_no,
                              "pattern": srule.pattern},
                ))
    return out


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
    numeric = [
        re.compile(p, re.IGNORECASE)
        for p in (
            list(DEFAULT_NUMERIC_PATTERNS)
            + list(rules.claim_audit.evidence_tags_required_for)
        )
    ]
    evidence_tags = list(rules.claim_audit.evidence_tags_allowed)
    stale = list(rules.claim_audit.stale_terms)

    # Text + BOM JSON scan
    files = _expand_globs(rules.claim_audit.scan_paths, repo)
    n_text = 0
    for path in files:
        try:
            rel = str(path.relative_to(repo)).replace("\\", "/")
        except ValueError:
            rel = str(path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            findings.extend(_scan_json_notes(
                path, rel, forbidden, numeric, evidence_tags, stale,
            ))
            n_text += 1
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            findings.extend(_scan_text_for_claims(
                text, rel, forbidden, numeric, evidence_tags, stale,
            ))
            n_text += 1

    # Source-regex pass over .py files
    if rules.claim_audit.source_regex_rules:
        py_globs = list({s.file_glob for s in rules.claim_audit.source_regex_rules})
        py_files = _expand_globs(py_globs, repo)
        for path in py_files:
            try:
                rel = str(path.relative_to(repo)).replace("\\", "/")
            except ValueError:
                rel = str(path)
            findings.extend(_scan_python_for_source_rules(
                path, rel, rules.claim_audit.source_regex_rules,
            ))

    duration_ms = (time.time() - t0) * 1000
    rep = Report(
        findings=findings,
        duration_ms=duration_ms,
        meta={
            "category": "claim_audit",
            "repo": str(repo),
            "files_scanned": n_text,
            "n_forbidden": len(forbidden),
            "n_numeric_patterns": len(numeric),
            "n_stale_terms": len(stale),
        },
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
