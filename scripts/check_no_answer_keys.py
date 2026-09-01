#!/usr/bin/env python3
"""Object-level MARB answer-key compatibility guard with redacted output."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
KEY_PATH_RE = re.compile(
    rb"(^|/)m3_reference_round1\.(step|stp)$"
    rb"|(^|/)[^/]*reference[^/]*\.(step|stp)$"
    rb"|(^|/)ph[0-9]+_reference"
    rb"|(^|/)_private/",
    re.IGNORECASE,
)
REDACTED_SPEC = b"examples/m3_crete/m3_reference_assembly.yaml"
POSE_RE = re.compile(rb"(?m)^[ \t]*(translate_mm|rotate_deg|source_origin_mm):")


class GuardError(RuntimeError):
    pass


def _git(args: Sequence[str]) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise GuardError() from None
    if result.returncode != 0:
        raise GuardError()
    return result.stdout


class Guard:
    def __init__(self) -> None:
        self.findings: list[tuple[str, str, int]] = []
        self.ordinals = {"filename": 0, "blob": 0}

    def _next(self, surface: str) -> int:
        self.ordinals[surface] += 1
        return self.ordinals[surface]

    def scan_path(self, path: bytes) -> None:
        ordinal = self._next("filename")
        if KEY_PATH_RE.search(path):
            self.findings.append(("filename", "MARB-PATH-001", ordinal))

    def scan_pose_blob(self, oid: str) -> None:
        ordinal = self._next("blob")
        raw = _git(["cat-file", "blob", oid])
        if POSE_RE.search(raw):
            self.findings.append(("blob", "MARB-CONTENT-001", ordinal))

    def scan_tree(self, treeish: str) -> None:
        raw = _git(["ls-tree", "-r", "-z", "--full-tree", treeish])
        pose_oid: str | None = None
        for record in raw.split(b"\0"):
            if not record:
                continue
            header, separator, path = record.partition(b"\t")
            fields = header.split()
            if not separator or len(fields) != 3:
                raise GuardError()
            self.scan_path(path)
            if path == REDACTED_SPEC:
                try:
                    kind = fields[1].decode("ascii", errors="strict")
                    oid = fields[2].decode("ascii", errors="strict")
                except UnicodeError:
                    raise GuardError() from None
                if kind != "blob" or not re.fullmatch(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", oid):
                    raise GuardError()
                pose_oid = oid
        if pose_oid is not None:
            self.scan_pose_blob(pose_oid)

    def scan_range(self, revision_args: Sequence[str]) -> None:
        if not revision_args:
            raise GuardError()
        raw = _git(["rev-list", "--reverse", "--topo-order", *revision_args])
        for line in raw.splitlines():
            try:
                oid = line.decode("ascii", errors="strict")
            except UnicodeError:
                raise GuardError() from None
            if not re.fullmatch(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", oid):
                raise GuardError()
            self.scan_tree(oid)

    def emit(self) -> int:
        if not self.findings:
            print("answer-key-guard: status=clean surface=repository")
            return 0
        for surface, pattern_id, ordinal in sorted(set(self.findings)):
            print(
                "answer-key-guard: "
                f"status=blocked surface={surface} pattern={pattern_id} ordinal={ordinal}",
                file=sys.stderr,
            )
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tree", nargs="?", const="HEAD")
    group.add_argument("--range", nargs=argparse.REMAINDER)
    group.add_argument("--stdin", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    guard = Guard()
    try:
        args = build_parser().parse_args(argv)
        if args.stdin:
            for path in sys.stdin.buffer.read().splitlines():
                guard.scan_path(path)
        elif args.tree:
            guard.scan_tree(args.tree)
        elif args.range is not None:
            guard.scan_range(args.range)
        else:
            raise GuardError()
    except GuardError:
        print(
            "answer-key-guard: status=error surface=repository pattern=SYSTEM-GIT-READ ordinal=1",
            file=sys.stderr,
        )
        return 64
    except Exception:
        print(
            "answer-key-guard: status=error surface=repository pattern=SYSTEM-GUARD-ERROR ordinal=1",
            file=sys.stderr,
        )
        return 64
    return guard.emit()


if __name__ == "__main__":
    raise SystemExit(main())
