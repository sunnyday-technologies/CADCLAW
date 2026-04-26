"""
CADCLAW MCP Server — Model Context Protocol interface for CAD validation.

Exposes CADCLAW's 5 validation gates as tools that Claude (or any MCP client)
can call directly. No code generation needed — the user describes what they
want checked, Claude calls the appropriate tools.

Tools:
  - load_assembly: Load a STEP file and return part inventory summary
  - check_inventory: Validate part counts against expected
  - check_interference: Find solid-solid overlaps between parts
  - check_adjacency: Validate spatial relationships between part types
  - check_dimensions: Validate part dimensions against expected ranges
  - compute_deflection: Beam deflection analysis
  - compute_motor_budget: Motor torque budget analysis
  - compute_belt_tension: Belt tension safety analysis
  - tolerance_stack: Worst-case / RSS / Monte Carlo tolerance analysis
  - disassembly_sequence: Ordered part-removal plan
  - export_exploded_view: Radial or axial exploded STEP export

Usage:
  python -m cadclaw_mcp.server
  # or add to Claude's MCP config:
  # "cadclaw": {"command": "python", "args": ["-m", "cadclaw_mcp.server"]}

Protocol: MCP over stdio (JSON-RPC 2.0)
"""
import contextlib
import io
import sys
import os
import json
import traceback

# Add parent to path so cadharness imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from cadharness.inventory import load_and_dedup, sig, InventoryCheck, Region
from cadharness.interference import InterferenceCheck
from cadharness.adjacency import AdjacencyCheck, AdjacencyRule
from cadharness.dimensional import DimensionalCheck, DimRule
from cadharness.kinematics import beam_deflection, motor_torque_budget, belt_tension
from cadharness.tolerance import ToleranceChain
from cadharness.disassembly import DisassemblySequence

# v0.6 additions — gates that take a rule file and return a structured Report.
from cadharness.findings import Severity
from cadharness.doctor import run_doctor
from cadharness.rules import load_rules
from cadharness.bom_audit import run_bom_audit
from cadharness.publish_audit import run_publish_audit
from cadharness.claim_audit import run_claim_audit
from cadharness.parity import compare_steps

# ============================================================
# MCP Protocol Implementation (stdio transport)
# ============================================================

# Global state: loaded assembly parts
_loaded_parts = None
_loaded_path = None
_label_map = {}


def _label_fn(solid):
    d = sig(solid)
    if d in _label_map:
        return _label_map[d]
    if d[0] == 1.5 and len(d) >= 2 and d[1] == 6.0:
        return 'belt'
    return 'other'


# ============================================================
# Tool implementations
# ============================================================

def tool_load_assembly(path: str, labels: dict = None) -> dict:
    """Load a STEP file and return a summary of parts found."""
    global _loaded_parts, _loaded_path, _label_map

    if labels:
        # Convert string tuple keys back to actual tuples
        _label_map = {}
        for k, v in labels.items():
            if isinstance(k, str):
                _label_map[tuple(float(x) for x in k.strip("()").split(","))] = v
            else:
                _label_map[tuple(k)] = v
    else:
        _label_map = {}

    _loaded_parts = load_and_dedup(path)
    _loaded_path = path

    from collections import Counter
    inv = Counter(_label_fn(s) for s in _loaded_parts)

    return {
        "status": "loaded",
        "path": path,
        "total_parts": len(_loaded_parts),
        "inventory": dict(inv),
    }


def tool_check_inventory(expected: dict) -> dict:
    """Check loaded assembly part counts against expected."""
    if _loaded_parts is None:
        return {"error": "No assembly loaded. Call load_assembly first."}

    check = InventoryCheck(_loaded_path, _label_map, expected)
    result = check.run(parts=_loaded_parts)

    return {
        "passed": result.passed,
        "total_parts": result.total_parts,
        "inventory": result.inventory,
        "mismatches": result.mismatches,
    }


def tool_check_interference(skip_labels: list = None, min_volume: float = 1.0) -> dict:
    """Find solid-solid overlaps between parts."""
    if _loaded_parts is None:
        return {"error": "No assembly loaded. Call load_assembly first."}

    skip = set(skip_labels) if skip_labels else set()
    check = InterferenceCheck(_loaded_parts, _label_fn,
                               skip_labels=skip, min_volume=min_volume)
    result = check.run()

    clips = []
    for c in result.clips:
        clips.append({
            "part_a": c.label_a,
            "part_b": c.label_b,
            "center_a": list(c.center_a),
            "center_b": list(c.center_b),
            "overlap_mm3": round(c.volume, 1),
        })

    return {
        "passed": result.passed,
        "checked_pairs": result.checked_pairs,
        "interferences": len(clips),
        "clips": clips,
    }


def tool_check_adjacency(rules: list) -> dict:
    """Validate spatial relationships between part types."""
    if _loaded_parts is None:
        return {"error": "No assembly loaded. Call load_assembly first."}

    adj_rules = [AdjacencyRule(
        source=r["source"],
        target=r["target"],
        max_distance=r.get("max_distance", 50.0)
    ) for r in rules]

    check = AdjacencyCheck(_loaded_parts, _label_fn, adj_rules)
    result = check.run()

    violations = []
    for v in result.violations:
        violations.append({
            "source": v.source_label,
            "source_position": list(v.source_center),
            "nearest_target": v.nearest_target_label,
            "distance_mm": round(v.nearest_distance, 1),
            "max_allowed_mm": v.max_allowed,
        })

    return {
        "passed": result.passed,
        "violations": violations,
    }


def tool_check_dimensions(rules: list) -> dict:
    """Check part dimensions against expected ranges."""
    if _loaded_parts is None:
        return {"error": "No assembly loaded. Call load_assembly first."}

    dim_rules = [DimRule(
        label=r["label"],
        thin_axis=r.get("thin_axis"),
        thin_tol=r.get("thin_tol", 0.5),
    ) for r in rules]

    check = DimensionalCheck(_loaded_parts, _label_fn, dim_rules)
    result = check.run()

    violations = [{"label": v.label, "message": v.message}
                  for v in result.violations]

    return {
        "passed": result.passed,
        "violations": violations,
    }


def tool_compute_deflection(span_m: float, point_load_kg: float,
                             I_cm4: float, beam_kg_per_m: float,
                             E_GPa: float = 69.0, limit_mm: float = 0.5) -> dict:
    """Compute beam deflection (simply-supported, center load)."""
    result = beam_deflection(
        span_m=span_m,
        point_load_kg=point_load_kg,
        I_m4=I_cm4 * 1e-8,
        beam_kg_per_m=beam_kg_per_m,
        E_Pa=E_GPa * 1e9,
        limit_mm=limit_mm,
    )
    return {
        "point_load_sag_mm": round(result.point_load_mm, 3),
        "self_weight_sag_mm": round(result.self_weight_mm, 3),
        "total_sag_mm": round(result.total_mm, 3),
        "limit_mm": result.limit_mm,
        "passed": result.passed,
    }


def tool_compute_motor_budget(mass_kg: float, n_motors: int,
                               pulley_radius_mm: float,
                               motor_torque_Nm: float,
                               accel: float = 0.5,
                               gravity_axis: bool = False) -> dict:
    """Compute motor torque budget for a belt-driven axis."""
    result = motor_torque_budget(
        mass_kg=mass_kg,
        n_motors=n_motors,
        pulley_radius_m=pulley_radius_mm / 1000.0,
        motor_torque_Nm=motor_torque_Nm,
        accel_m_s2=accel,
        gravity_axis=gravity_axis,
    )
    return {
        "force_total_N": round(result.force_total_N, 1),
        "torque_required_Nm": round(result.torque_required_Nm, 4),
        "torque_available_Nm": round(result.torque_available_Nm, 4),
        "safety_factor": round(result.safety_factor, 1),
        "passed": result.passed,
    }


def tool_compute_belt_tension(force_N: float, n_belts: int = 1) -> dict:
    """Check belt tension against safety limits."""
    result = belt_tension(force_N=force_N, n_belts=n_belts)
    return {
        "tension_per_belt_N": round(result.tension_N, 1),
        "safety_to_break": round(result.safety_to_break, 1),
        "safety_to_working": round(result.safety_to_working, 1),
        "passed": result.passed,
    }


def tool_tolerance_stack(chain_name: str, dimensions: list,
                          target: float = 0.0, tolerance: float = 0.5,
                          mc_samples: int = 100000) -> dict:
    """Compute tolerance stack analysis (worst-case, RSS, Monte Carlo).

    Defines a chain of dimensions that accumulate to a critical result.
    Reports whether the stack meets the functional tolerance requirement.
    Includes Cpk process capability and per-dimension variance contribution.
    """
    chain = ToleranceChain(chain_name)
    for d in dimensions:
        chain.add(
            name=d["name"],
            nominal=d["nominal"],
            plus=d.get("plus", 0.1),
            minus=d.get("minus", d.get("plus", 0.1)),
            distribution=d.get("distribution", "normal"),
            direction=d.get("direction", 1.0),
        )

    result = chain.analyze(target=target, tolerance=tolerance,
                            mc_samples=mc_samples)

    return {
        "chain_name": result.chain_name,
        "nominal_result_mm": round(result.nominal_result, 3),
        "target_mm": result.target,
        "tolerance_mm": result.tolerance,
        "worst_case": {
            "min": round(result.worst_case_min, 3),
            "max": round(result.worst_case_max, 3),
            "range": round(result.worst_case_range, 3),
            "passed": result.worst_case_passed,
        },
        "rss_3sigma": {
            "min": round(result.rss_min, 3),
            "max": round(result.rss_max, 3),
            "range": round(result.rss_range, 3),
            "passed": result.rss_passed,
        },
        "monte_carlo": {
            "mean": round(result.mc_mean, 3),
            "std": round(result.mc_std, 3),
            "yield_pct": round(result.mc_yield_pct, 2),
            "passed": result.mc_passed,
        },
        "cpk": round(result.cpk, 2),
        "capable": result.cpk >= 1.33,
        "contributors": result.contributors,
    }


def tool_disassembly_sequence(path: str, labels: dict = None,
                               priority: dict = None) -> dict:
    """Generate an ordered disassembly sequence for a STEP assembly.

    Returns each step as label + center position + removal axis/direction.
    """
    label_map = {}
    if labels:
        for k, v in labels.items():
            if isinstance(k, str):
                label_map[tuple(float(x) for x in k.strip("()").split(","))] = v
            else:
                label_map[tuple(k)] = v

    seq = DisassemblySequence(path, labels=label_map)
    seq.auto_sequence(priority=priority)

    return {
        "path": path,
        "n_steps": len(seq.steps),
        "centroid": list(seq.centroid),
        "steps": [
            {
                "order": i + 1,
                "label": s.label,
                "center": list(s.center),
                "removal_axis": s.removal_axis,
                "removal_direction": int(s.removal_direction),
            }
            for i, s in enumerate(seq.steps)
        ],
    }


def tool_doctor() -> dict:
    """Run the v0.6 environment doctor (Python, venv, deps, MCP, repo signals)."""
    report = run_doctor()
    return report.to_dict()


def tool_check_bom_against_cad(rules_path: str,
                                bom_path: str = None,
                                step_path: str = None) -> dict:
    """Compare a BOM JSON against a STEP assembly using a cadclaw.yaml rule file."""
    rules = load_rules(rules_path)
    bp = bom_path or rules.bom_audit.bom_path
    sp = step_path or rules.meta.step
    if not bp:
        return {"error": "bom_path required (pass argument or set bom_audit.bom_path in rules)"}
    if not sp:
        return {"error": "step_path required (pass argument or set meta.step in rules)"}
    report = run_bom_audit(bom_path=bp, step_path=sp, rules=rules)
    return report.to_dict()


def tool_check_publish_boundary(rules_path: str, repo_root: str = ".") -> dict:
    """Privacy-boundary scan: ignore_globs vs git state + redact-pattern content scan."""
    rules = load_rules(rules_path)
    report = run_publish_audit(rules, repo_root=repo_root)
    return report.to_dict()


def tool_check_claims(rules_path: str, repo_root: str = ".") -> dict:
    """Scan README/docs/BOM notes for forbidden absolutes, untagged numerics, stale terms."""
    rules = load_rules(rules_path)
    report = run_claim_audit(rules, repo_root=repo_root)
    return report.to_dict()


def tool_check_region_inventory(rules_path: str, step_path: str = None) -> dict:
    """Run the inventory gate with per-region constraints from cadclaw.yaml."""
    rules = load_rules(rules_path)
    sp = step_path or rules.meta.step
    if not sp:
        return {"error": "step_path required (pass argument or set meta.step in rules)"}
    sig_to_label = rules.sig_to_label()
    label_dict = {sig: name for sig, name in sig_to_label.items()}
    regions = [
        Region(
            name=r.name,
            x_range=tuple(r.x_range) if r.x_range else None,
            y_range=tuple(r.y_range) if r.y_range else None,
            z_range=tuple(r.z_range) if r.z_range else None,
            expected=dict(r.expected),
        )
        for r in rules.regions
    ] or None
    check = InventoryCheck(sp, label_dict, dict(rules.expected_inventory),
                            belt_heuristic=rules.belt_heuristic, regions=regions)
    result = check.run()
    return {
        "passed": result.passed,
        "total_parts": result.total_parts,
        "inventory": result.inventory,
        "expected": result.expected,
        "mismatches": result.mismatches,
        "regions": {
            name: {
                "passed": rr.passed,
                "total_parts": rr.total_parts,
                "inventory": rr.inventory,
                "mismatches": rr.mismatches,
            }
            for name, rr in result.region_results.items()
        },
    }


def tool_compare_step_parity(step_a: str, step_b: str) -> dict:
    """Compare two STEP files by dim-signature inventory; flag visibility-toggle bugs."""
    parity = compare_steps(step_a, step_b)
    return {
        "passed": parity.passed,
        "a_path": parity.a_path,
        "b_path": parity.b_path,
        "a_parts": parity.a_parts,
        "b_parts": parity.b_parts,
        "only_in_a": [{"sig": list(s), "count": c} for s, c in parity.only_in_a],
        "only_in_b": [{"sig": list(s), "count": c} for s, c in parity.only_in_b],
        "size_shrunk_warning": parity.size_shrunk_warning,
    }


def tool_export_exploded_view(path: str, output_path: str,
                               mode: str = "radial",
                               expansion: float = 0.35,
                               explode_distance: float = 300.0,
                               labels: dict = None) -> dict:
    """Export an exploded-view STEP file.

    mode='radial' pushes each part outward from the centroid by `expansion`
    of its distance from center. mode='axial' uses the per-part removal
    axis and `explode_distance`.
    """
    label_map = {}
    if labels:
        for k, v in labels.items():
            if isinstance(k, str):
                label_map[tuple(float(x) for x in k.strip("()").split(","))] = v
            else:
                label_map[tuple(k)] = v

    seq = DisassemblySequence(path, labels=label_map)
    seq.auto_sequence()

    if mode == "radial":
        seq.export_radial(output_path, expansion=expansion)
    elif mode == "axial":
        seq.export_exploded(output_path, explode_distance=explode_distance)
    else:
        return {"error": f"Unknown mode: {mode}. Use 'radial' or 'axial'."}

    size_kb = os.path.getsize(output_path) / 1024 if os.path.exists(output_path) else 0
    return {
        "output_path": output_path,
        "mode": mode,
        "size_kb": round(size_kb, 1),
        "n_parts": len(seq.parts),
    }


# ============================================================
# MCP Protocol: Tool definitions
# ============================================================

TOOLS = [
    {
        "name": "load_assembly",
        "description": "Load a STEP file and return a summary of all parts found, labeled by bounding-box signature. Must be called before any check_ tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the STEP file"},
                "labels": {
                    "type": "object",
                    "description": "Map of bbox signature tuples to part labels, e.g. {\"(40.0, 80.0, 1000.0)\": \"cbeam\"}",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "check_inventory",
        "description": "Validate that the loaded assembly contains the expected number of each part type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expected": {
                    "type": "object",
                    "description": "Map of part labels to expected counts, e.g. {\"cbeam\": 17, \"motor\": 6}",
                },
            },
            "required": ["expected"],
        },
    },
    {
        "name": "check_interference",
        "description": "Find solid-solid overlaps between assembly parts using exact BRep boolean intersection. Reports overlap volume in mm^3.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skip_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Part labels to skip (e.g. ['belt', 'wheel'])",
                },
                "min_volume": {
                    "type": "number",
                    "description": "Minimum overlap volume in mm^3 to report (default 1.0)",
                },
            },
        },
    },
    {
        "name": "check_adjacency",
        "description": "Validate that parts of one type are within a specified distance of parts of another type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                            "max_distance": {"type": "number"},
                        },
                        "required": ["source", "target"],
                    },
                },
            },
            "required": ["rules"],
        },
    },
    {
        "name": "check_dimensions",
        "description": "Validate part dimensions against expected ranges. Catches swapped box() args, wrong thickness, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "thin_axis": {"type": "number"},
                            "thin_tol": {"type": "number"},
                        },
                        "required": ["label"],
                    },
                },
            },
            "required": ["rules"],
        },
    },
    {
        "name": "compute_deflection",
        "description": "Compute beam deflection for a simply-supported beam with a center point load and distributed self-weight.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "span_m": {"type": "number", "description": "Beam span in meters"},
                "point_load_kg": {"type": "number", "description": "Point load at center in kg"},
                "I_cm4": {"type": "number", "description": "Second moment of area in cm^4"},
                "beam_kg_per_m": {"type": "number", "description": "Beam mass per meter in kg/m"},
                "E_GPa": {"type": "number", "description": "Young's modulus in GPa (default 69 = aluminum)"},
                "limit_mm": {"type": "number", "description": "Pass/fail limit in mm (default 0.5)"},
            },
            "required": ["span_m", "point_load_kg", "I_cm4", "beam_kg_per_m"],
        },
    },
    {
        "name": "compute_motor_budget",
        "description": "Compute motor torque budget for a belt-driven axis. Returns safety factor and pass/fail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mass_kg": {"type": "number", "description": "Total moving mass on this axis in kg"},
                "n_motors": {"type": "integer", "description": "Number of motors driving this axis"},
                "pulley_radius_mm": {"type": "number", "description": "GT2 pulley pitch radius in mm"},
                "motor_torque_Nm": {"type": "number", "description": "Motor holding torque in Nm"},
                "accel": {"type": "number", "description": "Target acceleration in m/s^2 (default 0.5)"},
                "gravity_axis": {"type": "boolean", "description": "True if this axis fights gravity (Z-axis)"},
            },
            "required": ["mass_kg", "n_motors", "pulley_radius_mm", "motor_torque_Nm"],
        },
    },
    {
        "name": "compute_belt_tension",
        "description": "Check belt tension against breaking and working load limits.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "force_N": {"type": "number", "description": "Total force on the belt system in Newtons"},
                "n_belts": {"type": "integer", "description": "Number of belts sharing the load (default 1)"},
            },
            "required": ["force_N"],
        },
    },
    {
        "name": "disassembly_sequence",
        "description": "Generate an ordered disassembly sequence for a STEP assembly. Each step lists the part label, its center, and which axis/direction to pull it out.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the STEP file"},
                "labels": {
                    "type": "object",
                    "description": "Map of bbox signature tuples to part labels",
                },
                "priority": {
                    "type": "object",
                    "description": "Map of label to priority number (lower = removed first)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "export_exploded_view",
        "description": "Export a STEP exploded view. Mode 'radial' pushes every part outward from the assembly centroid; 'axial' pushes along each part's removal axis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to input STEP file"},
                "output_path": {"type": "string", "description": "Path to write exploded STEP"},
                "mode": {"type": "string", "description": "'radial' (default) or 'axial'"},
                "expansion": {"type": "number", "description": "Radial expansion fraction (default 0.35)"},
                "explode_distance": {"type": "number", "description": "Axial explode distance mm (default 300)"},
                "labels": {"type": "object", "description": "Optional bbox-signature label map"},
            },
            "required": ["path", "output_path"],
        },
    },
    {
        "name": "doctor",
        "description": "Run the v0.6 environment doctor: Python, venv, dependencies, MCP self-check, repo signals.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_bom_against_cad",
        "description": "Compare a BOM JSON against a STEP assembly using a cadclaw.yaml rule file. Returns structured findings including BOM qty/mfg_type/term checks and CAD count comparison. Private BOM fields (vendors, sku, unit_cost) are never returned.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rules_path": {"type": "string", "description": "Path to cadclaw.yaml"},
                "bom_path": {"type": "string", "description": "Optional override for the BOM JSON path"},
                "step_path": {"type": "string", "description": "Optional override for the STEP file path"},
            },
            "required": ["rules_path"],
        },
    },
    {
        "name": "check_publish_boundary",
        "description": "Scan the working tree for private files that are tracked or staged (publish-audit). Uses ignore_globs vs git state, plus regex redact_patterns over scan_globs. Never echoes matched secret values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rules_path": {"type": "string"},
                "repo_root": {"type": "string", "description": "Path to the repo root (default '.')"},
            },
            "required": ["rules_path"],
        },
    },
    {
        "name": "check_claims",
        "description": "Lint README/docs/BOM notes for forbidden absolutes, untagged numeric claims, and user-supplied stale terms. Plus folded source-regex rules over .py files (protected output paths, silent fallback geometry).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rules_path": {"type": "string"},
                "repo_root": {"type": "string"},
            },
            "required": ["rules_path"],
        },
    },
    {
        "name": "check_region_inventory",
        "description": "Run the inventory gate with per-region (axis-aligned bounding-box) constraints from a cadclaw.yaml rule file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rules_path": {"type": "string"},
                "step_path": {"type": "string", "description": "Optional override for the STEP path"},
            },
            "required": ["rules_path"],
        },
    },
    {
        "name": "compare_step_parity",
        "description": "Compare two STEP files by dim-signature inventory. Detects parts present in one but not the other, plus the Fusion visibility-toggle bug (file shrinks but unique signatures grow).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "step_a": {"type": "string"},
                "step_b": {"type": "string"},
            },
            "required": ["step_a", "step_b"],
        },
    },
    {
        "name": "tolerance_stack",
        "description": "Compute tolerance stack analysis along an assembly chain. Returns worst-case, RSS (3-sigma), and Monte Carlo results with Cpk process capability and per-dimension variance contribution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chain_name": {"type": "string", "description": "Name for this tolerance chain (e.g. 'motor_alignment')"},
                "dimensions": {
                    "type": "array",
                    "description": "List of dimensions in the chain",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Dimension label"},
                            "nominal": {"type": "number", "description": "Nominal value in mm"},
                            "plus": {"type": "number", "description": "Plus tolerance in mm"},
                            "minus": {"type": "number", "description": "Minus tolerance in mm (defaults to plus)"},
                            "distribution": {"type": "string", "description": "normal, uniform, or triangular"},
                            "direction": {"type": "number", "description": "+1 to add, -1 to subtract"},
                        },
                        "required": ["name", "nominal", "plus"],
                    },
                },
                "target": {"type": "number", "description": "Target result value in mm (default 0)"},
                "tolerance": {"type": "number", "description": "Functional requirement +/- in mm (default 0.5)"},
                "mc_samples": {"type": "integer", "description": "Monte Carlo samples (default 100000)"},
            },
            "required": ["chain_name", "dimensions"],
        },
    },
]

# Tool dispatch
TOOL_HANDLERS = {
    "load_assembly": lambda args: tool_load_assembly(**args),
    "check_inventory": lambda args: tool_check_inventory(**args),
    "check_interference": lambda args: tool_check_interference(**args),
    "check_adjacency": lambda args: tool_check_adjacency(**args),
    "check_dimensions": lambda args: tool_check_dimensions(**args),
    "compute_deflection": lambda args: tool_compute_deflection(**args),
    "compute_motor_budget": lambda args: tool_compute_motor_budget(**args),
    "compute_belt_tension": lambda args: tool_compute_belt_tension(**args),
    "tolerance_stack": lambda args: tool_tolerance_stack(**args),
    "disassembly_sequence": lambda args: tool_disassembly_sequence(**args),
    "export_exploded_view": lambda args: tool_export_exploded_view(**args),
    # v0.6 additions
    "doctor": lambda args: tool_doctor(**args),
    "check_bom_against_cad": lambda args: tool_check_bom_against_cad(**args),
    "check_publish_boundary": lambda args: tool_check_publish_boundary(**args),
    "check_claims": lambda args: tool_check_claims(**args),
    "check_region_inventory": lambda args: tool_check_region_inventory(**args),
    "compare_step_parity": lambda args: tool_compare_step_parity(**args),
}


# ============================================================
# MCP JSON-RPC Protocol Handler
# ============================================================

def handle_request(request: dict) -> dict:
    """Handle an MCP JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "CADCLAW",
                    "version": "0.7.0",
                },
            },
        }

    elif method == "notifications/initialized":
        return None  # no response for notifications

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOL_HANDLERS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        try:
            # Tool handlers may call cadharness code that uses print() for
            # user-facing status. Stdout is reserved for the JSON-RPC stream,
            # so redirect any tool prints to stderr.
            with contextlib.redirect_stdout(sys.stderr):
                result = TOOL_HANDLERS[tool_name](tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    })}],
                    "isError": True,
                },
            }

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        }


def main():
    """Run the MCP server over stdio."""
    sys.stderr.write("CADCLAW MCP Server v0.1.0 starting...\n")
    sys.stderr.flush()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            # Skip empty lines
            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            response = handle_request(request)

            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        except json.JSONDecodeError as e:
            sys.stderr.write(f"JSON parse error: {e}\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"Server error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
