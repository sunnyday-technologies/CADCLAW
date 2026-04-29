"""
Rule file loader — pydantic v2 models + `load_rules(path)` for cadclaw.yaml.

The rule file is the single source of project-specific configuration: bbox
labels, expected inventory, regions, BOM rules, claim-audit rules,
publish-audit globs, and the confidence budget. Every section is optional;
missing sections skip their gate and append to `confidence_budget.not_checked`.

Schema version is locked at "0.9". Bumping is a deliberate breaking-change
signal; minor field additions stay at the current version and remain
backwards compatible.

v0.9 schema additions (over v0.7):
- `labels:` accepts EITHER a 3-tuple `[dx, dy, dz]` (legacy form, still
  supported) OR a `LabelSpec` dict with `sig` plus optional orientation
  / face-mate fields (`expected_face`, `expected_against`, `max_gap_mm`).
  See `LabelSpec` for the field set.

Usage:
    from cadclaw.rules import load_rules
    rules = load_rules("cadclaw.yaml")
    rules.labels                  # dict label -> LabelSpec (normalized)
    rules.label_to_sig()          # dict label -> (dx, dy, dz)  (legacy shape)
    rules.bom_audit.rules         # list[BomRuleModel]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSION = "0.9"
_VALID_FACE_PLANES = ("XY", "XZ", "YZ", "YX", "ZX", "ZY")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LabelSpec(_Strict):
    """A label entry — bbox signature plus optional orientation/face-mate hints.

    `sig` is the canonical sorted-tuple signature (rounded to 0.1mm) the
    inventory check matches against.

    `expected_face` declares which axis-aligned plane the part's largest
    bbox face must lie in. For a part with bbox `(5, 30, 30)`, the largest
    face is the 30×30 face perpendicular to the smallest dimension; its
    normal is along the axis of the smallest dim. So `expected_face: YZ`
    says "the largest face's normal is along the X axis" — equivalently,
    the part's THINNEST axis must be X. v0.9 gate #1 (orientation) reads
    this field. Accepted values: "XY", "XZ", "YZ" (and reverse aliases).
    Case-insensitive.

    `expected_against` is reserved for the face-mate adjacency variant —
    not yet wired through the harness as of v0.9 P1. Field validation
    accepts it; check execution is gated on the upstream label appearing
    in inventory.

    `max_gap_mm` tolerates floating-point STEP-import jitter when checking
    face-mate proximity. Default 0.5mm; tighten per-label if needed.
    """
    sig: List[float]
    expected_face: Optional[str] = None
    expected_against: Optional[str] = None
    max_gap_mm: float = 0.5

    @field_validator("sig")
    @classmethod
    def _check_sig(cls, v: List[float]) -> List[float]:
        if not isinstance(v, list) or len(v) != 3:
            raise ValueError(
                f"sig must be a 3-element list [dx, dy, dz], got {v!r}"
            )
        if not all(isinstance(x, (int, float)) for x in v):
            raise ValueError(
                f"sig elements must be numbers, got {v!r}"
            )
        return [float(x) for x in v]

    @field_validator("expected_face")
    @classmethod
    def _check_face(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().upper()
        if v not in _VALID_FACE_PLANES:
            raise ValueError(
                f"expected_face must be one of {sorted(set(_VALID_FACE_PLANES))}, "
                f"got {v!r}"
            )
        # Canonicalize reverse aliases.
        return {"YX": "XY", "ZX": "XZ", "ZY": "YZ"}.get(v, v)

    def thinnest_axis_index(self) -> Optional[int]:
        """Return 0/1/2 for X/Y/Z axis the largest face normal is along, or
        None if expected_face is unset.

        For `expected_face: YZ`, the largest face lies in the Y-Z plane,
        which means its normal is along the X axis → return 0.
        """
        if self.expected_face is None:
            return None
        return {"YZ": 0, "XZ": 1, "XY": 2}[self.expected_face]


class MetaModel(_Strict):
    project: Optional[str] = None
    description: Optional[str] = None
    step: Optional[str] = None
    bom: Optional[str] = None


class RegionModel(_Strict):
    name: str
    x_range: Optional[Tuple[Optional[float], Optional[float]]] = None
    y_range: Optional[Tuple[Optional[float], Optional[float]]] = None
    z_range: Optional[Tuple[Optional[float], Optional[float]]] = None
    expected: Dict[str, int] = Field(default_factory=dict)


class BomRuleModel(_Strict):
    id: Union[int, str]
    expected_qty: Optional[int] = None
    expected_mfg_type: Optional[str] = None
    expected_unit: Optional[str] = None
    required_terms: List[str] = Field(default_factory=list)
    forbidden_terms: List[str] = Field(default_factory=list)
    case_sensitive: bool = False
    use_regex: bool = False
    expected_label: Optional[Union[str, List[str]]] = None
    expected_sig: Optional[List[List[float]]] = None
    expected_cad_count: Optional[int] = None
    expected_design_qty: Optional[int] = None
    spare_qty: Optional[int] = None
    pack_size: Optional[int] = None
    min_cad_count: Optional[int] = None
    max_cad_count: Optional[int] = None
    expected_region: Optional[str] = None
    severity_overrides: Dict[str, str] = Field(default_factory=dict)


class BomAuditModel(_Strict):
    bom_path: Optional[str] = None
    ignore_labels: List[str] = Field(default_factory=list)
    exempt_categories: List[str] = Field(default_factory=list)
    warn_on_unmapped: bool = True
    warn_on_mojibake: bool = True
    rules: List[BomRuleModel] = Field(default_factory=list)


class SourceRegexRuleModel(_Strict):
    pattern: str
    severity: str = "fail"
    message: str
    file_glob: str = "**/*.py"


class ClaimAuditModel(_Strict):
    scan_paths: List[str] = Field(default_factory=lambda: ["README.md"])
    forbidden_absolutes_extra: List[str] = Field(default_factory=list)
    evidence_tags_required_for: List[str] = Field(default_factory=list)
    evidence_tags_allowed: List[str] = Field(
        default_factory=lambda: [
            "[analysis]",
            "[simulated]",
            "[measured-prototype]",
            "[measured-production]",
        ]
    )
    stale_terms: List[str] = Field(default_factory=list)
    source_regex_rules: List[SourceRegexRuleModel] = Field(default_factory=list)


class PublishAuditModel(_Strict):
    ignore_globs: List[str] = Field(default_factory=list)
    scan_globs: List[str] = Field(default_factory=list)
    redact_patterns: Dict[str, str] = Field(default_factory=dict)
    email_allowlist: List[str] = Field(default_factory=list)
    blob_size_warn_bytes: int = 20 * 1024 * 1024


class InterferenceModel(_Strict):
    """Pairwise solid-solid interference gate config.

    `min_clearance_mm` is the running clearance added to the suggested
    fix-vector when a clip is reported. The suggestion shifts part A by
    `overlap_on_axis + min_clearance_mm` along the cheapest axis so the
    moved part lands clear of the other rather than tangent to it.
    """
    skip_labels: List[str] = Field(default_factory=list)
    min_volume_mm3: float = 1.0
    min_clearance_mm: float = 1.0


class ConfidenceBudgetModel(_Strict):
    checked: List[str] = Field(default_factory=list)
    not_checked: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


class RuleSet(_Strict):
    schema_version: str = SCHEMA_VERSION
    meta: MetaModel = Field(default_factory=MetaModel)

    # `labels` accepts either a 3-tuple list (legacy) or a LabelSpec dict.
    # The `_normalize_labels` validator converts both shapes to LabelSpec
    # so downstream code always sees the rich form.
    labels: Dict[str, LabelSpec] = Field(default_factory=dict)
    belt_heuristic: bool = True

    expected_inventory: Dict[str, int] = Field(default_factory=dict)
    regions: List[RegionModel] = Field(default_factory=list)

    bom_audit: BomAuditModel = Field(default_factory=BomAuditModel)
    claim_audit: ClaimAuditModel = Field(default_factory=ClaimAuditModel)
    publish_audit: PublishAuditModel = Field(default_factory=PublishAuditModel)
    interference: InterferenceModel = Field(default_factory=InterferenceModel)
    confidence_budget: ConfidenceBudgetModel = Field(default_factory=ConfidenceBudgetModel)

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {v!r}; this CADCLAW expects "
                f"{SCHEMA_VERSION!r}. Migration: change schema_version to "
                f"{SCHEMA_VERSION!r}. v0.7 / v0.8.0 rule files mostly load "
                f"unchanged — only addition is the optional dict-form "
                "LabelSpec under `labels:` (legacy 3-tuple lists still work). "
                "New v0.9 LabelSpec fields: expected_face, expected_against, "
                "max_gap_mm — all optional."
            )
        return v

    @field_validator("labels", mode="before")
    @classmethod
    def _normalize_labels(cls, v: Any) -> Any:
        """Accept either a 3-tuple or a LabelSpec dict per label.

        Bare lists are wrapped as `{sig: <list>}` so the field type
        `Dict[str, LabelSpec]` always sees a dict. Other types pass
        through and let pydantic raise the canonical validation error.
        """
        if not isinstance(v, dict):
            return v
        out: Dict[str, Any] = {}
        for name, spec in v.items():
            if isinstance(spec, list):
                out[name] = {"sig": spec}
            else:
                out[name] = spec
        return out

    def label_to_sig(self) -> Dict[str, Tuple[float, float, float]]:
        """Resolve labels to sorted-tuple signatures matching `inventory.sig`."""
        out: Dict[str, Tuple[float, float, float]] = {}
        for name, spec in self.labels.items():
            if name == "belt_heuristic":
                continue
            sorted_sig = tuple(sorted(round(float(x), 1) for x in spec.sig))
            out[name] = sorted_sig
        return out

    def sig_to_label(self) -> Dict[Tuple[float, float, float], str]:
        """Reverse map: bbox sig -> label, matching the legacy dict shape."""
        return {sig: name for name, sig in self.label_to_sig().items()}

    def label_specs(self) -> Dict[str, LabelSpec]:
        """Return `LabelSpec` per label — the v0.9 rich form callers can
        read for orientation / face-mate / color / etc. fields."""
        return {name: spec for name, spec in self.labels.items()
                if name != "belt_heuristic"}


def load_rules(path: Union[str, Path]) -> RuleSet:
    """Load and validate a cadclaw.yaml file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"rule file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"rule file must be a YAML mapping at top level, got {type(data).__name__}")
    return RuleSet.model_validate(data)


def dump_rules(rules: RuleSet, path: Union[str, Path]) -> None:
    """Write a RuleSet to YAML — used by examples/init_rules.py."""
    data = rules.model_dump(exclude_defaults=False)
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
