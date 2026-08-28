"""Markdown reporter — PR-comment ready output."""
from __future__ import annotations

from typing import List

from ..findings import Finding, Report, Severity


_SEV_ORDER = {Severity.FAIL: 0, Severity.WARN: 1, Severity.PASS: 2}


def _badge(sev: Severity) -> str:
    return {
        Severity.FAIL: "fail",
        Severity.WARN: "warn",
        Severity.PASS: "pass",
    }[sev]


def render_markdown(report: Report) -> str:
    """Render a Report as Markdown suitable for a PR comment or report file."""
    project = report.meta.get("project", "report")
    step = report.meta.get("step", "")
    not_applicable = report.meta.get("applicability") == "not_applicable"
    overall = "N/A" if not_applicable else report.overall.value.upper()

    n_fail = len(report.by_severity(Severity.FAIL))
    n_warn = len(report.by_severity(Severity.WARN))
    n_pass = len(report.by_severity(Severity.PASS))

    lines: List[str] = []
    lines.append(f"# CADCLAW report — {project}")
    lines.append("")
    summary = (
        f"**Result: {overall}** ({n_pass} pass, {n_warn} warn, {n_fail} fail)"
    )
    if step:
        summary += f"  ·  STEP: `{step}`"
    summary += (
        f"  ·  {report.duration_ms:.0f} ms"
        f"  ·  schema {report.schema_version}"
        f"  ·  gate-spec {report.gate_spec_version}"
    )
    lines.append(summary)
    lines.append("")

    if report.findings:
        sorted_findings = sorted(
            report.findings, key=lambda f: (_SEV_ORDER[f.severity], f.category, f.id)
        )
        lines.append("## Findings")
        lines.append("")
        lines.append("| Severity | Gate | ID | Message |")
        lines.append("|---|---|---|---|")
        for f in sorted_findings:
            msg = f.message.replace("|", "\\|")
            lines.append(f"| {_badge(f.severity)} | {f.category} | `{f.id}` | {msg} |")
        lines.append("")

        fixes = [f for f in sorted_findings if f.suggested_fix]
        if fixes:
            lines.append("### Suggested fixes")
            lines.append("")
            for f in fixes:
                fix = f.suggested_fix or ""
                lines.append(f"- **`{f.id}`**: {fix}")
            lines.append("")
    else:
        lines.append("## Findings")
        lines.append("")
        lines.append("_Not applicable._" if not_applicable else "_No findings._")
        lines.append("")

    cb = report.confidence_budget
    if cb.checked or cb.not_checked or cb.assumptions:
        lines.append("## Confidence budget")
        lines.append("")
        if cb.checked:
            lines.append("**Checked:**")
            lines.append("")
            for item in cb.checked:
                lines.append(f"- {item}")
            lines.append("")
        if cb.not_checked:
            lines.append("**Not checked:**")
            lines.append("")
            for item in cb.not_checked:
                lines.append(f"- {item}")
            lines.append("")
        if cb.assumptions:
            lines.append("**Assumptions:**")
            lines.append("")
            for item in cb.assumptions:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines)
