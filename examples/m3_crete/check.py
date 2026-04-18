"""
M3-CRETE self-check — reference implementation using cad-harness.

Run:  python examples/m3_crete/check.py path/to/M3-2_Assembly.step
"""
import sys
sys.path.insert(0, '.')
from cadharness.harness import Harness
from cadharness.adjacency import AdjacencyRule
from cadharness.dimensional import DimRule

STEP = sys.argv[1] if len(sys.argv) > 1 else "M3-2_Assembly.step"

LABELS = {
    (40.0, 80.0, 1000.0): 'cbeam',
    (56.4, 56.4, 76.6):   'motor',
    (10.2, 23.9, 23.9):   'vwheel',
    (14.0, 15.0, 15.0):   'pulley',
    (12.7, 22.0, 22.0):   'idler',
    (3.0, 88.0, 127.0):   'plate',
    (4.0, 40.0, 80.0):    'shim',
    (4.0, 80.0, 96.0):    'zmount',
    (5.0, 40.0, 80.0):    'zcap',
    (4.0, 80.0, 100.0):   'bot-mount',
    (4.0, 80.0, 80.0):    'ymount',
    (5.0, 30.0, 30.0):    'idler-brk',
}

EXPECTED = {
    'cbeam': 17, 'motor': 6, 'vwheel': 24, 'pulley': 6,
    'idler': 5, 'plate': 6, 'shim': 2, 'zmount': 4,
    'zcap': 4, 'bot-mount': 4, 'ymount': 2, 'idler-brk': 1,
    'belt': 12, 'bracket': 0,
}

h = Harness(STEP)
h.add_inventory(LABELS, EXPECTED)
h.add_interference(skip_labels={'belt', 'vwheel', 'pulley', 'other'})
h.add_dimensional(rules=[
    DimRule('zmount', thin_axis=4.0, thin_tol=0.5),
    DimRule('zcap', thin_axis=5.0, thin_tol=0.5),
])

report = h.run()
print(report)
sys.exit(0 if report.passed else 1)
