import json
import tempfile
import unittest
from pathlib import Path

from cadclaw.assembly_compiler import (
    _apply_transform,
    inspect_component,
    plan_assembly_build,
    render_review_views,
    run_assembly_build,
    run_assembly_check_round,
    run_assembly_sequence,
)
from cadclaw.assembly_spec import Transform


class TestAssemblyCompiler(unittest.TestCase):
    def _touch(self, root: Path, rel: str) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
        return path

    def _write(self, root: Path, rel: str, text: str) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _export_box_step(self, path: Path, size: float = 10.0, dims=None) -> Path:
        import cadquery as cq

        path.parent.mkdir(parents=True, exist_ok=True)
        if dims is None:
            dims = (size, size, size)
        box = cq.Workplane("XY").box(*dims)
        cq.exporters.export(box, str(path))
        return path

    def _export_y_hole_plate_step(
        self,
        path: Path,
        points=None,
        dims=(40.0, 3.0, 40.0),
        hole_diameter: float = 5.0,
    ) -> Path:
        import cadquery as cq

        path.parent.mkdir(parents=True, exist_ok=True)
        points = points or [(-10.0, -10.0), (10.0, 10.0)]
        plate = (
            cq.Workplane("XY")
            .box(*dims)
            .faces(">Y")
            .workplane()
            .pushPoints(points)
            .hole(hole_diameter)
        )
        cq.exporters.export(plate, str(path))
        return path

    def test_transform_supports_explicit_scale_and_source_origin(self):
        import cadquery as cq

        source = cq.Workplane("XY").box(10, 20, 30).translate((5, 10, 15))
        transform = Transform.model_validate({
            "translate_mm": [100.0, 200.0, 300.0],
            "rotate_deg": [90.0, 0.0, 0.0],
            "scale": 0.1,
            "source_origin_mm": [5.0, 10.0, 15.0],
        })

        placed = _apply_transform(source, transform).val()
        bb = placed.BoundingBox()
        self.assertAlmostEqual(bb.xlen, 1.0, places=6)
        self.assertAlmostEqual(bb.ylen, 3.0, places=6)
        self.assertAlmostEqual(bb.zlen, 2.0, places=6)
        self.assertAlmostEqual((bb.xmin + bb.xmax) / 2.0, 100.0, places=6)
        self.assertAlmostEqual((bb.ymin + bb.ymax) / 2.0, 200.0, places=6)
        self.assertAlmostEqual((bb.zmin + bb.zmax) / 2.0, 300.0, places=6)

    def test_plan_resolves_direct_and_manifest_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cad_root = root / "CADRoot" / "CAD"
            self._touch(cad_root.parent, "CAD/Advanced/Linear Rail/Test Rail.step")

            manifest = self._write(root, "manifest.yaml", """
schema_version: m3_component_manifest.v0.1
components:
  - id: test_plate
    source_path: CAD/Components/Plates/Test Plate.step
""")
            self._touch(cad_root.parent, "CAD/Components/Plates/Test Plate.step")

            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
manifests:
  - {manifest.as_posix()}
component_roots:
  - {cad_root.as_posix()}
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
  design_inventory: {root.as_posix()}/build/inventory.json
instances:
  - id: rail_a
    role: rail
    source_path: CAD/Advanced/Linear Rail/Test Rail.step
  - id: plate_a
    role: plate
    component_id: test_plate
""")

            plan = plan_assembly_build(spec, dry_run=True)
            self.assertEqual(len(plan.instances), 2)
            self.assertTrue(all(instance.exists for instance in plan.instances))
            self.assertTrue(plan.instances[1].resolved_path.endswith("Test Plate.step"))

    def test_run_dry_run_with_connector_metadata_writes_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cad_root = root / "CADRoot" / "CAD"
            self._touch(cad_root.parent, "CAD/Advanced/Linear Rail/Test Rail.step")
            inventory_path = root / "build" / "inventory.json"
            metadata = self._write(root, "connectors.yaml", """
schema_version: connector_metadata.v0.1
components:
  - id: test_rail
    source_path: CAD/Advanced/Linear Rail/Test Rail.step
    frames:
      - id: end_a
        kind: extrusion_end
        origin_mm: [-500, 0, 0]
""")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
component_roots:
  - {cad_root.as_posix()}
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
  design_inventory: {inventory_path.as_posix()}
instances:
  - id: rail_a
    role: rail
    source_path: CAD/Advanced/Linear Rail/Test Rail.step
""")

            report = run_assembly_build(
                spec,
                connector_metadata_path=metadata,
                dry_run=True,
                write_inventory=True,
            )
            self.assertEqual(report.overall.value, "pass")
            self.assertEqual(report.meta["missing_sources"], 0)
            self.assertTrue(inventory_path.exists())
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            self.assertEqual(inventory["instances"][0]["connector_metadata"], "available")

    def test_missing_source_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
component_roots:
  - {root.as_posix()}/CAD
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: missing_part
    role: rail
    source_path: CAD/Advanced/Missing.step
""")

            report = run_assembly_build(spec, dry_run=True)
            self.assertEqual(report.overall.value, "fail")
            self.assertEqual(report.meta["missing_sources"], 1)
            self.assertTrue(any(f.id == "assemble.source_missing" for f in report.findings))

    def test_build_blocks_resolved_protected_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._touch(root, "CAD/Advanced/Thing.step")
            output = root / "build" / "out.step"
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
component_roots:
  - {(root / "CAD").as_posix()}
protected_paths:
  - build/out.step
outputs:
  step: {output.as_posix()}
  views_dir: {root.as_posix()}/build/views
instances:
  - id: thing
    role: test
    source_path: {source.as_posix()}
""")

            report = run_assembly_build(spec, dry_run=True)
            self.assertEqual(report.overall.value, "fail")
            self.assertTrue(
                any(f.id == "assemble.protected_output_path" for f in report.findings)
            )

    def test_build_marks_explicit_spacers_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._touch(root, "CAD/Advanced/Spacer.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: spacer_round
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: frame_spacer
    role: frame_side_spacer_6mm
    source_path: {source.as_posix()}
""")

            report = run_assembly_build(spec, dry_run=True)
            self.assertIn(
                "explicit spacer placement declarations",
                report.confidence_budget.checked,
            )
            self.assertNotIn(
                "spacer requirement inference",
                report.confidence_budget.not_checked,
            )

    def test_build_blocks_generated_source_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: generated_plate
    role: plate
    source_path: generated:nema23_plate
""")

            report = run_assembly_build(spec, dry_run=True)
            ids = {finding.id for finding in report.findings}
            self.assertIn("assemble.generated_geometry_blocked", ids)
            self.assertIn("assemble.source_missing", ids)

    def test_render_review_views_uses_declared_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            step = self._touch(root, "build/out.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {step.as_posix()}
  views_dir: {root.as_posix()}/build/views
review_views:
  - name: front-check
    view: front
    width: 320
    height: 200
instances:
  - id: thing
    role: test
    source_path: {step.as_posix()}
""")

            calls = []

            def fake_renderer(step_path, output_path, **kwargs):
                calls.append((step_path, output_path, kwargs))
                Path(output_path).write_text("png", encoding="utf-8")
                return output_path

            report = render_review_views(spec, renderer=fake_renderer)
            self.assertEqual(report.overall.value, "pass")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][2]["view"], "front")
            self.assertEqual(calls[0][2]["width"], 320)
            self.assertTrue(Path(report.meta["review_views"][0]["output_path"]).exists())

    def test_check_round_dry_run_validates_spec_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            step = self._touch(root, "CAD/Advanced/Thing.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
  design_inventory: {root.as_posix()}/build/inventory.json
validation:
  expected_inventory:
    rail: 2
instances:
  - id: thing
    role: rail
    source_path: {step.as_posix()}
""")

            report = run_assembly_check_round(spec, dry_run=True)
            self.assertEqual(report.overall.value, "fail")
            self.assertTrue(
                any(f.id == "assemble.expected_inventory_mismatch" for f in report.findings)
            )
            self.assertTrue(
                any(f.id == "assemble.review_render_skipped" for f in report.findings)
            )

    def test_check_round_runs_declared_interference_gate(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._export_box_step(root / "CAD" / "box.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [interference]
  interference:
    min_volume_mm3: 0.1
instances:
  - id: fixed_box
    role: frame
    source_path: {source.as_posix()}
  - id: clipping_box
    role: plate
    source_path: {source.as_posix()}
    transform:
      translate_mm: [5.0, 0.0, 0.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertEqual(report.overall.value, "fail")
            clip = next(f for f in report.findings if f.id == "interference.clip")
            self.assertEqual(clip.evidence["instance_a"], "fixed_box")
            self.assertEqual(clip.evidence["instance_b"], "clipping_box")
            self.assertIn("shift clipping_box", clip.suggested_fix)
            self.assertEqual(
                clip.evidence["suggest_shift"]["target_instance"],
                "clipping_box",
            )
            self.assertEqual(clip.evidence["suggest_shift"]["basis"], "role")
            self.assertIn("instance-level interference", report.confidence_budget.checked)
            self.assertNotIn("interference", report.confidence_budget.not_checked)

    def test_check_round_runs_declared_vslot_stackup_gate(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rail = self._export_box_step(
                root / "CAD" / "rail.step", dims=(100.0, 20.0, 20.0)
            )
            plate = self._export_box_step(
                root / "CAD" / "plate.step", dims=(3.0, 40.0, 40.0)
            )
            next_axis = self._export_box_step(
                root / "CAD" / "next.step", dims=(20.0, 20.0, 20.0)
            )
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [vslot_stackup]
  vslot_stackup:
    plate_thickness_mm: 3.0
    running_gap_mm: 1.0
    position_tolerance_mm: 0.25
    handoffs:
      - id: x_to_y
        current_instance: rail
        plate_instance: plate
        next_instance: next_axis
        axis: x
        side: positive
instances:
  - id: rail
    role: x_gantry_beam
    source_path: {rail.as_posix()}
  - id: plate
    role: gantry_plate
    source_path: {plate.as_posix()}
    transform:
      translate_mm: [51.5, 0.0, 0.0]
  - id: next_axis
    role: y_gantry
    source_path: {next_axis.as_posix()}
    transform:
      translate_mm: [64.0, 0.0, 0.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertFalse(
                any(f.id.startswith("vslot_stackup.") for f in report.findings)
            )
            self.assertTrue(report.meta["validation"]["vslot_stackup"]["checked"])
            self.assertIn("V-slot handoff stackup", report.confidence_budget.checked)

    def test_check_round_flags_vslot_plate_axis_misaligned(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rail = self._export_box_step(
                root / "CAD" / "rail.step", dims=(100.0, 20.0, 20.0)
            )
            plate = self._export_box_step(
                root / "CAD" / "plate.step", dims=(40.0, 3.0, 40.0)
            )
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [vslot_stackup]
  vslot_stackup:
    plate_thickness_mm: 3.0
    handoffs:
      - id: x_to_y
        current_instance: rail
        plate_instance: plate
        axis: x
        side: positive
instances:
  - id: rail
    role: x_gantry_beam
    source_path: {rail.as_posix()}
  - id: plate
    role: gantry_plate
    source_path: {plate.as_posix()}
    transform:
      translate_mm: [70.0, 0.0, 0.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertEqual(report.overall.value, "fail")
            self.assertTrue(
                any(f.id == "vslot_stackup.plate_axis_misaligned"
                    for f in report.findings)
            )

    def test_vslot_stackup_can_use_connector_frame_endpoint(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rail = self._export_box_step(
                root / "CAD" / "rail.step", dims=(100.0, 20.0, 20.0)
            )
            plate = self._export_box_step(
                root / "CAD" / "plate.step", dims=(3.0, 40.0, 40.0)
            )
            metadata = self._write(root, "connectors.yaml", f"""
schema_version: connector_metadata.v0.1
components:
  - id: rail
    source_path: {rail.as_posix()}
    frames:
      - id: working_end
        kind: extrusion_end
        origin_mm: [40.0, 0.0, 0.0]
""")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
connector_metadata: {metadata.as_posix()}
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [vslot_stackup]
  vslot_stackup:
    plate_thickness_mm: 3.0
    position_tolerance_mm: 0.25
    handoffs:
      - id: frame_endpoint_to_plate
        current_instance: rail
        current_frame: working_end
        plate_instance: plate
        axis: x
        side: positive
instances:
  - id: rail
    role: macro_actuator
    source_path: {rail.as_posix()}
  - id: plate
    role: gantry_plate
    source_path: {plate.as_posix()}
    transform:
      translate_mm: [41.5, 0.0, 0.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertFalse(
                any(f.id.startswith("vslot_stackup.") for f in report.findings)
            )

    def test_vslot_stackup_accepts_declared_plate_gap(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rail = self._export_box_step(
                root / "CAD" / "rail.step", dims=(100.0, 20.0, 20.0)
            )
            plate = self._export_box_step(
                root / "CAD" / "plate.step", dims=(3.0, 40.0, 40.0)
            )
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [vslot_stackup]
  vslot_stackup:
    plate_thickness_mm: 3.0
    position_tolerance_mm: 0.25
    handoffs:
      - id: rail_gap_to_plate
        current_instance: rail
        plate_instance: plate
        axis: x
        side: positive
        plate_gap_mm: 1.0
instances:
  - id: rail
    role: y_gantry_beam
    source_path: {rail.as_posix()}
  - id: plate
    role: z_carriage_plate
    source_path: {plate.as_posix()}
    transform:
      translate_mm: [52.5, 0.0, 0.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertFalse(
                any(f.id.startswith("vslot_stackup.") for f in report.findings)
            )

    def test_check_round_runs_declared_hole_alignment_gate(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rail = self._export_y_hole_plate_step(root / "CAD" / "rail.step")
            plate = self._export_y_hole_plate_step(root / "CAD" / "plate.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [hole_alignment]
  hole_alignment:
    max_error_mm: 0.25
    min_matches: 2
    radius_min_mm: 2.0
    radius_max_mm: 3.0
    groups:
      - id: y_to_z_mount_holes
        from_instance: y_rail
        to_instance: z_plate
        axis: y
instances:
  - id: y_rail
    role: y_gantry_beam
    source_path: {rail.as_posix()}
  - id: z_plate
    role: z_carriage_plate
    source_path: {plate.as_posix()}
    transform:
      translate_mm: [0.0, 12.0, 0.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertFalse(
                any(f.id.startswith("hole_alignment.") for f in report.findings)
            )
            self.assertTrue(report.meta["validation"]["hole_alignment"]["checked"])
            self.assertIn("authored hole alignment", report.confidence_budget.checked)

    def test_check_round_flags_hole_alignment_mismatch(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rail = self._export_y_hole_plate_step(root / "CAD" / "rail.step")
            plate = self._export_y_hole_plate_step(root / "CAD" / "plate.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [hole_alignment]
  hole_alignment:
    max_error_mm: 0.25
    min_matches: 2
    radius_min_mm: 2.0
    radius_max_mm: 3.0
    groups:
      - id: y_to_z_mount_holes
        from_instance: y_rail
        to_instance: z_plate
        axis: y
instances:
  - id: y_rail
    role: y_gantry_beam
    source_path: {rail.as_posix()}
  - id: z_plate
    role: z_carriage_plate
    source_path: {plate.as_posix()}
    transform:
      translate_mm: [2.0, 12.0, 0.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertEqual(report.overall.value, "fail")
            finding = next(
                f for f in report.findings
                if f.id == "hole_alignment.insufficient_matches"
            )
            self.assertEqual(finding.evidence["from_feature_count"], 2)
            self.assertEqual(finding.evidence["to_feature_count"], 2)
            self.assertAlmostEqual(
                finding.evidence["closest_pair"]["error_mm"],
                2.0,
                places=3,
            )

    def test_check_round_runs_open_channel_orientation_gate(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rail = self._export_box_step(root / "CAD" / "rail.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [open_channel_orientation]
  open_channel_orientation:
    angle_tolerance_deg: 1.0
    requirements:
      - id: y_left_channel_inward
        instance: y_left
        local_open_axis: [0.0, 1.0, 0.0]
        expected_global_axis: [1.0, 0.0, 0.0]
instances:
  - id: y_left
    role: y_gantry_beam
    source_path: {rail.as_posix()}
    transform:
      rotate_deg: [0.0, -90.0, -90.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertFalse(
                any(
                    f.id.startswith("open_channel_orientation.")
                    for f in report.findings
                )
            )
            self.assertTrue(
                report.meta["validation"]["open_channel_orientation"]["checked"]
            )
            self.assertIn(
                "C-Beam open-channel orientation",
                report.confidence_budget.checked,
            )

    def test_check_round_flags_open_channel_orientation_mismatch(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rail = self._export_box_step(root / "CAD" / "rail.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [open_channel_orientation]
  open_channel_orientation:
    angle_tolerance_deg: 1.0
    requirements:
      - id: y_left_channel_inward
        instance: y_left
        local_open_axis: [0.0, 1.0, 0.0]
        expected_global_axis: [1.0, 0.0, 0.0]
instances:
  - id: y_left
    role: y_gantry_beam
    source_path: {rail.as_posix()}
    transform:
      rotate_deg: [0.0, 90.0, 90.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertEqual(report.overall.value, "fail")
            finding = next(
                f for f in report.findings
                if f.id == "open_channel_orientation.channel_not_inward"
            )
            self.assertEqual(finding.evidence["instance"], "y_left")
            self.assertAlmostEqual(finding.evidence["angle_deg"], 180.0, places=3)

    def test_check_round_runs_bbox_alignment_gate(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spreader = self._export_box_step(
                root / "CAD" / "spreader.step", dims=(10.0, 100.0, 40.0)
            )
            top_rail = self._export_box_step(
                root / "CAD" / "top_rail.step", dims=(10.0, 100.0, 80.0)
            )
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [bbox_alignment]
  bbox_alignment:
    tolerance_mm: 0.1
    checks:
      - id: spreader_vertical
        instance: spreader
        axis: z
        expected_size_mm: 40.0
      - id: spreader_top_flush
        instance: spreader
        axis: z
        side: positive
        reference_instance: top_rail
        reference_side: positive
instances:
  - id: spreader
    role: spreader
    source_path: {spreader.as_posix()}
  - id: top_rail
    role: frame
    source_path: {top_rail.as_posix()}
    transform:
      translate_mm: [0.0, 0.0, -20.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertFalse(
                any(f.id.startswith("bbox_alignment.") for f in report.findings)
            )
            self.assertTrue(report.meta["validation"]["bbox_alignment"]["checked"])
            self.assertIn("bbox alignment", report.confidence_budget.checked)

    def test_check_round_flags_bbox_alignment_mismatch(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spreader = self._export_box_step(
                root / "CAD" / "spreader.step", dims=(10.0, 100.0, 20.0)
            )
            top_rail = self._export_box_step(
                root / "CAD" / "top_rail.step", dims=(10.0, 100.0, 80.0)
            )
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [bbox_alignment]
  bbox_alignment:
    tolerance_mm: 0.1
    checks:
      - id: spreader_vertical
        instance: spreader
        axis: z
        expected_size_mm: 40.0
      - id: spreader_top_flush
        instance: spreader
        axis: z
        side: positive
        reference_instance: top_rail
        reference_side: positive
instances:
  - id: spreader
    role: spreader
    source_path: {spreader.as_posix()}
  - id: top_rail
    role: frame
    source_path: {top_rail.as_posix()}
    transform:
      translate_mm: [0.0, 0.0, -20.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertEqual(report.overall.value, "fail")
            self.assertTrue(
                any(f.id == "bbox_alignment.size_mismatch" for f in report.findings)
            )
            self.assertTrue(
                any(f.id == "bbox_alignment.face_mismatch" for f in report.findings)
            )

    def test_check_round_runs_declared_frame_adjacency_gate(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            post = self._export_box_step(
                root / "CAD" / "post.step", dims=(20.0, 20.0, 100.0)
            )
            rail = self._export_box_step(
                root / "CAD" / "rail.step", dims=(50.0, 20.0, 20.0)
            )
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [frame_adjacency]
  frame_adjacency:
    gap_mm: 0.0
    position_tolerance_mm: 0.25
    min_overlap_mm: 10.0
    joints:
      - id: post_to_top_rail
        from_instance: post
        to_instance: rail
        axis: x
        side: positive
instances:
  - id: post
    role: vertical_post
    source_path: {post.as_posix()}
  - id: rail
    role: top_frame_rail_x
    source_path: {rail.as_posix()}
    transform:
      translate_mm: [35.0, 0.0, 40.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertFalse(
                any(f.id.startswith("frame_adjacency.") for f in report.findings)
            )
            self.assertTrue(report.meta["validation"]["frame_adjacency"]["checked"])
            self.assertIn("static frame adjacency", report.confidence_budget.checked)

    def test_check_round_flags_frame_adjacency_gap(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            post = self._export_box_step(
                root / "CAD" / "post.step", dims=(20.0, 20.0, 100.0)
            )
            rail = self._export_box_step(
                root / "CAD" / "rail.step", dims=(50.0, 20.0, 20.0)
            )
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [frame_adjacency]
  frame_adjacency:
    gap_mm: 0.0
    position_tolerance_mm: 0.25
    min_overlap_mm: 10.0
    joints:
      - id: post_to_top_rail
        from_instance: post
        to_instance: rail
        axis: x
        side: positive
instances:
  - id: post
    role: vertical_post
    source_path: {post.as_posix()}
  - id: rail
    role: top_frame_rail_x
    source_path: {rail.as_posix()}
    transform:
      translate_mm: [40.0, 0.0, 40.0]
""")

            report = run_assembly_check_round(
                spec,
                dry_run=False,
                render_views=False,
                write_inventory=False,
            )
            self.assertEqual(report.overall.value, "fail")
            finding = next(
                f for f in report.findings
                if f.id == "frame_adjacency.gap_out_of_range"
            )
            self.assertEqual(finding.evidence["joint"], "post_to_top_rail")
            self.assertEqual(finding.evidence["actual_gap_mm"], 5.0)

    def test_non_dry_run_exports_step_from_authored_fixture(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Path(__file__).resolve().parent / "fixtures" / "L1_good.step"
            out = root / "build" / "out.step"
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {out.as_posix()}
  views_dir: {root.as_posix()}/build/views
instances:
  - id: fixture_assembly
    role: fixture
    source_path: {fixture.as_posix()}
""")

            report = run_assembly_build(spec, dry_run=False)
            self.assertNotEqual(report.overall.value, "fail")
            self.assertTrue(out.exists())

    def test_inspect_component_reports_signatures_from_direct_source(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Path(__file__).resolve().parent / "fixtures" / "L1_good.step"
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: fixture_assembly
    role: fixture
    source_path: {fixture.as_posix()}
""")

            report = inspect_component(spec, source_path=fixture)
            self.assertEqual(report.overall.value, "pass")
            self.assertGreater(report.meta["part_count"], 0)
            self.assertTrue(report.meta["signature_histogram"])

    def test_inspect_component_resolves_manifest_component_id(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Path(__file__).resolve().parent / "fixtures" / "L1_good.step"
            manifest = self._write(root, "manifest.yaml", f"""
schema_version: m3_component_manifest.v0.1
components:
  - id: l1_fixture
    source_path: {fixture.as_posix()}
""")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
manifests:
  - {manifest.as_posix()}
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: fixture_assembly
    role: fixture
    component_id: l1_fixture
""")

            report = inspect_component(spec, component_id="l1_fixture")
            self.assertEqual(report.overall.value, "pass")
            self.assertEqual(report.meta["source_ref"], fixture.as_posix())

    def test_inspect_component_can_use_fake_renderer(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Path(__file__).resolve().parent / "fixtures" / "L1_good.step"
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: part
    role: fixture
    source_path: {fixture.as_posix()}
""")

            calls = []

            def fake_renderer(step_path, output_path, **kwargs):
                calls.append((step_path, output_path, kwargs))
                Path(output_path).write_text("png", encoding="utf-8")
                return output_path

            report = inspect_component(
                spec,
                source_path=fixture,
                render_views=True,
                views=["front"],
                renderer=fake_renderer,
            )
            self.assertEqual(report.overall.value, "pass")
            self.assertEqual(len(calls), 1)
            self.assertEqual(report.meta["rendered_views"][0]["view"], "front")

    def test_run_assembly_sequence_exports_steps_views_and_bom(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Path(__file__).resolve().parent / "fixtures" / "L1_good.step"
            out_dir = root / "build" / "sequence"
            bom = root / "build" / "bom.csv"
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
  bom: {bom.as_posix()}
bom:
  output_path: {bom.as_posix()}
instances:
  - id: x_beam
    role: x_gantry
    source_path: {fixture.as_posix()}
  - id: frame
    role: frame
    source_path: {fixture.as_posix()}
assembly_sequence:
  - id: x_gantry
    title: X Gantry
    instance_ids: [x_beam]
  - id: frame_context
    title: Frame Context
    instance_ids: [frame]
""")

            calls = []

            def fake_renderer(step_path, output_path, **kwargs):
                calls.append((step_path, output_path, kwargs))
                Path(output_path).write_text("png", encoding="utf-8")
                return output_path

            report = run_assembly_sequence(
                spec,
                output_dir=out_dir,
                view_names=["front"],
                renderer=fake_renderer,
            )
            self.assertEqual(report.overall.value, "pass")
            self.assertEqual(len(report.meta["steps"]), 2)
            self.assertEqual(report.meta["steps"][0]["validation_status"], "not_run")
            self.assertEqual(len(calls), 2)
            self.assertTrue((out_dir / "steps" / "01_x_gantry.step").exists())
            self.assertTrue((out_dir / "final" / "final_sequence_assembly.step").exists())
            self.assertTrue(report.meta["final_step"].endswith("final_sequence_assembly.step"))
            self.assertTrue((out_dir / "assembly_sequence_manifest.json").exists())
            self.assertTrue(bom.exists())
            bom_text = bom.read_text(encoding="utf-8")
            self.assertIn("quantity,role,source_ref", bom_text)
            self.assertIn("x_gantry", bom_text)

    def test_run_assembly_sequence_reports_step_interference(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._export_box_step(root / "CAD" / "box.step")
            out_dir = root / "build" / "sequence"
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [interference]
  interference:
    min_volume_mm3: 0.1
instances:
  - id: fixed_box
    role: frame
    source_path: {source.as_posix()}
  - id: clipping_box
    role: plate
    source_path: {source.as_posix()}
    transform:
      translate_mm: [5.0, 0.0, 0.0]
assembly_sequence:
  - id: frame
    title: Frame
    instance_ids: [fixed_box]
  - id: plate
    title: Plate
    instance_ids: [clipping_box]
""")

            report = run_assembly_sequence(
                spec,
                output_dir=out_dir,
                render_views=False,
            )
            self.assertEqual(report.overall.value, "fail")
            clip = next(f for f in report.findings if f.id == "interference.clip")
            self.assertEqual(clip.evidence["sequence_step"], "plate")
            self.assertIn("shift clipping_box", clip.suggested_fix)
            self.assertEqual(
                clip.evidence["suggest_shift"]["target_instance"],
                "clipping_box",
            )
            self.assertEqual(
                clip.evidence["suggest_shift"]["basis"],
                "current_step",
            )
            self.assertEqual(report.meta["steps"][0]["validation_status"], "pass")
            self.assertEqual(report.meta["steps"][1]["validation_status"], "fail")
            self.assertTrue(report.meta["steps"][1]["repair_suggestions"])
            self.assertIn(
                "sequence instance-level interference",
                report.confidence_budget.checked,
            )

    def test_run_assembly_sequence_stops_before_later_steps_on_failure(self):
        try:
            import cadquery  # noqa: F401
        except Exception as exc:
            self.skipTest(f"CadQuery unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._export_box_step(root / "CAD" / "box.step")
            out_dir = root / "build" / "sequence"
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  run_checks: [interference]
  interference:
    min_volume_mm3: 0.1
instances:
  - id: fixed_box
    role: frame
    source_path: {source.as_posix()}
  - id: clipping_box
    role: plate
    source_path: {source.as_posix()}
    transform:
      translate_mm: [5.0, 0.0, 0.0]
  - id: later_box
    role: later
    source_path: {source.as_posix()}
    transform:
      translate_mm: [50.0, 0.0, 0.0]
assembly_sequence:
  - id: frame
    title: Frame
    instance_ids: [fixed_box]
  - id: plate
    title: Plate
    instance_ids: [clipping_box]
  - id: later
    title: Later
    instance_ids: [later_box]
""")

            report = run_assembly_sequence(
                spec,
                output_dir=out_dir,
                render_views=False,
            )
            self.assertEqual(report.overall.value, "fail")
            self.assertEqual(report.meta["sequence_blocked_at"], "plate")
            self.assertEqual([step["id"] for step in report.meta["steps"]],
                             ["frame", "plate"])
            self.assertTrue(
                any(f.id == "assemble.sequence_blocked" for f in report.findings)
            )
            self.assertFalse((out_dir / "steps" / "03_later.step").exists())

    def test_run_assembly_sequence_dry_run_reports_sequence_without_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._touch(root, "CAD/Advanced/Thing.step")
            spec = self._write(root, "spec.yaml", f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: x_beam
    role: x_gantry
    source_path: {source.as_posix()}
assembly_sequence:
  - id: x_gantry
    title: X Gantry
    instance_ids: [x_beam]
""")

            report = run_assembly_sequence(spec, dry_run=True)
            self.assertEqual(report.overall.value, "warn")
            self.assertIsNone(report.meta["steps"][0]["output_step"])


if __name__ == "__main__":
    unittest.main()
