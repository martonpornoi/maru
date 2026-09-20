"""Keep the complete room identity archive inside independent source authority."""

import json
from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.venues import programme_exit_queries as queries
from maru.venues.timetable_queries import VenueTimetableQueryDeniedError


@pytest.fixture
def source(monkeypatch):
    args = dict(
        zip(
            ("actor_id", "organization_id", "edition_id", "correlation_id"),
            (UUID(int=i) for i in range(1, 5)),
            strict=True,
        )
    )
    room = queries.VenueTimetableSpace(
        UUID(int=5),
        2,
        "Main Stage",
        "Théâtre",
        "retired",
        UUID(int=6),
        3,
        "Convention Hotel",
        "active",
    )
    purpose, lock, owner = Mock(), Mock(), Mock(return_value=(room,))
    monkeypatch.setattr(queries, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(queries, "lock_programme_staffing_scope", lock)
    monkeypatch.setattr(queries, "list_venue_timetable_spaces", owner)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        queries,
        "load_programme_exit_venues",
        queries.load_programme_exit_venues.__wrapped__,
    )
    return SimpleNamespace(
        args=args, room=room, purpose=purpose, lock=lock, owner=owner
    )


def test_complete_explicit_schema_and_retired_identity(source):
    result = queries.load_programme_exit_venues(**source.args)
    document, schema = json.loads(result.data), json.loads(result.schema)
    assert result.owner == "venues"
    assert result.contract == "venues.programme-exit@1"
    assert document["scope"] == "programme-room-wayfinding@1"
    assert document["purpose_exclusions"] == list(queries.EXCLUSIONS)
    assert document["spaces"] == [
        {
            "id": str(source.room.id),
            "version": 2,
            "label": "Main Stage",
            "configuration_label": "Théâtre",
            "lifecycle": "retired",
            "venue_id": str(source.room.venue_id),
            "venue_version": 3,
            "venue_label": "Convention Hotel",
            "venue_lifecycle": "active",
        }
    ]
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(document)
    document["spaces"][0]["contact_email"] = "withheld@example.invalid"
    assert not Draft202012Validator(schema).is_valid(document)
    assert source.purpose.call_count == 3
    assert source.owner.call_count == 2
    assert all(call.kwargs == source.args for call in source.owner.call_args_list)
    source.lock.assert_called_once_with(
        organization_id=source.args["organization_id"],
        edition_id=source.args["edition_id"],
    )


def test_empty_owner_still_needs_both_authorities(source):
    source.owner.return_value = ()
    assert (
        json.loads(queries.load_programme_exit_venues(**source.args).data)["spaces"]
        == []
    )
    assert source.purpose.call_count == 3
    assert source.owner.call_count == 2


@pytest.mark.parametrize("after", [0, 1, 2])
def test_each_purpose_check_can_refuse(source, after):
    source.purpose.side_effect = [None] * after + [ProgrammeAuthorizationDeniedError()]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        queries.load_programme_exit_venues(**source.args)
    if after < 2:
        source.owner.assert_not_called()


@pytest.mark.parametrize("after", [0, 1])
@pytest.mark.parametrize("failure", [VenueTimetableQueryDeniedError, RuntimeError])
def test_source_policy_or_mandatory_audit_failure_never_returns_archive(
    source, after, failure
):
    source.owner.side_effect = [(source.room,)] * after + [failure()]
    with pytest.raises(failure):
        queries.load_programme_exit_venues(**source.args)


def test_source_drift_refuses_bytes(source):
    source.owner.side_effect = [(source.room,), (replace(source.room, version=3),)]
    with pytest.raises(queries.VenueTimetableQueryUnavailableError):
        queries.load_programme_exit_venues(**source.args)


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "correlation_id"]
)
@pytest.mark.parametrize("value", [UUID(int=0), "not-uuid", None, True])
def test_scope_validation_precedes_private_queries(source, field, value):
    with pytest.raises(queries.VenueTimetableQueryUnavailableError):
        queries.load_programme_exit_venues(**{**source.args, field: value})
    source.purpose.assert_not_called()
    source.owner.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", UUID(int=0)),
        ("venue_id", "not-uuid"),
        ("version", True),
        ("version", 0),
        ("venue_version", -1),
        ("venue_version", 1.5),
        ("label", None),
        ("configuration_label", b"not text"),
        ("lifecycle", []),
        ("venue_label", {}),
        ("venue_lifecycle", False),
        ("label", "\ud800"),
    ],
)
def test_malformed_typed_owner_projection_is_not_encoded(source, field, value):
    source.owner.return_value = (replace(source.room, **{field: value}),)
    with pytest.raises(queries.VenueTimetableQueryUnavailableError):
        queries.load_programme_exit_venues(**source.args)


@pytest.mark.parametrize("kind", ["list", "duplicate", "unknown", "overflow", "bytes"])
def test_invalid_or_overbudget_collection_is_never_partial(source, monkeypatch, kind):
    if kind == "list":
        source.owner.return_value = [source.room]
    elif kind == "duplicate":
        source.owner.return_value = (source.room, source.room)
    elif kind == "unknown":
        source.owner.return_value = (SimpleNamespace(secret="must not discover"),)
    elif kind == "overflow":
        monkeypatch.setattr(queries, "MAX_TIMETABLE_SPACES", 0)
    else:
        monkeypatch.setattr(queries, "MAX_EXIT_JSON_BYTES", 10)
    with pytest.raises(queries.VenueTimetableQueryUnavailableError):
        queries.load_programme_exit_venues(**source.args)
