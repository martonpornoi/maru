"""Portable bounded packaging only; no owner access, native or exit acceptance."""

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from maru.programme import exit_archive_protocol as protocol


def _context():
    return protocol.ProgrammeArchiveContext(
        uuid4(), uuid4(), uuid4(), uuid4(), datetime(2030, 9, 20, 8, tzinfo=UTC)
    )


def _sections():
    return tuple(
        protocol.ProgrammeArchiveSection(
            owner,
            f"{owner}.programme-exit@1",
            json.dumps({"synthetic": owner, "records": []}).encode(),
            b'{"type":"object","additionalProperties":false}',
        )
        for owner in protocol.OWNERS
    )


def test_exact_closed_owner_inventory_schemas_and_bytes_are_deterministic():
    context, sections = _context(), _sections()
    attachments = (
        protocol.ProgrammeArchiveFile(uuid4(), b"synthetic private file one"),
        protocol.ProgrammeArchiveFile(uuid4(), b"synthetic private file two"),
    )
    encoded = protocol.encode_programme_exit_archive(
        context=context, sections=sections, files=attachments
    )
    assert encoded == protocol.encode_programme_exit_archive(
        context=context,
        sections=tuple(reversed(sections)),
        files=tuple(reversed(attachments)),
    )
    with zipfile.ZipFile(io.BytesIO(encoded)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["contract"] == "programme.exit-archive@1"
        assert manifest["profile"] == {"code": "programme_operations", "version": 1}
        assert manifest["classification"] == "C3 Restricted"
        assert manifest["scope"] == {
            "organization_id": str(context.organization_id),
            "edition_id": str(context.edition_id),
            "requester_id": str(context.requester_id),
            "correlation_id": str(context.correlation_id),
            "generated_at": "2030-09-20T08:00:00+00:00",
        }
        assert len(manifest["members"]) == 18
        assert set(archive.namelist()) == {
            "manifest.json",
            *(member["path"] for member in manifest["members"]),
        }
        for member in manifest["members"]:
            value = archive.read(member["path"])
            assert len(value) == member["byte_length"]
            assert hashlib.sha256(value).hexdigest() == member["sha256"]
        for section in sections:
            assert archive.read(f"records/{section.owner}.json") == section.data
            assert archive.read(f"schemas/{section.owner}.json") == section.schema
        for item in archive.infolist():
            assert item.compress_type == zipfile.ZIP_STORED
            assert item.date_time == (1980, 1, 1, 0, 0, 0)
            assert item.external_attr >> 16 == 0o100600
        assert any(
            "Not encrypted or signed" in message for message in manifest["limitations"]
        )
        assert any(
            "Not a database backup" in message for message in manifest["limitations"]
        )
    assert b"private file one" not in repr(attachments).encode()
    assert b"synthetic" not in repr(sections).encode()


@pytest.mark.parametrize(
    "field", ["organization_id", "edition_id", "requester_id", "correlation_id"]
)
@pytest.mark.parametrize("value", [None, True, "not-an-id", UUID(int=0)])
def test_context_refuses_untrusted_or_empty_identifiers(field, value):
    with pytest.raises(
        protocol.ProgrammeArchiveInvalidError, match=r"^programme_exit_archive_invalid$"
    ):
        protocol.encode_programme_exit_archive(
            context=replace(_context(), **{field: value}), sections=_sections()
        )


@pytest.mark.parametrize(
    "value", [None, "2030-09-20", _context().generated_at.replace(tzinfo=None)]
)
def test_aware_generation_time_is_required(value):
    with pytest.raises(protocol.ProgrammeArchiveInvalidError):
        protocol.encode_programme_exit_archive(
            context=replace(_context(), generated_at=value), sections=_sections()
        )


def test_time_is_normalized_not_guessed_from_machine_timezone():
    context = _context()
    offset = replace(
        context,
        generated_at=context.generated_at.astimezone(timezone(timedelta(hours=2))),
    )
    assert protocol.encode_programme_exit_archive(
        context=context, sections=_sections()
    ) == protocol.encode_programme_exit_archive(context=offset, sections=_sections())


@pytest.mark.parametrize(
    "fault",
    ["missing", "duplicate", "foreign_owner", "future_contract", "raw_object", "list"],
)
def test_owner_sections_are_complete_closed_and_version_pinned(fault):
    sections = _sections()
    if fault == "missing":
        sections = sections[:-1]
    elif fault == "duplicate":
        sections = (*sections[:-1], sections[0])
    elif fault == "foreign_owner":
        sections = (replace(sections[0], owner="registration"), *sections[1:])
    elif fault == "future_contract":
        sections = (
            replace(sections[0], contract="applications.programme-exit@2"),
            *sections[1:],
        )
    elif fault == "raw_object":
        sections = (None, *sections[1:])
    else:
        sections = list(sections)
    with pytest.raises(protocol.ProgrammeArchiveInvalidError):
        protocol.encode_programme_exit_archive(context=_context(), sections=sections)


@pytest.mark.parametrize("field", ["data", "schema"])
@pytest.mark.parametrize(
    "value",
    [
        b"",
        b"[]",
        b"null",
        b"private not json",
        b"\xff",
        b'{"duplicate":1,"duplicate":2}',
        b'{"value":NaN}',
        b'{"value":1e9999}',
        b'{"value":"\\ud800"}',
        b'{"nested":{"same":1,"same":2}}',
    ],
    ids=[
        "empty",
        "list",
        "null",
        "text",
        "utf8",
        "duplicate",
        "nan",
        "overflow",
        "surrogate",
        "nested_duplicate",
    ],
)
def test_payload_and_schema_refuse_ambiguous_or_nonportable_json(field, value):
    sections = _sections()
    changed = (replace(sections[0], **{field: value}), *sections[1:])
    with pytest.raises(protocol.ProgrammeArchiveInvalidError) as error:
        protocol.encode_programme_exit_archive(context=_context(), sections=changed)
    assert str(error.value) == "programme_exit_archive_invalid"
    assert "private not json" not in str(error.value)


@pytest.mark.parametrize(
    "fault",
    ["zero", "path", "empty", "duplicate", "count", "size", "list", "raw_object"],
)
def test_files_have_only_opaque_ids_and_enforced_complete_bounds(monkeypatch, fault):
    item = protocol.ProgrammeArchiveFile(uuid4(), b"synthetic")
    files = (item,)
    if fault == "zero":
        files = (replace(item, file_id=UUID(int=0)),)
    elif fault == "path":
        files = (replace(item, file_id="../../private"),)
    elif fault == "empty":
        files = (replace(item, data=b""),)
    elif fault == "duplicate":
        files = (item, item)
    elif fault == "count":
        monkeypatch.setattr(protocol, "MAX_FILES", 0)
    elif fault == "size":
        monkeypatch.setattr(protocol, "MAX_FILE_BYTES", len(item.data) - 1)
    elif fault == "list":
        files = [item]
    else:
        files = (None,)
    with pytest.raises(protocol.ProgrammeArchiveInvalidError):
        protocol.encode_programme_exit_archive(
            context=_context(), sections=_sections(), files=files
        )


def test_total_content_limit_is_all_or_refuse_not_truncated(monkeypatch):
    sections = _sections()
    limit = sum(len(item.data) + len(item.schema) for item in sections)
    monkeypatch.setattr(protocol, "MAX_CONTENT_BYTES", limit)
    assert protocol.encode_programme_exit_archive(context=_context(), sections=sections)
    monkeypatch.setattr(protocol, "MAX_CONTENT_BYTES", limit - 1)
    with pytest.raises(protocol.ProgrammeArchiveInvalidError):
        protocol.encode_programme_exit_archive(context=_context(), sections=sections)


def test_individual_json_limit_precedes_parsing(monkeypatch):
    monkeypatch.setattr(protocol, "MAX_JSON_BYTES", 1)
    with pytest.raises(protocol.ProgrammeArchiveInvalidError):
        protocol.encode_programme_exit_archive(context=_context(), sections=_sections())
