import json
import tempfile
import unittest
from pathlib import Path

from cadclaw.assembly_compiler import plan_assembly_build, run_assembly_build


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


if __name__ == "__main__":
    unittest.main()
