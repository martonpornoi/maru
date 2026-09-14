"""Real PostgreSQL acceptance for exact-revision Programme review and decisions."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from maru.applications.models import (
    ProgrammeReviewAction,
    ProgrammeReviewCase,
    ProgrammeReviewReceipt,
)
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
from maru.applications.programme_review_authorization import (
    MANAGE_REVIEW,
    REVIEW,
    VIEW_DECISION_SELF,
)
from maru.applications.programme_review_inputs import ProgrammeReviewCommandInput
from maru.applications.programme_review_intake_queries import (
    get_programme_review_intake_seal,
    list_programme_review_intake_seals,
)
from maru.applications.programme_review_queries import (
    get_programme_review_detail,
    get_self_programme_decision,
    list_programme_review_cases,
    list_self_programme_decisions,
)
from maru.applications.programme_review_rules import accepted_review_is_effective
from maru.applications.programme_review_setup_queries import (
    get_programme_review_setup,
    get_programme_review_setup_policy,
    list_programme_review_setup_calls,
)
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
    _start_proposal,
)
from tests.support.programme_review import assign_and_score, create_review_world

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


def test_review_manager_setup_is_scoped_audited_and_separate_from_case_content():
    """Maintain native setup discovery acceptance while ADR 0100 defers execution."""
    world = create_review_world()
    request = world.read(
        world.call.manager.id,
        MANAGE_REVIEW,
        fields=frozenset({"review_setup"}),
    )
    page = list_programme_review_setup_calls(request=request, authorizer=_AUTHORIZER)
    assert [item.call_id for item in page.items] == [world.call.call_id]
    context = get_programme_review_setup(
        request=request,
        call_id=world.call.call_id,
        authorizer=_AUTHORIZER,
    )
    assert context.policy_version == 1
    assert context.questions
    assert not hasattr(context, "answers")
    policy = get_programme_review_setup_policy(
        request=request,
        call_id=world.call.call_id,
        version=1,
        authorizer=_AUTHORIZER,
    )
    assert policy.policy_id == world.policy_id
    assert policy.reason == "Pin explicit synthetic review policy."
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        get_programme_review_detail(
            request=request,
            case_id=world.case_id,
            authorizer=_AUTHORIZER,
        )


def test_complete_independent_review_decision_and_recipient_acknowledgement() -> None:
    """Retain real reviews, audit, event, outbox, message, and exact self receipt."""
    world = create_review_world()
    first = assign_and_score(world, world.reviewer.id)
    assign_and_score(world, world.peer.id, score=3)
    detail = get_programme_review_detail(
        request=world.read(world.reviewer.id, REVIEW),
        case_id=world.case_id,
        authorizer=_AUTHORIZER,
    )
    assert json.loads(detail.answers_json)[0]["value"] == "A sealed session description"
    assert "contributors" not in json.loads(detail.context_json)
    evidence = json.loads(detail.evidence_json)
    assert len([item for item in evidence if item["action"] == "scored"]) == 1
    assert str(world.peer.id) not in detail.evidence_json
    world.command(
        world.moderator.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.MODERATED, target_id=world.case_id
        ),
    )
    decision = world.command(
        world.decider.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.DECIDED,
            target_id=world.case_id,
            outcome="accepted",
            text="Your session is accepted for the next planning step.",
        ),
    )
    case = ProgrammeReviewCase.objects.select_related("proposal", "policy").get(
        id=world.case_id
    )
    assert accepted_review_is_effective(case)
    request = world.read(
        world.lead.id,
        VIEW_DECISION_SELF,
        fields=frozenset({"decision_message", "own_acknowledgement"}),
        self_access=True,
    )
    messages = list_self_programme_decisions(request=request, authorizer=_AUTHORIZER)
    assert len(messages.items) == 1
    assert messages.items[0].decision_id == decision.target_id
    assert messages.items[0].own_acknowledged is False
    assert (
        get_self_programme_decision(
            request=request, decision_id=decision.target_id, authorizer=_AUTHORIZER
        )
        == messages.items[0]
    )
    assert "accountable review action" not in messages.items[0].message
    world.command(
        world.lead.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.ACKNOWLEDGED,
            target_id=world.case_id,
            reference_id=decision.target_id,
        ),
        self_access=True,
    )
    assert (
        list_self_programme_decisions(request=request, authorizer=_AUTHORIZER)
        .items[0]
        .own_acknowledged
        is True
    )
    acknowledgement = list_self_programme_decisions(
        request=replace(request, requested_fields=frozenset({"own_acknowledgement"})),
        authorizer=_AUTHORIZER,
    ).items[0]
    assert acknowledgement.message is None
    assert acknowledgement.outcome is None
    assert acknowledgement.own_acknowledged_at is not None
    assert (
        get_self_programme_decision(
            request=replace(
                request, requested_fields=frozenset({"own_acknowledgement"})
            ),
            decision_id=decision.target_id,
            authorizer=_AUTHORIZER,
        )
        == acknowledgement
    )
    for receipt in ProgrammeReviewReceipt.objects.filter(
        case_id=world.case_id
    ).select_related("audit_event", "domain_event"):
        assert receipt.audit_event.principal_id == receipt.actor_id
        assert receipt.domain_event.causation_id == receipt.audit_event_id
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.REVIEWER_RECUSED,
            target_id=world.case_id,
            reference_id=first,
        ),
    )
    case.refresh_from_db()
    assert not accepted_review_is_effective(case)


def test_pending_assignment_and_management_never_imply_content_authority() -> None:
    """Allow a content-free conflict queue but deny before self clearance."""
    world = create_review_world()
    assigned = world.command(
        world.call.manager.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.REVIEWER_ASSIGNED,
            target_id=world.case_id,
            reference_id=world.reviewer.id,
        ),
    )
    queue = list_programme_review_cases(
        request=world.read(
            world.reviewer.id, REVIEW, fields=frozenset({"review_context"})
        ),
        authorizer=_AUTHORIZER,
    )
    assert queue.items[0].own_assignment_id == assigned.target_id
    assert queue.items[0].own_assignment_state == "pending"
    for actor, capability in (
        (world.reviewer.id, REVIEW),
        (world.peer.id, REVIEW),
        (world.call.manager.id, MANAGE_REVIEW),
    ):
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            get_programme_review_detail(
                request=world.read(actor, capability),
                case_id=world.case_id,
                authorizer=_AUTHORIZER,
            )
