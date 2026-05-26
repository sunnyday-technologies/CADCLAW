# M3-CRETE M3-2 — Shared Benchmark Core (ARB)

> **CANONICAL SHARED CORE.** This block is **identical across every track** (Fusion,
> CadQuery, …); only the per-backend "How to drive" stub differs. Edit *this* file,
> then regenerate the driver briefs with `prompts/build_briefs.py`. Frozen +
> versioned per ARB release — **do not tune it to make a run pass.** It deliberately
> states the target (the "what"), never a build method or order (the "how") —
> contributor build-order guidance (e.g. `AGENTS.md`) is intentionally kept out of
> this driver-facing brief.

## Task

Assemble the M3-CRETE M3-2 3D concrete-printing system from the provided authored
STEP parts, then export a single STEP assembly + a run log. You are being timed and
graded.

- Variant: M3-2. Target envelope/class: **2000 × 1000 × 1000 mm**.
- **Place authored STEP parts. Do not generate** contextual plates, brackets, motor
  mounts, NEMA hole patterns, idler holders, gantry plates, or adapter plates.
  Cut-to-length **extrusion stock** (C-beam / V-slot) and **belt segments** are the
  only geometry you may generate.
- **You decide all placement — positions, orientations, and the build approach.
  None is prescribed.** Keep assumptions / incomplete areas explicit.
- Printhead/tool payload and the final carriage→tool mount interface are **out of
  scope** this round — mark them as not-built.

## Fairness wall (critical — do not break this)

Build only from this brief + the provided kit. Do **not** open, search for, or
consult any reference assembly, answer key, solution spec, prior M3-CRETE design,
or project memory — even if your environment makes one reachable. Those are the
graded answer key; using them invalidates the run.

## Design constraints (the target — the "what," not the "how")

- The two-sided **X-axis printhead carriage** uses two **C-Beam Gantry Plate XLarge
  (125×125×6 mm)**, one each side of the X beam (off-axis toolhead forces). All
  other gantry plates are the small **V-Slot 20-80**: two at the X-to-Y handoff
  (one at each X-gantry end) and four for the Y-to-Z / Z-post carriages.
- **Y-gantry C-Beams**: 80 mm dimension vertical, open channels facing **inward**
  toward the print volume.
- **X-gantry C-Beams**: 80 mm dimension vertical. The 2 m X-gantry run has one
  **1000 mm 2040 V-slot insert centered across the middle splice** between the two
  1000 mm 4080 C-Beam segments.
- Each 2 m **top X-direction frame run** also has one 1000 mm 2040 insert centered
  across its splice.
- Frame is **open at the bottom in X** — no bottom X rails.
- **Lower Y static frame rails are 2080 V-slot** (not C-Beam).
- **Top center spreader**: a 2040 V-slot, placed with the **40 mm side vertical** and
  its top surface level with the surrounding top frame. It mounts on a **2-plate
  (6 mm) stack of small V-Slot 20-80 plates at each end** (four plates total).
- **Solid V Wheels**: four per gantry plate at the X-to-Y, X-carriage, and Y-to-Z
  interfaces; wheel centerlines align to the authored plate holes; the wheel inner
  face sits **7 mm off the plate face** (6 mm spacer + 1 mm washer).
- **Top** side-rail/post spacers use the authored **ZPMM** spacer; **lower** ones use
  the simple **6×40×80 mm flat spacer**.
- Drive: **Z and Y GT2 belts** run inside their C-beam channels with pulleys + return
  idlers; the **X drive is the authored VS_Belt_Pinion** (no separate X belt). **7
  NEMA 23 motors** are placed (4 Z, 2 Y, 1 X); the Y-motor screws directly to the
  C-beam (sensorless StallGuard homing — no physical endstop, no mount plate this
  round).

## The kit (authored parts; quantities are the target BOM)

| Part | Qty | Role |
|---|---|---|
| C-Beam 40×80×1000 Linear Rail | 14 | Z posts, X-gantry rails, top X frame, Y-gantry rails (or generate cut-to-length 40×80 stock) |
| V-Slot 20×80×1000 Linear Rail | 2 | lower Y static frame rails |
| V-Slot 20×40×1000 Linear Rail | 4 | top center spreader + 3 centered splice inserts |
| C-Beam Gantry Plate XLarge | 2 | X-carriage plates (one per side) |
| V-Slot Gantry Plate 20-80mm | 10 | 2 X-to-Y handoff + 4 Y-to-Z/Z-post + 4 spreader bracket |
| ZPMM motor-mount spacer (6 mm holes) | 4 | top motor-mount/post spacers |
| 6×40×80 mm flat frame shim | 4 | lower side-rail/post spacers |
| Solid V Wheel | 32 | 4 per gantry plate (X-to-Y, X-carriage, Y-to-Z) |
| GT2 Timing Pulley 20 Tooth | 4 | Z-axis drive pulley, one per post top |
| Smooth Idler Pulley Wheel | 4 | Z-axis return idler, one per post bottom |
| GT2 belt, Z run (942 mm) | 8 | Z-axis belt runs (2 per post) |
| GT2 belt, Y run (958 mm) | 4 | Y-axis belt runs (2 per Y gantry, inside channel) |
| NEMA 23 motor | 7 | one motor model, placed 7× — 4 Z (post tops), 2 Y, 1 X (drives the VS_Belt_Pinion); orient each instance yourself |
| VS_Belt_Pinion | 1 | X-axis belt + pulley actuator |

Total ≈ 100 placed instances. Repeated parts (extrusions, plates, wheels, and the
**single NEMA 23 motor model**) are one authored file each — place multiple
instances and orient them yourself; nothing is pre-rotated. (Your backend stub
names the exact file/data-source for each part.)

## Verify your work (as you go)

Inspect the in-progress assembly while you build, not only at the end — a single
viewpoint hides placement errors (a flipped part, the wrong rotation axis, a gap that
reads as solid contact head-on), and a fault is cheapest to fix before other parts
depend on it. Your backend stub lists the viewer available to you. Your kit also
includes reference images of the assembled target — a 3/4 `reference_overview.png`
(all components visible, a non-canonical angle) plus orthographic
`reference_front/top/side.png` — compare your build against them to check overall
arrangement and alignment. This is your own check; grading is a separate session.

<!--BACKEND_STUB-->

## Run log (you ARE being measured on effort)

Capture model/tool versions, **elapsed wall-clock time** (start now), **attempts**,
**retries**, **concrete corrections**, **human interventions**, and tokens if your
host exposes them. Save as YAML (`run_log.yaml`):

```yaml
schema_version: m3_ai_assembly_run_log.v0.1
run_id: <track>_<model>_<yyyymmdd>_<n>
benchmark_id: m3_ai_assembly
track: <filled by your backend stub>
status: complete
driver:
  ai_driver: <your model name + version>
  host_application: <your CAD backend + version>
timing: {started_utc: null, ended_utc: null, elapsed_minutes: null}
token_usage: {capture_status: unavailable, total_tokens: null}
attempts:
  - {attempt_id: A01, is_retry: false, driver_action: <what you did>, result: pending, corrections: [], human_interventions: [], notes: null}
summary: {attempt_count: null, retry_count: null, correction_count: null, human_intervention_count: null, residual_not_built_yet: []}
privacy_review: {secrets_checked: false, notes: No credentials, API keys, or private supplier fields.}
```

## When you are done

Report: the STEP export path, the run-log path, anything left not-built, and a
one-paragraph summary of where you struggled. **Stop there** — grading is done by a
separate session. Do not grade yourself, and do not tune toward any gate.
