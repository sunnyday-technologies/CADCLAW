# CADCLAW M3 Configurator Plan

Last updated: 2026-05-14

Purpose: next-session plan for turning CADCLAW from a validation harness into an M3-CRETE configurator that can assemble validated machines from authored STEP components, frame-size inputs, motion-system choices, and BOM/vendor constraints.

General harness tracking now lives in `docs/AUTO_ASSEMBLY_HARNESS_PLAN.md`.
This file remains the M3-CRETE proving-project plan.

## Operating Principle

CADCLAW should remain honest about what it builds. For M3-CRETE, the configurator should place authored STEP components from `../M3-CRETE/CAD/Components` and `../M3-CRETE/CAD/Advanced`, generate only genuinely parametric stock, then run CADCLAW validation against the emitted assembly.

Generate:

- Linear stock cut to length: C-Beam, V-Slot, Open Rail, simple internal reinforcement bars.
- Belt segments where the path is explicit.
- Optional standard fastener stand-ins only when a project asks for modeled fasteners.

Do not generate:

- Plates, brackets, motor mounts, hole patterns, NEMA helpers, idler holders, or contextual adapters.
- Crude stand-ins for authored parts.

If a needed plate/bracket/mount STEP is missing, the configurator should stop with a `not_built_yet` finding or use an explicitly flagged placeholder that fails release validation.

## What We Have

CADCLAW v0.9.0 now provides a usable validation base:

- Inventory, region inventory, interference, adjacency, dimensional, orientation, floating-part, color/material, BOM audit, parity, render/disassembly, doctor, claim-audit, and publish-audit surfaces.
- A local Python 3.11 CADCLAW runtime with CadQuery/OCP/VTK.
- M3-CRETE field-test knowledge around Fusion export omissions, CADQuery/Fusion parity, output-path clobbering, BOM drift, and unsafe parametric plate generation.

M3-CRETE CAD component libraries are present:

- `CAD/Components`: V-Slot rails in multiple profiles and lengths, NEMA 23 motors, NEMA 23 motor plates, V-Slot gantry plates, tee nuts, brackets, pulleys, idlers, wheels, spacers, bearings.
- `CAD/Advanced`: C-Beam and Open Rail stock, C-Beam actuator assemblies, C-Beam plates, NEMA 17/NEMA 23 actuator assemblies, screws, spacers, couplings, wheels, electronics.
- `CAD/Advanced/Assemblies` appears to contain prebuilt actuator assemblies; useful as references or optional macro-components, but not as the only source of configurable machines.
- Directory comparison on 2026-05-15 found `Components` is not simply replicated in `Advanced`: 68 `Components` STEP files, 76 `Advanced` STEP files, no exact normalized filename overlap, no exact SHA-256 file duplicates, and only 6 `Components` files with matching `Advanced` bbox-signature sets. Default first-pass manifest scope should be `Advanced` because of the macro assemblies; include `Components` explicitly when lower-level V-Slot/NEMA23/tee-nut assets are needed.

M3-CRETE BOM data exists separately:

- Public/design BOM source: `../M3-CRETE/bom/data.json`.
- CAD-derived structural/hardware BOM CSVs under `../M3-CRETE/CAD/`.
- Private order/procurement records exist and must not be treated as public BOM truth or echoed in reports.

## Old Goals: Keep, Revise, Deprecate

Keep:

- `cadclaw build` / `cadclaw build-piece` as a command idea, but define it as "compose and validate an assembly from a spec," not "author arbitrary CAD."
- Rule-file confidence budget extensions: `not_built_yet`, `parametric_placeholder`, source-of-truth tracking.
- STEP-vs-STEP parity, region inventory, Fusion visibility-toggle detection, and protected output path linting.
- Interactive BOM negotiation: source availability, price, shipping, and substitutions feed selection, while public reports redact private vendor/order fields.

Revise:

- The v1.0 "primitive library expanded to cover the M3-CRETE BOM" should become "component registry expanded to cover the M3-CRETE CAD/BOM libraries."
- "Generate wheels/motors/plates" should become "place authored wheel/motor/plate STEPs with connector metadata."
- The rule file should evolve from validation-only into a build spec, but with authored STEP references and placement frames as first-class data.

Deprecate:

- Parametric generation of plates, brackets, motor adapters, spacers with bolt patterns, or NEMA bolt-circle helpers.
- Any plan that uses rectangular/cylindrical stand-ins for real authored parts without a failing placeholder marker.
- Direct CADQuery export to `CAD/M3-2_Assembly.step`; generated outputs must use distinct paths such as `*_cadclaw_configured.step`.

## Gap To Close

1. Component registry

Create a manifest for every usable STEP component:

- Stable id, display name, source path, category, source library (`Components` or `Advanced`).
- Bbox signature, part count if the file is an assembly, and optional color/material expectations.
- Authorship/license/source note.
- BOM binding: public BOM id(s), procurement class, unit, quantity behavior.
- Private procurement extensions stored outside public reports: vendor, SKU, source URL, stock, unit cost, shipping class.

2. Connector and mating metadata

For each reusable component, define coordinate frames:

- Mount faces, rail slots, wheel contact lines, motor shaft axes, pulley/idler axes, belt planes, extrusion ends.
- Constraints: mate, align, offset, mirror, pattern, region, clearance.
- Orientation expectations that CADCLAW can validate after placement.

3. Config spec

Define an M3 machine spec:

- Build envelope target: 1 m, 2 m, 4 m class machines, with exact interpretation documented as target build volume/envelope, not an unsupported public claim.
- Frame profile families: C-Beam, V-Slot profile choices, Open Rail where applicable.
- Motion architecture per axis: belt, lead screw, rack/pinion, actuator macro-component, motor type.
- Segmentation policy: preferred stock lengths, splice count, max shippable length, reinforcement/splice rules.
- Required clearances, travel margins, printhead mass assumptions, and not-certified load cases.

4. Assembly templates

Create parametric placement templates that import STEP components:

- Frame cube template for 1 m / 2 m / 4 m variants.
- X/Y/Z axis templates with explicit motion-system choices.
- Gantry/carriage templates that place authored plates, wheels, motors, pulleys/idlers, belts, and brackets.
- Joint/splice templates that derive hardware counts and connector placement.

5. BOM negotiation loop

Add a selection layer that can propose alternatives:

- Choose extrusion type/length combination from BOM and source availability.
- Account for shipping constraints and source availability without exposing private vendor/order values in CADCLAW reports.
- Emit a decision trace: selected option, rejected options, cost/availability reason, assumptions, and required user approval.

6. Validation loop

Every generated assembly should immediately run:

- Inventory and region inventory against the build spec.
- Interference and floating-part checks.
- Orientation and color/material checks where metadata exists.
- Dimensional checks for frame envelope and axis travel.
- Kinematic sanity checks for beam deflection, motor torque, belt tension; these remain decision support, not certification.
- BOM-vs-CAD audit against the selected BOM.
- Claim-audit for any generated public copy.
- Render/parity for human review.

## Next-Session First Pass

1. Build `m3_component_manifest.yaml` from both M3 CAD component directories.

- Start by listing all STEP files.
- Run CADCLAW inspect/signature extraction for each.
- First pass may scan `CAD/Advanced` only, because `Advanced/Assemblies` carries prebuilt actuator macro-components. Treat `CAD/Components` as a supplemental lower-level library, not a duplicate cache.
- Mark files as `part`, `assembly`, or `macro_assembly`.
- Bind obvious public BOM ids where possible; leave ambiguous bindings as `needs_user_mapping`.

2. Define the first spec schema.

- `machine_class`: `M3-1`, `M3-2`, `M3-4`.
- `envelope_mm`: documented target dimensions.
- `frame_profile`, `axis_systems`, `stock_policy`, `source_policy`.
- `outputs`: configured STEP path, generated BOM path, report path.

3. Prototype only one narrow vertical slice.

Recommended slice: rectangular base/top frame from authored extrusion stock plus corner/joining components, for `M3-1`.

Acceptance:

- Produces a STEP at a non-authoritative output path.
- Emits a BOM/design inventory.
- Runs CADCLAW harness.
- Reports `not_built_yet` for axes/gantry rather than pretending the machine is complete.

4. Add connector metadata for the parts used by that slice.

- Extrusion endpoints.
- Corner bracket mating faces.
- Joining plate faces.
- T-nut/fastener derivation rules as BOM-only unless modeled.

5. Expand axis-by-axis.

- Add Y rails and drive.
- Add X gantry.
- Add Z/lift system.
- Add printhead/tooling interface only from authored STEP assets.

## Open Decisions

- Are 1 m, 2 m, and 4 m "cubic meter" variants build-volume targets, outer-frame targets, or named product classes? Public copy should not imply validated cubic-meter performance until physically validated.
- Should actuator assemblies in `CAD/Advanced/Assemblies` be treated as placeable macro-components, or only as reference assemblies decomposed into lower-level parts?
- Which extrusion families are approved for each machine class?
- What maximum shipped stock length should the BOM negotiator prefer?
- What vendor/source data may be public, and what stays private procurement state?
- Where should the configurator live: CADCLAW core, M3-CRETE repo, or a separate `cadclaw_m3` package?

## Definition Of Complete

The first useful configurator is complete when a user can provide:

- Machine class / target envelope.
- Frame profile family and axis motion choices, or permission for CADCLAW to choose.
- Source/cost/availability policy.

And CADCLAW can produce:

- Configured STEP assembly from authored parts and generated stock.
- Public BOM/design inventory with private procurement fields redacted.
- CADCLAW report saying what was checked, what was not checked, what was assumed, and what remains not built.
- Rendered review image/GIF.
- Explicit warning that physical performance still requires engineering and build validation.
