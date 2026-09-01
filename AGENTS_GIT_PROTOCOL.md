# Shared git protocol — read before editing this repository

More than one AI agent edits this repository from more than one working copy
(Codex and Claude Code, in separate clones). **GitHub is the shared memory.** A
local clone tells you nothing about what the other agent did. Every defect found
in the 2026-08-21 publishing audit traced back to this one habit gap.

Seven rules. They take about a minute.

### 1. Fetch before you work

```bash
git fetch origin && git status -sb
```

If you are behind, reconcile before editing. On 2026-08-21 both repositories had
local `main` sitting on an abandoned pre-rewrite history for weeks, and neither
agent noticed because neither fetched.

### 2. Commit what you validate, in the same session

The single largest failure mode here is **validated work left uncommitted**. The
2026-08-11 repair passed every gate and then sat uncommitted in two working trees
for ten days. Nobody else could see it, the live sites stayed wrong, and the next
agent had no way to know it existed. If you validated it, commit it. If it is not
ready to commit, say so explicitly in your handoff.

### 3. Never force-push, and never push local `main` blind

Both remotes were rewritten to scrub `nick@sunn3d.com` to `dev@sunn3d.com`. Any
clone taken before that rewrite has an unrelated history whose trees are identical
but whose SHAs all differ. Pushing it would replace the remote and delete commits
that exist nowhere else.

If `git merge-base HEAD origin/main` exits non-zero, you are on an orphaned
history. Do not push. Reset to `origin/main` and replay your work on top:

```bash
git branch backup/pre-reset-$(date +%Y%m%d)     # keep the old history
git stash push -u                                # if you have uncommitted work
git reset --hard origin/main
git stash pop
```

### 4. Commit as `Sunnyday Technologies <dev@sunn3d.com>`

`nick@sunn3d.com` was deliberately scrubbed from both histories. Committing under
it reintroduces what the rewrite removed.

### 5. The site source must be committed, not just built

`docs/` here, `publishing/` in MARB, is the Cloudflare Pages source. CI builds from
a clean checkout of an exact commit, so anything untracked simply does not exist at
deploy time. `docs/_headers` was untracked for months, which meant every CI build
would have failed and the security headers could never have shipped.

### 6. Prove it from a clean clone before you call it done

The working tree lies. It holds files git ignores, files git has never seen, and
files with line endings that differ from a fresh checkout. Test what CI sees:

```bash
git clone --no-hardlinks --single-branch --branch main . /tmp/clean
cd /tmp/clean && ./scripts/build-site.ps1
```

This one check caught three separate release-blocking defects on 2026-08-21: a
missing `_headers`, an unpinned line-ending policy that broke the build on every
Windows clone, and a rights assertion that required a file which must never be in
git.

### 7. Verify the local publication gate before pushing

The tracked hook is preventive only when it is installed and its required
ignored local policy overlay is present. Run:

```text
python scripts/manage_prepublication_hooks.py verify
```

Create pull requests through `scripts/create_public_pr.py` so title and body are
checked before GitHub receives them. The GitHub workflow is a post-publication
backstop; it cannot prevent first exposure.

---

### Also: never run a hard checkout with uncommitted work in the tree

`git reset --hard`, `git checkout -- .`, and `git add --renormalize` all re-read or
overwrite the working tree and will silently destroy uncommitted edits. Commit
first, then renormalize. This was learned twice in one session.

---

Full reasoning and evidence:
`Publications/agentic-web/evidence/CADCLAW_AUDIT_2026-08-21.md`
