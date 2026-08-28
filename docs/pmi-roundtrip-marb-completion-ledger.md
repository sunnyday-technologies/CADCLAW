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
- Native comparison is not applicable unless a readable native-reference
  artifact or explicitly identified proxy is supplied.
- Interface gaps are checked only for declared, unambiguous interface pairs.
- CADCLAW semantic-PMI and round-trip work ship through separate pull requests.
- MARB work remains in its separate repository and task. Existing benchmark
  runs are never silently re-scored or overwritten.

## Delivery status

| ID | Deliverable | Status | Dependency | Branch/task | PR | Merge commit |
|---|---|---|---|---|---|---|
| C1 | CADCLAW semantic AP242 PMI gate | MERGED | None | `feat/pmi-present-gate` (deleted after merge) | [#9](https://github.com/sunnyday-technologies/CADCLAW/pull/9) | `db41bea9495be8200490fa38bbd145c91bad716c` |
| C2 | CADCLAW AP242 STEP round-trip gate | NOT STARTED | C1 merged | `codex/roundtrip-step-gate` | TBD | TBD |
| M1 | MARB repeat-run reporting and acceptable-solution policy | IN PROGRESS | Independent | task `01a046b7-1430-7792-b891-709e5b60c7ff` | TBD | TBD |
| M2 | MARB `L2-RESOLVE` task | NOT STARTED | M1 method/version decisions | Same MARB task | TBD | TBD |
| M3 | MARB `L4-ECO` task | NOT STARTED | M1; C2 only if used as a first-class gate | Same MARB task | TBD | TBD |
| B1 | Fresh versioned benchmark cohort | BLOCKED | C1, C2, M1, M2, and M3 merged | N/A | N/A | N/A |
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
- NIST STC06 fixture SHA-256:
  `71777C28DA76DA0E8A667E4CBE792D5F72C09B5C56440C9744D3D50CA96ECC8D`
- NIST FTC11 fixture SHA-256:
  `20A92EDF514AE0989D556F9C7B9F065AED741CFBB361B7FE4CB7938A1EB5C232`
- Resolved CI issue: the GitHub Linux runner initially reached VTK rendering
  without a display and exited 139. The full, unchanged suite now runs under
  Xvfb; no rendering tests are skipped.

### C2 - AP242 STEP round trip

- [ ] Actual OCCT import -> AP242 export -> reimport executes.
- [ ] Exact part count and assembly/per-part bounding comparisons execute.
- [ ] Every declared interface pair reports its gap comparison.
- [ ] Semantic PMI classes present in the source are compared before/after.
- [ ] A real intentionally dropped-PMI translation is detected.
- [ ] Independence is not claimed for unknown or OCCT source translators.
- [ ] Native comparison reports not applicable without a reference artifact.
- [ ] Focused, full-suite, JSON-output, site, and clean-clone validation pass.
- [ ] Separate PR is green, reviewed, merged, and read back from `main`.

Evidence slots:

- Gate-method version: TBD
- OCP version: TBD
- Normal round-trip report and artifact hashes: TBD
- Broken-translation report and artifact hash: TBD
- PR/check links: TBD

### M1/M2/M3 - MARB

- [ ] M1 publishes repeat-run distributions and preserves legacy single-run
  provenance.
- [ ] New frontier cells require at least three seeded runs under the accepted
  policy.
- [ ] M2 publishes the scored `L2-RESOLVE` method and evidence.
- [ ] M3 publishes the scored `L4-ECO` method and evidence.
- [ ] Each task is independently reviewable and merged through its own PR, with
  Tasks 3 and 4 paired only as allowed by the MARB prompt.
- [ ] Every merge bumps or records the applicable MARB method/spec version and
  preserves old cells' original version tags.
- [ ] MARB PR links, merge commits, and clean-run evidence are recorded here.

Evidence slots:

- M1 PR / merge / validation: TBD
- M2 PR / merge / validation: TBD
- M3 PR / merge / validation: TBD

### B1 - Fresh benchmark cohort

- [ ] Dataset/task contract is versioned and frozen before runs begin.
- [ ] Start with a bounded official NIST AP242 cohort; add a Berkeley robot
  hand/forearm assembly only if authored assembly STEP, license, and provenance
  are verified.
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

Mark the overall plan `COMPLETE` only when C1, C2, M1, M2, M3, B1, and R1 are
complete and their evidence slots are populated. D1 may remain `DEFERRED`.
