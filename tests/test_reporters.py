"""Tests for cadclaw/reporters — text / markdown / json."""
import json
import unittest

from cadclaw.findings import (
    ConfidenceBudget,
    Finding,
    Report,
    Severity,
)
from cadclaw.reporters import render_json, render_markdown, render_text


def _sample_report() -> Report:
    r = Report(
        meta={"project": "m3-crete", "step": "m3.step"},
        findings=[
            Finding("inventory.count_mismatch", "inventory", Severity.FAIL,
                    "cbeam: got 16, expected 17",
                    suggested_fix="check the BOM"),
            Finding("bom.qty_mismatch", "bom_audit", Severity.WARN,
                    "id=5 qty=12, expected 12"),
            Finding("inventory.region_count_mismatch", "inventory", Severity.PASS,
                    "all regions ok"),
        ],
        confidence_budget=ConfidenceBudget(
            checked=["inventory", "bom_audit"],
            not_checked=["thread engagement", "belt slip"],
            assumptions=["mm units"],
        ),
        duration_ms=125.0,
    )
    r.overall = r.compute_overall()
    return r


class TestTextReporter(unittest.TestCase):
    def test_includes_overall_severity(self):
        text = render_text(_sample_report(), color=False)
        self.assertIn("FAIL", text)

    def test_includes_each_finding(self):
        text = render_text(_sample_report(), color=False)
        self.assertIn("inventory.count_mismatch", text)
        self.assertIn("bom.qty_mismatch", text)

    def test_includes_suggested_fix(self):
        text = render_text(_sample_report(), color=False)
        self.assertIn("check the BOM", text)

    def test_includes_confidence_budget(self):
        text = render_text(_sample_report(), color=False)
        self.assertIn("did not check", text.lower())
        self.assertIn("thread engagement", text)
        self.assertIn("Assumptions", text)

    def test_no_findings_shows_pass(self):
        r = Report()
        r.overall = r.compute_overall()
        text = render_text(r, color=False)
        self.assertIn("PASS", text)
        self.assertIn("no findings", text)

    def test_color_off_has_no_ansi(self):
        text = render_text(_sample_report(), color=False)
        self.assertNotIn("\033[", text)

    def test_color_on_has_ansi(self):
        text = render_text(_sample_report(), color=True)
        self.assertIn("\033[", text)


class TestMarkdownReporter(unittest.TestCase):
    def test_starts_with_header(self):
        md = render_markdown(_sample_report())
        self.assertTrue(md.startswith("# CADCLAW report"))

    def test_includes_findings_table(self):
        md = render_markdown(_sample_report())
        self.assertIn("| Severity | Gate | ID | Message |", md)

    def test_includes_overall_result(self):
        md = render_markdown(_sample_report())
        self.assertIn("**Result: FAIL**", md)

    def test_includes_confidence_budget(self):
        md = render_markdown(_sample_report())
        self.assertIn("Confidence budget", md)
        self.assertIn("Not checked", md)

    def test_no_findings_renders_cleanly(self):
        r = Report()
        r.overall = r.compute_overall()
        md = render_markdown(r)
        self.assertIn("No findings", md)

    def test_finding_with_pipe_in_message_is_escaped(self):
        r = Report(findings=[
            Finding("a", "x", Severity.WARN, "got | two | parts"),
        ])
        r.overall = r.compute_overall()
        md = render_markdown(r)
        # The literal pipe should be escaped so the table doesn't break
        self.assertIn("got \\| two \\| parts", md)


class TestJsonReporter(unittest.TestCase):
    def test_produces_valid_json(self):
        s = render_json(_sample_report())
        d = json.loads(s)
        self.assertEqual(d["overall"], "fail")
        self.assertEqual(d["schema_version"], "0.7")

    def test_locked_schema_version(self):
        s = render_json(_sample_report())
        d = json.loads(s)
        self.assertEqual(d["schema_version"], "0.7")

    def test_findings_are_round_trippable(self):
        s = render_json(_sample_report())
        d = json.loads(s)
        self.assertEqual(len(d["findings"]), 3)
        first = d["findings"][0]
        self.assertEqual(first["id"], "inventory.count_mismatch")
        self.assertEqual(first["severity"], "fail")
        self.assertEqual(first["category"], "inventory")
        self.assertEqual(first["suggested_fix"], "check the BOM")

    def test_confidence_budget_present(self):
        s = render_json(_sample_report())
        d = json.loads(s)
        self.assertIn("not_checked", d["confidence_budget"])
        self.assertIn("thread engagement", d["confidence_budget"]["not_checked"])


if __name__ == "__main__":
    unittest.main()
