"""Build an animated disassembly GIF from any assembly STEP.

Run:  python examples/m3_crete/make_gif.py path/to/assembly.step [out.gif]
"""
import sys
import time
sys.path.insert(0, '.')

from cadharness.render import make_disassembly_gif

step_path = sys.argv[1] if len(sys.argv) > 1 else "M3-2_Assembly.step"
gif_path = sys.argv[2] if len(sys.argv) > 2 else "disassembly.gif"

t0 = time.time()
n_frames = make_disassembly_gif(
    step_path, gif_path,
    n_transition_frames=3,
    fps=12,
    width=640, height=480,
    tessellation_tol=0.8,
)
print(f"{n_frames} frames -> {gif_path} in {time.time() - t0:.1f}s")
