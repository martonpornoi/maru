"""Real owner query boundaries retain exact self filters and independent policies."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db import DatabaseError
from django.db.models import Q

from maru.identity.queries import ActiveVerifiedPersonReference
from maru.programme import personal_scope_references as hosting
from maru.workforce import personal_scope_references as work
from tests.unit.test_personal_timetable_discovery import decision


@pytest.fixture(params=["hosting", "work"])
def owner(request, monkeypatch):
    actor, organization, edition = (UUID(int=value) for value in range(1, 4))
    module = hosting if request.param == "hosting" else work
    model = (
        module.ProgrammeHostRelationship
        if module is hosting
        else module.ShiftCommitment
    )
    fields = (
        {"own_host_relationship", "own_host_invitation"}
        if module is hosting
        else {"shifts"}
    )
    policy = (
        Mock(
            return_value=SimpleNamespace(
                actor_id=actor,
                organization_id=organization,
                edition_id=edition,
                decision=decision(fields),
            )
        )
        if module is hosting
        else Mock(return_value=decision(fields))
    )
    monkeypatch.setattr(
        module,
        "authorize_programme_scope" if module is hosting else "_authorize",
        policy,
    )
    person = Mock(return_value=ActiveVerifiedPersonReference(actor))
    monkeypatch.setattr(module, "resolve_active_verified_person_reference", person)
    monkeypatch.setattr(module.transaction, "atomic", nullcontext)
    lock = Mock(return_value=True)
    monkeypatch.setattr(module, "lock_edition_ownership", lock)
    query = MagicMock()
    manager = Mock(return_value=query)
    monkeypatch.setattr(model.objects, "filter", manager)
    for name in ("order_by", "values_list", "distinct"):
        getattr(query, name).return_value = query
    query.__getitem__.return_value = ((organization, edition),)
    query.exclude.return_value.exists.return_value = False
    query.exists.return_value = True
    adoption = Mock(
        return_value=Q(
            edition__adoption_profile_code="synthetic",
            edition__adoption_profile_version=1,
        )
    )
    monkeypatch.setattr(
        module,
        "adoption_profile_filter_for_capabilities"
        if module is hosting
        else "adoption_profile_filter_for_adapter",
        adoption,
    )
    return SimpleNamespace(
        module=module,
        actor=actor,
        organization=organization,
        edition=edition,
        policy=policy,
        person=person,
        lock=lock,
        query=query,
        manager=manager,
        adoption=adoption,
    )


def candidates(owner):
    function = (
        owner.module.personal_host_scope_candidates
        if owner.module is hosting
        else owner.module.personal_shift_scope_candidates
    )
    return function(actor_id=owner.actor)


def proof(owner):
    function = (
        owner.module.personal_host_scope_proof
        if owner.module is hosting
        else owner.module.personal_shift_scope_proof
    )
    return function(
        actor_id=owner.actor,
        organization_id=owner.organization,
        edition_id=owner.edition,
    )


def unavailable(owner):
    return (
        hosting.ProgrammeQueryUnavailableError
        if owner.module is hosting
        else work.ShiftUnavailableError
    )


def denied(owner):
    return (
        hosting.ProgrammeAuthorizationDeniedError
        if owner.module is hosting
        else work.ShiftAuthorizationDeniedError
    )


def test_candidates_select_only_own_profile_filtered_opaque_pairs(owner):
    result = candidates(owner)
    assert result.actor_id == owner.actor
    assert result.scopes == ((owner.organization, owner.edition),)
    owner.manager.assert_called_once_with(
        owner.adoption.return_value, account_id=owner.actor
    )
    owner.query.values_list.assert_called_once_with("organization_id", "edition_id")
    owner.query.__getitem__.assert_called_once_with(slice(None, 257))
    assert owner.adoption.call_args.kwargs == {"field_prefix": "edition"}
    owner.policy.assert_not_called()
    owner.lock.assert_not_called()
    assert owner.person.call_count == 2


def test_owner_overflow_is_not_truncated(owner):
    owner.query.__getitem__.return_value = tuple(
        (owner.organization, UUID(int=value)) for value in range(100, 357)
    )
    with pytest.raises(unavailable(owner)):
        candidates(owner)


def test_current_proof_uses_exact_self_and_parent_coherence(owner):
    result = proof(owner)
    assert result.present is True
    owner.manager.assert_called_once_with(
        account_id=owner.actor,
        organization_id=owner.organization,
        edition_id=owner.edition,
    )
    owner.lock.assert_called_once_with(
        organization_id=owner.organization, edition_id=owner.edition
    )
    assert any(call.kwargs.get("lock") is True for call in owner.person.call_args_list)
    assert owner.policy.call_count == 2
    expected = (
        {"item__organization_id": owner.organization, "item__edition_id": owner.edition}
        if owner.module is hosting
        else {
            "demand__organization_id": owner.organization,
            "demand__edition_id": owner.edition,
            "demand__position__organization_id": owner.organization,
            "demand__position__edition_id": owner.edition,
            "demand__position__department__organization_id": owner.organization,
            "demand__position__department__edition_id": owner.edition,
        }
    )
    owner.query.exclude.assert_called_once_with(**expected)


@pytest.mark.parametrize(
    "defect", ["denied", "person", "parent", "corruption", "database"]
)
def test_real_owner_boundary_fails_closed(owner, defect):
    if defect == "denied":
        owner.policy.side_effect = denied(owner)
    elif defect == "person":
        owner.person.return_value = None
    elif defect == "parent":
        owner.lock.return_value = False
    elif defect == "corruption":
        owner.query.exclude.return_value.exists.return_value = True
    else:
        owner.manager.side_effect = DatabaseError("database unavailable")
    with pytest.raises((denied(owner), unavailable(owner))):
        proof(owner)
    if defect in {"denied", "person"}:
        owner.lock.assert_not_called()
        owner.manager.assert_not_called()
