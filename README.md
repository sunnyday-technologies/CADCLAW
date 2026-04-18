# CAD Harness

**The testing framework CAD never had.**

Automated validation, interference detection, and structural analysis for STEP assemblies. Like pytest for mechanical design.

## The Problem

CAD assemblies break silently. Parts clip into each other, BOMs drift from geometry, motor mounts end up 600mm from the motor. Engineers catch these errors by eye — if they catch them at all. There is no `pytest` for CAD.

## What CAD Harness Does

CAD Harness validates STEP assemblies through a chain of automated gates:

| Gate | What it catches |
|------|----------------|
| **Inventory** | Missing/extra parts. Labels by bbox signature, counts against expected. |
| **Interference** | Solid-solid overlaps. BRep boolean intersection, not just bbox. |
| **Adjacency** | Parts that should be near each other but aren't (motor 600mm from mount). |
| **Dimensional** | Wrong thickness, swapped `box()` args, impossible dimensions. |
| **Kinematics** | Beam deflection, motor torque budgets, belt tension, racking. |

All gates run against a single loaded STEP file. The harness passes only if every gate passes.

## Quick Start

```bash
pip install cadquery
pip install cad-harness   # or: git clone + pip install -e .
```

```python
from cadharness.harness import Harness
from cadharness.adjacency import AdjacencyRule

h = Harness("my_assembly.step")

h.add_inventory(
    labels={(40.0, 80.0, 1000.0): 'beam', (56.4, 56.4, 76.6): 'motor'},
    expected={'beam': 4, 'motor': 2, 'belt': 3}
)

h.add_interference(skip_labels={'belt', 'wheel'})

h.add_adjacency(rules=[
    AdjacencyRule('motor', 'bracket', max_distance=50)
])

report = h.run()
print(report)
# CAD HARNESS REPORT — PASSED
#   Parts: 42
#   Time:  3200ms
#
#   [PASS] inventory (120ms)
#   [PASS] interference (2800ms)
#   [PASS] adjacency (15ms)
```

## How It Works

Every solid in a STEP file has a bounding box. The sorted dimensions `(dx, dy, dz)` rounded to 0.1mm form a **signature** — a fingerprint that identifies part types without needing part names or metadata.

```
(40.0, 80.0, 1000.0) → "beam"     # 4080 C-beam extrusion
(56.4, 56.4, 76.6)   → "motor"    # NEMA23 stepper
(4.0, 80.0, 96.0)    → "mount"    # motor mount plate
```

This works because mechanical parts have characteristic dimensions. A NEMA23 is always 56.4mm square. A 4080 extrusion is always 40x80mm. The harness exploits this invariant to label, count, and validate without parsing STEP metadata.

## Origin Story

CAD Harness was extracted from the [M3-CRETE](https://github.com/sunnyday-technologies/M3-CRETE) open-source concrete 3D printer project, where it was developed during a human-AI collaboration between a mechanical engineer and Claude (Anthropic's AI). The harness:

- Caught 53 solid-solid interferences in a single run
- Reduced STEP file size from 70MB to 13MB by identifying geometry bloat
- Validated 150+ assembly changes across 15 design sessions without visual inspection
- Prevented 3 regressions that would have shipped broken geometry to builders

See [examples/m3_crete/](examples/m3_crete/) for the reference implementation.

## Modules

### `cadharness.inventory`
Label parts by bbox signature, count them, compare to expected inventory.

### `cadharness.interference`
Pairwise solid-solid overlap using OCC `BRepAlgoAPI_Common`. Bbox pre-filter for performance. Reports overlap volume in mm^3.

### `cadharness.adjacency`
Validate that parts of type A have a part of type B within N mm. Catches misplaced/scattered components.

### `cadharness.dimensional`
Check part dimensions against expected ranges. Catches wrong thickness, swapped args, scaling errors.

### `cadharness.kinematics`
Structural analysis from assembly parameters. Beam deflection (Euler-Bernoulli), motor torque budgets, belt tension, GT2 tooth skip resistance.

### `cadharness.harness`
The runner. Chains gates, loads parts once, reports pass/fail with timing.

## CI/CD Integration

```yaml
# .github/workflows/cad-check.yml
- name: Validate assembly
  run: |
    pip install cadquery cad-harness
    python check.py assembly.step
```

Exit code 0 = passed. Exit code 1 = failed. Works in any CI system.

## Who This Is For

- **Open-source hardware projects** — catch assembly errors before builders hit them
- **CadQuery/FreeCAD users** — the testing layer the ecosystem is missing
- **Small manufacturing teams** — automated QA between design and procurement
- **AI-assisted CAD workflows** — validate that AI-generated changes don't break the assembly

## Running Tests

```bash
git clone https://github.com/sunnyday-technologies/cad-harness.git
cd cad-harness
pip install cadquery

# Generate test fixture STEP assemblies (L1-L3, good + bad variants)
python tests/generate_fixtures.py

# Run the test suite (17 tests)
python tests/test_harness.py
```

The test fixtures are generated from CadQuery — no external downloads needed.
Three tiers of increasing complexity:

| Level | Parts | Tests |
|-------|-------|-------|
| L1: Bracket assembly | 5 | Inventory, interference |
| L2: Motor mount | 10 | Inventory, adjacency |
| L3: Gantry corner | 18 | Full 4-gate harness |

Each level has a "good" variant (should pass) and "bad" variant (deliberate errors
for the harness to catch: clipping, missing parts, scattered motors).

## Requirements

- Python 3.10+
- CadQuery 2.7+ (provides OCC/STEP support)
- No commercial CAD software needed

## License

MIT License. Copyright (c) 2026 Sunnyday Technologies.

Built during the [M3-CRETE](https://m3-crete.com) project — an open-source concrete
3D printer where CAD Harness caught 53 interferences, reduced STEP file size from
70 MB to 13 MB, and validated 150+ assembly changes across a human-AI design collaboration.
