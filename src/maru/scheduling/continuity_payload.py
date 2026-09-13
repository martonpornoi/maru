"""Closed audience-specific on-site cards, independent of network or signature trust."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .continuity_protocol import (
    MAX_CONTINUITY_PAYLOAD_BYTES,
    ContinuityInvalidError,
    ContinuityManifest,
    ContinuityScope,
    _canonical,
    _date,
    _json,
    _scope_document,
    _utc,
    _uuid,
    _validate_release_state,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

CONTINUITY_PAYLOAD_CONTRACT = "scheduling.programme-onsite@1"
MAX_CONTINUITY_ENTRIES = 7120
MAX_CONTINUITY_FACTS = 65536
MAX_CONTINUITY_FACT_TEXT = 5000
_TITLE_LENGTH = 240
_SHA256_HEX_LENGTH = 64
_MAX_ZONE_LENGTH = 100
_ASCII_SPACE = 32
_ASCII_DELETE = 127
_SOURCE_CONTRACTS = {
    "public": "scheduling.public-timetable@1",
    "exact_person": "scheduling.personal-timetable@1",
    "private_operator": "scheduling.operator-run-sheet@1",
}
_PUBLIC_FACTS = frozenset(
    {
        "summary",
        "content_note",
        "room",
        "venue",
        "reviewed_copy",
        "wayfinding_version",
        "service_day",
    }
)
_HOST_FACTS = frozenset(
    {
        "role",
        "briefing",
        "host_version",
        "room",
        "venue",
        "wayfinding_version",
        "service_day",
    }
)
_WORK_FACTS = frozenset(
    {
        "status",
        "location",
        "briefing",
        "supervision",
        "department",
        "position",
        "commitment_version",
        "demand_version",
        "demand_status",
        "rest_until",
    }
)
_STAFFING_FACTS = frozenset(
    {
        "status",
        "location",
        "briefing",
        "supervision",
        "demand_version",
        "required_headcount",
        "retained_work",
        "programme_link",
    }
)
_KINDS = {
    "public": frozenset({"public_event"}),
    "exact_person": frozenset(
        {
            "host_presence",
            "work_claimed",
            "work_confirmed",
            "work_removed",
            "work_completed",
        }
    ),
    "private_operator": frozenset({"operator_event", "staffing_demand"}),
}
_KEY_PREFIXES = {
    "public_event": "public",
    "operator_event": "operator",
    "host_presence": "host",
    "work_claimed": "work",
    "work_confirmed": "work",
    "work_removed": "work",
    "work_completed": "work",
    "staffing_demand": "demand",
}
_PHASE_FIELDS = ("setup", "delivery_start", "delivery_end", "teardown")
_PAYLOAD_FIELDS = frozenset(
    {
        "contract",
        "scope",
        "source_contract",
        "source_sha256",
        "observed_at",
        "zone_name",
        "release_state",
        "pointer_version",
        "release_id",
        "published_at",
        "hosting_status",
        "work_status",
        "entries",
    }
)


@dataclass(frozen=True, slots=True)
class ContinuityFact:
    """One code-labelled fact within a deliberately admitted owner field ceiling.

    Attributes
    ----------
    code
        Closed presentation field; a public card cannot contain a private field code.
    value
        Bounded plain text, escaped by the renderer and never executable markup.
    """

    code: str
    value: str


@dataclass(frozen=True, slots=True)
class ContinuityEntry:
    """One timetable or retained-work card with explicit timing semantics.

    Attributes
    ----------
    key, kind
        Stable prefixed owner identity and closed audience-specific timing meaning.
    title
        Reviewed event title or separately current own/work instruction title.
    starts_at, ends_at
        Public time, required host presence, operator envelope or retained work.
    space_id, day_id
        Approved room/day references where available, not inferred work locations.
    context
        Four-phase host/operator context, not extra assigned host work.
    facts
        Deliberately admitted text and exact source/version references.
    """

    key: str
    kind: str
    title: str
    starts_at: datetime
    ends_at: datetime
    space_id: UUID | None
    day_id: UUID | None
    context: tuple[datetime, datetime, datetime, datetime] | None
    facts: tuple[ContinuityFact, ...]


@dataclass(frozen=True, slots=True)
class ContinuityProjection:
    """Complete minimized on-site data derived from exactly one owner projection.

    Attributes
    ----------
    scope
        Exact source audience/person/target/layer ceiling, not a grant.
    source_contract, source_sha256
        Validated owning output contract and digest of its complete source document.
    observed_at, zone_name
        Final owner observation and edition IANA presentation zone.
    release_state, pointer_version, release_id, published_at
        Released facts; unobserved personal state never implies absence or publication.
    hosting_status, work_status
        Explicit unadopted/unobserved/unrequested/available source-layer meaning.
    entries
        Complete bounded cards; a partial layer is never represented as success.
    """

    scope: ContinuityScope
    source_contract: str
    source_sha256: str
    observed_at: datetime
    zone_name: str
    release_state: str
    pointer_version: int | None
    release_id: UUID | None
    published_at: datetime | None
    hosting_status: str
    work_status: str
    entries: tuple[ContinuityEntry, ...]


@dataclass(frozen=True, slots=True)
class ContinuityNowNext:
    """Time-based groups, never evidence that a person attended or did work.

    Attributes
    ----------
    at
        Explicit aware evaluation instant rather than the browser's guessed zone.
    now
        Every operative interval containing at, preserving concurrent items.
    next
        Every operative item tied at the earliest following start.
    """

    at: datetime
    now: tuple[ContinuityEntry, ...]
    next: tuple[ContinuityEntry, ...]


def _text(value: str, maximum: int, *, required: bool = False) -> str:
    # Keep the offline parser independent of Django and live owner-query imports.
    if (
        type(value) is not str
        or len(value) > maximum
        or (required and not value.strip())
        or any(
            (ord(char) < _ASCII_SPACE and char not in "\t\n\r")
            or ord(char) == _ASCII_DELETE
            for char in value
        )
    ):
        raise ContinuityInvalidError
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ContinuityInvalidError from error
    return value


def _fact_codes(entry: ContinuityEntry, scope: ContinuityScope) -> frozenset[str]:
    if entry.kind == "public_event":
        return _PUBLIC_FACTS
    if entry.kind == "host_presence":
        return _HOST_FACTS
    if entry.kind.startswith("work_"):
        return _WORK_FACTS
    if entry.kind == "staffing_demand":
        if "staffing" not in scope.layers:
            raise ContinuityInvalidError
        return _STAFFING_FACTS
    result = _PUBLIC_FACTS | (set(scope.layers) - {"staffing"})
    if set(scope.layers) - {"staffing"}:
        result |= {"delivery_version"}
    if "staffing" in scope.layers:
        result |= {"programme_link"}
    return frozenset(result)


def _entry_times(entry: ContinuityEntry) -> dict[str, object]:
    start, end = _utc(entry.starts_at), _utc(entry.ends_at)
    if start >= end:
        raise ContinuityInvalidError
    context = None
    if entry.context is not None:
        if (
            type(entry.context) is not tuple
            or len(entry.context) != len(_PHASE_FIELDS)
            or entry.kind not in {"operator_event", "host_presence"}
        ):
            raise ContinuityInvalidError
        setup, delivery_start, delivery_end, teardown = map(_utc, entry.context)
        if (
            not setup <= delivery_start < delivery_end <= teardown
            or not setup <= start < end <= teardown
        ):
            raise ContinuityInvalidError
        if entry.kind == "operator_event" and (start != setup or end != teardown):
            raise ContinuityInvalidError
        context = dict(
            zip(
                _PHASE_FIELDS,
                (_utc(value).isoformat() for value in entry.context),
                strict=True,
            )
        )
    elif entry.kind in {"operator_event", "host_presence"}:
        raise ContinuityInvalidError
    return {
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
        "context": context,
    }


def _entry(entry: ContinuityEntry, scope: ContinuityScope) -> dict[str, object]:
    if (
        type(entry) is not ContinuityEntry
        or type(entry.kind) is not str
        or entry.kind not in _KINDS[scope.audience]
        or type(entry.key) is not str
    ):
        raise ContinuityInvalidError
    parts = entry.key.split(":")
    if parts[0] != _KEY_PREFIXES[entry.kind] or len(parts) != (
        3 if entry.kind == "host_presence" else 2
    ):
        raise ContinuityInvalidError
    for identifier in parts[1:]:
        _uuid(identifier)
    times = _entry_times(entry)
    ids = {}
    for name, value in (("space_id", entry.space_id), ("day_id", entry.day_id)):
        ids[name] = str(value) if value is not None else None
        _uuid(ids[name], optional=True)
    if entry.kind in {"public_event", "operator_event", "host_presence"}:
        if entry.space_id is None or entry.day_id is None:
            raise ContinuityInvalidError
    elif entry.space_id is not None or entry.day_id is not None:
        raise ContinuityInvalidError
    if type(entry.facts) is not tuple or len(entry.facts) > MAX_CONTINUITY_FACTS:
        raise ContinuityInvalidError
    allowed, facts, seen = _fact_codes(entry, scope), [], set()
    for fact in entry.facts:
        if (
            type(fact) is not ContinuityFact
            or type(fact.code) is not str
            or fact.code not in allowed
        ):
            raise ContinuityInvalidError
        if fact.code in seen and fact.code not in {"retained_work", "programme_link"}:
            raise ContinuityInvalidError
        seen.add(fact.code)
        facts.append(
            {"code": fact.code, "value": _text(fact.value, MAX_CONTINUITY_FACT_TEXT)}
        )
    return {
        "key": entry.key,
        "kind": entry.kind,
        "title": _text(entry.title, _TITLE_LENGTH, required=True),
        **times,
        **ids,
        "facts": facts,
    }


def _layer_states(projection: ContinuityProjection) -> None:
    if (
        type(projection.hosting_status) is not str
        or type(projection.work_status) is not str
    ):
        raise ContinuityInvalidError
    if projection.scope.audience == "public":
        valid = projection.hosting_status == projection.work_status == "not_applicable"
    elif projection.scope.audience == "private_operator":
        valid = projection.hosting_status == "not_applicable" and (
            projection.work_status in {"available", "unadopted"}
            if "staffing" in projection.scope.layers
            else projection.work_status == "unrequested"
        )
    else:
        valid = (
            projection.hosting_status == projection.release_state
            and projection.work_status in {"available", "unadopted"}
        )
    if not valid:
        raise ContinuityInvalidError


def _source_metadata(projection: ContinuityProjection) -> None:
    _validate_release_state(
        audience=projection.scope.audience,
        state=projection.release_state,
        pointer=projection.pointer_version,
        release=projection.release_id,
    )
    if (
        type(projection.zone_name) is not str
        or not 1 <= len(projection.zone_name) <= _MAX_ZONE_LENGTH
    ):
        raise ContinuityInvalidError
    try:
        ZoneInfo(projection.zone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ContinuityInvalidError from error
    published = projection.published_at
    if projection.release_state in {"available", "invalidated"}:
        if published is None or _utc(published) > _utc(projection.observed_at):
            raise ContinuityInvalidError
    elif published is not None:
        raise ContinuityInvalidError


def _document(projection: ContinuityProjection) -> dict[str, object]:
    if type(projection) is not ContinuityProjection:
        raise ContinuityInvalidError
    scope = _scope_document(projection.scope)
    _source_metadata(projection)
    if projection.source_contract != _SOURCE_CONTRACTS[projection.scope.audience]:
        raise ContinuityInvalidError
    if (
        type(projection.source_sha256) is not str
        or len(projection.source_sha256) != _SHA256_HEX_LENGTH
        or any(
            character not in "0123456789abcdef"
            for character in projection.source_sha256
        )
    ):
        raise ContinuityInvalidError
    if (
        type(projection.entries) is not tuple
        or len(projection.entries) > MAX_CONTINUITY_ENTRIES
    ):
        raise ContinuityInvalidError
    _layer_states(projection)
    entries, seen, facts_count = [], set(), 0
    for row in projection.entries:
        entry = _entry(row, projection.scope)
        if row.key in seen:
            raise ContinuityInvalidError
        seen.add(row.key)
        facts_count += len(row.facts)
        if facts_count > MAX_CONTINUITY_FACTS:
            raise ContinuityInvalidError
        if (
            row.kind in {"public_event", "operator_event", "host_presence"}
            and projection.release_state != "available"
        ):
            raise ContinuityInvalidError
        if (
            row.kind.startswith("work_") or row.kind == "staffing_demand"
        ) and projection.work_status != "available":
            raise ContinuityInvalidError
        entries.append(entry)
    return {
        "contract": CONTINUITY_PAYLOAD_CONTRACT,
        "scope": scope,
        "source_contract": projection.source_contract,
        "source_sha256": projection.source_sha256,
        "observed_at": _utc(projection.observed_at).isoformat(),
        "zone_name": projection.zone_name,
        "release_state": projection.release_state,
        "pointer_version": projection.pointer_version,
        "release_id": str(projection.release_id) if projection.release_id else None,
        "published_at": _utc(projection.published_at).isoformat()
        if projection.published_at
        else None,
        "hosting_status": projection.hosting_status,
        "work_status": projection.work_status,
        "entries": sorted(
            entries, key=lambda row: (str(row["starts_at"]), str(row["key"]))
        ),
    }


def encode_continuity_payload(projection: ContinuityProjection) -> bytes:
    """Encode complete on-site cards without elevating their source authority.

    Parameters
    ----------
    projection : ContinuityProjection
        Complete audience-specific data from a fresh independently admitted owner read.

    Returns
    -------
    bytes
        Deterministically ordered canonical UTF-8 JSON, capped at eight MiB.

    Raises
    ------
    ContinuityInvalidError
        If the payload is malformed, mixed-audience, partial or over-bound.
    """
    encoded = _canonical(_document(projection))
    if len(encoded) > MAX_CONTINUITY_PAYLOAD_BYTES:
        raise ContinuityInvalidError
    return encoded


def _decoded_entry(value: object) -> ContinuityEntry:
    if type(value) is not dict or value.keys() != {
        "key",
        "kind",
        "title",
        "starts_at",
        "ends_at",
        "space_id",
        "day_id",
        "context",
        "facts",
    }:
        raise ContinuityInvalidError
    context = value["context"]
    if context is not None and (
        type(context) is not dict or context.keys() != set(_PHASE_FIELDS)
    ):
        raise ContinuityInvalidError
    facts = value["facts"]
    if type(facts) is not list or len(facts) > MAX_CONTINUITY_FACTS:
        raise ContinuityInvalidError
    result = []
    for fact in facts:
        if type(fact) is not dict or fact.keys() != {"code", "value"}:
            raise ContinuityInvalidError
        result.append(ContinuityFact(fact["code"], fact["value"]))
    return ContinuityEntry(
        value["key"],
        value["kind"],
        value["title"],
        _date(value["starts_at"]),
        _date(value["ends_at"]),
        _uuid(value["space_id"], optional=True),
        _uuid(value["day_id"], optional=True),
        (
            _date(context["setup"]),
            _date(context["delivery_start"]),
            _date(context["delivery_end"]),
            _date(context["teardown"]),
        )
        if context is not None
        else None,
        tuple(result),
    )


def decode_continuity_payload(
    payload: bytes, *, manifest: ContinuityManifest
) -> ContinuityProjection:
    """Decode authenticated data within its independently verified manifest ceiling.

    Parameters
    ----------
    payload : bytes
        Signed bytes whose integrity and known state were already verified.
    manifest : ContinuityManifest
        Verified scope and source metadata, not values copied from untrusted JSON.

    Returns
    -------
    ContinuityProjection
        Complete typed on-site cards, still explicitly historical when offline.

    Raises
    ------
    ContinuityInvalidError
        If data is malformed, exceeds the field ceiling or conflicts with its manifest.

    Notes
    -----
    This decoder verifies no signature and grants no access by itself. Normal offline
    callers must use the signature/known-state boundary before this representation.
    """
    data = _json(payload, _PAYLOAD_FIELDS, maximum=MAX_CONTINUITY_PAYLOAD_BYTES)
    expected = {
        "contract": CONTINUITY_PAYLOAD_CONTRACT,
        "scope": _scope_document(manifest.scope),
        "observed_at": _utc(manifest.observed_at).isoformat(),
        "zone_name": manifest.zone_name,
        "release_state": manifest.release_state,
        "pointer_version": manifest.pointer_version,
        "release_id": str(manifest.release_id) if manifest.release_id else None,
    }
    if any(data[field] != value for field, value in expected.items()):
        raise ContinuityInvalidError
    entries = data["entries"]
    if type(entries) is not list or len(entries) > MAX_CONTINUITY_ENTRIES:
        raise ContinuityInvalidError
    source_contract, source_sha256, hosting_status, work_status = (
        data[name]
        for name in (
            "source_contract",
            "source_sha256",
            "hosting_status",
            "work_status",
        )
    )
    if not (
        isinstance(source_contract, str)
        and isinstance(source_sha256, str)
        and isinstance(hosting_status, str)
        and isinstance(work_status, str)
    ):
        raise ContinuityInvalidError
    projection = ContinuityProjection(
        manifest.scope,
        source_contract,
        source_sha256,
        manifest.observed_at,
        manifest.zone_name,
        manifest.release_state,
        manifest.pointer_version,
        manifest.release_id,
        _date(data["published_at"]) if data["published_at"] is not None else None,
        hosting_status,
        work_status,
        tuple(_decoded_entry(row) for row in entries),
    )
    if encode_continuity_payload(projection) != payload:
        raise ContinuityInvalidError
    return projection


def _operative(entry: ContinuityEntry) -> bool:
    if entry.kind in {"work_removed", "work_completed"}:
        return False
    if entry.kind == "staffing_demand":
        return any(
            fact.code == "status" and fact.value in {"open", "locked"}
            for fact in entry.facts
        )
    return True


def programme_now_next(
    projection: ContinuityProjection, *, at: datetime
) -> ContinuityNowNext:
    """Group exact intervals with end-exclusive boundaries and all next-start ties.

    Parameters
    ----------
    projection : ContinuityProjection
        Complete validated on-site data with retained-work semantics unchanged.
    at : datetime
        Explicit aware evaluation instant, independent of local wall-clock ambiguity.

    Returns
    -------
    ContinuityNowNext
        Concurrent current entries and earliest future ties; never attendance proof.

    Notes
    -----
    ContinuityInvalidError propagates for invalid payloads or a naive evaluation time.
    Past scheduled work does not thereby become completed work; the full source state
    remains in the projection. Offline use still needs expiry and known-state checks.
    """
    encode_continuity_payload(projection)
    at = _utc(at)
    entries = sorted(
        (row for row in projection.entries if _operative(row)),
        key=lambda row: (_utc(row.starts_at), row.key),
    )
    now = tuple(row for row in entries if _utc(row.starts_at) <= at < _utc(row.ends_at))
    following = tuple(row for row in entries if _utc(row.starts_at) > at)
    next_rows = (
        tuple(
            row
            for row in following
            if _utc(row.starts_at) == _utc(following[0].starts_at)
        )
        if following
        else ()
    )
    return ContinuityNowNext(at, now, next_rows)
