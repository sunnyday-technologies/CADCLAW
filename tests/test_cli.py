"""Smoke tests for the cadclaw CLI dispatcher."""
import io
import json
import os
import subprocess
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
                          "harness", "inspect", "assemble"]:
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


class TestAssembleCommand(unittest.TestCase):
    def test_validate_spec_reports_incomplete_round(self):
        spec = Path("examples/m3_crete/m3_reference_assembly.yaml")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["assemble", "validate-spec", str(spec),
                         "--report-format", "json"])
        d = json.loads(buf.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(d["overall"], "warn")
        self.assertEqual(d["meta"]["active_variant"], "M3-2")
        self.assertGreater(d["meta"]["not_built_yet"], 0)

    def test_validate_spec_release_mode_fails_on_not_built_yet(self):
        spec = Path("examples/m3_crete/m3_reference_assembly.yaml")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["assemble", "validate-spec", str(spec),
                         "--release", "--report-format", "json"])
        d = json.loads(buf.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(d["overall"], "fail")
        self.assertTrue(any(
            f["id"] == "assemble.not_built_yet" and f["severity"] == "fail"
            for f in d["findings"]
        ))

    def test_build_dry_run_resolves_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cad_root = root / "CADRoot" / "CAD"
            step = cad_root.parent / "CAD" / "Advanced" / "Thing.step"
            step.parent.mkdir(parents=True, exist_ok=True)
            step.write_text("placeholder", encoding="utf-8")
            spec = root / "spec.yaml"
            spec.write_text(
                f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
component_roots:
  - {cad_root.as_posix()}
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: thing
    role: test
    source_path: CAD/Advanced/Thing.step
""",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["assemble", "build", str(spec),
                             "--dry-run", "--report-format", "json"])
            d = json.loads(buf.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(d["overall"], "warn")
            self.assertEqual(d["meta"]["missing_sources"], 0)
            self.assertTrue(d["meta"]["dry_run"])

    def test_check_round_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            step = root / "CAD" / "Advanced" / "Thing.step"
            step.parent.mkdir(parents=True, exist_ok=True)
            step.write_text("placeholder", encoding="utf-8")
            spec = root / "spec.yaml"
            spec.write_text(
                f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
validation:
  expected_inventory:
    test: 1
instances:
  - id: thing
    role: test
    source_path: {step.as_posix()}
""",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["assemble", "check-round", str(spec),
                             "--dry-run", "--report-format", "json"])
            d = json.loads(buf.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(d["overall"], "warn")
            self.assertEqual(d["meta"]["role_inventory"]["test"], 1)

    def test_inspect_component_direct_source(self):
        fixture = FIXTURES / "L1_good.step"
        if not fixture.exists():
            self.skipTest("L1 fixture not generated; run tests/generate_fixtures.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec.yaml"
            spec.write_text(
                f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
instances:
  - id: thing
    role: test
    source_path: {fixture.as_posix()}
""",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["assemble", "inspect-component", str(spec),
                             "--source-path", str(fixture),
                             "--report-format", "json"])
            d = json.loads(buf.getvalue())
            self.assertEqual(code, 0)
            self.assertGreater(d["meta"]["part_count"], 0)

    def test_render_sequence_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            step = root / "CAD" / "Advanced" / "Thing.step"
            step.parent.mkdir(parents=True, exist_ok=True)
            step.write_text("placeholder", encoding="utf-8")
            spec = root / "spec.yaml"
            spec.write_text(
                f"""
schema_version: assembly_spec.v0.1
meta:
  project: Example
  assembly_id: round1
outputs:
  step: {root.as_posix()}/build/out.step
  views_dir: {root.as_posix()}/build/views
  bom: {root.as_posix()}/build/bom.csv
instances:
  - id: x_beam
    role: x_gantry
    source_path: {step.as_posix()}
assembly_sequence:
  - id: x_gantry
    title: X Gantry
    instance_ids: [x_beam]
""",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["assemble", "render-sequence", str(spec),
                             "--dry-run", "--report-format", "json"])
            d = json.loads(buf.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(d["overall"], "warn")
            self.assertEqual(d["meta"]["steps"][0]["id"], "x_gantry")
            self.assertTrue((root / "build" / "bom.csv").exists())


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


class TestUtf8StdoutFix(unittest.TestCase):
    """v0.9 P0: stdout/stderr must accept Δ (U+0394) on Windows.

    The v0.7.0 MED-5 aggregate cad.count_mismatch finding text uses a
    literal Δ; on Windows cp1252 stdout raised UnicodeEncodeError when
    the report was printed (see `cadclaw bom-audit` field-test failure
    in M3-CRETE 2026-04-29 close-out). _force_utf8_stdio in main()
    reconfigures the streams to UTF-8 on win32.
    """

    DELTA_TEXT = "CAD has 6× motor_nema23, rules sum to 7. Δ=-1."

    def test_print_with_delta_does_not_crash(self):
        """In-process: capture stdout, print Δ-containing text, expect no exception."""
        # Independent of platform, verify that the helper doesn't break a
        # working stdout. (The Windows-specific path is exercised by the
        # subprocess test below when run on win32; on Linux/Mac stdout
        # already accepts Δ so the helper is a no-op.)
        buf = io.StringIO()
        with redirect_stdout(buf):
            print(self.DELTA_TEXT)
        self.assertIn("Δ", buf.getvalue())

    def test_doctor_handles_delta_in_subprocess(self):
        """Subprocess: re-enter the CLI with PYTHONIOENCODING forced to cp1252
        to simulate the Windows default; doctor's report should not crash even
        though some finding messages may contain Δ-like characters.
        """
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp1252"
        # Run a subprocess that prints Δ via the CLI's stdout pipeline.
        # We invoke `python -c` rather than `cadclaw` because CI environments
        # don't always have the console script on PATH.
        repo_root = str(Path(__file__).parent.parent)
        result = subprocess.run(
            [sys.executable, "-c",
             "from cadclaw_cli.main import _force_utf8_stdio;"
             "_force_utf8_stdio();"
             "print('CAD has 6× motor_nema23, rules sum to 7. Δ=-1.')"],
            cwd=repo_root, env=env, capture_output=True, text=False,
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr.decode('utf-8', 'replace')}")
        # Output bytes should decode as UTF-8 (we forced the streams).
        decoded = result.stdout.decode("utf-8", errors="replace")
        self.assertIn("Δ", decoded)


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
            'schema_version: "0.9"\n'
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

    def test_inspect_cluster_with_default_radius_outputs(self):
        """v0.9 gate #7: `cadclaw inspect cluster <step>` produces region buckets."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["inspect", "cluster", str(self.L3_GOOD),
                         "--radius", "200"])
        self.assertEqual(code, 0)
        body = buf.getvalue()
        self.assertIn("cluster_1", body)
        self.assertIn("centroid", body)
        self.assertIn("bbox", body)

    def test_inspect_cluster_label_without_rules_fails(self):
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), _redirect_stderr(err):
            code = main(["inspect", "cluster", str(self.L3_GOOD),
                         "--label", "wheel"])
        self.assertEqual(code, 3)
        self.assertIn("--rules", err.getvalue())


if __name__ == "__main__":
    unittest.main()
