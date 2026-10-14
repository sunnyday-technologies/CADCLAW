"""Profiler contract tests with fake operations only; no native geometry imports."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "profile_assembly_workflow.py"
SPEC = importlib.util.spec_from_file_location("profile_assembly_workflow_under_test", SCRIPT)
profiler = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profiler)


def test_call_counters_separate_attempts_returns_and_exceptions():
    ticks = iter([0.0, 1.0, 2.0, 5.0])
    instrumentation = profiler._CallInstrumentation(clock=lambda: next(ticks))
    assert instrumentation.call("query", lambda: False) is False
    def fail():
        raise ValueError("test exception text is not a metric")
    with pytest.raises(ValueError):
        instrumentation.call("query", fail)
    assert instrumentation.counts == {"query": 2}
    assert instrumentation.outcomes == {"query": {"attempted": 2, "returned": 1, "failed": 1}}
    assert instrumentation.stages == {"query": 4.0}
    instrumentation.reset()
    assert not instrumentation.counts and not instrumentation.outcomes and not instrumentation.stages


def test_wrappers_restore_in_reverse_order_after_failure():
    def original():
        raise ValueError("unit failure")
    owner = SimpleNamespace(query=original)
    instrumentation = profiler._CallInstrumentation()
    try:
        instrumentation.instrument(owner, "query", "first")
        instrumentation.instrument(owner, "query", "second")
        with pytest.raises(ValueError):
            owner.query()
    finally:
        instrumentation.restore()
    assert owner.query is original
    assert instrumentation.outcomes["first"]["failed"] == 1
    assert instrumentation.outcomes["second"]["failed"] == 1
    instrumentation.restore()  # Idempotent cleanup.


def test_measured_failure_returns_safe_receipt_and_stops_sampler(monkeypatch):
    threads = []
    original_thread = profiler.threading.Thread
    def tracking_thread(*args, **kwargs):
        thread = original_thread(*args, **kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setattr(profiler.threading, "Thread", tracking_thread)
    instrumentation = profiler._CallInstrumentation()
    def fail():
        raise ValueError("DO_NOT_LOG_TEST_EXCEPTION_CONTENT")
    report, record = profiler._measure_action(
        lambda: instrumentation.call("query", fail), instrumentation, resident_bytes=lambda: None,
    )
    assert report is None
    assert record["status"] == "error"
    assert record["error"] == {"phase": "measured_action", "exception_type": "ValueError"}
    assert record["call_outcomes"]["query"] == {"attempted": 1, "returned": 0, "failed": 1}
    assert record["peak_resident_bytes_sampled"] is None
    assert all(not thread.is_alive() for thread in threads)
    assert "DO_NOT_LOG_TEST_EXCEPTION_CONTENT" not in json.dumps(record)


def test_returned_failed_report_is_completed_execution():
    payload = {"overall": "fail", "findings": [{"id": "interference.clip"}]}
    report, record = profiler._measure_action(lambda: payload, profiler._CallInstrumentation(), resident_bytes=lambda: None)
    assert report is payload
    assert report["overall"] == "fail"
    assert record["status"] == "completed"
    assert record["cache_state"]["os_file_cache"] == "unknown"
    assert record["cache_state"]["python_process"] == "already_initialized"


def test_completion_metadata_is_copied_without_inventing_success():
    coverage = {"checked": False, "checked_pairs": 2, "exact_attempted_pairs": 2,
                "exact_successful_pairs": 1, "exact_failed_pairs": 1, "coverage_complete": False,
                "pair_results": [{"instance_a": "a", "instance_b": "b", "status": "failed"}]}
    cache = {"source_imports": 1, "source_hits": 2}
    payload = {"meta": {"validation": {"interference": coverage}, "geometry_cache": cache}}
    result = profiler._returned_metadata(payload)
    assert result["interference_completion"] == coverage
    assert result["candidate_pairs"] == 2
    result["interference_completion"]["pair_results"].clear()
    result["geometry_cache"]["source_hits"] = 999
    assert len(coverage["pair_results"]) == 1
    assert cache["source_hits"] == 2
    missing = profiler._returned_metadata({})
    assert missing["candidate_pairs"] is None
    assert missing["interference_completion"]["status"] == "unavailable"


def _fake_main_environment(monkeypatch, tmp_path, *, fail_import):
    code_root = tmp_path / "fake-code"
    (code_root / "cadclaw").mkdir(parents=True)
    (code_root / "cadclaw" / "assembly_compiler.py").write_text("# inert unit fixture\n")
    source = tmp_path / "fixture.step"
    source.write_bytes(b"inert source bytes; never loaded by a native library")
    def fail(*args, **kwargs):
        raise ValueError("DO_NOT_LOG_TEST_EXCEPTION_CONTENT")
    def imported(*args, **kwargs):
        return object()
    import_step = fail if fail_import else imported
    cq = SimpleNamespace(importers=SimpleNamespace(importStep=import_step),
                         Shape=SimpleNamespace(toVtkPolyData=lambda *a, **k: None))
    compiler = SimpleNamespace(__file__=str(code_root / "cadclaw" / "assembly_compiler.py"),
                               run_assembly_check_round=fail)
    for name in ("_export_step", "_placed_instance_shapes", "_run_spec_interference", "render_review_views"):
        setattr(compiler, name, lambda *a, **k: None)
    render = SimpleNamespace(_extract_step_colors=lambda *a, **k: None)
    native_common = lambda *a, **k: None
    brep = SimpleNamespace(BRepAlgoAPI_Common=native_common)
    monkeypatch.setitem(sys.modules, "cadquery", cq)
    monkeypatch.setitem(sys.modules, "cadclaw", SimpleNamespace(assembly_compiler=compiler, render=render))
    monkeypatch.setitem(sys.modules, "OCP", SimpleNamespace(BRepAlgoAPI=brep))
    monkeypatch.setitem(sys.modules, "yaml", SimpleNamespace(safe_dump=lambda value, **k: json.dumps(value)))
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=SimpleNamespace()))
    monkeypatch.setattr(profiler, "_resident_bytes", lambda: None)
    monkeypatch.setattr(profiler.importlib.metadata, "version", lambda name: "fake-unit-version")
    monkeypatch.setattr(profiler.subprocess, "check_output", lambda args, **k: "fake-commit\n" if "rev-parse" in args else "")
    # main prepends a code root; restore sys.path with the other monkeypatches.
    monkeypatch.setattr(sys, "path", list(sys.path))
    output = tmp_path / "evidence"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--output", str(output), "--label", "failure", "--code-root", str(code_root),
                                     "--source", str(source), "--skip-cameras", "--repetitions", "1"])
    return output, cq, import_step, brep, native_common


@pytest.mark.parametrize("fail_import", [True, False])
def test_main_preserves_error_receipt_and_prior_records_without_native_loads(monkeypatch, tmp_path, fail_import):
    output, cq, import_step, brep, native_common = _fake_main_environment(monkeypatch, tmp_path, fail_import=fail_import)
    with pytest.raises(RuntimeError, match="safe local error receipt"):
        profiler.main()
    raw = (output / "failure.json").read_text()
    receipt = json.loads(raw)
    assert receipt["schema"] == "cadclaw-workflow-profile.v0.2"
    assert receipt["complete"] is False
    assert receipt["measurement_valid"] is False
    assert receipt["status"] == "error"
    assert receipt["environment"]["cpu_contention"] == "not_measured"
    assert receipt["environment"]["os_file_cache"] == "unknown"
    assert receipt["records"][0]["scenario"] == "first_profiled_source_import"
    assert len(receipt["records"]) == (1 if fail_import else 2)
    assert receipt["records"][-1]["error"]["exception_type"] == "ValueError"
    assert "DO_NOT_LOG_TEST_EXCEPTION_CONTENT" not in raw
    assert cq.importers.importStep is import_step
    assert brep.BRepAlgoAPI_Common is native_common


def test_main_preserves_completion_metadata_when_evidence_collection_fails(monkeypatch, tmp_path):
    output, cq, import_step, brep, native_common = _fake_main_environment(monkeypatch, tmp_path, fail_import=False)
    coverage = {"checked": False, "checked_pairs": 1, "exact_failed_pairs": 1,
                "coverage_complete": False, "pair_results": [{"status": "failed"}]}
    payload = {"overall": "fail", "findings": [{"id": "interference.operation_failed"}],
               "meta": {"validation": {"interference": coverage}}}
    def report_with_bad_evidence(*args, **kwargs):
        (output / "failure" / "inventory.json").write_text("invalid json fixture")
        return SimpleNamespace(to_dict=lambda: payload)
    monkeypatch.setattr(sys.modules["cadclaw"].assembly_compiler, "run_assembly_check_round", report_with_bad_evidence)
    with pytest.raises(RuntimeError, match="safe local error receipt"):
        profiler.main()
    receipt = json.loads((output / "failure.json").read_text())
    record = receipt["records"][-1]
    assert record["status"] == "completed"
    assert record["evidence_status"] == "error"
    assert record["interference_completion"] == coverage
    assert receipt["complete"] is False
    assert cq.importers.importStep is import_step
    assert brep.BRepAlgoAPI_Common is native_common


def test_main_completed_profile_keeps_failed_geometry_separate_from_execution(monkeypatch, tmp_path):
    output, cq, import_step, brep, native_common = _fake_main_environment(monkeypatch, tmp_path, fail_import=False)
    coverage = {"checked": False, "checked_pairs": 1, "exact_successful_pairs": 0,
                "exact_failed_pairs": 1, "coverage_complete": False, "pair_results": [{"status": "failed"}]}
    payload = {"overall": "fail", "findings": [{"id": "interference.operation_failed"}],
               "meta": {"validation": {"interference": coverage}, "geometry_cache": {"source_imports": 1}}}
    monkeypatch.setattr(sys.modules["cadclaw"].assembly_compiler, "run_assembly_check_round",
                        lambda *a, **k: SimpleNamespace(to_dict=lambda: payload))
    profiler.main()
    receipt = json.loads((output / "failure.json").read_text())
    assert receipt["complete"] is True
    assert receipt["measurement_valid"] is True  # Frozen measurement, not geometric acceptance.
    assert receipt["status"] == "completed"
    assert len(receipt["records"]) == 3
    for record in receipt["records"][1:]:
        assert record["semantic"]["overall"] == "fail"
        assert record["interference_completion"] == coverage
        assert record["candidate_pairs"] == 1
        assert record["geometry_cache"] == {"source_imports": 1}
        assert record["workload_sha256"]
        assert record["workload_sha256_after"] == record["workload_sha256"]
        assert record["workload_changed_during_measurement"] is False
    assert receipt["records"][1]["workload_sha256"] != receipt["records"][2]["workload_sha256"]
    assert cq.importers.importStep is import_step
    assert brep.BRepAlgoAPI_Common is native_common


@pytest.mark.parametrize("existing", ["receipt", "work", "both"])
def test_main_rejects_reused_label_before_setup_and_preserves_bytes(monkeypatch, tmp_path, existing):
    output, _, _, _, _ = _fake_main_environment(monkeypatch, tmp_path, fail_import=False)
    output.mkdir()
    if existing in ("receipt", "both"):
        (output / "failure.json").write_bytes(b"prior receipt bytes\r\n")
    if existing in ("work", "both"):
        (output / "failure").mkdir()
        (output / "failure" / "workload.yaml").write_bytes(b"prior authored workload bytes\r\n")
    def snapshot():
        return {path.relative_to(output).as_posix(): path.read_bytes() if path.is_file() else None
                for path in output.rglob("*")}
    before = snapshot()
    def setup_must_not_run(*args, **kwargs):
        pytest.fail("reused labels must be rejected before setup or measured actions")
    monkeypatch.setattr(profiler, "_code_snapshot", setup_must_not_run)
    monkeypatch.setattr(profiler, "_measure_action", setup_must_not_run)
    with pytest.raises(RuntimeError, match="label already exists"):
        profiler.main()
    assert snapshot() == before


@pytest.mark.parametrize("mutation", ["edit", "unlink"])
@pytest.mark.parametrize("action_fails", [False, True])
def test_main_preserves_consumed_record_and_invalidates_workload_drift(monkeypatch, tmp_path, mutation, action_fails):
    output, cq, import_step, brep, native_common = _fake_main_environment(monkeypatch, tmp_path, fail_import=False)
    coverage = {"checked": False, "checked_pairs": 1, "exact_failed_pairs": 1, "coverage_complete": False}
    observed = {}
    def mutate_workload(spec_path, **kwargs):
        observed["before"] = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        cq.importers.importStep("inert fake operation")
        if mutation == "edit":
            spec_path.write_bytes(b"changed workload; not the measured settings")
            observed["after"] = hashlib.sha256(spec_path.read_bytes()).hexdigest()
        else:
            spec_path.unlink()
            observed["after"] = None
        if action_fails:
            raise ValueError("DO_NOT_LOG_TEST_EXCEPTION_CONTENT")
        return SimpleNamespace(to_dict=lambda: {"meta": {"validation": {"interference": coverage}}})
    monkeypatch.setattr(sys.modules["cadclaw"].assembly_compiler, "run_assembly_check_round", mutate_workload)
    with pytest.raises(RuntimeError, match="safe local error receipt"):
        profiler.main()
    raw = (output / "failure.json").read_text()
    receipt = json.loads(raw)
    assert receipt["complete"] is False
    assert receipt["measurement_valid"] is False
    assert len(receipt["records"]) == 2
    record = receipt["records"][-1]
    assert record["scenario"] == "unchanged_round"
    assert record["status"] == ("error" if action_fails else "completed")
    assert record["call_outcomes"]["step_imports"] == {"attempted": 1, "returned": 1, "failed": 0}
    assert record["wall_seconds"] >= 0
    assert record["workload_sha256"] == observed["before"]
    assert record["workload_sha256_after"] == observed["after"]
    assert record["workload_changed_during_measurement"] is True
    assert record["evidence_status"] == "error"
    assert record["evidence_error"] == {"phase": "workload_identity", "reason": "changed" if mutation == "edit" else "unavailable"}
    if mutation == "unlink":
        assert record["workload_read_error"] == {"exception_type": "FileNotFoundError"}
    if action_fails:
        assert record["error"] == {"phase": "measured_action", "exception_type": "ValueError"}
    else:
        assert record["interference_completion"] == coverage
    assert "DO_NOT_LOG_TEST_EXCEPTION_CONTENT" not in raw
    assert cq.importers.importStep is import_step
    assert brep.BRepAlgoAPI_Common is native_common


def test_failure_receipt_cannot_overwrite_late_existing_evidence(tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(b"prior evidence\r\n")
    with pytest.raises(FileExistsError):
        profiler._write_failure_receipt(receipt, {}, [], ValueError("redacted"))
    assert receipt.read_bytes() == b"prior evidence\r\n"


def test_main_source_drift_writes_one_invalid_receipt(monkeypatch, tmp_path):
    output, cq, import_step, brep, native_common = _fake_main_environment(monkeypatch, tmp_path, fail_import=False)
    def change_source(*args, **kwargs):
        (tmp_path / "fixture.step").write_bytes(b"source changed during fake operation")
        return SimpleNamespace(to_dict=lambda: {})
    monkeypatch.setattr(sys.modules["cadclaw"].assembly_compiler, "run_assembly_check_round", change_source)
    with pytest.raises(RuntimeError, match="inspect the safe local error receipt"):
        profiler.main()
    receipt = json.loads((output / "failure.json").read_text())
    assert receipt["status"] == "error"
    assert receipt["measurement_valid"] is False
    assert receipt["complete"] is False
    assert receipt["source"]["changed_during_measurement"] is True
    assert len(receipt["records"]) == 3
    assert cq.importers.importStep is import_step
    assert brep.BRepAlgoAPI_Common is native_common
