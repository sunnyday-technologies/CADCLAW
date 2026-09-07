# CADCLAW + MARB original-scope closeout

Date: 2026-09-06

The original CADCLAW/MARB update scope is technically complete. The work
expands what CADCLAW can check and strengthens how MARB executes, retains, and
traces benchmark evidence. It does not change the established MARB GAP, POS,
or ORIENT formulas.

## What changed

- CADCLAW now checks declared semantic AP242 PMI classes for dimensions,
  geometric tolerances, and datums using attributed fixtures.
- CADCLAW includes an opt-in OCCT/XCAF import -> export -> reimport
  preservation gate. This is a bounded self-round-trip check, not independent-
  kernel interoperability, native-CAD fidelity, or AP242 conformance.
- CADCLAW gate outcomes and methods are explicit, versioned, and fail closed
  when configured evidence is unknown, incomplete, unreadable, or not checked.
- MARB now separates deterministic cohort planning from explicitly authorized,
  isolated execution. A retained attempt binds source revision and tree,
  runtime contract, immutable image, plan, authorization, inputs, artifacts,
  grading records, and hashes.
- MARB repeat-run policy preserves independent attempts and requires a stated
  sample count before a cohort distribution or public board result is claimed.
  `L2-RESOLVE` and `L4-ECO` are defined but remain unmeasured.
- A fail-closed CADCLAW pre-publication gate checks outgoing Git objects and
  pull-request metadata before public release.

## Verification completed

- The retained MARB R8 provider-free qualification passed all nine fixed
  runtime smoke cases with container networking disabled. This qualifies only
  the exact source/image/runtime binding; it is not model-performance evidence.
- One authorized, local-no-charge `L1-ASSEMBLE` S1 sample completed the full
  boxed path: execution, sealed evidence retention, v0.10 metric grading, and
  separate CADCLAW native-gate grading.
- The S1 run retained a 29,319,093-byte STEP artifact. Its run log, artifact
  inventory, final STEP, editable source, and both grading reports were
  independently hash-read back.
- The single sample measured GAP median 170.0 mm, POS relative median 63.6 mm,
  and ORIENT aligned 16.7%. It failed the inventory, interference, and floating
  native gates. The failure was retained rather than retried or hidden.

## Claim boundary

The S1 result is one private execution smoke (`N=1`). It proves that the
updated boxed execution and trusted grading path operates end to end; it is not
a publishable model ranking, repeat-run distribution, manufacturability claim,
or physical validation. New datasets, repeated local-model campaigns,
autoresearch, external paid providers, graphical PMI, and material/process PMI
remain follow-on work.

## Concise external update

CADCLAW and MARB are now updated for the original scope. CADCLAW adds bounded
semantic-PMI and AP242 preservation checks with explicit, versioned,
fail-closed outcomes. MARB adds governed repeat runs plus a boxed execution
path that binds source, runtime, authorization, artifacts, and grading evidence
by hash. We verified the exact runtime with a nine-case provider-free smoke and
completed one local v0.10 sample end to end; the sample itself did not pass the
assembly gates, and that result was retained rather than hidden. The established
GAP, POS, and ORIENT formulas were not changed. Repeated campaigns and new
datasets remain the next phase.
