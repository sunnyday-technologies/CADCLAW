"""Summarize M3 AI assembly benchmark run logs.

The summarizer deliberately reads only explicit run-log fields. It does not
estimate tokens, infer secrets, or inspect provider credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int_or_none(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _sum_numeric(values: list[Any]) -> float | None:
    total = 0.0
    found = False
    for value in values:
        number = _number(value)
        if number is None:
            continue
        total += number
        found = True
    return total if found else None


def _token_total(run_tokens: dict[str, Any], attempts: list[dict[str, Any]]) -> int | None:
    direct = _int_or_none(run_tokens.get("total_tokens"))
    if direct is not None:
        return direct
    values: list[Any] = []
    for attempt in attempts:
        tokens = attempt.get("token_usage", {})
        if isinstance(tokens, dict):
            values.append(tokens.get("total_tokens"))
    total = _sum_numeric(values)
    return int(total) if total is not None else None


def _count_corrections(attempts: list[dict[str, Any]]) -> int:
    total = 0
    for attempt in attempts:
        corrections = attempt.get("corrections", [])
        if isinstance(corrections, list):
            total += len(corrections)
    return total


def _count_human_interventions(attempts: list[dict[str, Any]]) -> int:
    total = 0
    for attempt in attempts:
        interventions = attempt.get("human_interventions", [])
        if isinstance(interventions, list):
            total += len(interventions)
    return total


def summarize_run_log(data: dict[str, Any]) -> dict[str, Any]:
    attempts_raw = data.get("attempts", [])
    attempts = [item for item in attempts_raw if isinstance(item, dict)] if isinstance(attempts_raw, list) else []
    timing = data.get("timing", {}) if isinstance(data.get("timing"), dict) else {}
    tokens = data.get("token_usage", {}) if isinstance(data.get("token_usage"), dict) else {}
    summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}

    attempt_count = len(attempts)
    retry_count = sum(1 for attempt in attempts if bool(attempt.get("is_retry")))
    if retry_count == 0 and attempt_count > 1:
        retry_count = attempt_count - 1

    elapsed_minutes = _number(timing.get("elapsed_minutes"))
    if elapsed_minutes is None:
        elapsed_minutes = _sum_numeric([attempt.get("elapsed_minutes") for attempt in attempts])

    checks_run = 0
    failed_checks = 0
    warning_checks = 0
    for attempt in attempts:
        checks = attempt.get("checks_run", [])
        if not isinstance(checks, list):
            continue
        for check in checks:
            if not isinstance(check, dict):
                continue
            checks_run += 1
            result = str(check.get("result", "")).lower()
            if result in {"failed", "fail", "error"}:
                failed_checks += 1
            elif result in {"warning", "warn"}:
                warning_checks += 1

    return {
        "schema_version": "m3_ai_assembly_run_summary.v0.1",
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run_id": data.get("run_id"),
        "benchmark_id": data.get("benchmark_id"),
        "track": data.get("track"),
        "status": data.get("status"),
        "driver": data.get("driver", {}),
        "attempt_count": attempt_count,
        "retry_count": retry_count,
        "correction_count": _int_or_none(summary.get("correction_count")) or _count_corrections(attempts),
        "human_intervention_count": (
            _int_or_none(summary.get("human_intervention_count"))
            or _count_human_interventions(attempts)
        ),
        "checks_run_count": checks_run,
        "failed_check_count": failed_checks,
        "warning_check_count": warning_checks,
        "elapsed_minutes": elapsed_minutes,
        "time_capture_status": timing.get("capture_status"),
        "token_capture_status": tokens.get("capture_status"),
        "token_total": _token_total(tokens, attempts),
        "major_corrections": summary.get("major_corrections", []),
        "blockers": summary.get("blockers", []),
        "residual_not_built_yet": summary.get("residual_not_built_yet", []),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize an M3 benchmark run log.")
    parser.add_argument("run_log_yaml")
    parser.add_argument("--out", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = summarize_run_log(_load_yaml(Path(args.run_log_yaml)))
    body = json.dumps(summary, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body + "\n", encoding="utf-8")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
