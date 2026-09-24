"""Explicit portable Programme owner records, never model or DTO field discovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, cast
from uuid import UUID

from . import host_queries as hosts
from . import queries as core
from . import staffing_queries as staffing
from .exit_archive_protocol import ProgrammeArchiveInvalidError, ProgrammeArchiveSection
from .exit_core_queries import ProgrammeExitCore
from .exit_item_queries import ProgrammeExitItem
from .exit_lineage_queries import ProgrammeExitLineage, ProgrammeExitLineageCollection
from .exit_owner_queries import ProgrammeExitOwner, ProgrammeExitOwnerItem
from .exit_placement_queries import ProgrammeExitPlacementStream
from .host_inputs import ProgrammeHostAvailabilityPeriod
from .placement_queries import (
    ProgrammePlacementHistoryEntry,
    ProgrammePlacementHistoryHead,
)
from .release_inputs import ProgrammePlacementDecisionKind
from .staffing_inputs import ProgrammeStaffingExpectation

if TYPE_CHECKING:
    from collections.abc import Mapping

type JsonValue = str | int | bool | None | list[JsonValue] | dict[str, JsonValue]

MAX_OWNER_JSON_BYTES: Final = 67_108_864
MAX_OWNER_VALUE_NODES: Final = 2_000_000
MAX_RECORD_DEPTH: Final = 32

# Versioned, deliberate field selection. Never replace with asdict/fields/vars
# or model inspection: ordinary DTO evolution must not expand archive disclosure.
_RECORDS: Final[Mapping[type, tuple[str, tuple[str, ...]]]] = MappingProxyType(
    {
        ProgrammeExitOwner: ("owner", ("organization_id", "edition_id", "items")),
        ProgrammeExitOwnerItem: ("owner_item", ("content", "lineage", "placements")),
        ProgrammeExitItem: (
            "item_content",
            (
                "core",
                "roster",
                "host_histories",
                "host_dependencies",
                "staffing",
                "staffing_histories",
            ),
        ),
        ProgrammeExitCore: (
            "core",
            (
                "private",
                "working",
                "delivery",
                "discussion",
                "readiness",
                "copy_reviews",
            ),
        ),
        core.ProgrammePrivateItemProjection: ("private_item", ("item", "working")),
        core.ProgrammeItemProjection: (
            "item",
            ("id", "kind", "provenance_kind", "lifecycle", "aggregate_version"),
        ),
        core.ProgrammeWorkingProjection: (
            "working",
            ("internal_title", "working_summary", "item_version"),
        ),
        core.ProgrammeWorkingHistoryEntryProjection: (
            "working_revision",
            (
                "sequence",
                "internal_title",
                "working_summary",
                "actor_id",
                "reason",
                "occurred_at",
                "item_version",
            ),
        ),
        core.ProgrammeDeliveryHistoryEntryProjection: (
            "delivery_revision",
            (
                "sequence",
                "technical_requirements",
                "accessibility_delivery",
                "media_consent_notes",
                "actor_id",
                "reason",
                "occurred_at",
                "item_version",
            ),
        ),
        core.ProgrammeDiscussionEntryProjection: (
            "discussion",
            ("sequence", "body", "actor_id", "reason", "occurred_at", "item_version"),
        ),
        core.ProgrammeReadinessHistoryEntryProjection: (
            "readiness_history",
            (
                "concern",
                "kind",
                "sequence",
                "item_version",
                "requirement_version",
                "dependency_version",
                "disposition",
                "state",
                "source_code",
                "source_version",
                "note",
                "actor_id",
                "reason",
                "occurred_at",
            ),
        ),
        core.ProgrammePublicCopyReviewHistoryEntryProjection: (
            "copy_review",
            (
                "rendition_number",
                "source_item_version",
                "public_title",
                "public_summary",
                "public_content_note",
                "actor_id",
                "reason",
                "occurred_at",
                "withdrawn_at",
                "withdrawn_by_id",
                "withdrawal_reason",
            ),
        ),
        hosts.ProgrammeHostRosterSnapshot: ("roster", ("item_version", "entries")),
        hosts.ProgrammeHostRosterEntry: (
            "roster_entry",
            ("relationship", "account_id", "person_current", "display_label"),
        ),
        hosts.ProgrammeHostStateProjection: (
            "host_state",
            ("host_id", "role", "state", "version", "invitation_sequence"),
        ),
        hosts.ProgrammeHostHistoryEntry: (
            "host_history",
            (
                "relationship",
                "operation",
                "actor_id",
                "reason",
                "occurred_at",
                "item_version",
            ),
        ),
        hosts.ProgrammeHostDependencySnapshot: (
            "host_dependencies",
            ("item_id", "item_version", "edition_version", "contract", "hosts"),
        ),
        hosts.ProgrammeHostAvailabilityProjection: (
            "host_availability",
            ("host_id", "host_version", "availability_version", "status", "periods"),
        ),
        ProgrammeHostAvailabilityPeriod: (
            "shared_period",
            ("starts_at", "ends_at", "kind"),
        ),
        staffing.ProgrammeStaffingOverview: (
            "staffing",
            ("item_id", "item_version", "requirements", "item_lifecycle"),
        ),
        staffing.ProgrammeStaffingRequirementView: (
            "staffing_requirement",
            (
                "requirement_id",
                "occurrence_id",
                "version",
                "revision_id",
                "item_version",
                "occurrence_version",
                "lifecycle",
                "expectation",
            ),
        ),
        ProgrammeStaffingExpectation: (
            "staffing_expectation",
            (
                "position_id",
                "title",
                "location_label",
                "briefing",
                "supervision_note",
                "starts_at",
                "ends_at",
                "required_headcount",
                "break_minutes",
                "minimum_rest_minutes",
            ),
        ),
        staffing.ProgrammeStaffingHistoryEntry: (
            "staffing_history",
            ("requirement", "operation", "actor_id", "reason", "occurred_at"),
        ),
        ProgrammeExitPlacementStream: ("placement_stream", ("kind", "head", "entries")),
        ProgrammePlacementHistoryHead: (
            "placement_head",
            ("placement_id", "through_sequence"),
        ),
        ProgrammePlacementHistoryEntry: (
            "placement_decision",
            (
                "decision_id",
                "sequence",
                "state",
                "candidate_revision_id",
                "item_version",
                "source_digest",
                "actor_id",
                "reason",
                "occurred_at",
            ),
        ),
        ProgrammeExitLineage: ("lineage", ("item_id", "item_version", "collections")),
        ProgrammeExitLineageCollection: (
            "lineage_collection",
            ("name", "columns", "rows"),
        ),
    }
)


def _value(  # noqa: PLR0911 - explicit closed type dispatch, no reflective fallback
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
        if value.int == 0:
            raise ProgrammeArchiveInvalidError
        return str(value)
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ProgrammeArchiveInvalidError
        return value.astimezone(UTC).isoformat()
    if type(value) is ProgrammePlacementDecisionKind:
        return value.value
    if type(value) is tuple:
        return [_value(item, budget, depth + 1) for item in value]
    declaration = _RECORDS.get(type(value))
    if declaration is None:
        raise ProgrammeArchiveInvalidError
    name, attributes = declaration
    return {
        "$record": name,
        **{key: _value(getattr(value, key), budget, depth + 1) for key in attributes},
    }


def _schema() -> bytes:
    definitions = {
        name: {
            "type": "object",
            "properties": {
                "$record": {"const": name},
                **{key: {"$ref": "#/$defs/value"} for key in attributes},
            },
            "required": ["$record", *attributes],
            "additionalProperties": False,
        }
        for name, attributes in _RECORDS.values()
    }
    definitions["value"] = {
        "anyOf": [
            {"type": ["string", "integer", "boolean", "null"]},
            {"type": "array", "items": {"$ref": "#/$defs/value"}},
            *({"$ref": f"#/$defs/{name}"} for name, _attrs in _RECORDS.values()),
        ]
    }
    return json.dumps(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Restricted Programme-owned exit evidence v1",
            "$ref": "#/$defs/owner",
            "$defs": definitions,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def serialize_programme_exit_owner(
    snapshot: ProgrammeExitOwner,
) -> ProgrammeArchiveSection:
    """Encode explicit owner-selected fields and their portable closed record schema.

    Parameters
    ----------
    snapshot : ProgrammeExitOwner
        Complete currently authorized owner collection supplied by the composer.
        Constructing this DTO or encoding it is never proof of source authority.

    Returns
    -------
    ProgrammeArchiveSection
        Deterministic UTF-8 JSON data/schema for the larger archive packaging path.

    Raises
    ------
    ProgrammeArchiveInvalidError
        If the type, selected values, portable encoding or resource bounds fail.

    Notes
    -----
    This pure serializer performs no reads, writes or authorization. Its 64 MiB
    owner JSON ceiling intentionally exceeds the initial memory codec's 2 MiB
    limit; the complete background packaging/custody path must enforce its own
    larger declared envelope, never weaken the initial primitive's contract.
    """
    if type(snapshot) is not ProgrammeExitOwner:
        raise ProgrammeArchiveInvalidError
    try:
        projected = _value(snapshot, [MAX_OWNER_VALUE_NODES, MAX_OWNER_JSON_BYTES])
        encoded = json.dumps(
            projected,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise ProgrammeArchiveInvalidError from None
    if len(encoded) > MAX_OWNER_JSON_BYTES:
        raise ProgrammeArchiveInvalidError
    return ProgrammeArchiveSection(
        "programme", "programme.programme-exit@1", encoded, _schema()
    )
