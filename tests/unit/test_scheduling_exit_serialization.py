"""Portable Scheduling archive fields never imply live output or generic bytes."""

import json
from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from maru.programme.exit_archive_protocol import ProgrammeArchiveInvalidError
from maru.scheduling import exit_serialization as serializer
from maru.scheduling.exit_queries import SchedulingExitOwner
from maru.scheduling.release_artifacts import CanonicalReleaseArtifact


def empty():
    return SchedulingExitOwner(None, (), (), (), None, (), ())


def test_root_is_closed_and_explicitly_historical():
    result = serializer.serialize_scheduling_exit_owner(empty())
    assert result == serializer.serialize_scheduling_exit_owner(empty())
    assert result.owner == "scheduling"
    assert result.contract == "scheduling.programme-exit@1"
    data, schema = json.loads(result.data), json.loads(result.schema)
    assert data["purpose"] == "historical-evidence-not-current-timetable"
    assert data["day_columns"] == list(serializer.DAY_COLUMNS)
    assert data["occurrence_columns"] == list(serializer.OCCURRENCE_COLUMNS)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(data)
    assert not validator.is_valid({**data, "purpose": "current-timetable"})
    assert not validator.is_valid({**data, "extra_private": "hidden"})


@pytest.mark.parametrize("record_type", tuple(serializer._RECORDS))
def test_each_owner_record_has_only_explicit_pinned_fields(record_type):
    name, selected = serializer._RECORDS[record_type]
    assert set(selected) == {row.name for row in fields(record_type)}
    values = dict.fromkeys(selected, None)
    if record_type is CanonicalReleaseArtifact:
        values["payload"] = b"{}"
    record = record_type(**values)
    projected = serializer._value(record, [1000, 1000])
    assert projected["$record"] == name
    assert set(projected) == {"$record", *selected}
    schema = json.loads(serializer._schema())
    for key in ("type", "properties", "required", "additionalProperties"):
        schema.pop(key)
    schema["$ref"] = f"#/$defs/{name}"
    validator = Draft202012Validator(schema)
    assert validator.is_valid(projected)
    assert not validator.is_valid({**projected, "future_secret": "no"})


def test_only_canonical_artifact_payload_is_lossless_utf8_text():
    payload = '{"synthetic":"é\\n"}'.encode()
    artifact = CanonicalReleaseArtifact(
        "programme.release.canonical@1", payload, "a" * 64, len(payload)
    )
    projected = serializer._value(artifact, [1000, 1000])
    assert projected["payload"].encode() == payload
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value(payload, [1000, 1000])
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._field(
            CanonicalReleaseArtifact("contract", "not-bytes", "digest", 9), "payload"
        )


def test_unknown_future_dto_field_is_not_discovered(monkeypatch):
    monkeypatch.setattr(
        SchedulingExitOwner, "future_secret", "never-export", raising=False
    )
    result = serializer.serialize_scheduling_exit_owner(empty())
    assert b"future_secret" not in result.data
    assert b"never-export" not in result.data


@pytest.mark.parametrize("value", [None, True, False, 3, "private", (), (1, None)])
def test_portable_primitives(value):
    assert serializer._value(value, [100, 100]) == (
        list(value) if type(value) is tuple else value
    )


def test_exact_ids_dates_and_closed_operation_enum():
    assert serializer._value(UUID(int=1), [100, 100]) == str(UUID(int=1))
    assert (
        serializer._value(datetime(2030, 1, 1, tzinfo=UTC), [100, 100])
        == "2030-01-01T00:00:00+00:00"
    )
    assert (
        serializer._value(serializer.SchedulingOperation.RELEASE_WITHDRAW, [100, 100])
        == "release_withdraw"
    )


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        1.5,
        SimpleNamespace(),
        UUID(int=0),
        datetime(2030, 1, 1, tzinfo=UTC).replace(tzinfo=None),
    ],
)
def test_unknown_or_invalid_values_refused(value):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value(value, [100, 100])


@pytest.mark.parametrize("budget", [[0, 100], [100, 0]])
def test_projection_budget_refuses(budget):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value("private", budget)


def test_depth_budget_refuses(monkeypatch):
    monkeypatch.setattr(serializer, "MAX_RECORD_DEPTH", 0)
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value((1,), [100, 100])


@pytest.mark.parametrize("bound", ["MAX_OWNER_JSON_BYTES", "MAX_OWNER_VALUE_NODES"])
def test_owner_budget_refuses(monkeypatch, bound):
    monkeypatch.setattr(serializer, bound, 1)
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_scheduling_exit_owner(empty())


def test_unknown_root_and_invalid_utf8_fail_closed():
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_scheduling_exit_owner(SimpleNamespace())
    root = SchedulingExitOwner("\ud800", (), (), (), None, (), ())
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_scheduling_exit_owner(root)
