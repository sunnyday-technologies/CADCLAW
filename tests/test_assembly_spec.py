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
            self.assertEqual(
                instance.source_path,
                "examples/m3_crete/generated/ZPMM_6p1_motor_mount_spacer_6mm_holes.step",
            )
            self.assertEqual(instance.transform.scale, 1.0)
            self.assertEqual(instance.transform.source_origin_mm, [0.0, 0.0, 0.0])
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
        # Y gantries migrated to axis-only lock (M2): X is solved off the X-to-Y
        # plate's outer face with the 1mm running gap; the kept transform supplies
        # the free axes (Y span, Z height) and rotation. The locked X is authored
        # 0.0 (ignored by the resolver).
        y_left = next(instance for instance in spec.instances if instance.id == "y_gantry_left")
        y_right = next(instance for instance in spec.instances if instance.id == "y_gantry_right")
        self.assertEqual(y_left.transform.translate_mm, [0.0, -500.0, 420.0])
        self.assertEqual(y_left.transform.rotate_deg, [-90.0, 0.0, 0.0])
        self.assertEqual(y_left.place_relative_to.lock, "axis")
        self.assertEqual(y_left.place_relative_to.ref, "x_gantry_plate_left")
        self.assertEqual(y_left.place_relative_to.parent_frame, "face_y3")
        self.assertEqual(y_left.place_relative_to.frame, "open_channel_face")
        self.assertEqual(y_left.place_relative_to.axis, "x")
        self.assertEqual(y_left.place_relative_to.side, "negative")
        self.assertEqual(y_left.place_relative_to.offset_mm, 1.0)
        self.assertEqual(y_right.transform.translate_mm, [0.0, 500.0, 420.0])
        self.assertEqual(y_right.transform.rotate_deg, [-90.0, 0.0, 180.0])
        self.assertEqual(y_right.place_relative_to.lock, "axis")
        self.assertEqual(y_right.place_relative_to.ref, "x_gantry_plate_right")
        self.assertEqual(y_right.place_relative_to.parent_frame, "face_y0")
        self.assertEqual(y_right.place_relative_to.side, "positive")
        self.assertEqual(y_right.place_relative_to.offset_mm, 1.0)
        # Z-carriage plates cascade off their gantry (axis-lock x, offset 0) so
        # the y_to_z hole_alignment survives the gantry move.
        z_plates = [i for i in spec.instances if i.role == "z_carriage_plate"]
        self.assertEqual(len(z_plates), 4)
        for instance in z_plates:
            self.assertEqual(instance.place_relative_to.lock, "axis")
            self.assertEqual(instance.place_relative_to.axis, "x")
            self.assertIn("y_gantry", instance.place_relative_to.ref)
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
        top_frame_inserts = [
            instance for instance in spec.instances
            if instance.role == "top_frame_insert_2040"
        ]
        self.assertEqual(len(top_frame_inserts), 2)
        for instance in top_frame_inserts:
            self.assertEqual(
                instance.source_path,
                "CAD/Components/V-Slot/V-Slot 20x40x1000 Linear Rail.step",
            )
            self.assertEqual(instance.transform.rotate_deg, [90.0, 0.0, 90.0])
            self.assertEqual(instance.transform.translate_mm[0], -500.0)
        x_gantry_inserts = [
            instance for instance in spec.instances
            if instance.role == "x_gantry_insert_2040"
        ]
        self.assertEqual(len(x_gantry_inserts), 1)
        self.assertEqual(x_gantry_inserts[0].transform.translate_mm, [REDACTED])
        spreader_plates = [
            instance for instance in spec.instances
            if instance.role == "top_center_spreader_plate"
        ]
        # Four spreader bracket plates: a 2-plate (6mm) stack at each end of the
        # top spanner (per Nick 2026-05-23), all on the 80mm frame datum at Z=960.
        self.assertEqual(len(spreader_plates), 4)
        for instance in spreader_plates:
            self.assertEqual(instance.transform.translate_mm[2], 960.0)
        x_plate_instances = [
            instance for instance in spec.instances
            if instance.role == "x_gantry_plate"
        ]
        self.assertEqual(len(x_plate_instances), 2)
        for instance in x_plate_instances:
            # Corrected 2026-05-22 to the small V-Slot 20-80 plate and migrated to
            # constraint placement: position is solved by the relative-placement
            # resolver from the X-beam end, so no transform is typed.
            self.assertEqual(
                instance.source_path,
                "CAD/Components/Plates/V-Slot Gantry Plate 20-80mm.step",
            )
            self.assertIsNotNone(instance.place_relative_to)
            self.assertEqual(instance.place_relative_to.axis, "x")
            self.assertEqual(instance.place_relative_to.offset_mm, 0.0)
            self.assertEqual(instance.place_relative_to.rotate_deg, [0.0, 0.0, 90.0])
            self.assertEqual(instance.transform.translate_mm, [0.0, 0.0, 0.0])
        x_plate_left = next(
            i for i in x_plate_instances if i.id == "x_gantry_plate_left"
        )
        self.assertEqual(x_plate_left.place_relative_to.ref, "x_gantry_beam_left")
        self.assertEqual(x_plate_left.place_relative_to.parent_frame, "z_end_a")
        self.assertEqual(x_plate_left.place_relative_to.frame, "face_y0")
        self.assertEqual(x_plate_left.place_relative_to.side, "negative")
        x_carriage_instances = [
            instance for instance in spec.instances
            if instance.role == "x_carriage_plate"
        ]
        self.assertEqual(len(x_carriage_instances), 2)
        for instance in x_carriage_instances:
            # Restored 2026-05-23 (Nick): the X printhead carriage uses the C-Beam
            # Gantry Plate XLarge (125x125x6mm) for the toolhead's off-axis forces,
            # intentionally diverging from the V1.0 source's 0-XLarge. rotate
            # [-90,0,0] puts the 6mm thin axis along Y; the wheels are solved on
            # the XLarge hole frames by the resolver.
            self.assertEqual(
                instance.source_path,
                "CAD/Advanced/Plates/C-Beam Gantry Plate XLarge.STEP",
            )
            self.assertEqual(instance.transform.rotate_deg, [-90.0, 0.0, 0.0])
        # XLarge is placed ONLY at the two X printhead-carriage plates; all other
        # gantry plates stay the small V-Slot 20-80.
        xlarge_ids = {
            instance.id for instance in spec.instances
            if (instance.source_path or "").endswith("C-Beam Gantry Plate XLarge.STEP")
        }
        self.assertEqual(
            xlarge_ids, {"x_carriage_plate_front", "x_carriage_plate_back"}
        )
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
        self.assertEqual(len(wheel_instances), 32)
        for instance in wheel_instances:
            self.assertEqual(
                instance.source_path,
                "CAD/Components/Wheels/Solid V Wheel.step",
            )
        self.assertEqual(spec.validation["expected_inventory"]["v_wheel"], 32)
        self.assertEqual(spec.validation["expected_inventory"]["x_carriage_plate"], 2)
        vslot_stackup = spec.validation["vslot_stackup"]
        self.assertEqual(vslot_stackup["target_spacer_mm"], 6.0)
        self.assertTrue(
            any(
                handoff["id"] == "x_to_y_left"
                and handoff["plate_thickness_mm"] == 3.0
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
        self.assertTrue(
            any(
                group["id"] == "x_carriage_front_plate_wheels"
                and group["plate_instance"] == "x_carriage_plate_front"
                and len(group["wheel_instances"]) == 4
                for group in wheel_alignment["groups"]
            )
        )
        orientation = spec.validation["open_channel_orientation"]
        self.assertTrue(
            any(
                item["id"] == "left_y_gantry_channel_inward"
                and item["local_open_axis"] == [1.0, 0.0, 0.0]
                and item["expected_global_axis"] == [1.0, 0.0, 0.0]
                for item in orientation["requirements"]
            )
        )
        self.assertTrue(
            any(
                item["id"] == "right_y_gantry_channel_inward"
                and item["local_open_axis"] == [1.0, 0.0, 0.0]
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
        self.assertTrue(
            any(
                item["id"] == "top_center_spreader_plate_front_top_offset"
                and item["expected_offset_mm"] == 4.0
                for item in bbox_alignment["checks"]
            )
        )
        self.assertTrue(
            any(
                item["id"] == "y_gantry_left_80mm_vertical"
                and item["expected_size_mm"] == 80.0
                for item in bbox_alignment["checks"]
            )
        )
        self.assertTrue(
            any(
                item["id"] == "x_gantry_left_80mm_vertical"
                and item["expected_size_mm"] == 80.0
                for item in bbox_alignment["checks"]
            )
        )
        self.assertTrue(
            any(
                item["id"] == "x_carriage_front_left_lower_wheel_on_x_slot"
                and item["reference_instance"] == "x_gantry_beam_left"
                and item["expected_offset_mm"] == 0.0
                for item in bbox_alignment["checks"]
            )
        )
        self.assertEqual(
            [step.id for step in spec.assembly_sequence],
            [
                "x_gantry",
                "x_carriage",
                "y_gantry",
                "z_carriages",
                "z_posts",
                "frame_completion",
                "drive_train",
            ],
        )
        steps = {step.id: step for step in spec.assembly_sequence}
        self.assertIn("x_gantry_insert_center_2040", steps["x_gantry"].instance_ids)
        self.assertIn("top_front_insert_2040", steps["frame_completion"].instance_ids)
        self.assertIn("x_left_y_neg_lower_wheel", steps["x_gantry"].instance_ids)
        self.assertIn("x_carriage_front_left_lower_wheel", steps["x_carriage"].instance_ids)
        self.assertIn("z_front_left_outer_lower_wheel", steps["z_carriages"].instance_ids)


    def test_accepts_place_relative_to_without_transform(self):
        spec_text = """
schema_version: assembly_spec.v0.1
meta:
  project: P
  assembly_id: r
outputs:
  step: build/out.step
  views_dir: build/views
instances:
  - id: a
    role: rail
    source_path: CAD/a.step
  - id: b
    role: plate
    source_path: CAD/b.step
    place_relative_to:
      ref: a
      parent_frame: end
      frame: inner
      axis: x
      offset_mm: 1.0
"""
        path = self._write_tmp(spec_text)
        try:
            spec = load_assembly_spec(path)
            placement = spec.instances[1].place_relative_to
            self.assertEqual(placement.ref, "a")
            self.assertEqual(placement.axis, "x")
            self.assertEqual(placement.side, "positive")
            self.assertEqual(placement.offset_mm, 1.0)
        finally:
            Path(path).unlink()

    def test_rejects_transform_with_place_relative_to(self):
        spec_text = """
schema_version: assembly_spec.v0.1
meta:
  project: P
  assembly_id: r
outputs:
  step: build/out.step
  views_dir: build/views
instances:
  - id: a
    role: rail
    source_path: CAD/a.step
  - id: b
    role: plate
    source_path: CAD/b.step
    transform:
      translate_mm: [1.0, 0.0, 0.0]
    place_relative_to:
      ref: a
      parent_frame: end
      frame: inner
      axis: x
"""
        path = self._write_tmp(spec_text)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_rejects_place_relative_to_bad_axis(self):
        spec_text = """
schema_version: assembly_spec.v0.1
meta:
  project: P
  assembly_id: r
outputs:
  step: build/out.step
  views_dir: build/views
instances:
  - id: a
    role: rail
    source_path: CAD/a.step
  - id: b
    role: plate
    source_path: CAD/b.step
    place_relative_to:
      ref: a
      parent_frame: end
      frame: inner
      axis: w
"""
        path = self._write_tmp(spec_text)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_axis_lock_allows_coexisting_transform(self):
        # lock=axis keeps the instance transform (orientation + free axes); the
        # resolver overrides only the handoff axis, so a transform is allowed.
        spec_text = """
schema_version: assembly_spec.v0.1
meta:
  project: P
  assembly_id: r
outputs:
  step: build/out.step
  views_dir: build/views
instances:
  - id: a
    role: rail
    source_path: CAD/a.step
  - id: b
    role: y_gantry_beam
    source_path: CAD/b.step
    transform:
      translate_mm: [0.0, -500.0, 420.0]
      rotate_deg: [-90.0, 0.0, 0.0]
    place_relative_to:
      ref: a
      parent_frame: end
      frame: face
      axis: x
      side: negative
      offset_mm: 1.0
      lock: axis
"""
        path = self._write_tmp(spec_text)
        try:
            spec = load_assembly_spec(path)
            instance = spec.instances[1]
            self.assertEqual(instance.place_relative_to.lock, "axis")
            self.assertEqual(instance.transform.translate_mm, [0.0, -500.0, 420.0])
            self.assertEqual(instance.transform.rotate_deg, [-90.0, 0.0, 0.0])
        finally:
            Path(path).unlink()

    def test_axis_lock_rejects_orientation_on_placement(self):
        # In lock=axis mode orientation lives in the transform; setting it on the
        # placement block too is ambiguous and rejected.
        spec_text = """
schema_version: assembly_spec.v0.1
meta:
  project: P
  assembly_id: r
outputs:
  step: build/out.step
  views_dir: build/views
instances:
  - id: a
    role: rail
    source_path: CAD/a.step
  - id: b
    role: y_gantry_beam
    source_path: CAD/b.step
    transform:
      rotate_deg: [-90.0, 0.0, 0.0]
    place_relative_to:
      ref: a
      parent_frame: end
      frame: face
      axis: x
      lock: axis
      rotate_deg: [0.0, 0.0, 90.0]
"""
        path = self._write_tmp(spec_text)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()

    def test_rejects_unknown_lock_mode(self):
        spec_text = """
schema_version: assembly_spec.v0.1
meta:
  project: P
  assembly_id: r
outputs:
  step: build/out.step
  views_dir: build/views
instances:
  - id: a
    role: rail
    source_path: CAD/a.step
  - id: b
    role: plate
    source_path: CAD/b.step
    place_relative_to:
      ref: a
      parent_frame: end
      frame: inner
      axis: x
      lock: wobble
"""
        path = self._write_tmp(spec_text)
        try:
            with self.assertRaises(ValidationError):
                load_assembly_spec(path)
        finally:
            Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
