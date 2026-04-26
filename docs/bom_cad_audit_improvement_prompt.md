# CADCLAW Max/Max Improvement Prompt: Red-Team CADQuery, STEP, and BOM Audit Toolkit

## Goal

Turn CADCLAW from a promising STEP validation harness into a much more useful local CADQuery/STEP/BOM audit toolkit for real open-hardware release work.

This prompt should be treated as a red-team product spec. The implementation should identify where CADCLAW currently overclaims, where it silently depends on fragile environment assumptions, and where it needs sharper gates before it can honestly be described as "pytest for CAD."

The first major feature remains a first-class gate that compares a public/procurement BOM against a CAD assembly and reports drift in both directions:

- BOM item exists but is missing, stale, or incorrectly represented in CAD.
- CAD geometry exists but is missing from the BOM.
- BOM quantity, manufacturing type, material/source notes, and role descriptions contradict the CAD assembly or project-specific design rules.

This should work locally, without SaaS, and should be callable from Python, CLI, and the CADCLAW MCP server.

## Red-Team Thesis

CADCLAW should not merely answer "does this STEP contain the expected bounding-box signatures?" It should help a small manufacturing/open-hardware team avoid shipping a false public design:

- A STEP export can silently omit hidden Fusion parts.
- A CadQuery source script can lag behind the authoritative Fusion design.
- A public BOM can contain old purchased parts after the design moved to printed parts.
- A public claim can say "production-capable" or "validated" when the evidence only supports "candidate" or "prototype."
- A local procurement spreadsheet can contain private order data and must never be treated as publishable BOM truth.
- A green inventory check can be dangerously misleading if it only checks global counts and not where those parts are located.
- A successful install can still leave the user unable to run CADCLAW because the virtualenv points to a missing Python executable.

CADCLAW needs to detect these failure modes, explain them clearly, and avoid false confidence.

## Current Claim Red Team

Challenge these CADCLAW claims and improve the toolkit until they are substantially true:

1. "The testing framework CAD never had."
   - Current risk: CADCLAW tests STEP geometry, but not enough of the design-release pipeline.
   - Required improvement: include source-generation, STEP export, BOM, and public-claim checks in the normal harness.

2. "Like pytest for mechanical design."
   - Current risk: pytest has deterministic tests, fixtures, clear assertions, stable failure reports, and CI ergonomics. CADCLAW still relies heavily on user-crafted labels and environment-specific CADQuery installs.
   - Required improvement: add stable rule files, deterministic output, fixture generators, actionable failures, and `cadclaw doctor`.

3. "BOMs drift from geometry."
   - Current risk: README says this, but CADCLAW does not yet have a direct BOM-vs-CAD gate.
   - Required improvement: implement `bom_audit` as a first-class module and MCP tool.

4. "MCP gives Claude direct access to CAD validation."
   - Current risk: MCP tools are only as useful as the installed Python/CadQuery/OCP environment, and errors may be opaque.
   - Required improvement: MCP should expose `doctor`, environment status, dependency versions, and safe file-scope reporting.

5. "No commercial CAD software needed."
   - Current risk: true for CadQuery/STEP validation, but not true for validating Fusion-native `.f3d` browser visibility, suppressed parts, or design history.
   - Required improvement: clearly separate what CADCLAW can validate from STEP/CadQuery versus what requires export discipline or Fusion API integration.

6. "CAD via Python via prompt."
   - Current risk: vague marketing phrase.
   - Required improvement: define exact supported workflow: prompt -> modify CadQuery script/rule file -> regenerate STEP -> run CADCLAW gates -> inspect report/render. Do not imply direct reliable Fusion editing unless a Fusion connector exists.

## Why This Is Needed

During the M3-CRETE audit, CADCLAW could validate STEP inventory and geometry, but it did not provide a direct "BOM JSON vs CAD assembly" gate. M3-CRETE has:

- `bom/data.json` as the public interactive BOM source of truth.
- `bom/index.html` as the public interactive/no-JS BOM viewer.
- `CAD/m3_2_assembly.py` and STEP exports as geometry sources.
- Local SN001 build/procurement BOMs that must stay ignored/private.

The missing feature is a clean bridge between CAD-derived inventory and public BOM claims.

## Additional Obvious Gaps To Close

### 1. Environment Doctor

Add:

```bash
cadclaw doctor
```

It should report:

- Python executable path.
- Python version.
- Whether `cadquery`, `OCP`, `vtk`, and `Pillow` import correctly.
- CADCLAW package path and version.
- Whether the current virtualenv is broken, especially if `pyvenv.cfg` points to a missing base Python.
- Whether MCP entrypoint `cadclaw-mcp` can start and answer `tools/list`.
- Whether the current repo has likely CAD files and common rule files.

Acceptance case from M3-CRETE:

- `cad_venv/pyvenv.cfg` pointed to `[home-path-redacted] which was missing.
- `cadclaw doctor` should explain: "This venv is not portable; recreate it or install CADCLAW into an available Python."

### 2. Source-to-STEP Parity

Add a gate that compares:

- CadQuery source-generated STEP.
- Fusion/exported STEP.
- Previous known-good STEP.

It should report:

- File size changes.
- Total part count changes.
- Unique dimension-signature changes.
- Parts present in one STEP but missing from another.
- Suspicious "smaller export despite added geometry" warnings.

This protects against Fusion visibility toggles and stale CadQuery scripts.

### 3. Region-Aware Inventory

Global counts are not enough. A design can have 32 wheels globally but place them in the wrong regions.

Add first-class region rules:

```yaml
regions:
  z_posts:
    expected:
      vwheel: 16
  y_gantry:
    expected:
      vwheel: 8
  x_carriage:
    expected:
      vwheel: 8
      cbeam_gantry_plate: 2
```

Support axis-aligned boxes, named anchor points, and part-center filters. Report both global pass/fail and per-region pass/fail.

### 4. CADQuery Source Linting

CADCLAW should inspect CadQuery scripts for common design-release hazards:

- Hard-coded output path that can clobber a Fusion export.
- Silent fallback geometry.
- Unnamed parts.
- Repeated magic dimensions without constants.
- Missing `metadata`/part-name mapping for downstream audit.
- Assembly output that changes when imported versus when run as `__main__`.

M3-CRETE acceptance case:

- `m3_2_assembly.py` should never overwrite `CAD/M3-2_Assembly.step` if that path is reserved for Fusion/exported authoritative geometry. The linter should flag that.

### 5. Labeling Beyond Bounding Boxes

Bounding-box signatures are useful but brittle. Improve label confidence by combining:

- bbox dimension signature.
- volume.
- surface area.
- color/material metadata if present.
- STEP product names if present.
- CadQuery assembly names if available.
- user rule overrides.

Report confidence:

```json
{"label": "vwheel", "confidence": 0.92, "evidence": ["bbox", "volume", "name"]}
```

Warn when labels are ambiguous or multiple part types share the same bbox.

### 6. Public Claim Audit

Add an optional text-claim gate for README/docs/BOM notes:

- Detect unsupported absolutes: "production-ready", "validated", "guaranteed", "exclusive", "fully automated", "no risk."
- Require evidence tags for numeric performance claims.
- Separate verified physical measurements from simulation from design intent.
- Flag stale language contradicted by BOM rules.

Example:

- "less than 0.5mm flex under 5kg" should be tagged as `analysis`, `test`, or `physical-validation`.
- "actual flex is far below that" should either include a measured value or be marked as qualitative SN001 physical observation.

### 7. Privacy and Publish Boundary

CADCLAW should include a publish audit helper:

```bash
cadclaw publish-audit --repo . --public-bom bom/data.json
```

Default local-only ignores:

- `.env*`
- `bom/build_bom_*.py`
- `bom/M3-CRETE_*_build_bom.xlsx`
- `bom/orders/**`
- `_archive/**`
- raw transcripts
- personal order IDs, thread IDs, shipping/payment fields

It should print filenames and finding types, not secret values.

### 8. Rule Authoring Assistant

Add a command that scaffolds a rule file from a STEP/BOM pair:

```bash
cadclaw init-rules --step CAD/M3-2_Assembly.step --bom bom/data.json --out CAD/cadclaw_rules.yaml
```

It should:

- list detected CAD signatures.
- suggest labels.
- find BOM items with similar names.
- ask the user to confirm mappings.
- write a starter YAML file.

This is critical because hand-writing labels is the adoption bottleneck.

### 9. Human-Readable Reports

Provide three report formats:

- terse CLI report for CI.
- Markdown report for pull requests.
- JSON report for MCP/automation.

A good finding should look like:

```text
FAIL BOM-005: Straight Line Internal Connectors
Expected qty 12, found BOM qty 16.
Reason: M3-2 has three 2m X-direction butt joints and four connector bars per joint.
Suggested fix: set qty=12 and describe connector bars as alignment aids, not primary stiffness.
```

### 10. False Confidence Budget

Every report should include:

- what was checked.
- what was not checked.
- what assumptions were made.
- confidence level.

Example:

```text
Checked: STEP bbox inventory, BOM JSON rules, README claims.
Not checked: native Fusion browser visibility, actual physical deflection measurement, vendor stock availability.
Assumption: M3-2 has three reinforced 2m X-direction members.
```

This prevents CADCLAW from becoming another tool that sounds more certain than it is.

## Concrete M3-CRETE Cases This Gate Must Catch

1. Connector bars
   - BOM item: Straight Line Internal Connectors, id 5.
   - Expected for M3-2: 3 butt joints x 4 connector bars per joint = 12.
   - Role: alignment aid in top/bottom V-slots across the joint.
   - Must not overclaim "maximum rigidity" or primary centering/stiffness.
   - CAD/BOM audit should flag if count is not 12 or if text claims these provide primary stiffness.

2. 2040 reinforcement insert
   - BOM item: X-Direction Internal Reinforcement, id 65.
   - Expected for M3-2: 3 bars, each 1000mm long.
   - Geometry/design rule: each 1000mm 2040 insert is centered across a 2m 4080 C-Beam butt joint, spanning 500mm each side.
   - Role: primary centering and stiffness at X-direction 2m splices.
   - No adhesive in the current SN001 method.
   - Printed end retainers hold the insert in place.
   - Audit should flag stale "bonded", "JB Weld", "West System", or "custom 2m cut" language.

3. Printed retainers
   - BOM item: 2040 Insert End Retainers, id 85.
   - Expected for M3-2: 2 per reinforced 2m member, 6 total if there are 3 reinforced members.
   - Manufacturing type: print.
   - Audit should flag if missing from BOM when id 65 exists.

4. Printed motor mounts
   - Z motor mounts are integrated into the printed combined corner bracket.
   - No purchased steel NEMA23 L-brackets in the current reference design.
   - Audit should flag purchased motor mount BOM entries, approved commercial bracket suppliers, or claims like "cannot be easily 3D printed."

5. Printed idler mounts
   - Idler plates/mounts are 3D printed.
   - Expected count: 6 total = 4 Z-axis + 2 Y-axis.
   - Audit should flag old 14-plate counts or approved commercial idler plate suppliers.

6. All primary frame extrusions are 4080 C-Beam
   - Public BOM should not imply mixed 2040/2080 frame stock except for the internal 2040 reinforcement inserts.
   - Audit should distinguish "primary frame extrusion" from "internal reinforcement insert."

7. Wheel count
   - Expected total: 32 wheels.
   - Breakdown: Z 4x4=16, Y 2x4=8, X double-plate 2x4=8.
   - Audit should flag old 24/28/36 counts or local region mismatches.

8. Belt widths
   - Y/Z belts: 10mm.
   - X-gantry belt: 6mm to fit in the slot.
   - Audit should flag "X/Y/Z all 10mm" or "Y uses 6mm."

## Proposed API

Python:

```python
from cadharness.bom_audit import BomCadAudit, BomRule

audit = BomCadAudit(
    bom_path="bom/data.json",
    step_path="CAD/M3-2_Assembly.step",
    labels={
        (40.0, 80.0, 1000.0): "cbeam_4080",
        (20.0, 40.0, 1000.0): "insert_2040",
        (56.4, 56.4, 76.6): "nema23",
        (10.2, 23.9, 23.9): "vwheel",
    },
    rules=[
        BomRule(id=5, expected_qty=12, required_terms=["alignment aid"], forbidden_terms=["primary stiffness", "maximum rigidity"]),
        BomRule(id=65, expected_qty=3, expected_unit="bars (1.0m each)", required_terms=["500mm each side", "friction-fit"], forbidden_terms=["bonded", "JB Weld", "West System", "custom 2m cut"]),
        BomRule(id=85, expected_qty=6, expected_mfg_type="print"),
    ],
)

report = audit.run()
print(report)
raise SystemExit(0 if report.passed else 1)
```

CLI:

```bash
cadclaw bom-audit --bom bom/data.json --step CAD/M3-2_Assembly.step --rules CAD/bom_rules.yaml
cadclaw doctor
cadclaw parity --old CAD/M3-2_Assembly_previous.step --new CAD/M3-2_Assembly.step
cadclaw claim-audit --docs README.md bom/data.json --rules CAD/cadclaw_rules.yaml
cadclaw publish-audit --repo .
```

MCP tool:

```json
{
  "name": "check_bom_against_cad",
  "description": "Compare BOM JSON/CSV against a STEP assembly and project-specific BOM rules."
}
```

Add MCP tools:

- `doctor`
- `load_assembly`
- `check_inventory`
- `check_region_inventory`
- `check_bom_against_cad`
- `check_claims`
- `check_publish_boundary`
- `compare_step_parity`
- `init_rules_from_step_and_bom`

## Rule File Format

Support YAML or JSON:

```yaml
labels:
  "(40.0,80.0,1000.0)": cbeam_4080
  "(20.0,40.0,1000.0)": insert_2040

rules:
  - id: 5
    name: Straight Line Internal Connectors
    expected_qty: 12
    required_terms:
      - alignment aid
      - 4 connector bars per joint
    forbidden_terms:
      - maximum rigidity
      - primary stiffness
  - id: 65
    expected_qty: 3
    expected_mfg_type: buy
    required_terms:
      - 1000mm
      - 500mm on either side
      - friction-fit
      - printed retainers
    forbidden_terms:
      - bonded
      - structural adhesive
      - JB Weld
      - West System
      - custom 2m cut
  - id: 85
    expected_qty: 6
    expected_mfg_type: print
```

## Output Requirements

Return a structured report with:

- `passed`: boolean.
- `summary`: counts of pass/warn/fail.
- `findings`: list with severity, BOM item id/name, CAD signature if applicable, message, and suggested fix.
- `cad_inventory`: CAD-derived part counts by label.
- `bom_inventory`: BOM item counts by normalized part label.
- `unmapped_cad_parts`: CAD labels with no BOM mapping.
- `unmapped_bom_items`: BOM items with no CAD mapping, allowing `reference_only`, `consumable`, `electronics`, and `optional` exemptions.

The report must never print secrets or local procurement details.

## Local Privacy Boundary

The audit must default to public/design BOM files only. It should ignore:

- `bom/build_bom_*.py`
- `bom/M3-CRETE_*_build_bom.xlsx`
- `bom/orders/**`
- `_archive/**`
- `.env*`

## Acceptance Tests

Create fixtures where:

1. Connector bars are listed as 16 instead of 12 -> fail.
2. Connector bars claim "maximum rigidity" -> fail.
3. 2040 insert text says "bonded with JB Weld" -> fail.
4. id 85 printed retainers are missing while id 65 exists -> fail.
5. Z motor mounts are `mfg_type: buy` with approved steel bracket suppliers -> fail.
6. Idler plates are 14 and `mfg_type: buy` -> fail.
7. Wheel count is 24/28/36 instead of 32 -> fail.
8. X belt described as 10mm -> fail.
9. Clean current M3-CRETE BOM rules -> pass.
10. Broken virtualenv path in `pyvenv.cfg` -> `cadclaw doctor` fails with actionable repair guidance.
11. Fusion-exported STEP loses a part and shrinks unexpectedly -> parity warning.
12. Global wheel count is correct but all X wheels are missing and extras are elsewhere -> global inventory pass but region inventory fail.
13. Two different parts share a bbox signature -> label ambiguity warning.
14. README says "production-ready" without evidence tag -> claim audit warning/fail depending severity config.
15. Local order spreadsheet is present but ignored -> publish audit pass.
16. Local order spreadsheet is staged -> publish audit fail without printing private values.
17. CadQuery script writes to a protected Fusion-export path -> source lint fail.
18. Missing rule file -> command suggests `cadclaw init-rules`.
19. BOM has a printed part with approved commercial-only supplier and no self-manufacture route -> fail.
20. BOM has a purchased item that CAD/rules say is printed -> fail.

## Definition of Done

The implementation is not done until:

- `cadclaw doctor` clearly distinguishes package install success from runnable CAD environment success.
- The M3-CRETE current public BOM passes the new BOM audit with a rule file.
- Intentional stale versions of M3-CRETE BOM fail with useful messages.
- The MCP server exposes the new checks and can return structured JSON without dumping private file contents.
- The README is updated to describe the exact "prompt -> CadQuery -> STEP -> CADCLAW validation" loop without implying unsupported Fusion-native editing.
- CI examples include both a minimal STEP inventory check and a BOM-to-CAD release gate.
- Docs include a "What CADCLAW Does Not Prove" section.

## "What CADCLAW Does Not Prove" Docs Requirement

Add this concept to the README/docs:

CADCLAW can provide structured evidence that a particular exported STEP file and a particular BOM/rule set agree under declared assumptions. It does not prove that:

- the native CAD model has no hidden/suppressed parts,
- the physical build matches the CAD,
- a vendor part is in stock,
- a printed part is strong enough for production,
- a structural claim is physically certified unless measurement data is attached,
- an AI-generated CAD change is correct without passing the checks.

This limitation should be explicit. It strengthens CADCLAW's credibility.

## LinkedIn-Friendly Summary

CADCLAW should become the local "pytest for CAD and BOMs": point it at a STEP assembly, a CadQuery source file, and a BOM, then let it tell you whether the geometry, procurement list, and public claims still agree. The next improvement is a release-grade audit layer that catches stale purchased parts, wrong counts, hidden STEP export omissions, broken CAD Python installs, and old design language before they reach GitHub or a builder.

For CADQuery users, the target workflow is:

1. Describe the design change in a prompt.
2. Modify or generate the CadQuery model.
3. Export STEP.
4. Run CADCLAW inventory/interference/region/BOM/claim checks.
5. Get a structured report showing what passed, what failed, and what the tool did not prove.

That is the honest version of "CAD via Python via prompt": not magic, but a local validation loop that makes AI-assisted mechanical design auditable.
