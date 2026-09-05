"""Real PostgreSQL acceptance for exact-revision Programme review and decisions."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from maru.applications.models import (
    ProgrammeReviewAction,
    ProgrammeReviewCase,
    ProgrammeReviewReceipt,
)
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_review_authorization import (
    MANAGE_REVIEW,
    REVIEW,
    VIEW_DECISION_SELF,
)
from maru.applications.programme_review_inputs import ProgrammeReviewCommandInput
from maru.applications.programme_review_queries import (
    get_programme_review_detail,
    list_programme_review_cases,
    list_self_programme_decisions,
)
from maru.applications.programme_review_rules import accepted_review_is_effective
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
)
from tests.support.programme_review import assign_and_score, create_review_world

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


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
