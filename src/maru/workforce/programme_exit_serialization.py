"""Explicit portable Programme Shift-link schema without personnel disclosure."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from maru.programme.exit_archive_protocol import (
    ProgrammeArchiveInvalidError,
    ProgrammeArchiveSection,
)
from maru.programme.staffing_inputs import ProgrammeStaffingSource

from .programme_binding_queries import (
    ProgrammeBindingHistoryEntry,
    ProgrammeBindingView,
)
from .programme_exit_queries import ProgrammeExitBinding

MAX_OWNER_JSON_BYTES: Final = 67_108_864
EXCLUSIONS: Final = (
    "unrelated-work",
    "worker-identities",
    "private-commitment-reasons",
    "availability-calendars",
)


def _uuid(value: UUID | None, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not UUID or not value.int:
        raise ProgrammeArchiveInvalidError
    return str(value)


def _integer(value: int) -> int:
    if type(value) is not int or not 1 <= value < 2**63:
        raise ProgrammeArchiveInvalidError
    return value


def _text(value: str) -> str:
    if type(value) is not str:
        raise ProgrammeArchiveInvalidError
    return value


def _source(value: ProgrammeStaffingSource) -> dict[str, object]:
    if type(value) is not ProgrammeStaffingSource:
        raise ProgrammeArchiveInvalidError
    return {
        "requirement_id": _uuid(value.requirement_id),
        "requirement_revision_id": _uuid(value.requirement_revision_id),
        "requirement_version": _integer(value.requirement_version),
        "occurrence_id": _uuid(value.occurrence_id),
        "occurrence_version": _integer(value.occurrence_version),
        "candidate_id": _uuid(value.candidate_id),
        "candidate_revision_id": _uuid(value.candidate_revision_id),
        "placement_id": _uuid(value.placement_id),
    }


def _binding(value: ProgrammeBindingView) -> dict[str, object]:
    if type(value) is not ProgrammeBindingView:
        raise ProgrammeArchiveInvalidError
    return {
        "binding_id": _uuid(value.binding_id),
        "version": _integer(value.version),
        "revision_id": _uuid(value.revision_id),
        "source": _source(value.source),
        "demand_id": _uuid(value.demand_id),
        "demand_version": _integer(value.demand_version),
        "work_terms_digest": _text(value.work_terms_digest),
        "source_digest": _text(value.source_digest),
        "operation": _text(value.operation),
        "predecessor_id": _uuid(value.predecessor_id, nullable=True),
    }


def _history(value: ProgrammeBindingHistoryEntry) -> dict[str, object]:
    if type(value) is not ProgrammeBindingHistoryEntry:
        raise ProgrammeArchiveInvalidError
    instant = value.occurred_at
    if (
        type(instant) is not datetime
        or instant.tzinfo is None
        or instant.utcoffset() is None
    ):
        raise ProgrammeArchiveInvalidError
    return {
        "binding": _binding(value.binding),
        "actor_id": _uuid(value.actor_id),
        "reason": _text(value.reason),
        "occurred_at": instant.astimezone(UTC).isoformat(),
    }


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _schema() -> bytes:
    identifier = {"type": "string", "format": "uuid"}
    integer = {"type": "integer", "minimum": 1, "maximum": 2**63 - 1}
    source = _object(
        {
            "requirement_id": identifier,
            "requirement_revision_id": identifier,
            "requirement_version": integer,
            "occurrence_id": identifier,
            "occurrence_version": integer,
            "candidate_id": identifier,
            "candidate_revision_id": identifier,
            "placement_id": identifier,
        }
    )
    binding = _object(
        {
            "binding_id": identifier,
            "version": integer,
            "revision_id": identifier,
            "source": {"$ref": "#/$defs/source"},
            "demand_id": identifier,
            "demand_version": integer,
            "work_terms_digest": {"type": "string"},
            "source_digest": {"type": "string"},
            "operation": {"type": "string"},
            "predecessor_id": {"anyOf": [identifier, {"type": "null"}]},
        }
    )
    history = _object(
        {
            "binding": {"$ref": "#/$defs/binding"},
            "actor_id": identifier,
            "reason": {"type": "string"},
            "occurred_at": {"type": "string", "format": "date-time"},
        }
    )
    item = _object(
        {
            "item_id": identifier,
            "current": {"$ref": "#/$defs/binding"},
            "history": {"type": "array", "items": {"$ref": "#/$defs/history"}},
        }
    )
    root = _object(
        {
            "scope": {"const": "programme-shift-links@1"},
            "purpose_exclusions": {"const": list(EXCLUSIONS)},
            "bindings": {"type": "array", "items": {"$ref": "#/$defs/item"}},
        }
    )
    return json.dumps(
        {
            **root,
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "source": source,
                "binding": binding,
                "history": history,
                "item": item,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def serialize_programme_exit_bindings(
    bindings: tuple[ProgrammeExitBinding, ...],
) -> ProgrammeArchiveSection:
    """Encode only explicit Shift-link provenance and separately authorized history.

    Parameters
    ----------
    bindings : tuple[ProgrammeExitBinding, ...]
        Complete owner-authorized collection, not a worker directory or draft import.

    Returns
    -------
    ProgrammeArchiveSection
        Deterministic closed JSON/schema with explicit private-data exclusions.

    Raises
    ------
    ProgrammeArchiveInvalidError
        If any selected shape, UUID, integer, instant, UTF-8 or byte budget is invalid.

    Notes
    -----
    Encoding grants no source rights. Every field is explicitly named; new DTO
    fields, ORM rows, retry payloads and private Workforce data are not discovered.
    """
    if type(bindings) is not tuple or any(
        type(row) is not ProgrammeExitBinding for row in bindings
    ):
        raise ProgrammeArchiveInvalidError
    try:
        records = []
        remaining = MAX_OWNER_JSON_BYTES
        for row in bindings:
            if type(row.history) is not tuple:
                raise ProgrammeArchiveInvalidError
            record = {
                "item_id": _uuid(row.item_id),
                "current": _binding(row.current),
                "history": [_history(entry) for entry in row.history],
            }
            remaining -= len(
                json.dumps(
                    record, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
            )
            if remaining < 0:
                raise ProgrammeArchiveInvalidError
            records.append(record)
        data = json.dumps(
            {
                "scope": "programme-shift-links@1",
                "purpose_exclusions": EXCLUSIONS,
                "bindings": records,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise ProgrammeArchiveInvalidError from None
    if len(data) > MAX_OWNER_JSON_BYTES:
        raise ProgrammeArchiveInvalidError
    return ProgrammeArchiveSection(
        "workforce", "workforce.programme-exit@1", data, _schema()
    )
