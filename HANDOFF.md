# CADCLAW — Session Handoff

Last updated: 2026-04-29

Authoritative cross-machine carry-over for post-release work. Travels with `git pull`.

---

## In progress — v0.9 (active development line)

Driven by the M3-CRETE 2026-04-29 V1.0 close-out field test
(`D:/SunnydayTech/M3-CRETE/docs/session_logs/2026-04-29-cadclaw-close-out-handoff.md`).
The user's V1.0 freeze surfaced 6 manual fixes that "should have been done by
CADCLAW" — orientation issues, color mismatches, and a floating part that
geometric checks missed.

**Shipped on `main` toward v0.9** (not yet released as a tag/PyPI):
- **P0 — cp1252 stdout fix** (commit `4eef772`). `_force_utf8_stdio()` in
  `main()` reconfigures Windows stdout/stderr to UTF-8 so the v0.7.0 MED-5
  `Δ` character no longer crashes `cadclaw bom-audit`.
- **Gate #7 — `cadclaw inspect cluster <step>`** (commit `01e21d3`).
  Single-link agglomerative spatial clustering. Replaces the manual
  10-minute "where are these unlabeled parts?" analysis that the V1.0
  session ran by eye.
- **Gate #1 — orientation / face-mate gate** (this commit). New schema
  `0.7 → 0.9` extends `labels:` to accept either a 3-tuple (legacy) or a
  `LabelSpec` dict with `expected_face` / `expected_against` / `max_gap_mm`.
  New `cadclaw/orientation.py` module computes each part's UNSORTED bbox
  thinnest-axis and compares against the rule's expected face plane.
  Closes 4 of 6 V1.0 manual fixes: misoriented idlers + connectors that
  had correct bboxes but wrong rotation. Findings carry a structured
  `suggested_fix` describing the rotation (e.g. `"rotate 90° about Z"`),
  matching the v0.7.1 interference auto-fix-vector pattern.

**Remaining v0.9 work** before cutting a release tag:
- Gate #2 — color/material attribute check (closes V1.0 fixes 1 + 6).
- Gate #3 — floating-part detection (closes V1.0 fix 2).
- Gates #4–9 may slip to v0.9.x if v0.9.0 ships with #1 + #2 + #3.

**Schema migration** for users on v0.7 / v0.8.0 yamls: bump
`schema_version: "0.9"`. Existing 3-tuple labels keep working unchanged.
v0.6 / v0.7 → v0.9 migration error message in `rules.py:_check_version`
spells this out.

---

## Current version

**v0.8.0** — module rename `cadharness` → `cadclaw` prepared on 2026-04-29.

### What's in v0.8.0

A breaking-but-shimmed import-name change. The PyPI package name is unchanged (`pip install cadclaw`); the Python module that PyPI installs is now `cadclaw`, matching the project name. Field-test feedback ("`cadclaw` sounds way cooler than `cadharness`") plus the ergonomic absurdity of `pip install cadclaw && import cadharness` made this a clean v0.8 milestone.

**The rename:**

- `cadharness/` → `cadclaw/` (every submodule preserved per-file via `git mv`).
- `pyproject.toml` packages list now includes both `cadclaw*` and `cadharness*` so the wheel ships the new module **and** the compat shim.
- `cadclaw_cli/` and `cadclaw_mcp/` (which were already correctly named) had every internal `from cadclaw.X import Y` swept.

**The compat shim** ([cadharness/__init__.py](cadharness/__init__.py)):

- Pure re-export — no duplicated state, no version drift. Aliases every `cadclaw.<sub>` submodule into `sys.modules` under `cadharness.<sub>` so `from cadharness.bom_audit import run_bom_audit` keeps resolving to the same function as `from cadclaw.bom_audit import run_bom_audit` (verified by `assertIs` in `tests/test_compat_shim.py`).
- Emits one `DeprecationWarning` on first `import cadharness`, naming v0.8.0 as the rename point and v1.0 as the removal point.
- Subpackage support — `from cadharness.reporters.text import render_text` works without per-file shim code; `__getattr__` falls through to `cadclaw.<name>` for anything not pre-aliased.
- Tested with 6 new tests in `tests/test_compat_shim.py` covering: deprecation warning fires, version matches, function identity preserved, subpackage submodules work, attribute access falls through.

**Migration from v0.7.1 to v0.8.0:**

- Recommended: change `from cadharness.X import Y` → `from cadclaw.X import Y` at your convenience. The deprecation warning will tell you each entry point that needs updating.
- No code changes are *required* — every v0.7.1 import path works in v0.8.0.
- The `cadharness` module will be removed in v1.0.

**Test count**: 234 → 240 passing (6 new compat-shim tests). Schema unchanged at 0.7.

**Why this is the v0.8 milestone** (instead of the build-piece prototype that
HANDOFF.md previously sketched): module-name confusion was the single biggest
papercut in M3-CRETE field tests, and the rename is a fully-shimmed change
that costs zero engineering for downstream users while clearing the import-
name embarrassment for new ones. Builder primitives stay parked until M3-CRETE
surfaces a real demand.

**PyPI status:** PyPI is currently stuck at v0.5.0; v0.6, v0.7, v0.7.1 were never published. v0.8.0 is the clean re-publish point — `pip install --upgrade cadclaw` will jump users from 0.5.0 → 0.8.0 in one move with no broken imports.

---

## Previously: v0.7.1 (2026-04-26)

**v0.7.1** — ergonomics polish prepared on 2026-04-26 (same day as v0.7.0).

### What's in v0.7.1

Closes the M3-CRETE 2026-04-26 nudge-session field-test backlog
(handoff: `M3-CRETE/docs/session_logs/2026-04-26-cadclaw-nudge-handoff.md`).
The session demonstrated CADCLAW's canonical success — a 0.35mm rear
X-rail clip detected against the X-carriage gantry plate, fixed by
shifting the plate +1.35mm in Y — but exposed three ergonomics gaps:

- **Ergo-1 — Auto-suggested fix vector for interference clips.**
  ([cadclaw/interference.py](cadclaw/interference.py)) `Clip` now
  carries `bbox_a`, `bbox_b`, `overlap_dims`, `suggest_axis`,
  `suggest_shift_mm`, `clearance_mm`. The harness picks the axis with
  the smallest bbox overlap (cheapest fix) and computes a signed
  translation that pushes part A clear with the configured clearance
  (default 1mm). Reports now read `plate at (1495, 540, 366) clips
  cbeam by 264 mm³ — shift +Y by 1.35mm to clear with 1mm clearance`
  instead of just the volume number. Wired through the MCP
  `check_interference` tool. New optional `interference:` section in
  `cadclaw.yaml` (`skip_labels`, `min_volume_mm3`, `min_clearance_mm`)
  — additive, no schema bump.
- **Ergo-2 — `cadclaw inspect <step>` subcommand.**
  ([cadclaw/inspect.py](cadclaw/inspect.py),
  [cadclaw_cli/main.py](cadclaw_cli/main.py)) Three sub-subcommands
  replace the throwaway probe scripts users were writing:
  `cadclaw inspect sigs <step>` for a bbox-signature histogram,
  `cadclaw inspect part <step> --at X,Y,Z|--sig dx,dy,dz|--label NAME`
  for "what is this part", and `cadclaw inspect overlaps <step>
  --label NAME|--at X,Y,Z [--clearance MM]` for "what overlaps with X"
  (uses the same fix-vector math from Ergo-1). All accept optional
  `--rules cadclaw.yaml` for label resolution.
- **Ergo-3 — `AGENTS.md` + de-bias starter examples.**
  ([AGENTS.md](AGENTS.md), [README.md](README.md),
  [cadclaw.yaml](cadclaw.yaml)) New top-level `AGENTS.md` documents
  the "place authored parts; do not generate them" rule for AI
  assistants. README links to it from a new "Using CADCLAW with an
  AI assistant" section. Starter `cadclaw.yaml` clarifies that labels
  are *observational* (CADCLAW labels what's there; it does not
  generate parts) and now uses explicit `{}` / `[]` for empty
  sections so it loads cleanly out of the box (was: `labels:` with
  only commented entries parsed as `None` and tripped pydantic).
- **LOW-7 — `publish.committed` finding text rephrased.**
  ([cadclaw/publish_audit.py](cadclaw/publish_audit.py)) The
  v0.7 message auto-suggested `git rm --cached` without considering
  that `ignore_globs` over-matching is also a possibility (e.g.
  `blog/**` accidentally covering live GitHub Pages content).
  Rephrased to present "(1) the FILE is wrong" vs "(2) the RULE is
  wrong" symmetrically with `Do NOT blindly run git rm --cached`.
- **INFO-9 — UTF-8 mojibake detection in BOM strings.**
  ([cadclaw/bom_audit.py](cadclaw/bom_audit.py),
  [cadclaw/rules.py](cadclaw/rules.py)) New `bom.encoding_issue`
  WARN finding when BOM `name`/`description`/`notes` fields contain
  cp1252-misencoded UTF-8 sequences (`â€"`, `Ã©`, `Ã¼`, `Â°`, etc.).
  Opt-out via `bom_audit.warn_on_mojibake: false`. Detection is
  conservative (matches `Ã` or `Â` followed by a high-Latin-1 char,
  plus the literal `â€` prefix) so legitimate Latin text like
  "São Paulo" is not flagged.

**Test count**: 207 → 234 passing (27 new tests across Ergo-1, Ergo-2,
LOW-7, INFO-9). No schema bump — `cadclaw.yaml` files written for
v0.7.0 continue to load with no changes required.

### Migration from v0.7.0 to v0.7.1

No required changes. New optional fields:

- `interference.skip_labels`, `interference.min_volume_mm3`,
  `interference.min_clearance_mm` (Ergo-1)
- `bom_audit.warn_on_mojibake: bool = True` (INFO-9 — set to `false`
  to suppress the detector)
- `claim_audit.scan_paths: [README.md, AGENTS.md]` is suggested if
  you ship an AGENTS.md.

The `interference:` section is currently used by the harness Python
API (`Harness.add_interference(min_clearance_mm=...)`) and by the MCP
`check_interference` tool. Wiring `cadclaw harness` (the YAML-driven
runner) to read `rules.interference` is part of v0.8 — see "v0.8 —
ergonomics, take 2" below.

---

## Previously: v0.7.0 (2026-04-26)

**v0.7.0** — field-test-driven polish release prepared on 2026-04-26.

### What's in v0.7.0

Closes the remaining 6 items from the M3-CRETE 2026-04-26 field test
(HIGH-1 and LOW-8 already shipped in v0.6 PR5; v0.6.1 was a
citation/version-string patch). Verification target: M3-CRETE harness
failures **16 → ≤2** and warns **59 → ≤8**.

- **Schema bump 0.6 → 0.7** ([cadclaw/rules.py](cadclaw/rules.py)).
  Hard-fail with a one-line migration hint when an old `cadclaw.yaml`
  with `schema_version: "0.6"` is loaded. New optional fields
  (`expected_design_qty`, `spare_qty`, `exempt_categories`,
  `warn_on_unmapped`) require no rename to migrate. Bumped because
  observable behavior changed for users with multi-rule labels (MED-5
  aggregation) and changed CAD-count fallback semantics (MED-6).
- **MED-2 — negation-aware `forbidden_terms`**
  ([cadclaw/bom_audit.py](cadclaw/bom_audit.py)). Forbidden-term
  matches preceded by a negation token within 30 chars (bounded by
  sentence punctuation) are suppressed. Tokens: `not`, `no`, `never`,
  `do not`, `don't`, `doesn't`, `replaces`, `instead of`, `rather than`,
  `without`, `excludes`. Required-term matching keeps dumb-substring
  semantics — `required_terms: ["plastic"]` should still satisfy "no
  plastic" because the rule asks about presence-of-token, not assertion.
  `use_regex: true` rules bypass the lookback (authors get raw control
  via lookbehinds).
- **MED-3 — license- and negation-aware `claim_audit`**
  ([cadclaw/claim_audit.py](cadclaw/claim_audit.py)). License
  attribution lines (`(CC BY`, `MIT License`, `Apache License`, `GPL`,
  `SPDX-License-Identifier:`, `Copyright (c)`, `Copyright ©`) and
  single-line HTML comments (`<!-- ... -->`) are blanked before
  `forbidden_absolutes` and `stale_terms` scanning so e.g. a CC BY-SA
  attribution citing "OpenBuilds" doesn't trigger a fix that would be a
  license violation. Numeric-claim regex still scans the original text
  (license blocks citing deflection numbers should still warrant
  evidence tags). Same negation logic as MED-2.
- **MED-4 — drop "validated" from default `forbidden_absolutes`**
  ([cadclaw/claim_audit.py](cadclaw/claim_audit.py)). The word is
  too overloaded across third-party-product mentions and ASTM-validated
  phrases to be a default. Projects that want it caught can opt in via
  `forbidden_absolutes_extra: ["validated"]`.
- **MED-5 — aggregate `cad.count_mismatch` per label**
  ([cadclaw/bom_audit.py](cadclaw/bom_audit.py)). When multiple
  BOM rules expect the same CAD label, the audit now emits ONE
  aggregated finding showing per-rule expected counts and total delta
  (`CAD has 6× motor_nema23, rules sum to 7 (ids 9+14+19 expect
  1+2+4). Δ=-1.`) instead of N redundant findings. Single-rule labels
  keep the v0.6 message verbatim. Severity for the aggregated finding
  is the strictest of contributing rules' `severity_overrides`.
- **MED-6 — `expected_design_qty` + `spare_qty`**
  ([cadclaw/rules.py](cadclaw/rules.py),
  [cadclaw/bom_audit.py](cadclaw/bom_audit.py)). Two new optional
  `BomRuleModel` fields separate design count (CAD intent) from order
  count (BOM `qty`, procurement). `expected_design_qty` takes precedence
  in `_effective_cad_count` over the v0.6 fallback to BOM qty, fixing
  the cbeam-with-spare false positive. `spare_qty` is informational; if
  `expected_qty` AND `expected_design_qty` AND `spare_qty` are all set
  and `expected_qty != design + spare`, a soft `bom.spare_qty_inconsistent`
  WARN is emitted (real procurement legitimately diverges via split
  shipments / replenishments — don't enforce).
- **LOW-6 — `bom.unmapped_item` noise reduction**
  ([cadclaw/rules.py](cadclaw/rules.py),
  [cadclaw/bom_audit.py](cadclaw/bom_audit.py)). Two orthogonal
  levers added to `BomAuditModel`: `exempt_categories: List[str]`
  (case-insensitive substring match against the BOM item's `category`
  field) and `warn_on_unmapped: bool = True` (set False to suppress
  entirely). M3-CRETE recipe drops 51 → ~3 warns: `exempt_categories:
  ["Fasteners", "Electronics", "Wire", "Consumables"]`.

**Test count**: 176 → 207 passing (31 new tests across MED-2/3/4/5/6 and
LOW-6).

### Migration from v0.6.x to v0.7.0

1. Bump `schema_version: "0.6"` → `schema_version: "0.7"` in your
   `cadclaw.yaml`. No field renames required.
2. If you relied on "validated" being flagged as a forbidden absolute,
   add `forbidden_absolutes_extra: ["validated"]` under `claim_audit`.
3. (Optional) Adopt `expected_design_qty` / `spare_qty` for BOM items
   that intentionally order more than the design uses (e.g. spares,
   pack-multiples). Example:
   ```yaml
   - id: 67
     expected_design_qty: 17
     spare_qty: 1
     expected_label: cbeam
   ```
4. (Optional) Add `bom_audit.exempt_categories` and/or set
   `warn_on_unmapped: false` to quiet the unmapped-item noise on real
   BOMs with electronics, fasteners, wire, etc.

### Deferred from v0.7 to v0.7.1

- **LOW-7** — `publish.committed` finding text rephrasing (the
  auto-suggested `git rm --cached` is dangerous when `ignore_globs` is
  the bug; cosmetic-only diff, no impact on M3-CRETE numbers).
- **INFO-9** — UTF-8 mojibake detection in BOM. M3-CRETE artifact
  already fixed in field test; CADCLAW detector remains useful for
  catching the same issue on other BOMs but isn't load-bearing for the
  M3-CRETE field test rerun.

---

## Previously: v0.6.0 → v0.6.1 (2026-04-26)

v0.6.1 was a citation/version-string patch (`CITATION.cff`,
`pyproject.toml`, `cadclaw/__init__.py`, `cadclaw_mcp/server.py`) —
no logic changes.

## Previously: v0.6.0 (2026-04-25, "honest core")

### What's in v0.6.0

- **Findings / Severity / Report model** (`cadclaw/findings.py`) — single shape every gate emits; `pass` / `warn` / `fail` rollup; JSON-safe `evidence`; locked `schema_version: "0.6"`.
- **YAML rule loader** (`cadclaw/rules.py`, pydantic v2) at `cadclaw.yaml`. Bbox sigs are 3-element lists, every section optional.
- **BOM-vs-CAD audit** (`cadclaw/bom_audit.py` + `bom_loader.py`) — headline gate. Catches qty / mfg_type / unit mismatches, required-or-forbidden text terms, and CAD-side count drift. Privacy enforced at the serializer (`vendors`, `sku`, `unit_cost`, `_*` always dropped).
- **Doctor** (`cadclaw/doctor.py`) — Python / venv / deps / MCP / repo signals. Catches the broken-pyvenv case where `pyvenv.cfg home =` points at a missing interpreter.
- **Publish-audit** (`cadclaw/publish_audit.py`) — three-state (untracked / staged / committed) file model + regex content scan with email allowlist. Never echoes matched secret values.
- **Claim-audit** (`cadclaw/claim_audit.py`) — forbidden absolutes, untagged numeric claims, user-supplied stale terms, plus two folded source-regex rules (protected output paths, silent fallback geometry) over `.py` files.
- **`cadclaw` console script** (`cadclaw_cli/`) — argparse stdlib. Subcommands: `doctor`, `bom-audit`, `parity`, `claim-audit`, `publish-audit`, `inventory`, `harness`. Exit codes 0/1/2/3.
- **Three reporters** (`cadclaw/reporters/`) — text (CLI, ANSI auto), markdown (PR-comment ready), json (versioned, MCP/CI).
- **6 new MCP tools** in `cadclaw_mcp/server.py`: `doctor`, `check_bom_against_cad`, `check_publish_boundary`, `check_claims`, `check_region_inventory`, `compare_step_parity`. Plus 11 v0.5 tools kept verbatim → 17 total.
- **`examples/init_rules.py`** — one-shot scaffolder that emits a starter `cadclaw.yaml` from a STEP + BOM pair.
- **README + `docs/index.html`** rewritten — softer hero, explicit "What CADCLAW Does Not Prove" section, honesty toolchain callout.
- **156 passing tests** (73 v0.5 + 83 new): findings/rules/reporters, doctor, CLI, BOM audit acceptance (privacy + 13 cases), publish-audit (state classification + redact), claim-audit (forbidden + numeric + stale + source-regex).

New deps: `pyyaml>=6.0`, `pydantic>=2.5`.

### v0.6 field-test fixes (HIGH-1 / LOW-8 / blob_size, 2026-04-26)

After v0.6 PRs 1–4 were committed, the worktree was field-tested against
the real M3-CRETE project (101-component STEP, 64-part BOM with populated
`vendors`/`sku`/`unit_cost`). The privacy guard verified — zero findings
cited any always-private field. Three issues surfaced and were patched
before v0.6.0 ships:

- **HIGH-1 — BOM loader accepts `parts:` synonym** ([bom_loader.py](cadclaw/bom_loader.py))
  Hardware BOMs commonly use `{"version": "...", "parts": [...]}` (M3-CRETE
  does). The loader now accepts `items` and `parts` interchangeably; `items`
  wins on conflict. Other top-level keys (`version`, `generated`, `source`,
  `notes`) are ignored as author metadata. Released the M3-CRETE shim.

- **LOW-8 — `cadclaw harness` `duration_ms` always 0** ([cadclaw_cli/main.py](cadclaw_cli/main.py))
  `_cmd_harness` built `aggregate = Report(...)` with the default
  `duration_ms=0.0` and never set it. Now wraps the runner in a
  `time.time()` and sets `aggregate.duration_ms` before emit.

- **`publish_audit.blob_size_warn_bytes` default 5 MB → 20 MB** ([rules.py:102](cadclaw/rules.py#L102))
  5 MB triggered on M3-CRETE's 9.2 MB STEP and would on most real
  assemblies. Still configurable per-project; set `0` to disable.

Tests added: 19 in `tests/test_bom_loader.py` (parts-key acceptance,
reject-unknown-key regression, privacy projection lock-in,
exemption logic), 1 in `tests/test_cli.py` (timing assertion).
Total: **176 passing tests**.

### v0.7 candidates (driven by M3-CRETE field test, 2026-04-26)

Deferred from v0.6 to land as a coherent v0.7 polish release. Field-test
report at `D:/SunnydayTech/M3-CRETE/cadclaw-v0.6-field-test-2026-04-26.md`.

**Shipped in v0.7.0** — see top of this file for what landed:
- MED-2 — negation-aware `forbidden_terms`
- MED-3 — license / negation-aware `claim_audit`
- MED-4 — drop "validated" from default `forbidden_absolutes`
- MED-5 — aggregate `cad.count_mismatch` per label
- MED-6 — `expected_design_qty` + `spare_qty`
- LOW-6 — `bom.unmapped_item` noise reduction (`exempt_categories` + `warn_on_unmapped`)

**Deferred to v0.7.1**:
- **LOW-7 — `publish.committed` finding text** — current message "X is
  committed but listed in ignore_globs" suggests `git rm --cached`,
  which is dangerous if the user's `ignore_globs` rule is the mistake
  (e.g. `blog/**` covering live GitHub Pages content). Rephrase to
  present both options (file is wrong vs rule is wrong).
- **INFO-9 — UTF-8 mojibake detection in BOM** — surface
  `bom.encoding_issue` when string fields contain `â€"`, `Ã©`, etc.
  (cp1252-misencoded UTF-8). Nice-to-have. (M3-CRETE artifact already
  fixed in twin session — 44 corrupt sequences rewritten in place;
  CADCLAW detector remains useful for catching the same issue on other
  BOMs but is no longer a blocking concern for the M3-CRETE field
  test.)

### v0.7 (deferred, defensible)

- Full source-lint AST module — only protected-output and silent-fallback regex rules ship in v0.6.
- `cadclaw init-rules` as a CLI subcommand — ships as `examples/init_rules.py` script in v0.6.
- Label confidence beyond bbox (volume, surface area, STEP product name, AP242 color).
- MCP super-tool `run_harness(rules_path)`.
- Subprocess-based MCP self-check inside `doctor`.
- Cloud / virtual-python-host hosting (explicit out of scope).

Run tests: `python -m unittest discover tests` — ~80 s, all 176 must pass.

---

## v1.0 north star — builder + validator unified

**Goal**: CADCLAW becomes the assemble-as-you-go tool. The same
`cadclaw.yaml` that today validates "X has 4 wheels at signature
[10.2, 23.9, 23.9]" also generates those wheels at those positions. Rule
file declarations flow both ways: CAD ↔ rule, BOM ↔ rule, region ↔ rule.
Pieces declare themselves, the file accumulates, the harness reports
"what's built, what's pending, what's wrong" at every step.

**Hard constraint — no new geometry kernel.** v1.0 must orchestrate
existing open-source CAD-as-code libraries, not reinvent. Candidates:

- [**CadQuery**](https://github.com/CadQuery/cadquery) — already a
  CADCLAW dep; mature; STEP import/export; assembly + selectors. The
  default backend.
- [**build123d**](https://github.com/gumyr/build123d) — modern fork of
  CadQuery (same OCP kernel) with a cleaner API. Optional alt backend.
- [**OCP**](https://github.com/CadQuery/OCP) — the underlying OpenCascade
  Python bindings. Already pulled in via CadQuery. Direct use only for
  things CadQuery can't express.
- **OpenSCAD**, **FreeCAD scripting** — possible secondary backends
  behind the same rule abstraction; out of scope for v1.0 unless
  someone has a strong use case.

**What CADCLAW adds on top** (none of which is a kernel):

1. The rule file as the canonical spec. Each piece optionally carries a
   `build:` block with a parametric recipe (e.g. CadQuery snippet, or a
   reference to a named primitive). Validation logic stays as-is.
2. A `cadclaw build` / `cadclaw build-piece` CLI that reads the spec,
   composes pieces via the chosen backend, writes a STEP, and runs the
   harness in one go.
3. A build/validate REPL: AI agents (or humans) iterate
   build-piece → validate → patch spec → continue. Each iteration is
   visible in the harness's confidence budget.
4. Honesty extensions: `confidence_budget.not_built_yet` for declared-
   but-not-emitted pieces, `parametric_placeholder: true` markers for
   stand-in geometry awaiting replacement, source-of-truth tracking when
   the same piece exists in multiple backends (CadQuery script ↔ Fusion
   STEP ↔ build123d script).
5. A library of named primitives (vwheel, cbeam, plate, motor_nemaXX,
   etc.) backed by CadQuery. Each primitive is a thin wrapper —
   parameters in, OCP shape out — not a new modeling system.

**Stepping stones**:

- **v0.8** — design-doc + minimal `cadclaw build-piece` for one or two
  primitives (vwheel, cbeam). Round-trip: declare in yaml, generate
  STEP, validate against the same yaml. Prove the loop.
- **v0.9** — primitive library expanded to cover the M3-CRETE BOM.
  `cadclaw build` composes a full assembly. The rule file becomes
  authoritative for both build and validate on that one project.
- **v1.0** — backend abstraction (CadQuery default, build123d optional),
  REPL-friendly MCP tools, confidence-budget extensions for
  not-built-yet / parametric-placeholder. Documented "build a project
  from scratch with cadclaw" tutorial.

**Out of scope** (defensibly):

- Writing a CAD kernel. OCP/OpenCascade does the geometry; CADCLAW
  composes.
- Native `.f3d` editing. Fusion stays an export source; CADCLAW reads
  the resulting STEP.
- A GUI. The CLI + MCP + rule file are the interface.
- Replacing CadQuery's API. CADCLAW's value is the spec + audit + REPL,
  not the modeling DSL.

The honesty ethos carries forward: the v0.6 README's "What CADCLAW Does
Not Prove" section gets a sibling — "What CADCLAW Did Not Build" —
listing every piece that's specced but not yet emitted.

---

## Previously: v0.5.0 (2026-04-19)

- Tolerance stacking (9 tests, hand-calculated answers)
- Disassembly: `export_radial()` method, O(n²) lookup bug fixed in `export_exploded()`
- `cadclaw/render.py` module: STEP → PNG → animated GIF via offscreen VTK + Pillow
- MCP server: `disassembly_sequence`, `export_exploded_view` tools; stdout-to-stderr fix
- 52 passing tests (up from 17); VTK + GIF stitching integration tests included
- `pyproject.toml` fixes, Pillow dep, `cadclaw-mcp` console script

---

## Post-release work (this session — 2026-04-20)

### Done

- **Abandoned `feat/cable-drag-chains`** (Y:/M3-CRETE) — reverted regression of authored brackets + removed out-of-scope kinematic simulation. Branch deleted locally (never pushed). Stash `stash@{0}` kept as safety net.
- **Dropped `m3crete_radial_dragchains.gif`** from CADCLAW docs (was untracked; just `rm`'d).
- **Added GIF output size gate** to `cadclaw/render.py`:
  - `GIF_SIZE_WARN_BYTES = 5_000_000` (matches Claude API vision cap directly)
  - `_warn_if_gif_too_large()` fires stderr warning at both save paths (`render_frames_to_gif`, `render_radial_explode_gif`)
  - Initial threshold was 4.5 MB; raised to 5.0 MB after empirical evidence showed 4.76 MB files worked in chat
- **Added** `examples/m3_crete/render_baseline.py` — repeatable runner for both GIF types, points at the current authoritative M3-CRETE STEP.
- **Dropped sequential-disassembly GIF** — only the radial explode + 360 spin is published now; it communicates the same thing in 15 s of render vs 10 min.
- **Re-rendered `docs/media/m3crete_radial_spin.gif`** from the 9.18 MB Fusion full-model export — 4.08 MB, 76 frames, 720×540, `gif_colors=48`, `dither=Image.NONE` (flat colors, no speckle).
- **Dither fix in `render.py`** — switched `convert("P", ...)` to `dither=Image.NONE` at both save paths. This eliminates the "grey-with-green-speckles" quantization artifact on the Sunnyday-green printed parts. Default adaptive-palette dither was Floyd-Steinberg and mixed non-green pixels into flat-green regions.
- **STEP color import (AP242) in `render.py`** — new `_extract_step_colors()` helper uses `STEPCAFControl_Reader` + `XCAFDoc_ColorTool` to pull per-shape RGB from the STEP's AP242 color metadata. `render_step_to_png` and `render_radial_explode_gif` now take `use_step_colors: bool = True` (default on). Priority: STEP color → label map → default. Verified against the M3-CRETE Fusion export: 85 colored shapes extracted cleanly (V-wheels and pulleys come through green as Fusion tagged them; motors black; plates dark).
- **Dropped `cadclaw/wheel_carriage.py`** — written, smoke-tested, then removed. User's insight reframed the problem: buried-wheel was passing validation because `skip_labels={'belt','vwheel'}` in the example config was suppressing the very check that should have caught it. Minimal fix was to drop `'vwheel'` from [examples/m3_crete/check.py:38](examples/m3_crete/check.py#L38). No new module.

### Key findings

- **Claude Code `Read` tool image limit ≈ 5 MB** (documented API cap). Empirically: 4.76 MB sometimes accepted, 5.05 MB+ rejected. Gate at 5 MB is operationally safe with `optimize=True` on GIFs.
- **GIF quantization artifact on flat-color parts** — default Pillow `convert("P", palette=Image.ADAPTIVE)` uses Floyd-Steinberg dithering, which produces visible speckle on nominally-flat colored surfaces (Sunnyday green became "grey with green speckles"). Fix: pass `dither=Image.NONE`. Costs some gradient smoothness, wins flat color fidelity — right trade for CAD renders with solid per-part colors.
- **Interference-check blanket skips are anti-patterns.** `skip_labels={'belt','vwheel'}` was suppressing legitimate mis-placement detection. The correct posture: reserve skips for labels with *geometric* justification (belts wrap pulleys, creating unavoidable tooth-mesh overlap). Wheels correctly placed in V-grooves overlap the groove *void* (no solid material), not the extrusion — so they don't need skipping in the first place.
- **Fusion STEP exports silently drop invisible parts.** The user hit this twice in this session — a part that was toggled invisible in Fusion's browser panel was not included in the STEP export, with no warning. Compensate by: (a) preferring CADQuery-regen STEPs for reproducibility, (b) sanity-check part counts after each Fusion export, (c) flag any Fusion export that is *smaller* than a prior version despite added geometry.
- **X-axis flexure resolved by extrusion rotation alone** — the 2 m X-beam (two 1 m sections butt-joined) only needs to be rotated to tall orientation (80 mm vertical). Bare-beam deflection at 5 kg mid-span = 0.225 mm (target ≤ 0.5 mm). No internal plate reinforcement needed for deflection control per the 2026-04-20 calc. Joint-integrity splice plate is a separate concern, deferred.
- **Directly writing a CADQuery regen to `CAD/M3-2_Assembly.step` will clobber any Fusion-exported STEP at that path.** `m3_2_assembly.py` hard-codes its output path. **Fix before next CADQuery regen:** change the output path to a distinct name (e.g. `M3-2_Assembly_cadquery.step`) so Fusion and CADQuery outputs never collide.

### M3-CRETE state — two-sided divergence (as of 2026-04-20)

- **Fusion side** (`M3-CRETE/CAD/M3-2_Assembly.step`, 9.18 MB) — latest authoritative source:
  - Has: X-axis tall rotation, X-gantry carriage (plate + V-wheels), top T-plate connector, all brackets
  - This is the single source of truth for GIF rendering as of end-of-session
- **CADQuery side** (`M3-CRETE/CAD/m3_2_assembly.py`, 757 lines) — stale relative to Fusion:
  - Missing: X-axis tall rotation, X-gantry carriage
  - Has: 3D-printed green T-brackets at mid-X spreader, combined motor-mount plates, bottom spacer plates, Y-motor adapter plates, correct L-brackets
  - **Next-session work**: rotate X-rail template to tall, add X-gantry carriage by replicating Z/Y carriage geometry pattern (explicit user ask: "copy the same carriage we are using from the z- and y axes (we are replicating here intentionally)")

### CADCLAW improvement opportunities (user-flagged during 2026-04-20 session)

Concrete gaps CADCLAW should catch automatically, not leave to eyeball:

1. **Source-to-source parity check** — compare two STEPs (e.g., Fusion export vs CADQuery regen) and report parts present in one but not the other. Would have caught the X-carriage-plate gap and the triangular-gusset-vs-rectangular-approximation mismatch in seconds.
2. **Template-substitution warnings** — when a CADQuery script replaces real geometry with a parametric placeholder (e.g., cylinder stand-in for a V-wheel), emit a warning. Buried placeholders are a recurring gotcha.
3. **Per-region inventory** — allow BOM-style counts per spatial region ("X-carriage should have 8 wheels + 2 plates"), not just global counts. Would catch region-local omissions that pass a global check.
4. **Bbox-sig vs transform-aware color matching** — current `_extract_step_colors` keys by untransformed leaf bbox; many AP242-colored parts fall through to the label-map fallback because the render's transformed shapes don't match keys. Fix: key by dim-signature (sorted tuple) so all instances of a shape share a color even after translation.
5. **Fusion visibility-toggle detector** — a Fusion STEP export that is *smaller* than a prior version despite added parts should raise a structured warning. Recurring pitfall this session.

Logged as CADCLAW v0.6.0 candidates.

### Current in-flight

- Render `bzuwfkofy` — re-rendering both GIFs from the new 9.18 MB Fusion export (disassembly ~10 min, radial_spin ~15 s).
- HANDOFF.md update (this file) written mid-render.

### Uncommitted state at snapshot

**CADCLAW** (branch `feat/simultaneous-explode`):
- `cadclaw/render.py` (5 MB size gate + `dither=Image.NONE`)
- `docs/media/m3crete_radial_spin.gif` (4.08 MB clean re-render from Fusion full model)
- `docs/media/m3crete_disassembly.gif` dropped — radial-spin replaces it
- `examples/m3_crete/check.py` (dropped `vwheel` from interference skip list)
- `README.md` (disassembly → radial-spin hero GIF reference)
- `examples/m3_crete/render_baseline.py` (new render runner, radial-only)

**M3-CRETE** (branch `main`):
- `CAD/M3-2_Assembly.step` — new Fusion export, 9.18 MB, authoritative

---

## Remaining CADCLAW work (post-v0.5.0)

1. **PyPI publishing** — `python -m build && twine upload dist/*`. `pyproject.toml` audited.
2. **JOSS paper** — time-gated to **2026-10-18** (6 months after first public commit on 2026-04-18).
3. **Render tuning** — if future GIFs are needed, `render_baseline.py` is the template. Tuned defaults: 720×540, `gif_colors=32`, `n_transition_frames=1` (disassembly), `rotate_frames=48` (radial).
4. **GIF gate — consider making it configurable** via env var or constructor arg rather than module-level constant, if future pipelines want different thresholds.

## Remaining M3-CRETE work

1. **Catch CADQuery script up with Fusion** — rotate X-rail to tall + add X-gantry carriage (Z/Y pattern replication). Then regen, verify visual parity with Fusion, publish a deterministic source.
2. **Split script output path** so CADQuery regen never clobbers Fusion-exported `M3-2_Assembly.step`. Change `m3_2_assembly.py:750` from `"M3-2_Assembly.step"` to e.g. `"M3-2_Assembly_cadquery.step"`.
3. **Butt-joint splice plate** (deferred this session) — 2 m X-beam made of two 1 m sections. Tall orientation handles deflection; plate is for joint integrity. Size and bolt spacing TBD next session. Internal C-channel: 26 × 36 mm interior (tall orientation); plate oriented width-vertical.
4. **Other remaining CAD cleanup from pre-session backlog**: NEMA23 hole alignment (verify 3 corners vs Nick's reference corner), bottom spacer/idler-bracket treatment, CF reinforcement rods (BOM vs STEP), Y-motor adapter plate refinement, limit switches.

## Content / marketing

- Reddit posts — drafted, not posted.
- Hackaday project page — not updated.
- LinkedIn article — live, monitoring engagement.

## Physical build

- Window: **2026-04-19 → 2026-04-26**. Real-world validation is the last gate.

---

## File location map

Two repos, both on GitHub under the `sunnyday-technologies` org:
- CADCLAW — active branch `feat/simultaneous-explode`
- M3-CRETE — active branch `main`

### Key CADCLAW files
- `cadclaw/render.py` — STEP→PNG→GIF pipeline, size gate at `GIF_SIZE_WARN_BYTES=5_000_000`
- `cadclaw/disassembly.py` — sequence generator
- `cadclaw/tolerance.py`, `inventory.py`, `interference.py` — validation modules
- `cadclaw_mcp/` — MCP server
- `examples/m3_crete/render_baseline.py` — render runner (points at authoritative M3-CRETE STEP)
- `docs/media/m3crete_*.gif` — published demo GIFs
- `tests/test_harness.py` — 52 passing tests

### Key M3-CRETE files
- `CAD/m3_2_assembly.py` — CADQuery assembly script (757 lines); loads `M3-2_AllC.step`, outputs to `CAD/M3-2_Assembly.step` (hard-coded, collision risk)
- `CAD/M3-2_AllC.step` — 24 MB source (inputs)
- `CAD/M3-2_Assembly.step` — **9.18 MB Fusion export, authoritative source of truth**
- `CAD/M3-2_Assembly_latest.step`, `CAD/M3-2_Assembly-latest.step` — intermediate Fusion exports (can be deleted once `.step` is confirmed complete)

---

## Release checklist (for next machine / future you)

When v0.5.0 is ready to publish:

1. `python -m unittest tests.test_harness` — all 52 must pass.
2. `git add -A && git commit -m "v0.5.0: <summary>"`
3. `git tag -a v0.5.0 -m "CADCLAW v0.5.0"`
4. `git push origin main --tags`
5. Create GitHub Release at `github.com/sunnyday-technologies/CADCLAW/releases/new`. Zenodo archives automatically.
6. Badge README with the v0.5.0 DOI (optional — concept DOI already covers it).
7. `python -m build && twine upload dist/*` for PyPI.

## How the next session should use this file

Read this first to restore context. Update or cross out items as they complete. Don't delete — history of what was done / deferred is useful. If Claude's per-machine user memory is missing, this file is authoritative.

In particular for this session's carry-forward:
- The CADQuery script `m3_2_assembly.py` is the thing that most needs attention next: catch it up to the Fusion design (X-axis rotation + X-gantry carriage) AND change its output path so it doesn't clobber Fusion exports.
- GIF size gate is set at 5 MB; if you generate a new GIF and see the warning, use `gif_colors=32`, `720x540`, `n_transition_frames=1` as the shrink recipe.
- Fusion exports require visibility audit — never trust a Fusion STEP export until part count has been checked against the assembly design.
