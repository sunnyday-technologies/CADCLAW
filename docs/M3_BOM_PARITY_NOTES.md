# M3 BOM Parity Notes

Status: working parity map for the current CADCLAW M3-2 reference assembly.

Boundary:

- CADCLAW owns the model-derived BOM/design inventory emitted from the current
  placed STEP sources, instance roles, and declared generated stock.
- M3-CRETE owns the builder-facing interactive/procurement BOM at
  `../M3-CRETE/bom/data.json`.
- CADCLAW should compare those two views and report evidence-backed deltas. It
  should not silently overwrite the M3 interactive BOM.
- When a user changes member choices, CADCLAW can show the model impact and
  parity drift so M3 can decide whether the public BOM should become lighter,
  heavier, more accurate, or more conservative.

The current CADCLAW reference assembly contains only the placed frame and
gantry datum assets. It does not yet model belts, motors, wheels, fasteners,
or printhead/tooling. For that reason, the current BOM parity rule file
intentionally checks only the placed STEP signatures:

- `cbeam_4080_1000`: 14 design pieces, checked against BOM id `67` with one
  procurement spare. Lower Y rails and the top center spreader are no longer
  counted as C-Beam.
- `vslot_2080_1000`: 2 lower Y-direction static frame rails, checked against
  new/updated BOM id `86`.
- `vslot_2040_1000`: 1 top center spreader extrusion, checked against
  new/updated BOM id `87`.
- `cbeam_gantry_plate_xlarge`: 2 X-axis plates, checked against BOM id `84`.
- `vslot_gantry_plate_20_80`: 6 small 3mm plates, checked against BOM id `69`:
  4 Y-to-Z/Z-post carriage plates plus 2 top-center spreader bracket/spacer
  plates.
- `zpmm_motor_mount_spacer`: 4 motor-mount/spacer plates, checked against BOM
  id `75`.
- `flat_frame_spacer_6mm`: 4 simple 6 x 40 x 80mm lower frame spacers, checked
  against BOM id `79`.

Run:

```powershell
.venv\Scripts\python.exe -m cadclaw_cli.main bom-audit `
  --rules examples\m3_crete\m3_bom_audit.yaml `
  --step examples\m3_crete\build\sequence\final\final_sequence_assembly.step `
  --bom "D:\SunnydayTech\M3-CRETE\bom\data.json" `
  --report-format json `
  -o examples\m3_crete\build\m3_bom_parity_report.json
```

Current result: expected to `FAIL` until the M3 interactive BOM is either
updated to match the newer field guidance for lower Y rails, the top center
spreader, small plate quantities, and the split between ZPMM motor-mount
spacers and lower flat spacers, or the CADCLAW reference spec is revised to
match a deliberately different M3 BOM choice.

Known gaps from the current parity report:

- BOM id `67` must drop from 17 design C-Beam pieces to 14 design C-Beam pieces
  plus one spare.
- BOM id `69` must describe six smaller `V-Slot 20-80` gantry plates, not a
  common `125x125` Y/Z plate strategy.
- BOM id `75` should carry the authored `ZPMM.step` motor-mount/spacer at
  6.1 mm printed thickness, with four instances.
- BOM id `79` should carry the simple 6 x 40 x 80mm lower flat spacer, with
  four instances, and should not describe a motor mount.
- New/updated BOM ids `86` and `87` should carry the 2080 lower Y rails and
  2040 top center spreader, respectively.

Passing this narrow parity check will require either updating the M3-owned
interactive BOM to match the current authored CAD placement or revising the
reference assembly if the BOM is intentionally ahead of the CADCLAW spec. Full
release parity still requires adding the remaining not-built-yet subsystems to
the assembly or explicitly scoping them out of the benchmark fixture.
