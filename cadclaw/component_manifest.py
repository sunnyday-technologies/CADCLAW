"""Component manifest helpers for authored STEP libraries.

The manifest is intentionally observational: it records where authored
STEP assets live, what their bbox signatures look like, and which entries
still need BOM or connector metadata. It does not author contextual
geometry such as plates, brackets, mounts, or hole patterns.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import yaml


DEFAULT_LIBRARIES = ("Components", "Advanced")
Sig3 = Tuple[float, float, float]


@dataclass(frozen=True)
class SignatureSummary:
    sig: Sig3
    count: int


@dataclass(frozen=True)
class StepInspection:
    status: str
    part_count: int
    signatures: List[SignatureSummary]
    error_type: Optional[str] = None


def slugify(value: str) -> str:
    """Return a stable, ASCII-ish id fragment for manifest entries."""
    lowered = value.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unnamed"


def iter_step_files(
    cad_root: Path | str,
    libraries: Sequence[str] = DEFAULT_LIBRARIES,
) -> List[Path]:
    """Return all STEP files under the requested CAD component libraries."""
    root = Path(cad_root)
    files: List[Path] = []
    for library in libraries:
        lib_root = root / library
        if not lib_root.exists():
            continue
        for path in lib_root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".step", ".stp"}:
                files.append(path)
    return sorted(files, key=lambda p: p.as_posix().lower())


def inspect_step_file(path: Path | str) -> StepInspection:
    """Inspect one STEP file using CADCLAW's existing bbox histogram API.

    Error details are deliberately reduced to an exception class name so a
    generated manifest does not accidentally echo local paths or sensitive
    environment details from a lower-level parser error.
    """
    try:
        from .inspect import histogram_signatures, load_parts

        parts = load_parts(str(path))
        buckets = histogram_signatures(parts)
    except Exception as exc:  # pragma: no cover - exercised by CAD runtime
        return StepInspection(
            status="inspect_failed",
            part_count=0,
            signatures=[],
            error_type=exc.__class__.__name__,
        )

    return StepInspection(
        status="ok",
        part_count=len(parts),
        signatures=[
            SignatureSummary(sig=b.sig, count=b.count)
            for b in buckets
        ],
    )


def _source_path(path: Path, cad_root: Path) -> str:
    try:
        rel = path.relative_to(cad_root)
    except ValueError:
        return path.name
    return (Path("CAD") / rel).as_posix()


def _entry_id(library: str, category: str, stem: str) -> str:
    return "_".join([slugify(library), slugify(category), slugify(stem)])


def _entry_kind(category: str, inspection: StepInspection) -> str:
    if category.lower() == "assemblies":
        return "macro_assembly"
    if inspection.status == "ok" and inspection.part_count > 1:
        return "assembly"
    return "part"


def _is_stock_like(category: str, stem: str) -> bool:
    category_slug = slugify(category)
    if category_slug not in {"linear_rail", "v_slot"}:
        return False
    text = f"{category} {stem}".lower()
    stock_terms = (
        "linear rail",
        "v-slot",
        "v slot",
        "c-beam",
        "c beam",
        "open rail",
    )
    return any(term in text for term in stock_terms)


def _entry_for_path(
    path: Path,
    cad_root: Path,
    inspect_step: Callable[[Path], StepInspection],
) -> dict:
    rel_parts = path.relative_to(cad_root).parts
    library = rel_parts[0] if len(rel_parts) > 0 else "Unknown"
    category = rel_parts[1] if len(rel_parts) > 1 else "Uncategorized"
    display_name = path.stem
    inspection = inspect_step(path)
    stock_like = _is_stock_like(category, display_name)

    return {
        "id": _entry_id(library, category, display_name),
        "display_name": display_name,
        "source_library": library,
        "category": category,
        "source_path": _source_path(path, cad_root),
        "kind": _entry_kind(category, inspection),
        "stock_like": stock_like,
        "generation_policy": (
            "stock_profile_may_be_generated_or_placed"
            if stock_like else "place_authored_step_only"
        ),
        "inspection": {
            "status": inspection.status,
            "part_count": inspection.part_count,
            "signatures": [
                {"sig": list(summary.sig), "count": summary.count}
                for summary in inspection.signatures
            ],
            **(
                {"error_type": inspection.error_type}
                if inspection.error_type else {}
            ),
        },
        "bom_binding": {
            "status": "needs_user_mapping",
            "public_bom_ids": [],
        },
        "connector_metadata": {
            "status": "needs_definition",
        },
        "source_note": (
            "Authored STEP asset. Verify upstream license/source terms before "
            "public redistribution."
        ),
    }


def build_component_manifest(
    cad_root: Path | str,
    libraries: Sequence[str] = DEFAULT_LIBRARIES,
    inspect_step: Callable[[Path], StepInspection] = inspect_step_file,
    generated_at: Optional[str] = None,
) -> dict:
    """Build a component manifest for STEP files under `cad_root`."""
    root = Path(cad_root)
    entries = [
        _entry_for_path(path, root, inspect_step)
        for path in iter_step_files(root, libraries=libraries)
    ]
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()

    return {
        "schema_version": "m3_component_manifest.v0.1",
        "generated_at": timestamp,
        "source_cad_root_hint": root.as_posix(),
        "libraries": list(libraries),
        "policy": {
            "default_non_stock_geometry": "place_authored_step_only",
            "generated_geometry_allowed": [
                "linear stock cut to length",
                "explicit belt segments",
                "optional standard fastener stand-ins when requested",
            ],
            "missing_required_component": "emit_not_built_yet",
            "release_placeholder_policy": "explicit placeholders fail release validation",
        },
        "components": entries,
    }


def write_manifest(manifest: dict, output_path: Path | str) -> None:
    """Write a manifest as stable YAML."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(manifest, f, sort_keys=False, allow_unicode=False)


__all__ = [
    "DEFAULT_LIBRARIES",
    "SignatureSummary",
    "StepInspection",
    "build_component_manifest",
    "inspect_step_file",
    "iter_step_files",
    "slugify",
    "write_manifest",
]
