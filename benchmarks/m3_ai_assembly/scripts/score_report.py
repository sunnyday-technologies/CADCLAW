"""Score a normalized M3 AI assembly benchmark report.

This is an early deterministic scorer for development use. It turns CADCLAW
findings into a weighted score while preserving hard-fail conditions for
protected paths, missing sources, non-loadable render inputs, and blocked
generated geometry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BENCHMARK = REPO_ROOT / "benchmarks" / "m3_ai_assembly" / "benchmark.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _cadclaw_report(data: dict[str, Any]) -> dict[str, Any]:
    if "cadclaw_report" in data:
        report = data["cadclaw_report"]
    else:
        report = data
    if not isinstance(report, dict):
        raise ValueError("report JSON must contain an object cadclaw_report or be a report object")
    return report


def _findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings = report.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("cadclaw_report.findings must be a list")
    return [f for f in findings if isinstance(f, dict)]


def _count(findings: list[dict[str, Any]], *, severity: str | None = None,
           category: str | None = None, finding_id: str | None = None) -> int:
    total = 0
    for finding in findings:
        if severity is not None and finding.get("severity") != severity:
            continue
        if category is not None and finding.get("category") != category:
            continue
        if finding_id is not None and finding.get("id") != finding_id:
            continue
        total += 1
    return total


def _bounded(value: float, weight: float) -> float:
    return max(0.0, min(weight, value))


def score_report(report_data: dict[str, Any], benchmark: dict[str, Any]) -> dict[str, Any]:
    report = _cadclaw_report(report_data)
    findings = _findings(report)
    scoring = benchmark.get("scoring", {})
    weights = scoring.get("weights", {}) if isinstance(scoring, dict) else {}
    grader = benchmark.get("grader", {})
    hard_ids = set(grader.get("hard_fail_finding_ids", [])) if isinstance(grader, dict) else set()
    hard_categories = set(grader.get("hard_fail_categories", [])) if isinstance(grader, dict) else set()

    fail_count = _count(findings, severity="fail")
    warn_count = _count(findings, severity="warn")
    not_built_count = _count(findings, finding_id="assemble.not_built_yet")
    generated_blocked = _count(findings, finding_id="assemble.generated_geometry_blocked")
    source_missing = _count(findings, finding_id="assemble.source_missing")
    expected_inventory_mismatch = _count(findings, finding_id="assemble.expected_inventory_mismatch")
    dimensional_failures = _count(findings, category="dimensional", severity="fail")
    claim_failures = (
        _count(findings, category="claim_audit", severity="fail")
        + _count(findings, category="publish_audit", severity="fail")
    )

    hard_fail_findings = [
        finding for finding in findings
        if finding.get("id") in hard_ids or finding.get("category") in hard_categories
    ]

    gate_weight = float(weights.get("cadclaw_gate_results", 35))
    completeness_weight = float(weights.get("completeness_and_authored_asset_fidelity", 25))
    topology_weight = float(weights.get("dimensional_topology_match", 15))
    repro_weight = float(weights.get("reproducibility_and_provenance", 10))
    claims_weight = float(weights.get("claim_hygiene_packaging", 5))

    gate_score = _bounded(gate_weight - fail_count * 10 - warn_count * 1.5, gate_weight)
    completeness_score = _bounded(
        completeness_weight
        - not_built_count * 4
        - generated_blocked * 15
        - source_missing * 10,
        completeness_weight,
    )
    topology_score = _bounded(
        topology_weight
        - expected_inventory_mismatch * 5
        - dimensional_failures * 5,
        topology_weight,
    )

    meta = report.get("meta", {}) if isinstance(report.get("meta", {}), dict) else {}
    dry_run = bool(meta.get("dry_run"))
    build_meta = meta.get("build", {}) if isinstance(meta.get("build"), dict) else {}
    missing_sources = int(build_meta.get("missing_sources", 0) or 0)
    render_meta = meta.get("render", {}) if isinstance(meta.get("render"), dict) else {}
    render_skipped = bool(render_meta.get("skipped"))

    repro_score = repro_weight
    if dry_run:
        repro_score -= 3
    if missing_sources:
        repro_score -= 5
    if render_skipped:
        repro_score -= 1
    repro_score = _bounded(repro_score, repro_weight)

    claims_score = _bounded(claims_weight - claim_failures * 2.5, claims_weight)

    weighted_total = round(
        gate_score
        + completeness_score
        + topology_score
        + repro_score
        + claims_score,
        3,
    )
    hard_failed = bool(hard_fail_findings)
    final_score = 0.0 if hard_failed else weighted_total

    return {
        "schema_version": "m3_ai_assembly_score.v0.1",
        "benchmark_id": benchmark.get("benchmark_id", "m3_ai_assembly"),
        "hard_failed": hard_failed,
        "score": final_score,
        "weighted_score_before_hard_fail": weighted_total,
        "max_score": sum([
            gate_weight,
            completeness_weight,
            topology_weight,
            repro_weight,
            claims_weight,
        ]),
        "subscores": {
            "cadclaw_gate_results": round(gate_score, 3),
            "completeness_and_authored_asset_fidelity": round(completeness_score, 3),
            "dimensional_topology_match": round(topology_score, 3),
            "reproducibility_and_provenance": round(repro_score, 3),
            "claim_hygiene_packaging": round(claims_score, 3),
        },
        "finding_counts": {
            "fail": fail_count,
            "warn": warn_count,
            "not_built_yet": not_built_count,
            "generated_geometry_blocked": generated_blocked,
            "source_missing": source_missing,
            "expected_inventory_mismatch": expected_inventory_mismatch,
        },
        "hard_fail_findings": [
            {
                "id": finding.get("id"),
                "category": finding.get("category"),
                "message": finding.get("message"),
            }
            for finding in hard_fail_findings
        ],
        "limitations": [
            "Early scorer; weights and penalties must be version-pinned with benchmark releases.",
            "Effort/autonomy (interventions, retries, time, tokens) is reported separately from the run log (see summarize_run_log.py), not folded into the artifact score.",
            "Dry-run reports cannot prove STEP loadability or visual alignment.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Score an M3 AI assembly grader report.")
    p.add_argument("report_json")
    p.add_argument("--benchmark", default=str(DEFAULT_BENCHMARK))
    p.add_argument("--out", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_data = json.loads(Path(args.report_json).read_text(encoding="utf-8"))
    benchmark = _load_yaml(Path(args.benchmark))
    score = score_report(report_data, benchmark)
    body = json.dumps(score, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body + "\n", encoding="utf-8")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
