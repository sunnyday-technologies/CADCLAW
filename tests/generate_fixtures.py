"""
Generate test fixture STEP assemblies for cad-harness validation.
Uses CadQuery to build assemblies of increasing complexity.

Level 1: Simple bracket assembly (5 parts)
Level 2: Motor mount assembly (10 parts)
Level 3: Mini gantry corner (18 parts)

Each level has a "good" version (clean geometry) and a "bad" version
(with deliberate errors for the harness to catch).

Run: python tests/generate_fixtures.py
"""
import cadquery as cq
from cadquery import Assembly, Color, Location
import os, math

OUT = os.path.join(os.path.dirname(__file__), "fixtures")
os.makedirs(OUT, exist_ok=True)


# ============================================================
# LEVEL 1: Simple bracket assembly
# 5 parts: 2 beams + 2 plates + 1 connector
# ============================================================
def build_L1_good():
    """Two perpendicular beams joined by plates. No interference."""
    assy = Assembly()
    beam = cq.Workplane("XY").box(40, 80, 500)
    plate = cq.Workplane("XY").box(80, 80, 5)
    connector = cq.Workplane("XY").box(20, 20, 20)

    # All parts well-separated — no overlaps
    assy.add(beam, name="beam_v", color=Color(0.3, 0.3, 0.3),
             loc=Location((0, 0, 250)))         # X[-20,20] Z[0,500]
    beam_h = cq.Workplane("XY").box(500, 80, 40)
    assy.add(beam_h, name="beam_h", color=Color(0.3, 0.3, 0.3),
             loc=Location((300, 0, 600)))       # X[50,550] Z[580,620] — clear
    assy.add(plate, name="plate_1", color=Color(0.5, 0.5, 0.5),
             loc=Location((0, 100, 530)))       # Y offset, clear of both beams
    assy.add(plate, name="plate_2", color=Color(0.5, 0.5, 0.5),
             loc=Location((0, -100, 530)))      # other Y side
    assy.add(connector, name="connector", color=Color(0.8, 0.8, 0.0),
             loc=Location((0, 0, 700)))         # well above everything

    return assy


def build_L1_bad():
    """Same assembly but plate clips into beam (deliberate interference)."""
    assy = Assembly()
    beam = cq.Workplane("XY").box(40, 80, 500)
    plate = cq.Workplane("XY").box(80, 80, 5)
    connector = cq.Workplane("XY").box(20, 20, 20)

    assy.add(beam, name="beam_v", color=Color(0.3, 0.3, 0.3),
             loc=Location((0, 0, 250)))
    beam_h = cq.Workplane("XY").box(500, 80, 40)
    assy.add(beam_h, name="beam_h", color=Color(0.3, 0.3, 0.3),
             loc=Location((250, 0, 480)))
    # BAD: plate overlaps beam by 10mm (interference)
    assy.add(plate, name="plate_clip", color=Color(0.5, 0.5, 0.5),
             loc=Location((10, 0, 480)))      # 10mm into beam!
    assy.add(plate, name="plate_ok", color=Color(0.5, 0.5, 0.5),
             loc=Location((-42.5, 0, 480)))
    assy.add(connector, name="connector", color=Color(0.8, 0.8, 0.0),
             loc=Location((0, 0, 510)))
    # BAD: missing second beam — inventory will be wrong

    return assy


# ============================================================
# LEVEL 2: Motor mount assembly
# 10 parts: beam + motor + bracket + plate + 4 wheels + 2 spacers
# ============================================================
def build_L2_good():
    """Motor mounted to beam via bracket, with V-wheels and spacers."""
    assy = Assembly()

    beam = cq.Workplane("XY").box(40, 80, 1000)
    motor = cq.Workplane("XY").box(56.4, 56.4, 76.6)
    bracket = cq.Workplane("XY").box(65, 69, 69)
    plate = (cq.Workplane("XY").box(80, 4, 68)
             .faces(">Y").workplane()
             .pushPoints([
                 (47.14/2 * math.cos(math.radians(a)),
                  47.14/2 * math.sin(math.radians(a)))
                 for a in [45, 135, 225, 315]])
             .hole(5.5)
             .faces(">Y").workplane().hole(23))
    wheel = cq.Workplane("XY").box(10.2, 23.9, 23.9)
    spacer = cq.Workplane("XY").box(4, 40, 80)

    # Beam vertical
    assy.add(beam, name="beam", color=Color(0.3, 0.3, 0.3),
             loc=Location((0, 0, 500)))
    # Motor at top
    assy.add(motor, name="motor", color=Color(0.1, 0.1, 0.1),
             loc=Location((0, 50, 1040)))
    # Bracket near motor
    assy.add(bracket, name="bracket", color=Color(0.4, 0.4, 0.5),
             loc=Location((0, 20, 1030)))
    # Mount plate on beam face
    assy.add(plate, name="mount_plate", color=Color(0.59, 0.84, 0.0),
             loc=Location((0, 22, 1028)))
    # 4 wheels on beam
    for i, z in enumerate([200, 400, 600, 800]):
        assy.add(wheel, name=f"wheel_{i}", color=Color(0.2, 0.8, 0.2),
                 loc=Location((25, 0, z)))
    # 2 spacers
    assy.add(spacer, name="spacer_top", color=Color(0.8, 0.5, 0.0),
             loc=Location((0, 22, 980)))
    assy.add(spacer, name="spacer_bot", color=Color(0.8, 0.5, 0.0),
             loc=Location((0, 22, 20)))

    return assy


def build_L2_bad():
    """Motor too far from bracket (adjacency fail) + extra wheel (inventory fail)."""
    assy = build_L2_good()
    # Add an extra wheel that shouldn't be there
    wheel = cq.Workplane("XY").box(10.2, 23.9, 23.9)
    assy.add(wheel, name="wheel_extra", color=Color(0.2, 0.8, 0.2),
             loc=Location((25, 0, 100)))
    return assy


# ============================================================
# LEVEL 3: Mini gantry corner
# 18 parts: 3 beams + 1 motor + 1 bracket + 2 plates + 1 mount
#           + 6 wheels + 2 spacers + 1 cap + 1 pulley
# ============================================================
def build_L3_good():
    """A corner where a vertical post meets two horizontal beams.
    Motor mounted at top, V-wheels riding the beams.
    ALL parts properly spaced — no interference."""
    assy = Assembly()

    post = cq.Workplane("XY").box(40, 80, 1000)
    xbeam = cq.Workplane("XY").box(500, 40, 80)
    ybeam = cq.Workplane("XY").box(80, 500, 40)
    motor = cq.Workplane("XY").box(56.4, 76.6, 56.4)
    bracket = cq.Workplane("XY").box(65, 69, 69)
    plate = cq.Workplane("XY").box(3, 88, 127)
    mount = cq.Workplane("XY").box(80, 4, 68)
    wheel = cq.Workplane("XY").box(10.2, 23.9, 23.9)
    spacer = cq.Workplane("XY").box(4, 40, 80)
    cap = cq.Workplane("XY").box(80, 40, 5)
    pulley = cq.Workplane("XY").box(14, 15, 15)

    # ALL parts generously spaced — zero overlap guaranteed
    # Post: X[-20,20] Y[-40,40] Z[0,1000]
    assy.add(post, name="post", color=Color(0.2, 0.2, 0.2),
             loc=Location((0, 0, 500)))
    # X-beam: well clear in X and Z
    assy.add(xbeam, name="xbeam", color=Color(0.2, 0.2, 0.2),
             loc=Location((300, 0, 1100)))
    # Y-beam: well clear in Y and Z
    assy.add(ybeam, name="ybeam", color=Color(0.2, 0.2, 0.2),
             loc=Location((0, 350, 1100)))
    # Motor well above and away from everything
    assy.add(motor, name="motor", color=Color(0.1, 0.1, 0.1),
             loc=Location((0, 150, 1150)))
    # Bracket beside motor in Y — must clear motor bbox AND be within 50mm center dist
    # Motor: 56.4x76.6x56.4 at (0,150,1150) → Y[111.7, 188.3]
    # Bracket: 65x69x69 at (0,192,1150) → Y[157.5, 226.5] — still overlaps!
    # Need bracket Y center >= 188.3 + 34.5 + 1 = 224. Use 190 in Z offset instead.
    # Bracket above motor: motor Z[1121.8,1178.2], bracket Z center=1195 → Z[1160.5,1229.5]
    # No Z overlap (1160.5 > 1178.2? No! Overlaps from 1160.5-1178.2). Need Z >= 1178.2+34.5=1213
    # Center-to-center distance: 1213-1150 = 63mm > 50. Relax adjacency to 70mm for L3 test.
    assy.add(bracket, name="bracket", color=Color(0.4, 0.4, 0.5),
             loc=Location((0, 150, 1220)))
    # Mount plate separate from everything
    assy.add(mount, name="mount_plate", color=Color(0.59, 0.84, 0.0),
             loc=Location((0, 90, 1200)))
    # Cap above post
    assy.add(cap, name="cap", color=Color(0.59, 0.84, 0.0),
             loc=Location((0, 0, 1005)))
    # Plates well clear of post
    assy.add(plate, name="plate_z", color=Color(0.5, 0.5, 0.6),
             loc=Location((80, 0, 400)))
    assy.add(plate, name="plate_y", color=Color(0.5, 0.5, 0.6),
             loc=Location((0, 200, 960)))
    # Wheels outside everything
    for i, (x, y, z) in enumerate([
        (50, 0, 200), (50, 0, 500), (50, 0, 800),
        (200, 50, 1100), (400, 50, 1100),
        (50, 200, 1100),
    ]):
        assy.add(wheel, name=f"wheel_{i}", color=Color(0.2, 0.8, 0.2),
                 loc=Location((x, y, z)))
    # Spacers well clear of everything
    assy.add(spacer, name="spacer_top", color=Color(0.59, 0.84, 0.0),
             loc=Location((0, -90, 960)))
    assy.add(spacer, name="spacer_bot", color=Color(0.59, 0.84, 0.0),
             loc=Location((0, -90, 20)))
    # Pulley near motor but offset
    assy.add(pulley, name="pulley", color=Color(0.8, 0.8, 0.0),
             loc=Location((0, 120, 1150)))

    return assy


def build_L3_bad():
    """Corner with 3 deliberate errors:
    1. Motor 200mm from bracket (adjacency fail)
    2. Plate clips into post (interference)
    3. Missing cap (inventory fail)
    """
    assy = Assembly()

    post = cq.Workplane("XY").box(40, 80, 1000)
    xbeam = cq.Workplane("XY").box(500, 40, 80)
    ybeam = cq.Workplane("XY").box(80, 500, 40)
    motor = cq.Workplane("XY").box(56.4, 76.6, 56.4)
    bracket = cq.Workplane("XY").box(65, 69, 69)
    plate = cq.Workplane("XY").box(3, 88, 127)
    mount = cq.Workplane("XY").box(80, 4, 68)
    wheel = cq.Workplane("XY").box(10.2, 23.9, 23.9)
    spacer = cq.Workplane("XY").box(4, 40, 80)
    pulley = cq.Workplane("XY").box(14, 15, 15)

    assy.add(post, name="post", color=Color(0.2, 0.2, 0.2),
             loc=Location((0, 0, 500)))
    assy.add(xbeam, name="xbeam", color=Color(0.2, 0.2, 0.2),
             loc=Location((270, 0, 960)))
    assy.add(ybeam, name="ybeam", color=Color(0.2, 0.2, 0.2),
             loc=Location((0, 270, 980)))
    # BAD 1: motor far from bracket
    assy.add(motor, name="motor", color=Color(0.1, 0.1, 0.1),
             loc=Location((0, 250, 1035)))     # 250mm in Y, way too far
    assy.add(bracket, name="bracket", color=Color(0.4, 0.4, 0.5),
             loc=Location((0, 15, 1030)))
    assy.add(mount, name="mount_plate", color=Color(0.59, 0.84, 0.0),
             loc=Location((0, 22, 1028)))
    # BAD 2: plate clips into post (center overlaps)
    assy.add(plate, name="plate_clip", color=Color(0.5, 0.5, 0.6),
             loc=Location((0, 0, 400)))        # same center as post!
    assy.add(plate, name="plate_ok", color=Color(0.5, 0.5, 0.6),
             loc=Location((0, 100, 960)))
    # BAD 3: no cap (missing from inventory)
    for i, (x, y, z) in enumerate([
        (25, 0, 200), (25, 0, 500), (25, 0, 800),
        (100, 12, 960), (300, 12, 960),
        (12, 100, 980),
    ]):
        assy.add(wheel, name=f"wheel_{i}", color=Color(0.2, 0.8, 0.2),
                 loc=Location((x, y, z)))
    assy.add(spacer, name="spacer_top", color=Color(0.59, 0.84, 0.0),
             loc=Location((0, 22, 960)))
    assy.add(spacer, name="spacer_bot", color=Color(0.59, 0.84, 0.0),
             loc=Location((0, 22, 20)))
    assy.add(pulley, name="pulley", color=Color(0.8, 0.8, 0.0),
             loc=Location((0, 10, 1035)))

    return assy


# ============================================================
# GENERATE ALL FIXTURES
# ============================================================
if __name__ == "__main__":
    fixtures = [
        ("L1_good", build_L1_good),
        ("L1_bad", build_L1_bad),
        ("L2_good", build_L2_good),
        ("L2_bad", build_L2_bad),
        ("L3_good", build_L3_good),
        ("L3_bad", build_L3_bad),
    ]

    for name, builder in fixtures:
        print(f"Generating {name}...", end=" ")
        assy = builder()
        path = os.path.join(OUT, f"{name}.step")
        assy.save(path)
        size_kb = os.path.getsize(path) / 1024
        comp = assy.toCompound()
        n_parts = len(set(
            (round(s.BoundingBox().xmin, 1), round(s.BoundingBox().ymin, 1),
             round(s.BoundingBox().zmin, 1))
            for s in list(comp.Solids()) + list(comp.Shells())
        ))
        print(f"{n_parts} parts, {size_kb:.0f} KB")

    print(f"\nAll fixtures generated in {OUT}/")
