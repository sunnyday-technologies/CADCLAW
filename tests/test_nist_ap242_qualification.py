"""Integrity tests for tracked NIST AP242 software-qualification cohorts."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "run-nist-ap242-qualification.ps1"
EVIDENCE_ROOT = REPO / "evidence" / "qualifications" / "nist-ap242"
TEST_WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"
MANIFEST_VERSION = "nist-ap242-qualification-manifest.v1"
REPORT_SCHEMA_VERSION = "0.7"
RULES_SCHEMA_VERSION = "0.9"
GATE_SPEC_VERSION = "0.12.0"
EXPECTED_CLASSES = ("dimensions", "geometric_tolerances", "datums")
EXPECTED_FIXTURES = {
    "nist-ftc-11-ap242-e2": {
        "path": "tests/fixtures/pmi_semantic/nist_ftc_11_asme1_ap242-e2.stp",
        "sha256": "20a92edf514ae0989d556f9c7b9f065aed741cfbb361b7fe4cb7938a1eb5c232",
        "counts": {"dimensions": 6, "geometric_tolerances": 4, "datums": 4},
        "provenance_fragment": "archive member is AP242 e2, while its embedded Part 21 FILE_NAME reports AP242 e1",
    },
    "nist-stc-06-ap242-e3": {
        "path": "tests/fixtures/pmi_semantic/nist_stc_06_asme1_ap242-e3.stp",
        "sha256": "71777c28da76da0e8a667e4cbe792d5f72c09b5c56440c9744d3d50ca96ecc8d",
        "counts": {"dimensions": 17, "geometric_tolerances": 25, "datums": 51},
        "provenance_fragment": "archive member and this cohort identify the fixture as AP242 e3",
    },
}
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
COHORT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{5,79}$")
WINDOWS_DEVICE_STEM = re.compile(r"(?i)^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$")
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?<![a-z0-9])[a-z]:[\\/]")
UNC_ABSOLUTE_PATH = re.compile(r"(?<![\\])\\\\[^\\/\s]+[\\/][^\\/\s]+")
POSIX_ABSOLUTE_PATH = re.compile(r"(?<![a-z0-9:/])/(?!/)(?:[^/\s]+(?:/|$))")
FORBIDDEN_KEYS = {
    "cwd",
    "env",
    "environment",
    "executable",
    "home",
    "host",
    "hostname",
    "user",
    "username",
    "working_directory",
}
FORBIDDEN_KEY_SEGMENT = re.compile(
    r"(?:^|_)(?:token|tokens|password|passwords|auth|authentication|authorization|credential|credentials|secret|secrets)(?:_|$)"
)
FORBIDDEN_API_KEY = re.compile(r"(?:^|_)api_?key(?:_|$)")
FORBIDDEN_PRIVATE_KEY = re.compile(r"(?:^|_)private_?key(?:_|$)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AssertionError(f"timestamp is not UTC: {value!r}")
    return parsed


def normalized_key(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value).lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def forbidden_key(value: str) -> bool:
    normalized = normalized_key(value)
    return (
        normalized in FORBIDDEN_KEYS
        or FORBIDDEN_KEY_SEGMENT.search(normalized) is not None
        or FORBIDDEN_API_KEY.search(normalized) is not None
        or FORBIDDEN_PRIVATE_KEY.search(normalized) is not None
    )


def assert_sanitized(test: unittest.TestCase, value, context: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            test.assertFalse(forbidden_key(str(key)), f"{context}.{key}")
            assert_sanitized(test, child, f"{context}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_sanitized(test, child, f"{context}[{index}]")
    elif isinstance(value, str):
        test.assertNotRegex(value, r"(?i)\bfile://", context)
        test.assertIsNone(WINDOWS_ABSOLUTE_PATH.search(value), context)
        test.assertIsNone(UNC_ABSOLUTE_PATH.search(value), context)
        test.assertIsNone(POSIX_ABSOLUTE_PATH.search(value), context)


def assert_valid_cohort_id(test: unittest.TestCase, value: str) -> None:
    test.assertRegex(value, COHORT_ID)
    test.assertFalse(value.endswith((".", " ")))
    test.assertIsNone(WINDOWS_DEVICE_STEM.fullmatch(value.split(".", 1)[0]))


def assert_flat_checksum_coverage(
    test: unittest.TestCase, cohort_dir: Path, checksum_records: dict[str, str]
) -> None:
    nested_directories = [path for path in cohort_dir.rglob("*") if path.is_dir()]
    test.assertFalse(nested_directories, nested_directories)
    actual_files = {path.name for path in cohort_dir.iterdir() if path.is_file()}
    test.assertIn("SHA256SUMS", actual_files)
    test.assertEqual(set(checksum_records), actual_files - {"SHA256SUMS"})


def normalized_relative(path: str) -> str:
    return path.replace("\\", "/")


class TestNistQualificationWorkflowContract(unittest.TestCase):
    @staticmethod
    def _powershell() -> str | None:
        return shutil.which("pwsh") or shutil.which("powershell")

    def _invoke_extracted_function(
        self, function_name: str, case: str, path_argument: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        powershell = self._powershell()
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        command = r'''
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:CADCLAW_QUALIFICATION_TEST_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw "runner parse failed" }
$wantedName = $env:CADCLAW_QUALIFICATION_TEST_FUNCTION
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $wantedName
}, $true)
if ($null -eq $functionAst) { throw "function not found" }
. ([scriptblock]::Create($functionAst.Extent.Text))
switch ($env:CADCLAW_QUALIFICATION_TEST_CASE) {
    "head-mismatch" {
        Assert-CleanExactMainPreflight -HeadCommit ("a" * 40) -OriginMainCommit ("b" * 40) -WorktreeStatus @()
    }
    "dirty" {
        Assert-CleanExactMainPreflight -HeadCommit ("a" * 40) -OriginMainCommit ("a" * 40) -WorktreeStatus @("M tracked-file")
    }
    "path" {
        Assert-NoReparsePointInExistingAncestors -Path $env:CADCLAW_QUALIFICATION_TEST_PATH -Context "test output"
    }
    "write-lf" {
        Write-Utf8NoBom -Path $env:CADCLAW_QUALIFICATION_TEST_PATH -Content "alpha`r`nbeta`rgamma`n"
    }
    default { throw "unknown test case" }
}
'''
        arguments = [
            powershell,
            "-NoProfile",
            "-Command",
            command,
        ]
        qualification_environment = os.environ.copy()
        qualification_environment.update(
            {
                "CADCLAW_QUALIFICATION_TEST_SCRIPT": str(SCRIPT),
                "CADCLAW_QUALIFICATION_TEST_FUNCTION": function_name,
                "CADCLAW_QUALIFICATION_TEST_CASE": case,
                "CADCLAW_QUALIFICATION_TEST_PATH": (
                    str(path_argument) if path_argument is not None else ""
                ),
            }
        )
        return subprocess.run(
            arguments,
            cwd=REPO,
            env=qualification_environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_local_work_root_is_explicitly_ignored(self):
        completed = subprocess.run(
            [
                "git",
                "check-ignore",
                "-q",
                ".qualification-temp/nist-ap242/test-cohort/scratch.json",
            ],
            cwd=REPO,
            check=False,
        )
        self.assertEqual(completed.returncode, 0)

    def test_unit_test_checkout_retains_history_for_evidence_verification(self):
        workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
        checkout = re.search(
            r"(?ms)^\s*- uses: actions/checkout@v4\s+with:\s+fetch-depth:\s*0\s*$",
            workflow,
        )
        self.assertIsNotNone(checkout)

    def test_all_tracked_cohort_text_is_pinned_to_lf(self):
        cohort = "evidence/qualifications/nist-ap242/example-cohort"
        for path in (
            f"{cohort}/README.md",
            f"{cohort}/manifest.json",
            f"{cohort}/example.pmi-present.json",
            f"{cohort}/SHA256SUMS",
        ):
            with self.subTest(path=path):
                completed = subprocess.run(
                    ["git", "check-attr", "text", "eol", "--", path],
                    cwd=REPO,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                attributes = {}
                for line in completed.stdout.splitlines():
                    _, attribute, value = line.split(": ", 2)
                    attributes[attribute] = value
                self.assertEqual(attributes, {"text": "set", "eol": "lf"})

    def test_script_keeps_fresh_exact_main_and_nonoverwrite_guards(self):
        text = SCRIPT.read_text(encoding="utf-8")
        required_fragments = (
            'git fetch --no-tags origin "refs/heads/main:refs/remotes/origin/main"',
            '"origin/main^{commit}"',
            "TargetCommit must be an exact 40-character commit SHA",
            "TargetCommit must equal the freshly fetched origin/main commit",
            "Assert-CleanExactMainPreflight",
            "caller HEAD must equal the freshly fetched origin/main commit",
            "caller worktree must be clean",
            "git archive --format=zip",
            "the exact target commit does not contain this qualification runner",
            "qualification runner hash at target commit",
            "the exact target commit does not ignore the local qualification work root",
            "source_root not in module_path.parents",
            "CADCLAW import did not come from the target snapshot",
            "cohort '$CohortId' already exists",
            "local qualification work for '$CohortId' already exists",
            ".qualification-temp\\nist-ap242\\$CohortId",
            '"--roundtrip-out", $qualificationDerivativePath',
            '"IFSelect_RetError"',
            '"ret_error_provisionally_validated"',
            '"pass_with_provisional_writer_status"',
            "Assert-NoSensitiveRuntimeFields",
            "Assert-NoReparsePointInExistingAncestors",
            "System.IO.FileAttributes]::ReparsePoint",
            "[System.IO.Directory]::Move",
            "same volume for atomic publication",
            "temporary target snapshot cleanup",
            "temporary target snapshot cleanup could not be verified",
            "exact-parent or GUID-leaf safety check",
            "^cadclaw-nist-ap242-[0-9a-f]{32}$",
            '"software_qualification"',
            'marb_benchmark = $false',
            'model_calls = 0',
            '$qualificationReportSchemaVersion = "0.7"',
            '$qualificationRulesSchemaVersion = "0.9"',
            '$qualificationGateSpecVersion = "0.12.0"',
            "PMI frozen count",
            "round-trip source count",
            '$Content.Replace("`r`n", "`n").Replace("`r", "`n")',
            "Write-Utf8NoBom -Path $qualificationPmiReportPath",
            "Write-Utf8NoBom -Path $qualificationRoundtripReportPath",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, text)
        self.assertLess(
            text.index("Assert-CleanExactMainPreflight -HeadCommit"),
            text.index("New-Item -ItemType Directory -Path $qualificationDerivativeRoot"),
        )
        self.assertNotIn(
            "Move-Item -LiteralPath $qualificationStagingRoot", text
        )
        self.assertLess(
            text.rindex(
                'Assert-NoReparsePointInExistingAncestors -Path $qualificationSnapshotFull'
            ),
            text.rindex(
                "Remove-Item -LiteralPath $qualificationSnapshotFull -Recurse"
            ),
        )
        self.assertLess(
            text.index("Write-Utf8NoBom -Path $qualificationPmiReportPath"),
            text.index(
                'Read-ValidatedJsonReport $qualificationPmiReportPath'
            ),
        )
        self.assertLess(
            text.index("Write-Utf8NoBom -Path $qualificationRoundtripReportPath"),
            text.index(
                'Read-ValidatedJsonReport $qualificationRoundtripReportPath'
            ),
        )

    def test_utf8_writer_canonicalizes_line_endings_without_bom(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "canonical.txt"
            completed = self._invoke_extracted_function(
                "Write-Utf8NoBom", "write-lf", output
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(output.read_bytes(), b"alpha\nbeta\ngamma\n")

    def test_invalid_and_windows_device_cohort_ids_fail_before_fetch_or_write(self):
        powershell = self._powershell()
        if powershell is None:
            self.skipTest("PowerShell is unavailable")
        for invalid_id in ("../invalid", "con.txt", "com1.log", "valid.", "name "):
            with self.subTest(cohort_id=invalid_id):
                completed = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-File",
                        str(SCRIPT),
                        "-CohortId",
                        invalid_id,
                    ],
                    cwd=REPO,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(
                    "CohortId must", completed.stderr + completed.stdout
                )
                self.assertNotIn("Fetching", completed.stderr + completed.stdout)

    def test_clean_exact_main_preflight_rejects_mismatch_and_dirty_tree(self):
        for case, fragment in (
            ("head-mismatch", "caller HEAD must equal"),
            ("dirty", "caller worktree must be clean"),
        ):
            with self.subTest(case=case):
                completed = self._invoke_extracted_function(
                    "Assert-CleanExactMainPreflight", case
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(fragment, completed.stderr + completed.stdout)

    def test_reparse_output_ancestor_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            real = temporary_path / "real"
            link = temporary_path / "link"
            real.mkdir()
            junction_created = False
            try:
                os.symlink(real, link, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                powershell = self._powershell()
                if os.name != "nt" or powershell is None:
                    self.skipTest(f"directory symlink unavailable: {exc}")
                qualification_environment = os.environ.copy()
                qualification_environment.update(
                    {
                        "CADCLAW_QUALIFICATION_JUNCTION_PATH": str(link),
                        "CADCLAW_QUALIFICATION_JUNCTION_TARGET": str(real),
                    }
                )
                junction = subprocess.run(
                    [
                        powershell,
                        "-NoProfile",
                        "-Command",
                        "$null = New-Item -ItemType Junction -Path $env:CADCLAW_QUALIFICATION_JUNCTION_PATH -Target $env:CADCLAW_QUALIFICATION_JUNCTION_TARGET",
                    ],
                    env=qualification_environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if junction.returncode != 0:
                    self.skipTest(f"directory junction unavailable: {exc}")
                junction_created = True
            try:
                completed = self._invoke_extracted_function(
                    "Assert-NoReparsePointInExistingAncestors",
                    "path",
                    link / "future" / "cohort",
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(
                    "symlink or reparse point", completed.stderr + completed.stdout
                )
            finally:
                if junction_created:
                    qualification_environment = os.environ.copy()
                    qualification_environment[
                        "CADCLAW_QUALIFICATION_JUNCTION_PATH"
                    ] = str(link)
                    subprocess.run(
                        [
                            self._powershell(),
                            "-NoProfile",
                            "-Command",
                            "Remove-Item -LiteralPath $env:CADCLAW_QUALIFICATION_JUNCTION_PATH -Force",
                        ],
                        env=qualification_environment,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

    def test_sanitizer_rejects_secret_keys_and_absolute_paths(self):
        for key in (
            "api_key",
            "accessToken",
            "private-key",
            "password",
            "authorization",
            "credential",
            "secret",
            "hostname",
        ):
            with self.subTest(key=key):
                with self.assertRaises(AssertionError):
                    assert_sanitized(self, {key: "redacted"}, "payload")
        for value in (
            r"C:\work\report.json",
            r"\\server\share\report.json",
            "/tmp/report.json",
            "failure at /var/tmp/report.json",
            "file:///tmp/report.json",
        ):
            with self.subTest(value=value):
                with self.assertRaises(AssertionError):
                    assert_sanitized(self, {"message": value}, "payload")

    def test_sanitizer_accepts_public_https_and_declared_relative_paths(self):
        assert_sanitized(
            self,
            {
                "source_page": "https://www.nist.gov/document/nist-pmi-step-files",
                "source_path": "tests/fixtures/pmi_semantic/input.stp",
                "local_ignored_root": ".qualification-temp/nist-ap242/cohort/derivatives",
                "authoring_proxy_comparison": {"status": "not_applicable"},
            },
            "payload",
        )


class TestTrackedNistQualificationCohorts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cohort_dirs = sorted(
            path
            for path in EVIDENCE_ROOT.iterdir()
            if path.is_dir() and (path / "manifest.json").is_file()
        )

    def test_index_defines_runner_first_evidence_second_sequence(self):
        index = (EVIDENCE_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("executing runner must also be present byte-for-byte", index)
        self.assertIn("prevents a runner that is only uncommitted", index)

    def test_no_unrecognized_evidence_directories(self):
        immediate_directories = {
            path for path in EVIDENCE_ROOT.iterdir() if path.is_dir()
        }
        self.assertEqual(immediate_directories, set(self.cohort_dirs))

    def test_every_cohort_is_self_consistent(self):
        for cohort_dir in self.cohort_dirs:
            with self.subTest(cohort=cohort_dir.name):
                self._assert_cohort(cohort_dir)

    def test_frozen_pmi_counts_and_gate_spec_reject_drift(self):
        expected = EXPECTED_FIXTURES["nist-ftc-11-ap242-e2"]
        baseline = self._valid_pmi_report(expected)
        for mutation in ("count", "duplicate", "gate-spec"):
            with self.subTest(mutation=mutation):
                report = copy.deepcopy(baseline)
                if mutation == "count":
                    report["meta"]["class_results"][0]["count"] += 1
                elif mutation == "duplicate":
                    report["meta"]["class_results"].append(
                        copy.deepcopy(report["meta"]["class_results"][0])
                    )
                else:
                    report["meta"]["gate_spec_version"] = "0.12.1"
                with self.assertRaises(AssertionError):
                    self._assert_pmi_report(report, expected)

    def test_roundtrip_requires_exact_three_frozen_class_results(self):
        expected = EXPECTED_FIXTURES["nist-ftc-11-ap242-e2"]
        gate = {
            "derivative_sha256": "d" * 64,
            "derivative_schema": "AP242_TEST",
            "write_status": "IFSelect_RetDone",
            "write_disposition": "ret_done",
            "derivative_retention": "local_only_ignored",
            "derivative_size_bytes": 1,
        }
        baseline = self._valid_roundtrip_report(expected)
        for mutation in ("missing", "unexpected", "before", "after"):
            with self.subTest(mutation=mutation):
                report = copy.deepcopy(baseline)
                results = report["meta"]["translation_comparison"][
                    "supported_semantic_pmi_class_counts"
                ]["results"]
                if mutation == "missing":
                    results.pop()
                elif mutation == "unexpected":
                    results[-1]["class"] = "notes"
                elif mutation == "before":
                    results[0]["before_count"] += 1
                else:
                    results[0]["after_count"] += 1
                with self.assertRaises(AssertionError):
                    self._assert_roundtrip_report(report, expected, gate)

    def test_checksum_contract_rejects_extra_files_and_nested_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            cohort = Path(temporary)
            for name in ("manifest.json", "README.md", "SHA256SUMS", "extra.txt"):
                (cohort / name).write_text(name, encoding="utf-8")
            with self.assertRaises(AssertionError):
                assert_flat_checksum_coverage(
                    self,
                    cohort,
                    {"manifest.json": "0" * 64, "README.md": "1" * 64},
                )

    def test_target_commit_verification_fails_closed_when_commit_is_unavailable(self):
        manifest = {
            "repository": {
                "target_commit": "0" * 40,
                "target_tree": "1" * 40,
                "runner_sha256": "2" * 64,
            },
            "rules": {
                "path": "tests/fixtures/pmi_semantic/cadclaw.yaml",
                "sha256": "3" * 64,
                "size_bytes": 1,
            },
            "fixtures": [],
        }
        with self.assertRaises(AssertionError):
            self._assert_target_commit_material(manifest)
        with tempfile.TemporaryDirectory() as temporary:
            cohort = Path(temporary)
            for name in ("manifest.json", "README.md", "SHA256SUMS"):
                (cohort / name).write_text(name, encoding="utf-8")
            (cohort / "nested").mkdir()
            with self.assertRaises(AssertionError):
                assert_flat_checksum_coverage(
                    self,
                    cohort,
                    {"manifest.json": "0" * 64, "README.md": "1" * 64},
                )

    def _assert_cohort(self, cohort_dir: Path) -> None:
        assert_valid_cohort_id(self, cohort_dir.name)
        self.assertFalse(list(cohort_dir.rglob("*.step")))
        self.assertFalse(list(cohort_dir.rglob("*.stp")))

        manifest_path = cohort_dir / "manifest.json"
        readme_path = cohort_dir / "README.md"
        checksum_path = cohort_dir / "SHA256SUMS"
        for required in (manifest_path, readme_path, checksum_path):
            self.assertTrue(required.is_file(), required)

        for tracked_text in cohort_dir.iterdir():
            if tracked_text.is_file():
                tracked_bytes = tracked_text.read_bytes()
                self.assertFalse(
                    tracked_bytes.startswith(b"\xef\xbb\xbf"),
                    f"tracked evidence must not use a UTF-8 BOM: {tracked_text.name}",
                )
                self.assertNotIn(
                    b"\r",
                    tracked_bytes,
                    f"tracked evidence must use canonical LF bytes: {tracked_text.name}",
                )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], MANIFEST_VERSION)
        self.assertEqual(manifest["cohort_id"], cohort_dir.name)
        self.assertEqual(manifest["qualification_kind"], "software_qualification")
        classification = manifest["classification"]
        self.assertEqual(classification["type"], "software_qualification")
        self.assertTrue(classification["software_qualification"])
        self.assertFalse(classification["marb_benchmark"])
        self.assertEqual(classification["model_calls"], 0)
        self.assertEqual(
            classification["cost"],
            {
                "status": "not_incurred",
                "value": 0,
                "currency": "USD",
                "scope": "model/provider API cost",
            },
        )
        self.assertTrue(manifest["qualification_passed"])

        self.assertEqual(
            manifest["contracts"],
            {
                "manifest_schema_version": MANIFEST_VERSION,
                "report_schema_version": REPORT_SCHEMA_VERSION,
                "rules_schema_version": RULES_SCHEMA_VERSION,
                "gate_spec_version": GATE_SPEC_VERSION,
            },
        )

        started = parse_utc(manifest["started_utc"])
        completed = parse_utc(manifest["completed_utc"])
        self.assertLessEqual(started, completed)

        repository = manifest["repository"]
        self.assertEqual(
            repository["url"],
            "https://github.com/sunnyday-technologies/CADCLAW",
        )
        self.assertRegex(repository["target_commit"], HEX_40)
        self.assertRegex(repository["target_tree"], HEX_40)
        self.assertEqual(
            repository["target_commit"],
            repository["fetched_origin_main_commit"],
        )
        self.assertEqual(
            repository["target_commit"], repository["caller_head_commit"]
        )
        self.assertTrue(repository["target_equals_fetched_origin_main"])
        self.assertTrue(repository["caller_head_equals_fetched_origin_main"])
        self.assertTrue(repository["caller_worktree_clean"])
        self.assertRegex(repository["runner_sha256"], HEX_64)
        self.assertEqual(
            repository["execution_source"],
            "clean git archive of the exact target commit",
        )
        self._assert_target_commit_material(manifest)

        runtime = manifest["runtime"]
        self.assertTrue(runtime["python"]["implementation"])
        self.assertTrue(runtime["python"]["version"])
        self.assertTrue(runtime["cadclaw_version"])
        self.assertTrue(runtime["cadquery_version"])
        self.assertTrue(runtime["cadquery_ocp_version"])
        self.assertTrue(runtime["powershell_version"])
        self.assertEqual(
            set(runtime["operating_system"]),
            {"system", "release", "version", "machine"},
        )
        self.assertEqual(
            manifest["rules"]["path"],
            "tests/fixtures/pmi_semantic/cadclaw.yaml",
        )
        self.assertEqual(
            manifest["rules"]["schema_version"], RULES_SCHEMA_VERSION
        )
        self.assertRegex(manifest["rules"]["sha256"], HEX_64)
        self.assertGreater(manifest["rules"]["size_bytes"], 0)
        self.assertEqual(manifest["fixture_source"]["retrieved_date"], "2026-08-27")

        self.assertEqual(
            tuple(manifest["declared_semantic_pmi_classes"]), EXPECTED_CLASSES
        )
        fixtures = {item["id"]: item for item in manifest["fixtures"]}
        self.assertEqual(set(fixtures), set(EXPECTED_FIXTURES))

        saw_ret_error = False
        expected_report_files: set[str] = set()
        for fixture_id, expected in EXPECTED_FIXTURES.items():
            fixture = fixtures[fixture_id]
            self.assertEqual(fixture["source_path"], expected["path"])
            self.assertEqual(fixture["source_sha256"], expected["sha256"])
            self.assertEqual(
                fixture["source_size_bytes"], (REPO / expected["path"]).stat().st_size
            )
            self.assertEqual(
                sha256(REPO / expected["path"]), expected["sha256"]
            )
            self.assertEqual(
                fixture["source_kind"],
                "authored NIST AP242 single-product qualification fixture",
            )
            self.assertIn(
                expected["provenance_fragment"], fixture["provenance_note"]
            )

            pmi_gate = fixture["pmi_present"]
            roundtrip_gate = fixture["roundtrip_step"]
            self._assert_gate_timing(pmi_gate, started, completed)
            self._assert_gate_timing(roundtrip_gate, started, completed)
            self.assertEqual(pmi_gate["exit_code"], 0)
            self.assertEqual(roundtrip_gate["exit_code"], 0)
            self.assertEqual(pmi_gate["outcome"], "pass")
            self.assertEqual(roundtrip_gate["outcome"], "pass")
            self.assertEqual(pmi_gate["report_schema_version"], REPORT_SCHEMA_VERSION)
            self.assertEqual(
                roundtrip_gate["report_schema_version"], REPORT_SCHEMA_VERSION
            )
            self.assertEqual(pmi_gate["gate_spec_version"], GATE_SPEC_VERSION)
            self.assertEqual(
                roundtrip_gate["gate_spec_version"], GATE_SPEC_VERSION
            )
            self.assertEqual(pmi_gate["semantic_class_counts"], expected["counts"])
            self.assertEqual(
                pmi_gate["argv_sanitized"],
                self._expected_pmi_argv(cohort_dir.name, fixture_id, expected["path"]),
            )
            self.assertEqual(
                roundtrip_gate["argv_sanitized"],
                self._expected_roundtrip_argv(
                    cohort_dir.name, fixture_id, expected["path"]
                ),
            )

            pmi_report_path = cohort_dir / pmi_gate["report"]
            roundtrip_report_path = cohort_dir / roundtrip_gate["report"]
            expected_report_files.update(
                {pmi_report_path.name, roundtrip_report_path.name}
            )
            self.assertEqual(sha256(pmi_report_path), pmi_gate["report_sha256"])
            self.assertEqual(pmi_report_path.stat().st_size, pmi_gate["report_size_bytes"])
            self.assertEqual(
                sha256(roundtrip_report_path),
                roundtrip_gate["report_sha256"],
            )
            self.assertEqual(
                roundtrip_report_path.stat().st_size,
                roundtrip_gate["report_size_bytes"],
            )
            self._assert_pmi_report(
                json.loads(pmi_report_path.read_text(encoding="utf-8")),
                expected,
            )
            roundtrip_report = json.loads(
                roundtrip_report_path.read_text(encoding="utf-8")
            )
            self._assert_roundtrip_report(
                roundtrip_report,
                expected,
                roundtrip_gate,
            )
            if roundtrip_gate["write_status"] == "IFSelect_RetError":
                saw_ret_error = True

        if saw_ret_error:
            self.assertEqual(
                manifest["outcome"], "pass_with_provisional_writer_status"
            )
        else:
            self.assertEqual(manifest["outcome"], "pass")

        derivative_policy = manifest["derivative_policy"]
        self.assertFalse(derivative_policy["tracked_derivatives"])
        self.assertTrue(derivative_policy["retained_for_local_review"])
        self.assertEqual(
            derivative_policy["local_ignored_root"],
            f".qualification-temp/nist-ap242/{cohort_dir.name}/derivatives",
        )

        self.assertTrue(manifest["scope"])
        self.assertGreaterEqual(len(manifest["limitations"]), 7)
        assert_sanitized(self, manifest, f"manifest {cohort_dir.name}")

        readme = readme_path.read_text(encoding="utf-8")
        self.assertIn(manifest["outcome"], readme)
        self.assertIn(repository["target_commit"], readme)
        self.assertIn(derivative_policy["local_ignored_root"], readme)
        self.assertIn("not a MARB/model benchmark", readme)
        self.assertIn("embedded Part 21 FILE_NAME reports AP242 e1", readme)

        checksum_records = {}
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)", line)
            self.assertIsNotNone(match, line)
            self.assertNotIn(match.group(2), checksum_records)
            checksum_records[match.group(2)] = match.group(1)
        expected_checksum_files = {
            "README.md",
            "manifest.json",
            *expected_report_files,
        }
        self.assertEqual(set(checksum_records), expected_checksum_files)
        assert_flat_checksum_coverage(self, cohort_dir, checksum_records)
        for name, digest in checksum_records.items():
            self.assertEqual(sha256(cohort_dir / name), digest)

    def _assert_target_commit_material(self, manifest: dict) -> None:
        repository = manifest["repository"]
        target = repository["target_commit"]
        available = subprocess.run(
            ["git", "cat-file", "-e", f"{target}^{{commit}}"],
            cwd=REPO,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self.assertEqual(
            available.returncode,
            0,
            "recorded target commit is unavailable; cohort provenance cannot be verified",
        )

        target_tree = subprocess.run(
            ["git", "rev-parse", f"{target}^{{tree}}"],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(target_tree, repository["target_tree"])

        def blob(path: str) -> bytes:
            return subprocess.run(
                ["git", "show", f"{target}:{path}"],
                cwd=REPO,
                capture_output=True,
                check=True,
            ).stdout

        runner_blob = blob("scripts/run-nist-ap242-qualification.ps1")
        self.assertEqual(sha256_bytes(runner_blob), repository["runner_sha256"])
        rules_blob = blob(manifest["rules"]["path"])
        self.assertEqual(sha256_bytes(rules_blob), manifest["rules"]["sha256"])
        self.assertEqual(len(rules_blob), manifest["rules"]["size_bytes"])
        for fixture in manifest["fixtures"]:
            fixture_blob = blob(fixture["source_path"])
            self.assertEqual(sha256_bytes(fixture_blob), fixture["source_sha256"])
            self.assertEqual(len(fixture_blob), fixture["source_size_bytes"])

    @staticmethod
    def _expected_pmi_argv(
        cohort_id: str, fixture_id: str, fixture_path: str
    ) -> list[str]:
        return [
            "<python-executable>",
            "-m",
            "cadclaw_cli.main",
            "pmi-present",
            "--rules",
            "tests/fixtures/pmi_semantic/cadclaw.yaml",
            "--step",
            fixture_path,
            "--report-format",
            "json",
            "-o",
            f".qualification-temp/nist-ap242/{cohort_id}/cohort-staging/{fixture_id}.pmi-present.json",
        ]

    @staticmethod
    def _expected_roundtrip_argv(
        cohort_id: str, fixture_id: str, fixture_path: str
    ) -> list[str]:
        return [
            "<python-executable>",
            "-m",
            "cadclaw_cli.main",
            "roundtrip-step",
            "--rules",
            "tests/fixtures/pmi_semantic/cadclaw.yaml",
            "--step",
            fixture_path,
            "--roundtrip-out",
            f".qualification-temp/nist-ap242/{cohort_id}/derivatives/{fixture_id}.roundtrip.stp",
            "--report-format",
            "json",
            "-o",
            f".qualification-temp/nist-ap242/{cohort_id}/cohort-staging/{fixture_id}.roundtrip-step.json",
        ]

    @staticmethod
    def _valid_pmi_report(expected: dict) -> dict:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "overall": "pass",
            "meta": {
                "gate": "PMI_PRESENT_SEMANTIC",
                "applicability": "applicable",
                "scope": "semantic_only",
                "gate_spec_version": GATE_SPEC_VERSION,
                "step": expected["path"],
                "rules": "tests/fixtures/pmi_semantic/cadclaw.yaml",
                "step_schema": "AP242_TEST",
                "class_results": [
                    {"class": name, "status": "present", "count": expected["counts"][name]}
                    for name in EXPECTED_CLASSES
                ],
            },
        }

    @staticmethod
    def _valid_roundtrip_report(expected: dict) -> dict:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "overall": "pass",
            "meta": {
                "gate": "ROUNDTRIP_STEP",
                "applicability": "applicable",
                "gate_spec_version": GATE_SPEC_VERSION,
                "derivative": {
                    "persisted": True,
                    "source_sha256": expected["sha256"],
                    "output_sha256": "d" * 64,
                    "output_schema": "AP242_TEST",
                    "write_status": "IFSelect_RetDone",
                    "write_disposition": "ret_done",
                },
                "translation_comparison": {
                    "status": "pass",
                    "supported_semantic_pmi_class_counts": {
                        "status": "compared",
                        "scope": "supported_semantic_class_counts_only",
                        "results": [
                            {
                                "class": name,
                                "status": "preserved",
                                "before_count": expected["counts"][name],
                                "after_count": expected["counts"][name],
                            }
                            for name in EXPECTED_CLASSES
                        ],
                    },
                },
            },
        }

    def _assert_gate_timing(
        self, gate: dict, cohort_started: datetime, cohort_completed: datetime
    ) -> None:
        gate_started = parse_utc(gate["started_utc"])
        gate_completed = parse_utc(gate["completed_utc"])
        self.assertLessEqual(cohort_started, gate_started)
        self.assertLessEqual(gate_started, gate_completed)
        self.assertLessEqual(gate_completed, cohort_completed)

    def _assert_pmi_report(self, report: dict, expected: dict) -> None:
        self.assertEqual(report["schema_version"], REPORT_SCHEMA_VERSION)
        self.assertEqual(report["overall"], "pass")
        meta = report["meta"]
        self.assertEqual(meta["gate"], "PMI_PRESENT_SEMANTIC")
        self.assertEqual(meta["applicability"], "applicable")
        self.assertEqual(meta["scope"], "semantic_only")
        self.assertEqual(meta["gate_spec_version"], GATE_SPEC_VERSION)
        self.assertEqual(normalized_relative(meta["step"]), expected["path"])
        self.assertEqual(
            normalized_relative(meta["rules"]),
            "tests/fixtures/pmi_semantic/cadclaw.yaml",
        )
        self.assertTrue(meta["step_schema"].upper().startswith("AP242"))
        self.assertEqual(len(meta["class_results"]), len(EXPECTED_CLASSES))
        class_results = {item["class"]: item for item in meta["class_results"]}
        self.assertEqual(set(class_results), set(EXPECTED_CLASSES))
        for name in EXPECTED_CLASSES:
            self.assertEqual(class_results[name]["status"], "present")
            self.assertEqual(class_results[name]["count"], expected["counts"][name])
        assert_sanitized(self, report, "PMI report")

    def _assert_roundtrip_report(
        self, report: dict, expected: dict, gate: dict
    ) -> None:
        self.assertEqual(report["schema_version"], REPORT_SCHEMA_VERSION)
        self.assertEqual(report["overall"], "pass")
        meta = report["meta"]
        self.assertEqual(meta["gate"], "ROUNDTRIP_STEP")
        self.assertEqual(meta["applicability"], "applicable")
        self.assertEqual(meta["gate_spec_version"], GATE_SPEC_VERSION)
        derivative = meta["derivative"]
        self.assertTrue(derivative["persisted"])
        self.assertEqual(derivative["source_sha256"], expected["sha256"])
        self.assertRegex(derivative["output_sha256"], HEX_64)
        self.assertEqual(
            derivative["output_sha256"], gate["derivative_sha256"]
        )
        self.assertEqual(derivative["output_schema"], gate["derivative_schema"])
        self.assertEqual(derivative["write_status"], gate["write_status"])
        self.assertEqual(
            derivative["write_disposition"], gate["write_disposition"]
        )
        self.assertEqual(gate["derivative_retention"], "local_only_ignored")
        self.assertGreater(gate["derivative_size_bytes"], 0)

        if derivative["write_status"] == "IFSelect_RetDone":
            self.assertEqual(derivative["write_disposition"], "ret_done")
        elif derivative["write_status"] == "IFSelect_RetError":
            self.assertEqual(
                derivative["write_disposition"],
                "ret_error_provisionally_validated",
            )
            self.assertTrue(
                any(
                    "provisionally validated error-status recovery" in item
                    for item in report["confidence_budget"]["not_checked"]
                )
            )
        else:
            self.fail(
                f"unsupported writer status: {derivative['write_status']}"
            )

        comparison = meta["translation_comparison"]
        self.assertEqual(comparison["status"], "pass")
        pmi_comparison = comparison["supported_semantic_pmi_class_counts"]
        self.assertEqual(pmi_comparison["status"], "compared")
        self.assertEqual(
            pmi_comparison["scope"], "supported_semantic_class_counts_only"
        )
        self.assertEqual(len(pmi_comparison["results"]), len(EXPECTED_CLASSES))
        results = {item["class"]: item for item in pmi_comparison["results"]}
        self.assertEqual(set(results), set(EXPECTED_CLASSES))
        for name in EXPECTED_CLASSES:
            self.assertEqual(results[name]["status"], "preserved")
            self.assertEqual(results[name]["before_count"], expected["counts"][name])
            self.assertEqual(results[name]["after_count"], expected["counts"][name])
        assert_sanitized(self, report, "round-trip report")


if __name__ == "__main__":
    unittest.main()
