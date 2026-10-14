"""Guarded, opt-in OCP measurements for a pair of valid solids.

Inputs are CadQuery Shape wrappers already placed in the same millimetre frame.
This module does not import sources, heal geometry, screen by bounding boxes,
change assembly policies, or select an optional geometry backend. Numerical
thresholds classify the result; they are not certified error bounds.
"""
from __future__ import annotations

import math
from types import SimpleNamespace


def _load_ocp():
    """Keep OCP behind one lazy native import boundary."""
    import OCP
    from OCP.BRep import BRep_Tool
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.Precision import Precision
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_ON, TopAbs_VERTEX
    from OCP.TopTools import TopTools_ListOfShape

    return SimpleNamespace(
        Common=BRepAlgoAPI_Common,
        Properties=GProp_GProps,
        volume_properties=BRepGProp.VolumeProperties_s,
        Distance=BRepExtrema_DistShapeShape,
        Classifier=BRepClass3d_SolidClassifier,
        Analyzer=BRepCheck_Analyzer,
        ShapeList=TopTools_ListOfShape,
        ON=TopAbs_ON,
        max_tolerance=BRep_Tool.MaxTolerance_s,
        tolerance_types=(TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX),
        confusion=Precision.Confusion_s,
        version=str(OCP.__version__),
    )


def _point_coordinates(point) -> list[float]:
    values = [float(point.X()), float(point.Y()), float(point.Z())]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("invalid witness coordinates")
    return values


def query_solid_pair(
    shape_a,
    shape_b,
    *,
    linear_tolerance_mm: float = 1e-6,
    volume_tolerance_mm3: float = 1e-9,
) -> dict:
    """Measure one solid pair without modifying either operand.

    ``touching_within_tolerance`` requires completed zero-volume intersection,
    a distance within the linear threshold, and two boundary-classified nearest
    witnesses. It does not assert exact tangency. Positive intersection below
    the volume threshold, inconsistent evidence, and unconfirmed contact remain
    unresolved. Native execution failures return redacted codes and null metrics.

    Callers supply source/instance identities and enforce any process timeout;
    this synchronous primitive makes no cancellation or assembly-coverage claim.
    """
    result = {
        "schema": "cadclaw.solid_pair_query.v1",
        "execution_status": "failed",
        "relation": "unresolved",
        "minimum_distance_mm": None,
        "intersection_volume_mm3": None,
        "witnesses": None,
        "tolerances": {"linear_mm": None, "volume_mm3": None},
        "native_tolerance_floor_mm": None,
        "backend": {"name": "OCP", "version": None, "authoritative": True},
        "scope": "single_valid_solids_in_shared_mm_frame",
        "stage": "input",
        "error_code": None,
        "limitations": [
            "caller_must_supply_shared_mm_frame",
            "classification_thresholds_are_not_certified_accuracy_bounds",
            "single_valid_solids_only_no_healing",
            "static_pair_only_no_motion_or_physical_validation",
        ],
    }

    def stop(status: str, stage: str, code: str) -> dict:
        result.update(execution_status=status, relation="unresolved", stage=stage, error_code=code)
        if status != "completed":
            result.update(minimum_distance_mm=None, intersection_volume_mm3=None, witnesses=None)
        return result

    for key, value in (("linear_mm", linear_tolerance_mm), ("volume_mm3", volume_tolerance_mm3)):
        try:
            converted = float(value)
        except Exception:
            return stop("failed", "input", "invalid_tolerance")
        if isinstance(value, bool) or not math.isfinite(converted) or converted <= 0:
            return stop("failed", "input", "invalid_tolerance")
        result["tolerances"][key] = converted
    linear = result["tolerances"]["linear_mm"]
    volume_limit = result["tolerances"]["volume_mm3"]

    try:
        ocp = _load_ocp()
    except Exception:
        return stop("unavailable", "backend", "backend_unavailable")
    result["backend"]["version"] = ocp.version

    stage = "operand_validation"
    try:
        operand_volumes = []
        for shape in (shape_a, shape_b):
            if not all(hasattr(shape, name) for name in ("wrapped", "ShapeType", "isValid", "Volume", "copy")):
                return stop("unsupported", stage, "unsupported_operand_type")
            if shape.wrapped.IsNull():
                return stop("failed", stage, "null_operand")
            if shape.ShapeType() != "Solid":
                return stop("unsupported", stage, "unsupported_operand_type")
        # CadQuery's copy() duplicates topology and geometry. Even validation
        # and mass queries can populate native flags/caches, so isolate them as
        # well as the explicitly non-destructive Boolean from caller operands.
        stage = "operand_copy"
        shape_a, shape_b = shape_a.copy(), shape_b.copy()
        stage = "operand_validation"
        for shape in (shape_a, shape_b):
            if not shape.isValid():
                return stop("failed", stage, "invalid_operand")
            operand_volume = float(shape.Volume())
            if not math.isfinite(operand_volume) or operand_volume <= 0:
                return stop("failed", stage, "invalid_operand_volume")
            operand_volumes.append(operand_volume)

        stage = "operand_tolerance"
        native_tolerances = [float(ocp.confusion())]
        for shape in (shape_a, shape_b):
            native_tolerances.extend(float(ocp.max_tolerance(shape.wrapped, kind))
                                     for kind in ocp.tolerance_types)
        if any(not math.isfinite(value) or value < 0 for value in native_tolerances):
            return stop("failed", stage, "invalid_native_tolerance")
        native_floor = max(native_tolerances)
        result["native_tolerance_floor_mm"] = native_floor
        if linear < native_floor:
            return stop("unsupported", stage, "requested_tolerance_below_native_floor")

        # The convenience Common(a, b) constructor can build immediately. Set
        # protection and serial execution before Build using empty construction.
        stage = "common_setup"
        arguments, tools = ocp.ShapeList(), ocp.ShapeList()
        arguments.Append(shape_a.wrapped)
        tools.Append(shape_b.wrapped)
        common = ocp.Common()
        common.SetArguments(arguments)
        common.SetTools(tools)
        common.SetNonDestructive(True)
        common.SetRunParallel(False)
        stage = "common_build"
        common.Build()
        stage = "common_status"
        if not common.IsDone():
            return stop("failed", stage, "boolean_not_done")
        stage = "intersection_validation"
        intersection = common.Shape()
        if intersection.IsNull() or not ocp.Analyzer(intersection).IsValid():
            return stop("failed", stage, "invalid_intersection_result")
        stage = "intersection_volume"
        properties = ocp.Properties()
        ocp.volume_properties(intersection, properties)
        volume = float(properties.Mass())
        if not math.isfinite(volume) or volume < 0:
            return stop("failed", stage, "invalid_intersection_volume")

        stage = "distance_setup"
        distance = ocp.Distance()
        distance.SetMultiThread(False)
        distance.SetDeflection(linear)
        distance.LoadS1(shape_a.wrapped)
        distance.LoadS2(shape_b.wrapped)
        stage = "distance_perform"
        performed = distance.Perform()
        stage = "distance_status"
        if not performed or not distance.IsDone():
            return stop("failed", stage, "distance_not_done")
        if distance.NbSolution() < 1:
            return stop("failed", stage, "distance_no_solutions")
        stage = "distance_value"
        gap = float(distance.Value())
        if not math.isfinite(gap) or gap < 0:
            return stop("failed", stage, "invalid_distance")
        inner_solution = bool(distance.InnerSolution())
        result.update(minimum_distance_mm=gap, intersection_volume_mm3=volume)

        if (volume > min(operand_volumes) + volume_limit
                or (volume > volume_limit and gap > linear)
                or (inner_solution and volume == 0)):
            return stop("completed", "classification", "inconsistent_geometry_metrics")
        if 0 < volume <= volume_limit:
            return stop("completed", "classification", "intersection_volume_within_tolerance")
        if volume > volume_limit:
            result.update(execution_status="completed", relation="intersecting", stage="complete")
            return result

        stage = "distance_witnesses"
        point_a, point_b = distance.PointOnShape1(1), distance.PointOnShape2(1)
        coordinates_a, coordinates_b = _point_coordinates(point_a), _point_coordinates(point_b)
        witness_gap = math.dist(coordinates_a, coordinates_b)
        if not math.isfinite(witness_gap) or abs(witness_gap - gap) > linear:
            return stop("completed", "classification", "inconsistent_geometry_metrics")
        result["witnesses"] = {"point_a_mm": coordinates_a, "point_b_mm": coordinates_b}
        if gap > linear:
            result.update(execution_status="completed", relation="separated", stage="complete")
            return result

        stage = "contact_classification"
        for shape, point in ((shape_a, point_a), (shape_b, point_b)):
            classifier = ocp.Classifier(shape.wrapped)
            classifier.Perform(point, linear)
            if classifier.State() != ocp.ON:
                return stop("completed", "classification", "contact_not_confirmed")
        result.update(execution_status="completed", relation="touching_within_tolerance", stage="complete")
        return result
    except Exception:
        return stop("failed", stage, f"{stage}_failed")
