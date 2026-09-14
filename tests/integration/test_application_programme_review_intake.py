"""Maintained native case-intake acceptance; execution deferred under ADR 0100."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from maru.applications.models import ProgrammeReviewAction
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_commands import (
    append_programme_proposal_answer,
    decline_programme_proposal_invitation,
    invite_programme_proposal_collaborator,
    seal_programme_proposal,
    submit_programme_proposal,
    withdraw_programme_proposal,
)
from maru.applications.programme_inputs import ProgrammeProposalInvitationInput
from maru.applications.programme_review_authorization import MANAGE_REVIEW
from maru.applications.programme_review_inputs import ProgrammeReviewCommandInput
from maru.applications.programme_review_intake_queries import (
    get_programme_review_intake_seal,
    list_programme_review_intake_seals,
)
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
    _start_proposal,
)
from tests.support.programme_review import create_review_world

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


def test_case_intake_filters_conflicts_and_retains_original_opening_replay():
    """Exercise native pagination, retained collaboration, exact creation and replay."""
    world = create_review_world()
    proposal = _start_proposal(world.call, lead=world.peer)
    common = {
        "actor_id": world.peer.id,
        "organization_id": world.call.edition.organization_id,
        "edition_id": world.call.edition.id,
        "proposal_id": proposal.proposal_id,
        "reason": "Synthetic exact review intake source.",
        "source_channel": "test",
        "now": world.call.now,
        "authorizer": _AUTHORIZER,
    }
    invited = invite_programme_proposal_collaborator(
        **common,
        invitation=ProgrammeProposalInvitationInput(
            invitee_email=world.reviewer.email,
            expires_at=world.call.now + timedelta(days=1),
        ),
        expected_version=proposal.version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    declined = decline_programme_proposal_invitation(
        **(common | {"actor_id": world.reviewer.id}),
        expected_version=invited.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    answered = append_programme_proposal_answer(
        **common,
        question_id=world.call.question_id,
        value="Synthetic intake evidence, never a chooser title.",
        expected_version=declined.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    sealed = seal_programme_proposal(
        **common,
        expected_version=answered.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    submitted = submit_programme_proposal(
        **common,
        revision_id=sealed.target_id,
        expected_version=sealed.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    request = world.read(
        world.call.manager.id, MANAGE_REVIEW, fields=frozenset({"review_setup"})
    )
    lookup = {
        "request": request,
        "call_id": world.call.call_id,
        "authorizer": _AUTHORIZER,
    }
    page = list_programme_review_intake_seals(**lookup, limit=1)
    assert [item.revision_id for item in page.items] == [sealed.target_id]
    assert page.next_cursor is None
    assert not list_programme_review_intake_seals(
        **lookup, after_id=sealed.target_id
    ).items
    for actor in (world.peer, world.reviewer):
        assert not list_programme_review_intake_seals(
            **(lookup | {"request": replace(request, actor_id=actor.id)})
        ).items
    selected = get_programme_review_intake_seal(**lookup, revision_id=sealed.target_id)
    assert selected.eligible
    assert not hasattr(selected, "answers")
    retry_key = uuid4()
    command = ProgrammeReviewCommandInput(
        ProgrammeReviewAction.CASE_OPENED,
        proposal.proposal_id,
        policy_id=world.policy_id,
        reference_id=sealed.target_id,
    )
    opened = world.command(
        world.call.manager.id, command, expected_version=0, retry_key=retry_key
    )
    assert not list_programme_review_intake_seals(**lookup).items
    selected = get_programme_review_intake_seal(**lookup, revision_id=sealed.target_id)
    assert selected.opened
    assert not selected.eligible
    withdraw_programme_proposal(
        **common,
        expected_version=submitted.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    retained = get_programme_review_intake_seal(**lookup, revision_id=sealed.target_id)
    assert retained.seal == selected.seal
    replay = world.command(
        world.call.manager.id, command, expected_version=0, retry_key=retry_key
    )
    assert replay.receipt_id == opened.receipt_id
    assert replay.replayed
    for wrong in (
        {"call_id": uuid4()},
        {"request": replace(request, requested_fields=frozenset({"review_context"}))},
        {"request": replace(request, edition_id=uuid4())},
        {"request": replace(request, organization_id=uuid4())},
        {"request": replace(request, department_id=uuid4())},
    ):
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            get_programme_review_intake_seal(
                **(lookup | wrong), revision_id=sealed.target_id
            )
