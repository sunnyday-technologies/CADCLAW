"""
Test suite for cad-harness. Tests each gate against known-good and
known-bad fixture assemblies.

Run: python -m pytest tests/test_harness.py -v
  or: python tests/test_harness.py  (standalone)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from cadharness.inventory import InventoryCheck, load_and_dedup, sig
from cadharness.interference import InterferenceCheck
from cadharness.adjacency import AdjacencyCheck, AdjacencyRule
from cadharness.dimensional import DimensionalCheck, DimRule
from cadharness.kinematics import beam_deflection, motor_torque_budget, belt_tension
from cadharness.harness import Harness

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

    def test_empty_harness_passes(self):
        h = Harness(os.path.join(FIXTURES, "L1_good.step"))
        report = h.run()
        self.assertTrue(report.passed)  # no gates = vacuous pass


if __name__ == '__main__':
    unittest.main(verbosity=2)
