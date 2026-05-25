"""Fast review render of the built STEP, matching the grader's coloring.

The grader's review views (the good earlier renders) pass NO label/color
override to the renderer, so it uses the STEP's embedded per-part colors -- the
compiler writes those from each instance's ``color_label`` (extrusions black,
wheels/pulleys/idlers green, plates metal-grey, motors grey). An explicit sig
label map has priority over the embedded colors and washes parts out, so we
deliberately don't pass one here. Renders the existing build STEP (no rebuild).

  .venv\\Scripts\\python.exe examples\\m3_crete\\quick_render.py side iso front
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from cadclaw.render import render_step_to_png  # noqa: E402

STEP = REPO / "examples/m3_crete/build/m3_reference_round1.step"
OUT = REPO / "examples/m3_crete/build/views"

views = sys.argv[1:] or ["side", "iso", "front"]
for v in views:
    out = OUT / f"_check_{v}.png"
    render_step_to_png(str(STEP), str(out), width=1500, height=950, view=v)
    print("rendered", out)
