import tempfile
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError

from cadclaw.connector_metadata import (
    CONNECTOR_METADATA_VERSION,
    ConnectorMetadata,
    dump_connector_metadata,
    load_connector_metadata,
)


GOOD_METADATA = """
schema_version: connector_metadata.v0.1
assumptions:
  - Local frames are draft placement aids.
components:
  - id: cbeam_1000
    source_path: CAD/Advanced/Linear Rail/C-Beam 40x80x1000 Linear Rail.step
    frames:
      - id: negative_x_end
        kind: extrusion_end
        origin_mm: [-500, 0, 0]
        x_axis: [-1, 0, 0]
      - id: positive_x_end
        kind: extrusion_end
        origin_mm: [500, 0, 0]
mates:
  - id: splice_a
    kind: align
    from_instance: rail_a
    from_frame: positive_x_end
    to_instance: rail_b
    to_frame: negative_x_end
    offset_mm: [0, 0, 0]
"""


class TestConnectorMetadata(unittest.TestCase):
    def _write_tmp(self, text: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(text)
            return f.name

    def test_load_good_metadata(self):
        path = self._write_tmp(GOOD_METADATA)
        try:
            metadata = load_connector_metadata(path)
            self.assertEqual(metadata.schema_version, CONNECTOR_METADATA_VERSION)
            self.assertEqual(metadata.components[0].frames[0].origin_mm, [-500.0, 0.0, 0.0])
            self.assertIn("cbeam_1000", metadata.component_keys())
            self.assertIn(
                "CAD/Advanced/Linear Rail/C-Beam 40x80x1000 Linear Rail.step",
                metadata.component_keys(),
            )
        finally:
            Path(path).unlink()

    def test_dump_round_trips(self):
        metadata = ConnectorMetadata.model_validate(yaml.safe_load(GOOD_METADATA))
        dumped = dump_connector_metadata(metadata)
        loaded = ConnectorMetadata.model_validate(yaml.safe_load(dumped))
        self.assertEqual(loaded.mates[0].kind, "align")

    def test_rejects_duplicate_component_ids(self):
        bad = GOOD_METADATA.replace(
            "mates:",
            "  - id: cbeam_1000\n    source_path: CAD/Other.step\nmates:",
        )
        with self.assertRaises(ValidationError):
            ConnectorMetadata.model_validate(yaml.safe_load(bad))

    def test_rejects_duplicate_frame_ids(self):
        bad = GOOD_METADATA.replace(
            "      - id: positive_x_end",
            "      - id: negative_x_end",
        )
        with self.assertRaises(ValidationError):
            ConnectorMetadata.model_validate(yaml.safe_load(bad))

    def test_rejects_unknown_frame_kind(self):
        bad = GOOD_METADATA.replace("kind: extrusion_end", "kind: magic_snap", 1)
        with self.assertRaises(ValidationError):
            ConnectorMetadata.model_validate(yaml.safe_load(bad))

    def test_rejects_bad_vector(self):
        bad = GOOD_METADATA.replace("origin_mm: [-500, 0, 0]", "origin_mm: [-500, 0]")
        with self.assertRaises(ValidationError):
            ConnectorMetadata.model_validate(yaml.safe_load(bad))

    def test_m3_connector_seed_loads(self):
        metadata = load_connector_metadata("examples/m3_crete/m3_connector_metadata.yaml")
        self.assertGreaterEqual(len(metadata.components), 6)
        self.assertTrue(any(c.id == "cbeam_40x80_1000" for c in metadata.components))
        self.assertFalse(any(c.id == "cbeam_linear_actuator_1000" for c in metadata.components))
        self.assertFalse(any(c.id == "m3_frame_shim_4080_6mm" for c in metadata.components))
        # Restored 2026-05-23: XLarge is back for the X printhead-carriage plates
        # (Nick's off-axis-force requirement), so its connector frames are present.
        xlarge = next(c for c in metadata.components if c.id == "cbeam_gantry_plate_xlarge")
        self.assertEqual(
            xlarge.source_path,
            "CAD/Advanced/Plates/C-Beam Gantry Plate XLarge.STEP",
        )
        wheel = next(c for c in metadata.components if c.id == "solid_v_wheel_standard")
        self.assertEqual(wheel.source_path, "CAD/Components/Wheels/Solid V Wheel.step")
        self.assertFalse(any(c.id == "vslot_2080_1200" for c in metadata.components))
        active_2080 = next(c for c in metadata.components if c.id == "vslot_2080_1000")
        self.assertEqual(
            active_2080.source_path,
            "CAD/Components/V-Slot/V-Slot 20x80x1000 Linear Rail.step",
        )
        active_2040 = next(c for c in metadata.components if c.id == "vslot_2040_1000")
        self.assertEqual(
            active_2040.source_path,
            "CAD/Components/V-Slot/V-Slot 20x40x1000 Linear Rail.step",
        )
        zpmm = next(c for c in metadata.components if c.id == "zpmm_motor_mount_spacer")
        self.assertEqual(
            zpmm.source_path,
            "examples/m3_crete/generated/ZPMM_6p1_motor_mount_spacer_6mm_holes.step",
        )
        zpmm_tags = {tag for frame in zpmm.frames for tag in frame.tags}
        self.assertIn("derived_from_authored_step", zpmm_tags)
        self.assertIn("native_mm_scale", zpmm_tags)
        flat_spacer = next(c for c in metadata.components if c.id == "m3_flat_frame_spacer_6mm")
        self.assertEqual(
            flat_spacer.source_path,
            "examples/m3_crete/generated/M3_6mm_frame_shim_4080.step",
        )


if __name__ == "__main__":
    unittest.main()
