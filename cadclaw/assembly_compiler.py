"""CadQuery assembly compiler skeleton for CADCLAW assembly specs.

The first implementation slice focuses on deterministic source resolution and
dry-run reporting. Full geometry export is deliberately small and explicit:
place authored STEP assets with declared transforms, then write the configured
non-authoritative STEP path.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import csv
import math
import os
from pathlib import Path
import json
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

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
    transform: Dict[str, object]
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
    validation_status: str = "not_run"
    repair_suggestions: List[str] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass(frozen=True)
class PlacedInstanceShape:
    id: str
    role: str
    source_ref: str
    shape: object


@dataclass(frozen=True)
class CylindricalFeature:
    instance_id: str
    source_ref: str
    center_mm: Tuple[float, float, float]
    axis: Tuple[float, float, float]
    radius_mm: float


@dataclass(frozen=True)
class InterferenceRepair:
    target_id: str
    axis: str
    shift_mm: float
    overlap_dims: Tuple[float, float, float]
    basis: str


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


def _requested_validation_checks(spec: AssemblySpec) -> set[str]:
    raw = spec.validation.get("run_checks", [])
    if not isinstance(raw, list):
        return set()
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def _validation_section(spec: AssemblySpec, name: str) -> dict:
    raw = spec.validation.get(name, {})
    return raw if isinstance(raw, dict) else {}


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
    ox, oy, oz = transform.source_origin_mm
    result = workplane
    if ox or oy or oz:
        result = result.translate((-ox, -oy, -oz))
    if transform.scale != 1.0:
        import cadquery as cq

        result = cq.Workplane("XY").newObject([
            shape.scale(transform.scale) for shape in result.vals()
        ])
    if rx:
        result = result.rotate((0, 0, 0), (1, 0, 0), rx)
    if ry:
        result = result.rotate((0, 0, 0), (0, 1, 0), ry)
    if rz:
        result = result.rotate((0, 0, 0), (0, 0, 1), rz)
    return result.translate((tx, ty, tz))


def _rotate_point(
    point: Tuple[float, float, float],
    axis: str,
    degrees: float,
) -> Tuple[float, float, float]:
    if not degrees:
        return point
    radians = math.radians(degrees)
    c = math.cos(radians)
    s = math.sin(radians)
    x, y, z = point
    if axis == "x":
        return (x, y * c - z * s, y * s + z * c)
    if axis == "y":
        return (x * c + z * s, y, -x * s + z * c)
    return (x * c - y * s, x * s + y * c, z)


def _apply_transform_to_point(
    point: Iterable[float],
    transform: Transform,
) -> Tuple[float, float, float]:
    x, y, z = [float(value) for value in point]
    rx, ry, rz = transform.rotate_deg
    tx, ty, tz = transform.translate_mm
    ox, oy, oz = transform.source_origin_mm
    scaled = (
        (x - ox) * transform.scale,
        (y - oy) * transform.scale,
        (z - oz) * transform.scale,
    )
    rotated = _rotate_point(scaled, "x", rx)
    rotated = _rotate_point(rotated, "y", ry)
    rotated = _rotate_point(rotated, "z", rz)
    return (rotated[0] + tx, rotated[1] + ty, rotated[2] + tz)


def _connector_components_by_source(
    spec: AssemblySpec,
    spec_path: Path,
) -> Dict[str, object]:
    if not spec.connector_metadata:
        return {}
    metadata_path = _resolve_config_path(
        spec.connector_metadata, spec_path.resolve().parent
    )
    if not metadata_path.exists():
        return {}
    try:
        metadata = load_connector_metadata(metadata_path)
    except Exception:
        return {}
    by_key: Dict[str, object] = {}
    for component in metadata.components:
        by_key[component.id] = component
        if component.component_id:
            by_key[component.component_id] = component
        if component.source_path:
            by_key[Path(component.source_path).as_posix()] = component
    return by_key


def _instance_source_ref_for_matching(
    instance: Instance,
    manifest_sources: Dict[str, str],
) -> Optional[str]:
    if instance.source_path:
        return Path(instance.source_path).as_posix()
    if instance.component_id and instance.component_id in manifest_sources:
        return Path(manifest_sources[instance.component_id]).as_posix()
    return None


def _connector_frame_origin(
    spec: AssemblySpec,
    spec_path: Path,
    component_by_key: Dict[str, object],
    manifest_sources: Dict[str, str],
    instance: Instance,
    frame_id: str,
) -> Optional[Tuple[float, float, float]]:
    keys = []
    if instance.component_id:
        keys.append(instance.component_id)
    source_ref = _instance_source_ref_for_matching(instance, manifest_sources)
    if source_ref:
        keys.append(source_ref)
    component = None
    for key in keys:
        component = component_by_key.get(key)
        if component is not None:
            break
    if component is None:
        return None
    for frame in component.frames:
        if frame.id == frame_id:
            return _apply_transform_to_point(frame.origin_mm, instance.transform)
    return None


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


def _placed_instance_shapes(
    spec: AssemblySpec,
    spec_path: Path,
    plan: AssemblyBuildPlan,
    instance_ids: Iterable[str] | None = None,
) -> Tuple[List[PlacedInstanceShape], List[Finding]]:
    import cadquery as cq

    spec_dir = spec_path.resolve().parent
    manifest_sources = _load_manifest_sources(spec.manifests, spec_dir)
    by_id = {instance.id: instance for instance in spec.instances}
    wanted = set(instance_ids) if instance_ids is not None else None
    records: List[PlacedInstanceShape] = []
    findings: List[Finding] = []

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
        try:
            source = cq.importers.importStep(str(source_path))
            placed = _apply_transform(source, instance.transform)
            records.append(PlacedInstanceShape(
                id=resolved.id,
                role=resolved.role,
                source_ref=source_ref,
                shape=placed.val(),
            ))
        except Exception as exc:
            findings.append(Finding(
                id="assemble.placed_shape_load_failed",
                category="assemble",
                severity=Severity.FAIL,
                message=f"{resolved.id}: failed to load transformed STEP shape: {exc}",
                evidence={
                    "instance": resolved.id,
                    "source_ref": source_ref,
                    "resolved_path": _display_path(source_path),
                },
            ))
    return records, findings


def _bbox_tuple(shape) -> Tuple[float, float, float, float, float, float]:
    bb = shape.BoundingBox()
    return (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)


def _bbox_center_from_tuple(
    bb: Tuple[float, float, float, float, float, float],
) -> Tuple[float, float, float]:
    return ((bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0, (bb[2] + bb[5]) / 2.0)


def _bbox_overlaps(
    a: Tuple[float, float, float, float, float, float],
    b: Tuple[float, float, float, float, float, float],
    tol: float = -0.5,
) -> bool:
    return (
        a[0] < b[3] + tol and b[0] < a[3] + tol and
        a[1] < b[4] + tol and b[1] < a[4] + tol and
        a[2] < b[5] + tol and b[2] < a[5] + tol
    )


def _pair_key(a: str, b: str) -> str:
    return "||".join(sorted([a, b]))


def _role_move_rank(role: str) -> int:
    role_l = role.lower()
    if "spacer" in role_l or "shim" in role_l:
        return 10
    if "plate" in role_l or "carriage" in role_l or "mount" in role_l:
        return 20
    if "actuator" in role_l or "gantry" in role_l:
        return 40
    if "beam" in role_l or "rail" in role_l:
        return 60
    if "post" in role_l or "frame" in role_l:
        return 80
    return 50


def _repair_candidate_score(
    record: PlacedInstanceShape,
    preferred_movable_ids: set[str],
) -> Tuple[int, int, str]:
    step_rank = 0 if record.id in preferred_movable_ids else 1
    return (step_rank, _role_move_rank(record.role), record.id)


def _choose_interference_repair(
    a: PlacedInstanceShape,
    bb_a: Tuple[float, float, float, float, float, float],
    b: PlacedInstanceShape,
    bb_b: Tuple[float, float, float, float, float, float],
    clearance: float,
    preferred_movable_ids: set[str] | None = None,
) -> InterferenceRepair:
    from .interference import _suggest_clear_shift

    preferred = preferred_movable_ids or set()
    axis_a, shift_a, overlap = _suggest_clear_shift(bb_a, bb_b, clearance)
    axis_b, shift_b, _ = _suggest_clear_shift(bb_b, bb_a, clearance)
    score_a = _repair_candidate_score(a, preferred)
    score_b = _repair_candidate_score(b, preferred)

    if score_a < score_b:
        basis = "current_step" if a.id in preferred and b.id not in preferred else "role"
        return InterferenceRepair(a.id, axis_a, shift_a, overlap, basis)
    basis = "current_step" if b.id in preferred and a.id not in preferred else "role"
    return InterferenceRepair(b.id, axis_b, shift_b, overlap, basis)


def _axis_index(axis: object) -> Optional[int]:
    if not isinstance(axis, str):
        return None
    return {"x": 0, "y": 1, "z": 2}.get(axis.lower())


def _bbox_axis_min(
    bbox: Tuple[float, float, float, float, float, float],
    axis_index: int,
) -> float:
    return bbox[axis_index]


def _bbox_axis_max(
    bbox: Tuple[float, float, float, float, float, float],
    axis_index: int,
) -> float:
    return bbox[axis_index + 3]


def _bbox_axis_len(
    bbox: Tuple[float, float, float, float, float, float],
    axis_index: int,
) -> float:
    return _bbox_axis_max(bbox, axis_index) - _bbox_axis_min(bbox, axis_index)


def _bbox_axis_overlap(
    a: Tuple[float, float, float, float, float, float],
    b: Tuple[float, float, float, float, float, float],
    axis_index: int,
) -> float:
    return min(_bbox_axis_max(a, axis_index), _bbox_axis_max(b, axis_index)) - max(
        _bbox_axis_min(a, axis_index), _bbox_axis_min(b, axis_index)
    )


def _as_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _handoff_id(raw: object, index: int) -> str:
    if isinstance(raw, dict) and raw.get("id"):
        return str(raw["id"])
    return f"handoff_{index}"


def _handoff_instance(raw: dict, *names: str) -> Optional[str]:
    for name in names:
        value = raw.get(name)
        if value:
            return str(value)
    return None


def _side_value(raw: object) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    side = raw.lower()
    if side in {"negative", "neg", "-"}:
        return "negative"
    if side in {"positive", "pos", "+"}:
        return "positive"
    return None


def _side_label(side: str, axis: str) -> str:
    return f"{'-' if side == 'negative' else '+'}{axis.upper()}"


def _axis_label(axis_index: int) -> str:
    return ("x", "y", "z")[axis_index]


def _candidate_spacer_values(raw: object) -> List[float]:
    if isinstance(raw, (list, tuple)):
        return [float(value) for value in raw if isinstance(value, (int, float))]
    return []


def _axis_unit_vector(axis_index: int) -> Tuple[float, float, float]:
    if axis_index == 0:
        return (1.0, 0.0, 0.0)
    if axis_index == 1:
        return (0.0, 1.0, 0.0)
    return (0.0, 0.0, 1.0)


def _axis_parallel(
    vector: Tuple[float, float, float],
    axis_index: int,
    tolerance_deg: float,
) -> bool:
    target = _axis_unit_vector(axis_index)
    dot = abs(
        vector[0] * target[0] + vector[1] * target[1] + vector[2] * target[2]
    )
    return dot >= math.cos(math.radians(tolerance_deg))


def _planar_point(
    point: Tuple[float, float, float],
    axis_index: int,
) -> Tuple[float, float]:
    if axis_index == 0:
        return (point[1], point[2])
    if axis_index == 1:
        return (point[0], point[2])
    return (point[0], point[1])


def _planar_distance(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
    axis_index: int,
) -> float:
    a2 = _planar_point(a, axis_index)
    b2 = _planar_point(b, axis_index)
    return math.hypot(a2[0] - b2[0], a2[1] - b2[1])


def _cylindrical_features(
    record: PlacedInstanceShape,
    axis_index: int,
    axis_tolerance_deg: float,
    radius_min: float,
    radius_max: float,
) -> List[CylindricalFeature]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    features: List[CylindricalFeature] = []
    for face in record.shape.Faces():
        try:
            surface = BRepAdaptor_Surface(face.wrapped, True)
            if surface.GetType() != GeomAbs_Cylinder:
                continue
            cylinder = surface.Cylinder()
            radius = float(cylinder.Radius())
            if radius < radius_min or radius > radius_max:
                continue
            axis = cylinder.Axis()
            direction = axis.Direction()
            vector = (
                float(direction.X()),
                float(direction.Y()),
                float(direction.Z()),
            )
            if not _axis_parallel(vector, axis_index, axis_tolerance_deg):
                continue
            location = axis.Location()
            features.append(CylindricalFeature(
                instance_id=record.id,
                source_ref=record.source_ref,
                center_mm=(
                    float(location.X()),
                    float(location.Y()),
                    float(location.Z()),
                ),
                axis=vector,
                radius_mm=radius,
            ))
        except Exception:
            continue
    return features


def _match_cylindrical_features(
    from_features: List[CylindricalFeature],
    to_features: List[CylindricalFeature],
    axis_index: int,
    max_error_mm: float,
    radius_tolerance_mm: float,
) -> Tuple[List[dict], Optional[dict]]:
    candidates: List[tuple[float, int, int]] = []
    for from_index, from_feature in enumerate(from_features):
        for to_index, to_feature in enumerate(to_features):
            if abs(from_feature.radius_mm - to_feature.radius_mm) > radius_tolerance_mm:
                continue
            error = _planar_distance(
                from_feature.center_mm,
                to_feature.center_mm,
                axis_index,
            )
            candidates.append((error, from_index, to_index))

    matches: List[dict] = []
    used_from: set[int] = set()
    used_to: set[int] = set()
    closest: Optional[dict] = None
    for error, from_index, to_index in sorted(candidates, key=lambda item: item[0]):
        if closest is None:
            closest = {
                "from_center_mm": [
                    round(value, 3) for value in from_features[from_index].center_mm
                ],
                "to_center_mm": [
                    round(value, 3) for value in to_features[to_index].center_mm
                ],
                "error_mm": round(error, 3),
            }
        if error > max_error_mm:
            continue
        if from_index in used_from or to_index in used_to:
            continue
        used_from.add(from_index)
        used_to.add(to_index)
        matches.append({
            "from_center_mm": [
                round(value, 3) for value in from_features[from_index].center_mm
            ],
            "to_center_mm": [
                round(value, 3) for value in to_features[to_index].center_mm
            ],
            "error_mm": round(error, 3),
            "radius_mm": round(from_features[from_index].radius_mm, 3),
        })
    return matches, closest


def _run_hole_alignment(
    spec: AssemblySpec,
    spec_path: Path,
    plan: AssemblyBuildPlan,
    instance_ids: Iterable[str] | None = None,
) -> tuple[List[Finding], dict]:
    config = _validation_section(spec, "hole_alignment")
    groups_raw = config.get("groups", config.get("pairs", []))
    findings: List[Finding] = []
    if not isinstance(groups_raw, list):
        findings.append(Finding(
            id="hole_alignment.config_invalid",
            category="assemble",
            severity=Severity.FAIL,
            message="validation.hole_alignment.groups must be a list",
        ))
        return findings, {"checked": False, "reason": "config_invalid"}

    records, shape_findings = _placed_instance_shapes(
        spec, spec_path, plan, instance_ids=instance_ids
    )
    findings.extend(shape_findings)
    by_id = {record.id: record for record in records}

    default_max_error = _as_float(config.get("max_error_mm"), 0.75)
    default_min_matches = int(config.get("min_matches", 1))
    default_radius_min = _as_float(config.get("radius_min_mm"), 1.0)
    default_radius_max = _as_float(config.get("radius_max_mm"), 10.0)
    default_radius_tol = _as_float(config.get("radius_tolerance_mm"), 0.35)
    default_axis_tol = _as_float(config.get("axis_tolerance_deg"), 5.0)

    checked_groups: List[str] = []
    partial_groups: List[str] = []
    skipped_groups: List[str] = []
    feature_counts: Dict[str, int] = {}

    for index, raw in enumerate(groups_raw, start=1):
        group_id = _handoff_id(raw, index)
        if not isinstance(raw, dict):
            findings.append(Finding(
                id="hole_alignment.group_invalid",
                category="assemble",
                severity=Severity.FAIL,
                message=f"{group_id}: group entry must be a mapping",
            ))
            continue

        from_id = _handoff_instance(raw, "from_instance", "current_instance")
        to_id = _handoff_instance(raw, "to_instance", "plate_instance", "next_instance")
        axis = str(raw.get("axis", raw.get("handoff_axis", ""))).lower()
        axis_idx = _axis_index(axis)
        if not from_id or not to_id or axis_idx is None:
            findings.append(Finding(
                id="hole_alignment.group_invalid",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"{group_id}: requires from_instance, to_instance, and axis"
                ),
                evidence={"group": group_id},
            ))
            continue

        if from_id not in by_id or to_id not in by_id:
            if instance_ids is not None:
                partial_groups.append(group_id)
            else:
                skipped_groups.append(group_id)
            continue

        checked_groups.append(group_id)
        max_error = _as_float(raw.get("max_error_mm"), default_max_error)
        min_matches = int(raw.get("min_matches", default_min_matches))
        radius_min = _as_float(raw.get("radius_min_mm"), default_radius_min)
        radius_max = _as_float(raw.get("radius_max_mm"), default_radius_max)
        radius_tol = _as_float(raw.get("radius_tolerance_mm"), default_radius_tol)
        axis_tol = _as_float(raw.get("axis_tolerance_deg"), default_axis_tol)

        from_features = _cylindrical_features(
            by_id[from_id], axis_idx, axis_tol, radius_min, radius_max
        )
        to_features = _cylindrical_features(
            by_id[to_id], axis_idx, axis_tol, radius_min, radius_max
        )
        feature_counts[from_id] = len(from_features)
        feature_counts[to_id] = len(to_features)
        matches, closest = _match_cylindrical_features(
            from_features,
            to_features,
            axis_idx,
            max_error,
            radius_tol,
        )
        if len(matches) < min_matches:
            findings.append(Finding(
                id="hole_alignment.insufficient_matches",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"{group_id}: only {len(matches)} authored cylindrical "
                    f"feature matches found between {from_id} and {to_id}; "
                    f"expected at least {min_matches}"
                ),
                suggested_fix=(
                    f"Move or rotate {to_id} until its authored holes align "
                    f"with {from_id} in the plane perpendicular to "
                    f"{axis.upper()}."
                ),
                evidence={
                    "group": group_id,
                    "from_instance": from_id,
                    "to_instance": to_id,
                    "axis": axis,
                    "max_error_mm": max_error,
                    "min_matches": min_matches,
                    "from_feature_count": len(from_features),
                    "to_feature_count": len(to_features),
                    "closest_pair": closest,
                    "matches": matches[:10],
                },
            ))

    return findings, {
        "checked": True,
        "checked_groups": checked_groups,
        "partial_groups": sorted(set(partial_groups)),
        "skipped_groups": skipped_groups,
        "feature_counts": feature_counts,
        "max_error_mm": default_max_error,
        "min_matches": default_min_matches,
        "radius_min_mm": default_radius_min,
        "radius_max_mm": default_radius_max,
    }


def _run_vslot_stackup(
    spec: AssemblySpec,
    spec_path: Path,
    plan: AssemblyBuildPlan,
    instance_ids: Iterable[str] | None = None,
) -> tuple[List[Finding], dict]:
    config = _validation_section(spec, "vslot_stackup")
    handoffs_raw = config.get("handoffs", [])
    findings: List[Finding] = []
    if not isinstance(handoffs_raw, list):
        findings.append(Finding(
            id="vslot_stackup.config_invalid",
            category="assemble",
            severity=Severity.FAIL,
            message="validation.vslot_stackup.handoffs must be a list",
        ))
        return findings, {"checked": False, "reason": "config_invalid"}

    records, shape_findings = _placed_instance_shapes(
        spec, spec_path, plan, instance_ids=instance_ids
    )
    findings.extend(shape_findings)
    by_id = {record.id: record for record in records}
    bboxes = {record.id: _bbox_tuple(record.shape) for record in records}
    by_instance = {instance.id: instance for instance in spec.instances}
    manifest_sources = _load_manifest_sources(
        spec.manifests, spec_path.resolve().parent
    )
    connector_by_key = _connector_components_by_source(spec, spec_path)

    default_plate_thickness = _as_float(config.get("plate_thickness_mm"), 3.0)
    default_running_gap = _as_float(config.get("running_gap_mm"), 1.0)
    thickness_tol = _as_float(config.get("thickness_tolerance_mm"), 0.5)
    position_tol = _as_float(config.get("position_tolerance_mm"), 1.0)
    spacer_min = _as_float(config.get("min_spacer_mm"), 0.0)
    spacer_target = _as_float(config.get("target_spacer_mm"), 0.0)
    spacer_candidates = _candidate_spacer_values(config.get("candidate_spacer_mm"))
    known_too_small = _candidate_spacer_values(config.get("known_too_small_mm"))

    checked_handoffs: List[str] = []
    partial_handoffs: List[str] = []
    skipped_handoffs: List[str] = []

    for index, raw in enumerate(handoffs_raw, start=1):
        handoff_id = _handoff_id(raw, index)
        if not isinstance(raw, dict):
            findings.append(Finding(
                id="vslot_stackup.handoff_invalid",
                category="assemble",
                severity=Severity.FAIL,
                message=f"{handoff_id}: handoff entry must be a mapping",
            ))
            continue

        current_id = _handoff_instance(raw, "current_instance", "rail_instance")
        plate_id = _handoff_instance(raw, "plate_instance")
        axis = str(raw.get("axis", raw.get("handoff_axis", ""))).lower()
        axis_idx = _axis_index(axis)
        side = _side_value(raw.get("side"))
        if not current_id or not plate_id or axis_idx is None or not side:
            findings.append(Finding(
                id="vslot_stackup.handoff_invalid",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"{handoff_id}: requires current_instance, "
                    "plate_instance, axis, and side"
                ),
                evidence={"handoff": handoff_id},
            ))
            continue

        if current_id not in by_id or plate_id not in by_id:
            skipped_handoffs.append(handoff_id)
            continue

        checked_handoffs.append(handoff_id)
        current = by_id[current_id]
        plate = by_id[plate_id]
        bb_current = bboxes[current_id]
        bb_plate = bboxes[plate_id]
        plate_thickness = _as_float(
            raw.get("plate_thickness_mm"), default_plate_thickness
        )
        running_gap = _as_float(raw.get("running_gap_mm"), default_running_gap)
        plate_gap = _as_float(raw.get("plate_gap_mm"), 0.0)

        actual_plate_thickness = _bbox_axis_len(bb_plate, axis_idx)
        if abs(actual_plate_thickness - plate_thickness) > thickness_tol:
            findings.append(Finding(
                id="vslot_stackup.plate_axis_misaligned",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"{handoff_id}: {plate_id} is {actual_plate_thickness:.2f}mm "
                    f"thick along {axis.upper()}, expected {plate_thickness:g}mm"
                ),
                suggested_fix=(
                    f"Rotate {plate_id} so the gantry plate's thin axis is "
                    f"aligned to {_side_label(side, axis)} before placing the "
                    "next V-slot axis."
                ),
                evidence={
                    "handoff": handoff_id,
                    "current_instance": current.id,
                    "plate_instance": plate.id,
                    "axis": axis,
                    "side": side,
                    "actual_plate_thickness_mm": round(actual_plate_thickness, 3),
                    "expected_plate_thickness_mm": plate_thickness,
                    "bbox_plate": [round(value, 3) for value in bb_plate],
                },
            ))

        current_frame = raw.get("current_frame")
        current_end_from = "bbox"
        if current_frame:
            origin = _connector_frame_origin(
                spec,
                spec_path,
                connector_by_key,
                manifest_sources,
                by_instance[current_id],
                str(current_frame),
            )
            if origin is None:
                findings.append(Finding(
                    id="vslot_stackup.connector_frame_missing",
                    category="assemble",
                    severity=Severity.FAIL,
                    message=(
                        f"{handoff_id}: connector frame {current_frame!r} "
                        f"was not found for {current_id}"
                    ),
                    suggested_fix=(
                        "Add/verify connector metadata for the authored STEP "
                        "or remove current_frame so the check falls back to "
                        "the full placed bbox."
                    ),
                    evidence={
                        "handoff": handoff_id,
                        "current_instance": current_id,
                        "current_frame": str(current_frame),
                    },
                ))
                continue
            current_end = origin[axis_idx]
            current_end_from = f"connector_frame:{current_frame}"
        elif side == "negative":
            current_end = _bbox_axis_min(bb_current, axis_idx)
        else:
            current_end = _bbox_axis_max(bb_current, axis_idx)

        if side == "negative":
            plate_inner = _bbox_axis_max(bb_plate, axis_idx)
            actual_plate_gap = current_end - plate_inner
        else:
            plate_inner = _bbox_axis_min(bb_plate, axis_idx)
            actual_plate_gap = plate_inner - current_end
        if abs(actual_plate_gap - plate_gap) > position_tol:
            findings.append(Finding(
                id="vslot_stackup.plate_not_on_end_face",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"{handoff_id}: {plate_id} is "
                    f"{actual_plate_gap:.2f}mm from the "
                    f"{_side_label(side, axis)} end face of {current_id}, "
                    f"expected {plate_gap:g}mm"
                ),
                suggested_fix=(
                    f"Move {plate_id} along {axis.upper()} until its inner "
                    f"face has the declared {plate_gap:g}mm V-slot handoff "
                    f"gap from {current_id}."
                ),
                evidence={
                    "handoff": handoff_id,
                    "current_instance": current.id,
                    "plate_instance": plate.id,
                    "axis": axis,
                    "side": side,
                    "current_end_from": current_end_from,
                    "actual_plate_gap_mm": round(actual_plate_gap, 3),
                    "expected_plate_gap_mm": plate_gap,
                    "position_tolerance_mm": position_tol,
                },
            ))

        spacer_id = _handoff_instance(raw, "spacer_instance")
        if spacer_id:
            if spacer_id not in by_id:
                partial_handoffs.append(handoff_id)
            else:
                spacer = by_id[spacer_id]
                bb_spacer = bboxes[spacer_id]
                actual_spacer = _bbox_axis_len(bb_spacer, axis_idx)
                target = _as_float(raw.get("spacer_mm"), spacer_target)
                minimum = _as_float(raw.get("min_spacer_mm"), spacer_min)
                candidates = _candidate_spacer_values(
                    raw.get("candidate_spacer_mm")
                ) or spacer_candidates
                too_small = _candidate_spacer_values(
                    raw.get("known_too_small_mm")
                ) or known_too_small
                if minimum and actual_spacer + thickness_tol < minimum:
                    findings.append(Finding(
                        id="vslot_stackup.spacer_too_small",
                        category="assemble",
                        severity=Severity.FAIL,
                        message=(
                            f"{handoff_id}: {spacer_id} is "
                            f"{actual_spacer:.2f}mm along {axis.upper()}, "
                            f"below the {minimum:g}mm minimum"
                        ),
                        suggested_fix=(
                            f"Use a V-slot handoff spacer in the tested "
                            f"{candidates or [target]}mm range; avoid "
                            f"{too_small or [4.0]}mm where movement tolerance "
                            "is insufficient."
                        ),
                        evidence={
                            "handoff": handoff_id,
                            "spacer_instance": spacer.id,
                            "axis": axis,
                            "actual_spacer_mm": round(actual_spacer, 3),
                            "min_spacer_mm": minimum,
                            "known_too_small_mm": too_small,
                        },
                    ))
                elif target and not any(
                    abs(actual_spacer - candidate) <= thickness_tol
                    for candidate in (candidates or [target])
                ):
                    findings.append(Finding(
                        id="vslot_stackup.spacer_not_candidate",
                        category="assemble",
                        severity=Severity.WARN,
                        message=(
                            f"{handoff_id}: {spacer_id} is "
                            f"{actual_spacer:.2f}mm, outside candidate "
                            f"spacer values {candidates or [target]}"
                        ),
                        evidence={
                            "handoff": handoff_id,
                            "spacer_instance": spacer.id,
                            "axis": axis,
                            "actual_spacer_mm": round(actual_spacer, 3),
                            "candidate_spacer_mm": candidates or [target],
                        },
                    ))

                if side == "negative":
                    plate_outer = _bbox_axis_min(bb_plate, axis_idx)
                    spacer_inner = _bbox_axis_max(bb_spacer, axis_idx)
                    spacer_flush = spacer_inner - plate_outer
                else:
                    plate_outer = _bbox_axis_max(bb_plate, axis_idx)
                    spacer_inner = _bbox_axis_min(bb_spacer, axis_idx)
                    spacer_flush = plate_outer - spacer_inner
                if abs(spacer_flush) > position_tol:
                    findings.append(Finding(
                        id="vslot_stackup.spacer_not_on_plate_face",
                        category="assemble",
                        severity=Severity.FAIL,
                        message=(
                            f"{handoff_id}: {spacer_id} is not stacked "
                            f"against the outer face of {plate_id}"
                        ),
                        suggested_fix=(
                            f"Move {spacer_id} along {axis.upper()} so the "
                            f"{target or actual_spacer:g}mm spacer sits "
                            "directly outside the gantry plate."
                        ),
                        evidence={
                            "handoff": handoff_id,
                            "plate_instance": plate.id,
                            "spacer_instance": spacer.id,
                            "axis": axis,
                            "side": side,
                            "flush_delta_mm": round(spacer_flush, 3),
                        },
                    ))

        next_id = _handoff_instance(raw, "next_instance", "to_instance")
        if next_id:
            if next_id not in by_id:
                partial_handoffs.append(handoff_id)
            else:
                next_record = by_id[next_id]
                bb_next = bboxes[next_id]
                reference_id = plate.id
                bb_reference = bb_plate
                expected_gap = _as_float(raw.get("next_gap_mm"), running_gap)
                if spacer_id and spacer_id in by_id:
                    reference_id = spacer_id
                    bb_reference = bboxes[spacer_id]
                    expected_gap = _as_float(raw.get("next_gap_mm"), 0.0)
                if side == "negative":
                    reference_outer = _bbox_axis_min(bb_reference, axis_idx)
                    next_near = _bbox_axis_max(bb_next, axis_idx)
                    actual_gap = reference_outer - next_near
                else:
                    reference_outer = _bbox_axis_max(bb_reference, axis_idx)
                    next_near = _bbox_axis_min(bb_next, axis_idx)
                    actual_gap = next_near - reference_outer
                if abs(actual_gap - expected_gap) > position_tol:
                    findings.append(Finding(
                        id="vslot_stackup.running_gap_out_of_range",
                        category="assemble",
                        severity=Severity.FAIL,
                        message=(
                            f"{handoff_id}: gap from {reference_id} to "
                            f"{next_id} is {actual_gap:.2f}mm, expected "
                            f"{expected_gap:g}mm"
                        ),
                        suggested_fix=(
                            f"Move {next_id} along {axis.upper()} so it sits "
                            f"outside {reference_id} with the "
                            f"{expected_gap:g}mm V-slot stack gap."
                        ),
                        evidence={
                            "handoff": handoff_id,
                            "reference_instance": reference_id,
                            "plate_instance": plate.id,
                            "next_instance": next_record.id,
                            "axis": axis,
                            "side": side,
                            "actual_gap_mm": round(actual_gap, 3),
                            "expected_gap_mm": expected_gap,
                            "position_tolerance_mm": position_tol,
                        },
                    ))

    return findings, {
        "checked": True,
        "checked_handoffs": checked_handoffs,
        "partial_handoffs": sorted(set(partial_handoffs)),
        "skipped_handoffs": skipped_handoffs,
        "instance_ids": list(instance_ids) if instance_ids is not None else None,
        "plate_thickness_mm": default_plate_thickness,
        "running_gap_mm": default_running_gap,
        "min_spacer_mm": spacer_min or None,
        "target_spacer_mm": spacer_target or None,
        "known_too_small_mm": known_too_small,
    }


def _run_frame_adjacency(
    spec: AssemblySpec,
    spec_path: Path,
    plan: AssemblyBuildPlan,
    instance_ids: Iterable[str] | None = None,
) -> tuple[List[Finding], dict]:
    config = _validation_section(spec, "frame_adjacency")
    joints_raw = config.get("joints", [])
    findings: List[Finding] = []
    if not isinstance(joints_raw, list):
        findings.append(Finding(
            id="frame_adjacency.config_invalid",
            category="assemble",
            severity=Severity.FAIL,
            message="validation.frame_adjacency.joints must be a list",
        ))
        return findings, {"checked": False, "reason": "config_invalid"}

    records, shape_findings = _placed_instance_shapes(
        spec, spec_path, plan, instance_ids=instance_ids
    )
    findings.extend(shape_findings)
    by_id = {record.id: record for record in records}
    bboxes = {record.id: _bbox_tuple(record.shape) for record in records}

    default_gap = _as_float(config.get("gap_mm"), 0.0)
    position_tol = _as_float(config.get("position_tolerance_mm"), 0.5)
    default_min_overlap = _as_float(config.get("min_overlap_mm"), 1.0)

    checked_joints: List[str] = []
    partial_joints: List[str] = []
    skipped_joints: List[str] = []
    gap_failures_by_member: Dict[tuple[str, int], List[dict]] = {}

    for index, raw in enumerate(joints_raw, start=1):
        joint_id = _handoff_id(raw, index)
        if not isinstance(raw, dict):
            findings.append(Finding(
                id="frame_adjacency.joint_invalid",
                category="assemble",
                severity=Severity.FAIL,
                message=f"{joint_id}: joint entry must be a mapping",
            ))
            continue

        from_id = _handoff_instance(raw, "from_instance", "a_instance")
        to_id = _handoff_instance(raw, "to_instance", "b_instance")
        axis = str(raw.get("axis", "")).lower()
        axis_idx = _axis_index(axis)
        side = _side_value(raw.get("side"))
        if not from_id or not to_id or axis_idx is None or not side:
            findings.append(Finding(
                id="frame_adjacency.joint_invalid",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"{joint_id}: requires from_instance, to_instance, "
                    "axis, and side"
                ),
                evidence={"joint": joint_id},
            ))
            continue

        if from_id not in by_id or to_id not in by_id:
            if instance_ids is not None:
                partial_joints.append(joint_id)
            else:
                skipped_joints.append(joint_id)
            continue

        checked_joints.append(joint_id)
        from_record = by_id[from_id]
        to_record = by_id[to_id]
        bb_from = bboxes[from_id]
        bb_to = bboxes[to_id]
        expected_gap = _as_float(raw.get("gap_mm"), default_gap)
        min_overlap = _as_float(raw.get("min_overlap_mm"), default_min_overlap)

        if side == "positive":
            from_face = _bbox_axis_max(bb_from, axis_idx)
            to_near = _bbox_axis_min(bb_to, axis_idx)
            actual_gap = to_near - from_face
            move_delta = expected_gap - actual_gap
        else:
            from_face = _bbox_axis_min(bb_from, axis_idx)
            to_near = _bbox_axis_max(bb_to, axis_idx)
            actual_gap = from_face - to_near
            move_delta = actual_gap - expected_gap

        if abs(actual_gap - expected_gap) > position_tol:
            sign = "+" if move_delta >= 0 else "-"
            gap_record = {
                "joint": joint_id,
                "from_instance": from_record.id,
                "to_instance": to_record.id,
                "axis": axis,
                "side": side,
                "actual_gap_mm": round(actual_gap, 3),
                "expected_gap_mm": expected_gap,
                "move_delta_mm": round(move_delta, 3),
            }
            gap_failures_by_member.setdefault((to_record.id, axis_idx), []).append(
                gap_record
            )
            findings.append(Finding(
                id="frame_adjacency.gap_out_of_range",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"{joint_id}: static frame joint gap between {from_id} "
                    f"and {to_id} is {actual_gap:.2f}mm along "
                    f"{axis.upper()}, expected {expected_gap:g}mm"
                ),
                suggested_fix=(
                    f"Move {to_id} {sign}{axis.upper()} by "
                    f"{abs(move_delta):.2f}mm or add an authored connector/"
                    "spacer STEP declared in the assembly spec."
                ),
                evidence={
                    "joint": joint_id,
                    "from_instance": from_record.id,
                    "to_instance": to_record.id,
                    "axis": axis,
                    "side": side,
                    "actual_gap_mm": round(actual_gap, 3),
                    "expected_gap_mm": expected_gap,
                    "position_tolerance_mm": position_tol,
                    "bbox_from": [round(value, 3) for value in bb_from],
                    "bbox_to": [round(value, 3) for value in bb_to],
                },
            ))

        overlap_failures = []
        for other_idx in range(3):
            if other_idx == axis_idx:
                continue
            overlap = _bbox_axis_overlap(bb_from, bb_to, other_idx)
            if overlap + position_tol < min_overlap:
                overlap_failures.append({
                    "axis": _axis_label(other_idx),
                    "overlap_mm": round(overlap, 3),
                })
        if overlap_failures:
            findings.append(Finding(
                id="frame_adjacency.insufficient_bearing",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"{joint_id}: {from_id} and {to_id} do not have enough "
                    "overlap on the structural bearing axes"
                ),
                suggested_fix=(
                    f"Align {to_id} so the mated C-Beam/post faces overlap "
                    f"by at least {min_overlap:g}mm on the axes perpendicular "
                    f"to {axis.upper()}."
                ),
                evidence={
                    "joint": joint_id,
                    "from_instance": from_record.id,
                    "to_instance": to_record.id,
                    "axis": axis,
                    "side": side,
                    "min_overlap_mm": min_overlap,
                    "overlap_failures": overlap_failures,
                },
            ))

    for (member_id, axis_idx), gaps in sorted(gap_failures_by_member.items()):
        sides = {str(gap["side"]) for gap in gaps}
        if not {"positive", "negative"}.issubset(sides):
            continue
        excess_gap = sum(
            max(0.0, float(gap["actual_gap_mm"]) - float(gap["expected_gap_mm"]))
            for gap in gaps
        )
        if excess_gap <= position_tol:
            continue
        axis = _axis_label(axis_idx)
        findings.append(Finding(
            id="frame_adjacency.member_too_short_for_span",
            category="assemble",
            severity=Severity.FAIL,
            message=(
                f"{member_id}: static frame member cannot close its declared "
                f"{axis.upper()} joints by translation; paired gaps total "
                f"{excess_gap:.2f}mm"
            ),
            suggested_fix=(
                f"Resolve {member_id} with an authored connector/spacer STEP, "
                "a declared splice/second rail, or a corrected frame datum; "
                "do not hide this by adding clearance to a static frame joint."
            ),
            evidence={
                "member_instance": member_id,
                "axis": axis,
                "paired_gap_total_mm": round(excess_gap, 3),
                "gap_findings": gaps,
            },
        ))

    return findings, {
        "checked": True,
        "checked_joints": checked_joints,
        "partial_joints": sorted(set(partial_joints)),
        "skipped_joints": skipped_joints,
        "instance_ids": list(instance_ids) if instance_ids is not None else None,
        "gap_mm": default_gap,
        "position_tolerance_mm": position_tol,
        "min_overlap_mm": default_min_overlap,
    }


def _run_spec_interference(
    spec: AssemblySpec,
    spec_path: Path,
    plan: AssemblyBuildPlan,
    instance_ids: Iterable[str] | None = None,
    preferred_movable_ids: Iterable[str] | None = None,
) -> tuple[List[Finding], dict]:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    config = _validation_section(spec, "interference")
    min_volume = float(config.get("min_volume_mm3", config.get("min_volume", 1.0)))
    clearance = float(config.get("min_clearance_mm", 1.0))
    max_findings = int(config.get("max_findings", 50))
    skip_roles = {str(value) for value in config.get("skip_roles", [])}
    skip_instances = {str(value) for value in config.get("skip_instances", [])}
    skip_pairs = {
        _pair_key(str(pair[0]), str(pair[1]))
        for pair in config.get("skip_pairs", [])
        if isinstance(pair, list) and len(pair) == 2
    }

    records, findings = _placed_instance_shapes(
        spec, spec_path, plan, instance_ids=instance_ids
    )
    bboxes = {record.id: _bbox_tuple(record.shape) for record in records}
    preferred = {str(value) for value in preferred_movable_ids or []}
    checked_pairs = 0

    for index, a in enumerate(records):
        if a.id in skip_instances or a.role in skip_roles:
            continue
        bb_a = bboxes[a.id]
        for b in records[index + 1:]:
            if b.id in skip_instances or b.role in skip_roles:
                continue
            if _pair_key(a.id, b.id) in skip_pairs:
                continue
            bb_b = bboxes[b.id]
            if not _bbox_overlaps(bb_a, bb_b):
                continue
            checked_pairs += 1
            try:
                common = BRepAlgoAPI_Common(a.shape.wrapped, b.shape.wrapped)
                common.Build()
                if not common.IsDone():
                    continue
                props = GProp_GProps()
                BRepGProp.VolumeProperties_s(common.Shape(), props)
                volume = props.Mass()
            except Exception:
                continue
            if volume <= min_volume:
                continue
            repair = _choose_interference_repair(
                a,
                bb_a,
                b,
                bb_b,
                clearance,
                preferred_movable_ids=preferred,
            )
            sign = "+" if repair.shift_mm >= 0 else "-"
            suggestion = (
                f"shift {repair.target_id} {sign}{repair.axis.upper()} "
                f"by {abs(repair.shift_mm):.2f}mm to clear the paired part "
                f"with {clearance:g}mm clearance"
            )
            findings.append(Finding(
                id="interference.clip",
                category="interference",
                severity=Severity.FAIL,
                message=(
                    f"{a.id} ({a.role}) clips {b.id} ({b.role}) "
                    f"by {volume:.0f} mm3"
                ),
                suggested_fix=suggestion,
                evidence={
                    "instance_a": a.id,
                    "role_a": a.role,
                    "source_ref_a": a.source_ref,
                    "instance_b": b.id,
                    "role_b": b.role,
                    "source_ref_b": b.source_ref,
                    "volume_mm3": round(volume, 1),
                    "center_a": [round(value, 3) for value in _bbox_center_from_tuple(bb_a)],
                    "center_b": [round(value, 3) for value in _bbox_center_from_tuple(bb_b)],
                    "bbox_a": [round(value, 3) for value in bb_a],
                    "bbox_b": [round(value, 3) for value in bb_b],
                    "overlap_dims_mm": [round(value, 3) for value in repair.overlap_dims],
                    "suggest_shift": {
                        "target_instance": repair.target_id,
                        "axis": repair.axis,
                        "mm": round(repair.shift_mm, 3),
                        "clearance_mm": clearance,
                        "basis": repair.basis,
                    },
                },
            ))
            if len([f for f in findings if f.id == "interference.clip"]) >= max_findings:
                return findings, {
                    "checked": True,
                    "checked_pairs": checked_pairs,
                    "placed_instances": len(records),
                    "max_findings_reached": True,
                    "instance_ids": list(instance_ids) if instance_ids is not None else None,
                    "preferred_movable_ids": sorted(preferred) or None,
                }

    return findings, {
        "checked": True,
        "checked_pairs": checked_pairs,
        "placed_instances": len(records),
        "max_findings_reached": False,
        "instance_ids": list(instance_ids) if instance_ids is not None else None,
        "preferred_movable_ids": sorted(preferred) or None,
    }


def _with_sequence_step(finding: Finding, step_id: str) -> Finding:
    return Finding(
        id=finding.id,
        category=finding.category,
        severity=finding.severity,
        message=f"{step_id}: {finding.message}",
        suggested_fix=finding.suggested_fix,
        evidence={**finding.evidence, "sequence_step": step_id},
    )


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
    stop_on_validation_fail: bool = True,
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
    requested_checks = _requested_validation_checks(spec)
    validate_interference = "interference" in requested_checks
    validate_vslot_stackup = "vslot_stackup" in requested_checks
    validate_frame_adjacency = "frame_adjacency" in requested_checks
    validate_hole_alignment = "hole_alignment" in requested_checks

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
    sequence_interference_checked = (
        validate_interference and not dry_run and not blocking
    )
    sequence_vslot_stackup_checked = (
        validate_vslot_stackup and not dry_run and not blocking
    )
    sequence_frame_adjacency_checked = (
        validate_frame_adjacency and not dry_run and not blocking
    )
    sequence_hole_alignment_checked = (
        validate_hole_alignment and not dry_run and not blocking
    )
    sequence_blocked_at: Optional[str] = None
    if renderer is None and render_views:
        from .render import render_step_to_png as renderer

    for index, step in enumerate(spec.assembly_sequence, start=1):
        if sequence_blocked_at:
            break
        cumulative = _ordered_unique([*cumulative, *step.instance_ids])
        safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in step.id)
        step_prefix = f"{index:02d}_{safe_id}"
        step_path = steps_dir / f"{step_prefix}.step"
        rendered: List[ReviewViewOutput] = []
        validation_status = "not_run"
        repair_suggestions: List[str] = []

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

        step_failed = False
        validation_ran = False
        if sequence_interference_checked:
            validation_ran = True
            step_findings, _step_meta = _run_spec_interference(
                spec,
                spec_file,
                plan,
                instance_ids=cumulative,
                preferred_movable_ids=step.instance_ids,
            )
            tagged_findings = [
                _with_sequence_step(finding, step.id)
                for finding in step_findings
            ]
            findings.extend(tagged_findings)
            step_failed = any(
                finding.severity == Severity.FAIL
                for finding in tagged_findings
            )
            validation_status = "fail" if step_failed else "pass"
            repair_suggestions = [
                finding.suggested_fix
                for finding in tagged_findings
                if finding.severity == Severity.FAIL and finding.suggested_fix
            ]
        if sequence_vslot_stackup_checked:
            validation_ran = True
            step_findings, _step_meta = _run_vslot_stackup(
                spec,
                spec_file,
                plan,
                instance_ids=cumulative,
            )
            tagged_findings = [
                _with_sequence_step(finding, step.id)
                for finding in step_findings
            ]
            findings.extend(tagged_findings)
            step_failed = step_failed or any(
                finding.severity == Severity.FAIL
                for finding in tagged_findings
            )
            repair_suggestions.extend(
                finding.suggested_fix
                for finding in tagged_findings
                if finding.severity == Severity.FAIL and finding.suggested_fix
            )
            validation_status = "fail" if step_failed else "pass"
        if sequence_frame_adjacency_checked:
            validation_ran = True
            step_findings, _step_meta = _run_frame_adjacency(
                spec,
                spec_file,
                plan,
                instance_ids=cumulative,
            )
            tagged_findings = [
                _with_sequence_step(finding, step.id)
                for finding in step_findings
            ]
            findings.extend(tagged_findings)
            step_failed = step_failed or any(
                finding.severity == Severity.FAIL
                for finding in tagged_findings
            )
            repair_suggestions.extend(
                finding.suggested_fix
                for finding in tagged_findings
                if finding.severity == Severity.FAIL and finding.suggested_fix
            )
            validation_status = "fail" if step_failed else "pass"
        if sequence_hole_alignment_checked:
            validation_ran = True
            step_findings, _step_meta = _run_hole_alignment(
                spec,
                spec_file,
                plan,
                instance_ids=cumulative,
            )
            tagged_findings = [
                _with_sequence_step(finding, step.id)
                for finding in step_findings
            ]
            findings.extend(tagged_findings)
            step_failed = step_failed or any(
                finding.severity == Severity.FAIL
                for finding in tagged_findings
            )
            repair_suggestions.extend(
                finding.suggested_fix
                for finding in tagged_findings
                if finding.severity == Severity.FAIL and finding.suggested_fix
            )
            validation_status = "fail" if step_failed else "pass"
        elif validation_ran:
            validation_status = "fail" if step_failed else "pass"

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
            validation_status=validation_status,
            repair_suggestions=repair_suggestions,
            notes=step.notes,
        ))

        if step_failed and stop_on_validation_fail:
            sequence_blocked_at = step.id
            findings.append(Finding(
                id="assemble.sequence_blocked",
                category="assemble",
                severity=Severity.FAIL,
                message=(
                    f"assembly sequence stopped at {step.id} because declared "
                    "validation failed"
                ),
                suggested_fix=(
                    "Review the step's validation findings, edit the assembly "
                    "spec transforms or connector metadata, rerun this step, "
                    "then continue only after the gate passes."
                ),
                evidence={
                    "step": step.id,
                    "stop_on_validation_fail": stop_on_validation_fail,
                    "remaining_steps": [
                        remaining.id
                        for remaining in spec.assembly_sequence[index:]
                    ],
                },
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
        if dry_run or blocking or sequence_blocked_at or not cumulative:
            findings.append(Finding(
                id="assemble.sequence_rotation_skipped",
                category="assemble",
                severity=Severity.WARN,
                message="final rotation GIF skipped because final STEP export did not run",
                evidence={
                    "dry_run": dry_run,
                    "blocking": blocking,
                    "sequence_blocked_at": sequence_blocked_at,
                },
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
        "sequence_blocked_at": sequence_blocked_at,
        "stop_on_validation_fail": stop_on_validation_fail,
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
            *(
                ["sequence instance-level interference"]
                if sequence_interference_checked else []
            ),
            *(
                ["sequence V-slot handoff stackup"]
                if sequence_vslot_stackup_checked else []
            ),
            *(
                ["sequence static frame adjacency"]
                if sequence_frame_adjacency_checked else []
            ),
            *(
                ["sequence authored hole alignment"]
                if sequence_hole_alignment_checked else []
            ),
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
                [] if sequence_interference_checked
                else ["sequence instance-level interference"]
                if validate_interference else []
            ),
            *(
                [] if sequence_vslot_stackup_checked
                else ["sequence V-slot handoff stackup"]
                if validate_vslot_stackup else []
            ),
            *(
                [] if sequence_frame_adjacency_checked
                else ["sequence static frame adjacency"]
                if validate_frame_adjacency else []
            ),
            *(
                [] if sequence_hole_alignment_checked
                else ["sequence authored hole alignment"]
                if validate_hole_alignment else []
            ),
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
            "sequence_blocked_at": sequence_blocked_at,
            "stop_on_validation_fail": stop_on_validation_fail,
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
    requested_checks = _requested_validation_checks(spec)
    validation_meta: Dict[str, object] = {}
    geometry_plan: Optional[AssemblyBuildPlan] = None

    def _get_geometry_plan() -> AssemblyBuildPlan:
        nonlocal geometry_plan
        if geometry_plan is None:
            geometry_plan = plan_assembly_build(
                spec_file,
                connector_metadata_path=connector_metadata_path or spec.connector_metadata,
                dry_run=False,
            )
        return geometry_plan

    if "interference" in requested_checks:
        if dry_run:
            validation_meta["interference"] = {
                "checked": False,
                "reason": "dry_run",
            }
        elif build_report.overall == Severity.FAIL:
            validation_meta["interference"] = {
                "checked": False,
                "reason": "build_failed",
            }
        else:
            interference_findings, interference_meta = _run_spec_interference(
                spec,
                spec_file,
                _get_geometry_plan(),
            )
            findings.extend(interference_findings)
            validation_meta["interference"] = interference_meta

    if "vslot_stackup" in requested_checks:
        if dry_run:
            validation_meta["vslot_stackup"] = {
                "checked": False,
                "reason": "dry_run",
            }
        elif build_report.overall == Severity.FAIL:
            validation_meta["vslot_stackup"] = {
                "checked": False,
                "reason": "build_failed",
            }
        else:
            stackup_findings, stackup_meta = _run_vslot_stackup(
                spec,
                spec_file,
                _get_geometry_plan(),
            )
            findings.extend(stackup_findings)
            validation_meta["vslot_stackup"] = stackup_meta

    if "frame_adjacency" in requested_checks:
        if dry_run:
            validation_meta["frame_adjacency"] = {
                "checked": False,
                "reason": "dry_run",
            }
        elif build_report.overall == Severity.FAIL:
            validation_meta["frame_adjacency"] = {
                "checked": False,
                "reason": "build_failed",
            }
        else:
            frame_findings, frame_meta = _run_frame_adjacency(
                spec,
                spec_file,
                _get_geometry_plan(),
            )
            findings.extend(frame_findings)
            validation_meta["frame_adjacency"] = frame_meta

    if "hole_alignment" in requested_checks:
        if dry_run:
            validation_meta["hole_alignment"] = {
                "checked": False,
                "reason": "dry_run",
            }
        elif build_report.overall == Severity.FAIL:
            validation_meta["hole_alignment"] = {
                "checked": False,
                "reason": "build_failed",
            }
        else:
            hole_findings, hole_meta = _run_hole_alignment(
                spec,
                spec_file,
                _get_geometry_plan(),
            )
            findings.extend(hole_findings)
            validation_meta["hole_alignment"] = hole_meta

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
    if validation_meta.get("interference", {}).get("checked"):
        if "interference" in confidence.not_checked:
            confidence.not_checked.remove("interference")
        if "instance-level interference" not in confidence.checked:
            confidence.checked.append("instance-level interference")
    elif "interference" in requested_checks:
        reason = validation_meta.get("interference", {}).get("reason", "not_run")
        label = f"interference ({reason})"
        if label not in confidence.not_checked:
            confidence.not_checked.append(label)
    if validation_meta.get("vslot_stackup", {}).get("checked"):
        if "V-slot handoff stackup" not in confidence.checked:
            confidence.checked.append("V-slot handoff stackup")
    elif "vslot_stackup" in requested_checks:
        reason = validation_meta.get("vslot_stackup", {}).get("reason", "not_run")
        label = f"V-slot handoff stackup ({reason})"
        if label not in confidence.not_checked:
            confidence.not_checked.append(label)
    if validation_meta.get("frame_adjacency", {}).get("checked"):
        if "static frame adjacency" not in confidence.checked:
            confidence.checked.append("static frame adjacency")
    elif "frame_adjacency" in requested_checks:
        reason = validation_meta.get("frame_adjacency", {}).get(
            "reason", "not_run"
        )
        label = f"static frame adjacency ({reason})"
        if label not in confidence.not_checked:
            confidence.not_checked.append(label)
    if validation_meta.get("hole_alignment", {}).get("checked"):
        if "authored hole alignment" not in confidence.checked:
            confidence.checked.append("authored hole alignment")
    elif "hole_alignment" in requested_checks:
        reason = validation_meta.get("hole_alignment", {}).get("reason", "not_run")
        label = f"authored hole alignment ({reason})"
        if label not in confidence.not_checked:
            confidence.not_checked.append(label)
    for check_name in sorted(
        requested_checks - {
            "inventory",
            "interference",
            "vslot_stackup",
            "frame_adjacency",
            "hole_alignment",
        }
    ):
        label = f"{check_name} (not yet wired for assembly specs)"
        if label not in confidence.not_checked:
            confidence.not_checked.append(label)
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
            "validation": validation_meta,
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
