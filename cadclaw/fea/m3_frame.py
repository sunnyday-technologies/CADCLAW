"""
M3-CRETE X-gantry frame model — authored structural idealization.

Phase 1 has no STEP centerline extraction (that is Phase 2), so the
M3-CRETE X-gantry beam is idealized here from the confirmed build
geometry. This is an *analysis idealization*, not generated CAD — it
places no parts and produces no geometry; it only describes nodes and
beam members for the FEA gate.

Confirmed geometry (per Nick, 2026-05-16):

    X-gantry beam : OpenBuilds V-Slot 4080 extrusion, 80 x 40 mm
                    profile, 2000 mm long, single continuous member.
    orientation   : 80 mm dimension vertical — strong axis resists the
                    vertical printhead load.
    alloy         : analyzed as 6061-T6. CADCLAW standardizes every
                    frame extrusion on 6061-T6 — the per-supplier alloy
                    and temper are not known at design time, and 6061-T6
                    is the common structural-extrusion baseline.
    supports      : the two Y-axis carriages at the beam ends. They
                    clamp the extrusion, so they restrain all three
                    translations and twist (rx) about the beam axis,
                    while leaving the bending rotations free — a
                    pinned-but-twist-held support. One end frees the
                    axial DOF so the run is not axially locked.

No splice: the handoff's mid-span splice plate applied to a 1 m
factory-cut flat bar. The X-gantry is now a single 2000 mm extrusion,
so the model carries one uniform section end to end.

Vertical axis is global Y; gravity and the printhead load act -Y.

Supersedes an earlier idealization that used a 1/4" x 3" 6061-T6 flat
bar with a 16" splice doubler — that section (and the handoff's
δ ≈ 0.44 mm anchor tied to it) does not match the V-Slot 4080 build.
"""
from __future__ import annotations

from .frame_model import FrameModel, Material, Section, Support

# --- confirmed geometry ----------------------------------------------------
SPAN_M = 2.0
MIDSPAN_M = SPAN_M / 2.0

# M3-2 reference-assembly centerline coordinates. The CAD assembly uses
# X/Y/Z in mm, with Z vertical. The FEA model uses X/Y/Z in metres, with
# +Y vertical, so CAD Z maps to FEA Y and CAD Y maps to FEA Z.
M3_2_X_LEFT_M = -1.04
M3_2_X_MID_M = 0.0
M3_2_X_RIGHT_M = 1.04
M3_2_FRONT_M = -0.503
M3_2_MID_DEPTH_M = 0.0
M3_2_BACK_M = 0.503
M3_2_BOTTOM_M = 0.02
M3_2_CARRIAGE_M = 0.42
M3_2_TOP_M = 0.98


def m3_xgantry_frame() -> FrameModel:
    """Build the M3-CRETE X-gantry `FrameModel` (no loads — see LoadCase).

    Three nodes along X: the two carriage ends and the midspan
    printhead node (named ``printhead`` so the gate finds the load
    point automatically). Two members, both the V-Slot 4080 section.

    Joints reported by the gate:
        carriage_left / carriage_right — T-bolt X-frame anchors
        printhead                      — the midspan printhead carriage
    """
    al = Material.aluminum_6061_t6()
    beam = Section.vslot_4080("xbeam_4080", strong_axis_vertical=True)

    m = FrameModel(name="m3_xgantry")
    m.add_node("carriage_L", 0.0, 0.0, 0.0)
    m.add_node("printhead", MIDSPAN_M, 0.0, 0.0)
    m.add_node("carriage_R", SPAN_M, 0.0, 0.0)

    m.add_member("seg_L", "carriage_L", "printhead", al, beam)
    m.add_member("seg_R", "printhead", "carriage_R", al, beam)

    # Carriages clamp the beam: restrain translations + twist (rx),
    # leave bending rotations free. Right end frees axial X.
    m.add_support(Support("carriage_L", dx=True, dy=True, dz=True, rx=True))
    m.add_support(Support("carriage_R", dx=False, dy=True, dz=True, rx=True))

    m.add_joint("carriage_left", "carriage_L", joint_type="tbolt_xframe")
    m.add_joint("printhead", "printhead", joint_type="printhead_carriage")
    m.add_joint("carriage_right", "carriage_R", joint_type="tbolt_xframe")
    return m


def m3_2_frame() -> FrameModel:
    """Build the M3-2 full-machine beam-frame idealization.

    This is the Phase-1 "light FEA" companion to
    ``examples/m3_crete/m3_reference_assembly.yaml``. It includes the
    structural centerlines needed for an initial PyNiteFEA solve:

    * four Z posts split at the moving Y-gantry carriage height;
    * top X rails, top side rails, and bottom side rails;
    * the two Y gantries;
    * the 2 m X gantry and printhead node.

    It is intentionally not STEP auto-extraction and not solid-element
    analysis. The 6.1 mm ZPMM spacer/plate stack is collapsed to shared
    joint nodes, which is adequate for first-pass frame-member decision
    support but not a replacement for local spacer/mount stress analysis.
    """
    al = Material.aluminum_6061_t6()
    beam = Section.vslot_4080("m3_2_cbeam_4080", strong_axis_vertical=True)

    m = FrameModel(name="m3_2_frame")

    xs = {
        "L": M3_2_X_LEFT_M,
        "C": M3_2_X_MID_M,
        "R": M3_2_X_RIGHT_M,
    }
    zs = {
        "F": M3_2_FRONT_M,
        "M": M3_2_MID_DEPTH_M,
        "B": M3_2_BACK_M,
    }
    ys = {
        "bottom": M3_2_BOTTOM_M,
        "carriage": M3_2_CARRIAGE_M,
        "top": M3_2_TOP_M,
    }

    def node_id(x_key: str, depth_key: str, height_key: str) -> str:
        return f"{x_key}_{depth_key}_{height_key}"

    def add_node(x_key: str, depth_key: str, height_key: str) -> None:
        m.add_node(
            node_id(x_key, depth_key, height_key),
            xs[x_key], ys[height_key], zs[depth_key],
        )

    def add_member(mid: str, a: str, b: str) -> None:
        m.add_member(mid, a, b, al, beam)

    # Four posts, split at carriage height so the moving Y-gantry load path
    # can enter the Z posts where the carriage plates ride.
    for x_key in ("L", "R"):
        for depth_key in ("F", "B"):
            for height_key in ("bottom", "carriage", "top"):
                add_node(x_key, depth_key, height_key)
            base = node_id(x_key, depth_key, "bottom")
            carriage = node_id(x_key, depth_key, "carriage")
            top = node_id(x_key, depth_key, "top")
            add_member(f"post_{x_key}{depth_key}_lower", base, carriage)
            add_member(f"post_{x_key}{depth_key}_upper", carriage, top)
            m.add_support(Support.fixed(base))
            m.add_joint(f"z_post_{x_key}{depth_key}_base", base,
                        joint_type="fixed_base_idealization")
            m.add_joint(f"z_post_{x_key}{depth_key}_carriage", carriage,
                        joint_type="z_carriage_plate_stack")
            m.add_joint(f"z_post_{x_key}{depth_key}_top", top,
                        joint_type="frame_corner")

    # Top frame X rails: two 1000 mm stock members per front/back run, with
    # a center splice node. There are no bottom X members in this open-frame
    # reference design.
    for depth_key in ("F", "B"):
        add_node("C", depth_key, "top")
        add_member(
            f"top_x_{depth_key}_left",
            node_id("L", depth_key, "top"),
            node_id("C", depth_key, "top"),
        )
        add_member(
            f"top_x_{depth_key}_right",
            node_id("C", depth_key, "top"),
            node_id("R", depth_key, "top"),
        )
        m.add_joint(f"top_x_{depth_key}_splice", node_id("C", depth_key, "top"),
                    joint_type="top_rail_splice")

    # Top side rails at left, center, and right; bottom side rails only at
    # left and right, matching the open-frame assembly spec.
    for x_key in ("L", "C", "R"):
        add_member(
            f"top_side_{x_key}",
            node_id(x_key, "F", "top"),
            node_id(x_key, "B", "top"),
        )
    for x_key in ("L", "R"):
        add_member(
            f"bottom_side_{x_key}",
            node_id(x_key, "F", "bottom"),
            node_id(x_key, "B", "bottom"),
        )

    # Y gantries at carriage height, split at the X-gantry handoff point.
    for x_key in ("L", "R"):
        add_node(x_key, "M", "carriage")
        add_member(
            f"y_gantry_{x_key}_front",
            node_id(x_key, "F", "carriage"),
            node_id(x_key, "M", "carriage"),
        )
        add_member(
            f"y_gantry_{x_key}_back",
            node_id(x_key, "M", "carriage"),
            node_id(x_key, "B", "carriage"),
        )
        m.add_joint(f"x_to_y_handoff_{x_key}", node_id(x_key, "M", "carriage"),
                    joint_type="x_plate_to_y_gantry")

    # X gantry and printhead load node.
    m.add_node("printhead", M3_2_X_MID_M, M3_2_CARRIAGE_M, M3_2_MID_DEPTH_M)
    add_member("x_gantry_left", node_id("L", "M", "carriage"), "printhead")
    add_member("x_gantry_right", "printhead", node_id("R", "M", "carriage"))
    m.add_joint("printhead", "printhead", joint_type="printhead_carriage")

    return m
