# CADCLAW gate-method specification

Current gate-method version: **0.13.0**.

This version is independent of:

- the CADCLAW package version;
- the `cadclaw.yaml` rules schema (`0.9`); and
- the JSON report schema (`0.7`).

Every newly generated `Report` carries `meta.gate_spec_version`. The existing
top-level report schema and positional `Report` constructor remain unchanged.
Historical reports are not silently re-scored. A report without this metadata
key is a legacy, pre-0.11 gate-method report; consumers must use its stored
package/report-schema context and must not infer a newer method tag. Reports
tagged `0.11.0` retain the semantic-PMI method below, and reports or immutable
qualification cohorts tagged `0.12.0` must not be relabeled as `0.13.0`.

## 0.13.0 — configured-harness execution integrity

The YAML-backed union harness now has one versioned registry,
`harness-gates.v1`, shared by the public `run_configured_harness` library
entry point, the `cadclaw harness` CLI wrapper, and the stateless MCP
`run_harness` tool. Registry v1 freezes these ordered gate IDs:

`inventory`, `interference`, `bom_audit`, `claim_audit`, `publish_audit`,
`pmi_present`, `roundtrip_step`, `orientation`, `floating`, and `color`.

Unknown, duplicate, overlapping, blank, and effective-empty selectors are
typed selection errors. Every valid run carries exactly one terminal ledger
row for every registered gate, using `pass`, `warn`, `fail`, `error`,
`not_applicable`, `not_checked`, or `skipped`. The selected-gate status
partitions are disjoint, registry-ordered, and exhaustive. A successfully
evaluated gate alone enters `confidence_budget.checked`; nested descriptive
prose cannot masquerade as a checked gate identity.

`meta.gate_registry.aggregate_status` distinguishes an evaluated design
failure from an execution error and from an all-not-applicable request. The
CLI returns 3 for `aggregate_status: error`, 1 for an evaluated failure, 2 for
warn-only, and 0 for pass or an explicitly reported all-not-applicable result.
Missing prerequisites, unreadable or malformed configured evidence, invalid
configured audit regexes, native/BRep failures, and incomplete label or
bounding-box evaluation are errors or not-checked outcomes rather than
evidence of a clear assembly. A configured audit lane that scans zero files
does not pass. An explicitly requested or configured gate that remains
not-checked fails the aggregate. The low-level `Harness` also rejects an empty
gate list instead of relying on the vacuous truth of `all([])`.

Interference is now wired into the configured union runner. Fewer than two
eligible parts is `not_checked`; label, bounding-box, and exact-boolean errors
are redacted execution errors; and focused MCP/inspect callers no longer
report an incomplete evaluation as clear. These orchestration and execution
integrity changes justify the gate-method version bump. The
`cadclaw.yaml` rules schema remains **0.9**, and the JSON `Report` schema
remains **0.7**.

## 0.12.0 — bounded AP242 STEP round-trip preservation

`ROUNDTRIP_STEP` is opt-in. When enabled, it performs an actual OCCT XCAF
import of the submitted STEP, exports that document with the AP242 schema, and
reimports the derivative. A disabled gate is `not_applicable` and does not run
the exporter. The source cannot be selected as the output, and a caller must
not overwrite an existing derivative. When no output path is supplied, the
temporary derivative is removed after comparison.

The translation comparison checks:

- exact count of CADCLAW-deduplicated imported renderable shapes: solids and
  shells collected by the shared render loader and deduplicated by coincident
  bounding-box signatures rounded to 0.1 mm (not a STEP product count);
- assembly and deterministically one-to-one-matched per-part axis-aligned
  bounding measures, within configured absolute/relative tolerances;
- the minimum shape distance for every explicitly declared, unambiguous
  interface pair, within its configured tolerance; and
- counts for each supported semantic-PMI class that is present in the source.

The minimum-cost one-to-one part-correspondence method is limited to 256
matched renderable shapes. If an equal-count comparison exceeds that boundary,
the gate returns `roundtrip.part_count_limit_exceeded` before allocating its
quadratic cost matrix. It does not sample, truncate, or call the omitted
per-part comparison a pass.

Every declared interface pair receives a result. A missing or ambiguous
selector is an error, not an omitted comparison or a guessed nearest part.
Semantic PMI is limited to class-count preservation for dimensions, geometric
tolerances, and datums. It does not compare PMI element identity, values,
references, associations, or construction correctness. If the source contains
none of those supported classes, the PMI comparison is `not_applicable`.

Source-translator family and product/version are caller declarations recorded
as assumptions. `unknown` and `occt` do not establish an independent-kernel
translation. A named `non_occt` source is described only as *declared
independent*; CADCLAW does not infer or verify translator identity from the
STEP header. An optional `authoring_reference_step_proxy` is another STEP
artifact and produces a separately labeled proxy comparison. It is not a
native-CAD model, native-reader check, or proof of authoring correctness.

Public report metadata contains content hashes plus bounded aggregate statuses
and deltas rather than full per-part geometry snapshots, source/proxy paths, or
duplicated finding trees. `IFSelect_RetDone` is the normal writer success.
Only `IFSelect_RetError` may be accepted provisionally, and only when the
writer produced a non-empty, non-symlink regular artifact with an AP242
`FILE_SCHEMA` that successfully reimports through STEPCAFControl into XCAF.
The raw writer status
and disposition remain visible as `meta.derivative.write_status` and
`meta.derivative.write_disposition`; the downstream scoped geometry and
source-present semantic-PMI comparisons still determine the gate result. All
other writer statuses, failed provisional checks, and other import, transfer,
reimport, selector, measurement, or cleanup failures remain explicit errors.
Provisional acceptance does not validate writer-internal reference integrity,
graphical PMI, or standards conformance. Repository regression coverage uses
an authored NIST AP242 fixture for the positive path and a real AP242 export
with semantic-PMI writing disabled for the negative control; the latter must
preserve the tested geometry evidence while failing semantic-PMI class-count
preservation.

### Known omissions

This method does not check:

- proprietary native-CAD state or suppressed/hidden native parts;
- verified translator identity or general cross-kernel interoperability;
- topology identity, surface/curve classes, tessellation, or design history;
- PMI element values, references, associations, construction, or presentation;
- graphical PMI, materials, process/general notes, or validation properties;
- assembly kinematics, manufacturability, physical performance, or safety; or
- compliance or conformance with AP242, ASME Y14, or another standard.

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
