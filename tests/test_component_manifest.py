import tempfile
import unittest
from pathlib import Path

from cadclaw.component_manifest import (
    SignatureSummary,
    StepInspection,
    build_component_manifest,
    iter_step_files,
    slugify,
)


class TestComponentManifest(unittest.TestCase):
    def _touch(self, root: Path, rel: str) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
        return path

    def test_slugify_stabilizes_manifest_ids(self):
        self.assertEqual(slugify("NEMA 23 / V-Slot Plate.STEP"), "nema_23_v_slot_plate_step")

    def test_iter_step_files_scopes_to_requested_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adv = self._touch(root, "Advanced/Assemblies/C-Beam Linear Actuator 500mm.step")
            self._touch(root, "Components/Plates/Motor Mount Plate Nema 23.step")
            self._touch(root, "Other/Thing.step")
            self._touch(root, "Advanced/readme.txt")

            self.assertEqual(iter_step_files(root, libraries=("Advanced",)), [adv])

    def test_build_manifest_defaults_to_authored_placement_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._touch(root, "Advanced/Assemblies/C-Beam Linear Actuator 500mm.step")
            self._touch(root, "Advanced/Plates/C-Beam Gantry Plate XLarge.STEP")
            self._touch(root, "Advanced/Linear Rail/C-Beam 1000mm.step")

            def fake_inspect(path: Path) -> StepInspection:
                if "Assemblies" in path.parts:
                    return StepInspection(
                        status="ok",
                        part_count=12,
                        signatures=[SignatureSummary(sig=(20.0, 40.0, 500.0), count=2)],
                    )
                return StepInspection(status="ok", part_count=1, signatures=[])

            manifest = build_component_manifest(
                root,
                libraries=("Advanced",),
                inspect_step=fake_inspect,
                generated_at="2026-05-15T00:00:00+00:00",
            )

            entries = {entry["display_name"]: entry for entry in manifest["components"]}
            self.assertEqual(manifest["libraries"], ["Advanced"])
            self.assertEqual(
                entries["C-Beam Linear Actuator 500mm"]["kind"],
                "macro_assembly",
            )
            self.assertEqual(
                entries["C-Beam Linear Actuator 500mm"]["generation_policy"],
                "place_authored_step_only",
            )
            self.assertEqual(
                entries["C-Beam Gantry Plate XLarge"]["generation_policy"],
                "place_authored_step_only",
            )
            self.assertEqual(
                entries["C-Beam 1000mm"]["generation_policy"],
                "stock_profile_may_be_generated_or_placed",
            )
            self.assertEqual(
                entries["C-Beam Gantry Plate XLarge"]["bom_binding"]["status"],
                "needs_user_mapping",
            )


if __name__ == "__main__":
    unittest.main()
