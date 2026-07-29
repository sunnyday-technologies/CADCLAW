"""
CADCLAW MCP Server — Model Context Protocol interface for CAD validation.

Exposes CADCLAW's core validation, analysis, and audit checks as tools that an
MCP-compatible client can call directly. No CAD authoring access is granted:
the user describes what they want checked, and the client calls the appropriate
CADCLAW tool.

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
  - doctor: Environment diagnostics
  - check_bom_against_cad: BOM JSON vs STEP audit
  - check_publish_boundary: privacy / publish-boundary audit
  - check_claims: public-claim audit
  - check_region_inventory: inventory with region constraints
  - compare_step_parity: STEP-vs-STEP dim-signature comparison

Assembly tools (build authored parts into a STEP assembly):
  - assemble_validate_spec: Validate an assembly spec without compiling
  - assemble_build: Resolve sources and compile the assembly with CadQuery
  - assemble_check_round: Build + inventory-check + render one review round
  - assemble_inspect_component: Inspect one authored STEP component
  - assemble_render_views: Render the spec's declared review views
  - assemble_render_sequence: Export step-by-step build STEPs, views, BOM CSV

Visual review: the render-producing tools return the PNGs as inline image
content by default (`return_images`), so the calling model can actually look
at what it built instead of trusting a path string. The files stay on disk as
the human-auditable traceability artifact.

Usage:
  python -m cadclaw_mcp.server
  # or add to an MCP host config:
  # "cadclaw": {"command": "python", "args": ["-m", "cadclaw_mcp.server"]}

Protocol: MCP over stdio (JSON-RPC 2.0)
"""
import base64
import contextlib
import io
import sys
import os
import json
import traceback

# Add parent to path so cadclaw imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from cadclaw.inventory import load_and_dedup, sig, InventoryCheck, Region
from cadclaw.interference import InterferenceCheck
from cadclaw.adjacency import AdjacencyCheck, AdjacencyRule
from cadclaw.dimensional import DimensionalCheck, DimRule
from cadclaw.kinematics import beam_deflection, motor_torque_budget, belt_tension
from cadclaw.tolerance import ToleranceChain
from cadclaw.disassembly import DisassemblySequence

# v0.6 additions — gates that take a rule file and return a structured Report.
from cadclaw.findings import Severity
from cadclaw.doctor import run_doctor
from cadclaw.rules import load_rules
from cadclaw.bom_audit import run_bom_audit
from cadclaw.publish_audit import run_publish_audit
from cadclaw.claim_audit import run_claim_audit
from cadclaw.parity import compare_steps
from cadclaw.assembly_compiler import (
    inspect_component,
    render_review_views,
    run_assembly_build,
    run_assembly_check_round,
    run_assembly_sequence,
    validate_assembly_spec,
)
from cadclaw import __version__ as CADCLAW_VERSION

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


def tool_check_interference(skip_labels: list = None, min_volume: float = 1.0,
                            min_clearance_mm: float = 1.0) -> dict:
    """Find solid-solid overlaps between parts."""
    if _loaded_parts is None:
        return {"error": "No assembly loaded. Call load_assembly first."}

    skip = set(skip_labels) if skip_labels else set()
    check = InterferenceCheck(_loaded_parts, _label_fn,
                               skip_labels=skip, min_volume=min_volume,
                               min_clearance_mm=min_clearance_mm)
    result = check.run()

    clips = []
    for c in result.clips:
        clips.append({
            "part_a": c.label_a,
            "part_b": c.label_b,
            "center_a": list(c.center_a),
            "center_b": list(c.center_b),
            "overlap_mm3": round(c.volume, 1),
            "overlap_dims_mm": [round(x, 3) for x in c.overlap_dims],
            "suggest_shift": {
                "axis": c.suggest_axis,
                "mm": round(c.suggest_shift_mm, 3),
                "clearance_mm": c.clearance_mm,
            },
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
    """Run the environment doctor (Python, venv, deps, MCP, repo signals)."""
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
# Assembly tools — compile authored parts into a STEP assembly
# ============================================================

# Inline-image budget. Renders are the point of the visual-review loop, but a
# 20-view sequence would blow the client's context, so cap what goes inline.
# Every render is written to disk regardless; the caps only bound what is
# echoed back into the conversation.
MAX_INLINE_IMAGES = 6
MAX_IMAGE_BYTES = 4_000_000

# Key used to smuggle image paths from a tool handler out to the JSON-RPC
# layer, which turns them into MCP image content blocks. Stripped from the
# JSON payload before it is serialized.
_IMAGES_KEY = "_inline_image_paths"


def _rendered_paths(views) -> list:
    """Filter a list of view-output dicts down to successfully rendered paths."""
    paths = []
    for view in views or []:
        if isinstance(view, dict) and view.get("rendered") and view.get("output_path"):
            paths.append(view["output_path"])
    return paths


def _collect_view_paths(report_dict: dict) -> list:
    """Pull rendered PNG paths out of an assembly report's meta block.

    Each assembly entry point nests its views differently:
      render_review_views  -> meta.review_views
      check_round          -> meta.render.review_views
      inspect_component    -> meta.rendered_views
      render_sequence      -> meta.steps[*].review_views
    """
    meta = report_dict.get("meta") or {}
    paths = []

    paths.extend(_rendered_paths(meta.get("review_views")))
    paths.extend(_rendered_paths((meta.get("render") or {}).get("review_views")))
    paths.extend(_rendered_paths(meta.get("rendered_views")))

    for step in meta.get("steps") or []:
        paths.extend(_rendered_paths((step or {}).get("review_views")))

    # de-duplicate while preserving order
    seen = set()
    unique = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _attach_images(result: dict, return_images: bool) -> dict:
    """Mark a report's rendered views for inline return, within budget."""
    paths = _collect_view_paths(result)
    result["rendered_view_count"] = len(paths)
    if not return_images or not paths:
        return result
    result[_IMAGES_KEY] = paths[:MAX_INLINE_IMAGES]
    if len(paths) > MAX_INLINE_IMAGES:
        result["inline_images_truncated"] = {
            "shown": MAX_INLINE_IMAGES,
            "total": len(paths),
            "note": (
                "All views were written to disk; only the first "
                f"{MAX_INLINE_IMAGES} are inlined. Open the rest from "
                "views_dir."
            ),
        }
    return result


def _image_content_blocks(paths: list) -> list:
    """Read PNGs and return them as MCP image content blocks."""
    blocks = []
    for path in paths:
        try:
            size = os.path.getsize(path)
            if size > MAX_IMAGE_BYTES:
                blocks.append({
                    "type": "text",
                    "text": f"[{path} omitted: {size} bytes exceeds inline cap]",
                })
                continue
            with open(path, "rb") as handle:
                data = base64.b64encode(handle.read()).decode("ascii")
            blocks.append({
                "type": "image",
                "data": data,
                "mimeType": "image/png",
            })
        except Exception as exc:  # a missing render must not kill the response
            blocks.append({"type": "text", "text": f"[{path} unreadable: {exc}]"})
    return blocks


def tool_assemble_validate_spec(spec: str, release: bool = False) -> dict:
    """Validate an assembly spec (schema + declared paths) without compiling."""
    return validate_assembly_spec(spec, release=release).to_dict()


def tool_assemble_build(spec: str, connector_metadata: str = None,
                        dry_run: bool = False,
                        write_design_inventory: bool = False) -> dict:
    """Resolve authored STEP sources and compile the assembly."""
    return run_assembly_build(
        spec,
        connector_metadata_path=connector_metadata,
        dry_run=dry_run,
        write_inventory=write_design_inventory,
    ).to_dict()


def tool_assemble_check_round(spec: str, connector_metadata: str = None,
                              dry_run: bool = False,
                              render_views: bool = True,
                              write_inventory: bool = True,
                              write_report: bool = False,
                              return_images: bool = True) -> dict:
    """Build, inventory-check, render review views, and report one round.

    This is the main iteration loop: edit the spec, call this, look at the
    returned renders, fix what is wrong, repeat.
    """
    report = run_assembly_check_round(
        spec,
        connector_metadata_path=connector_metadata,
        dry_run=dry_run,
        render_views=render_views,
        write_inventory=write_inventory,
        write_report=write_report,
    )
    return _attach_images(report.to_dict(), return_images)


def tool_assemble_inspect_component(spec: str, component_id: str = None,
                                    source_path: str = None,
                                    render_views: bool = False,
                                    views: str = "front,side,top,iso",
                                    views_dir: str = None,
                                    return_images: bool = True) -> dict:
    """Inspect one authored STEP component: signatures, part count, views."""
    if not component_id and not source_path:
        return {"error": "provide either component_id or source_path"}
    view_names = [v.strip() for v in views.split(",") if v.strip()]
    report = inspect_component(
        spec,
        component_id=component_id,
        source_path=source_path,
        render_views=render_views,
        views=view_names,
        views_dir=views_dir,
    )
    return _attach_images(report.to_dict(), return_images and render_views)


def tool_assemble_render_views(spec: str, step: str = None,
                               views_dir: str = None,
                               return_images: bool = True) -> dict:
    """Render the review_views declared by an assembly spec.

    The visual-review step: renders the assembly from the declared angles and
    hands the images back so they can be checked against the design intent.
    """
    report = render_review_views(spec, step_path=step, views_dir=views_dir)
    return _attach_images(report.to_dict(), return_images)


def tool_assemble_render_sequence(spec: str, output_dir: str = None,
                                  views: str = "front,side,top,hero,iso",
                                  dry_run: bool = False,
                                  render_views: bool = True,
                                  rotate_final: bool = False,
                                  bom_csv: str = None,
                                  write_bom: bool = True,
                                  return_images: bool = True) -> dict:
    """Export partial assembly STEPs, per-step views, and a BOM CSV."""
    view_names = [v.strip() for v in views.split(",") if v.strip()]
    report = run_assembly_sequence(
        spec,
        output_dir=output_dir,
        view_names=view_names,
        dry_run=dry_run,
        render_views=render_views,
        rotate_final=rotate_final,
        bom_csv_path=bom_csv,
        write_bom=write_bom,
    )
    return _attach_images(report.to_dict(), return_images)


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
        "description": "Find solid-solid overlaps between assembly parts using exact BRep boolean intersection. Reports overlap volume in mm^3 plus a per-clip suggested fix shift (axis, signed mm, clearance) along the cheapest bbox-overlap axis.",
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
                "min_clearance_mm": {
                    "type": "number",
                    "description": "Running clearance added to the suggested fix-shift (default 1.0). The shift = overlap_on_axis + min_clearance_mm.",
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
        "description": "Run the environment doctor: Python, venv, dependencies, MCP self-check, repo signals.",
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
        "description": "Compare two STEP files by dim-signature inventory. Detects parts present in one but not the other, plus hidden/suppressed-part export drift (file shrinks but unique signatures grow).",
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
    {
        "name": "assemble_validate_spec",
        "description": "Validate an assembly spec (schema plus the presence of every path it references) without compiling geometry. Run this before assemble_build. Set release=true to turn required-for-release not_built_yet items into failures.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "string", "description": "Path to the assembly spec YAML"},
                "release": {"type": "boolean", "description": "Treat required not_built_yet items as release-blocking failures"},
            },
            "required": ["spec"],
        },
    },
    {
        "name": "assemble_build",
        "description": "Resolve authored STEP sources declared by an assembly spec and compile them into a STEP assembly with CadQuery. Parts are seated by connector frames and datum chains. Use dry_run=true to resolve and report paths without importing or exporting geometry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "string", "description": "Path to the assembly spec YAML"},
                "connector_metadata": {"type": "string", "description": "Optional connector metadata YAML with local frames and mates"},
                "dry_run": {"type": "boolean", "description": "Resolve paths only; do not import or export geometry"},
                "write_design_inventory": {"type": "boolean", "description": "Write spec.outputs.design_inventory with the resolved instances"},
            },
            "required": ["spec"],
        },
    },
    {
        "name": "assemble_check_round",
        "description": "The main assembly iteration loop: build the assembly, run the inventory and placement checks, render the declared review views, and return one combined report. Returns the renders as inline images so you can visually confirm the build matches design intent before continuing. Edit the spec, call this, look at the images, fix, repeat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "string", "description": "Path to the assembly spec YAML"},
                "connector_metadata": {"type": "string", "description": "Optional connector metadata YAML"},
                "dry_run": {"type": "boolean", "description": "Resolve and check the spec without importing or exporting geometry"},
                "render_views": {"type": "boolean", "description": "Render the review views after a successful build (default true)"},
                "write_inventory": {"type": "boolean", "description": "Write the design inventory during the round (default true)"},
                "write_report": {"type": "boolean", "description": "Write the round report to spec.outputs.report when declared"},
                "return_images": {"type": "boolean", "description": "Return rendered views as inline images (default true)"},
            },
            "required": ["spec"],
        },
    },
    {
        "name": "assemble_inspect_component",
        "description": "Inspect a single authored STEP component referenced by an assembly spec: bounding-box signatures, part count, and optional isolated review renders. Use this to confirm what a part actually looks like and how it is oriented before placing it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "string", "description": "Path to the assembly spec YAML"},
                "component_id": {"type": "string", "description": "Component id to resolve from the spec manifests"},
                "source_path": {"type": "string", "description": "Direct authored STEP path to resolve instead of a component id"},
                "render_views": {"type": "boolean", "description": "Render isolated component review views"},
                "views": {"type": "string", "description": "Comma-separated views to render, e.g. front,side,top,iso"},
                "views_dir": {"type": "string", "description": "Optional output directory for the component views"},
                "return_images": {"type": "boolean", "description": "Return rendered views as inline images (default true)"},
            },
            "required": ["spec"],
        },
    },
    {
        "name": "assemble_render_views",
        "description": "Render the review_views declared by an assembly spec and return them as inline images. This is the visual-review step: it produces the PNG traceability artifacts on disk and lets you see the current state of the assembly from the declared angles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "string", "description": "Path to the assembly spec YAML"},
                "step": {"type": "string", "description": "Optional STEP path to render; defaults to spec.outputs.step"},
                "views_dir": {"type": "string", "description": "Optional output directory; defaults to spec.outputs.views_dir"},
                "return_images": {"type": "boolean", "description": "Return rendered views as inline images (default true)"},
            },
            "required": ["spec"],
        },
    },
    {
        "name": "assemble_render_sequence",
        "description": "Export the step-by-step assembly sequence: a partial STEP per build step, per-step review renders, and a BOM CSV. Produces the human-auditable record of how the machine goes together, and optionally a rotating GIF of the finished assembly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "string", "description": "Path to the assembly spec YAML"},
                "output_dir": {"type": "string", "description": "Directory for sequence STEPs, images, and manifest"},
                "views": {"type": "string", "description": "Comma-separated review views to render per step"},
                "dry_run": {"type": "boolean", "description": "Report the sequence and BOM without exporting STEP or PNG files"},
                "render_views": {"type": "boolean", "description": "Render per-step PNGs (default true)"},
                "rotate_final": {"type": "boolean", "description": "Render a rotating GIF from the completed sequence assembly"},
                "bom_csv": {"type": "string", "description": "Optional BOM CSV output path"},
                "write_bom": {"type": "boolean", "description": "Generate the BOM CSV (default true)"},
                "return_images": {"type": "boolean", "description": "Return rendered views as inline images (default true)"},
            },
            "required": ["spec"],
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
    "assemble_validate_spec": lambda args: tool_assemble_validate_spec(**args),
    "assemble_build": lambda args: tool_assemble_build(**args),
    "assemble_check_round": lambda args: tool_assemble_check_round(**args),
    "assemble_inspect_component": lambda args: tool_assemble_inspect_component(**args),
    "assemble_render_views": lambda args: tool_assemble_render_views(**args),
    "assemble_render_sequence": lambda args: tool_assemble_render_sequence(**args),
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
                    "version": CADCLAW_VERSION,
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
            # Tool handlers may call cadclaw code that uses print() for
            # user-facing status. Stdout is reserved for the JSON-RPC stream,
            # so redirect any tool prints to stderr.
            with contextlib.redirect_stdout(sys.stderr):
                result = TOOL_HANDLERS[tool_name](tool_args)

            # Render-producing tools flag their PNGs for inline return. Strip
            # the marker before serializing, then append the images as MCP
            # image content so the model can actually look at the build.
            image_paths = []
            if isinstance(result, dict):
                image_paths = result.pop(_IMAGES_KEY, []) or []

            content = [{"type": "text", "text": json.dumps(result, indent=2)}]
            if image_paths:
                content.extend(_image_content_blocks(image_paths))

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": content},
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
    sys.stderr.write(f"CADCLAW MCP Server v{CADCLAW_VERSION} starting...\n")
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
