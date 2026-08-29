"""Shared, fail-closed axis-aligned bounding-box validation.

Geometry gates must not interpret a malformed native bounding box as a valid
zero-width, touching, or non-overlapping part.  This module provides the one
typed boundary used by the registered inventory, interference, orientation,
and floating gates.
"""
from __future__ import annotations

import math
from typing import Tuple


BBox6 = Tuple[float, float, float, float, float, float]


class GeometryBoundingBoxError(RuntimeError):
    """A native shape did not provide a finite, ordered bounding box."""

    def __init__(self, code: str = "geometry.bbox_invalid"):
        self.code = code
        super().__init__("geometry bounding box could not be evaluated")


def validate_bbox(values) -> BBox6:
    """Return six finite floats with ``min <= max`` on every axis.

    The exception deliberately contains no native-reader text, shape
    representation, or submitted path.
    """
    try:
        bbox = tuple(float(value) for value in values)
    except Exception:
        raise GeometryBoundingBoxError() from None
    if len(bbox) != 6 or not all(math.isfinite(value) for value in bbox):
        raise GeometryBoundingBoxError() from None
    if any(bbox[index] > bbox[index + 3] for index in range(3)):
        raise GeometryBoundingBoxError() from None
    return bbox  # type: ignore[return-value]


def bbox_tuple(solid) -> BBox6:
    """Read and validate ``solid.BoundingBox()`` without leaking native text."""
    try:
        bbox = solid.BoundingBox()
        values = (
            bbox.xmin,
            bbox.ymin,
            bbox.zmin,
            bbox.xmax,
            bbox.ymax,
            bbox.zmax,
        )
    except Exception:
        raise GeometryBoundingBoxError("geometry.bbox_read_failed") from None
    return validate_bbox(values)


def bbox_center(bbox: BBox6) -> Tuple[float, float, float]:
    """Return the center of an already validated bounding box."""
    values = validate_bbox(bbox)
    return (
        (values[0] + values[3]) / 2.0,
        (values[1] + values[4]) / 2.0,
        (values[2] + values[5]) / 2.0,
    )
