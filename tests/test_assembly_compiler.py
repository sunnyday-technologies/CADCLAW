import json
import tempfile
import unittest
from pathlib import Path

from cadclaw.assembly_compiler import (
    plan_assembly_build,
    render_review_views,
    run_assembly_build,
    run_assembly_check_round,
)


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


if __name__ == "__main__":
    unittest.main()
