"""Database-free preview admission, original-person recovery and minimized audit."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.authorization.services import AuthorizationDenied
from maru.workforce import programme_starter_creation as creation
from maru.workforce.programme_starter_inputs import ProgrammeStarterScope
from maru.workforce.programme_starter_selection import (
    ProgrammeStarterDraft,
    _sign_selection,
)


@pytest.fixture
def world(monkeypatch):
    actor, approver = SimpleNamespace(id=UUID(int=1)), SimpleNamespace(id=UUID(int=2))
    scope = ProgrammeStarterScope(UUID(int=3), UUID(int=4), UUID(int=5))
    draft = ProgrammeStarterDraft(
        "approver@example.invalid", "Synthetic staffing.", UUID(int=6)
    )
    mocks, audits, trace = {}, [], []
    targets = (object(), object())
    for name in (
        "_require_profile",
        "_require_actor",
        "_lock_scope",
        "_require_integrity",
        "_require_planning",
        "_require_controller",
        "lock_retired_department_authority_boundaries",
    ):
        mock = MagicMock(side_effect=lambda *_a, _name=name, **_kw: trace.append(_name))
        monkeypatch.setattr(creation, name, mock)
        mocks[name] = mock
    monkeypatch.setattr(creation.transaction, "atomic", nullcontext)
    monkeypatch.setattr(creation, "_resolve_scope", lambda _: targets)
    locks = MagicMock(
        side_effect=lambda ids: {
            person.id: person for person in (actor, approver) if person.id in ids
        }
    )
    monkeypatch.setattr(creation, "_lock_people", locks)
    lookup = MagicMock(return_value=SimpleNamespace(account_id=approver.id))
    monkeypatch.setattr(
        creation, "resolve_active_verified_person_reference_by_email", lookup
    )
    labels = MagicMock(return_value={approver.id: "Approver"})
    monkeypatch.setattr(
        creation, "active_verified_person_account_display_labels", labels
    )
    monkeypatch.setattr(
        creation,
        "page_access_scope_label",
        lambda target: "Organization" if target is targets[0] else "Edition",
    )
    monkeypatch.setattr(
        creation,
        "resolve_private_planning_edition_reference",
        lambda **_: SimpleNamespace(accepts_private_planning_writes=True),
    )
    monkeypatch.setattr(creation, "append_audit", audits.append)
    return SimpleNamespace(
        actor=actor,
        approver=approver,
        scope=scope,
        draft=draft,
        mocks=mocks,
        audits=audits,
        trace=trace,
        locks=locks,
        lookup=lookup,
        labels=labels,
    )


def prepare(world, **changes):
    return creation.prepare_programme_starter_creation(
        **(
            {
                "actor": world.actor,
                "scope": world.scope,
                "draft": world.draft,
                "correlation_id": uuid4(),
                "source_channel": "test",
            }
            | changes
        )
    )


def test_initial_page_reads_fixed_meaning_without_people_lookup(world):
    result = creation.load_programme_starter_creation(
        actor=world.actor, scope=world.scope, correlation_id=uuid4()
    )
    assert result.selection is None
    assert result.can_request
    world.lookup.assert_not_called()
    world.labels.assert_not_called()
    world.locks.assert_called_once_with({world.actor.id})
    assert world.audits[0].operation == "workforce.programme_starter.preview"


def test_fresh_preview_requires_real_named_approver_and_signs_original_id(world):
    result = prepare(world)
    assert result.selection.details.approver_id == world.approver.id
    assert result.approver_name == "Approver"
    world.lookup.assert_called_once_with(email=world.draft.approver_email)
    world.locks.assert_called_once_with({world.actor.id, world.approver.id})
    assert len(world.mocks["_require_controller"].call_args_list) == 3
    assert world.audits[0].principal_id == world.actor.id
    assert world.audits[0].retention_class == "security-extended"


def test_original_proof_never_reselects_changed_email_or_refreshes_planning(world):
    original = _sign_selection(
        world.actor.id, world.scope, world.draft, world.approver.id
    )
    world.lookup.side_effect = AssertionError("No second email lookup")
    result = prepare(world, proof=original.proof)
    assert result.selection == original
    world.lookup.assert_not_called()
    world.locks.assert_called_once_with({world.actor.id})
    world.mocks["_require_planning"].assert_not_called()


@pytest.mark.parametrize("fault", ["missing", "self", "authority", "label"])
def test_ineligible_fresh_approver_has_no_partial_name_or_signature(world, fault):
    if fault == "missing":
        world.lookup.return_value = None
    elif fault == "self":
        world.lookup.return_value.account_id = world.actor.id
    elif fault == "authority":
        world.mocks["_require_controller"].side_effect = [
            None,
            AuthorizationDenied("Unavailable", reason_code="test"),
            None,
        ]
    else:
        world.labels.return_value = {}
    result = prepare(world)
    assert result.selection is None
    assert result.approver_name == ""


def test_original_missing_person_has_neutral_label_without_reselection(world):
    original = _sign_selection(
        world.actor.id, world.scope, world.draft, world.approver.id
    )
    world.labels.return_value = {}
    result = prepare(world, proof=original.proof)
    assert result.selection == original
    assert result.approver_name == "Unavailable person"
    world.lookup.assert_not_called()


def test_invalid_proof_and_final_authority_loss_release_no_preview(world):
    with pytest.raises(ValidationError):
        prepare(world, proof="invalid")
    assert not world.audits
    world.mocks["_require_controller"].side_effect = [
        None,
        None,
        AuthorizationDenied("Unavailable", reason_code="test"),
    ]
    with pytest.raises(AuthorizationDenied):
        prepare(world)
    assert not world.audits
