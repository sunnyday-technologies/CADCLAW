<!-- track: fusion_native_driver -->
## How to drive — Autodesk Fusion (via the Fusion MCP)

Build in a live Fusion via the Fusion MCP tools available in this session.

1. Confirm the MCP: `fusion_mcp_read` `queryType:"projects"` lists
   `M3-AI-Benchmark-Kit`; `queryType:"document"`, `operation:"search"`
   (`project:"M3-AI-Benchmark-Kit"`) lists the kit DataFiles. **The kit parts are
   the uploaded DataFiles in that project** (names match the kit table above).
2. Create a new Fusion design in that project for the assembly.
3. Insert kit parts as occurrences and position/orient them via `fusion_mcp_execute`
   `featureType:"script"` (Fusion Python API: `Occurrences.addByInsert`,
   `transformBy` / `Matrix3D`). Look up the exact API via `fusion_mcp_read`
   `queryType:"apiDocumentation"`.
4. Sanity-check as you go with `fusion_mcp_read` `queryType:"screenshot"`.
5. Export the design to a single STEP via `ExportManager` / `STEPExportOptions` to
   `fusion_native_export.step` in your run folder.

Tooling quirks (from prior runs — operational, not solution hints):
- A freshly-inserted **referenced occurrence's `boundingBox` returns zero in the
  same script call** (lazy geometry load). Re-read it on a *later* MCP call before
  using it to position anything.
- The fuzzy document search can miss a kit file; do a **recursive walk of the
  project's data folders** to enumerate all kit DataFiles.

In the run log, set `track: fusion_native_driver` and
`host_application: Autodesk Fusion (via Fusion MCP)`.
