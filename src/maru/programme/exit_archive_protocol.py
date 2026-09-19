"""Bounded Programme exit packaging, never authorization or a database backup.

Only owner-authorized collectors may supply these sections. Encoding proves neither
source completeness nor permission to retain or disclose the supplied records.
No collector, route, profile activation, import or stop-use operation is added here.
"""

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

CONTRACT: Final = "programme.exit-archive@1"
OWNERS: Final = (
    "applications",
    "audit",
    "authorization",
    "events",
    "programme",
    "scheduling",
    "venues",
    "workforce",
)
MAX_JSON_BYTES: Final = 2_097_152
MAX_FILE_BYTES: Final = 10_485_760
MAX_FILES: Final = 256
MAX_CONTENT_BYTES: Final = 33_554_432


class ProgrammeArchiveInvalidError(ValueError):
    """Reject incomplete or malformed packaging without disclosing record contents."""

    def __init__(self) -> None:
        super().__init__("programme_exit_archive_invalid")


@dataclass(frozen=True, slots=True)
class ProgrammeArchiveContext:
    """Known request scope, not credentials or proof of an authorized query.

    Attributes
    ----------
    organization_id, edition_id
        Exact tenant and edition selected independently of serialized source data.
    requester_id, correlation_id
        Requesting person and trace for independently retained owner read audits.
    generated_at
        Aware generation instant; not a promise that records remain current.
    """

    organization_id: UUID
    edition_id: UUID
    requester_id: UUID
    correlation_id: UUID
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class ProgrammeArchiveSection:
    """One already authorized owner's payload and portable schema, kept private.

    Attributes
    ----------
    owner
        Exact member of the closed Programme composite owner set.
    contract
        Exact version-one owner archive contract, not arbitrary future discovery.
    data, schema
        Complete bounded UTF-8 JSON objects supplied by the owning collector.
        Their business-field and retention ceilings remain that owner's duty.
    """

    owner: str
    contract: str
    data: bytes = field(repr=False)
    schema: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProgrammeArchiveFile:
    """Opaque identified bytes released through the Applications file boundary.

    Attributes
    ----------
    file_id
        Exact owner file identity; never a caller-supplied filesystem path.
    data
        Bytes already checked for current owner access, clean state and retention.
        Packaging does not inspect, scan, execute or authorize their contents.
    """

    file_id: UUID
    data: bytes = field(repr=False)


def _uuid(value: UUID) -> str:
    if type(value) is not UUID or value.int == 0:
        raise ProgrammeArchiveInvalidError
    return str(value)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProgrammeArchiveInvalidError
        result[key] = value
    return result


def _invalid_constant(_value: str) -> object:
    raise ProgrammeArchiveInvalidError


def _json_object(data: bytes) -> None:
    if type(data) is not bytes or not 0 < len(data) <= MAX_JSON_BYTES:
        raise ProgrammeArchiveInvalidError
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_invalid_constant,
        )
        if type(value) is not dict:
            raise ProgrammeArchiveInvalidError
        # Reject lone escaped surrogates and numeric overflow as well as bad UTF-8.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError):
        raise ProgrammeArchiveInvalidError from None


def _context_document(context: ProgrammeArchiveContext) -> dict[str, object]:
    if type(context) is not ProgrammeArchiveContext:
        raise ProgrammeArchiveInvalidError
    observed = context.generated_at
    if (
        type(observed) is not datetime
        or observed.tzinfo is None
        or observed.utcoffset() is None
    ):
        raise ProgrammeArchiveInvalidError
    return {
        "organization_id": _uuid(context.organization_id),
        "edition_id": _uuid(context.edition_id),
        "requester_id": _uuid(context.requester_id),
        "correlation_id": _uuid(context.correlation_id),
        "generated_at": observed.astimezone(UTC).isoformat(),
    }


def _members(
    sections: tuple[ProgrammeArchiveSection, ...],
    files: tuple[ProgrammeArchiveFile, ...],
) -> tuple[tuple[str, bytes], ...]:
    if (
        type(sections) is not tuple
        or len(sections) != len(OWNERS)
        or any(type(section) is not ProgrammeArchiveSection for section in sections)
        or type(files) is not tuple
        or len(files) > MAX_FILES
        or any(type(item) is not ProgrammeArchiveFile for item in files)
    ):
        raise ProgrammeArchiveInvalidError
    if any(type(section.owner) is not str for section in sections):
        raise ProgrammeArchiveInvalidError
    if {section.owner for section in sections} != set(OWNERS):
        raise ProgrammeArchiveInvalidError
    members: list[tuple[str, bytes]] = []
    for section in sorted(sections, key=lambda item: item.owner):
        if (
            type(section.contract) is not str
            or section.contract != f"{section.owner}.programme-exit@1"
        ):
            raise ProgrammeArchiveInvalidError
        _json_object(section.data)
        _json_object(section.schema)
        members.extend(
            (
                (f"records/{section.owner}.json", section.data),
                (f"schemas/{section.owner}.json", section.schema),
            )
        )
    identifiers = [_uuid(item.file_id) for item in files]
    if len(set(identifiers)) != len(identifiers):
        raise ProgrammeArchiveInvalidError
    for identifier, item in sorted(
        zip(identifiers, files, strict=True), key=lambda pair: pair[0]
    ):
        if type(item.data) is not bytes or not 0 < len(item.data) <= MAX_FILE_BYTES:
            raise ProgrammeArchiveInvalidError
        members.append((f"files/applications/{identifier}.bin", item.data))
    if sum(len(data) for _, data in members) > MAX_CONTENT_BYTES:
        raise ProgrammeArchiveInvalidError
    return tuple(members)


def encode_programme_exit_archive(
    *,
    context: ProgrammeArchiveContext,
    sections: tuple[ProgrammeArchiveSection, ...],
    files: tuple[ProgrammeArchiveFile, ...] = (),
) -> bytes:
    """Encode a deterministic classified ZIP without accessing a database or files.

    Parameters
    ----------
    context : ProgrammeArchiveContext
        Independently validated request metadata, not an authorization substitute.
    sections : tuple[ProgrammeArchiveSection, ...]
        Exactly one complete authorized section/schema from every required owner.
    files : tuple[ProgrammeArchiveFile, ...], default=()
        Bounded current-authorized Applications file bytes and opaque identities.

    Returns
    -------
    bytes
        Uncompressed bounded ZIP with a versioned restricted manifest and hashes.

    Notes
    -----
    Validation helpers reject invalid scope, owner contracts, JSON, files or
    complete content bounds with ``ProgrammeArchiveInvalidError``.
    Hashes detect byte mismatch, not forged origin or altered manifests. This is
    neither encrypted storage nor a signature, importer, backup, current timetable
    or grant. Collectors must prove completeness, field/retention ceilings, current
    access and file linkage before encoding and again before actual disclosure.
    """
    scope = _context_document(context)
    members = _members(sections, files)
    manifest = {
        "contract": CONTRACT,
        "profile": {"code": "programme_operations", "version": 1},
        "scope": scope,
        "classification": "C3 Restricted",
        "purpose": "authorized_programme_exit_records",
        "members": [
            {
                "path": path,
                "byte_length": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for path, data in members
        ],
        "owner_contracts": {owner: f"{owner}.programme-exit@1" for owner in OWNERS},
        "limitations": [
            "Historical records; not a current timetable or permission grant.",
            "Not a database backup, restore procedure or writable import.",
            "Not encrypted or signed; hashes alone do not authenticate the source.",
            "Keep purpose/field restrictions and accountable retention/disposal.",
        ],
    }
    encoded_manifest = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, data in (("manifest.json", encoded_manifest), *members):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    return result.getvalue()
