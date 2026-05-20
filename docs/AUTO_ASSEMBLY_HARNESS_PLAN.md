# CADCLAW Auto-Assembly Harness Plan

Last updated: 2026-05-18

Purpose: define and track a general CADCLAW assembly harness that lets an
LLM or human assemble a STEP-based machine with CadQuery, using authored
parts, intermediate rendered review views, and CADCLAW validation gates.
M3-CRETE is the first proving project, not a hardcoded product assumption.

## North Star

CADCLAW should support this loop:

1. A user provides a reference asset, component STEP folders, and a target
   assembly intent.
2. An LLM drafts or edits an assembly spec.
3. CADCLAW compiles the spec with CadQuery by placing authored STEP assets
   and generating only explicitly allowed stock-like geometry.
4. CADCLAW emits a STEP, design inventory, validation report, and named
   review views.
5. The human/LLM reviews those views, makes corrections, and repeats.

The harness is not an autonomous CAD authoring system. It is a structured
placement, validation, and review loop.

## First Reference Asset

The initial tracked target is the M3-CRETE frame render:

- Local reference image: `../M3-CRETE/docs/M3-CRETE_render.jpg`
- Role: visual assembly target for topology, rough proportions, and review
  view comparison.
- Limitation: this image is not dimensional evidence. Exact dimensions must
  come from the assembly spec, authored STEP components, or user-supplied
  measurements.

If the reference image becomes part of the open-source fixture set, copy it
into a public repo path with license/source notes first. Until then, keep the
spec capable of referencing a local asset without embedding it.

## Operating Rules

- Place authored STEP parts for plates, brackets, mounts, motors, gantries,
  wheels, pulleys, idlers, adapters, and other contextual geometry.
- Generate only declared stock-like geometry: linear extrusion cuts, explicit
  belt segments, optional fastener stand-ins when requested.
- Never generate NEMA hole patterns, contextual plates, or rectangular/cylindrical
  stand-ins for authored parts.
- Generated output paths must be non-authoritative and must not overwrite native
  CAD exports.
- Every incomplete section must be represented as `not_built_yet`, not hidden.
- Every round should produce both machine-readable findings and human-readable
  rendered views.

## General Architecture

```text
STEP folders
  -> component manifest
  -> connector metadata
  -> assembly spec
  -> CadQuery assembly compiler
  -> STEP output
  -> CADCLAW validation gates
  -> review views
  -> human/LLM correction loop
```

## Benchmark Track

The M3 assembly workflow benchmark is tracked in
`docs/M3_AI_ASSEMBLY_BENCHMARK.md`. It compares:

- **Native CAD driver:** an LLM works through native CAD or CAD-API tooling and
  exports STEP.
- **CADCLAW spec driver:** an LLM edits assembly specs and connector metadata
  while CADCLAW/CadQuery compiles and validates each round.

CADCLAW grades both routes with the same STEP, BOM, and review-view checks.
This keeps the comparison focused on where verification belongs in the loop,
not on which tool can produce the most plausible render.

## Core Artifacts

1. **Component Manifest**
   Records authored STEP assets, bbox signatures, source library, part counts,
   generation policy, BOM binding status, and connector metadata status.

2. **Connector Metadata**
   Defines reusable local frames: extrusion endpoints, mount faces, rail slots,
   wheel contact lines, motor shaft axes, belt planes, and bracket faces.

3. **Assembly Spec**
   Declares reference assets, manifests, outputs, placed instances, transforms,
   review views, validation expectations, assumptions, and `not_built_yet`
   items.

4. **CadQuery Compiler**
   Imports authored STEP parts, applies transforms and patterns, optionally
   generates stock-only geometry, exports STEP, and writes design inventory.

5. **Review Views**
   Named renders such as `front`, `left`, `right`, `top`, `iso`, and local
   detail views. These are first-class outputs because the human guide catches
   alignment mistakes visually between rounds.

6. **Validation Report**
   Runs CADCLAW checks immediately after assembly. Reports what passed, what
   failed, what was not checked, and what is not built yet.

7. **FEA Decision Support (Future)**
   Optional PyNiteFEA models in `FEA/` can compare static frame member sizes,
   joint layouts, and assembly techniques after connector-valid geometry
   exists. This is for engineering decision support and comparison, not a
   substitute for authored CAD placement or physical validation.

## M3-CRETE First Slice

Goal: approximate the reference printer frame using authored assets from:

- `../M3-CRETE/CAD/Advanced`
- `../M3-CRETE/CAD/Components`

Existing M3-CRETE work to reuse, not duplicate:

- `../M3-CRETE/CAD/m3_2_assembly.py` is the current
  hand-built CadQuery/filter-and-replace assembly script.
- `../M3-CRETE/CAD/preview_assembly.py` already encodes the
  most valuable human/LLM workflow pattern: engineering invariants plus
  generated orthographic review PNGs after every edit.
- `../M3-CRETE/CAD/bom_generate.py` already derives a structural
  BOM and hardware pack from the live assembly. CADCLAW should generalize this
  into a design-inventory/BOM emitter instead of starting from a blank design.
- `../M3-CRETE/config.js` defines the active variant model:
  M3-2 is the base BOM quantity set, with M3-1 and M3-4 expressed through
  quantity overrides.

Initial output targets:

- `examples/m3_crete/build/m3_reference_round1.step`
- `examples/m3_crete/build/m3_reference_round1_inventory.json`
- `examples/m3_crete/build/m3_reference_round1_report.json`
- `examples/m3_crete/build/views/*.png`

Current useful build:

- X gantry beam and X-carriage/end plates first.
- Authored 1000 mm C-Beam rail datums as the two Y gantries; the full actuator
  macro stays out until its end hardware can be placed without clipping.
- X-to-Y and Y-to-Z handoff plate declarations from authored plate STEP assets.
- Explicit 6 mm side-rail/post frame spacer declarations so the frame clearance
  is visible in the design inventory and BOM CSV.
- Four C-Beam Z posts and the remaining 1000 mm frame extrusions placed after
  the moving gantry stackup.

Acceptance for round 1:

- Produces a non-authoritative STEP.
- Produces front/iso/top review renders.
- Lists every authored STEP placed.
- Emits a design inventory.
- Emits `not_built_yet` for missing axes, belt paths, motors, tooling, and
  any connector metadata not yet defined.
- Does not create contextual plates/brackets from scratch.

## M3-CRETE Variant Targets

The assembly harness should treat these as configuration variants:

| Variant | Target Envelope | Notes |
|---|---:|---|
| M3-1 | 1000 x 1000 x 1000 mm | No spliced long axis; all primary stock is 1000 mm. |
| M3-2 | 2000 x 1000 x 1000 mm | Current proving target; X direction is spliced from 1000 mm stock. |
| M3-4 | 2000 x 2000 x 1000 mm | X and Y directions are spliced; BOM quantities come from variant overrides. |

These are target build envelopes/classes, not public claims of physically
validated performance.

## Lessons From Prior M3-CRETE Assembly Work

- **Self-checks are part of assembly, not an afterthought.** The old
  `preview_assembly.py` ran hundreds of geometry invariants and wrote
  orthographic PNGs. CADCLAW's new assembly round should always emit both.
- **Prefer placement and filter-and-replace over re-authoring.** Existing
  code captured authored STEP parts and cloned them by signature when
  necessary. That remains the right pattern for mounts, brackets, plates,
  carriages, wheels, and motor-adjacent geometry.
- **Generated geometry needs guardrails.** C-beam/linear stock and belts are
  reasonable generated/parameterized geometry; contextual plates and bolt
  patterns are not.
- **Source STEP visibility is fragile.** Native CAD exports can omit hidden or
  suppressed parts. The harness should compare inventories between
  reference/source STEP files and generated assemblies.
- **Output paths must be protected.** Earlier work explicitly moved CadQuery
  output to `M3-2_Assembly_cadquery.step` to avoid clobbering authoritative
  native CAD exports.
- **BOM is partly modeled and partly derived.** Fasteners and some hardware
  should come from rules over detected joints and placed parts, not necessarily
  from modeled bodies.
- **Variant quantities already exist.** CADCLAW should ingest or mirror the
  `config.js` variant-override model instead of inventing a second variant
  source of truth.
- **Known exclusions should become validation rules.** Do not reintroduce
  limit switches, leveling feet, external X-gantry reinforcement, HEPA filters,
  LED lighting, or carbon-fiber bars unless the project spec explicitly changes.
- **M3-2 design-specific constraints matter.** 4080 C-Beam is the primary
  structure; 1000 mm stock is the shipping-constrained standard length; C
  openings face inward; X-gantry reinforcement stays internal/below wheel path.
- **Build inside-out when spacing depends on motion.** For M3-2, the X gantry
  end plates are the X-to-Y handoff; the Y gantry ends attach to Z-carriage
  plates; the Z posts and frame then accommodate that stackup. The assembly
  sequence is therefore a spacing strategy, not just a presentation order.
- **Spacer placement must be explicit.** Current user guidance sets the
  side-rail/post frame spacer at 6 mm. That spacer moves the frame outward to
  accommodate the gantry; it is not inserted between the moving gantry plate
  and the Z post. In the current design the spacer is also the motor mount, so
  the final ZPMM STEP/BOM binding must be frozen before release.
- **Plate family selection is part of the tolerance stack.** The X-to-Y
  handoff uses the 125 x 125 x 6 mm C-Beam Gantry Plate XLarge asset, 2x
  total. The Y-to-Z/Z-post carriage interfaces use the smaller V-Slot 20-80
  gantry plate asset, inspected as roughly 127 x 88 x 3 mm. Substituting one
  plate family into the other interface should fail the reference spec.
- **V-slot handoff stackup is now a declared validation gate.** CADCLAW checks
  declared V-slot/C-Beam handoffs for the repeated pattern: current gantry end
  face, declared gantry plate thickness with its thin axis aligned to the
  handoff axis, a declared running clearance, then the next axis. This is
  general to V-slot style assemblies and should fail early when a plate is
  embedded in a rail body or rotated onto the wrong plane.
- **Authored-hole alignment is now a declared validation gate.** CADCLAW can
  read cylindrical features from placed STEP assets and compare hole centers
  in the plane perpendicular to the handoff axis. This catches the Y-gantry to
  Z-carriage mounting-hole alignment issue without generating bolt patterns or
  treating nominal public specs as assembly evidence.
- **Static frame joints need a different gate than motion clearances.** The
  frame should not be made "valid" by adding clearance. C-Beam/post joints
  need flush adjacency and bearing overlap for rigidity; visible gaps should
  fail unless an authored connector or spacer STEP is explicitly placed.
- **FEA belongs after geometry validity.** A PyNiteFEA helper can later compare
  4080, 2080, or 2040 static frame-member options and joint techniques, but it
  should consume the already-declared assembly topology. Gantry extrusions stay
  C-Beam unless a separate authored reinforcement spec says otherwise.
- **Authored STEP exports still need unit sanity checks before placement.**
  The resized `ZPMM.step` export now loads as 6.1 x 80 x 97 mm, matching user
  guidance that the intended printed thickness is 6.1 mm. CADCLAW still
  declares `source_origin_mm` so the in-place CAD export is recentered before
  rotation and placement.
- **Rendered review is not validation.** A clipping error in the M3 reference
  sequence exposed that `validation.run_checks: [interference]` was declared
  but not executed by `assemble check-round`. The assembly compiler now runs an
  instance-level solid interference gate and reports `interference.clip`
  findings with instance IDs and suggested clear shifts.
- **Assembly should be gated, not compiled straight through.** Each cumulative
  step should be exported, checked, rendered for review, and then either marked
  `pass` or stopped with explicit repair suggestions. Later steps should not be
  rendered on top of a failed datum.
- **Repair suggestions need assembly context.** The raw boolean overlap can
  compute a minimum clear shift, but the suggested target should respect the
  build step and role semantics. For example, an X plate embedded in an X beam
  should report "move the plate off the beam face"; a later frame/post element
  added around an already accepted gantry should usually move to accommodate the
  accepted gantry datum.

## Implementation Checklist

- [x] Component manifest helper.
- [x] M3-CRETE Advanced manifest generation.
- [x] Compare `Components` vs `Advanced` and document that they are not
      duplicates.
- [x] General assembly spec schema and loader.
- [x] M3-CRETE reference assembly spec.
- [x] CLI spec validator: `cadclaw assemble validate-spec`.
- [x] Formal M3 AI assembly benchmark plan.
- [x] Shareable process-flow graphics and repeatable generator.
- [x] Connector metadata schema.
- [x] Compiler dry-run/source-resolution report.
- [x] Initial CadQuery compiler for explicit authored-STEP placements.
- [x] Stock-only generation policy guards for the current spec contract.
- [x] Design inventory emitter.
- [x] Standard review view renderer.
- [x] Validation wrapper for generated assembly rounds.
- [x] Initial CLI tools for LLM operation.
- [x] Gantry-first M3-2 assembly sequence: X gantry, Y gantries, Z carriage
      plates, Z posts, then frame completion with 6 mm frame spacers.
- [x] Explicit 6 mm side-rail/post frame spacer declarations in the M3
      reference spec and BOM CSV path.
- [x] Correct plate-family assignment by handoff: X-to-Y uses 2x C-Beam
      Gantry Plate XLarge, while Y-to-Z/Z-post carriage interfaces use the
      smaller 3 mm V-Slot 20-80 plate.
- [x] Instance-level interference validation wired into assembly check rounds
      and per-step sequence reports.
- [x] Gated `render-sequence` behavior that stops at the first declared
      validation failure by default.
- [x] Per-step manifest status and repair suggestions for human checkpoint
      review.
- [x] Role-aware/context-aware interference repair target selection.
- [x] V-slot handoff stackup validation gate with explicit 3 mm plate and
      declared running clearance.
- [x] Static frame adjacency validation gate for flush C-Beam/post joints and
      structural bearing overlap.
- [x] Authored cylindrical-feature alignment gate for Y-gantry to Z-carriage
      hole checks in the M3 reference sequence.
- [x] Resolve the M3-2 side-rail/post gap exposed by static frame adjacency
      for the reference round: posts are placed on the 6 mm frame-spacer datum,
      and resized native-scale ZPMM motor-mount/spacer instances bridge
      post-to-side-rail joints.
- [x] Generate user-approved no-hole flat spacer plate STEP assets for the
      M3 reference round, including `M3_6mm_frame_shim_4080.step` inspected as
      6 x 40 x 80 mm. This remains a simple fallback fixture; the active M3
      reference spec now uses the authored ZPMM STEP instead.
- [x] Inspect exported `ZPMM.step` candidate and render isolated review views.
      The resized file is authored and loadable; the inspected native bbox is
      6.1 x 80 x 97 mm, with a user-confirmed intended printed thickness of
      6.1 mm.
- [x] Replace generated frame shim placeholders with the authored ZPMM
      motor-mount/spacer STEP using native millimeter scale and explicit
      source-origin recentering.
- [x] Add optional PyNiteFEA integration for static frame member and
      joint-technique comparison after connector-valid geometry exists. The
      first tracked M3 load cases live in
      `examples/m3_crete/m3_fea_load_cases.yaml`; generated reports, CSVs, and
      stress/strain plots are emitted under `examples/m3_crete/build/fea/`.

## LLM Tool Surface

The eventual tool surface should be deterministic and narrow:

- `cadclaw manifest build`
- `cadclaw assemble inspect-component`
- `cadclaw assemble validate-spec`
- `cadclaw assemble build`
- `cadclaw assemble render-views`
- `cadclaw assemble render-sequence`
- `cadclaw assemble check-round`
- `cadclaw assemble suggest-adjustment`
- `cadclaw fea joint-adequacy`
- `examples/m3_crete/run_fea_load_cases.py`
- future `cadclaw fea compare-frame` helper for member-option sweeps

The LLM should edit specs and connector metadata, not freehand arbitrary
CadQuery scripts.

Current implementation status:

- `assemble build` resolves authored STEP sources, writes design inventory,
  and can export an explicit CadQuery assembly from placed authored STEP files.
- `assemble inspect-component` resolves one authored STEP component from a
  spec/manifest or direct source path, reports bbox signatures, and can render
  isolated review views for orientation checks.
- `assemble render-views` renders declared PNG review views from the generated
  STEP using the existing CADCLAW VTK renderer.
- `assemble render-sequence` exports cumulative partial STEP assemblies,
  renders per-step X/Y/Z/hero/iso image sets, runs per-step instance-level
  interference, V-slot handoff stackup, static frame adjacency, and authored
  hole-alignment checks when requested, stops on the first failed validation by
  default, records per-step validation status and repair suggestions in the
  sequence manifest, can render a final rotating GIF after all gates pass, and
  emits a public-safe CSV BOM grouped by authored STEP source and role.
- `assemble check-round` runs one build round, verifies declared spec role
  inventory, runs declared instance-level interference, V-slot handoff
  stackup, static frame adjacency, and authored hole-alignment checks,
  optionally renders review views, and emits a single report.
- `assemble suggest-adjustment` remains future work; for now adjustment advice
  comes from existing CADCLAW findings such as `interference.clip`.

## Open Decisions

- Should the first compiler live in CADCLAW core, `examples/m3_crete`, or a
  future `cadclaw_assembly` package?
- What connector metadata is the minimum needed before placement becomes
  reliable instead of image-guided guessing?
- Which M3-CRETE dimensions are authoritative for M3-1/M3-2/M3-4: outer frame,
  target build envelope, or product class names?
- Public fixtures should include the resized native-scale `ZPMM.step` directly
  when licensing/source notes permit; the generated no-hole shim is superseded
  for the active M3 reference and should stay out of the minimal test kit.
- Which spacer/motor-mount instances need top-only, bottom-only, mirrored, or
  endcap geometry once the final ZPMM STEP is available?
- Which frame-member options should the future FEA comparison sweep include
  first: 4080 baseline, 2080 static rails, 2040 static rails, or 2040
  reinforcement members around C-Beam gantries?
- Which reference assets can be redistributed publicly?
- How strict should release validation be about `not_built_yet` findings?
