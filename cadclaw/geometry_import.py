"""Reusable helpers for importing authored geometry from a reference STEP.

Motivating use case: when a CADQuery-driven assembly script needs a
complex authored part (e.g. a gusset with a custom polygon profile and
a dense bolt pattern), it is almost always better to **clone the real
shape from an authoritative STEP** than to re-author a parametric
approximation that silently loses detail on every regen.

Pattern:
    from cadclaw.geometry_import import shapes_by_dim_sig

    authored_gussets = shapes_by_dim_sig(
        "M3-2_Assembly.step",
        dim_sig=(4.0, 160.0, 280.0),
    )
    for g in authored_gussets:
        assy.add(cq.Workplane().add(g), color=GREEN)

Keeps the full polygon profile, hole grid, fillets, and any other
authored detail from the reference file. Avoids the "lost detail on
regen" failure mode that produces visibly-simpler parts in the output.
"""
from typing import List, Optional, Tuple

import cadquery as cq

from .inventory import sig as _dim_sig


def _bb_center_sig(shape, ndigits: int = 1) -> Tuple[float, float, float]:
    """Rounded (cx, cy, cz) tuple used to dedup same-shape-at-same-position."""
    bb = shape.BoundingBox()
    return (
        round((bb.xmin + bb.xmax) / 2.0, ndigits),
        round((bb.ymin + bb.ymax) / 2.0, ndigits),
        round((bb.zmin + bb.zmax) / 2.0, ndigits),
    )


def shapes_by_dim_sig(
    step_path: str,
    dim_sig: Tuple[float, float, float],
    dedup_by_center: bool = True,
) -> List[cq.Shape]:
    """Return all solids/shells in `step_path` whose dim-signature (sorted
    3-tuple of rounded extents) matches `dim_sig`.

    Many Fusion STEP exports contain each authored part twice (once in
    the flat compound, once in a hidden assembly tree). When
    `dedup_by_center=True` (default), shapes with the same rounded
    centroid are treated as duplicates and only the first is returned.

    Args:
        step_path: Path to the reference STEP.
        dim_sig: Sorted 3-tuple of rounded bbox extents (mm, 1-dp).
            Matches `cadclaw.inventory.sig`.
        dedup_by_center: Drop duplicates sharing the same centroid.

    Returns:
        List of `cq.Shape` instances. Empty list if the file doesn't
        exist or no shapes match.

    Raises:
        Never. File errors return [] and are silent (callers check len).
    """
    try:
        compound = cq.importers.importStep(step_path).val()
    except Exception:
        return []
    raw = list(compound.Solids()) + list(compound.Shells())

    out: List[cq.Shape] = []
    seen_centers = set()
    for s in raw:
        if _dim_sig(s) != dim_sig:
            continue
        if dedup_by_center:
            key = _bb_center_sig(s)
            if key in seen_centers:
                continue
            seen_centers.add(key)
        out.append(s)
    return out


def first_shape_by_dim_sig(
    step_path: str,
    dim_sig: Tuple[float, float, float],
) -> Optional[cq.Shape]:
    """Convenience: first shape matching the dim-signature, or None."""
    shapes = shapes_by_dim_sig(step_path, dim_sig)
    return shapes[0] if shapes else None


def clone_to_assembly(
    assy,
    shapes: List[cq.Shape],
    name_prefix: str,
    color=None,
    at_origin: bool = False,
):
    """Add each shape in `shapes` to a CADQuery Assembly, preserving the
    authored position unless `at_origin=True`.

    Complements `shapes_by_dim_sig`: one-liner for the common pattern
    "take authored parts from reference STEP, drop them into my assy."
    """
    from cadquery import Location, Workplane, Vector
    for i, s in enumerate(shapes):
        wp = Workplane().add(s)
        kwargs = {"name": f"{name_prefix}_{i}"}
        if color is not None:
            kwargs["color"] = color
        if at_origin:
            bb = s.BoundingBox()
            cx = (bb.xmin + bb.xmax) / 2.0
            cy = (bb.ymin + bb.ymax) / 2.0
            cz = (bb.zmin + bb.zmax) / 2.0
            kwargs["loc"] = Location(Vector(-cx, -cy, -cz))
        assy.add(wp, **kwargs)
