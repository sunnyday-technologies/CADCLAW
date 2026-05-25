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

Current M3-2 fixture constraints:

- Build inside-out: place the X gantry and end plates first, add the two-sided
  X carriage, then the Y gantries, then Y-to-Z/Z-post carriage plates, then
  the Z posts and frame members around that motion stack.
- The two-sided X-axis printhead carriage uses two C-Beam Gantry Plate XLarge
  (125x125x6 mm), one each side of the X beam, for the toolhead's off-axis
  forces. All other gantry plates are the small V-Slot 20-80: two at the X-to-Y
  handoff (one at each X gantry end) and the four Y-to-Z/Z-post carriage plates.
  (This X-carriage XLarge choice intentionally diverges from the V1.0 source,
  which has zero XLarge.)
- Y-gantry C-Beams place their 80 mm dimension vertically and open channels
  face inward toward the printer volume.
- X-gantry C-Beams also place their 80 mm dimension vertically. The 2 m
  X-gantry run contains one authored 1000 mm 2040 V-slot insert centered
  across the middle splice between the two 1000 mm 4080 C-Beam segments.
- Each 2 m top X-direction frame run also contains one authored 1000 mm 2040
  V-slot insert centered across its middle splice.
- The frame is open at the bottom in the X direction; do not add bottom X
  frame rails unless the benchmark spec changes.
- Lower Y-direction static frame rails are 2080 V-slot, not C-Beam.
- The top center spreader is a 2040 V-slot extrusion. Place it with the 40 mm
  side vertical and the top surface level with the surrounding top frame
  members.
- The top center spreader uses a 2-plate (6 mm) stack of small V-Slot 20-80
  plates at each end (four plates total) as mounting bracket/spacer stock.
- Place authored Solid V Wheel STEP instances at the modeled X-to-Y,
  X-carriage, and Y-to-Z carriage interfaces so wheel-slot and wheel-hole
  location choices are visible in review renders. Each gantry plate uses four
  wheels; wheel centerlines align to authored plate holes, and the wheel inner
  face is held 7 mm off the plate face by a 6 mm spacer plus 1 mm washer stack.
  Eccentric washers may absorb a few millimeters of remaining adjustment, but
  the alignment error must be reported.
- Top side-rail/post spacer locations use the authored ZPMM motor-mount/spacer
  STEP. Lower side-rail/post spacer locations use a simple 6 x 40 x 80 mm flat
  spacer.
- CADCLAW's model-derived BOM is an overcheck artifact. Compare it against the
  M3 interactive BOM, but do not overwrite the M3-owned public BOM.

Known incomplete areas in the current seed:

- Connector frames need rendered-view and CAD inspection verification.
- Z-axis and Y-axis GT2 belts are placed as cosmetic per-run stock, with
  pulleys and return idlers; the X drive is the authored VS_Belt_Pinion. Final
  belt-path tuning remains a render-review item.
- The seven NEMA 23 motors are placed; no separate motor mount plates are used
  (the Y-motor screws directly to the C-beam, and homing is sensorless via the
  stepper driver's StallGuard, so there is no physical endstop part). Mount
  plates may be added in a later version.
- Y gantries are placed authored C-Beam rail datums; their Z-carriage plates and
  wheels cascade onto them via the relative-placement resolver.
- 32 Solid V Wheel instances are placed in the current seed, including the
  two-sided X-carriage wheel set.
- The current seed checks authored-hole alignment for the Y-gantry to
  Z-carriage plate interfaces.
- Printhead/tool payload and final carriage mount interface have not been
  selected for this round.

Output expectations:

- A machine-readable run manifest with model/tool versions, elapsed time,
  prompt id, input checksums where available, and non-secret provenance.
- A final STEP or dry-run assembly plan at a generated benchmark path.
- CADCLAW design inventory and report.
- Review renders for non-dry-run assemblies.
- A human intervention log noting manual edits, approvals, restarts, and failed
  attempts.
