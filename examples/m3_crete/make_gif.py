"""Build an animated disassembly GIF of the M3-CRETE frame.

Per-part coloring matches the Fusion viewport — extrusions render
black, printed brackets green, metal plates grey.

Run:  python examples/m3_crete/make_gif.py path/to/assembly.step [out.gif]
"""
import sys
import time
sys.path.insert(0, '.')

from cadclaw.render import make_disassembly_gif

LABELS = {
    (40.0, 80.0, 1000.0): 'cbeam',
    (56.4, 56.4, 76.6):   'motor',
    (10.2, 23.9, 23.9):   'vwheel',
    (14.0, 15.0, 15.0):   'pulley',
    (12.7, 22.0, 22.0):   'idler',
    (3.0, 88.0, 127.0):   'plate',
    (4.0, 80.0, 100.0):   'bot-mount',
    (44.0, 80.0, 102.0):  'bracket',
    (4.0, 160.0, 280.0):  'plate',
}

step_path = sys.argv[1] if len(sys.argv) > 1 else "M3-2_Assembly.step"
gif_path = sys.argv[2] if len(sys.argv) > 2 else "docs/media/m3crete_disassembly.gif"

t0 = time.time()
n_frames = make_disassembly_gif(
    step_path, gif_path,
    labels=LABELS,
    n_transition_frames=2,
    fps=10,
    width=960, height=720,
    tessellation_tol=0.8,
)
print(f"{n_frames} frames -> {gif_path} in {time.time() - t0:.1f}s")
