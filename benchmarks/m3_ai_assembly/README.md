# M3 AI Assembly Benchmark

Status: prerelease scaffold.

This benchmark compares two AI-assisted assembly workflows against the same
M3-CRETE M3-2 target:

- Claude-Fusion: an LLM drives Fusion/native CAD tooling and exports STEP.
- AI-CADCLAW: an LLM edits CADCLAW assembly specs and connector metadata, then
  CADCLAW compiles authored STEP assets with CadQuery.

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
- `assets/checksums.txt` is intentionally empty until redistributable assets
  are approved.
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
