"""Tests for cadclaw/rules.py — pydantic schema, YAML round-trip."""
import os
import tempfile
import unittest

from pydantic import ValidationError

from cadclaw.rules import (
    BomRuleModel,
    InterferenceModel,
    LabelSpec,
    RuleSet,
    SCHEMA_VERSION,
    dump_rules,
    load_rules,
)


GOOD_YAML = """
schema_version: "0.9"
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
            self.assertEqual(rules.schema_version, "0.9")
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

    def test_m3_bom_audit_rules_load(self):
        rules = load_rules("examples/m3_crete/m3_bom_audit.yaml")
        self.assertIn("cbeam_4080_1000", rules.labels)
        self.assertIn("vslot_2080_1000", rules.labels)
        self.assertIn("vslot_2040_1000", rules.labels)
        self.assertIn("zpmm_motor_mount_spacer", rules.labels)
        self.assertIn("flat_frame_spacer_6mm", rules.labels)
        self.assertIn("solid_v_wheel_standard", rules.labels)
        self.assertEqual(len(rules.bom_audit.rules), 8)
        by_id = {rule.id: rule for rule in rules.bom_audit.rules}
        self.assertEqual(by_id[17].expected_label, "solid_v_wheel_standard")
        self.assertEqual(by_id[17].expected_design_qty, 32)
        self.assertEqual(by_id[67].expected_design_qty, 14)
        self.assertEqual(by_id[67].spare_qty, 1)
        self.assertEqual(by_id[84].expected_design_qty, 4)
        self.assertEqual(by_id[75].expected_label, "zpmm_motor_mount_spacer")
        self.assertEqual(by_id[79].expected_label, "flat_frame_spacer_6mm")
        self.assertEqual(by_id[86].expected_label, "vslot_2080_1000")
        self.assertEqual(by_id[87].expected_label, "vslot_2040_1000")
        self.assertEqual(by_id[87].expected_design_qty, 3)

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
schema_version: "0.9"
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
            self.assertIn("0.9", msg)
        finally:
            os.unlink(path)

    def test_v07_schema_version_rejected_with_migration_hint(self):
        """v0.9 schema bump: v0.7 yamls must carry a clear migration message."""
        bad = 'schema_version: "0.7"\n'
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError) as cm:
                load_rules(path)
            msg = str(cm.exception)
            self.assertIn("0.9", msg)
            self.assertIn("expected_face", msg)
        finally:
            os.unlink(path)

    def test_extra_top_level_field_rejected(self):
        bad = """
schema_version: "0.9"
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
schema_version: "0.9"
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


class TestLabelSpec(unittest.TestCase):
    """v0.9 gate #1 schema: `labels:` accepts both 3-tuple and dict forms."""

    def _write_tmp(self, text: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(text)
            return f.name

    def test_legacy_3tuple_form_still_works(self):
        text = (
            'schema_version: "0.9"\n'
            'labels:\n'
            '  cbeam: [40.0, 80.0, 1000.0]\n'
        )
        path = self._write_tmp(text)
        try:
            rules = load_rules(path)
            self.assertEqual(rules.labels["cbeam"].sig, [40.0, 80.0, 1000.0])
            self.assertIsNone(rules.labels["cbeam"].expected_face)
        finally:
            os.unlink(path)

    def test_dict_form_with_expected_face(self):
        text = (
            'schema_version: "0.9"\n'
            'labels:\n'
            '  idler_bracket:\n'
            '    sig: [5.0, 30.0, 30.0]\n'
            '    expected_face: YZ\n'
            '    expected_against: cbeam\n'
            '    max_gap_mm: 0.5\n'
        )
        path = self._write_tmp(text)
        try:
            rules = load_rules(path)
            spec = rules.labels["idler_bracket"]
            self.assertEqual(spec.sig, [5.0, 30.0, 30.0])
            self.assertEqual(spec.expected_face, "YZ")
            self.assertEqual(spec.expected_against, "cbeam")
            self.assertEqual(spec.max_gap_mm, 0.5)
            # YZ → largest face normal along X (axis index 0).
            self.assertEqual(spec.thinnest_axis_index(), 0)
        finally:
            os.unlink(path)

    def test_face_aliases_canonicalized(self):
        # YX should canonicalize to XY, ZY → YZ, ZX → XZ.
        s = LabelSpec(sig=[1.0, 2.0, 3.0], expected_face="zy")
        self.assertEqual(s.expected_face, "YZ")
        s = LabelSpec(sig=[1.0, 2.0, 3.0], expected_face="yx")
        self.assertEqual(s.expected_face, "XY")

    def test_invalid_face_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            LabelSpec(sig=[1.0, 2.0, 3.0], expected_face="ABC")

    def test_label_to_sig_handles_both_forms(self):
        text = (
            'schema_version: "0.9"\n'
            'labels:\n'
            '  cbeam: [40.0, 80.0, 1000.0]\n'
            '  bracket:\n'
            '    sig: [5.0, 30.0, 30.0]\n'
            '    expected_face: YZ\n'
        )
        path = self._write_tmp(text)
        try:
            rules = load_rules(path)
            l2s = rules.label_to_sig()
            self.assertEqual(l2s["cbeam"], (40.0, 80.0, 1000.0))
            self.assertEqual(l2s["bracket"], (5.0, 30.0, 30.0))
            s2l = rules.sig_to_label()
            self.assertEqual(s2l[(40.0, 80.0, 1000.0)], "cbeam")
            self.assertEqual(s2l[(5.0, 30.0, 30.0)], "bracket")
        finally:
            os.unlink(path)

    def test_label_specs_excludes_belt_heuristic(self):
        text = (
            'schema_version: "0.9"\n'
            'labels:\n'
            '  cbeam: [40.0, 80.0, 1000.0]\n'
            'belt_heuristic: true\n'
        )
        path = self._write_tmp(text)
        try:
            rules = load_rules(path)
            specs = rules.label_specs()
            self.assertIn("cbeam", specs)
            self.assertNotIn("belt_heuristic", specs)
        finally:
            os.unlink(path)


class TestInterferenceModel(unittest.TestCase):
    """v0.7.1 Ergo-1: optional `interference:` section in cadclaw.yaml."""

    def _write_tmp(self, text: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(text)
            return f.name

    def test_defaults_when_section_omitted(self):
        path = self._write_tmp('schema_version: "0.9"\n')
        try:
            rules = load_rules(path)
            self.assertEqual(rules.interference.skip_labels, [])
            self.assertEqual(rules.interference.min_volume_mm3, 1.0)
            self.assertEqual(rules.interference.min_clearance_mm, 1.0)
        finally:
            os.unlink(path)

    def test_yaml_overrides_clearance_and_skips(self):
        text = (
            'schema_version: "0.9"\n'
            'interference:\n'
            '  skip_labels: [belt, vwheel]\n'
            '  min_clearance_mm: 0.5\n'
            '  min_volume_mm3: 2.0\n'
        )
        path = self._write_tmp(text)
        try:
            rules = load_rules(path)
            self.assertEqual(rules.interference.skip_labels, ["belt", "vwheel"])
            self.assertEqual(rules.interference.min_clearance_mm, 0.5)
            self.assertEqual(rules.interference.min_volume_mm3, 2.0)
        finally:
            os.unlink(path)

    def test_extra_field_rejected(self):
        with self.assertRaises(ValidationError):
            InterferenceModel(skip_labels=["belt"], not_a_field=True)


if __name__ == "__main__":
    unittest.main()
