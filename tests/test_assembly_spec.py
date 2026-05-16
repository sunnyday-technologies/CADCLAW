import tempfile
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError

from cadclaw.assembly_spec import (
    ASSEMBLY_SPEC_VERSION,
    AssemblySpec,
    dump_assembly_spec,
    load_assembly_spec,
)


GOOD_SPEC = """
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
reference_assets:
  - path: example/reference.jpg
    role: visual_reference
    dimensional_evidence: false
manifests:
  - examples/example_manifest.yaml
component_roots:
  - example/CAD
protected_paths:
  - example/CAD/Authoritative.step
outputs:
  step: examples/example/build/round1.step
  views_dir: examples/example/build/views
  report: examples/example/build/report.json
bom:
  source_path: example/bom/data.json
  output_path: examples/example/build/bom.json
  private_fields_redacted: true
active_variant: Example-1
variants:
  - id: Example-1
    label: Example 1
    envelope_mm: [1000, 500, 250]
assumptions:
  - Reference image is not dimensional evidence.
constraints:
  - id: no_plate_generation
    severity: fail
    rule: Do not generate contextual plates.
instances:
  - id: rail_1
    role: frame_rail
    source_path: CAD/Advanced/Linear Rail/C-Beam 40x80x1000 Linear Rail.step
    transform:
      translate_mm: [0, 0, 0]
      rotate_deg: [0, 90, 0]
review_views:
  - name: hero_match
    view: hero
assembly_sequence:
  - id: frame_start
    title: Frame Start
    instance_ids: [rail_1]
not_built_yet:
  - item: belt paths
    reason: Explicit belt path geometry is not defined yet.
validation:
  run_checks: [inventory, interference]
"""


class TestAssemblySpec(unittest.TestCase):
    def _write_tmp(self, text: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(text)
            return f.name

    def test_load_good_spec(self):
        path = self._write_tmp(GOOD_SPEC)
        try:
            spec = load_assembly_spec(path)
            self.assertEqual(spec.schema_version, ASSEMBLY_SPEC_VERSION)
            self.assertEqual(spec.meta.project, "Example")
            self.assertEqual(spec.active_variant, "Example-1")
            self.assertEqual(spec.variants[0].envelope_mm, [1000.0, 500.0, 250.0])
            self.assertTrue(spec.bom.private_fields_redacted)
            self.assertEqual(spec.constraints[0].severity, "fail")
            self.assertEqual(spec.instances[0].transform.rotate_deg, [0.0, 90.0, 0.0])
            self.assertFalse(spec.reference_assets[0].dimensional_evidence)
            self.assertEqual(spec.assembly_sequence[0].id, "frame_start")
        finally:
            Path(path).unlink()

    def test_dump_round_trips(self):
        spec = AssemblySpec.model_validate(
            {
                "schema_version": ASSEMBLY_SPEC_VERSION,
                "meta": {"project": "Example", "assembly_id": "round1"},
                "outputs": {"step": "out.step", "views_dir": "views"},
                "instances": [
                    {
                        "id": "part",
                        "role": "test",
                        "component_id": "example_component",
                    }
                ],
            }
        )
        dumped = dump_assembly_spec(spec)
        loaded = AssemblySpec.model_validate(yaml.safe_load(dumped))
        self.assertEqual(loaded.instances[0].component_id, "example_component")

    def test_rejects_protected_output_path(self):
        bad = GOOD_SPEC.replace(
            "step: examples/example/build/round1.step",
            "step: example/CAD/Authoritative.step",
        )
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_rejects_unknown_view(self):
        bad = GOOD_SPEC.replace("view: hero", "view: three_quarter_magic")
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_rejects_instance_without_component_or_source(self):
        bad = GOOD_SPEC.replace(
            "    source_path: CAD/Advanced/Linear Rail/C-Beam 40x80x1000 Linear Rail.step\n",
            "",
        )
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_rejects_unknown_active_variant(self):
        bad = GOOD_SPEC.replace("active_variant: Example-1", "active_variant: Missing")
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_rejects_unknown_constraint_severity(self):
        bad = GOOD_SPEC.replace("severity: fail", "severity: fatal")
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_rejects_unknown_sequence_instance(self):
        bad = GOOD_SPEC.replace("instance_ids: [rail_1]", "instance_ids: [missing]")
        path = self._write_tmp(bad)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_m3_reference_spec_loads(self):
        spec = load_assembly_spec("examples/m3_crete/m3_reference_assembly.yaml")
        self.assertEqual(spec.meta.project, "M3-CRETE")
        self.assertEqual(spec.active_variant, "M3-2")
        self.assertEqual(
            {variant.id: variant.envelope_mm for variant in spec.variants}["M3-2"],
            [2000.0, 1000.0, 1000.0],
        )
        self.assertTrue(any(c.id == "no_external_x_gantry_reinforcement" for c in spec.constraints))
        self.assertGreater(len(spec.instances), 0)
        self.assertGreater(len(spec.assembly_sequence), 0)
        self.assertGreater(len(spec.not_built_yet), 0)
        self.assertNotIn("M3-2_Assembly.step", spec.outputs.step)


if __name__ == "__main__":
    unittest.main()
