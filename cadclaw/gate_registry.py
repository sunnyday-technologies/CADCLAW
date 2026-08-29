"""Versioned gate identities and fail-closed harness selection.

The registry is deliberately independent of the CLI so library and MCP
callers resolve the same gate names without duplicating selector rules.
It records only gates wired into the YAML-backed union harness; a name that is
not in this registry is not executable through that entry point.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Optional, Tuple, Union


GateNames = Optional[Union[str, Iterable[str]]]


class GateSelectionError(ValueError):
    """The requested gate identities do not form an executable selection."""

    _SAFE_MESSAGES = {
        "invalid_selector_type": "gate selector has an invalid type",
        "empty_selector": "gate selector must name at least one gate",
        "non_string_gate": "gate selector identities must be strings",
        "empty_gate_id": "gate selector contains an empty identity",
        "duplicate_gate": "gate selector contains a duplicate identity",
        "unknown_gate": "gate selector contains an unknown identity",
        "overlapping_selectors": "gate selectors overlap",
        "empty_selection": "gate selection is empty",
    }

    def __init__(self, reason_code: str, message: str | None = None):
        self.reason_code = reason_code
        super().__init__(self._SAFE_MESSAGES.get(
            reason_code,
            "gate selection is invalid",
        ))


class GateStatus(str, Enum):
    """One terminal state for a configured-harness gate.

    The JSON report keeps exactly one of these states for every registered
    gate.  ``error`` means the gate was attempted but could not establish a
    result; it is never treated as ``fail`` evidence about the submitted CAD.
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"
    NOT_CHECKED = "not_checked"
    SKIPPED = "skipped"


@dataclass
class GateLedgerEntry:
    """Mutable internal ledger row serialized through ``to_dict``."""

    gate_id: str
    selected: bool
    configured: bool = False
    status: GateStatus = GateStatus.NOT_CHECKED
    reason: Optional[str] = None
    finding_counts: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "gate_id": self.gate_id,
            "selected": self.selected,
            "configured": self.configured,
            "status": self.status.value,
        }
        if self.reason:
            payload["reason"] = self.reason
        if self.finding_counts is not None:
            payload["finding_counts"] = dict(self.finding_counts)
        return payload


@dataclass(frozen=True)
class GateDefinition:
    """One stable gate identity exposed by the YAML-backed union harness."""

    gate_id: str
    allows_not_applicable: bool = False


@dataclass(frozen=True)
class GateSelection:
    """A validated, deterministic gate selection."""

    registry_version: str
    selected_ids: Tuple[str, ...]
    only_ids: Optional[Tuple[str, ...]]
    skip_ids: Tuple[str, ...]

    def wants(self, gate_id: str) -> bool:
        return gate_id in self.selected_ids


class GateRegistry:
    """Resolve ``only``/``skip`` selectors against versioned gate IDs."""

    def __init__(self, version: str, definitions: Iterable[GateDefinition]):
        self.version = version
        self.definitions = tuple(definitions)
        ids = tuple(definition.gate_id for definition in self.definitions)
        if not ids:
            raise ValueError("a gate registry must contain at least one gate")
        if any(not gate_id or gate_id.strip() != gate_id for gate_id in ids):
            raise ValueError("gate IDs must be non-empty and whitespace-free")
        if len(ids) != len(set(ids)):
            raise ValueError("gate IDs must be unique")
        self.ids = ids
        self._id_set = frozenset(ids)

    @staticmethod
    def _parse_names(value: GateNames, option: str) -> Optional[frozenset[str]]:
        safe_error = None
        try:
            if value is None:
                return None
            if isinstance(value, str):
                raw_names = value.split(",")
            else:
                raw_names = list(value)
            if not raw_names:
                raise GateSelectionError("empty_selector")

            names = []
            for raw_name in raw_names:
                if not isinstance(raw_name, str):
                    raise GateSelectionError("non_string_gate")
                # ``raw_name`` may be a hostile ``str`` subclass whose
                # equality/hash methods raise or expose submitted values after
                # this guarded normalization block. Coerce the trimmed token
                # to an exact built-in string before it reaches a set.
                name = str(raw_name.strip())
                if not name:
                    raise GateSelectionError("empty_gate_id")
                names.append(name)
            if len(names) != len(set(names)):
                raise GateSelectionError("duplicate_gate")
            return frozenset(names)
        except GateSelectionError:
            raise
        except Exception:
            # Custom iterables and string subclasses are untrusted selector
            # input. Never expose their exception text or values.
            safe_error = GateSelectionError("invalid_selector_type")
        # Raise after leaving the source handler so the library exception has
        # neither a visible traceback chain nor a retained raw ``__context__``.
        assert safe_error is not None
        raise safe_error from None

    def _reject_unknown(self, names: frozenset[str], option: str) -> None:
        unknown = sorted(names - self._id_set)
        if unknown:
            raise GateSelectionError("unknown_gate")

    def resolve(self, *, only: GateNames = None, skip: GateNames = None) -> GateSelection:
        """Validate selectors and return IDs in registry order.

        Blank tokens, unknown identities, overlapping selectors, and an empty
        effective selection are input errors.  Failing here prevents an
        autonomous caller from mistaking "no gate ran" for a passing report.
        """
        only_names = self._parse_names(only, "--only")
        skip_names = self._parse_names(skip, "--skip") or frozenset()

        if only_names is not None:
            self._reject_unknown(only_names, "--only")
        self._reject_unknown(skip_names, "--skip")

        overlap = (only_names or frozenset()) & skip_names
        if overlap:
            raise GateSelectionError("overlapping_selectors")

        requested = self._id_set if only_names is None else only_names
        selected = tuple(
            gate_id for gate_id in self.ids
            if gate_id in requested and gate_id not in skip_names
        )
        if not selected:
            raise GateSelectionError("empty_selection")

        ordered_only = (
            None
            if only_names is None
            else tuple(gate_id for gate_id in self.ids if gate_id in only_names)
        )
        ordered_skip = tuple(
            gate_id for gate_id in self.ids if gate_id in skip_names
        )
        return GateSelection(
            registry_version=self.version,
            selected_ids=selected,
            only_ids=ordered_only,
            skip_ids=ordered_skip,
        )

    def allows_not_applicable(self, gate_id: str) -> bool:
        return next(
            definition.allows_not_applicable
            for definition in self.definitions
            if definition.gate_id == gate_id
        )


HARNESS_GATE_REGISTRY = GateRegistry(
    version="harness-gates.v1",
    definitions=(
        GateDefinition("inventory"),
        GateDefinition("interference"),
        GateDefinition("bom_audit"),
        GateDefinition("claim_audit"),
        GateDefinition("publish_audit"),
        GateDefinition("pmi_present", allows_not_applicable=True),
        GateDefinition("roundtrip_step", allows_not_applicable=True),
        GateDefinition("orientation"),
        GateDefinition("floating"),
        GateDefinition("color"),
    ),
)
