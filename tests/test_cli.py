"""Smoke tests for the cadclaw CLI dispatcher."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

from cadclaw_cli.main import build_parser, main


FIXTURES = Path(__file__).parent / "fixtures"


@contextmanager
def _redirect_stderr(buf):
    old = sys.stderr
    sys.stderr = buf
    try:
        yield
    finally:
        sys.stderr = old


class TestParser(unittest.TestCase):
    def test_known_subcommands(self):
        p = build_parser()
        names = set()
        for action in p._actions:
            if hasattr(action, "choices") and action.choices:
                names.update(action.choices.keys())
        for expected in ["doctor", "parity", "inventory",
                          "bom-audit", "claim-audit", "publish-audit",
                          "harness", "inspect"]:
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


class TestInspectCommands(unittest.TestCase):
    """v0.7.1 Ergo-2: `cadclaw inspect sigs|part|overlaps <step>`."""

    L3_GOOD = FIXTURES / "L3_good.step"

    def setUp(self):
        if not self.L3_GOOD.exists():
            self.skipTest("L3 fixtures not generated; run tests/generate_fixtures.py")

    def test_inspect_sigs_lists_unique_signatures(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["inspect", "sigs", str(self.L3_GOOD)])
        self.assertEqual(code, 0)
        body = buf.getvalue()
        self.assertIn("unique signatures", body)
        # L3_good has at least beam, motor, wheel — multiple sigs.
        self.assertIn("count", body)

    def test_inspect_sigs_with_rules_resolves_labels(self):
        rules_yaml = (
            'schema_version: "0.7"\n'
            'labels:\n'
            '  beam:    [40.0, 80.0, 1000.0]\n'
            '  motor:   [56.4, 56.4, 76.6]\n'
        )
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(rules_yaml)
            rules_path = f.name
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["inspect", "sigs", str(self.L3_GOOD),
                             "--rules", rules_path])
            self.assertEqual(code, 0)
            body = buf.getvalue()
            self.assertIn("motor", body)
        finally:
            os.unlink(rules_path)

    def test_inspect_part_no_filters_lists_all(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["inspect", "part", str(self.L3_GOOD)])
        self.assertEqual(code, 0)
        self.assertIn("part(s) match", buf.getvalue())

    def test_inspect_part_at_returns_empty_far_away(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["inspect", "part", str(self.L3_GOOD),
                         "--at", "999999,999999,999999"])
        self.assertEqual(code, 0)
        self.assertIn("no parts match", buf.getvalue())

    def test_inspect_part_xyz_parser_rejects_bad_input(self):
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf):
            try:
                with _redirect_stderr(err):
                    main(["inspect", "part", str(self.L3_GOOD),
                          "--at", "not,a,point"])
                self.fail("should have exited 3")
            except SystemExit as e:
                self.assertEqual(e.code, 3)
        self.assertIn("--at", err.getvalue())

    def test_inspect_overlaps_requires_target(self):
        # No --label and no --at → exit 3.
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), _redirect_stderr(err):
            code = main(["inspect", "overlaps", str(self.L3_GOOD)])
        self.assertEqual(code, 3)
        self.assertIn("target", err.getvalue())

    def test_inspect_overlaps_label_without_rules_fails(self):
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), _redirect_stderr(err):
            code = main(["inspect", "overlaps", str(self.L3_GOOD),
                         "--label", "plate"])
        self.assertEqual(code, 3)
        self.assertIn("--rules", err.getvalue())


if __name__ == "__main__":
    unittest.main()
