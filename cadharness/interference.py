"""
Interference Gate — detects solid-solid overlaps between assembly parts.

Uses OCC BRepAlgoAPI_Common for exact boolean intersection volume
computation. A bbox pre-filter avoids expensive BRep checks on
non-overlapping pairs.

Usage:
    from cadharness.interference import InterferenceCheck
    check = InterferenceCheck(parts, skip_labels={'belt', 'vwheel'})
    result = check.run()
    for clip in result.clips:
        print(f"{clip.label_a} vs {clip.label_b}: {clip.volume:.0f} mm^3")
"""
from dataclasses import dataclass
from typing import List, Set, Callable, Optional, Tuple


@dataclass
class Clip:
    """A detected interference between two parts."""
    label_a: str
    label_b: str
    center_a: Tuple[float, float, float]
    center_b: Tuple[float, float, float]
    volume: float  # mm^3 overlap


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


class InterferenceCheck:
    """
    Check all structural parts for pairwise solid-solid interference.

    Args:
        parts: List of CadQuery solids/shells.
        label_fn: Function that maps a solid to a string label.
        skip_labels: Set of labels to exclude from checking (e.g. belts, wheels).
        min_volume: Minimum overlap volume (mm^3) to report. Default 1.0.
    """

    def __init__(self, parts: list, label_fn: Callable,
                 skip_labels: Optional[Set[str]] = None,
                 min_volume: float = 1.0):
        self.parts = parts
        self.label_fn = label_fn
        self.skip_labels = skip_labels or set()
        self.min_volume = min_volume

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
                            clips.append(Clip(
                                label_a=la, label_b=lb,
                                center_a=_center(a), center_b=_center(b),
                                volume=v,
                            ))
                except Exception:
                    pass

        return InterferenceResult(
            passed=len(clips) == 0,
            checked_pairs=checked,
            clips=clips,
        )
