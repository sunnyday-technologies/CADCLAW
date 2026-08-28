"""Fixture-backed tests for semantic AP242 PMI presence reporting."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from cadclaw.findings import Severity
from cadclaw.pmi import (
    PmiExtractionError,
    SemanticPmiSnapshot,
    _count_semantic_dimensions,
    _read_step_schema,
    extract_semantic_pmi,
    run_pmi_present,
)
from cadclaw.reporters import render_markdown, render_text
from cadclaw_cli.main import main


FIXTURES = Path(__file__).parent / "fixtures" / "pmi_semantic"
STC_06 = FIXTURES / "nist_stc_06_asme1_ap242-e3.stp"
FTC_11 = FIXTURES / "nist_ftc_11_asme1_ap242-e2.stp"


class TestSemanticPmiExtraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stc_06 = extract_semantic_pmi(STC_06)
        cls.ftc_11 = extract_semantic_pmi(FTC_11)

    def test_nist_stc_06_exact_versioned_counts(self):
        self.assertEqual(self.stc_06.counts, {
            "dimensions": 17,
            "geometric_tolerances": 25,
            "datums": 51,
        })
        self.assertIn("AP242", self.stc_06.step_schema)
        self.assertRegex(self.stc_06.reader_version, r"^\d+\.\d+\.")
        self.assertEqual(
            self.stc_06.diagnostics,
            {
                "raw_dimension_labels": 19,
                "presentation_only_dimension_labels_ignored": 2,
            },
        )

    def test_nist_ftc_11_exact_versioned_counts(self):
        self.assertEqual(self.ftc_11.counts, {
            "dimensions": 6,
            "geometric_tolerances": 4,
            "datums": 4,
        })
        self.assertEqual(self.ftc_11.scope, "semantic_only")

    def test_presentation_only_dimension_labels_do_not_count_as_semantic(self):
        class Labels:
            values = ["common", "presentation"]

            def Length(self):
                return len(self.values)

            def Value(self, index):
                return self.values[index - 1]

        class Dimension:
            def __init__(self, dimension_type):
                self.dimension_type = dimension_type

            def GetObject(self):
                return self

            def GetType(self):
                return self.dimension_type

        semantic, presentation = _count_semantic_dimensions(
            Labels(),
            Dimension,
            {"common", "presentation"},
        )
        self.assertEqual(semantic, 0)
        self.assertEqual(presentation, 2)

    def test_ap214_is_unsupported_not_absent(self):
        body = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('AUTOMOTIVE_DESIGN_CC2'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".stp", delete=False, encoding="utf-8"
        ) as stream:
            stream.write(body)
            path = stream.name
        try:
            with self.assertRaises(PmiExtractionError) as caught:
                extract_semantic_pmi(path)
            self.assertEqual(caught.exception.code, "pmi.schema_unsupported")
        finally:
            os.unlink(path)

    def test_schema_name_containing_ap242_is_not_treated_as_ap242(self):
        body = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('NOT_AP242_FAKE'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".stp", delete=False, encoding="utf-8"
        ) as stream:
            stream.write(body)
            path = stream.name
        try:
            with self.assertRaises(PmiExtractionError) as caught:
                extract_semantic_pmi(path)
            self.assertEqual(caught.exception.code, "pmi.schema_unsupported")
        finally:
            os.unlink(path)

    def test_commented_fake_schema_does_not_override_header_schema(self):
        body = """ISO-10303-21;
/* FILE_SCHEMA(('AP242_FAKE')); */
HEADER;
FILE_DESCRIPTION(('FILE_SCHEMA((''AP242_FAKE''))'),'2;1');
FILE_SCHEMA(('AUTOMOTIVE_DESIGN_CC2'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".stp", delete=False, encoding="utf-8"
        ) as stream:
            stream.write(body)
            path = stream.name
        try:
            with self.assertRaises(PmiExtractionError) as caught:
                extract_semantic_pmi(path)
            self.assertEqual(caught.exception.code, "pmi.schema_unsupported")
        finally:
            os.unlink(path)

    def test_malformed_ap242_is_import_error_not_absent(self):
        body = """ISO-10303-21;
HEADER;
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));
ENDSEC;
THIS IS NOT A VALID DATA SECTION
"""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".stp", delete=False, encoding="utf-8"
        ) as stream:
            stream.write(body)
            path = stream.name
        try:
            with self.assertRaises(PmiExtractionError) as caught:
                extract_semantic_pmi(path)
            self.assertIn(caught.exception.code, {
                "pmi.read_failed",
                "pmi.transfer_failed",
            })
        finally:
            os.unlink(path)

    def test_schema_missing_is_a_structured_error(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".stp", delete=False, encoding="utf-8"
        ) as stream:
            stream.write("ISO-10303-21;\nHEADER;\nENDSEC;\n")
            path = stream.name
        try:
            with self.assertRaises(PmiExtractionError) as caught:
                extract_semantic_pmi(path)
            self.assertEqual(caught.exception.code, "pmi.schema_missing")
        finally:
            os.unlink(path)

    def test_schema_text_is_bounded_and_sanitized(self):
        schema = "AP242<script>" + ("X" * 300)
        body = f"ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('{schema}'));\nENDSEC;"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".stp", delete=False, encoding="utf-8"
        ) as stream:
            stream.write(body)
            path = Path(stream.name)
        try:
            observed = _read_step_schema(path)
            self.assertLessEqual(len(observed), 160)
            self.assertNotIn("<", observed)
            self.assertNotIn(">", observed)
        finally:
            path.unlink()

    def test_missing_reader_is_a_structured_error(self):
        with mock.patch.dict(sys.modules, {"OCP": None}):
            with self.assertRaises(PmiExtractionError) as caught:
                extract_semantic_pmi(FTC_11)
        self.assertEqual(caught.exception.code, "pmi.reader_unavailable")

    def test_native_read_exception_is_a_structured_error(self):
        class BrokenReader:
            def SetGDTMode(self, _value):
                pass

            def SetMatMode(self, _value):
                pass

            def SetNameMode(self, _value):
                pass

            def SetViewMode(self, _value):
                pass

            def ReadFile(self, _path):
                raise RuntimeError("native failure")

        with mock.patch(
            "OCP.STEPCAFControl.STEPCAFControl_Reader",
            BrokenReader,
        ):
            with self.assertRaises(PmiExtractionError) as caught:
                extract_semantic_pmi(FTC_11)
        self.assertEqual(caught.exception.code, "pmi.read_failed")


class TestPmiPresentReport(unittest.TestCase):
    def test_empty_declaration_is_explicitly_not_applicable_without_input(self):
        report = run_pmi_present(None, [])
        self.assertEqual(report.meta["applicability"], "not_applicable")
        self.assertEqual(report.findings, [])
        self.assertEqual(report.overall, Severity.PASS)
        self.assertIn("N/A", render_text(report, color=False))
        self.assertIn("Result: N/A", render_markdown(report))
        self.assertIn(
            "not applicable — task has no declared PMI requirements",
            report.confidence_budget.not_checked[0],
        )

    def test_each_expected_class_is_reported_separately(self):
        report = run_pmi_present(
            FTC_11,
            ["dimensions", "geometric_tolerances", "datums"],
        )
        statuses = {
            item["class"]: item["status"]
            for item in report.meta["class_results"]
        }
        self.assertEqual(statuses, {
            "dimensions": "present",
            "geometric_tolerances": "present",
            "datums": "present",
        })
        self.assertEqual(len(report.findings), 3)
        self.assertEqual(report.overall, Severity.PASS)

    def test_declared_class_with_zero_count_is_absent_and_fails(self):
        snapshot = SemanticPmiSnapshot(
            step_path="fixture.stp",
            step_schema="AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF",
            counts={
                "dimensions": 0,
                "geometric_tolerances": 4,
                "datums": 4,
            },
            reader_version="7.8.1.1",
            diagnostics={
                "raw_dimension_labels": 2,
                "presentation_only_dimension_labels_ignored": 2,
            },
        )
        with mock.patch("cadclaw.pmi.extract_semantic_pmi", return_value=snapshot):
            report = run_pmi_present("fixture.stp", ["dimensions"])
        self.assertEqual(report.meta["class_results"][0]["status"], "absent")
        self.assertEqual(report.findings[0].id, "pmi.dimensions.absent")
        self.assertEqual(report.findings[0].severity, Severity.FAIL)
        self.assertEqual(report.overall, Severity.FAIL)

    def test_scope_discloses_graphical_and_process_note_omissions(self):
        report = run_pmi_present(FTC_11, ["dimensions"])
        omitted = "\n".join(report.confidence_budget.not_checked)
        self.assertIn("graphical PMI", omitted)
        self.assertIn("material assignments", omitted)
        self.assertIn("process and general notes", omitted)
        self.assertIn("standards conformance", omitted)

    def test_unsupported_class_is_not_silently_ignored(self):
        report = run_pmi_present(FTC_11, ["process_notes"])
        self.assertEqual(report.overall, Severity.FAIL)
        self.assertEqual(report.findings[0].id, "pmi.unsupported_class")

    def test_m3_rules_report_not_applicable_through_union_harness(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "harness",
                "--rules", "tests/fixtures/m3_crete/cadclaw_m3.yaml",
                "--only", "pmi_present",
                "--report-format", "json",
            ])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["meta"]["pmi_present"]["applicability"],
            "not_applicable",
        )
        self.assertEqual(payload["meta"]["applicability"], "not_applicable")
        self.assertTrue(any(
            "not applicable" in item
            for item in payload["confidence_budget"]["not_checked"]
        ))

    def test_focused_cli_reports_each_declared_fixture_class(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([
                "pmi-present",
                "--rules", "tests/fixtures/pmi_semantic/cadclaw.yaml",
                "--report-format", "json",
            ])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["meta"]["applicability"], "applicable")
        self.assertEqual(
            [item["status"] for item in payload["meta"]["class_results"]],
            ["present", "present", "present"],
        )


if __name__ == "__main__":
    unittest.main()
