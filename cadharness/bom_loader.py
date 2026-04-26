"""
BOM JSON loader + privacy-aware serializer.

The BOM is the public source of truth for procurement. CADCLAW reads it but
never echoes private fields (vendor pricing, internal SKUs, customer order
ids) back to the user, even by accident in a finding's `evidence` block.

Privacy is enforced at the **serializer**, not at the rule layer — that's the
only safe place because a finding can quote any field. `to_public_dict()`
projects through an allowlist; `vendors`, `sku`, `unit_cost`, and any field
prefixed with `_` are always dropped regardless of config.

Schema (canonical, see plan):
  required: id, name, qty, mfg_type
  optional: description, notes, unit, material, category, tags
  always-private (dropped at serialization): vendors, sku, unit_cost, _*
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


REQUIRED_FIELDS = ("id", "name", "qty", "mfg_type")
PUBLIC_ALLOWLIST = (
    "id", "name", "qty", "unit", "mfg_type",
    "material", "category", "tags",
    "description", "notes",
    "exempt_from_cad",
)
ALWAYS_PRIVATE = ("vendors", "sku", "unit_cost", "cost", "price", "supplier")
EXEMPT_MFG_TYPES = ("consumable", "electronic", "fastener")


class BomLoadError(ValueError):
    pass


def load_bom(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Load a BOM JSON file. Returns a list of items.

    Accepts either a top-level list or a top-level `{"items": [...]}` object.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"BOM file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "items" in data:
        items = data["items"]
    elif isinstance(data, list):
        items = data
    else:
        raise BomLoadError(
            f"BOM JSON must be a list or {{items: [...]}}, got {type(data).__name__}"
        )
    if not isinstance(items, list):
        raise BomLoadError("BOM 'items' must be a list")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise BomLoadError(f"BOM item {i} is not an object")
        for field in REQUIRED_FIELDS:
            if field not in item:
                raise BomLoadError(
                    f"BOM item {i} (id={item.get('id', '?')}) missing required field {field!r}"
                )
    return items


def index_bom(items: List[Dict[str, Any]]) -> Dict[Any, Dict[str, Any]]:
    """Index BOM items by id. Raises if duplicate ids found."""
    out: Dict[Any, Dict[str, Any]] = {}
    for item in items:
        iid = item["id"]
        if iid in out:
            raise BomLoadError(f"duplicate BOM id: {iid!r}")
        out[iid] = item
    return out


def to_public_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    """Project a BOM item through the public-fields allowlist.

    Drops anything not in the allowlist. Drops anything in ALWAYS_PRIVATE
    even if it accidentally appears. Drops `_`-prefixed keys.
    """
    return {
        k: v for k, v in item.items()
        if k in PUBLIC_ALLOWLIST
        and k not in ALWAYS_PRIVATE
        and not k.startswith("_")
    }


def is_exempt_from_cad(item: Dict[str, Any]) -> bool:
    """Apply the exemption rule: consumables, electronics, fasteners,
    `exempt_from_cad: true`, or `tags` containing `"exempt"`."""
    if item.get("exempt_from_cad") is True:
        return True
    if item.get("mfg_type") in EXEMPT_MFG_TYPES:
        return True
    tags = item.get("tags") or []
    if isinstance(tags, list) and "exempt" in tags:
        return True
    return False


def haystack_text(item: Dict[str, Any]) -> str:
    """Concatenate searchable text fields for required/forbidden term checks."""
    parts: List[str] = []
    for field in ("name", "description", "notes"):
        v = item.get(field)
        if isinstance(v, str):
            parts.append(v)
    return " ".join(parts)
