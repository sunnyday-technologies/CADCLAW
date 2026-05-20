import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "m3_ai_assembly" / "benchmark.yaml"
SCORE_SCRIPT = ROOT / "benchmarks" / "m3_ai_assembly" / "scripts" / "score_report.py"
PACKAGE_SCRIPT = ROOT / "benchmarks" / "m3_ai_assembly" / "scripts" / "package_testkit.py"


def _load_score_module():
    spec = importlib.util.spec_from_file_location("m3_score_report", SCORE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_package_module():
    spec = importlib.util.spec_from_file_location("m3_package_testkit", PACKAGE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestM3BenchmarkScripts(unittest.TestCase):
    def test_benchmark_yaml_loads(self):
        data = yaml.safe_load(BENCHMARK.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], "m3_ai_assembly_benchmark.v0.1")
        self.assertIn("hard_fail_finding_ids", data["grader"])

    def test_score_report_warns_without_hard_fail(self):
        scorer = _load_score_module()
        benchmark = yaml.safe_load(BENCHMARK.read_text(encoding="utf-8"))
        score = scorer.score_report({
            "cadclaw_report": {
                "overall": "warn",
                "findings": [
                    {
                        "id": "assemble.not_built_yet",
                        "category": "assemble",
                        "severity": "warn",
                        "message": "motors pending",
                    }
                ],
                "meta": {
                    "dry_run": True,
                    "build": {"missing_sources": 0},
                    "render": {"skipped": True},
                },
            }
        }, benchmark)
        self.assertFalse(score["hard_failed"])
        self.assertGreater(score["score"], 0)
        self.assertEqual(score["finding_counts"]["not_built_yet"], 1)

    def test_score_report_hard_fails_on_missing_source(self):
        scorer = _load_score_module()
        benchmark = yaml.safe_load(BENCHMARK.read_text(encoding="utf-8"))
        score = scorer.score_report({
            "cadclaw_report": {
                "overall": "fail",
                "findings": [
                    {
                        "id": "assemble.source_missing",
                        "category": "assemble",
                        "severity": "fail",
                        "message": "source missing",
                    }
                ],
                "meta": {"dry_run": True, "build": {"missing_sources": 1}},
            }
        }, benchmark)
        self.assertTrue(score["hard_failed"])
        self.assertEqual(score["score"], 0.0)

    def test_package_testkit_builds_text_scaffold_zip(self):
        packager = _load_package_module()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "m3_testkit.zip"
            summary = packager.build_package(output)
            self.assertTrue(output.exists())
            self.assertGreater(summary["file_count"], 5)
            with zipfile.ZipFile(output) as zf:
                names = set(zf.namelist())
            self.assertIn("benchmarks/m3_ai_assembly/package_manifest.json", names)
            self.assertIn("examples/m3_crete/m3_testkit_assets.yaml", names)
            self.assertIn("examples/m3_crete/m3_bom_audit.yaml", names)
            self.assertFalse(any(name.lower().endswith(".step") for name in names))


if __name__ == "__main__":
    unittest.main()
