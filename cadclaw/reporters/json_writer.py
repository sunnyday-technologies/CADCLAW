"""JSON reporter — stable, versioned envelope for MCP and CI consumption."""
from __future__ import annotations

import json

from ..findings import Report


def render_json(report: Report, indent: int = 2) -> str:
    """Render a Report as canonical JSON. Schema is locked at report.schema_version."""
    return json.dumps(report.to_dict(), indent=indent, sort_keys=False, default=str)
