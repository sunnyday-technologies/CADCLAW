# Semantic AP242 PMI fixtures

These two authored, single-product STEP files come from the NIST MBE PMI
Validation and Conformance Testing dataset. They are repository test evidence
for `PMI_PRESENT_SEMANTIC`; CADCLAW did not generate or modify their geometry.
The project selected these official cases instead of fabricating a synthetic
multi-part PMI assembly.

Source pages:

- https://www.nist.gov/ctl/smart-connected-systems-division/smart-connected-manufacturing-systems-group/mbe-pmi-0
- https://www.nist.gov/document/nist-pmi-step-files

Retrieved: 2026-08-27.

| File | NIST case | AP242 edition | SHA-256 | OCP 7.8.1.1 semantic counts |
|---|---|---|---|---|
| `nist_stc_06_asme1_ap242-e3.stp` | Simplified Test Case 06 | e3 | `71777c28da76da0e8a667e4cbe792d5f72c09b5c56440c9744d3d50ca96ecc8d` | dimensions 17; geometric tolerances 25; datums 51; 2 presentation-only dimension labels ignored |
| `nist_ftc_11_asme1_ap242-e2.stp` | Fully-Toleranced Test Case 11 | e2 | `20a92edf514ae0989d556f9c7b9f065aed741cfbb361b7fe4cb7938a1eb5c232` | dimensions 6; geometric tolerances 4; datums 4; 2 presentation-only dimension labels ignored |

Both are direct members of the downloaded archive under
`NIST-PMI-STEP-Files/`. The FTC 11 archive member is named `...ap242-e2.stp`,
while its embedded Part 21 `FILE_NAME` value says `...ap242-e1.stp`; this table
uses the archive member name and does not silently normalize that upstream
mismatch.

NIST states that its test cases, CAD models, and STEP files may be used
without restriction, requests acknowledgement, and says their use does not
imply NIST recommendation or endorsement. The NIST logo is not included.

These files are not asserted to be error-free conformance references. NIST's
dataset notes that some supplied files may contain syntax or translation
issues. The counts above describe this versioned CADCLAW/OCCT observation;
they do not certify either the files or the reader.

Run the positive declared-check example from the repository root:

```powershell
cadclaw pmi-present --rules tests/fixtures/pmi_semantic/cadclaw.yaml
```
