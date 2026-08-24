# Changelog

All notable changes to CADCLAW are documented here.

This project uses `MAJOR.MINOR.PATCH`. While CADCLAW is pre-1.0, breaking
changes bump MINOR and are called out explicitly under **Changed**.

## [Unreleased]

### Added

- **Third-party licence attribution.** README's License section now carries the
  notice required by the Open CASCADE Exception ("makes use of, and is based on,
  facilities provided by the Open CASCADE Technology software") plus a full
  component/role/licence table for the dependency chain. The site footer carries
  the same notice. CADCLAW's own MIT grant is unchanged: the wheel and sdist
  contain no compiled libraries and redistribute no third-party code — OCCT
  (LGPL-2.1 with the Open CASCADE Exception) and CasADi (LGPL-3.0-or-later)
  reach your environment from PyPI via your own package manager.

### Changed

- **`cadquery-ocp>=7.8` is now a declared dependency.** CADCLAW imports `OCP`
  directly (`STEPCAFControl`, `BRepAlgoAPI`, `BRepGProp`, `BRepAdaptor`,
  `XCAFDoc`, and others), not only through CadQuery's public API, so the
  dependency is now stated rather than relied on transitively. The floor is
  deliberately loose: CadQuery 2.7 pins `cadquery-ocp>=7.8.1,<7.9`, and the two
  constraints intersect instead of fighting when CadQuery moves to a newer OCP.

## [0.10.0] — 2026-07-29

The assembly half of CADCLAW becomes reachable from an AI assistant, and the
project's canonical description is corrected to match what the tool actually
does.

### Added

- **Six MCP assembly tools**, taking the server from 17 tools to 23:
  `assemble_validate_spec`, `assemble_build`, `assemble_check_round`,
  `assemble_inspect_component`, `assemble_render_views`, and
  `assemble_render_sequence`. An MCP-compatible assistant can now build an
  assembly, not only check one.
- **Inline visual review.** Render-producing MCP tools return their PNGs as MCP
  image content, so the calling model can look at the assembly it just built
  instead of trusting a path string. Toggle per call with `return_images`.
  Inline images are capped by `MAX_INLINE_IMAGES` (6) and `MAX_IMAGE_BYTES`
  (4 MB) so a long sequence cannot flood the client context; when the cap
  truncates, the report says how many views were omitted. Every render is still
  written to disk, which is the human-auditable traceability artifact for the
  round.
- `cadclaw.assembly_compiler.validate_assembly_spec(spec_path, release=False)`
  is now a public library function returning a `Report`.
- `tests/test_relative_placement.py` — 11 tests covering the constraint
  placement resolver: both lock modes, datum-chain composition, topological
  ordering, and every failure finding (cycle, missing ref, missing parent
  frame, missing child frame). This code previously had no test coverage.
- `tests/test_mcp_assembly.py` — 19 tests covering the assembly tools, the
  image-return path, the inline budget, and error handling.
- A test asserting every advertised MCP tool schema has a registered handler.
- **A shipped, tested example of constraint placement**:
  `examples/relative_placement/`. Three parts, one datum, and both `lock`
  modes, with authored stand-in STEP parts and connector metadata. Until now
  `place_relative_to` appeared in **zero** shipped specs, so the flagship
  placement capability was documented but never demonstrated.
- `docs/assembly-spec.md` — field-by-field reference for `assembly_spec.v0.1`,
  including both lock modes, the datum chain, the resolver's failure findings,
  `protected_paths`, and `not_built_yet`.
- `tests/test_example_relative_placement.py` — 8 tests pinning the example's
  solved coordinates to the values the docs publish, and proving the chain
  propagates: moving the datum carries all three parts, and thickening the
  plate pushes the gantry out without re-typing a coordinate.
- This changelog.

### Changed

- **Canonical description.** CADCLAW identifies as an *assembly and validation*
  framework, not a validation framework alone. The citation title is now
  "CADCLAW: Automated assembly and validation framework for STEP-based CAD".
  Updated across README, `CITATION.cff`, `.zenodo.json`, `pyproject.toml`,
  `docs/llms.txt`, the MCP manifest, the site JSON-LD, and `AGENTS.md`.
- `AGENTS.md` now states the distinction explicitly: **assembling is in scope,
  authoring is not.** CADCLAW places parts the user drew; it never generates
  geometry. This refines the existing anti-generation rule rather than relaxing
  it.
- `cadclaw assemble validate-spec` delegates to the new shared
  `validate_assembly_spec()` instead of carrying its own copy of the logic. CLI
  output and exit codes are unchanged.

### Security

- **Answer-key placement was redacted from the public M3 example.**
  `examples/m3_crete/m3_reference_assembly.yaml` is now a spec-shape example
  rather than a placement one: the per-instance `transform` blocks are removed,
  along with the pose assertions in `tests/test_assembly_spec.py` that pinned
  the same values. The part roster, roles, and counts stay, since M3-CRETE is
  open hardware and its structure is published by design. The complete
  reference assembly is distributed through the gated dataset.
- **Added a key-guard**, ported from MARB: `scripts/check_no_answer_keys.sh`
  (the single source of truth for blocked patterns), a `pre-push` hook, and the
  `key-guard` CI workflow as the server-side backstop. It blocks key-shaped
  paths *and* content-checks that solved poses have not returned to the
  redacted example. Verified to fire on both violation types.
- **`_private/` is now ignored by the committed `.gitignore`.** It was
  protected only by `.git/info/exclude`, which is local to one clone and never
  travels — a fresh clone, CI runner, or agent sandbox had no protection.
- A regression test asserts the redaction holds, so poses cannot silently
  return to the example.

### Fixed

- Documentation cited the Zenodo *version* DOI (`10.5281/zenodo.19647391`) in
  several places. All references now use the *concept* DOI
  (`10.5281/zenodo.19647390`), which resolves to the latest version.
- The published architecture description still referred to `cadharness` as the
  package holding the gates. It has been a deprecated compatibility shim since
  0.8.0; the package is `cadclaw`.

### Notes

- No breaking changes. The 17 pre-existing MCP tools, the CLI surface, and the
  `cadharness` shim are untouched.
- The Zenodo record keeps the old title until this version is deposited, since
  the DOI metadata updates only on a new release.

## [0.9.0] — 2026-06-05

Structural FEA gate (`cadclaw.fea`, PyNite backend, optional `cadclaw[fea]`
extra), orientation/face-mate gate, color/material check, floating-part
detection, and the relative-placement resolver. Reliability: cp1252 stdout fix
for `bom-audit` on Windows. Accuracy: the kinematics gate was relabeled
"Structural" to reflect that it does static load math, not motion sweeps, and
unimplemented racking / GT2-tooth-skip claims were removed.

## [0.8.0] — 2026-04-29

`cadharness` renamed to `cadclaw`, with a compatibility shim that aliases every
`cadclaw.<sub>` submodule under `cadharness.<sub>` and emits one
`DeprecationWarning` per process. The PyPI package name is unchanged. The shim
is removed in 1.0.

## [0.7.0] and earlier

See the [GitHub releases](https://github.com/sunnyday-technologies/CADCLAW/releases)
for 0.7.0, 0.6.1, 0.6.0, and earlier. Highlights: the Findings/Severity/Report
model, the YAML rule loader, the BOM-vs-CAD audit, the honesty toolchain
(`doctor`, `publish-audit`, `claim-audit`), the console script, and the initial
MCP server.
