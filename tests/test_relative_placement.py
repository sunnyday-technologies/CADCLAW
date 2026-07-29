"""Tests for the constraint-based placement resolver.

`place_relative_to` is the datum-chain alternative to hand-typed coordinates:
an instance seats its own connector frame against a parent's frame, offset
along one axis. These tests pin the solved transforms and the failure findings.
"""
import tempfile
import unittest
from pathlib import Path

from cadclaw.assembly_compiler import resolve_relative_placements
from cadclaw.assembly_spec import load_assembly_spec


CONNECTORS = """
schema_version: connector_metadata.v0.1
components:
  - id: rail
    source_path: CAD/rail.step
    frames:
      - id: end_a
        kind: extrusion_end
        origin_mm: [-500, 0, 0]
      - id: top
        kind: mount_face
        origin_mm: [0, 0, 20]
  - id: plate
    source_path: CAD/plate.step
    frames:
      - id: mount
        kind: mount_face
        origin_mm: [0, 5, 0]
      - id: origin
        kind: reference
        origin_mm: [0, 0, 0]
"""


class TestRelativePlacement(unittest.TestCase):
    def _project(self, tmp: str, instances: str) -> Path:
        """Write a minimal spec with two authored components and return its path."""
        root = Path(tmp)
        cad = root / "CAD"
        cad.mkdir(parents=True, exist_ok=True)
        (cad / "rail.step").write_text("placeholder", encoding="utf-8")
        (cad / "plate.step").write_text("placeholder", encoding="utf-8")
        (root / "connectors.yaml").write_text(CONNECTORS, encoding="utf-8")

        spec = root / "spec.yaml"
        spec.write_text(f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: relative_round
connector_metadata: connectors.yaml
component_roots:
  - {root.as_posix()}
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
{instances}
""", encoding="utf-8")
        return spec

    def _resolve(self, tmp: str, instances: str):
        spec_path = self._project(tmp, instances)
        spec = load_assembly_spec(spec_path)
        return resolve_relative_placements(spec, spec_path)

    @staticmethod
    def _by_id(spec):
        return {instance.id: instance for instance in spec.instances}

    # --- frame lock (full 3-axis seat) ---------------------------------

    def test_frame_lock_seats_child_frame_on_parent_frame_with_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved, findings = self._resolve(tmp, """
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: rail_a
      parent_frame: end_a
      frame: mount
      axis: x
      offset_mm: 10.0
""")
            self.assertEqual(findings, [])
            plate = self._by_id(resolved)["plate_a"]
            # parent frame end_a sits at x=-500; +10 offset puts the seat at
            # x=-490, and the child's own frame is 5mm up its local +Y.
            self.assertEqual(list(plate.transform.translate_mm), [-490.0, -5.0, 0.0])
            # the constraint is consumed once solved
            self.assertIsNone(plate.place_relative_to)

    def test_frame_lock_negative_side_offsets_the_other_way(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved, findings = self._resolve(tmp, """
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: rail_a
      parent_frame: end_a
      frame: origin
      axis: x
      side: negative
      offset_mm: 10.0
""")
            self.assertEqual(findings, [])
            plate = self._by_id(resolved)["plate_a"]
            self.assertEqual(list(plate.transform.translate_mm), [-510.0, 0.0, 0.0])

    def test_parent_transform_composes_into_the_datum(self):
        """A relative child follows its parent's absolute transform."""
        with tempfile.TemporaryDirectory() as tmp:
            resolved, findings = self._resolve(tmp, """
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
    transform:
      translate_mm: [0.0, 0.0, 100.0]
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: rail_a
      parent_frame: end_a
      frame: origin
      axis: x
      offset_mm: 0.0
""")
            self.assertEqual(findings, [])
            plate = self._by_id(resolved)["plate_a"]
            self.assertEqual(list(plate.transform.translate_mm), [-500.0, 0.0, 100.0])

    # --- axis lock (solve only the handoff axis) -----------------------

    def test_axis_lock_solves_only_the_handoff_axis(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved, findings = self._resolve(tmp, """
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    transform:
      translate_mm: [100.0, 250.0, 7.0]
      rotate_deg: [-90.0, 0.0, 0.0]
    place_relative_to:
      ref: rail_a
      parent_frame: top
      frame: origin
      axis: z
      offset_mm: 5.0
      lock: axis
""")
            self.assertEqual(findings, [])
            plate = self._by_id(resolved)["plate_a"]
            # X and Y keep their authored values; only Z is solved
            # (parent top frame z=20, +5 offset -> 25).
            self.assertEqual(list(plate.transform.translate_mm), [100.0, 250.0, 25.0])
            # orientation stays with the instance transform
            self.assertEqual(list(plate.transform.rotate_deg), [-90.0, 0.0, 0.0])

    # --- chains and pass-through ---------------------------------------

    def test_chain_resolves_in_topological_order_not_file_order(self):
        """c depends on b, b depends on a, but c is declared first."""
        with tempfile.TemporaryDirectory() as tmp:
            resolved, findings = self._resolve(tmp, """
  - id: plate_c
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: plate_b
      parent_frame: origin
      frame: origin
      axis: x
      offset_mm: 10.0
  - id: plate_b
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: rail_a
      parent_frame: end_a
      frame: origin
      axis: x
      offset_mm: 10.0
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
""")
            self.assertEqual(findings, [])
            by_id = self._by_id(resolved)
            self.assertEqual(list(by_id["plate_b"].transform.translate_mm), [-490.0, 0.0, 0.0])
            self.assertEqual(list(by_id["plate_c"].transform.translate_mm), [-480.0, 0.0, 0.0])
            # declaration order is preserved in the resolved spec
            self.assertEqual([i.id for i in resolved.instances],
                             ["plate_c", "plate_b", "rail_a"])

    def test_absolute_transforms_pass_through_untouched(self):
        """Migration to constraint placement is incremental."""
        with tempfile.TemporaryDirectory() as tmp:
            resolved, findings = self._resolve(tmp, """
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
    transform:
      translate_mm: [1.0, 2.0, 3.0]
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    transform:
      translate_mm: [4.0, 5.0, 6.0]
""")
            self.assertEqual(findings, [])
            by_id = self._by_id(resolved)
            self.assertEqual(list(by_id["rail_a"].transform.translate_mm), [1.0, 2.0, 3.0])
            self.assertEqual(list(by_id["plate_a"].transform.translate_mm), [4.0, 5.0, 6.0])

    # --- failure findings ----------------------------------------------

    def _finding_ids(self, findings):
        return [f.id for f in findings]

    def test_unknown_ref_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, findings = self._resolve(tmp, """
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: does_not_exist
      parent_frame: end_a
      frame: origin
      axis: x
""")
            self.assertIn("assemble.relative_placement_ref_missing",
                          self._finding_ids(findings))

    def test_dependency_cycle_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, findings = self._resolve(tmp, """
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: plate_b
      parent_frame: origin
      frame: origin
      axis: x
  - id: plate_b
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: plate_a
      parent_frame: origin
      frame: origin
      axis: x
""")
            self.assertIn("assemble.relative_placement_cycle",
                          self._finding_ids(findings))

    def test_missing_parent_frame_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, findings = self._resolve(tmp, """
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: rail_a
      parent_frame: no_such_frame
      frame: origin
      axis: x
""")
            self.assertIn("assemble.relative_placement_parent_frame_missing",
                          self._finding_ids(findings))

    def test_missing_child_frame_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, findings = self._resolve(tmp, """
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
  - id: plate_a
    role: plate
    source_path: CAD/plate.step
    place_relative_to:
      ref: rail_a
      parent_frame: end_a
      frame: no_such_frame
      axis: x
""")
            self.assertIn("assemble.relative_placement_frame_missing",
                          self._finding_ids(findings))

    def test_specs_without_relative_placement_are_returned_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = self._project(tmp, """
  - id: rail_a
    role: rail
    source_path: CAD/rail.step
""")
            spec = load_assembly_spec(spec_path)
            resolved, findings = resolve_relative_placements(spec, spec_path)
            self.assertEqual(findings, [])
            self.assertIs(resolved, spec)


if __name__ == "__main__":
    unittest.main()
