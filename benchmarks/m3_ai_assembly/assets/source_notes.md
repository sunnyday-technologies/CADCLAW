# M3 Benchmark Asset Source Notes

Status: the text scaffold (`package_testkit.py`) bundles no binary STEP, BOM, or
native CAD assets. Two binary asset classes are version-controlled in the repo and
shipped only in the runnable blind kit (not the text scaffold): the
OpenBuilds-derived kit STEPs, and the target **reference images** described below.

The local M3-CRETE proving workflow uses authored CAD assets from the adjacent
M3-CRETE working tree. Those files are suitable for local development but
should not be redistributed in a public test kit until license, source, and
redistribution review is complete.

Reference images (bundled, redistributable):

- `benchmarks/m3_ai_assembly/assets/reference/reference_{overview,front,top,side}.png`
- Sunnyday-authored renders of the M3 target, generated reproducibly by
  `benchmarks/m3_ai_assembly/scripts/make_reference_images.py` from the canonical
  assembly using CADCLAW's own renderer.
- They show the target's *arrangement* only — no dimensions, no coordinates, no
  spec, and no redistributed OpenBuilds source geometry — so they stay inside the
  benchmark fairness wall (a picture of the goal, like a human builder gets).
- Shipped in the blind kit so a driver can compare its build against the target;
  excluded from the text-only scaffold.

Current minimal asset allowlist:

- `examples/m3_crete/m3_testkit_assets.yaml`

Primary upstream source to cite for OpenBuilds-derived STEP assets:

- OpenBuilds STEP Parts Library:
  `https://builds.openbuilds.com/projectresources/step-parts-library.162/`

Packaging rule:

- Include only declared, redistributable files.
- Record SHA-256 checksums for every included binary or reference asset.
- Keep private procurement data, credentials, order records, and local native
  CAD exports out of the package.
