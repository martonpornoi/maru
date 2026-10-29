"""Check a saved rota's member hashes offline without extracting its contents."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import NoReturn
    from zipfile import ZipInfo

MAX_UNCOMPRESSED_BYTES = 16_777_216
MAX_ARCHIVE_BYTES = MAX_UNCOMPRESSED_BYTES + 65_536
MAX_MANIFEST_BYTES = 8_192
MAX_DIRECTORY_BYTES = 4_096
MAX_EXTRACT_VERSION = 20
ZIP_END = struct.Struct("<4s4H2LH")
LOCAL_HEADER = struct.Struct("<4s5H3L2H")
CONTENT_MEMBERS = frozenset({"rota.json", "schema.json", "rota.html", "README.txt"})
PACKAGE_MEMBERS = CONTENT_MEMBERS | {"manifest.json"}
ASSURANCE = (
    "Integrity matches the supplied manifest only. This does not establish "
    "authenticity, schema validity, freshness, current permissions or readiness."
)


class RotaIntegrityError(ValueError):
    """Report a fixed integrity failure code without source-content details."""


@dataclass(frozen=True, slots=True)
class RotaIntegritySummary:
    """Describe the verified byte boundary without identifying rota content.

    Attributes
    ----------
    archive_bytes : int
        Number of bytes read from the selected archive.
    uncompressed_bytes : int
        Total bytes across all five members, including the manifest.
    checked_content_members : int
        Number of content members whose lengths and hashes matched.
    """

    archive_bytes: int
    uncompressed_bytes: int
    checked_content_members: int


def _read_archive(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RotaIntegrityError("unavailable_file")
        raw = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise RotaIntegrityError("archive_too_large")
    return raw


def _check_directory(raw: bytes) -> int:
    # Bound the central directory before ZipFile creates an entry per record.
    if len(raw) < ZIP_END.size:
        raise RotaIntegrityError("invalid_archive")
    signature, disk, directory_disk, local_count, count, size, offset, comment = (
        ZIP_END.unpack(raw[-ZIP_END.size :])
    )
    if (
        signature != b"PK\x05\x06"
        or disk != 0
        or directory_disk != 0
        or local_count != len(PACKAGE_MEMBERS)
        or count != len(PACKAGE_MEMBERS)
        or comment != 0
        or not 0 < size <= MAX_DIRECTORY_BYTES
        or offset <= 0
        or offset + size != len(raw) - ZIP_END.size
        or raw[-42:-38] == b"PK\x06\x07"
    ):
        raise RotaIntegrityError("unsupported_archive_layout")
    return int(offset)


def _check_extra(raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        if offset + 4 > len(raw):
            raise RotaIntegrityError("invalid_archive")
        kind, size = struct.unpack_from("<2H", raw, offset)
        if kind == 1:
            raise RotaIntegrityError("unsupported_member")
        offset += 4 + size
        if offset > len(raw):
            raise RotaIntegrityError("invalid_archive")


def _members(archive: ZipFile) -> dict[str, ZipInfo]:
    entries = archive.infolist()
    if len(entries) != len(PACKAGE_MEMBERS):
        raise RotaIntegrityError("invalid_members")
    if {entry.filename for entry in entries} != PACKAGE_MEMBERS:
        raise RotaIntegrityError("invalid_members")
    if min(entry.header_offset for entry in entries) != 0:
        raise RotaIntegrityError("unsupported_archive_layout")
    total = 0
    for entry in entries:
        mode = stat.S_IFMT(entry.external_attr >> 16)
        if (
            entry.orig_filename != entry.filename
            or entry.is_dir()
            or entry.external_attr & 0x10
            or mode not in {0, stat.S_IFREG}
            or entry.flag_bits & ~0x800
            or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or entry.extract_version > MAX_EXTRACT_VERSION
            or entry.comment
        ):
            raise RotaIntegrityError("unsupported_member")
        _check_extra(entry.extra)
        total += entry.file_size
    if total > MAX_UNCOMPRESSED_BYTES:
        raise RotaIntegrityError("contents_too_large")
    return {entry.filename: entry for entry in entries}


def _member_bytes(
    raw: bytes, entry: ZipInfo, boundary: int, limit: int, overflow: str
) -> bytes:
    header = raw[entry.header_offset : entry.header_offset + LOCAL_HEADER.size]
    if len(header) != LOCAL_HEADER.size:
        raise RotaIntegrityError("invalid_archive")
    signature, version, flags, method, _, _, crc, compressed, size, names, extras = (
        LOCAL_HEADER.unpack(header)
    )
    if version > MAX_EXTRACT_VERSION or flags & ~0x800:
        raise RotaIntegrityError("unsupported_member")
    if (
        signature != b"PK\x03\x04"
        or flags != entry.flag_bits
        or method != entry.compress_type
        or crc != entry.CRC
        or compressed != entry.compress_size
        or size != entry.file_size
    ):
        raise RotaIntegrityError("invalid_archive")
    name_start = entry.header_offset + LOCAL_HEADER.size
    extra_start = name_start + names
    start = extra_start + extras
    end = start + compressed
    if start > end or end != boundary or boundary > len(raw):
        raise RotaIntegrityError("invalid_archive")
    name = raw[name_start:extra_start].decode("utf-8" if flags & 0x800 else "cp437")
    if name != entry.filename:
        raise RotaIntegrityError("invalid_archive")
    _check_extra(raw[extra_start:start])
    compressed_bytes = raw[start:end]
    if method == ZIP_STORED:
        if len(compressed_bytes) > limit:
            raise RotaIntegrityError(overflow)
        content = compressed_bytes
    else:
        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        content = decompressor.decompress(compressed_bytes, limit + 1)
        if len(content) > limit:
            raise RotaIntegrityError(overflow)
        if (
            not decompressor.eof
            or decompressor.unused_data
            or decompressor.unconsumed_tail
        ):
            raise RotaIntegrityError("invalid_archive")
    if len(content) != entry.file_size:
        code = (
            "invalid_manifest"
            if entry.filename == "manifest.json"
            else "content_mismatch"
        )
        raise RotaIntegrityError(code)
    if zlib.crc32(content) != entry.CRC:
        raise RotaIntegrityError("invalid_archive")
    return content


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RotaIntegrityError("invalid_manifest")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    raise RotaIntegrityError("invalid_manifest")


def _manifest(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise RotaIntegrityError("invalid_manifest") from error
    if (
        type(value) is not dict
        or set(value) != {"format", "version", "files"}
        or value["format"] != "maru.workforce-rota-manifest"
        or type(value["version"]) is not int
        or value["version"] != 1
        or type(value["files"]) is not dict
        or set(value["files"]) != CONTENT_MEMBERS
    ):
        raise RotaIntegrityError("invalid_manifest")
    for metadata in value["files"].values():
        if (
            type(metadata) is not dict
            or set(metadata) != {"bytes", "sha256"}
            or type(metadata["bytes"]) is not int
            or not 0 <= metadata["bytes"] <= MAX_UNCOMPRESSED_BYTES
            or type(metadata["sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"]) is None
        ):
            raise RotaIntegrityError("invalid_manifest")
    return cast("dict[str, Any]", value["files"])


def _check_content(content: bytes, metadata: dict[str, Any]) -> None:
    if (
        len(content) != metadata["bytes"]
        or hashlib.sha256(content).hexdigest() != metadata["sha256"]
    ):
        raise RotaIntegrityError("content_mismatch")


def verify_rota_package(path: Path) -> RotaIntegritySummary:
    """Check a bounded saved package without extracting or interpreting content.

    Parameters
    ----------
    path : Path
        User-selected regular archive file; no source path is included in output.

    Returns
    -------
    RotaIntegritySummary
        Matched member counts and byte bounds, not authenticity or schema evidence.

    Raises
    ------
    RotaIntegrityError
        If the file, ZIP layout, members, manifest, CRC, lengths or hashes fail.

    Notes
    -----
    This function initializes no Django, database, network or extraction path.
    Supplied HTML and schemas are read as bytes only. Copies remain personal data.
    """
    try:
        raw = _read_archive(path)
        directory = _check_directory(raw)
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = _members(archive)
            ordered = sorted(entries.values(), key=lambda entry: entry.header_offset)
            boundaries = {
                entry.filename: ordered[index + 1].header_offset
                if index + 1 < len(ordered)
                else directory
                for index, entry in enumerate(ordered)
            }
            manifest_bytes = _member_bytes(
                raw,
                entries["manifest.json"],
                boundaries["manifest.json"],
                min(MAX_MANIFEST_BYTES, MAX_UNCOMPRESSED_BYTES),
                "invalid_manifest",
            )
            manifest = _manifest(manifest_bytes)
            total = len(manifest_bytes)
            for name in sorted(CONTENT_MEMBERS):
                content = _member_bytes(
                    raw,
                    entries[name],
                    boundaries[name],
                    MAX_UNCOMPRESSED_BYTES - total,
                    "contents_too_large",
                )
                _check_content(content, manifest[name])
                total += len(content)
            return RotaIntegritySummary(
                archive_bytes=len(raw),
                uncompressed_bytes=total,
                checked_content_members=len(manifest),
            )
    except RotaIntegrityError:
        raise
    except OSError as error:
        raise RotaIntegrityError("unavailable_file") from error
    except (
        BadZipFile,
        EOFError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ) as error:
        raise RotaIntegrityError("invalid_archive") from error


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        """Exit without echoing rejected paths or argument values.

        Parameters
        ----------
        message : str
            Parser detail discarded to preserve minimized failure output.

        Notes
        -----
        Delegates to the parser's exit handler with status two and fixed text.
        """
        del message
        self.exit(2, "Rota integrity command failed: invalid_arguments. Use --help.\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline package-integrity command with minimized fixed outcomes.

    Parameters
    ----------
    argv : Sequence[str] | None, default=None
        Explicit command arguments, or ``None`` for process arguments.

    Returns
    -------
    int
        Zero for matching integrity, one for a refused file; argument errors use two.
    """
    parser = _ArgumentParser(
        prog="python -m maru.workforce.rota_integrity",
        description=__doc__,
        allow_abbrev=False,
    )
    parser.add_argument("package", type=Path, help="saved version-one rota ZIP")
    arguments = parser.parse_args(argv)
    try:
        summary = verify_rota_package(arguments.package)
    except RotaIntegrityError as error:
        sys.stderr.write(
            f"Rota integrity check failed: {error}\n"
            "Keep the source unchanged; obtain a fresh authorized copy.\n"
        )
        return 1
    sys.stdout.write(
        "Rota integrity matched: five required files; "
        f"{summary.checked_content_members} content hashes; "
        f"{summary.uncompressed_bytes} uncompressed bytes.\n"
        f"{ASSURANCE}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
