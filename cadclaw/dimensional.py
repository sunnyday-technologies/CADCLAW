"""
Dimensional Gate — validates part dimensions against expected ranges.

Catches geometry errors like wrong thickness, swapped box() args, or
parts that are impossibly large/small.

Usage:
    from cadclaw.dimensional import DimensionalCheck, DimRule
    rules = [DimRule('plate', thin_axis=5.0, tolerance=0.5)]
    check = DimensionalCheck(parts, label_fn, rules)
    result = check.run()
"""
from dataclasses import dataclass
from typing import List, Callable, Optional


@dataclass
class DimRule:
    """Validates dimensional properties of a part type.

    Args:
        label: Part type label to check.
        thin_axis: Expected smallest dimension (mm). None to skip.
        thin_tol: Tolerance on thin axis (mm).
        thick_axes: Expected two larger dimensions as (min, max) tuple. None to skip.
        thick_tol: Tolerance on thick axes.
    """
    label: str
    thin_axis: Optional[float] = None
    thin_tol: float = 0.5
    thick_axes: Optional[tuple] = None
    thick_tol: float = 2.0


@dataclass
class DimViolation:
    label: str
    center: tuple
    actual_dims: tuple
    rule: DimRule
    message: str


@dataclass
class DimensionalResult:
    passed: bool
    violations: List[DimViolation]


def _center(s):
    bb = s.BoundingBox()
    return ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2)


class DimensionalCheck:
    def __init__(self, parts: list, label_fn: Callable, rules: List[DimRule]):
        self.parts = parts
        self.label_fn = label_fn
        self.rules = {r.label: r for r in rules}

    def run(self) -> DimensionalResult:
        violations = []

        for s in self.parts:
            lbl = self.label_fn(s)
            if lbl not in self.rules:
                continue
            rule = self.rules[lbl]
            bb = s.BoundingBox()
            dims = sorted([bb.xmax - bb.xmin, bb.ymax - bb.ymin, bb.zmax - bb.zmin])

            if rule.thin_axis is not None:
                if abs(dims[0] - rule.thin_axis) > rule.thin_tol:
                    violations.append(DimViolation(
                        label=lbl, center=_center(s),
                        actual_dims=tuple(dims), rule=rule,
                        message=f"thin axis {dims[0]:.1f}mm, expected {rule.thin_axis}+/-{rule.thin_tol}mm"
                    ))

            if rule.thick_axes is not None:
                for i, (lo, hi) in enumerate(rule.thick_axes):
                    if dims[i + 1] < lo - rule.thick_tol or dims[i + 1] > hi + rule.thick_tol:
                        violations.append(DimViolation(
                            label=lbl, center=_center(s),
                            actual_dims=tuple(dims), rule=rule,
                            message=f"axis {i+1} = {dims[i+1]:.1f}mm, expected [{lo}, {hi}]+/-{rule.thick_tol}mm"
                        ))

        return DimensionalResult(
            passed=len(violations) == 0,
            violations=violations,
        )
