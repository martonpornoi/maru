"""Closed stop dispositions and source identity without private source fields."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from maru.authorization import programme_stop_queries as queries

NOW = datetime(2030, 9, 1, tzinfo=UTC)


def _row(**changes):
    return {
        "id": uuid4(),
        "edition_id": uuid4(),
        "department_id": None,
        "resource_binding_id": None,
        "principal_id": uuid4(),
        "effective_from": NOW - timedelta(days=1),
        "expires_at": None,
        "revoked_at": None,
        "revoked_by_id": None,
        **changes,
    }


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "retained_historical"),
        ({"edition_id": None}, "retained_shared"),
        ({"expires_at": NOW}, "already_inactive"),
        ({"effective_from": NOW + timedelta(seconds=1)}, "already_inactive"),
        ({"revoked_at": NOW}, "separately_revoked"),
        ({"revoked_at": NOW, "edition_id": None}, "separately_revoked"),
    ],
)
def test_exact_dispositions_do_not_claim_stop_changed_authority(changes, expected):
    row = _row(**changes)
    result = queries._reference("capability_grant", row, NOW)
    assert result.disposition == expected
    assert result.id == row["id"]
    assert "principal_id" not in asdict(result)
    assert str(row["principal_id"]) not in repr(result)


@pytest.mark.parametrize(
    ("changes", "scope"),
    [
        ({"edition_id": None}, "organization"),
        ({}, "edition"),
        ({"department_id": uuid4()}, "department"),
        ({"department_id": uuid4(), "resource_binding_id": uuid4()}, "resource"),
    ],
)
def test_exact_scope_is_not_collapsed_into_an_edition_wide_grant(changes, scope):
    assert (
        queries._reference("role_assignment", _row(**changes), NOW).scope_level == scope
    )


def test_hidden_recipient_and_validity_changes_still_change_source_identity():
    row = _row()
    original = queries._reference("capability_grant", row, NOW)
    for changes in (
        {"principal_id": uuid4()},
        {"effective_from": NOW - timedelta(hours=1)},
        {"expires_at": NOW + timedelta(hours=1)},
    ):
        assert (
            queries._reference(
                "capability_grant", {**row, **changes}, NOW
            ).source_fingerprint
            != original.source_fingerprint
        )


def _projection(**changes):
    return queries._project(
        **{
            "organization_id": uuid4(),
            "edition_id": uuid4(),
            "grants": (),
            "roles": (),
            "requests": (),
            "now": NOW,
            **changes,
        }
    )


def test_pending_expiry_is_not_invented_rejection():
    requests = [
        {"decision__id": None, "approval_deadline": NOW + timedelta(seconds=1)},
        {"decision__id": None, "approval_deadline": NOW},
        {"decision__id": uuid4(), "approval_deadline": NOW},
    ]
    result = _projection(requests=requests)
    assert (
        result.pending_requests,
        result.expired_requests,
        result.decided_requests,
    ) == (1, 1, 1)


@pytest.mark.parametrize("field", ["grants", "roles", "requests"])
def test_overflow_never_returns_a_partial_impact(monkeypatch, field):
    monkeypatch.setattr(queries, "MAX_STOP_AUTHORITY_RECORDS", 1)
    with pytest.raises(queries.ProgrammeStopAuthorityUnavailableError):
        _projection(**{field: [{}, {}]})


def test_empty_identity_is_stable_but_bound_to_exact_scope():
    scope = {"organization_id": uuid4(), "edition_id": uuid4()}
    first = _projection(**scope)
    assert first == _projection(**scope)
    assert first != _projection(**{**scope, "edition_id": uuid4()})
    assert first != _projection(**{**scope, "organization_id": uuid4()})


def test_query_field_inventory_excludes_private_people_labels_and_reasons():
    forbidden = {
        "reason",
        "revocation_reason",
        "email",
        "display_name",
        "author_id",
        "approver_id",
        "recipient_id",
    }
    assert not forbidden.intersection(queries._REQUEST_FIELDS)
    assert not forbidden.intersection(queries._SOURCE_FIELDS)
    assert all(
        "__" not in field or field.startswith("decision__")
        for field in queries._REQUEST_FIELDS
    )


@pytest.mark.parametrize("value", [object(), NOW.replace(tzinfo=None)])
def test_source_serializer_rejects_unknown_or_naive_values(value):
    with pytest.raises(queries.ProgrammeStopAuthorityUnavailableError):
        queries._digest({"source": value})
