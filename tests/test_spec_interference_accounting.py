"""Intersection completion/coverage contracts using fake native responses only."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cadclaw import assembly_compiler as compiler
from cadclaw.assembly_spec import AssemblySpec
from cadclaw.findings import ConfidenceBudget, Report, Severity


def _spec(count=2, config=None):
    return AssemblySpec.model_validate({
        "meta": {"project": "Accounting", "assembly_id": "accounting"},
        "outputs": {"step": "out.step", "views_dir": "views"},
        "instances": [{"id": f"part_{i}", "role": "authored", "source_path": "fixture.step"}
                      for i in range(count)],
        "validation": {"run_checks": ["interference"], "interference": config or {}},
    })


def _setup(monkeypatch, spec, outcomes=None, bounds=None, missing=()):
    outcomes = outcomes or {}
    calls = []
    native_error = "private native diagnostic must not escape"

    class Props:
        value = 0.0
        fail_mass = False

        def Mass(self):
            if self.fail_mass:
                raise RuntimeError(native_error)
            return self.value

    class Common:
        def __init__(self, a, b):
            self.outcome = outcomes.get((a, b), 0.0)
            calls.append((a, b))
            if self.outcome == "constructor":
                raise RuntimeError(native_error)

        def Build(self):
            if self.outcome == "build":
                raise RuntimeError(native_error)

        def IsDone(self):
            if self.outcome == "is_done":
                raise RuntimeError(native_error)
            return self.outcome != "not_done"

        def Shape(self):
            if self.outcome == "shape":
                raise RuntimeError(native_error)
            return self.outcome

    def volume_properties(outcome, props):
        if outcome == "volume":
            raise RuntimeError(native_error)
        props.fail_mass = outcome == "mass"
        props.value = outcome

    monkeypatch.setitem(sys.modules, "OCP.BRepAlgoAPI", SimpleNamespace(BRepAlgoAPI_Common=Common))
    monkeypatch.setitem(sys.modules, "OCP.BRepGProp", SimpleNamespace(
        BRepGProp=SimpleNamespace(VolumeProperties_s=volume_properties)))
    monkeypatch.setitem(sys.modules, "OCP.GProp", SimpleNamespace(GProp_GProps=Props))
    records = []
    for instance in spec.instances:
        if instance.id in missing:
            continue
        box = (bounds or {}).get(instance.id, (0, 0, 0, 10, 10, 10))
        bb = SimpleNamespace(**dict(zip(("xmin", "ymin", "zmin", "xmax", "ymax", "zmax"), box)))
        shape = SimpleNamespace(wrapped=instance.id, BoundingBox=lambda bb=bb: bb)
        records.append(compiler.PlacedInstanceShape(instance.id, instance.role, "fixture.step", shape))

    def placed(*args, instance_ids=None, **kwargs):
        return ([record for record in records if instance_ids is None or record.id in instance_ids], [])

    monkeypatch.setattr(compiler, "_placed_instance_shapes", placed)
    return calls


def _run(monkeypatch, spec, **setup):
    calls = _setup(monkeypatch, spec, **setup)
    findings, meta = compiler._run_spec_interference(spec, Path("spec.yaml"), None)
    return findings, meta, calls


@pytest.mark.parametrize("volume,status,above", [
    (0.0, "successful_empty", False),
    (0.25, "successful_overlap", False),
    (1.0, "successful_overlap", False),
    (2.0, "successful_overlap", True),
])
def test_success_volume_and_threshold_are_separate(monkeypatch, volume, status, above):
    findings, meta, calls = _run(monkeypatch, _spec(), outcomes={("part_0", "part_1"): volume})
    assert calls == [("part_0", "part_1")]
    assert meta["checked_pairs"] == meta["exact_attempted_pairs"] == meta["exact_successful_pairs"] == 1
    assert meta["exact_failed_pairs"] == 0
    assert meta["checked"] and meta["coverage_complete"] and meta["exact_coverage_complete"]
    assert meta["pair_results"] == [{"instance_a": "part_0", "instance_b": "part_1",
                                    "status": status, "volume_mm3": volume, "above_threshold": above}]
    assert meta["below_threshold_overlap_pairs"] == int(0 < volume <= 1)
    assert bool(findings) == above
    if above:
        assert findings[0].id == "interference.clip"
        assert findings[0].evidence["suggest_shift"]["clearance_mm"] == 1.0


@pytest.mark.parametrize("outcome,reason", [
    ("constructor", "constructor_failed"), ("build", "build_failed"),
    ("is_done", "is_done_failed"), ("not_done", "boolean_not_done"),
    ("shape", "volume_failed"), ("volume", "volume_failed"), ("mass", "volume_failed"),
    (-0.01, "invalid_volume"), (float("nan"), "invalid_volume"),
    (float("inf"), "invalid_volume"),
])
def test_native_failures_are_not_successful_queries(monkeypatch, outcome, reason):
    findings, meta, _ = _run(monkeypatch, _spec(), outcomes={("part_0", "part_1"): outcome})
    assert meta["checked_pairs"] == meta["exact_failed_pairs"] == 1
    assert meta["exact_successful_pairs"] == 0
    assert not meta["checked"] and not meta["coverage_complete"]
    assert meta["pair_results"][0]["status"] == "failed"
    assert meta["pair_results"][0]["reason"] == reason
    assert {finding.id for finding in findings} == {"interference.execution_error", "interference.incomplete"}
    assert all(finding.severity == Severity.FAIL for finding in findings)
    payload = json.dumps({"meta": meta, "findings": [finding.to_dict() for finding in findings]}, allow_nan=False)
    assert "private native diagnostic" not in payload


def test_failure_does_not_hide_other_pairs(monkeypatch):
    findings, meta, calls = _run(monkeypatch, _spec(3), outcomes={
        ("part_0", "part_1"): "not_done", ("part_0", "part_2"): 0.4})
    assert len(calls) == 3
    assert meta["checked_pairs"] == 3 and meta["exact_successful_pairs"] == 2
    assert meta["exact_failed_pairs"] == 1 and not meta["checked"]
    assert [pair["status"] for pair in meta["pair_results"]] == ["failed", "successful_overlap", "successful_empty"]
    assert any(finding.id == "interference.incomplete" for finding in findings)


@pytest.mark.parametrize("config,reason", [
    ({"skip_instances": ["part_0"]}, "configured_instance"),
    ({"skip_roles": ["authored"]}, "configured_role"),
    ({"skip_pairs": [["part_1", "part_0"]]}, "configured_pair"),
])
def test_policy_skips_are_explicit(monkeypatch, config, reason):
    findings, meta, calls = _run(monkeypatch, _spec(config=config))
    assert not findings and not calls
    assert not meta["checked"] and meta["coverage_complete"]
    assert meta["reason"] == "no_eligible_pairs" and meta["policy_skipped_pairs"] == 1
    assert meta["pair_results"][0] == {"instance_a": "part_0", "instance_b": "part_1",
                                       "status": "skipped", "reason": reason}


@pytest.mark.parametrize("box", [(20, 0, 0, 30, 10, 10), (9.75, 0, 0, 19.75, 10, 10)])
def test_existing_bbox_screen_is_not_exact_success(monkeypatch, box):
    findings, meta, calls = _run(monkeypatch, _spec(), bounds={"part_1": box})
    assert not findings and not calls
    assert not meta["checked"] and meta["coverage_complete"] and not meta["exact_coverage_complete"]
    assert meta["reason"] == "screening_only" and meta["screened_pairs"] == 1
    assert meta["pair_results"][0]["reason"] == "bbox_screened"
    assert meta["bbox_screen_tolerance_mm"] == -0.5


def test_cap_records_remaining_candidates_and_fails_incomplete_coverage(monkeypatch):
    findings, meta, calls = _run(monkeypatch, _spec(3, {"max_findings": 1}),
                               outcomes={("part_0", "part_1"): 2.0})
    assert len(calls) == meta["exact_successful_pairs"] == 1
    assert meta["max_findings_reached"] and not meta["coverage_complete"] and not meta["checked"]
    assert meta["not_attempted_pairs"] == 2
    assert all(pair["reason"] == "max_findings_reached" for pair in meta["pair_results"][1:])
    assert {finding.id for finding in findings} == {"interference.clip", "interference.incomplete"}


def test_cap_reached_on_last_pair_does_not_invent_unattempted_work(monkeypatch):
    _, meta, _ = _run(monkeypatch, _spec(config={"max_findings": 1}),
                      outcomes={("part_0", "part_1"): 2.0})
    assert meta["max_findings_reached"] and meta["coverage_complete"] and meta["checked"]
    assert meta["not_attempted_pairs"] == 0


def test_missing_shape_remains_in_pair_accounting(monkeypatch):
    findings, meta, calls = _run(monkeypatch, _spec(3), missing=("part_1",))
    assert calls == [("part_0", "part_2")]
    assert meta["total_pairs"] == 3 and meta["not_attempted_pairs"] == 2
    assert meta["missing_instance_ids"] == ["part_1"] and not meta["coverage_complete"]
    assert any(finding.id == "interference.incomplete" for finding in findings)


def test_invalid_bbox_cannot_be_silently_screened(monkeypatch):
    findings, meta, calls = _run(monkeypatch, _spec(), bounds={"part_1": (0, 0, 0, float("nan"), 10, 10)})
    assert not calls and not meta["coverage_complete"]
    assert meta["pair_results"][0]["reason"] == "invalid_bbox"
    assert any(finding.id == "interference.incomplete" for finding in findings)


def test_no_pair_is_not_a_vacuous_exact_check(monkeypatch):
    findings, meta, calls = _run(monkeypatch, _spec(1))
    assert not findings and not calls
    assert meta["coverage_complete"] and not meta["checked"]
    assert meta["reason"] == "no_eligible_pairs" and meta["pair_results"] == []


def _patch_runner_inputs(monkeypatch, spec, tmp_path):
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec.model_dump()), encoding="utf-8")
    plan = compiler.AssemblyBuildPlan(str(path), str(tmp_path / "out.step"), False, [
        compiler.ResolvedInstance(item.id, item.role, "fixture.step", "fixture.step", True, item.transform.model_dump())
        for item in spec.instances])
    monkeypatch.setattr(compiler, "plan_assembly_build", lambda *args, **kwargs: plan)
    monkeypatch.setattr(compiler, "_export_step", lambda *args, **kwargs: Path(kwargs.get("output_path", tmp_path / "out.step")))
    return path


def test_check_round_does_not_mark_failed_query_checked(monkeypatch, tmp_path):
    spec = _spec()
    _setup(monkeypatch, spec, outcomes={("part_0", "part_1"): "not_done"})
    path = _patch_runner_inputs(monkeypatch, spec, tmp_path)
    monkeypatch.setattr(compiler, "run_assembly_build", lambda *args, **kwargs: Report(
        confidence_budget=ConfidenceBudget(not_checked=["interference"])))
    report = compiler.run_assembly_check_round(path, render_views=False, write_inventory=False)
    assert report.overall == Severity.FAIL
    assert not report.meta["validation"]["interference"]["checked"]
    assert "instance-level interference" not in report.confidence_budget.checked
    assert "interference (incomplete)" in report.confidence_budget.not_checked


def test_sequence_retains_failed_pair_ledger_and_stops(monkeypatch, tmp_path):
    spec = _spec(3)
    spec = spec.model_copy(update={"assembly_sequence": []})
    data = spec.model_dump()
    data["assembly_sequence"] = [
        {"id": "first", "title": "First pair", "instance_ids": ["part_0", "part_1"]},
        {"id": "later", "title": "Later part", "instance_ids": ["part_2"]},
    ]
    spec = AssemblySpec.model_validate(data)
    _setup(monkeypatch, spec, outcomes={("part_0", "part_1"): "not_done"})
    path = _patch_runner_inputs(monkeypatch, spec, tmp_path)
    report = compiler.run_assembly_sequence(path, output_dir=tmp_path / "sequence", render_views=False,
                                           write_bom=False, rotate_final=False)
    assert report.overall == Severity.FAIL
    manifest = json.loads((tmp_path / "sequence" / "assembly_sequence_manifest.json").read_text())
    assert manifest["sequence_blocked_at"] == "first" and len(manifest["steps"]) == 1
    step = manifest["steps"][0]
    assert step["validation_status"] == "fail"
    assert step["validation"]["interference"]["pair_results"][0]["status"] == "failed"
    assert "sequence instance-level interference" not in report.confidence_budget.checked


def test_sequence_single_part_has_explicit_not_checked_status(monkeypatch, tmp_path):
    data = _spec(1).model_dump()
    data["assembly_sequence"] = [{"id": "first", "title": "Single part", "instance_ids": ["part_0"]}]
    spec = AssemblySpec.model_validate(data)
    _setup(monkeypatch, spec)
    path = _patch_runner_inputs(monkeypatch, spec, tmp_path)
    report = compiler.run_assembly_sequence(path, output_dir=tmp_path / "sequence", render_views=False,
                                           write_bom=False, rotate_final=False)
    manifest = json.loads((tmp_path / "sequence" / "assembly_sequence_manifest.json").read_text())
    assert manifest["steps"][0]["validation_status"] == "not_checked"
    assert manifest["steps"][0]["validation"]["interference"]["reason"] == "no_eligible_pairs"
    assert "sequence instance-level interference" not in report.confidence_budget.checked


def test_query_findings_do_not_mutate_cached_import_findings(monkeypatch):
    spec = _spec()
    outcomes = {("part_0", "part_1"): "not_done"}
    _setup(monkeypatch, spec, outcomes=outcomes)
    records, _ = compiler._placed_instance_shapes()
    imported_findings = []
    monkeypatch.setattr(compiler, "_placed_instance_shapes", lambda *args, **kwargs: (records, imported_findings))
    first_findings, first_meta = compiler._run_spec_interference(spec, Path("spec.yaml"), None)
    outcomes[("part_0", "part_1")] = 0.0
    second_findings, second_meta = compiler._run_spec_interference(spec, Path("spec.yaml"), None)
    assert imported_findings == []
    assert first_findings and not first_meta["checked"]
    assert not second_findings and second_meta["checked"]


def test_screening_only_check_round_preserves_confidence_limit(monkeypatch, tmp_path):
    spec = _spec()
    _setup(monkeypatch, spec, bounds={"part_1": (20, 0, 0, 30, 10, 10)})
    path = _patch_runner_inputs(monkeypatch, spec, tmp_path)
    monkeypatch.setattr(compiler, "run_assembly_build", lambda *args, **kwargs: Report(
        confidence_budget=ConfidenceBudget(not_checked=["interference"])))
    report = compiler.run_assembly_check_round(path, render_views=False, write_inventory=False)
    assert not report.meta["validation"]["interference"]["checked"]
    assert "instance-level interference" not in report.confidence_budget.checked
    assert "instance-level interference bbox screening" in report.confidence_budget.checked
    assert "exact interference for bbox-screened pairs" in report.confidence_budget.not_checked


def test_authored_plate_positive_native_intersection(monkeypatch):
    # This is a small authored-source control, not generated replacement geometry.
    cq = pytest.importorskip("cadquery")
    source = Path(__file__).resolve().parents[1] / "examples/relative_placement/parts/plate.step"
    shape = cq.importers.importStep(str(source)).val()
    records = [compiler.PlacedInstanceShape(f"part_{index}", "authored", str(source), shape)
               for index in range(2)]
    monkeypatch.setattr(compiler, "_placed_instance_shapes", lambda *args, **kwargs: (records, []))
    findings, meta = compiler._run_spec_interference(_spec(), Path("spec.yaml"), None)
    assert meta["exact_attempted_pairs"] == meta["exact_successful_pairs"] == 1
    assert meta["exact_failed_pairs"] == 0 and meta["coverage_complete"]
    assert meta["pair_results"][0]["status"] == "successful_overlap"
    assert meta["pair_results"][0]["volume_mm3"] == pytest.approx(shape.Volume(), rel=1e-6)
    assert any(finding.id == "interference.clip" for finding in findings)



def _bound_pair_visits(monkeypatch, maximum):
    original = compiler.combinations
    visits = []

    def bounded(*args):
        for pair in original(*args):
            visits.append(None)
            assert len(visits) <= maximum, "pair traversal exceeded the reporting bound"
            yield pair

    monkeypatch.setattr(compiler, "combinations", bounded)
    return visits


def test_large_fully_excluded_scope_is_bulk_counted(monkeypatch):
    visits = _bound_pair_visits(monkeypatch, 0)
    findings, meta, calls = _run(monkeypatch, _spec(10_000, {"skip_roles": ["authored"]}))
    assert not findings and not calls and not visits
    assert meta["total_pairs"] == meta["policy_skipped_pairs"] == 49_995_000
    assert meta["pair_reason_counts"] == {"configured_role": 49_995_000}
    assert meta["pair_status_counts"] == {"skipped": 49_995_000}
    assert meta["coverage_complete"] and not meta["checked"]
    assert meta["eligible_pairs"] == 0
    assert meta["pair_results"] == [] and not meta["pair_results_complete"]
    assert meta["pair_results_omitted"] == meta["total_pairs"]


def test_large_dense_cap_bulk_counts_tail_and_preserves_policy_exclusions(monkeypatch):
    spec = _spec(10_000, {"max_findings": 1, "skip_instances": ["part_9998"],
                         "skip_roles": ["excluded"],
                         "skip_pairs": [["part_0", "part_1"], ["part_1", "part_2"],
                                        ["part_0", "part_9999"]]})
    spec.instances[-1].role = "excluded"
    visits = _bound_pair_visits(monkeypatch, 3)
    bbox_calls = []
    original = compiler._bbox_overlaps

    def counted_bbox(*args):
        bbox_calls.append(None)
        return original(*args)

    monkeypatch.setattr(compiler, "_bbox_overlaps", counted_bbox)
    findings, meta, calls = _run(monkeypatch, spec, outcomes={("part_0", "part_2"): 2.0})
    assert calls == [("part_0", "part_2")] and len(bbox_calls) == 1 and len(visits) == 3
    assert meta["total_pairs"] == 49_995_000
    assert meta["policy_skipped_pairs"] == 9_999 + 9_998 + 2
    assert meta["not_attempted_pairs"] == meta["bulk_not_attempted_pairs"] == 49_975_000
    assert meta["pair_reason_counts"] == {"configured_instance": 9_999, "configured_role": 9_998,
                                          "configured_pair": 2, "max_findings_reached": 49_975_000}
    assert sum(meta["pair_status_counts"].values()) == meta["total_pairs"]
    assert len(meta["pair_results"]) == 2 <= meta["pair_results_limit"] == 10_000
    assert meta["pair_results_omitted"] == meta["total_pairs"] - 2
    assert not meta["coverage_complete"] and not meta["checked"] and not meta["pair_results_complete"]
    assert {finding.id for finding in findings} == {"interference.clip", "interference.incomplete"}


def test_detail_truncation_preserves_complete_exact_aggregate(monkeypatch):
    monkeypatch.setattr(compiler, "_INTERFERENCE_PAIR_DETAIL_LIMIT", 3)
    spec = _spec(4)
    outcomes = {(a.id, b.id): 0.25 for a, b in compiler.combinations(spec.instances, 2)}
    findings, meta, calls = _run(monkeypatch, spec, outcomes=outcomes)
    assert not findings and len(calls) == 6
    assert meta["exact_successful_pairs"] == meta["below_threshold_overlap_pairs"] == 6
    assert meta["checked"] and meta["coverage_complete"] and meta["exact_coverage_complete"]
    assert len(meta["pair_results"]) == 3 and meta["pair_results_omitted"] == 3
    assert not meta["pair_results_complete"]


def test_large_systemic_failure_stops_at_error_reporting_limit(monkeypatch):
    monkeypatch.setattr(compiler, "_INTERFERENCE_PAIR_DETAIL_LIMIT", 3)
    spec = _spec(4)
    outcomes = {(a.id, b.id): "not_done" for a, b in compiler.combinations(spec.instances, 2)}
    visits = _bound_pair_visits(monkeypatch, 4)
    findings, meta, calls = _run(monkeypatch, spec, outcomes=outcomes)
    assert len(calls) == meta["exact_failed_pairs"] == 3 and len(visits) == 4
    assert meta["execution_error_limit_reached"] and meta["execution_error_details_omitted"] == 0
    assert meta["not_attempted_pairs"] == meta["bulk_not_attempted_pairs"] == 3
    assert meta["pair_reason_counts"]["execution_error_limit_reached"] == 3
    assert len(meta["pair_results"]) == 3 and meta["pair_results_omitted"] == 3
    assert sum(finding.id == "interference.execution_error" for finding in findings) == 3
    assert not meta["checked"] and not meta["coverage_complete"]


def test_small_scope_has_complete_detail_metadata(monkeypatch):
    _, meta, _ = _run(monkeypatch, _spec())
    assert meta["pair_results_complete"] and meta["pair_results_omitted"] == 0
    assert meta["pair_results_limit"] == 10_000
    assert meta["bulk_not_attempted_pairs"] == 0



def test_delimiter_id_fallback_bounds_error_details_without_losing_failures(monkeypatch):
    monkeypatch.setattr(compiler, "_INTERFERENCE_PAIR_DETAIL_LIMIT", 3)
    spec = _spec(4)
    spec.instances[-1].id = "part||3"
    outcomes = {(a.id, b.id): "not_done" for a, b in compiler.combinations(spec.instances, 2)}
    findings, meta, calls = _run(monkeypatch, spec, outcomes=outcomes)
    assert len(calls) == meta["exact_failed_pairs"] == meta["total_pairs"] == 6
    assert meta["not_attempted_pairs"] == 0 and not meta["execution_error_limit_reached"]
    assert meta["execution_error_details_omitted"] == 3
    assert len(meta["pair_results"]) == meta["pair_results_omitted"] == 3
    assert sum(finding.id == "interference.execution_error" for finding in findings) == 3
    assert meta["pair_status_counts"] == {"failed": 6}
    assert not meta["coverage_complete"] and not meta["checked"]
