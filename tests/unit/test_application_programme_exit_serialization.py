"""Pin every portable Applications archive field and explicit private omission."""

import json
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from maru.applications import programme_exit_serialization as serializer
from maru.applications.programme_exit_configuration_queries import (
    ProgrammeExitConfiguration,
)
from maru.applications.programme_exit_department_queries import ProgrammeExitDepartment
from maru.applications.programme_exit_file_queries import ProgrammeExitReviewFile
from maru.programme.exit_archive_protocol import ProgrammeArchiveInvalidError


def arguments():
    return {
        "organization_id": UUID(int=1),
        "edition_id": UUID(int=2),
        "departments": (),
    }


def test_portable_root_is_deterministic_and_declares_purpose_exclusions():
    result = serializer.serialize_programme_exit_applications(**arguments())
    assert result == serializer.serialize_programme_exit_applications(**arguments())
    assert result.owner == "applications"
    assert result.contract == "applications.programme-exit@1"
    document, schema = json.loads(result.data), json.loads(result.schema)
    assert document["scope"] == "reviewed-proposals@1"
    assert document["purpose_exclusions"] == list(serializer.EXCLUSIONS)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(document)
    assert not validator.is_valid({**document, "private_extra": "secret"})
    assert not validator.is_valid({**document, "purpose_exclusions": []})
    assert not validator.is_valid({**document, "scope": "all-private-proposals"})


@pytest.mark.parametrize("record_type", tuple(serializer._RECORDS))
def test_all_selected_fields_are_explicit_and_pinned(record_type):
    name, selected = serializer._RECORDS[record_type]
    excluded = {"data"} if record_type is ProgrammeExitReviewFile else set()
    assert set(selected) == {row.name for row in fields(record_type)} - excluded
    values = dict.fromkeys(selected, None)
    record = record_type(**values, **dict.fromkeys(excluded, b"private bytes"))
    projected = serializer._value(record, [1000, 1000])
    assert projected == {"$record": name, **values}
    schema = json.loads(serializer._schema())
    schema.pop("type")
    schema.pop("properties")
    schema.pop("required")
    schema.pop("additionalProperties")
    schema["$ref"] = f"#/$defs/{name}"
    validator = Draft202012Validator(schema)
    assert validator.is_valid(projected)
    assert not validator.is_valid({**projected, "future_secret": "private"})


def test_new_dto_property_is_not_discovered(monkeypatch):
    monkeypatch.setattr(
        ProgrammeExitDepartment, "future_secret", "must not leak", raising=False
    )
    department = ProgrammeExitDepartment(
        ProgrammeExitConfiguration(UUID(int=3), ()), ()
    )
    result = serializer.serialize_programme_exit_applications(
        **{**arguments(), "departments": (department,)}
    )
    assert b"future_secret" not in result.data
    assert b"must not leak" not in result.data
    assert Draft202012Validator(json.loads(result.schema)).is_valid(
        json.loads(result.data)
    )


def test_bytes_are_never_serialized_into_file_metadata():
    file = ProgrammeExitReviewFile(
        *(UUID(int=i) for i in range(1, 5)), "file", 2, 7, "0" * 64, b"PRIVATE"
    )
    projection = serializer._value(file, [1000, 1000])
    assert "data" not in projection
    assert "PRIVATE" not in json.dumps(projection)


@pytest.mark.parametrize("value", [None, True, False, 5, "plain", (), (1, None)])
def test_closed_primitives_are_portable(value):
    assert serializer._value(value, [100, 100]) == (
        list(value) if type(value) is tuple else value
    )


def test_exact_decimal_uuid_and_utc_encodings():
    assert serializer._value(Decimal("1.2500"), [100, 100]) == "1.2500"
    assert serializer._value(UUID(int=1), [100, 100]) == str(UUID(int=1))
    assert (
        serializer._value(datetime(2030, 1, 1, tzinfo=UTC), [100, 100])
        == "2030-01-01T00:00:00+00:00"
    )


@pytest.mark.parametrize(
    "value",
    [
        b"private",
        {},
        [],
        SimpleNamespace(secret="private"),
        1.25,
        Decimal("NaN"),
        Decimal("Infinity"),
        UUID(int=0),
        datetime(2030, 1, 1),  # noqa: DTZ001 -- rejection fixture for a naive instant.
    ],
)
def test_unknown_unbounded_or_nonportable_values_refused(value):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value(value, [100, 100])


@pytest.mark.parametrize("budget", [[0, 100], [100, 0]])
def test_projection_budgets_fail_closed(budget):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value("text", budget)


def test_nested_values_are_bounded(monkeypatch):
    monkeypatch.setattr(serializer, "MAX_RECORD_DEPTH", 1)
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer._value(((1,),), [100, 100])


@pytest.mark.parametrize(
    "change",
    [
        {"organization_id": "not-a-uuid"},
        {"edition_id": UUID(int=0)},
        {"departments": []},
        {"departments": (SimpleNamespace(),)},
    ],
)
def test_root_types_are_closed(change):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_applications(**{**arguments(), **change})


@pytest.mark.parametrize("bound", ["MAX_OWNER_JSON_BYTES", "MAX_OWNER_VALUE_NODES"])
def test_root_bounds_fail_closed(monkeypatch, bound):
    monkeypatch.setattr(serializer, bound, 1)
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_applications(**arguments())


def test_bad_utf8_is_reported_as_invalid_archive():
    department = ProgrammeExitDepartment(ProgrammeExitConfiguration("\ud800", ()), ())
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_applications(
            **{**arguments(), "departments": (department,)}
        )
