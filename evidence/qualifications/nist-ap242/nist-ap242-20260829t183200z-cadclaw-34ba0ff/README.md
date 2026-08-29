# NIST AP242 software-qualification cohort: nist-ap242-20260829t183200z-cadclaw-34ba0ff

Outcome: **pass**

This cohort qualifies CADCLAW commit 34ba0ffdb3b7b21b46182b85a08e6759527fe1d9 (tree 3dbf743936af408eea1e236654a81bdb3be99493), which exactly matched freshly fetched origin/main when the run began. CADCLAW executed from a clean Git archive of that commit; the caller's branch and working tree were not used as Python source.

## Evidence

The cohort runs pmi-present and roundtrip-step against the authored NIST FTC 11 AP242 e2 and STC 06 AP242 e3 fixtures. The FTC 11 archive member is AP242 e2 even though its embedded Part 21 FILE_NAME reports AP242 e1; this cohort retains the archive-member identity without normalization. manifest.json records exact fixture, report, derivative, commit, tree, runtime, and toolchain hashes or versions, along with UTC gate timestamps and exit outcomes. SHA256SUMS covers every tracked cohort artifact other than itself.

Both OCCT writes returned IFSelect_RetDone with the exact ret_done disposition.

Derivative STEP files are retained only under the ignored local directory .qualification-temp/nist-ap242/nist-ap242-20260829t183200z-cadclaw-34ba0ff/derivatives. They are not part of this tracked cohort. Their hashes, sizes, schemas, and exact OCCT writer statuses/dispositions remain in manifest.json and the raw round-trip reports.

## Scope and limitations

This is a no-spend software-qualification cohort, not a MARB/model benchmark and not a geometry-authoring exercise. It checks declared semantic dimensions, geometric tolerances, and datums; AP242 export/reimport; bounded geometry preservation; and supported semantic PMI class-count preservation.

It does not certify graphical PMI, saved views, materials, process/general notes, semantic values or associations, standards conformance, native-model fidelity, independent-kernel translation, NIST endorsement, or error-free reference-file status. See manifest.json for the complete confidence boundary.
