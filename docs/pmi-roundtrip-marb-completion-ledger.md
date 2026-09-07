# PMI -> Round-trip -> MARB -> Benchmark Completion Ledger

Last updated: 2026-09-06

Owner: Sunnyday Technologies

Overall status: **COMPLETE — original implementation merged; boxed S1 executed
and graded; repeated benchmark cohorts remain follow-on work**

Status values: `NOT STARTED`, `IN PROGRESS`, `READY FOR REVIEW`, `MERGED`,
`COMPLETE`, `BLOCKED`, and `DEFERRED`.

This file is the durable source of truth for the work requested in the CADCLAW
PMI/round-trip prompt and the companion MARB prompt. Update it in the same
session as every validated commit, pull request, merge, benchmark run, and
external closeout. An open pull request or a started validation is not
completion.

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

| ID | Deliverable | Status | Dependency | Branch/task | PR | Current verified commit |
|---|---|---|---|---|---|---|
| C1 | CADCLAW semantic AP242 PMI gate | COMPLETE | None | `feat/pmi-present-gate` (deleted after merge) | [#9](https://github.com/sunnyday-technologies/CADCLAW/pull/9) | `3de26c15857299d3aef8a73b05574e7a7299b591` |
| C2 | CADCLAW AP242 STEP round-trip gate | COMPLETE | C1 merged | `codex/roundtrip-step-gate` (deleted after merge) | [#11](https://github.com/sunnyday-technologies/CADCLAW/pull/11) | `64150bfcf719574dd5f98f59f613a5737d145b2e` |
| M1 | MARB repeat-run reporting and acceptable-solution policy | COMPLETE | Independent | `codex/marb-repeat-run-policy` | [MARB #5](https://github.com/sunnyday-technologies/MARB/pull/5) | `5bb4ae6fd2c449c1fb107025129e18845fd8c96c` |
| M2 | MARB `L2-RESOLVE` task contract | COMPLETE | M1 method/version decisions | `codex/marb-l2-resolve-v0.11` | [MARB #6](https://github.com/sunnyday-technologies/MARB/pull/6) | `24da2a6641a5681313d4b112b3e98fdeca5262c2` |
| M3 | MARB `L4-ECO` task and authenticated evidence gates | COMPLETE | M1 and C2 | `codex/marb-l4-eco-v0.12` | [MARB #7](https://github.com/sunnyday-technologies/MARB/pull/7) | `072dfab66999c968facb8a640d39739a80353c7b` |
| Q1 | Reproducible NIST AP242 qualification runner and evidence-integrity guards | COMPLETE | C1 and C2 | Runner/fix branches deleted after merge | [#13](https://github.com/sunnyday-technologies/CADCLAW/pull/13), [#14](https://github.com/sunnyday-technologies/CADCLAW/pull/14), [#15](https://github.com/sunnyday-technologies/CADCLAW/pull/15) | `735b173182883dc90e7449701c1302fd21b876f4`; `b1ede598a83ec952aa57add0732ef93809b98be9`; `93022d729ee9bb4eb7cd2d8aa09b8fa12fddfa20` |
| Q2 | Fresh NIST FTC11/STC06 software-qualification cohort and evidence closeout | COMPLETE | Q1 merged | Qualification/evidence branches deleted after merge | [#16](https://github.com/sunnyday-technologies/CADCLAW/pull/16), [#17](https://github.com/sunnyday-technologies/CADCLAW/pull/17) | `9424a2629094b5a7e579180e1ed6b1c21d349d87`; `2cc7ed03c1739c457386bbb4e17286d3daf6daf3` |
| H2a | Deterministic, non-writing MARB cohort planner | COMPLETE | M1, M2, and M3 merged | `codex/marb-cohort-runner-plan` | [MARB #8](https://github.com/sunnyday-technologies/MARB/pull/8) | `d4f1dd836b94159bc72ed0b72be0e7c324239329` |
| H2b | Non-destructive, provenance-complete, isolated MARB cohort executor | COMPLETE | H2a merged | `codex/marb-cohort-runner-executor` (deleted after merge); task `01a046b7-1430-7792-b891-709e5b60c7ff` | [MARB #9](https://github.com/sunnyday-technologies/MARB/pull/9) | `56177ae5815c99dce6a90ad509902cd196d840fd` |
| S1 | One boxed local-no-charge `L1-ASSEMBLE` smoke run | COMPLETE | H2b complete; exact OCI image/provider-free runtime qualified; one authorized retained attempt executed and graded | Private retained evidence | N/A | N/A |
| B1 | Fresh MARB model benchmark cohort | BLOCKED | H2b complete; immutable gated-key revisions and trusted grading; provider/model/data-sharing/run-limit authorization; aggregate campaign ledger | N/A | N/A | N/A |
| R1 | Evidence-backed original-scope public closeout | COMPLETE | S1 complete | `docs/cadclaw-marb-original-scope-closeout-2026-09-06.md`; prior recommendation update user-attested; final S1 supplement prepared here | N/A | N/A |
| D1 | Material/process semantic-PMI expansion | DEFERRED | Positive fixture and verified extraction method | TBD | TBD | TBD |
| H1 | Remove stale Open3DCP re-pushed branches | COMPLETE | None | Deleted `precedent-crosswalk` and `whitepaper-v1-1` | Already merged as Open3DCP #10/#11 | N/A |

The CADCLAW repository subsequently received a metadata-only history rewrite.
GitHub's PR records retain the original merge identities, while current
`origin/main` contains tree-identical replacements. The verified mapping is:
`db41bea9495be8200490fa38bbd145c91bad716c` ->
`3de26c15857299d3aef8a73b05574e7a7299b591`;
`14c7864abea2568cb0c0a462619fe6e1f1183700` ->
`64150bfcf719574dd5f98f59f613a5737d145b2e`;
`2305d841c2ecf73d8ceb8e3a398766d2000e0912` ->
`735b173182883dc90e7449701c1302fd21b876f4`;
`94b0fd0072a9e6bf0a1ac54df5f3c9f0266b59c2` ->
`b1ede598a83ec952aa57add0732ef93809b98be9`;
`4579c5e925dfcc13236973aca295f42128704823` ->
`93022d729ee9bb4eb7cd2d8aa09b8fa12fddfa20`;
`cdbb45882fcd19092d4082cf490c27db12878d81` ->
`9424a2629094b5a7e579180e1ed6b1c21d349d87`; and
`251bfb96a50b3a79378c9171d9a485e4884eb58c` ->
`2cc7ed03c1739c457386bbb4e17286d3daf6daf3`. Each pair has the
same Git tree; every replacement is an ancestor of current `origin/main`.

## Scope boundary and effort telemetry

The original PMI/round-trip delivery tranche is complete: C1, C2, M1, M2, M3,
Q1, Q2, H2a, H2b, S1, and R1 are complete. Nightwatch/autoresearch, Hugging
Face model selection and loading, repeated variability campaigns, and new
dataset intake are follow-on work. They are not prerequisites for reporting
the merged gate and task-contract updates. S1 used one real, boxed,
local-no-charge `L1-ASSEMBLE` sample to demonstrate execution and trusted
grading; it is not a publishable benchmark cell. MARB's repeat-run policy still
requires its stated sample count before a board result or distribution claim is
published.

The follow-on HF/autoresearch implementation is isolated on MARB branch
`codex/hf-local-model-profile` and is not merged or part of the original-scope
closeout. No model download, external-provider call, or benchmark run is
attributed to that branch at this snapshot.

Effort figures below come from the retained Codex task telemetry for task
`01a0458e-6340-7e83-988a-4715438fbd92`. Token counters reset across long task
segments, so totals are reconstructed by summing the maximum of each monotonic
counter segment. Cached input is a subset of input. These figures measure model
context processing, including repeated cached-context replay after long turns
and compaction; they are not unique authored words, human labor hours, or an
API invoice. Active time sums this task's top-level `task_started` to
`task_complete` intervals, matched by turn ID; an unfinished interval is cut at
the next turn start or the snapshot cutoff. Subagent intervals are not added
separately. It includes tool/test wait time and excludes pauses between turns.
Snapshot cutoffs are parsed from each raw ISO-8601 event timestamp before JSON
object conversion so the UTC marker cannot be lost to local-time coercion.

| Snapshot | Reconstructed tokens | Input (cached / non-cached) | Output | Compactions | Wall span | Active task span |
|---|---:|---:|---:|---:|---:|---:|
| Original merged-implementation snapshot, 2026-08-28 13:42:38 UTC | 252,920,161 | 252,431,305 (249,292,928 / 3,138,377) | 488,856 | 10 | 14h 13m 23s | 13h 40m 03s |
| Follow-on session snapshot, 2026-08-29 18:26:16 UTC | 565,060,522 | 563,886,489 (556,214,400 / 7,672,089) | 1,174,033 | 16 | 1d 18h 57m 01s | 18h 11m 05s |

The difference after the original merged-implementation snapshot is 312,140,361
model tokens and approximately 4h 31m 02s of additional active task span. That
later interval includes coordination, pauses/resumes, GateRegistry and STEP
capture hardening, Nightwatch/autoresearch design, and the unmerged local-model
profile work; it must not be represented as effort required solely to implement
the two original CADCLAW gates.

### Recommended follow-on task boundaries

The cached-input dominance in this long, multi-repository task shows that future
work should use narrower sessions. Use one repository and one release gate per
session: CADCLAW changes, MARB changes, one boxed smoke, autoresearch design,
local-model selection/loading, and repeated benchmark campaigns should each be
separate. End each session at a merged PR or explicit blocked gate, update this
ledger with exact commits and evidence, and start the next session from that
durable record rather than replaying the full conversation. Keep any metered
external-provider authorization in the specific benchmark session that uses it.

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
- [x] PR #9 is merged and its tree-identical rewritten commit is verified on
  current `main`.

Evidence:

- Semantic-PMI implementation head before tracking/CI follow-ups:
  `ccc0f11d95802f093e46b36a0bb4b86fbe0222ca`
- Final PR head: `dc386bc492192cf3bd1dfd3a1ad3f48344e97821`
- GitHub-recorded pre-rewrite merge:
  `db41bea9495be8200490fa38bbd145c91bad716c`; current tree-identical `main`
  replacement: `3de26c15857299d3aef8a73b05574e7a7299b591`.
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
- PR #11 GitHub-recorded pre-rewrite merge:
  `14c7864abea2568cb0c0a462619fe6e1f1183700`; current tree-identical `main`
  replacement: `64150bfcf719574dd5f98f59f613a5737d145b2e`.

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
  `92dae6e9e08e8801188e4d260cb374128be1d77a`, GitHub-recorded pre-rewrite
  merge `2305d841c2ecf73d8ceb8e3a398766d2000e0912`, current tree-identical
  replacement `735b173182883dc90e7449701c1302fd21b876f4`.
- Runner exact-head GitHub checks: 447 tests ran with 13 environment-dependent
  skips; both CodeQL analyses and both answer-key guards passed. The exact-head
  local Windows clean clone ran the same 447 tests with 6 expected skips.
- Cross-platform tracked-byte integrity: [#14](https://github.com/sunnyday-technologies/CADCLAW/pull/14),
  head `b11a91f0af4fe43f0ea9abaa3cf2efa93a3a16ab`, GitHub-recorded pre-rewrite
  merge `94b0fd0072a9e6bf0a1ac54df5f3c9f0266b59c2`, current tree-identical
  replacement `b1ede598a83ec952aa57add0732ef93809b98be9`. Exact-head unit, CodeQL, and
  answer-key checks passed; the local full suite ran 449 tests with 6 expected
  skips.
- Case-sensitive lowercase cohort-ID guard: [#15](https://github.com/sunnyday-technologies/CADCLAW/pull/15),
  head `e56fc0c5da46e931f4f4737565fa40ce96d56118`, GitHub-recorded pre-rewrite
  merge `4579c5e925dfcc13236973aca295f42128704823`, current tree-identical
  replacement `93022d729ee9bb4eb7cd2d8aa09b8fa12fddfa20`. Exact-head unit, CodeQL, and
  answer-key checks passed; the local qualification module passed 17 tests.
- Two pre-publication local runs exposed the byte-normalization and ID-case
  gaps. Their evidence was never committed or published and remains only in
  ignored local backups.
- Cohort ID: `nist-ap242-20260828t101004z-cadclaw-4579c5e925df`.
- Historical exact target commit/tree:
  `4579c5e925dfcc13236973aca295f42128704823` /
  `581b78c92e049adfb00ad181e59a94d29ca3ef2a`; current tree-identical commit:
  `93022d729ee9bb4eb7cd2d8aa09b8fa12fddfa20`.
- Exact runner SHA-256:
  `1c031f7eb4318be9a38261b2545c765a60af1f634e2cbd01a5035d0d68ddb8c5`.
- Manifest:
  `evidence/qualifications/nist-ap242/nist-ap242-20260828t101004z-cadclaw-4579c5e925df/manifest.json`.
- FTC11 derivative SHA-256:
  `b21d95857ffc57fb87eecb924f0b91c49cf06fa71aff3da416227ab34196d885`.
- STC06 derivative SHA-256:
  `161a3ec55b152f367f4d77991fcb7f28aaf4b2e107cb736c4c1ccd24a2eb13f6`.
- Evidence-only PR / merge: [#16](https://github.com/sunnyday-technologies/CADCLAW/pull/16),
  head `8236a267cc5caebc032be94349224d5a4db93f6f`, GitHub-recorded pre-rewrite
  merge `cdbb45882fcd19092d4082cf490c27db12878d81`, current tree-identical
  replacement `9424a2629094b5a7e579180e1ed6b1c21d349d87`. Exact-head unit, CodeQL, and
  answer-key checks passed.
- Documentation closeout PR / merge:
  [#17](https://github.com/sunnyday-technologies/CADCLAW/pull/17),
  GitHub-recorded pre-rewrite merge
  `251bfb96a50b3a79378c9171d9a485e4884eb58c`, current tree-identical
  replacement `2cc7ed03c1739c457386bbb4e17286d3daf6daf3`.

### H2a/H2b - MARB cohort execution safety

- [x] The deterministic planner freezes task/kit/request identities, rejects
  registered-path collisions and unsafe paths, and makes zero provider, model,
  network, or benchmark-result writes.
- [x] The planner is explicitly labeled plan-only and cannot be confused with
  benchmark execution readiness.
- [x] The executor requires explicit execution authorization and creates
  UUID-backed, new-only run directories without mutating canonical board,
  registry, or historical evidence paths.
- [x] Model-produced Python runs only in a digest-pinned isolated container with
  read-only prior-workspace and immutable-input mounts, size-capped tmpfs for
  child writes, one exact writable export-file bind, no network, a read-only
  root, dropped capabilities, a clean environment, and no Docker socket.
  Brokered `write_file` content is validated and capped before the trusted host
  writes it into the attempt-local workspace.
- [x] L1/L2/L4 routing, continuous baseline-to-change sessions for L2/L4,
  deterministic editable-source ZIPs, STEP capture, failed-run retention, and
  exact provider/settings/timing/token/cost provenance are implemented and
  tested before any model call.

Evidence:

- H2a: [MARB #8](https://github.com/sunnyday-technologies/MARB/pull/8), head
  `7daf26d73da869de52b85d5d595b163421dd4322`, merge
  `d4f1dd836b94159bc72ed0b72be0e7c324239329`. Board policy, both answer-key
  guards, and both CodeQL analyses passed; the local dependency-free suite ran
  121 tests with one expected Windows newline-filename skip.
- H2b: [MARB #9](https://github.com/sunnyday-technologies/MARB/pull/9), head
  `b9eb841007e4f2d1f1cde072785203a4aefecd30`, merge
  `56177ae5815c99dce6a90ad509902cd196d840fd`. The 23-file final snapshot ran
  117 focused tests with one expected platform skip and 213 full board-policy
  tests with two expected platform skips; the exact committed head repeated all
  213 tests plus the answer-key and secret tree guards in a clean LFS-disabled
  checkout. GitHub board policy, both answer-key guards, both CodeQL analyses,
  and the additional CodeQL check passed on the exact PR head.
- Pre-fix Codex Security scan `a08e05b2-00f6-4b54-bb1e-da88773fea2c`
  identified one Medium untrusted-Git-executable boundary. The final snapshot
  binds and hash-locks the absolute Git executable across process creation,
  suppresses replacement refs, and bounds timeout/output; independent final
  verification marked occurrence `occ_20e331fb9692f0cfa2bccc28` fixed.
- The original H2a/H2b implementation validation made no container,
  provider/model, deployment, or provider-cost claim. Later runtime
  qualification is recorded separately below and is not a model benchmark.
- Runtime-policy hardening merged through
  [MARB #19](https://github.com/sunnyday-technologies/MARB/pull/19) at merge
  commit `352dbdec14324bf5d75200064efefe1a86099a55`. It preserves exact declared
  tmpfs-policy enforcement while allowing the container runtime's pre-start
  omission of derived mount records; partial or foreign mappings remain
  rejected.
- Retained private qualification R8 passed all nine fixed provider-free runtime
  cases against that merged source with container network mode `none`. The
  independently read-back record binds the source, immutable image, tools, and
  case results. It records no model/provider call, benchmark attempt, score,
  board mutation, deployment, or public performance claim.

### S1 - one boxed local smoke

- [x] Use the merged H2b executor and the frozen public `L1-ASSEMBLE` kit.
- [x] Use exactly one explicitly authorized local-no-charge model identity; no
  Grok, GPT, Claude, or other metered/external call is implied or authorized.
- [x] Record and verify the immutable OCI image `RepoDigest`, model/runtime
  identity, CADCLAW/MARB revisions, plan and authorization digests, timestamps,
  token usage, and retained artifact hashes.
- [x] Complete the documented no-provider/no-network container smoke before the
  model call.
- [x] Grade and read back the single retained attempt without mutating a public
  board row or presenting N=1 as a benchmark distribution.
- [x] Preserve checked/not-checked scope and any failure; a failed real smoke is
  evidence to fix the harness, not a result to hide or rerun until lucky.

Closeout:

- The exact immutable CAD sandbox image and provider-free runtime policy passed
  retained R8 qualification before the model call.
- One local-no-charge model identity passed the two-turn compatibility probe;
  the single authorized slot was then consumed once, with no retry.
- The executor completed and sealed the attempt with no pipeline or executor
  failure, retaining a 29,319,093-byte final STEP and editable source. The run log, artifact
  inventory, final STEP, and grade reports were independently hash-read back.
- Trusted offline v0.10 grading measured GAP median 170.0 mm, POS relative
  median 63.6 mm, and ORIENT aligned 16.7%. Separate native grading failed the
  inventory, interference, and floating gates with 64 total findings. The
  failure was retained; no replacement attempt was made.
- The result remains one private execution smoke (`N=1`), not a public board
  cell or model-performance distribution. No board, registry, site, deployment,
  or physical-validation claim was mutated.
- The HF/autoresearch branch remains follow-on and was not used to manufacture
  this S1 result.

Evidence slots:

- Run ID: private retained S1 sample; public alias `S1-20260906-01`.
- Exact model/runtime authorization: retained privately; local-no-charge,
  one authorized attempt, one consumed attempt, zero retries.
- Artifact manifest and grade: run-log SHA-256
  `0a916fca23adcd03248d54ac2d2c4ac8cff6bf91a592359c5607e4f610e44b42`;
  artifact-inventory SHA-256
  `a2b8494917a6742e738a9d1cc658368195eb36cf1122219a1ec7bff0b587a242`;
  final-STEP SHA-256
  `221a2a866593483c21336695a5aea577f9bdb845c4cad470e4e35e5a17643463`;
  v0.10 metric-report SHA-256
  `3ad454a60a36672c537e3ecbc4899c5749330c4081ff0d6d1eb2485811dbe63d`;
  native-grade SHA-256
  `dd1b5d4b10becd4fa9c39505daf1afbc1af60e20961d1d9c214e1c8b9bca7ad5`.
- Provider-free runtime prerequisite: R8, 9/9 fixed cases passed; private
  evidence retained and independently read back.

### B1 - Fresh benchmark cohort (follow-on)

- [ ] Dataset/task contract is versioned and frozen before runs begin.
- [x] Merge the separate bounded official NIST AP242 software-qualification
  cohort before model runs.
- [ ] Add a Berkeley robot hand/forearm assembly only if authored assembly STEP,
  license, and provenance are verified through a dataset-intake PR.
- [ ] A new run/cohort ID is used; no historical result is overwritten or
  silently re-scored.
- [x] An immutable approved OCI image `RepoDigest` and its build provenance are
  recorded, and the exact qualified host/image pair passed the documented R8
  provider-free, network-none runtime smoke before any model call.
- [ ] An explicitly approved aggregate campaign ledger reserves every N>=3/N>=9
  slot and enforces cohort-wide concurrency/uniqueness across checkouts and
  hosts; H2b's checkout-local `.slot-claims` are not treated as a global lock.
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

- H2b is merged, but the legacy destructive batch path remains prohibited and
  H2b itself remains fail-closed until every runtime, campaign, and execution
  authorization gate below is satisfied.
- `L2-RESOLVE` and `L4-ECO` require immutable gated-key revisions plus a trusted
  grading/readback path before their outputs can be called gradeable.
- The runtime prerequisite is satisfied only for the exact R8 source/image/host
  binding. Any replacement image, source revision, or execution host requires a
  new qualification before a model call.
- N>=3/N>=9 execution requires a separately approved aggregate campaign ledger
  with cross-checkout/cross-host slot uniqueness and concurrency control; H2b
  intentionally authorizes only one checkout-local slot at a time.
- Provider, exact model/version, data-sharing choice, and run limits require
  explicit approval before model calls. Current H2b accepts only an approved
  `local-no-charge` billing mode and rejects metered calls; an approved dollar
  budget alone cannot authorize a metered run until a frozen provider-specific
  pre-call pricing/token policy is implemented and separately reviewed.

### R1 - original-scope public closeout

- [x] Report uses merged-code and S1 smoke evidence only; it does not present
  the single run as a board benchmark or performance distribution.
- [x] Authoring, translation, and benchmark findings are separated.
- [x] Limitations and deferred scope are explicit.
- [x] No PMI/interoperability compliance or manufacturability claim is made.
- [x] Report artifact, source manifest, publication channel, and preparation
  date are recorded.

Evidence slots:

- Report path/link:
  `docs/cadclaw-marb-original-scope-closeout-2026-09-06.md`.
- Source manifest: report SHA-256
  `7f56a96df4dbc14a5b2f2b0d4c2c962e6ec7668430839944ffa51eca9cf29fca`;
  merged CADCLAW/MARB PR and commit identities are recorded in this ledger.
- Publication channel/preparation date: final technical closeout prepared for
  the CADCLAW GitHub repository on 2026-09-06. The user separately attested
  that the recommendation-driven update had already been communicated; this
  ledger does not claim independent delivery verification of the final S1
  supplement.

## Approved deferral

Material assignments and process/general notes are deferred from the current
semantic-PMI gate. Resume D1 only through a separate PR and gate-method-version
update after both a redistributable positive AP242 fixture and a verified
association-level extraction method exist.

Graphical PMI remains explicitly out of scope and is never implied by semantic
PMI success.

## Completion rule

Mark the original PMI/round-trip PR-and-report tranche `COMPLETE` only when C1,
C2, M1, M2, M3, Q1, Q2, H2a, H2b, S1, and R1 are complete and their evidence
slots are populated. B1 is the follow-on repeated benchmark program and may
continue after the original-scope report. D1 may remain `DEFERRED`.
