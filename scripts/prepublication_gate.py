#!/usr/bin/env python3
"""Fail-closed confidentiality checks over exact outgoing Git objects.

Diagnostics intentionally contain only stable surface IDs, pattern IDs,
ordinals, and status. Never add candidate text, paths, refs, object IDs,
exception strings, or Git stderr to this program's output.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "policy" / "prepublication.v1.json"
DEFAULT_OVERLAY = ROOT / ".prepublication-policy.local.json"
ZERO_OID = "0" * 40
MAX_POLICY_BYTES = 1024 * 1024
MAX_EVENT_BYTES = 4 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024

SURFACES = frozenset({
    "ref",
    "filename",
    "blob",
    "workflow_filename",
    "workflow_content",
    "workflow_metadata",
    "commit_message",
    "tag_message",
    "pr_title",
    "pr_body",
})
RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
OID_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
REQUIRED_PUBLIC_DENY_IDS = frozenset({
    "PUBLIC-REF-001",
    "PUBLIC-PATH-001",
    "PUBLIC-PATH-002",
    "PUBLIC-CONTENT-001",
    "PUBLIC-CONTENT-002",
    "PUBLIC-CONTENT-003",
})
REQUIRED_PUBLIC_ALLOW_IDS = frozenset({
    "PUBLIC-ALLOW-001",
    "PUBLIC-ALLOW-002",
})
REQUIRED_PUBLIC_RULE_SIGNATURES = {
    "PUBLIC-REF-001": (
        frozenset({"ref"}),
        "regex",
        r"(?i)(?:^|/)(?:private|confidential|internal)(?:[-_/]|$)",
        frozenset(),
    ),
    "PUBLIC-PATH-001": (
        frozenset({"filename", "workflow_filename"}),
        "regex",
        r"(?i)(?:^|/)(?:_private|private|confidential|internal)(?:/|$)",
        frozenset(),
    ),
    "PUBLIC-PATH-002": (
        frozenset({"filename", "workflow_filename"}),
        "regex",
        r"(?i)(?:^|/)\.env(?:\.[^/]*)?$",
        frozenset(),
    ),
    "PUBLIC-CONTENT-001": (
        frozenset({
            "blob",
            "workflow_content",
            "commit_message",
            "tag_message",
            "pr_title",
            "pr_body",
        }),
        "regex",
        r"(?i)\b(?:DO[_-]NOT[_-]PUBLISH|INTERNAL[_-]ONLY|CONFIDENTIAL[_-]DATA)(?:[_-][A-Z0-9]+)*\b",
        frozenset(),
    ),
    "PUBLIC-CONTENT-002": (
        frozenset({
            "blob",
            "workflow_content",
            "commit_message",
            "tag_message",
            "pr_title",
            "pr_body",
        }),
        "regex",
        r"[-]{5}BEGIN[ ](?:RSA[ ]|EC[ ]|OPENSSH[ ])?PRIVATE[ ]KEY[-]{5}",
        frozenset(),
    ),
    "PUBLIC-CONTENT-003": (
        frozenset({
            "blob",
            "workflow_content",
            "commit_message",
            "tag_message",
            "pr_title",
            "pr_body",
        }),
        "regex",
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*[A-Za-z0-9_./+=-]{20,}",
        frozenset(),
    ),
    "PUBLIC-ALLOW-001": (
        frozenset({"filename", "workflow_filename"}),
        "literal",
        ".env.example",
        frozenset({"PUBLIC-PATH-002"}),
    ),
    "PUBLIC-ALLOW-002": (
        frozenset({
            "blob",
            "workflow_content",
            "commit_message",
            "tag_message",
            "pr_title",
            "pr_body",
        }),
        "literal",
        "CONFIDENTIAL_DATA_PUBLIC_EXAMPLE",
        frozenset({"PUBLIC-CONTENT-001"}),
    ),
}


class SafeGateError(RuntimeError):
    """An error whose public projection is fixed and value-free."""

    def __init__(self, surface: str, pattern_id: str):
        self.surface = surface
        self.pattern_id = pattern_id
        super().__init__("pre-publication gate error")


class PolicyError(SafeGateError):
    def __init__(self):
        super().__init__("policy", "SYSTEM-POLICY-INVALID")


@dataclass(frozen=True)
class Rule:
    id: str
    surfaces: frozenset[str]
    kind: str
    pattern: str
    regex: re.Pattern[str]
    suppresses: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Policy:
    version: int
    max_blob_bytes: int
    deny: tuple[Rule, ...]
    allow: tuple[Rule, ...]
    overlay_loaded: bool


@dataclass(frozen=True, order=True)
class Finding:
    surface: str
    pattern_id: str
    ordinal: int
    status: str


class Reporter:
    def __init__(self) -> None:
        self._ordinals: dict[str, int] = defaultdict(int)
        self.findings: list[Finding] = []

    def next_ordinal(self, surface: str) -> int:
        self._ordinals[surface] += 1
        return self._ordinals[surface]

    def add(self, surface: str, pattern_id: str, ordinal: int, status: str) -> None:
        self.findings.append(Finding(surface, pattern_id, ordinal, status))

    def add_error(self, surface: str, pattern_id: str) -> None:
        self.add(surface, pattern_id, self.next_ordinal(surface), "error")

    def emit(self) -> int:
        if not self.findings:
            print("prepublication-gate: status=clean surface=publication")
            return 0
        for finding in sorted(set(self.findings)):
            print(
                "prepublication-gate: "
                f"status={finding.status} "
                f"surface={finding.surface} "
                f"pattern={finding.pattern_id} "
                f"ordinal={finding.ordinal}",
                file=sys.stderr,
            )
        if any(item.status == "error" for item in self.findings):
            return 2
        return 1


def _read_bounded(path: Path, maximum: int, error: SafeGateError) -> bytes:
    try:
        stat = path.stat()
        if stat.st_size < 1 or stat.st_size > maximum or not path.is_file():
            raise error
        return path.read_bytes()
    except (OSError, ValueError):
        raise error from None


def _strict_object(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise PolicyError() from None
    if not isinstance(value, dict):
        raise PolicyError()
    return value


def _compile_rule(raw: object, allow: bool) -> Rule:
    if not isinstance(raw, dict):
        raise PolicyError()
    expected = {"id", "surfaces", "kind", "pattern"}
    if allow:
        expected.add("suppresses")
    if set(raw) != expected:
        raise PolicyError()

    rule_id = raw.get("id")
    surfaces = raw.get("surfaces")
    kind = raw.get("kind")
    pattern = raw.get("pattern")
    if not isinstance(rule_id, str) or not RULE_ID_RE.fullmatch(rule_id):
        raise PolicyError()
    if (
        not isinstance(surfaces, list)
        or not surfaces
        or any(not isinstance(item, str) or item not in SURFACES for item in surfaces)
        or len(set(surfaces)) != len(surfaces)
    ):
        raise PolicyError()
    if kind not in {"literal", "regex"}:
        raise PolicyError()
    if not isinstance(pattern, str) or not pattern or len(pattern) > 4096 or "\x00" in pattern:
        raise PolicyError()

    expression = re.escape(unicodedata.normalize("NFKC", pattern)) if kind == "literal" else pattern
    try:
        compiled = re.compile(expression)
    except re.error:
        raise PolicyError() from None
    if compiled.search("") is not None:
        raise PolicyError()

    suppresses: frozenset[str] = frozenset()
    if allow:
        raw_suppresses = raw.get("suppresses")
        if (
            not isinstance(raw_suppresses, list)
            or not raw_suppresses
            or any(not isinstance(item, str) or not RULE_ID_RE.fullmatch(item) for item in raw_suppresses)
            or len(set(raw_suppresses)) != len(raw_suppresses)
        ):
            raise PolicyError()
        suppresses = frozenset(raw_suppresses)
    return Rule(
        id=rule_id,
        surfaces=frozenset(surfaces),
        kind=kind,
        pattern=pattern,
        regex=compiled,
        suppresses=suppresses,
    )


def _rule_signature(rule: Rule) -> tuple[frozenset[str], str, str, frozenset[str]]:
    return rule.surfaces, rule.kind, rule.pattern, rule.suppresses


def _parse_policy_document(raw: bytes, overlay: bool) -> tuple[int, int | None, list[Rule], list[Rule]]:
    document = _strict_object(raw)
    expected = {"schema", "policy_version", "deny", "allow"}
    if not overlay:
        expected.add("max_blob_bytes")
    if set(document) != expected:
        raise PolicyError()
    schema = document.get("schema")
    expected_schema = (
        "cadclaw-prepublication-overlay.v1"
        if overlay
        else "cadclaw-prepublication-policy.v1"
    )
    if schema != expected_schema or document.get("policy_version") != 1:
        raise PolicyError()

    raw_deny = document.get("deny")
    raw_allow = document.get("allow")
    if not isinstance(raw_deny, list) or not raw_deny or not isinstance(raw_allow, list):
        raise PolicyError()
    deny = [_compile_rule(item, allow=False) for item in raw_deny]
    allow = [_compile_rule(item, allow=True) for item in raw_allow]
    if not overlay:
        by_id = {item.id: item for item in (*deny, *allow)}
        for rule_id, signature in REQUIRED_PUBLIC_RULE_SIGNATURES.items():
            if rule_id not in by_id or _rule_signature(by_id[rule_id]) != signature:
                raise PolicyError()
    for item in allow:
        if item.suppresses & REQUIRED_PUBLIC_DENY_IDS:
            if overlay or item.id not in REQUIRED_PUBLIC_ALLOW_IDS:
                raise PolicyError()

    maximum: int | None = None
    if not overlay:
        maximum = document.get("max_blob_bytes")  # type: ignore[assignment]
        if not isinstance(maximum, int) or isinstance(maximum, bool) or not (1024 <= maximum <= 100 * 1024 * 1024):
            raise PolicyError()
    return 1, maximum, deny, allow


def load_policy(
    policy_path: Path = DEFAULT_POLICY,
    overlay_path: Path = DEFAULT_OVERLAY,
    *,
    require_overlay: bool,
) -> Policy:
    public_raw = _read_bounded(policy_path, MAX_POLICY_BYTES, PolicyError())
    version, maximum, deny, allow = _parse_policy_document(public_raw, overlay=False)
    overlay_loaded = False
    if overlay_path.exists():
        overlay_raw = _read_bounded(overlay_path, MAX_POLICY_BYTES, PolicyError())
        overlay_version, _, overlay_deny, overlay_allow = _parse_policy_document(
            overlay_raw,
            overlay=True,
        )
        if overlay_version != version:
            raise PolicyError()
        deny.extend(overlay_deny)
        allow.extend(overlay_allow)
        overlay_loaded = True
    elif require_overlay:
        raise SafeGateError("policy", "SYSTEM-OVERLAY-MISSING")

    ids = [item.id for item in deny] + [item.id for item in allow]
    if len(ids) != len(set(ids)):
        raise PolicyError()
    deny_ids = {item.id for item in deny}
    for item in allow:
        if not item.suppresses.issubset(deny_ids):
            raise PolicyError()
        for suppressed in item.suppresses:
            target = next(rule for rule in deny if rule.id == suppressed)
            if not (item.surfaces & target.surfaces):
                raise PolicyError()
    assert maximum is not None
    return Policy(version, maximum, tuple(deny), tuple(allow), overlay_loaded)


class GitAccess:
    def __init__(self, repo: Path):
        self.repo = repo

    def run(self, args: Sequence[str], surface: str = "git_object") -> bytes:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.repo,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise SafeGateError(surface, "SYSTEM-GIT-UNAVAILABLE") from None
        if result.returncode != 0:
            raise SafeGateError(surface, "SYSTEM-GIT-READ")
        return result.stdout

    def object_type(self, oid: str) -> str:
        raw = self.run(["cat-file", "-t", oid])
        try:
            value = raw.decode("ascii", errors="strict").strip()
        except UnicodeError:
            raise SafeGateError("git_object", "SYSTEM-GIT-OBJECT-TYPE") from None
        if value not in {"blob", "commit", "tag", "tree"}:
            raise SafeGateError("git_object", "SYSTEM-GIT-OBJECT-TYPE")
        return value

    def object_size(self, oid: str) -> int:
        raw = self.run(["cat-file", "-s", oid])
        try:
            value = int(raw.decode("ascii", errors="strict").strip())
        except (UnicodeError, ValueError):
            raise SafeGateError("git_object", "SYSTEM-GIT-OBJECT-SIZE") from None
        if value < 0:
            raise SafeGateError("git_object", "SYSTEM-GIT-OBJECT-SIZE")
        return value

    def object_bytes(self, kind: str, oid: str) -> bytes:
        return self.run(["cat-file", kind, oid])


class GateScanner:
    def __init__(self, policy: Policy, repo: Path):
        self.policy = policy
        self.git = GitAccess(repo)
        self.reporter = Reporter()
        self._generic_blobs: set[str] = set()
        self._workflow_blobs: set[tuple[str, bytes]] = set()
        self._commits: set[str] = set()
        self._workflow_tips: set[str] = set()

    @staticmethod
    def _text_views(data: bytes) -> tuple[str, ...]:
        """Return normalized views for common text encodings without guessing one."""

        decoded = [data.decode("utf-8", errors="surrogateescape")]
        for encoding, unit in (
            ("utf-16-le", 2),
            ("utf-16-be", 2),
            ("utf-32-le", 4),
            ("utf-32-be", 4),
        ):
            if len(data) >= unit:
                decoded.append(data.decode(encoding, errors="replace"))
        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in decoded:
            text = unicodedata.normalize("NFKC", candidate.lstrip("\ufeff"))
            if text not in seen:
                seen.add(text)
                normalized.append(text)
        return tuple(normalized)

    def scan_bytes(self, surface: str, data: bytes) -> None:
        if surface not in SURFACES:
            raise SafeGateError("scanner", "SYSTEM-SURFACE-UNKNOWN")
        ordinal = self.reporter.next_ordinal(surface)
        texts = self._text_views(data)
        for deny in self.policy.deny:
            if surface not in deny.surfaces:
                continue
            blocked = False
            for text in texts:
                for match in deny.regex.finditer(text):
                    matched = match.group(0)
                    allowed = any(
                        surface in exception.surfaces
                        and deny.id in exception.suppresses
                        and exception.regex.fullmatch(matched) is not None
                        for exception in self.policy.allow
                    )
                    if not allowed:
                        blocked = True
                        break
                if blocked:
                    break
            if blocked:
                self.reporter.add(surface, deny.id, ordinal, "blocked")

    def _scan_blob(self, oid: str, surface: str, workflow_path: bytes | None = None) -> None:
        if not OID_RE.fullmatch(oid):
            raise SafeGateError("git_object", "SYSTEM-GIT-OID")
        if surface == "blob":
            if oid in self._generic_blobs:
                return
            self._generic_blobs.add(oid)
        elif workflow_path is not None:
            key = (oid, workflow_path)
            if key in self._workflow_blobs:
                return
            self._workflow_blobs.add(key)

        size = self.git.object_size(oid)
        ordinal = self.reporter.next_ordinal(surface)
        if size > self.policy.max_blob_bytes:
            self.reporter.add(surface, "SYSTEM-BLOB-OVERSIZE", ordinal, "blocked")
            return
        raw = self.git.object_bytes("blob", oid)
        if len(raw) != size:
            raise SafeGateError("git_object", "SYSTEM-GIT-OBJECT-SIZE")
        # Reuse the already assigned ordinal while preserving scan_bytes' public API.
        self.reporter._ordinals[surface] -= 1
        self.scan_bytes(surface, raw)

    @staticmethod
    def _workflow_path(path: bytes) -> bool:
        lowered = path.lower()
        return lowered.startswith(b".github/workflows/") and lowered.endswith((b".yml", b".yaml"))

    def _scan_workflow_entry(
        self,
        path: bytes,
        mode: str,
        kind: str,
        oid: str,
        status: str,
    ) -> None:
        self.scan_bytes("workflow_filename", path)
        metadata = f"mode={mode};kind={kind};status={status}".encode("ascii", errors="strict")
        self.scan_bytes("workflow_metadata", metadata)
        if mode not in {"100644", "100755"} or kind != "blob":
            ordinal = self.reporter.next_ordinal("workflow_metadata")
            self.reporter.add(
                "workflow_metadata",
                "SYSTEM-WORKFLOW-METADATA",
                ordinal,
                "blocked",
            )
            return
        self._scan_blob(oid, "workflow_content", workflow_path=path)

    def _scan_commit_message(self, oid: str) -> None:
        raw = self.git.object_bytes("commit", oid)
        marker = raw.find(b"\n\n")
        if marker < 0:
            raise SafeGateError("commit_message", "SYSTEM-COMMIT-MALFORMED")
        self.scan_bytes("commit_message", raw[marker + 2 :])

    def _parse_diff(self, raw: bytes) -> Iterable[tuple[list[bytes], bytes, str, str, str]]:
        records = raw.split(b"\0")
        index = 0
        while index < len(records) and records[index]:
            header = records[index]
            index += 1
            if not header.startswith(b":"):
                raise SafeGateError("filename", "SYSTEM-DIFF-MALFORMED")
            fields = header[1:].split()
            if len(fields) != 5:
                raise SafeGateError("filename", "SYSTEM-DIFF-MALFORMED")
            old_mode_b, new_mode_b, _old_oid_b, new_oid_b, status_b = fields
            try:
                old_mode = old_mode_b.decode("ascii", errors="strict")
                new_mode = new_mode_b.decode("ascii", errors="strict")
                new_oid = new_oid_b.decode("ascii", errors="strict")
                status = status_b.decode("ascii", errors="strict")
            except UnicodeError:
                raise SafeGateError("filename", "SYSTEM-DIFF-MALFORMED") from None
            if index >= len(records):
                raise SafeGateError("filename", "SYSTEM-DIFF-MALFORMED")
            first_path = records[index]
            index += 1
            paths = [first_path]
            new_path = first_path
            if status.startswith(("R", "C")):
                if index >= len(records):
                    raise SafeGateError("filename", "SYSTEM-DIFF-MALFORMED")
                new_path = records[index]
                index += 1
                paths.append(new_path)
            yield paths, new_path, new_mode, new_oid, status

    def scan_commit(self, oid: str) -> None:
        if oid in self._commits:
            return
        self._commits.add(oid)
        self._scan_commit_message(oid)
        raw = self.git.run([
            "diff-tree",
            "--root",
            "-r",
            "-m",
            "--no-commit-id",
            "--raw",
            "--no-abbrev",
            "-z",
            oid,
        ])
        self._scan_diff_entries(raw)

    def _scan_diff_entries(self, raw: bytes) -> None:
        seen_paths: set[bytes] = set()
        for paths, new_path, new_mode, new_oid, status in self._parse_diff(raw):
            for path in paths:
                if path not in seen_paths:
                    self.scan_bytes("filename", path)
                    seen_paths.add(path)
                if self._workflow_path(path):
                    self.scan_bytes("workflow_filename", path)
            if set(new_oid) == {"0"}:
                continue
            kind = self.git.object_type(new_oid)
            if kind == "blob":
                self._scan_blob(new_oid, "blob")
            if self._workflow_path(new_path):
                self._scan_workflow_entry(new_path, new_mode, kind, new_oid, status)

    def scan_index(self) -> None:
        raw = self.git.run([
            "diff-index",
            "--cached",
            "-r",
            "--raw",
            "--no-abbrev",
            "-z",
            "HEAD",
            "--",
        ], "index")
        self._scan_diff_entries(raw)

    def _scan_tip_workflows(self, treeish: str) -> None:
        if treeish in self._workflow_tips:
            return
        self._workflow_tips.add(treeish)
        raw = self.git.run(["ls-tree", "-r", "-z", "--full-tree", treeish])
        for record in raw.split(b"\0"):
            if not record:
                continue
            header, separator, path = record.partition(b"\t")
            fields = header.split()
            if not separator or len(fields) != 3:
                raise SafeGateError("workflow_metadata", "SYSTEM-TREE-MALFORMED")
            if not self._workflow_path(path):
                continue
            try:
                mode = fields[0].decode("ascii", errors="strict")
                kind = fields[1].decode("ascii", errors="strict")
                oid = fields[2].decode("ascii", errors="strict")
            except UnicodeError:
                raise SafeGateError("workflow_metadata", "SYSTEM-TREE-MALFORMED") from None
            self._scan_workflow_entry(path, mode, kind, oid, "tracked")

    def _scan_direct_tree(self, treeish: str) -> None:
        raw = self.git.run(["ls-tree", "-r", "-z", "--full-tree", treeish])
        for record in raw.split(b"\0"):
            if not record:
                continue
            header, separator, path = record.partition(b"\t")
            fields = header.split()
            if not separator or len(fields) != 3:
                raise SafeGateError("filename", "SYSTEM-TREE-MALFORMED")
            try:
                mode = fields[0].decode("ascii", errors="strict")
                kind = fields[1].decode("ascii", errors="strict")
                oid = fields[2].decode("ascii", errors="strict")
            except UnicodeError:
                raise SafeGateError("filename", "SYSTEM-TREE-MALFORMED") from None
            self.scan_bytes("filename", path)
            if kind == "blob":
                self._scan_blob(oid, "blob")
            if self._workflow_path(path):
                self._scan_workflow_entry(path, mode, kind, oid, "tracked")

    def _scan_tag(self, oid: str) -> str:
        target = oid
        seen: set[str] = set()
        while self.git.object_type(target) == "tag":
            if target in seen:
                raise SafeGateError("tag_message", "SYSTEM-TAG-MALFORMED")
            seen.add(target)
            raw = self.git.object_bytes("tag", target)
            marker = raw.find(b"\n\n")
            if marker < 0:
                raise SafeGateError("tag_message", "SYSTEM-TAG-MALFORMED")
            header = raw[:marker].splitlines()
            object_lines = [line[7:] for line in header if line.startswith(b"object ")]
            type_lines = [line[5:] for line in header if line.startswith(b"type ")]
            if len(object_lines) != 1 or len(type_lines) != 1:
                raise SafeGateError("tag_message", "SYSTEM-TAG-MALFORMED")
            try:
                next_target = object_lines[0].decode("ascii", errors="strict")
                declared_type = type_lines[0].decode("ascii", errors="strict")
            except UnicodeError:
                raise SafeGateError("tag_message", "SYSTEM-TAG-MALFORMED") from None
            if not OID_RE.fullmatch(next_target):
                raise SafeGateError("git_object", "SYSTEM-GIT-OID")
            actual_type = self.git.object_type(next_target)
            if declared_type != actual_type:
                raise SafeGateError("tag_message", "SYSTEM-TAG-MALFORMED")
            self.scan_bytes("tag_message", raw[marker + 2 :])
            target = next_target
        return target

    def _list_commits(
        self,
        local_oid: str,
        exclusions: Sequence[str],
    ) -> list[str]:
        args = ["rev-list", "--reverse", "--topo-order", local_oid]
        args.extend(f"^{item}" for item in exclusions)
        raw = self.git.run(args)
        commits: list[str] = []
        for line in raw.splitlines():
            try:
                oid = line.decode("ascii", errors="strict")
            except UnicodeError:
                raise SafeGateError("git_object", "SYSTEM-GIT-OID") from None
            if not OID_RE.fullmatch(oid):
                raise SafeGateError("git_object", "SYSTEM-GIT-OID")
            commits.append(oid)
        return commits

    def scan_update(
        self,
        local_oid: str,
        remote_oid: str,
        remote_ref: bytes,
        *,
        new_ref_exclusions: Sequence[str] = (),
    ) -> None:
        if not OID_RE.fullmatch(local_oid) or not OID_RE.fullmatch(remote_oid):
            raise SafeGateError("ref", "SYSTEM-UPDATE-MALFORMED")
        # Deletions transmit no new object or metadata. Validate their shape but
        # never prevent removal of a remote ref that should not exist.
        if set(local_oid) == {"0"}:
            self.reporter.next_ordinal("ref")
            return
        self.scan_bytes("ref", remote_ref)

        object_type = self.git.object_type(local_oid)
        target = self._scan_tag(local_oid) if object_type == "tag" else local_oid
        target_type = self.git.object_type(target)
        if target_type == "blob":
            self._scan_blob(target, "blob")
            return
        if target_type == "tree":
            self._scan_direct_tree(target)
            return
        if target_type != "commit":
            raise SafeGateError("git_object", "SYSTEM-GIT-OBJECT-TYPE")

        exclusions = list(new_ref_exclusions)
        if set(remote_oid) != {"0"}:
            exclusions.append(remote_oid)
        commits = self._list_commits(target, exclusions)
        for commit in commits:
            self.scan_commit(commit)
        self._scan_tip_workflows(target)


def _parse_updates_bytes(raw: bytes) -> list[tuple[str, str, bytes, str]]:
    if not raw or len(raw) > MAX_METADATA_BYTES:
        raise SafeGateError("ref", "SYSTEM-UPDATES-UNREADABLE")
    updates: list[tuple[str, str, bytes, str]] = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 4:
            raise SafeGateError("ref", "SYSTEM-UPDATE-MALFORMED")
        try:
            local_ref = parts[0].decode("utf-8", errors="surrogateescape")
            local_oid = parts[1].decode("ascii", errors="strict")
            remote_oid = parts[3].decode("ascii", errors="strict")
        except UnicodeError:
            raise SafeGateError("ref", "SYSTEM-UPDATE-MALFORMED") from None
        updates.append((local_ref, local_oid, parts[2], remote_oid))
    if not updates:
        raise SafeGateError("ref", "SYSTEM-UPDATES-EMPTY")
    return updates


def _parse_updates(path: Path) -> list[tuple[str, str, bytes, str]]:
    raw = _read_bounded(
        path,
        MAX_METADATA_BYTES,
        SafeGateError("ref", "SYSTEM-UPDATES-UNREADABLE"),
    )
    return _parse_updates_bytes(raw)


def _read_updates_stdin() -> list[tuple[str, str, bytes, str]]:
    try:
        raw = sys.stdin.buffer.read(MAX_METADATA_BYTES + 1)
    except (OSError, ValueError):
        raise SafeGateError("ref", "SYSTEM-UPDATES-UNREADABLE") from None
    return _parse_updates_bytes(raw)


def scan_pre_push(
    scanner: GateScanner,
    updates: Sequence[tuple[str, str, bytes, str]],
) -> None:
    for _local_ref, local_oid, remote_ref, remote_oid in updates:
        scanner.scan_update(
            local_oid,
            remote_oid,
            remote_ref,
        )


def _read_event(path: Path) -> dict[str, object]:
    raw = _read_bounded(
        path,
        MAX_EVENT_BYTES,
        SafeGateError("event", "SYSTEM-EVENT-UNREADABLE"),
    )
    try:
        event = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise SafeGateError("event", "SYSTEM-EVENT-MALFORMED") from None
    if not isinstance(event, dict):
        raise SafeGateError("event", "SYSTEM-EVENT-MALFORMED")
    return event


def _required_string(mapping: object, key: str, surface: str) -> str:
    if not isinstance(mapping, dict):
        raise SafeGateError(surface, "SYSTEM-EVENT-MALFORMED")
    value = mapping.get(key)
    if not isinstance(value, str):
        raise SafeGateError(surface, "SYSTEM-EVENT-MALFORMED")
    return value


def scan_ci_event(scanner: GateScanner, event_path: Path, event_name: str) -> None:
    event = _read_event(event_path)
    if event_name == "push":
        local_oid = _required_string(event, "after", "ref")
        remote_oid = _required_string(event, "before", "ref")
        remote_ref_text = _required_string(event, "ref", "ref")
        exclusions: list[str] = []
        if set(remote_oid) == {"0"} and set(local_oid) != {"0"}:
            repository = event.get("repository")
            default_branch = _required_string(repository, "default_branch", "ref")
            if not default_branch or "\x00" in default_branch:
                raise SafeGateError("ref", "SYSTEM-EVENT-MALFORMED")
            default_ref = f"refs/remotes/origin/{default_branch}"
            try:
                scanner.git.run(["rev-parse", "--verify", default_ref], "git_object")
            except SafeGateError:
                scanner.git.run(
                    [
                        "fetch",
                        "--quiet",
                        "--no-tags",
                        "origin",
                        f"+refs/heads/{default_branch}:{default_ref}",
                    ],
                    "git_object",
                )
            exclusions.append(default_ref)
        scanner.scan_update(
            local_oid,
            remote_oid,
            remote_ref_text.encode("utf-8", errors="surrogateescape"),
            new_ref_exclusions=exclusions,
        )
        return

    if event_name == "pull_request":
        pull_request = event.get("pull_request")
        title = _required_string(pull_request, "title", "pr_title")
        body_value = pull_request.get("body") if isinstance(pull_request, dict) else None
        body = "" if body_value is None else body_value
        if not isinstance(body, str):
            raise SafeGateError("pr_body", "SYSTEM-EVENT-MALFORMED")
        base = pull_request.get("base") if isinstance(pull_request, dict) else None
        head = pull_request.get("head") if isinstance(pull_request, dict) else None
        base_ref = _required_string(base, "ref", "ref")
        head_ref = _required_string(head, "ref", "ref")
        base_oid = _required_string(base, "sha", "ref")
        head_oid = _required_string(head, "sha", "ref")
        scanner.scan_bytes("ref", base_ref.encode("utf-8", errors="surrogateescape"))
        scanner.scan_bytes("ref", head_ref.encode("utf-8", errors="surrogateescape"))
        scanner.scan_bytes("pr_title", title.encode("utf-8", errors="surrogateescape"))
        scanner.scan_bytes("pr_body", body.encode("utf-8", errors="surrogateescape"))
        scanner.scan_update(
            head_oid,
            base_oid,
            head_ref.encode("utf-8", errors="surrogateescape"),
        )
        return

    raise SafeGateError("event", "SYSTEM-EVENT-UNSUPPORTED")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--public-only", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate")
    subparsers.add_parser("index")
    pre_push = subparsers.add_parser("pre-push")
    updates = pre_push.add_mutually_exclusive_group(required=True)
    updates.add_argument("--updates-file", type=Path)
    updates.add_argument("--updates-stdin", action="store_true")

    ci = subparsers.add_parser("ci-event")
    ci.add_argument("--event-path", type=Path, required=True)
    ci.add_argument("--event-name", choices=("push", "pull_request"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    reporter = Reporter()
    try:
        args = build_parser().parse_args(argv)
        policy = load_policy(
            args.policy,
            args.overlay,
            require_overlay=not args.public_only,
        )
        scanner = GateScanner(policy, args.repo.resolve())
        reporter = scanner.reporter
        if args.command == "validate":
            pass
        elif args.command == "index":
            scanner.scan_index()
        elif args.command == "pre-push":
            updates = (
                _read_updates_stdin()
                if args.updates_stdin
                else _parse_updates(args.updates_file)
            )
            scan_pre_push(scanner, updates)
        elif args.command == "ci-event":
            scan_ci_event(scanner, args.event_path, args.event_name)
        else:
            raise SafeGateError("scanner", "SYSTEM-COMMAND-UNKNOWN")
    except SafeGateError as exc:
        reporter.add_error(exc.surface, exc.pattern_id)
    except Exception:
        reporter.add_error("scanner", "SYSTEM-SCANNER-ERROR")
    return reporter.emit()


if __name__ == "__main__":
    raise SystemExit(main())
