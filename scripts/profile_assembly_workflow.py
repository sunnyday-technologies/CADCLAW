"""Deterministic offline assembly/review diagnostic using an existing STEP.

Timing is evidence, never a test assertion. Output belongs in a local evidence
directory: this script imports authored inputs and creates no source geometry.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
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



class _CallInstrumentation:
    """Attempt/return/exception accounting; returned does not mean geometry passed."""

    def __init__(self, clock=None):
        self.clock = clock or time.perf_counter
        self.counts = Counter()
        self.stages = defaultdict(float)
        self.outcomes = {}
        self.patches = []

    def reset(self):
        self.counts.clear()
        self.stages.clear()
        self.outcomes.clear()

    def call(self, name, action, *, stage=None):
        self.counts[name] += 1
        outcome = self.outcomes.setdefault(name, {"attempted": 0, "returned": 0, "failed": 0})
        outcome["attempted"] += 1
        started = self.clock()
        try:
            result = action()
        except BaseException:
            outcome["failed"] += 1
            raise
        else:
            outcome["returned"] += 1
            return result
        finally:
            self.stages[stage or name] += self.clock() - started

    def replace(self, owner, name, replacement):
        original = getattr(owner, name)
        self.patches.append((owner, name, original))
        setattr(owner, name, replacement)
        return original

    def instrument(self, owner, name, count_name=None):
        original = getattr(owner, name)
        def wrapped(*args, **kwargs):
            return self.call(count_name or name, lambda: original(*args, **kwargs))
        self.replace(owner, name, wrapped)
        return original

    def restore(self):
        for owner, name, original in reversed(self.patches):
            setattr(owner, name, original)
        self.patches.clear()


def _measure_action(action, instrumentation, *, resident_bytes=None, clock=None):
    """Always close the sampler and return an error receipt without exception text."""
    resident_bytes = resident_bytes or _resident_bytes
    clock = clock or time.perf_counter
    instrumentation.reset()
    peak = [resident_bytes()]
    stop = threading.Event()
    def sample():
        while not stop.wait(0.01):
            value = resident_bytes()
            if value is not None:
                peak[0] = max(peak[0] or 0, value)
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    started = clock()
    report = None
    error = None
    try:
        report = action()
    except BaseException as exc:
        error = {"phase": "measured_action", "exception_type": type(exc).__name__}
    finally:
        wall_seconds = clock() - started
        stop.set()
        sampler.join()
    record = {
        "status": "error" if error else "completed",
        "wall_seconds": wall_seconds,
        "peak_resident_bytes_sampled": peak[0],
        "counts": dict(instrumentation.counts),
        "call_outcomes": deepcopy(instrumentation.outcomes),
        "stage_seconds_inclusive": dict(instrumentation.stages),
        "cache_state": {"python_process": "already_initialized", "os_file_cache": "unknown",
                        "persistent_cache_enabled_by_profiler": False},
    }
    if error:
        record["error"] = error
    return report, record


def _returned_metadata(payload):
    """Copy compiler coverage verbatim; callable return is not a completed exact check."""
    meta = payload.get("meta") or {}
    interference = (meta.get("validation") or {}).get("interference")
    return {
        "interference_completion": deepcopy(interference) if interference is not None else {
            "status": "unavailable", "reason": "no_interference_metadata_returned"},
        "geometry_cache": deepcopy(meta.get("geometry_cache")),
        "candidate_pairs": interference.get("checked_pairs") if isinstance(interference, dict) else None,
        "candidate_pairs_basis": "legacy checked_pairs field; attempted native pairs, not completed pairs",
    }


def _write_failure_receipt(path, context, records, exc):
    """Preserve consumed work without emitting exception messages or arguments."""
    receipt = {**context, "complete": False, "measurement_valid": False,
               "status": "error", "error": {"exception_type": type(exc).__name__},
               "records": records}
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


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
    instrumentation = _CallInstrumentation()
    instrument = instrumentation.instrument
    records = []
    context = {
        "schema": "cadclaw-workflow-profile.v0.2", "label": args.label,
        "code_root": str(code_root), "commit": commit_before, "dirty_before": dirty_before,
        "code_sha256_before": code_before, "runner_sha256": runner_sha256_before,
        "source": {"path": str(source), "sha256": source_sha256_before, "bytes": source_bytes_before},
        "runtime": {"python": platform.python_version(), **{name: importlib.metadata.version(name)
                    for name in ("cadquery", "cadquery-ocp", "vtk", "numpy")}},
        "environment": {"platform": platform.platform(), "machine": platform.machine(),
                        "processor": platform.processor() or None, "logical_cpus": os.cpu_count(),
                        "cpu_contention": "not_measured", "os_file_cache": "unknown"},
        "call_outcome_note": "counts are attempts; returned means callable returned; failed means raised, not geometric failure",
    }
    receipt_path = args.output / f"{args.label}.json"

    try:
        original_import = instrument(cq.importers, "importStep", "step_imports")
        instrument(cq.Shape, "toVtkPolyData", "tessellations")
        original_common = BRepAlgoAPI.BRepAlgoAPI_Common
        class MeasuredCommon:
            def __init__(self, *a, **kw):
                self.native = instrumentation.call("exact_common_operations", lambda: original_common(*a, **kw),
                                                   stage="exact_common_constructor")
            def Build(self, *a, **kw):
                return instrumentation.call("exact_common_builds", lambda: self.native.Build(*a, **kw),
                                            stage="exact_common_build")
            def __getattr__(self, name):
                return getattr(self.native, name)
        instrumentation.replace(BRepAlgoAPI, "BRepAlgoAPI_Common", MeasuredCommon)
        for name in ("_export_step", "_placed_instance_shapes", "_run_spec_interference", "render_review_views"):
            instrument(compiler, name)
        instrument(render, "_extract_step_colors", "step_color_reads")

        def measure(scenario, iteration, action):
            report, record = _measure_action(action, instrumentation)
            record.update({"scenario": scenario, "iteration": iteration,
                           "workload_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest()})
            records.append(record)
            if record["status"] == "error":
                raise RuntimeError("measured action failed; safe error metadata is preserved")
            payload = report.to_dict() if hasattr(report, "to_dict") else {}
            record.update(_returned_metadata(payload))
            # Independent exported geometry measurement is outside the timed action.
            compound = original_import(str(output_step)).val() if output_step.exists() else None
            geometry = sorted([
                {"bounds": [round(v, 5) for v in (s.BoundingBox().xmin, s.BoundingBox().ymin,
                            s.BoundingBox().zmin, s.BoundingBox().xmax, s.BoundingBox().ymax, s.BoundingBox().zmax)],
                 "volume": round(s.Volume(), 5), "area": round(s.Area(), 5),
                 "center": [round(v, 5) for v in s.Center().toTuple()], "valid": s.isValid()}
                for s in compound.Solids()
            ], key=lambda v: v["bounds"]) if compound else []
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
            record.update({"semantic": semantic, "semantic_sha256": _hash_json(semantic),
                           "inventory_instances_sha256": _hash_json(inventory.get("instances")),
                           "step_bytes": output_step.stat().st_size if output_step.exists() else 0,
                           "step_sha256": hashlib.sha256(output_step.read_bytes()).hexdigest() if output_step.exists() else None,
                           "images": images})
            print(json.dumps({key: records[-1][key] for key in ("scenario", "iteration", "wall_seconds", "counts", "semantic_sha256")}), flush=True)

        measure("first_profiled_source_import", 0, lambda: cq.importers.importStep(str(source)))
        check = lambda: compiler.run_assembly_check_round(spec_path, render_views=False)
        # Calls share a Python process; no OS-cache reset or uncontended-CPU state is established.
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
        result = {**context, "complete": True, "status": "completed", "label": args.label,
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
        receipt_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if code_changed or source_changed or runner_changed:
            raise RuntimeError("measured code, runner or source changed; timing evidence is invalid")
    except BaseException as exc:
        if records and records[-1]["status"] != "error":
            records[-1]["evidence_status"] = "error"
            records[-1]["error"] = {"phase": "evidence_or_finalization", "exception_type": type(exc).__name__}
        _write_failure_receipt(receipt_path, locals().get("result", context), records, exc)
        raise RuntimeError("profiling failed; inspect the safe local error receipt") from None
    finally:
        instrumentation.restore()


if __name__ == "__main__":
    main()
