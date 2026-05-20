"""Package the public-safe M3 benchmark/dev-kit scaffold.

This intentionally packages only text seeds, rules, docs, prompts, and helper
scripts. Binary STEP/image/BOM assets are excluded until redistribution review
adds them explicitly to the benchmark asset policy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_ROOT = REPO_ROOT / "benchmarks" / "m3_ai_assembly"
DEFAULT_OUTPUT = REPO_ROOT / "build" / "m3_ai_assembly_testkit.zip"

PACKAGE_PATHS = [
    "benchmarks/m3_ai_assembly/README.md",
    "benchmarks/m3_ai_assembly/benchmark.yaml",
    "benchmarks/m3_ai_assembly/assets/checksums.txt",
    "benchmarks/m3_ai_assembly/assets/source_notes.md",
    "benchmarks/m3_ai_assembly/prompts/standard_prompt.md",
    "benchmarks/m3_ai_assembly/results/.gitkeep",
    "benchmarks/m3_ai_assembly/scripts/run_grader.py",
    "benchmarks/m3_ai_assembly/scripts/score_report.py",
    "benchmarks/m3_ai_assembly/scripts/package_testkit.py",
    "docs/M3_AI_ASSEMBLY_BENCHMARK.md",
    "docs/M3_BOM_PARITY_NOTES.md",
    "examples/m3_crete/m3_reference_assembly.yaml",
    "examples/m3_crete/m3_connector_metadata.yaml",
    "examples/m3_crete/m3_testkit_assets.yaml",
    "examples/m3_crete/m3_bom_audit.yaml",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def iter_package_files(paths: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for rel in paths:
        path = REPO_ROOT / rel
        if not path.exists():
            raise FileNotFoundError(rel)
        if not path.is_file():
            raise ValueError(f"Package path is not a file: {rel}")
        files.append(path)
    return files


def build_package(output: Path) -> dict:
    files = iter_package_files(PACKAGE_PATHS)
    output.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": "m3_ai_assembly_testkit_manifest.v0.1",
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_commit": git_commit(),
        "asset_policy": "text scaffold only; no binary STEP/image/BOM/native CAD assets included",
        "files": [],
    }

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(REPO_ROOT).as_posix()
            digest = sha256(path)
            zf.write(path, rel)
            manifest["files"].append({
                "path": rel,
                "sha256": digest,
                "bytes": path.stat().st_size,
            })
        zf.writestr(
            "benchmarks/m3_ai_assembly/package_manifest.json",
            json.dumps(manifest, indent=2) + "\n",
        )

    return {
        "output": str(output),
        "file_count": len(files),
        "sha256": sha256(output),
        "manifest": manifest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package the public-safe M3 benchmark/dev-kit scaffold."
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT),
        help="Output ZIP path.",
    )
    args = parser.parse_args()
    summary = build_package(Path(args.out))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
