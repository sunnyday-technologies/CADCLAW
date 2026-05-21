# M3 Local Status

Last updated: 2026-05-21

Scope: local-only CADCLAW work in `D:\SunnydayTech\CADCLAW`. Do not assume
GitHub publication or remote sync unless explicitly requested.

GitHub remote note: the online repository has been reinstated with history
removed to eliminate past PII from public git history. Treat that remote as a
new sanitized root. Do not push this local repository's old history directly;
move current work by applying selected patches or file copies onto a fresh
clone of the sanitized remote.

## Current Save Point

- Branch: `codex/check-efficiency-review`
- Recent local commits:
  - `1fdb1d3 Improve M3 GIF visualization palette`
  - `aef3b42 Keep M3 explode GIF under size gate`
  - `feeb9ed Record local M3 verification status`
- Working policy: authored STEP placement first; do not generate contextual
  plates, brackets, mounts, hole patterns, or idler holders, except the
  explicitly user-approved M3 ZPMM spacer correction noted below.

## Latest Verification

- Full test suite: `372 passed`, `26 warnings` from CadQuery future-save
  notices.
- M3 render sequence:
  - All six declared steps passed validation.
  - `sequence_blocked_at: null`
  - Expected overall status: `warn` because explicit `not_built_yet` items
    remain.
  - Geometry cache summary: `36` requests, `30` hits, `6` misses, `225`
    loaded instances, `6` cached instance sets.
- ZPMM spacer correction:
  - `examples\m3_crete\generated\ZPMM_6p1_motor_mount_spacer_6mm_holes.step`
    is a one-off derivative of the user-confirmed authored `ZPMM.step`.
  - The outline and large motor-spindle opening are preserved.
  - The four existing motor holes are 6mm through-holes.
  - Six C-Beam end-alignment holes are added from the asymmetric 4080
    screw-port pattern; the open-channel non-holes are not used.
- Single check-round:
  - Overall status: `warn`
  - Findings: eight `assemble.not_built_yet` items only.
- BOM parity against `D:\SunnydayTech\M3-CRETE\bom\data.json`:
  - Overall status: `fail`
  - Reason: M3 interactive BOM has not yet been updated to match the current
    CADCLAW reference assembly for 4080 count, XLarge plate count, 20-80 plate
    description, ZPMM spacer quantity/thickness, lower flat spacer definition,
    and 2080/2040 rail entries.
- FEA load cases:
  - All existing load cases passed.
  - This is decision-support only, not physical validation or certification.

## Current Generated Local Artifacts

- Final sequence STEP:
  `examples\m3_crete\build\sequence\final\final_sequence_assembly.step`
- Assembly progress GIF:
  `examples\m3_crete\build\sequence\final\assembly_progress_360.gif`
- Slow exploded rotation GIF:
  `examples\m3_crete\build\sequence\final\final_explode_slow_rotate.gif`
- Sequence report:
  `examples\m3_crete\build\sequence\sequence_report.json`
- Sequence manifest:
  `examples\m3_crete\build\sequence\assembly_sequence_manifest.json`
- Model-derived BOM CSV:
  `examples\m3_crete\build\m3_reference_round1_bom.csv`
- BOM parity report:
  `examples\m3_crete\build\m3_bom_parity_report.json`
- Check-round report:
  `examples\m3_crete\build\m3_check_round_report.json`
- FEA summary:
  `examples\m3_crete\build\fea\summary.json`
- One-off derived ZPMM spacer STEP:
  `examples\m3_crete\generated\ZPMM_6p1_motor_mount_spacer_6mm_holes.step`

Generated files under `examples\m3_crete\build\` are local build artifacts and
are not intended to be committed unless the project policy changes.

## Visualization Decisions

- STEP/AP metadata should remain full fidelity. AP242 is preferred when it is
  available and compatible, with AP214 supported as a geometry-compatible
  fallback.
- Shareable M3 GIFs use CADCLAW semantic colors instead of STEP-stored colors.
  This avoids AP242/source-asset color drift in article and review artifacts.
- GIFs use a fixed 64-color CADCLAW palette to keep file size low while
  preserving functional black/green/metal color separation.
- The three X-direction 2040 splice inserts are explicitly revealed downward in
  GIF output so they remain visible when otherwise nested inside black C-Beams.
  The top-center 2040 spreader is not moved because it is already visible.

## Remaining Work That Needs Mechanical or Product Input

- Freeze connector frames for rail endpoints, plates, wheel contact lines,
  and static frame joints from source CAD/rendered inspection.
- Add authored STEP placement for belt paths, pulleys, idlers, motors, motor
  plates, and Z drive assemblies.
- Freeze ZPMM motor-mount/spacer handedness and final connector binding in the
  assembled frame views.
- Select and place the printhead/tooling payload interface on the X carriage.
- Update or intentionally diverge the M3 interactive BOM to resolve the current
  parity report.
- Extend FEA from fixed load cases to frame-member option sweeps and broader
  lateral rigidity comparisons.
