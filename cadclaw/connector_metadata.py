"""Connector metadata schema for CADCLAW assembly placement.

Connector metadata is the bridge between an authored STEP asset and reliable
LLM-operated assembly. It records local coordinate frames such as extrusion
ends, mount faces, shaft axes, and belt planes. The data is descriptive; it
does not generate contextual plates or hole patterns.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CONNECTOR_METADATA_VERSION = "connector_metadata.v0.1"

_FRAME_KINDS = {
    "extrusion_end",
    "mount_face",
    "rail_slot",
    "wheel_contact",
    "shaft_axis",
    "belt_plane",
    "bracket_face",
    "reference",
}

_MATE_KINDS = {
    "mate",
    "align",
    "offset",
    "mirror",
    "pattern",
    "reference",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _vec3(value: List[float], field_name: str) -> List[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field_name} must be a 3-element list")
    if not all(isinstance(v, (int, float)) for v in value):
        raise ValueError(f"{field_name} values must be numbers")
    return [float(v) for v in value]


class ConnectorFrame(_Strict):
    id: str
    kind: str = "reference"
    origin_mm: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    x_axis: List[float] = Field(default_factory=lambda: [1.0, 0.0, 0.0])
    y_axis: List[float] = Field(default_factory=lambda: [0.0, 1.0, 0.0])
    z_axis: List[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    tags: List[str] = Field(default_factory=list)
    verified: bool = False
    notes: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, value: str) -> str:
        kind = value.lower()
        if kind not in _FRAME_KINDS:
            raise ValueError(f"kind must be one of {sorted(_FRAME_KINDS)}")
        return kind

    @field_validator("origin_mm", "x_axis", "y_axis", "z_axis")
    @classmethod
    def _check_vec3(cls, value: List[float], info) -> List[float]:
        return _vec3(value, info.field_name)


class ComponentConnectorSet(_Strict):
    id: str
    source_path: Optional[str] = None
    component_id: Optional[str] = None
    frames: List[ConnectorFrame] = Field(default_factory=list)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _check_component_identity(self) -> "ComponentConnectorSet":
        if not self.source_path and not self.component_id:
            raise ValueError("component connector set needs source_path or component_id")
        seen: set[str] = set()
        for frame in self.frames:
            if frame.id in seen:
                raise ValueError(f"duplicate frame id {frame.id!r} in {self.id!r}")
            seen.add(frame.id)
        return self


class MateConstraint(_Strict):
    id: str
    kind: str = "mate"
    from_instance: str
    from_frame: str
    to_instance: str
    to_frame: str
    offset_mm: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    notes: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, value: str) -> str:
        kind = value.lower()
        if kind not in _MATE_KINDS:
            raise ValueError(f"kind must be one of {sorted(_MATE_KINDS)}")
        return kind

    @field_validator("offset_mm")
    @classmethod
    def _check_offset(cls, value: List[float]) -> List[float]:
        return _vec3(value, "offset_mm")


class ConnectorMetadata(_Strict):
    schema_version: str = CONNECTOR_METADATA_VERSION
    components: List[ComponentConnectorSet] = Field(default_factory=list)
    mates: List[MateConstraint] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, value: str) -> str:
        if value != CONNECTOR_METADATA_VERSION:
            raise ValueError(
                f"unsupported connector metadata version {value!r}; "
                f"expected {CONNECTOR_METADATA_VERSION!r}"
            )
        return value

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "ConnectorMetadata":
        component_ids: set[str] = set()
        for component in self.components:
            if component.id in component_ids:
                raise ValueError(f"duplicate component connector id {component.id!r}")
            component_ids.add(component.id)
        mate_ids: set[str] = set()
        for mate in self.mates:
            if mate.id in mate_ids:
                raise ValueError(f"duplicate mate id {mate.id!r}")
            mate_ids.add(mate.id)
        return self

    def component_keys(self) -> set[str]:
        keys: set[str] = set()
        for component in self.components:
            keys.add(component.id)
            if component.component_id:
                keys.add(component.component_id)
            if component.source_path:
                keys.add(Path(component.source_path).as_posix())
        return keys


def load_connector_metadata(path: str | Path) -> ConnectorMetadata:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return ConnectorMetadata.model_validate(data)


def dump_connector_metadata(metadata: ConnectorMetadata) -> str:
    return yaml.safe_dump(
        metadata.model_dump(exclude_none=True),
        sort_keys=False,
        allow_unicode=False,
    )


__all__ = [
    "CONNECTOR_METADATA_VERSION",
    "ComponentConnectorSet",
    "ConnectorFrame",
    "ConnectorMetadata",
    "MateConstraint",
    "dump_connector_metadata",
    "load_connector_metadata",
]
