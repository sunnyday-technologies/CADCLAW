# CADCLAW — Session Handoff

Last updated: 2026-04-20 (mid-session snapshot; session ongoing)
Authoritative carry-over across machines. Session transcripts live at `~/.claude/projects/y--SunnydayTech-CADCLAW/*.jsonl` on the machine where they were recorded; this file is the durable copy that travels with `git pull`.

**Important**: the user is retaining session transcripts, this file, and memory files as IP/claims evidence for tool development, publishing, and best-practices documentation. Do not delete anything. When in doubt, save.

---

## Current version

**v0.5.0** — bundled release on 2026-04-19. Everything below is post-release work.

---

## What's in v0.5.0 (shipped)

- Tolerance stacking (9 tests, hand-calculated answers)
- Disassembly: `export_radial()` method, O(n²) lookup bug fixed in `export_exploded()`
- `cadharness/render.py` module: STEP → PNG → animated GIF via offscreen VTK + Pillow
- MCP server: `disassembly_sequence`, `export_exploded_view` tools; stdout-to-stderr fix
- 52 passing tests (up from 17); VTK + GIF stitching integration tests included
- `pyproject.toml` fixes, Pillow dep, `cadclaw-mcp` console script

Run tests: `python -m unittest tests.test_harness -v` — ~30 s, all 52 must pass.

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
- **Dropped `cadharness/wheel_carriage.py`** — written, smoke-tested, then removed. User's insight reframed the problem: buried-wheel was passing validation because `skip_labels={'belt','vwheel'}` in the example config was suppressing the very check that should have caught it. Minimal fix was to drop `'vwheel'` from [examples/m3_crete/check.py:38](examples/m3_crete/check.py#L38). No new module.

### Key findings

- **Claude Code `Read` tool image limit ≈ 5 MB** (documented API cap). Empirically: 4.76 MB sometimes accepted, 5.05 MB+ rejected. Gate at 5 MB is operationally safe with `optimize=True` on GIFs.
- **GIF quantization artifact on flat-color parts** — default Pillow `convert("P", palette=Image.ADAPTIVE)` uses Floyd-Steinberg dithering, which produces visible speckle on nominally-flat colored surfaces (Sunnyday green became "grey with green speckles"). Fix: pass `dither=Image.NONE`. Costs some gradient smoothness, wins flat color fidelity — right trade for CAD renders with solid per-part colors.
- **Interference-check blanket skips are anti-patterns.** `skip_labels={'belt','vwheel'}` was suppressing legitimate mis-placement detection. The correct posture: reserve skips for labels with *geometric* justification (belts wrap pulleys, creating unavoidable tooth-mesh overlap). Wheels correctly placed in V-grooves overlap the groove *void* (no solid material), not the extrusion — so they don't need skipping in the first place.
- **Fusion STEP exports silently drop invisible parts.** The user hit this twice in this session — a part that was toggled invisible in Fusion's browser panel was not included in the STEP export, with no warning. Compensate by: (a) preferring CADQuery-regen STEPs for reproducibility, (b) sanity-check part counts after each Fusion export, (c) flag any Fusion export that is *smaller* than a prior version despite added geometry.
- **X-axis flexure resolved by extrusion rotation alone** — the 2 m X-beam (two 1 m sections butt-joined) only needs to be rotated to tall orientation (80 mm vertical). Bare-beam deflection at 5 kg mid-span = 0.225 mm (target ≤ 0.5 mm). No internal plate reinforcement needed for deflection control per the 2026-04-20 calc. Joint-integrity splice plate is a separate concern, deferred.
- **Directly writing a CADQuery regen to `CAD/M3-2_Assembly.step` will clobber any Fusion-exported STEP at that path.** `m3_2_assembly.py` hard-codes its output path. **Fix before next CADQuery regen:** change the output path to a distinct name (e.g. `M3-2_Assembly_cadquery.step`) so Fusion and CADQuery outputs never collide.

### M3-CRETE state — two-sided divergence (as of 2026-04-20)

- **Fusion side** (`Y:/SunnydayTech/M3-CRETE/CAD/M3-2_Assembly.step`, 9.18 MB, 12:48 on 2026-04-20) — latest authoritative source:
  - Has: X-axis tall rotation, X-gantry carriage (plate + V-wheels), top T-plate connector, all brackets
  - This is the single source of truth for GIF rendering as of end-of-session
- **CADQuery side** (`Y:/SunnydayTech/M3-CRETE/CAD/m3_2_assembly.py`, 757 lines) — stale relative to Fusion:
  - Missing: X-axis tall rotation, X-gantry carriage
  - Has: 3D-printed green T-brackets at mid-X spreader, combined motor-mount plates, bottom spacer plates, Y-motor adapter plates, correct L-brackets
  - **Next-session work**: rotate X-rail template to tall, add X-gantry carriage by replicating Z/Y carriage geometry pattern (explicit user ask: "copy the same carriage we are using from the z- and y axes (we are replicating here intentionally)")

### Current in-flight

- Render `bzuwfkofy` — re-rendering both GIFs from the new 9.18 MB Fusion export (disassembly ~10 min, radial_spin ~15 s).
- HANDOFF.md update (this file) written mid-render.

### Uncommitted state at snapshot

**CADCLAW** (`Y:/SunnydayTech/CADCLAW`, branch `feat/simultaneous-explode`):
- `M cadharness/render.py` (5 MB size gate + `dither=Image.NONE`)
- `M docs/media/m3crete_radial_spin.gif` (4.08 MB clean re-render from Fusion full model)
- `D docs/media/m3crete_disassembly.gif` (dropped — radial-spin replaces it)
- `M examples/m3_crete/check.py` (dropped `vwheel` from interference skip list)
- `M README.md` (disassembly → radial-spin hero GIF reference)
- `M HANDOFF.md` (this update)
- `?? examples/m3_crete/render_baseline.py` (new render runner, radial-only)
- 2 unpushed commits ahead of origin from prior sessions (`9eaa3b2`, `6079c61`)

**M3-CRETE** (`Y:/SunnydayTech/M3-CRETE`, branch `main`):
- `M CAD/M3-2_Assembly.step` (user's new Fusion export, 9.18 MB, authoritative)
- Untracked blog/docs images — pre-existing, not from this session

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

See also: auto-memory at `C:/Users/Sunny/.claude/projects/y--SunnydayTech-CADCLAW/memory/reference_multi_repo_file_layout.md`

- CADCLAW repo: `Y:/SunnydayTech/CADCLAW` (branch `feat/simultaneous-explode`)
- M3-CRETE (authored): `Y:/SunnydayTech/M3-CRETE` (branch `main`)
- M3-CRETE (local clone): `C:/Users/Sunny/Projects/M3-CRETE` (branch `main`)
- Remotes: `github.com/sunnyday-technologies/CADCLAW`, `github.com/sunnyday-technologies/M3-CRETE`

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
