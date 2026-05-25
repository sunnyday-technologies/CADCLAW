# CadQuery Driver Brief — CADCLAW spec/code benchmark track

> **HOW TO USE:** Paste everything between the `=== BEGIN ===` / `=== END ===`
> markers into a **fresh agent session** (Claude Code, or GPT/Codex CLI — the model
> under test). Start that session **inside this blind-kit folder** (it contains
> `kit/` + this brief and nothing else), in a directory that is **not** a CADCLAW
> checkout, so no reference solution or project memory can leak in. This brief +
> `kit/` are the *only* design inputs the driver gets.
>
> **Fairness wall (critical):** the kit folder deliberately contains **no
> reference assembly, no answer key, no solution spec** — only the authored part
> files. The driver must build from the task + kit alone. Do not fetch the
> M3-CRETE design, the CADCLAW reference spec, or any prior solution.
>
> After the run, hand the exported STEP back to the grader session (the one that
> owns `grade_native_step.py`). Same grader, same gates as the Fusion track — this
> is the apples-to-apples backend comparison (CadQuery code vs Fusion GUI), and the
> apples-to-apples model comparison if run with GPT vs Claude.

---

`=== BEGIN ===`

You are the **CadQuery driver** in an AI-CAD assembly benchmark. Build a machine
in **CadQuery** (Python) from the parts kit and task below, then export a single
STEP file. You are being timed and graded. Work only from this brief + the `kit/`
folder.

**Fairness wall (critical — do not break this).** This brief + `kit/` are your
*only* design input. Do **not** open, search for, or consult any reference
assembly, answer key, BOM solution, prior M3-CRETE design, or CADCLAW reference
spec, even if your environment makes one reachable. If project notes or memory
describe this assembly's solution, ignore them and build only from the task + kit.

## Task

Assemble the M3-CRETE M3-2 3D concrete-printing system from the authored STEP
assets in `kit/`.

- Variant: M3-2. Target envelope/class: **2000 × 1000 × 1000 mm**.
- **Place authored STEP parts. Do not generate** contextual plates, brackets,
  motor mounts, NEMA hole patterns, idler holders, gantry plates, or adapter
  plates. Cut-to-length **extrusion stock** (C-beam / V-slot bars) and **belt
  segments** are the only geometry you may generate; everything else is placed
  from a `kit/` STEP.
- Keep assumptions / incomplete areas explicit.
- Produce a non-authoritative STEP assembly + a run log.

### Fixture constraints (the design intent — your spec)

- Build inside-out: place the **X gantry and end plates** first, add the
  **two-sided X carriage**, then the **Y gantries**, then the **Y-to-Z / Z-post
  carriage plates**, then the **Z posts and frame** around that motion stack. The
  X-gantry is the datum; everything else references it (so end-plate movement
  tolerances propagate from the datum, not from fixed coordinates).
- The two-sided **X-axis printhead carriage** uses two **C-Beam Gantry Plate
  XLarge (125×125×6 mm)**, one each side of the X beam (off-axis toolhead forces).
  All other gantry plates are the small **V-Slot 20-80**: two at the X-to-Y
  handoff (one at each X-gantry end) and four for the Y-to-Z / Z-post carriages.
- **Y-gantry C-Beams**: 80 mm dimension vertical, open channels facing **inward**
  toward the print volume.
- **X-gantry C-Beams**: 80 mm dimension vertical. The 2 m X-gantry run has one
  **1000 mm 2040 V-slot insert centered across the middle splice** between the two
  1000 mm 4080 C-Beam segments.
- Each 2 m **top X-direction frame run** also has one 1000 mm 2040 insert centered
  across its splice.
- Frame is **open at the bottom in X** — no bottom X rails.
- **Lower Y static frame rails are 2080 V-slot** (not C-Beam).
- **Top center spreader**: a 2040 V-slot, placed with the **40 mm side vertical**
  and its top surface level with the surrounding top frame. It mounts on a
  **2-plate (6 mm) stack of small V-Slot 20-80 plates at each end** (four plates
  total).
- **Solid V Wheels**: four per gantry plate at the X-to-Y, X-carriage, and Y-to-Z
  interfaces; wheel centerlines align to the authored plate holes; the wheel inner
  face sits **7 mm off the plate face** (6 mm spacer + 1 mm washer).
- **Top** side-rail/post spacers use the authored **ZPMM** spacer; **lower** ones
  use the simple **6×40×80 mm flat spacer**.
- Drive: **Z and Y GT2 belts** run inside their C-beam channels with pulleys +
  return idlers; the **X drive is the authored VS_Belt_Pinion** (no separate X
  belt). **7 NEMA 23 motors** are placed (4 Z, 2 Y, 1 X); the Y-motor screws
  directly to the C-beam (sensorless StallGuard homing — no physical endstop, no
  mount plate this round).
- Printhead/tool payload and final carriage mount interface are **out of scope**
  this round — mark them as not-built.

## The kit (`kit/` — authored STEP files)

Insert these authored parts; quantities are the target BOM. Filenames are exactly
as they appear in `kit/`.

| Part (file in `kit/`) | Qty | Role |
|---|---|---|
| `C-Beam 40x80x1000 Linear Rail.step` | 14 | Z posts, X-gantry rails, top X frame, Y-gantry rails (or generate cut-to-length 40×80 stock) |
| `V-Slot 20x80x1000 Linear Rail.step` | 2 | lower Y static frame rails |
| `V-Slot 20x40x1000 Linear Rail.step` | 4 | top center spreader + 3 centered splice inserts |
| `C-Beam Gantry Plate XLarge.STEP` | 2 | X-carriage plates (one per side) |
| `V-Slot Gantry Plate 20-80mm.step` | 10 | 2 X-to-Y handoff + 4 Y-to-Z/Z-post + 4 spreader bracket |
| `ZPMM_6p1_motor_mount_spacer_6mm_holes.step` | 4 | top motor-mount/post spacers |
| `M3_6mm_frame_shim_4080.step` | 4 | lower side-rail/post flat spacers |
| `Solid V Wheel.step` | 32 | 4 per gantry plate (X-to-Y, X-carriage, Y-to-Z) |
| `GT2 Timing Pulley 20 Tooth.step` | 4 | Z-axis drive pulley, one per post top |
| `Smooth Idler Pulley Wheel.step` | 4 | Z-axis return idler, one per post bottom |
| `M3_GT2_belt_Z_942mm.step` | 8 | Z-axis belt runs (2 per post) |
| `M3_GT2_belt_Y_958mm.step` | 4 | Y-axis belt runs (2 per Y gantry, inside channel) |
| `M3_NEMA23_motor_src5/src6/src7/src143.step` | 4 | Z-axis motors (post tops), 1 each |
| `M3_NEMA23_motor_src8/src58.step` | 2 | Y-axis motors, 1 each |
| `M3_NEMA23_motor_src74.step` | 1 | X-axis motor (drives the VS_Belt_Pinion) |
| `VS_Belt_Pinion.step` | 1 | X-axis belt + pulley actuator |

Total ≈ 100 placed instances. The motor STEPs were exported preserving their
source orientation, so importing them un-rotated lands them close to their
mounting attitude.

## How to drive CadQuery (operational pointers — figure out the specifics)

1. Set up: `pip install cadquery` (and optionally `cadclaw` if you want to
   self-inspect inventory as you go). Confirm `import cadquery as cq` works.
2. Import each kit part with `cq.importers.importStep("kit/<file>")`. Probe each
   part's bounding box / center of mass to learn its local axes and orientation
   before placing.
3. Place copies into one assembly by computing per-instance transforms
   (`cq.Assembly().add(part, loc=cq.Location(cq.Vector(x,y,z), cq.Vector(ax),
   deg))`, or `.translate(...).rotate(...)`). **You decide all coordinates — none
   are provided.** Cut-to-length 40×80 / 20×80 / 20×40 stock and belt segments may
   be generated parametrically; place everything else from `kit/`.
4. Sanity-check as you go (counts, rough placement).
5. **Export the finished assembly to a single STEP** (relative to your run
   folder): `cadquery_native_export.step` — e.g. via
   `cq.exporters.export(assembly.toCompound(), "cadquery_native_export.step")`.
6. Mark anything you could not place as **not-built** in your notes.

## What to record (the run log — you ARE being measured on effort)

Capture: model/tool versions, **elapsed wall-clock time** (start the clock now),
**attempts**, **retries**, **concrete corrections**, **human interventions**, and
token usage if your host exposes it. Save it as YAML to `run_log.yaml` in your run
folder. Use this shape (fill every field; leave a value `null` only if genuinely
unavailable, and note why):

```yaml
schema_version: m3_ai_assembly_run_log.v0.1
run_id: cadquery_native_<model>_<yyyymmdd>_<n>
benchmark_id: m3_ai_assembly
track: cadquery_native_driver
status: complete            # planned | in_progress | complete | abandoned
driver:
  ai_driver: <your model name + version>        # e.g. Claude / GPT, with version
  host_application: CadQuery (Python)
  host_application_version: <cadquery version>
timing:
  started_utc: null
  ended_utc: null
  elapsed_minutes: null
token_usage:
  capture_status: unavailable
  total_tokens: null
attempts:
  - attempt_id: A01
    is_retry: false
    driver_action: <what you did this attempt>
    result: pending           # success | partial | failed
    corrections: []
    human_interventions: []
    notes: null
outputs:
  final_step: cadquery_native_export.step
summary:
  attempt_count: null
  retry_count: null
  correction_count: null
  human_intervention_count: null
  residual_not_built_yet: []
privacy_review:
  secrets_checked: false
  notes: Do not include credentials, API keys, or private supplier fields.
```

## When you are done

Report: the STEP export path, the run-log path, anything left not-built, and a
one-paragraph summary of where you struggled. **Stop there** — grading is done by
a separate session with `grade_native_step.py`. Do not grade yourself, and do not
tune toward any gate you weren't given.

`=== END ===`

---

## Grader-side (for the clean/reference session — not part of the driver prompt)

After the driver exports `cadquery_native_export.step`, grade it identically to
the Fusion track:

```powershell
.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\grade_native_step.py `
  --step <path>\cadquery_native_export.step `
  --out benchmarks\m3_ai_assembly\results\cadquery_native_report.json
.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\score_report.py `
  benchmarks\m3_ai_assembly\results\cadquery_native_report.json `
  --out benchmarks\m3_ai_assembly\results\cadquery_native_score.json
```

Fill the comparison: this is a **blind** track. Compare blind-vs-blind across
Claude-Fusion, Claude-CadQuery, and GPT-CadQuery; the resolver-built reference
(~15/100 full-stack) is the **informed ceiling**, not a competitor.
