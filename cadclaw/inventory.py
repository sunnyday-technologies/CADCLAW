"""
Inventory Gate — validates part counts by bounding-box signature.

Every part in a STEP assembly has a unique bbox "fingerprint" (sorted
dimensions rounded to 0.1mm). This module labels parts by signature,
counts them, and compares against an expected inventory.

Per-region inventory (v0.6 extension): pass `regions=[Region(...), ...]` to
validate that spatially-localized sub-assemblies also contain the expected
parts. A part's centroid is tested against each region's axis-aligned
bounds; open bounds (None) are wildcards. Regions can overlap — a part
falling in two regions counts toward both.

Usage:
    from cadclaw.inventory import InventoryCheck, Region
    regions = [
        Region("x_carriage", z_range=(100.0, 250.0),
               expected={'wheel': 8, 'plate': 2}),
    ]
    check = InventoryCheck("assembly.step", labels={...},
                           expected={...}, regions=regions)
    result = check.run()
    assert result.passed
    # Per-region breakdown: result.region_results["x_carriage"].inventory
"""
import cadquery as cq
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Tuple, List, Optional

from .bbox import bbox_center, bbox_tuple


@dataclass
class Region:
    """An axis-aligned spatial region with a local expected inventory.

    Each `*_range` is `(lo, hi)` inclusive on both ends. `None` on any
    bound (or the whole range) leaves that axis unconstrained. A part is
    "in" the region iff its centroid lies within every specified range.

    `expected` is a label -> count map scoped to this region only (not
    the whole assembly). Labels not listed default to 0 expected.
    """
    name: str
    x_range: Optional[Tuple[float, float]] = None
    y_range: Optional[Tuple[float, float]] = None
    z_range: Optional[Tuple[float, float]] = None
    expected: Dict[str, int] = field(default_factory=dict)

    def contains(self, centroid: Tuple[float, float, float]) -> bool:
        """True iff centroid (cx, cy, cz) falls inside every specified range."""
        cx, cy, cz = centroid
        for val, rng in ((cx, self.x_range), (cy, self.y_range), (cz, self.z_range)):
            if rng is None:
                continue
            lo, hi = rng
            if lo is not None and val < lo:
                return False
            if hi is not None and val > hi:
                return False
        return True


@dataclass
class RegionResult:
    """Per-region inventory breakdown."""
    name: str
    passed: bool
    total_parts: int
    inventory: Dict[str, int]
    expected: Dict[str, int]
    mismatches: List[str]


@dataclass
class InventoryResult:
    """Result of an inventory check.

    `region_results` is keyed by region name and is populated only when
    `InventoryCheck` was constructed with `regions=[...]`. `passed` is
    the AND of the global check and every region check.
    """
    passed: bool
    total_parts: int
    inventory: Dict[str, int]
    expected: Dict[str, int]
    mismatches: List[str]
    region_results: Dict[str, RegionResult] = field(default_factory=dict)


def sig(solid) -> Tuple[float, ...]:
    """Compute the bbox signature of a solid: sorted (dx, dy, dz) rounded to 0.1mm."""
    xmin, ymin, zmin, xmax, ymax, zmax = bbox_tuple(solid)
    return tuple(sorted([
        round(xmax - xmin, 1),
        round(ymax - ymin, 1),
        round(zmax - zmin, 1),
    ]))


def center(solid) -> Tuple[float, float, float]:
    """Compute the bbox center of a solid."""
    return bbox_center(bbox_tuple(solid))


def load_and_dedup(step_path: str) -> list:
    """Load a STEP file and deduplicate by bbox key."""
    compound = cq.importers.importStep(step_path).val()
    raw = list(compound.Solids()) + list(compound.Shells())
    seen = set()
    parts = []
    for s in raw:
        bbox = bbox_tuple(s)
        k = tuple(round(value, 1) for value in bbox)
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
        regions: Optional list of `Region` defining local expected counts.
                 Each part's centroid is tested against every region; a
                 region check fails if its local count doesn't match. The
                 overall result.passed is False if any region fails.
    """

    def __init__(self, step_path: str, labels: Dict[Tuple, str],
                 expected: Dict[str, int], belt_heuristic: bool = True,
                 regions: Optional[List[Region]] = None):
        self.step_path = step_path
        self.labels = labels
        self.expected = expected
        self.belt_heuristic = belt_heuristic
        self.regions = list(regions) if regions else []

    def label_of(self, solid) -> str:
        d = sig(solid)
        if d in self.labels:
            return self.labels[d]
        if self.belt_heuristic and d[0] == 1.5 and len(d) >= 2 and d[1] == 6.0:
            return 'belt'
        return 'other'

    @staticmethod
    def _mismatches_for(inv: Dict[str, int], expected: Dict[str, int]) -> List[str]:
        mismatches = []
        for k in sorted(set(list(inv.keys()) + list(expected.keys()))):
            got = inv.get(k, 0)
            want = expected.get(k, 0)
            if got != want:
                mismatches.append(f"{k}: got {got}, expected {want}")
        return mismatches

    def _region_result(self, region: Region, parts: list) -> RegionResult:
        local = [s for s in parts if region.contains(center(s))]
        inv = Counter(self.label_of(s) for s in local)
        mismatches = self._mismatches_for(dict(inv), region.expected)
        return RegionResult(
            name=region.name,
            passed=len(mismatches) == 0,
            total_parts=len(local),
            inventory=dict(inv),
            expected=dict(region.expected),
            mismatches=mismatches,
        )

    def run(self, parts: Optional[list] = None) -> InventoryResult:
        """Run the inventory check. Optionally pass pre-loaded parts.

        When `regions` were provided at construction, returns per-region
        results in `result.region_results` and folds region failures into
        `result.passed`.
        """
        if parts is None:
            parts = load_and_dedup(self.step_path)

        inv = Counter(self.label_of(s) for s in parts)
        mismatches = self._mismatches_for(dict(inv), self.expected)

        region_results: Dict[str, RegionResult] = {}
        for region in self.regions:
            region_results[region.name] = self._region_result(region, parts)

        all_passed = (len(mismatches) == 0
                      and all(r.passed for r in region_results.values()))

        return InventoryResult(
            passed=all_passed,
            total_parts=len(parts),
            inventory=dict(inv),
            expected=self.expected,
            mismatches=mismatches,
            region_results=region_results,
        )
