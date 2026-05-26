"""Render the multi-view reference images of the M3 target for the kit.

Renders the canonical full assembly from a non-canonical 3/4 overview plus
front/top/side orthographic views, with CADCLAW's own renderer, so a blind driver
can compare its build against the same neutral, dimensionless renders, and so the
only variable is interpretation. The primary overview is deliberately NOT an
isometric: it shows every unique component position (mirrored ones implied) while
discouraging the driver from gaming a clean iso projection via 2D matching instead
of 3D reasoning.

These show the target's *arrangement*, not its transforms or coordinates -- a
picture of the goal, like a human builder gets from an assembly photo. They carry
no dimensions and no spec, so they stay inside the benchmark fairness wall.

Build the source STEP first (writes examples/m3_crete/build/m3_reference_round1.step):

  .venv/Scripts/python.exe benchmarks/m3_ai_assembly/scripts/run_grader.py \\
    --spec examples/m3_crete/m3_reference_assembly.yaml --no-dry-run \\
    --no-render-views --out build/_ref_build_report.json

then run this script.
"""
from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from cadclaw.render import DEFAULT_COLOR_MAP, render_step_to_png  # noqa: E402

SRC = REPO_ROOT / "examples" / "m3_crete" / "build" / "m3_reference_round1.step"
OUT_DIR = REPO_ROOT / "benchmarks" / "m3_ai_assembly" / "assets" / "reference"
# (name, preset, azimuth_deg, elevation_deg). "overview" is a deliberately
# non-canonical 3/4 (front swung + tilted) -- all unique component positions
# visible, but not an iso the driver could 2D-match instead of reasoning in 3D.
VIEWS = [
    ("overview", "front", -35.0, 12.0),
    ("front", "front", 0.0, 0.0),
    ("top", "top", 0.0, 0.0),
    ("side", "side", 0.0, 0.0),
]

# bbox dim-signature (sorted, rounded 0.1) -> semantic label, so the renderer
# colors the drive train and carriage distinctly from the black frame. Without
# this the dark-grey steppers read as black against the black extrusions.
LABELS = {
    (40.0, 80.0, 1000.0): "cbeam",
    (20.0, 80.0, 1000.0): "vslot_2080",
    (20.0, 40.0, 1000.0): "vslot_2040",
    (5.0, 33.2, 1996.0): "cbeam",
    (10.2, 23.9, 23.9): "vwheel",
    (14.0, 15.0, 15.0): "pulley",
    (12.7, 22.0, 22.0): "idler",
    (3.0, 88.0, 127.0): "plate",
    (6.0, 125.0, 125.0): "plate",
    (56.4, 56.4, 76.6): "motor",
    (6.1, 80.0, 97.0): "shim",
    (6.0, 40.0, 80.0): "shim",
    (1.5, 6.0, 942.5): "belt",
    (1.5, 6.0, 957.6): "belt",
}
# Lift the stepper color so motors are visible against the black extrusions.
COLOR_MAP = {**DEFAULT_COLOR_MAP, "motor": (0.42, 0.50, 0.60)}


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"source STEP missing: {SRC}\n(build it first -- see this file's docstring)")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, preset, az, el in VIEWS:
        out = OUT_DIR / f"reference_{name}.png"
        render_step_to_png(
            str(SRC), str(out), view=preset, azimuth=az, elevation=el,
            width=1600, height=1200, labels=LABELS, color_map=COLOR_MAP,
            use_step_colors=False,
            background_top=(1.0, 1.0, 1.0), background_bottom=(1.0, 1.0, 1.0),
        )
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
