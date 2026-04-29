"""
Generate the v0.9 gate sandbox — a synthetic STEP that exercises
orientation, floating-part, and cluster gates with known seeded issues.

Run: python tests/generate_v09_sandbox.py

Output:
  tests/fixtures/v09_sandbox/v09_assembly.step
  tests/fixtures/v09_sandbox/cadclaw.yaml

The assembly is intentionally small (~12 parts) but contains:

- **Two correctly-oriented brackets** (5 × 30 × 30) on a cbeam — orientation
  gate sees `expected_face: YZ` and these pass.
- **One MISORIENTED bracket** (rotated 90° about Z) — orientation gate
  flags as `cad.misoriented` with a `rotate 90° about Z` suggested fix.
- **Two correctly-attached idlers** sitting on brackets — floating gate
  sees them within 5mm of structural and passes.
- **One FLOATING idler** placed 200mm from anything — floating gate flags
  as `cad.floating_part` with a "move toward nearest cbeam" suggestion.
- **A spatially-distinct hardware cluster** at one end — cluster gate
  groups it as a single region.

Tests in `tests/test_v09_sandbox.py` consume these fixtures and assert
the gates produce the seeded findings.
"""
import os
from pathlib import Path

import cadquery as cq
from cadquery import Assembly, Color, Location


OUT = Path(__file__).parent / "fixtures" / "v09_sandbox"
OUT.mkdir(parents=True, exist_ok=True)


def build_v09_assembly():
    """Build the sandbox assembly with seeded v0.9 gate issues."""
    assy = Assembly()

    # Structural cbeam — anchor for everything except the floating idler.
    # Long axis = X. bbox = (1000, 40, 80).
    cbeam = cq.Workplane("XY").box(1000.0, 40.0, 80.0)
    assy.add(cbeam, name="cbeam_main", color=Color(0.3, 0.3, 0.3),
             loc=Location((500.0, 0.0, 40.0)))   # X=[0,1000] Y=[-20,20] Z=[0,80]

    # Plate (also structural per the rule file).
    plate = cq.Workplane("XY").box(40.0, 80.0, 4.0)
    assy.add(plate, name="plate_anchor", color=Color(0.5, 0.5, 0.5),
             loc=Location((100.0, 0.0, 84.0)))   # sits on +Z face of cbeam

    # ---- Two CORRECTLY-ORIENTED idler_brackets -----------------------------
    # Spec: sig (5, 30, 30), expected_face: YZ → thinnest axis must be X.
    # bracket_thin_x has 5mm along X → CORRECT.
    bracket_correct_1 = cq.Workplane("XY").box(5.0, 30.0, 30.0)
    assy.add(bracket_correct_1, name="bracket_ok_1", color=Color(0, 0.6, 0),
             loc=Location((250.0, 0.0, 100.0)))  # touches cbeam top face

    bracket_correct_2 = cq.Workplane("XY").box(5.0, 30.0, 30.0)
    assy.add(bracket_correct_2, name="bracket_ok_2", color=Color(0, 0.6, 0),
             loc=Location((400.0, 0.0, 100.0)))

    # ---- One MISORIENTED idler_bracket ------------------------------------
    # Same sorted sig (5, 30, 30) but rotated so 5mm axis is along Y.
    # Orientation gate must flag this.
    bracket_misorient = cq.Workplane("XY").box(30.0, 5.0, 30.0)
    assy.add(bracket_misorient, name="bracket_BAD", color=Color(0.6, 0, 0),
             loc=Location((600.0, 0.0, 100.0)))  # touches cbeam top face

    # ---- Two CORRECTLY-ATTACHED idlers ------------------------------------
    # Sit on top of the brackets, well within max_gap_mm of the cbeam.
    idler_attached_1 = cq.Workplane("XY").box(12.7, 22.0, 22.0)
    assy.add(idler_attached_1, name="idler_ok_1", color=Color(0, 0, 0.7),
             loc=Location((250.0, 0.0, 130.0)))

    idler_attached_2 = cq.Workplane("XY").box(12.7, 22.0, 22.0)
    assy.add(idler_attached_2, name="idler_ok_2", color=Color(0, 0, 0.7),
             loc=Location((400.0, 0.0, 130.0)))

    # ---- One FLOATING idler -----------------------------------------------
    # Placed far from any cbeam/plate — floating gate must flag it.
    idler_floating = cq.Workplane("XY").box(12.7, 22.0, 22.0)
    assy.add(idler_floating, name="idler_FLOATING", color=Color(0.7, 0, 0),
             loc=Location((1500.0, 500.0, 500.0)))

    # ---- Cluster of small hardware at one end -----------------------------
    # 4 small parts grouped together touching cbeam top face — cluster
    # gate should produce one cluster of 4. Z=82.5 puts nut bottom at
    # Z=80, exactly touching cbeam top.
    for i, x in enumerate([20.0, 30.0, 40.0, 50.0]):
        nut = cq.Workplane("XY").box(8.0, 8.0, 5.0)
        assy.add(nut, name=f"nut_{i}", color=Color(0.4, 0.4, 0.4),
                 loc=Location((x, 0.0, 82.5)))   # touches cbeam top

    return assy


def write_starter_yaml() -> str:
    return """# v0.9 sandbox rule file. Drives integration tests in
# tests/test_v09_sandbox.py against tests/fixtures/v09_sandbox/v09_assembly.step.
schema_version: "0.9"

meta:
  project: v09_sandbox
  step: tests/fixtures/v09_sandbox/v09_assembly.step

# Two structural labels (legacy 3-tuple form), one orientation-aware
# label (v0.9 LabelSpec form), two attached/floating candidates.
labels:
  cbeam:
    sig: [40.0, 80.0, 1000.0]
  plate_anchor:
    sig: [4.0, 40.0, 80.0]
  idler_bracket:
    sig: [5.0, 30.0, 30.0]
    expected_face: YZ          # largest face in YZ → thinnest axis must be X
    expected_against: cbeam
    max_gap_mm: 5.0
  idler:
    sig: [12.7, 22.0, 22.0]
  nut:
    sig: [5.0, 8.0, 8.0]

belt_heuristic: false

expected_inventory:
  cbeam: 1
  plate_anchor: 1
  idler_bracket: 3
  idler: 3
  nut: 4

# v0.9 gate #3: cbeam, plate, and idler_bracket are anchors. The two
# correctly-attached idlers sit on top of the brackets (within max_gap),
# so they pass; the floating idler at (1500, 500, 500) is far from
# everything → flagged.
floating_check:
  structural_labels: [cbeam, plate_anchor, idler_bracket]
  exempt_labels: [belt]
  max_gap_mm: 5.0
"""


def main() -> int:
    assy = build_v09_assembly()
    step_path = OUT / "v09_assembly.step"
    assy.save(str(step_path))
    print(f"  wrote {step_path}")

    yaml_path = OUT / "cadclaw.yaml"
    yaml_path.write_text(write_starter_yaml(), encoding="utf-8")
    print(f"  wrote {yaml_path}")

    print()
    print("Sandbox assembly seeded with these issues for the v0.9 gates:")
    print("  - 1 misoriented idler_bracket (orientation gate must flag)")
    print("  - 1 floating idler (floating gate must flag)")
    print("  - 1 cluster of 4 nuts (cluster gate must group)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
