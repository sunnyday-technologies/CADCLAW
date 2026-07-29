"""One-time authoring script for the relative-placement example parts.

CADCLAW does not generate geometry at build time: it places parts you authored
in real CAD. This example still needs parts to place, so this script authors
three simple stand-ins ONCE and writes them to `parts/`. The STEP files are
committed; you do not need to run this. Treat `parts/*.step` exactly as you
would treat an export from Fusion, Rhino, or SolidWorks.

Run only if you want to regenerate them:

    python examples/relative_placement/make_parts.py

Geometry (all boxes, corner at the local origin):

    rail_x.step   600 x 40 x 40   the datum rail
    plate.step     10 x 120 x 120 the mounting plate
    rail_y.step    40 x 400 x 40  the gantry rail
"""
from pathlib import Path

import cadquery as cq

PARTS = Path(__file__).parent / "parts"

# (name, x_mm, y_mm, z_mm)
SHAPES = [
    ("rail_x", 600.0, 40.0, 40.0),
    ("plate", 10.0, 120.0, 120.0),
    ("rail_y", 40.0, 400.0, 40.0),
]


def main() -> None:
    PARTS.mkdir(parents=True, exist_ok=True)
    for name, dx, dy, dz in SHAPES:
        # centered=False puts the box corner at the local origin, so the
        # connector-frame origins in connectors.yaml are easy to read off.
        solid = cq.Workplane("XY").box(dx, dy, dz, centered=False)
        out = PARTS / f"{name}.step"
        cq.exporters.export(solid, str(out))
        print(f"wrote {out} ({dx} x {dy} x {dz} mm)")


if __name__ == "__main__":
    main()
