"""
Rule file loader — pydantic v2 models + `load_rules(path)` for cadclaw.yaml.

The rule file is the single source of project-specific configuration: bbox
labels, expected inventory, regions, BOM rules, claim-audit rules,
publish-audit globs, and the confidence budget. Every section is optional;
missing sections skip their gate and append to `confidence_budget.not_checked`.

Schema version is locked at "0.7". Bumping it is a deliberate breaking-change
signal; minor field additions stay at the current version and remain
backwards compatible.

Usage:
    from cadharness.rules import load_rules
    rules = load_rules("cadclaw.yaml")
    rules.labels                  # dict label -> [dx, dy, dz]
    rules.bom_audit.rules         # list[BomRuleModel]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSION = "0.7"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


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


class ConfidenceBudgetModel(_Strict):
    checked: List[str] = Field(default_factory=list)
    not_checked: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)


class RuleSet(_Strict):
    schema_version: str = SCHEMA_VERSION
    meta: MetaModel = Field(default_factory=MetaModel)

    labels: Dict[str, List[float]] = Field(default_factory=dict)
    belt_heuristic: bool = True

    expected_inventory: Dict[str, int] = Field(default_factory=dict)
    regions: List[RegionModel] = Field(default_factory=list)

    bom_audit: BomAuditModel = Field(default_factory=BomAuditModel)
    claim_audit: ClaimAuditModel = Field(default_factory=ClaimAuditModel)
    publish_audit: PublishAuditModel = Field(default_factory=PublishAuditModel)
    confidence_budget: ConfidenceBudgetModel = Field(default_factory=ConfidenceBudgetModel)

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {v!r}; this CADCLAW expects "
                f"{SCHEMA_VERSION!r}. Migration: change schema_version to "
                f"{SCHEMA_VERSION!r}; new optional fields are "
                "expected_design_qty, spare_qty, exempt_categories, "
                "warn_on_unmapped — no field renames required."
            )
        return v

    @field_validator("labels")
    @classmethod
    def _check_labels(cls, v: Dict[str, List[float]]) -> Dict[str, List[float]]:
        for name, sig in v.items():
            if name == "belt_heuristic":
                continue
            if not isinstance(sig, list) or len(sig) != 3:
                raise ValueError(
                    f"label {name!r}: signature must be a 3-element list [dx,dy,dz], got {sig!r}"
                )
            if not all(isinstance(x, (int, float)) for x in sig):
                raise ValueError(
                    f"label {name!r}: signature elements must be numbers, got {sig!r}"
                )
        return v

    def label_to_sig(self) -> Dict[str, Tuple[float, float, float]]:
        """Resolve labels to sorted-tuple signatures matching `inventory.sig`."""
        out: Dict[str, Tuple[float, float, float]] = {}
        for name, sig in self.labels.items():
            if name == "belt_heuristic":
                continue
            out[name] = tuple(sorted(round(float(x), 1) for x in sig))
        return out

    def sig_to_label(self) -> Dict[Tuple[float, float, float], str]:
        """Reverse map: bbox sig -> label, matching the legacy dict shape."""
        return {sig: name for name, sig in self.label_to_sig().items()}


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
