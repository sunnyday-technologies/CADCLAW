"""CLI-friendly text reporter — stdlib only, ANSI optional."""
from __future__ import annotations

import sys
from typing import List

from ..findings import Finding, Report, Severity
from .. import __version__


_SEV_ORDER = {Severity.FAIL: 0, Severity.WARN: 1, Severity.PASS: 2}


def _ansi(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _sev_tag(sev: Severity, color: bool) -> str:
    text = sev.value.upper().rjust(4)
    if not color:
        return f"[{text}]"
    code = {Severity.FAIL: "31", Severity.WARN: "33", Severity.PASS: "32"}[sev]
    return _ansi(f"[{text}]", code, True)


def _group_findings_by_category(findings: List[Finding]):
    groups: dict[str, List[Finding]] = {}
    for f in findings:
        groups.setdefault(f.category, []).append(f)
    for cat in groups:
        groups[cat].sort(key=lambda f: _SEV_ORDER[f.severity])
    return groups


def render_text(report: Report, color: bool | None = None) -> str:
    """Render a Report as compact CLI text. Color auto-detects from isatty."""
    if color is None:
        color = sys.stdout.isatty()

    project = report.meta.get("project", "")
    step = report.meta.get("step", "")
    rules = report.meta.get("rules", "")
    header_bits = [f"CADCLAW {__version__}", f"schema {report.schema_version}"]
    if project:
        header_bits.append(project)
    if step:
        header_bits.append(step)
    header_bits.append(f"{report.duration_ms:.0f}ms")

    n_fail = len(report.by_severity(Severity.FAIL))
    n_warn = len(report.by_severity(Severity.WARN))
    n_pass = len(report.by_severity(Severity.PASS))

    lines: List[str] = [
        "  ".join(header_bits),
        "",
    ]

    if not report.findings:
        lines.append(f"  {_sev_tag(Severity.PASS, color)} no findings")
    else:
        groups = _group_findings_by_category(report.findings)
        for cat, items in sorted(groups.items()):
            for f in items:
                tag = _sev_tag(f.severity, color)
                lines.append(f"  {tag}  {f.category:<14} {f.id:<28} {f.message}")
                if f.suggested_fix:
                    lines.append(f"          fix: {f.suggested_fix}")

    lines.append("")
    overall = report.overall.value.upper()
    summary = f"{n_pass} pass, {n_warn} warn, {n_fail} fail. overall: {overall}"
    lines.append(summary)

    cb = report.confidence_budget
    if cb.not_checked:
        lines.append("")
        lines.append("What CADCLAW did not check:")
        for item in cb.not_checked:
            lines.append(f"  - {item}")
    if cb.assumptions:
        lines.append("")
        lines.append("Assumptions:")
        for item in cb.assumptions:
            lines.append(f"  - {item}")

    return "\n".join(lines)
