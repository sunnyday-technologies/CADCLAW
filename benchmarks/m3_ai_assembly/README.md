# M3 Assembly Workflow Benchmark

Status: prerelease scaffold.

This benchmark compares two AI-assisted assembly workflows against the same
M3-CRETE M3-2 target:

- Native CAD driver: an LLM drives a native CAD or CAD-API workflow and exports
  STEP.
- CADCLAW spec driver: an LLM edits CADCLAW assembly specs and connector
  metadata, then CADCLAW compiles authored STEP assets with CadQuery.

The benchmark grades exported artifacts with CADCLAW. It is decision support
for assembly correctness and reproducibility; it does not certify physical
printer performance.

## Current Contents

- `benchmark.yaml` defines the benchmark contract and scoring weights.
- `prompts/standard_prompt.md` is the shared prompt seed for both tracks.
- `scripts/run_grader.py` runs the CADCLAW assembly check-round and writes a
  normalized report.
- `scripts/score_report.py` converts a normalized CADCLAW report into an
  early benchmark score.
- `scripts/package_testkit.py` builds a public-safe ZIP containing only text
  seeds, prompts, scripts, and docs.
- `assets/checksums.txt` is intentionally empty until redistributable assets
  are approved.
- `assets/source_notes.md` records current source/provenance guidance.
- `results/.gitkeep` reserves the local result-output directory.

## Asset Policy

Do not add private or unlicensed STEP files, reference images, BOMs, order
data, or native CAD exports here. Assets can be added only after source,
license, redistributability, and checksum notes are recorded.

The current seed spec references local M3-CRETE assets outside this repository.
That is suitable for local development, not for a public Zenodo test kit.

## Example

```powershell
python benchmarks\m3_ai_assembly\scripts\run_grader.py `
  --spec examples\m3_crete\m3_reference_assembly.yaml `
  --dry-run `
  --out benchmarks\m3_ai_assembly\results\m3_dry_run_report.json

python benchmarks\m3_ai_assembly\scripts\score_report.py `
  benchmarks\m3_ai_assembly\results\m3_dry_run_report.json `
  --out benchmarks\m3_ai_assembly\results\m3_dry_run_score.json
```

Dry-run reports are expected to warn until connector frames, belts, motors,
drive assemblies, and tooling interfaces are fully specified and verified.

## Package

```powershell
python benchmarks\m3_ai_assembly\scripts\package_testkit.py `
  --out build\m3_ai_assembly_testkit.zip
```

The package script does not include local STEP, image, native CAD, or BOM
assets. Add those only after the asset allowlist, source notes, and checksums
are ready for public redistribution.
