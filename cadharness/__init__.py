"""
Compatibility shim: `cadharness` was renamed to `cadclaw` in v0.8.0.

This module exists so code written against v0.7 and earlier
(`from cadharness.bom_audit import run_bom_audit`, `import cadharness`,
etc.) keeps working with a one-time DeprecationWarning. New code should
`import cadclaw` directly.

Mechanism: every `cadclaw.<sub>` submodule is registered in `sys.modules`
under the name `cadharness.<sub>` so Python's import machinery resolves
both names to the same module object. There is no duplicate code, no
re-imported state, no version drift.

This shim will be removed in v1.0.
"""
from __future__ import annotations

import importlib as _importlib
import sys as _sys
import warnings as _warnings

_warnings.warn(
    "The `cadharness` module has been renamed to `cadclaw` in v0.8.0. "
    "Update your imports — `cadharness` will be removed in v1.0.",
    DeprecationWarning,
    stacklevel=2,
)

# Eagerly import cadclaw (the real package) and re-export public API.
import cadclaw as _cadclaw  # noqa: E402
from cadclaw import __version__, __author__  # noqa: E402, F401

# Submodules that user code reaches into directly. Order doesn't matter,
# but `reporters` is a subpackage so we expose its leaf modules too.
_SUBMODULES = (
    "adjacency",
    "bom_audit",
    "bom_loader",
    "claim_audit",
    "dimensional",
    "disassembly",
    "doctor",
    "findings",
    "gate_spec",
    "geometry_import",
    "harness",
    "inspect",
    "interference",
    "inventory",
    "kinematics",
    "parity",
    "pmi",
    "roundtrip",
    "publish_audit",
    "render",
    "rules",
    "tolerance",
    "reporters",
    "reporters.text",
    "reporters.markdown",
    "reporters.json_writer",
)


def _alias_submodule(sub: str) -> None:
    cadclaw_name = f"cadclaw.{sub}"
    cadharness_name = f"cadharness.{sub}"
    try:
        mod = _importlib.import_module(cadclaw_name)
    except ImportError:  # pragma: no cover — should never happen at install time
        return
    _sys.modules[cadharness_name] = mod


for _sub in _SUBMODULES:
    _alias_submodule(_sub)


def __getattr__(name: str):
    """Lazy fallback — `cadharness.foo` resolves to `cadclaw.foo`.

    Hit when user code does `cadharness.foo` (attribute access on the
    package) for a submodule we did not pre-alias. Keeps the shim
    self-healing across minor refactors of `cadclaw`.
    """
    try:
        mod = _importlib.import_module(f"cadclaw.{name}")
    except ImportError as exc:
        raise AttributeError(
            f"module 'cadharness' has no attribute {name!r}"
        ) from exc
    _sys.modules[f"cadharness.{name}"] = mod
    return mod
