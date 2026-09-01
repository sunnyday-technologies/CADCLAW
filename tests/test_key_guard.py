"""Regression tests for the public-repository answer-key path guard."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestAnswerKeyGuard(unittest.TestCase):
    def _scan_path(self, path: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_no_answer_keys.py"), "--stdin"],
            cwd=ROOT,
            input=f"{path}\n",
            text=True,
            capture_output=True,
            check=False,
        )

    def test_reference_stp_is_blocked(self):
        candidate = "private/reference_model.stp"
        result = self._scan_path(candidate)
        self.assertEqual(result.returncode, 1)
        self.assertIn("status=blocked", result.stderr)
        self.assertNotIn(candidate, result.stderr)

    def test_marb_round1_stp_is_blocked(self):
        result = self._scan_path("bench/m3_reference_round1.stp")
        self.assertEqual(result.returncode, 1)

    def test_approved_nist_fixture_name_is_not_key_shaped(self):
        result = self._scan_path(
            "tests/fixtures/pmi_semantic/nist_ftc_11_asme1_ap242-e2.stp"
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
