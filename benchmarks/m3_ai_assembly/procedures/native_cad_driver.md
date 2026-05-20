# Native CAD Driver Procedure

Purpose: run the native-CAD-driver track against the same M3-CRETE M3-2
fixture. This procedure is tool-neutral: the driver may use Fusion, another
native CAD package, or a CAD API, but the exported artifact is graded by
CADCLAW.

Inputs:

- Prompt: `benchmarks/m3_ai_assembly/prompts/standard_prompt.md`
- Benchmark contract: `benchmarks/m3_ai_assembly/benchmark.yaml`
- Minimal STEP asset allowlist: `examples/m3_crete/m3_testkit_assets.yaml`
- Seed assembly spec for target constraints and CADCLAW grading:
  `examples/m3_crete/m3_reference_assembly.yaml`
- Connector metadata for intended local frames:
  `examples/m3_crete/m3_connector_metadata.yaml`
- Reference topology image, if redistributed for the run.

Procedure:

1. Prepare a fresh native CAD project/workspace.
2. Provide only the approved test-kit assets, the shared prompt, and the seed
   constraint files listed above.
3. Instruct the AI driver to place authored parts and export a non-authoritative
   STEP assembly. It must not modify or overwrite authoritative M3-CRETE native
   CAD exports.
4. Export the assembly STEP to a benchmark output path, for example:
   `benchmarks/m3_ai_assembly/results/native_cad_driver.step`.
5. Create or adapt a CADCLAW assembly/rule wrapper for grading that exported
   STEP against the benchmark gates. Record any manual mapping needed between
   native CAD part names and CADCLAW labels.
6. Run CADCLAW grading and scoring with the same scoring script used by the
   CADCLAW-spec-driver track.
7. Record the exact native CAD tool version, AI driver, prompt id, elapsed
   time, manual interventions, failed attempts, and exported-file checksums.

Current M3-2 fixture constraints to verify before export:

- No bottom X-direction frame rails in the open-frame design.
- Lower Y-direction static frame rails are 2080 V-slot.
- The top center spreader is 2040 V-slot with the 40 mm side vertical and top
  face level with the top frame.
- Y-gantry C-Beams place the 80 mm dimension vertically and open channels face
  inward.
- X-gantry C-Beams place the 80 mm dimension vertically and include one
  internal 2040 insert per 1000 mm C-Beam segment.
- X-to-Y plates and X-carriage plates are C-Beam Gantry Plate XLarge;
  Y-to-Z/Z-post carriage plates are V-Slot 20-80.
- Top spacer/motor-mount locations use ZPMM; lower spacer locations use the
  simple flat 6 x 40 x 80 mm spacer.

Run log requirements:

- Include model/tool names only as run metadata, not as preference claims.
- Keep the comparison academic and artifact-based: CADCLAW grades exported
  STEP/BOM/text outputs, not the brand of model or CAD system.
- Do not include credentials, API keys, private procurement records, or native
  CAD files that are not approved for redistribution.

Expected current blocker:

- This run requires a configured native CAD automation environment. CADCLAW can
  grade the resulting STEP once exported, but this repository does not itself
  drive the external CAD application.
