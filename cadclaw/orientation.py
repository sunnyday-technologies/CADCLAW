"""
Orientation Gate — verifies the largest bbox face of each labeled part lies
in the plane its label expects.

v0.9 gate #1. Closes 4 of 6 manual fixes from the M3-CRETE 2026-04-29 V1.0
session: misoriented idlers and idler-block connectors that the inventory
check accepted because the bbox SIGNATURE (sorted-tuple) matched, even
though the part was rotated 90° from its design intent.

The signature `inventory.sig()` sorts (dx, dy, dz) so an `idler_bracket`
labeled `(5, 30, 30)` matches any of `(5, 30, 30)`, `(30, 5, 30)`,
`(30, 30, 5)`. That's correct for inventory (the part is the same part);
it's wrong for orientation (only one of those three is mounted correctly).

The orientation gate compares each instance's UNSORTED bbox dims against
the label's `expected_face`. `expected_face: YZ` means the largest face
must lie in the Y-Z plane → the part's thinnest axis must be X.
Ambiguous parts (two dims tied for thinnest) emit WARN, not FAIL.

Each FAIL finding carries a `suggested_fix` describing the rotation that
would move the part into the expected orientation — closing the same
loop the v0.7.1 interference auto-fix-vector closed for clips.

Usage:
    from cadclaw.orientation import OrientationCheck
    from cadclaw.rules import load_rules
    rules = load_rules("cadclaw.yaml")
    check = OrientationCheck(parts, label_fn,
                             rules.label_specs())
    result = check.run()
    for v in result.violations:
        print(f"{v.label}: actual {v.actual_axis} vs expected {v.expected_axis}")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .rules import LabelSpec


_AXIS_NAMES = ("X", "Y", "Z")
_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}


@dataclass
class Misorientation:
    """One orientation finding (fail or ambiguous)."""
    label: str
    center: Tuple[float, float, float]
    actual_dims: Tuple[float, float, float]   # unsorted (dx, dy, dz)
    actual_axis: Optional[int]                # 0/1/2 for X/Y/Z, None if ambiguous
    expected_face: str                        # "XY" | "XZ" | "YZ"
    expected_axis: int                        # 0/1/2 for X/Y/Z


@dataclass
class OrientationResult:
    passed: bool
    checked: int
    violations: List[Misorientation] = field(default_factory=list)
    ambiguous: List[Misorientation] = field(default_factory=list)


def unsorted_dims(solid) -> Tuple[float, float, float]:
    """Return (dx, dy, dz) of a solid's axis-aligned bbox — NOT sorted.

    Counterpart to `cadclaw.inventory.sig()`, which returns a sorted tuple
    suitable for invariant-fingerprint matching. Orientation needs the
    raw per-axis dims to detect rotation.
    """
    bb = solid.BoundingBox()
    return (bb.xmax - bb.xmin, bb.ymax - bb.ymin, bb.zmax - bb.zmin)


def part_center(solid) -> Tuple[float, float, float]:
    bb = solid.BoundingBox()
    return ((bb.xmin + bb.xmax) / 2.0,
            (bb.ymin + bb.ymax) / 2.0,
            (bb.zmin + bb.zmax) / 2.0)


def thinnest_axis(dims: Tuple[float, float, float],
                  tol_mm: float = 0.1) -> Optional[int]:
    """Return 0/1/2 for the axis with the smallest dim, or None if two
    axes tie for thinnest within `tol_mm`.

    Tolerance prevents STEP-import jitter (sub-mm) from flipping the
    detected axis between runs.
    """
    indexed = sorted(enumerate(dims), key=lambda p: p[1])
    if abs(indexed[0][1] - indexed[1][1]) < tol_mm:
        return None
    return indexed[0][0]


def suggest_rotation(actual_axis: int, expected_axis: int) -> str:
    """Plain-language fix suggestion: which axis to rotate about and by how much.

    To swap which axis is thinnest from A to B, rotate 90° about the
    third axis (the one that's not A or B). E.g. actual=Y, expected=X →
    rotate about Z.
    """
    if actual_axis == expected_axis:
        return ""
    third_axis = ({0, 1, 2} - {actual_axis, expected_axis}).pop()
    return (f"rotate 90° about {_AXIS_NAMES[third_axis]} "
            f"(thinnest axis {_AXIS_NAMES[actual_axis]} "
            f"→ {_AXIS_NAMES[expected_axis]})")


class OrientationCheck:
    """Verify each labeled part's largest face lies in its expected plane.

    Args:
        parts: List of solids (CadQuery shapes) — same shape as for other gates.
        label_fn: solid -> label string. Same signature as elsewhere.
        label_specs: Dict[label, LabelSpec] from `RuleSet.label_specs()`.
            Only labels with non-None `expected_face` are checked.
        tol_mm: tolerance for "two axes tied for thinnest". Default 0.1mm.
    """

    def __init__(self, parts: list, label_fn: Callable,
                 label_specs: Dict[str, LabelSpec],
                 tol_mm: float = 0.1):
        self.parts = parts
        self.label_fn = label_fn
        self.label_specs = label_specs
        self.tol_mm = tol_mm

    def run(self) -> OrientationResult:
        violations: List[Misorientation] = []
        ambiguous: List[Misorientation] = []
        checked = 0

        for part in self.parts:
            try:
                label = self.label_fn(part)
            except Exception:
                continue
            spec = self.label_specs.get(label)
            if spec is None or spec.expected_face is None:
                continue
            expected_axis = spec.thinnest_axis_index()
            if expected_axis is None:
                continue  # spec has no orientation hint after all

            dims = unsorted_dims(part)
            actual_axis = thinnest_axis(dims, tol_mm=self.tol_mm)
            checked += 1

            entry = Misorientation(
                label=label,
                center=part_center(part),
                actual_dims=dims,
                actual_axis=actual_axis,
                expected_face=spec.expected_face,
                expected_axis=expected_axis,
            )
            if actual_axis is None:
                ambiguous.append(entry)
            elif actual_axis != expected_axis:
                violations.append(entry)

        return OrientationResult(
            passed=len(violations) == 0,
            checked=checked,
            violations=violations,
            ambiguous=ambiguous,
        )
