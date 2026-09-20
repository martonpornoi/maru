"""Portable Shift-link fields exclude unrelated private workforce records."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from maru.programme.exit_archive_protocol import ProgrammeArchiveInvalidError
from maru.programme.staffing_inputs import ProgrammeStaffingSource
from maru.workforce import programme_exit_serialization as serializer
from maru.workforce.programme_binding_queries import (
    ProgrammeBindingHistoryEntry,
    ProgrammeBindingView,
)
from maru.workforce.programme_exit_queries import ProgrammeExitBinding


def record():
    source = ProgrammeStaffingSource(
        UUID(int=1),
        UUID(int=2),
        1,
        UUID(int=3),
        1,
        UUID(int=4),
        UUID(int=5),
        UUID(int=6),
    )
    current = ProgrammeBindingView(
        UUID(int=7),
        1,
        UUID(int=8),
        source,
        UUID(int=9),
        2,
        "a" * 64,
        "b" * 64,
        "create",
        None,
    )
    history = ProgrammeBindingHistoryEntry(
        current,
        UUID(int=10),
        "Synthetic accountable link",
        datetime(2030, 1, 1, tzinfo=UTC),
    )
    return ProgrammeExitBinding(UUID(int=11), current, (history,))


@pytest.mark.parametrize("rows", [(), (record(),)])
def test_deterministic_closed_schema_and_explicit_private_exclusions(rows):
    section = serializer.serialize_programme_exit_bindings(rows)
    assert section == serializer.serialize_programme_exit_bindings(rows)
    assert section.owner == "workforce"
    assert section.contract == "workforce.programme-exit@1"
    document, schema = json.loads(section.data), json.loads(section.schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert validator.is_valid(document)
    assert document["purpose_exclusions"] == list(serializer.EXCLUSIONS)
    assert not validator.is_valid({**document, "worker_directory": []})
    assert not validator.is_valid({**document, "purpose_exclusions": []})
    if rows:
        document["bindings"][0]["history"][0]["private_commitment_reason"] = "never"
        assert not validator.is_valid(document)


def test_future_fields_are_not_discovered(monkeypatch):
    monkeypatch.setattr(
        ProgrammeBindingView, "private_future", "never-export", raising=False
    )
    section = serializer.serialize_programme_exit_bindings((record(),))
    assert b"private_future" not in section.data
    assert b"never-export" not in section.data


@pytest.mark.parametrize("value", [[], (SimpleNamespace(),), None])
def test_root_type_is_closed(value):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_bindings(value)


@pytest.mark.parametrize(
    "change",
    [
        {"item_id": UUID(int=0)},
        {"item_id": "fake"},
        {"history": []},
        {"current": SimpleNamespace()},
    ],
)
def test_record_shapes_are_closed(change):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_bindings((replace(record(), **change),))


@pytest.mark.parametrize(
    "change",
    [
        {"version": 0},
        {"version": True},
        {"version": 2**63},
        {"source": SimpleNamespace()},
        {"operation": 3},
        {"predecessor_id": "unknown"},
    ],
)
def test_binding_scalars_and_source_are_closed(change):
    row = record()
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_bindings(
            (replace(row, current=replace(row.current, **change)),)
        )


@pytest.mark.parametrize(
    "history",
    [
        SimpleNamespace(),
        replace(record().history[0], occurred_at=None),
        replace(
            record().history[0],
            occurred_at=datetime(2030, 1, 1, tzinfo=UTC).replace(tzinfo=None),
        ),
    ],
)
def test_history_shape_and_aware_instant_required(history):
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_bindings(
            (replace(record(), history=(history,)),)
        )


def test_known_optional_predecessor_stays_explicit():
    row = record()
    section = serializer.serialize_programme_exit_bindings(
        (replace(row, current=replace(row.current, predecessor_id=UUID(int=99))),)
    )
    assert json.loads(section.data)["bindings"][0]["current"]["predecessor_id"] == str(
        UUID(int=99)
    )


@pytest.mark.parametrize("rows", [(), (record(),)])
def test_owner_byte_budget_fails_without_partial_output(monkeypatch, rows):
    monkeypatch.setattr(serializer, "MAX_OWNER_JSON_BYTES", 1)
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_bindings(rows)


def test_invalid_utf8_private_text_fails_closed():
    row = record()
    with pytest.raises(ProgrammeArchiveInvalidError):
        serializer.serialize_programme_exit_bindings(
            (replace(row, current=replace(row.current, operation="\ud800")),)
        )
