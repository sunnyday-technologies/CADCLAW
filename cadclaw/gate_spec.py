"""Version tag for CADCLAW's declared gate methods.

This is deliberately separate from the package version, the ``cadclaw.yaml``
rules schema, and the JSON report schema.  Gate behavior can evolve without
silently re-labelling historical reports or forcing a breaking rules migration.
"""

GATE_SPEC_VERSION = "0.13.0"
