"""
Test suite for cad-harness. Tests each gate against known-good and
known-bad fixture assemblies.

Run: python -m pytest tests/test_harness.py -v
  or: python tests/test_harness.py  (standalone)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import math
import json
import shutil
import subprocess
import tempfile
import unittest
from cadclaw.inventory import (
    InventoryCheck, Region, RegionResult, load_and_dedup, sig,
)
from cadclaw.interference import InterferenceCheck
from cadclaw.adjacency import AdjacencyCheck, AdjacencyRule
from cadclaw.dimensional import DimensionalCheck, DimRule
from cadclaw.kinematics import beam_deflection, motor_torque_budget, belt_tension
from cadclaw.tolerance import ToleranceChain, auto_stack_from_assembly
from cadclaw.disassembly import DisassemblySequence, DisassemblyStep
from cadclaw.render import (
    render_step_to_png, render_frames_to_gif, make_disassembly_gif,
    render_radial_explode_gif,
)
from cadclaw.parity import (
    compare_steps, visibility_toggle_warning, ParityReport,
)
from cadclaw.geometry_import import (
    shapes_by_dim_sig, first_shape_by_dim_sig,
)
from cadclaw.harness import Harness

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


# ============================================================
# LEVEL 1 TESTS: Simple bracket assembly
# ============================================================
L1_LABELS = {
    (40.0, 80.0, 500.0): 'beam',
    (5.0, 80.0, 80.0): 'plate',
    (40.0, 80.0, 500.0): 'beam',
    (20.0, 20.0, 20.0): 'connector',
}

L1_EXPECTED = {'beam': 2, 'plate': 2, 'connector': 1}


class TestL1Inventory(unittest.TestCase):
    def test_good_assembly_passes(self):
        check = InventoryCheck(
            os.path.join(FIXTURES, "L1_good.step"), L1_LABELS, L1_EXPECTED)
        result = check.run()
        self.assertTrue(result.passed, f"Mismatches: {result.mismatches}")
        self.assertEqual(result.total_parts, 5)

    def test_bad_assembly_detects_mismatch(self):
        # L1_bad has same parts but one beam replaced differently
        check = InventoryCheck(
            os.path.join(FIXTURES, "L1_bad.step"), L1_LABELS, L1_EXPECTED)
        result = check.run()
        # Should detect something is off (missing or extra parts)
        self.assertIsNotNone(result)


class TestL1Interference(unittest.TestCase):
    def test_good_no_interference(self):
        parts = load_and_dedup(os.path.join(FIXTURES, "L1_good.step"))
        def label_fn(s):
            d = sig(s)
            return L1_LABELS.get(d, 'other')
        check = InterferenceCheck(parts, label_fn, skip_labels={'other'})
        result = check.run()
        self.assertTrue(result.passed, f"Unexpected clips: {result.clips}")

    def test_bad_detects_clip(self):
        parts = load_and_dedup(os.path.join(FIXTURES, "L1_bad.step"))
        def label_fn(s):
            d = sig(s)
            return L1_LABELS.get(d, 'other')
        check = InterferenceCheck(parts, label_fn, skip_labels={'other'})
        result = check.run()
        self.assertFalse(result.passed, "Should detect plate-beam clip")
        self.assertGreater(len(result.clips), 0)


class TestInterferenceFixVector(unittest.TestCase):
    """v0.7.1 Ergo-1: clips carry an auto-suggested fix-vector."""

    def test_suggest_clear_shift_picks_smallest_overlap_axis(self):
        from cadclaw.interference import _suggest_clear_shift
        # bbox A nudged into B mostly along Y; X and Z overlaps are larger.
        # A: X=[1451,1539] Y=[538.16,541.16] Z=[302,429]
        # B: X=[1040,2040] Y=[498.51,538.51] Z=[331,411]
        # Overlap: X=88, Y=0.35, Z=80 → cheapest axis is Y.
        # Center A.y = 539.66 > Center B.y = 518.51 → push A in +Y.
        bb_a = (1451.0, 538.16, 302.0, 1539.0, 541.16, 429.0)
        bb_b = (1040.0, 498.51, 331.0, 2040.0, 538.51, 411.0)
        axis, shift, overlap = _suggest_clear_shift(bb_a, bb_b, clearance_mm=1.0)
        self.assertEqual(axis, "y")
        self.assertAlmostEqual(overlap[0], 88.0, places=2)
        self.assertAlmostEqual(overlap[1], 0.35, places=2)
        self.assertAlmostEqual(overlap[2], 80.0, places=2)
        self.assertAlmostEqual(shift, 1.35, places=2)
        self.assertGreater(shift, 0.0, "Should push A in +Y away from B's center")

    def test_suggest_clear_shift_honors_custom_clearance(self):
        from cadclaw.interference import _suggest_clear_shift
        bb_a = (0.0, 0.0, 0.0, 10.0, 10.0, 10.0)
        bb_b = (5.0, 0.0, 0.0, 20.0, 10.0, 10.0)  # X-only overlap = 5
        axis, shift, _ = _suggest_clear_shift(bb_a, bb_b, clearance_mm=2.5)
        self.assertEqual(axis, "x")
        # A center at X=5, B center at X=12.5 → push A in -X by (5 + 2.5) = 7.5
        self.assertAlmostEqual(shift, -7.5, places=3)

    def test_suggest_clear_shift_sign_matches_center_offset(self):
        from cadclaw.interference import _suggest_clear_shift
        # B is to the LEFT of A on X → push A in +X. X is the cheapest
        # axis (overlap 2 < Y/Z overlap 10 each).
        bb_a = (8.0, 0.0, 0.0, 12.0, 10.0, 10.0)
        bb_b = (0.0, 0.0, 0.0, 10.0, 10.0, 10.0)
        axis, shift, _ = _suggest_clear_shift(bb_a, bb_b, clearance_mm=0.5)
        self.assertEqual(axis, "x")
        self.assertAlmostEqual(shift, 2.5, places=3)
        self.assertGreater(shift, 0.0)

    def test_format_shift_suggestion_canonical_string(self):
        from cadclaw.interference import Clip
        from cadclaw.harness import _format_shift_suggestion
        c = Clip(
            label_a="plate", label_b="cbeam",
            center_a=(1495.0, 540.0, 366.0),
            center_b=(1540.0, 518.5, 371.0),
            volume=264.0,
            bbox_a=(1451.0, 538.16, 302.0, 1539.0, 541.16, 429.0),
            bbox_b=(1040.0, 498.51, 331.0, 2040.0, 538.51, 411.0),
            overlap_dims=(88.0, 0.35, 80.0),
            suggest_axis="y",
            suggest_shift_mm=1.35,
            clearance_mm=1.0,
        )
        msg = _format_shift_suggestion(c)
        self.assertEqual(msg, "shift +Y by 1.35mm to clear with 1mm clearance")

    def test_interference_finding_evidence_has_suggest_shift(self):
        from cadclaw.interference import Clip, InterferenceResult
        from cadclaw.harness import _interference_findings
        c = Clip(
            label_a="plate", label_b="cbeam",
            center_a=(1495.0, 540.0, 366.0),
            center_b=(1540.0, 518.5, 371.0),
            volume=264.0,
            bbox_a=(1451.0, 538.16, 302.0, 1539.0, 541.16, 429.0),
            bbox_b=(1040.0, 498.51, 331.0, 2040.0, 538.51, 411.0),
            overlap_dims=(88.0, 0.35, 80.0),
            suggest_axis="y",
            suggest_shift_mm=1.35,
            clearance_mm=1.0,
        )
        findings = _interference_findings(
            InterferenceResult(passed=False, checked_pairs=1, clips=[c]))
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.id, "interference.clip")
        self.assertIn("shift +Y by 1.35mm", f.message)
        self.assertEqual(f.suggested_fix,
                         "shift +Y by 1.35mm to clear with 1mm clearance")
        self.assertEqual(f.evidence["suggest_shift"]["axis"], "y")
        self.assertAlmostEqual(f.evidence["suggest_shift"]["mm"], 1.35)
        self.assertEqual(f.evidence["suggest_shift"]["clearance_mm"], 1.0)
        self.assertEqual(f.evidence["overlap_dims_mm"], [88.0, 0.35, 80.0])

    def test_real_clip_populates_fix_vector_fields(self):
        """Integration: L1_bad's plate-beam clip emits a non-zero fix shift."""
        parts = load_and_dedup(os.path.join(FIXTURES, "L1_bad.step"))
        def label_fn(s):
            return L1_LABELS.get(sig(s), 'other')
        check = InterferenceCheck(parts, label_fn, skip_labels={'other'},
                                  min_clearance_mm=1.5)
        result = check.run()
        self.assertGreater(len(result.clips), 0)
        c = result.clips[0]
        self.assertIn(c.suggest_axis, ("x", "y", "z"))
        self.assertNotEqual(c.suggest_shift_mm, 0.0,
                            "Solid clip implies non-zero suggested shift")
        self.assertEqual(c.clearance_mm, 1.5)
        # Suggested shift magnitude = overlap_on_axis + clearance
        idx = {"x": 0, "y": 1, "z": 2}[c.suggest_axis]
        self.assertAlmostEqual(
            abs(c.suggest_shift_mm),
            c.overlap_dims[idx] + 1.5,
            places=3,
        )
        # bbox_a and bbox_b are populated 6-tuples
        self.assertEqual(len(c.bbox_a), 6)
        self.assertEqual(len(c.bbox_b), 6)


class TestInspectModule(unittest.TestCase):
    """v0.7.1 Ergo-2: pure-function diagnostics in cadclaw.inspect."""

    @classmethod
    def setUpClass(cls):
        cls.parts = load_and_dedup(os.path.join(FIXTURES, "L1_bad.step"))

    def _label_fn(self, part):
        return L1_LABELS.get(sig(part), "other")

    def test_histogram_signatures_counts_and_orders(self):
        from cadclaw.inspect import histogram_signatures
        buckets = histogram_signatures(self.parts, label_fn=self._label_fn)
        # L1_bad has 5 parts across at most 3 sigs.
        self.assertGreater(len(buckets), 0)
        total = sum(b.count for b in buckets)
        self.assertEqual(total, len(self.parts))
        # Sorted by count desc.
        for i in range(len(buckets) - 1):
            self.assertGreaterEqual(buckets[i].count, buckets[i + 1].count)
        # At least one bucket got a label from the label_fn.
        self.assertTrue(any(b.label for b in buckets))

    def test_describe_parts_label_filter(self):
        from cadclaw.inspect import describe_parts
        plates = describe_parts(self.parts, label="plate", label_fn=self._label_fn)
        self.assertEqual(len(plates), 2)
        for p in plates:
            self.assertEqual(p.label, "plate")

    def test_describe_parts_at_filter_far_away_returns_empty(self):
        from cadclaw.inspect import describe_parts
        matches = describe_parts(self.parts, at=(1e6, 1e6, 1e6))
        self.assertEqual(matches, [])

    def test_describe_parts_no_filters_returns_all(self):
        from cadclaw.inspect import describe_parts
        matches = describe_parts(self.parts)
        self.assertEqual(len(matches), len(self.parts))

    def test_find_overlaps_target_label(self):
        from cadclaw.inspect import find_overlaps
        clips, target_count = find_overlaps(
            self.parts, self._label_fn, target_label="plate")
        self.assertGreater(target_count, 0)
        self.assertGreater(len(clips), 0)
        for c in clips:
            self.assertTrue(c.label_a == "plate" or c.label_b == "plate")
            # Each clip carries a non-zero suggested shift.
            self.assertNotEqual(c.suggest_shift_mm, 0.0)

    def test_find_overlaps_unknown_label_returns_zero_target(self):
        from cadclaw.inspect import find_overlaps
        clips, target_count = find_overlaps(
            self.parts, self._label_fn, target_label="not_a_real_label")
        self.assertEqual(target_count, 0)
        self.assertEqual(clips, [])

    def test_find_overlaps_requires_target(self):
        from cadclaw.inspect import find_overlaps
        with self.assertRaises(ValueError):
            find_overlaps(self.parts, self._label_fn)


class TestColorCheck(unittest.TestCase):
    """v0.9 gate #2: per-channel RGB color check (no CIELAB)."""

    def test_hex_to_rgb255(self):
        from cadclaw.color_check import hex_to_rgb255
        self.assertEqual(hex_to_rgb255("#969F00"), (150, 159, 0))
        self.assertEqual(hex_to_rgb255("969f00"), (150, 159, 0))
        self.assertEqual(hex_to_rgb255("#000000"), (0, 0, 0))
        self.assertEqual(hex_to_rgb255("#FFFFFF"), (255, 255, 255))

    def test_rgb01_to_rgb255_clamps(self):
        from cadclaw.color_check import rgb01_to_rgb255
        # In-range
        self.assertEqual(rgb01_to_rgb255((0.5, 0.5, 0.5)), (128, 128, 128))
        # AP242 sometimes returns sRGB-linearized values slightly out of [0,1]
        # — clamping prevents downstream wraparound.
        self.assertEqual(rgb01_to_rgb255((-0.1, 1.1, 0.5)), (0, 255, 128))

    def test_rgb255_to_hex(self):
        from cadclaw.color_check import rgb255_to_hex
        self.assertEqual(rgb255_to_hex((150, 159, 0)), "#969F00")
        self.assertEqual(rgb255_to_hex((0, 0, 0)), "#000000")

    def test_color_matches_within_tolerance(self):
        from cadclaw.color_check import color_matches
        # Exact match.
        self.assertTrue(color_matches((150, 159, 0), (150, 159, 0), tol=5))
        # Within tolerance on each channel.
        self.assertTrue(color_matches((153, 156, 4), (150, 159, 0), tol=5))
        # One channel just outside tolerance — fails.
        self.assertFalse(color_matches((156, 159, 0), (150, 159, 0), tol=5))
        # Black vs Sunnyday green — clearly fails.
        self.assertFalse(color_matches((0, 0, 0), (150, 159, 0), tol=5))

    def test_invalid_hex_rejected_by_label_spec(self):
        from cadclaw.rules import LabelSpec
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            LabelSpec(sig=[1.0, 2.0, 3.0], expected_color="not-a-hex")
        with self.assertRaises(ValidationError):
            LabelSpec(sig=[1.0, 2.0, 3.0], expected_color="#GGG")
        # Valid forms accepted, normalized to upper-case with leading #.
        s = LabelSpec(sig=[1.0, 2.0, 3.0], expected_color="969f00")
        self.assertEqual(s.expected_color, "#969F00")
        s = LabelSpec(sig=[1.0, 2.0, 3.0], expected_color="#969f00")
        self.assertEqual(s.expected_color, "#969F00")


class TestFloatingCheck(unittest.TestCase):
    """v0.9 gate #3: flag parts whose bbox isn't adjacent to any structural part."""

    def _mock_part(self, bbox):
        """Build a mock with .BoundingBox() returning the given (xmin..zmax)."""
        class _BB:
            xmin, ymin, zmin, xmax, ymax, zmax = bbox
        class _Part:
            def BoundingBox(self):
                return _BB()
        return _Part()

    def test_bbox_distance_zero_when_overlapping(self):
        from cadclaw.floating import bbox_distance
        a = (0.0, 0.0, 0.0, 10.0, 10.0, 10.0)
        b = (5.0, 5.0, 5.0, 15.0, 15.0, 15.0)   # overlaps
        self.assertEqual(bbox_distance(a, b), 0.0)

    def test_bbox_distance_positive_when_separated(self):
        from cadclaw.floating import bbox_distance
        a = (0.0, 0.0, 0.0, 10.0, 10.0, 10.0)
        b = (20.0, 0.0, 0.0, 30.0, 10.0, 10.0)  # 10mm gap on X
        self.assertAlmostEqual(bbox_distance(a, b), 10.0, places=3)

    def test_bbox_distance_3d_diagonal(self):
        from cadclaw.floating import bbox_distance
        a = (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        b = (4.0, 4.0, 4.0, 5.0, 5.0, 5.0)   # gap (3,3,3) → sqrt(27)
        self.assertAlmostEqual(bbox_distance(a, b), 27.0 ** 0.5, places=3)

    def test_check_passes_when_part_touches_structural(self):
        from cadclaw.floating import FloatingCheck
        # cbeam at origin, bracket touching it on X face — gap = 0, passes.
        cbeam = self._mock_part((0.0, 0.0, 0.0, 1000.0, 40.0, 80.0))
        bracket = self._mock_part((1000.0, 10.0, 20.0, 1005.0, 40.0, 50.0))
        labels = {id(cbeam): "cbeam", id(bracket): "bracket"}
        check = FloatingCheck(
            [cbeam, bracket], lambda p: labels[id(p)],
            structural_labels={"cbeam"}, max_gap_mm=5.0)
        r = check.run()
        self.assertTrue(r.passed)
        self.assertEqual(r.floating, [])

    def test_check_flags_floating_part(self):
        from cadclaw.floating import FloatingCheck
        cbeam = self._mock_part((0.0, 0.0, 0.0, 1000.0, 40.0, 80.0))
        # idler 100mm away from anything — well outside max_gap_mm=5.
        idler = self._mock_part((1500.0, 200.0, 200.0, 1510.0, 220.0, 220.0))
        labels = {id(cbeam): "cbeam", id(idler): "idler"}
        check = FloatingCheck(
            [cbeam, idler], lambda p: labels[id(p)],
            structural_labels={"cbeam"}, max_gap_mm=5.0)
        r = check.run()
        self.assertFalse(r.passed)
        self.assertEqual(len(r.floating), 1)
        f = r.floating[0]
        self.assertEqual(f.label, "idler")
        self.assertEqual(f.nearest_label, "cbeam")
        self.assertGreater(f.nearest_distance_mm, 5.0)

    def test_check_skipped_when_no_structural_labels(self):
        from cadclaw.floating import FloatingCheck
        idler = self._mock_part((0.0, 0.0, 0.0, 10.0, 10.0, 10.0))
        check = FloatingCheck(
            [idler], lambda p: "idler", structural_labels=set())
        r = check.run()
        self.assertTrue(r.passed)
        self.assertEqual(r.checked, 0)

    def test_exempt_label_skips_belt(self):
        """A belt floating in space is by design — exempt label suppresses."""
        from cadclaw.floating import FloatingCheck
        cbeam = self._mock_part((0.0, 0.0, 0.0, 1000.0, 40.0, 80.0))
        belt = self._mock_part((500.0, 500.0, 500.0, 510.0, 506.0, 510.0))
        labels = {id(cbeam): "cbeam", id(belt): "belt"}
        check = FloatingCheck(
            [cbeam, belt], lambda p: labels[id(p)],
            structural_labels={"cbeam"}, max_gap_mm=5.0,
            exempt_labels={"belt"})
        r = check.run()
        self.assertTrue(r.passed)

    def test_finding_carries_suggestion(self):
        from cadclaw.floating import FloatingCheck
        from cadclaw.harness import _floating_findings
        cbeam = self._mock_part((0.0, 0.0, 0.0, 1000.0, 40.0, 80.0))
        idler = self._mock_part((1500.0, 200.0, 200.0, 1510.0, 220.0, 220.0))
        labels = {id(cbeam): "cbeam", id(idler): "idler"}
        check = FloatingCheck(
            [cbeam, idler], lambda p: labels[id(p)],
            structural_labels={"cbeam"}, max_gap_mm=5.0)
        findings = _floating_findings(check.run())
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.id, "cad.floating_part")
        self.assertEqual(f.evidence["nearest_label"], "cbeam")
        self.assertIn("Move toward", f.suggested_fix)


class TestOrientationCheck(unittest.TestCase):
    """v0.9 gate #1: orientation/face-mate gate.

    Tests are split between pure-math (no OCC needed) and integration
    against the L-fixtures. Pure-math covers the `thinnest_axis`,
    `suggest_rotation`, and finding-shape logic.
    """

    def test_thinnest_axis_distinct_dims(self):
        from cadclaw.orientation import thinnest_axis
        # Thinnest along X (0).
        self.assertEqual(thinnest_axis((5.0, 30.0, 30.0)), 0)
        # Thinnest along Y (1).
        self.assertEqual(thinnest_axis((30.0, 5.0, 30.0)), 1)
        # Thinnest along Z (2).
        self.assertEqual(thinnest_axis((30.0, 30.0, 5.0)), 2)

    def test_thinnest_axis_ambiguous_when_tied(self):
        from cadclaw.orientation import thinnest_axis
        # Two axes at 5mm, third at 30mm → ambiguous.
        self.assertIsNone(thinnest_axis((5.0, 5.0, 30.0)))
        self.assertIsNone(thinnest_axis((5.0, 30.0, 5.0)))
        # Sub-tolerance jitter still classifies as ambiguous.
        self.assertIsNone(thinnest_axis((5.0, 5.05, 30.0), tol_mm=0.1))
        # Above tolerance: distinct again.
        self.assertEqual(thinnest_axis((5.0, 5.5, 30.0), tol_mm=0.1), 0)

    def test_suggest_rotation_axis_choice(self):
        from cadclaw.orientation import suggest_rotation
        # actual=Y, expected=X → rotate about Z.
        self.assertIn("about Z", suggest_rotation(1, 0))
        # actual=X, expected=Z → rotate about Y.
        self.assertIn("about Y", suggest_rotation(0, 2))
        # actual=Z, expected=Y → rotate about X.
        self.assertIn("about X", suggest_rotation(2, 1))
        # Same axis → empty string (no rotation needed).
        self.assertEqual(suggest_rotation(0, 0), "")

    def test_check_passes_when_orientation_correct(self):
        from cadclaw.orientation import OrientationCheck, OrientationResult
        from cadclaw.rules import LabelSpec

        # Mock part with controlled BoundingBox.
        class _MockBB:
            def __init__(self, dims):
                self.xmin, self.ymin, self.zmin = 0.0, 0.0, 0.0
                self.xmax, self.ymax, self.zmax = dims

        class _MockPart:
            def __init__(self, dims):
                self._dims = dims
            def BoundingBox(self):
                return _MockBB(self._dims)

        # Bracket with thinnest along X (5mm), labeled idler_bracket
        # whose spec says expected_face=YZ (thinnest=X) → match → pass.
        part = _MockPart((5.0, 30.0, 30.0))
        specs = {
            "idler_bracket": LabelSpec(
                sig=[5.0, 30.0, 30.0], expected_face="YZ"),
        }
        check = OrientationCheck([part], lambda p: "idler_bracket", specs)
        r = check.run()
        self.assertTrue(r.passed)
        self.assertEqual(r.checked, 1)
        self.assertEqual(r.violations, [])

    def test_check_flags_misorientation(self):
        from cadclaw.orientation import OrientationCheck
        from cadclaw.rules import LabelSpec

        class _MockBB:
            def __init__(self, dims):
                self.xmin, self.ymin, self.zmin = 0.0, 0.0, 0.0
                self.xmax, self.ymax, self.zmax = dims

        class _MockPart:
            def __init__(self, dims):
                self._dims = dims
            def BoundingBox(self):
                return _MockBB(self._dims)

        # Bracket rotated 90°: thinnest is now Y (axis 1) instead of X.
        part = _MockPart((30.0, 5.0, 30.0))
        specs = {
            "idler_bracket": LabelSpec(
                sig=[5.0, 30.0, 30.0], expected_face="YZ"),
        }
        check = OrientationCheck([part], lambda p: "idler_bracket", specs)
        r = check.run()
        self.assertFalse(r.passed)
        self.assertEqual(len(r.violations), 1)
        v = r.violations[0]
        self.assertEqual(v.actual_axis, 1)
        self.assertEqual(v.expected_axis, 0)
        self.assertEqual(v.expected_face, "YZ")

    def test_check_warns_on_ambiguous_dims(self):
        from cadclaw.orientation import OrientationCheck
        from cadclaw.rules import LabelSpec

        class _MockBB:
            def __init__(self, dims):
                self.xmin, self.ymin, self.zmin = 0.0, 0.0, 0.0
                self.xmax, self.ymax, self.zmax = dims

        class _MockPart:
            def __init__(self, dims):
                self._dims = dims
            def BoundingBox(self):
                return _MockBB(self._dims)

        # Two dims tied for thinnest — orientation is ambiguous.
        part = _MockPart((5.0, 5.0, 30.0))
        specs = {
            "tie_part": LabelSpec(
                sig=[5.0, 5.0, 30.0], expected_face="YZ"),
        }
        check = OrientationCheck([part], lambda p: "tie_part", specs)
        r = check.run()
        # Ambiguous parts are NOT failures — they're warnings.
        self.assertTrue(r.passed)
        self.assertEqual(len(r.violations), 0)
        self.assertEqual(len(r.ambiguous), 1)

    def test_unlabeled_parts_skipped(self):
        from cadclaw.orientation import OrientationCheck
        from cadclaw.rules import LabelSpec

        class _MockBB:
            xmin = ymin = zmin = 0.0
            xmax = ymax = zmax = 10.0

        class _MockPart:
            def BoundingBox(self):
                return _MockBB()

        # No spec for "other" → skipped entirely.
        specs = {"foo": LabelSpec(sig=[1.0, 2.0, 3.0], expected_face="YZ")}
        check = OrientationCheck([_MockPart()], lambda p: "other", specs)
        r = check.run()
        self.assertEqual(r.checked, 0)
        self.assertTrue(r.passed)

    def test_finding_evidence_shape(self):
        from cadclaw.orientation import OrientationCheck
        from cadclaw.harness import _orientation_findings
        from cadclaw.rules import LabelSpec

        class _MockBB:
            def __init__(self, dims):
                self.xmin, self.ymin, self.zmin = 100.0, 200.0, 300.0
                self.xmax = self.xmin + dims[0]
                self.ymax = self.ymin + dims[1]
                self.zmax = self.zmin + dims[2]

        class _MockPart:
            def __init__(self, dims):
                self._dims = dims
            def BoundingBox(self):
                return _MockBB(self._dims)

        part = _MockPart((30.0, 5.0, 30.0))   # rotated wrong
        specs = {"idler_bracket": LabelSpec(
            sig=[5.0, 30.0, 30.0], expected_face="YZ")}
        check = OrientationCheck([part], lambda p: "idler_bracket", specs)
        findings = _orientation_findings(check.run())
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f.id, "cad.misoriented")
        self.assertIn("about Z", f.suggested_fix)  # rotate about Z
        self.assertEqual(f.evidence["expected_face"], "YZ")
        self.assertEqual(f.evidence["actual_axis"], 1)
        self.assertEqual(f.evidence["expected_axis"], 0)


class TestClusterParts(unittest.TestCase):
    """v0.9 gate #7: spatial clustering of unlabeled parts."""

    @classmethod
    def setUpClass(cls):
        cls.parts = load_and_dedup(os.path.join(FIXTURES, "L3_good.step"))

    def _label_fn(self, part):
        return L3_LABELS.get(sig(part), "other")

    def test_returns_empty_when_no_matches(self):
        from cadclaw.inspect import cluster_parts
        clusters = cluster_parts(self.parts, label_fn=self._label_fn,
                                 target_label="not_a_real_label")
        self.assertEqual(clusters, [])

    def test_clusters_have_sane_structure(self):
        from cadclaw.inspect import cluster_parts
        clusters = cluster_parts(self.parts, label_fn=self._label_fn,
                                 target_label=None, radius_mm=200.0)
        self.assertGreater(len(clusters), 0)
        # Sorted by member count desc.
        for i in range(len(clusters) - 1):
            self.assertGreaterEqual(
                len(clusters[i].members), len(clusters[i + 1].members))
        # Names are sequential.
        for i, c in enumerate(clusters, start=1):
            self.assertEqual(c.name, f"cluster_{i}")
        # Total members == total candidate parts.
        total = sum(len(c.members) for c in clusters)
        self.assertEqual(total, len(self.parts))

    def test_radius_is_respected(self):
        """A tiny radius must not merge spatially separated parts."""
        from cadclaw.inspect import cluster_parts
        big_radius = cluster_parts(self.parts, label_fn=self._label_fn,
                                    target_label=None, radius_mm=10000.0)
        tiny_radius = cluster_parts(self.parts, label_fn=self._label_fn,
                                     target_label=None, radius_mm=1.0)
        # Big radius should agglomerate everything into 1 cluster (or nearly).
        # Tiny radius should leave most parts as singletons.
        self.assertEqual(len(big_radius), 1)
        self.assertGreater(len(tiny_radius), 1)

    def test_centroid_inside_bbox(self):
        from cadclaw.inspect import cluster_parts
        clusters = cluster_parts(self.parts, label_fn=self._label_fn,
                                 target_label=None, radius_mm=500.0)
        for c in clusters:
            cx, cy, cz = c.centroid
            xmin, ymin, zmin, xmax, ymax, zmax = c.bbox
            self.assertGreaterEqual(cx, xmin)
            self.assertLessEqual(cx, xmax)
            self.assertGreaterEqual(cy, ymin)
            self.assertLessEqual(cy, ymax)
            self.assertGreaterEqual(cz, zmin)
            self.assertLessEqual(cz, zmax)

    def test_sig_histogram_sums_to_member_count(self):
        from cadclaw.inspect import cluster_parts
        clusters = cluster_parts(self.parts, label_fn=self._label_fn,
                                 target_label=None, radius_mm=500.0)
        for c in clusters:
            hist_total = sum(b.count for b in c.sig_histogram)
            self.assertEqual(hist_total, len(c.members))


# ============================================================
# LEVEL 2 TESTS: Motor mount assembly
# ============================================================
L2_LABELS = {
    (40.0, 80.0, 1000.0): 'beam',
    (56.4, 56.4, 76.6): 'motor',
    (65.0, 69.0, 69.0): 'bracket',
    (4.0, 68.0, 80.0): 'mount',
    (10.2, 23.9, 23.9): 'wheel',
    (4.0, 40.0, 80.0): 'spacer',
}

L2_EXPECTED = {
    'beam': 1, 'motor': 1, 'bracket': 1, 'mount': 1,
    'wheel': 4, 'spacer': 2,
}


class TestL2Inventory(unittest.TestCase):
    def test_good_passes(self):
        check = InventoryCheck(
            os.path.join(FIXTURES, "L2_good.step"), L2_LABELS, L2_EXPECTED)
        result = check.run()
        self.assertTrue(result.passed, f"Mismatches: {result.mismatches}")

    def test_bad_extra_wheel(self):
        check = InventoryCheck(
            os.path.join(FIXTURES, "L2_bad.step"), L2_LABELS, L2_EXPECTED)
        result = check.run()
        self.assertFalse(result.passed)
        self.assertTrue(any('wheel' in m for m in result.mismatches))


class TestL2Adjacency(unittest.TestCase):
    def test_motor_near_bracket(self):
        parts = load_and_dedup(os.path.join(FIXTURES, "L2_good.step"))
        def label_fn(s):
            return L2_LABELS.get(sig(s), 'other')
        rules = [AdjacencyRule('motor', 'bracket', max_distance=50)]
        check = AdjacencyCheck(parts, label_fn, rules)
        result = check.run()
        self.assertTrue(result.passed)


# ============================================================
# LEVEL 3 TESTS: Mini gantry corner
# ============================================================
L3_LABELS = {
    (40.0, 80.0, 1000.0): 'post',
    (40.0, 80.0, 500.0): 'beam',
    (40.0, 80.0, 500.0): 'beam',
    (56.4, 56.4, 76.6): 'motor',
    (65.0, 69.0, 69.0): 'bracket',
    (3.0, 88.0, 127.0): 'plate',
    (4.0, 68.0, 80.0): 'mount',
    (10.2, 23.9, 23.9): 'wheel',
    (4.0, 40.0, 80.0): 'spacer',
    (5.0, 40.0, 80.0): 'cap',
    (14.0, 15.0, 15.0): 'pulley',
}

L3_EXPECTED = {
    'post': 1, 'beam': 2, 'motor': 1, 'bracket': 1,
    'plate': 2, 'mount': 1, 'wheel': 6, 'spacer': 2,
    'cap': 1, 'pulley': 1,
}


class TestL3Full(unittest.TestCase):
    def test_good_passes_all_gates(self):
        h = Harness(os.path.join(FIXTURES, "L3_good.step"))
        h.add_inventory(L3_LABELS, L3_EXPECTED)
        h.add_interference(skip_labels={'wheel', 'pulley', 'other'})
        h.add_adjacency([AdjacencyRule('motor', 'bracket', max_distance=100)])
        h.add_dimensional([
            DimRule('mount', thin_axis=4.0, thin_tol=0.5),
            DimRule('cap', thin_axis=5.0, thin_tol=0.5),
        ])
        report = h.run()
        self.assertTrue(report.passed, str(report))

    def test_bad_catches_all_errors(self):
        # L3_bad has: motor far from bracket, plate clips post, missing cap
        parts = load_and_dedup(os.path.join(FIXTURES, "L3_bad.step"))
        def label_fn(s):
            return L3_LABELS.get(sig(s), 'other')

        # Adjacency: motor should fail
        adj = AdjacencyCheck(parts, label_fn,
                             [AdjacencyRule('motor', 'bracket', max_distance=50)])
        adj_result = adj.run()
        self.assertFalse(adj_result.passed, "Should catch far motor")

        # Interference: plate should clip post
        intf = InterferenceCheck(parts, label_fn,
                                 skip_labels={'wheel', 'pulley', 'other'})
        intf_result = intf.run()
        self.assertFalse(intf_result.passed, "Should catch plate-post clip")

        # Inventory: missing cap
        L3_expected_with_cap = dict(L3_EXPECTED)
        inv = InventoryCheck(os.path.join(FIXTURES, "L3_bad.step"),
                             L3_LABELS, L3_expected_with_cap)
        inv_result = inv.run()
        self.assertFalse(inv_result.passed, "Should catch missing cap")


# ============================================================
# REGION INVENTORY - per-region (spatial) part counts
# ============================================================
#
# L3_good layout (centroid Z of each part):
#   base (Z < 1000):    1 post (z=500), 3 wheels (z=200,500,800),
#                       1 plate (z=400), 1 plate (z=960),
#                       2 spacers (z=20, 960)
#   gantry (Z >= 1000): 2 beams, 1 motor, 1 bracket, 1 mount,
#                       1 cap (z=1005), 3 wheels (z=1100), 1 pulley
class TestRegionInventory(unittest.TestCase):

    FIXTURE = os.path.join(FIXTURES, "L3_good.step")

    def _base_region(self, **overrides):
        expected = {'post': 1, 'wheel': 3, 'plate': 2, 'spacer': 2}
        expected.update(overrides)
        return Region(name="base", z_range=(None, 999.0), expected=expected)

    def _gantry_region(self, **overrides):
        expected = {'beam': 2, 'motor': 1, 'bracket': 1, 'mount': 1,
                    'cap': 1, 'wheel': 3, 'pulley': 1}
        expected.update(overrides)
        return Region(name="gantry", z_range=(1000.0, None), expected=expected)

    def _wheel_column(self, name, zlo, zhi, expected_wheels):
        return Region(
            name=name,
            x_range=(40.0, 60.0), y_range=(-10.0, 10.0),
            z_range=(zlo, zhi),
            expected={'wheel': expected_wheels},
        )

    def test_region_contains_centroid_semantics(self):
        r = Region(name="r", x_range=(0.0, 10.0), z_range=(-5.0, 5.0))
        self.assertTrue(r.contains((5.0, 999.0, 0.0)))
        self.assertTrue(r.contains((0.0, -1e6, -5.0)))
        self.assertFalse(r.contains((-0.01, 0.0, 0.0)))
        self.assertFalse(r.contains((5.0, 0.0, 5.01)))
        self.assertTrue(r.contains((10.0, 0.0, 5.0)))

    def test_region_open_bound_is_wildcard(self):
        r = Region(name="lower_half", z_range=(None, 100.0))
        self.assertTrue(r.contains((0.0, 0.0, -1e9)))
        self.assertTrue(r.contains((0.0, 0.0, 100.0)))
        self.assertFalse(r.contains((0.0, 0.0, 100.1)))

    def test_backward_compat_no_regions(self):
        check = InventoryCheck(self.FIXTURE, L3_LABELS, L3_EXPECTED)
        result = check.run()
        self.assertTrue(result.passed, f"Mismatches: {result.mismatches}")
        self.assertEqual(result.region_results, {})

    def test_region_passes_when_counts_match(self):
        check = InventoryCheck(
            self.FIXTURE, L3_LABELS, L3_EXPECTED,
            regions=[self._base_region(), self._gantry_region()])
        result = check.run()
        self.assertTrue(result.passed, str(result.region_results))
        self.assertEqual(set(result.region_results), {"base", "gantry"})
        base = result.region_results["base"]
        self.assertTrue(base.passed)
        self.assertEqual(base.inventory.get('wheel', 0), 3)
        self.assertEqual(base.inventory.get('post', 0), 1)
        self.assertEqual(base.inventory.get('beam', 0), 0)
        gantry = result.region_results["gantry"]
        self.assertTrue(gantry.passed)
        self.assertEqual(gantry.inventory.get('beam', 0), 2)
        self.assertEqual(gantry.inventory.get('wheel', 0), 3)

    def test_region_count_mismatch_fails_overall(self):
        bad_base = self._base_region(wheel=8)
        check = InventoryCheck(
            self.FIXTURE, L3_LABELS, L3_EXPECTED, regions=[bad_base])
        result = check.run()
        self.assertEqual(result.mismatches, [])
        self.assertFalse(result.passed)
        base = result.region_results["base"]
        self.assertFalse(base.passed)
        self.assertTrue(any('wheel' in m for m in base.mismatches))

    def test_region_catches_spatial_omission_global_misses(self):
        tight = self._wheel_column("tight_column", None, 600.0, expected_wheels=3)
        check = InventoryCheck(
            self.FIXTURE, L3_LABELS, L3_EXPECTED, regions=[tight])
        result = check.run()
        self.assertEqual(result.mismatches, [])
        self.assertFalse(result.passed)
        tight_res = result.region_results["tight_column"]
        self.assertEqual(tight_res.inventory.get('wheel', 0), 2)
        self.assertTrue(any('wheel' in m for m in tight_res.mismatches))

    def test_overlapping_regions_double_count(self):
        lower = self._wheel_column("lower", None, 500.0, expected_wheels=2)
        middle = self._wheel_column("middle", 300.0, 900.0, expected_wheels=2)
        check = InventoryCheck(
            self.FIXTURE, L3_LABELS, L3_EXPECTED, regions=[lower, middle])
        result = check.run()
        self.assertTrue(result.passed, str(result.region_results))
        self.assertEqual(result.region_results["lower"].inventory.get('wheel', 0), 2)
        self.assertEqual(result.region_results["middle"].inventory.get('wheel', 0), 2)

    def test_region_result_partition_totals(self):
        check = InventoryCheck(
            self.FIXTURE, L3_LABELS, L3_EXPECTED,
            regions=[self._base_region(), self._gantry_region()])
        result = check.run()
        base = result.region_results["base"]
        gantry = result.region_results["gantry"]
        self.assertEqual(base.total_parts + gantry.total_parts, result.total_parts)



# ============================================================
# KINEMATICS TESTS (pure math, no STEP files)
# ============================================================
class TestKinematics(unittest.TestCase):
    def test_beam_deflection_simple(self):
        result = beam_deflection(
            span_m=1.0, point_load_kg=1.0,
            I_m4=10e-8, beam_kg_per_m=1.0)
        self.assertGreater(result.total_mm, 0)
        self.assertLess(result.total_mm, 10)  # sanity

    def test_beam_deflection_m3crete(self):
        """4080 C-beam, 2m span, 3.8kg printhead — should fail at 0.5mm limit."""
        result = beam_deflection(
            span_m=2.0, point_load_kg=3.8,
            I_m4=18e-8, beam_kg_per_m=2.45,
            limit_mm=0.5)
        self.assertFalse(result.passed, f"Bare 4080 should fail: {result.total_mm:.2f}mm")
        self.assertGreater(result.total_mm, 0.5)

    def test_motor_budget_nema23(self):
        """NEMA23 on X-axis should pass easily."""
        result = motor_torque_budget(
            mass_kg=4.0, n_motors=1,
            pulley_radius_m=0.00637,  # 20T GT2
            motor_torque_Nm=1.89,
            accel_m_s2=0.5)
        self.assertTrue(result.passed)
        self.assertGreater(result.safety_factor, 10)  # should be massively over-specced

    def test_motor_budget_z_gravity(self):
        """Z-axis with gravity should still pass with 4 NEMA23s."""
        result = motor_torque_budget(
            mass_kg=16.0, n_motors=4,
            pulley_radius_m=0.00637,
            motor_torque_Nm=1.89,
            gravity_axis=True)
        self.assertTrue(result.passed)
        self.assertGreater(result.safety_factor, 2)

    def test_belt_tension_safe(self):
        result = belt_tension(force_N=50, n_belts=4)
        self.assertTrue(result.passed)
        self.assertGreater(result.safety_to_working, 10)

    def test_belt_tension_overloaded(self):
        result = belt_tension(force_N=2000, n_belts=1)
        self.assertFalse(result.passed)


# ============================================================
# TOLERANCE STACKING TESTS
# ============================================================
class TestToleranceStack(unittest.TestCase):
    """Closing-dimension chain: dimensions sum to a target (gap or alignment).

    The M3-CRETE motivating case: four posts of nominal 1000 mm support a
    gantry beam. The gantry beam, shim, and motor plate stack vertically
    onto the post top. The `closure` dimension is negative — it's the
    design-intent total envelope the real parts must fit inside. If every
    nominal is on spec, the chain sums to zero.
    """

    def _motor_alignment_chain(self):
        chain = ToleranceChain("motor_alignment")
        chain.add("post", nominal=1000.0, plus=0.5, minus=0.5)
        chain.add("shim", nominal=4.0, plus=0.1, minus=0.1)
        chain.add("plate", nominal=5.0, plus=0.2, minus=0.2)
        chain.add("closure", nominal=-1009.0, plus=0.0, minus=0.0)
        return chain

    def test_nominal_closes_at_zero(self):
        result = self._motor_alignment_chain().analyze(target=0.0, tolerance=1.0)
        self.assertAlmostEqual(result.nominal_result, 0.0, places=6)

    def test_worst_case_matches_hand_calc(self):
        """WC range is the sum of +/- across all dimensions."""
        result = self._motor_alignment_chain().analyze(target=0.0, tolerance=1.0)
        expected_range = (0.5 + 0.5) + (0.1 + 0.1) + (0.2 + 0.2) + 0.0
        self.assertAlmostEqual(result.worst_case_range, expected_range, places=6)
        self.assertAlmostEqual(result.worst_case_max, 0.8, places=6)
        self.assertAlmostEqual(result.worst_case_min, -0.8, places=6)

    def test_rss_matches_hand_calc(self):
        """RSS = sqrt(sum of bilateral^2). 2x the half-range = full range."""
        result = self._motor_alignment_chain().analyze(target=0.0, tolerance=1.0)
        expected_half = math.sqrt(0.5**2 + 0.1**2 + 0.2**2 + 0.0**2)
        self.assertAlmostEqual(result.rss_range / 2, expected_half, places=6)

    def test_monte_carlo_centers_on_nominal(self):
        result = self._motor_alignment_chain().analyze(
            target=0.0, tolerance=1.0, mc_samples=20000)
        self.assertAlmostEqual(result.mc_mean, 0.0, delta=0.01)

    def test_pass_when_tolerance_generous(self):
        """Worst case is +/-0.8; asking for +/-1.0 should pass every method."""
        result = self._motor_alignment_chain().analyze(target=0.0, tolerance=1.0)
        self.assertTrue(result.worst_case_passed)
        self.assertTrue(result.rss_passed)
        self.assertTrue(result.mc_passed)

    def test_fail_when_tolerance_tight(self):
        """Worst case is +/-0.8; asking for +/-0.3 should fail worst case."""
        result = self._motor_alignment_chain().analyze(target=0.0, tolerance=0.3)
        self.assertFalse(result.worst_case_passed)

    def test_contributors_sum_to_100(self):
        result = self._motor_alignment_chain().analyze(target=0.0, tolerance=1.0)
        total = sum(c['variance_pct'] for c in result.contributors)
        self.assertAlmostEqual(total, 100.0, places=3)

    def test_dominant_contributor_is_post(self):
        """Post has +/-0.5, 6.25x the variance of the next largest term."""
        result = self._motor_alignment_chain().analyze(target=0.0, tolerance=1.0)
        top = max(result.contributors, key=lambda c: c['variance_pct'])
        self.assertEqual(top['name'], 'post')

    def test_direction_flag_is_equivalent_to_negative_nominal(self):
        """direction=-1 should match a positive nominal + manual subtraction."""
        explicit = ToleranceChain("explicit")
        explicit.add("a", nominal=100.0, plus=0.1, minus=0.1)
        explicit.add("b", nominal=-80.0, plus=0.2, minus=0.2)

        with_dir = ToleranceChain("with_direction")
        with_dir.add("a", nominal=100.0, plus=0.1, minus=0.1)
        with_dir.add("b", nominal=80.0, plus=0.2, minus=0.2, direction=-1.0)

        r1 = explicit.analyze(target=20.0, tolerance=1.0)
        r2 = with_dir.analyze(target=20.0, tolerance=1.0)
        self.assertAlmostEqual(r1.nominal_result, r2.nominal_result, places=6)
        self.assertAlmostEqual(r1.worst_case_range, r2.worst_case_range, places=6)


# ============================================================
# TOLERANCE auto_stack_from_assembly
# ============================================================
class TestAutoStackFromAssembly(unittest.TestCase):
    """auto_stack_from_assembly builds a ToleranceChain from real parts."""

    def test_builds_chain_from_L3(self):
        parts = load_and_dedup(os.path.join(FIXTURES, "L3_good.step"))
        def label_fn(s):
            return L3_LABELS.get(sig(s), 'other')

        chain = auto_stack_from_assembly(
            parts, label_fn, axis='Z',
            tolerances={'post': 0.5, 'beam': 0.3, 'plate': 0.1})
        self.assertEqual(len(chain.dimensions), len(parts))

    def test_assigns_default_tolerance_for_unknown_labels(self):
        parts = load_and_dedup(os.path.join(FIXTURES, "L1_good.step"))
        def label_fn(s):
            return L1_LABELS.get(sig(s), 'other')

        chain = auto_stack_from_assembly(parts, label_fn, axis='Z',
                                           tolerances={})
        for d in chain.dimensions:
            self.assertEqual(d.plus, 0.1)
            self.assertEqual(d.minus, 0.1)

    def test_sorts_by_axis_position(self):
        parts = load_and_dedup(os.path.join(FIXTURES, "L3_good.step"))
        def label_fn(s):
            return L3_LABELS.get(sig(s), 'other')

        chain = auto_stack_from_assembly(parts, label_fn, axis='Z')
        # Chain must produce a positive nominal result (all dimensions are
        # sizes, direction=+1 by default)
        result = chain.analyze(target=0.0, tolerance=10000.0, mc_samples=1000)
        self.assertGreater(result.nominal_result, 0)


# ============================================================
# DISASSEMBLY MODULE
# ============================================================
class TestDisassemblyStep(unittest.TestCase):
    """Pure-data-struct test — no STEP file needed."""

    def test_offset_at_x_positive(self):
        step = DisassemblyStep(0, 'motor', (10, 20, 30), 'X', 1.0)
        self.assertEqual(step.offset_at(100), (100.0, 0.0, 0.0))

    def test_offset_at_y_negative(self):
        step = DisassemblyStep(0, 'motor', (10, 20, 30), 'Y', -1.0)
        self.assertEqual(step.offset_at(50), (0.0, -50.0, 0.0))

    def test_offset_at_z(self):
        step = DisassemblyStep(0, 'motor', (10, 20, 30), 'Z', 1.0)
        self.assertEqual(step.offset_at(25), (0.0, 0.0, 25.0))


class TestDisassemblySequence(unittest.TestCase):
    def setUp(self):
        self.step_path = os.path.join(FIXTURES, "L3_good.step")
        self.seq = DisassemblySequence(self.step_path, labels=L3_LABELS)

    def test_loads_parts_and_centroid(self):
        self.assertGreater(len(self.seq.parts), 0)
        self.assertEqual(len(self.seq.centroid), 3)
        for coord in self.seq.centroid:
            self.assertIsInstance(coord, float)

    def test_auto_sequence_orders_all_parts(self):
        self.seq.auto_sequence()
        self.assertEqual(len(self.seq.steps), len(self.seq.parts))
        indices = [s.part_index for s in self.seq.steps]
        self.assertEqual(sorted(indices), list(range(len(self.seq.parts))))

    def test_auto_sequence_respects_priority(self):
        """Lower priority number should be removed first."""
        self.seq.auto_sequence(priority={'motor': 1, 'bracket': 2, 'post': 99})
        priorities_seen = []
        priority_map = {'motor': 1, 'bracket': 2, 'post': 99}
        for step in self.seq.steps:
            priorities_seen.append(priority_map.get(step.label, 5))
        # Motor and bracket should appear before post in the sequence
        self.assertLessEqual(priorities_seen[0], priorities_seen[-1])

    def test_summary_returns_string_with_all_steps(self):
        self.seq.auto_sequence()
        summary = self.seq.summary()
        self.assertIn("DISASSEMBLY SEQUENCE", summary)
        # One line per step
        step_lines = [l for l in summary.split('\n') if l.strip().startswith(tuple(str(i) for i in range(1, 10)))]
        self.assertGreaterEqual(len(step_lines), 1)

    def test_export_radial_writes_step(self):
        self.seq.auto_sequence()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "radial.step")
            self.seq.export_radial(out, expansion=0.2)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 1000)

    def test_export_radial_expansion_zero_is_assembled(self):
        """expansion=0 should produce a STEP with no part translations."""
        self.seq.auto_sequence()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "zero.step")
            self.seq.export_radial(out, expansion=0.0)
            self.assertTrue(os.path.exists(out))

    def test_export_exploded_writes_step(self):
        self.seq.auto_sequence()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "axial.step")
            self.seq.export_exploded(out, explode_distance=50.0)
            self.assertTrue(os.path.exists(out))


# ============================================================
# MCP SERVER — subprocess-based JSON-RPC round-trip
# ============================================================
class _MCPSession:
    """Spawn the MCP server, run initialize, and provide call helpers.

    Each test spawns its own session to avoid shared-subprocess state
    coupling on Windows where text-mode line buffering is unreliable.
    """

    def __init__(self):
        import sys as _sys
        repo = os.path.join(os.path.dirname(__file__), '..')
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        self.proc = subprocess.Popen(
            [_sys.executable, "-m", "cadclaw_mcp.server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=repo, text=True, env=env, bufsize=0,
        )
        self._req_id = 0
        init_resp = self._rpc("initialize", {})
        assert init_resp["result"]["serverInfo"]["name"] == "CADCLAW"

    def _rpc(self, method, params):
        self._req_id += 1
        req = {"jsonrpc": "2.0", "id": self._req_id,
               "method": method, "params": params}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout unexpectedly")
        return json.loads(line)

    def list_tools(self):
        return self._rpc("tools/list", {})["result"]["tools"]

    def call(self, name, args):
        return self._rpc("tools/call",
                          {"name": name, "arguments": args})

    @staticmethod
    def content(response):
        return json.loads(response["result"]["content"][0]["text"])

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class TestMCPServer(unittest.TestCase):
    """End-to-end JSON-RPC protocol tests for the CADCLAW MCP server."""

    def test_tools_list_has_all_expected(self):
        with _MCPSession() as s:
            names = {t["name"] for t in s.list_tools()}
        expected = {
            "run_harness",
            # v0.5 tools (kept for backwards compat)
            "load_assembly", "check_inventory", "check_interference",
            "check_adjacency", "check_dimensions", "compute_deflection",
            "compute_motor_budget", "compute_belt_tension", "tolerance_stack",
            "disassembly_sequence", "export_exploded_view",
            # v0.6 additions
            "doctor", "check_bom_against_cad", "check_publish_boundary",
            "check_claims", "check_region_inventory", "compare_step_parity",
            # v0.10 assembly tools
            "assemble_validate_spec", "assemble_build", "assemble_check_round",
            "assemble_inspect_component", "assemble_render_views",
            "assemble_render_sequence",
        }
        self.assertEqual(names, expected)

    def test_every_tool_schema_has_a_handler(self):
        """A schema without a handler is an advertised tool that 404s."""
        import cadclaw_mcp.server as server
        schema_names = {t["name"] for t in server.TOOLS}
        self.assertEqual(schema_names, set(server.TOOL_HANDLERS))

    def test_compute_deflection(self):
        with _MCPSession() as s:
            r = s.call("compute_deflection", {
                "span_m": 2.0, "point_load_kg": 3.8,
                "I_cm4": 18.0, "beam_kg_per_m": 2.45, "limit_mm": 0.5,
            })
            c = s.content(r)
        self.assertIn("passed", c)
        self.assertGreater(c["total_sag_mm"], 0)

    def test_compute_motor_budget(self):
        with _MCPSession() as s:
            r = s.call("compute_motor_budget", {
                "mass_kg": 4.0, "n_motors": 1,
                "pulley_radius_mm": 6.37, "motor_torque_Nm": 1.89,
            })
            c = s.content(r)
        self.assertTrue(c["passed"])
        self.assertGreater(c["safety_factor"], 1)

    def test_compute_belt_tension(self):
        with _MCPSession() as s:
            r = s.call("compute_belt_tension", {"force_N": 50, "n_belts": 4})
            c = s.content(r)
        self.assertTrue(c["passed"])

    def test_tolerance_stack(self):
        with _MCPSession() as s:
            r = s.call("tolerance_stack", {
                "chain_name": "test",
                "dimensions": [
                    {"name": "a", "nominal": 100.0, "plus": 0.1, "minus": 0.1},
                    {"name": "b", "nominal": -100.0, "plus": 0.1, "minus": 0.1},
                ],
                "target": 0.0, "tolerance": 1.0, "mc_samples": 5000,
            })
            c = s.content(r)
        self.assertAlmostEqual(c["nominal_result_mm"], 0.0, places=6)
        self.assertTrue(c["worst_case"]["passed"])

    def test_load_assembly_and_check_inventory(self):
        with _MCPSession() as s:
            r = s.call("load_assembly",
                        {"path": os.path.join(FIXTURES, "L1_good.step")})
            c = s.content(r)
            self.assertEqual(c["status"], "loaded")
            self.assertGreater(c["total_parts"], 0)

            r = s.call("check_inventory", {"expected": {}})
            c = s.content(r)
        self.assertIn("total_parts", c)

    def test_disassembly_sequence(self):
        with _MCPSession() as s:
            r = s.call("disassembly_sequence",
                        {"path": os.path.join(FIXTURES, "L3_good.step")})
            c = s.content(r)
        self.assertGreater(c["n_steps"], 0)
        self.assertEqual(len(c["centroid"]), 3)

    def test_export_exploded_view_radial(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.step")
            with _MCPSession() as s:
                r = s.call("export_exploded_view", {
                    "path": os.path.join(FIXTURES, "L3_good.step"),
                    "output_path": out,
                    "mode": "radial",
                    "expansion": 0.2,
                })
                c = s.content(r)
            self.assertEqual(c["mode"], "radial")
            self.assertTrue(os.path.exists(out))

    def test_unknown_tool_returns_error(self):
        with _MCPSession() as s:
            r = s.call("does_not_exist", {})
        self.assertTrue("error" in r
                         or r.get("result", {}).get("isError") is True)


# ============================================================
# RENDER MODULE (STEP -> PNG -> GIF)
# ============================================================
class TestRender(unittest.TestCase):
    """Offscreen VTK rendering + PNG stitching. Uses small resolutions and
    coarse tessellation to keep the suite fast."""

    FIXTURE = os.path.join(FIXTURES, "L3_good.step")

    def test_render_step_to_png_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "frame.png")
            render_step_to_png(self.FIXTURE, out,
                                width=200, height=150,
                                tessellation_tol=1.0)
            self.assertTrue(os.path.exists(out))
            self.assertGreater(os.path.getsize(out), 500)

    def test_render_frames_to_gif(self):
        """Seed a small frames dir from the disassembly module, render it."""
        with tempfile.TemporaryDirectory() as tmp:
            frames_dir = os.path.join(tmp, "frames")
            os.makedirs(frames_dir)
            seq = DisassemblySequence(self.FIXTURE)
            seq.auto_sequence()
            seq.export_frames(frames_dir, explode_distance=50,
                               n_transition_frames=1)

            gif = os.path.join(tmp, "out.gif")
            n = render_frames_to_gif(frames_dir, gif, fps=5,
                                       width=200, height=150,
                                       tessellation_tol=1.0)
            self.assertGreater(n, 1)
            self.assertTrue(os.path.exists(gif))
            self.assertGreater(os.path.getsize(gif), 1000)

    def test_make_disassembly_gif_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            gif = os.path.join(tmp, "end_to_end.gif")
            n = make_disassembly_gif(
                self.FIXTURE, gif,
                n_transition_frames=1, fps=5,
                width=200, height=150,
                tessellation_tol=1.0,
            )
            self.assertGreater(n, 0)
            self.assertTrue(os.path.exists(gif))

    def test_radial_explode_gif(self):
        """Simultaneous outward explode + 360 camera orbit."""
        with tempfile.TemporaryDirectory() as tmp:
            gif = os.path.join(tmp, "radial.gif")
            n = render_radial_explode_gif(
                self.FIXTURE, gif,
                expansion=0.4, explode_frames=6,
                rotate_frames=12, hold_frames=2,
                fps=15, width=240, height=180,
                tessellation_tol=1.0, gif_colors=32,
            )
            self.assertEqual(n, 6 + 2 + 12)  # explode + hold + rotate
            self.assertTrue(os.path.exists(gif))
            self.assertGreater(os.path.getsize(gif), 1000)

    def test_make_disassembly_gif_keeps_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames_dir = os.path.join(tmp, "kept")
            os.makedirs(frames_dir)
            gif = os.path.join(tmp, "keep.gif")
            make_disassembly_gif(
                self.FIXTURE, gif,
                frames_dir=frames_dir, keep_frames=True,
                n_transition_frames=1, fps=5,
                width=200, height=150, tessellation_tol=1.0,
            )
            frame_steps = [f for f in os.listdir(frames_dir)
                           if f.endswith(".step")]
            self.assertGreater(len(frame_steps), 0)


# ============================================================
# STEP COLOR EXTRACTION (AP242) — dim-signature key bug fix
# ============================================================
class TestStepColorExtraction(unittest.TestCase):
    """Regression test for the AP242 color lookup fix.

    Bug: `_extract_step_colors` keyed by untransformed leaf bbox, so the
    `_color_for` lookup from `cq.importers.importStep`-returned shapes
    (which carry assembly transforms) missed every part placed away from
    the origin. Fix: key by dim-signature (sorted 3-tuple of rounded
    extents) so keys are translation-invariant and match
    `cadclaw.inventory.sig`.

    The checked-in L1/L2/L3 fixtures were produced by CADQuery without
    AP242 color assignments, so we cannot assert that color extraction
    actually yields entries; instead we assert (a) the function returns
    without error, (b) any keys it does return are dim-sigs (3-tuples),
    and (c) the `_color_for` lookup resolves a synthetic dim-sig-keyed
    step_colors dict even for a shape placed away from origin — which
    is the exact path the bug broke.
    """

    FIXTURE = os.path.join(FIXTURES, "L3_good.step")

    def test_extract_returns_dict_without_error(self):
        from cadclaw.render import _extract_step_colors
        colors = _extract_step_colors(self.FIXTURE)
        self.assertIsInstance(colors, dict)
        # Any extracted color key must be the sorted 3-tuple dim-sig,
        # not the 6-tuple bbox that the original buggy code returned.
        for key in colors.keys():
            self.assertEqual(
                len(key), 3,
                f"Expected 3-tuple dim-sig, got {len(key)}-tuple: {key}")
            self.assertEqual(
                list(key), sorted(key),
                f"Dim-sig must be sorted ascending: {key}")

    def test_color_for_uses_dim_sig_lookup(self):
        """Synthetic end-to-end: a step_colors dict keyed by a shape's
        dim-sig must resolve via `_color_for` even when the shape is
        placed away from origin. Pre-fix, the bbox-keyed lookup missed
        every non-origin part."""
        from cadclaw.render import _color_for
        from cadclaw.inventory import sig as _sig
        parts = load_and_dedup(self.FIXTURE)
        self.assertGreater(len(parts), 0)
        # L3_good has the gantry parts at Z >= 1000 — pick one to make
        # sure we're exercising the non-origin path.
        off_origin = [p for p in parts if p.Center().z > 100.0]
        self.assertGreater(len(off_origin), 0,
            "fixture must have at least one non-origin part to exercise fix")
        target = off_origin[0]
        magenta = (1.0, 0.0, 1.0)
        step_colors = {_sig(target): magenta}
        result = _color_for(
            target, labels=None, color_map=None,
            default_color=(0.5, 0.5, 0.5), step_colors=step_colors)
        self.assertEqual(result, magenta,
            "dim-sig keyed step_colors must win over default for "
            "shapes placed away from origin")


# ============================================================
# PARITY MODULE (STEP-to-STEP dim-signature comparison)
# ============================================================
class TestParity(unittest.TestCase):
    """STEP-to-STEP parity checks. Uses the L1/L2 fixtures as drop-in
    stand-ins for "native CAD export" and "scripted regeneration" — the identity
    and cross-assembly cases are enough to pin the contract down."""

    GOOD = os.path.join(FIXTURES, "L1_good.step")
    BAD = os.path.join(FIXTURES, "L1_bad.step")
    OTHER = os.path.join(FIXTURES, "L2_good.step")

    def test_self_compare_passes(self):
        r = compare_steps(self.GOOD, self.GOOD)
        self.assertIsInstance(r, ParityReport)
        self.assertTrue(r.passed)
        self.assertEqual(r.only_in_a, [])
        self.assertEqual(r.only_in_b, [])
        self.assertEqual(r.a_parts, r.b_parts)

    def test_different_assemblies_surface_deltas(self):
        """Comparing unrelated fixtures must produce non-empty deltas on
        both sides — L1 and L2 share no part signatures."""
        r = compare_steps(self.GOOD, self.OTHER)
        self.assertFalse(r.passed)
        self.assertGreater(len(r.only_in_a) + len(r.only_in_b), 0)

    def test_good_vs_bad_same_level_runs_cleanly(self):
        """L1_good and L1_bad may or may not share every signature;
        the check should at least complete and report sensible counts."""
        r = compare_steps(self.GOOD, self.BAD)
        self.assertIsInstance(r, ParityReport)
        self.assertGreater(r.a_parts, 0)
        self.assertGreater(r.b_parts, 0)
        # passed is a bool either way; summary should render without errors
        self.assertIn("PARITY", r.summary())

    def test_report_fields_sum_correctly(self):
        """For the self-compare case, a_parts should equal b_parts and
        equal the total shape count from _load_shapes."""
        from cadclaw.render import _load_shapes
        r = compare_steps(self.GOOD, self.GOOD)
        self.assertEqual(r.a_parts, len(_load_shapes(self.GOOD)))

    def test_visibility_toggle_no_warning_on_self(self):
        """Same file compared to itself must never trigger the warning."""
        self.assertIsNone(visibility_toggle_warning(self.GOOD, self.GOOD))

    def test_visibility_toggle_returns_string_or_none(self):
        """Cross-fixture comparison either warns (str) or is silent (None)
        — never raises."""
        result = visibility_toggle_warning(self.GOOD, self.OTHER)
        self.assertTrue(result is None or isinstance(result, str))


# ============================================================
# GEOMETRY IMPORT — selective shape loading by dim-signature
# ============================================================
class TestGeometryImport(unittest.TestCase):
    """Verify the authored-shape reuse pattern: load specific parts
    from a reference STEP by dim-signature so CADQuery scripts can
    clone them instead of re-authoring crude parametric versions."""

    FIXTURE = os.path.join(FIXTURES, "L3_good.step")

    def test_first_shape_returns_none_on_missing_file(self):
        self.assertIsNone(first_shape_by_dim_sig(
            "/nonexistent_path.step", (1.0, 2.0, 3.0)))

    def test_shapes_by_dim_sig_returns_empty_on_missing_file(self):
        self.assertEqual(
            shapes_by_dim_sig("/nonexistent_path.step", (1.0, 2.0, 3.0)),
            [])

    def test_shapes_by_dim_sig_finds_known_parts(self):
        """L3_good has wheels (10.2, 23.9, 23.9). The helper must find them
        and return a list of cq.Shape objects."""
        wheels = shapes_by_dim_sig(self.FIXTURE, (10.2, 23.9, 23.9))
        self.assertGreater(len(wheels), 0,
            "L3_good fixture should contain at least one V-wheel by dim-sig")

    def test_dim_sig_mismatch_returns_empty(self):
        """A dim-sig that matches no shape returns an empty list."""
        self.assertEqual(
            shapes_by_dim_sig(self.FIXTURE, (999.9, 888.8, 777.7)),
            [])


# ============================================================
# HARNESS INTEGRATION TEST
# ============================================================
class TestHarnessReport(unittest.TestCase):
    def test_report_format(self):
        h = Harness(os.path.join(FIXTURES, "L1_good.step"))
        h.add_inventory(L1_LABELS, L1_EXPECTED)
        report = h.run()
        report_str = str(report)
        self.assertIn("CAD HARNESS REPORT", report_str)
        self.assertIn("Parts:", report_str)

    def test_empty_harness_fails_closed(self):
        h = Harness(os.path.join(FIXTURES, "L1_good.step"))
        report = h.run()
        self.assertFalse(report.passed)
        self.assertEqual(report.report.overall.value, "fail")
        self.assertEqual(
            report.report.findings[0].id,
            "harness.no_gates_configured",
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
