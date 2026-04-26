"""Tests for cadharness/rules.py — pydantic schema, YAML round-trip."""
import os
import tempfile
import unittest

from pydantic import ValidationError

from cadharness.rules import (
    BomRuleModel,
    RuleSet,
    SCHEMA_VERSION,
    dump_rules,
    load_rules,
)


GOOD_YAML = """
schema_version: "0.7"
meta:
  project: m3-crete
  step: examples/m3_crete/m3.step
labels:
  cbeam: [40.0, 80.0, 1000.0]
  motor_nema23: [56.4, 56.4, 76.6]
expected_inventory:
  cbeam: 17
  motor_nema23: 6
regions:
  - name: x_carriage
    z_range: [100.0, 250.0]
    expected: { vwheel: 8 }
bom_audit:
  bom_path: bom.json
  rules:
    - id: 5
      expected_qty: 12
      expected_label: connector_bar
      forbidden_terms: ["maximum rigidity"]
claim_audit:
  scan_paths: [README.md]
  stale_terms: ["JB Weld"]
publish_audit:
  ignore_globs: [".env*"]
confidence_budget:
  not_checked: ["thread engagement"]
"""


class TestRuleLoader(unittest.TestCase):
    def _write_tmp(self, text: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(text)
            return f.name

    def test_load_valid_rules(self):
        path = self._write_tmp(GOOD_YAML)
        try:
            rules = load_rules(path)
            self.assertEqual(rules.schema_version, "0.7")
            self.assertEqual(rules.meta.project, "m3-crete")
            self.assertIn("cbeam", rules.labels)
            self.assertEqual(rules.expected_inventory["cbeam"], 17)
            self.assertEqual(len(rules.regions), 1)
            self.assertEqual(rules.regions[0].name, "x_carriage")
            self.assertEqual(len(rules.bom_audit.rules), 1)
            self.assertEqual(rules.bom_audit.rules[0].id, 5)
            self.assertEqual(rules.claim_audit.stale_terms, ["JB Weld"])
            self.assertEqual(rules.publish_audit.ignore_globs, [".env*"])
        finally:
            os.unlink(path)

    def test_label_sig_helpers(self):
        path = self._write_tmp(GOOD_YAML)
        try:
            rules = load_rules(path)
            l2s = rules.label_to_sig()
            self.assertEqual(l2s["cbeam"], (40.0, 80.0, 1000.0))
            s2l = rules.sig_to_label()
            self.assertEqual(s2l[(40.0, 80.0, 1000.0)], "cbeam")
        finally:
            os.unlink(path)

    def test_label_sig_helpers_sort_dimensions(self):
        # Out-of-order dims should sort to canonical form
        text = GOOD_YAML + "\nlabels:\n  weird: [1000.0, 40.0, 80.0]\n"
        # actually we already define labels above; build a new file
        text2 = """
schema_version: "0.7"
labels:
  weird: [1000.0, 40.0, 80.0]
"""
        path = self._write_tmp(text2)
        try:
            rules = load_rules(path)
            self.assertEqual(rules.label_to_sig()["weird"], (40.0, 80.0, 1000.0))
        finally:
            os.unlink(path)

    def test_unknown_schema_version_rejected(self):
        bad = 'schema_version: "0.5"\n'
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_rules(path)
        finally:
            os.unlink(path)

    def test_v06_schema_version_rejected_with_migration_hint(self):
        bad = 'schema_version: "0.6"\n'
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError) as cm:
                load_rules(path)
            msg = str(cm.exception)
            self.assertIn("Migration", msg)
            self.assertIn("0.7", msg)
        finally:
            os.unlink(path)

    def test_extra_top_level_field_rejected(self):
        bad = """
schema_version: "0.7"
not_a_real_section: foo
"""
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_rules(path)
        finally:
            os.unlink(path)

    def test_bad_label_signature_shape_rejected(self):
        bad = """
schema_version: "0.7"
labels:
  cbeam: [40.0, 80.0]
"""
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_rules(path)
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_rules("/nonexistent/path/cadclaw.yaml")

    def test_empty_yaml_loads_with_defaults(self):
        path = self._write_tmp("")
        try:
            rules = load_rules(path)
            self.assertEqual(rules.schema_version, SCHEMA_VERSION)
            self.assertEqual(rules.labels, {})
            self.assertEqual(rules.bom_audit.rules, [])
        finally:
            os.unlink(path)

    def test_dump_round_trip(self):
        path = self._write_tmp(GOOD_YAML)
        out = self._write_tmp("")
        try:
            rules = load_rules(path)
            dump_rules(rules, out)
            rules2 = load_rules(out)
            self.assertEqual(rules2.meta.project, rules.meta.project)
            self.assertEqual(rules2.expected_inventory, rules.expected_inventory)
        finally:
            os.unlink(path)
            os.unlink(out)


class TestBomRuleModel(unittest.TestCase):
    def test_string_id_allowed(self):
        rule = BomRuleModel(id="frame-001", expected_qty=12)
        self.assertEqual(rule.id, "frame-001")

    def test_int_id_allowed(self):
        rule = BomRuleModel(id=5, expected_qty=12)
        self.assertEqual(rule.id, 5)

    def test_extra_field_rejected(self):
        with self.assertRaises(ValidationError):
            BomRuleModel(id=5, not_a_field="x")


if __name__ == "__main__":
    unittest.main()
