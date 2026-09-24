"""Bounded background ZIP encoding into private custody, never download authority."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .exit_archive_protocol import (
    CONTRACT,
    OWNERS,
    ProgrammeArchiveContext,
    ProgrammeArchiveFile,
    ProgrammeArchiveInvalidError,
    ProgrammeArchiveSection,
    _context_document,
    _invalid_constant,
    _pairs,
    _uuid,
)

if TYPE_CHECKING:
    from collections.abc import Buffer
    from typing import BinaryIO

CAPACITY_CONTRACT: Final = "programme.exit-background-capacity@1"
MAX_RECORD_BYTES: Final = 134_217_728
MAX_SCHEMA_BYTES: Final = 2_097_152
MAX_FILE_BYTES: Final = 10_485_760
MAX_FILES: Final = 2_000
MAX_CONTENT_BYTES: Final = 1_073_741_824
MAX_METADATA_BYTES: Final = 2_097_152
WRITE_CHUNK_BYTES: Final = 1_048_576


@dataclass(frozen=True, slots=True)
class ProgrammeArchiveEncoding:
    """Integrity facts for exactly the bytes written to the caller's private sink.

    Attributes
    ----------
    size_bytes, sha256, member_count
        Whole ZIP byte count/digest and manifest-plus-content member count.
        None is authentication, source permission or a stored success receipt.
    """

    size_bytes: int
    sha256: str
    member_count: int


class _BoundedSink(io.RawIOBase):
    def __init__(self, sink: BinaryIO) -> None:
        self.sink = sink
        self.count = 0
        self.digest = hashlib.sha256()

    def writable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.count

    def write(self, data: Buffer, /) -> int:
        value = bytes(data)
        if self.count + len(value) > MAX_CONTENT_BYTES + MAX_METADATA_BYTES:
            raise ProgrammeArchiveInvalidError
        written = self.sink.write(value)
        if type(written) is not int or written != len(value):
            raise ProgrammeArchiveInvalidError
        self.count += written
        self.digest.update(value)
        return written


def _json(data: bytes, maximum: int) -> dict[str, object]:
    if type(data) is not bytes or not 0 < len(data) <= maximum:
        raise ProgrammeArchiveInvalidError
    try:
        result = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_invalid_constant,
        )
        if type(result) is not dict:
            raise ProgrammeArchiveInvalidError
        json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProgrammeArchiveInvalidError from None
    return result


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
        or any(type(file) is not ProgrammeArchiveFile for file in files)
    ):
        raise ProgrammeArchiveInvalidError
    if any(type(section.owner) is not str for section in sections) or {
        section.owner for section in sections
    } != set(OWNERS):
        raise ProgrammeArchiveInvalidError
    result: list[tuple[str, bytes]] = []
    for section in sorted(sections, key=lambda row: row.owner):
        if section.contract != f"{section.owner}.programme-exit@1":
            raise ProgrammeArchiveInvalidError
        _json(section.data, MAX_RECORD_BYTES)
        _json(section.schema, MAX_SCHEMA_BYTES)
        result.extend(
            (
                (f"records/{section.owner}.json", section.data),
                (f"schemas/{section.owner}.json", section.schema),
            )
        )
    identifiers = [_uuid(file.file_id) for file in files]
    if len(set(identifiers)) != len(identifiers):
        raise ProgrammeArchiveInvalidError
    for identifier, file in sorted(
        zip(identifiers, files, strict=True), key=lambda pair: pair[0]
    ):
        if type(file.data) is not bytes or not 0 < len(file.data) <= MAX_FILE_BYTES:
            raise ProgrammeArchiveInvalidError
        result.append((f"files/applications/{identifier}.bin", file.data))
    if sum(len(data) for _path, data in result) > MAX_CONTENT_BYTES:
        raise ProgrammeArchiveInvalidError
    return tuple(result)


def write_programme_exit_archive(
    *,
    context: ProgrammeArchiveContext,
    sections: tuple[ProgrammeArchiveSection, ...],
    files: tuple[ProgrammeArchiveFile, ...],
    source_digest: str,
    sink: BinaryIO,
) -> ProgrammeArchiveEncoding:
    """Write one complete bounded background package without a second ZIP buffer.

    Parameters
    ----------
    context : ProgrammeArchiveContext
        Exact server-selected generation scope and attribution, not credentials.
    sections : tuple[ProgrammeArchiveSection, ...]
        All eight complete independently authorized owner sections and schemas.
    files : tuple[ProgrammeArchiveFile, ...]
        Exact clean retained files already admitted by Applications.
    source_digest : str
        Complete collection content identity, never a source-permission substitute.
    sink : BinaryIO
        Private fresh writable custody sink; never an HTTP response or public path.

    Returns
    -------
    ProgrammeArchiveEncoding
        Byte identity for completed private encoding only.

    Raises
    ------
    ProgrammeArchiveInvalidError
        If scope, source identity, complete members, capacity or a short write fails.

    Notes
    -----
    Validation precedes the first write. A sink outage still requires the caller
    to roll back/dispose partial custody; these bytes must never be made public.
    Every write is bounded and the sink remains open and owned by the caller.
    The existing smaller in-memory encoder keeps its original refusal ceilings.
    """
    scope = _context_document(context)
    if (
        type(source_digest) is not str
        or re.fullmatch(r"[0-9a-f]{64}", source_digest) is None
    ):
        raise ProgrammeArchiveInvalidError
    members = _members(sections, files)
    events = _json(
        next(section.data for section in sections if section.owner == "events"),
        MAX_RECORD_BYTES,
    )
    profile_code, profile_version = (
        events.get("adoption_profile_code"),
        events.get("adoption_profile_version"),
    )
    if (
        type(profile_code) is not str
        or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", profile_code) is None
        or type(profile_version) is not int
        or profile_version < 1
        or events.get("id") != scope["edition_id"]
        or events.get("organization_id") != scope["organization_id"]
    ):
        raise ProgrammeArchiveInvalidError
    manifest = {
        "contract": CONTRACT,
        "capacity_contract": CAPACITY_CONTRACT,
        "profile": {"code": profile_code, "version": profile_version},
        "scope": scope,
        "classification": "C3 Restricted",
        "purpose": "authorized_programme_exit_records",
        "source_digest": source_digest,
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
            "Complete only within each declared owner scope and purpose exclusions.",
            "Historical records; not a current timetable or permission grant.",
            "Not a database backup, restore procedure or writable import.",
            "Not encrypted or signed; hashes alone do not authenticate the source.",
            "Keep purpose/field restrictions and accountable retention/disposal.",
        ],
    }
    encoded = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(encoded) > MAX_METADATA_BYTES:
        raise ProgrammeArchiveInvalidError
    target = _BoundedSink(sink)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, data in (("manifest.json", encoded), *members):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            with archive.open(info, "w") as member:
                for offset in range(0, len(data), WRITE_CHUNK_BYTES):
                    member.write(memoryview(data)[offset : offset + WRITE_CHUNK_BYTES])
    return ProgrammeArchiveEncoding(
        target.count, target.digest.hexdigest(), len(members) + 1
    )
