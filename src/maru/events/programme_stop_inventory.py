"""Bounded stop-impact metadata encoding; neither a reader nor an authorization."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from django.utils import timezone

if TYPE_CHECKING:
    from collections.abc import Iterable

MAX_STOP_SOURCE_ROWS: Final = 10_000
MAX_STOP_SOURCE_BYTES: Final = 8_388_608
MAX_STOP_COLLECTIONS: Final = 64
MAX_STOP_METADATA_FIELDS: Final = 16
MAX_STOP_METADATA_TEXT: Final = 128
MAX_STOP_METADATA_STATES: Final = 32
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)
_OWNERS: Final = frozenset(
    {"applications", "programme", "scheduling", "workforce", "venues", "effects"}
)


class ProgrammeStopInventoryUnavailableError(RuntimeError):
    """Refuse malformed or partial stop metadata without disclosing source rows."""

    def __init__(self) -> None:
        super().__init__("programme_stop_inventory_unavailable")


@dataclass(frozen=True, slots=True)
class ProgrammeStopMetadataSource:
    """Carry an owner's already admitted complete metadata projection.

    Attributes
    ----------
    code, fields
        Literal collection and selected metadata columns, always starting with id.
    rows
        Complete UUID-ordered tuples, bounded by the owning reader before transfer.
        Never supply answer payloads, files, labels, reasons or other private text.
    state_field
        Optional exact closed-state column to count, not arbitrary free text.
    """

    code: str
    fields: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    state_field: str | None = None


@dataclass(frozen=True, slots=True)
class ProgrammeStopCollectionCount:
    """Disclose only complete collection totals and closed-state counts.

    Attributes
    ----------
    code, total
        Owner-defined collection and its complete observed record count.
    states
        Deterministically ordered closed states and counts, empty when inapplicable.
    """

    code: str
    total: int
    states: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ProgrammeStopInventory:
    """Retain aggregate stop accounting without leaking metadata source identities.

    Attributes
    ----------
    owner, collections
        Exact owner and complete ordered collection counts.
    source_fingerprint
        Scope-bound identity of the selected metadata, not access or a live lock.
    """

    owner: str
    collections: tuple[ProgrammeStopCollectionCount, ...]
    source_fingerprint: str


def _scalar(value: object) -> str:
    if type(value) is UUID:
        return str(value)
    if type(value) is datetime and timezone.is_aware(value):
        return value.isoformat()
    raise ProgrammeStopInventoryUnavailableError


def build_programme_stop_inventory(
    *,
    owner: str,
    organization_id: UUID,
    edition_id: UUID,
    sources: Iterable[ProgrammeStopMetadataSource],
) -> ProgrammeStopInventory:
    """Hash complete owner metadata and return only minimized impact counts.

    Parameters
    ----------
    owner : str
        Exact reviewed stop owner, not dynamic module discovery.
    organization_id : UUID
        Exact explicitly selected tenant, never discovered through private records.
    edition_id : UUID
        Independently authorized and coherently locked scope of every supplied row.
    sources : Iterable[ProgrammeStopMetadataSource]
        Literal complete collection inventory supplied by the owning reader, with
        UUID-ordered rows. Yield collections one at a time to bound live memory;
        counts must never be built from a truncated page.

    Returns
    -------
    ProgrammeStopInventory
        Deterministic counts and SHA-256 metadata identity; no source row escapes.

    Raises
    ------
    ProgrammeStopInventoryUnavailableError
        If owner, shape, identities, ordering, state vocabulary or bounds fail.

    Notes
    -----
    This database-free encoder proves no field permission, scope ownership,
    inventory completeness or source freshness. Each public owner reader must
    enforce those facts, its literal inventory and disclosure audit independently.
    """
    if (
        type(owner) is not str
        or owner not in _OWNERS
        or any(
            type(value) is not UUID or not value.int
            for value in (organization_id, edition_id)
        )
    ):
        raise ProgrammeStopInventoryUnavailableError
    try:
        pending = iter(sources)
    except TypeError:
        raise ProgrammeStopInventoryUnavailableError from None
    digest = hashlib.sha256()
    digest.update(
        f"events.programme-stop-inventory@1:{owner}:{organization_id}:{edition_id}\n".encode(
            "ascii"
        )
    )
    counts = []
    names: set[str] = set()
    size = 0
    for source in pending:
        if (
            len(names) >= MAX_STOP_COLLECTIONS
            or type(source) is not ProgrammeStopMetadataSource
            or type(source.code) is not str
            or _CODE.fullmatch(source.code) is None
            or source.code in names
            or type(source.fields) is not tuple
            or not source.fields
            or source.fields[0] != "id"
            or len(source.fields) > MAX_STOP_METADATA_FIELDS
            or any(
                type(field) is not str or _CODE.fullmatch(field) is None
                for field in source.fields
            )
            or len(set(source.fields)) != len(source.fields)
            or type(source.rows) is not tuple
            or len(source.rows) > MAX_STOP_SOURCE_ROWS
            or (
                source.state_field is not None
                and source.state_field not in source.fields
            )
        ):
            raise ProgrammeStopInventoryUnavailableError
        names.add(source.code)
        digest.update(
            json.dumps(
                [source.code, source.fields, source.state_field], separators=(",", ":")
            ).encode("ascii")
        )
        state_position = (
            None
            if source.state_field is None
            else source.fields.index(source.state_field)
        )
        states: dict[str, int] = {}
        previous = 0
        for row in source.rows:
            if (
                type(row) is not tuple
                or len(row) != len(source.fields)
                or type(row[0]) is not UUID
                or row[0].int <= previous
                or any(
                    type(value) not in (type(None), bool, int, str, UUID, datetime)
                    for value in row
                )
                or any(
                    type(value) is str and len(value) > MAX_STOP_METADATA_TEXT
                    for value in row
                )
            ):
                raise ProgrammeStopInventoryUnavailableError
            previous = row[0].int
            if state_position is not None:
                state = row[state_position]
                if type(state) is not str or _CODE.fullmatch(state) is None:
                    raise ProgrammeStopInventoryUnavailableError
                states[state] = states.get(state, 0) + 1
                if len(states) > MAX_STOP_METADATA_STATES:
                    raise ProgrammeStopInventoryUnavailableError
            try:
                encoded = json.dumps(
                    row,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                    default=_scalar,
                ).encode("ascii")
            except (TypeError, ValueError, UnicodeError):
                raise ProgrammeStopInventoryUnavailableError from None
            size += len(encoded)
            if size > MAX_STOP_SOURCE_BYTES:
                raise ProgrammeStopInventoryUnavailableError
            digest.update(encoded)
            digest.update(b"\n")
        counts.append(
            ProgrammeStopCollectionCount(
                source.code, len(source.rows), tuple(sorted(states.items()))
            )
        )
    if not counts:
        raise ProgrammeStopInventoryUnavailableError
    return ProgrammeStopInventory(owner, tuple(counts), digest.hexdigest())
