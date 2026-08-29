"""Fail-closed selector and YAML union-harness gate accounting tests."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cadclaw.bbox import GeometryBoundingBoxError
from cadclaw.findings import Report
from cadclaw.gate_registry import GateSelectionError, HARNESS_GATE_REGISTRY
from cadclaw.harness import run_configured_harness
from cadclaw.interference import (
    InterferenceCheck,
    InterferenceExecutionError,
    InterferenceResult,
)
from cadclaw_cli.main import main


class TestGateRegistry(unittest.TestCase):
    def test_version_one_registry_contract_is_frozen(self):
        self.assertEqual(HARNESS_GATE_REGISTRY.version, "harness-gates.v1")
        self.assertEqual(HARNESS_GATE_REGISTRY.ids, (
            "inventory",
            "interference",
            "bom_audit",
            "claim_audit",
            "publish_audit",
            "pmi_present",
            "roundtrip_step",
            "orientation",
            "floating",
            "color",
        ))

    def test_selection_is_normalized_in_registry_order(self):
        selection = HARNESS_GATE_REGISTRY.resolve(
            only=" color, inventory,interference ",
        )
        self.assertEqual(
            selection.selected_ids,
            ("inventory", "interference", "color"),
        )
        self.assertTrue(selection.wants("interference"))
        self.assertFalse(selection.wants("floating"))

    def test_unknown_only_and_skip_are_rejected(self):
        for kwargs in (
            {"only": "inventory,does_not_exist"},
            {"only": "Inventory"},
            {"skip": "does_not_exist"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(GateSelectionError):
                    HARNESS_GATE_REGISTRY.resolve(**kwargs)

    def test_blank_tokens_are_rejected(self):
        for value in ("", " ", ",", "inventory,", ",inventory"):
            with self.subTest(value=value):
                with self.assertRaises(GateSelectionError):
                    HARNESS_GATE_REGISTRY.resolve(only=value)

    def test_overlap_and_all_skipped_are_rejected(self):
        with self.assertRaises(GateSelectionError):
            HARNESS_GATE_REGISTRY.resolve(
                only="inventory,interference",
                skip="interference",
            )
        with self.assertRaises(GateSelectionError):
            HARNESS_GATE_REGISTRY.resolve(
                skip=",".join(HARNESS_GATE_REGISTRY.ids),
            )

    def test_selection_errors_have_stable_reason_codes(self):
        cases = (
            ({"only": []}, "empty_selector"),
            ({"only": "inventory,"}, "empty_gate_id"),
            ({"only": "inventory,inventory"}, "duplicate_gate"),
            ({"only": "missing"}, "unknown_gate"),
            ({"only": "inventory", "skip": "inventory"},
             "overlapping_selectors"),
            ({"skip": list(HARNESS_GATE_REGISTRY.ids)}, "empty_selection"),
        )
        for kwargs, reason_code in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(GateSelectionError) as caught:
                    HARNESS_GATE_REGISTRY.resolve(**kwargs)
                self.assertEqual(caught.exception.reason_code, reason_code)


class TestInterferenceExecutionErrors(unittest.TestCase):
    class _BoundingBox:
        xmin = 0.0
        ymin = 0.0
        zmin = 0.0
        xmax = 10.0
        ymax = 10.0
        zmax = 10.0

    class _Solid:
        wrapped = object()

        def BoundingBox(self):
            return TestInterferenceExecutionErrors._BoundingBox()

    def test_native_boolean_error_fails_without_exposing_exception_text(self):
        check = InterferenceCheck(
            [self._Solid(), self._Solid()],
            lambda _part: "fixture",
        )
        with patch(
            "OCP.BRepAlgoAPI.BRepAlgoAPI_Common",
            side_effect=RuntimeError("sensitive-host-detail"),
        ):
            result = check.run()

        self.assertFalse(result.passed)
        self.assertEqual(result.checked_pairs, 1)
        self.assertEqual(result.error_count, 1)
        self.assertEqual(result.clips, [])

        from cadclaw.harness import _interference_findings
        findings = _interference_findings(result)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].id, "interference.execution_error")
        self.assertEqual(findings[0].severity.value, "fail")
        self.assertNotIn("sensitive-host-detail", findings[0].message)
        self.assertNotIn("sensitive-host-detail", str(findings[0].evidence))

    def test_native_boolean_not_done_is_an_execution_error(self):
        check = InterferenceCheck(
            [self._Solid(), self._Solid()],
            lambda _part: "fixture",
        )
        common = SimpleNamespace(Build=lambda: None, IsDone=lambda: False)
        with patch(
            "OCP.BRepAlgoAPI.BRepAlgoAPI_Common",
            return_value=common,
        ):
            result = check.run()

        self.assertFalse(result.passed)
        self.assertEqual(result.checked_pairs, 1)
        self.assertEqual(result.error_count, 1)

    def test_one_eligible_part_is_not_a_vacuous_pass(self):
        result = InterferenceCheck(
            [self._Solid()],
            lambda _part: "fixture",
        ).run()
        self.assertFalse(result.passed)
        self.assertEqual(result.eligible_parts, 1)
        self.assertEqual(result.not_checked_reason, "fewer than two eligible parts")

    def test_label_errors_are_results_and_bbox_errors_are_typed(self):
        label_result = InterferenceCheck(
            [self._Solid(), self._Solid()],
            lambda _part: (_ for _ in ()).throw(
                RuntimeError("sensitive-label-detail")
            ),
        ).run()
        self.assertFalse(label_result.passed)
        self.assertEqual(label_result.error_count, 2)

        class _BadBBox(self._Solid):
            def BoundingBox(self):
                raise RuntimeError("sensitive-bbox-detail")

        with self.assertRaises(GeometryBoundingBoxError) as caught:
            InterferenceCheck(
                [_BadBBox(), self._Solid()],
                lambda _part: "fixture",
            ).run()
        self.assertNotIn("sensitive", str(caught.exception))


class TestHarnessGateSelection(unittest.TestCase):
    @staticmethod
    def _write_rules(root: Path, body: str) -> Path:
        path = root / "cadclaw.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_unknown_json_selector_returns_structured_code_3_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = self._write_rules(
                Path(tmp),
                'schema_version: "0.9"\n',
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "harness",
                    "--rules", str(rules),
                    "--only", "inventory,does_not_exist",
                    "--report-format", "json",
                ])

        self.assertEqual(code, 3)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["overall"], "fail")
        self.assertEqual(payload["meta"]["error"], "invalid_gate_selection")
        self.assertEqual(
            payload["findings"][0]["id"],
            "harness.invalid_gate_selection",
        )

    def test_unknown_text_skip_returns_code_3_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = self._write_rules(
                Path(tmp),
                'schema_version: "0.9"\n',
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "harness",
                    "--rules", str(rules),
                    "--skip", "does_not_exist",
                ])

        self.assertEqual(code, 3)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn(
            "gate selector contains an unknown identity",
            stderr.getvalue(),
        )
        self.assertNotIn("not-a-gate", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_explicit_unconfigured_gate_fails_instead_of_empty_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = self._write_rules(
                Path(tmp),
                'schema_version: "0.9"\n',
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "harness",
                    "--rules", str(rules),
                    "--only", "inventory",
                    "--report-format", "json",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["overall"], "fail")
        self.assertEqual(payload["confidence_budget"]["checked"], [])
        registry = payload["meta"]["gate_registry"]
        self.assertEqual(registry["requested_gate_ids"], ["inventory"])
        self.assertEqual(registry["checked_gate_ids"], [])
        self.assertEqual(registry["not_checked_gate_ids"], ["inventory"])
        self.assertTrue(any(
            finding["id"] == "harness.requested_gate_not_checked"
            for finding in payload["findings"]
        ))

    def test_partial_explicit_selection_cannot_hide_an_unchecked_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = self._write_rules(
                root,
                """schema_version: "0.9"
claim_audit:
  scan_paths: [README.md]
""",
            )
            stdout = io.StringIO()
            with patch(
                "cadclaw.claim_audit.run_claim_audit",
                return_value=Report(meta={"files_scanned": 1}),
            ):
                with redirect_stdout(stdout):
                    code = main([
                        "harness",
                        "--rules", str(rules),
                        "--repo", str(root),
                        "--only", "claim_audit,interference",
                        "--report-format", "json",
                    ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["overall"], "fail")
        registry = payload["meta"]["gate_registry"]
        self.assertEqual(registry["checked_gate_ids"], ["claim_audit"])
        self.assertEqual(registry["not_checked_gate_ids"], ["interference"])

    def test_default_run_fails_when_configured_gate_lacks_prerequisite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = self._write_rules(
                root,
                """schema_version: "0.9"
interference: {}
claim_audit:
  scan_paths: [README.md]
""",
            )
            stdout = io.StringIO()
            with patch(
                "cadclaw.claim_audit.run_claim_audit",
                return_value=Report(meta={"files_scanned": 1}),
            ):
                with redirect_stdout(stdout):
                    code = main([
                        "harness",
                        "--rules", str(rules),
                        "--repo", str(root),
                        "--report-format", "json",
                    ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 3)
        self.assertEqual(payload["overall"], "fail")
        registry = payload["meta"]["gate_registry"]
        self.assertEqual(
            registry["configured_gate_ids"],
            ["interference", "claim_audit"],
        )
        self.assertEqual(registry["configured_not_checked_gate_ids"], [])
        self.assertEqual(registry["status_gate_ids"]["error"], [
            "interference",
        ])
        self.assertTrue(any(
            finding["id"] == "harness.gate_prerequisite_missing"
            for finding in payload["findings"]
        ))

    def test_configured_interference_runs_and_is_reported_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = self._write_rules(
                Path(tmp),
                """schema_version: "0.9"
meta:
  step: fixture.step
interference:
  skip_labels: [belt]
  min_volume_mm3: 2.0
  min_clearance_mm: 0.5
""",
            )
            stdout = io.StringIO()
            with (
                patch(
                    "cadclaw.inventory.load_and_dedup",
                    return_value=[object(), object()],
                ),
                patch("cadclaw.inventory.sig", return_value=(1.0, 1.0, 1.0)),
                patch("cadclaw.harness.InterferenceCheck") as check_cls,
                redirect_stdout(stdout),
            ):
                check_cls.return_value.run.return_value = InterferenceResult(
                    passed=True,
                    checked_pairs=0,
                    clips=[],
                )
                code = main([
                    "harness",
                    "--rules", str(rules),
                    "--only", "interference",
                    "--report-format", "json",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["overall"], "pass")
        self.assertEqual(payload["confidence_budget"]["checked"], [
            "interference",
        ])
        registry = payload["meta"]["gate_registry"]
        self.assertEqual(registry["requested_gate_ids"], ["interference"])
        self.assertEqual(registry["checked_gate_ids"], ["interference"])
        self.assertEqual(registry["not_checked_gate_ids"], [])
        _, kwargs = check_cls.call_args
        self.assertEqual(kwargs["skip_labels"], {"belt"})
        self.assertEqual(kwargs["min_volume"], 2.0)
        self.assertEqual(kwargs["min_clearance_mm"], 0.5)

    def test_configured_interference_with_no_pairs_is_not_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = self._write_rules(
                Path(tmp),
                """schema_version: "0.9"
meta:
  step: fixture.step
interference: {}
""",
            )
            stdout = io.StringIO()
            with (
                patch("cadclaw.inventory.load_and_dedup", return_value=[]),
                patch("cadclaw.harness.InterferenceCheck") as check_cls,
                redirect_stdout(stdout),
            ):
                check_cls.return_value.run.return_value = InterferenceResult(
                    passed=False,
                    checked_pairs=0,
                    clips=[],
                    eligible_parts=0,
                    not_checked_reason="fewer than two eligible parts",
                )
                code = main([
                    "harness",
                    "--rules", str(rules),
                    "--only", "interference",
                    "--report-format", "json",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload["meta"]["gate_registry"]["checked_gate_ids"], [])
        self.assertIn(
            "interference (fewer than two eligible parts)",
            payload["confidence_budget"]["not_checked"],
        )

    def test_regions_only_inventory_is_a_configured_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = self._write_rules(
                Path(tmp),
                """schema_version: "0.9"
meta:
  step: fixture.step
regions:
  - name: workcell
    x_range: [0, 100]
    expected: {fixture: 0}
""",
            )
            stdout = io.StringIO()
            with (
                patch("cadclaw.inventory.InventoryCheck") as check_cls,
                redirect_stdout(stdout),
            ):
                check_cls.return_value.run.return_value = SimpleNamespace(
                    mismatches=[],
                    region_results={},
                )
                code = main([
                    "harness",
                    "--rules", str(rules),
                    "--only", "inventory",
                    "--report-format", "json",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["meta"]["gate_registry"]["checked_gate_ids"], [
            "inventory",
        ])


class TestSharedHarnessContract(unittest.TestCase):
    @staticmethod
    def _write_rules(root: Path, body: str) -> Path:
        path = root / "cadclaw.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_library_cli_and_mcp_use_the_same_registry_and_checked_set(self):
        from cadclaw_mcp.server import tool_run_harness

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("bounded claim text\n", encoding="utf-8")
            rules = self._write_rules(
                root,
                'schema_version: "0.9"\nclaim_audit:\n  scan_paths: [README.md]\n',
            )
            library = run_configured_harness(
                rules,
                repo_root=root,
                only=["claim_audit"],
            ).to_dict()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "harness", "--rules", str(rules),
                    "--repo", str(root), "--only", "claim_audit",
                    "--report-format", "json",
                ])
            cli = json.loads(stdout.getvalue())
            mcp = tool_run_harness(
                str(rules),
                repo_root=str(root),
                only=["claim_audit"],
            )

        self.assertEqual(code, 0)
        for payload in (library, cli, mcp):
            registry = payload["meta"]["gate_registry"]
            self.assertEqual(payload["schema_version"], "0.7")
            self.assertEqual(registry["version"], "harness-gates.v1")
            self.assertEqual(registry["selected_gate_ids"], ["claim_audit"])
            self.assertEqual(registry["checked_gate_ids"], ["claim_audit"])
            self.assertEqual(payload["confidence_budget"]["checked"], [
                "claim_audit",
            ])
            self.assertEqual(len(registry["gates"]), len(HARNESS_GATE_REGISTRY.ids))
            self.assertEqual(
                [row["gate_id"] for row in registry["gates"]],
                list(HARNESS_GATE_REGISTRY.ids),
            )
            json.dumps(payload)

    def test_default_claim_audit_behavior_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("safe\n", encoding="utf-8")
            rules = self._write_rules(root, 'schema_version: "0.9"\n')
            report = run_configured_harness(rules, repo_root=root)

        registry = report.meta["gate_registry"]
        self.assertIn("claim_audit", registry["configured_gate_ids"])
        self.assertIn("claim_audit", registry["checked_gate_ids"])

    def test_selected_status_partition_is_disjoint_and_skip_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("safe\n", encoding="utf-8")
            rules = self._write_rules(
                root,
                'schema_version: "0.9"\nclaim_audit:\n  scan_paths: [README.md]\n',
            )
            report = run_configured_harness(
                rules,
                repo_root=root,
                skip=["inventory"],
            )

        registry = report.meta["gate_registry"]
        self.assertEqual(registry["skip_gate_ids"], ["inventory"])
        self.assertEqual(registry["skipped_gate_ids"], ["inventory"])
        partitions = registry["status_gate_ids"]
        flattened = [
            gate_id for gate_ids in partitions.values() for gate_id in gate_ids
        ]
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertEqual(set(flattened), set(registry["selected_gate_ids"]))
        self.assertNotIn("inventory", flattened)
        all_partitions = registry["all_status_gate_ids"]
        all_flattened = [
            gate_id for gate_ids in all_partitions.values() for gate_id in gate_ids
        ]
        self.assertEqual(len(all_flattened), len(set(all_flattened)))
        self.assertEqual(set(all_flattened), set(HARNESS_GATE_REGISTRY.ids))
        excluded = registry["outside_selection_gate_ids"] + registry["skipped_gate_ids"]
        self.assertEqual(len(excluded), len(set(excluded)))
        self.assertEqual(
            set(excluded),
            set(HARNESS_GATE_REGISTRY.ids) - set(registry["selected_gate_ids"]),
        )

    def test_all_selected_not_applicable_is_not_generic_check_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = self._write_rules(
                Path(tmp),
                'schema_version: "0.9"\n',
            )
            report = run_configured_harness(
                rules,
                only=["pmi_present", "roundtrip_step"],
            )

        registry = report.meta["gate_registry"]
        self.assertEqual(report.overall.value, "pass")
        self.assertEqual(report.meta["applicability"], "not_applicable")
        self.assertTrue(registry["all_selected_not_applicable"])
        self.assertEqual(registry["aggregate_status"], "not_applicable")
        self.assertEqual(registry["checked_gate_ids"], [])
        self.assertEqual(registry["status_gate_ids"]["not_applicable"], [
            "pmi_present", "roundtrip_step",
        ])

    def test_missing_step_file_is_typed_redacted_error_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = self._write_rules(
                root,
                'schema_version: "0.9"\nmeta:\n  step: secret-missing.step\n'
                'expected_inventory:\n  fixture: 1\n',
            )
            report = run_configured_harness(rules, only=["inventory"])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "harness", "--rules", str(rules),
                    "--only", "inventory", "--report-format", "json",
                ])
            cli_payload = json.loads(stdout.getvalue())

        body = json.dumps(report.to_dict())
        registry = report.meta["gate_registry"]
        self.assertEqual(report.overall.value, "fail")
        self.assertEqual(registry["aggregate_status"], "error")
        self.assertEqual(registry["status_gate_ids"]["error"], ["inventory"])
        self.assertEqual(code, 3)
        self.assertEqual(
            cli_payload["meta"]["gate_registry"]["aggregate_status"],
            "error",
        )
        self.assertNotIn("STEP File could not be loaded", body)
        self.assertNotIn("secret-missing.step", body)

    def test_zero_evidence_claim_and_publish_gates_do_not_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim_rules = self._write_rules(
                root,
                'schema_version: "0.9"\nclaim_audit:\n'
                '  scan_paths: [definitely-no-such-file.md]\n',
            )
            claim = run_configured_harness(
                claim_rules, repo_root=root, only=["claim_audit"],
            )
            publish_rules = root / "publish.yaml"
            publish_rules.write_text(
                'schema_version: "0.9"\npublish_audit:\n'
                '  ignore_globs: [private/**]\n',
                encoding="utf-8",
            )
            publish = run_configured_harness(
                publish_rules, repo_root=root, only=["publish_audit"],
            )

        claim_registry = claim.meta["gate_registry"]
        self.assertEqual(claim.overall.value, "fail")
        self.assertEqual(
            claim_registry["status_gate_ids"]["not_checked"],
            ["claim_audit"],
        )

        # A non-repository root is a failed git classification, not a
        # legitimate empty classification result.
        publish_registry = publish.meta["gate_registry"]
        self.assertEqual(publish.overall.value, "fail")
        self.assertEqual(
            publish_registry["status_gate_ids"]["error"],
            ["publish_audit"],
        )

    def test_each_configured_claim_lane_requires_successful_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("safe\n", encoding="utf-8")
            rules = self._write_rules(
                root,
                'schema_version: "0.9"\nclaim_audit:\n'
                '  scan_paths: [README.md]\n  source_regex_rules:\n'
                '    - pattern: value\n      message: value found\n'
                '      file_glob: missing/*.py\n',
            )
            report = run_configured_harness(
                rules, repo_root=root, only=["claim_audit"],
            )

        registry = report.meta["gate_registry"]
        self.assertEqual(report.overall.value, "fail")
        self.assertEqual(registry["status_gate_ids"]["not_checked"], [
            "claim_audit",
        ])

    def test_malformed_configured_json_is_operational_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.json").write_text("{not json", encoding="utf-8")
            rules = self._write_rules(
                root,
                'schema_version: "0.9"\nclaim_audit:\n'
                '  scan_paths: [bad.json]\n',
            )
            report = run_configured_harness(
                rules, repo_root=root, only=["claim_audit"],
            )

        registry = report.meta["gate_registry"]
        self.assertEqual(report.overall.value, "fail")
        self.assertEqual(registry["status_gate_ids"]["error"], ["claim_audit"])
        self.assertEqual(registry["aggregate_status"], "error")
        self.assertTrue(any(
            finding.id == "claim.scan_error" for finding in report.findings
        ))

    def test_publish_content_lane_with_zero_matches_is_not_checked(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(
                ["git", "init", "--quiet"],
                cwd=root,
                check=True,
                capture_output=True,
            )
            rules = self._write_rules(
                root,
                'schema_version: "0.9"\npublish_audit:\n'
                '  scan_globs: [missing/*.md]\n  redact_patterns:\n'
                '    email: test@example.com\n',
            )
            report = run_configured_harness(
                rules, repo_root=root, only=["publish_audit"],
            )

        registry = report.meta["gate_registry"]
        self.assertEqual(report.overall.value, "fail")
        self.assertEqual(registry["status_gate_ids"]["not_checked"], [
            "publish_audit",
        ])

    def test_invalid_audit_regex_is_error_not_checked_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("safe\n", encoding="utf-8")
            (root / "sample.py").write_text("value = 1\n", encoding="utf-8")
            claim_rules = self._write_rules(
                root,
                'schema_version: "0.9"\nclaim_audit:\n'
                '  scan_paths: [README.md]\n  source_regex_rules:\n'
                '    - pattern: "["\n      message: invalid\n',
            )
            claim = run_configured_harness(
                claim_rules, repo_root=root, only=["claim_audit"],
            )
            zero_match_claim_rules = root / "zero-match-claim.yaml"
            zero_match_claim_rules.write_text(
                'schema_version: "0.9"\nclaim_audit:\n'
                '  scan_paths: [README.md]\n  source_regex_rules:\n'
                '    - pattern: "["\n      message: invalid\n'
                '      file_glob: missing/*.py\n',
                encoding="utf-8",
            )
            zero_match_claim = run_configured_harness(
                zero_match_claim_rules,
                repo_root=root,
                only=["claim_audit"],
            )
            publish_rules = root / "publish.yaml"
            publish_rules.write_text(
                'schema_version: "0.9"\npublish_audit:\n'
                '  scan_globs: ["**/*"]\n  redact_patterns:\n    bad: "["\n',
                encoding="utf-8",
            )
            publish = run_configured_harness(
                publish_rules, repo_root=root, only=["publish_audit"],
            )

        for report, gate_id in (
            (claim, "claim_audit"),
            (zero_match_claim, "claim_audit"),
            (publish, "publish_audit"),
        ):
            registry = report.meta["gate_registry"]
            self.assertEqual(report.overall.value, "fail")
            self.assertEqual(registry["status_gate_ids"]["error"], [gate_id])
            self.assertEqual(registry["aggregate_status"], "error")

    def test_geometry_label_error_is_runner_error_not_partial_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = self._write_rules(
                root,
                'schema_version: "0.9"\nmeta:\n  step: fixture.step\n'
                'labels:\n  fixture:\n    sig: [1, 2, 3]\n'
                '    expected_face: XY\n',
            )
            with (
                patch("cadclaw.inventory.load_and_dedup", return_value=[object()]),
                patch("cadclaw.inventory.sig", side_effect=RuntimeError("secret")),
            ):
                report = run_configured_harness(rules, only=["orientation"])

        registry = report.meta["gate_registry"]
        self.assertEqual(report.overall.value, "fail")
        self.assertEqual(registry["status_gate_ids"]["error"], ["orientation"])
        self.assertNotIn("secret", json.dumps(report.to_dict()))


class TestMCPHarnessContract(unittest.TestCase):
    def test_run_harness_schema_and_handler_share_registry_ids(self):
        from cadclaw_mcp.server import TOOLS, TOOL_HANDLERS

        self.assertEqual(len(TOOLS), 24)
        self.assertEqual(len(TOOL_HANDLERS), 24)
        self.assertEqual(
            {tool["name"] for tool in TOOLS},
            set(TOOL_HANDLERS),
        )
        definition = next(tool for tool in TOOLS if tool["name"] == "run_harness")
        self.assertIn("run_harness", TOOL_HANDLERS)
        for selector in ("only", "skip"):
            schema = definition["inputSchema"]["properties"][selector]
            self.assertEqual(schema["minItems"], 1)
            self.assertTrue(schema["uniqueItems"])
            self.assertEqual(schema["items"]["enum"], list(HARNESS_GATE_REGISTRY.ids))

    def test_run_harness_invalid_selection_is_structured(self):
        from cadclaw_mcp.server import tool_run_harness

        payload = tool_run_harness(
            "unused.yaml",
            only=["does_not_exist"],
        )
        self.assertEqual(payload["overall"], "fail")
        self.assertEqual(payload["meta"]["reason_code"], "unknown_gate")
        self.assertEqual(
            payload["meta"]["gate_registry"]["aggregate_status"],
            "error",
        )

    def test_focused_interference_error_precedes_not_checked(self):
        from cadclaw_mcp import server

        solids = [
            TestInterferenceExecutionErrors._Solid(),
            TestInterferenceExecutionErrors._Solid(),
        ]
        calls = iter((RuntimeError("secret"), "fixture"))

        def _label(_part):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value

        with (
            patch.object(server, "_loaded_parts", solids),
            patch.object(server, "_label_fn", side_effect=_label),
        ):
            payload = server.tool_check_interference()

        self.assertEqual(payload["status"], "error")
        self.assertFalse(payload["passed"])
        self.assertGreater(payload["error_count"], 0)

    def test_focused_one_part_interference_is_not_checked(self):
        from cadclaw_mcp import server

        with (
            patch.object(
                server,
                "_loaded_parts",
                [TestInterferenceExecutionErrors._Solid()],
            ),
            patch.object(server, "_label_fn", return_value="fixture"),
        ):
            payload = server.tool_check_interference()

        self.assertEqual(payload["status"], "not_checked")
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["eligible_parts"], 1)

    def test_inspect_overlap_propagates_exact_error(self):
        from cadclaw.inspect import find_overlaps

        solids = [
            TestInterferenceExecutionErrors._Solid(),
            TestInterferenceExecutionErrors._Solid(),
        ]
        with patch("cadclaw.interference.InterferenceCheck") as check_cls:
            check_cls.return_value.run.return_value = InterferenceResult(
                passed=False,
                checked_pairs=1,
                clips=[],
                error_count=1,
                eligible_parts=2,
            )
            with self.assertRaises(InterferenceExecutionError):
                find_overlaps(
                    solids,
                    lambda _part: "fixture",
                    target_label="fixture",
                )

    def test_inspect_overlap_rejects_target_excluded_by_skip_labels(self):
        from cadclaw.inspect import find_overlaps

        belt = TestInterferenceExecutionErrors._Solid()
        frame_a = TestInterferenceExecutionErrors._Solid()
        frame_b = TestInterferenceExecutionErrors._Solid()
        labels = {
            id(belt): "belt",
            id(frame_a): "frame",
            id(frame_b): "frame",
        }

        with patch("cadclaw.interference.InterferenceCheck") as check_cls:
            with self.assertRaises(InterferenceExecutionError) as caught:
                find_overlaps(
                    [belt, frame_a, frame_b],
                    lambda part: labels[id(part)],
                    target_label="belt",
                    skip_labels={"belt"},
                )

        self.assertEqual(caught.exception.code, "interference.not_checked")
        self.assertIn("excluded by skip_labels", str(caught.exception))
        check_cls.assert_not_called()

    def test_inspect_overlap_binds_labels_once_by_exact_identity(self):
        from cadclaw.inspect import find_overlaps

        class EqualityTrapSolid(TestInterferenceExecutionErrors._Solid):
            __hash__ = None

            def __eq__(self, _other):
                return True

        target = EqualityTrapSolid()
        frame_a = EqualityTrapSolid()
        frame_b = EqualityTrapSolid()
        parts = [target, target, frame_a, frame_b]
        calls_by_identity = {}

        def _nondeterministic_label(part):
            key = id(part)
            calls_by_identity[key] = calls_by_identity.get(key, 0) + 1
            if part is target:
                return "plate" if calls_by_identity[key] == 1 else "skipme"
            return "frame"

        observed_labels = []

        def _check_factory(check_parts, cached_label_fn, **_kwargs):
            observed_labels.extend(cached_label_fn(part) for part in check_parts)
            return SimpleNamespace(run=lambda: InterferenceResult(
                passed=True,
                checked_pairs=0,
                clips=[],
                eligible_parts=len(check_parts),
            ))

        with patch(
            "cadclaw.interference.InterferenceCheck",
            side_effect=_check_factory,
        ):
            clips, target_count = find_overlaps(
                parts,
                _nondeterministic_label,
                target_label="plate",
                skip_labels={"skipme"},
            )

        self.assertEqual(clips, [])
        self.assertEqual(target_count, 2)
        self.assertEqual(observed_labels, ["plate", "plate", "frame", "frame"])
        self.assertEqual(calls_by_identity, {
            id(target): 1,
            id(frame_a): 1,
            id(frame_b): 1,
        })

    def test_inspect_label_resolution_error_is_not_no_target(self):
        from cadclaw.inspect import find_overlaps

        solids = [TestInterferenceExecutionErrors._Solid()]
        with self.assertRaises(InterferenceExecutionError) as caught:
            find_overlaps(
                solids,
                lambda _part: (_ for _ in ()).throw(RuntimeError("secret")),
                target_label="fixture",
            )
        self.assertEqual(caught.exception.code, "interference.label_error")
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
