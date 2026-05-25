<!-- track: cadquery_native_driver -->
## How to drive — CadQuery (Python)

Build the assembly in CadQuery from the STEP files in `kit/`.

1. `pip install cadquery`; confirm `import cadquery as cq` works. (Optionally
   `pip install cadclaw` to self-inspect inventory — but do **not** fetch any
   reference spec.)
2. Import each kit part with `cq.importers.importStep("kit/<file>")`. Probe each
   part's bounding box / center of mass to learn its local axes and orientation
   before placing.
3. Assemble by computing per-instance transforms — e.g.
   `cq.Assembly().add(part, loc=cq.Location(cq.Vector(x,y,z), cq.Vector(ax), deg))`
   or `.translate(...).rotate(...)`. Cut-to-length 40×80 / 20×80 / 20×40 stock and
   belt segments may be generated; place everything else from `kit/`.
4. Export the assembly to a single STEP — `cadquery_native_export.step` in your run
   folder — e.g. `cq.exporters.export(asm.toCompound(), "cadquery_native_export.step")`.

The kit parts are the `.step` files in `kit/` (filenames match the kit table above;
the four Z / two Y / one X motors are `M3_NEMA23_motor_src*.step`).

In the run log, set `track: cadquery_native_driver` and
`host_application: CadQuery (Python)`.
