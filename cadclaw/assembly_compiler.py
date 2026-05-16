"""CadQuery assembly compiler skeleton for CADCLAW assembly specs.

The first implementation slice focuses on deterministic source resolution and
dry-run reporting. Full geometry export is deliberately small and explicit:
place authored STEP assets with declared transforms, then write the configured
non-authoritative STEP path.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import csv
import os
from pathlib import Path
import json
import time
from typing import Callable, Dict, Iterable, List, Optional

import yaml

from .assembly_spec import AssemblySpec, Instance, ReviewView, Transform, load_assembly_spec
from .connector_metadata import ConnectorMetadata, load_connector_metadata
from .findings import ConfidenceBudget, Finding, Report, Severity


DESIGN_INVENTORY_VERSION = "design_inventory.v0.1"
GENERATED_SOURCE_PREFIXES = ("generated:", "parametric:", "placeholder:")


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


@dataclass(frozen=True)
class ReviewViewOutput:
    name: str
    view: str
    output_path: str
    width: int
    height: int
    rendered: bool
    message: Optional[str] = None


@dataclass(frozen=True)
class AssemblySequenceStepOutput:
    id: str
    title: str
    step_index: int
    instance_ids: List[str]
    cumulative_instance_ids: List[str]
    output_step: Optional[str]
    review_views: List[ReviewViewOutput]
    notes: Optional[str] = None


def _shape_bbox(shape) -> List[float]:
    bb = shape.BoundingBox()
    return [
        round(bb.xmin, 3),
        round(bb.ymin, 3),
        round(bb.zmin, 3),
        round(bb.xmax, 3),
        round(bb.ymax, 3),
        round(bb.zmax, 3),
    ]


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


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve(strict=False))) == os.path.normcase(
        str(b.resolve(strict=False))
    )


def _ordered_unique(values: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _has_explicit_spacers(spec: AssemblySpec) -> bool:
    return any("spacer" in instance.role.lower() for instance in spec.instances)


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


def _protected_output_findings(spec: AssemblySpec, spec_dir: Path) -> List[Finding]:
    output = _resolve_output_path(spec.outputs.step)
    findings: List[Finding] = []
    for protected_value in spec.protected_paths:
        protected = _resolve_config_path(protected_value, spec_dir)
        if _same_path(output, protected):
            findings.append(Finding(
                id="assemble.protected_output_path",
                category="assemble",
                severity=Severity.FAIL,
                message=f"output STEP would overwrite protected CAD export: {spec.outputs.step}",
                suggested_fix="Set outputs.step to a generated build path outside protected CAD exports.",
                evidence={
                    "output_step": _display_path(output),
                    "protected_path": _display_path(protected),
                },
            ))
    return findings


def _generation_policy_findings(plan: AssemblyBuildPlan) -> List[Finding]:
    findings: List[Finding] = []
    for instance in plan.instances:
        source = instance.source_ref.strip().lower()
        if source.startswith(GENERATED_SOURCE_PREFIXES):
            findings.append(Finding(
                id="assemble.generated_geometry_blocked",
                category="assemble",
                severity=Severity.FAIL,
                message=f"{instance.id}: generated geometry source is not allowed in assembly specs",
                suggested_fix=(
                    "Use an authored STEP source_path/component_id, or explicitly add a "
                    "future stock-only generator contract for this part."
                ),
                evidence={
                    "instance": instance.id,
                    "source_ref": instance.source_ref,
                    "blocked_prefixes": list(GENERATED_SOURCE_PREFIXES),
                },
            ))
    return findings


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


def _export_step(
    spec: AssemblySpec,
    spec_path: Path,
    plan: AssemblyBuildPlan,
    output_path: str | Path | None = None,
    instance_ids: Iterable[str] | None = None,
) -> Path:
    import cadquery as cq
    from cadquery import Assembly

    assy = Assembly()
    spec_dir = spec_path.resolve().parent
    manifest_sources = _load_manifest_sources(spec.manifests, spec_dir)
    by_id = {instance.id: instance for instance in spec.instances}
    wanted = set(instance_ids) if instance_ids is not None else None
    for resolved in plan.instances:
        if wanted is not None and resolved.id not in wanted:
            continue
        if not resolved.exists:
            continue
        instance = by_id[resolved.id]
        source_ref = _instance_source_ref(instance, manifest_sources)
        if source_ref is None:
            continue
        source_path = resolve_source_path(source_ref, spec, spec_dir)
        source = cq.importers.importStep(str(source_path))
        placed = _apply_transform(source, instance.transform)
        assy.add(placed, name=resolved.id)

    output = Path(output_path) if output_path is not None else _resolve_output_path(spec.outputs.step)
    if not output.is_absolute():
        output = _resolve_output_path(str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    assy.save(str(output))
    return output


def write_design_inventory(plan: AssemblyBuildPlan, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(plan.to_dict(), f, indent=2)
        f.write("\n")


def write_assembly_bom_csv(
    plan: AssemblyBuildPlan,
    output_path: str | Path,
    instance_ids: Iterable[str] | None = None,
) -> None:
    path = Path(output_path)
    if not path.is_absolute():
        path = _resolve_output_path(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)

    wanted = set(instance_ids) if instance_ids is not None else None
    rows: Dict[tuple, dict] = {}
    for instance in plan.instances:
        if wanted is not None and instance.id not in wanted:
            continue
        key = (
            instance.source_ref,
            instance.role,
            instance.color_label or "",
            instance.connector_metadata,
        )
        row = rows.setdefault(key, {
            "quantity": 0,
            "role": instance.role,
            "source_ref": instance.source_ref,
            "resolved_path": instance.resolved_path,
            "color_label": instance.color_label or "",
            "connector_metadata": instance.connector_metadata,
            "instance_ids": [],
        })
        row["quantity"] += 1
        row["instance_ids"].append(instance.id)

    with path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "quantity",
            "role",
            "source_ref",
            "resolved_path",
            "color_label",
            "connector_metadata",
            "instance_ids",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(rows.values(), key=lambda r: (r["role"], r["source_ref"])):
            writer.writerow({
                **row,
                "instance_ids": ";".join(row["instance_ids"]),
            })


def inspect_component(
    spec_path: str | Path,
    component_id: str | None = None,
    source_path: str | Path | None = None,
    render_views: bool = False,
    views: Optional[List[str]] = None,
    views_dir: str | Path | None = None,
    renderer: Optional[Callable[..., str]] = None,
) -> Report:
    start = time.time()
    spec_file = Path(spec_path)
    spec_dir = spec_file.resolve().parent
    spec = load_assembly_spec(spec_file)
    manifest_sources = _load_manifest_sources(spec.manifests, spec_dir)

    findings: List[Finding] = []
    if bool(component_id) == bool(source_path):
        findings.append(Finding(
            id="assemble.inspect_component_selector_invalid",
            category="assemble",
            severity=Severity.FAIL,
            message="provide exactly one of component_id or source_path",
        ))
        source_ref = "<invalid-selector>"
        resolved = Path(source_ref)
    elif component_id:
        if component_id not in manifest_sources:
            findings.append(Finding(
                id="assemble.inspect_component_missing_manifest_entry",
                category="assemble",
                severity=Severity.FAIL,
                message=f"component_id not found in manifests: {component_id}",
                evidence={"component_id": component_id},
            ))
            source_ref = component_id
            resolved = Path(component_id)
        else:
            source_ref = manifest_sources[component_id]
            resolved = resolve_source_path(source_ref, spec, spec_dir)
    else:
        source_ref = str(source_path)
        resolved = resolve_source_path(source_ref, spec, spec_dir)

    exists = resolved.exists()
    part_summaries: List[dict] = []
    signature_histogram: Dict[str, int] = {}
    render_outputs: List[ReviewViewOutput] = []
    if not exists:
        findings.append(Finding(
            id="assemble.inspect_component_source_missing",
            category="assemble",
            severity=Severity.FAIL,
            message=f"component STEP not found: {source_ref}",
            evidence={
                "source_ref": source_ref,
                "resolved_path": _display_path(resolved),
            },
        ))
    elif source_ref.strip().lower().startswith(GENERATED_SOURCE_PREFIXES):
        findings.extend(_generation_policy_findings(AssemblyBuildPlan(
            spec_path=str(spec_path),
            output_step=spec.outputs.step,
            dry_run=True,
            instances=[ResolvedInstance(
                id=component_id or "source_path",
                role="component",
                source_ref=source_ref,
                resolved_path=_display_path(resolved),
                exists=True,
                transform={"translate_mm": [0.0, 0.0, 0.0], "rotate_deg": [0.0, 0.0, 0.0]},
            )],
        )))
    else:
        from .inventory import center, load_and_dedup, sig

        parts = load_and_dedup(str(resolved))
        if not parts:
            findings.append(Finding(
                id="assemble.inspect_component_empty",
                category="assemble",
                severity=Severity.FAIL,
                message=f"component STEP loaded but no solids/shells were found: {source_ref}",
                evidence={"resolved_path": _display_path(resolved)},
            ))
        for index, part in enumerate(parts):
            signature = sig(part)
            key = ",".join(f"{value:g}" for value in signature)
            signature_histogram[key] = signature_histogram.get(key, 0) + 1
            part_summaries.append({
                "index": index,
                "signature_mm": list(signature),
                "center_mm": [round(value, 3) for value in center(part)],
                "bbox_mm": _shape_bbox(part),
            })

        if render_views:
            view_names = views or ["front", "side", "top", "iso"]
            out_dir = (
                Path(views_dir)
                if views_dir is not None
                else _resolve_output_path(spec.outputs.views_dir) / "components"
            )
            if not out_dir.is_absolute():
                out_dir = _resolve_output_path(str(out_dir))
            safe_id = component_id or Path(source_ref).stem
            safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in safe_id)
            out_dir.mkdir(parents=True, exist_ok=True)
            if renderer is None:
                from .render import render_step_to_png as renderer
            for view_name in view_names:
                output = out_dir / f"{safe_id}_{view_name}.png"
                try:
                    renderer(
                        str(resolved),
                        str(output),
                        width=900,
                        height=700,
                        view=view_name,
                    )
                    render_outputs.append(ReviewViewOutput(
                        name=f"{safe_id}_{view_name}",
                        view=view_name,
                        output_path=_display_path(output),
                        width=900,
                        height=700,
                        rendered=output.exists(),
                    ))
                    if not output.exists():
                        findings.append(Finding(
                            id="assemble.inspect_component_render_missing_output",
                            category="assemble",
                            severity=Severity.FAIL,
                            message=f"{view_name}: renderer completed but no PNG was written",
                            evidence={"output_path": _display_path(output)},
                        ))
                except Exception as exc:
                    findings.append(Finding(
                        id="assemble.inspect_component_render_failed",
                        category="assemble",
                        severity=Severity.FAIL,
                        message=f"{view_name}: component render failed: {exc}",
                        evidence={"view": view_name, "output_path": _display_path(output)},
                    ))
                    render_outputs.append(ReviewViewOutput(
                        name=f"{safe_id}_{view_name}",
                        view=view_name,
                        output_path=_display_path(output),
                        width=900,
                        height=700,
                        rendered=False,
                        message=str(exc),
                    ))

    report = Report(
        findings=findings,
        confidence_budget=ConfidenceBudget(
            checked=[
                "component source path resolution",
                "STEP loadability" if exists else "STEP path presence",
                "bbox signature extraction" if part_summaries else "bbox signature extraction not completed",
            ],
            not_checked=[] if render_views else ["component review rendering"],
            assumptions=list(spec.assumptions),
        ),
        duration_ms=(time.time() - start) * 1000,
        meta={
            "spec": str(spec_path),
            "component_id": component_id,
            "source_ref": source_ref,
            "resolved_path": _display_path(resolved),
            "exists": exists,
            "part_count": len(part_summaries),
            "signature_histogram": signature_histogram,
            "parts": part_summaries,
            "rendered_views": [asdict(output) for output in render_outputs],
        },
    )
    report.overall = report.compute_overall()
    return report


def _sequence_output_dir(spec: AssemblySpec, output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        path = Path(output_dir)
    else:
        step_path = _resolve_output_path(spec.outputs.step)
        path = step_path.parent / "sequence"
    if not path.is_absolute():
        path = _resolve_output_path(str(path))
    return path


def _review_views_for_names(spec: AssemblySpec, view_names: List[str]) -> List[ReviewView]:
    by_key: Dict[str, ReviewView] = {}
    for view in spec.review_views:
        by_key[view.name] = view
        by_key[view.view] = view

    resolved: List[ReviewView] = []
    for name in view_names:
        if name in by_key:
            view = by_key[name]
            resolved.append(ReviewView(
                name=name,
                view=view.view,
                width=view.width,
                height=view.height,
                azimuth=view.azimuth,
                elevation=view.elevation,
                notes=view.notes,
            ))
        else:
            resolved.append(ReviewView(name=name, view=name, width=1400, height=900))
    return resolved


def run_assembly_sequence(
    spec_path: str | Path,
    output_dir: str | Path | None = None,
    view_names: Optional[List[str]] = None,
    dry_run: bool = False,
    render_views: bool = True,
    rotate_final: bool = False,
    bom_csv_path: str | Path | None = None,
    write_bom: bool = True,
    renderer: Optional[Callable[..., str]] = None,
    gif_renderer: Optional[Callable[..., int]] = None,
) -> Report:
    start = time.time()
    spec_file = Path(spec_path)
    spec = load_assembly_spec(spec_file)
    out_dir = _sequence_output_dir(spec, output_dir)
    steps_dir = out_dir / "steps"
    views_dir = out_dir / "views"
    final_dir = out_dir / "final"
    view_names = view_names or ["front", "side", "top", "hero", "iso"]
    review_views = _review_views_for_names(spec, view_names)

    plan = plan_assembly_build(spec_file, dry_run=dry_run)
    findings: List[Finding] = []
    findings.extend(_protected_output_findings(spec, spec_file.resolve().parent))
    findings.extend(_generation_policy_findings(plan))
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

    if not spec.assembly_sequence:
        findings.append(Finding(
            id="assemble.sequence_not_provided",
            category="assemble",
            severity=Severity.FAIL,
            message="assembly_sequence is required to render assembly process steps",
        ))

    cumulative: List[str] = []
    step_outputs: List[AssemblySequenceStepOutput] = []
    blocking = any(f.severity == Severity.FAIL for f in findings)
    if renderer is None and render_views:
        from .render import render_step_to_png as renderer

    for index, step in enumerate(spec.assembly_sequence, start=1):
        cumulative = _ordered_unique([*cumulative, *step.instance_ids])
        safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in step.id)
        step_prefix = f"{index:02d}_{safe_id}"
        step_path = steps_dir / f"{step_prefix}.step"
        rendered: List[ReviewViewOutput] = []

        if not dry_run and not blocking:
            written_step = _export_step(
                spec,
                spec_file,
                plan,
                output_path=step_path,
                instance_ids=cumulative,
            )
        else:
            written_step = None

        if render_views and written_step is not None:
            for view in review_views:
                output = views_dir / f"{step_prefix}_{view.name}.png"
                try:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    renderer(
                        str(written_step),
                        str(output),
                        width=view.width,
                        height=view.height,
                        view=view.view,
                        azimuth=view.azimuth,
                        elevation=view.elevation,
                    )
                    rendered.append(ReviewViewOutput(
                        name=view.name,
                        view=view.view,
                        output_path=_display_path(output),
                        width=view.width,
                        height=view.height,
                        rendered=output.exists(),
                    ))
                    if not output.exists():
                        findings.append(Finding(
                            id="assemble.sequence_view_missing_output",
                            category="assemble",
                            severity=Severity.FAIL,
                            message=f"{step.id}/{view.name}: renderer completed but no PNG was written",
                            evidence={"output_path": _display_path(output)},
                        ))
                except Exception as exc:
                    findings.append(Finding(
                        id="assemble.sequence_view_render_failed",
                        category="assemble",
                        severity=Severity.FAIL,
                        message=f"{step.id}/{view.name}: render failed: {exc}",
                        evidence={"step": step.id, "view": view.view},
                    ))
                    rendered.append(ReviewViewOutput(
                        name=view.name,
                        view=view.view,
                        output_path=_display_path(output),
                        width=view.width,
                        height=view.height,
                        rendered=False,
                        message=str(exc),
                    ))
        elif render_views:
            findings.append(Finding(
                id="assemble.sequence_view_render_skipped",
                category="assemble",
                severity=Severity.WARN,
                message=f"{step.id}: review views skipped because STEP export did not run",
                evidence={"step": step.id, "dry_run": dry_run, "blocking": blocking},
            ))

        step_outputs.append(AssemblySequenceStepOutput(
            id=step.id,
            title=step.title,
            step_index=index,
            instance_ids=list(step.instance_ids),
            cumulative_instance_ids=list(cumulative),
            output_step=_display_path(written_step) if written_step else None,
            review_views=rendered,
            notes=step.notes,
        ))

    bom_output = None
    if write_bom:
        bom_value = bom_csv_path or spec.bom.output_path or spec.outputs.bom
        bom_output = Path(bom_value) if bom_value else out_dir / "assembly_bom.csv"
        if not bom_output.is_absolute():
            bom_output = _resolve_output_path(str(bom_output))
        write_assembly_bom_csv(plan, bom_output, instance_ids=cumulative or None)

    rotation_output = None
    if rotate_final:
        if dry_run or blocking or not cumulative:
            findings.append(Finding(
                id="assemble.sequence_rotation_skipped",
                category="assemble",
                severity=Severity.WARN,
                message="final rotation GIF skipped because final STEP export did not run",
                evidence={"dry_run": dry_run, "blocking": blocking},
            ))
        else:
            final_dir.mkdir(parents=True, exist_ok=True)
            final_step = final_dir / "final_sequence_assembly.step"
            written_final = _export_step(
                spec,
                spec_file,
                plan,
                output_path=final_step,
                instance_ids=cumulative,
            )
            rotation_output = final_dir / "final_rotate.gif"
            try:
                if gif_renderer is None:
                    from .render import render_radial_explode_gif as gif_renderer
                gif_renderer(
                    str(written_final),
                    str(rotation_output),
                    expansion=0.0,
                    explode_frames=1,
                    hold_frames=1,
                    rotate_frames=48,
                    fps=12,
                    width=960,
                    height=720,
                    view="hero",
                    gif_width=960,
                    gif_height=540,
                )
            except Exception as exc:
                findings.append(Finding(
                    id="assemble.sequence_rotation_failed",
                    category="assemble",
                    severity=Severity.FAIL,
                    message=f"final rotation GIF failed: {exc}",
                    evidence={"output_path": _display_path(rotation_output)},
                ))

    manifest = {
        "schema_version": "assembly_sequence_manifest.v0.1",
        "spec": str(spec_path),
        "project": spec.meta.project,
        "assembly_id": spec.meta.assembly_id,
        "active_variant": spec.active_variant,
        "output_dir": _display_path(out_dir),
        "steps": [
            {
                **asdict(step),
                "review_views": [asdict(view) for view in step.review_views],
            }
            for step in step_outputs
        ],
        "bom_csv": _display_path(bom_output) if bom_output else None,
        "rotation_gif": _display_path(rotation_output) if rotation_output else None,
    }
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "assembly_sequence_manifest.json"
        with manifest_path.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
    else:
        manifest_path = None

    confidence = ConfidenceBudget(
        checked=[
            "assembly sequence declaration",
            "instance source path resolution",
            "authored STEP placement policy",
            "BOM CSV generation" if write_bom else "BOM CSV skipped by request",
            *(
                ["explicit spacer placement declarations"]
                if _has_explicit_spacers(spec) else []
            ),
        ],
        not_checked=[
            *([] if not dry_run else ["sequence STEP export"]),
            *([] if render_views else ["sequence review rendering"]),
            *([] if rotate_final else ["final rotation GIF"]),
            *(
                [] if _has_explicit_spacers(spec)
                else ["spacer requirement inference"]
            ),
            "website BOM parity",
        ],
        assumptions=list(spec.assumptions),
    )
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
            "output_dir": _display_path(out_dir),
            "manifest": _display_path(manifest_path) if manifest_path else None,
            "steps": manifest["steps"],
            "bom_csv": manifest["bom_csv"],
            "rotation_gif": manifest["rotation_gif"],
        },
    )
    report.overall = report.compute_overall()
    return report


def _validate_expected_inventory(spec: AssemblySpec) -> tuple[List[Finding], dict]:
    expected_raw = spec.validation.get("expected_inventory")
    counts = Counter(instance.role for instance in spec.instances)
    inventory = dict(sorted(counts.items()))
    findings: List[Finding] = []
    if not expected_raw:
        findings.append(Finding(
            id="assemble.expected_inventory_not_provided",
            category="assemble",
            severity=Severity.WARN,
            message="spec.validation.expected_inventory was not provided",
        ))
        return findings, inventory

    if not isinstance(expected_raw, dict):
        findings.append(Finding(
            id="assemble.expected_inventory_invalid",
            category="assemble",
            severity=Severity.FAIL,
            message="spec.validation.expected_inventory must be a mapping of role to count",
            evidence={"expected_inventory_type": type(expected_raw).__name__},
        ))
        return findings, inventory

    expected: Dict[str, int] = {}
    for role, value in expected_raw.items():
        if not isinstance(value, int) or value < 0:
            findings.append(Finding(
                id="assemble.expected_inventory_invalid",
                category="assemble",
                severity=Severity.FAIL,
                message=f"expected count for role {role!r} must be a non-negative integer",
                evidence={"role": role, "value": value},
            ))
            continue
        expected[str(role)] = value

    for role in sorted(set(expected) | set(inventory)):
        got = inventory.get(role, 0)
        want = expected.get(role, 0)
        if got != want:
            findings.append(Finding(
                id="assemble.expected_inventory_mismatch",
                category="assemble",
                severity=Severity.FAIL,
                message=f"{role}: spec has {got}, expected {want}",
                evidence={"role": role, "got": got, "expected": want},
            ))
    return findings, inventory


def _view_output_path(views_dir: Path, view: ReviewView) -> Path:
    safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in view.name)
    return views_dir / f"{safe_name or view.view}.png"


def render_review_views(
    spec_path: str | Path,
    step_path: str | Path | None = None,
    views_dir: str | Path | None = None,
    renderer: Optional[Callable[..., str]] = None,
) -> Report:
    start = time.time()
    spec_file = Path(spec_path)
    spec = load_assembly_spec(spec_file)
    step = Path(step_path) if step_path is not None else _resolve_output_path(spec.outputs.step)
    if not step.is_absolute():
        step = _resolve_output_path(str(step))
    out_dir = Path(views_dir) if views_dir is not None else _resolve_output_path(spec.outputs.views_dir)
    if not out_dir.is_absolute():
        out_dir = _resolve_output_path(str(out_dir))

    findings: List[Finding] = []
    outputs: List[ReviewViewOutput] = []
    if not spec.review_views:
        findings.append(Finding(
            id="assemble.review_views_not_provided",
            category="assemble",
            severity=Severity.WARN,
            message="no review_views were declared in the assembly spec",
        ))

    if not step.exists():
        findings.append(Finding(
            id="assemble.step_missing_for_render",
            category="assemble",
            severity=Severity.FAIL,
            message=f"cannot render review views because STEP does not exist: {step}",
            evidence={"step": _display_path(step)},
        ))
    else:
        if renderer is None:
            from .render import render_step_to_png as renderer
        out_dir.mkdir(parents=True, exist_ok=True)
        for view in spec.review_views:
            output = _view_output_path(out_dir, view)
            try:
                renderer(
                    str(step),
                    str(output),
                    width=view.width,
                    height=view.height,
                    view=view.view,
                    azimuth=view.azimuth,
                    elevation=view.elevation,
                )
                rendered = output.exists()
                if not rendered:
                    findings.append(Finding(
                        id="assemble.review_view_missing_output",
                        category="assemble",
                        severity=Severity.FAIL,
                        message=f"{view.name}: renderer completed but no PNG was written",
                        evidence={"output_path": _display_path(output)},
                    ))
                outputs.append(ReviewViewOutput(
                    name=view.name,
                    view=view.view,
                    output_path=_display_path(output),
                    width=view.width,
                    height=view.height,
                    rendered=rendered,
                ))
            except Exception as exc:
                findings.append(Finding(
                    id="assemble.review_view_render_failed",
                    category="assemble",
                    severity=Severity.FAIL,
                    message=f"{view.name}: review view render failed: {exc}",
                    evidence={
                        "view": view.view,
                        "output_path": _display_path(output),
                    },
                ))
                outputs.append(ReviewViewOutput(
                    name=view.name,
                    view=view.view,
                    output_path=_display_path(output),
                    width=view.width,
                    height=view.height,
                    rendered=False,
                    message=str(exc),
                ))

    report = Report(
        findings=findings,
        confidence_budget=ConfidenceBudget(
            checked=["review view declarations", "STEP path presence"],
            not_checked=[] if step.exists() else ["rendered view alignment"],
            assumptions=list(spec.assumptions),
        ),
        duration_ms=(time.time() - start) * 1000,
        meta={
            "spec": str(spec_path),
            "step": _display_path(step),
            "views_dir": _display_path(out_dir),
            "review_views": [asdict(output) for output in outputs],
        },
    )
    report.overall = report.compute_overall()
    return report


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
    findings.extend(_protected_output_findings(spec, spec_file.resolve().parent))
    findings.extend(_generation_policy_findings(plan))
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

    blocking = [
        finding for finding in findings
        if finding.severity == Severity.FAIL
    ]
    if not dry_run and not missing and not blocking:
        _export_step(spec, spec_file, plan)

    if write_inventory and spec.outputs.design_inventory:
        write_design_inventory(plan, spec.outputs.design_inventory)

    confidence = ConfidenceBudget(
        checked=[
            "assembly spec schema",
            "instance source path resolution",
            "protected output path validation",
            "authored STEP placement policy",
            "connector metadata presence"
            if metadata_value else "connector metadata omission",
            *(
                ["explicit spacer placement declarations"]
                if _has_explicit_spacers(spec) else []
            ),
        ],
        not_checked=[
            "interference",
            "BOM-vs-CAD parity",
            "rendered view alignment",
            *(
                [] if _has_explicit_spacers(spec)
                else ["spacer requirement inference"]
            ),
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


def run_assembly_check_round(
    spec_path: str | Path,
    connector_metadata_path: str | Path | None = None,
    dry_run: bool = False,
    write_inventory: bool = True,
    render_views: bool = True,
    write_report: bool = False,
) -> Report:
    start = time.time()
    spec_file = Path(spec_path)
    spec = load_assembly_spec(spec_file)
    build_report = run_assembly_build(
        spec_file,
        connector_metadata_path=connector_metadata_path,
        dry_run=dry_run,
        write_inventory=write_inventory,
    )
    findings = list(build_report.findings)
    inventory_findings, role_inventory = _validate_expected_inventory(spec)
    findings.extend(inventory_findings)

    render_report: Optional[Report] = None
    render_skipped_reason: Optional[str] = None
    if render_views:
        if dry_run:
            render_skipped_reason = "dry_run"
            findings.append(Finding(
                id="assemble.review_render_skipped",
                category="assemble",
                severity=Severity.WARN,
                message="review views were skipped because this check round is a dry run",
            ))
        elif build_report.overall == Severity.FAIL:
            render_skipped_reason = "build_failed"
            findings.append(Finding(
                id="assemble.review_render_skipped",
                category="assemble",
                severity=Severity.WARN,
                message="review views were skipped because assembly build failed",
            ))
        else:
            render_report = render_review_views(spec_file)
            findings.extend(render_report.findings)

    confidence = ConfidenceBudget(
        checked=list(build_report.confidence_budget.checked),
        not_checked=list(build_report.confidence_budget.not_checked),
        assumptions=list(build_report.confidence_budget.assumptions),
    )
    for item in ["spec role inventory"]:
        if item not in confidence.checked:
            confidence.checked.append(item)
    if render_report:
        confidence.merge(render_report.confidence_budget)
    elif render_views:
        label = f"review view rendering ({render_skipped_reason})"
        if label not in confidence.not_checked:
            confidence.not_checked.append(label)

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
            "build": build_report.meta,
            "role_inventory": role_inventory,
            "render": render_report.meta if render_report else {
                "skipped": bool(render_views),
                "reason": render_skipped_reason,
            },
        },
    )
    report.overall = report.compute_overall()

    if write_report and spec.outputs.report:
        path = _resolve_output_path(spec.outputs.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(report.to_dict(), f, indent=2)
            f.write("\n")
    return report


__all__ = [
    "AssemblyBuildPlan",
    "AssemblySequenceStepOutput",
    "DESIGN_INVENTORY_VERSION",
    "ResolvedInstance",
    "inspect_component",
    "plan_assembly_build",
    "render_review_views",
    "run_assembly_sequence",
    "resolve_source_path",
    "run_assembly_check_round",
    "run_assembly_build",
    "write_assembly_bom_csv",
    "write_design_inventory",
]
