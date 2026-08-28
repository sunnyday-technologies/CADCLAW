# PMI -> Round-trip -> MARB -> Benchmark Completion Ledger

Last updated: 2026-08-28

Owner: Sunnyday Technologies

Overall status: **IN PROGRESS**

Status values: `NOT STARTED`, `IN PROGRESS`, `READY FOR REVIEW`, `MERGED`,
`COMPLETE`, `BLOCKED`, and `DEFERRED`.

This file is the durable source of truth for the work requested in the CADCLAW
PMI/round-trip prompt and the companion MARB prompt. Update it in the same
session as every validated commit, pull request, merge, benchmark run, and Marc
closeout. An open pull request or a started validation is not completion.

## Decision lock

- Use official, authored NIST AP242 fixtures for semantic-PMI and round-trip
  regression coverage.
- The current semantic-PMI gate covers dimensions, geometric tolerances, and
  datums.
- Material assignments and process/general notes are deferred until a
  redistributable positive fixture and a verified association-level extraction
  method are available.
- Graphical PMI, standards compliance, and conformance claims remain out of
  scope.
- The round trip is an actual OCCT import -> AP242 export -> reimport.
- Translator independence is reported only for a declared non-OCCT source;
  otherwise it is unknown or not applicable.
- Authoring-reference comparison is only a STEP-to-STEP proxy comparison; it
  is not native-CAD inspection. It is not applicable unless an explicitly
  identified authoring-reference STEP proxy is supplied.
- Interface gaps are checked only for declared, unambiguous interface pairs.
- CADCLAW semantic-PMI and round-trip work ship through separate pull requests.
- MARB work remains in its separate repository and task. Existing benchmark
  runs are never silently re-scored or overwritten.

## Delivery status

| ID | Deliverable | Status | Dependency | Branch/task | PR | Merge commit |
|---|---|---|---|---|---|---|
| C1 | CADCLAW semantic AP242 PMI gate | COMPLETE | None | `feat/pmi-present-gate` (deleted after merge) | [#9](https://github.com/sunnyday-technologies/CADCLAW/pull/9) | `db41bea9495be8200490fa38bbd145c91bad716c` |
| C2 | CADCLAW AP242 STEP round-trip gate | COMPLETE | C1 merged | `codex/roundtrip-step-gate` (deleted after merge) | [#11](https://github.com/sunnyday-technologies/CADCLAW/pull/11) | `14c7864abea2568cb0c0a462619fe6e1f1183700` |
| M1 | MARB repeat-run reporting and acceptable-solution policy | COMPLETE | Independent | `codex/marb-repeat-run-policy` | [MARB #5](https://github.com/sunnyday-technologies/MARB/pull/5) | `5bb4ae6fd2c449c1fb107025129e18845fd8c96c` |
| M2 | MARB `L2-RESOLVE` task contract | COMPLETE | M1 method/version decisions | `codex/marb-l2-resolve-v0.11` | [MARB #6](https://github.com/sunnyday-technologies/MARB/pull/6) | `24da2a6641a5681313d4b112b3e98fdeca5262c2` |
| M3 | MARB `L4-ECO` task and authenticated evidence gates | COMPLETE | M1 and C2 | `codex/marb-l4-eco-v0.12` | [MARB #7](https://github.com/sunnyday-technologies/MARB/pull/7) | `072dfab66999c968facb8a640d39739a80353c7b` |
| Q1 | Reproducible NIST AP242 qualification runner and evidence-integrity guards | COMPLETE | C1 and C2 | Runner/fix branches deleted after merge | [#13](https://github.com/sunnyday-technologies/CADCLAW/pull/13), [#14](https://github.com/sunnyday-technologies/CADCLAW/pull/14), [#15](https://github.com/sunnyday-technologies/CADCLAW/pull/15) | `2305d841c2ecf73d8ceb8e3a398766d2000e0912`; `94b0fd0072a9e6bf0a1ac54df5f3c9f0266b59c2`; `4579c5e925dfcc13236973aca295f42128704823` |
| Q2 | Fresh NIST FTC11/STC06 software-qualification cohort | READY FOR REVIEW | Q1 merged | `codex/nist-ap242-qualification-evidence-20260828` | TBD | TBD |
| H2 | Non-destructive, provenance-complete, isolated MARB cohort runner | IN PROGRESS | M1, M2, and M3 merged | `codex/marb-cohort-runner-plan`; task `01a046b7-1430-7792-b891-709e5b60c7ff` | TBD | TBD |
| B1 | Fresh MARB model benchmark cohort | BLOCKED | H2; immutable gated-key revisions; provider/model/budget approval | N/A | N/A | N/A |
| R1 | Evidence-backed update to Marc | BLOCKED | B1 complete | N/A | N/A | N/A |
| D1 | Material/process semantic-PMI expansion | DEFERRED | Positive fixture and verified extraction method | TBD | TBD | TBD |
| H1 | Remove stale Open3DCP re-pushed branches | COMPLETE | None | Deleted `precedent-crosswalk` and `whitepaper-v1-1` | Already merged as Open3DCP #10/#11 | N/A |

## Acceptance evidence

### C1 - Semantic AP242 PMI

- [x] Dimensions, geometric tolerances, and datums are reported separately.
- [x] Missing declarations report not applicable instead of passing.
- [x] Import, transfer, and extraction failures are errors rather than PMI
  absence.
- [x] Official fixture provenance, attribution, and SHA-256 values are recorded.
- [x] Gate-method version is recorded without changing the existing report or
  rules schema contracts.
- [x] Focused and full local suites pass: 397 passed, 6 skipped.
- [x] CodeQL and answer-key guards pass on PR #9.
- [x] GitHub unit tests pass in the Linux headless runner.
- [x] Fresh-clone fixture generation, full suite, and site build pass.
- [x] PR disclosure and approved deferral receive final readback.
- [x] PR #9 is merged and the merge commit is verified on `main`.

Evidence:

- Semantic-PMI implementation head before tracking/CI follow-ups:
  `ccc0f11d95802f093e46b36a0bb4b86fbe0222ca`
- Final PR head: `dc386bc492192cf3bd1dfd3a1ad3f48344e97821`
- Merge commit on `main`: `db41bea9495be8200490fa38bbd145c91bad716c`
- GitHub Linux unit run:
  [33145078839](https://github.com/sunnyday-technologies/CADCLAW/actions/runs/33145078839),
  397 tests passed under Xvfb; all CodeQL and answer-key checks also passed.
- Fresh clone of `codex/update-completion-ledger`: fixture generation passed;
  397 tests passed with 16 environment-dependent skips; site allowlist build
  passed with 16 files, 112 checked links, and 16/16 source-output hashes.
- Ledger evidence correction:
  [#10](https://github.com/sunnyday-technologies/CADCLAW/pull/10)
- NIST STC06 fixture SHA-256:
  `71777C28DA76DA0E8A667E4CBE792D5F72C09B5C56440C9744D3D50CA96ECC8D`
- NIST FTC11 fixture SHA-256:
  `20A92EDF514AE0989D556F9C7B9F065AED741CFBB361B7FE4CB7938A1EB5C232`
- Resolved CI issue: the GitHub Linux runner initially reached VTK rendering
  without a display and exited 139. The full, unchanged suite now runs under
  Xvfb; no rendering tests are skipped.

### C2 - AP242 STEP round trip

- [x] Actual OCCT import -> AP242 export -> reimport executes.
- [x] Exact CADCLAW-deduplicated renderable-shape count and
  assembly/per-part bounding comparisons execute.
- [x] Every declared interface pair reports its gap comparison or a structured
  unresolved-selector error.
- [x] Semantic PMI classes present in the source are compared before/after as
  supported class counts.
- [x] A real intentionally dropped-PMI AP242 translation is detected.
- [x] Independence is not claimed for unknown or OCCT source translators.
- [x] Authoring-reference STEP-proxy comparison reports not applicable without
  an explicit proxy; no native-CAD correctness is implied.
- [x] Focused, full-suite, JSON-output, and site validation pass.
- [x] OCCT reader/writer global state is restored and malformed source/proxy
  inputs cannot pollute focused JSON stdout or expose local paths.
- [x] Focused round-trip reports omit the caller's absolute rules path.
- [x] One-to-one matching errors before quadratic allocation above the fixed
  256-renderable-shape method limit.
- [x] OCCT `IFSelect_RetError` recovery is bounded to a non-empty,
  non-symlink AP242 artifact that XCAF can reimport; the raw status and
  provisional disposition remain visible and downstream scoped comparisons
  remain decisive.
- [x] The round-trip module passes on both Windows/OCP 7.8 and Linux/OCP 7.9.
- [x] Clean-clone validation passes from the committed branch.
- [x] Separate PR is green, reviewed, merged, and read back from `main`.

Evidence slots:

- Gate-method version: `0.12.0`
- OCP module versions: `7.8.1.1` in Windows validation and `7.9.3.1` in the
  isolated Linux compatibility validation. The Linux environment used
  CadQuery `2.8.0` and the `cadquery-ocp` package `7.9.3.1.1`, matching the
  dependency line selected by GitHub CI.
- Positive evidence:
  `TestNistRoundtripIntegration.test_real_ap242_export_reimport_preserves_geometry_and_pmi`
  preserves the NIST FTC11 fixture's renderable-shape geometry evidence and
  supported semantic-PMI class counts `6 / 4 / 4`. Source SHA-256 is recorded
  above under C1; each generated derivative report emits source/output hashes.
- Negative evidence:
  `TestNistRoundtripIntegration.test_real_dimtol_disabled_export_is_detected_as_pmi_loss`
  performs a real AP242 export with OCCT `DimTol` writing disabled. Geometry
  evidence is preserved while all three supported PMI class-count comparisons
  fail. The derivative is intentionally temporary and is not a distributed
  fixture or compliance artifact.
- Frozen-tree round-trip module: 25 tests plus 7 subtests passed on both
  Windows/OCP 7.8.1.1 and Linux/OCP 7.9.3.1. The real NIST FTC11 positive
  fixture remains unskipped and preserves the scoped renderable-shape geometry
  evidence plus supported semantic-PMI counts `6 / 4 / 4`.
- Local focused adjacent suite: 122 passed.
- Local full suite: 432 passed, 6 expected skips.
- Site allowlist build: 16 files, 112 links, 16/16 source-output hashes.
- Clean clone of commit `67dce397d917d98c77f8f64a4e1d5cb020ea6978`:
  fixture generation passed; full suite passed 427 tests with 16
  environment-dependent skips; site build passed with 16 files, 112 links,
  and 16/16 source-output hashes.
- A formal security diff scan of the pre-hardening snapshot reported three
  low-severity findings: absolute rules-path disclosure, secondary OCCT reader
  diagnostics, and unbounded part-matching complexity. All three are fixed and
  covered by regressions; frozen-tree review reports no remaining confirmed
  finding. Historical scan snapshot digest:
  `sha256:9e970ae7b753ca8dceccc7a9089d17ef297dd7e4347ad4a9a47a5c561db08275`.
- Initial PR #11 Linux unit run
  [33148644666](https://github.com/sunnyday-technologies/CADCLAW/actions/runs/33148644666)
  exposed an OCP 7.9 portability issue: the writer created a reimportable
  AP242 derivative but returned `IFSelect_RetError`. The bounded compatibility
  fix never reclassifies that result as `RetDone`; it records
  `ret_error_provisionally_validated` only after artifact/schema/XCAF checks,
  leaves writer-reference and graphical-PMI integrity unchecked, and still
  requires the geometry and source-present semantic-PMI comparisons to pass.
- Corrected PR head: `60225ce272046311889e2c3288c0d9c0b937213f`.
- Corrected-head GitHub Linux unit run:
  [33150606045](https://github.com/sunnyday-technologies/CADCLAW/actions/runs/33150606045),
  432 tests passed with 6 expected skips. Both CodeQL analyses and both
  answer-key guards also passed on the exact head.
- PR #11 merge commit, verified on `main`:
  `14c7864abea2568cb0c0a462619fe6e1f1183700`.

### M1/M2/M3 - MARB task contracts and evidence gates

- [x] M1 publishes repeat-run distributions and preserves legacy single-run
  provenance.
- [x] New frontier cells require at least three independent runs under the accepted
  policy.
- [x] M2 publishes the task-specific `L2-RESOLVE` method and pending-evidence
  contract without relabeling an unmeasured task as a result.
- [x] M3 publishes the `L4-ECO` method, public invariant gate, and authenticated
  pending-evidence contract without publishing an unmeasured board row.
- [x] Each task is independently reviewable and merged through its own PR, with
  Tasks 3 and 4 paired only as allowed by the MARB prompt.
- [x] Every merge bumps or records the applicable MARB method/spec version and
  preserves old cells' original version tags.
- [x] MARB PR links, merge commits, and clean-run evidence are recorded here.
- [x] `L2-RESOLVE` and `L4-ECO` remain explicitly unmeasured, with zero board
  rows, until immutable gated-key revisions and qualifying repeat runs exist.

Evidence slots:

- M1: [MARB #5](https://github.com/sunnyday-technologies/MARB/pull/5),
  head `0509ab68be430d0c2bc0f2944341fa97573c9123`, merge
  `5bb4ae6fd2c449c1fb107025129e18845fd8c96c`. Clean-clone focused validation
  passed 30/30 tests and the full local suite passed 41/41; board policy,
  answer-key guards, and both CodeQL analyses passed.
- M2: [MARB #6](https://github.com/sunnyday-technologies/MARB/pull/6),
  head `eb618bc1e0644742930afcce7f1e0e5c72407697`, merge
  `24da2a6641a5681313d4b112b3e98fdeca5262c2`. Board policy, answer-key guards,
  and both CodeQL analyses passed on the exact head.
- M3: [MARB #7](https://github.com/sunnyday-technologies/MARB/pull/7),
  head `b620061b52224dde064a8834daa209eccd346b75`, merge
  `072dfab66999c968facb8a640d39739a80353c7b`. The dependency-free suite passed
  (91 tests, with one expected Windows newline-filename skip); publication
  validation, both answer-key guards, and both CodeQL analyses passed. The
  immutable gated distribution remains pending, so the task has zero runs and
  zero board rows.

### Q1/Q2 - NIST AP242 software qualification

- [x] The runner requires a clean checkout whose `HEAD` equals freshly fetched
  `origin/main` and executes CADCLAW from an exact Git archive.
- [x] The runner, rules, fixture blobs, target tree, schemas, and gate method
  are fail-closed and hash-bound.
- [x] Cohort paths are new-only; reparse points are rejected and final
  publication is atomic and non-overwriting.
- [x] Generated STEP derivatives remain local and ignored; tracked reports
  retain their hashes, sizes, schemas, and raw writer statuses.
- [x] FTC11 preserves semantic-PMI counts `6 / 4 / 4` and STC06 preserves
  `17 / 25 / 51` for dimensions / geometric tolerances / datums.
- [x] Both AP242 export/reimport runs pass with `IFSelect_RetDone` / `ret_done`.
- [x] The manifest identifies this as software qualification, not a MARB/model
  benchmark, with zero model calls and no model/provider API cost.
- [x] Checked and unchecked scope, NIST attribution, the FTC11 e2 archive-name
  versus embedded e1 declaration, and no-endorsement language are recorded.

Evidence:

- Runner: [#13](https://github.com/sunnyday-technologies/CADCLAW/pull/13), head
  `92dae6e9e08e8801188e4d260cb374128be1d77a`, merge
  `2305d841c2ecf73d8ceb8e3a398766d2000e0912`.
- Runner exact-head GitHub checks: 447 tests ran with 13 environment-dependent
  skips; both CodeQL analyses and both answer-key guards passed. The exact-head
  local Windows clean clone ran the same 447 tests with 6 expected skips.
- Cross-platform tracked-byte integrity: [#14](https://github.com/sunnyday-technologies/CADCLAW/pull/14),
  head `b11a91f0af4fe43f0ea9abaa3cf2efa93a3a16ab`, merge
  `94b0fd0072a9e6bf0a1ac54df5f3c9f0266b59c2`. Exact-head unit, CodeQL, and
  answer-key checks passed; the local full suite ran 449 tests with 6 expected
  skips.
- Case-sensitive lowercase cohort-ID guard: [#15](https://github.com/sunnyday-technologies/CADCLAW/pull/15),
  head `e56fc0c5da46e931f4f4737565fa40ce96d56118`, merge
  `4579c5e925dfcc13236973aca295f42128704823`. Exact-head unit, CodeQL, and
  answer-key checks passed; the local qualification module passed 17 tests.
- Two pre-publication local runs exposed the byte-normalization and ID-case
  gaps. Their evidence was never committed or published and remains only in
  ignored local backups.
- Cohort ID: `nist-ap242-20260828t101004z-cadclaw-4579c5e925df`.
- Exact target commit/tree: `4579c5e925dfcc13236973aca295f42128704823` /
  `581b78c92e049adfb00ad181e59a94d29ca3ef2a`.
- Exact runner SHA-256:
  `1c031f7eb4318be9a38261b2545c765a60af1f634e2cbd01a5035d0d68ddb8c5`.
- Manifest:
  `evidence/qualifications/nist-ap242/nist-ap242-20260828t101004z-cadclaw-4579c5e925df/manifest.json`.
- FTC11 derivative SHA-256:
  `b21d95857ffc57fb87eecb924f0b91c49cf06fa71aff3da416227ab34196d885`.
- STC06 derivative SHA-256:
  `161a3ec55b152f367f4d77991fcb7f28aaf4b2e107cb736c4c1ccd24a2eb13f6`.
- Evidence-only PR / merge: TBD.

### B1 - Fresh benchmark cohort

- [ ] Dataset/task contract is versioned and frozen before runs begin.
- [ ] Merge the separate bounded official NIST AP242 software-qualification
  cohort before model runs.
- [ ] Add a Berkeley robot hand/forearm assembly only if authored assembly STEP,
  license, and provenance are verified through a dataset-intake PR.
- [ ] A new run/cohort ID is used; no historical result is overwritten or
  silently re-scored.
- [ ] CADCLAW commit, MARB commit, rules hash, fixture/kit hash, and gate-method
  version are recorded.
- [ ] Exact model/provider/version, timestamps, seeds, runtime, tokens, and cost
  are recorded.
- [ ] Submitted STEP, derivative STEP, reports, and manifest have hashes.
- [ ] Checked, not checked, assumptions, errors, and not-applicable outcomes are
  preserved in the scorecard.

Evidence slots:

- Cohort/run ID: TBD
- Code and configuration provenance: TBD
- Artifact manifest: TBD
- Final scorecard: TBD

Current blockers:

- The legacy MARB batch harness is destructive on reused run folders and runs
  model-produced Python on the host with inherited environment access. The
  current MARB branch is a guarded deterministic planner only; a separate H2b
  isolated executor remains required before any fresh model execution.
- `L2-RESOLVE` and `L4-ECO` require immutable gated-key revisions plus a trusted
  grading/readback path before their outputs can be called gradeable.
- Provider, exact model/version, data-sharing choice, run limits, and budget
  require explicit approval before model calls.

### R1 - Marc closeout

- [ ] Report uses merged-code and fresh-benchmark evidence only.
- [ ] Authoring, translation, and benchmark findings are separated.
- [ ] Limitations and deferred scope are explicit.
- [ ] No PMI/interoperability compliance or manufacturability claim is made.
- [ ] Report artifact, source manifest, delivery channel, and delivery date are
  recorded.

Evidence slots:

- Report path/link: TBD
- Source manifest: TBD
- Delivery channel/date: TBD

## Approved deferral

Material assignments and process/general notes are deferred from the current
semantic-PMI gate. Resume D1 only through a separate PR and gate-method-version
update after both a redistributable positive AP242 fixture and a verified
association-level extraction method exist.

Graphical PMI remains explicitly out of scope and is never implied by semantic
PMI success.

## Completion rule

Mark the overall plan `COMPLETE` only when C1, C2, M1, M2, M3, Q1, Q2, H2, B1,
and R1 are complete and their evidence slots are populated. D1 may remain
`DEFERRED`.
