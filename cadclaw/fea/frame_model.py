"""
Frame model — solver-agnostic description of a 3D beam frame.

This module holds *only* the structural idealization: nodes, members,
supports, materials, sections, and a load case. It knows nothing about
PyniteFEA, CalculiX, or STEP files. A `FrameSolver` consumes a
`FrameModel` + `LoadCase` and returns a `SolverResult`.

Units are SI throughout and must stay consistent:
    length  metres (m)
    force   newtons (N)
    moment  newton-metres (N·m)
    stress  pascals (Pa)
    E, G    pascals (Pa)
    I, J    m^4      A   m^2      rho   kg/m^3

Coordinate convention: global +Y is vertical (up). Gravity and the
printhead load act along -Y. This matches the load-case defaults in
`LoadCase`; if a future assembly uses a different vertical axis, set
`LoadCase.gravity_dir` accordingly rather than rotating the model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


g = 9.80665  # m/s^2 — standard gravity


# --------------------------------------------------------------------------
# Material + section
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Material:
    """Isotropic linear-elastic material.

    `fy` is the yield strength used to derive a member's allowable
    moment in the joint-adequacy gate. `G` defaults to the isotropic
    relation E / (2 (1 + nu)) when not given.
    """
    name: str
    E: float                       # Young's modulus, Pa
    nu: float                      # Poisson's ratio
    rho: float                     # density, kg/m^3
    fy: float                      # yield strength, Pa
    G: Optional[float] = None      # shear modulus, Pa (derived if None)

    @property
    def shear_modulus(self) -> float:
        return self.G if self.G is not None else self.E / (2.0 * (1.0 + self.nu))

    @classmethod
    def aluminum_6061_t6(cls) -> "Material":
        """6061-T6 aluminum.

        E = 68.9 GPa, nu = 0.33, rho = 2700 kg/m^3, fy = 276 MPa
        (40 ksi minimum yield, the Aluminum Association value for
        6061-T6 in thicknesses up to ~25 mm).
        """
        return cls(name="6061-T6", E=68.9e9, nu=0.33, rho=2700.0, fy=276e6)

    @classmethod
    def aluminum_6063_t5(cls) -> "Material":
        """6063-T5 aluminum — the OpenBuilds V-Slot extrusion alloy.

        E = 68.9 GPa, nu = 0.33, rho = 2700 kg/m^3, fy = 145 MPa
        (typical 6063-T5 extruded tensile yield; alloy temper spread is
        wide — confirm against the extrusion supplier's mill data. The
        joint-adequacy gate flags this in its confidence budget).
        """
        return cls(name="6063-T5", E=68.9e9, nu=0.33, rho=2700.0, fy=145e6)


@dataclass(frozen=True)
class Section:
    """Beam cross-section properties about the local axes.

    Local axis convention follows PyniteFEA: the member's local x runs
    i-node -> j-node; bending about local z uses `Iz`, bending about
    local y uses `Iy`. `Sz` / `Sy` are the elastic section moduli used
    to convert a bending moment to an extreme-fibre stress.
    """
    name: str
    A: float       # area, m^2
    Iy: float      # second moment about local y, m^4
    Iz: float      # second moment about local z, m^4
    J: float       # torsion constant, m^4
    Sz: float      # section modulus about local z, m^3
    Sy: float      # section modulus about local y, m^3

    @classmethod
    def rectangular(cls, name: str, width: float, height: float) -> "Section":
        """Solid rectangular bar — `width` along local y, `height` along local z.

        For a flat bar standing on edge (height >> width), local z is the
        strong bending axis. `J` uses the standard closed-form torsion
        constant for a solid rectangle (Roark), accurate for any aspect
        ratio; for a thin bar it converges to (1/3)·long·short^3.
        """
        b, h = float(width), float(height)
        A = b * h
        Iz = b * h ** 3 / 12.0
        Iy = h * b ** 3 / 12.0
        Sz = b * h ** 2 / 6.0
        Sy = h * b ** 2 / 6.0
        long_s, short_s = (h, b) if h >= b else (b, h)
        r = short_s / long_s
        J = long_s * short_s ** 3 * (1.0 / 3.0 - 0.21 * r * (1.0 - r ** 4 / 12.0))
        return cls(name=name, A=A, Iy=Iy, Iz=Iz, J=J, Sz=Sz, Sy=Sy)

    @classmethod
    def vslot_4080(cls, name: str = "vslot_4080",
                   strong_axis_vertical: bool = True) -> "Section":
        """OpenBuilds V-Slot 4080 (40 x 80 mm) aluminium extrusion.

        Published profile properties (OpenBuilds / Systeal data sheet):
            cross-section area              742 mm^2
            I about the 80 mm (strong) axis 53.16e4 mm^4
            I about the 40 mm (weak) axis   11.22e4 mm^4

        With `strong_axis_vertical` (default) the 80 mm dimension is the
        bending depth — local z is the strong axis, the orientation a
        gantry X-beam uses to resist the vertical printhead load.

        `J` is approximated as Iy + Iz. Torsion is not a governing
        quantity for the symmetric vertical load case; the gate's
        confidence budget records the approximation.
        """
        A = 742e-6                       # m^2
        i_strong = 53.16e4 * 1e-12       # mm^4 -> m^4
        i_weak = 11.22e4 * 1e-12
        c_strong = 0.080 / 2.0           # extreme-fibre distance, strong
        c_weak = 0.040 / 2.0             # extreme-fibre distance, weak
        if strong_axis_vertical:
            Iz, Iy, cz, cy = i_strong, i_weak, c_strong, c_weak
        else:
            Iz, Iy, cz, cy = i_weak, i_strong, c_weak, c_strong
        return cls(name=name, A=A, Iy=Iy, Iz=Iz, J=Iy + Iz,
                   Sz=Iz / cz, Sy=Iy / cy)


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Node:
    """A frame node. Coordinates in metres."""
    id: str
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Support:
    """A support / restraint at a node.

    Each flag True = that degree of freedom is restrained. A *pinned*
    support restrains the three translations and frees the three
    rotations — the idealization the M3-CRETE bolt-through and T-bolt
    joints get (the extrusion bends before the fastener assembly does,
    so the connection is treated as a translation-only restraint).
    """
    node_id: str
    dx: bool = True
    dy: bool = True
    dz: bool = True
    rx: bool = False
    ry: bool = False
    rz: bool = False

    @classmethod
    def pinned(cls, node_id: str) -> "Support":
        return cls(node_id, dx=True, dy=True, dz=True, rx=False, ry=False, rz=False)

    @classmethod
    def fixed(cls, node_id: str) -> "Support":
        return cls(node_id, dx=True, dy=True, dz=True, rx=True, ry=True, rz=True)


@dataclass(frozen=True)
class Member:
    """A prismatic beam member between two nodes."""
    id: str
    i_node: str
    j_node: str
    material: Material
    section: Section


@dataclass(frozen=True)
class Joint:
    """A named connection location the joint-adequacy gate reports on.

    `node_id` references the frame node at the connection. `joint_type`
    is descriptive only (e.g. ``bolt_through_m5``, ``tbolt_xframe``) —
    it is echoed into the CSV but does not change the analysis, because
    Phase 1 models every connection as a translation-restraining
    (pinned) joint and checks the *extrusion*, not the fastener.
    """
    id: str
    node_id: str
    joint_type: str = "bolt_through_m5"


@dataclass(frozen=True)
class PointLoad:
    """A concentrated load or moment applied at a node.

    `direction` is one of FX/FY/FZ (force, N) or MX/MY/MZ (moment, N·m),
    global axes. A downward printhead load is FY with a negative `value`.
    """
    node_id: str
    direction: str
    value: float


@dataclass
class LoadCase:
    """A single static load case.

    `point_loads` are explicit nodal loads. When `self_weight` is True
    the solver adds each member's distributed self-weight
    (rho · A · g) along `gravity_dir`. Phase 1 runs exactly one load
    case; the kinematic travel sweep is deferred to Phase 2.
    """
    name: str = "service"
    point_loads: List[PointLoad] = field(default_factory=list)
    self_weight: bool = True
    gravity_dir: str = "FY"   # global axis self-weight acts along
    gravity: float = g        # magnitude of g, m/s^2 (sign from gravity below)

    def add_point_load(self, node_id: str, direction: str, value: float) -> None:
        self.point_loads.append(PointLoad(node_id, direction, value))


# --------------------------------------------------------------------------
# Frame model
# --------------------------------------------------------------------------
@dataclass
class FrameModel:
    """A complete frame: nodes, members, supports, and named joints.

    Built programmatically (see `cadclaw.fea.m3_frame`) or, in Phase 2,
    from STEP centerline extraction. Loads live in a separate
    `LoadCase` so the same model can be re-solved under different cases.
    """
    name: str = "frame"
    nodes: Dict[str, Node] = field(default_factory=dict)
    members: Dict[str, Member] = field(default_factory=dict)
    supports: Dict[str, Support] = field(default_factory=dict)
    joints: Dict[str, Joint] = field(default_factory=dict)

    # -- builders -----------------------------------------------------------
    def add_node(self, id: str, x: float, y: float, z: float) -> Node:
        n = Node(id, float(x), float(y), float(z))
        self.nodes[id] = n
        return n

    def add_member(self, id: str, i_node: str, j_node: str,
                   material: Material, section: Section) -> Member:
        for nid in (i_node, j_node):
            if nid not in self.nodes:
                raise KeyError(f"member {id!r} references undefined node {nid!r}")
        m = Member(id, i_node, j_node, material, section)
        self.members[id] = m
        return m

    def add_support(self, support: Support) -> Support:
        if support.node_id not in self.nodes:
            raise KeyError(f"support references undefined node {support.node_id!r}")
        self.supports[support.node_id] = support
        return support

    def add_joint(self, id: str, node_id: str,
                  joint_type: str = "bolt_through_m5") -> Joint:
        if node_id not in self.nodes:
            raise KeyError(f"joint {id!r} references undefined node {node_id!r}")
        j = Joint(id, node_id, joint_type)
        self.joints[id] = j
        return j

    # -- queries ------------------------------------------------------------
    def members_at_node(self, node_id: str) -> List[Member]:
        """Members incident to `node_id` (either end)."""
        return [m for m in self.members.values()
                if m.i_node == node_id or m.j_node == node_id]

    def member_length(self, member_id: str) -> float:
        m = self.members[member_id]
        a, b = self.nodes[m.i_node], self.nodes[m.j_node]
        return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))

    def validate(self) -> List[str]:
        """Return a list of structural-setup problems (empty == ok)."""
        problems: List[str] = []
        if not self.members:
            problems.append("model has no members")
        if not self.supports:
            problems.append("model has no supports — frame is unrestrained")
        for mid in self.members:
            if self.member_length(mid) <= 0.0:
                problems.append(f"member {mid!r} has zero length")
        for j in self.joints.values():
            if not self.members_at_node(j.node_id):
                problems.append(f"joint {j.id!r} sits on node "
                                f"{j.node_id!r} with no members")
        return problems
