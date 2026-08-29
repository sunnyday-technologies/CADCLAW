"""
Floating-part Gate — flag parts that aren't adjacent to any structural part.

v0.9 gate #3. Closes the M3-CRETE V1.0 manual fix #2 ("removed an idler +
idler block floating in the center"). Inventory + interference checks
both passed for the floating idler — its bbox signature was correct and
it wasn't clipping anything — but it was disconnected from the assembly.

The check is direct adjacency: for each candidate part, find the minimum
3D bbox-to-bbox distance to any STRUCTURAL part (label in
`structural_labels`). If that distance > `max_gap_mm`, the candidate is
unmoored — flag as `cad.floating_part`.

"Structural" is intentionally project-specific. M3-CRETE uses
`[cbeam, plate, idler_brk]`; another project might use `[frame_rail,
baseplate]`. The gate runs only when `structural_labels` is non-empty
(empty by default — opt-in).

`exempt_labels` skips parts that are designed to float (belts hang
between pulleys; that's correct geometry). Default exempts `belt`.

Usage:
    from cadclaw.floating import FloatingCheck
    check = FloatingCheck(parts, label_fn,
                          structural_labels={"cbeam", "plate"},
                          max_gap_mm=5.0,
                          exempt_labels={"belt"})
    result = check.run()
    for f in result.floating:
        print(f"{f.label} at {f.center} — nearest {f.nearest_label} "
              f"is {f.nearest_distance_mm:.1f}mm away")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set, Tuple

from .bbox import bbox_center as _validated_bbox_center
from .bbox import bbox_tuple as _validated_bbox_tuple
from .bbox import validate_bbox


BBox6 = Tuple[float, float, float, float, float, float]
Point3 = Tuple[float, float, float]


@dataclass
class FloatingPart:
    """One floating-part finding."""
    label: str
    center: Point3
    bbox: BBox6
    nearest_label: Optional[str]
    nearest_center: Optional[Point3]
    nearest_distance_mm: float


@dataclass
class FloatingResult:
    passed: bool
    checked: int
    floating: List[FloatingPart] = field(default_factory=list)


def _bbox_tuple(solid) -> BBox6:
    return _validated_bbox_tuple(solid)


def _bbox_center(bbox: BBox6) -> Point3:
    return _validated_bbox_center(bbox)


def bbox_distance(a: BBox6, b: BBox6) -> float:
    """Minimum 3D distance between two axis-aligned bboxes.

    Zero if the bboxes overlap. For non-overlapping bboxes, this is the
    Euclidean distance from the corner of A nearest B to the corresponding
    corner of B (i.e., the minimum gap).

    Math: per axis, the gap is `max(0, max(a.min - b.max, b.min - a.max))`.
    The 3D distance is the L2-norm of those three axis gaps.
    """
    a = validate_bbox(a)
    b = validate_bbox(b)
    dx = max(0.0, max(a[0] - b[3], b[0] - a[3]))
    dy = max(0.0, max(a[1] - b[4], b[1] - a[4]))
    dz = max(0.0, max(a[2] - b[5], b[2] - a[5]))
    return (dx * dx + dy * dy + dz * dz) ** 0.5


class FloatingCheck:
    """Verify each non-exempt part is adjacent to at least one structural part.

    Args:
        parts: List of solids.
        label_fn: solid -> label.
        structural_labels: set of labels that count as anchors. The check
            runs only when this set is non-empty (empty list disables).
        max_gap_mm: a candidate must be within this distance of some
            structural part's bbox to count as "attached." Default 5.0.
        exempt_labels: labels skipped entirely (genuinely floating, e.g.
            belts hanging between pulleys). Default: `{"belt"}`.
    """

    def __init__(self, parts: list, label_fn: Callable,
                 structural_labels: Set[str],
                 max_gap_mm: float = 5.0,
                 exempt_labels: Optional[Set[str]] = None):
        self.parts = parts
        self.label_fn = label_fn
        self.structural_labels = set(structural_labels)
        self.max_gap_mm = max_gap_mm
        self.exempt_labels = set(exempt_labels) if exempt_labels else {"belt"}

    def run(self) -> FloatingResult:
        if not self.structural_labels:
            return FloatingResult(passed=True, checked=0, floating=[])

        # Pre-compute bboxes + labels once.
        records = []
        for part in self.parts:
            # Do not silently omit an unlabelable part.  A caller can redact
            # and classify the raised exception, while omission would make a
            # partial adjacency evaluation indistinguishable from a pass.
            lbl = self.label_fn(part)
            records.append((lbl, _bbox_tuple(part)))

        structural = [(lbl, bb) for lbl, bb in records
                      if lbl in self.structural_labels]
        if not structural:
            # No structural parts at all → nothing to anchor against.
            # Conservative: treat as a setup error, not a failure of every
            # part. Return passed but checked=0; the harness wires it as a
            # confidence_budget note rather than a failure.
            return FloatingResult(passed=True, checked=0, floating=[])

        floating: List[FloatingPart] = []
        checked = 0

        for lbl, bb in records:
            if lbl in self.exempt_labels:
                continue
            if lbl in self.structural_labels:
                # Structural parts are anchors, not candidates.
                # Catastrophically misplaced structural parts are caught
                # by inventory + interference; the floating gate is
                # scoped to "secondary parts must touch structural."
                continue
            checked += 1
            # Find the minimum bbox distance to any structural part.
            best_dist = float("inf")
            best_lbl = None
            best_bb = None
            for s_lbl, s_bb in structural:
                d = bbox_distance(bb, s_bb)
                if d < best_dist:
                    best_dist = d
                    best_lbl = s_lbl
                    best_bb = s_bb
                    if best_dist == 0.0:
                        break  # touching — can't beat that
            if best_dist > self.max_gap_mm:
                floating.append(FloatingPart(
                    label=lbl,
                    center=_bbox_center(bb),
                    bbox=bb,
                    nearest_label=best_lbl,
                    nearest_center=_bbox_center(best_bb) if best_bb else None,
                    nearest_distance_mm=best_dist if best_dist != float("inf") else -1.0,
                ))

        return FloatingResult(
            passed=len(floating) == 0,
            checked=checked,
            floating=floating,
        )
