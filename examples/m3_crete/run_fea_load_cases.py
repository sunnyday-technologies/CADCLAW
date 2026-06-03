"""Run tracked M3-CRETE light FEA load cases.

This is intentionally a thin orchestration layer around cadclaw.fea. The
frame model remains an authored structural idealization, and the script only
applies declared loads, exports CADCLAW reports, and writes member demand
tables/plots for review.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC = Path(__file__).with_name("m3_fea_load_cases.yaml")

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cadclaw.fea import (  # noqa: E402
    LoadCase,
    evaluate_joint_adequacy,
    joint_adequacy_report,
    m3_2_frame,
    m3_xgantry_frame,
    member_demand_envelopes,
    render_member_maps,
    write_joint_csv,
    write_member_demand_csv,
)


FRAME_BUILDERS = {
    "m3-xgantry": m3_xgantry_frame,
    "m3-2-frame": m3_2_frame,
}
VALID_DIRECTIONS = {"FX", "FY", "FZ", "MX", "MY", "MZ"}


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def load_spec(path: str | Path = DEFAULT_SPEC) -> dict[str, Any]:
    """Load and minimally validate the M3 FEA load-case YAML."""
    spec_path = Path(path)
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if data.get("schema_version") != "m3_fea_load_cases.v0.1":
        raise ValueError(
            f"{spec_path} is not an m3_fea_load_cases.v0.1 spec"
        )
    cases = data.get("load_cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{spec_path} has no load_cases")
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{spec_path} has duplicate load case ids")
    return data


def _case_load(
    case: dict[str, Any],
    defaults: dict[str, Any],
    frame,
) -> tuple[LoadCase | None, float, str | None]:
    """Return explicit LoadCase or the default printhead load parameters."""
    self_weight = bool(case.get("self_weight", defaults.get("self_weight", True)))
    gravity_dir = str(case.get("gravity_dir", defaults.get("gravity_dir", "FY"))).upper()
    point_loads = case.get("point_loads") or []
    if not point_loads:
        return (
            None,
            float(case.get("load_n", defaults.get("load_n", 49.0))),
            case.get("load_node", defaults.get("load_node")),
        )

    load_case = LoadCase(
        name=str(case["id"]),
        self_weight=self_weight,
        gravity_dir=gravity_dir,
    )
    for entry in point_loads:
        node = str(entry["node"])
        direction = str(entry["direction"]).upper()
        if node not in frame.nodes:
            raise KeyError(f"load case {case['id']}: unknown node {node!r}")
        if direction not in VALID_DIRECTIONS:
            raise ValueError(
                f"load case {case['id']}: invalid direction {direction!r}"
            )
        load_case.add_point_load(node, direction, float(entry["value_n"]))
    return load_case, 0.0, None


def _max_joint_utilization(rows: Iterable[dict[str, Any]]) -> float:
    values = [float(row.get("utilization") or 0.0) for row in rows]
    return max(values, default=0.0)


def _member_summary(frame, solver_result) -> dict[str, Any]:
    if solver_result is None or not solver_result.converged:
        return {
            "max_member_stress_MPa": None,
            "max_member_strain_microstrain": None,
            "critical_member": None,
        }
    demands = member_demand_envelopes(frame, solver_result)
    if not demands:
        return {
            "max_member_stress_MPa": 0.0,
            "max_member_strain_microstrain": 0.0,
            "critical_member": None,
        }
    critical_member = max(
        demands,
        key=lambda member_id: demands[member_id]["peak_stress_MPa"],
    )
    return {
        "max_member_stress_MPa": round(
            demands[critical_member]["peak_stress_MPa"], 6
        ),
        "max_member_strain_microstrain": round(
            demands[critical_member]["peak_strain_microstrain"], 6
        ),
        "critical_member": critical_member,
    }


def _plot_load_label(
    load_case: LoadCase | None,
    load_n: float,
    load_node: str | None,
) -> str | None:
    if load_case is None and load_node == "printhead":
        return f"{load_n:g} N center load"
    return None


def run_case(
    case: dict[str, Any],
    defaults: dict[str, Any],
    output_root: Path,
    *,
    render_plots: bool = True,
) -> dict[str, Any]:
    """Run one load case and write its report/CSV/plot outputs."""
    frame_name = str(case["frame"])
    if frame_name not in FRAME_BUILDERS:
        raise ValueError(f"unsupported frame {frame_name!r}")

    frame = FRAME_BUILDERS[frame_name]()
    load_case, load_n, load_node = _case_load(case, defaults, frame)
    case_dir = output_root / str(case["id"])
    plots_dir = case_dir / "plots"
    case_dir.mkdir(parents=True, exist_ok=True)

    result = evaluate_joint_adequacy(
        frame,
        load_case=load_case,
        load_n=load_n,
        load_node=load_node,
        safety_factor=float(
            case.get("safety_factor", defaults.get("safety_factor", 1.65))
        ),
        deflection_limit_mm=float(
            case.get(
                "deflection_limit_mm",
                defaults.get("deflection_limit_mm", 0.5),
            )
        ),
        self_weight=bool(
            case.get("self_weight", defaults.get("self_weight", True))
        ),
        gravity_dir=str(
            case.get("gravity_dir", defaults.get("gravity_dir", "FY"))
        ).upper(),
    )

    report = joint_adequacy_report(result)
    report_dict = report.to_dict()
    report_dict["meta"].update({
        "load_case_id": case["id"],
        "load_case_description": case.get("description", ""),
        "frame": frame_name,
        "point_loads": case.get("point_loads", []),
        "load_node": load_node,
        "load_n": load_n if load_case is None else None,
    })

    report_path = case_dir / "report.json"
    joint_csv_path = case_dir / "joint_adequacy.csv"
    member_csv_path = case_dir / "member_demands.csv"
    report_path.write_text(json.dumps(report_dict, indent=2) + "\n",
                           encoding="utf-8")
    write_joint_csv(result.rows, str(joint_csv_path))

    outputs: dict[str, Any] = {
        "report_json": str(report_path),
        "joint_csv": str(joint_csv_path),
        "member_csv": None,
        "stress_plot": None,
        "strain_plot": None,
    }
    if result.solver_result is not None and result.solver_result.converged:
        write_member_demand_csv(frame, result.solver_result, member_csv_path)
        outputs["member_csv"] = str(member_csv_path)
        if render_plots:
            try:
                stress_plot, strain_plot = render_member_maps(
                    frame,
                    result.solver_result,
                    plots_dir,
                    title_prefix=str(case["id"]),
                    load_label=_plot_load_label(load_case, load_n, load_node),
                )
            except ImportError as exc:
                outputs["plot_warning"] = f"plots skipped: {exc}"
            else:
                outputs["stress_plot"] = str(stress_plot)
                outputs["strain_plot"] = str(strain_plot)

    summary = {
        "id": case["id"],
        "frame": frame_name,
        "overall": report.overall.value,
        "converged": (
            result.solver_result.converged
            if result.solver_result is not None else False
        ),
        "deflection_mm": round(result.deflection_mm, 6),
        "deflection_limit_mm": result.deflection_limit_mm,
        "max_joint_utilization": _max_joint_utilization(result.rows),
        **_member_summary(frame, result.solver_result),
        "outputs": outputs,
    }
    return summary


def run_cases(
    spec_path: str | Path = DEFAULT_SPEC,
    *,
    case_ids: set[str] | None = None,
    output_root: str | Path | None = None,
    render_plots: bool = True,
) -> dict[str, Any]:
    """Run selected load cases from the YAML spec and write summary.json."""
    spec = load_spec(spec_path)
    defaults = dict(spec.get("defaults") or {})
    root = _repo_path(output_root or defaults["output_root"])
    selected = []
    for case in spec["load_cases"]:
        if case_ids is not None and case["id"] not in case_ids:
            continue
        selected.append(case)
    if case_ids is not None:
        missing = sorted(case_ids - {case["id"] for case in selected})
        if missing:
            raise ValueError(f"unknown load case id(s): {', '.join(missing)}")

    root.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "m3_fea_load_case_results.v0.1",
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "spec_path": str(Path(spec_path)),
        "output_root": str(root),
        "load_cases": [
            run_case(case, defaults, root, render_plots=render_plots)
            for case in selected
        ],
    }
    summary_path = root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n",
                            encoding="utf-8")
    summary["summary_json"] = str(summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run M3-CRETE light FEA load cases."
    )
    parser.add_argument("--spec", default=str(DEFAULT_SPEC),
                        help="Load-case YAML path.")
    parser.add_argument("--case", action="append", default=None,
                        help="Run one load-case id. Repeatable.")
    parser.add_argument("--output-root", default=None,
                        help="Override the spec output_root.")
    parser.add_argument("--no-plots", action="store_true",
                        help="Skip stress/strain PNG generation.")
    args = parser.parse_args(argv)

    summary = run_cases(
        args.spec,
        case_ids=set(args.case) if args.case else None,
        output_root=args.output_root,
        render_plots=not args.no_plots,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
