"""Pin portable explicit owner schemas and prevent implicit disclosure expansion."""

import json
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from maru.programme import exit_serialization as serializer
from maru.programme.exit_archive_protocol import ProgrammeArchiveInvalidError
from maru.programme.exit_owner_queries import ProgrammeExitOwner
from maru.programme.host_queries import (
    ProgrammeHostInvitationProjection,
    ProgrammeHostSelfSnapshot,
)
from maru.programme.release_inputs import ProgrammePlacementDecisionKind


def empty():
    return ProgrammeExitOwner(UUID(int=1), UUID(int=2), ())


def test_empty_owner_is_deterministic_and_matches_portable_closed_schema():
    encoded = serializer.serialize_programme_exit_owner(empty())
    assert encoded == serializer.serialize_programme_exit_owner(empty())
    assert encoded.owner == "programme"
    assert encoded.contract == "programme.programme-exit@1"
    data, schema = json.loads(encoded.data), json.loads(encoded.schema)
    assert data == {
        "$record": "owner",
        "organization_id": str(UUID(int=1)),
        "edition_id": str(UUID(int=2)),
        "items": [],
    }
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(data)
    assert not validator.is_valid({**data, "private_key": "forbidden"})
    assert not validator.is_valid(
        {key: value for key, value in data.items() if key != "items"}
    )
    assert not validator.is_valid({**data, "$record": "unknown"})


@pytest.mark.parametrize("record_type", tuple(serializer._RECORDS))
def test_every_declared_record_field_is_pinned_and_serializes(record_type):
    name, selected = serializer._RECORDS[record_type]
    # Introspection belongs only in regression tests, never disclosure selection.
    assert set(selected) == {field.name for field in fields(record_type)}
    record = record_type(**dict.fromkeys(selected, None))
    projected = serializer._value(record, [1000, 1000])
    assert projected == {"$record": name, **dict.fromkeys(selected, None)}
    schema = json.loads(serializer._schema())
    schema["$ref"] = f"#/$defs/{name}"
    assert Draft202012Validator(schema).is_valid(projected)
    assert not Draft202012Validator(schema).is_valid(
        {**projected, "future_secret": "never"}
    )


def test_new_dto_property_is_not_discovered(monkeypatch):
    monkeypatch.setattr(
        ProgrammeExitOwner, "future_secret", "must not leak", raising=False
    )
    result = serializer.serialize_programme_exit_owner(empty())
    assert b"future_secret" not in result.data
    assert b"must not leak" not in result.data
    assert ProgrammeHostInvitationProjection not in serializer._RECORDS
    assert ProgrammeHostSelfSnapshot not in serializer._RECORDS


@pytest.mark.parametrize(
    "value", [None, True, False, 0, 2**63 - 1, "synthetic é", (), (1, None)]
)
def test_only_portable_primitives_and_arrays_are_preserved(value):
    result = serializer._value(value, [100, 100])
    assert result == (list(value) if type(value) is tuple else value)


def test_uuids_instants_and_closed_string_codes_have_stable_encoding():
    instant = datetime(2030, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=2)))
    assert serializer._value(instant, [100, 100]) == "2030-01-02T01:04:00+00:00"
    assert serializer._value(UUID(int=1), [100, 100]) == str(UUID(int=1))
    kind = ProgrammePlacementDecisionKind.ACCESSIBILITY_FIT
    assert serializer._value(kind, [100, 100]) == kind.value


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        b"secret",
        1.5,
        float("nan"),
        object(),
        SimpleNamespace(secret="never"),
        UUID(int=0),
        datetime(2030, 1, 1),  # noqa: DTZ001 - deliberate rejected naive input
    ],
)
def test_unknown_objects_and_nonportable_values_refuse(value):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value(value, [100, 100])


@pytest.mark.parametrize(
    "bound", ["MAX_OWNER_JSON_BYTES", "MAX_OWNER_VALUE_NODES", "MAX_RECORD_DEPTH"]
)
def test_bounded_encoding_refuses_overflow(monkeypatch, bound):
    monkeypatch.setattr(serializer, bound, 0)
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_owner(empty())


def test_whole_encoded_byte_limit_and_selected_text_limit_are_both_enforced(
    monkeypatch,
):
    size = len(serializer.serialize_programme_exit_owner(empty()).data)
    monkeypatch.setattr(serializer, "MAX_OWNER_JSON_BYTES", size)
    serializer.serialize_programme_exit_owner(empty())
    monkeypatch.setattr(serializer, "MAX_OWNER_JSON_BYTES", size - 1)
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_owner(empty())
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value("éé", [100, 3])


def test_invalid_utf8_is_safely_wrapped_without_returned_private_content():
    with pytest.raises(
        ProgrammeArchiveInvalidError, match=r"^programme_exit_archive_invalid$"
    ):
        serializer.serialize_programme_exit_owner(replace(empty(), items=("\ud800",)))


@pytest.mark.parametrize("value", [None, {}, (), SimpleNamespace()])
def test_root_must_be_the_exact_owner_projection(value):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_owner(value)
