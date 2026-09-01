#!/usr/bin/env python3
"""Install or verify CADCLAW's repository-local pre-publication hooks."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence

import prepublication_gate as gate


ROOT = Path(__file__).resolve().parents[1]
HOOKS_PATH = "scripts/hooks"
HOOK = ROOT / HOOKS_PATH / "pre-push"
LOCAL_OVERLAY = ROOT / ".prepublication-policy.local.json"
ALL_LOCAL_SURFACES = sorted(gate.SURFACES)


class BootstrapError(RuntimeError):
    def __init__(self, pattern_id: str):
        self.pattern_id = pattern_id
        super().__init__("hook bootstrap error")


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
        raise BootstrapError("SYSTEM-BOOTSTRAP-GIT") from None
    if result.returncode != 0:
        raise BootstrapError("SYSTEM-BOOTSTRAP-GIT")
    return result.stdout


def _repository_is_exact() -> None:
    raw = _git(["rev-parse", "--show-toplevel"])
    try:
        discovered = Path(raw.decode("utf-8", errors="strict").strip()).resolve()
    except (UnicodeError, OSError, ValueError):
        raise BootstrapError("SYSTEM-BOOTSTRAP-ROOT") from None
    if discovered != ROOT.resolve():
        raise BootstrapError("SYSTEM-BOOTSTRAP-ROOT")


def _parse_embedded_literals(path: Path) -> list[str]:
    raw = gate._read_bounded(
        path,
        gate.MAX_POLICY_BYTES,
        gate.SafeGateError("policy", "SYSTEM-IMPORT-UNREADABLE"),
    )
    try:
        module = ast.parse(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, SyntaxError):
        raise BootstrapError("SYSTEM-IMPORT-MALFORMED") from None

    candidates: list[list[str]] = []
    for statement in module.body:
        if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        value_node = statement.value
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        if not any(name.lower().endswith("denylist") for name in names):
            continue
        try:
            value = ast.literal_eval(value_node)
        except (ValueError, TypeError, SyntaxError, MemoryError):
            raise BootstrapError("SYSTEM-IMPORT-MALFORMED") from None
        if (
            not isinstance(value, (tuple, list))
            or not value
            or any(not isinstance(item, str) or not item or len(item) > 4096 for item in value)
        ):
            raise BootstrapError("SYSTEM-IMPORT-MALFORMED")
        candidates.append(list(value))
    if len(candidates) != 1:
        raise BootstrapError("SYSTEM-IMPORT-AMBIGUOUS")
    return candidates[0]


def _overlay_bytes_from_literals(values: list[str]) -> bytes:
    document = {
        "schema": "cadclaw-prepublication-overlay.v1",
        "policy_version": 1,
        "deny": [
            {
                "id": f"LOCAL-IMPORTED-{ordinal:03d}",
                "surfaces": ALL_LOCAL_SURFACES,
                "kind": "literal",
                "pattern": value,
            }
            for ordinal, value in enumerate(values, start=1)
        ],
        "allow": [],
    }
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _validate_overlay_bytes(raw: bytes) -> None:
    gate._parse_policy_document(raw, overlay=True)


def _write_overlay(raw: bytes) -> None:
    _validate_overlay_bytes(raw)
    temporary = ROOT / f".prepublication-policy.local.tmp-{os.getpid()}"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, LOCAL_OVERLAY)
        try:
            os.chmod(LOCAL_OVERLAY, 0o600)
        except OSError:
            pass
    except OSError:
        raise BootstrapError("SYSTEM-OVERLAY-WRITE") from None
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _install_overlay(
    overlay_source: Path | None,
    literal_source: Path | None,
    protected_path: Path | None,
) -> None:
    if sum(item is not None for item in (overlay_source, literal_source, protected_path)) > 1:
        raise BootstrapError("SYSTEM-OVERLAY-SOURCE")
    if overlay_source is not None:
        raw = gate._read_bounded(
            overlay_source,
            gate.MAX_POLICY_BYTES,
            gate.SafeGateError("policy", "SYSTEM-OVERLAY-SOURCE"),
        )
        _write_overlay(raw)
    elif literal_source is not None:
        _write_overlay(_overlay_bytes_from_literals(_parse_embedded_literals(literal_source)))
    elif protected_path is not None:
        try:
            resolved = protected_path.resolve(strict=False)
            values = list(dict.fromkeys((str(resolved), resolved.as_posix(), resolved.name)))
        except (OSError, ValueError):
            raise BootstrapError("SYSTEM-OVERLAY-SOURCE") from None
        if any(not value for value in values):
            raise BootstrapError("SYSTEM-OVERLAY-SOURCE")
        _write_overlay(_overlay_bytes_from_literals(values))
    elif not LOCAL_OVERLAY.exists():
        raise BootstrapError("SYSTEM-OVERLAY-MISSING")


def _verify_hook_files() -> None:
    try:
        raw = HOOK.read_bytes()
    except OSError:
        raise BootstrapError("SYSTEM-HOOK-MISSING") from None
    if not raw.startswith(b"#!/bin/sh\n") or b"\r\n" in raw:
        raise BootstrapError("SYSTEM-HOOK-BYTES")
    staged = _git(["ls-files", "--stage", "--", HOOKS_PATH + "/pre-push"])
    fields = staged.split(maxsplit=1)
    if not fields or fields[0] != b"100755":
        raise BootstrapError("SYSTEM-HOOK-MODE")


def _verify_ignored_overlay() -> None:
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", LOCAL_OVERLAY.name],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise BootstrapError("SYSTEM-OVERLAY-IGNORE") from None
    if result.returncode != 0:
        raise BootstrapError("SYSTEM-OVERLAY-IGNORE")


def _config_value(key: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--local", "--get", key],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise BootstrapError("SYSTEM-BOOTSTRAP-GIT") from None
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        raise BootstrapError("SYSTEM-BOOTSTRAP-GIT")
    try:
        return result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeError:
        raise BootstrapError("SYSTEM-BOOTSTRAP-GIT") from None


def _install_config() -> None:
    current = _config_value("core.hooksPath")
    if current not in {None, HOOKS_PATH}:
        raise BootstrapError("SYSTEM-HOOKS-PATH-CONFLICT")
    _git(["config", "--local", "core.hooksPath", HOOKS_PATH])
    executable = Path(sys.executable).resolve().as_posix()
    _git(["config", "--local", "prepublication.python", executable])


def _verify_config() -> None:
    if _config_value("core.hooksPath") != HOOKS_PATH:
        raise BootstrapError("SYSTEM-HOOKS-PATH")
    configured_python = _config_value("prepublication.python")
    if not configured_python:
        raise BootstrapError("SYSTEM-PYTHON-CONFIG")
    try:
        executable = Path(configured_python).resolve()
        current = Path(sys.executable).resolve()
        if not executable.is_file() or executable != current:
            raise BootstrapError("SYSTEM-PYTHON-CONFIG")
    except (OSError, ValueError):
        raise BootstrapError("SYSTEM-PYTHON-CONFIG") from None


def verify() -> None:
    _repository_is_exact()
    _verify_hook_files()
    _verify_ignored_overlay()
    gate.load_policy(gate.DEFAULT_POLICY, LOCAL_OVERLAY, require_overlay=True)
    _verify_config()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "verify"))
    parser.add_argument("--overlay-source", type=Path)
    parser.add_argument("--import-literal-source", type=Path)
    parser.add_argument("--protect-path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.action == "verify" and (
            args.overlay_source or args.import_literal_source or args.protect_path
        ):
            raise BootstrapError("SYSTEM-BOOTSTRAP-ARGUMENT")
        _repository_is_exact()
        if args.action == "install":
            _install_overlay(
                args.overlay_source,
                args.import_literal_source,
                args.protect_path,
            )
            _install_config()
        verify()
    except gate.SafeGateError as exc:
        print(
            "prepublication-bootstrap: "
            f"status=error surface={exc.surface} pattern={exc.pattern_id} ordinal=1",
            file=sys.stderr,
        )
        return 2
    except BootstrapError as exc:
        print(
            "prepublication-bootstrap: "
            f"status=error surface=bootstrap pattern={exc.pattern_id} ordinal=1",
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            "prepublication-bootstrap: "
            "status=error surface=bootstrap pattern=SYSTEM-BOOTSTRAP-ERROR ordinal=1",
            file=sys.stderr,
        )
        return 2
    print("prepublication-bootstrap: status=clean surface=bootstrap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
