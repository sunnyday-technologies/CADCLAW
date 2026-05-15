"""CadQuery assembly compiler skeleton for CADCLAW assembly specs.

The first implementation slice focuses on deterministic source resolution and
dry-run reporting. Full geometry export is deliberately small and explicit:
place authored STEP assets with declared transforms, then write the configured
non-authoritative STEP path.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import json
import time
from typing import Dict, Iterable, List, Optional

import yaml

from .assembly_spec import AssemblySpec, Instance, Transform, load_assembly_spec
from .connector_metadata import ConnectorMetadata, load_connector_metadata
from .findings import ConfidenceBudget, Finding, Report, Severity


DESIGN_INVENTORY_VERSION = "design_inventory.v0.1"


@dataclass(frozen=True)
class ResolvedInstance:
    id: str
    role: str
    source_ref: str
    resolved_path: str
    exists: bool
    transform: Dict[str, List[float]]
    color_label: Optional[str] = None
    connector_metadata: str = "not_checked"


@dataclass(frozen=True)
class AssemblyBuildPlan:
    spec_path: str
    output_step: str
    dry_run: bool
    instances: List[ResolvedInstance]
    connector_metadata_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "schema_version": DESIGN_INVENTORY_VERSION,
            "spec_path": self.spec_path,
            "output_step": self.output_step,
            "dry_run": self.dry_run,
            "connector_metadata_path": self.connector_metadata_path,
            "instances": [asdict(instance) for instance in self.instances],
        }


def _as_posix(path: Path) -> str:
    return path.as_posix()


def _display_path(path: Path) -> str:
    if path.is_absolute():
        try:
            return Path(os.path.relpath(path, Path.cwd())).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def _resolve_config_path(value: str, spec_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return cwd_candidate
    return spec_dir / path


def _resolve_output_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _load_manifest_sources(manifest_paths: Iterable[str], spec_dir: Path) -> Dict[str, str]:
    sources: Dict[str, str] = {}
    for manifest_path in manifest_paths:
        path = _resolve_config_path(manifest_path, spec_dir)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get("components", []):
            entry_id = entry.get("id")
            source_path = entry.get("source_path")
            if entry_id and source_path:
                sources[str(entry_id)] = str(source_path)
    return sources


def _candidate_paths(source_ref: str, spec: AssemblySpec, spec_dir: Path) -> List[Path]:
    source = Path(source_ref)
    if source.is_absolute():
        return [source]

    candidates: List[Path] = [
        Path.cwd() / source,
        spec_dir / source,
    ]
    source_posix = source.as_posix()
    for root_value in spec.component_roots:
        root = _resolve_config_path(root_value, spec_dir)
        candidates.append(root / source)
        if source_posix.startswith("CAD/"):
            candidates.append(root.parent / source)
            candidates.append(root / Path(source_posix.removeprefix("CAD/")))
    return candidates


def resolve_source_path(source_ref: str, spec: AssemblySpec, spec_dir: Path) -> Path:
    candidates = _candidate_paths(source_ref, spec, spec_dir)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _instance_source_ref(
    instance: Instance,
    manifest_sources: Dict[str, str],
) -> Optional[str]:
    if instance.source_path:
        return instance.source_path
    if instance.component_id:
        return manifest_sources.get(instance.component_id)
    return None


def _metadata_status(
    instance: Instance,
    source_ref: str,
    metadata: Optional[ConnectorMetadata],
) -> str:
    if metadata is None:
        return "not_provided"
    keys = metadata.component_keys()
    if instance.component_id and instance.component_id in keys:
        return "available"
    if source_ref in keys or Path(source_ref).as_posix() in keys:
        return "available"
    return "missing"


def plan_assembly_build(
    spec_path: str | Path,
    connector_metadata_path: str | Path | None = None,
    dry_run: bool = True,
) -> AssemblyBuildPlan:
    spec_file = Path(spec_path)
    spec_dir = spec_file.resolve().parent
    spec = load_assembly_spec(spec_file)
    manifest_sources = _load_manifest_sources(spec.manifests, spec_dir)
    metadata_value = connector_metadata_path or spec.connector_metadata
    metadata_path = (
        _resolve_config_path(str(metadata_value), spec_dir)
        if metadata_value else None
    )
    metadata = load_connector_metadata(metadata_path) if metadata_path else None

    resolved: List[ResolvedInstance] = []
    for instance in spec.instances:
        source_ref = _instance_source_ref(instance, manifest_sources)
        if source_ref is None:
            source_ref = instance.component_id or "<missing-source>"
            resolved_path = Path(source_ref)
            exists = False
        else:
            resolved_path = resolve_source_path(source_ref, spec, spec_dir)
            exists = resolved_path.exists()
        transform = instance.transform.model_dump()
        resolved.append(ResolvedInstance(
            id=instance.id,
            role=instance.role,
            source_ref=source_ref,
            resolved_path=_display_path(resolved_path),
            exists=exists,
            transform=transform,
            color_label=instance.color_label,
            connector_metadata=_metadata_status(instance, source_ref, metadata),
        ))

    return AssemblyBuildPlan(
        spec_path=_as_posix(spec_file),
        output_step=spec.outputs.step,
        dry_run=dry_run,
        instances=resolved,
        connector_metadata_path=_display_path(metadata_path) if metadata_path else None,
    )


def _apply_transform(workplane, transform: Transform):
    rx, ry, rz = transform.rotate_deg
    tx, ty, tz = transform.translate_mm
    result = workplane
    if rx:
        result = result.rotate((0, 0, 0), (1, 0, 0), rx)
    if ry:
        result = result.rotate((0, 0, 0), (0, 1, 0), ry)
    if rz:
        result = result.rotate((0, 0, 0), (0, 0, 1), rz)
    return result.translate((tx, ty, tz))


def _export_step(spec: AssemblySpec, spec_path: Path, plan: AssemblyBuildPlan) -> None:
    import cadquery as cq
    from cadquery import Assembly

    assy = Assembly()
    by_id = {instance.id: instance for instance in spec.instances}
    for resolved in plan.instances:
        if not resolved.exists:
            continue
        source = cq.importers.importStep(resolved.resolved_path)
        placed = _apply_transform(source, by_id[resolved.id].transform)
        assy.add(placed, name=resolved.id)

    output = _resolve_output_path(spec.outputs.step)
    output.parent.mkdir(parents=True, exist_ok=True)
    assy.save(str(output))


def write_design_inventory(plan: AssemblyBuildPlan, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(plan.to_dict(), f, indent=2)
        f.write("\n")


def run_assembly_build(
    spec_path: str | Path,
    connector_metadata_path: str | Path | None = None,
    dry_run: bool = True,
    write_inventory: bool = False,
) -> Report:
    start = time.time()
    spec_file = Path(spec_path)
    spec = load_assembly_spec(spec_file)
    metadata_value = connector_metadata_path or spec.connector_metadata
    plan = plan_assembly_build(
        spec_file,
        connector_metadata_path=metadata_value,
        dry_run=dry_run,
    )

    findings: List[Finding] = []
    missing = [instance for instance in plan.instances if not instance.exists]
    for instance in missing:
        findings.append(Finding(
            id="assemble.source_missing",
            category="assemble",
            severity=Severity.FAIL,
            message=f"{instance.id}: source STEP not found",
            evidence={
                "instance": instance.id,
                "source_ref": instance.source_ref,
                "resolved_path": instance.resolved_path,
            },
        ))

    if metadata_value:
        missing_meta = [
            instance for instance in plan.instances
            if instance.connector_metadata == "missing"
        ]
        for instance in missing_meta:
            findings.append(Finding(
                id="assemble.connector_metadata_missing",
                category="assemble",
                severity=Severity.WARN,
                message=f"{instance.id}: no connector frames for source",
                evidence={
                    "instance": instance.id,
                    "source_ref": instance.source_ref,
                },
            ))
    else:
        findings.append(Finding(
            id="assemble.connector_metadata_not_provided",
            category="assemble",
            severity=Severity.WARN,
            message="connector metadata was not provided for this build round",
        ))

    for item in spec.not_built_yet:
        findings.append(Finding(
            id="assemble.not_built_yet",
            category="assemble",
            severity=Severity.WARN,
            message=f"{item.item}: {item.reason}",
            evidence={
                "item": item.item,
                "required_for_release": item.required_for_release,
            },
        ))

    if not dry_run and not missing:
        _export_step(spec, spec_file, plan)

    if write_inventory and spec.outputs.design_inventory:
        write_design_inventory(plan, spec.outputs.design_inventory)

    confidence = ConfidenceBudget(
        checked=[
            "assembly spec schema",
            "instance source path resolution",
            "protected output path validation",
            "connector metadata presence"
            if metadata_value else "connector metadata omission",
        ],
        not_checked=[
            "interference",
            "BOM-vs-CAD parity",
            "rendered view alignment",
            *(
                ["CadQuery STEP export"]
                if dry_run else []
            ),
        ],
        assumptions=list(spec.assumptions),
    )
    report = Report(
        findings=findings,
        confidence_budget=confidence,
        duration_ms=(time.time() - start) * 1000,
        meta={
            "spec": str(spec_path),
            "project": spec.meta.project,
            "assembly_id": spec.meta.assembly_id,
            "active_variant": spec.active_variant,
            "dry_run": dry_run,
            "output_step": spec.outputs.step,
            "instances": len(plan.instances),
            "missing_sources": len(missing),
            "connector_metadata": plan.connector_metadata_path,
            "resolved_instances": [asdict(instance) for instance in plan.instances],
        },
    )
    report.overall = report.compute_overall()
    return report


__all__ = [
    "AssemblyBuildPlan",
    "DESIGN_INVENTORY_VERSION",
    "ResolvedInstance",
    "plan_assembly_build",
    "resolve_source_path",
    "run_assembly_build",
    "write_design_inventory",
]
