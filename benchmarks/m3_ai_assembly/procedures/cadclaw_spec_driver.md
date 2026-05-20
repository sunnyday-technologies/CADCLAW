# CADCLAW Spec Driver Procedure

Purpose: run the CADCLAW-spec-driver track against the M3-CRETE M3-2 fixture.

Inputs:

- Prompt: `benchmarks/m3_ai_assembly/prompts/standard_prompt.md`
- Benchmark contract: `benchmarks/m3_ai_assembly/benchmark.yaml`
- Seed assembly spec: `examples/m3_crete/m3_reference_assembly.yaml`
- Connector metadata: `examples/m3_crete/m3_connector_metadata.yaml`
- Minimal asset allowlist: `examples/m3_crete/m3_testkit_assets.yaml`

Procedure:

1. Start from a clean branch or record all local changes in the run manifest.
2. Give the shared prompt to the AI driver.
3. Permit edits only to CADCLAW specs, connector metadata, benchmark run notes,
   and generated benchmark output paths.
4. Run the grader:

```powershell
.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\run_grader.py `
  --spec examples\m3_crete\m3_reference_assembly.yaml `
  --no-dry-run `
  --no-render-views `
  --out benchmarks\m3_ai_assembly\results\cadclaw_spec_driver_report.json
```

5. Score the report:

```powershell
.venv\Scripts\python.exe benchmarks\m3_ai_assembly\scripts\score_report.py `
  benchmarks\m3_ai_assembly\results\cadclaw_spec_driver_report.json `
  --out benchmarks\m3_ai_assembly\results\cadclaw_spec_driver_score.json
```

6. Record elapsed time, model/tool version, prompt id, input checksums where
   available, interventions, and any failed attempts. Do not record credentials,
   private procurement fields, or local secret paths.

Expected current status:

- CADCLAW gates pass for the placed reference geometry.
- The report remains `WARN` until declared `not_built_yet` subsystems are
  either modeled from authored STEP assets or explicitly scoped out of the run.
