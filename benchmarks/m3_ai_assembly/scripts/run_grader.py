"""Run the M3 AI assembly benchmark grader.

The grader is intentionally thin: it delegates the actual CAD checks to
CADCLAW's assembly check-round and wraps the result with benchmark metadata.
It never prints secret values and does not read environment credentials.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cadclaw import __version__ as CADCLAW_VERSION  # noqa: E402
from cadclaw.assembly_compiler import run_assembly_check_round  # noqa: E402
from cadclaw.findings import Severity  # noqa: E402


DEFAULT_BENCHMARK = REPO_ROOT / "benchmarks" / "m3_ai_assembly" / "benchmark.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _exit_code_for_severity(value: str) -> int:
    if value == Severity.FAIL.value:
        return 1
    if value == Severity.WARN.value:
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the M3 AI assembly CADCLAW grader.")
    p.add_argument("--benchmark", default=str(DEFAULT_BENCHMARK))
    p.add_argument("--spec", default=None,
                   help="Assembly spec to grade; defaults to benchmark seeds.assembly_spec.")
    p.add_argument("--connector-metadata", default=None)
    p.add_argument("--out", default=None,
                   help="Write normalized JSON report to this path.")
    p.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=None,
                   help="Resolve and grade without STEP export/rendering.")
    p.add_argument("--render-views", action=argparse.BooleanOptionalAction, default=None,
                   help="Render review views after a non-dry-run build.")
    p.add_argument("--strict-exit", action="store_true",
                   help="Return CADCLAW severity exit codes instead of 0 on generated reports.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    benchmark_path = Path(args.benchmark)
    benchmark = _load_yaml(benchmark_path)
    seeds = benchmark.get("seeds", {})
    if not isinstance(seeds, dict):
        raise ValueError("benchmark seeds must be a mapping")

    spec_path = Path(args.spec or seeds.get("assembly_spec", ""))
    if not spec_path:
        raise ValueError("--spec or seeds.assembly_spec is required")

    t0 = time.time()
    grader = benchmark.get("grader", {})
    dry_run = (
        bool(grader.get("default_dry_run", False))
        if args.dry_run is None else args.dry_run
    )
    render_views = (
        bool(grader.get("default_render_views", False))
        if args.render_views is None else args.render_views
    )

    report = run_assembly_check_round(
        spec_path,
        connector_metadata_path=args.connector_metadata,
        dry_run=dry_run,
        render_views=render_views,
        write_inventory=True,
        write_report=False,
    )

    normalized = {
        "schema_version": "m3_ai_assembly_grader_report.v0.1",
        "benchmark_id": benchmark.get("benchmark_id", "m3_ai_assembly"),
        "benchmark_status": benchmark.get("status", "unknown"),
        "target": benchmark.get("target", {}),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cadclaw_version": CADCLAW_VERSION,
            "elapsed_ms": round((time.time() - t0) * 1000, 3),
        },
        "inputs": {
            "benchmark": benchmark_path.as_posix(),
            "spec": spec_path.as_posix(),
            "connector_metadata": args.connector_metadata,
        },
        "cadclaw_report": report.to_dict(),
    }

    body = json.dumps(normalized, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body + "\n", encoding="utf-8")
    else:
        print(body)

    if args.strict_exit:
        return _exit_code_for_severity(report.overall.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
