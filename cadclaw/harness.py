"""
Harness — programmatic runner for chained geometry checks.

Usage:
    from cadclaw import Harness
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
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from .inventory import InventoryCheck, InventoryResult, load_and_dedup, sig
from .interference import InterferenceCheck, InterferenceResult
from .adjacency import AdjacencyCheck, AdjacencyResult, AdjacencyRule
from .dimensional import DimensionalCheck, DimensionalResult, DimRule
from .orientation import (
    OrientationCheck, OrientationResult, suggest_rotation,
    _AXIS_NAMES,
)
from .floating import FloatingCheck, FloatingResult
from .color_check import ColorCheck, ColorResult
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
        """Set the bbox signature → label mapping used by configured checks."""
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

    def add_interference(self, skip_labels=None, min_volume=1.0,
                         min_clearance_mm=1.0):
        """Add an interference gate.

        `min_clearance_mm` controls the suggested fix-vector: when a
        clip is reported, the suggestion shifts part A by the minimum
        interval translation along the cheapest axis so it lands clear
        of part B with that running clearance.
        """
        self._gates.append(('interference', {
            'skip_labels': skip_labels or set(),
            'min_volume': min_volume,
            'min_clearance_mm': min_clearance_mm,
        }))

    def add_adjacency(self, rules: List[AdjacencyRule]):
        """Add an adjacency gate."""
        self._gates.append(('adjacency', rules))

    def add_dimensional(self, rules: List[DimRule]):
        """Add a dimensional gate."""
        self._gates.append(('dimensional', rules))

    def add_orientation(self, label_specs, tol_mm: float = 0.1):
        """Add an orientation / face-mate gate (v0.9 gate #1).

        `label_specs` is `Dict[label, LabelSpec]` (typically from
        `RuleSet.label_specs()`). Only labels with a non-None
        `expected_face` are checked.
        """
        self._gates.append(('orientation', {
            'label_specs': label_specs,
            'tol_mm': tol_mm,
        }))

    def add_floating_check(self, structural_labels, max_gap_mm: float = 5.0,
                           exempt_labels=None):
        """Add a floating-part gate (v0.9 gate #3).

        Flag any non-exempt part whose minimum bbox distance to any
        structural part exceeds `max_gap_mm`. `structural_labels` must
        be non-empty for the gate to run.
        """
        self._gates.append(('floating', {
            'structural_labels': set(structural_labels),
            'max_gap_mm': max_gap_mm,
            'exempt_labels': set(exempt_labels) if exempt_labels else {"belt"},
        }))

    def run(self) -> HarnessReport:
        t0 = time.time()

        # Load parts once, share across configured geometry checks.
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
                    min_volume=config['min_volume'],
                    min_clearance_mm=config.get('min_clearance_mm', 1.0))
                r = check.run()
                passed = r.passed
                details = '\n'.join(_format_clip_detail(c) for c in r.clips) if r.clips else ''
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

            elif name == 'orientation':
                check = OrientationCheck(
                    parts, label_fn,
                    label_specs=config['label_specs'],
                    tol_mm=config.get('tol_mm', 0.1))
                r = check.run()
                passed = r.passed
                details = '\n'.join(_format_misorientation(m) for m in r.violations) if r.violations else ''
                findings = _orientation_findings(r)

            elif name == 'floating':
                check = FloatingCheck(
                    parts, label_fn,
                    structural_labels=config['structural_labels'],
                    max_gap_mm=config.get('max_gap_mm', 5.0),
                    exempt_labels=config.get('exempt_labels'))
                r = check.run()
                passed = r.passed
                details = '\n'.join(_format_floating(f) for f in r.floating) if r.floating else ''
                findings = _floating_findings(r)

            else:
                continue

            results.append(GateResult(
                name=name, passed=passed, details=details,
                duration_ms=(time.time() - gt) * 1000,
                findings=findings))
            all_findings.extend(findings)

        if not results:
            all_findings.append(Finding(
                id="harness.no_gates_configured",
                category="harness",
                severity=Severity.FAIL,
                message="the harness has no configured gates",
            ))

        # ``all([])`` is mathematically true but operationally unsafe here:
        # an empty validation plan has established nothing about the CAD.
        all_passed = bool(results) and all(r.passed for r in results)
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


def _format_shift_suggestion(c) -> str:
    """e.g. 'shift +Y by 1.35mm to clear with 1mm clearance'."""
    axis_upper = c.suggest_axis.upper()
    sign = "+" if c.suggest_shift_mm >= 0 else "-"
    mag = abs(c.suggest_shift_mm)
    clearance = c.clearance_mm
    clearance_str = f"{clearance:g}mm"
    return (f"shift {sign}{axis_upper} by {mag:.2f}mm "
            f"to clear with {clearance_str} clearance")


def _format_clip_detail(c) -> str:
    """Compact CLI line: 'plate at (x,y,z) clips cbeam by Vmm3 — shift +Y by ...'."""
    cx, cy, cz = c.center_a
    head = (f"{c.label_a} at ({cx:.0f}, {cy:.0f}, {cz:.0f}) "
            f"clips {c.label_b} by {c.volume:.0f} mm^3")
    if c.suggest_shift_mm == 0.0:
        return head
    return f"{head} — {_format_shift_suggestion(c)}"


def _interference_findings(r: InterferenceResult) -> List[Finding]:
    out: List[Finding] = []
    if r.not_checked_reason and not r.error_count:
        out.append(Finding(
            id="interference.not_checked",
            category="interference",
            severity=Severity.FAIL,
            message=f"interference was not checked: {r.not_checked_reason}",
            evidence={"eligible_parts": r.eligible_parts},
        ))
    if r.error_count:
        out.append(Finding(
            id="interference.execution_error",
            category="interference",
            severity=Severity.FAIL,
            message=(
                f"{r.error_count} interference evaluation(s) could not "
                "complete"
            ),
            evidence={
                "error_count": r.error_count,
                "candidate_pairs_attempted": r.checked_pairs,
                "eligible_parts": r.eligible_parts,
            },
        ))
    for c in r.clips:
        suggestion = _format_shift_suggestion(c)
        out.append(Finding(
            id="interference.clip",
            category="interference",
            severity=Severity.FAIL,
            message=(f"{c.label_a} vs {c.label_b}: {c.volume:.0f} mm3 overlap"
                     f" — {suggestion}"),
            suggested_fix=suggestion,
            evidence={
                "label_a": c.label_a,
                "label_b": c.label_b,
                "volume_mm3": round(c.volume, 1),
                "center_a": list(c.center_a),
                "center_b": list(c.center_b),
                "bbox_a": list(c.bbox_a),
                "bbox_b": list(c.bbox_b),
                "overlap_dims_mm": [round(x, 3) for x in c.overlap_dims],
                "suggest_shift": {
                    "axis": c.suggest_axis,
                    "mm": round(c.suggest_shift_mm, 3),
                    "clearance_mm": c.clearance_mm,
                },
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


def _format_misorientation(m) -> str:
    """Compact CLI line: 'idler at (1496, 530, 421) thinnest=Y, expected=X (face YZ) — rotate 90° about Z'."""
    cx, cy, cz = m.center
    actual = _AXIS_NAMES[m.actual_axis] if m.actual_axis is not None else "ambiguous"
    expected = _AXIS_NAMES[m.expected_axis]
    head = (f"{m.label} at ({cx:.0f}, {cy:.0f}, {cz:.0f}) "
            f"thinnest={actual}, expected={expected} (face {m.expected_face})")
    if m.actual_axis is None:
        return head
    return f"{head} — {suggest_rotation(m.actual_axis, m.expected_axis)}"


def _color_findings(r: ColorResult) -> List[Finding]:
    out: List[Finding] = []
    for v in r.violations:
        out.append(Finding(
            id="cad.color_mismatch",
            category="color",
            severity=Severity.FAIL,
            message=(
                f"{v.label}: expected color {v.expected_hex}, "
                f"got {v.actual_hex} (Δ per channel {v.delta_per_channel}, "
                f"tolerance ±{v.tolerance_rgb})"
            ),
            suggested_fix=(
                f"Update the part's color attribute in the source CAD to "
                f"{v.expected_hex} (current {v.actual_hex}). If the current "
                f"color is intentional, raise color_tolerance_rgb on the "
                f"label's rule or remove expected_color."
            ),
            evidence={
                "label": v.label,
                "expected_hex": v.expected_hex,
                "actual_hex": v.actual_hex,
                "delta_rgb": list(v.delta_per_channel),
                "tolerance_rgb": v.tolerance_rgb,
            },
        ))
    for m in r.missing:
        out.append(Finding(
            id="cad.color_missing",
            category="color",
            severity=Severity.WARN,
            message=(
                f"{m.label}: expected_color {m.expected_hex} set in rules, "
                f"but the STEP carries no color attribute for this label"
            ),
            suggested_fix=(
                "Either author the part with a color in your CAD package, "
                "or remove expected_color from the label rule if uncolored "
                "is intentional."
            ),
            evidence={
                "label": m.label,
                "expected_hex": m.expected_hex,
            },
        ))
    return out


def _format_floating(f) -> str:
    """Compact CLI line: 'idler at (x,y,z) is 12mm from nearest cbeam'."""
    cx, cy, cz = f.center
    head = f"{f.label} at ({cx:.0f}, {cy:.0f}, {cz:.0f})"
    if f.nearest_label is None:
        return f"{head} — no structural part within reach"
    return (f"{head} is {f.nearest_distance_mm:.1f}mm from nearest "
            f"{f.nearest_label} (max gap allowed)")


def _floating_findings(r: FloatingResult) -> List[Finding]:
    out: List[Finding] = []
    for f in r.floating:
        if f.nearest_label is None:
            suggestion = ("Verify this part is intentionally placed; if so, "
                          "add its label to floating_check.exempt_labels. "
                          "Otherwise its host part is missing from the assembly.")
        else:
            suggestion = (
                f"Move toward nearest structural part ({f.nearest_label} at "
                f"{tuple(round(x, 1) for x in (f.nearest_center or (0,0,0)))}) "
                f"by {f.nearest_distance_mm:.1f}mm to anchor it; if this is "
                f"intentional, add to floating_check.exempt_labels."
            )
        out.append(Finding(
            id="cad.floating_part",
            category="floating",
            severity=Severity.FAIL,
            message=(
                f"{f.label} at ({f.center[0]:.0f}, {f.center[1]:.0f}, "
                f"{f.center[2]:.0f}) is {f.nearest_distance_mm:.1f}mm from "
                f"nearest structural part"
                + (f" ({f.nearest_label})" if f.nearest_label else "")
            ),
            suggested_fix=suggestion,
            evidence={
                "label": f.label,
                "center": list(f.center),
                "bbox": list(f.bbox),
                "nearest_label": f.nearest_label,
                "nearest_distance_mm": round(f.nearest_distance_mm, 3),
            },
        ))
    return out


def _orientation_findings(r: OrientationResult) -> List[Finding]:
    out: List[Finding] = []
    for m in r.violations:
        rotation = suggest_rotation(m.actual_axis, m.expected_axis)
        actual_name = _AXIS_NAMES[m.actual_axis]
        expected_name = _AXIS_NAMES[m.expected_axis]
        out.append(Finding(
            id="cad.misoriented",
            category="orientation",
            severity=Severity.FAIL,
            message=(
                f"{m.label}: thinnest axis is {actual_name}, expected "
                f"{expected_name} (face {m.expected_face}) — {rotation}"
            ),
            suggested_fix=rotation,
            evidence={
                "label": m.label,
                "center": list(m.center),
                "actual_dims_mm": [round(x, 3) for x in m.actual_dims],
                "actual_axis": m.actual_axis,
                "expected_face": m.expected_face,
                "expected_axis": m.expected_axis,
            },
        ))
    for m in r.ambiguous:
        out.append(Finding(
            id="cad.orientation_ambiguous",
            category="orientation",
            severity=Severity.WARN,
            message=(
                f"{m.label}: cannot verify orientation — two bbox dims "
                f"tied for thinnest ({m.actual_dims})"
            ),
            evidence={
                "label": m.label,
                "center": list(m.center),
                "actual_dims_mm": [round(x, 3) for x in m.actual_dims],
                "expected_face": m.expected_face,
            },
        ))
    return out


def _roundtrip_config_from_rules(rules):
    """Convert strict YAML models to the round-trip module's config."""
    from .roundtrip import (
        InterfacePair,
        PartSelector,
        RoundtripConfig,
        SourceTranslator,
    )

    model = rules.roundtrip_step

    def _selector(item):
        return PartSelector(
            label=item.label,
            near_mm=tuple(item.near_mm) if item.near_mm is not None else None,
            max_center_distance_mm=item.max_center_distance_mm,
        )

    return RoundtripConfig(
        source_translator=SourceTranslator(
            family=model.source_translator.family,
            name=model.source_translator.name,
            version=model.source_translator.version,
        ),
        authoring_reference_step_proxy=model.authoring_reference_step_proxy,
        interface_pairs=tuple(
            InterfacePair(
                id=pair.id,
                a=_selector(pair.a),
                b=_selector(pair.b),
                tolerance_mm=pair.tolerance_mm,
            )
            for pair in model.interface_pairs
        ),
        bbox_tolerance_mm=model.bbox_tolerance_mm,
        bbox_volume_relative_tolerance=model.bbox_volume_relative_tolerance,
        bbox_volume_absolute_tolerance_mm3=(
            model.bbox_volume_absolute_tolerance_mm3
        ),
        interface_gap_tolerance_mm=model.interface_gap_tolerance_mm,
    )


def run_configured_harness(
    rules_path: str = "cadclaw.yaml",
    *,
    repo_root: str = ".",
    only=None,
    skip=None,
) -> Report:
    """Run the versioned YAML-backed gate union and return one ``Report``.

    This is the canonical library entry point used by both the CLI and MCP.
    Gate selection is validated before any gate runs, and ``meta.gate_registry``
    contains exactly one terminal ledger row for every registered gate.
    Operational errors are redacted and fail closed without being represented
    as design failures established by the affected gate.
    """
    from .bom_audit import run_bom_audit
    from .claim_audit import run_claim_audit
    from .color_check import ColorCheck
    from .findings import ConfidenceBudget
    from .floating import FloatingCheck
    from .gate_registry import (
        GateLedgerEntry,
        GateStatus,
        HARNESS_GATE_REGISTRY,
    )
    from .inventory import InventoryCheck, Region
    from .orientation import OrientationCheck
    from .pmi import run_pmi_present
    from .publish_audit import run_publish_audit
    from .roundtrip import run_roundtrip_step
    from .rules import RulesConfigError, load_rules_safe

    started = time.time()
    rules_path = os.fspath(rules_path)
    repo_root = os.fspath(repo_root)
    selection = HARNESS_GATE_REGISTRY.resolve(only=only, skip=skip)
    try:
        rules = load_rules_safe(rules_path)
    except RulesConfigError as exc:
        report = Report(
            meta={
                "error": "rules_configuration_error",
                **exc.to_dict(),
                "gate_registry": {
                    "version": selection.registry_version,
                    "registered_gate_ids": list(HARNESS_GATE_REGISTRY.ids),
                    "selected_gate_ids": list(selection.selected_ids),
                    "requested_gate_ids": list(selection.selected_ids),
                    "only_gate_ids": (
                        list(selection.only_ids)
                        if selection.only_ids is not None else None
                    ),
                    "skip_gate_ids": list(selection.skip_ids),
                    "aggregate_status": "error",
                    "configuration_unavailable": True,
                    "gates": [],
                },
            },
            confidence_budget=ConfidenceBudget(
                not_checked=[
                    "harness gates could not be configured from the rule file"
                ]
            ),
        )
        report.add(Finding(
            id=exc.reason_code,
            category="harness",
            severity=Severity.FAIL,
            message="rule configuration could not be loaded",
            evidence={**exc.to_dict(), "status": "error"},
        ))
        report.overall = report.compute_overall()
        report.duration_ms = (time.time() - started) * 1000
        return report
    selected = set(selection.selected_ids)
    explicitly_skipped = set(selection.skip_ids)

    configured: Dict[str, bool] = {
        "inventory": bool(rules.expected_inventory) or any(
            region.expected for region in rules.regions
        ),
        "interference": "interference" in rules.model_fields_set,
        "bom_audit": bool(rules.bom_audit.rules),
        "claim_audit": bool(
            rules.claim_audit.scan_paths
            or rules.claim_audit.source_regex_rules
        ),
        "publish_audit": bool(
            rules.publish_audit.ignore_globs
            or rules.publish_audit.scan_globs
        ),
        "pmi_present": bool(rules.pmi_present.expected_classes),
        "roundtrip_step": bool(rules.roundtrip_step.enabled),
        "orientation": any(
            spec.expected_face for spec in rules.label_specs().values()
        ),
        "floating": bool(rules.floating_check.structural_labels),
        "color": any(
            spec.expected_color for spec in rules.label_specs().values()
        ),
    }

    entries: Dict[str, GateLedgerEntry] = {}
    for gate_id in HARNESS_GATE_REGISTRY.ids:
        entry = GateLedgerEntry(
            gate_id=gate_id,
            selected=gate_id in selected,
            configured=configured[gate_id],
        )
        if gate_id in explicitly_skipped:
            entry.status = GateStatus.SKIPPED
            entry.reason = "excluded by --skip"
        elif gate_id not in selected:
            entry.status = GateStatus.NOT_CHECKED
            entry.reason = "not selected by --only"
        entries[gate_id] = entry

    aggregate = Report(
        meta={
            "project": rules.meta.project or "",
            "rules": rules_path,
        },
        confidence_budget=ConfidenceBudget(
            checked=[],
            not_checked=list(rules.confidence_budget.not_checked),
            assumptions=list(rules.confidence_budget.assumptions),
        ),
    )

    def _finding_counts(findings: List[Finding]) -> Dict[str, int]:
        return {
            severity.value: sum(
                1 for finding in findings if finding.severity == severity
            )
            for severity in (Severity.PASS, Severity.WARN, Severity.FAIL)
        }

    def _status_from_findings(findings: List[Finding]):
        severities = {finding.severity for finding in findings}
        if Severity.FAIL in severities:
            return GateStatus.FAIL
        if Severity.WARN in severities:
            return GateStatus.WARN
        return GateStatus.PASS

    def _terminal(
        gate_id: str,
        status,
        *,
        reason: Optional[str] = None,
        findings: Optional[List[Finding]] = None,
    ) -> None:
        entry = entries[gate_id]
        entry.status = status
        entry.reason = reason
        if findings is not None:
            entry.finding_counts = _finding_counts(findings)
        if status in (GateStatus.PASS, GateStatus.WARN, GateStatus.FAIL):
            if gate_id not in aggregate.confidence_budget.checked:
                aggregate.confidence_budget.checked.append(gate_id)
        elif status in (GateStatus.ERROR, GateStatus.NOT_CHECKED):
            disclosure = f"{gate_id} ({reason or status.value})"
            if disclosure not in aggregate.confidence_budget.not_checked:
                aggregate.confidence_budget.not_checked.append(disclosure)

    def _extend_subreport(sub: Report) -> None:
        aggregate.findings.extend(sub.findings)
        # Gate identities, rather than gate-specific prose, are the canonical
        # checked set. Preserve the sub-report's assumptions and omissions.
        for item in sub.confidence_budget.not_checked:
            if item not in aggregate.confidence_budget.not_checked:
                aggregate.confidence_budget.not_checked.append(item)
        for item in sub.confidence_budget.assumptions:
            if item not in aggregate.confidence_budget.assumptions:
                aggregate.confidence_budget.assumptions.append(item)

    def _record_exception(gate_id: str, _exc: Exception) -> None:
        before = len(aggregate.findings)
        aggregate.add(Finding(
            id="harness.gate_execution_error",
            category=gate_id,
            severity=Severity.FAIL,
            message=f"{gate_id} could not complete",
            evidence={
                "gate_id": gate_id,
                "reason_code": "harness.gate_execution_failed",
                "status": "error",
            },
        ))
        _terminal(
            gate_id,
            GateStatus.ERROR,
            reason="gate execution error",
            findings=aggregate.findings[before:],
        )

    def _missing_prerequisite(gate_id: str, prerequisite: str) -> None:
        before = len(aggregate.findings)
        aggregate.add(Finding(
            id="harness.gate_prerequisite_missing",
            category=gate_id,
            severity=Severity.FAIL,
            message=(
                f"{gate_id} requires configured prerequisite {prerequisite}"
            ),
            evidence={
                "gate_id": gate_id,
                "prerequisite": prerequisite,
                "status": "error",
            },
        ))
        _terminal(
            gate_id,
            GateStatus.ERROR,
            reason=f"missing prerequisite: {prerequisite}",
            findings=aggregate.findings[before:],
        )

    def _execute(gate_id: str, callback) -> None:
        before = len(aggregate.findings)
        try:
            outcome = callback()
        except Exception as exc:
            _record_exception(gate_id, exc)
            return
        new_findings = aggregate.findings[before:]
        status = None
        reason = None
        if outcome is not None:
            status, reason = outcome
        if status is None:
            status = _status_from_findings(new_findings)
        if (
            status == GateStatus.ERROR
            and not any(
                finding.severity == Severity.FAIL for finding in new_findings
            )
        ):
            aggregate.add(Finding(
                id="harness.gate_execution_error",
                category=gate_id,
                severity=Severity.FAIL,
                message=f"{gate_id} could not complete every configured check",
                evidence={"gate_id": gate_id, "status": "error"},
            ))
            new_findings = aggregate.findings[before:]
        _terminal(
            gate_id,
            status,
            reason=reason,
            findings=new_findings,
        )

    label_specs = rules.label_specs()
    step_path = rules.meta.step
    loaded_parts = None
    label_fn = None

    def _load_geometry():
        nonlocal loaded_parts, label_fn
        if loaded_parts is not None:
            return loaded_parts, label_fn
        from .inventory import load_and_dedup, sig as part_signature

        signature_labels = rules.sig_to_label()
        belt_heuristic = rules.belt_heuristic

        def _label(part):
            dimensions = part_signature(part)
            if dimensions in signature_labels:
                return signature_labels[dimensions]
            if (
                belt_heuristic
                and len(dimensions) >= 2
                and dimensions[0] == 1.5
                and dimensions[1] == 6.0
            ):
                return "belt"
            return "other"

        loaded_parts = load_and_dedup(step_path)
        label_fn = _label
        return loaded_parts, label_fn

    for gate_id in selection.selected_ids:
        if not configured[gate_id]:
            if HARNESS_GATE_REGISTRY.allows_not_applicable(gate_id):
                if gate_id == "pmi_present":
                    sub = run_pmi_present(
                        step_path=step_path,
                        expected_classes=(),
                    )
                    _extend_subreport(sub)
                    aggregate.meta["pmi_present"] = {
                        key: value for key, value in sub.meta.items()
                        if key not in {"project", "rules"}
                    }
                elif gate_id == "roundtrip_step":
                    aggregate.meta["roundtrip_step"] = {
                        "gate": "ROUNDTRIP_STEP",
                        "applicability": "not_applicable",
                        "reason": (
                            "disabled; opt in with "
                            "roundtrip_step.enabled: true"
                        ),
                    }
                    aggregate.confidence_budget.not_checked.append(
                        "roundtrip_step (disabled; opt in with "
                        "roundtrip_step.enabled: true)"
                    )
                _terminal(
                    gate_id,
                    GateStatus.NOT_APPLICABLE,
                    reason="no applicable gate assertions configured",
                    findings=[],
                )
            else:
                _terminal(
                    gate_id,
                    GateStatus.NOT_CHECKED,
                    reason="gate assertions are not configured",
                    findings=[],
                )
            continue

        if gate_id == "inventory":
            if not step_path:
                _missing_prerequisite(gate_id, "rules.meta.step")
                continue

            def _inventory_gate():
                signature_labels = rules.sig_to_label()
                regions = [
                    Region(
                        name=region.name,
                        x_range=(
                            tuple(region.x_range) if region.x_range else None
                        ),
                        y_range=(
                            tuple(region.y_range) if region.y_range else None
                        ),
                        z_range=(
                            tuple(region.z_range) if region.z_range else None
                        ),
                        expected=dict(region.expected),
                    )
                    for region in rules.regions
                ] or None
                result = InventoryCheck(
                    step_path,
                    dict(signature_labels),
                    dict(rules.expected_inventory),
                    belt_heuristic=rules.belt_heuristic,
                    regions=regions,
                ).run()
                aggregate.findings.extend(_inventory_findings(result))

            _execute(gate_id, _inventory_gate)

        elif gate_id == "interference":
            if not step_path:
                _missing_prerequisite(gate_id, "rules.meta.step")
                continue

            def _interference_gate():
                parts, resolved_label_fn = _load_geometry()
                result = InterferenceCheck(
                    parts,
                    resolved_label_fn,
                    skip_labels=set(rules.interference.skip_labels),
                    min_volume=rules.interference.min_volume_mm3,
                    min_clearance_mm=rules.interference.min_clearance_mm,
                ).run()
                aggregate.findings.extend(_interference_findings(result))
                if result.error_count:
                    return GateStatus.ERROR, "one or more pair evaluations errored"
                if result.not_checked_reason:
                    return GateStatus.NOT_CHECKED, result.not_checked_reason
                return None

            _execute(gate_id, _interference_gate)

        elif gate_id == "bom_audit":
            if not rules.bom_audit.bom_path:
                _missing_prerequisite(gate_id, "bom_audit.bom_path")
                continue
            if not step_path:
                _missing_prerequisite(gate_id, "rules.meta.step")
                continue

            def _bom_gate():
                sub = run_bom_audit(
                    bom_path=rules.bom_audit.bom_path,
                    step_path=step_path,
                    rules=rules,
                )
                _extend_subreport(sub)

            _execute(gate_id, _bom_gate)

        elif gate_id == "claim_audit":
            def _claim_gate():
                sub = run_claim_audit(rules, repo_root=repo_root)
                _extend_subreport(sub)
                if any(
                    finding.id in {
                        "claim.bad_numeric_pattern",
                        "claim.bad_source_pattern",
                        "claim.no_scannable_claim_fields",
                        "claim.scan_error",
                    }
                    for finding in sub.findings
                ) or int(sub.meta.get("scan_error_count", 0)):
                    return GateStatus.ERROR, "configured claim scan errored"
                missing_lanes = []
                if (
                    rules.claim_audit.scan_paths
                    and int(sub.meta.get("files_scanned", 0)) == 0
                ):
                    missing_lanes.append("claim text paths")
                if (
                    rules.claim_audit.source_regex_rules
                    and int(sub.meta.get("source_files_scanned", 0)) == 0
                ):
                    missing_lanes.append("source-regex paths")
                if missing_lanes:
                    return (
                        GateStatus.NOT_CHECKED,
                        "no files scanned for: " + ", ".join(missing_lanes),
                    )
                return None

            _execute(gate_id, _claim_gate)

        elif gate_id == "publish_audit":
            def _publish_gate():
                sub = run_publish_audit(rules, repo_root=repo_root)
                _extend_subreport(sub)
                if any(
                    finding.id in {
                        "publish.bad_pattern",
                        "publish.git_classification_error",
                        "publish.scan_error",
                    }
                    for finding in sub.findings
                ) or int(sub.meta.get("n_content_scan_errors", 0)) or int(
                    sub.meta.get("n_git_classification_errors", 0)
                ) or sub.meta.get("execution_status") == "error":
                    return GateStatus.ERROR, "configured publish scan errored"
                classified = sum(
                    int(sub.meta.get(name, 0))
                    for name in ("n_tracked", "n_staged", "n_untracked")
                )
                if classified == 0:
                    return GateStatus.NOT_CHECKED, "no repository files were classified"
                if (
                    rules.publish_audit.scan_globs
                    and int(sub.meta.get("n_content_scan_files", 0)) == 0
                ):
                    return (
                        GateStatus.NOT_CHECKED,
                        "no files matched the configured content-scan lane",
                    )
                return None

            _execute(gate_id, _publish_gate)

        elif gate_id == "pmi_present":
            if not step_path:
                _missing_prerequisite(gate_id, "rules.meta.step")
                continue

            def _pmi_gate():
                sub = run_pmi_present(
                    step_path=step_path,
                    expected_classes=rules.pmi_present.expected_classes,
                )
                _extend_subreport(sub)
                aggregate.meta["pmi_present"] = {
                    key: value for key, value in sub.meta.items()
                    if key not in {"project", "rules"}
                }
                applicability = sub.meta.get("applicability")
                if applicability == "error":
                    return GateStatus.ERROR, "semantic PMI evaluation errored"
                if applicability == "not_applicable":
                    return GateStatus.NOT_APPLICABLE, "no applicable PMI assertions"
                return None

            _execute(gate_id, _pmi_gate)

        elif gate_id == "roundtrip_step":
            if not step_path:
                _missing_prerequisite(gate_id, "rules.meta.step")
                continue

            def _roundtrip_gate():
                sub = run_roundtrip_step(
                    step_path=step_path,
                    config=_roundtrip_config_from_rules(rules),
                    output_path=None,
                    label_signatures=rules.label_to_sig(),
                )
                _extend_subreport(sub)
                aggregate.meta["roundtrip_step"] = {
                    key: value for key, value in sub.meta.items()
                    if key not in {"project", "rules"}
                }
                if sub.meta.get("applicability") == "error":
                    return GateStatus.ERROR, "round-trip evaluation errored"
                return None

            _execute(gate_id, _roundtrip_gate)

        elif gate_id == "orientation":
            if not step_path:
                _missing_prerequisite(gate_id, "rules.meta.step")
                continue

            def _orientation_gate():
                parts, resolved_label_fn = _load_geometry()
                result = OrientationCheck(
                    parts,
                    resolved_label_fn,
                    label_specs,
                ).run()
                aggregate.findings.extend(_orientation_findings(result))
                if result.checked == 0:
                    return GateStatus.NOT_CHECKED, "no matching labeled parts"
                return None

            _execute(gate_id, _orientation_gate)

        elif gate_id == "floating":
            if not step_path:
                _missing_prerequisite(gate_id, "rules.meta.step")
                continue

            def _floating_gate():
                parts, resolved_label_fn = _load_geometry()
                result = FloatingCheck(
                    parts,
                    resolved_label_fn,
                    structural_labels=set(
                        rules.floating_check.structural_labels
                    ),
                    max_gap_mm=rules.floating_check.max_gap_mm,
                    exempt_labels=set(rules.floating_check.exempt_labels),
                ).run()
                aggregate.findings.extend(_floating_findings(result))
                if result.checked == 0:
                    return (
                        GateStatus.NOT_CHECKED,
                        "no eligible parts or structural anchors",
                    )
                return None

            _execute(gate_id, _floating_gate)

        elif gate_id == "color":
            if not step_path:
                _missing_prerequisite(gate_id, "rules.meta.step")
                continue

            def _color_gate():
                result = ColorCheck(step_path, label_specs).run()
                aggregate.findings.extend(_color_findings(result))
                if result.checked == 0:
                    return GateStatus.NOT_CHECKED, "no configured labels evaluated"
                return None

            _execute(gate_id, _color_gate)

    rows = [entries[gate_id] for gate_id in HARNESS_GATE_REGISTRY.ids]
    all_status_ids = {
        status.value: [
            entry.gate_id for entry in rows if entry.status == status
        ]
        for status in GateStatus
    }
    status_ids = {
        status.value: [
            entry.gate_id for entry in rows
            if entry.selected and entry.status == status
        ]
        for status in GateStatus
    }
    checked_gate_ids = [
        entry.gate_id for entry in rows
        if entry.status in (GateStatus.PASS, GateStatus.WARN, GateStatus.FAIL)
    ]
    selected_rows = [entry for entry in rows if entry.selected]
    all_selected_not_applicable = bool(selected_rows) and all(
        entry.status == GateStatus.NOT_APPLICABLE for entry in selected_rows
    )
    explicit_not_checked = [
        entry.gate_id for entry in selected_rows
        if entry.status == GateStatus.NOT_CHECKED
    ] if selection.only_ids is not None else []
    configured_not_checked = [
        entry.gate_id for entry in selected_rows
        if entry.configured and entry.status == GateStatus.NOT_CHECKED
    ]
    selected_not_checked = [
        entry.gate_id for entry in selected_rows
        if entry.status == GateStatus.NOT_CHECKED
    ]
    outside_selection = [
        entry.gate_id for entry in rows
        if not entry.selected and entry.status == GateStatus.NOT_CHECKED
    ]

    aggregate.meta["gate_registry"] = {
        "version": selection.registry_version,
        "registered_gate_ids": list(HARNESS_GATE_REGISTRY.ids),
        "selected_gate_ids": list(selection.selected_ids),
        # Retained for report consumers introduced by the initial hardening
        # draft; it is an alias of selected_gate_ids.
        "requested_gate_ids": list(selection.selected_ids),
        "only_gate_ids": (
            list(selection.only_ids) if selection.only_ids is not None else None
        ),
        "skip_gate_ids": list(selection.skip_ids),
        "configured_gate_ids": [
            gate_id for gate_id in HARNESS_GATE_REGISTRY.ids
            if configured[gate_id]
        ],
        "checked_gate_ids": checked_gate_ids,
        "executed_gate_ids": [
            entry.gate_id for entry in rows
            if entry.selected and entry.status in (
                GateStatus.PASS,
                GateStatus.WARN,
                GateStatus.FAIL,
                GateStatus.ERROR,
            )
        ],
        "not_applicable_gate_ids": status_ids["not_applicable"],
        "not_checked_gate_ids": selected_not_checked,
        "outside_selection_gate_ids": outside_selection,
        "skipped_gate_ids": list(selection.skip_ids),
        "configured_not_checked_gate_ids": configured_not_checked,
        "all_selected_not_applicable": all_selected_not_applicable,
        "status_gate_ids": status_ids,
        "all_status_gate_ids": all_status_ids,
        "gates": [entry.to_dict() for entry in rows],
    }

    if all_selected_not_applicable:
        aggregate.meta["applicability"] = "not_applicable"
    elif (
        len(selection.selected_ids) == 1
        and selection.selected_ids[0] in {"pmi_present", "roundtrip_step"}
    ):
        gate_id = selection.selected_ids[0]
        nested_applicability = aggregate.meta.get(gate_id, {}).get(
            "applicability"
        )
        if nested_applicability:
            aggregate.meta["applicability"] = nested_applicability

    if explicit_not_checked or configured_not_checked or (
        not checked_gate_ids and not all_selected_not_applicable
        and not status_ids["error"]
    ):
        finding_id = (
            "harness.requested_gate_not_checked"
            if explicit_not_checked
            else (
                "harness.configured_gate_not_checked"
                if configured_not_checked
                else "harness.no_checks_executed"
            )
        )
        aggregate.add(Finding(
            id=finding_id,
            category="harness",
            severity=Severity.FAIL,
            message=(
                "selected harness gates did not establish a check result"
            ),
            evidence={
                "selected_gate_ids": list(selection.selected_ids),
                "not_checked_gate_ids": explicit_not_checked,
                "configured_not_checked_gate_ids": configured_not_checked,
            },
        ))

    # Canonical checked-set parity: report prose from nested gates never adds
    # identities here, and registry order is stable.
    aggregate.confidence_budget.checked = checked_gate_ids
    aggregate.overall = aggregate.compute_overall()
    if status_ids["error"]:
        aggregate.meta["gate_registry"]["aggregate_status"] = "error"
        # Error reports must not disclose operator-selected config paths or
        # arbitrary project labels. Successful/evaluated reports retain them.
        aggregate.meta.pop("rules", None)
        aggregate.meta.pop("project", None)
    elif all_selected_not_applicable:
        aggregate.meta["gate_registry"]["aggregate_status"] = (
            "not_applicable"
        )
    else:
        aggregate.meta["gate_registry"]["aggregate_status"] = (
            aggregate.overall.value
        )
    aggregate.duration_ms = (time.time() - started) * 1000
    return aggregate
