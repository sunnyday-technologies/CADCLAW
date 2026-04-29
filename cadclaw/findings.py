"""
Findings model — the unified Severity / Finding / Report dataclasses every
v0.6 gate emits.

This is intentionally stdlib-only (no pydantic) so existing v0.5 callers can
import `Finding` without paying for the rule-file dependency. Pydantic models
in `cadclaw/rules.py` validate config; this module is what gates produce.

Usage:
    from cadclaw.findings import Finding, Severity, Report, ConfidenceBudget

    findings = [
        Finding(
            id="bom.qty_mismatch",
            category="bom_audit",
            severity=Severity.FAIL,
            message="BOM id=5 qty=16, expected 12",
            suggested_fix="Set qty to 12",
            evidence={"rule_id": 5, "got": 16, "expected": 12},
        ),
    ]
    report = Report(findings=findings)
    report.overall = report.compute_overall()
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"

    def rank(self) -> int:
        return {"pass": 0, "warn": 1, "fail": 2}[self.value]


@dataclass(frozen=True)
class Finding:
    """One structured finding from a gate.

    `id` is dotted (`gate.code`) for stable filtering. `category` matches the
    gate name. `evidence` is JSON-safe — no STEP shapes, no live objects.
    """
    id: str
    category: str
    severity: Severity
    message: str
    suggested_fix: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class ConfidenceBudget:
    """What this report tested, what it didn't, and what it assumed."""
    checked: List[str] = field(default_factory=list)
    not_checked: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)

    def merge(self, other: "ConfidenceBudget") -> None:
        for src, dst in (
            (other.checked, self.checked),
            (other.not_checked, self.not_checked),
            (other.assumptions, self.assumptions),
        ):
            for item in src:
                if item not in dst:
                    dst.append(item)


@dataclass
class Report:
    """Unified report shape every v0.7 gate / runner produces."""
    schema_version: str = "0.7"
    overall: Severity = Severity.PASS
    findings: List[Finding] = field(default_factory=list)
    confidence_budget: ConfidenceBudget = field(default_factory=ConfidenceBudget)
    duration_ms: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)

    def compute_overall(self) -> Severity:
        sevs = {f.severity for f in self.findings}
        if Severity.FAIL in sevs:
            return Severity.FAIL
        if Severity.WARN in sevs:
            return Severity.WARN
        return Severity.PASS

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def extend(self, findings: List[Finding]) -> None:
        self.findings.extend(findings)

    def by_severity(self, severity: Severity) -> List[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def passed(self) -> bool:
        return self.overall != Severity.FAIL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "overall": self.overall.value,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
            "findings": [f.to_dict() for f in self.findings],
            "confidence_budget": {
                "checked": self.confidence_budget.checked,
                "not_checked": self.confidence_budget.not_checked,
                "assumptions": self.confidence_budget.assumptions,
            },
        }
