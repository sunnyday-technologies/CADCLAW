"""
Interference Gate — detects solid-solid overlaps between assembly parts.

Uses OCC BRepAlgoAPI_Common for exact boolean intersection volume
computation. A bbox pre-filter avoids expensive BRep checks on
non-overlapping pairs.

When a clip is detected, the bbox-overlap dimensions also yield a
suggested fix vector — the smallest-overlap axis is the cheapest to
clear, and the sign of the center-to-center vector tells which way to
push part A. Output looks like:

    plate at (1495, 540, 366) clips cbeam by 264 mm^3
      shift +Y by 1.35mm to clear with 1mm clearance

Usage:
    from cadclaw.interference import InterferenceCheck
    check = InterferenceCheck(parts, label_fn,
                              skip_labels={'belt'},
                              min_clearance_mm=1.0)
    result = check.run()
    for clip in result.clips:
        print(f"{clip.label_a} vs {clip.label_b}: {clip.volume:.0f} mm^3")
        print(f"  shift {clip.suggest_axis} by {clip.suggest_shift_mm}mm")
"""
from dataclasses import dataclass, field
from typing import List, Set, Callable, Optional, Tuple

from .bbox import (
    GeometryBoundingBoxError,
    bbox_center as _validated_bbox_center,
    bbox_tuple as _validated_bbox_tuple,
)


BBox = Tuple[float, float, float, float, float, float]  # (xmin,ymin,zmin,xmax,ymax,zmax)


class InterferenceExecutionError(RuntimeError):
    """Exact interference evidence could not be established."""

    def __init__(self, code: str, message: str, *, error_count: int = 0):
        super().__init__(message)
        self.code = code
        self.error_count = error_count


@dataclass
class Clip:
    """A detected interference between two parts.

    The `suggest_*` fields encode the minimum translation needed to
    push part A clear of part B with the configured clearance — picked
    along the bbox axis with the smallest overlap (cheapest fix).
    """
    label_a: str
    label_b: str
    center_a: Tuple[float, float, float]
    center_b: Tuple[float, float, float]
    volume: float                       # mm^3 overlap
    bbox_a: BBox = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    bbox_b: BBox = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    overlap_dims: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # (dx, dy, dz)
    suggest_axis: str = "x"             # "x" | "y" | "z"
    suggest_shift_mm: float = 0.0       # signed; +/- along suggest_axis to push A clear
    clearance_mm: float = 1.0


@dataclass
class InterferenceResult:
    passed: bool
    checked_pairs: int
    clips: List[Clip]
    error_count: int = 0
    eligible_parts: int = 0
    not_checked_reason: Optional[str] = None


def _bb_overlap(a, b, tol=-0.5):
    return _bb_overlap_bounds(_bbox_tuple(a), _bbox_tuple(b), tol=tol)


def _bb_overlap_bounds(a: BBox, b: BBox, tol=-0.5):
    return (a[0] < b[3] + tol and b[0] < a[3] + tol and
            a[1] < b[4] + tol and b[1] < a[4] + tol and
            a[2] < b[5] + tol and b[2] < a[5] + tol)


def _center(s):
    return _validated_bbox_center(_bbox_tuple(s))


def _bbox_tuple(s) -> BBox:
    return _validated_bbox_tuple(s)


def _suggest_clear_shift(bb_a: BBox, bb_b: BBox,
                         clearance_mm: float) -> Tuple[str, float, Tuple[float, float, float]]:
    """Pick the cheapest axis to push A clear of B.

    Returns (axis, signed_shift_mm, overlap_dims). The shift magnitude
    is the minimum interval translation that separates A from B with
    the requested clearance. For edge overlaps this equals
    `overlap_on_axis + clearance_mm`; for containment/nested overlaps
    it is larger, because the contained interval has to move all the way
    past one side of the containing interval.
    """
    ax_min, ay_min, az_min, ax_max, ay_max, az_max = bb_a
    bx_min, by_min, bz_min, bx_max, by_max, bz_max = bb_b

    ox = max(0.0, min(ax_max, bx_max) - max(ax_min, bx_min))
    oy = max(0.0, min(ay_max, by_max) - max(ay_min, by_min))
    oz = max(0.0, min(az_max, bz_max) - max(az_min, bz_min))

    def _axis_shift(a_min: float, a_max: float,
                    b_min: float, b_max: float) -> float:
        move_negative = b_min - clearance_mm - a_max
        move_positive = b_max + clearance_mm - a_min
        if abs(move_negative) < abs(move_positive):
            return move_negative
        if abs(move_positive) < abs(move_negative):
            return move_positive
        center_a = (a_min + a_max) / 2.0
        center_b = (b_min + b_max) / 2.0
        return move_positive if center_a >= center_b else move_negative

    candidates = [
        ("x", _axis_shift(ax_min, ax_max, bx_min, bx_max)),
        ("y", _axis_shift(ay_min, ay_max, by_min, by_max)),
        ("z", _axis_shift(az_min, az_max, bz_min, bz_max)),
    ]
    candidates.sort(key=lambda p: abs(p[1]))
    axis, shift = candidates[0]

    return axis, shift, (ox, oy, oz)


class InterferenceCheck:
    """
    Check all structural parts for pairwise solid-solid interference.

    Args:
        parts: List of CadQuery solids/shells.
        label_fn: Function that maps a solid to a string label.
        skip_labels: Set of labels to exclude from checking (e.g. belts, wheels).
        min_volume: Minimum overlap volume (mm^3) to report. Default 1.0.
        min_clearance_mm: Clearance added to the suggested fix shift so
            the moved part lands clear of the other rather than tangent.
            Default 1.0.
    """

    def __init__(self, parts: list, label_fn: Callable,
                 skip_labels: Optional[Set[str]] = None,
                 min_volume: float = 1.0,
                 min_clearance_mm: float = 1.0):
        self.parts = parts
        self.label_fn = label_fn
        self.skip_labels = skip_labels or set()
        self.min_volume = min_volume
        self.min_clearance_mm = min_clearance_mm

    def run(self) -> InterferenceResult:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp

        clips = []
        checked = 0
        error_count = 0
        check_parts = []

        # Resolve each label once.  A model-supplied or project label function
        # can fail just like an OCCT call; that is an execution error, never
        # evidence that the omitted part is clear.
        for i, solid in enumerate(self.parts):
            try:
                label = self.label_fn(solid)
            except GeometryBoundingBoxError:
                raise
            except Exception:
                error_count += 1
                continue
            if label not in self.skip_labels:
                # Validate every eligible part before pair filtering.  A
                # malformed box must not become "fewer than two parts" or a
                # false non-overlap result.
                check_parts.append((i, solid, label, _bbox_tuple(solid)))

        not_checked_reason = None
        if len(check_parts) < 2:
            not_checked_reason = "fewer than two eligible parts"

        for idx_a in range(len(check_parts)):
            i, a, la, bba = check_parts[idx_a]
            for idx_b in range(idx_a + 1, len(check_parts)):
                j, b, lb, bbb = check_parts[idx_b]
                try:
                    if not _bb_overlap_bounds(bba, bbb):
                        continue
                    checked += 1
                    common = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
                    common.Build()
                    if common.IsDone():
                        gp = GProp_GProps()
                        BRepGProp.VolumeProperties_s(common.Shape(), gp)
                        v = gp.Mass()
                        if v > self.min_volume:
                            axis, shift, overlap = _suggest_clear_shift(
                                bba, bbb, self.min_clearance_mm)
                            clips.append(Clip(
                                label_a=la, label_b=lb,
                                center_a=_validated_bbox_center(bba),
                                center_b=_validated_bbox_center(bbb),
                                volume=v,
                                bbox_a=bba, bbox_b=bbb,
                                overlap_dims=overlap,
                                suggest_axis=axis,
                                suggest_shift_mm=shift,
                                clearance_mm=self.min_clearance_mm,
                            ))
                    else:
                        error_count += 1
                except Exception:
                    # Native boolean failures are not evidence that the pair
                    # is clear.  Keep exception text out of the public result,
                    # but fail the gate so callers cannot publish a false PASS.
                    error_count += 1

        return InterferenceResult(
            passed=(
                len(clips) == 0
                and error_count == 0
                and not_checked_reason is None
            ),
            checked_pairs=checked,
            clips=clips,
            error_count=error_count,
            eligible_parts=len(check_parts),
            not_checked_reason=not_checked_reason,
        )
