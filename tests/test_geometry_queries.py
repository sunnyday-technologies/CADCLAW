"""Independent solid-pair controls: frozen STEP imports and injected native failures.

No geometry authoring or healing runs here. Box dimensions are documented in
examples/relative_placement/README.md and make_parts.py; the existing M3 spacer
is the user-approved authored derivative documented in m3_reference_assembly.yaml.
"""
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from cadclaw import geometry_queries as queries


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "plate": ("examples/relative_placement/parts/plate.step", "0318632ddd9fb62a2539837f968088a53166b454bd86b6aed38a0f43f2923aa8"),
    "rail_x": ("examples/relative_placement/parts/rail_x.step", "4af47e3e191776f83402bdb02d250e3edb2e11e26bbddea6a971803312ef5117"),
    "rail_y": ("examples/relative_placement/parts/rail_y.step", "102dc8c91c4eefdd169a6f3d63c2dd34a54c4d5ae0094e6576fb5d4821e457b4"),
    "spacer": ("examples/m3_crete/generated/ZPMM_6p1_motor_mount_spacer_6mm_holes.step", "ddf443baec7ddc42f7f22dc817f6c023538b7bc522930eb6a669f342282b0943"),
}


@pytest.fixture(scope="module")
def authored_solids():
    cq = pytest.importorskip("cadquery")
    solids = {}
    for name, (relative, digest) in SOURCES.items():
        path = ROOT / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        imported = cq.importers.importStep(str(path)).solids().vals()
        assert len(imported) == 1
        assert imported[0].isValid()
        solids[name] = imported[0]
    yield solids
    for relative, digest in SOURCES.values():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


def _fingerprint(shape):
    data = BytesIO()
    assert shape.exportBrep(data)
    return hashlib.sha256(data.getvalue()).hexdigest()


def _native_query(a, b, **kwargs):
    before = (_fingerprint(a), _fingerprint(b))
    result = queries.query_solid_pair(a, b, **kwargs)
    assert (_fingerprint(a), _fingerprint(b)) == before
    # Strict JSON serialization rejects nonfinite metrics, tolerances and witnesses.
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    assert result["schema"] == "cadclaw.solid_pair_query.v1"
    assert result["scope"] == "single_valid_solids_in_shared_mm_frame"
    assert result["backend"]["name"] == "OCP"
    assert result["backend"]["authoritative"] is True
    assert isinstance(result["backend"]["version"], str) and result["backend"]["version"]
    assert result["limitations"]
    return result


def _resolved(result, relation):
    assert result["execution_status"] == "completed", result
    assert result["relation"] == relation, result
    assert result["stage"] == "complete"
    assert result["error_code"] is None


def test_frozen_box_dimensions_match_documented_controls(authored_solids):
    for name, dimensions in {"plate": (10, 120, 120), "rail_x": (600, 40, 40), "rail_y": (40, 400, 40)}.items():
        box = authored_solids[name].BoundingBox()
        assert (box.xlen, box.ylen, box.zlen) == pytest.approx(dimensions, abs=1e-7)
        assert authored_solids[name].Volume() == pytest.approx(math.prod(dimensions), rel=1e-9)


@pytest.mark.parametrize("shift,gap", [((12, 0, 0), 2), ((12, 123, 0), math.sqrt(13)), ((12, 123, 124), math.sqrt(29))])
def test_authored_separation_has_exact_distance_and_consistent_witnesses(authored_solids, shift, gap):
    plate = authored_solids["plate"]
    result = _native_query(plate, plate.translate(shift))
    _resolved(result, "separated")
    assert result["intersection_volume_mm3"] == pytest.approx(0, abs=1e-10)
    assert result["minimum_distance_mm"] == pytest.approx(gap, abs=1e-7)
    witnesses = result["witnesses"]
    assert math.dist(witnesses["point_a_mm"], witnesses["point_b_mm"]) == pytest.approx(gap, abs=1e-7)


@pytest.mark.parametrize("shift", [(10, 0, 0), (10, 120, 0), (10, 120, 120)], ids=["face", "edge", "vertex"])
def test_authored_boundary_contact_is_not_positive_volume(authored_solids, shift):
    plate = authored_solids["plate"]
    result = _native_query(plate, plate.translate(shift))
    _resolved(result, "touching_within_tolerance")
    assert result["intersection_volume_mm3"] == pytest.approx(0, abs=1e-10)
    assert result["minimum_distance_mm"] <= result["tolerances"]["linear_mm"]
    assert result["witnesses"] is not None



@pytest.mark.parametrize("gap,tolerance,relation", [
    (5e-7, 1e-6, "touching_within_tolerance"),
    (2e-6, 1e-6, "separated"),
    (1e-4, 1e-3, "touching_within_tolerance"),
    (1e-4, 1e-5, "separated"),
])
def test_positive_gap_relation_depends_on_declared_tolerance(authored_solids, gap, tolerance, relation):
    plate = authored_solids["plate"]
    result = _native_query(plate, plate.translate((10 + gap, 0, 0)), linear_tolerance_mm=tolerance)
    _resolved(result, relation)
    assert result["intersection_volume_mm3"] == pytest.approx(0, abs=1e-10)
    assert result["minimum_distance_mm"] > 0  # Within tolerance does not assert exact tangency.
    assert result["minimum_distance_mm"] == pytest.approx(gap, abs=1e-9)


def test_native_authored_solid_rejects_precision_below_its_floor(authored_solids):
    plate = authored_solids["plate"]
    result = _native_query(plate, plate.translate((12, 0, 0)), linear_tolerance_mm=1e-12)
    _assert_safe_failure(result, "requested_tolerance_below_native_floor", status="unsupported")
    assert result["native_tolerance_floor_mm"] > result["tolerances"]["linear_mm"]

def test_thin_sub_reporting_threshold_overlap_is_still_intersecting(authored_solids):
    # 0.1 mm penetration and 0.1 mm3 overlap: below both legacy screening/report scales.
    plate = authored_solids["plate"]
    result = _native_query(plate, plate.translate((9.9, 119, 119)))
    _resolved(result, "intersecting")
    assert result["intersection_volume_mm3"] == pytest.approx(0.1, abs=1e-7)
    assert result["minimum_distance_mm"] <= 1e-6


def test_positive_volume_within_requested_volume_tolerance_stays_unresolved(authored_solids):
    plate = authored_solids["plate"]
    result = _native_query(plate, plate.translate((9.9, 119, 119)), volume_tolerance_mm3=0.2)
    assert result["execution_status"] == "completed"
    assert result["relation"] == "unresolved"
    assert result["error_code"] == "intersection_volume_within_tolerance"
    assert result["intersection_volume_mm3"] == pytest.approx(0.1, abs=1e-7)


def test_coincident_copies_preserve_operands_and_report_full_volume(authored_solids):
    plate = authored_solids["plate"]
    result = _native_query(plate, plate.copy())
    _resolved(result, "intersecting")
    assert result["intersection_volume_mm3"] == pytest.approx(144000, rel=1e-9)
    assert result["minimum_distance_mm"] <= 1e-6


def test_contained_rail_with_shared_boundary_reports_inner_volume(authored_solids):
    outer = authored_solids["rail_x"]
    inner = authored_solids["rail_y"].rotate((0, 0, 0), (0, 0, 1), -90).translate((100, 40, 0))
    result = _native_query(outer, inner)
    _resolved(result, "intersecting")
    assert result["intersection_volume_mm3"] == pytest.approx(640000, rel=1e-9)


def test_strictly_contained_existing_spacer_uses_solid_not_surface_distance(authored_solids):
    # Existing frozen STEP only: rigid rotation places its 6.1 mm thickness along X.
    outer = authored_solids["plate"]
    inner = authored_solids["spacer"].rotate((0, 0, 0), (0, 1, 0), 90).translate((5, 60, 60))
    a, b = outer.BoundingBox(), inner.BoundingBox()
    assert all(getattr(a, axis + "min") < getattr(b, axis + "min") < getattr(b, axis + "max") < getattr(a, axis + "max")
               for axis in "xyz")
    result = _native_query(outer, inner)
    _resolved(result, "intersecting")
    assert result["minimum_distance_mm"] <= 1e-6
    assert result["intersection_volume_mm3"] == pytest.approx(inner.Volume(), rel=1e-7)


def test_pair_measurements_survive_shared_rigid_transform_and_operand_swap(authored_solids):
    plate = authored_solids["plate"]
    a = plate.rotate((0, 0, 0), (0, 0, 1), 37).translate((100, -50, 25))
    b = plate.translate((12, 0, 0)).rotate((0, 0, 0), (0, 0, 1), 37).translate((100, -50, 25))
    for first, second in ((a, b), (b, a)):
        result = _native_query(first, second)
        _resolved(result, "separated")
        assert result["minimum_distance_mm"] == pytest.approx(2, abs=1e-7)
        assert result["intersection_volume_mm3"] == pytest.approx(0, abs=1e-10)
        witness = result["witnesses"]
        assert math.dist(witness["point_a_mm"], witness["point_b_mm"]) == pytest.approx(2, abs=1e-7)


def test_face_and_multi_solid_compound_are_explicitly_unsupported(authored_solids):
    cq = pytest.importorskip("cadquery")
    plate = authored_solids["plate"]
    compound = cq.Compound.makeCompound([plate, plate.translate((12, 0, 0))])
    for unsupported in (plate.Faces()[0], compound):
        result = _native_query(unsupported, plate)
        assert result["execution_status"] == "unsupported"
        assert result["relation"] == "unresolved"
        assert result["error_code"] == "unsupported_operand_type"
        assert result["minimum_distance_mm"] is None and result["intersection_volume_mm3"] is None


class _Operand:
    def __init__(self, *, kind="Solid", valid=True, volume=1, null=False):
        self.wrapped = SimpleNamespace(IsNull=lambda: null)
        self.kind, self.valid, self.volume = kind, valid, volume

    def copy(self):
        return _Operand(kind=self.kind, valid=self.valid, volume=self.volume, null=self.wrapped.IsNull())

    def ShapeType(self):
        return self.kind

    def isValid(self):
        return self.valid

    def Volume(self):
        return self.volume


def _fake_backend(**settings):
    log = []
    def value(key, default):
        result = settings.get(key, default)
        if isinstance(result, Exception):
            raise result
        return result
    class ShapeList(list):
        def Append(self, shape):
            self.append(shape)
    class Common:
        def __init__(self):
            value("common_setup", None)
        def SetArguments(self, shapes):
            pass
        def SetTools(self, shapes):
            pass
        def SetNonDestructive(self, enabled):
            log.append(("non_destructive", enabled))
        def SetRunParallel(self, enabled):
            log.append(("boolean_parallel", enabled))
        def Build(self):
            log.append(("build", None))
            value("common_build", None)
        def IsDone(self):
            return value("common_done", True)
        def Shape(self):
            return SimpleNamespace(IsNull=lambda: value("common_null", False))
    class Properties:
        def Mass(self):
            return value("volume", 0.0)
    def point(x):
        return SimpleNamespace(X=lambda: x, Y=lambda: 0.0, Z=lambda: 0.0)
    class Distance:
        def SetMultiThread(self, enabled):
            log.append(("distance_parallel", enabled))
        def SetDeflection(self, tolerance):
            pass
        def LoadS1(self, shape):
            pass
        def LoadS2(self, shape):
            pass
        def Perform(self):
            log.append(("distance_perform", None))
            return value("performed", True)
        def IsDone(self):
            return value("distance_done", True)
        def NbSolution(self):
            return value("solutions", 1)
        def Value(self):
            return value("distance", 2.0)
        def InnerSolution(self):
            return value("inner", False)
        def PointOnShape1(self, index):
            return point(value("point_a", 0.0))
        def PointOnShape2(self, index):
            return point(value("point_b", settings.get("distance", 2.0)))
    class Classifier:
        def __init__(self, shape):
            pass
        def Perform(self, point, tolerance):
            value("classify", None)
        def State(self):
            return value("boundary_state", "ON")
    backend = SimpleNamespace(Common=Common, Properties=Properties,
        volume_properties=lambda shape, properties: None, Distance=Distance,
        Classifier=Classifier, ShapeList=ShapeList, ON="ON", version="fake-unit-only",
        Analyzer=lambda shape: SimpleNamespace(IsValid=lambda: value("common_valid", True)),
        max_tolerance=lambda shape, kind: value("native_tolerance", 1e-7),
        tolerance_types=("FACE", "EDGE", "VERTEX"), confusion=lambda: 1e-7)
    return backend, log


def _install_fake(monkeypatch, **settings):
    backend, log = _fake_backend(**settings)
    monkeypatch.setattr(queries, "_load_ocp", lambda: backend)
    return log


def _assert_safe_failure(result, code, *, status="failed"):
    assert result["execution_status"] == status
    assert result["relation"] == "unresolved"
    assert result["error_code"] == code
    assert result["minimum_distance_mm"] is None
    assert result["intersection_volume_mm3"] is None
    assert result["witnesses"] is None
    raw = json.dumps(result, allow_nan=False)
    assert "DO_NOT_LOG_NATIVE_EXCEPTION" not in raw


@pytest.mark.parametrize("kwargs", [
    {"linear_tolerance_mm": item} for item in (0, -1, math.nan, math.inf, True, "not-a-number")
] + [{"volume_tolerance_mm3": item} for item in (0, -1, math.nan, math.inf, True, None)])
def test_invalid_tolerances_never_reach_native_backend(monkeypatch, kwargs):
    def unexpected_backend():
        pytest.fail("invalid input must not call the native backend")
    monkeypatch.setattr(queries, "_load_ocp", unexpected_backend)
    _assert_safe_failure(queries.query_solid_pair(_Operand(), _Operand(), **kwargs), "invalid_tolerance")


@pytest.mark.parametrize("operand,code,status", [
    (object(), "unsupported_operand_type", "unsupported"),
    (_Operand(kind="Compound"), "unsupported_operand_type", "unsupported"),
    (_Operand(null=True), "null_operand", "failed"),
    (_Operand(valid=False), "invalid_operand", "failed"),
    *[(_Operand(volume=v), "invalid_operand_volume", "failed") for v in (0, -1, math.nan, math.inf)],
])
def test_invalid_or_unsupported_operands_do_not_execute_boolean(monkeypatch, operand, code, status):
    log = _install_fake(monkeypatch)
    result = queries.query_solid_pair(operand, _Operand())
    _assert_safe_failure(result, code, status=status)
    assert not log


def test_missing_backend_returns_unavailable_without_exception_text(monkeypatch):
    def missing():
        raise ImportError("DO_NOT_LOG_NATIVE_EXCEPTION")
    monkeypatch.setattr(queries, "_load_ocp", missing)
    _assert_safe_failure(queries.query_solid_pair(_Operand(), _Operand()), "backend_unavailable", status="unavailable")


@pytest.mark.parametrize("settings,code", [
    ({"common_setup": RuntimeError("DO_NOT_LOG_NATIVE_EXCEPTION")}, "common_setup_failed"),
    ({"common_build": RuntimeError("DO_NOT_LOG_NATIVE_EXCEPTION")}, "common_build_failed"),
    ({"common_done": False}, "boolean_not_done"),
    ({"common_done": RuntimeError("DO_NOT_LOG_NATIVE_EXCEPTION")}, "common_status_failed"),
    ({"common_null": True}, "invalid_intersection_result"),
    ({"common_valid": False}, "invalid_intersection_result"),
    *[({"volume": v}, "invalid_intersection_volume") for v in (math.nan, math.inf, -1)],
    ({"performed": False}, "distance_not_done"),
    ({"distance_done": False}, "distance_not_done"),
    ({"solutions": 0}, "distance_no_solutions"),
    *[({"distance": v}, "invalid_distance") for v in (math.nan, math.inf, -1)],
    ({"point_a": math.nan}, "distance_witnesses_failed"),
    ({"distance": 0.0, "classify": RuntimeError("DO_NOT_LOG_NATIVE_EXCEPTION")}, "contact_classification_failed"),
    ({"native_tolerance": math.nan}, "invalid_native_tolerance"),
    ({"native_tolerance": RuntimeError("DO_NOT_LOG_NATIVE_EXCEPTION")}, "operand_tolerance_failed"),
])
def test_native_failure_or_nonfinite_result_never_becomes_clearance(monkeypatch, settings, code):
    _install_fake(monkeypatch, **settings)
    _assert_safe_failure(queries.query_solid_pair(_Operand(), _Operand()), code)


def test_native_setup_protects_operands_and_disables_parallel_work_before_execution(monkeypatch):
    log = _install_fake(monkeypatch)
    result = queries.query_solid_pair(_Operand(), _Operand())
    _resolved(result, "separated")
    assert log.index(("non_destructive", True)) < log.index(("build", None))
    assert log.index(("boolean_parallel", False)) < log.index(("build", None))
    assert log.index(("distance_parallel", False)) < log.index(("distance_perform", None))


def test_requested_linear_precision_below_native_floor_is_not_qualified(monkeypatch):
    log = _install_fake(monkeypatch, native_tolerance=2e-5)
    result = queries.query_solid_pair(_Operand(), _Operand())
    _assert_safe_failure(result, "requested_tolerance_below_native_floor", status="unsupported")
    assert result["native_tolerance_floor_mm"] == 2e-5
    assert not log


@pytest.mark.parametrize("settings,code", [
    ({"volume": 1.0, "distance": 2.0}, "inconsistent_geometry_metrics"),
    ({"volume": 2.0, "distance": 0.0}, "inconsistent_geometry_metrics"),
    ({"volume": 0.0, "inner": True}, "inconsistent_geometry_metrics"),
    ({"distance": 2.0, "point_b": 3.0}, "inconsistent_geometry_metrics"),
    ({"distance": 0.0, "boundary_state": "IN"}, "contact_not_confirmed"),
    ({"volume": 1e-10, "distance": 0.0}, "intersection_volume_within_tolerance"),
])
def test_completed_but_unconfirmed_metrics_stay_unresolved(monkeypatch, settings, code):
    _install_fake(monkeypatch, **settings)
    result = queries.query_solid_pair(_Operand(), _Operand())
    assert result["execution_status"] == "completed"
    assert result["relation"] == "unresolved"
    assert result["error_code"] == code
    json.dumps(result, allow_nan=False)


def test_unexpected_tolerance_conversion_exception_is_redacted(monkeypatch):
    class BadFloat:
        def __float__(self):
            raise RuntimeError("DO_NOT_LOG_NATIVE_EXCEPTION")
    def unexpected_backend():
        pytest.fail("invalid input must not call the native backend")
    monkeypatch.setattr(queries, "_load_ocp", unexpected_backend)
    _assert_safe_failure(queries.query_solid_pair(_Operand(), _Operand(), linear_tolerance_mm=BadFloat()), "invalid_tolerance")


def test_kernel_confusion_floor_applies_even_with_zero_entity_tolerances(monkeypatch):
    log = _install_fake(monkeypatch, native_tolerance=0)
    result = queries.query_solid_pair(_Operand(), _Operand(), linear_tolerance_mm=1e-8)
    _assert_safe_failure(result, "requested_tolerance_below_native_floor", status="unsupported")
    assert result["native_tolerance_floor_mm"] == 1e-7
    assert not log


def test_operand_copy_exception_is_redacted_before_any_boolean(monkeypatch):
    log = _install_fake(monkeypatch)
    class UncopyableOperand(_Operand):
        def copy(self):
            raise RuntimeError("DO_NOT_LOG_NATIVE_EXCEPTION")
    result = queries.query_solid_pair(UncopyableOperand(), _Operand())
    _assert_safe_failure(result, "operand_copy_failed")
    assert not log
