"""Smoke tests for the cadclaw CLI dispatcher."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from cadclaw_cli.main import build_parser, main


FIXTURES = Path(__file__).parent / "fixtures"


class TestParser(unittest.TestCase):
    def test_known_subcommands(self):
        p = build_parser()
        names = set()
        for action in p._actions:
            if hasattr(action, "choices") and action.choices:
                names.update(action.choices.keys())
        for expected in ["doctor", "parity", "inventory",
                          "bom-audit", "claim-audit", "publish-audit",
                          "harness"]:
            self.assertIn(expected, names)


class TestDoctorCommand(unittest.TestCase):
    def test_doctor_runs_and_exits(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["doctor", "--report-format", "json"])
        self.assertIn(code, (0, 1, 2))
        body = buf.getvalue()
        d = json.loads(body)
        self.assertEqual(d["schema_version"], "0.7")
        self.assertIn("findings", d)


class TestParityCommand(unittest.TestCase):
    def test_parity_finds_difference_in_l3_fixtures(self):
        a = FIXTURES / "L3_good.step"
        b = FIXTURES / "L3_bad.step"
        if not (a.exists() and b.exists()):
            self.skipTest("L3 fixtures not generated; run tests/generate_fixtures.py")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["parity", str(a), str(b),
                         "--report-format", "json"])
        d = json.loads(buf.getvalue())
        # L3_bad has 1 fewer part
        self.assertEqual(d["overall"], "fail")
        self.assertTrue(any(f["category"] == "parity" for f in d["findings"]))


class TestExitCodes(unittest.TestCase):
    def test_missing_rules_file_returns_3(self):
        buf = io.StringIO()
        err = io.StringIO()
        old_err = sys.stderr
        sys.stderr = err
        try:
            with redirect_stdout(buf):
                code = main(["bom-audit", "--rules", "/nonexistent.yaml"])
        finally:
            sys.stderr = old_err
        self.assertEqual(code, 3)


class TestHarnessTiming(unittest.TestCase):
    """LOW-8 (M3-CRETE field test): the union runner used to drop
    `aggregate.duration_ms` and reports always showed 0 ms. Verify the
    harness sets a non-zero duration."""

    def test_harness_reports_nonzero_duration(self):
        rules_path = FIXTURES / "m3_crete" / "cadclaw_m3.yaml"
        if not rules_path.exists():
            self.skipTest("m3_crete fixtures not present")
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["harness", "--rules", str(rules_path),
                  "--report-format", "json",
                  "--skip", "publish_audit,claim_audit"])
        d = json.loads(buf.getvalue())
        self.assertGreater(d["duration_ms"], 0,
                           msg="aggregate Report.duration_ms must be set by _cmd_harness")


if __name__ == "__main__":
    unittest.main()
