"""Generate the one-off M3 ZPMM motor-mount spacer correction.

This is a deliberately narrow M3-CRETE exception to CADCLAW's default
"place authored parts, do not author plates" rule. The user-confirmed ZPMM
geometry is correct, but the current exported STEP uses 5mm through-holes.
For the M3 reference test kit we import that STEP and derive a copy with:

- the original outline and spindle opening preserved,
- the same four NEMA-23 motor-hole locations enlarged to 6mm, and
- the six 6mm C-Beam end-alignment holes added in the blank rail-side
  portion, using the asymmetric C-Beam screw-port pattern.

Do not generalize this script into CADCLAW core. It exists so this custom
M3 spacer can be used consistently by the assembly harness.
"""
from __future__ import annotations

from pathlib import Path

import cadquery as cq


ROOT = Path(__file__).resolve().parent
SOURCE_PATH = ROOT.parents[2] / "M3-CRETE" / "CAD" / "ZPMM.step"
OUT_DIR = ROOT / "generated"
OUT_PATH = OUT_DIR / "ZPMM_6p1_motor_mount_spacer_6mm_holes.step"

WIDTH_X_MM = 80.0
HEIGHT_Y_MM = 97.0
THICKNESS_MM = 6.1

# Fitted from the user-confirmed ZPMM.step faceted hole loops after recentering
# the source bounding box. The spindle opening is preserved from the source STEP;
# its center is recorded here only as a regression note.
SPINDLE_CENTER = (-0.591, -19.674)
SPINDLE_DIAMETER_MM = 44.0
NEMA23_BODY_WIDTH_MM = 56.4
MOTOR_HOLE_DIAMETER_MM = 6.0
MOTOR_HOLE_CENTERS = [
    (-24.170, -43.270),
    (22.970, -43.270),
    (-24.170, 3.870),
    (22.970, 3.870),
]

# C-Beam 4080 end-drill clearance holes. The matching C-Beam STEP carries
# six screw-port centerlines at:
#   (-10,+30), (+10,+30), (-10,+10), (-10,-10), (-10,-30), (+10,-30)
# in its native 40 x 80 end profile. The open channel removes the two
# symmetric middle holes on the +X side; keep that asymmetry instead of
# inventing a rectangular four-hole pattern.
#
# The ZPMM blank rail-side area is 80mm wide, so rotate the C-Beam profile
# 90 degrees into the plate plane. Its 40mm profile height is placed so the
# NEMA 23 motor body's rail-side face rests on the 4080 extrusion envelope.
# This gives the motor body a mechanical support/thermal path instead of
# asking the printed spacer plate to cantilever the motor by itself.
CBEAM_HOLE_DIAMETER_MM = 6.0
CBEAM_PROFILE_HALF_HEIGHT_MM = 20.0
CBEAM_PROFILE_CENTER_Y_MM = (
    SPINDLE_CENTER[1] + (NEMA23_BODY_WIDTH_MM / 2.0) + CBEAM_PROFILE_HALF_HEIGHT_MM
)
CBEAM_HOLE_CENTERS = [
    (30.0, CBEAM_PROFILE_CENTER_Y_MM - 10.0),
    (30.0, CBEAM_PROFILE_CENTER_Y_MM + 10.0),
    (10.0, CBEAM_PROFILE_CENTER_Y_MM - 10.0),
    (-10.0, CBEAM_PROFILE_CENTER_Y_MM - 10.0),
    (-30.0, CBEAM_PROFILE_CENTER_Y_MM - 10.0),
    (-30.0, CBEAM_PROFILE_CENTER_Y_MM + 10.0),
]


def load_centered_source() -> cq.Workplane:
    source = cq.importers.importStep(str(SOURCE_PATH)).val()
    bb = source.BoundingBox()
    centered = source.translate(
        (
            -((bb.xmin + bb.xmax) / 2.0),
            -((bb.ymin + bb.ymax) / 2.0),
            -((bb.zmin + bb.zmax) / 2.0),
        )
    )
    return cq.Workplane("XY").add(centered)


def build_zpmm() -> cq.Workplane:
    plate = load_centered_source()
    cut_points = [*MOTOR_HOLE_CENTERS, *CBEAM_HOLE_CENTERS]
    diameters = [
        *([MOTOR_HOLE_DIAMETER_MM] * len(MOTOR_HOLE_CENTERS)),
        *([CBEAM_HOLE_DIAMETER_MM] * len(CBEAM_HOLE_CENTERS)),
    ]
    for (x, y), diameter in zip(cut_points, diameters):
        cutter = (
            cq.Workplane("XY")
            .center(x, y)
            .circle(diameter / 2.0)
            .extrude(THICKNESS_MM + 2.0)
            .translate((0.0, 0.0, -(THICKNESS_MM / 2.0) - 1.0))
        )
        plate = plate.cut(cutter)
    return plate


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    part = build_zpmm()
    cq.exporters.export(part, str(OUT_PATH))
    # Normalize line endings/trailing whitespace for stable local diffs.
    lines = OUT_PATH.read_text(encoding="utf-8").splitlines()
    OUT_PATH.write_text(
        "\n".join(line.rstrip() for line in lines) + "\n",
        encoding="utf-8",
    )
    print(OUT_PATH.as_posix())


if __name__ == "__main__":
    main()
