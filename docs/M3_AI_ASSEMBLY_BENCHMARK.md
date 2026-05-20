# M3 Assembly Workflow Benchmark

Status: draft benchmark plan

Purpose: compare two AI-assisted CAD assembly workflows on the same
M3-CRETE M3-2 target, using the same reference assets and CADCLAW as the
grader. The benchmark is intended to measure assembly correctness and
reproducibility, not to certify physical performance.

## Comparison

| Track | Description | Primary artifact |
|---|---|---|
| Native CAD driver | AI works in or through native CAD or CAD-API tooling and exports STEP. | Native-authored/exported STEP assembly. |
| CADCLAW spec driver | AI edits CADCLAW assembly specs and placement metadata, then CADCLAW compiles authored STEP assets into an assembly. | CADCLAW-generated STEP assembly plus spec, inventory, and report. |

Both tracks receive the same prompt, same target definition, same STEP asset
library, same reference image, and same public constraints. The grader is
CADCLAW run against the exported STEP, not subjective approval of the tool
used to create it.

## Target

- Project: M3-CRETE.
- Variant: M3-2.
- Target envelope: `2000 x 1000 x 1000 mm`.
- Interpretation: target build envelope/class, not a claim of physical
  validation or certified performance.
- Required posture: assemble from authored parts; generate only allowed
  stock-like geometry.

## Shared Inputs

Initial local sources:

- Reference image: `../M3-CRETE/docs/M3-CRETE_render.jpg`.
- Minimal test-kit asset declaration:
  `examples/m3_crete/m3_testkit_assets.yaml`.
- CADCLAW assembly spec seed:
  `examples/m3_crete/m3_reference_assembly.yaml`.
- CADCLAW broad component manifest, for internal discovery only:
  `examples/m3_crete/m3_component_manifest.yaml`.
- Public BOM source, if included in a run:
  `../M3-CRETE/bom/data.json`.

The reference image is for topology, proportions, and human review only. Exact
dimensions must come from the target spec, authored STEP assets, or validated
measurements.

Current M3-2 wheel placement uses four authored Solid V Wheel STEP instances
per modeled gantry plate. The wheel centerlines align to authored gantry-plate
holes, and the wheel inner face is checked at a 7 mm standoff from the plate
face to represent the 6 mm spacer plus 1 mm washer stack. Eccentric washers
may absorb a few millimeters of remaining adjustment, but the run report must
still expose that alignment evidence.

The shared benchmark/dev-kit package should include only the STEP files listed
in `m3_testkit_assets.yaml`, plus license/source notes. The full local
OpenBuilds-derived `Advanced` and `Components` directories are useful for
discovery but should not be treated as the public input package. Cite the
upstream OpenBuilds STEP Parts Library for provenance rather than vendoring
unused catalog files.

Protected authoritative exports must not be overwritten:

- `../M3-CRETE/CAD/M3-2_Assembly.step`
- `../M3-CRETE/CAD/M3-2_Assembly_latest.step`
- `../M3-CRETE/CAD/M3-2_Assembly-latest.step`

## Allowed Geometry Policy

Allowed generation:

- Linear extrusion or rail stock cut to declared lengths.
- Belt segments where the belt path is explicit.
- Standard fastener stand-ins only when the test kit explicitly enables
  modeled fasteners.

Required placement from authored STEP:

- Plates, brackets, motor mounts, gantry plates, idler holders, adapters,
  motors, wheels, pulleys, actuator assemblies, and other contextual parts.

Forbidden:

- Generated NEMA hole patterns or bolt-circle helpers.
- Contextual plates or brackets made with primitive CAD recipes.
- Crude stand-ins for authored parts unless explicitly marked as
  `not_built_yet` or `parametric_placeholder` and scored as incomplete.

## Required Outputs Per Run

Each competitor run should emit:

- Final STEP assembly at a non-authoritative benchmark output path.
- Machine-readable run manifest with tool versions, model/provider name,
  prompt id, input asset hashes, and elapsed time.
- Source artifacts needed to reproduce the run: native script/export notes for
  the native-CAD-driver track, assembly spec and placement metadata for the
  CADCLAW-spec-driver track.
- CADCLAW design inventory.
- CADCLAW validation report.
- Named review renders: `front`, `left`, `right`, `top`, `iso`, plus any
  local detail views required by the report.
- Human intervention log: manual edits, approvals, restarts, and failed runs.

The run manifest must not contain API keys, auth headers, private procurement
fields, private database URLs, or secret environment values.

## CADCLAW Grading Gates

Minimum gates:

- STEP loadability and solid inventory.
- Inventory and region inventory against expected M3-2 components.
- Interference checks with configured clearance.
- Floating-part and adjacency checks for placed assemblies.
- Dimensional checks for target envelope and major axis spans.
- Authored-hole alignment checks for declared connector/handoff groups.
- Orientation/color/material checks where metadata exists.
- BOM-vs-CAD audit when the public BOM is included.
- Parity/protected-path checks to prevent clobbering authoritative native CAD
  exports.
- Claim-audit for any generated public text.

Every report must include a confidence budget: checked, not checked,
assumptions, and `not_built_yet` items.

## Metrics

Primary metrics:

- CADCLAW pass rate by gate.
- Number and severity of CADCLAW findings.
- Completeness: expected major subsystems present, `not_built_yet` count, and
  unauthorized placeholder count.
- Authored-asset fidelity: fraction of non-stock parts placed from approved
  STEP assets.
- Dimensional accuracy against M3-2 target envelope and configured spans.
- Interference volume/count and minimum clearance violations.
- BOM parity: missing, extra, and quantity-drifted items.
- Reproducibility: clean rerun success, deterministic output hashes where
  practical, and complete provenance.
- Human effort: manual corrections, restarts, elapsed wall time, and prompt
  count.

Secondary metrics:

- Review-view usefulness: required views rendered, nonblank, and aligned with
  the target topology.
- Cost observability: public, non-secret cost assumptions recorded when used.
- Claim hygiene: no unsupported production-readiness, validation, compliance,
  carbon, durability, patent, or guarantee claims.

Suggested score breakdown:

| Area | Weight |
|---|---:|
| CADCLAW gate results | 35 |
| Assembly completeness and authored-asset fidelity | 25 |
| Dimensional/topology match | 15 |
| Reproducibility and provenance | 10 |
| Human effort | 10 |
| Claim hygiene and packaging readiness | 5 |

Hard fails override weighted score for secret exposure, protected-path
overwrite, non-loadable STEP output, or uncontrolled generation of contextual
plates/brackets.

## Test Kit Packaging

Proposed public package layout:

```text
benchmarks/m3_ai_assembly/
  README.md
  benchmark.yaml
  prompts/
  assets/
    reference/
    step/
    checksums.txt
  seeds/
    m3_reference_assembly.yaml
    m3_testkit_assets.yaml
    m3_connector_metadata.yaml
  rules/
    cadclaw.yaml
  scripts/
    run_grader.py
    score_report.py
  expected_schema/
  results/
    .gitkeep
```

Packaging rules:

- Include only redistributable STEP assets and reference images with license
  and source notes.
- Use checksums for every asset.
- Exclude private procurement/order data and all credentials.
- Pin CADCLAW version, Python version, CadQuery/OCP versions, OS, and scorer
  version.
- Store large STEP/reference assets in a release artifact or Zenodo deposit if
  they are too large for normal Git history.
- Include `CITATION.cff`, license files, and a benchmark README explaining
  what is checked and what remains outside scope.

Zenodo notes:

- Publish immutable benchmark releases, not mutable local paths.
- Record asset hashes and scorer commit SHA in the Zenodo metadata.
- Use a concept DOI for the benchmark family and versioned DOIs for fixture
  releases.
- Do not publish a result as broadly representative of AI CAD ability unless
  multiple targets and repeated runs are included.

## Public Claim Cautions

Use careful language:

- "designed to assemble from authored STEP assets"
- "CADCLAW-graded decision support"
- "early benchmark"
- "where sufficient validated data is available"
- "requires physical validation"

Avoid unsupported claims:

- "production ready"
- "certified"
- "fully validated"
- "guaranteed"
- "proves AI can replace CAD engineers"
- "proves one model/tool is best at CAD"
- "physically validated M3-2 performance"

CADCLAW checks configured rules against STEP/BOM/text artifacts. Passing the
benchmark means the run passed those gates for this fixture; it does not prove
the physical machine, native CAD source, procurement state, or all possible
manufacturing constraints.

## Next Implementation Steps

- [ ] Preserve the exact native-CAD-driver test procedure and prompt variant
      used for any published run.
- [ ] Audit which M3-CRETE STEP assets and reference images can be redistributed
      publicly.
- [x] Freeze an initial M3-2 seed spec and component manifest for benchmark use.
- [x] Add a benchmark fixture directory scaffold with asset checksum and
      license-note placeholders.
- [x] Implement `run_grader.py` to run the CADCLAW gates and emit normalized
      JSON.
- [x] Implement `score_report.py` with the metric weights and hard-fail rules
      above.
- [ ] Run at least one native-CAD-driver and one CADCLAW-spec-driver dry run
      against the same fixture.
- [ ] Publish a prerelease fixture package, then archive the first stable test
      kit on Zenodo.

## Local References

- `docs/AUTO_ASSEMBLY_HARNESS_PLAN.md`
- `docs/M3_CONFIGURATOR_PLAN.md`
- `examples/m3_crete/m3_reference_assembly.yaml`
- `examples/m3_crete/m3_testkit_assets.yaml`
- `examples/m3_crete/m3_bom_audit.yaml`
- `docs/M3_BOM_PARITY_NOTES.md`
- `examples/m3_crete/m3_component_manifest.yaml`
