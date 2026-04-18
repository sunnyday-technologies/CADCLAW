"""
Inventory Gate — validates part counts by bounding-box signature.

Every part in a STEP assembly has a unique bbox "fingerprint" (sorted
dimensions rounded to 0.1mm). This module labels parts by signature,
counts them, and compares against an expected inventory.

Usage:
    from cadharness.inventory import InventoryCheck
    check = InventoryCheck("assembly.step", labels={...}, expected={...})
    result = check.run()
    assert result.passed
"""
import cadquery as cq
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Tuple, List, Optional


@dataclass
class InventoryResult:
    """Result of an inventory check."""
    passed: bool
    total_parts: int
    inventory: Dict[str, int]
    expected: Dict[str, int]
    mismatches: List[str]


def sig(solid) -> Tuple[float, ...]:
    """Compute the bbox signature of a solid: sorted (dx, dy, dz) rounded to 0.1mm."""
    bb = solid.BoundingBox()
    return tuple(sorted([
        round(bb.xmax - bb.xmin, 1),
        round(bb.ymax - bb.ymin, 1),
        round(bb.zmax - bb.zmin, 1),
    ]))


def center(solid) -> Tuple[float, float, float]:
    """Compute the bbox center of a solid."""
    bb = solid.BoundingBox()
    return (
        (bb.xmin + bb.xmax) / 2.0,
        (bb.ymin + bb.ymax) / 2.0,
        (bb.zmin + bb.zmax) / 2.0,
    )


def load_and_dedup(step_path: str) -> list:
    """Load a STEP file and deduplicate by bbox key."""
    compound = cq.importers.importStep(step_path).val()
    raw = list(compound.Solids()) + list(compound.Shells())
    seen = set()
    parts = []
    for s in raw:
        bb = s.BoundingBox()
        k = (round(bb.xmin, 1), round(bb.ymin, 1), round(bb.zmin, 1),
             round(bb.xmax, 1), round(bb.ymax, 1), round(bb.zmax, 1))
        if k not in seen:
            seen.add(k)
            parts.append(s)
    return parts


class InventoryCheck:
    """
    Validate that an assembly contains the expected number of each part type.

    Args:
        step_path: Path to the STEP file to check.
        labels: Dict mapping bbox signature tuples to human-readable labels.
                Example: {(40.0, 80.0, 1000.0): 'cbeam', (56.4, 56.4, 76.6): 'motor'}
        expected: Dict mapping labels to expected counts.
                  Example: {'cbeam': 17, 'motor': 6}
        belt_heuristic: If True, parts with dims[0]==1.5 and dims[1]==6.0 are labeled 'belt'.
    """

    def __init__(self, step_path: str, labels: Dict[Tuple, str],
                 expected: Dict[str, int], belt_heuristic: bool = True):
        self.step_path = step_path
        self.labels = labels
        self.expected = expected
        self.belt_heuristic = belt_heuristic

    def label_of(self, solid) -> str:
        d = sig(solid)
        if d in self.labels:
            return self.labels[d]
        if self.belt_heuristic and d[0] == 1.5 and len(d) >= 2 and d[1] == 6.0:
            return 'belt'
        return 'other'

    def run(self, parts: Optional[list] = None) -> InventoryResult:
        """Run the inventory check. Optionally pass pre-loaded parts."""
        if parts is None:
            parts = load_and_dedup(self.step_path)

        inv = Counter(self.label_of(s) for s in parts)
        mismatches = []
        all_keys = sorted(set(list(inv.keys()) + list(self.expected.keys())))

        for k in all_keys:
            got = inv.get(k, 0)
            want = self.expected.get(k, 0)
            if got != want:
                mismatches.append(f"{k}: got {got}, expected {want}")

        return InventoryResult(
            passed=len(mismatches) == 0,
            total_parts=len(parts),
            inventory=dict(inv),
            expected=self.expected,
            mismatches=mismatches,
        )
