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
        roles = {instance.role for instance in spec.instances}
        self.assertIn("y_gantry_beam", roles)
        self.assertNotIn("y_gantry_actuator", roles)
        self.assertIn("frame_side_motor_mount_spacer_6mm", roles)
        self.assertIn("frame_side_flat_spacer_6mm", roles)
        self.assertNotIn("y_axis_spacer_6mm", roles)
        motor_mount_spacers = [
            instance for instance in spec.instances
            if instance.role == "frame_side_motor_mount_spacer_6mm"
        ]
        self.assertEqual(len(motor_mount_spacers), 4)
        for instance in motor_mount_spacers:
            self.assertEqual(instance.source_path, "ZPMM.step")
            self.assertEqual(instance.transform.scale, 1.0)
            self.assertEqual(instance.transform.source_origin_mm, [1316.785, 2283.831, 3.05])
            self.assertEqual(instance.transform.rotate_deg, [90.0, 0.0, 0.0])
        flat_spacers = [
            instance for instance in spec.instances
            if instance.role == "frame_side_flat_spacer_6mm"
        ]
        self.assertEqual(len(flat_spacers), 4)
        for instance in flat_spacers:
            self.assertEqual(
                instance.source_path,
                "examples/m3_crete/generated/M3_6mm_frame_shim_4080.step",
            )
            self.assertEqual(instance.transform.rotate_deg, [0.0, 0.0, 0.0])
        bottom_rails = [
            instance for instance in spec.instances
            if instance.role == "bottom_frame_rail_y_2080"
        ]
        self.assertEqual(len(bottom_rails), 2)
        for instance in bottom_rails:
            self.assertEqual(
                instance.source_path,
                "CAD/Components/V-Slot/V-Slot 20x80x1000 Linear Rail.step",
            )
        y_left = next(instance for instance in spec.instances if instance.id == "y_gantry_left")
        y_right = next(instance for instance in spec.instances if instance.id == "y_gantry_right")
        self.assertEqual(y_left.transform.rotate_deg, [0.0, -90.0, -90.0])
        self.assertEqual(y_right.transform.rotate_deg, [0.0, 90.0, 90.0])
        spreaders = [
            instance for instance in spec.instances
            if instance.role == "top_center_spreader_2040"
        ]
        self.assertEqual(len(spreaders), 1)
        self.assertEqual(
            spreaders[0].source_path,
            "CAD/Components/V-Slot/V-Slot 20x40x1000 Linear Rail.step",
        )
        self.assertEqual(spreaders[0].transform.rotate_deg, [90.0, 0.0, 0.0])
        self.assertEqual(spreaders[0].transform.translate_mm, [REDACTED])
        spreader_plates = [
            instance for instance in spec.instances
            if instance.role == "top_center_spreader_plate"
        ]
        self.assertEqual(len(spreader_plates), 2)
        x_plate_instances = [
            instance for instance in spec.instances
            if instance.role == "x_gantry_plate"
        ]
        self.assertEqual(len(x_plate_instances), 2)
        for instance in x_plate_instances:
            self.assertEqual(
                instance.source_path,
                "CAD/Advanced/Plates/C-Beam Gantry Plate XLarge.STEP",
            )
            self.assertEqual(instance.transform.source_origin_mm, [0.0, 0.0, 3.0])
            self.assertEqual(instance.transform.rotate_deg, [0.0, 90.0, 0.0])
        z_plate_instances = [
            instance for instance in spec.instances
            if instance.role == "z_carriage_plate"
        ]
        self.assertEqual(len(z_plate_instances), 4)
        for instance in z_plate_instances:
            self.assertEqual(
                instance.source_path,
                "CAD/Components/Plates/V-Slot Gantry Plate 20-80mm.step",
            )
            self.assertNotEqual(
                instance.component_id,
                "advanced_plates_c_beam_gantry_plate_xlarge",
            )
        wheel_instances = [
            instance for instance in spec.instances
            if instance.role == "v_wheel"
        ]
        self.assertEqual(len(wheel_instances), 24)
        for instance in wheel_instances:
            self.assertEqual(
                instance.source_path,
                "CAD/Components/Wheels/Solid V Wheel.step",
            )
        self.assertEqual(spec.validation["expected_inventory"]["v_wheel"], 24)
        vslot_stackup = spec.validation["vslot_stackup"]
        self.assertEqual(vslot_stackup["target_spacer_mm"], 6.0)
        self.assertTrue(
            any(
                handoff["id"] == "x_to_y_left"
                and handoff["plate_thickness_mm"] == 6.0
                for handoff in vslot_stackup["handoffs"]
            )
        )
        self.assertIn("hole_alignment", spec.validation["run_checks"])
        self.assertIn("wheel_alignment", spec.validation["run_checks"])
        self.assertIn("open_channel_orientation", spec.validation["run_checks"])
        self.assertIn("bbox_alignment", spec.validation["run_checks"])
        hole_alignment = spec.validation["hole_alignment"]
        self.assertTrue(
            any(
                group["id"] == "y_to_z_front_left_holes"
                and group["from_instance"] == "y_gantry_left"
                and group["to_instance"] == "z_carriage_plate_front_left"
                for group in hole_alignment["groups"]
            )
        )
        self.assertTrue(
            any(
                handoff["id"] == "y_to_z_front_left"
                and "spacer_instance" not in handoff
                and handoff["plate_gap_mm"] == 1.0
                and handoff["next_gap_mm"] == 2.0
                for handoff in vslot_stackup["handoffs"]
            )
        )
        wheel_alignment = spec.validation["wheel_alignment"]
        self.assertEqual(wheel_alignment["expected_wheels_per_plate"], 4)
        self.assertEqual(wheel_alignment["plate_face_to_wheel_inner_face_mm"], 7.0)
        self.assertEqual(wheel_alignment["eccentric_adjustment_allowance_mm"], 3.5)
        self.assertTrue(
            any(
                group["id"] == "x_left_plate_wheels"
                and group["plate_instance"] == "x_gantry_plate_left"
                and len(group["wheel_instances"]) == 4
                for group in wheel_alignment["groups"]
            )
        )
        orientation = spec.validation["open_channel_orientation"]
        self.assertTrue(
            any(
                item["id"] == "left_y_gantry_channel_inward"
                and item["expected_global_axis"] == [1.0, 0.0, 0.0]
                for item in orientation["requirements"]
            )
        )
        self.assertTrue(
            any(
                item["id"] == "right_y_gantry_channel_inward"
                and item["expected_global_axis"] == [-1.0, 0.0, 0.0]
                for item in orientation["requirements"]
            )
        )
        bbox_alignment = spec.validation["bbox_alignment"]
        self.assertTrue(
            any(
                item["id"] == "top_center_spreader_40mm_vertical"
                and item["expected_size_mm"] == 40.0
                for item in bbox_alignment["checks"]
            )
        )
        self.assertTrue(
            any(
                item["id"] == "top_center_spreader_top_flush"
                and item["reference_instance"] == "top_left_side_rail"
                and item["reference_side"] == "positive"
                for item in bbox_alignment["checks"]
            )
        )
        self.assertEqual(
            [step.id for step in spec.assembly_sequence],
            [
                "x_gantry",
                "y_gantry",
                "z_carriages",
                "z_posts",
                "frame_completion",
            ],
        )
        steps = {step.id: step for step in spec.assembly_sequence}
        self.assertIn("x_left_y_neg_lower_wheel", steps["x_gantry"].instance_ids)
        self.assertIn("z_front_left_outer_lower_wheel", steps["z_carriages"].instance_ids)


if __name__ == "__main__":
    unittest.main()
