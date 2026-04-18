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


@dataclass
class GateResult:
    name: str
    passed: bool
    details: str
    duration_ms: float


@dataclass
class HarnessReport:
    passed: bool
    total_parts: int
    gates: List[GateResult]
    duration_ms: float

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

        for name, config in self._gates:
            gt = time.time()

            if name == 'inventory':
                check = config
                r = check.run(parts=parts)
                passed = r.passed
                details = '\n'.join(r.mismatches) if r.mismatches else ''

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

            elif name == 'adjacency':
                check = AdjacencyCheck(parts, label_fn, config)
                r = check.run()
                passed = r.passed
                details = '\n'.join(
                    f"{v.source_label} at ({v.source_center[0]:.0f},"
                    f"{v.source_center[1]:.0f},{v.source_center[2]:.0f}) "
                    f"nearest {v.nearest_target_label} = {v.nearest_distance:.0f}mm"
                    for v in r.violations) if r.violations else ''

            elif name == 'dimensional':
                check = DimensionalCheck(parts, label_fn, config)
                r = check.run()
                passed = r.passed
                details = '\n'.join(v.message for v in r.violations) if r.violations else ''

            else:
                continue

            results.append(GateResult(
                name=name, passed=passed, details=details,
                duration_ms=(time.time() - gt) * 1000))

        all_passed = all(r.passed for r in results)
        return HarnessReport(
            passed=all_passed,
            total_parts=len(parts),
            gates=results,
            duration_ms=(time.time() - t0) * 1000,
        )
