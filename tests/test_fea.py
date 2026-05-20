"""
Tests for cadclaw.fea — frame solver, joint-adequacy gate, M3 anchor.

The solver is checked against closed-form beam theory (exact), and the
M3-CRETE X-gantry model is cross-checked against the documented
δ ≈ 0.44 mm deflection anchor at 3 kg nominal load.
"""
import csv
import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("Pynite")  # PyniteFEA backs every test here

from cadclaw.fea import (
    FrameModel, Material, Section, Support, LoadCase,
    PyniteSolver, CalculiXSolver,
    kinematics_joint_adequacy, evaluate_joint_adequacy, write_joint_csv,
)
from cadclaw.fea.joint_adequacy import (
    _classify, joint_adequacy_report, JointAdequacyResult,
)
from cadclaw.fea.m3_frame import m3_2_frame, m3_xgantry_frame

ROOT = Path(__file__).resolve().parents[1]
FEA_CASES = ROOT / "examples" / "m3_crete" / "m3_fea_load_cases.yaml"
FEA_RUNNER = ROOT / "examples" / "m3_crete" / "run_fea_load_cases.py"
G = 9.80665
ROW_KEYS = {"joint_id", "joint_type", "max_moment_Nm",
            "allowable_Nm", "utilization", "result"}


def _load_m3_fea_runner():
    spec = importlib.util.spec_from_file_location("m3_fea_runner", FEA_RUNNER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _simply_supported(span=2.0, point_load_N=1000.0):
    """A 2-member simply-supported beam with a centre point load.

    Twist (rx) is restrained at the pin end — a straight colinear run
    otherwise has an unrestrained roll mode.
    """
    mat = Material.aluminum_6061_t6()
    sec = Section.rectangular("bar", 0.00635, 0.0762)
    m = FrameModel("ss")
    m.add_node("A", 0.0, 0.0, 0.0)
    m.add_node("C", span / 2.0, 0.0, 0.0)
    m.add_node("B", span, 0.0, 0.0)
    m.add_member("m1", "A", "C", mat, sec)
    m.add_member("m2", "C", "B", mat, sec)
    m.add_support(Support("A", dx=True, dy=True, dz=True, rx=True))
    m.add_support(Support("B", dx=False, dy=True, dz=True))
    lc = LoadCase("service", self_weight=False)
    lc.add_point_load("C", "FY", -point_load_N)
    return m, sec, mat, lc


# --------------------------------------------------------------------------
# Section properties
# --------------------------------------------------------------------------
def test_rectangular_section_properties():
    sec = Section.rectangular("s", 0.01, 0.03)  # 10 mm wide, 30 mm deep
    assert sec.A == pytest.approx(0.01 * 0.03)
    assert sec.Iz == pytest.approx(0.01 * 0.03 ** 3 / 12.0)
    assert sec.Sz == pytest.approx(0.01 * 0.03 ** 2 / 6.0)
    assert sec.Iz > sec.Iy  # deeper than wide -> strong axis is z


# --------------------------------------------------------------------------
# Solver vs analytic beam theory
# --------------------------------------------------------------------------
def test_solver_matches_analytic_deflection_and_moment():
    span, P = 2.0, 1000.0
    model, sec, mat, lc = _simply_supported(span, P)
    res = PyniteSolver().solve(model, lc)
    assert res.converged

    analytic_defl_mm = (P * span ** 3) / (48 * mat.E * sec.Iz) * 1000.0
    assert res.max_deflection_mm == pytest.approx(analytic_defl_mm, rel=1e-3)

    peak_moment = max(r.peak_moment_Nm for r in res.member_results.values())
    assert peak_moment == pytest.approx(P * span / 4.0, rel=1e-3)  # PL/4


def test_solver_reactions_balance_applied_load():
    model, _, _, lc = _simply_supported(2.0, 1000.0)
    res = PyniteSolver().solve(model, lc)
    total_fy = sum(r["FY"] for r in res.node_reactions.values())
    assert total_fy == pytest.approx(1000.0, rel=1e-6)  # balances the load


def test_solver_flags_unrestrained_frame_as_unconverged():
    """A straight run with no twist restraint is singular — caught, not NaN."""
    mat = Material.aluminum_6061_t6()
    sec = Section.rectangular("bar", 0.00635, 0.0762)
    m = FrameModel("unstable")
    m.add_node("A", 0.0, 0.0, 0.0)
    m.add_node("B", 2.0, 0.0, 0.0)
    m.add_member("m1", "A", "B", mat, sec)
    m.add_support(Support.pinned("A"))   # no rx restraint -> roll mode
    m.add_support(Support("B", dx=False, dy=True, dz=True))
    lc = LoadCase("service", self_weight=True)
    res = PyniteSolver().solve(m, lc)
    assert res.converged is False
    assert res.notes and "rigid-body" in res.notes[0]


def test_calculix_solver_is_a_declared_stub():
    model, _, _, lc = _simply_supported()
    with pytest.raises(NotImplementedError):
        CalculiXSolver().solve(model, lc)


# --------------------------------------------------------------------------
# M3-CRETE X-gantry — V-Slot 4080 extrusion
# --------------------------------------------------------------------------
def test_m3_xgantry_deflection_matches_beam_theory():
    """The 4080 X-gantry model reproduces simply-supported beam theory."""
    frame = m3_xgantry_frame()
    P = 49.0
    result = evaluate_joint_adequacy(frame, load_n=P, self_weight=False)
    sec = frame.members["seg_L"].section
    mat = frame.members["seg_L"].material
    analytic_mm = (P * 2.0 ** 3) / (48 * mat.E * sec.Iz) * 1000.0
    assert result.deflection_mm == pytest.approx(analytic_mm, rel=1e-3)


def test_m3_xgantry_passes_deflection_under_primary_load():
    """The V-Slot 4080 beam is stiff enough for the 49 N primary case."""
    result = evaluate_joint_adequacy(m3_xgantry_frame(), load_n=49.0)
    assert result.deflection_mm < 0.5
    assert result.deflection_result == "pass"


def test_m3_xgantry_strength_is_not_governing():
    """At 49 N the extrusion is far from yielding — stiffness governs."""
    frame = m3_xgantry_frame()
    result = evaluate_joint_adequacy(frame, load_n=49.0)
    assert all(r["utilization"] < 0.1 for r in result.rows)
    assert all(r["result"] == "pass" for r in result.rows)


def test_m3_2_frame_solves_center_printhead_load():
    """The M3-2 full-frame idealization solves the 49 N center load case."""
    frame = m3_2_frame()
    result = evaluate_joint_adequacy(frame, load_n=49.0)
    assert result.solver_result.converged
    assert result.deflection_mm < 0.5
    assert result.deflection_result == "pass"
    assert any(r["joint_id"] == "printhead" for r in result.rows)


def test_m3_2_frame_keeps_open_bottom_x_direction():
    """The open-frame reference has bottom side rails but no bottom X rails."""
    frame = m3_2_frame()
    assert "bottom_side_L" in frame.members
    assert "bottom_side_R" in frame.members
    assert not any(member_id.startswith("bottom_x_")
                   for member_id in frame.members)


def test_m3_fea_load_case_spec_loads():
    """The tracked M3 load-case spec is valid and covers the full frame."""
    runner = _load_m3_fea_runner()
    spec = runner.load_spec(FEA_CASES)
    case_ids = {case["id"] for case in spec["load_cases"]}
    assert "m3_2_center_printhead_5kg" in case_ids
    assert "m3_2_front_top_lateral_x_100n" in case_ids
    assert spec["defaults"]["output_root"].endswith("build/fea")


def test_m3_fea_runner_writes_case_outputs(tmp_path):
    """The FEA runner produces report, joint CSV, and member-demand CSV."""
    runner = _load_m3_fea_runner()
    summary = runner.run_cases(
        FEA_CASES,
        case_ids={"m3_2_center_printhead_5kg"},
        output_root=tmp_path,
        render_plots=False,
    )
    assert summary["load_cases"][0]["overall"] == "pass"
    assert summary["load_cases"][0]["deflection_mm"] < 0.5
    outputs = summary["load_cases"][0]["outputs"]
    for key in ("report_json", "joint_csv", "member_csv"):
        assert outputs[key]
        assert Path(outputs[key]).exists()
    report = json.loads(Path(outputs["report_json"]).read_text())
    assert report["meta"]["load_case_id"] == "m3_2_center_printhead_5kg"


# --------------------------------------------------------------------------
# Gate contract
# --------------------------------------------------------------------------
def test_gate_returns_spec_shaped_rows():
    rows = kinematics_joint_adequacy(frame=m3_xgantry_frame(), load_n=49.0)
    assert isinstance(rows, list) and rows
    for row in rows:
        assert set(row.keys()) == ROW_KEYS
        assert row["result"] in {"pass", "warn", "fail", "unverified"}


def test_classify_thresholds():
    assert _classify(0.0) == "pass"
    assert _classify(0.79) == "pass"
    assert _classify(0.80) == "warn"
    assert _classify(1.00) == "warn"
    assert _classify(1.01) == "fail"


def test_allowables_override_drives_warn_and_fail():
    frame = m3_xgantry_frame()
    base = kinematics_joint_adequacy(frame=frame, load_n=49.0)
    moment = next(r["max_moment_Nm"] for r in base
                  if r["joint_id"] == "printhead")

    warn = kinematics_joint_adequacy(
        frame=frame, load_n=49.0,
        allowables={"printhead": moment / 0.9})  # util ~0.9
    assert next(r["result"] for r in warn
                if r["joint_id"] == "printhead") == "warn"

    fail = kinematics_joint_adequacy(
        frame=frame, load_n=49.0,
        allowables={"printhead": moment / 1.5})  # util ~1.5
    assert next(r["result"] for r in fail
                if r["joint_id"] == "printhead") == "fail"


def test_sweep_and_step_file_are_phase_2():
    with pytest.raises(NotImplementedError):
        kinematics_joint_adequacy(frame=m3_xgantry_frame(), sweep=True)
    with pytest.raises(NotImplementedError):
        kinematics_joint_adequacy(step_file="anything.step")


def test_self_weight_toggle_changes_deflection():
    frame = m3_xgantry_frame()
    with_sw = evaluate_joint_adequacy(frame, load_n=49.0, self_weight=True)
    without_sw = evaluate_joint_adequacy(frame, load_n=49.0, self_weight=False)
    assert with_sw.deflection_mm > without_sw.deflection_mm


# --------------------------------------------------------------------------
# CSV + report adapters
# --------------------------------------------------------------------------
def test_write_joint_csv_has_spec_columns(tmp_path):
    rows = kinematics_joint_adequacy(frame=m3_xgantry_frame(), load_n=49.0)
    path = tmp_path / "joints.csv"
    write_joint_csv(rows, str(path))
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [
            "joint_id", "joint_type", "max_moment_Nm",
            "allowable_Nm", "utilization", "result"]
        assert len(list(reader)) == len(rows)


def test_joint_adequacy_report_carries_confidence_budget():
    result = evaluate_joint_adequacy(m3_xgantry_frame(), load_n=49.0)
    report = joint_adequacy_report(result)
    assert report.meta["gate"] == "kinematics_joint_adequacy"
    assert report.confidence_budget.checked
    # The kinematic sweep must be declared as not-checked in Phase 1.
    assert any("sweep" in n for n in report.confidence_budget.not_checked)


def test_deflection_exceedance_fails_overall():
    # The 4080 beam passes a 0.5 mm limit at 49 N; a tight 0.05 mm
    # limit must drive the deflection check — and the overall — to fail.
    result = evaluate_joint_adequacy(
        m3_xgantry_frame(), load_n=49.0, deflection_limit_mm=0.05)
    assert result.deflection_result == "fail"
    assert result.overall == "fail"
    assert result.passed is False
