"""The shipped relative-placement example must keep working.

`examples/relative_placement/` is the worked example for `place_relative_to`.
It is referenced from the README and from docs/assembly-spec.md, so it needs to
build and to solve to the documented coordinates. If these tests fail, the
example is lying to readers.

The chain under test:

    rail_x  (datum, absolute)
      └── plate    lock: frame   full 3-axis seat on the rail's +X end
            └── rail_y  lock: axis   2 mm standoff off the plate's +X face
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from cadclaw.assembly_compiler import run_assembly_build, validate_assembly_spec
from cadclaw.inventory import load_and_dedup

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "examples" / "relative_placement"
SPEC = EXAMPLE / "gantry.yaml"


def _boxes(step_path):
    """Return each part's bounding box, sorted by xmin, as plain tuples."""
    parts = load_and_dedup(str(step_path))
    boxes = []
    for part in parts:
        bb = part.BoundingBox()
        boxes.append((
            round(bb.xmin, 3), round(bb.xmax, 3),
            round(bb.ymin, 3), round(bb.ymax, 3),
            round(bb.zmin, 3), round(bb.zmax, 3),
        ))
    return sorted(boxes)


class TestShippedExampleIsValid(unittest.TestCase):
    def test_the_example_files_are_present(self):
        for name in ["gantry.yaml", "connectors.yaml", "README.md", "make_parts.py"]:
            self.assertTrue((EXAMPLE / name).exists(), f"missing {name}")
        for part in ["rail_x", "plate", "rail_y"]:
            self.assertTrue((EXAMPLE / "parts" / f"{part}.step").exists())

    def test_spec_validates(self):
        report = validate_assembly_spec(str(SPEC))
        self.assertEqual(report.overall.value, "pass")

    def test_the_example_actually_uses_relative_placement(self):
        """Guards the whole point of the example."""
        spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
        placed = [i for i in spec["instances"] if i.get("place_relative_to")]
        self.assertEqual(len(placed), 2, "expected 2 constraint-placed instances")

        locks = {i["id"]: i["place_relative_to"]["lock"] for i in placed}
        self.assertEqual(locks, {"plate": "frame", "rail_y": "axis"},
                         "example must demonstrate BOTH lock modes")

    def test_only_the_datum_carries_a_typed_position(self):
        spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
        absolute = [
            i["id"] for i in spec["instances"]
            if not i.get("place_relative_to")
        ]
        self.assertEqual(absolute, ["rail_x"])


class TestChainSolvesCorrectly(unittest.TestCase):
    """Build into a temp copy so the committed example output is untouched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name) / "relative_placement"
        shutil.copytree(EXAMPLE, self.work, ignore=shutil.ignore_patterns("build"))
        self.spec_path = self.work / "gantry.yaml"
        self._retarget(self.spec_path, self.work)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _retarget(spec_path, work):
        """Point the spec's roots and outputs at the temp copy."""
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        spec["component_roots"] = [work.as_posix()]
        spec["connector_metadata"] = (work / "connectors.yaml").as_posix()
        spec["outputs"]["step"] = (work / "build" / "gantry.step").as_posix()
        spec["outputs"]["views_dir"] = (work / "build" / "views").as_posix()
        spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
        return spec

    def _build(self):
        report = run_assembly_build(str(self.spec_path), dry_run=False)
        step = self.work / "build" / "gantry.step"
        self.assertTrue(step.exists(), "build produced no STEP")
        return report, _boxes(step)

    def test_build_passes_and_places_three_parts(self):
        report, boxes = self._build()
        self.assertNotEqual(report.overall.value, "fail")
        self.assertEqual(len(boxes), 3)

    def test_solved_coordinates_match_the_documented_values(self):
        """These are the numbers docs/assembly-spec.md tells readers to expect."""
        _, boxes = self._build()
        self.assertEqual(boxes, [
            # rail_x: the datum, exactly where it was typed
            (0.0, 600.0, 0.0, 40.0, 0.0, 40.0),
            # plate: seated flush on the rail's +X end (X 600), and self-centered
            # on the rail's mid-section in Y and Z -- all three axes solved
            (600.0, 610.0, -40.0, 80.0, -40.0, 80.0),
            # rail_y: X solved to a 2 mm standoff off the plate face at 610;
            # Y and Z stay exactly as authored in the instance transform
            (612.0, 652.0, -180.0, 220.0, 40.0, 80.0),
        ])

    def test_lengthening_the_datum_carries_the_whole_chain(self):
        """The point of a datum chain: change the datum, everything follows."""
        _, before = self._build()

        spec = yaml.safe_load(self.spec_path.read_text(encoding="utf-8"))
        # Author a longer datum rail by shifting it +100 in X. In a real project
        # this would be a new authored STEP; the propagation behavior is the same.
        for inst in spec["instances"]:
            if inst["id"] == "rail_x":
                inst["transform"]["translate_mm"] = [100.0, 0.0, 0.0]
        self.spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")

        _, after = self._build()
        # every part moved +100 in X; nothing else changed, nothing re-typed
        for old, new in zip(before, after):
            self.assertAlmostEqual(new[0], old[0] + 100.0, places=3)
            self.assertAlmostEqual(new[1], old[1] + 100.0, places=3)
            self.assertEqual(new[2:], old[2:])

    def test_thicker_plate_pushes_the_gantry_out(self):
        """A tolerance change downstream of the seat propagates, not re-typed."""
        _, before = self._build()
        gantry_x_before = before[2][0]

        # thicken the plate by moving its outboard handoff frame 5 mm further out
        conn_path = self.work / "connectors.yaml"
        conn = yaml.safe_load(conn_path.read_text(encoding="utf-8"))
        for comp in conn["components"]:
            if comp["id"] == "plate":
                for frame in comp["frames"]:
                    if frame["id"] == "face_pos_x":
                        frame["origin_mm"][0] += 5.0
        conn_path.write_text(yaml.safe_dump(conn, sort_keys=False), encoding="utf-8")

        _, after = self._build()
        self.assertAlmostEqual(after[2][0], gantry_x_before + 5.0, places=3)
        # the datum and the plate itself did not move
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[1], before[1])


if __name__ == "__main__":
    unittest.main()
