<!-- track: fusion_native_driver -->
## How to drive — Autodesk Fusion (via the Fusion MCP)

Build in a live Fusion via the Fusion MCP tools available in this session.

1. Create a new Fusion design for the assembly.
2. Import each kit part from the local **`kit/`** folder of this kit, via
   `fusion_mcp_execute` `featureType:"script"` (Fusion Python API:
   `app.importManager.createSTEPImportOptions(path)` then `importToTarget`). The kit
   parts are the STEP files in `kit/` (names match the kit table above) — they are
   the **only** part source.
3. Position/orient each occurrence with `transformBy` / `Matrix3D`. Look up the exact
   API via `fusion_mcp_read` `queryType:"apiDocumentation"`.
4. To inspect your work, capture the live viewport with `fusion_mcp_read`
   `queryType:"screenshot"` from any camera orientation — front, top, right, or
   isometric (drive the viewport via the Fusion API / named views). The target
   reference images are in this kit folder (see the brief).
5. Export the design to a single STEP via `ExportManager` / `STEPExportOptions` to
   `fusion_native_export.step` in your run folder.

Tooling quirks (from prior runs — operational, not solution hints):
- A freshly-imported body's `boundingBox` can read zero in the **same** script call
  (lazy geometry load). Re-read it on a *later* MCP call before using it to position
  anything.
- Import **only from the `kit/` folder**. Do **not** search Fusion Team/cloud
  projects for parts — a same-named file in another project (e.g. **M3-CRETE, which
  holds the reference design / answer key**) would invalidate the run.

In the run log, set `track: fusion_native_driver` and
`host_application: Autodesk Fusion (via Fusion MCP)`.
