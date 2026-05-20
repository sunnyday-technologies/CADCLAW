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

Forbidden-term matching is negation-aware (v0.7 / MED-2). When a forbidden
term appears in a BOM description preceded by a negation token within 30
characters (bounded by sentence punctuation) — e.g. "do not substitute the
10mm belt" — the match is suppressed. The negation tokens are: not, no,
never, do not, don't, doesn't, replaces, instead of, rather than, without,
excludes. Required-term matching keeps dumb-substring semantics because
required_terms asks about presence-of-token, not assertion strength.

Usage:
    from cadclaw.bom_audit import run_bom_audit
    from cadclaw.rules import load_rules
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
from collections import Counter, defaultdict
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

_NEGATION_PATTERN = re.compile(
    r"\b(?:not|no|never|do not|don't|doesn't|replaces|instead of|rather than|without|excludes)\b",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARIES = (".", "!", "?", "\n")
_NEGATION_LOOKBACK_CHARS = 30


def _negation_window(haystack: str, term_index: int) -> str:
    """Return the prefix preceding term_index, ≤30 chars, truncated to just
    past the most-recent sentence boundary. Used to test whether a
    forbidden-term hit is negated.
    """
    start = max(0, term_index - _NEGATION_LOOKBACK_CHARS)
    window = haystack[start:term_index]
    last_boundary = max(
        (window.rfind(b) for b in _SENTENCE_BOUNDARIES),
        default=-1,
    )
    if last_boundary >= 0:
        window = window[last_boundary + 1:]
    return window


def _is_negated(haystack: str, term_index: int) -> bool:
    """True if a negation token precedes the term hit within the lookback window."""
    return bool(_NEGATION_PATTERN.search(_negation_window(haystack, term_index)))


# v0.7.1 / INFO-9: detect cp1252-misencoded UTF-8 in BOM string fields.
#
# When a BOM author saves a UTF-8 file as cp1252 (or vice-versa), characters
# like em-dash, smart quotes, accents, NBSP, and degree become double-byte
# mojibake sequences such as `â€"`, `â€™`, `Ã©`, `Ã¼`, `Â `, `Â°`. The pattern
# is the high-byte UTF-8 lead-byte (0xC3 / 0xC2 / 0xE2-0x80) read through the
# cp1252 codepage, producing visible Latin Capital Letter A With Tilde (Ã),
# Latin Capital Letter A With Circumflex (Â), or Latin Small Letter A With
# Circumflex (â) followed by another non-ASCII byte. Detecting any of these
# pairs is a reliable mojibake signal.
_MOJIBAKE_PATTERN = re.compile(r"[ÃÂ][-ÿ]|â€[-ÿ]?")


def _string_fields_with_mojibake(item: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Return [(field_name, sample_excerpt), ...] for fields that smell of
    cp1252/UTF-8 double-encoding. Limited to public-allowlist string fields
    so private content never leaks into a finding's evidence.
    """
    hits: List[Tuple[str, str]] = []
    for field in ("name", "description", "notes"):
        v = item.get(field)
        if not isinstance(v, str):
            continue
        m = _MOJIBAKE_PATTERN.search(v)
        if m is None:
            continue
        # Show ~12 chars of context centered on the match. Keep it short
        # so the report stays scannable on narrow PR comment widths.
        i = m.start()
        start = max(0, i - 8)
        end = min(len(v), m.end() + 8)
        hits.append((field, v[start:end]))
    return hits


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


def _term_matches(
    haystack: str,
    term: str,
    *,
    case_sensitive: bool,
    use_regex: bool,
    negation_aware: bool = False,
) -> bool:
    """Test whether `term` appears in `haystack`.

    When `negation_aware=True` and `use_regex=False`, suppress the match if
    a negation token precedes the hit within 30 chars (bounded by sentence
    punctuation). Forbidden-term rules pass `negation_aware=True`;
    required-term rules don't, because `required_terms: ["plastic"]`
    should still satisfy "no plastic" — required asks about
    presence-of-token, not assertion. Regex rules ignore `negation_aware`;
    authors get raw control via lookbehinds.
    """
    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        return bool(re.search(term, haystack, flags=flags))
    if case_sensitive:
        h, t = haystack, term
    else:
        h, t = haystack.lower(), term.lower()
    if not t:
        return False
    if not negation_aware:
        return t in h
    idx = h.find(t)
    while idx >= 0:
        if not _is_negated(haystack, idx):
            return True
        idx = h.find(t, idx + 1)
    return False


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
    """Resolve the expected CAD-side count for this rule.

    Precedence (v0.7):
      1. rule.expected_design_qty — design intent (NEW canonical CAD field).
      2. rule.expected_cad_count — explicit per-rule override.
      3. rule.pack_size × item.qty — derived from procurement pack size.
      4. item.qty — fallback (BOM procurement qty). Note: this conflates
         design count with order count; use expected_design_qty for explicit
         control when the BOM intentionally orders extras (spares, packaging
         multiples, etc.).
    """
    if rule.expected_design_qty is not None:
        return rule.expected_design_qty
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

    # v0.7.1 / INFO-9: scan BOM string fields for cp1252-misencoded UTF-8.
    # One WARN per affected item; the cited excerpt is bounded to ~16 chars
    # to keep PR-comment widths reasonable. Opt-out via
    # bom_audit.warn_on_mojibake: false.
    if rules.bom_audit.warn_on_mojibake:
        for item in items:
            hits = _string_fields_with_mojibake(item)
            if not hits:
                continue
            field_list = ", ".join(name for name, _ in hits)
            sample = hits[0][1]
            findings.append(Finding(
                id="bom.encoding_issue",
                category="bom_audit",
                severity=Severity.WARN,
                message=(
                    f"BOM id={item.get('id', '?')!r}: cp1252/UTF-8 mojibake "
                    f"in field(s) {field_list} (sample: {sample!r})."
                ),
                suggested_fix=(
                    "The BOM file was likely saved with the wrong encoding "
                    "at some point — re-encode it as UTF-8 (in your editor: "
                    "File > Save With Encoding > UTF-8). To suppress this "
                    "check, set bom_audit.warn_on_mojibake: false."
                ),
                evidence={
                    "bom_id": item.get("id"),
                    "fields": [name for name, _ in hits],
                    "sample": sample,
                },
            ))

    matched_bom_ids: set = set()
    matched_labels: set = set()
    # v0.7 / MED-5: aggregate cad.count_mismatch per labels-tuple. Multiple
    # rules pointing at the same label get summed into one finding so the
    # user sees the actual delta, not three individual mismatches.
    label_aggregation: Dict[Tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)
    bom_rules = rules.bom_audit.rules

    for rule in bom_rules:
        rule_findings: List[Finding] = []
        item = bom_by_id.get(rule.id)
        labels = _resolve_labels(rule)
        if labels:
            for label in labels:
                matched_labels.add(label)
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
            expected = (
                rule.expected_design_qty
                if rule.expected_design_qty is not None
                else rule.expected_cad_count
            )
            if expected is not None and labels:
                label_aggregation[tuple(sorted(labels))].append({
                    "rule_id": rule.id,
                    "expected": expected,
                    "severity": Severity.FAIL,
                    "labels": list(labels),
                })
            findings.extend(_apply_severity_override(rule, f) for f in rule_findings)
            continue

        matched_bom_ids.add(rule.id)
        public_item = to_public_dict(item)

        # 4a-v07. Spare-qty consistency check (MED-6) — soft signal only.
        # If the rule sets expected_qty (procurement) AND expected_design_qty
        # (CAD intent) AND spare_qty, verify expected_qty == design + spare.
        # Real-world procurement legitimately diverges (split shipments,
        # mid-build replenishments) so this is WARN, not FAIL.
        if (rule.expected_qty is not None
                and rule.expected_design_qty is not None
                and rule.spare_qty is not None):
            implied = rule.expected_design_qty + rule.spare_qty
            if rule.expected_qty != implied:
                rule_findings.append(Finding(
                    id="bom.spare_qty_inconsistent",
                    category="bom_audit",
                    severity=Severity.WARN,
                    message=(
                        f"BOM id={rule.id}: expected_qty ({rule.expected_qty}) "
                        f"!= expected_design_qty ({rule.expected_design_qty}) "
                        f"+ spare_qty ({rule.spare_qty}) = {implied}."
                    ),
                    suggested_fix=(
                        "Reconcile the three values: typically "
                        "expected_qty = expected_design_qty + spare_qty. "
                        "If your procurement intentionally diverges "
                        "(split shipments, replenishments) the warning is informational."
                    ),
                    evidence={
                        "rule_id": rule.id,
                        "expected_qty": rule.expected_qty,
                        "expected_design_qty": rule.expected_design_qty,
                        "spare_qty": rule.spare_qty,
                        "implied_total": implied,
                    },
                ))

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
                negation_aware=True,
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
        if labels:
            cad_count = sum(cad_inventory.get(l, 0) for l in labels)
            expected = _effective_cad_count(rule, item)
            # v0.7 / MED-5: defer cad.count_mismatch emission so we can
            # aggregate multiple rules pointing at the same label. Track
            # this rule's contribution; the aggregated finding is emitted
            # after the rule loop. Single-rule labels get the v0.6-style
            # message verbatim there.
            if expected is not None:
                override_str = (
                    rule.severity_overrides.get("cad.count_mismatch")
                    or rule.severity_overrides.get("count_mismatch")
                )
                rule_severity = Severity.FAIL
                if override_str and override_str.lower() in _SEV:
                    rule_severity = _SEV[override_str.lower()]
                label_aggregation[tuple(sorted(labels))].append({
                    "rule_id": rule.id,
                    "expected": expected,
                    "severity": rule_severity,
                    "labels": list(labels),
                })
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

    # 4f-aggregate. cad.count_mismatch — emit one finding per label-set,
    # summing contributions from multiple rules. Single-rule labels keep
    # the v0.6-style message; multi-rule labels get the aggregated form
    # showing per-rule expected counts and overall delta.
    for labels_tuple, contributions in sorted(label_aggregation.items()):
        cad_count = sum(cad_inventory.get(l, 0) for l in labels_tuple)
        expected_total = sum(c["expected"] for c in contributions)
        if cad_count == expected_total:
            continue
        labels_list = list(labels_tuple)
        labels_display = labels_list[0] if len(labels_list) == 1 else labels_list
        rule_ids = [c["rule_id"] for c in contributions]
        # Strictest severity wins (FAIL > WARN > PASS)
        severity = max((c["severity"] for c in contributions), key=lambda s: s.rank())
        if len(contributions) == 1:
            c = contributions[0]
            findings.append(Finding(
                id="cad.count_mismatch",
                category="bom_audit",
                severity=severity,
                message=(
                    f"CAD has {cad_count}× {labels_display} "
                    f"but BOM/rule expects {c['expected']} (id={c['rule_id']})."
                ),
                suggested_fix=(
                    f"Either fix the CAD assembly so the count is "
                    f"{c['expected']}, or update BOM id={c['rule_id']}."
                ),
                evidence={
                    "rule_id": c["rule_id"],
                    "labels": labels_list,
                    "cad_count": cad_count,
                    "expected_cad_count": c["expected"],
                },
            ))
        else:
            expected_each = [c["expected"] for c in contributions]
            delta = cad_count - expected_total
            ids_str = "+".join(str(r) for r in rule_ids)
            expected_str = "+".join(str(e) for e in expected_each)
            findings.append(Finding(
                id="cad.count_mismatch",
                category="bom_audit",
                severity=severity,
                message=(
                    f"CAD has {cad_count}× {labels_display}, rules sum to "
                    f"{expected_total} (ids {ids_str} expect {expected_str}). "
                    f"Δ={delta:+d}."
                ),
                suggested_fix=(
                    f"Either fix the CAD assembly so the count is "
                    f"{expected_total}, or update one of the BOM rules "
                    f"({rule_ids})."
                ),
                evidence={
                    "labels": labels_list,
                    "cad_count": cad_count,
                    "rule_ids": rule_ids,
                    "rule_expected": expected_each,
                    "expected_total": expected_total,
                    "delta": delta,
                },
            ))

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
    # v0.7 / LOW-6: two new orthogonal levers reduce noise on real BOMs:
    #   - exempt_categories: items with `category` matching skip the loop
    #   - warn_on_unmapped (default True): when False, suppress entirely
    exempt_cats_lower = {c.lower() for c in rules.bom_audit.exempt_categories}
    warn_on_unmapped = rules.bom_audit.warn_on_unmapped
    for iid, item in bom_by_id.items():
        if iid in matched_bom_ids:
            continue
        if is_exempt_from_cad(item):
            continue
        if exempt_cats_lower:
            cat = item.get("category")
            if isinstance(cat, str) and any(
                e in cat.lower() for e in exempt_cats_lower
            ):
                continue
        if not warn_on_unmapped:
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
