# CADCLAW — Session Handoff

Last updated: 2026-04-19
Authoritative carry-over across machines. Prior session transcript lived at `~/.claude/projects/c--Users-Sunny-Projects-M3-CRETE/bd4a112a-*.jsonl` on one specific machine; this file is the durable copy that travels with `git pull`.

---

## Current version

**v0.5.0** — bundled release on 2026-04-19 with everything below.

---

## What's in v0.5.0

- **Tolerance stacking** — 9 new tests with hand-calculated answers verifying worst-case, RSS, Monte Carlo, Cpk, contributor decomposition, direction-flag equivalence.
- **Disassembly** — new `export_radial()` method (outward-from-centroid explosion, scales with distance). O(n²) lookup bug fixed in `export_exploded()`.
- **Render (new module)** — `cadharness/render.py`: STEP → PNG → animated GIF via offscreen VTK + Pillow. One-call helper `make_disassembly_gif()` closes the loop from assembly to shareable visual.
- **MCP server** — 2 new tools: `disassembly_sequence`, `export_exploded_view` (radial or axial). Critical bug fixed: tool stdout was corrupting the JSON-RPC stream; server now redirects tool stdout to stderr via `contextlib.redirect_stdout`.
- **Test suite** — 52 passing tests, up from 17. Coverage: every public function in every module, subprocess-based MCP round-trip tests, real VTK rendering, real GIF stitching.
- **pyproject.toml** — fixed broken `build-backend`, bumped to 0.5.0, added Pillow dep, added `cadclaw-mcp` console script, included `cadclaw_mcp/` in package find.

## How to run the full test suite

```bash
cd CADCLAW
python -m unittest tests.test_harness -v
```

All 52 tests must pass. Takes ~30s end-to-end. Requires `cadquery>=2.7` and `Pillow>=10` (both pulled in by `pip install -e .`).

## Remaining CADCLAW work

1. **M3-CRETE demo GIF** — pipeline is tested and shipped, but the production-size GIF (89 parts × 3 transitions = 268 frames × ~21 MB STEP each) pegs memory and takes ~20 min end-to-end. For a shareable demo, run `python examples/m3_crete/make_gif.py path/to/M3-2_Assembly.step docs/media/m3crete_disassembly.gif` overnight or with `n_transition_frames=1, width=480` for a quick version. Not a release blocker.
2. **PyPI publishing** — after v0.5.0 is tagged and the GitHub Release triggers Zenodo, run `python -m build && twine upload dist/*`. `pyproject.toml` is already audited.
3. **JOSS paper** — time-gated to **2026-10-18** (6 months after the first public commit on 2026-04-18). Draft can start anytime; submission must wait.

## Remaining M3-CRETE CAD work (sister repo)

- NEMA23 hole alignment on corner brackets (Fusion has 1 correct, verify 3).
- Bottom spacer/idler brackets — Fusion treatment like corners.
- CF reinforcement rods — in BOM, missing from STEP.
- Y-motor adapter plates — Fusion refinement.
- Limit switches — never addressed.

## Content / marketing

- Reddit posts — drafted, not posted.
- Hackaday project page — not updated.
- LinkedIn article — live, monitoring engagement.

## Physical build

- Window: **2026-04-19 → 2026-04-26**. Real-world validation is the last gate.

---

## Release checklist (for next machine / future you)

When v0.5.0 is ready to publish:

1. `python -m unittest tests.test_harness` — all 52 must pass.
2. `git add -A && git commit -m "v0.5.0: <summary>"`
3. `git tag -a v0.5.0 -m "CADCLAW v0.5.0"`
4. `git push origin main --tags`
5. Create GitHub Release at `github.com/sunnyday-technologies/CADCLAW/releases/new` with tag v0.5.0. Zenodo archives automatically → new version DOI appears within ~5 min.
6. Badge README with the v0.5.0 DOI (optional — concept DOI already covers it).
7. `python -m build && twine upload dist/*` for PyPI.

## How the next session should use this file

Read this first to restore context. Update or cross out items as they complete. Don't delete — history of what was done / deferred is useful. If Claude's per-machine user memory is missing, this file is authoritative.
