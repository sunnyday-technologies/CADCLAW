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

    @field_validator("translate_mm", "rotate_deg")
    @classmethod
    def _check_vec3(cls, value: List[float]) -> List[float]:
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError("transform vectors must be 3-element lists")
        if not all(isinstance(v, (int, float)) for v in value):
            raise ValueError("transform vector elements must be numbers")
        return [float(v) for v in value]


class Instance(_Strict):
    id: str
    role: str
    component_id: Optional[str] = None
    source_path: Optional[str] = None
    transform: Transform = Field(default_factory=Transform)
    color_label: Optional[str] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _component_or_source(self) -> "Instance":
        if not self.component_id and not self.source_path:
            raise ValueError("instance requires component_id or source_path")
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
    component_roots: List[str] = Field(default_factory=list)
    protected_paths: List[str] = Field(default_factory=list)
    outputs: Outputs
    bom: BomPlan = Field(default_factory=BomPlan)
    assumptions: List[str] = Field(default_factory=list)
    constraints: List[AssemblyConstraint] = Field(default_factory=list)
    instances: List[Instance] = Field(default_factory=list)
    review_views: List[ReviewView] = Field(default_factory=list)
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
    "AssemblySpec",
    "BomPlan",
    "Instance",
    "MachineVariant",
    "NotBuiltYet",
    "Outputs",
    "ReferenceAsset",
    "ReviewView",
    "Transform",
    "dump_assembly_spec",
    "load_assembly_spec",
]
