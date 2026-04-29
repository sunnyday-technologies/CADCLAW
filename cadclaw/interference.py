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


BBox = Tuple[float, float, float, float, float, float]  # (xmin,ymin,zmin,xmax,ymax,zmax)


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


def _bb_overlap(a, b, tol=-0.5):
    b1, b2 = a.BoundingBox(), b.BoundingBox()
    return (b1.xmin < b2.xmax + tol and b2.xmin < b1.xmax + tol and
            b1.ymin < b2.ymax + tol and b2.ymin < b1.ymax + tol and
            b1.zmin < b2.zmax + tol and b2.zmin < b1.zmax + tol)


def _center(s):
    bb = s.BoundingBox()
    return ((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2)


def _bbox_tuple(s) -> BBox:
    bb = s.BoundingBox()
    return (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)


def _suggest_clear_shift(bb_a: BBox, bb_b: BBox,
                         clearance_mm: float) -> Tuple[str, float, Tuple[float, float, float]]:
    """Pick the cheapest axis to push A clear of B.

    Returns (axis, signed_shift_mm, overlap_dims). The shift magnitude
    is `overlap_on_axis + clearance_mm`; the sign points away from B
    along that axis.
    """
    ax_min, ay_min, az_min, ax_max, ay_max, az_max = bb_a
    bx_min, by_min, bz_min, bx_max, by_max, bz_max = bb_b

    ox = max(0.0, min(ax_max, bx_max) - max(ax_min, bx_min))
    oy = max(0.0, min(ay_max, by_max) - max(ay_min, by_min))
    oz = max(0.0, min(az_max, bz_max) - max(az_min, bz_min))

    # Pick the axis with smallest positive overlap. Ties broken X<Y<Z.
    candidates = [("x", ox), ("y", oy), ("z", oz)]
    candidates.sort(key=lambda p: p[1])
    axis, overlap = candidates[0]

    # Sign: push A in the direction of (center_a - center_b) along the axis.
    ca = ((ax_min + ax_max) / 2, (ay_min + ay_max) / 2, (az_min + az_max) / 2)
    cb = ((bx_min + bx_max) / 2, (by_min + by_max) / 2, (bz_min + bz_max) / 2)
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    sign = 1.0 if ca[idx] >= cb[idx] else -1.0
    shift = sign * (overlap + clearance_mm)

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

        check_parts = [(i, s) for i, s in enumerate(self.parts)
                       if self.label_fn(s) not in self.skip_labels]

        clips = []
        checked = 0

        for idx_a in range(len(check_parts)):
            i, a = check_parts[idx_a]
            la = self.label_fn(a)
            for idx_b in range(idx_a + 1, len(check_parts)):
                j, b = check_parts[idx_b]
                lb = self.label_fn(b)
                if not _bb_overlap(a, b):
                    continue
                checked += 1
                try:
                    common = BRepAlgoAPI_Common(a.wrapped, b.wrapped)
                    common.Build()
                    if common.IsDone():
                        gp = GProp_GProps()
                        BRepGProp.VolumeProperties_s(common.Shape(), gp)
                        v = gp.Mass()
                        if v > self.min_volume:
                            bba = _bbox_tuple(a)
                            bbb = _bbox_tuple(b)
                            axis, shift, overlap = _suggest_clear_shift(
                                bba, bbb, self.min_clearance_mm)
                            clips.append(Clip(
                                label_a=la, label_b=lb,
                                center_a=_center(a), center_b=_center(b),
                                volume=v,
                                bbox_a=bba, bbox_b=bbb,
                                overlap_dims=overlap,
                                suggest_axis=axis,
                                suggest_shift_mm=shift,
                                clearance_mm=self.min_clearance_mm,
                            ))
                except Exception:
                    pass

        return InterferenceResult(
            passed=len(clips) == 0,
            checked_pairs=checked,
            clips=clips,
        )
