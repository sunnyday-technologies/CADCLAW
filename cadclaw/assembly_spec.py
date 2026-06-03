"""Assembly spec schema for CADCLAW's CadQuery assembly harness.

This module defines the declarative contract an LLM or human edits before
CADCLAW compiles an authored-STEP assembly. It is intentionally strict:
unknown keys fail validation, generated outputs must avoid protected CAD
exports, and incomplete work is represented explicitly as `not_built_yet`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ASSEMBLY_SPEC_VERSION = "assembly_spec.v0.1"
_VALID_VIEWS = {
    "iso",
    "iso_left",
    "iso_below",
    "iso_below_left",
    "hero",
    "front",
    "back",
    "side",
    "top",
    "bottom",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _norm_path(value: str) -> str:
    return Path(value).as_posix().rstrip("/").lower()


class ReferenceAsset(_Strict):
    path: str
    role: str = "visual_reference"
    notes: Optional[str] = None
    dimensional_evidence: bool = False


class Outputs(_Strict):
    step: str
    views_dir: str
    report: Optional[str] = None
    design_inventory: Optional[str] = None
    bom: Optional[str] = None


class MachineVariant(_Strict):
    id: str
    label: str
    envelope_mm: List[float]
    notes: Optional[str] = None

    @field_validator("envelope_mm")
    @classmethod
    def _check_envelope(cls, value: List[float]) -> List[float]:
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError("envelope_mm must be [x, y, z]")
        if not all(isinstance(v, (int, float)) and v > 0 for v in value):
            raise ValueError("envelope_mm values must be positive numbers")
        return [float(v) for v in value]


class BomPlan(_Strict):
    source_path: Optional[str] = None
    variant_config_path: Optional[str] = None
    output_path: Optional[str] = None
    private_fields_redacted: bool = True
    notes: Optional[str] = None


class AssemblyConstraint(_Strict):
    id: str
    severity: str = "fail"
    rule: str
    source: Optional[str] = None
    applies_to_variants: List[str] = Field(default_factory=list)

    @field_validator("severity")
    @classmethod
    def _check_severity(cls, value: str) -> str:
        severity = value.lower()
        if severity not in {"info", "warn", "fail"}:
            raise ValueError("severity must be one of info, warn, fail")
        return severity


class Transform(_Strict):
    translate_mm: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    rotate_deg: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: float = 1.0
    source_origin_mm: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])

    @field_validator("translate_mm", "rotate_deg", "source_origin_mm")
    @classmethod
    def _check_vec3(cls, value: List[float]) -> List[float]:
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError("transform vectors must be 3-element lists")
        if not all(isinstance(v, (int, float)) for v in value):
            raise ValueError("transform vector elements must be numbers")
        return [float(v) for v in value]

    @field_validator("scale")
    @classmethod
    def _check_scale(cls, value: float) -> float:
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("transform scale must be a positive number")
        return float(value)


class RelativePlacement(_Strict):
    """Constraint-based placement: solve this instance's transform from a parent.

    The instance's connector frame ``frame`` is seated onto the parent
    instance's connector frame ``parent_frame``: the frame origins are offset by
    ``offset_mm`` along the global ``axis`` in the ``side`` direction. This is the
    datum-chain alternative to an absolute :class:`Transform`.

    ``lock`` selects how many axes the resolver solves:

    - ``"frame"`` (default): a full 3-axis seat. The child frame origin is made
      to coincide with the parent frame origin (then offset along ``axis``), so
      all three translation components are solved. The instance must NOT carry an
      explicit ``transform``; orientation is authored here via ``rotate_deg`` /
      ``scale`` / ``source_origin_mm``.
    - ``"axis"``: an axis-only lock. The resolver solves ONLY the ``axis``
      translation component (seating the child frame ``offset_mm`` off the parent
      frame along that axis); the instance keeps its own ``transform`` for
      orientation and the two free (non-handoff) translation axes. The authored
      value of the locked axis is ignored — it is solved — so it may be left at
      0.0. ``rotate_deg`` / ``scale`` / ``source_origin_mm`` here must stay unset:
      orientation lives in the instance ``transform`` so there is one source of
      truth. This is the lightweight mode for a gantry that hands off along one
      axis while spanning the others (e.g. the Y-gantry off the X-to-Y plate).
    """

    ref: str
    parent_frame: str
    frame: str
    axis: str
    side: str = "positive"
    offset_mm: float = 0.0
    lock: str = "frame"
    rotate_deg: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale: float = 1.0
    source_origin_mm: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    notes: Optional[str] = None

    @field_validator("axis")
    @classmethod
    def _check_axis(cls, value: str) -> str:
        axis = value.lower()
        if axis not in {"x", "y", "z"}:
            raise ValueError("axis must be one of x, y, z")
        return axis

    @field_validator("lock")
    @classmethod
    def _check_lock(cls, value: str) -> str:
        lock = value.lower()
        if lock not in {"frame", "axis"}:
            raise ValueError("lock must be 'frame' (full seat) or 'axis' (axis-only)")
        return lock

    @field_validator("side")
    @classmethod
    def _check_side(cls, value: str) -> str:
        side = value.lower()
        if side not in {"positive", "negative"}:
            raise ValueError("side must be positive or negative")
        return side

    @field_validator("rotate_deg", "source_origin_mm")
    @classmethod
    def _check_vec3(cls, value: List[float]) -> List[float]:
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError("placement vectors must be 3-element lists")
        if not all(isinstance(v, (int, float)) for v in value):
            raise ValueError("placement vector elements must be numbers")
        return [float(v) for v in value]

    @field_validator("scale")
    @classmethod
    def _check_scale(cls, value: float) -> float:
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError("placement scale must be a positive number")
        return float(value)


class Instance(_Strict):
    id: str
    role: str
    component_id: Optional[str] = None
    source_path: Optional[str] = None
    transform: Transform = Field(default_factory=Transform)
    place_relative_to: Optional[RelativePlacement] = None
    color_label: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _component_or_source(self) -> "Instance":
        if not self.component_id and not self.source_path:
            raise ValueError("instance requires component_id or source_path")
        return self

    @model_validator(mode="after")
    def _placement_is_exclusive(self) -> "Instance":
        placement = self.place_relative_to
        if placement is None:
            return self
        has_transform = self.transform.model_dump() != Transform().model_dump()
        if placement.lock == "axis":
            # Axis-only lock keeps the instance transform for orientation and the
            # two free axes; the resolver overrides only the handoff axis. So a
            # transform is expected here, but orientation must NOT also be set on
            # the placement block (one source of truth for orientation).
            placement_orients = (
                placement.rotate_deg != [0.0, 0.0, 0.0]
                or placement.scale != 1.0
                or placement.source_origin_mm != [0.0, 0.0, 0.0]
            )
            if placement_orients:
                raise ValueError(
                    "place_relative_to.lock=axis takes orientation/scale/"
                    "source_origin from the instance transform; leave "
                    "rotate_deg/scale/source_origin unset on the placement"
                )
        elif has_transform:
            raise ValueError(
                "instance cannot set both an explicit transform and "
                "place_relative_to; author orientation in "
                "place_relative_to.rotate_deg and let the resolver solve "
                "the translation"
            )
        return self


class ReviewView(_Strict):
    name: str
    view: str = "iso"
    width: int = 1280
    height: int = 720
    azimuth: float = 0.0
    elevation: float = 0.0
    notes: Optional[str] = None

    @field_validator("view")
    @classmethod
    def _check_view(cls, value: str) -> str:
        view = value.lower()
        if view not in _VALID_VIEWS:
            raise ValueError(
                f"view must be one of {sorted(_VALID_VIEWS)}, got {value!r}"
            )
        return view


class AssemblySequenceStep(_Strict):
    id: str
    title: str
    instance_ids: List[str]
    notes: Optional[str] = None

    @field_validator("instance_ids")
    @classmethod
    def _check_instance_ids(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("assembly sequence step needs at least one instance_id")
        if len(set(value)) != len(value):
            raise ValueError("assembly sequence step contains duplicate instance_ids")
        return value


class NotBuiltYet(_Strict):
    item: str
    reason: str
    required_for_release: bool = True


class AssemblyMeta(_Strict):
    project: str
    assembly_id: str
    description: Optional[str] = None


class AssemblySpec(_Strict):
    schema_version: str = ASSEMBLY_SPEC_VERSION
    meta: AssemblyMeta
    active_variant: Optional[str] = None
    variants: List[MachineVariant] = Field(default_factory=list)
    reference_assets: List[ReferenceAsset] = Field(default_factory=list)
    manifests: List[str] = Field(default_factory=list)
    connector_metadata: Optional[str] = None
    component_roots: List[str] = Field(default_factory=list)
    protected_paths: List[str] = Field(default_factory=list)
    outputs: Outputs
    bom: BomPlan = Field(default_factory=BomPlan)
    assumptions: List[str] = Field(default_factory=list)
    constraints: List[AssemblyConstraint] = Field(default_factory=list)
    instances: List[Instance] = Field(default_factory=list)
    review_views: List[ReviewView] = Field(default_factory=list)
    assembly_sequence: List[AssemblySequenceStep] = Field(default_factory=list)
    not_built_yet: List[NotBuiltYet] = Field(default_factory=list)
    validation: Dict[str, object] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        if value != ASSEMBLY_SPEC_VERSION:
            raise ValueError(
                f"unsupported assembly spec version {value!r}; "
                f"expected {ASSEMBLY_SPEC_VERSION!r}"
            )
        return value

    @model_validator(mode="after")
    def _check_protected_outputs(self) -> "AssemblySpec":
        output_step = _norm_path(self.outputs.step)
        for protected in self.protected_paths:
            if output_step == _norm_path(protected):
                raise ValueError(
                    f"outputs.step must not overwrite protected path: "
                    f"{self.outputs.step}"
                )
        if self.active_variant:
            known = {variant.id for variant in self.variants}
            if known and self.active_variant not in known:
                raise ValueError(
                    f"active_variant {self.active_variant!r} is not listed "
                    f"in variants"
                )
        known_instances = {instance.id for instance in self.instances}
        for step in self.assembly_sequence:
            missing = [
                instance_id for instance_id in step.instance_ids
                if instance_id not in known_instances
            ]
            if missing:
                raise ValueError(
                    f"assembly_sequence step {step.id!r} references unknown "
                    f"instance ids: {missing}"
                )
        return self


def load_assembly_spec(path: str | Path) -> AssemblySpec:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return AssemblySpec.model_validate(data)


def dump_assembly_spec(spec: AssemblySpec) -> str:
    return yaml.safe_dump(
        spec.model_dump(exclude_none=True),
        sort_keys=False,
        allow_unicode=False,
    )


__all__ = [
    "ASSEMBLY_SPEC_VERSION",
    "AssemblyConstraint",
    "AssemblySequenceStep",
    "AssemblySpec",
    "BomPlan",
    "Instance",
    "MachineVariant",
    "NotBuiltYet",
    "Outputs",
    "ReferenceAsset",
    "RelativePlacement",
    "ReviewView",
    "Transform",
    "dump_assembly_spec",
    "load_assembly_spec",
]
