# CADCLAW — Session Handoff

Last updated: 2026-04-25

Authoritative cross-machine carry-over for post-release work. Travels with `git pull`.

---

## Current version

**v0.6.0** — honest core release prepared on 2026-04-25.

### What's in v0.6.0

- **Findings / Severity / Report model** (`cadharness/findings.py`) — single shape every gate emits; `pass` / `warn` / `fail` rollup; JSON-safe `evidence`; locked `schema_version: "0.6"`.
- **YAML rule loader** (`cadharness/rules.py`, pydantic v2) at `cadclaw.yaml`. Bbox sigs are 3-element lists, every section optional.
- **BOM-vs-CAD audit** (`cadharness/bom_audit.py` + `bom_loader.py`) — headline gate. Catches qty / mfg_type / unit mismatches, required-or-forbidden text terms, and CAD-side count drift. Privacy enforced at the serializer (`vendors`, `sku`, `unit_cost`, `_*` always dropped).
- **Doctor** (`cadharness/doctor.py`) — Python / venv / deps / MCP / repo signals. Catches the broken-pyvenv case where `pyvenv.cfg home =` points at a missing interpreter.
- **Publish-audit** (`cadharness/publish_audit.py`) — three-state (untracked / staged / committed) file model + regex content scan with email allowlist. Never echoes matched secret values.
- **Claim-audit** (`cadharness/claim_audit.py`) — forbidden absolutes, untagged numeric claims, user-supplied stale terms, plus two folded source-regex rules (protected output paths, silent fallback geometry) over `.py` files.
- **`cadclaw` console script** (`cadclaw_cli/`) — argparse stdlib. Subcommands: `doctor`, `bom-audit`, `parity`, `claim-audit`, `publish-audit`, `inventory`, `harness`. Exit codes 0/1/2/3.
- **Three reporters** (`cadharness/reporters/`) — text (CLI, ANSI auto), markdown (PR-comment ready), json (versioned, MCP/CI).
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

- **HIGH-1 — BOM loader accepts `parts:` synonym** ([bom_loader.py](cadharness/bom_loader.py))
  Hardware BOMs commonly use `{"version": "...", "parts": [...]}` (M3-CRETE
  does). The loader now accepts `items` and `parts` interchangeably; `items`
  wins on conflict. Other top-level keys (`version`, `generated`, `source`,
  `notes`) are ignored as author metadata. Released the M3-CRETE shim.

- **LOW-8 — `cadclaw harness` `duration_ms` always 0** ([cadclaw_cli/main.py](cadclaw_cli/main.py))
  `_cmd_harness` built `aggregate = Report(...)` with the default
  `duration_ms=0.0` and never set it. Now wraps the runner in a
  `time.time()` and sets `aggregate.duration_ms` before emit.

- **`publish_audit.blob_size_warn_bytes` default 5 MB → 20 MB** ([rules.py:102](cadharness/rules.py#L102))
  5 MB triggered on M3-CRETE's 9.2 MB STEP and would on most real
  assemblies. Still configurable per-project; set `0` to disable.

Tests added: 19 in `tests/test_bom_loader.py` (parts-key acceptance,
reject-unknown-key regression, privacy projection lock-in,
exemption logic), 1 in `tests/test_cli.py` (timing assertion).
Total: **176 passing tests**.

### v0.7 candidates (driven by M3-CRETE field test, 2026-04-26)

Deferred from v0.6 to land as a coherent v0.7 polish release. Field-test
report at `D:/SunnydayTech/M3-CRETE/cadclaw-v0.6-field-test-2026-04-26.md`.

- **MED-2 — negation-aware `forbidden_terms`** — substring match catches
  "not the primary stiffness" as if it were "primary stiffness". Cheap
  win: look back ~30 chars for negation tokens (`not`, `no`, `never`,
  `do not`, etc.) before flagging.
- **MED-3 — license / comment / negation-aware `claim_audit`** — same
  root cause as MED-2 but for docs. Skip lines starting with comment
  markers (`#`, `//`, `<!--`); auto-exempt `LICENSE` / `NOTICE` /
  `COPYING` / `AUTHORS`. The "OpenBuilds in CC BY-SA attribution" case
  is high-priority — flagging it could lead to a license violation if a
  user follows the suggested fix.
- **MED-4 — `forbidden_absolutes` move out of defaults** — "validated"
  is too aggressive as a default; flags legitimate third-party-product
  mentions. Make the default list empty and let projects opt in via
  `forbidden_absolutes_extra`.
- **MED-5 — aggregate `cad.count_mismatch` per label** — when 3 BOM
  rules expect the same label, emit one finding summing the rules,
  not three separate ones.
- **MED-6 — `expected_qty` conflates design count with order count**
  — surfaced post-test (twin session) on M3-CRETE id=67 (cbeam): BOM
  qty=18 = 17 design + 1 spare; CAD has 17. All three v0.6 workarounds
  failed (rule expected_qty=17 fails BOM check; =18 fails CAD check;
  omitting it falls back to BOM qty). Add `expected_design_qty` (vs
  CAD) and `expected_order_qty` (vs BOM) as separate rule fields, plus
  `spare_qty` as syntactic sugar (`order = design + spare`). Ship (1)
  + (2) together; common procurement pattern. No v0.6 escape hatch
  exists short of moving the label to `ignore_labels` (kills all
  validation for that label).
- **LOW-6 — `bom.unmapped_item` noise reduction** — 51/64 warns on a
  64-item BOM. Demote to `info` severity by default, AND/OR honor an
  optional `bom_audit.exempt_categories` field that maps to BOM items'
  existing `category` field.
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

## Previously: v0.5.0 (2026-04-19)

- Tolerance stacking (9 tests, hand-calculated answers)
- Disassembly: `export_radial()` method, O(n²) lookup bug fixed in `export_exploded()`
- `cadharness/render.py` module: STEP → PNG → animated GIF via offscreen VTK + Pillow
- MCP server: `disassembly_sequence`, `export_exploded_view` tools; stdout-to-stderr fix
- 52 passing tests (up from 17); VTK + GIF stitching integration tests included
- `pyproject.toml` fixes, Pillow dep, `cadclaw-mcp` console script

---

## Post-release work (this session — 2026-04-20)

### Done

- **Abandoned `feat/cable-drag-chains`** (Y:/M3-CRETE) — reverted regression of authored brackets + removed out-of-scope kinematic simulation. Branch deleted locally (never pushed). Stash `stash@{0}` kept as safety net.
- **Dropped `m3crete_radial_dragchains.gif`** from CADCLAW docs (was untracked; just `rm`'d).
- **Added GIF output size gate** to `cadharness/render.py`:
  - `GIF_SIZE_WARN_BYTES = 5_000_000` (matches Claude API vision cap directly)
  - `_warn_if_gif_too_large()` fires stderr warning at both save paths (`render_frames_to_gif`, `render_radial_explode_gif`)
  - Initial threshold was 4.5 MB; raised to 5.0 MB after empirical evidence showed 4.76 MB files worked in chat
- **Added** `examples/m3_crete/render_baseline.py` — repeatable runner for both GIF types, points at the current authoritative M3-CRETE STEP.
- **Dropped sequential-disassembly GIF** — only the radial explode + 360 spin is published now; it communicates the same thing in 15 s of render vs 10 min.
- **Re-rendered `docs/media/m3crete_radial_spin.gif`** from the 9.18 MB Fusion full-model export — 4.08 MB, 76 frames, 720×540, `gif_colors=48`, `dither=Image.NONE` (flat colors, no speckle).
- **Dither fix in `render.py`** — switched `convert("P", ...)` to `dither=Image.NONE` at both save paths. This eliminates the "grey-with-green-speckles" quantization artifact on the Sunnyday-green printed parts. Default adaptive-palette dither was Floyd-Steinberg and mixed non-green pixels into flat-green regions.
- **STEP color import (AP242) in `render.py`** — new `_extract_step_colors()` helper uses `STEPCAFControl_Reader` + `XCAFDoc_ColorTool` to pull per-shape RGB from the STEP's AP242 color metadata. `render_step_to_png` and `render_radial_explode_gif` now take `use_step_colors: bool = True` (default on). Priority: STEP color → label map → default. Verified against the M3-CRETE Fusion export: 85 colored shapes extracted cleanly (V-wheels and pulleys come through green as Fusion tagged them; motors black; plates dark).
- **Dropped `cadharness/wheel_carriage.py`** — written, smoke-tested, then removed. User's insight reframed the problem: buried-wheel was passing validation because `skip_labels={'belt','vwheel'}` in the example config was suppressing the very check that should have caught it. Minimal fix was to drop `'vwheel'` from [examples/m3_crete/check.py:38](examples/m3_crete/check.py#L38). No new module.

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
- `cadharness/render.py` (5 MB size gate + `dither=Image.NONE`)
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
- `cadharness/render.py` — STEP→PNG→GIF pipeline, size gate at `GIF_SIZE_WARN_BYTES=5_000_000`
- `cadharness/disassembly.py` — sequence generator
- `cadharness/tolerance.py`, `inventory.py`, `interference.py` — validation modules
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
