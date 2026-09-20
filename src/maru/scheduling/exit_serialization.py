"""Portable historical Scheduling records, never a live timetable export."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, cast
from uuid import UUID

from maru.programme.exit_archive_protocol import (
    ProgrammeArchiveInvalidError,
    ProgrammeArchiveSection,
)

from . import planning_queries as planning
from .catalogs import SchedulingOperation
from .exit_queries import (
    DAY_COLUMNS,
    OCCURRENCE_COLUMNS,
    SchedulingExitOwner,
    SchedulingExitRelease,
)
from .release_artifacts import CanonicalReleaseArtifact
from .release_workspace_queries import ReleaseHistoryEntry, ReleasePointerObservation
from .time_rules import SchedulingEnvelope, SchedulingWindow

if TYPE_CHECKING:
    from collections.abc import Mapping

type JsonValue = str | int | bool | None | list[JsonValue] | dict[str, JsonValue]
MAX_OWNER_JSON_BYTES: Final = 134_217_728
MAX_OWNER_VALUE_NODES: Final = 2_000_000
MAX_RECORD_DEPTH: Final = 32
_RECORDS: Final[Mapping[type, tuple[str, tuple[str, ...]]]] = MappingProxyType(
    {
        SchedulingExitOwner: (
            "owner",
            (
                "planning",
                "manifests",
                "day_revisions",
                "occurrence_revisions",
                "pointer",
                "release_history",
                "releases",
            ),
        ),
        SchedulingExitRelease: (
            "release",
            (
                "release_id",
                "approval_id",
                "candidate_revision_id",
                "previous_release_id",
                "pointer_version",
                "source_digest",
                "artifact",
            ),
        ),
        CanonicalReleaseArtifact: (
            "canonical_artifact",
            ("contract", "payload", "sha256", "byte_length"),
        ),
        planning.SchedulingPlanningSnapshot: (
            "planning",
            (
                "control_version",
                "edition_version",
                "accepts_writes",
                "days",
                "occurrences",
                "candidates",
                "selected_candidate_id",
                "placements",
                "zone_name",
            ),
        ),
        planning.PlanningDay: (
            "day",
            (
                "id",
                "revision_id",
                "version",
                "label",
                "lifecycle",
                "window",
                "precision_minutes",
            ),
        ),
        planning.PlanningOccurrence: (
            "occurrence",
            (
                "id",
                "revision_id",
                "version",
                "item_id",
                "lifecycle",
                "group_key",
                "group_sequence",
            ),
        ),
        planning.PlanningCandidate: (
            "candidate",
            ("id", "revision_id", "version", "label", "lifecycle", "placement_count"),
        ),
        planning.PlanningPlacement: (
            "placement",
            (
                "id",
                "occurrence_id",
                "occurrence_revision_id",
                "day_revision_id",
                "space_id",
                "capacity_mode",
                "expected_attendance",
                "envelope",
                "day_id",
            ),
        ),
        planning.PlanningHistoryEntry: (
            "candidate_revision",
            (
                "revision_id",
                "version",
                "label",
                "operation",
                "source_revision_id",
                "placement_count",
                "actor_id",
                "reason",
                "occurred_at",
            ),
        ),
        planning.PlanningHistoricalManifest: (
            "candidate_manifest",
            ("candidate_id", "entry", "placements"),
        ),
        SchedulingWindow: ("window", ("starts_at", "ends_at")),
        SchedulingEnvelope: (
            "envelope",
            (
                "setup_starts_at",
                "effective_starts_at",
                "effective_ends_at",
                "teardown_ends_at",
            ),
        ),
        ReleasePointerObservation: ("pointer", ("active_release_id", "version")),
        ReleaseHistoryEntry: (
            "release_history",
            (
                "id",
                "release_id",
                "operation",
                "version",
                "actor_id",
                "reason",
                "occurred_at",
            ),
        ),
    }
)


def _field(record: object, key: str) -> object:
    if type(record) is CanonicalReleaseArtifact and key == "payload":
        if type(record.payload) is not bytes:
            raise ProgrammeArchiveInvalidError
        return record.payload.decode("utf-8")
    return getattr(record, key)


def _value(  # noqa: PLR0911 -- deliberate closed dispatch, never model reflection.
    value: object, budget: list[int], depth: int = 0
) -> JsonValue:
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_RECORD_DEPTH:
        raise ProgrammeArchiveInvalidError
    if value is None:
        return None
    if type(value) is str:
        budget[1] -= len(value.encode("utf-8"))
        if budget[1] < 0:
            raise ProgrammeArchiveInvalidError
        return value
    if type(value) in (int, bool):
        return cast("int | bool", value)
    if type(value) is UUID:
        if not value.int:
            raise ProgrammeArchiveInvalidError
        return str(value)
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ProgrammeArchiveInvalidError
        return value.astimezone(UTC).isoformat()
    if type(value) is SchedulingOperation:
        return value.value
    if type(value) is tuple:
        return [_value(item, budget, depth + 1) for item in value]
    declaration = _RECORDS.get(type(value))
    if declaration is None:
        raise ProgrammeArchiveInvalidError
    name, fields = declaration
    return {
        "$record": name,
        **{key: _value(_field(value, key), budget, depth + 1) for key in fields},
    }


def _schema() -> bytes:
    definitions = {
        name: {
            "type": "object",
            "properties": {
                "$record": {"const": name},
                **{key: {"$ref": "#/$defs/value"} for key in fields},
            },
            "required": ["$record", *fields],
            "additionalProperties": False,
        }
        for name, fields in _RECORDS.values()
    }
    definitions["value"] = {
        "anyOf": [
            {"type": ["string", "integer", "boolean", "null"]},
            {"type": "array", "items": {"$ref": "#/$defs/value"}},
            *({"$ref": f"#/$defs/{name}"} for name, _fields in _RECORDS.values()),
        ]
    }
    properties = {
        "purpose": {"const": "historical-evidence-not-current-timetable"},
        "day_columns": {"const": list(DAY_COLUMNS)},
        "occurrence_columns": {"const": list(OCCURRENCE_COLUMNS)},
        "evidence": {"$ref": "#/$defs/owner"},
    }
    return json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Restricted Scheduling exit evidence v1",
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
            "$defs": definitions,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def serialize_scheduling_exit_owner(
    snapshot: SchedulingExitOwner,
) -> ProgrammeArchiveSection:
    """Encode only closed owner records and lossless canonical artifact text.

    Parameters
    ----------
    snapshot : SchedulingExitOwner
        Complete currently authorized collection, not an arbitrary model graph.

    Returns
    -------
    ProgrammeArchiveSection
        Deterministic UTF-8 JSON/schema with explicit historical-only meaning.

    Raises
    ------
    ProgrammeArchiveInvalidError
        If record types, selected values, UTF-8 encoding or resource bounds fail.

    Notes
    -----
    This pure encoding grants no authority, verifies no source permissions and
    never labels old release bytes as a usable current timetable. Canonical bytes
    were independently verified by the owning collector; payload strings retain
    their exact UTF-8 byte representation, without generic binary serialization.
    """
    if type(snapshot) is not SchedulingExitOwner:
        raise ProgrammeArchiveInvalidError
    try:
        document = {
            "purpose": "historical-evidence-not-current-timetable",
            "day_columns": DAY_COLUMNS,
            "occurrence_columns": OCCURRENCE_COLUMNS,
            "evidence": _value(snapshot, [MAX_OWNER_VALUE_NODES, MAX_OWNER_JSON_BYTES]),
        }
        data = json.dumps(
            document,
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
        "scheduling", "scheduling.programme-exit@1", data, _schema()
    )
