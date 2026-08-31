# NIST AP242 software qualification

This directory holds immutable, no-spend software-qualification cohorts for
CADCLAW's semantic AP242 PMI and STEP round-trip gates. It is deliberately
separate from MARB: these two authored NIST single-product fixtures qualify a
versioned CADCLAW runtime; they do not measure an AI model's assembly skill.

Run a fresh cohort only after checking out a clean `main` whose `HEAD` equals
freshly fetched `origin/main`. Create the evidence feature branch after the
script finishes, so the qualification itself observes exact clean `main`:

```powershell
.\scripts\run-nist-ap242-qualification.ps1 `
  -CohortId "20260828t180000z-main-abcdef0"
```

The script fetches `origin/main`, resolves an exact commit, and executes
CADCLAW from a clean Git archive of that commit. An optional `-TargetCommit`
must be a full 40-character SHA and must equal the freshly fetched
`origin/main`; this guards against silently qualifying a stale or moving
revision. The caller's branch and working-tree changes are never imported as
CADCLAW source because a non-main or dirty caller is rejected before any
qualification output is created. The executing runner must also be present byte-for-byte in that
exact target commit, and the target must contain the local-work ignore rule.
This intentionally prevents a runner that is only uncommitted or present on a
feature branch from producing publishable evidence.

Each cohort is new-path-only and contains:

- `manifest.json` using `nist-ap242-qualification-manifest.v1`;
- the raw JSON reports for `pmi-present` and `roundtrip-step` on FTC 11 and
  STC 06;
- a cohort README with the scope and limitations; and
- `SHA256SUMS` for every other tracked cohort artifact.

Generated derivative STEP files remain under the ignored local directory
`.qualification-temp/nist-ap242/<cohort-id>/derivatives`. They are never copied
into tracked evidence. Their hashes, sizes, schemas, and exact OCCT writer
status/disposition are retained in the manifest and raw reports.

The frozen semantic counts are FTC 11 dimensions/geometric tolerances/datums
`6/4/4` and STC 06 `17/25/51`. FTC 11's NIST archive member is AP242 e2 while
its embedded Part 21 `FILE_NAME` reports AP242 e1; the archive-member e2
identity is retained without normalization. The current runner freezes report
schema 0.7, rules schema 0.9, and gate-spec 0.13.0. The immutable tracked
`nist-ap242-20260828t101004z-cadclaw-4579c5e925df` cohort predates that bump and correctly remains
tagged gate-spec 0.12.0; it is historical evidence and is not relabeled.

Repository author-metadata cleanup can change commit IDs without changing
their source trees. `history-rewrite-attestation.v1.json` maps an immutable
cohort's recorded commit to its replacement commit only when the replacement
is retained by rewritten `main` and resolves to the cohort's exact recorded
tree. Tests then revalidate the runner, rules, and fixture blobs from that
replacement tree. The cohort manifest remains unchanged, and an absent,
non-ancestral, or tree-mismatched replacement fails closed.

Output ancestors may not be symlinks or reparse points. Final publication uses
a same-volume atomic directory move that fails if the cohort destination
already exists. Cohort IDs reject Windows device-name stems and trailing dots
or spaces.

`IFSelect_RetError` is never rewritten as `IFSelect_RetDone`. If CADCLAW's
bounded artifact, AP242-schema, and XCAF-reimport checks accept that status,
the manifest preserves `ret_error_provisionally_validated` and marks the
cohort `pass_with_provisional_writer_status`.

Do not reuse a cohort ID. A failed attempt leaves its ignored local work in
place so that a retry cannot silently replace evidence; diagnose it and choose
a new ID. No model/provider calls, tokens, costs, or paid benchmark work are
part of this workflow.
