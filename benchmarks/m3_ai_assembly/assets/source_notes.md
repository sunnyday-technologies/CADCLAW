# M3 Benchmark Asset Source Notes

Status: no binary STEP, image, BOM, or native CAD assets are bundled in this
repository benchmark scaffold.

The local M3-CRETE proving workflow uses authored CAD assets from the adjacent
M3-CRETE working tree. Those files are suitable for local development but
should not be redistributed in a public test kit until license, source, and
redistribution review is complete.

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
