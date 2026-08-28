"""Fixture-backed tests for the opt-in STEP translation round-trip gate.

The integration cases reuse authored STEP files already tracked by the
repository.  They do not create geometry.  The intentionally broken
translation is generated only in a temporary directory by disabling OCCT's
semantic-PMI writer mode while leaving the imported geometry intact.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings

import cadclaw.roundtrip as roundtrip_module
from cadclaw.assembly_compiler import run_assembly_build
from cadclaw.findings import Severity
from cadclaw.pmi import extract_semantic_pmi
from cadclaw.roundtrip import (
    GeometrySnapshot,
    InterfacePair,
    PartGeometry,
    PartSelector,
    RoundtripConfig,
    RoundtripError,
    SourceTranslator,
    compare_roundtrip_artifacts,
    export_ap242,
    run_roundtrip_step,
    snapshot_geometry,
)


REPO = Path(__file__).resolve().parent.parent
NIST_FTC_11 = (
    REPO
    / "tests"
    / "fixtures"
    / "pmi_semantic"
    / "nist_ftc_11_asme1_ap242-e2.stp"
)
NIST_STC_06 = (
    REPO
    / "tests"
    / "fixtures"
    / "pmi_semantic"
    / "nist_stc_06_asme1_ap242-e3.stp"
)
RELATIVE_PARTS = REPO / "examples" / "relative_placement" / "parts"
AUTHORED_RAIL = RELATIVE_PARTS / "rail_x.step"
AUTHORED_PLATE = RELATIVE_PARTS / "plate.step"
EXPECTED_FTC_11_PMI = {
    "dimensions": 6,
    "geometric_tolerances": 4,
    "datums": 4,
}


def _writer_with_write_override(write_override):
    """Delegate a STEPCAF writer except for its final ``Write`` result.

    Capturing the real writer before the caller patches the OCP module keeps
    these tests on the real XCAF transfer/export path.  Only the final status
    or artifact is varied to exercise CADCLAW's cross-version classification.
    """
    from OCP.STEPCAFControl import STEPCAFControl_Writer as RealWriter

    class WriterWithWriteOverride:
        def __init__(self, *args, **kwargs):
            self._inner = RealWriter(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def Write(self, output_path):
            return write_override(self._inner, Path(output_path))

    return WriterWithWriteOverride


def _nested_keys(value) -> set[str]:
    """Return every mapping key in a JSON-like value."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys.update(_nested_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys.update(_nested_keys(item))
    return keys


def _nested_strings(value) -> list[str]:
    """Return scalar strings from a JSON-like value."""
    strings: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            strings.extend(_nested_strings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            strings.extend(_nested_strings(item))
    elif isinstance(value, str):
        strings.append(value)
    return strings


def _occt_default_messenger_printer_count() -> int:
    """Return the caller-visible OCCT default messenger printer count."""
    from OCP.Message import Message

    printers = Message.DefaultMessenger_s().Printers()
    if printers.IsEmpty():
        return 0
    return printers.Upper() - printers.Lower() + 1


def _export_ap242_without_semantic_pmi(source: Path, output: Path) -> None:
    """Write a real AP242 derivative whose DimTol mode is disabled.

    This is deliberately independent of ``export_ap242`` so a regression in
    the production AP242 writer's mandatory ``SetDimTolMode(True)`` cannot
    make the negative control silently stop being negative.
    """
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.Message import Message
    from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_Controller, STEPControl_StepModelType
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document

    document = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    reader = STEPCAFControl_Reader()
    reader.SetGDTMode(True)
    reader.SetMatMode(True)
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    reader.SetPropsMode(True)
    reader.SetSHUOMode(True)
    reader.SetViewMode(False)
    read_status = reader.ReadFile(str(source))
    if read_status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise AssertionError(f"negative-control read failed: {read_status.name}")
    if not reader.Transfer(document):
        raise AssertionError("negative-control XCAF transfer failed")

    if not STEPControl_Controller.Init_s():
        raise AssertionError("negative-control STEP controller init failed")
    previous_schema = Interface_Static.IVal_s("write.step.schema")
    messenger = Message.DefaultMessenger_s()
    printer_sequence = messenger.Printers()
    printers = (
        []
        if printer_sequence.IsEmpty()
        else [
            printer_sequence.Value(index)
            for index in range(
                printer_sequence.Lower(), printer_sequence.Upper() + 1
            )
        ]
    )
    try:
        if not Interface_Static.SetIVal_s("write.step.schema", 5):
            raise AssertionError("negative-control AP242 selection failed")
        for printer in printers:
            messenger.RemovePrinter(printer)

        writer = STEPCAFControl_Writer()
        writer.SetDimTolMode(False)
        writer.SetMaterialMode(True)
        writer.SetNameMode(True)
        writer.SetColorMode(True)
        writer.SetLayerMode(True)
        writer.SetPropsMode(True)
        writer.SetSHUOMode(True)
        if not writer.Transfer(
            document,
            STEPControl_StepModelType.STEPControl_AsIs,
        ):
            raise AssertionError("negative-control AP242 transfer failed")
        write_status = writer.Write(str(output))
        if write_status != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise AssertionError(
                f"negative-control AP242 write failed: {write_status.name}"
            )
    finally:
        Interface_Static.SetIVal_s("write.step.schema", previous_schema)
        for printer in printers:
            messenger.AddPrinter(printer)

    if not output.is_file():
        raise AssertionError("negative-control writer produced no derivative")


def _build_duplicate_authored_parts(output_dir: Path) -> Path:
    """Place tracked authored parts into a temporary three-part assembly."""
    output_step = output_dir / "duplicate-authored-parts.step"
    spec_path = output_dir / "duplicate-authored-parts.yaml"
    spec_path.write_text(
        f"""schema_version: assembly_spec.v0.1
meta:
  project: roundtrip-selector-test
  assembly_id: duplicate-authored-parts
outputs:
  step: {output_step.as_posix()}
  views_dir: {(output_dir / 'views').as_posix()}
instances:
  - id: rail_a
    role: rail
    source_path: {AUTHORED_RAIL.as_posix()}
    transform:
      translate_mm: [0.0, 0.0, 0.0]
  - id: rail_b
    role: rail
    source_path: {AUTHORED_RAIL.as_posix()}
    transform:
      translate_mm: [0.0, 100.0, 0.0]
  - id: plate
    role: plate
    source_path: {AUTHORED_PLATE.as_posix()}
    transform:
      translate_mm: [700.0, 0.0, 0.0]
""",
        encoding="utf-8",
    )
    report = run_assembly_build(spec_path, dry_run=False)
    if report.overall == Severity.FAIL or not output_step.is_file():
        raise AssertionError("temporary authored-part placement did not build")
    return output_step


class TestNistRoundtripIntegration(unittest.TestCase):
    def test_real_ap242_export_reimport_preserves_geometry_and_pmi(self):
        with tempfile.TemporaryDirectory() as tmp:
            derivative = Path(tmp) / "nist-ftc-11-roundtrip.stp"
            exported = export_ap242(NIST_FTC_11, derivative)
            comparison = compare_roundtrip_artifacts(NIST_FTC_11, derivative)

            self.assertTrue(derivative.is_file())
            self.assertIn("AP242", exported.output_schema.upper())
            self.assertIn(
                exported.write_status,
                {"IFSelect_RetDone", "IFSelect_RetError"},
            )
            self.assertEqual(
                exported.write_disposition,
                {
                    "IFSelect_RetDone": "ret_done",
                    "IFSelect_RetError": (
                        "ret_error_provisionally_validated"
                    ),
                }[exported.write_status],
            )
            self.assertTrue(
                comparison.passed,
                [finding.to_dict() for finding in comparison.findings],
            )
            self.assertEqual(comparison.pmi_status, "compared")
            self.assertEqual(
                {
                    item.pmi_class: (item.before_count, item.after_count, item.status)
                    for item in comparison.pmi_results
                },
                {
                    name: (count, count, "preserved")
                    for name, count in EXPECTED_FTC_11_PMI.items()
                },
            )
            public_summary = comparison.to_dict()
            self.assertNotIn("geometry_before", public_summary)
            self.assertNotIn("geometry_after", public_summary)
            self.assertNotIn("findings", public_summary)
            pmi_summary = public_summary[
                "supported_semantic_pmi_class_counts"
            ]
            self.assertEqual(pmi_summary["status"], "compared")
            self.assertEqual(
                pmi_summary["scope"],
                "supported_semantic_class_counts_only",
            )
            self.assertEqual(
                {
                    item["class"]: (
                        item["before_count"],
                        item["after_count"],
                        item["status"],
                    )
                    for item in pmi_summary["results"]
                },
                {
                    name: (count, count, "preserved")
                    for name, count in EXPECTED_FTC_11_PMI.items()
                },
            )

            source_geometry = snapshot_geometry(NIST_FTC_11)
            derivative_geometry = snapshot_geometry(derivative)
            self.assertGreater(source_geometry.part_count, 0)
            self.assertEqual(
                source_geometry.part_count,
                derivative_geometry.part_count,
            )
            for before, after in zip(
                source_geometry.assembly_bbox_mm,
                derivative_geometry.assembly_bbox_mm,
            ):
                self.assertAlmostEqual(before, after, places=6)

            self.assertEqual(
                extract_semantic_pmi(NIST_FTC_11).counts,
                EXPECTED_FTC_11_PMI,
            )
            self.assertEqual(
                extract_semantic_pmi(derivative).counts,
                EXPECTED_FTC_11_PMI,
            )

    def test_ret_error_artifact_is_provisional_and_scoped_checks_stay_decisive(self):
        from OCP.IFSelect import IFSelect_ReturnStatus
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_Controller
        from cadclaw_cli.main import main

        stepcaf_module = importlib.import_module("OCP.STEPCAFControl")
        underlying_statuses: list[str] = []

        def force_ret_error_after_real_write(writer, output):
            status = writer.Write(str(output))
            underlying_statuses.append(status.name)
            return IFSelect_ReturnStatus.IFSelect_RetError

        writer_type = _writer_with_write_override(
            force_ret_error_after_real_write
        )
        self.assertTrue(STEPControl_Controller.Init_s())
        pre_test_schema = Interface_Static.IVal_s("write.step.schema")
        with tempfile.TemporaryDirectory() as tmp:
            derivative = Path(tmp) / "forced-ret-error-ftc11.stp"
            stdout = io.StringIO()
            try:
                self.assertTrue(
                    Interface_Static.SetIVal_s("write.step.schema", 3)
                )
                printers_before = _occt_default_messenger_printer_count()
                with (
                    mock.patch.object(
                        stepcaf_module,
                        "STEPCAFControl_Writer",
                        writer_type,
                    ),
                    redirect_stdout(stdout),
                ):
                    code = main([
                        "roundtrip-step",
                        "--rules",
                        str(NIST_FTC_11.parent / "cadclaw.yaml"),
                        "--step",
                        str(NIST_FTC_11),
                        "--roundtrip-out",
                        str(derivative),
                        "--report-format",
                        "json",
                    ])

                self.assertEqual(
                    Interface_Static.IVal_s("write.step.schema"),
                    3,
                )
                self.assertEqual(
                    _occt_default_messenger_printer_count(),
                    printers_before,
                )
            finally:
                restored = Interface_Static.SetIVal_s(
                    "write.step.schema",
                    pre_test_schema,
                )
                if not restored:
                    raise AssertionError(
                        "test could not restore its pre-test OCCT STEP schema"
                    )

            self.assertTrue(derivative.is_file())
            self.assertIn(
                underlying_statuses,
                [
                    ["IFSelect_RetDone"],
                    ["IFSelect_RetError"],
                ],
            )
            self.assertEqual(code, 0, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["overall"], "pass")
            derivative_meta = payload["meta"]["derivative"]
            self.assertEqual(
                derivative_meta["write_status"],
                "IFSelect_RetError",
            )
            self.assertEqual(
                derivative_meta["write_disposition"],
                "ret_error_provisionally_validated",
            )
            self.assertNotIn("source_path", derivative_meta)
            self.assertNotIn("output_path", derivative_meta)

            self.assertNotIn(
                "roundtrip.write.ret_error_provisionally_validated",
                {finding["id"] for finding in payload["findings"]},
            )
            self.assertIn(
                "ROUNDTRIP_STEP: OCCT writer-internal reference integrity "
                "and graphical PMI after provisionally validated "
                "error-status recovery",
                payload["confidence_budget"]["not_checked"],
            )

            pmi_summary = payload["meta"]["translation_comparison"][
                "supported_semantic_pmi_class_counts"
            ]
            self.assertEqual(pmi_summary["status"], "compared")
            self.assertEqual(
                {
                    item["class"]: (
                        item["before_count"],
                        item["after_count"],
                        item["status"],
                    )
                    for item in pmi_summary["results"]
                },
                {
                    name: (count, count, "preserved")
                    for name, count in EXPECTED_FTC_11_PMI.items()
                },
            )

    def test_ret_error_rejects_missing_non_ap242_and_malformed_ap242_artifacts(self):
        from OCP.IFSelect import IFSelect_ReturnStatus

        stepcaf_module = importlib.import_module("OCP.STEPCAFControl")

        def missing_artifact(writer, output):
            writer.Write(str(output))
            output.unlink()
            return IFSelect_ReturnStatus.IFSelect_RetError

        def empty_artifact(writer, output):
            writer.Write(str(output))
            output.write_bytes(b"")
            return IFSelect_ReturnStatus.IFSelect_RetError

        def non_ap242_artifact(writer, output):
            writer.Write(str(output))
            output.write_bytes(AUTHORED_RAIL.read_bytes())
            return IFSelect_ReturnStatus.IFSelect_RetError

        def malformed_ap242_artifact(writer, output):
            writer.Write(str(output))
            output.write_text(
                """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('malformed fixture'),'2;1');
FILE_NAME('malformed','','','','','','');
FILE_SCHEMA(('AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF'));
ENDSEC;
DATA;
#1=THIS_IS_NOT_VALID_STEP_SYNTAX(
ENDSEC;
END-ISO-10303-21;
""",
                encoding="utf-8",
            )
            return IFSelect_ReturnStatus.IFSelect_RetError

        cases = (
            (
                "missing",
                missing_artifact,
                "OCCT IFSelect_RetError did not produce a non-empty derivative",
            ),
            (
                "empty",
                empty_artifact,
                "OCCT IFSelect_RetError did not produce a non-empty derivative",
            ),
            (
                "non-ap242",
                non_ap242_artifact,
                "OCCT IFSelect_RetError derivative is not AP242",
            ),
            (
                "malformed-ap242",
                malformed_ap242_artifact,
                "OCCT IFSelect_RetError AP242 derivative could not be "
                "reimported into XCAF",
            ),
        )
        for name, write_override, expected_message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / f"private-{name}.stp"
                writer_type = _writer_with_write_override(write_override)
                printers_before = _occt_default_messenger_printer_count()
                with mock.patch.object(
                    stepcaf_module,
                    "STEPCAFControl_Writer",
                    writer_type,
                ):
                    with self.assertRaises(RoundtripError) as caught:
                        export_ap242(AUTHORED_RAIL, output)

                self.assertEqual(caught.exception.code, "roundtrip.write_failed")
                self.assertEqual(str(caught.exception), expected_message)
                self.assertNotIn(str(output), str(caught.exception))
                self.assertNotIn(str(AUTHORED_RAIL), str(caught.exception))
                if name == "malformed-ap242":
                    self.assertIsInstance(
                        caught.exception.__cause__,
                        RoundtripError,
                    )
                    self.assertIn(
                        caught.exception.__cause__.code,
                        {
                            "roundtrip.read_failed",
                            "roundtrip.transfer_failed",
                        },
                    )
                    self.assertNotIn(
                        str(output),
                        str(caught.exception.__cause__),
                    )
                self.assertEqual(
                    _occt_default_messenger_printer_count(),
                    printers_before,
                )

    def test_provisional_ret_error_does_not_override_comparison_failure(self):
        # A deliberately mismatched writer model/artifact is isolated because
        # OCCT's process-global transfer session is outside this gate's public
        # contract and would otherwise contaminate unrelated later exporters.
        script = r"""
import importlib
import json
from pathlib import Path
import sys
from unittest import mock
from OCP.IFSelect import IFSelect_ReturnStatus
from cadclaw.roundtrip import run_roundtrip_step

stepcaf_module = importlib.import_module("OCP.STEPCAFControl")
real_writer_type = stepcaf_module.STEPCAFControl_Writer

class SubstituteWriter:
    def __init__(self, *args, **kwargs):
        self._inner = real_writer_type(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def Write(self, output_path):
        self._inner.Write(output_path)
        Path(output_path).write_bytes(Path(sys.argv[2]).read_bytes())
        return IFSelect_ReturnStatus.IFSelect_RetError

with mock.patch.object(
    stepcaf_module,
    "STEPCAFControl_Writer",
    SubstituteWriter,
):
    report = run_roundtrip_step(sys.argv[1], output_path=sys.argv[3])
print(json.dumps(report.to_dict()))
"""
        with tempfile.TemporaryDirectory() as tmp:
            derivative = Path(tmp) / "substituted-valid-ap242.stp"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(NIST_FTC_11),
                    str(NIST_STC_06),
                    str(derivative),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(derivative.is_file())
            payload = json.loads(completed.stdout)

        self.assertEqual(payload["overall"], "fail")
        self.assertEqual(
            payload["meta"]["derivative"]["write_status"],
            "IFSelect_RetError",
        )
        self.assertEqual(
            payload["meta"]["derivative"]["write_disposition"],
            "ret_error_provisionally_validated",
        )
        failed_ids = {
            finding["id"]
            for finding in payload["findings"]
            if finding["severity"] == "fail"
        }
        self.assertTrue(
            {
                "roundtrip.translation.pmi.dimensions.changed",
                "roundtrip.translation.pmi.geometric_tolerances.changed",
                "roundtrip.translation.pmi.datums.changed",
            }.issubset(failed_ids)
        )
        self.assertTrue(
            {
                "roundtrip.translation.assembly_bbox.changed",
                "roundtrip.translation.assembly_bbox_volume.changed",
                "roundtrip.translation.per_part_geometry.changed",
            }.intersection(failed_ids)
        )

    def test_ret_error_artifact_unreadable_failure_is_path_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "private-unreadable-artifact.stp"
            output.write_bytes(b"non-empty")
            injected_diagnostic = f"could not stat {output}"
            with mock.patch.object(
                Path,
                "lstat",
                side_effect=OSError(injected_diagnostic),
            ):
                with self.assertRaises(RoundtripError) as caught:
                    roundtrip_module._validate_ret_error_artifact(output)

        self.assertEqual(caught.exception.code, "roundtrip.write_failed")
        self.assertEqual(
            str(caught.exception),
            "OCCT IFSelect_RetError validation could not read the derivative "
            "artifact",
        )
        self.assertNotIn(str(output), str(caught.exception))
        self.assertNotIn(injected_diagnostic, str(caught.exception))

    def test_non_done_non_error_writer_statuses_always_fail(self):
        from OCP.IFSelect import IFSelect_ReturnStatus

        stepcaf_module = importlib.import_module("OCP.STEPCAFControl")
        statuses = (
            IFSelect_ReturnStatus.IFSelect_RetVoid,
            IFSelect_ReturnStatus.IFSelect_RetFail,
            IFSelect_ReturnStatus.IFSelect_RetStop,
        )
        for forced_status in statuses:
            with (
                self.subTest(status=forced_status.name),
                tempfile.TemporaryDirectory() as tmp,
            ):
                output = Path(tmp) / f"valid-but-{forced_status.name}.stp"

                def override_status_after_real_write(
                    writer,
                    output_path,
                    status=forced_status,
                ):
                    writer.Write(str(output_path))
                    return status

                writer_type = _writer_with_write_override(
                    override_status_after_real_write
                )
                with mock.patch.object(
                    stepcaf_module,
                    "STEPCAFControl_Writer",
                    writer_type,
                ), mock.patch.object(
                    roundtrip_module,
                    "_validate_ret_error_artifact",
                ) as validator:
                    with self.assertRaises(RoundtripError) as caught:
                        export_ap242(AUTHORED_RAIL, output)

                validator.assert_not_called()
                self.assertTrue(output.is_file())
                self.assertEqual(caught.exception.code, "roundtrip.write_failed")
                self.assertEqual(
                    str(caught.exception),
                    f"OCCT AP242 write failed (status {forced_status.name})",
                )
                self.assertNotIn(str(output), str(caught.exception))
                self.assertNotIn(str(AUTHORED_RAIL), str(caught.exception))

    def test_real_dimtol_disabled_export_is_detected_as_pmi_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "nist-ftc-11-dimtol-disabled.stp"
            _export_ap242_without_semantic_pmi(NIST_FTC_11, broken)

            self.assertEqual(
                extract_semantic_pmi(NIST_FTC_11).counts,
                EXPECTED_FTC_11_PMI,
            )
            self.assertEqual(
                extract_semantic_pmi(broken).counts,
                {name: 0 for name in EXPECTED_FTC_11_PMI},
            )

            source_geometry = snapshot_geometry(NIST_FTC_11)
            broken_geometry = snapshot_geometry(broken)
            self.assertEqual(source_geometry.part_count, broken_geometry.part_count)
            for before, after in zip(
                source_geometry.assembly_bbox_mm,
                broken_geometry.assembly_bbox_mm,
            ):
                self.assertAlmostEqual(before, after, places=6)

            comparison = compare_roundtrip_artifacts(NIST_FTC_11, broken)
            self.assertFalse(comparison.passed)
            self.assertEqual(comparison.pmi_status, "compared")
            self.assertEqual(
                {item.pmi_class: item.after_count for item in comparison.pmi_results},
                {name: 0 for name in EXPECTED_FTC_11_PMI},
            )
            failed_ids = {
                finding.id
                for finding in comparison.findings
                if finding.severity == Severity.FAIL
            }
            self.assertEqual(
                failed_ids,
                {
                    "roundtrip.translation.pmi.dimensions.changed",
                    "roundtrip.translation.pmi.geometric_tolerances.changed",
                    "roundtrip.translation.pmi.datums.changed",
                },
            )


class TestRoundtripScopeAndSafety(unittest.TestCase):
    def test_unknown_source_and_missing_proxy_are_explicitly_not_applicable(self):
        created_directories: list[Path] = []
        real_temporary_directory = tempfile.TemporaryDirectory

        class TrackingTemporaryDirectory(real_temporary_directory):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created_directories.append(Path(self.name))

        with mock.patch(
            "cadclaw.roundtrip.tempfile.TemporaryDirectory",
            TrackingTemporaryDirectory,
        ):
            report = run_roundtrip_step(AUTHORED_RAIL)

        self.assertTrue(report.passed, [item.to_dict() for item in report.findings])
        self.assertEqual(
            report.meta["translation_independence"],
            {
                "status": "not_applicable",
                "declared_family": "unknown",
                "verified": False,
                "reason": (
                    "source translator is unknown; kernel independence was not "
                    "established"
                ),
            },
        )
        self.assertEqual(
            report.meta["authoring_proxy_comparison"],
            {
                "status": "not_applicable",
                "reason": "no authoring-reference STEP proxy was supplied",
            },
        )
        self.assertNotIn("source_path", report.meta["derivative"])
        self.assertNotIn("output_path", report.meta["derivative"])
        self.assertFalse(report.meta["derivative"]["persisted"])
        self.assertEqual(
            report.meta["derivative"]["temporary_cleanup"],
            "complete",
        )
        self.assertTrue(created_directories)
        self.assertTrue(all(not path.exists() for path in created_directories))

    def test_declared_non_occt_source_is_claimed_only_as_unverified_declaration(self):
        config = RoundtripConfig(
            source_translator=SourceTranslator(
                family="non_occt",
                name="Declared external CAD translator",
                version="fixture declaration",
            )
        )
        report = run_roundtrip_step(AUTHORED_RAIL, config=config)
        self.assertTrue(report.passed, [item.to_dict() for item in report.findings])
        self.assertEqual(
            report.meta["translation_independence"],
            {
                "status": "declared_independent",
                "declared_family": "non_occt",
                "name": "Declared external CAD translator",
                "version": "fixture declaration",
                "verified": False,
                "reason": (
                    "a non-OCCT source translator was declared; provenance was "
                    "not independently verified"
                ),
            },
        )

    def test_missing_and_ambiguous_interface_selectors_are_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            assembly = _build_duplicate_authored_parts(Path(tmp))
            plate = PartSelector(signature_mm=(10.0, 120.0, 120.0))
            config = RoundtripConfig(interface_pairs=(
                InterfacePair(
                    id="missing-part",
                    a=PartSelector(signature_mm=(1.0, 2.0, 3.0)),
                    b=plate,
                ),
                InterfacePair(
                    id="ambiguous-rail",
                    a=PartSelector(signature_mm=(40.0, 40.0, 600.0)),
                    b=plate,
                ),
            ))
            comparison = compare_roundtrip_artifacts(
                assembly,
                assembly,
                config=config,
            )

        self.assertFalse(comparison.passed)
        failed_ids = {
            finding.id
            for finding in comparison.findings
            if finding.severity == Severity.FAIL
        }
        self.assertIn("roundtrip.selector_missing", failed_ids)
        self.assertIn("roundtrip.selector_ambiguous", failed_ids)
        self.assertEqual(
            {
                result.id: (
                    result.status,
                    result.error_code,
                    result.before_gap_mm,
                    result.after_gap_mm,
                    result.delta_mm,
                )
                for result in comparison.interface_results
            },
            {
                "missing-part": (
                    "error",
                    "roundtrip.selector_missing",
                    None,
                    None,
                    None,
                ),
                "ambiguous-rail": (
                    "error",
                    "roundtrip.selector_ambiguous",
                    None,
                    None,
                    None,
                ),
            },
        )

    def test_declared_interface_pair_survives_real_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assembly = _build_duplicate_authored_parts(root)
            derivative = root / "duplicate-authored-parts-roundtrip.stp"
            export_ap242(assembly, derivative)

            pair = InterfacePair(
                id="rail-a-to-plate",
                a=PartSelector(
                    label="rail",
                    near_mm=(300.0, 20.0, 20.0),
                    max_center_distance_mm=0.01,
                ),
                b=PartSelector(
                    label="plate",
                    near_mm=(705.0, 60.0, 60.0),
                    max_center_distance_mm=0.01,
                ),
                tolerance_mm=0.01,
            )
            comparison = compare_roundtrip_artifacts(
                assembly,
                derivative,
                config=RoundtripConfig(interface_pairs=(pair,)),
                label_signatures={
                    "rail": (40.0, 40.0, 600.0),
                    "plate": (10.0, 120.0, 120.0),
                },
            )

        self.assertTrue(
            comparison.passed,
            [finding.to_dict() for finding in comparison.findings],
        )
        self.assertEqual(len(comparison.interface_results), 1)
        result = comparison.interface_results[0]
        self.assertEqual(result.id, "rail-a-to-plate")
        self.assertAlmostEqual(result.before_gap_mm, 100.0, places=6)
        self.assertAlmostEqual(result.after_gap_mm, 100.0, places=6)
        self.assertAlmostEqual(result.delta_mm, 0.0, places=6)
        self.assertEqual(result.tolerance_mm, 0.01)
        self.assertEqual(result.status, "preserved")
        pair_findings = [
            finding
            for finding in comparison.findings
            if finding.id
            == "roundtrip.translation.interface.rail-a-to-plate.preserved"
        ]
        self.assertEqual(len(pair_findings), 1)
        self.assertEqual(pair_findings[0].severity, Severity.PASS)

    def test_minimum_cost_part_matching_handles_sort_boundary_crossing(self):
        def part(index, bbox):
            dimensions = (
                bbox[3] - bbox[0],
                bbox[4] - bbox[1],
                bbox[5] - bbox[2],
            )
            return PartGeometry(
                index=index,
                bbox_mm=bbox,
                center_mm=tuple(
                    (bbox[axis] + bbox[axis + 3]) / 2.0
                    for axis in range(3)
                ),
                signature_mm=tuple(sorted(round(value, 1) for value in dimensions)),
                bbox_volume_mm3=(
                    dimensions[0] * dimensions[1] * dimensions[2]
                ),
            )

        part_a_before = part(0, (0.0, 0.0, 0.0, 10.0, 1.0, 1.0))
        part_b_before = part(1, (0.001, 100.0, 0.0, 2.001, 101.0, 1.0))
        # A 0.002-mm translation across nearly equal leading bbox coordinates
        # reverses the loader's lexicographic order without changing identity.
        part_b_after = part(0, (-0.001, 100.0, 0.0, 1.999, 101.0, 1.0))
        part_a_after = part(1, (0.002, 0.0, 0.0, 10.002, 1.0, 1.0))
        before = GeometrySnapshot(
            step_path="before.stp",
            part_count=2,
            assembly_bbox_mm=(0.0, 0.0, 0.0, 10.0, 101.0, 1.0),
            assembly_bbox_volume_mm3=1010.0,
            parts=(part_a_before, part_b_before),
        )
        after = GeometrySnapshot(
            step_path="after.stp",
            part_count=2,
            assembly_bbox_mm=(-0.001, 0.0, 0.0, 10.002, 101.0, 1.0),
            assembly_bbox_volume_mm3=1010.303,
            parts=(part_b_after, part_a_after),
        )
        config = RoundtripConfig(
            bbox_tolerance_mm=0.01,
            bbox_volume_relative_tolerance=0.0,
            bbox_volume_absolute_tolerance_mm3=1.0,
        )

        assignment = roundtrip_module._minimum_cost_part_matching(
            before.parts,
            after.parts,
        )
        findings, summary = roundtrip_module._compare_geometry(
            before,
            after,
            config,
            "translation",
        )

        self.assertEqual(assignment, ((0, 1), (1, 0)))
        per_part = [
            finding
            for finding in findings
            if finding.id == "roundtrip.translation.per_part_geometry.preserved"
        ]
        self.assertEqual(len(per_part), 1)
        self.assertEqual(per_part[0].severity, Severity.PASS)
        per_part_summary = summary["per_part_geometry"]
        self.assertEqual(per_part_summary["status"], "preserved")
        self.assertEqual(
            per_part_summary["matching_strategy"],
            "minimum_cost_one_to_one",
        )
        self.assertEqual(per_part_summary["matched_parts"], 2)
        self.assertAlmostEqual(
            per_part_summary["max_bbox_delta_mm"],
            0.002,
            places=12,
        )
        self.assertEqual(per_part_summary["max_bbox_volume_delta_mm3"], 0.0)
        self.assertEqual(
            per_part_summary["maximum_matched_renderable_shapes"],
            roundtrip_module._MAX_MATCHED_RENDERABLE_SHAPES,
        )

    def test_matching_limit_refuses_before_cost_matrix_and_is_path_free(self):
        limit = roundtrip_module._MAX_MATCHED_RENDERABLE_SHAPES
        unit_part = PartGeometry(
            index=0,
            bbox_mm=(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            center_mm=(0.5, 0.5, 0.5),
            signature_mm=(1.0, 1.0, 1.0),
            bbox_volume_mm3=1.0,
        )
        oversized_parts = (unit_part,) * (limit + 1)
        before = GeometrySnapshot(
            step_path=r"C:\private\submitted-before.step",
            part_count=limit + 1,
            assembly_bbox_mm=(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            assembly_bbox_volume_mm3=1.0,
            parts=oversized_parts,
        )
        after = GeometrySnapshot(
            step_path=r"C:\private\derivative-after.step",
            part_count=limit + 1,
            assembly_bbox_mm=(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            assembly_bbox_volume_mm3=1.0,
            parts=oversized_parts,
        )

        with mock.patch.object(roundtrip_module, "_part_match_cost") as cost:
            with self.assertRaises(RoundtripError) as caught:
                roundtrip_module._compare_geometry(
                    before,
                    after,
                    RoundtripConfig(),
                    "translation",
                )

        cost.assert_not_called()
        self.assertEqual(
            caught.exception.code,
            "roundtrip.part_count_limit_exceeded",
        )
        self.assertIn(str(limit), str(caught.exception))
        self.assertIn(str(limit + 1), str(caught.exception))
        self.assertNotIn(before.step_path, str(caught.exception))
        self.assertNotIn(after.step_path, str(caught.exception))

    def test_matching_limit_allows_boundary_before_matrix_construction(self):
        class CostMatrixConstructionReached(Exception):
            pass

        limit = roundtrip_module._MAX_MATCHED_RENDERABLE_SHAPES
        unit_part = PartGeometry(
            index=0,
            bbox_mm=(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
            center_mm=(0.5, 0.5, 0.5),
            signature_mm=(1.0, 1.0, 1.0),
            bbox_volume_mm3=1.0,
        )
        boundary_parts = (unit_part,) * limit

        with mock.patch.object(
            roundtrip_module,
            "_part_match_cost",
            side_effect=CostMatrixConstructionReached,
        ) as cost:
            with self.assertRaises(CostMatrixConstructionReached):
                roundtrip_module._minimum_cost_part_matching(
                    boundary_parts,
                    boundary_parts,
                )

        cost.assert_called_once_with(unit_part, unit_part)

    def test_malformed_geometry_reader_restores_default_messenger_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            malformed_proxy = Path(tmp) / "malformed-authoring-proxy.step"
            malformed_proxy.write_text(
                "not a STEP exchange file",
                encoding="utf-8",
            )
            printers_before = _occt_default_messenger_printer_count()
            with self.assertRaises(RoundtripError) as caught:
                roundtrip_module._load_geometry(malformed_proxy)
            printers_after = _occt_default_messenger_printer_count()

        self.assertEqual(caught.exception.code, "roundtrip.geometry_import_failed")
        self.assertEqual(printers_after, printers_before)
        self.assertNotIn(str(malformed_proxy), str(caught.exception))

    def test_public_report_meta_is_bounded_path_free_and_uses_proxy_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            proxy = Path(tmp) / "private-authoring-reference-proxy.step"
            proxy.write_bytes(AUTHORED_RAIL.read_bytes())
            expected_submitted_sha256 = hashlib.sha256(
                AUTHORED_RAIL.read_bytes()
            ).hexdigest()
            expected_proxy_sha256 = hashlib.sha256(proxy.read_bytes()).hexdigest()
            config = RoundtripConfig(
                authoring_reference_step_proxy=str(proxy),
            )
            self.assertTrue(hasattr(config, "authoring_reference_step_proxy"))
            report = run_roundtrip_step(AUTHORED_RAIL, config=config)

        self.assertTrue(report.passed, [item.to_dict() for item in report.findings])
        payload = report.to_dict()
        meta = payload["meta"]
        self.assertIn("translation_comparison", meta)
        self.assertIn("authoring_proxy_comparison", meta)
        self.assertNotIn("authoring_comparison", meta)
        self.assertEqual(
            meta["method_limits"]["part_matching"],
            {
                "strategy": "minimum_cost_one_to_one",
                "maximum_matched_renderable_shapes": (
                    roundtrip_module._MAX_MATCHED_RENDERABLE_SHAPES
                ),
                "limit_behavior": (
                    "structured_error_before_cost_matrix_allocation"
                ),
            },
        )
        self.assertEqual(
            meta["authoring_proxy_comparison"]["phase"],
            "proxy_comparison",
        )
        self.assertEqual(
            meta["authoring_proxy_comparison"]["artifacts"],
            {
                "authoring_reference_step_proxy_sha256": (
                    expected_proxy_sha256
                ),
                "submitted_step_sha256": expected_submitted_sha256,
            },
        )

        public_meta_keys = _nested_keys(meta)
        self.assertTrue({
            "geometry_before",
            "geometry_after",
            "parts",
            "findings",
            "source_step",
            "source_path",
            "output_path",
            "proxy_path",
            "submitted_step_path",
        }.isdisjoint(public_meta_keys))
        self.assertFalse({
            key for key in public_meta_keys if key.endswith("_path")
        })
        for public_string in _nested_strings(payload):
            self.assertNotIn(str(AUTHORED_RAIL), public_string)
            self.assertNotIn(str(proxy), public_string)
        self.assertGreater(len(payload["findings"]), 0)
        self.assertIn(
            "supported_semantic_pmi_class_counts",
            meta["translation_comparison"],
        )

    def test_hashing_oserror_is_path_free_in_public_error_report(self):
        original_open = Path.open
        sensitive_path = str(AUTHORED_RAIL)

        def fail_submitted_step_hash(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get("mode", "r")
            if Path(path) == AUTHORED_RAIL and mode == "rb":
                raise OSError(f"hashing failed for {sensitive_path}")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", new=fail_submitted_step_hash):
            report = run_roundtrip_step(AUTHORED_RAIL)

        self.assertFalse(report.passed)
        failed = [
            finding
            for finding in report.findings
            if finding.id == "roundtrip.input_unreadable"
        ]
        self.assertEqual(len(failed), 1)
        self.assertEqual(
            failed[0].message,
            "could not read the STEP artifact for hashing",
        )
        public_strings = _nested_strings(report.to_dict())
        for public_string in public_strings:
            self.assertNotIn(sensitive_path, public_string)
            self.assertNotIn("hashing failed for", public_string)

    def test_ap242_export_restores_occt_global_schema_and_messenger_state(self):
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_Controller

        self.assertTrue(STEPControl_Controller.Init_s())
        pre_test_schema = Interface_Static.IVal_s("write.step.schema")
        try:
            self.assertTrue(
                Interface_Static.SetIVal_s("write.step.schema", 3)
            )
            self.assertEqual(
                Interface_Static.IVal_s("write.step.schema"),
                3,
            )
            printers_before = _occt_default_messenger_printer_count()

            with tempfile.TemporaryDirectory() as tmp:
                derivative = Path(tmp) / "global-state-roundtrip.stp"
                export_ap242(AUTHORED_RAIL, derivative)
                self.assertTrue(derivative.is_file())

            self.assertEqual(
                Interface_Static.IVal_s("write.step.schema"),
                3,
            )
            self.assertEqual(
                _occt_default_messenger_printer_count(),
                printers_before,
            )
        finally:
            restored = Interface_Static.SetIVal_s(
                "write.step.schema",
                pre_test_schema,
            )
            if not restored:
                raise AssertionError(
                    "test could not restore its pre-test OCCT STEP schema"
                )

    def test_export_refuses_source_and_existing_output_without_overwriting(self):
        with self.assertRaises(RoundtripError) as same_path:
            export_ap242(AUTHORED_RAIL, AUTHORED_RAIL)
        self.assertEqual(same_path.exception.code, "roundtrip.output_is_source")

        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing.stp"
            sentinel = b"existing output must survive"
            existing.write_bytes(sentinel)
            with self.assertRaises(RoundtripError) as occupied:
                export_ap242(AUTHORED_RAIL, existing)
            self.assertEqual(occupied.exception.code, "roundtrip.output_exists")
            self.assertEqual(existing.read_bytes(), sentinel)

    def test_focused_cli_json_exit_code_and_stdout_are_clean(self):
        script = (
            "import sys; "
            "from cadclaw_cli.main import main; "
            "raise SystemExit(main(sys.argv[1:]))"
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                "roundtrip-step",
                "--rules",
                str((NIST_FTC_11.parent / "cadclaw.yaml").resolve()),
                "--step",
                str(AUTHORED_RAIL),
                "--report-format",
                "json",
            ],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                "round-trip writer polluted JSON stdout: "
                f"{exc}; stdout prefix={completed.stdout[:160]!r}"
            )
        self.assertEqual(payload["meta"]["gate"], "ROUNDTRIP_STEP")
        self.assertEqual(payload["meta"]["derivative"]["temporary_cleanup"], "complete")
        self.assertNotIn(
            str((NIST_FTC_11.parent / "cadclaw.yaml").resolve()),
            completed.stdout,
        )

    def test_malformed_step_failure_still_emits_one_json_document(self):
        script = (
            "import sys; "
            "from cadclaw_cli.main import main; "
            "raise SystemExit(main(sys.argv[1:]))"
        )
        with tempfile.TemporaryDirectory() as tmp:
            malformed = Path(tmp) / "malformed.stp"
            malformed.write_text("not a STEP exchange file", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    "roundtrip-step",
                    "--rules",
                    "tests/fixtures/pmi_semantic/cadclaw.yaml",
                    "--step",
                    str(malformed),
                    "--report-format",
                    "json",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                "round-trip reader polluted JSON stdout on failure: "
                f"{exc}; stdout prefix={completed.stdout[:160]!r}"
            )
        self.assertEqual(payload["overall"], "fail")
        self.assertEqual(payload["meta"]["applicability"], "error")
        self.assertNotIn(str(malformed), completed.stdout)

    def test_malformed_authoring_proxy_still_emits_one_json_document(self):
        script = (
            "import sys; "
            "from cadclaw_cli.main import main; "
            "raise SystemExit(main(sys.argv[1:]))"
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            malformed_proxy = tmp_path / "malformed-proxy.stp"
            malformed_proxy.write_text(
                "not a STEP exchange file",
                encoding="utf-8",
            )
            rules = tmp_path / "cadclaw.yaml"
            rules.write_text(
                "\n".join([
                    'schema_version: "0.9"',
                    "meta:",
                    "  project: malformed-proxy-test",
                    f'  step: "{AUTHORED_RAIL.as_posix()}"',
                    "roundtrip_step:",
                    "  enabled: true",
                    "  authoring_reference_step_proxy: "
                    f'"{malformed_proxy.as_posix()}"',
                    "",
                ]),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    script,
                    "roundtrip-step",
                    "--rules",
                    str(rules),
                    "--report-format",
                    "json",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                "authoring-proxy reader polluted JSON stdout: "
                f"{exc}; stdout prefix={completed.stdout[:160]!r}"
            )
        self.assertEqual(payload["overall"], "fail")
        self.assertEqual(
            payload["meta"]["authoring_proxy_comparison"]["status"],
            "error",
        )
        self.assertNotIn(str(malformed_proxy), completed.stdout)
        self.assertNotIn(str(rules), completed.stdout)

    def test_harness_disabled_does_not_call_roundtrip_or_export(self):
        from cadclaw_cli.main import main

        stdout = io.StringIO()
        with (
            mock.patch("cadclaw.roundtrip.run_roundtrip_step") as runner,
            mock.patch("cadclaw.roundtrip.export_ap242") as exporter,
            redirect_stdout(stdout),
        ):
            code = main([
                "harness",
                "--rules",
                "tests/fixtures/pmi_semantic/cadclaw.yaml",
                "--only",
                "roundtrip_step",
                "--report-format",
                "json",
            ])

        self.assertEqual(code, 0)
        runner.assert_not_called()
        exporter.assert_not_called()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["meta"]["applicability"], "not_applicable")

    def test_harness_enabled_only_returns_nested_bounded_roundtrip_meta(self):
        from cadclaw_cli.main import main

        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp) / "cadclaw.yaml"
            rules.write_text(
                f"""schema_version: "0.9"
meta:
  project: roundtrip-harness-test
  step: "{AUTHORED_RAIL.as_posix()}"
roundtrip_step:
  enabled: true
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "harness",
                    "--rules",
                    str(rules),
                    "--only",
                    "roundtrip_step",
                    "--report-format",
                    "json",
                ])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["meta"]["applicability"], "applicable")
        nested = payload["meta"]["roundtrip_step"]
        self.assertIn("translation_comparison", nested)
        self.assertEqual(
            nested["authoring_proxy_comparison"]["status"],
            "not_applicable",
        )
        self.assertTrue({
            "geometry_before",
            "geometry_after",
            "parts",
            "findings",
            "source_step",
            "source_path",
            "output_path",
        }.isdisjoint(_nested_keys(nested)))

    def test_cadharness_roundtrip_alias_is_same_module(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            old_module = importlib.import_module("cadharness.roundtrip")
            new_module = importlib.import_module("cadclaw.roundtrip")
        self.assertIs(old_module, new_module)


if __name__ == "__main__":
    unittest.main()
