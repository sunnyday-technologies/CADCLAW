"""Grade a native-track (e.g. Fusion-exported) STEP assembly as a black box.

The native CAD driver exports a single STEP with no CADCLAW roles or transforms.
This wrapper grades it the way the FusionClaw write-up frames verification
"bolted on at the end": load the STEP, label each solid by its bbox signature,
and run the host-agnostic gates a raw export can actually support --

  * inventory   (right count of each part type, by bbox signature)
  * interference (solid clips, skipping rolling/belt contacts)
  * floating     (parts disconnected from the structural frame)

The per-instance role gates (vslot stackup, hole/wheel alignment, frame
adjacency) stay on the CADCLAW-spec track. Requiring a native exporter to emit
CADCLAW roles/transforms would contaminate the comparison, so the native track
is graded only on what the geometry itself proves.

Expected inventory and the signature -> label map are derived from the shared
reference spec, so both tracks are graded against the same target. The output
report uses the same schema as run_grader.py, so score_report.py scores both
tracks on one rubric.

  .venv\\Scripts\\python.exe benchmarks\\m3_ai_assembly\\scripts\\grade_native_step.py \\
    --step <fusion_export.step> \\
    --out benchmarks\\m3_ai_assembly\\results\\native_cad_driver_report.json
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import time
from collections import Counter
from pathlib import Path

import cadquery as cq
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cadclaw import __version__ as CADCLAW_VERSION  # noqa: E402
from cadclaw.assembly_compiler import plan_assembly_build  # noqa: E402
from cadclaw.harness import Harness  # noqa: E402
from cadclaw.inventory import load_and_dedup, sig  # noqa: E402

DEFAULT_BENCHMARK = REPO_ROOT / "benchmarks" / "m3_ai_assembly" / "benchmark.yaml"

# Parts that legitimately ride on / span other parts: skip from interference,
# and exempt from floating (their mounts -- motors, axles -- are not modeled).
ROLLING = {"v_wheel", "pulley", "idler"}
COSMETIC = {"belt"}
# Motors mount to the frame with hardware we do not model (screwed into the
# C-beam slot, seated on the ZPMM spacer). Like wheels and belts they are
# accessories, not structure, and they contact structural parts at their mount
# by design -- so they are skipped from interference and exempt from floating,
# the same treatment the spec track gives the drive_motor role. (The Y motor
# also provides homing via the stepper driver's StallGuard, a sensorless
# firmware feature -- there is no physical endstop part to model or collide.)
_MOTOR_RE = re.compile(r"motor|nema", re.IGNORECASE)


def is_accessory(label: str) -> bool:
    """Drive-train / rolling parts that ride on or mount to structure, and so
    are skipped from interference and exempt from the floating check."""
    return label in ROLLING or label in COSMETIC or bool(_MOTOR_RE.search(label))


def _looks_like_belt(dims) -> bool:
    """A belt reads as a thin, very elongated strap or loop regardless of its
    exact extruded cross-section. A GT2 strap is ~1.5x6; a closed belt loop's
    placed bounding box differs from its modeled one, so match by shape class
    (thinnest dim small, longest dim long) rather than an exact signature."""
    return len(dims) >= 2 and min(dims) <= 6.5 and max(dims) >= 150.0


def solid_label(stem: str, dims) -> str:
    """Label a single solid by authored-part name, falling back to geometry for
    composite parts. VS_Belt_Pinion, for example, imports as one belt loop plus
    one pulley solid; the loop is named-belt, the pulley has no name of its own
    and is recovered from its small-wheel geometry."""
    s = stem.lower()
    ordered = sorted(dims)
    if _looks_like_belt(dims):
        return "belt"
    if "belt" in s and ordered and ordered[-1] >= 150.0:
        return "belt"                      # belt loop as modeled (fat bbox)
    if "solid v wheel" in s:
        return "v_wheel"
    if "idler" in s:
        return "idler"
    if "pulley" in s:
        return "pulley"
    if "gantry plate xlarge" in s:
        return "plate_xlarge"
    if "gantry plate 20-80" in s or "gantry plate 20_80" in s:
        return "plate_2080"
    if "c-beam" in s and "linear rail" in s:
        return "cbeam_4080"
    if "20x80" in s:
        return "vslot_2080"
    if "20x40" in s:
        return "vslot_2040"
    if "zpmm" in s:
        return "spacer_zpmm"
    if "shim" in s:
        return "spacer_flat"
    if _MOTOR_RE.search(s):
        return re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    # Composite-part leftover small drive wheel (e.g. the VS_Belt_Pinion pulley
    # solid): a pulley is a small narrow wheel; an idler is a wider one.
    if ordered and ordered[-1] <= 26.0:
        return "idler" if ordered[len(ordered) // 2] >= 18.0 else "pulley"
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _abs(display_path: str) -> Path:
    p = Path(display_path)
    return p if p.is_absolute() else (REPO_ROOT / display_path).resolve()


def derive_target(spec_path: Path):
    """Build the signature->label map and expected counts from the spec.

    Enumerates EVERY solid of each authored part, not just the first, so a
    composite drive part (e.g. VS_Belt_Pinion = one belt loop + one pulley)
    contributes both of its solids to the expected inventory the same way the
    graded STEP's loader will see them."""
    plan = plan_assembly_build(spec_path, dry_run=True)
    sig_to_label: dict[tuple, str] = {}
    expected: Counter = Counter()
    solids_cache: dict[str, list] = {}
    collisions: list[str] = []
    missing: list[str] = []
    for inst in plan.instances:
        if not inst.exists:
            missing.append(inst.id)
            continue
        rp = inst.resolved_path
        if rp not in solids_cache:
            stem = Path(rp).stem
            solids_cache[rp] = [
                (sig(solid), solid_label(stem, sig(solid)))
                for solid in cq.importers.importStep(str(_abs(rp))).solids().vals()
            ]
        for s, label in solids_cache[rp]:
            if s in sig_to_label and sig_to_label[s] != label:
                collisions.append(f"{s}: {sig_to_label[s]} vs {label}")
                label = sig_to_label[s]
            sig_to_label[s] = label
            expected[label] += 1
    return sig_to_label, dict(expected), missing, collisions


def observed_inventory(step_path: Path, sig_to_label: dict) -> dict:
    counts: Counter = Counter()
    for solid in load_and_dedup(str(step_path)):
        d = sig(solid)
        if d in sig_to_label:
            counts[sig_to_label[d]] += 1
        elif _looks_like_belt(d):
            counts["belt"] += 1
        else:
            counts["other"] += 1
    return dict(counts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Grade a native-track STEP as a black box.")
    ap.add_argument("--step", required=True, help="Native (e.g. Fusion) STEP export to grade.")
    ap.add_argument("--spec", default=None,
                    help="Reference spec for expected inventory; defaults to benchmark seed.")
    ap.add_argument("--benchmark", default=str(DEFAULT_BENCHMARK))
    ap.add_argument("--out", default=None)
    ap.add_argument("--render-views", action=argparse.BooleanOptionalAction, default=None,
                    help="Render review views of the submitted STEP for human/AI review "
                         "(defaults to benchmark grader.default_render_views).")
    args = ap.parse_args(argv)

    t0 = time.time()
    benchmark = yaml.safe_load(Path(args.benchmark).read_text(encoding="utf-8")) or {}
    seeds = benchmark.get("seeds", {})
    spec_path = Path(args.spec) if args.spec else (REPO_ROOT / seeds.get("assembly_spec", ""))
    step_path = Path(args.step)
    if not step_path.exists():
        print(f"STEP not found: {step_path}")
        return 1

    sig_to_label, expected, missing, collisions = derive_target(spec_path)

    # Augment the label map with thin/elongated solids present in the GRADED
    # STEP that the modeled-part signatures missed -- e.g. a closed belt loop
    # whose placed bounding box differs from its modeled one -- so they label as
    # 'belt' and are skipped from interference like every other belt.
    for solid in load_and_dedup(str(step_path)):
        d = sig(solid)
        if d not in sig_to_label and _looks_like_belt(d):
            sig_to_label[d] = "belt"

    accessory = {lbl for lbl in set(sig_to_label.values()) if is_accessory(lbl)}
    structural = sorted(set(sig_to_label.values()) - accessory)

    harness = Harness(str(step_path))
    harness.set_labels(sig_to_label)
    harness.add_inventory(labels=sig_to_label, expected=expected)
    harness.add_interference(skip_labels=set(accessory), min_volume=1.0, min_clearance_mm=1.0)
    harness.add_floating_check(structural_labels=set(structural), max_gap_mm=5.0,
                               exempt_labels=set(accessory))
    hr = harness.run()

    observed = observed_inventory(step_path, sig_to_label)

    # Review views: render the submitted STEP so a blind native run leaves a
    # reviewable visual artifact (otherwise the only output is the JSON report).
    # Best-effort and never fails the grade. The native track exports a single
    # STEP, so these are the only record of the assembly's geometry/positions.
    grader_cfg = benchmark.get("grader", {}) if isinstance(benchmark, dict) else {}
    render_views = (
        bool(grader_cfg.get("default_render_views", False))
        if args.render_views is None else args.render_views
    )
    review_views: list[str] = []
    if render_views and args.out:
        try:
            from cadclaw.render import render_step_to_png
            views_dir = Path(args.out).parent / f"{Path(args.out).stem}_views"
            views_dir.mkdir(parents=True, exist_ok=True)
            for view in ("iso", "front", "side", "top", "iso_below"):
                png = views_dir / f"{step_path.stem}_{view}.png"
                render_step_to_png(str(step_path), str(png), view=view)
                review_views.append(png.as_posix())
            print(f"wrote {len(review_views)} review views -> {views_dir}")
        except Exception as exc:  # rendering is best-effort; never fail the grade
            print(f"review render skipped: {exc}")
    elif render_views and not args.out:
        print("review render skipped: --out is required to place review views")

    report = hr.report
    report.meta = dict(report.meta or {})
    report.meta.update({
        "track": "native_cad_driver",
        "expected_inventory": expected,
        "observed_inventory": observed,
    })

    normalized = {
        "schema_version": "m3_ai_assembly_grader_report.v0.1",
        "benchmark_id": benchmark.get("benchmark_id", "m3_ai_assembly"),
        "benchmark_status": benchmark.get("status", "unknown"),
        "track": "native_cad_driver",
        "target": benchmark.get("target", {}),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cadclaw_version": CADCLAW_VERSION,
            "elapsed_ms": round((time.time() - t0) * 1000, 3),
        },
        "inputs": {
            "benchmark": Path(args.benchmark).as_posix(),
            "step": step_path.as_posix(),
            "spec_for_expected_inventory": spec_path.as_posix(),
        },
        "native_summary": {
            "total_parts": hr.total_parts,
            "passed": hr.passed,
            "gates": [{"name": g.name, "passed": g.passed} for g in hr.gates],
            "expected_inventory": expected,
            "observed_inventory": observed,
            "signature_label_collisions": collisions,
            "unresolved_spec_instances": missing,
        },
        "cadclaw_report": report.to_dict(),
    }

    body = json.dumps(normalized, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body + "\n", encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(body)
    print(f"\nnative grade: passed={hr.passed} parts={hr.total_parts} "
          f"gates={[(g.name, g.passed) for g in hr.gates]}")
    if collisions:
        print(f"signature/label collisions: {collisions}")
    return 0


if __name__ == "__main__":
    try:  # avoid cp1252 mojibake of fix-vector arrows (->) on Windows stdout
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
