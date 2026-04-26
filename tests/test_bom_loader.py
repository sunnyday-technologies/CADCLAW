"""Tests for cadharness/bom_loader.py — top-level shape acceptance."""
import json
import os
import tempfile
import unittest

from cadharness.bom_loader import (
    ALWAYS_PRIVATE,
    BomLoadError,
    PUBLIC_ALLOWLIST,
    is_exempt_from_cad,
    load_bom,
    to_public_dict,
)


def _write_tmp_json(data) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        return f.name


_MIN_ITEM = {"id": 1, "name": "thing", "qty": 1, "mfg_type": "buy"}


class TestTopLevelShapes(unittest.TestCase):
    """The loader must accept three shapes and reject the rest."""

    def test_accepts_top_level_list(self):
        path = _write_tmp_json([_MIN_ITEM])
        try:
            items = load_bom(path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], 1)
        finally:
            os.unlink(path)

    def test_accepts_items_key(self):
        path = _write_tmp_json({"items": [_MIN_ITEM], "version": "1.0"})
        try:
            items = load_bom(path)
            self.assertEqual(len(items), 1)
        finally:
            os.unlink(path)

    def test_accepts_parts_key(self):
        """HIGH-1 (M3-CRETE field test): hardware BOMs use `parts:` more often
        than `items:`. Loader must accept both interchangeably."""
        path = _write_tmp_json({
            "version": "0.6",
            "generated": "2026-04-26",
            "source": "M3-CRETE",
            "notes": "test fixture for the parts-key shape",
            "parts": [_MIN_ITEM],
        })
        try:
            items = load_bom(path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], 1)
        finally:
            os.unlink(path)

    def test_items_wins_over_parts_when_both_present(self):
        # `items` is the preferred key; if both are set it should be authoritative.
        items_winner = {"id": 99, "name": "from_items", "qty": 1, "mfg_type": "buy"}
        parts_loser = {"id": 1, "name": "from_parts", "qty": 1, "mfg_type": "buy"}
        path = _write_tmp_json({"items": [items_winner], "parts": [parts_loser]})
        try:
            items = load_bom(path)
            self.assertEqual(items[0]["id"], 99)
        finally:
            os.unlink(path)

    def test_rejects_unknown_top_level_keys(self):
        # Regression guard against being too promiscuous: a list under an
        # unexpected key (e.g. `bom`, `data`, `entries`) must NOT be accepted.
        path = _write_tmp_json({"bom": [_MIN_ITEM]})
        try:
            with self.assertRaises(BomLoadError) as ctx:
                load_bom(path)
            self.assertIn("items", str(ctx.exception))
            self.assertIn("parts", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_rejects_string_top_level(self):
        path = _write_tmp_json("not a bom")
        try:
            with self.assertRaises(BomLoadError):
                load_bom(path)
        finally:
            os.unlink(path)

    def test_rejects_non_list_under_known_key(self):
        path = _write_tmp_json({"parts": "not a list"})
        try:
            with self.assertRaises(BomLoadError):
                load_bom(path)
        finally:
            os.unlink(path)


class TestRequiredFieldValidation(unittest.TestCase):
    def test_missing_id_rejected(self):
        path = _write_tmp_json([{"name": "x", "qty": 1, "mfg_type": "buy"}])
        try:
            with self.assertRaises(BomLoadError) as ctx:
                load_bom(path)
            self.assertIn("'id'", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_missing_mfg_type_rejected(self):
        path = _write_tmp_json([{"id": 1, "name": "x", "qty": 1}])
        try:
            with self.assertRaises(BomLoadError):
                load_bom(path)
        finally:
            os.unlink(path)


class TestPrivacyProjection(unittest.TestCase):
    def test_to_public_dict_drops_vendors(self):
        item = {**_MIN_ITEM, "vendors": [{"name": "Acme", "price": 99.99}]}
        public = to_public_dict(item)
        self.assertNotIn("vendors", public)

    def test_to_public_dict_drops_underscore_keys(self):
        item = {**_MIN_ITEM, "_internal_id": "PRIVATE-001"}
        public = to_public_dict(item)
        self.assertNotIn("_internal_id", public)

    def test_to_public_dict_keeps_allowlisted_fields(self):
        item = {
            **_MIN_ITEM,
            "description": "a thing",
            "notes": "alignment aid",
            "tags": ["frame"],
        }
        public = to_public_dict(item)
        for key in ("id", "name", "qty", "mfg_type", "description", "notes", "tags"):
            self.assertIn(key, public)

    def test_always_private_keys_match_documented_set(self):
        # Lock-in: this is a contract. Bumping it is a privacy-policy change.
        self.assertEqual(
            set(ALWAYS_PRIVATE),
            {"vendors", "sku", "unit_cost", "cost", "price", "supplier"},
        )


class TestExemptionLogic(unittest.TestCase):
    def test_consumable_exempt(self):
        self.assertTrue(is_exempt_from_cad({**_MIN_ITEM, "mfg_type": "consumable"}))

    def test_electronic_exempt(self):
        self.assertTrue(is_exempt_from_cad({**_MIN_ITEM, "mfg_type": "electronic"}))

    def test_fastener_exempt(self):
        self.assertTrue(is_exempt_from_cad({**_MIN_ITEM, "mfg_type": "fastener"}))

    def test_explicit_exempt_flag(self):
        self.assertTrue(is_exempt_from_cad(
            {**_MIN_ITEM, "exempt_from_cad": True}
        ))

    def test_exempt_tag(self):
        self.assertTrue(is_exempt_from_cad(
            {**_MIN_ITEM, "tags": ["frame", "exempt"]}
        ))

    def test_buy_not_exempt(self):
        self.assertFalse(is_exempt_from_cad({**_MIN_ITEM, "mfg_type": "buy"}))


if __name__ == "__main__":
    unittest.main()
