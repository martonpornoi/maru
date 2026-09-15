"""Complete independent item-task policy, exact owners and fail-closed absence."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.policy import PolicyDecision
from maru.events.queries import PrivatePlanningEditionReference
from maru.identity.queries import ActiveVerifiedAccountReference
from maru.programme import entry_references as refs


@pytest.fixture
def entry(monkeypatch):
    values = {
        name: UUID(int=index)
        for index, name in enumerate(
            ("actor_id", "organization_id", "edition_id"), start=1
        )
    }
    actor = Mock(return_value=ActiveVerifiedAccountReference(values["actor_id"]))
    edition = Mock(
        return_value=PrivatePlanningEditionReference(
            values["edition_id"],
            values["organization_id"],
            accepts_private_planning_writes=True,
        )
    )
    policy = Mock(
        return_value=PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset({"reason", "audit"}),
            reason_code="direct_grant",
        )
    )
    monkeypatch.setattr(refs, "resolve_active_verified_account_reference", actor)
    monkeypatch.setattr(refs, "resolve_private_planning_edition_reference", edition)
    monkeypatch.setattr(
        refs, "DEFAULT_PROGRAMME_AUTHORIZER", SimpleNamespace(authorize=policy)
    )
    return SimpleNamespace(values=values, actor=actor, edition=edition, policy=policy)


@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("writable", [False, True])
def test_complete_minimal_decision_and_owner_reference(entry, allowed, writable):
    if not allowed:
        entry.policy.return_value = replace(
            entry.policy.return_value,
            allowed=False,
            obligations=frozenset(),
            reason_code="permission_absent",
        )
    entry.edition.return_value = replace(
        entry.edition.return_value, accepts_private_planning_writes=writable
    )
    result = refs.resolve_programme_item_entry_reference(**entry.values)
    assert result == refs.ProgrammeItemEntryReference(
        **entry.values,
        accepts_private_planning_writes=writable,
        decision=entry.policy.return_value,
    )
    entry.policy.assert_called_once_with(
        principal_id=entry.values["actor_id"],
        organization_id=entry.values["organization_id"],
        edition_id=entry.values["edition_id"],
        capability_code=refs.PROGRAMME_MANAGE_ITEMS,
        requested_fields=frozenset(),
    )


@pytest.mark.parametrize("field", ["actor_id", "organization_id", "edition_id"])
@pytest.mark.parametrize("value", [None, "unknown", UUID(int=0)])
def test_invalid_identifiers_never_resolve_owners(entry, field, value):
    with pytest.raises(refs.ProgrammeAuthorizationDeniedError):
        refs.resolve_programme_item_entry_reference(**(entry.values | {field: value}))
    entry.actor.assert_not_called()
    entry.edition.assert_not_called()
    entry.policy.assert_not_called()


@pytest.mark.parametrize("source", ["actor", "edition"])
@pytest.mark.parametrize("malformed", [None, object()])
def test_missing_or_untyped_owner_is_not_permission_absence(entry, source, malformed):
    getattr(entry, source).return_value = malformed
    with pytest.raises(refs.ProgrammeAuthorizationDeniedError):
        refs.resolve_programme_item_entry_reference(**entry.values)
    entry.policy.assert_not_called()


@pytest.mark.parametrize(
    ("source", "changes"),
    [
        ("actor", {"account_id": UUID(int=90)}),
        ("edition", {"organization_id": UUID(int=90)}),
        ("edition", {"edition_id": UUID(int=90)}),
        ("edition", {"accepts_private_planning_writes": 1}),
    ],
)
def test_wrong_owner_or_lifecycle_shape_never_reaches_policy(entry, source, changes):
    mock = getattr(entry, source)
    mock.return_value = replace(mock.return_value, **changes)
    with pytest.raises(refs.ProgrammeAuthorizationDeniedError):
        refs.resolve_programme_item_entry_reference(**entry.values)
    entry.policy.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed": 1},
        {"fields": frozenset({"working"})},
        {"fields": set()},
        {"obligations": frozenset()},
        {"obligations": frozenset({"reason", "audit", "unexpected"})},
        {"obligations": {"reason", "audit"}},
        {"reason_code": []},
        {"reason_code": "unknown"},
        {"policy_version": "old"},
        {"allowed": False, "reason_code": "permission_absent"},
        {
            "allowed": False,
            "reason_code": "profile_excluded",
            "obligations": frozenset(),
        },
    ],
)
def test_malformed_or_nonordinary_policy_fails_closed(entry, changes):
    entry.policy.return_value = replace(entry.policy.return_value, **changes)
    with pytest.raises(refs.ProgrammeAuthorizationDeniedError):
        refs.resolve_programme_item_entry_reference(**entry.values)


def test_untyped_policy_is_not_absent_permission(entry):
    entry.policy.return_value = True
    with pytest.raises(refs.ProgrammeAuthorizationDeniedError):
        refs.resolve_programme_item_entry_reference(**entry.values)


@pytest.mark.parametrize("source", ["actor", "edition", "policy"])
def test_dependency_failure_is_not_empty_permission(entry, source):
    getattr(entry, source).side_effect = DatabaseError("Synthetic dependency failure")
    with pytest.raises(DatabaseError):
        refs.resolve_programme_item_entry_reference(**entry.values)


def test_no_public_substitute_authorizer_argument(entry):
    with pytest.raises(TypeError, match="authorizer"):
        refs.resolve_programme_item_entry_reference(
            **entry.values, authorizer=SimpleNamespace(authorize=Mock())
        )
    entry.policy.assert_not_called()
