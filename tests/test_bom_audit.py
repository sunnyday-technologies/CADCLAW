"""Acceptance tests for cadharness/bom_audit.py.

Each test pins a specific code path the BOM audit must catch. The L3_good.step
fixture provides the CAD inventory; the bom_*.json files are the BOM under
test; tests/fixtures/m3_crete/cadclaw_m3.yaml is the rule file.
"""
import unittest
from pathlib import Path

from cadharness.bom_audit import run_bom_audit
from cadharness.findings import Severity
from cadharness.rules import load_rules


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
