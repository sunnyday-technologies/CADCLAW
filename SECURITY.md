# Security reporting

CADCLAW is a Python tool that compiles declarative assembly specs with CadQuery
and runs verification gates over the result. Unlike the data-standard projects,
it **executes code and reads files you point it at**, and it **writes reports,
renders, and audit output** that are frequently published. Both directions
matter: what it runs, and what it emits.

## Reporting

Preferred: GitHub's private reporting — **Security → Report a vulnerability** on
<https://github.com/sunnyday-technologies/CADCLAW>.

If you cannot use GitHub, email **security@sunn3d.com**. Please do not open a
public issue for anything in the first three categories below.

## In scope

- Code execution reachable from an assembly spec, project config, or CAD file
  that a user would reasonably treat as data rather than as a program.
- Path traversal or writes outside the intended output directory.
- **Secrets or personal data leaking into generated output** — reports, renders,
  BOM exports, GIFs, or logs. The redaction layer exists specifically to prevent
  this, so a bypass of `redact_patterns`, or an unredacted credential appearing
  in published output, is a genuine vulnerability rather than a cosmetic bug.
- The `email_allowlist` suppressing an address it should have flagged, or
  failing to suppress one it was configured to allow.
- An honesty-toolchain gate (doctor, publish-audit, claim-audit) reporting a
  pass it did not earn. These gates are used to make public claims; a gate that
  can be made to lie is a trust defect, not a feature request.
- Credentials or personal data committed to this repository, including in test
  fixtures.

## Out of scope

- A verification gate producing a false positive or a debatable severity on
  legitimate geometry. That is a normal issue.
- Vulnerabilities in CadQuery, OCCT, or other dependencies. Report upstream;
  tell us too if CADCLAW's usage makes the impact worse.
- Running CADCLAW on deliberately hostile input in an environment where you
  already accept arbitrary code execution.

## Response

We aim to acknowledge within five working days. Where a fix changes gate
behaviour, the changelog states what previously passed and no longer does, so
anyone relying on an earlier audit can re-run it.

## Maintainer publication boundary

Maintainers should install and use the local Git-object and pull-request
metadata checks described in [docs/prepublication-gate.md](docs/prepublication-gate.md).
The GitHub workflow is explicitly a post-publication backstop, not proof that
first exposure was prevented.
