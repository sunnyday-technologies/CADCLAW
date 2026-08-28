# CADCLAW gate-method specification

Current gate-method version: **0.11.0**.

This version is independent of:

- the CADCLAW package version;
- the `cadclaw.yaml` rules schema (`0.9`); and
- the JSON report schema (`0.7`).

Every newly generated `Report` carries `meta.gate_spec_version`. The existing
top-level report schema and positional `Report` constructor remain unchanged.
Historical reports are not silently re-scored. A report without this metadata
key is a legacy, pre-0.11 gate-method report; consumers must use its stored
package/report-schema context and must not infer the 0.11 method tag.

## 0.11.0 — semantic AP242 PMI presence

`PMI_PRESENT_SEMANTIC` reads a submitted STEP AP242 file through OCCT's XCAF
document model. A task declares expected classes in
`pmi_present.expected_classes`. The supported classes are:

- `dimensions`;
- `geometric_tolerances` (semantic feature-control-frame data);
- `datums`.

The report records `present` or `absent` separately for each declared class,
with the observed XCAF label count as evidence. There is no combined PMI score.
An absent declared class is a failed declared check. If no classes are
declared, applicability is `not_applicable` and the confidence budget says
`task has no declared PMI requirements`.

Presentation-only OCCT dimension labels (`CommonLabel` and
`DimensionPresentation`) are excluded from the semantic dimension count and
recorded as diagnostics. Import failure, malformed STEP, non-AP242 input, and
native reader/extraction failure are errors rather than evidence of absent PMI.
The report records the installed OCP/OCCT reader version; fixture expectations
in this method were established with OCP 7.8.1.1.

### Known omissions

This method does not check:

- graphical PMI presentation or annotation rendering;
- material assignments;
- process notes or general notes;
- validation properties;
- correctness or completeness of every GD&T construction subtype;
- native-CAD-model to derivative-STEP fidelity; or
- compliance or conformance with AP242, ASME Y14, or another standard.

### Fixture evidence

Repository tests use two unmodified, authored, single-product NIST MBE PMI
STEP files with
source URLs, hashes, observed counts, and reuse terms recorded in
`tests/fixtures/pmi_semantic/README.md`. Their presence demonstrates the tested
reader behavior for those exact files and dependency versions; it is not an
endorsement or certification by NIST.
