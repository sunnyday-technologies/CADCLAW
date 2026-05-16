# Standard M3-CRETE Assembly Prompt

Assemble the M3-CRETE M3-2 3D concrete printing system from the provided
authored STEP assets and reference image.

Target:

- Variant: M3-2.
- Target envelope/class: 2000 x 1000 x 1000 mm.
- Use the reference image for topology and visual review only; exact dimensions
  must come from the spec, authored STEP assets, or validated measurements.

Rules:

- Place authored STEP parts. Do not generate contextual plates, brackets,
  motor mounts, NEMA hole patterns, idler holders, gantry plates, or adapter
  plates from primitive CAD recipes.
- Generate only explicitly allowed stock-like geometry: linear rail/extrusion
  stock, explicit belt segments, or standard fastener stand-ins if the test kit
  enables them.
- Do not overwrite authoritative native CAD exports.
- Keep assumptions and incomplete areas explicit as `not_built_yet`.
- Produce a non-authoritative STEP assembly, design inventory, validation
  report, and review views.

Known incomplete areas in the current seed:

- Connector frames need rendered-view and CAD inspection verification.
- Belt paths and pulley/idler routing are not fully specified.
- Motors and motor plates require authored assets and connector metadata.
- Y gantries are represented by authored actuator macro assemblies in the
  current seed; Z drive assemblies still need connector-backed placement.
- Printhead/tooling interface has not been selected for this round.

Output expectations:

- A machine-readable run manifest with model/tool versions, elapsed time,
  prompt id, input checksums where available, and non-secret provenance.
- A final STEP or dry-run assembly plan at a generated benchmark path.
- CADCLAW design inventory and report.
- Review renders for non-dry-run assemblies.
- A human intervention log noting manual edits, approvals, restarts, and failed
  attempts.
