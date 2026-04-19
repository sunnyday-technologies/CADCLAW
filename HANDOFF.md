# CADCLAW — Session Handoff

Last updated: 2026-04-19
Prior session transcript: `c--Users-Sunny-Projects-M3-CRETE/bd4a112a-305c-40e6-843e-f0c3952d67ee.jsonl` (local to prior machine, may not be accessible from a different computer — this file is the durable copy).

---

## State as of handoff (2026-04-19)

Three repos are live on GitHub + Zenodo with DOIs assigned:
- **M3-CRETE** — v2.6.0, 62 parts, 89 parts in assembly, 8.8 MB STEP
- **CADCLAW** — 7 modules, MCP server, 17 tests (this repo)
- **Open3DCP** — v1.5.0, 239 columns

Publications out: LinkedIn article live, blog post live, Reddit drafts ready.

---

## Remaining CADCLAW work (this repo)

1. **Tolerance stacking test** — needs a corrected chain definition. Math works, test input was wrong.
2. **Disassembly module** — radial explosion method needs cleanup.
3. **MCP server** — untested with an actual Claude Code connection. Needs a live round-trip.
4. **PyPI publishing** — `pip install cadclaw` not yet available.
5. **JOSS paper** — submit October 2026 (JOSS requires 6 months of public repo history; repo went public 2026-04-18, so earliest submission 2026-10-18).

## Remaining M3-CRETE CAD work (sister repo)

- **NEMA23 hole alignment** on corner brackets — your Fusion file has one correct, needs verification on the other 3.
- **Bottom spacer / idler brackets** — need the same Fusion treatment the corners got (currently parametric boxes, not Nick-designed).
- **CF reinforcement rods** — in BOM but not in STEP model.
- **Y-motor adapter plates** — in assembly but could use Fusion refinement.
- **Limit switches** — never addressed.

## Content / marketing

- Reddit posts — drafted, not posted.
- Hackaday project page — not updated.
- LinkedIn article — posted, monitoring engagement.

## Physical build

- Targeted for this week (2026-04-19 → 2026-04-26). Real-world validation.

---

## Recommended next actions (if unsure where to start)

Pick-order for CADCLAW work:
1. Tolerance stacking chain definition (concrete bug, known root cause).
2. MCP server live test (adjacent, no publishing infra needed).
3. Disassembly radial explosion cleanup.
4. PyPI publishing (blocks `pip install` adoption).
5. JOSS paper (time-gated until Oct 2026 regardless).

## How the next session should use this file

- Read this file first to restore context.
- Update / cross out items as you complete them; don't delete — history is useful.
- If Claude's per-machine user memory is missing (different computer), this file is the authoritative carry-over.
