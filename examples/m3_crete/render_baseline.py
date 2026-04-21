"""Render the canonical M3-CRETE radial-explode + 360 spin GIF from the
authoritative Fusion export (X-axis in tall orientation, X-gantry
carriage present, top T-plate connector, all brackets).

One GIF now — the sequential disassembly variant was dropped; the
radial explode + camera spin communicates the same thing in 15 s of
render vs 10 min and is cleaner visually.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

STEP = r"Y:/SunnydayTech/M3-CRETE/CAD/M3-2_Assembly.step"
OUTDIR = r"Y:/SunnydayTech/CADCLAW/docs/media"

LABELS = {
    (40.0, 80.0, 1000.0): "cbeam",
    (56.4, 56.4, 76.6):   "motor",
    (10.2, 23.9, 23.9):   "vwheel",
    (14.0, 15.0, 15.0):   "pulley",
    (12.7, 22.0, 22.0):   "idler",
    (3.0, 88.0, 127.0):   "plate",
    (4.0, 80.0, 100.0):   "bot-mount",
    (44.0, 80.0, 102.0):  "bracket",
    (4.0, 160.0, 280.0):  "plate",
}


def render_radial_spin():
    from cadharness.render import render_radial_explode_gif
    out = os.path.join(OUTDIR, "m3crete_radial_spin.gif")
    t0 = time.time()
    n = render_radial_explode_gif(
        STEP, out,
        expansion=0.45,
        explode_frames=24,
        hold_frames=4,
        rotate_frames=48,
        fps=16,
        width=720, height=540,
        gif_colors=56,
        tessellation_tol=0.6,
        labels=LABELS,
    )
    print(f"[radial_spin] {n} frames -> {out} in {time.time()-t0:.1f}s "
          f"({os.path.getsize(out)/1_000_000:.2f} MB)")


if __name__ == "__main__":
    render_radial_spin()
