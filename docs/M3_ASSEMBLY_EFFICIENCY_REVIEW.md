# M3 Assembly Efficiency Review

> **Canonical M3 frame facts: [M3_FRAME_CANON.md](M3_FRAME_CANON.md) + the gate-verified spec.** This doc covers *compute* efficiency (the geometry-shape cache). The plate table below is a point-in-time snapshot and is now stale: the reference places **0 C-Beam Gantry Plate XLarge** (all gantry plates are the small V-Slot 20-80), and the instance count has grown past 70 with the drive train. Defer to the canon.

Status: initial process review on `codex/check-efficiency-review`.

This note separates repository test coverage from M3 assembly validation work.
The recent `371 passed` result was the full Python test suite, not 371
individual CAD checks against the M3 printer.

## Current M3 Reference Size

`examples/m3_crete/m3_reference_assembly.yaml` currently declares 70 placed
instances:

| Role | Count |
|---|---:|
| `v_wheel` | 32 |
| `top_frame_rail_x` | 4 |
| `vertical_post` | 4 |
| `z_carriage_plate` | 4 |
| `frame_side_motor_mount_spacer_6mm` | 4 |
| `frame_side_flat_spacer_6mm` | 4 |
| `top_frame_rail_y` | 2 |
| `top_frame_insert_2040` | 2 |
| `bottom_frame_rail_y_2080` | 2 |
| `x_gantry_beam` | 2 |
| `x_gantry_plate` | 2 |
| `x_carriage_plate` | 2 |
| `y_gantry_beam` | 2 |
| `top_center_spreader_plate` | 2 |
| `x_gantry_insert_2040` | 1 |
| `top_center_spreader_2040` | 1 |

Those 70 placements come from only 8 unique STEP source files:

| STEP source | Placements |
|---|---:|
| `CAD/Components/Wheels/Solid V Wheel.step` | 32 |
| `CAD/Advanced/Linear Rail/C-Beam 40x80x1000 Linear Rail.step` | 14 |
| `CAD/Components/Plates/V-Slot Gantry Plate 20-80mm.step` | 6 |
| `CAD/Advanced/Plates/C-Beam Gantry Plate XLarge.STEP` | 4 |
| `ZPMM.step` | 4 |
| `examples/m3_crete/generated/M3_6mm_frame_shim_4080.step` | 4 |
| `CAD/Components/V-Slot/V-Slot 20x40x1000 Linear Rail.step` | 4 |
| `CAD/Components/V-Slot/V-Slot 20x80x1000 Linear Rail.step` | 2 |

## Declared Checks

The M3 spec currently requests:

- `inventory`
- `interference`
- `vslot_stackup`
- `frame_adjacency`
- `hole_alignment`
- `wheel_alignment`
- `open_channel_orientation`
- `bbox_alignment`
- `floating`
- `dimensional`

`inventory` is handled separately. Seven geometry/design gates are wired for
assembly specs today: interference, V-slot stackup, frame adjacency, authored
hole alignment, wheel alignment, open-channel orientation, and bbox alignment.
`floating` and `dimensional` are still reported as not wired for assembly
specs, so they should either be implemented or removed from this specific M3
run configuration before release scoring.

## Measured Redundancy

Before this branch, `assemble check-round` reloaded and transformed the same
69 placed shapes once per shape-consuming validation gate:

- 6 shape-consuming gates x 69 placements = 414 transformed shape loads.
- 1 STEP export x 69 placements = 69 additional loads.
- Total current check-round geometry load pressure: 483 instance-loads.

The same pattern is more expensive in `render-sequence` because validation is
cumulative at each step:

| Step | Cumulative Instances |
|---|---:|
| `02_x_carriage` | 24 |
| `03_y_gantry` | 26 |
| `04_z_carriages` | 46 |
| `05_z_posts` | 50 |
| `06_frame_completion` | 69 |

With six shape-consuming gates, those cumulative validations account for 1,290
shape loads for steps 02-06, before counting STEP exports. Including the
earlier `01_x_gantry` step brings the total to 1,374 validation shape loads and
229 export loads.

## Current Branch Improvement

This branch adds a per-run `GeometryShapeCache` for transformed instance
shapes used by validation gates. For `check-round`, all full-assembly
shape-consuming gates now reuse the same transformed shape set:

- Validation shape loads drop from 414 to 69.
- Including the required final STEP export, load pressure drops from 483 to
  138.
- The report metadata includes `meta.geometry_cache` with request, hit, miss,
  loaded-instance, and cached-set counts.

For `render-sequence`, the cache is per sequence run and keyed by cumulative
instance set. It avoids reloading the same cumulative step for every gate:

- Validation shape loads drop from 1,374 to 229.
- Including cumulative STEP exports, load pressure drops from 1,603 to 458.

## Remaining Efficiency Candidates

- **Source-level caching:** Only 8 unique STEP files back the current 69
  placements. A future source cache could import each STEP once, then clone and
  transform copies. This is the next largest improvement, but it needs care to
  avoid mutating shared CadQuery/OCC shapes.
- **Geometry index:** Bboxes, cylindrical features, and instance lookup maps are
  recomputed in several gates. A shared `PlacedGeometryIndex` could calculate
  those once per cached instance set.
- **Sequence/check-round reuse:** If `render-sequence` validates the final
  cumulative step, a follow-on `check-round` should be able to reuse the
  sequence report or run only missing report families such as BOM/report
  packaging.
- **Run-check hygiene:** Remove or wire `floating` and `dimensional` for the M3
  assembly spec so declared checks match actual checks.
- **Benchmark timing:** The run-log template should capture elapsed time for
  each gate so future comparisons can report not only accuracy but validation
  cost.

## GIF Follow-On Artifact

The article/demo artifact request is now tracked as a build output:

- `examples/m3_crete/build/sequence/final/assembly_progress_360.gif`
- `examples/m3_crete/build/sequence/final/final_explode_slow_rotate.gif`

The first uses the May 20 sequence STEP outputs from steps 02 through 06 and
shows cumulative assembly over one slow 360-degree orbit. The second uses the
final sequence assembly STEP and produces a slower exploded 360-degree orbit.
These generated GIFs are intentionally ignored build artifacts.
