"""Acceptance tests for cadharness/bom_audit.py.

Each test pins a specific code path the BOM audit must catch. The L3_good.step
fixture provides the CAD inventory; the bom_*.json files are the BOM under
test; tests/fixtures/m3_crete/cadclaw_m3.yaml is the rule file.
"""
import json
import tempfile
import unittest
from pathlib import Path

from cadharness.bom_audit import run_bom_audit
from cadharness.findings import Severity
from cadharness.rules import BomAuditModel, BomRuleModel, RuleSet, load_rules


FIXTURES = Path(__file__).parent / "fixtures"
M3 = FIXTURES / "m3_crete"
RULES = M3 / "cadclaw_m3.yaml"
STEP = FIXTURES / "L3_good.step"


def _run(bom_name: str):
    rules = load_rules(str(RULES))
    return run_bom_audit(
        bom_path=str(M3 / bom_name),
        step_path=str(STEP),
        rules=rules,
    )


def _has_finding(report, fid: str, **evidence_match) -> bool:
    for f in report.findings:
        if f.id != fid:
            continue
        if all(f.evidence.get(k) == v for k, v in evidence_match.items()):
            return True
    return False


class TestBomGoodPasses(unittest.TestCase):
    def test_good_bom_passes_against_l3_fixture(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated; run tests/generate_fixtures.py")
        report = _run("bom_good.json")
        self.assertEqual(report.overall, Severity.PASS,
                         msg=f"Findings: {[f.id for f in report.findings]}")
        self.assertTrue(report.passed)


class TestStaleConnectors(unittest.TestCase):
    def test_qty_16_fails(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_stale_connectors.json")
        self.assertFalse(report.passed)
        self.assertTrue(_has_finding(report, "bom.qty_mismatch", rule_id=5))

    def test_maximum_rigidity_phrase_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_stale_connectors.json")
        self.assertTrue(any(
            f.id == "bom.forbidden_term_present" and f.evidence.get("term") == "maximum rigidity"
            for f in report.findings
        ))

    def test_primary_stiffness_phrase_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_stale_connectors.json")
        self.assertTrue(any(
            f.id == "bom.forbidden_term_present" and f.evidence.get("term") == "primary stiffness"
            for f in report.findings
        ))


class TestStaleInserts(unittest.TestCase):
    def test_jb_weld_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_stale_inserts.json")
        self.assertFalse(report.passed)
        self.assertTrue(any(
            f.id == "bom.forbidden_term_present" and f.evidence.get("term") == "JB Weld"
            for f in report.findings
        ))

    def test_west_system_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_stale_inserts.json")
        self.assertTrue(any(
            f.id == "bom.forbidden_term_present" and f.evidence.get("term") == "West System"
            for f in report.findings
        ))

    def test_custom_2m_cut_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_stale_inserts.json")
        self.assertTrue(any(
            f.id == "bom.forbidden_term_present" and f.evidence.get("term") == "custom 2m cut"
            for f in report.findings
        ))


class TestStaleMotorMounts(unittest.TestCase):
    def test_buy_instead_of_print_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_stale_motor_mounts.json")
        self.assertFalse(report.passed)
        self.assertTrue(any(
            f.id == "bom.mfg_type_mismatch" and f.evidence.get("rule_id") == 41
            for f in report.findings
        ))


class TestWrongWheelCount(unittest.TestCase):
    def test_qty_24_fails(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_wrong_wheels.json")
        self.assertFalse(report.passed)
        self.assertTrue(any(
            f.id == "bom.qty_mismatch" and f.evidence.get("rule_id") == 12
                and f.evidence.get("got") == 24
            for f in report.findings
        ))


class TestWrongBeltWidths(unittest.TestCase):
    def test_x_belt_described_as_10mm_fails(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_wrong_belts.json")
        self.assertFalse(report.passed)
        # X-belt rule (id=30): requires "6mm", forbids "10mm"
        self.assertTrue(any(
            f.id == "bom.forbidden_term_present"
                and f.evidence.get("rule_id") == 30
                and f.evidence.get("term") == "10mm"
            for f in report.findings
        ))
        self.assertTrue(any(
            f.id == "bom.required_term_missing"
                and f.evidence.get("rule_id") == 30
            for f in report.findings
        ))

    def test_yz_belt_described_as_6mm_fails(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_wrong_belts.json")
        self.assertTrue(any(
            f.id == "bom.forbidden_term_present"
                and f.evidence.get("rule_id") == 31
                and f.evidence.get("term") == "6mm"
            for f in report.findings
        ))


class TestExemptItemsSuppressed(unittest.TestCase):
    def test_fasteners_and_electronics_not_flagged_as_unmapped(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        report = _run("bom_good.json")
        # id=200 (fastener) and id=300 (electronic) should NOT appear as unmapped
        for f in report.findings:
            if f.id == "bom.unmapped_item":
                self.assertNotEqual(f.evidence.get("rule_id"), 200)
                self.assertNotEqual(f.evidence.get("rule_id"), 300)


class TestMED2NegationAwareForbiddenTerms(unittest.TestCase):
    """v0.7 / MED-2: forbidden_terms suppress matches preceded by a negation
    token within ~30 chars (bounded by sentence punctuation).

    Each case mirrors a real false-positive from the M3-CRETE 2026-04-26
    field test: descriptions that warn AGAINST a substitution were flagged
    as if they were ASSERTING the forbidden thing.
    """

    def _run_inline(self, bom_items, rule_kwargs_list):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bom_items, f)
            tmp = f.name
        try:
            rules = RuleSet(bom_audit=BomAuditModel(rules=[
                BomRuleModel(**kw) for kw in rule_kwargs_list
            ]))
            return run_bom_audit(bom_path=tmp, step_path=str(STEP), rules=rules)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_not_the_primary_stiffness_does_not_flag(self):
        """M3-CRETE id=5 case: 'not the primary stiffness'."""
        bom = [{
            "id": 100, "name": "Connector Bar", "qty": 12, "mfg_type": "buy",
            "description": (
                "These are alignment aids, not the primary stiffness "
                "or centering method."
            ),
        }]
        report = self._run_inline(bom, [{"id": 100, "forbidden_terms": ["primary stiffness"]}])
        self.assertFalse(_has_finding(report, "bom.forbidden_term_present", rule_id=100))

    def test_do_not_substitute_10mm_does_not_flag(self):
        """M3-CRETE id=15 case: 'do not substitute the 10mm belt'."""
        bom = [{
            "id": 101, "name": "X belt", "qty": 1, "mfg_type": "buy",
            "description": (
                "Uses 6mm GT2 because the X belt must fit inside the gantry "
                "slot; do not substitute the 10mm belt used on Y/Z here."
            ),
        }]
        report = self._run_inline(bom, [{"id": 101, "forbidden_terms": ["10mm"]}])
        self.assertFalse(_has_finding(report, "bom.forbidden_term_present", rule_id=101))

    def test_no_purchased_does_not_flag(self):
        """M3-CRETE id=24 case: 'No purchased Z motor brackets'."""
        bom = [{
            "id": 102, "name": "Z bracket", "qty": 4, "mfg_type": "print",
            "description": (
                "No purchased Z motor brackets in the current reference design."
            ),
        }]
        report = self._run_inline(bom, [{"id": 102, "forbidden_terms": ["purchased"]}])
        self.assertFalse(_has_finding(report, "bom.forbidden_term_present", rule_id=102))

    def test_replaces_jb_weld_does_not_flag_jb_weld(self):
        bom = [{
            "id": 103, "name": "Loctite tube", "qty": 1, "mfg_type": "buy",
            "description": "This part replaces JB Weld in the bond joint design.",
        }]
        report = self._run_inline(bom, [{"id": 103, "forbidden_terms": ["JB Weld"]}])
        self.assertFalse(_has_finding(report, "bom.forbidden_term_present", rule_id=103))

    def test_unnegated_forbidden_term_still_fires(self):
        """Sanity: real assertion of a forbidden term must still flag."""
        bom = [{
            "id": 104, "name": "Insert", "qty": 1, "mfg_type": "buy",
            "description": "Uses JB Weld for bonding the corner joint.",
        }]
        report = self._run_inline(bom, [{"id": 104, "forbidden_terms": ["JB Weld"]}])
        self.assertTrue(_has_finding(report, "bom.forbidden_term_present", rule_id=104))

    def test_negation_in_prior_sentence_does_not_suppress(self):
        """Sentence-boundary truncation: 'Do not use plastic.' in sentence 1
        should NOT suppress 'plastic' assertion in sentence 2."""
        bom = [{
            "id": 105, "name": "Frame", "qty": 1, "mfg_type": "buy",
            "description": "Do not use plastic. The frame contains plastic spacers.",
        }]
        report = self._run_inline(bom, [{"id": 105, "forbidden_terms": ["plastic"]}])
        self.assertTrue(_has_finding(report, "bom.forbidden_term_present", rule_id=105))

    def test_required_term_still_dumb_match(self):
        """Required-term rule must NOT use negation-awareness — 'no plastic'
        should satisfy `required_terms: ["plastic"]` because the rule asks
        about presence-of-token, not assertion."""
        bom = [{
            "id": 106, "name": "Bracket", "qty": 1, "mfg_type": "buy",
            "description": "Uses no plastic in the load path.",
        }]
        report = self._run_inline(bom, [{"id": 106, "required_terms": ["plastic"]}])
        self.assertFalse(_has_finding(report, "bom.required_term_missing", rule_id=106))

    def test_regex_path_ignores_negation_aware(self):
        """Regex authors get raw control via lookbehinds; negation_aware
        is silently ignored on the regex path."""
        bom = [{
            "id": 107, "name": "Bracket", "qty": 1, "mfg_type": "buy",
            "description": "Do not use steel here.",
        }]
        report = self._run_inline(bom, [{
            "id": 107, "forbidden_terms": [r"steel"], "use_regex": True,
        }])
        # use_regex bypass: even though preceded by 'Do not', the regex
        # path doesn't check for negation. Author can use lookbehinds if
        # they want negation-awareness.
        self.assertTrue(_has_finding(report, "bom.forbidden_term_present", rule_id=107))


class TestMED5AggregatedCadCountMismatch(unittest.TestCase):
    """v0.7 / MED-5: when multiple BOM rules expect the same CAD label,
    emit one aggregated cad.count_mismatch with the delta, not N separate
    findings each saying their own per-rule expected count.
    """

    def _run_inline(self, bom_items, rule_kwargs_list, labels=None):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bom_items, f)
            tmp = f.name
        try:
            rules = RuleSet(
                labels=labels or {},
                bom_audit=BomAuditModel(rules=[
                    BomRuleModel(**kw) for kw in rule_kwargs_list
                ]),
            )
            return run_bom_audit(bom_path=tmp, step_path=str(STEP), rules=rules)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_three_rules_same_label_emit_one_aggregated_finding(self):
        """M3-CRETE motor_nema23 case: 3 rules expect motor_nema23 with
        qtys 1+2+4=7. CAD (L3_good fixture) has motor_nema23 parts. The
        aggregated finding sums the 3 rules and reports one delta."""
        # L3_good has 1 NEMA23 motor (sig 56.4, 56.4, 76.6).
        bom = [
            {"id": 9, "name": "X-axis NEMA23", "qty": 1, "mfg_type": "buy"},
            {"id": 14, "name": "Y-axis NEMA23 pair", "qty": 2, "mfg_type": "buy"},
            {"id": 19, "name": "Z-axis NEMA23 quad", "qty": 4, "mfg_type": "buy"},
        ]
        rules = [
            {"id": 9, "expected_qty": 1, "expected_label": "motor_nema23"},
            {"id": 14, "expected_qty": 2, "expected_label": "motor_nema23"},
            {"id": 19, "expected_qty": 4, "expected_label": "motor_nema23"},
        ]
        report = self._run_inline(
            bom, rules,
            labels={"motor_nema23": [56.4, 56.4, 76.6]},
        )
        # Expect exactly ONE cad.count_mismatch for motor_nema23
        motor_findings = [
            f for f in report.findings
            if f.id == "cad.count_mismatch"
                and (f.evidence.get("label") == "motor_nema23"
                     or "motor_nema23" in (f.evidence.get("labels") or []))
        ]
        self.assertEqual(len(motor_findings), 1,
                         f"Expected 1 aggregated finding, got {len(motor_findings)}: "
                         f"{[f.message for f in motor_findings]}")
        f = motor_findings[0]
        self.assertEqual(f.evidence["expected_total"], 7)
        self.assertEqual(set(f.evidence["rule_ids"]), {9, 14, 19})
        self.assertEqual(set(f.evidence["rule_expected"]), {1, 2, 4})
        # CAD count should be cad_count - 7 = delta
        self.assertEqual(f.evidence["delta"],
                         f.evidence["cad_count"] - 7)
        # Aggregated message format
        self.assertIn("rules sum to 7", f.message)
        self.assertIn("Δ=", f.message)

    def test_single_rule_label_uses_v06_message(self):
        """Single-rule labels keep the v0.6 message verbatim — no aggregation
        kicks in for the common case."""
        bom = [
            {"id": 100, "name": "X NEMA23", "qty": 5, "mfg_type": "buy"},
        ]
        rules = [
            {"id": 100, "expected_qty": 5, "expected_label": "motor_nema23"},
        ]
        report = self._run_inline(
            bom, rules,
            labels={"motor_nema23": [56.4, 56.4, 76.6]},
        )
        motor_findings = [
            f for f in report.findings
            if f.id == "cad.count_mismatch"
                and "motor_nema23" in (f.evidence.get("labels") or [])
        ]
        self.assertEqual(len(motor_findings), 1)
        # v0.6 message format: "but BOM/rule expects N (id=X)"
        self.assertIn("BOM/rule expects 5", motor_findings[0].message)
        self.assertIn("(id=100)", motor_findings[0].message)
        # No aggregated-only fields in evidence
        self.assertNotIn("rule_ids", motor_findings[0].evidence)
        self.assertNotIn("delta", motor_findings[0].evidence)

    def test_no_aggregation_when_count_matches_total(self):
        """If CAD count equals the sum of expected counts across all rules,
        no finding is emitted even if the per-rule counts disagree."""
        # L3_good has 1 NEMA23. Two rules summing to 1: 0+1=1 matches.
        bom = [
            {"id": 100, "name": "Spare X NEMA23", "qty": 0, "mfg_type": "buy"},
            {"id": 101, "name": "Y NEMA23", "qty": 1, "mfg_type": "buy"},
        ]
        rules = [
            {"id": 100, "expected_cad_count": 0, "expected_label": "motor_nema23"},
            {"id": 101, "expected_cad_count": 1, "expected_label": "motor_nema23"},
        ]
        report = self._run_inline(
            bom, rules,
            labels={"motor_nema23": [56.4, 56.4, 76.6]},
        )
        motor_findings = [
            f for f in report.findings
            if f.id == "cad.count_mismatch"
                and "motor_nema23" in (f.evidence.get("labels") or [])
        ]
        self.assertEqual(motor_findings, [],
                         f"Expected no mismatch, got {[f.message for f in motor_findings]}")

    def test_severity_override_strictest_wins(self):
        """When multiple contributing rules have different severity_overrides,
        the strictest (FAIL > WARN > PASS) is used for the aggregated finding."""
        bom = [
            {"id": 100, "name": "X NEMA23", "qty": 5, "mfg_type": "buy"},
            {"id": 101, "name": "Y NEMA23", "qty": 5, "mfg_type": "buy"},
        ]
        rules = [
            # rule 100 demotes to warn; rule 101 stays at default (fail)
            {
                "id": 100, "expected_qty": 5, "expected_label": "motor_nema23",
                "severity_overrides": {"cad.count_mismatch": "warn"},
            },
            {"id": 101, "expected_qty": 5, "expected_label": "motor_nema23"},
        ]
        report = self._run_inline(
            bom, rules,
            labels={"motor_nema23": [56.4, 56.4, 76.6]},
        )
        motor_findings = [
            f for f in report.findings
            if f.id == "cad.count_mismatch"
                and "motor_nema23" in (f.evidence.get("labels") or [])
        ]
        self.assertEqual(len(motor_findings), 1)
        # Strictest is FAIL (rule 101 default)
        self.assertEqual(motor_findings[0].severity, Severity.FAIL)


class TestMED6ExpectedDesignQtyAndSpareQty(unittest.TestCase):
    """v0.7 / MED-6: separate design count (CAD) from order count (BOM qty).
    M3-CRETE id=67 case: BOM qty=18 = 17 design + 1 spare; CAD has 17.
    All three v0.6 workarounds failed; v0.7 introduces expected_design_qty
    and spare_qty.
    """

    def _run_inline(self, bom_items, rule_kwargs_list, labels=None):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bom_items, f)
            tmp = f.name
        try:
            rules = RuleSet(
                labels=labels or {},
                bom_audit=BomAuditModel(rules=[
                    BomRuleModel(**kw) for kw in rule_kwargs_list
                ]),
            )
            return run_bom_audit(bom_path=tmp, step_path=str(STEP), rules=rules)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_expected_design_qty_takes_precedence_over_qty(self):
        """M3-CRETE id=67 cbeam: BOM qty=18 (procurement, includes 1 spare),
        CAD has 17 (design). Without expected_design_qty, the v0.6
        fallback to BOM qty would fire cad.count_mismatch (17 vs 18).
        With expected_design_qty=17, the CAD check passes."""
        # L3_good has 1 cbeam. Use that as our "design count = 1".
        bom = [
            {"id": 67, "name": "C-Beam frame member", "qty": 2, "mfg_type": "buy"},
        ]
        rules = [
            {
                "id": 67,
                "expected_design_qty": 1,
                "expected_label": "cbeam",
            },
        ]
        report = self._run_inline(
            bom, rules,
            labels={"cbeam": [40.0, 80.0, 1000.0]},
        )
        cbeam_count_findings = [
            f for f in report.findings
            if f.id == "cad.count_mismatch"
                and "cbeam" in (f.evidence.get("labels") or [])
        ]
        # CAD = 1, expected_design_qty = 1 → no mismatch
        self.assertEqual(cbeam_count_findings, [],
                         f"Expected no cad.count_mismatch, got "
                         f"{[f.message for f in cbeam_count_findings]}")

    def test_spare_qty_consistent_no_warning(self):
        """expected_qty = expected_design_qty + spare_qty — should NOT warn."""
        bom = [
            {"id": 67, "name": "C-Beam", "qty": 2, "mfg_type": "buy"},
        ]
        rules = [
            {
                "id": 67,
                "expected_qty": 2,
                "expected_design_qty": 1,
                "spare_qty": 1,
                "expected_label": "cbeam",
            },
        ]
        report = self._run_inline(
            bom, rules,
            labels={"cbeam": [40.0, 80.0, 1000.0]},
        )
        spare_findings = [
            f for f in report.findings if f.id == "bom.spare_qty_inconsistent"
        ]
        self.assertEqual(spare_findings, [])

    def test_spare_qty_inconsistent_warns(self):
        """expected_qty (5) != expected_design_qty (1) + spare_qty (1) = 2 → 1 warn."""
        bom = [
            {"id": 67, "name": "C-Beam", "qty": 5, "mfg_type": "buy"},
        ]
        rules = [
            {
                "id": 67,
                "expected_qty": 5,
                "expected_design_qty": 1,
                "spare_qty": 1,
                "expected_label": "cbeam",
            },
        ]
        report = self._run_inline(
            bom, rules,
            labels={"cbeam": [40.0, 80.0, 1000.0]},
        )
        spare_findings = [
            f for f in report.findings
            if f.id == "bom.spare_qty_inconsistent" and f.evidence.get("rule_id") == 67
        ]
        self.assertEqual(len(spare_findings), 1)
        self.assertEqual(spare_findings[0].severity, Severity.WARN)
        self.assertEqual(spare_findings[0].evidence["implied_total"], 2)

    def test_no_inconsistency_warning_when_field_missing(self):
        """If only some of the trio (expected_qty, expected_design_qty,
        spare_qty) are set, the consistency check is skipped."""
        bom = [
            {"id": 67, "name": "C-Beam", "qty": 2, "mfg_type": "buy"},
        ]
        rules = [
            # No spare_qty — consistency check skipped
            {
                "id": 67,
                "expected_qty": 2,
                "expected_design_qty": 1,
                "expected_label": "cbeam",
            },
        ]
        report = self._run_inline(
            bom, rules,
            labels={"cbeam": [40.0, 80.0, 1000.0]},
        )
        spare_findings = [
            f for f in report.findings if f.id == "bom.spare_qty_inconsistent"
        ]
        self.assertEqual(spare_findings, [])

    def test_v06_fallback_to_bom_qty_still_works(self):
        """When neither expected_design_qty nor expected_cad_count is set,
        the v0.6 fallback to BOM qty for the CAD count check is preserved
        for backwards compatibility."""
        # L3_good has 1 cbeam. Set BOM qty=2 → fallback fires the mismatch.
        bom = [
            {"id": 67, "name": "C-Beam", "qty": 2, "mfg_type": "buy"},
        ]
        rules = [
            # No expected_design_qty, no expected_cad_count, no pack_size
            {"id": 67, "expected_label": "cbeam"},
        ]
        report = self._run_inline(
            bom, rules,
            labels={"cbeam": [40.0, 80.0, 1000.0]},
        )
        cbeam_findings = [
            f for f in report.findings
            if f.id == "cad.count_mismatch"
                and "cbeam" in (f.evidence.get("labels") or [])
        ]
        # CAD has 1, BOM qty=2, fallback expects 2 → mismatch
        self.assertEqual(len(cbeam_findings), 1)


class TestLOW6UnmappedItemNoiseReduction(unittest.TestCase):
    """v0.7 / LOW-6: reduce bom.unmapped_item noise via two orthogonal levers:
    exempt_categories (skip items by `category` field) and warn_on_unmapped
    (suppress entirely).
    """

    def _run_with_audit_kwargs(self, bom_items, audit_kwargs):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bom_items, f)
            tmp = f.name
        try:
            rules = RuleSet(bom_audit=BomAuditModel(**audit_kwargs))
            return run_bom_audit(bom_path=tmp, step_path=str(STEP), rules=rules)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_exempt_categories_suppresses_unmapped_item(self):
        """Items whose `category` matches an entry in exempt_categories are
        skipped from the unmapped_item warn loop."""
        bom = [
            {
                "id": 200, "name": "M5 cap screw", "qty": 100, "mfg_type": "buy",
                "category": "Fasteners",
            },
            {
                "id": 201, "name": "M5 washer", "qty": 100, "mfg_type": "buy",
                "category": "Fasteners",
            },
            {
                "id": 202, "name": "Some real part", "qty": 1, "mfg_type": "buy",
                "category": "Frame Hardware",
            },
        ]
        report = self._run_with_audit_kwargs(bom, {
            "exempt_categories": ["Fasteners"],
            "rules": [],
        })
        unmapped = [f for f in report.findings if f.id == "bom.unmapped_item"]
        unmapped_ids = {f.evidence.get("rule_id") for f in unmapped}
        self.assertNotIn(200, unmapped_ids)
        self.assertNotIn(201, unmapped_ids)
        # Frame Hardware is not exempt → still flagged
        self.assertIn(202, unmapped_ids)

    def test_exempt_categories_case_insensitive_substring(self):
        """Match is case-insensitive substring — so 'electronics' matches
        a category 'Electronics & PCBA'."""
        bom = [
            {
                "id": 200, "name": "PCB", "qty": 1, "mfg_type": "buy",
                "category": "Electronics & PCBA",
            },
        ]
        report = self._run_with_audit_kwargs(bom, {
            "exempt_categories": ["electronics"],
            "rules": [],
        })
        self.assertEqual(
            [f for f in report.findings if f.id == "bom.unmapped_item"],
            [],
        )

    def test_warn_on_unmapped_false_suppresses_all(self):
        """When warn_on_unmapped=False, no bom.unmapped_item warns are
        emitted regardless of category/exemption."""
        bom = [
            {"id": 300, "name": "Mystery part", "qty": 1, "mfg_type": "buy"},
            {"id": 301, "name": "Other mystery", "qty": 1, "mfg_type": "buy"},
        ]
        report = self._run_with_audit_kwargs(bom, {
            "warn_on_unmapped": False,
            "rules": [],
        })
        self.assertEqual(
            [f for f in report.findings if f.id == "bom.unmapped_item"],
            [],
        )

    def test_warn_on_unmapped_default_true_preserves_v06_behavior(self):
        """Default warn_on_unmapped=True preserves v0.6 behavior — every
        unmapped item that isn't exempt produces a warn."""
        bom = [
            {"id": 400, "name": "Mystery part", "qty": 1, "mfg_type": "buy"},
        ]
        report = self._run_with_audit_kwargs(bom, {"rules": []})
        unmapped = [f for f in report.findings if f.id == "bom.unmapped_item"]
        self.assertEqual(len(unmapped), 1)
        self.assertEqual(unmapped[0].evidence.get("rule_id"), 400)


class TestINFO9MojibakeDetection(unittest.TestCase):
    """v0.7.1 INFO-9: detect cp1252-misencoded UTF-8 in BOM string fields."""

    def _bom_with(self, items):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8")
        json.dump(items, f, ensure_ascii=False)
        f.close()
        return f.name

    def _run_with_bom(self, items, **bom_audit_kwargs):
        bom_path = self._bom_with(items)
        try:
            rules = RuleSet(
                bom_audit=BomAuditModel(
                    bom_path=bom_path,
                    rules=[],
                    **bom_audit_kwargs,
                ),
            )
            report = run_bom_audit(
                bom_path=bom_path, step_path=str(STEP), rules=rules,
            )
        finally:
            Path(bom_path).unlink(missing_ok=True)
        return report

    def test_em_dash_mojibake_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated.")
        report = self._run_with_bom([
            {"id": 1, "name": "C-beam â€” 1m",
             "qty": 1, "mfg_type": "buy"},
        ])
        encoding_findings = [f for f in report.findings
                             if f.id == "bom.encoding_issue"]
        self.assertEqual(len(encoding_findings), 1)
        self.assertEqual(encoding_findings[0].severity, Severity.WARN)
        self.assertEqual(encoding_findings[0].evidence["bom_id"], 1)
        self.assertIn("name", encoding_findings[0].evidence["fields"])

    def test_e_acute_mojibake_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated.")
        report = self._run_with_bom([
            {"id": 2, "name": "pulley", "qty": 1, "mfg_type": "buy",
             "description": "tagged Ã© plate"},
        ])
        encoding_findings = [f for f in report.findings
                             if f.id == "bom.encoding_issue"]
        self.assertEqual(len(encoding_findings), 1)
        self.assertIn("description", encoding_findings[0].evidence["fields"])

    def test_clean_unicode_not_flagged(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated.")
        report = self._run_with_bom([
            {"id": 3, "name": "C-beam — 1m",         # CLEAN em-dash
             "qty": 1, "mfg_type": "buy",
             "description": "made by São Paulo Industries"},  # CLEAN ã
        ])
        encoding_findings = [f for f in report.findings
                             if f.id == "bom.encoding_issue"]
        self.assertEqual(encoding_findings, [])

    def test_warn_on_mojibake_false_suppresses(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated.")
        report = self._run_with_bom([
            {"id": 4, "name": "C-beam â€” 1m",  # mojibake
             "qty": 1, "mfg_type": "buy"},
        ], warn_on_mojibake=False)
        encoding_findings = [f for f in report.findings
                             if f.id == "bom.encoding_issue"]
        self.assertEqual(encoding_findings, [])

    def test_multiple_fields_one_finding(self):
        if not STEP.exists():
            self.skipTest("L3_good.step not generated.")
        report = self._run_with_bom([
            {"id": 5, "name": "C-beam â€” 1m",
             "qty": 1, "mfg_type": "buy",
             "description": "tagged Ã© plate"},
        ])
        encoding_findings = [f for f in report.findings
                             if f.id == "bom.encoding_issue"]
        self.assertEqual(len(encoding_findings), 1)
        # Both fields cited in evidence
        self.assertIn("name", encoding_findings[0].evidence["fields"])
        self.assertIn("description", encoding_findings[0].evidence["fields"])


class TestPrivacy(unittest.TestCase):
    def test_vendors_field_never_in_report(self):
        # Build a BOM with vendors/sku/unit_cost on every item, run the audit,
        # ensure no finding's evidence dict contains those keys.
        import json
        import tempfile
        bom = [
            {
                "id": 5,
                "name": "Connector Bar",
                "qty": 16,  # mismatch — triggers a finding citing the item
                "mfg_type": "buy",
                "vendors": [{"name": "Acme", "price": 99.99}],
                "sku": "PRIVATE-SKU-1234",
                "unit_cost": 5.50,
                "_internal": "should never appear",
                "description": "alignment aid only",
            },
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bom, f)
            tmp = f.name
        try:
            rules = load_rules(str(RULES))
            report = run_bom_audit(
                bom_path=tmp, step_path=str(STEP), rules=rules,
            )
        finally:
            Path(tmp).unlink(missing_ok=True)

        full_text = str([f.to_dict() for f in report.findings])
        self.assertNotIn("PRIVATE-SKU-1234", full_text)
        self.assertNotIn("99.99", full_text)
        self.assertNotIn("vendors", full_text)
        self.assertNotIn("Acme", full_text)
        self.assertNotIn("_internal", full_text)


if __name__ == "__main__":
    unittest.main()
