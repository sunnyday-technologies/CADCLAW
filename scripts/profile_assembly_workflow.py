"""Deterministic offline assembly/review diagnostic using an existing STEP.

Timing is evidence, never a test assertion. Output belongs in a local evidence
directory: this script imports authored inputs and creates no source geometry.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import ctypes
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def _hash_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _resident_bytes():
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
                )
            ]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess
        process.restype = ctypes.c_void_p
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if get_memory(process(), ctypes.byref(counters), counters.cb):
            return counters.WorkingSetSize
    return None


def _code_snapshot(root):
    paths = sorted([*(root / "cadclaw").rglob("*.py"), *(root / "cadclaw_mcp").rglob("*.py")])
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--code-root", type=Path, default=ROOT, help="Measure this checkout with the same runner/workload")
    parser.add_argument("--source", type=Path, default=ROOT / "tests/fixtures/pmi_semantic/nist_ftc_11_asme1_ap242-e2.stp")
    parser.add_argument("--copies", type=int, default=6)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--skip-cameras", action="store_true", help="Measure source reuse before camera optimization")
    parser.add_argument("--overlap", action="store_true", help="Include a positive exact-intersection control using authored shapes")
    args = parser.parse_args()
    code_root = args.code_root.resolve(strict=True)
    source = args.source.resolve(strict=True)
    source_sha256_before = hashlib.sha256(source.read_bytes()).hexdigest()
    source_bytes_before = source.stat().st_size
    runner_sha256_before = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    sys.path.insert(0, str(code_root))
    code_before = _code_snapshot(code_root)
    commit_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=code_root, text=True).strip()
    dirty_before = subprocess.check_output(["git", "status", "--porcelain"], cwd=code_root, text=True).splitlines()
    setup_started = time.perf_counter()
    import cadquery as cq
    import yaml
    from cadclaw import assembly_compiler as compiler
    from cadclaw import render
    from OCP import BRepAlgoAPI

    if Path(compiler.__file__).resolve() != code_root / "cadclaw/assembly_compiler.py":
        raise RuntimeError("profiler imported a different code root")

    args.output.mkdir(parents=True, exist_ok=True)
    work = args.output / args.label
    work.mkdir(exist_ok=True)
    spec_path = work / "workload.yaml"
    output_step = work / "assembly.step"
    # Widely separated occurrences keep the interference control deterministic.
    spec = {
        "schema_version": "assembly_spec.v0.1",
        "meta": {"project": "Offline profiling fixture", "assembly_id": "repeated-authored-source"},
        "outputs": {"step": output_step.as_posix(), "views_dir": (work / "views").as_posix(),
                    "design_inventory": (work / "inventory.json").as_posix()},
        "validation": {"run_checks": ["inventory", "interference"], "expected_inventory": {"fixture": args.copies}},
        "review_views": [{"name": view, "view": view, "width": 320, "height": 240}
                         for view in ("iso", "front", "top")],
        "instances": [{"id": f"fixture_{index}", "role": "fixture", "source_path": source.as_posix(),
                       "transform": {"translate_mm": [index * 400.0, 0, 0], "rotate_deg": [0, 0, index * 10.0]}}
                      for index in range(args.copies)],
    }
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    if args.overlap:
        if args.copies < 2:
            raise ValueError("overlap control requires two or more copies")
        spec["instances"][1]["transform"] = {"translate_mm": [0, 1, 0], "rotate_deg": [0, 0, 0]}
        spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    setup_seconds = time.perf_counter() - setup_started
    counts = Counter()
    stages = defaultdict(float)

    def instrument(owner, name, count_name=None):
        original = getattr(owner, name)
        def wrapped(*a, **kw):
            counts[count_name or name] += 1
            started = time.perf_counter()
            try:
                return original(*a, **kw)
            finally:
                stages[count_name or name] += time.perf_counter() - started
        setattr(owner, name, wrapped)
        return original

    original_import = instrument(cq.importers, "importStep", "step_imports")
    instrument(cq.Shape, "toVtkPolyData", "tessellations")
    original_common = BRepAlgoAPI.BRepAlgoAPI_Common
    class MeasuredCommon:
        def __init__(self, *a, **kw):
            counts["exact_common_operations"] += 1
            started = time.perf_counter()
            try:
                self.native = original_common(*a, **kw)
            finally:
                stages["exact_common_constructor"] += time.perf_counter() - started
        def Build(self, *a, **kw):
            counts["exact_common_builds"] += 1
            started = time.perf_counter()
            try:
                return self.native.Build(*a, **kw)
            finally:
                stages["exact_common_build"] += time.perf_counter() - started
        def __getattr__(self, name):
            return getattr(self.native, name)
    BRepAlgoAPI.BRepAlgoAPI_Common = MeasuredCommon
    for name in ("_export_step", "_placed_instance_shapes", "_run_spec_interference", "render_review_views"):
        instrument(compiler, name)
    instrument(render, "_extract_step_colors", "step_color_reads")
    records = []

    def measure(scenario, iteration, action):
        counts.clear()
        stages.clear()
        peak = [_resident_bytes()]
        stop = threading.Event()
        def sample():
            while not stop.wait(0.01):
                value = _resident_bytes()
                if value is not None:
                    peak[0] = max(peak[0] or 0, value)
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        started = time.perf_counter()
        try:
            report = action()
        finally:
            wall_seconds = time.perf_counter() - started
            stop.set()
            sampler.join()
        measured_counts, measured_stages = dict(counts), dict(stages)
        # Independent exported geometry measurement is outside the timed action.
        compound = original_import(str(output_step)).val() if output_step.exists() else None
        geometry = sorted([
            {"bounds": [round(v, 5) for v in (s.BoundingBox().xmin, s.BoundingBox().ymin,
                        s.BoundingBox().zmin, s.BoundingBox().xmax, s.BoundingBox().ymax, s.BoundingBox().zmax)],
             "volume": round(s.Volume(), 5), "area": round(s.Area(), 5),
             "center": [round(v, 5) for v in s.Center().toTuple()], "valid": s.isValid()}
            for s in compound.Solids()
        ], key=lambda v: v["bounds"]) if compound else []
        payload = report.to_dict() if hasattr(report, "to_dict") else {}
        semantic = {"findings": payload.get("findings"), "overall": payload.get("overall"),
                    "role_inventory": payload.get("meta", {}).get("role_inventory"),
                    "validation": payload.get("meta", {}).get("validation"), "geometry": geometry}
        images = {}
        from PIL import Image
        for png in sorted((work / "views").glob("*.png")):
            with Image.open(png) as image:
                colors = image.convert("RGB").getcolors(image.width * image.height)
                images[png.name] = {"bytes": png.stat().st_size,
                                    "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
                                    "unique_colors": len(colors), "size": list(image.size)}
        inventory = json.loads((work / "inventory.json").read_text()) if (work / "inventory.json").exists() else {}
        records.append({"scenario": scenario, "iteration": iteration, "wall_seconds": wall_seconds,
                        "peak_resident_bytes_sampled": peak[0], "counts": measured_counts,
                        "stage_seconds_inclusive": measured_stages, "semantic": semantic,
                        "semantic_sha256": _hash_json(semantic),
                        "inventory_instances_sha256": _hash_json(inventory.get("instances")),
                        "candidate_pairs": payload.get("meta", {}).get("validation", {}).get("interference", {}).get("checked_pairs"),
                        "step_bytes": output_step.stat().st_size if output_step.exists() else 0,
                        "step_sha256": hashlib.sha256(output_step.read_bytes()).hexdigest() if output_step.exists() else None,
                        "images": images})
        print(json.dumps({key: records[-1][key] for key in ("scenario", "iteration", "wall_seconds", "counts", "semantic_sha256")}), flush=True)

    measure("cold_source_load", 0, lambda: cq.importers.importStep(str(source)))
    check = lambda: compiler.run_assembly_check_round(spec_path, render_views=False)
    # The first operation is cold geometry; later calls are independent warm rounds.
    for iteration in range(args.repetitions):
        measure("unchanged_round", iteration, check)
    spec["instances"][-1]["transform"]["translate_mm"][1] = 30.0
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    for iteration in range(args.repetitions):
        measure("placement_change_round", iteration, check)
    if not args.skip_cameras:
        for iteration in range(args.repetitions):
            measure("camera_only_three_views", iteration, lambda: compiler.render_review_views(spec_path))
    code_after = _code_snapshot(code_root)
    code_changed = sorted(key for key in set(code_before) | set(code_after) if code_before.get(key) != code_after.get(key))
    try:
        source_sha256_after = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError:
        source_sha256_after = None
    runner_sha256_after = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    source_changed = source_sha256_before != source_sha256_after
    runner_changed = runner_sha256_before != runner_sha256_after
    result = {"schema": "cadclaw-workflow-profile.v0.1", "label": args.label,
              "code_root": str(code_root), "commit": commit_before, "dirty_before": dirty_before,
              "code_sha256_before": code_before, "code_sha256_after": code_after,
              "code_changed_during_measurement": code_changed,
              "measurement_valid": not (code_changed or source_changed or runner_changed),
              "runner_sha256": runner_sha256_before, "runner_sha256_after": runner_sha256_after,
              "runner_changed_during_measurement": runner_changed,
              "source": {"path": str(source), "sha256": source_sha256_before, "bytes": source_bytes_before,
                         "sha256_after": source_sha256_after, "changed_during_measurement": source_changed},
              "runtime": {"python": platform.python_version(), **{name: importlib.metadata.version(name)
                          for name in ("cadquery", "cadquery-ocp", "vtk", "numpy")}},
              "copies": args.copies, "repetitions": args.repetitions, "setup_seconds": setup_seconds,
              "positive_overlap_control": args.overlap,
              "memory_method": "10ms process working-set sampling; native allocations included",
              "stage_note": "stage timings are inclusive and can overlap; exported parity reads excluded",
              "fixture_note": "Existing shipped authored NIST STEP; no geometry authored by this script",
              "records": records}
    (args.output / f"{args.label}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if code_changed or source_changed or runner_changed:
        raise RuntimeError("measured code, runner or source changed; timing evidence is invalid")


if __name__ == "__main__":
    main()
