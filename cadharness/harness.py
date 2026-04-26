"""
Harness — the main runner that chains all gates together.

Usage:
    from cadharness import Harness
    h = Harness("assembly.step", config="harness.yaml")
    report = h.run()
    print(report)
    sys.exit(0 if report.passed else 1)

Or programmatically:
    h = Harness("assembly.step")
    h.add_inventory(labels={...}, expected={...})
    h.add_interference(skip_labels={'belt'})
    h.add_adjacency(rules=[...])
    h.add_dimensional(rules=[...])
    report = h.run()
"""
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional
from .inventory import InventoryCheck, InventoryResult, load_and_dedup, sig
from .interference import InterferenceCheck, InterferenceResult
from .adjacency import AdjacencyCheck, AdjacencyResult, AdjacencyRule
from .dimensional import DimensionalCheck, DimensionalResult, DimRule
from .findings import Finding, Report, Severity


@dataclass
class GateResult:
    name: str
    passed: bool
    details: str
    duration_ms: float
    findings: List[Finding] = field(default_factory=list)


@dataclass
class HarnessReport:
    passed: bool
    total_parts: int
    gates: List[GateResult]
    duration_ms: float
    report: Optional[Report] = None

    def __str__(self):
        lines = [
            f"CAD HARNESS REPORT — {'PASSED' if self.passed else 'FAILED'}",
            f"  Parts: {self.total_parts}",
            f"  Time:  {self.duration_ms:.0f}ms",
            "",
        ]
        for g in self.gates:
            marker = 'PASS' if g.passed else 'FAIL'
            lines.append(f"  [{marker}] {g.name} ({g.duration_ms:.0f}ms)")
            if not g.passed:
                for line in g.details.split('\n'):
                    lines.append(f"         {line}")
        return '\n'.join(lines)


class Harness:
    """
    Chain multiple validation gates against a STEP assembly.

    Gates run in order. Each gate receives the same pre-loaded parts list.
    The harness passes only if ALL gates pass.
    """

    def __init__(self, step_path: str):
        self.step_path = step_path
        self._gates = []
        self._labels = {}
        self._label_fn = None

    def _default_label_fn(self, solid):
        d = sig(solid)
        if d in self._labels:
            return self._labels[d]
        if d[0] == 1.5 and len(d) >= 2 and d[1] == 6.0:
            return 'belt'
        return 'other'

    def set_labels(self, labels: dict):
        """Set the bbox signature → label mapping used by all gates."""
        self._labels = labels
        self._label_fn = self._default_label_fn

    def set_label_fn(self, fn):
        """Set a custom label function (overrides set_labels)."""
        self._label_fn = fn

    def add_inventory(self, labels: dict, expected: dict):
        """Add an inventory gate."""
        self.set_labels(labels)
        self._gates.append(('inventory', InventoryCheck(
            self.step_path, labels, expected)))

    def add_interference(self, skip_labels=None, min_volume=1.0):
        """Add an interference gate."""
        self._gates.append(('interference', {
            'skip_labels': skip_labels or set(),
            'min_volume': min_volume,
        }))

    def add_adjacency(self, rules: List[AdjacencyRule]):
        """Add an adjacency gate."""
        self._gates.append(('adjacency', rules))

    def add_dimensional(self, rules: List[DimRule]):
        """Add a dimensional gate."""
        self._gates.append(('dimensional', rules))

    def run(self) -> HarnessReport:
        t0 = time.time()

        # Load parts once, share across all gates
        parts = load_and_dedup(self.step_path)
        label_fn = self._label_fn or self._default_label_fn

        results = []
        all_findings: List[Finding] = []

        for name, config in self._gates:
            gt = time.time()
            findings: List[Finding] = []

            if name == 'inventory':
                check = config
                r = check.run(parts=parts)
                passed = r.passed
                details = '\n'.join(r.mismatches) if r.mismatches else ''
                findings = _inventory_findings(r)

            elif name == 'interference':
                check = InterferenceCheck(
                    parts, label_fn,
                    skip_labels=config['skip_labels'],
                    min_volume=config['min_volume'])
                r = check.run()
                passed = r.passed
                details = '\n'.join(
                    f"{c.label_a} vs {c.label_b}: {c.volume:.0f}mm3"
                    for c in r.clips) if r.clips else ''
                findings = _interference_findings(r)

            elif name == 'adjacency':
                check = AdjacencyCheck(parts, label_fn, config)
                r = check.run()
                passed = r.passed
                details = '\n'.join(
                    f"{v.source_label} at ({v.source_center[0]:.0f},"
                    f"{v.source_center[1]:.0f},{v.source_center[2]:.0f}) "
                    f"nearest {v.nearest_target_label} = {v.nearest_distance:.0f}mm"
                    for v in r.violations) if r.violations else ''
                findings = _adjacency_findings(r)

            elif name == 'dimensional':
                check = DimensionalCheck(parts, label_fn, config)
                r = check.run()
                passed = r.passed
                details = '\n'.join(v.message for v in r.violations) if r.violations else ''
                findings = _dimensional_findings(r)

            else:
                continue

            results.append(GateResult(
                name=name, passed=passed, details=details,
                duration_ms=(time.time() - gt) * 1000,
                findings=findings))
            all_findings.extend(findings)

        all_passed = all(r.passed for r in results)
        duration_ms = (time.time() - t0) * 1000

        rich = Report(
            findings=all_findings,
            duration_ms=duration_ms,
            meta={"step": self.step_path, "total_parts": len(parts)},
        )
        rich.overall = rich.compute_overall()

        return HarnessReport(
            passed=all_passed,
            total_parts=len(parts),
            gates=results,
            duration_ms=duration_ms,
            report=rich,
        )


def _inventory_findings(r: InventoryResult) -> List[Finding]:
    out: List[Finding] = []
    for mismatch in r.mismatches:
        # mismatch format: "label: got N, expected M"
        try:
            label, rest = mismatch.split(":", 1)
            out.append(Finding(
                id="inventory.count_mismatch",
                category="inventory",
                severity=Severity.FAIL,
                message=mismatch,
                evidence={"label": label.strip(), "summary": rest.strip()},
            ))
        except ValueError:
            out.append(Finding(
                id="inventory.count_mismatch",
                category="inventory",
                severity=Severity.FAIL,
                message=mismatch,
            ))
    for region_name, region_result in r.region_results.items():
        for mismatch in region_result.mismatches:
            try:
                label, rest = mismatch.split(":", 1)
            except ValueError:
                label, rest = mismatch, ""
            out.append(Finding(
                id="inventory.region_count_mismatch",
                category="inventory",
                severity=Severity.FAIL,
                message=f"region {region_name}: {mismatch}",
                evidence={
                    "region": region_name,
                    "label": label.strip(),
                    "summary": rest.strip(),
                },
            ))
    return out


def _interference_findings(r: InterferenceResult) -> List[Finding]:
    out: List[Finding] = []
    for c in r.clips:
        out.append(Finding(
            id="interference.clip",
            category="interference",
            severity=Severity.FAIL,
            message=f"{c.label_a} vs {c.label_b}: {c.volume:.0f} mm3 overlap",
            evidence={
                "label_a": c.label_a,
                "label_b": c.label_b,
                "volume_mm3": round(c.volume, 1),
                "center_a": list(c.center_a),
                "center_b": list(c.center_b),
            },
        ))
    return out


def _adjacency_findings(r: AdjacencyResult) -> List[Finding]:
    out: List[Finding] = []
    for v in r.violations:
        out.append(Finding(
            id="adjacency.too_far",
            category="adjacency",
            severity=Severity.FAIL,
            message=(
                f"{v.source_label} nearest {v.nearest_target_label} "
                f"= {v.nearest_distance:.0f}mm (max {v.max_allowed:.0f}mm)"
            ),
            evidence={
                "source_label": v.source_label,
                "source_center": list(v.source_center),
                "nearest_target_label": v.nearest_target_label,
                "nearest_distance_mm": round(v.nearest_distance, 1),
                "max_allowed_mm": v.max_allowed,
            },
        ))
    return out


def _dimensional_findings(r: DimensionalResult) -> List[Finding]:
    out: List[Finding] = []
    for v in r.violations:
        out.append(Finding(
            id="dimensional.violation",
            category="dimensional",
            severity=Severity.FAIL,
            message=v.message,
            evidence={"label": v.label},
        ))
    return out
