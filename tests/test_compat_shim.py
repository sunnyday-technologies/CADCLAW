"""v0.8.0 — verify the `cadharness` → `cadclaw` rename compat shim.

Three things must hold:
  1. `import cadharness` works AND emits a DeprecationWarning.
  2. `from cadharness.<sub> import Y` resolves to the same Y as
     `from cadclaw.<sub> import Y` (no duplicated state).
  3. The shim's version matches `cadclaw.__version__`.
"""
from __future__ import annotations

import importlib
import sys
import unittest
import warnings


class TestCompatShim(unittest.TestCase):
    def _reimport_cadharness(self):
        for name in list(sys.modules):
            if name == "cadharness" or name.startswith("cadharness."):
                del sys.modules[name]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            importlib.import_module("cadharness")
            return list(caught)

    def test_cadharness_import_emits_deprecation_warning(self):
        caught = self._reimport_cadharness()
        deprecations = [w for w in caught
                        if issubclass(w.category, DeprecationWarning)]
        self.assertGreaterEqual(len(deprecations), 1,
                                 "Expected at least one DeprecationWarning on `import cadharness`")
        msg = str(deprecations[0].message)
        self.assertIn("cadharness", msg)
        self.assertIn("cadclaw", msg)
        self.assertIn("v0.8.0", msg)

    def test_cadharness_version_matches_cadclaw(self):
        self._reimport_cadharness()
        import cadharness
        import cadclaw
        self.assertEqual(cadharness.__version__, cadclaw.__version__)

    def test_submodule_imports_resolve_to_cadclaw(self):
        self._reimport_cadharness()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from cadharness.bom_audit import run_bom_audit as old_fn
            from cadclaw.bom_audit import run_bom_audit as new_fn
        self.assertIs(old_fn, new_fn)

    def test_findings_class_identity(self):
        self._reimport_cadharness()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from cadharness.findings import Finding as OldFinding
            from cadclaw.findings import Finding as NewFinding
        self.assertIs(OldFinding, NewFinding)

    def test_reporters_subpackage_resolves(self):
        """Subpackage shim — `cadharness.reporters.text` must work."""
        self._reimport_cadharness()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from cadharness.reporters.text import render_text as old_fn
            from cadclaw.reporters.text import render_text as new_fn
        self.assertIs(old_fn, new_fn)

    def test_attribute_access_falls_through(self):
        """`cadharness.<sub>` attribute access (not just `from ... import`)."""
        self._reimport_cadharness()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import cadharness
            import cadclaw
            self.assertIs(cadharness.bom_audit, cadclaw.bom_audit)
            self.assertIs(cadharness.inspect, cadclaw.inspect)


if __name__ == "__main__":
    unittest.main()
