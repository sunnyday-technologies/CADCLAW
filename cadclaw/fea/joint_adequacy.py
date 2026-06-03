"""
kinematics_joint_adequacy — CADCLAW gate for M3-CRETE frame adequacy.

Evaluates whether aluminium frame extrusions are adequate at named
joint locations under a static printhead load. Per the M3-CRETE
connection model, every joint (M5 bolt-through, and T-bolt on the 2 m
X-frame members) is idealized as a translation-restraining *pinned*
joint: the aluminium extrusion bends before the fastener assembly
yields, so the governing limit is the **extrusion section capacity**,
not a fastener allowable.

For each joint the gate reports:
    max_moment_Nm  peak bending moment in any extrusion incident to the
                   joint, anywhere along that member
    allowable_Nm   that member's section capacity, fy/SF · S
    utilization    max_moment_Nm / allowable_Nm
    result         pass (<0.8) | warn (0.8-1.0) | fail (>1.0)

Allowables are computed from material + cross-section by default; pass
an `allowables` dict to override specific joints (e.g. a connection
that genuinely *is* fastener-governed).

Phase 1 scope: single static load case. The kinematic travel sweep
(`sweep=True`) and STEP auto-extraction (`step_file`) are deferred to
Phase 2 and raise `NotImplementedError` until then.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..findings import ConfidenceBudget, Finding, Report, Severity
from .frame_model import FrameModel, LoadCase
from .solver import FrameSolver, PyniteSolver, SolverResult

# Utilization thresholds (spec): pass < 0.8, 0.8-1.0 warn, > 1.0 fail.
WARN_THRESHOLD = 0.8
FAIL_THRESHOLD = 1.0

DEFAULT_SAFETY_FACTOR = 1.65   # Default bending safety factor.
DEFAULT_DEFLECTION_LIMIT_MM = 0.5


def _classify(utilization: float) -> str:
    if utilization > FAIL_THRESHOLD:
        return "fail"
    if utilization >= WARN_THRESHOLD:
        return "warn"
    return "pass"


@dataclass
class JointAdequacyResult:
    """Full outcome of a joint-adequacy evaluation.

    `rows` is the spec's `list[dict]` gate output (also what
    `kinematics_joint_adequacy` returns directly). The remaining fields
    carry the deflection check and provenance the CLI / harness surface
    alongside it.
    """
    rows: List[dict] = field(default_factory=list)
    deflection_mm: float = 0.0
    deflection_limit_mm: float = DEFAULT_DEFLECTION_LIMIT_MM
    deflection_result: str = "pass"
    solver_result: Optional[SolverResult] = None
    safety_factor: float = DEFAULT_SAFETY_FACTOR
    assumptions: List[str] = field(default_factory=list)
    not_checked: List[str] = field(default_factory=list)

    @property
    def overall(self) -> str:
        """Worst result across all joints and the deflection check."""
        order = {"pass": 0, "unverified": 1, "warn": 2, "fail": 3}
        worst = max([order[self.deflection_result]]
                    + [order.get(r["result"], 1) for r in self.rows],
                    default=0)
        return {v: k for k, v in order.items()}[worst]

    @property
    def passed(self) -> bool:
        return self.overall != "fail"


def _resolve_load_case(frame: FrameModel, load_case: Optional[LoadCase],
                       load_n: float, load_node: Optional[str],
                       self_weight: bool, gravity_dir: str) -> LoadCase:
    """Build the static load case, or validate a caller-supplied one."""
    if load_case is not None:
        return load_case
    if load_node is None:
        if "printhead" in frame.nodes:
            load_node = "printhead"
        else:
            raise ValueError(
                "load_node not given and no node named 'printhead' exists; "
                "specify which node the printhead load applies to."
            )
    if load_node not in frame.nodes:
        raise KeyError(f"load_node {load_node!r} is not a node in the frame")
    lc = LoadCase(name="service", self_weight=self_weight, gravity_dir=gravity_dir)
    # Printhead load acts downward — negative along the vertical (gravity) axis.
    lc.add_point_load(load_node, gravity_dir, -abs(load_n))
    return lc


def evaluate_joint_adequacy(
    frame: FrameModel,
    *,
    load_case: Optional[LoadCase] = None,
    load_n: float = 49.0,
    load_node: Optional[str] = None,
    allowables: Optional[Dict[str, float]] = None,
    safety_factor: float = DEFAULT_SAFETY_FACTOR,
    deflection_limit_mm: float = DEFAULT_DEFLECTION_LIMIT_MM,
    self_weight: bool = True,
    gravity_dir: str = "FY",
    solver: Optional[FrameSolver] = None,
) -> JointAdequacyResult:
    """Run the static load case and evaluate every joint in `frame`.

    Returns a `JointAdequacyResult`. See `kinematics_joint_adequacy`
    for the thin spec-shaped wrapper that returns `result.rows`.
    """
    solver = solver or PyniteSolver()
    allowables = dict(allowables or {})
    lc = _resolve_load_case(frame, load_case, load_n, load_node,
                            self_weight, gravity_dir)

    sr = solver.solve(frame, lc)
    result = JointAdequacyResult(
        solver_result=sr,
        safety_factor=safety_factor,
        deflection_limit_mm=deflection_limit_mm,
    )
    result.assumptions.append(
        f"every joint idealized as a pinned (translation-restraining) "
        f"connection; allowable moment = fy / {safety_factor:g} x section "
        f"modulus of the governing extrusion material/section (the extrusion is "
        f"assumed to yield before the fastener assembly)"
    )
    if not lc.self_weight:
        result.not_checked.append("member self-weight (disabled for this run)")

    if not sr.converged:
        result.not_checked.append("FEA did not converge — no joint results")
        result.deflection_result = "unverified"
        return result

    if not frame.joints:
        result.not_checked.append("no joints defined on the frame model")

    for joint in frame.joints.values():
        incident = frame.members_at_node(joint.node_id)
        explicit = allowables.get(joint.id)

        best = None  # (utilization, moment, allowable, axis, member_id)
        for m in incident:
            mr = sr.member_results.get(m.id)
            if mr is None:
                continue
            sigma_allow = m.material.fy / safety_factor
            for axis, moment, modulus in (
                ("z", mr.peak_moment_z_Nm, m.section.Sz),
                ("y", mr.peak_moment_y_Nm, m.section.Sy),
            ):
                cap = explicit if explicit is not None else sigma_allow * modulus
                if cap <= 0:
                    continue
                util = moment / cap
                if best is None or util > best[0]:
                    best = (util, moment, cap, axis, m.id)

        if best is None:
            row = {
                "joint_id": joint.id,
                "joint_type": joint.joint_type,
                "max_moment_Nm": 0.0,
                "allowable_Nm": 0.0,
                "utilization": 0.0,
                "result": "unverified",
            }
            result.not_checked.append(
                f"joint {joint.id!r}: no member capacity available")
        else:
            util, moment, cap, axis, mid = best
            row = {
                "joint_id": joint.id,
                "joint_type": joint.joint_type,
                "max_moment_Nm": round(moment, 3),
                "allowable_Nm": round(cap, 3),
                "utilization": round(util, 4),
                "result": _classify(util),
            }
            if explicit is not None:
                result.assumptions.append(
                    f"joint {joint.id!r}: allowable overridden to "
                    f"{explicit:g} Nm by caller")
        result.rows.append(row)

    result.deflection_mm = sr.max_deflection_mm
    result.deflection_result = (
        "fail" if sr.max_deflection_mm > deflection_limit_mm else "pass")
    return result


def kinematics_joint_adequacy(
    frame: Optional[FrameModel] = None,
    *,
    step_file: Optional[str] = None,
    load_n: float = 49.0,
    sweep: bool = False,
    allowables: Optional[Dict[str, float]] = None,
    load_node: Optional[str] = None,
    load_case: Optional[LoadCase] = None,
    safety_factor: float = DEFAULT_SAFETY_FACTOR,
    deflection_limit_mm: float = DEFAULT_DEFLECTION_LIMIT_MM,
    self_weight: bool = True,
    gravity_dir: str = "FY",
    solver: Optional[FrameSolver] = None,
    csv_path: Optional[str] = None,
) -> List[dict]:
    """CADCLAW gate `kinematics_joint_adequacy` — spec-shaped entry point.

    Returns the per-joint `list[dict]` defined in the handoff spec:
    ``{joint_id, joint_type, max_moment_Nm, allowable_Nm, utilization,
    result}``. When `csv_path` is given, also writes that table to CSV.

    Phase 1 requires `frame` (an authored `FrameModel`). `step_file`
    (STEP centerline auto-extraction) and `sweep` (kinematic travel
    sweep) are Phase 2 and raise `NotImplementedError`.
    """
    if sweep:
        raise NotImplementedError(
            "the kinematic travel sweep is a Phase-2 feature; Phase 1 "
            "evaluates a single static load position. Call with sweep=False."
        )
    if frame is None:
        if step_file is not None:
            raise NotImplementedError(
                "STEP centerline auto-extraction is a Phase-2 feature; "
                "Phase 1 takes an authored FrameModel via `frame=`. See "
                "cadclaw.fea.m3_frame for the M3-CRETE X-gantry model."
            )
        raise ValueError("kinematics_joint_adequacy requires `frame=` (Phase 1)")

    result = evaluate_joint_adequacy(
        frame, load_case=load_case, load_n=load_n, load_node=load_node,
        allowables=allowables, safety_factor=safety_factor,
        deflection_limit_mm=deflection_limit_mm, self_weight=self_weight,
        gravity_dir=gravity_dir, solver=solver,
    )
    if csv_path:
        write_joint_csv(result.rows, csv_path)
    return result.rows


_SEVERITY = {
    "pass": Severity.PASS,
    "warn": Severity.WARN,
    "fail": Severity.FAIL,
    "unverified": Severity.WARN,
}


def joint_adequacy_findings(result: JointAdequacyResult) -> List[Finding]:
    """Adapt a `JointAdequacyResult` to CADCLAW `Finding` objects.

    Emits a finding only for joints that warn / fail / are unverified,
    plus one for the deflection check — matching the convention of the
    other gates (passing checks produce no finding).
    """
    out: List[Finding] = []
    for row in result.rows:
        verdict = row["result"]
        if verdict == "pass":
            continue
        sev = _SEVERITY.get(verdict, Severity.WARN)
        if verdict == "unverified":
            out.append(Finding(
                id="kinematics.joint_unverified",
                category="kinematics",
                severity=sev,
                message=(f"joint {row['joint_id']}: no extrusion capacity "
                         f"available — adequacy not evaluated"),
                suggested_fix=("Ensure a member with a defined section and "
                               "material yield strength is incident to this "
                               "joint, or supply an explicit allowable."),
                evidence=dict(row),
            ))
            continue
        out.append(Finding(
            id="kinematics.joint_overstress",
            category="kinematics",
            severity=sev,
            message=(f"joint {row['joint_id']} ({row['joint_type']}): "
                     f"moment {row['max_moment_Nm']:.1f} Nm vs allowable "
                     f"{row['allowable_Nm']:.1f} Nm, "
                     f"utilization {row['utilization']:.2f} ({verdict})"),
            suggested_fix=(
                "Reduce span or load at this joint, increase the extrusion "
                "section modulus, or add a doubler. Utilization is moment / "
                "(fy / safety_factor x section modulus)."),
            evidence=dict(row),
        ))

    if result.deflection_result == "fail":
        out.append(Finding(
            id="kinematics.deflection_exceeded",
            category="kinematics",
            severity=Severity.FAIL,
            message=(f"frame deflection {result.deflection_mm:.3f} mm exceeds "
                     f"limit {result.deflection_limit_mm:.3f} mm"),
            suggested_fix=("Stiffen the span (deeper section, shorter span, "
                           "or mid-span support) or raise the deflection "
                           "limit if the print process tolerates it."),
            evidence={"deflection_mm": round(result.deflection_mm, 4),
                      "limit_mm": result.deflection_limit_mm},
        ))
    elif result.deflection_result == "unverified":
        out.append(Finding(
            id="kinematics.deflection_unverified",
            category="kinematics",
            severity=Severity.WARN,
            message="frame deflection not evaluated — FEA did not converge",
            evidence={},
        ))
    return out


def joint_adequacy_report(result: JointAdequacyResult) -> Report:
    """Build a full CADCLAW `Report` (findings + confidence budget)."""
    findings = joint_adequacy_findings(result)
    budget = ConfidenceBudget(
        checked=[
            "frame deflection under the static load case",
            "aluminium extrusion bending capacity at each named joint",
        ],
        not_checked=list(result.not_checked) + [
            "kinematic travel sweep (printhead position swept across "
            "gantry travel) -- Phase 2",
            "fastener pull-out / shear / preload -- joints modeled as "
            "pinned, the extrusion is assumed to govern",
            "P-Delta and other geometric nonlinearity",
            "member buckling and lateral-torsional stability",
            "fatigue / cyclic loading",
            "stress concentration at bolt holes and connection details",
            "torsion constant J of the extrusion (approximated; not a "
            "governing quantity under the symmetric vertical load case)",
            "6061-T6 yield strength (assumed 276 MPa typical -- confirm "
            "against the extrusion supplier's mill data)",
        ],
        assumptions=list(result.assumptions),
    )
    sr = result.solver_result
    report = Report(
        findings=findings,
        confidence_budget=budget,
        meta={
            "gate": "kinematics_joint_adequacy",
            "solver": sr.solver_name if sr else None,
            "converged": sr.converged if sr else False,
            "deflection_mm": round(result.deflection_mm, 4),
            "deflection_limit_mm": result.deflection_limit_mm,
            "safety_factor": result.safety_factor,
            "joints": len(result.rows),
        },
    )
    report.overall = report.compute_overall()
    return report


def write_joint_csv(rows: List[dict], path: str) -> None:
    """Write joint-adequacy rows to CSV with the spec column order."""
    cols = ["joint_id", "joint_type", "max_moment_Nm",
            "allowable_Nm", "utilization", "result"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in cols})
