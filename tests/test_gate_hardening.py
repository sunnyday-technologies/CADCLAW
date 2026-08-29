"""Focused regressions for fail-closed gate and redaction boundaries."""
from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import traceback
import types
import unittest
from unittest import mock

from cadclaw.bbox import GeometryBoundingBoxError
from cadclaw.claim_audit import DEFAULT_FORBIDDEN_ABSOLUTES, run_claim_audit
from cadclaw.color_check import ColorCheck
from cadclaw.harness import run_configured_harness
from cadclaw.interference import InterferenceCheck
from cadclaw.inventory import InventoryCheck
from cadclaw.orientation import OrientationCheck
from cadclaw.floating import FloatingCheck
from cadclaw.publish_audit import GitClassificationError, run_publish_audit
from cadclaw.render import (
    StepColorReadError,
    _extract_step_colors,
    _step_color_dim_sig,
)
from cadclaw.reporters import render_json, render_markdown, render_text
from cadclaw.rules import (
    ClaimAuditModel,
    LabelSpec,
    PublishAuditModel,
    RuleSet,
    RulesConfigError,
    load_rules_safe,
)
from cadclaw_cli.main import main
from cadclaw_mcp import server as mcp_server


PRIVATE_MARKER = "PRIVATE_RULE_VALUE_MARKER"
PRIVATE_KEY_MARKER = "PRIVATE_DYNAMIC_KEY_MARKER"


class _Box:
    def __init__(self, values):
        (
            self.xmin,
            self.ymin,
            self.zmin,
            self.xmax,
            self.ymax,
            self.zmax,
        ) = values


class _Part:
    wrapped = object()

    def __init__(self, values):
        self._values = values

    def BoundingBox(self):
        return _Box(self._values)


def _serialized(report) -> str:
    return "\n".join((
        render_text(report, color=False),
        render_markdown(report),
        render_json(report),
    ))


class TestSafeRulesBoundary(unittest.TestCase):
    def _write(self, root: Path, body: str, name: str = "rules.yaml") -> Path:
        path = root / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_validation_projection_redacts_values_keys_and_exception_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                Path(tmp),
                'schema_version: "0.9"\n'
                f'{PRIVATE_KEY_MARKER}: "{PRIVATE_MARKER}"\n'
                'labels:\n'
                f'  {PRIVATE_KEY_MARKER}:\n'
                f'    sig: [1, "{PRIVATE_MARKER}"]\n',
            )
            with self.assertRaises(RulesConfigError) as caught:
                load_rules_safe(path)

        exc = caught.exception
        rendered = "".join(traceback.format_exception(exc))
        projection = json.dumps(exc.to_dict())
        for marker in (PRIVATE_MARKER, PRIVATE_KEY_MARKER):
            self.assertNotIn(marker, str(exc))
            self.assertNotIn(marker, rendered)
            self.assertNotIn(marker, projection)
        self.assertEqual(exc.reason_code, "rules.validation_failed")
        self.assertEqual(exc.stage, "validation")
        self.assertGreaterEqual(exc.error_count, 1)
        self.assertTrue(any("<item>" in location for location in exc.locations))
        self.assertIsNone(exc.__cause__)
        self.assertIsNone(exc.__context__)

    def test_yaml_projection_exposes_only_numeric_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                Path(tmp),
                'schema_version: "0.9"\n'
                f'meta: {{description: "{PRIVATE_MARKER}\n',
            )
            with self.assertRaises(RulesConfigError) as caught:
                load_rules_safe(path)
        payload = json.dumps(caught.exception.to_dict())
        self.assertNotIn(PRIVATE_MARKER, payload)
        self.assertEqual(caught.exception.reason_code, "rules.yaml_invalid")
        self.assertIsInstance(caught.exception.line, int)
        self.assertIsInstance(caught.exception.column, int)

    def test_unexpected_rule_processing_error_is_fixed_and_context_free(self):
        with mock.patch(
            "cadclaw.rules.load_rules",
            side_effect=RecursionError(PRIVATE_MARKER),
        ):
            with self.assertRaises(RulesConfigError) as caught:
                load_rules_safe("private-rules.yaml")
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertEqual(
            caught.exception.reason_code,
            "rules.processing_failed",
        )
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_library_and_cli_config_reports_are_redacted_and_exit_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules_path = self._write(
                root,
                'schema_version: "0.9"\n'
                f'{PRIVATE_KEY_MARKER}: "{PRIVATE_MARKER}"\n',
            )
            report = run_configured_harness(rules_path, only=["claim_audit"])
            self.assertEqual(
                report.meta["gate_registry"]["aggregate_status"],
                "error",
            )
            self.assertEqual(report.meta["gate_registry"]["gates"], [])
            self.assertNotIn(PRIVATE_MARKER, _serialized(report))
            self.assertNotIn(PRIVATE_KEY_MARKER, _serialized(report))

            for output_format in ("text", "md", "json"):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    code = main([
                        "claim-audit",
                        "--rules", str(rules_path),
                        "--report-format", output_format,
                    ])
                self.assertEqual(code, 3)
                self.assertNotIn(PRIVATE_MARKER, stdout.getvalue())
                self.assertNotIn(PRIVATE_KEY_MARKER, stdout.getvalue())

            output_path = root / "safe-report.json"
            code = main([
                "harness",
                "--rules", str(rules_path),
                "--report-format", "json",
                "--out", str(output_path),
            ])
            self.assertEqual(code, 3)
            stored = output_path.read_text(encoding="utf-8")
            self.assertNotIn(PRIVATE_MARKER, stored)
            self.assertNotIn(PRIVATE_KEY_MARKER, stored)

    def test_every_rules_path_mcp_tool_uses_typed_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules_path = self._write(
                Path(tmp),
                'schema_version: "0.9"\n'
                f'{PRIVATE_KEY_MARKER}: "{PRIVATE_MARKER}"\n',
            )
            for tool_name in (
                "run_harness",
                "check_bom_against_cad",
                "check_publish_boundary",
                "check_claims",
                "check_region_inventory",
            ):
                response = mcp_server.handle_request({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": tool_name,
                        "arguments": {"rules_path": str(rules_path)},
                    },
                })
                rendered = json.dumps(response)
                self.assertNotIn(PRIVATE_MARKER, rendered)
                self.assertNotIn(PRIVATE_KEY_MARKER, rendered)
                self.assertNotIn("traceback", rendered.lower())
                self.assertIn("rules_configuration_error", rendered)

    def test_mcp_unexpected_error_envelope_is_fixed(self):
        def _raise(_arguments):
            raise RuntimeError(PRIVATE_MARKER)

        with mock.patch.dict(mcp_server.TOOL_HANDLERS, {"private_probe": _raise}):
            response = mcp_server.handle_request({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "private_probe", "arguments": {}},
            })
        rendered = json.dumps(response)
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn("traceback", rendered.lower())
        self.assertIn("mcp.unexpected_error", rendered)

    def test_gate_execution_error_omits_exception_type_rules_path_and_project(self):
        private_exception = type(PRIVATE_KEY_MARKER, (RuntimeError,), {})
        with tempfile.TemporaryDirectory() as tmp:
            rules_path = Path(tmp) / f"{PRIVATE_MARKER}.yaml"
            rules_path.write_text(
                'schema_version: "0.9"\n'
                f'meta:\n  project: "{PRIVATE_KEY_MARKER}"\n'
                'claim_audit:\n  scan_paths: [README.md]\n',
                encoding="utf-8",
            )
            with mock.patch(
                "cadclaw.claim_audit.run_claim_audit",
                side_effect=private_exception(PRIVATE_MARKER),
            ):
                report = run_configured_harness(
                    rules_path,
                    only=["claim_audit"],
                )
        rendered = _serialized(report)
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn(PRIVATE_KEY_MARKER, rendered)
        self.assertNotIn("exception_type", rendered)
        self.assertNotIn("rules", report.meta)
        self.assertNotIn("project", report.meta)

    def test_selector_errors_never_echo_submitted_id(self):
        from cadclaw.gate_registry import (
            GateSelectionError,
            HARNESS_GATE_REGISTRY,
        )

        with self.assertRaises(GateSelectionError) as caught:
            HARNESS_GATE_REGISTRY.resolve(only=[PRIVATE_MARKER])
        self.assertNotIn(PRIVATE_MARKER, str(caught.exception))
        self.assertEqual(caught.exception.reason_code, "unknown_gate")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = main([
                "harness",
                "--rules", "unused.yaml",
                "--only", PRIVATE_MARKER,
            ])
        self.assertEqual(code, 3)
        self.assertNotIn(PRIVATE_MARKER, stderr.getvalue())

        response = mcp_server.tool_run_harness(
            "unused.yaml",
            only=[PRIVATE_MARKER],
        )
        self.assertNotIn(PRIVATE_MARKER, json.dumps(response))

    def test_selector_iterable_exception_is_fixed_and_context_free(self):
        from cadclaw.gate_registry import (
            GateSelectionError,
            HARNESS_GATE_REGISTRY,
        )

        def _exploding_selector():
            yield "inventory"
            raise RuntimeError(PRIVATE_MARKER)

        with self.assertRaises(GateSelectionError) as caught:
            HARNESS_GATE_REGISTRY.resolve(only=_exploding_selector())
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

        response = mcp_server.tool_run_harness(
            "unused.yaml",
            only=_exploding_selector(),
        )
        self.assertNotIn(PRIVATE_MARKER, json.dumps(response))

    def test_selector_string_subclass_is_canonicalized_before_set_use(self):
        from cadclaw.gate_registry import HARNESS_GATE_REGISTRY

        class _HostileString(str):
            __hash__ = str.__hash__

            def strip(self):
                return self

            def __eq__(self, _other):
                raise RuntimeError(PRIVATE_MARKER)

        selection = HARNESS_GATE_REGISTRY.resolve(
            only=[_HostileString("inventory")],
        )
        self.assertEqual(selection.selected_ids, ("inventory",))

        response = mcp_server.tool_run_harness(
            "unused.yaml",
            only=[_HostileString("inventory")],
        )
        self.assertNotIn(PRIVATE_MARKER, json.dumps(response))


class TestClaimAndPublishEvidence(unittest.TestCase):
    def test_valid_claim_terms_and_evidence_tags_are_not_echoed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "claims.md").write_text(
                f"{PRIVATE_MARKER} 42 mm\n",
                encoding="utf-8",
            )
            rules = RuleSet(claim_audit=ClaimAuditModel(
                scan_paths=["claims.md"],
                forbidden_absolutes_extra=[PRIVATE_MARKER],
                stale_terms=[PRIVATE_MARKER],
                evidence_tags_required_for=[r"\b42\s*mm\b"],
                evidence_tags_allowed=[PRIVATE_KEY_MARKER],
            ))
            report = run_claim_audit(rules, repo_root=str(root))

        rendered = _serialized(report)
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn(PRIVATE_KEY_MARKER, rendered)
        self.assertTrue(any(
            finding.id == "claim.forbidden_absolute"
            and finding.evidence.get("rule_ordinal")
                == len(DEFAULT_FORBIDDEN_ABSOLUTES) + 1
            for finding in report.findings
        ))
        self.assertTrue(any(
            finding.id == "claim.stale_term"
            and finding.evidence.get("rule_ordinal") == 1
            for finding in report.findings
        ))
        self.assertTrue(any(
            finding.id == "claim.untagged_numeric"
            for finding in report.findings
        ))

    def test_top_level_manifest_description_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(
                json.dumps({
                    "description": "This is a production-ready assembly.",
                    "objects": [{"notes": "decision support only"}],
                }),
                encoding="utf-8",
            )
            rules = RuleSet(claim_audit=ClaimAuditModel(
                scan_paths=["manifest.json"],
            ))
            report = run_claim_audit(rules, repo_root=str(root))
        self.assertTrue(any(
            finding.id == "claim.forbidden_absolute"
            for finding in report.findings
        ))
        self.assertEqual(report.meta["files_scanned"], 1)

    def test_valid_json_without_claim_fields_is_execution_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(
                json.dumps({"objects": [{"mass": 4.2}]}),
                encoding="utf-8",
            )
            rules = RuleSet(claim_audit=ClaimAuditModel(
                scan_paths=["manifest.json"],
            ))
            report = run_claim_audit(rules, repo_root=str(root))
        self.assertEqual(report.meta["files_scanned"], 0)
        self.assertEqual(report.meta["execution_status"], "error")
        self.assertTrue(any(
            finding.id == "claim.no_scannable_claim_fields"
            for finding in report.findings
        ))

    def test_invalid_claim_regex_is_redacted_typed_error(self):
        rules = RuleSet(claim_audit=ClaimAuditModel(
            scan_paths=["README.md"],
            evidence_tags_required_for=[f"(?P<{PRIVATE_KEY_MARKER}>{PRIVATE_MARKER}"],
        ))
        report = run_claim_audit(rules, repo_root=".")
        rendered = _serialized(report)
        self.assertEqual(report.meta["execution_status"], "error")
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn(PRIVATE_KEY_MARKER, rendered)
        self.assertTrue(any(
            finding.id == "claim.bad_numeric_pattern"
            and "pattern_ordinal" in finding.evidence
            for finding in report.findings
        ))

    def test_valid_source_rule_redacts_configured_message_and_pattern(self):
        rules = RuleSet(claim_audit=ClaimAuditModel(
            source_regex_rules=[{
                "pattern": "class TestClaimAndPublishEvidence",
                "severity": "warn",
                "message": PRIVATE_MARKER,
                "file_glob": "tests/test_gate_hardening.py",
            }],
        ))
        report = run_claim_audit(rules, repo_root=".")
        rendered = _serialized(report)
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn("class TestClaimAndPublishEvidence", rendered)
        finding = next(
            finding for finding in report.findings
            if finding.id == "claim.source_regex"
        )
        self.assertEqual(finding.evidence["kind"], "source_regex")
        self.assertEqual(finding.evidence["rule_ordinal"], 1)

    def test_invalid_publish_regex_is_redacted_typed_error(self):
        rules = RuleSet(publish_audit=PublishAuditModel(
            scan_globs=["README.md"],
            redact_patterns={
                PRIVATE_KEY_MARKER: f"(?P<{PRIVATE_KEY_MARKER}>{PRIVATE_MARKER}"
            },
        ))
        with mock.patch(
            "cadclaw.publish_audit._classify_files",
            return_value=({}, []),
        ):
            report = run_publish_audit(rules, repo_root=".")
        rendered = _serialized(report)
        self.assertEqual(report.meta["execution_status"], "error")
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn(PRIVATE_KEY_MARKER, rendered)
        finding = next(
            finding for finding in report.findings
            if finding.id == "publish.bad_pattern"
        )
        self.assertIn("pattern_ordinal", finding.evidence)
        self.assertNotIn("pattern", finding.evidence)
        self.assertNotIn("kind", finding.evidence)

    def test_each_failed_git_lane_is_an_execution_error_even_with_files(self):
        def _git(args, _repo):
            if args[:2] == ["diff", "--cached"]:
                raise GitClassificationError("unknown")
            if "--others" in args:
                return ["LOCAL.md"]
            return ["README.md"]

        rules = RuleSet(publish_audit=PublishAuditModel(
            ignore_globs=["private/**"],
        ))
        with mock.patch("cadclaw.publish_audit._git", side_effect=_git):
            report = run_publish_audit(rules, repo_root=".")
        self.assertGreater(report.meta["n_tracked"], 0)
        self.assertEqual(report.meta["git_classification_error_lanes"], ["staged"])
        self.assertEqual(report.meta["execution_status"], "error")
        self.assertTrue(any(
            finding.id == "publish.git_classification_error"
            and finding.evidence["lane"] == "staged"
            for finding in report.findings
        ))

    def test_valid_publish_match_redacts_dynamic_key_and_operational_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = "README.md"
            (root / relative).write_text(PRIVATE_MARKER, encoding="utf-8")
            rules = RuleSet(publish_audit=PublishAuditModel(
                scan_globs=["*.md"],
                redact_patterns={PRIVATE_KEY_MARKER: PRIVATE_MARKER},
            ))
            with mock.patch(
                "cadclaw.publish_audit._classify_files",
                return_value=({relative: "committed"}, []),
            ):
                report = run_publish_audit(rules, repo_root=str(root))
        rendered = _serialized(report)
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn(PRIVATE_KEY_MARKER, rendered)
        finding = next(
            finding for finding in report.findings
            if finding.id == "publish.scan_match"
        )
        self.assertEqual(finding.evidence["kind"], "redact_pattern")
        self.assertEqual(finding.evidence["pattern_ordinal"], 1)

    def test_claim_and_publish_operational_errors_omit_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim_name = f"{PRIVATE_MARKER}.json"
            (root / claim_name).write_text("{}", encoding="utf-8")
            claim_rules = RuleSet(claim_audit=ClaimAuditModel(
                scan_paths=[claim_name],
            ))
            with mock.patch(
                "cadclaw.claim_audit._scan_json_notes",
                return_value=([], "error"),
            ):
                claim = run_claim_audit(claim_rules, repo_root=str(root))

            publish_name = f"{PRIVATE_KEY_MARKER}.md"
            (root / publish_name).write_text("safe", encoding="utf-8")
            publish_rules = RuleSet(publish_audit=PublishAuditModel(
                scan_globs=["*.md"],
                redact_patterns={"fixed": "safe"},
            ))
            with mock.patch(
                "cadclaw.publish_audit._classify_files",
                return_value=({publish_name: "committed"}, []),
            ), mock.patch(
                "cadclaw.publish_audit._scan_file_for_patterns",
                return_value=([], False),
            ):
                publish = run_publish_audit(
                    publish_rules,
                    repo_root=str(root),
                )

        for report in (claim, publish):
            rendered = _serialized(report)
            self.assertNotIn(PRIVATE_MARKER, rendered)
            self.assertNotIn(PRIVATE_KEY_MARKER, rendered)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("repo", report.meta)

    def test_claim_invalid_utf8_and_deep_json_are_typed_scan_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            invalid_name = f"{PRIVATE_MARKER}-utf8.json"
            (root / invalid_name).write_bytes(b"\xff")
            depth = sys.getrecursionlimit() + 50
            deep_name = f"{PRIVATE_KEY_MARKER}-deep.json"
            (root / deep_name).write_text(
                "[" * depth
                + '{"description":"safe"}'
                + "]" * depth,
                encoding="utf-8",
            )
            rules = RuleSet(claim_audit=ClaimAuditModel(
                scan_paths=[invalid_name, deep_name],
            ))
            report = run_claim_audit(rules, repo_root=str(root))

        rendered = _serialized(report)
        self.assertEqual(report.meta["execution_status"], "error")
        self.assertEqual(report.meta["scan_error_count"], 2)
        self.assertEqual(
            sum(finding.id == "claim.scan_error" for finding in report.findings),
            2,
        )
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn(PRIVATE_KEY_MARKER, rendered)
        self.assertNotIn("repo", report.meta)

    def test_focused_cli_missing_file_error_omits_submitted_path(self):
        stderr = io.StringIO()
        private_path = f"C:/private/{PRIVATE_MARKER}.step"
        with mock.patch(
            "cadclaw.parity.compare_steps",
            side_effect=FileNotFoundError(private_path),
        ), contextlib.redirect_stderr(stderr):
            code = main(["parity", private_path, "other.step"])
        self.assertEqual(code, 3)
        self.assertNotIn(PRIVATE_MARKER, stderr.getvalue())


class TestColorPmiAndBoundingBoxes(unittest.TestCase):
    def test_color_reader_failure_is_typed_but_no_metadata_is_missing_warn(self):
        specs = {
            "plate": LabelSpec(sig=[1, 2, 3], expected_color="#969F00"),
        }
        with mock.patch(
            "cadclaw.render._extract_step_colors",
            side_effect=StepColorReadError("color.read_failed"),
        ):
            with self.assertRaises(StepColorReadError) as caught:
                ColorCheck("private-input.step", specs).run()
        self.assertNotIn("private-input.step", str(caught.exception))

        with mock.patch("cadclaw.render._extract_step_colors", return_value={}):
            result = ColorCheck("fixture.step", specs).run()
        self.assertTrue(result.passed)
        self.assertEqual(result.checked, 1)
        self.assertEqual(len(result.missing), 1)

    def test_strict_color_bbox_and_traversal_errors_are_typed(self):
        with self.assertRaises(StepColorReadError) as bbox_error:
            _step_color_dim_sig(object(), strict=True)
        self.assertEqual(bbox_error.exception.code, "color.bbox_failed")
        self.assertIsNone(_step_color_dim_sig(object(), strict=False))

        done = object()
        reader = mock.Mock()
        reader.ReadFile.return_value = done
        reader.Transfer.return_value = True
        document = mock.Mock()

        modules = {}
        definitions = {
            "OCP.STEPCAFControl": {"STEPCAFControl_Reader": lambda: reader},
            "OCP.IFSelect": {
                "IFSelect_ReturnStatus": types.SimpleNamespace(
                    IFSelect_RetDone=done,
                ),
            },
            "OCP.TDocStd": {"TDocStd_Document": lambda _name: document},
            "OCP.TCollection": {
                "TCollection_ExtendedString": lambda value: value,
            },
            "OCP.XCAFDoc": {
                "XCAFDoc_DocumentTool": types.SimpleNamespace(
                    ShapeTool_s=mock.Mock(side_effect=RuntimeError(PRIVATE_MARKER)),
                    ColorTool_s=mock.Mock(),
                ),
                "XCAFDoc_ColorType": object(),
            },
            "OCP.TDF": {"TDF_LabelSequence": mock.Mock},
            "OCP.Quantity": {"Quantity_Color": mock.Mock},
        }
        for name, attributes in definitions.items():
            module = types.ModuleType(name)
            for key, value in attributes.items():
                setattr(module, key, value)
            modules[name] = module

        with mock.patch.dict(sys.modules, modules):
            with self.assertRaises(StepColorReadError) as traversal_error:
                _extract_step_colors("private.step", strict=True)
            self.assertEqual(
                traversal_error.exception.code,
                "color.traversal_failed",
            )
            self.assertNotIn(PRIVATE_MARKER, str(traversal_error.exception))
            self.assertEqual(_extract_step_colors("private.step"), {})

        class _BadCount:
            def __add__(self, _other):
                raise RuntimeError(PRIVATE_MARKER)

        class _BadSequence:
            def Length(self):
                return _BadCount()

        shape_tool = mock.Mock()
        malformed_modules = dict(modules)
        malformed_tdf = types.ModuleType("OCP.TDF")
        malformed_tdf.TDF_LabelSequence = _BadSequence
        malformed_modules["OCP.TDF"] = malformed_tdf
        malformed_xcaf = types.ModuleType("OCP.XCAFDoc")
        malformed_xcaf.XCAFDoc_DocumentTool = types.SimpleNamespace(
            ShapeTool_s=mock.Mock(return_value=shape_tool),
            ColorTool_s=mock.Mock(return_value=mock.Mock()),
        )
        malformed_xcaf.XCAFDoc_ColorType = object()
        malformed_modules["OCP.XCAFDoc"] = malformed_xcaf

        with mock.patch.dict(sys.modules, malformed_modules):
            with self.assertRaises(StepColorReadError) as count_error:
                _extract_step_colors("private.step", strict=True)
        self.assertEqual(
            count_error.exception.code,
            "color.traversal_failed",
        )
        self.assertNotIn(PRIVATE_MARKER, str(count_error.exception))

    def test_configured_color_reader_failure_is_aggregate_error_and_cli_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules_path = Path(tmp) / "rules.yaml"
            rules_path.write_text(
                'schema_version: "0.9"\n'
                'meta:\n  step: fixture.step\n'
                'labels:\n'
                '  plate:\n'
                '    sig: [1, 2, 3]\n'
                '    expected_color: "#969F00"\n',
                encoding="utf-8",
            )
            with mock.patch(
                "cadclaw.render._extract_step_colors",
                side_effect=StepColorReadError("color.read_failed"),
            ):
                report = run_configured_harness(
                    rules_path,
                    only=["color"],
                )
            self.assertEqual(
                report.meta["gate_registry"]["status_gate_ids"]["error"],
                ["color"],
            )
            with mock.patch(
                "cadclaw.render._extract_step_colors",
                side_effect=StepColorReadError("color.read_failed"),
            ), contextlib.redirect_stdout(io.StringIO()):
                code = main([
                    "harness",
                    "--rules", str(rules_path),
                    "--only", "color",
                    "--report-format", "json",
                ])
            self.assertEqual(code, 3)

            with mock.patch(
                "cadclaw.render._extract_step_colors",
                return_value={},
            ):
                missing = run_configured_harness(
                    rules_path,
                    only=["color"],
                )
            self.assertEqual(
                missing.meta["gate_registry"]["status_gate_ids"]["warn"],
                ["color"],
            )

    def test_pmi_input_errors_redact_reader_text_and_submitted_path(self):
        from cadclaw.pmi import PmiExtractionError, run_pmi_present

        private_path = f"C:/private/{PRIVATE_MARKER}.stp"
        with mock.patch(
            "cadclaw.pmi.extract_semantic_pmi",
            side_effect=PmiExtractionError("pmi.read_failed", PRIVATE_MARKER),
        ):
            report = run_pmi_present(private_path, ["dimensions"])
        rendered = _serialized(report)
        self.assertNotIn(PRIVATE_MARKER, rendered)
        self.assertNotIn(private_path, rendered)
        self.assertEqual(report.findings[0].evidence["reason_code"], "pmi.read_failed")

    def test_all_registered_geometry_paths_reject_nonfinite_or_inverted_bbox(self):
        bad_values = (
            (0, 0, 0, math.nan, 1, 1),
            (0, 0, 0, math.inf, 1, 1),
            (2, 0, 0, 1, 1, 1),
        )
        specs = {"part": LabelSpec(sig=[1, 1, 1], expected_face="YZ")}
        for values in bad_values:
            part = _Part(values)
            with self.subTest(values=values, gate="inventory"):
                with self.assertRaises(GeometryBoundingBoxError):
                    InventoryCheck("unused", {}, {}).run(parts=[part])
            with self.subTest(values=values, gate="interference"):
                with self.assertRaises(GeometryBoundingBoxError):
                    InterferenceCheck([part, _Part((0, 0, 0, 1, 1, 1))],
                                      lambda _part: "part").run()
            with self.subTest(values=values, gate="orientation"):
                with self.assertRaises(GeometryBoundingBoxError):
                    OrientationCheck([part], lambda _part: "part", specs).run()
            with self.subTest(values=values, gate="floating"):
                with self.assertRaises(GeometryBoundingBoxError):
                    FloatingCheck(
                        [part, _Part((0, 0, 0, 1, 1, 1))],
                        lambda candidate: "anchor" if candidate is not part else "part",
                        structural_labels={"anchor"},
                    ).run()

    def test_malformed_interference_bbox_is_harness_aggregate_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules_path = Path(tmp) / "rules.yaml"
            rules_path.write_text(
                'schema_version: "0.9"\n'
                'meta:\n  step: fixture.step\n'
                'labels:\n  part: [1, 1, 1]\n'
                'interference: {}\n',
                encoding="utf-8",
            )
            parts = [
                _Part((0, 0, 0, math.nan, 1, 1)),
                _Part((0, 0, 0, 1, 1, 1)),
            ]
            with mock.patch(
                "cadclaw.inventory.load_and_dedup",
                return_value=parts,
            ):
                report = run_configured_harness(
                    rules_path,
                    only=["interference"],
                )
        registry = report.meta["gate_registry"]
        self.assertEqual(registry["aggregate_status"], "error")
        self.assertEqual(registry["status_gate_ids"]["error"], ["interference"])
        finding = next(
            finding for finding in report.findings
            if finding.id == "harness.gate_execution_error"
        )
        self.assertEqual(
            finding.evidence["reason_code"],
            "harness.gate_execution_failed",
        )
        self.assertNotIn("exception_type", finding.evidence)


if __name__ == "__main__":
    unittest.main()
