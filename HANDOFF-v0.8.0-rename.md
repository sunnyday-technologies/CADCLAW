# CADCLAW v0.8.0 — module rename handoff

**Date:** 2026-04-29
**Triggered by:** M3-CRETE field-test feedback ("`cadclaw` sounds way cooler than `cadharness`").
**Goal:** Rename the Python module from `cadharness/` to `cadclaw/` so `pip install cadclaw` lets you `import cadclaw` (today you have to `import cadharness`, which is confusing).
**Compatibility target:** Soft transition — existing users on `import cadharness` keep working with a `DeprecationWarning` until v1.0.

---

## Why this is a real version bump

It's a **breaking-but-shimmed** import change. The PyPI package name doesn't change; the import name does. Any third-party code that does `from cadharness.bom_audit import run_bom_audit` will get a deprecation warning and keep working, so users won't break — but the *symbol resolution* is technically different. That's a minor bump under semver-for-libraries. **v0.8.0** is the right tag.

It also makes a clean cut for **PyPI re-publish**. PyPI is currently stuck at v0.5.0 (per `pip index versions cadclaw`); v0.6, v0.7, v0.7.1 were never pushed. v0.8.0 with the rename + everything else accumulated is a clean drop for users to upgrade to.

---

## Concrete steps

### 1. Rename the package directory
```bash
cd D:/SunnydayTech/CADCLAW
git mv cadharness cadclaw
```
This preserves history per-file. Don't `rm -rf` and re-create.

### 2. Sweep imports
```bash
# Use ripgrep to find every reference
rg -l "cadharness" --type py --type md --type toml --type yaml
```
Expected hit categories:
- `cadclaw_cli/*.py` — internal imports
- `cadclaw_mcp/*.py` — internal imports
- `tests/*.py` — test imports
- `examples/*.py` — `init_rules.py`
- `pyproject.toml` — `[tool.setuptools.packages.find]` or explicit `packages` list
- `README.md`, `AGENTS.md`, `HANDOFF*.md` — docs that show import lines
- Any `__pycache__` — ignore, they regenerate

Replace strategy:
```bash
rg -l "cadharness" | xargs sed -i 's/from cadharness\./from cadclaw./g; s/import cadharness$/import cadclaw/g; s/cadharness\./cadclaw./g'
```
**Caveat:** the compat shim at `cadharness/__init__.py` (next step) intentionally keeps the literal `cadharness` string, so don't sed-replace inside that one file.

### 3. Add the compat shim

Create `cadharness/__init__.py` (a NEW directory; the old one was renamed to `cadclaw/`):
```python
"""Deprecated alias for `cadclaw`.

This shim exists so code written against v0.7 and earlier (`import cadharness`)
keeps working. New code should `import cadclaw` directly.

Removed in v1.0.
"""
import warnings as _warnings

_warnings.warn(
    "The `cadharness` module has been renamed to `cadclaw` in v0.8.0. "
    "Update your imports — `cadharness` will be removed in v1.0.",
    DeprecationWarning,
    stacklevel=2,
)

from cadclaw import *  # noqa: F401, F403, E402
from cadclaw import __version__  # noqa: F401, E402
```

Add to `pyproject.toml` packages list (or let `find` pick it up — verify with `pip install -e . && python -c "import cadharness; import cadclaw; print(cadclaw.__version__)"`).

### 4. Submodule re-exports (if `cadharness.bom_audit` etc. were public API)

If existing user code does `from cadharness.bom_audit import run_bom_audit`, the bare `from cadclaw import *` shim won't cover that. Two options:

**Option A** (recommended) — generate one-line re-export shims under `cadharness/`:
```bash
for sub in bom_audit publish_audit claim_audit doctor rules bom_loader findings reporters; do
  echo "from cadclaw.$sub import *  # noqa" > cadharness/$sub.py
done
```
Add the same `DeprecationWarning` to each, or just to the parent `__init__.py`.

**Option B** — rely on Python's lazy import system + a `__getattr__` hook in `cadharness/__init__.py`. More elegant, slightly more complex.

Pick A unless the submodule list is volatile.

### 5. Update version
- `cadclaw/__init__.py` — `__version__ = "0.8.0"`
- `pyproject.toml` — `version = "0.8.0"`
- `CITATION.cff` — bump `version:` field
- `README.md` install section — verify it still says `pip install cadclaw` (it should — the package name didn't change)

### 6. Run the test suite
```bash
pytest tests/ -v
```
Expected: same pass count as v0.7.1, **plus** a new test that asserts the deprecation works:

`tests/test_compat_shim.py`:
```python
import warnings
import pytest

def test_cadharness_import_emits_deprecation_warning():
    # Re-import under a clean warnings filter
    import importlib, sys
    if "cadharness" in sys.modules:
        del sys.modules["cadharness"]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import cadharness  # noqa
        assert any(issubclass(rec.category, DeprecationWarning) for rec in w)

def test_cadharness_reexports_match_cadclaw():
    import cadharness, cadclaw
    assert cadharness.__version__ == cadclaw.__version__
```

### 7. Update M3-CRETE-side references
File `D:/SunnydayTech/M3-CRETE/cadclaw-v0.6-field-test-2026-04-26.md` references `cadharness/bom_loader.py:50-57` etc. After the retest report is updated (separate task), references should point at `cadclaw/bom_loader.py` paths — but the line numbers may shift, so re-grep when updating.

---

## Release flow (GitHub → PyPI + Zenodo)

`.github/workflows/` should already have the publish wiring (CITATION.cff + ORCID/DOI metadata commits suggest this was set up in PR #5). To verify before the v0.8.0 push:

```bash
ls -la .github/workflows/
```
Look for: `publish.yml` / `release.yml` / `pypi.yml` and a Zenodo-DOI step. If the publish key exists as a GitHub Actions secret, the release should auto-fire on tag push.

**Release command (after PR merges):**
```bash
git tag -a v0.8.0 -m "v0.8.0 — rename cadharness → cadclaw (compat shim retained)"
git push origin v0.8.0
```

The tag push triggers the workflow → PyPI gets v0.8.0 → Zenodo mints a new DOI under the existing concept DOI.

**If PyPI publish fails because v0.5.0 is still listed and our metadata diverged:** a `pip index versions cadclaw` between v0.5.0 → v0.8.0 is fine; PyPI doesn't care about gaps. If the workflow uses *trusted publishing* (OIDC) it'll just work; if it uses an API token check the secret hasn't expired.

---

## Sanity checks before tagging

- [ ] `pip install -e .` from a fresh venv → `cadclaw doctor` PASS
- [ ] `import cadclaw` works
- [ ] `import cadharness` works AND emits DeprecationWarning
- [ ] `cadharness.bom_audit.run_bom_audit` resolves to the same function as `cadclaw.bom_audit.run_bom_audit` (test option-A submodule shims)
- [ ] M3-CRETE retest still passes 1/16/5 against the renamed module
- [ ] `pytest tests/` — green
- [ ] CITATION.cff version bumped; ORCID + concept-DOI metadata still present
- [ ] No stray `cadharness` strings outside the compat shim files (`rg "cadharness" -g '!cadharness/**'` should be empty)

---

## Things NOT in v0.8.0 scope

- **PyPI re-namespace** — keep package name `cadclaw`. Don't change pyproject `name`.
- **Removing the shim** — that's v1.0.
- **Changing CLI name** — already `cadclaw`. No change.
- **MCP server module name** — `cadclaw_mcp`, already correct.
- **CLI module name** — `cadclaw_cli`, already correct.

---

## File index

- `D:/SunnydayTech/CADCLAW/cadharness/` → rename target (becomes `cadclaw/`)
- `D:/SunnydayTech/CADCLAW/pyproject.toml` — packages list + version
- `D:/SunnydayTech/CADCLAW/CITATION.cff` — version field
- `D:/SunnydayTech/CADCLAW/README.md`, `AGENTS.md` — docs sweep
- `D:/SunnydayTech/CADCLAW/.github/workflows/` — verify publish flow before tag push
- `D:/SunnydayTech/M3-CRETE/cadclaw-v0.6-field-test-2026-04-26.md` — re-grep `cadharness` paths after rename, update line refs
