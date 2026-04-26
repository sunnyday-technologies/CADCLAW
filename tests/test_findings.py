"""Tests for cadharness/findings.py — Severity rollup, Finding round-trip."""
import json
import unittest

from cadharness.findings import (
    ConfidenceBudget,
    Finding,
    Report,
    Severity,
)


class TestSeverity(unittest.TestCase):
    def test_rank_order(self):
        self.assertLess(Severity.PASS.rank(), Severity.WARN.rank())
        self.assertLess(Severity.WARN.rank(), Severity.FAIL.rank())

    def test_str_value(self):
        self.assertEqual(Severity.FAIL.value, "fail")
        self.assertEqual(Severity.WARN.value, "warn")
        self.assertEqual(Severity.PASS.value, "pass")


class TestFinding(unittest.TestCase):
    def test_to_dict_serializes_severity_as_string(self):
        f = Finding(
            id="bom.qty_mismatch",
            category="bom_audit",
            severity=Severity.FAIL,
            message="id=5 qty=16, expected 12",
            evidence={"rule_id": 5, "got": 16, "expected": 12},
        )
        d = f.to_dict()
        self.assertEqual(d["severity"], "fail")
        self.assertEqual(d["evidence"]["rule_id"], 5)
        # Round-trip through JSON
        roundtrip = json.loads(json.dumps(d))
        self.assertEqual(roundtrip, d)

    def test_default_evidence_is_empty_dict(self):
        f = Finding(id="x", category="y", severity=Severity.PASS, message="ok")
        self.assertEqual(f.evidence, {})


class TestReportRollup(unittest.TestCase):
    def test_compute_overall_fail_wins(self):
        r = Report(findings=[
            Finding(id="a", category="x", severity=Severity.PASS, message=""),
            Finding(id="b", category="x", severity=Severity.WARN, message=""),
            Finding(id="c", category="x", severity=Severity.FAIL, message=""),
        ])
        self.assertEqual(r.compute_overall(), Severity.FAIL)

    def test_compute_overall_warn_when_no_fail(self):
        r = Report(findings=[
            Finding(id="a", category="x", severity=Severity.PASS, message=""),
            Finding(id="b", category="x", severity=Severity.WARN, message=""),
        ])
        self.assertEqual(r.compute_overall(), Severity.WARN)

    def test_compute_overall_pass_when_only_pass(self):
        r = Report(findings=[
            Finding(id="a", category="x", severity=Severity.PASS, message=""),
        ])
        self.assertEqual(r.compute_overall(), Severity.PASS)

    def test_compute_overall_pass_when_no_findings(self):
        r = Report(findings=[])
        self.assertEqual(r.compute_overall(), Severity.PASS)

    def test_passed_property(self):
        r = Report(findings=[Finding("a", "x", Severity.WARN, "")])
        r.overall = r.compute_overall()
        self.assertTrue(r.passed)
        r2 = Report(findings=[Finding("b", "x", Severity.FAIL, "")])
        r2.overall = r2.compute_overall()
        self.assertFalse(r2.passed)


class TestReportSerialization(unittest.TestCase):
    def test_to_dict_has_locked_schema_version(self):
        r = Report()
        d = r.to_dict()
        self.assertEqual(d["schema_version"], "0.7")
        self.assertIn("findings", d)
        self.assertIn("confidence_budget", d)

    def test_to_dict_round_trips_through_json(self):
        r = Report(
            findings=[Finding("a", "x", Severity.WARN, "msg", "fix", {"k": "v"})],
            meta={"project": "p"},
            duration_ms=1.5,
        )
        r.overall = r.compute_overall()
        d = r.to_dict()
        s = json.dumps(d)
        roundtrip = json.loads(s)
        self.assertEqual(roundtrip["overall"], "warn")
        self.assertEqual(roundtrip["meta"]["project"], "p")
        self.assertEqual(roundtrip["findings"][0]["evidence"]["k"], "v")

    def test_by_severity_filters_correctly(self):
        r = Report(findings=[
            Finding("a", "x", Severity.PASS, ""),
            Finding("b", "x", Severity.WARN, ""),
            Finding("c", "x", Severity.WARN, ""),
            Finding("d", "x", Severity.FAIL, ""),
        ])
        self.assertEqual(len(r.by_severity(Severity.WARN)), 2)
        self.assertEqual(len(r.by_severity(Severity.FAIL)), 1)


class TestConfidenceBudget(unittest.TestCase):
    def test_merge_dedupes(self):
        a = ConfidenceBudget(
            checked=["inventory"],
            not_checked=["belt slip"],
            assumptions=["mm units"],
        )
        b = ConfidenceBudget(
            checked=["inventory", "bom"],
            not_checked=["thread engagement", "belt slip"],
            assumptions=["mm units"],
        )
        a.merge(b)
        self.assertEqual(a.checked, ["inventory", "bom"])
        self.assertEqual(set(a.not_checked), {"belt slip", "thread engagement"})
        self.assertEqual(a.assumptions, ["mm units"])


if __name__ == "__main__":
    unittest.main()
