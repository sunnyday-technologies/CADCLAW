#!/usr/bin/env python3
"""Scan PR metadata with the private overlay before invoking GitHub."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Sequence

import prepublication_gate as gate


ROOT = Path(__file__).resolve().parents[1]
PR_URL_RE = re.compile(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+")


def _read_body(args: argparse.Namespace) -> str:
    if args.body is not None:
        return args.body
    raw = gate._read_bounded(
        args.body_file,
        gate.MAX_METADATA_BYTES,
        gate.SafeGateError("pr_body", "SYSTEM-PR-BODY-UNREADABLE"),
    )
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise gate.SafeGateError("pr_body", "SYSTEM-PR-BODY-ENCODING") from None


def _current_branch(scanner: gate.GateScanner) -> bytes:
    raw = scanner.git.run(["symbolic-ref", "--quiet", "--short", "HEAD"], "ref").strip()
    if not raw:
        raise gate.SafeGateError("ref", "SYSTEM-HEAD-DETACHED")
    return raw


def _invoke_github(args: argparse.Namespace, body: str) -> str | None:
    executable = shutil.which("gh")
    if not executable:
        raise gate.SafeGateError("github", "SYSTEM-GITHUB-UNAVAILABLE")
    command = [executable, "pr", "create", "--title", args.title, "--body-file", "-"]
    if args.base:
        command.extend(["--base", args.base])
    if args.head:
        command.extend(["--head", args.head])
    if args.draft:
        command.append("--draft")
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            input=body.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise gate.SafeGateError("github", "SYSTEM-GITHUB-CREATE") from None
    if result.returncode != 0:
        raise gate.SafeGateError("github", "SYSTEM-GITHUB-CREATE")
    match = PR_URL_RE.search(result.stdout.decode("utf-8", errors="ignore"))
    return match.group(0) if match else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    body = parser.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file", type=Path)
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--draft", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    reporter = gate.Reporter()
    url: str | None = None
    try:
        args = build_parser().parse_args(argv)
        body = _read_body(args)
        if len(args.title.encode("utf-8")) > gate.MAX_METADATA_BYTES or len(body.encode("utf-8")) > gate.MAX_METADATA_BYTES:
            raise gate.SafeGateError("pr_body", "SYSTEM-PR-METADATA-OVERSIZE")
        policy = gate.load_policy(require_overlay=True)
        scanner = gate.GateScanner(policy, ROOT)
        reporter = scanner.reporter
        scanner.scan_bytes("ref", _current_branch(scanner))
        if args.base:
            scanner.scan_bytes("ref", args.base.encode("utf-8", errors="surrogateescape"))
        if args.head:
            scanner.scan_bytes("ref", args.head.encode("utf-8", errors="surrogateescape"))
        scanner.scan_bytes("pr_title", args.title.encode("utf-8", errors="surrogateescape"))
        scanner.scan_bytes("pr_body", body.encode("utf-8", errors="surrogateescape"))
        if reporter.findings:
            return reporter.emit()
        url = _invoke_github(args, body)
    except gate.SafeGateError as exc:
        reporter.add_error(exc.surface, exc.pattern_id)
        return reporter.emit()
    except Exception:
        reporter.add_error("github", "SYSTEM-PR-WRAPPER-ERROR")
        return reporter.emit()
    if url:
        print(url)
    else:
        print("public-pr: status=created surface=github")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
