# M3 Light FEA Load Cases

Status: repeatable PyNiteFEA beam-frame checks for the M3-2 reference
configuration.

This is a light structural idealization for early design decisions. It checks
frame-member stiffness, peak member stress/strain envelopes, and named joint
moment utilization. It is not a solid-element analysis of plates, motor mounts,
spacers, fasteners, or bolt holes, and it does not replace physical validation.

The tracked input is:

- `examples/m3_crete/m3_fea_load_cases.yaml`
- `examples/m3_crete/run_fea_load_cases.py`

Run all tracked cases:

```powershell
.venv\Scripts\python.exe examples\m3_crete\run_fea_load_cases.py
```

Run the full-frame 5 kg center-load case only:

```powershell
.venv\Scripts\python.exe examples\m3_crete\run_fea_load_cases.py `
  --case m3_2_center_printhead_5kg
```

Default outputs are written under `examples/m3_crete/build/fea/`:

- `summary.json`: one-row-per-case summary.
- `<case>/report.json`: CADCLAW report with confidence budget.
- `<case>/joint_adequacy.csv`: joint moment utilization table.
- `<case>/member_demands.csv`: member stress, strain, and deflection envelope.
- `<case>/plots/*_stress_distribution.png` and `*_strain_map.png`: beam-member
  demand maps when matplotlib is available.

Axis convention:

- Global `X`: 2 m machine span.
- Global `Y`: vertical, with gravity and printhead load in `-FY`.
- Global `Z`: machine depth.

Current tracked cases:

- `x_gantry_center_printhead_5kg`: isolated 2 m X-gantry center load.
- `m3_2_center_printhead_5kg`: full M3-2 frame center printhead load.
- `m3_2_front_top_lateral_x_100n`: front top-corner lateral X push.
- `m3_2_rear_top_lateral_x_100n`: rear top-corner lateral X push.
- `m3_2_front_top_depth_push_100n`: front top-corner depth-direction push.

Known scope limits:

- The M3-2 frame is an authored beam-centerline idealization, not STEP
  centerline extraction.
- ZPMM spacer/motor-mount stacks are collapsed to shared joint nodes.
- The gate checks extrusion member demands, not local spacer, fastener, plate,
  or wheel contact stresses.
- Kinematic sweeps across all printhead positions remain future work.
