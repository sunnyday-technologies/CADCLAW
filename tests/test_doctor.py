"""Tests for cadclaw/doctor.py."""
import os
import tempfile
import unittest
from pathlib import Path

from cadclaw.doctor import (
    probe_dependencies,
    probe_mcp_inproc,
    probe_python,
    probe_repo_signals,
    probe_venv,
    run_doctor,
)
from cadclaw.findings import Severity


class TestProbePython(unittest.TestCase):
    def test_python_310_passes(self):
        findings = probe_python()
        self.assertTrue(any(f.id == "doctor.python_ok" for f in findings))


class TestProbeVenv(unittest.TestCase):
    def test_no_pyvenv_cfg_is_pass(self):
        with tempfile.TemporaryDirectory() as td:
            findings = probe_venv(prefix=td)
            self.assertEqual(findings[0].id, "doctor.no_venv")
            self.assertEqual(findings[0].severity, Severity.PASS)

    def test_broken_pyvenv_cfg_fails(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "pyvenv.cfg"
            cfg.write_text(
                "home = [home-path-redacted]
                "include-system-site-packages = false\n"
                "version = 3.11.4\n",
                encoding="utf-8",
            )
            findings = probe_venv(prefix=td)
            self.assertEqual(findings[0].id, "doctor.pyvenv_broken")
            self.assertEqual(findings[0].severity, Severity.FAIL)
            # Suggested fix should mention recreating the venv
            self.assertIn("recreate", (findings[0].suggested_fix or "").lower())

    def test_pyvenv_pointing_at_existing_dir_passes(self):
        with tempfile.TemporaryDirectory() as venv_dir, \
             tempfile.TemporaryDirectory() as fake_python_home:
            # Create a fake python.exe so the probe sees something
            fake_exe = Path(fake_python_home) / "python.exe"
            fake_exe.write_text("")
            cfg = Path(venv_dir) / "pyvenv.cfg"
            cfg.write_text(f"home = {fake_python_home}\n", encoding="utf-8")
            findings = probe_venv(prefix=venv_dir)
            self.assertEqual(findings[0].id, "doctor.venv_ok")

    def test_pyvenv_with_no_home_line_warns(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "pyvenv.cfg"
            cfg.write_text("version = 3.11\n", encoding="utf-8")
            findings = probe_venv(prefix=td)
            self.assertEqual(findings[0].id, "doctor.pyvenv_no_home")


class TestProbeDependencies(unittest.TestCase):
    def test_includes_cadquery_check(self):
        findings = probe_dependencies()
        # All findings have a module name in evidence
        modules = {f.evidence.get("module") for f in findings}
        self.assertIn("cadquery", modules)
        self.assertIn("yaml", modules)
        self.assertIn("pydantic", modules)


class TestProbeMcpInproc(unittest.TestCase):
    def test_returns_at_least_one_finding(self):
        findings = probe_mcp_inproc()
        self.assertTrue(len(findings) >= 1)


class TestProbeRepoSignals(unittest.TestCase):
    def test_info_only_finding(self):
        with tempfile.TemporaryDirectory() as td:
            findings = probe_repo_signals(repo=td)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].severity, Severity.PASS)
            self.assertEqual(findings[0].evidence["step_count"], 0)


class TestRunDoctor(unittest.TestCase):
    def test_run_doctor_returns_report(self):
        report = run_doctor()
        self.assertEqual(report.schema_version, "0.7")
        self.assertGreater(len(report.findings), 0)
        # Confidence budget is populated
        self.assertGreater(len(report.confidence_budget.checked), 0)
        self.assertGreater(len(report.confidence_budget.not_checked), 0)

    def test_run_doctor_with_broken_pyvenv_overall_fail(self):
        with tempfile.TemporaryDirectory() as venv_dir:
            cfg = Path(venv_dir) / "pyvenv.cfg"
            cfg.write_text(
                "home = /nonexistent/path/to/python\n", encoding="utf-8")
            report = run_doctor(prefix=venv_dir)
            self.assertEqual(report.overall, Severity.FAIL)
            self.assertTrue(any(f.id == "doctor.pyvenv_broken"
                                for f in report.findings))


if __name__ == "__main__":
    unittest.main()
