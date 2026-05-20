# M3 BOM Parity Notes

Status: working parity map for the current CADCLAW M3-2 reference assembly.

The current CADCLAW reference assembly contains only the placed frame and
gantry datum assets. It does not yet model belts, motors, wheels, fasteners,
printhead/tooling, or the internal 2040 reinforcement inserts. For that reason,
the current BOM parity rule file intentionally checks only the placed STEP
signatures:

- `cbeam_4080_1000`: 17 design pieces, checked against BOM id `67` with one
  procurement spare.
- `cbeam_gantry_plate_xlarge`: 2 X-axis plates, checked against BOM id `84`.
- `vslot_gantry_plate_20_80`: 4 Y-to-Z/Z-post carriage plates, checked against
  BOM id `69`.
- `zpmm_motor_mount_spacer`: 8 motor-mount/spacer plates, checked against BOM
  id `79`.

Run:

```powershell
.venv\Scripts\python.exe -m cadclaw_cli.main bom-audit `
  --rules examples\m3_crete\m3_bom_audit.yaml `
  --step examples\m3_crete\build\sequence\final\final_sequence_assembly.step `
  --bom "D:\SunnydayTech\M3-CRETE\bom\data.json" `
  --report-format json `
  -o examples\m3_crete\build\m3_bom_parity_report.json
```

Current result: `FAIL`, as expected, because the CADCLAW reference now reflects
newer field guidance than the BOM text for two items.

Known gaps from the current parity report:

- BOM id `69` still describes a six-piece common `125x125` Y/Z plate strategy.
  The current CADCLAW reference uses four smaller `V-Slot 20-80` plates for the
  Y-to-Z/Z-post carriage interfaces.
- BOM id `79` still describes a `4mm` bottom spacer/idler mount. The current
  CADCLAW reference uses the authored `ZPMM.step` motor-mount/spacer at 6.1 mm
  printed thickness, with eight instances.

Passing this narrow parity check will require either updating the public BOM to
match the current authored CAD placement or revising the reference assembly if
the BOM is intentionally ahead of the CADCLAW spec. Full release parity still
requires adding the remaining not-built-yet subsystems to the assembly or
explicitly scoping them out of the benchmark fixture.
