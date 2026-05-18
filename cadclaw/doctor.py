"""
Doctor — environment diagnostic that catches the broken-venv / missing-dep
failure modes before users hit opaque MCP errors.

Probes (in order):
  1. probe_python              — interpreter path + version (>= 3.10)
  2. probe_venv                — pyvenv.cfg `home =` points at an existing Python
  3. probe_cadclaw             — package version + install path
  4. probe_dependencies        — cadquery / OCP / vtk / Pillow import + version
  5. probe_mcp_inproc          — handle_request({"method":"tools/list"}) works
  6. probe_repo_signals        — STEP / BOM / cadclaw.yaml glob signals (info only)

Each probe returns a List[Finding]. `run_doctor()` runs them all and returns a
unified `Report`.

Usage:
    from cadclaw.doctor import run_doctor
    report = run_doctor()
    sys.exit(0 if report.passed else 1)
"""
from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from .findings import ConfidenceBudget, Finding, Report, Severity


# ---------------------------------------------------------------------------
# Individual probes


def probe_python() -> List[Finding]:
    out: List[Finding] = []
    info = sys.version_info
    exe = sys.executable
    version_str = f"{info.major}.{info.minor}.{info.micro}"
    if info < (3, 10):
        out.append(Finding(
            id="doctor.python_too_old",
            category="doctor",
            severity=Severity.FAIL,
            message=f"Python {version_str} is below CADCLAW's minimum (3.10).",
            suggested_fix="Install Python 3.10 or later and recreate your venv.",
            evidence={"executable": exe, "version": version_str},
        ))
    else:
        out.append(Finding(
            id="doctor.python_ok",
            category="doctor",
            severity=Severity.PASS,
            message=f"Python {version_str} at {exe}",
            evidence={"executable": exe, "version": version_str},
        ))
    return out


def probe_venv(prefix: Optional[str] = None) -> List[Finding]:
    """Detect a broken venv: pyvenv.cfg `home =` pointing at a missing Python.

    `prefix` is overridable so tests can point this at a fixture directory.
    """
    out: List[Finding] = []
    p = Path(prefix) if prefix is not None else Path(sys.prefix)
    cfg = p / "pyvenv.cfg"
    if not cfg.exists():
        out.append(Finding(
            id="doctor.no_venv",
            category="doctor",
            severity=Severity.PASS,
            message=f"Not running inside a venv (no pyvenv.cfg at {p}).",
            evidence={"prefix": str(p)},
        ))
        return out

    home: Optional[str] = None
    try:
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.startswith("home"):
                _, _, val = line.partition("=")
                home = val.strip()
                break
    except OSError as e:
        out.append(Finding(
            id="doctor.pyvenv_read_error",
            category="doctor",
            severity=Severity.FAIL,
            message=f"could not read {cfg}: {e}",
            evidence={"path": str(cfg)},
        ))
        return out

    if home is None:
        out.append(Finding(
            id="doctor.pyvenv_no_home",
            category="doctor",
            severity=Severity.WARN,
            message=f"pyvenv.cfg at {cfg} has no `home =` line",
            evidence={"path": str(cfg)},
        ))
        return out

    home_path = Path(home)
    candidates = [home_path / "python.exe", home_path / "python3", home_path / "python"]
    if home_path.is_dir() and any(c.exists() for c in candidates):
        out.append(Finding(
            id="doctor.venv_ok",
            category="doctor",
            severity=Severity.PASS,
            message=f"venv home {home_path} exists.",
            evidence={"prefix": str(p), "home": home},
        ))
    else:
        out.append(Finding(
            id="doctor.pyvenv_broken",
            category="doctor",
            severity=Severity.FAIL,
            message=(
                f"pyvenv.cfg points to a Python interpreter that does not exist "
                f"on this machine (home = {home})."
            ),
            suggested_fix=(
                "This venv was probably created on a different machine. Recreate it:\n"
                "  rm -rf <venv-dir>\n"
                "  python -m venv <venv-dir>\n"
                "  <venv-dir>/Scripts/activate   # Windows\n"
                "  <venv-dir>/bin/activate       # POSIX\n"
                "  pip install -e ."
            ),
            evidence={"pyvenv_cfg": str(cfg), "home": home, "venv_prefix": str(p)},
        ))
    return out


def probe_cadclaw() -> List[Finding]:
    out: List[Finding] = []
    try:
        import importlib.metadata as md
        version = md.version("cadclaw")
    except Exception as e:
        out.append(Finding(
            id="doctor.cadclaw_metadata_missing",
            category="doctor",
            severity=Severity.WARN,
            message=f"could not read installed cadclaw version metadata: {e}",
            suggested_fix="Run `pip install -e .` from the repo root.",
        ))
        version = "unknown"

    try:
        import cadclaw
        path = getattr(cadclaw, "__file__", "?")
    except ImportError as e:
        out.append(Finding(
            id="doctor.cadclaw_import_failed",
            category="doctor",
            severity=Severity.FAIL,
            message=f"cadclaw package failed to import: {e}",
            suggested_fix="Reinstall cadclaw: pip install -e .",
        ))
        return out

    out.append(Finding(
        id="doctor.cadclaw_ok",
        category="doctor",
        severity=Severity.PASS,
        message=f"cadclaw {version} loaded from {path}",
        evidence={"version": version, "path": path},
    ))
    return out


_DEP_HINTS = {
    "cadquery": "pip install cadquery",
    "OCP": "pip install cadquery-ocp  # or reinstall cadquery",
    "vtk": "pip install vtk  # required for render module",
    "PIL": "pip install Pillow",
    "yaml": "pip install pyyaml",
    "pydantic": "pip install 'pydantic>=2.5'",
    "Pynite": "pip install PyniteFEA  # core only, not the [all] extra",
}

# Optional deps: a missing one is a WARN, not a FAIL — only the gate that
# needs it is unavailable. `Pynite` backs the cadclaw.fea kinematics gate.
_OPTIONAL_DEPS = {"Pynite"}


def probe_dependencies() -> List[Finding]:
    out: List[Finding] = []
    for mod_name in ["cadquery", "OCP", "vtk", "PIL", "yaml", "pydantic",
                     "Pynite"]:
        try:
            mod = importlib.import_module(mod_name)
            version = getattr(mod, "__version__", None) or getattr(mod, "VERSION", "?")
            if isinstance(version, tuple):
                version = ".".join(str(x) for x in version)
            out.append(Finding(
                id=f"doctor.dep_ok",
                category="doctor",
                severity=Severity.PASS,
                message=f"{mod_name} {version} importable",
                evidence={"module": mod_name, "version": str(version)},
            ))
        except ImportError as e:
            optional = mod_name in _OPTIONAL_DEPS
            out.append(Finding(
                id="doctor.optional_dep_missing" if optional
                   else "doctor.dep_missing",
                category="doctor",
                severity=Severity.WARN if optional else Severity.FAIL,
                message=(f"{mod_name} not installed — "
                         + ("the cadclaw.fea kinematics gate is unavailable"
                            if optional else f"import failed: {e}")),
                suggested_fix=_DEP_HINTS.get(mod_name, f"pip install {mod_name}"),
                evidence={"module": mod_name, "optional": optional},
            ))
    return out


def probe_mcp_inproc() -> List[Finding]:
    out: List[Finding] = []
    try:
        from cadclaw_mcp.server import handle_request, TOOLS
    except Exception as e:
        out.append(Finding(
            id="doctor.mcp_import_failed",
            category="doctor",
            severity=Severity.FAIL,
            message=f"cadclaw_mcp.server failed to import: {e}",
            suggested_fix="Reinstall cadclaw or check Python path.",
        ))
        return out

    try:
        resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = resp.get("result", {}).get("tools", []) if resp else []
        n = len(tools)
        if n >= 11:
            out.append(Finding(
                id="doctor.mcp_ok",
                category="doctor",
                severity=Severity.PASS,
                message=f"MCP server responds; {n} tools registered.",
                evidence={"tool_count": n},
            ))
        else:
            out.append(Finding(
                id="doctor.mcp_few_tools",
                category="doctor",
                severity=Severity.WARN,
                message=f"MCP server responds but reports only {n} tools (expected >= 11).",
                evidence={"tool_count": n},
            ))
    except Exception as e:
        out.append(Finding(
            id="doctor.mcp_handle_request_failed",
            category="doctor",
            severity=Severity.FAIL,
            message=f"MCP handle_request raised: {e}",
        ))
    return out


def probe_repo_signals(repo: Optional[str] = None) -> List[Finding]:
    """Info-only probe — what files we see in the working tree."""
    out: List[Finding] = []
    base = Path(repo) if repo else Path.cwd()
    step_files = list(base.glob("**/*.step")) + list(base.glob("**/*.STEP"))
    step_files = [f for f in step_files if ".git" not in f.parts]
    bom_files = list(base.glob("bom/*.json"))
    rules_file = base / "cadclaw.yaml"
    out.append(Finding(
        id="doctor.repo_signals",
        category="doctor",
        severity=Severity.PASS,
        message=(
            f"Found {len(step_files)} STEP file(s), {len(bom_files)} BOM file(s); "
            f"cadclaw.yaml {'present' if rules_file.exists() else 'absent'}."
        ),
        evidence={
            "repo": str(base),
            "step_count": len(step_files),
            "bom_count": len(bom_files),
            "has_cadclaw_yaml": rules_file.exists(),
        },
    ))
    return out


# ---------------------------------------------------------------------------
# Top-level runner


def run_doctor(repo: Optional[str] = None, prefix: Optional[str] = None) -> Report:
    """Run all probes and return a unified Report.

    `repo` and `prefix` are overridable for tests; they default to the cwd
    and `sys.prefix` respectively.
    """
    t0 = time.time()
    findings: List[Finding] = []
    findings.extend(probe_python())
    findings.extend(probe_venv(prefix=prefix))
    findings.extend(probe_cadclaw())
    findings.extend(probe_dependencies())
    findings.extend(probe_mcp_inproc())
    findings.extend(probe_repo_signals(repo=repo))
    duration_ms = (time.time() - t0) * 1000

    rep = Report(
        findings=findings,
        duration_ms=duration_ms,
        meta={"category": "doctor", "repo": str(repo or Path.cwd())},
        confidence_budget=ConfidenceBudget(
            checked=[
                "python version",
                "venv pyvenv.cfg",
                "cadclaw install",
                "core deps (cadquery, OCP, vtk, PIL, yaml, pydantic)",
                "MCP in-process tools/list",
                "repo file signals",
            ],
            not_checked=[
                "MCP over actual stdio subprocess",
                "OCC native library compatibility at runtime",
                "STEP file integrity",
            ],
            assumptions=[
                "Python on PATH matches sys.executable",
                "venv created with stdlib `venv` module (pyvenv.cfg present)",
            ],
        ),
    )
    rep.overall = rep.compute_overall()
    return rep
