"""Exact case-selection guard and compatibility of retained review retry shapes."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.applications import programme_review_commands as commands
from maru.applications.models import ProgrammeReviewAction
from maru.applications.programme_inputs import canonical_programme_digest
from maru.applications.programme_review_inputs import ProgrammeReviewCommandInput
from maru.applications.programme_review_rules import ProgrammeReviewConflictError


def intent(reference=None):
    return ProgrammeReviewCommandInput(
        ProgrammeReviewAction.CASE_OPENED,
        UUID(int=20),
        policy_id=UUID(int=30),
        reference_id=reference,
    )


def test_legacy_command_digest_shape_remains_unchanged_and_exact_seal_binds_intent():
    legacy = {
        "action": "case_opened",
        "target_id": UUID(int=20),
        "policy": None,
        "policy_id": UUID(int=30),
        "reference_id": None,
        "scores": (),
        "outcome": "",
        "text": "",
        "stage": None,
    }
    assert asdict(intent().normalized()) == legacy
    assert canonical_programme_digest(
        asdict(intent().normalized())
    ) == canonical_programme_digest(legacy)
    assert canonical_programme_digest(
        asdict(intent(UUID(int=40)).normalized())
    ) != canonical_programme_digest(legacy)
    assert canonical_programme_digest(
        asdict(intent(UUID(int=40)).normalized())
    ) != canonical_programme_digest(asdict(intent(UUID(int=41)).normalized()))


@pytest.mark.parametrize("reference", ["not-uuid", str(UUID(int=40)), 40])
def test_selected_seal_must_be_typed(reference):
    with pytest.raises(ValidationError):
        intent(reference).normalized()


def test_other_action_reference_requirements_are_not_weakened():
    with pytest.raises(ValidationError):
        replace(
            intent(), action=ProgrammeReviewAction.ACKNOWLEDGED, policy_id=None
        ).normalized()


@pytest.mark.parametrize("reference", [None, UUID(int=40), UUID(int=41)])
def test_canonical_locked_case_opening_rejects_changed_selected_seal(
    monkeypatch, reference
):
    proposal = SimpleNamespace(
        id=UUID(int=20), call_id=UUID(int=21), submitted_revision_id=UUID(int=40)
    )
    proposals, policies, cases = Mock(), Mock(), Mock()
    proposals.select_related.return_value.filter.return_value.first.return_value = (
        proposal
    )
    policy = SimpleNamespace(id=UUID(int=30))
    policies.filter.return_value.first.return_value = policy
    cases.filter.return_value.exists.return_value = False
    monkeypatch.setattr(commands.ProgrammeProposal, "objects", proposals)
    monkeypatch.setattr(commands.ProgrammeReviewPolicy, "objects", policies)
    monkeypatch.setattr(commands.ProgrammeReviewCase, "objects", cases)
    monkeypatch.setattr(commands, "is_proposal_contributor", Mock(return_value=False))
    scope = SimpleNamespace(
        actor_id=UUID(int=1),
        organization_id=UUID(int=2),
        edition_id=UUID(int=3),
        department_id=UUID(int=4),
    )
    if reference == UUID(int=41):
        with pytest.raises(ProgrammeReviewConflictError):
            commands._open_case(scope, intent(reference), 0)
        cases.create.assert_not_called()
    else:
        commands._open_case(scope, intent(reference), 0)
        cases.create.assert_called_once_with(
            proposal=proposal,
            revision_id=UUID(int=40),
            policy=policy,
            created_by_id=UUID(int=1),
        )
