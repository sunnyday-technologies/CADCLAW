"""
cadclaw.fea — structural frame FEA for CADCLAW kinematics gates.

A small, pure-Python frame-analysis layer: a solver-agnostic frame model,
a swappable `FrameSolver` backend (PyniteFEA by default), and the
`kinematics_joint_adequacy` gate that evaluates aluminium extrusion
adequacy at named joint locations.

Phase 1 scope (single static load case):
    from cadclaw.fea import kinematics_joint_adequacy
    from cadclaw.fea.m3_frame import m3_xgantry_frame

    model = m3_xgantry_frame()
    rows = kinematics_joint_adequacy(frame=model, load_n=49.0)
    for r in rows:
        print(r["joint_id"], r["utilization"], r["result"])

The kinematic travel sweep ("true kinetics") and STEP auto-extraction
are deferred to Phase 2 — see joint_adequacy.py / frame_extract.py.
"""
from .frame_model import (
    FrameModel, Material, Section, Node, Member, Support, Joint,
    PointLoad, LoadCase,
)
from .solver import FrameSolver, PyniteSolver, CalculiXSolver, SolverResult, MemberResult
from .joint_adequacy import (
    kinematics_joint_adequacy, evaluate_joint_adequacy,
    JointAdequacyResult, write_joint_csv,
    joint_adequacy_findings, joint_adequacy_report,
)
from .m3_frame import m3_2_frame, m3_xgantry_frame
from .visualize import (
    member_demand_envelopes, render_member_maps, write_member_demand_csv,
)

__all__ = [
    "FrameModel", "Material", "Section", "Node", "Member", "Support", "Joint",
    "PointLoad", "LoadCase",
    "FrameSolver", "PyniteSolver", "CalculiXSolver", "SolverResult", "MemberResult",
    "kinematics_joint_adequacy", "evaluate_joint_adequacy",
    "JointAdequacyResult", "write_joint_csv",
    "joint_adequacy_findings", "joint_adequacy_report",
    "m3_xgantry_frame", "m3_2_frame",
    "member_demand_envelopes", "render_member_maps", "write_member_demand_csv",
]
