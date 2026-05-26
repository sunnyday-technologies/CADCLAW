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

To inspect your work, a viewer is available: `pip install cadclaw`, then
`from cadclaw.render import render_step_to_png` and render a temp export from any
preset — `render_step_to_png("partial.step", "iso.png", view="iso")` (presets:
`front`, `top`, `side`, `iso`, `iso_below`). It is only a viewer — do **not** fetch
any reference spec.

The kit parts are the `.step` files in `kit/` (filenames match the kit table above;
all seven NEMA 23 motors are one model — `M3_NEMA23_motor.step` — placed seven times,
oriented by you).

In the run log, set `track: cadquery_native_driver` and
`host_application: CadQuery (Python)`.
