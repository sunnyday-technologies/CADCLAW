"""
Frame solver abstraction — swappable FEA backend for CADCLAW gates.

The CADCLAW kinematics gate calls a `FrameSolver`, never PyniteFEA
directly. This keeps the gate logic backend-agnostic so a CalculiX
backend can be dropped in for printed-concrete member gates (solid
elements) without touching gate code.

    solver = PyniteSolver()
    result = solver.solve(frame_model, load_case)

`PyniteSolver` is the default and the only backend implemented in
Phase 1 — it covers 3D beam/frame problems completely (point loads,
distributed loads, moment loads, fixed/pinned supports, member
shear/moment/deflection). `CalculiXSolver` is a declared-but-unbuilt
stub: it raises `NotImplementedError` so the abstraction is exercised
and the future seam is explicit.

PyniteFEA is pure Python (numpy + scipy) — install with
`pip install PyniteFEA` (the core, NOT the `[all]` extra; `[all]`
only adds VTK-based visualization the gate never uses).
"""
from __future__ import annotations

import math
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List

from .frame_model import FrameModel, LoadCase

_SINGULAR_HINT = (
    "stiffness matrix is singular — the frame has an unrestrained "
    "rigid-body mode. The most common cause is a straight run of "
    "colinear members with no twist restraint: restrain rotation "
    "about the member axis (rx) at one support."
)


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------
@dataclass
class MemberResult:
    """Per-member peak demands from a solved load case.

    Moments are bending moments in N·m; `peak_moment_Nm` is the larger
    absolute value across the two bending axes, anywhere along the
    member. Deflection is the peak absolute transverse displacement in
    millimetres. `moment_z_at_i` / `moment_z_at_j` are the strong-axis
    moments at the i- and j-node ends (useful for end-release checks).
    """
    member_id: str
    length_m: float
    peak_moment_z_Nm: float
    peak_moment_y_Nm: float
    peak_moment_Nm: float
    peak_deflection_mm: float
    moment_z_at_i_Nm: float
    moment_z_at_j_Nm: float


@dataclass
class SolverResult:
    """Outcome of one `FrameSolver.solve` call."""
    solver_name: str
    converged: bool
    load_case: str
    member_results: Dict[str, MemberResult] = field(default_factory=dict)
    node_reactions: Dict[str, Dict[str, float]] = field(default_factory=dict)
    max_deflection_mm: float = 0.0
    notes: List[str] = field(default_factory=list)

    def member(self, member_id: str) -> MemberResult:
        return self.member_results[member_id]


# --------------------------------------------------------------------------
# Solver abstraction
# --------------------------------------------------------------------------
class FrameSolver(ABC):
    """Abstract 3D frame solver. Backends implement `solve`."""

    name: str = "abstract"

    @abstractmethod
    def solve(self, model: FrameModel, loads: LoadCase) -> SolverResult:
        """Solve `model` under `loads` and return peak member demands."""
        raise NotImplementedError


class PyniteSolver(FrameSolver):
    """PyniteFEA backend — linear-elastic 3D frame analysis.

    Phase 1 runs a first-order linear static analysis (no P-Δ): the
    M3-CRETE gantry carries a transverse printhead load with negligible
    axial compression, so geometric stiffness barely moves the result.
    P-Δ is a Phase-2 option for the splice/column load paths.
    """

    name = "PyniteFEA"

    def solve(self, model: FrameModel, loads: LoadCase) -> SolverResult:
        try:
            from Pynite import FEModel3D
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ImportError(
                "PyniteFEA is required for PyniteSolver. Install the core "
                "package with `pip install PyniteFEA` (not the [all] extra)."
            ) from exc

        problems = model.validate()
        if problems:
            raise ValueError("frame model is not solvable: " + "; ".join(problems))

        fe = FEModel3D()

        for n in model.nodes.values():
            fe.add_node(n.id, n.x, n.y, n.z)

        # Materials + sections, deduplicated by name.
        seen_mat: set = set()
        seen_sec: set = set()
        for m in model.members.values():
            mat, sec = m.material, m.section
            if mat.name not in seen_mat:
                fe.add_material(mat.name, mat.E, mat.shear_modulus,
                                mat.nu, mat.rho, fy=mat.fy)
                seen_mat.add(mat.name)
            if sec.name not in seen_sec:
                fe.add_section(sec.name, sec.A, sec.Iy, sec.Iz, sec.J)
                seen_sec.add(sec.name)
            fe.add_member(m.id, m.i_node, m.j_node, mat.name, sec.name)

        for s in model.supports.values():
            fe.def_support(s.node_id, s.dx, s.dy, s.dz, s.rx, s.ry, s.rz)

        case = loads.name
        for pl in loads.point_loads:
            fe.add_node_load(pl.node_id, pl.direction, pl.value, case=case)

        if loads.self_weight:
            for m in model.members.values():
                w = m.material.rho * m.section.A * loads.gravity  # N/m, magnitude
                # Gravity acts in the negative direction of gravity_dir.
                fe.add_member_dist_load(m.id, loads.gravity_dir, -w, -w, case=case)

        fe.add_load_combo(case, {case: 1.0})

        notes: List[str] = []
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                fe.analyze(check_statics=False, sparse=True)
            if any("singular" in str(w.message).lower() for w in caught):
                notes.append(_SINGULAR_HINT)
                return SolverResult(solver_name=self.name, converged=False,
                                    load_case=case, notes=notes)
        except Exception as exc:  # solver instability, singular matrix, etc.
            notes.append(f"analysis did not converge: {exc}")
            return SolverResult(solver_name=self.name, converged=False,
                                load_case=case, notes=notes)

        member_results: Dict[str, MemberResult] = {}
        global_max_defl = 0.0
        for m in model.members.values():
            fm = fe.members[m.id]
            length = fm.L()
            mz_max = fm.max_moment("Mz", case)
            mz_min = fm.min_moment("Mz", case)
            my_max = fm.max_moment("My", case)
            my_min = fm.min_moment("My", case)
            peak_mz = max(abs(mz_max), abs(mz_min))
            peak_my = max(abs(my_max), abs(my_min))
            dy_max = fm.max_deflection("dy", case)
            dy_min = fm.min_deflection("dy", case)
            dz_max = fm.max_deflection("dz", case)
            dz_min = fm.min_deflection("dz", case)
            peak_defl_m = max(abs(dy_max), abs(dy_min), abs(dz_max), abs(dz_min))
            peak_defl_mm = peak_defl_m * 1000.0
            global_max_defl = max(global_max_defl, peak_defl_mm)
            member_results[m.id] = MemberResult(
                member_id=m.id,
                length_m=float(length),
                peak_moment_z_Nm=float(peak_mz),
                peak_moment_y_Nm=float(peak_my),
                peak_moment_Nm=float(max(peak_mz, peak_my)),
                peak_deflection_mm=float(peak_defl_mm),
                moment_z_at_i_Nm=float(fm.moment("Mz", 0.0, case)),
                moment_z_at_j_Nm=float(fm.moment("Mz", length, case)),
            )

        node_reactions: Dict[str, Dict[str, float]] = {}
        for s in model.supports.values():
            node = fe.nodes[s.node_id]
            node_reactions[s.node_id] = {
                "FX": float(node.RxnFX[case]), "FY": float(node.RxnFY[case]),
                "FZ": float(node.RxnFZ[case]), "MX": float(node.RxnMX[case]),
                "MY": float(node.RxnMY[case]), "MZ": float(node.RxnMZ[case]),
            }

        # Belt-and-suspenders: a singular solve can slip through as NaN
        # results without a warning. Treat any non-finite value as a
        # non-converged solve rather than reporting garbage demands.
        finite = all(
            math.isfinite(v)
            for mr in member_results.values()
            for v in (mr.peak_moment_Nm, mr.peak_deflection_mm)
        ) and all(
            math.isfinite(v)
            for rxn in node_reactions.values() for v in rxn.values()
        )
        if not finite:
            notes.append(_SINGULAR_HINT)
            return SolverResult(solver_name=self.name, converged=False,
                                load_case=case, notes=notes)

        return SolverResult(
            solver_name=self.name,
            converged=True,
            load_case=case,
            member_results=member_results,
            node_reactions=node_reactions,
            max_deflection_mm=float(global_max_defl),
            notes=notes,
        )


class CalculiXSolver(FrameSolver):
    """CalculiX backend — reserved for printed-concrete solid-element gates.

    Not implemented in Phase 1. The M3-CRETE frame is a beam-frame
    problem (extrusion members, bolted joints) that PyniteFEA solves
    completely; CalculiX is the right tool only for solid-element
    stress distribution across a printed concrete member's cross
    section — a separate gate. This stub keeps the swap seam explicit.
    """

    name = "CalculiX"

    def solve(self, model: FrameModel, loads: LoadCase) -> SolverResult:
        raise NotImplementedError(
            "CalculiXSolver is a Phase-2+ backend reserved for printed-"
            "concrete solid-element analysis. Use PyniteSolver for the "
            "M3-CRETE beam-frame kinematics gate."
        )
