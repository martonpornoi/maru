"""Archive only independently authorized Programme room wayfinding identities."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final, TypedDict
from uuid import UUID

from django.db import transaction

from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER
from maru.programme.exit_archive_protocol import ProgrammeArchiveSection
from maru.workforce.programme_references import lock_programme_staffing_scope

from .timetable_queries import (
    MAX_TIMETABLE_SPACES,
    VenueTimetableQueryUnavailableError,
    VenueTimetableSpace,
    list_venue_timetable_spaces,
)

if TYPE_CHECKING:
    from maru.programme.authorization import ProgrammeAuthorizer

MAX_EXIT_JSON_BYTES: Final = 2_097_152
EXCLUSIONS: Final = (
    "property-contacts",
    "layout-security-access-documents",
    "opening-restrictions",
    "unrelated-bookings",
    "foreign-busy-calendars",
)


class _Arguments(TypedDict):
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID


def _space(row: VenueTimetableSpace) -> dict[str, object]:
    if (
        type(row) is not VenueTimetableSpace
        or type(row.id) is not UUID
        or type(row.venue_id) is not UUID
        or not row.id.int
        or not row.venue_id.int
        or type(row.version) is not int
        or row.version < 1
        or type(row.venue_version) is not int
        or row.venue_version < 1
        or any(
            type(value) is not str
            for value in (
                row.label,
                row.configuration_label,
                row.lifecycle,
                row.venue_label,
                row.venue_lifecycle,
            )
        )
    ):
        raise VenueTimetableQueryUnavailableError
    return {
        "id": str(row.id),
        "version": row.version,
        "label": row.label,
        "configuration_label": row.configuration_label,
        "lifecycle": row.lifecycle,
        "venue_id": str(row.venue_id),
        "venue_version": row.venue_version,
        "venue_label": row.venue_label,
        "venue_lifecycle": row.venue_lifecycle,
    }


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _section(rows: tuple[VenueTimetableSpace, ...]) -> ProgrammeArchiveSection:
    if type(rows) is not tuple or len(rows) > MAX_TIMETABLE_SPACES:
        raise VenueTimetableQueryUnavailableError
    records = [_space(row) for row in rows]
    if len({row["id"] for row in records}) != len(records):
        raise VenueTimetableQueryUnavailableError
    space = _object(
        {
            "id": {"type": "string", "format": "uuid"},
            "venue_id": {"type": "string", "format": "uuid"},
            "version": {"type": "integer", "minimum": 1},
            "venue_version": {"type": "integer", "minimum": 1},
            **{
                name: {"type": "string"}
                for name in (
                    "label",
                    "configuration_label",
                    "lifecycle",
                    "venue_label",
                    "venue_lifecycle",
                )
            },
        }
    )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(
            {
                "scope": {"const": "programme-room-wayfinding@1"},
                "purpose_exclusions": {"const": list(EXCLUSIONS)},
                "spaces": {
                    "type": "array",
                    "items": space,
                    "maxItems": MAX_TIMETABLE_SPACES,
                },
            }
        ),
    }
    try:
        data = json.dumps(
            {
                "scope": "programme-room-wayfinding@1",
                "purpose_exclusions": EXCLUSIONS,
                "spaces": records,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        schema_bytes = json.dumps(
            schema, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (ValueError, UnicodeError, TypeError):
        raise VenueTimetableQueryUnavailableError from None
    if max(len(data), len(schema_bytes)) > MAX_EXIT_JSON_BYTES:
        raise VenueTimetableQueryUnavailableError
    return ProgrammeArchiveSection(
        "venues", "venues.programme-exit@1", data, schema_bytes
    )


@transaction.atomic
def load_programme_exit_venues(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeArchiveSection:
    """Collect complete room wayfinding while retaining real independent Venue policy.

    Parameters
    ----------
    actor_id : UUID
        Actual requester independently admitted for workspace labels.
    organization_id : UUID
        Exact expected tenant.
    edition_id : UUID
        Exact source edition, never inferred from a selected room.
    correlation_id : UUID
        Server-owned trace for mandatory owner sensitive-read audits.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional archive purpose, never a replacement for actual Venue policy.

    Returns
    -------
    ProgrammeArchiveSection
        Complete bounded label/identity schema with explicit excluded private layers.

    Raises
    ------
    VenueTimetableQueryUnavailableError
        If scope, inventory consistency, typed projection or serialization fails.

    Notes
    -----
    This contains no contact, layout, opening-restriction, booking or calendar
    data and makes no physical-availability claim. The multi-owner composer must
    prelock its entire Department/person closure before the child source audits.
    """
    arguments: _Arguments = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "correlation_id": correlation_id,
    }
    if any(type(value) is not UUID or not value.int for value in arguments.values()):
        raise VenueTimetableQueryUnavailableError

    def purpose() -> None:
        authorize_programme_archive_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )

    purpose()
    lock_programme_staffing_scope(
        organization_id=organization_id, edition_id=edition_id
    )
    purpose()
    rows = list_venue_timetable_spaces(**arguments)
    result = _section(rows)
    if list_venue_timetable_spaces(**arguments) != rows:
        raise VenueTimetableQueryUnavailableError
    purpose()
    return result
