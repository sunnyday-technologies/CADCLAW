"""
BOM-vs-CAD audit — the headline v0.6 gate.

Catches:
  * BOM item exists but is missing/stale/incorrectly represented in CAD
  * CAD geometry exists but is missing from the BOM
  * BOM qty / mfg_type / unit / required-or-forbidden text contradicts the rule
  * CAD count for a label disagrees with rule.expected_cad_count or qty * pack_size

The rule file (cadclaw.yaml) is the canonical mapping between BOM items and
CAD signatures; the BOM JSON itself stays free of CAD knowledge so the
project lead can author it without owning the labels.

Usage:
    from cadharness.bom_audit import run_bom_audit
    from cadharness.rules import load_rules
    rules = load_rules("cadclaw.yaml")
    report = run_bom_audit(
        bom_path="bom/data.json",
        step_path="CAD/m3.step",
        rules=rules,
    )
    sys.exit(0 if report.passed else 1)
"""
from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .bom_loader import (
    haystack_text,
    index_bom,
    is_exempt_from_cad,
    load_bom,
    to_public_dict,
)
from .findings import ConfidenceBudget, Finding, Report, Severity
from .inventory import load_and_dedup, sig
from .rules import BomRuleModel, RuleSet


_SEV = {"pass": Severity.PASS, "warn": Severity.WARN, "fail": Severity.FAIL}


def _label_fn_from_rules(rules: RuleSet):
    sig_to_label = rules.sig_to_label()
    belt_heuristic = rules.belt_heuristic

    def label_fn(solid) -> str:
        s = sig(solid)
        if s in sig_to_label:
            return sig_to_label[s]
        if belt_heuristic and len(s) >= 2 and s[0] == 1.5 and s[1] == 6.0:
            return "belt"
        return "other"

    return label_fn


def _resolve_labels(rule: BomRuleModel) -> List[str]:
    if rule.expected_label is None:
        return []
    if isinstance(rule.expected_label, str):
        return [rule.expected_label]
    return list(rule.expected_label)


def _term_matches(haystack: str, term: str, *, case_sensitive: bool, use_regex: bool) -> bool:
    if not case_sensitive:
        h = haystack.lower()
        t = term.lower()
    else:
        h = haystack
        t = term
    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        return bool(re.search(term, haystack, flags=flags))
    return t in h


def _apply_severity_override(rule: BomRuleModel, finding: Finding) -> Finding:
    """If the rule has a severity_override for this finding's id, apply it."""
    short = finding.id.split(".", 1)[1] if "." in finding.id else finding.id
    override = (
        rule.severity_overrides.get(finding.id)
        or rule.severity_overrides.get(short)
    )
    if override and override.lower() in _SEV:
        return Finding(
            id=finding.id,
            category=finding.category,
            severity=_SEV[override.lower()],
            message=finding.message,
            suggested_fix=finding.suggested_fix,
            evidence=finding.evidence,
        )
    return finding


def _effective_cad_count(rule: BomRuleModel, item: Dict[str, Any]) -> Optional[int]:
    if rule.expected_cad_count is not None:
        return rule.expected_cad_count
    if rule.pack_size is not None:
        qty = item.get("qty")
        if isinstance(qty, int):
            return qty * rule.pack_size
    qty = item.get("qty")
    if isinstance(qty, int):
        return qty
    return None


def run_bom_audit(
    bom_path: Union[str, Path],
    step_path: Union[str, Path],
    rules: RuleSet,
) -> Report:
    """Run the BOM-vs-CAD audit and return a unified Report."""
    t0 = time.time()
    findings: List[Finding] = []

    items = load_bom(bom_path)
    bom_by_id = index_bom(items)

    parts = load_and_dedup(str(step_path))
    label_fn = _label_fn_from_rules(rules)
    cad_inventory = Counter(label_fn(p) for p in parts)

    matched_bom_ids: set = set()
    matched_labels: set = set()
    bom_rules = rules.bom_audit.rules

    for rule in bom_rules:
        rule_findings: List[Finding] = []
        item = bom_by_id.get(rule.id)
        if item is None:
            rule_findings.append(Finding(
                id="bom.rule_no_match",
                category="bom_audit",
                severity=Severity.FAIL,
                message=f"BOM rule id={rule.id!r} has no matching BOM item.",
                suggested_fix=(
                    f"Either add a BOM item with id={rule.id!r} or remove the rule."
                ),
                evidence={"rule_id": rule.id},
            ))
            findings.extend(_apply_severity_override(rule, f) for f in rule_findings)
            continue

        matched_bom_ids.add(rule.id)
        public_item = to_public_dict(item)

        # 4a. BOM-stated qty
        if rule.expected_qty is not None:
            actual_qty = item.get("qty")
            if actual_qty != rule.expected_qty:
                rule_findings.append(Finding(
                    id="bom.qty_mismatch",
                    category="bom_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"BOM id={rule.id} qty={actual_qty}, expected {rule.expected_qty}."
                    ),
                    suggested_fix=f"Set BOM id={rule.id} qty to {rule.expected_qty}.",
                    evidence={
                        "rule_id": rule.id,
                        "got": actual_qty,
                        "expected": rule.expected_qty,
                        "item": public_item,
                    },
                ))

        # 4b. mfg_type
        if rule.expected_mfg_type is not None:
            actual = item.get("mfg_type")
            if actual != rule.expected_mfg_type:
                rule_findings.append(Finding(
                    id="bom.mfg_type_mismatch",
                    category="bom_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"BOM id={rule.id} mfg_type={actual!r}, expected "
                        f"{rule.expected_mfg_type!r}."
                    ),
                    suggested_fix=(
                        f"Set BOM id={rule.id} mfg_type to {rule.expected_mfg_type!r}."
                    ),
                    evidence={
                        "rule_id": rule.id,
                        "got": actual,
                        "expected": rule.expected_mfg_type,
                        "item": public_item,
                    },
                ))

        # 4c. unit (warn-by-default; loose match)
        if rule.expected_unit is not None:
            actual = item.get("unit")
            if actual != rule.expected_unit:
                rule_findings.append(Finding(
                    id="bom.unit_mismatch",
                    category="bom_audit",
                    severity=Severity.WARN,
                    message=(
                        f"BOM id={rule.id} unit={actual!r}, expected "
                        f"{rule.expected_unit!r}."
                    ),
                    evidence={
                        "rule_id": rule.id,
                        "got": actual,
                        "expected": rule.expected_unit,
                    },
                ))

        # 4d/e. required + forbidden terms over name+description+notes
        haystack = haystack_text(item)
        for term in rule.required_terms:
            if not _term_matches(
                haystack, term,
                case_sensitive=rule.case_sensitive,
                use_regex=rule.use_regex,
            ):
                rule_findings.append(Finding(
                    id="bom.required_term_missing",
                    category="bom_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"BOM id={rule.id} description does not contain required "
                        f"term {term!r}."
                    ),
                    suggested_fix=(
                        f"Add {term!r} to the description/notes for id={rule.id}, "
                        "or remove the requirement from the rule."
                    ),
                    evidence={"rule_id": rule.id, "term": term},
                ))
        for term in rule.forbidden_terms:
            if _term_matches(
                haystack, term,
                case_sensitive=rule.case_sensitive,
                use_regex=rule.use_regex,
            ):
                rule_findings.append(Finding(
                    id="bom.forbidden_term_present",
                    category="bom_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"BOM id={rule.id} description contains forbidden term {term!r}."
                    ),
                    suggested_fix=(
                        f"Remove {term!r} from the description/notes for id={rule.id}."
                    ),
                    evidence={"rule_id": rule.id, "term": term},
                ))

        # 4f. CAD-side count
        labels = _resolve_labels(rule)
        if labels:
            cad_count = sum(cad_inventory.get(l, 0) for l in labels)
            for l in labels:
                matched_labels.add(l)
            expected = _effective_cad_count(rule, item)
            if expected is not None and cad_count != expected:
                rule_findings.append(Finding(
                    id="cad.count_mismatch",
                    category="bom_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"CAD has {cad_count}× {labels[0] if len(labels)==1 else labels} "
                        f"but BOM/rule expects {expected} (id={rule.id})."
                    ),
                    suggested_fix=(
                        f"Either fix the CAD assembly so the count is {expected}, "
                        f"or update BOM id={rule.id}."
                    ),
                    evidence={
                        "rule_id": rule.id,
                        "labels": labels,
                        "cad_count": cad_count,
                        "expected_cad_count": expected,
                    },
                ))
            if rule.min_cad_count is not None and cad_count < rule.min_cad_count:
                rule_findings.append(Finding(
                    id="cad.count_below_min",
                    category="bom_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"CAD has {cad_count}× {labels} but rule.min_cad_count="
                        f"{rule.min_cad_count} (id={rule.id})."
                    ),
                    evidence={"rule_id": rule.id, "cad_count": cad_count,
                              "min": rule.min_cad_count},
                ))
            if rule.max_cad_count is not None and cad_count > rule.max_cad_count:
                rule_findings.append(Finding(
                    id="cad.count_above_max",
                    category="bom_audit",
                    severity=Severity.FAIL,
                    message=(
                        f"CAD has {cad_count}× {labels} but rule.max_cad_count="
                        f"{rule.max_cad_count} (id={rule.id})."
                    ),
                    evidence={"rule_id": rule.id, "cad_count": cad_count,
                              "max": rule.max_cad_count},
                ))

        for f in rule_findings:
            findings.append(_apply_severity_override(rule, f))

    # 5. Unmapped CAD parts
    ignored_labels = set(rules.bom_audit.ignore_labels)
    for label, count in sorted(cad_inventory.items()):
        if label in matched_labels:
            continue
        if label in ignored_labels:
            continue
        findings.append(Finding(
            id="cad.unmapped_label",
            category="bom_audit",
            severity=Severity.WARN,
            message=(
                f"CAD has {count}× {label!r} but no BOM rule covers it."
            ),
            suggested_fix=(
                f"Add a BOM rule for {label!r}, list it in bom_audit.ignore_labels, "
                "or fix the CAD assembly."
            ),
            evidence={"label": label, "count": count},
        ))

    # 6. Unmapped BOM items (suppressing exempt items)
    for iid, item in bom_by_id.items():
        if iid in matched_bom_ids:
            continue
        if is_exempt_from_cad(item):
            continue
        findings.append(Finding(
            id="bom.unmapped_item",
            category="bom_audit",
            severity=Severity.WARN,
            message=(
                f"BOM id={iid} {item.get('name','?')!r} has no audit rule."
            ),
            suggested_fix=(
                f"Add a bom_audit.rules entry for id={iid} or set "
                f"exempt_from_cad: true / mfg_type to consumable/electronic/fastener."
            ),
            evidence={"rule_id": iid, "item": to_public_dict(item)},
        ))

    duration_ms = (time.time() - t0) * 1000
    rep = Report(
        findings=findings,
        duration_ms=duration_ms,
        meta={
            "category": "bom_audit",
            "bom_path": str(bom_path),
            "step_path": str(step_path),
            "n_bom_items": len(items),
            "n_rules": len(bom_rules),
            "cad_inventory": dict(cad_inventory),
        },
        confidence_budget=ConfidenceBudget(
            checked=[
                "BOM ↔ rule binding by id",
                "BOM qty / mfg_type / unit fields",
                "required and forbidden terms in name+description+notes",
                "CAD count vs expected_cad_count or qty*pack_size",
                "unmapped CAD labels",
                "unmapped BOM items (with exemption logic)",
            ],
            not_checked=[
                "physical dimensional accuracy of purchased parts",
                "vendor identity / stock / pricing (always private)",
                "fastener torque, thread engagement, preload",
                "parts that share both bbox and STEP color",
                "BOM revision lineage (a wholesale BOM swap can pass)",
            ],
            assumptions=[
                "BOM is the public source of truth for procurement",
                "rule file labels align with the STEP export's bbox signatures",
                "mm units throughout",
            ],
        ),
    )
    rep.overall = rep.compute_overall()
    return rep
