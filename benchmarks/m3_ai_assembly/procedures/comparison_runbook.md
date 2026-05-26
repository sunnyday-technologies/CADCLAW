# M3 AI Assembly Comparison Runbook

Purpose: compare AI-assisted assembly workflows against the same M3-CRETE M3-2
target using artifact-based evidence.

This runbook is neutral by design. Record model, tool, and CAD-system names as
metadata only. The comparison is about exported artifacts, validation findings,
retries, corrections, elapsed time, token usage where available, and human
interventions.

## Tracks

1. **Initial CADCLAW setup retrospective**
   - Log: `benchmarks/m3_ai_assembly/run_logs/initial_cadclaw_setup_2026_05.yaml`
   - Purpose: baseline the first interactive CADCLAW setup effort.
   - Limitation: exact wall-clock time and token telemetry were not captured,
     so this run is useful for correction taxonomy but not for precise effort
     accounting.

2. **Native CAD driver**
   - Procedure: `benchmarks/m3_ai_assembly/procedures/native_cad_driver.md`
   - Example target: Fusion-driven assembly using the shared prompt and the
     approved asset package.
   - Output: exported STEP plus run log and CADCLAW grading report.

3. **Fresh CADCLAW spec driver**
   - Procedure: `benchmarks/m3_ai_assembly/procedures/cadclaw_spec_driver.md`
   - Example target: an AI driver edits CADCLAW YAML/spec metadata and uses
     CADCLAW to compile the assembly.
   - Output: generated STEP or dry-run plan, run log, CADCLAW report, and score.

## Required Inputs For Every Fresh Run

- `benchmarks/m3_ai_assembly/prompts/standard_prompt.md`
- `benchmarks/m3_ai_assembly/benchmark.yaml`
- `examples/m3_crete/m3_reference_assembly.yaml`
- `examples/m3_crete/m3_connector_metadata.yaml`
- `examples/m3_crete/m3_testkit_assets.yaml`
- The same approved STEP assets and reference image, with checksums where
  redistribution is allowed.

**Pre-run hygiene (blind tracks):** start the driver in a neutral working folder that
contains **no CADCLAW checkout, no `AGENTS.md`, and no project memory** — these can
carry build-order guidance or answer-key hints that void the run. The brief + kit are
the only design inputs.

## Measurement Rules

- Start timer when the shared prompt is given to the AI driver.
- Stop timer when the final report and score are written, or when the run is
  abandoned with a documented blocker.
- Count every artifact-check loop as an attempt.
- Count every attempt after the first as a retry.
- Count each concrete design/spec/CAD correction as one correction.
- Count human design decisions, approvals, native CAD exports, and corrective
  guidance as human interventions.
- Capture token usage from provider/API/host telemetry only. If telemetry is
  unavailable, mark it unavailable instead of estimating.

## Output Bundle

Each run should produce:

- Run log YAML using `run_logs/templates/run_log_template.yaml`.
- Run summary JSON from `scripts/summarize_run_log.py`.
- CADCLAW grader report JSON.
- Score report JSON.
- STEP or dry-run design inventory.
- Review images for non-dry-run assemblies.
- Optional generated demo GIFs:
  `examples/m3_crete/build/sequence/final/assembly_progress_360.gif` and
  `examples/m3_crete/build/sequence/final/final_explode_slow_rotate.gif`.
- Checksums for redistributable inputs and outputs.

## Comparison Fields

Use these fields for the comparison table:

- Track and run id.
- AI driver and CAD driver.
- Attempt count.
- Retry count.
- Correction count.
- Human intervention count.
- Elapsed minutes.
- Prompt, completion, reasoning/tool, and total tokens when available.
- CADCLAW overall severity.
- CADCLAW fail/warn counts.
- `not_built_yet` count.
- Hard-fail status.
- Final score.
- Residual blockers.

## Fresh CADCLAW Driver Command Sketch

```powershell
.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\run_grader.py `
  --spec examples\m3_crete\m3_reference_assembly.yaml `
  --no-dry-run `
  --render-views `
  --out benchmarks\m3_ai_assembly\results\fresh_cadclaw_driver_report.json

.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\score_report.py `
  benchmarks\m3_ai_assembly\results\fresh_cadclaw_driver_report.json `
  --out benchmarks\m3_ai_assembly\results\fresh_cadclaw_driver_score.json

.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\summarize_run_log.py `
  benchmarks\m3_ai_assembly\run_logs\fresh_cadclaw_driver.yaml `
  --out benchmarks\m3_ai_assembly\results\fresh_cadclaw_driver_run_summary.json

.venv\Scripts\python.exe examples\m3_crete\generate_sequence_gifs.py
```

## Fresh Native CAD Driver Command Sketch

After exporting a native CAD STEP, create a CADCLAW grading wrapper for that
export and run the same grader and scorer. The native CAD procedure records any
manual part-name mapping needed so the exported assembly is graded by the same
artifact-level checks.
