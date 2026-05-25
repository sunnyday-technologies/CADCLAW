# Fusion Driver Brief — Claude-Fusion benchmark track

> **HOW TO USE:** Paste everything between the `=== BEGIN ===` / `=== END ===`
> markers into a **fresh Claude Code session** that has the **Autodesk Fusion
> MCP** connected. Do **not** run it in a session that has seen the CADCLAW
> reference spec — and start that fresh session in an **empty/neutral working
> directory**, *not* inside a CADCLAW checkout, so project memory and notes don't
> auto-load into its context. This brief is the *only* design input the driver is
> allowed.
>
> **Fairness wall (critical):** the driver MUST NOT open or read
> `examples/m3_crete/m3_reference_assembly.yaml`,
> `examples/m3_crete/m3_connector_metadata.yaml`, the `build/` STEP outputs, or
> any session log. Those are the answer key; reading them invalidates the run.
> The driver works only from the task + kit below.
>
> After the run, hand the exported STEP path back to the grader session (the one
> that owns `grade_native_step.py`).

---

`=== BEGIN ===`

You are the **Claude-Fusion driver** in an AI-CAD assembly benchmark. Your job is
to build a machine in **Autodesk Fusion** (via the Fusion MCP tools available in
this session), from the parts kit and the task below, then export a single STEP
file. You are being timed and graded. Work only from this brief.

**Fairness wall (critical — do not break this).** This brief is your *only* design
input. Do **not** open, read, search, or otherwise consult any of the following,
even if your environment makes them reachable: `m3_reference_assembly.yaml`,
`m3_connector_metadata.yaml`, the CADCLAW assembly spec, any `build/` STEP output,
or any session/handoff log. Those are the graded answer key — reading them
invalidates the run. If project notes, memories, or auto-loaded context happen to
describe this assembly's solution, ignore them and build only from the task + kit
below.

## Task

Assemble the M3-CRETE M3-2 3D concrete-printing system from the provided authored
STEP assets.

- Variant: M3-2. Target envelope/class: **2000 × 1000 × 1000 mm**.
- **Place authored STEP parts. Do not generate** contextual plates, brackets,
  motor mounts, NEMA hole patterns, idler holders, gantry plates, or adapter
  plates. (Stock-like extrusion/belt segments are the only generatable geometry,
  and the kit already provides them.)
- Keep assumptions / incomplete areas explicit.
- Produce a non-authoritative STEP assembly + a run log.

### Fixture constraints (the design intent — your spec)

- Build inside-out: place the **X gantry and end plates** first, add the
  **two-sided X carriage**, then the **Y gantries**, then the **Y-to-Z / Z-post
  carriage plates**, then the **Z posts and frame** around that motion stack.
- The two-sided **X-axis printhead carriage** uses two **C-Beam Gantry Plate
  XLarge (125×125×6 mm)**, one each side of the X beam (off-axis toolhead
  forces). All other gantry plates are the small **V-Slot 20-80**: two at the
  X-to-Y handoff (one at each X-gantry end) and four for the Y-to-Z / Z-post
  carriages.
- **Y-gantry C-Beams**: 80 mm dimension vertical, open channels facing **inward**
  toward the print volume.
- **X-gantry C-Beams**: 80 mm dimension vertical. The 2 m X-gantry run has one
  **1000 mm 2040 V-slot insert centered across the middle splice** between the
  two 1000 mm 4080 C-Beam segments.
- Each 2 m **top X-direction frame run** also has one 1000 mm 2040 insert
  centered across its splice.
- Frame is **open at the bottom in X** — no bottom X rails.
- **Lower Y static frame rails are 2080 V-slot** (not C-Beam).
- **Top center spreader**: a 2040 V-slot, placed with the **40 mm side vertical**
  and its top surface level with the surrounding top frame. It mounts on a
  **2-plate (6 mm) stack of small V-Slot 20-80 plates at each end** (four plates
  total).
- **Solid V Wheels**: four per gantry plate at the X-to-Y, X-carriage, and
  Y-to-Z interfaces; wheel centerlines align to the authored plate holes; the
  wheel inner face sits **7 mm off the plate face** (6 mm spacer + 1 mm washer).
- **Top** side-rail/post spacers use the authored **ZPMM** spacer; **lower**
  ones use the simple **6×40×80 mm flat spacer**.
- Drive: **Z and Y GT2 belts** run inside their C-beam channels with pulleys +
  return idlers; the **X drive is the authored VS_Belt_Pinion** (no separate X
  belt). **7 NEMA 23 motors** are placed (4 Z, 2 Y, 1 X); the Y-motor screws
  directly to the C-beam (sensorless StallGuard homing — no physical endstop, no
  mount plate this round).
- Printhead/tool payload and final carriage mount interface are **out of scope**
  this round — mark them as not-built.

## The kit (already uploaded to the Fusion project `M3-AI-Benchmark-Kit`)

Insert these authored parts; quantities are the target BOM. Names are exactly as
they appear in the project's Data Panel.

| Part (Fusion file name) | Qty | Role |
|---|---|---|
| C-Beam 40x80x1000 Linear Rail | 14 | Z posts, X-gantry rails, top X frame, Y-gantry rails |
| V-Slot 20x80x1000 Linear Rail | 2 | lower Y static frame rails |
| V-Slot 20x40x1000 Linear Rail | 4 | top center spreader + 3 centered splice inserts |
| C-Beam Gantry Plate XLarge | 2 | X-carriage plates (one per side) |
| V-Slot Gantry Plate 20-80mm | 10 | 2 X-to-Y handoff + 4 Y-to-Z/Z-post + 4 spreader bracket |
| ZPMM_6p1_motor_mount_spacer_6mm_holes | 4 | top motor-mount/post spacers |
| M3_6mm_frame_shim_4080 | 4 | lower side-rail/post flat spacers |
| Solid V Wheel | 32 | 4 per gantry plate (X-to-Y, X-carriage, Y-to-Z) |
| GT2 Timing Pulley 20 Tooth | 4 | Z-axis drive pulley, one per post top |
| Smooth Idler Pulley Wheel | 4 | Z-axis return idler, one per post bottom |
| M3_GT2_belt_Z_942mm | 8 | Z-axis belt runs (2 per post) |
| M3_GT2_belt_Y_958mm | 4 | Y-axis belt runs (2 per Y gantry, inside channel) |
| M3_NEMA23_motor_src5 / src6 / src7 / src143 | 4 | Z-axis motors (post tops), 1 each |
| M3_NEMA23_motor_src8 / src58 | 2 | Y-axis motors, 1 each |
| M3_NEMA23_motor_src74 | 1 | X-axis motor (drives the VS_Belt_Pinion) |
| VS_Belt_Pinion | 1 | X-axis belt + pulley actuator |

Total ≈ 100 placed instances. The motor STEP files were exported preserving
their source orientation, so inserting them un-rotated lands them close to their
mounting attitude.

## How to drive Fusion (operational pointers — figure out the specifics)

1. Confirm the MCP works: `fusion_mcp_read` `queryType:"projects"` should list
   `M3-AI-Benchmark-Kit`; `queryType:"document"`, `operation:"search"` (with
   `project:"M3-AI-Benchmark-Kit"`) lists the kit DataFiles.
2. Create a **new Fusion design/document** for the assembly (keep it in that
   project).
3. Insert kit parts as component occurrences and position/orient them per the
   constraints above. Use `fusion_mcp_execute` `featureType:"script"` (Fusion
   Python API). Look up the exact API via `fusion_mcp_read`
   `queryType:"apiDocumentation"` — relevant areas: inserting a `DataFile` as an
   occurrence (`Occurrences.addByInsert`), component `transformBy` /
   `Matrix3D`, and STEP export via `ExportManager` / `STEPExportOptions`.
   *You decide the coordinates — they are not provided.*
4. Sanity-check as you go with `fusion_mcp_read` `queryType:"screenshot"`.
5. **Export the finished design to a single STEP** at this absolute path (create
   the folder if it does not exist):
   `D:\SunnydayTech\CADCLAW\benchmarks\m3_ai_assembly\results\fusion_native_export.step`
6. Mark anything you could not place as **not-built** in your notes.

## What to record (the run log — you ARE being measured on effort)

Capture: model/tool versions, **elapsed wall-clock time** (start the clock now),
**attempts**, **retries**, **concrete corrections**, **human interventions**, and
token usage if your host exposes it. Save it as YAML to this **absolute** path:
`D:\SunnydayTech\CADCLAW\benchmarks\m3_ai_assembly\run_logs\fusion_native_driver.yaml`

Use this shape (fill every field; leave a value `null` only if genuinely
unavailable, and note why):

```yaml
schema_version: m3_ai_assembly_run_log.v0.1
run_id: fusion_native_<yyyymmdd>_<n>
benchmark_id: m3_ai_assembly
track: fusion_native_driver
status: complete            # planned | in_progress | complete | abandoned
driver:
  ai_driver: <your model name + version>
  host_application: Autodesk Fusion (via Fusion MCP)
  host_application_version: <Fusion build, if known>
timing:
  started_utc: null
  ended_utc: null
  elapsed_minutes: null
token_usage:
  capture_status: unavailable   # -> captured, with numbers, if your host exposes them
  prompt_tokens: null
  completion_tokens: null
  total_tokens: null
attempts:
  - attempt_id: A01
    is_retry: false
    driver_action: <what you did this attempt>
    result: pending           # success | partial | failed
    corrections: []           # concrete fixes you made
    human_interventions: []   # any time a human had to step in
    notes: null
outputs:
  final_step: D:\SunnydayTech\CADCLAW\benchmarks\m3_ai_assembly\results\fusion_native_export.step
summary:
  attempt_count: null
  retry_count: null
  correction_count: null
  human_intervention_count: null
  residual_not_built_yet: []  # anything you marked not-built
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

After the driver exports the STEP:

```powershell
.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\grade_native_step.py `
  --step benchmarks\m3_ai_assembly\results\fusion_native_export.step `
  --out benchmarks\m3_ai_assembly\results\fusion_native_report.json
.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\score_report.py `
  benchmarks\m3_ai_assembly\results\fusion_native_report.json `
  --out benchmarks\m3_ai_assembly\results\fusion_native_score.json
```

Then summarize the run log and fill the comparison row (CADCLAW track =
~15/100 on the full ARB stack, L1 sub-grade 100/100; Fusion track = this result) + effort metrics from the runbook.
