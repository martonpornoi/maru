"""Portable background encoding stays bounded, deterministic and private-sink only."""

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from maru.programme import exit_archive_protocol as small
from maru.programme import exit_archive_stream as stream


@pytest.fixture
def package():
    context = small.ProgrammeArchiveContext(
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        datetime(2030, 1, 1, tzinfo=UTC),
    )
    sections = tuple(
        small.ProgrammeArchiveSection(
            owner,
            f"{owner}.programme-exit@1",
            json.dumps(
                {
                    "id": str(context.edition_id),
                    "organization_id": str(context.organization_id),
                    "adoption_profile_code": "programme_operations",
                    "adoption_profile_version": 1,
                }
                if owner == "events"
                else {"synthetic": owner}
            ).encode(),
            b'{"type":"object"}',
        )
        for owner in small.OWNERS
    )
    return {
        "context": context,
        "sections": sections,
        "files": (small.ProgrammeArchiveFile(UUID(int=5), b"synthetic PDF bytes"),),
        "source_digest": "a" * 64,
    }


def test_complete_deterministic_stored_zip_preserves_exact_members_and_manifest(
    package,
):
    destination = io.BytesIO()
    result = stream.write_programme_exit_archive(**package, sink=destination)
    data = destination.getvalue()
    assert not destination.closed
    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert result.size_bytes == len(data)
    assert result.member_count == 18
    reversed_sink = io.BytesIO()
    stream.write_programme_exit_archive(
        **{**package, "sections": package["sections"][::-1]}, sink=reversed_sink
    )
    assert reversed_sink.getvalue() == data
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["contract"] == small.CONTRACT
        assert manifest["capacity_contract"] == stream.CAPACITY_CONTRACT
        assert manifest["source_digest"] == package["source_digest"]
        assert manifest["profile"] == {"code": "programme_operations", "version": 1}
        assert manifest["classification"] == "C3 Restricted"
        assert set(manifest["owner_contracts"]) == set(small.OWNERS)
        for member in manifest["members"]:
            value = archive.read(member["path"])
            assert len(value) == member["byte_length"]
            assert hashlib.sha256(value).hexdigest() == member["sha256"]
        for info in archive.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.external_attr >> 16 == 0o100600
            assert not info.filename.startswith(("/", ".."))
        for section in package["sections"]:
            assert archive.read(f"records/{section.owner}.json") == section.data
            assert archive.read(f"schemas/{section.owner}.json") == section.schema


def test_larger_background_json_never_widens_the_provisional_codec(package):
    large = json.dumps({"synthetic": "a" * small.MAX_JSON_BYTES}).encode()
    sections = tuple(
        replace(row, data=large) if row.owner == "programme" else row
        for row in package["sections"]
    )
    writes = []

    class PrivateSink(io.BytesIO):
        def write(self, value):
            writes.append(len(value))
            return super().write(value)

    target = PrivateSink()
    result = stream.write_programme_exit_archive(
        **{**package, "sections": sections}, sink=target
    )
    assert max(writes) <= stream.WRITE_CHUNK_BYTES
    assert result.size_bytes > small.MAX_JSON_BYTES
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        small.encode_programme_exit_archive(
            context=package["context"], sections=sections, files=package["files"]
        )


@pytest.mark.parametrize(
    "kind", ["missing", "duplicate", "unknown", "contract", "list", "wrong-type"]
)
def test_invalid_owner_set_is_refused_before_any_write(package, kind):
    rows = package["sections"]
    if kind == "missing":
        rows = rows[:-1]
    elif kind == "duplicate":
        rows = (*rows[:-1], rows[0])
    elif kind == "unknown":
        rows = (replace(rows[0], owner="../private"), *rows[1:])
    elif kind == "contract":
        rows = (replace(rows[0], contract="programme.wrong@1"), *rows[1:])
    elif kind == "list":
        rows = list(rows)
    else:
        rows = (None, *rows[1:])
    target = io.BytesIO()
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream.write_programme_exit_archive(
            **{**package, "sections": rows}, sink=target
        )
    assert target.getvalue() == b""


@pytest.mark.parametrize("field", ["data", "schema"])
@pytest.mark.parametrize(
    "value",
    [
        b"",
        b"[]",
        b"\xff",
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":1e999}',
        rb'{"a":"\uD800"}',
        None,
    ],
)
def test_nonportable_json_never_writes_partial_output(package, field, value):
    rows = package["sections"]
    rows = (replace(rows[0], **{field: value}), *rows[1:])
    target = io.BytesIO()
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream.write_programme_exit_archive(
            **{**package, "sections": rows}, sink=target
        )
    assert target.getvalue() == b""


@pytest.mark.parametrize(
    "changed",
    [
        {"adoption_profile_code": "../invalid"},
        {"adoption_profile_version": True},
        {"adoption_profile_version": 0},
        {"id": str(UUID(int=6))},
        {"organization_id": str(UUID(int=6))},
    ],
)
def test_profile_and_scope_are_bound_to_actual_events_section(package, changed):
    rows = tuple(
        replace(row, data=json.dumps({**json.loads(row.data), **changed}).encode())
        if row.owner == "events"
        else row
        for row in package["sections"]
    )
    target = io.BytesIO()
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream.write_programme_exit_archive(
            **{**package, "sections": rows}, sink=target
        )
    assert target.getvalue() == b""


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MAX_RECORD_BYTES", 1),
        ("MAX_SCHEMA_BYTES", 1),
        ("MAX_FILE_BYTES", 1),
        ("MAX_FILES", 0),
        ("MAX_CONTENT_BYTES", 1),
        ("MAX_METADATA_BYTES", 1),
    ],
)
def test_each_supported_capacity_limit_fails_before_any_write(
    package, monkeypatch, name, value
):
    monkeypatch.setattr(stream, name, value)
    target = io.BytesIO()
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream.write_programme_exit_archive(**package, sink=target)
    assert target.getvalue() == b""


@pytest.mark.parametrize(
    "files",
    [
        [],
        (None,),
        (small.ProgrammeArchiveFile(UUID(int=0), b"x"),),
        (small.ProgrammeArchiveFile(UUID(int=1), b""),),
    ],
)
def test_malformed_file_collection_is_rejected(package, files):
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream.write_programme_exit_archive(
            **{**package, "files": files}, sink=io.BytesIO()
        )


def test_duplicate_file_identity_is_not_a_second_member(package):
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream.write_programme_exit_archive(
            **{**package, "files": package["files"] * 2}, sink=io.BytesIO()
        )


@pytest.mark.parametrize("digest", ["", "A" * 64, "f" * 63, None])
def test_invalid_source_identity_never_writes(package, digest):
    target = io.BytesIO()
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream.write_programme_exit_archive(
            **{**package, "source_digest": digest}, sink=target
        )
    assert target.getvalue() == b""


def test_bounded_sink_refuses_short_write_and_total_overflow(monkeypatch):
    class ShortSink(io.BytesIO):
        def write(self, value):
            super().write(value[:1])
            return 1

    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream._BoundedSink(ShortSink()).write(b"longer")
    target = io.BytesIO()
    monkeypatch.setattr(stream, "MAX_CONTENT_BYTES", 1)
    monkeypatch.setattr(stream, "MAX_METADATA_BYTES", 1)
    with pytest.raises(small.ProgrammeArchiveInvalidError):
        stream._BoundedSink(target).write(b"longer")
    assert target.getvalue() == b""
