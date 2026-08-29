"""
CADCLAW — Automated geometric validation, BOM-vs-CAD audit, and an honesty
toolchain (doctor / publish-audit / claim-audit) for STEP-based CAD
assemblies, with an MCP server for assistant-driven workflows.

https://github.com/sunnyday-technologies/CADCLAW
"""
__version__ = "0.10.0"
__author__ = "Sunnyday Technologies"

__all__ = [
    "Harness",
    "RulesConfigError",
    "load_rules_safe",
    "run_configured_harness",
    "__author__",
    "__version__",
]


def __getattr__(name: str):
    """Lazily expose harness APIs without making ``cadclaw doctor`` heavy."""
    if name in {"Harness", "run_configured_harness"}:
        from .harness import Harness, run_configured_harness

        return {
            "Harness": Harness,
            "run_configured_harness": run_configured_harness,
        }[name]
    if name in {"RulesConfigError", "load_rules_safe"}:
        from .rules import RulesConfigError, load_rules_safe

        return {
            "RulesConfigError": RulesConfigError,
            "load_rules_safe": load_rules_safe,
        }[name]
    raise AttributeError(f"module 'cadclaw' has no attribute {name!r}")
