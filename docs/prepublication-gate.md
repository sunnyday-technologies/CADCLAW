# Pre-publication confidentiality gate

CADCLAW maintainers use a local Git-object gate before a ref or pull request is
published. The gate is preventive only when the tracked hook and PR wrapper are
used locally. `.github/workflows/key-guard.yml` repeats the public checks after
GitHub receives an event; that workflow is a detection backstop and cannot undo
first exposure.

## Policy layers

`policy/prepublication.v1.json` is the versioned, generic public policy. Rules
have stable IDs, explicit surfaces, and deny or narrowly scoped allow behavior.
Unknown fields, duplicate IDs, unsupported schemas or surfaces, invalid regular
expressions, missing required rules, and invalid limits are errors rather than
partial passes.

Organization-specific exact terms belong only in
`.prepublication-policy.local.json`. That path is ignored and is required by
the local hook and PR wrapper. It is intentionally absent from CI and must never
be added to Git. `policy/prepublication.local.example.json` documents the
overlay shape using a synthetic placeholder; it is not an operational overlay.

Install from an already-formed private overlay:

```text
python scripts/manage_prepublication_hooks.py install --overlay-source <private-policy-file>
```

An existing Python source that contains exactly one top-level denylist tuple or
list of string literals can be converted mechanically without printing its
values:

```text
python scripts/manage_prepublication_hooks.py install --import-literal-source <private-source-file>
```

A private workspace path can instead seed exact full-path, normalized-path, and
leaf-name literals without committing those values:

```text
python scripts/manage_prepublication_hooks.py install --protect-path <private-workspace-path>
```

The installer refuses to replace a different `core.hooksPath`. It stores the
current Python executable in repository-local Git config, installs
`scripts/hooks`, verifies the hook's tracked executable mode and LF bytes,
checks that the local overlay is ignored, and validates both policy layers.
Verify an existing installation without changing it:

```text
python scripts/manage_prepublication_hooks.py verify
```

The same value-free policy can be applied to the staged diff before committing:

```text
python scripts/prepublication_gate.py index
```

## Checked before push

The hook reads all pre-push update records before invoking either checker. The
generic scanner runs first and checks:

- each non-deletion destination ref name;
- the complete subject and body of every newly reachable commit, including
  commits reached through merges;
- every changed source and destination filename in each outgoing commit,
  including files added and removed before the pushed tip;
- each outgoing changed blob by reading its Git object, never its working-tree
  or index copy;
- annotated-tag messages and direct blob refs;
- every tracked workflow filename, blob, and Git mode/type at each outgoing
  tip, plus changed workflow metadata within the outgoing history.

Git plumbing uses NUL-delimited filenames. Blob decoding preserves invalid
bytes for matching and checks normalized UTF-8, UTF-16, and UTF-32 text views.
A blob over the public policy limit is blocked rather than
skipped, and unreadable or malformed required Git objects are errors. Deletion
updates are structurally validated and allowed because they publish no new
object and may be needed to remove an unsafe ref. Existing-ref updates use the
exact advertised destination object as their boundary. New refs conservatively
scan their complete reachable history instead of trusting local remote-tracking
refs.

After the generic scanner passes, the separate MARB guard examines exact commit
trees and committed blobs for its existing repository-specific boundary. It
also reports only stable surface and pattern identifiers with ordinals.

## Pull requests

Create public pull requests through:

```text
python scripts/create_public_pr.py --title <title> --body-file <body-file> --base main
```

The wrapper requires the private overlay and scans the current branch, optional
base/head names, title, and complete body before invoking `gh pr create`. It
captures GitHub CLI diagnostics so rejected metadata is never reproduced by the
wrapper. Direct use of `gh`, the GitHub website, `--no-verify`, or a clone where
hooks were never installed bypasses local prevention.

## Output and boundaries

Blocked and error diagnostics contain only a status, safe surface identifier,
stable pattern ID, and ordinal. They do not contain matched text, filenames,
refs, commit text, pull-request text, object IDs, paths, Git stderr, exception
text, or policy values.

The gate does not scan uncommitted working-tree or index-only content because
those bytes are not transmitted by `git push`. It does not prove that generic
patterns cover every confidential value, replace GitHub secret scanning, change
repository visibility or branch rules, remove already-published history, or
authorize a merge. Updating the private overlay is an operational policy
decision; an approval cannot override a confidentiality block.
