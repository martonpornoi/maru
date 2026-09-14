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
from maru.applications.programme_decider_preview import (
    DecisionIntent,
    prepare_programme_decision_preview,
    verify_programme_decision_preview,
)
from maru.applications.programme_decider_queries import (
    get_programme_decision_work,
    list_programme_decision_cases,
    list_programme_decision_messages,
)
from maru.applications.programme_inputs import ProgrammeProposalInvitationInput
from maru.applications.programme_moderation_queries import (
    get_programme_moderation_case,
    get_programme_moderation_evidence,
    list_programme_moderation_cases,
)
from maru.applications.programme_review_authorization import (
    DECIDE,
    MANAGE_REVIEW,
    MODERATE,
    REVIEW,
    VIEW_DECISION_SELF,
)
from maru.applications.programme_review_commands import apply_programme_review_command
from maru.applications.programme_review_inputs import ProgrammeReviewCommandInput
from maru.applications.programme_review_intake_queries import (
    get_programme_review_intake_seal,
    list_programme_review_intake_seals,
)
from maru.applications.programme_review_management_queries import (
    get_programme_review_management,
    list_programme_review_management_cases,
)
from maru.applications.programme_review_queries import (
    get_programme_review_detail,
    get_self_programme_decision,
    list_programme_review_cases,
    list_self_programme_decisions,
)
from maru.applications.programme_review_rules import (
    ProgrammeReviewConflictError,
    accepted_review_is_effective,
)
from maru.applications.programme_review_setup_queries import (
    get_programme_review_setup,
    get_programme_review_setup_policy,
    list_programme_review_setup_calls,
)
from maru.applications.programme_reviewer_queries import (
    get_programme_reviewer_work,
    list_programme_reviewer_work,
)
from maru.applications.programme_reviewer_selection import (
    prepare_programme_reviewer_selection,
    read_programme_reviewer_selection,
)
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
    _start_proposal,
)
from tests.support.programme_review import assign_and_score, create_review_world
from tests.unit.test_application_programme_review_inputs import review_policy

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


def test_independent_decision_preview_waitlist_history_and_original_receipt():
    """Maintain native exact-message acceptance as unexecuted ADR 0100 debt."""
    world = create_review_world(with_collaborator=True)
    assign_and_score(world, world.reviewer.id)
    assign_and_score(world, world.peer.id)
    request = world.read(world.decider.id, DECIDE, fields=frozenset({"review_context"}))
    lookup = {"request": request, "authorizer": _AUTHORIZER}
    original = DecisionIntent(
        world.version,
        uuid4(),
        "waitlisted",
        "Exact recipient text.",
        "Private decider rationale.",
    )
    with pytest.raises(ProgrammeReviewConflictError):
        prepare_programme_decision_preview(
            **lookup, case_id=world.case_id, intent=original
        )
    world.command(
        world.moderator.id,
        ProgrammeReviewCommandInput(ProgrammeReviewAction.MODERATED, world.case_id),
    )
    original = replace(original, expected_version=world.version)
    assert [row.case_id for row in list_programme_decision_cases(**lookup).items] == [
        world.case_id
    ]
    for actor in (world.lead, world.collaborator, world.reviewer, world.moderator):
        excluded = lookup | {"request": replace(request, actor_id=actor.id)}
        assert not list_programme_decision_cases(**excluded).items
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            get_programme_decision_work(**excluded, case_id=world.case_id)
    preview = prepare_programme_decision_preview(
        **lookup, case_id=world.case_id, intent=original
    )
    assert world.version == original.expected_version
    assert preview.message == "Programme decision: waitlisted.\n\nExact recipient text."
    confirmed = verify_programme_decision_preview(
        request=request, case_id=world.case_id, intent=original, proof=preview.proof
    )
    common = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "department_id": request.department_id,
        "command": ProgrammeReviewCommandInput(
            ProgrammeReviewAction.DECIDED,
            world.case_id,
            outcome=confirmed.outcome,
            text=confirmed.text,
        ),
        "expected_version": confirmed.expected_version,
        "retry_key": confirmed.retry_key,
        "reason": confirmed.reason,
        "source_channel": "programme-decision-compose",
        "correlation_id": uuid4(),
        "authorizer": _AUTHORIZER,
    }
    receipt = apply_programme_review_command(**common)
    history = lookup | {
        "request": replace(request, requested_fields=frozenset({"review_evidence"})),
        "case_id": world.case_id,
    }
    stored = list_programme_decision_messages(**history).items
    assert len(stored) == 1
    assert stored[0].decision_id == receipt.target_id
    assert stored[0].message == preview.message
    assert original.reason not in stored[0].message
    with pytest.raises(ProgrammeReviewConflictError):
        prepare_programme_decision_preview(
            **lookup,
            case_id=world.case_id,
            intent=replace(original, expected_version=world.version),
        )
    successor = replace(
        original,
        expected_version=world.version,
        retry_key=uuid4(),
        outcome="accepted",
        text="Accepted after waitlisting.",
    )
    accepted = prepare_programme_decision_preview(
        **lookup, case_id=world.case_id, intent=successor
    )
    apply_programme_review_command(
        **(
            common
            | {
                "command": ProgrammeReviewCommandInput(
                    ProgrammeReviewAction.DECIDED,
                    world.case_id,
                    outcome=successor.outcome,
                    text=successor.text,
                ),
                "expected_version": successor.expected_version,
                "retry_key": successor.retry_key,
                "correlation_id": uuid4(),
            }
        )
    )
    page = list_programme_decision_messages(**history, limit=1)
    assert page.items[0].message == preview.message
    assert (
        list_programme_decision_messages(**history, after_version=page.next_version)
        .items[0]
        .message
        == accepted.message
    )
    replay = apply_programme_review_command(**(common | {"correlation_id": uuid4()}))
    assert replay.replayed
    assert replay.receipt_id == receipt.receipt_id
    assert (
        get_programme_decision_work(**lookup, case_id=world.case_id).case.state
        == "accepted"
    )


def test_moderation_discovery_readiness_reopening_and_original_receipt():
    """Maintain real owner moderation acceptance as unexecuted ADR 0100 debt."""
    policy = review_policy()
    first = policy.stages[0]
    world = create_review_world(
        policy=replace(policy, stages=(first, replace(first, code="technical"))),
        with_collaborator=True,
    )
    reviewer_assignment = assign_and_score(world, world.reviewer.id)
    assign_and_score(world, world.peer.id)
    request = world.read(
        world.moderator.id, MODERATE, fields=frozenset({"review_context"})
    )
    lookup = {"request": request, "authorizer": _AUTHORIZER}
    page = list_programme_moderation_cases(**lookup, limit=1)
    assert [row.case_id for row in page.items] == [world.case_id]
    assert not list_programme_moderation_cases(**lookup, after_id=world.case_id).items
    for actor in (world.lead, world.collaborator, world.reviewer, world.peer):
        excluded = lookup | {"request": replace(request, actor_id=actor.id)}
        assert not list_programme_moderation_cases(**excluded).items
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            get_programme_moderation_case(**excluded, case_id=world.case_id)
    for changes in (
        {"organization_id": uuid4()},
        {"edition_id": uuid4()},
        {"department_id": uuid4()},
        {"capability_code": MANAGE_REVIEW},
    ):
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            get_programme_moderation_case(
                **(lookup | {"request": replace(request, **changes)}),
                case_id=world.case_id,
            )
    protected = lookup | {
        "request": replace(request, requested_fields=frozenset({"review_evidence"})),
        "case_id": world.case_id,
    }
    evidence = get_programme_moderation_evidence(**protected)
    assert evidence.valid_scores == evidence.required_reviews == 2
    assert not evidence.ready
    moderate = ProgrammeReviewCommandInput(
        ProgrammeReviewAction.MODERATED, world.case_id
    )
    original_version, retry = world.version, uuid4()
    confirmed = world.command(
        world.moderator.id, moderate, expected_version=original_version, retry_key=retry
    )
    assert get_programme_moderation_evidence(**protected).ready
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.DISCUSSED,
            world.case_id,
            reference_id=reviewer_assignment,
            text="Later independent discussion.",
        ),
    )
    assert not get_programme_moderation_evidence(**protected).ready
    replay = world.command(
        world.moderator.id, moderate, expected_version=original_version, retry_key=retry
    )
    assert replay.replayed
    assert replay.receipt_id == confirmed.receipt_id
    world.command(world.moderator.id, moderate)
    world.command(
        world.moderator.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.STAGE_ADVANCED,
            world.case_id,
        ),
    )
    assert (
        get_programme_moderation_case(**lookup, case_id=world.case_id).case.stage == 1
    )
    world.command(
        world.moderator.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.STAGE_REOPENED,
            world.case_id,
            stage=0,
        ),
    )
    reopened = get_programme_moderation_evidence(**protected)
    assert reopened.valid_scores == 2
    assert not reopened.ready
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.moderator.id,
            ProgrammeReviewCommandInput(
                ProgrammeReviewAction.STAGE_ADVANCED,
                world.case_id,
            ),
        )
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.REVIEWER_RECUSED,
            world.case_id,
            reference_id=reviewer_assignment,
        ),
    )
    assert get_programme_moderation_evidence(**protected).valid_scores == 1
    assert not list_programme_moderation_cases(
        **(lookup | {"request": replace(request, actor_id=world.reviewer.id)})
    ).items


def test_own_reviewer_metadata_retains_original_rubric_after_progress_and_recusal():
    """Maintain native own scope/content/old-receipt debt without executing it."""
    policy = review_policy()
    first = policy.stages[0]
    later = replace(
        first,
        code="technical",
        criteria=(
            replace(first.criteria[0], code="delivery", label="Delivery quality"),
        ),
    )
    world = create_review_world(policy=replace(policy, stages=(first, later)))
    assignment = world.command(
        world.call.manager.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.REVIEWER_ASSIGNED,
            world.case_id,
            reference_id=world.reviewer.id,
        ),
    )
    request = world.read(
        world.reviewer.id, REVIEW, fields=frozenset({"review_context"})
    )
    common = {
        "request": request,
        "case_id": world.case_id,
        "assignment_id": assignment.target_id,
        "authorizer": _AUTHORIZER,
    }
    pending = get_programme_reviewer_work(**common)
    assert pending.state == "pending"
    assert not pending.has_scored
    assert list_programme_reviewer_work(
        request=request, authorizer=_AUTHORIZER
    ).items == (pending,)
    assert not list_programme_reviewer_work(
        request=request, after_id=assignment.target_id, authorizer=_AUTHORIZER
    ).items
    for changes in (
        {"actor_id": world.peer.id},
        {"organization_id": uuid4()},
        {"edition_id": uuid4()},
        {"department_id": uuid4()},
        {"capability_code": MANAGE_REVIEW},
    ):
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            get_programme_reviewer_work(
                **(common | {"request": replace(request, **changes)})
            )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        get_programme_review_detail(
            request=world.read(world.reviewer.id, REVIEW),
            case_id=world.case_id,
            authorizer=_AUTHORIZER,
        )
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.CONFLICT_CLEARED,
            world.case_id,
            reference_id=assignment.target_id,
        ),
    )
    original_version, retry = world.version, uuid4()
    score = ProgrammeReviewCommandInput(
        ProgrammeReviewAction.SCORED,
        world.case_id,
        reference_id=assignment.target_id,
        scores=tuple((row.code, row.maximum) for row in first.criteria),
    )
    scored = world.command(
        world.reviewer.id, score, expected_version=original_version, retry_key=retry
    )
    assert get_programme_reviewer_work(**common).has_scored
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.DISCUSSED,
            world.case_id,
            reference_id=assignment.target_id,
            text="Synthetic discussion after my score.",
        ),
    )
    assign_and_score(world, world.peer.id)
    detail = get_programme_review_detail(
        request=world.read(world.reviewer.id, REVIEW),
        case_id=world.case_id,
        authorizer=_AUTHORIZER,
    )
    assert str(world.peer.id) not in detail.evidence_json
    assert (
        len(
            [
                row
                for row in json.loads(detail.evidence_json)
                if row["action"] == "scored"
            ]
        )
        == 1
    )
    world.command(
        world.moderator.id,
        ProgrammeReviewCommandInput(ProgrammeReviewAction.MODERATED, world.case_id),
    )
    world.command(
        world.moderator.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.STAGE_ADVANCED, world.case_id
        ),
    )
    retained = get_programme_reviewer_work(**common)
    assert retained.case.stage == 1
    assert retained.rubric == pending.rubric
    assert retained.stage == 0
    replay = world.command(
        world.reviewer.id, score, expected_version=original_version, retry_key=retry
    )
    assert replay.replayed
    assert replay.receipt_id == scored.receipt_id
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.REVIEWER_RECUSED,
            world.case_id,
            reference_id=assignment.target_id,
        ),
    )
    assert get_programme_reviewer_work(**common).state == "recused"
    assert not list_programme_reviewer_work(
        request=request, authorizer=_AUTHORIZER
    ).items
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        get_programme_review_detail(
            request=world.read(world.reviewer.id, REVIEW),
            case_id=world.case_id,
            authorizer=_AUTHORIZER,
        )
    assert (
        world.command(
            world.reviewer.id, score, expected_version=original_version, retry_key=retry
        ).receipt_id
        == scored.receipt_id
    )


def test_named_manager_selection_preserves_person_after_email_change_and_late_removal():
    """Maintain native exact-person, complete roster and old-receipt acceptance debt."""
    world = create_review_world(with_collaborator=True)
    request = world.read(
        world.call.manager.id, MANAGE_REVIEW, fields=frozenset({"review_context"})
    )
    common = {"request": request, "case_id": world.case_id, "authorizer": _AUTHORIZER}
    for person in (world.call.manager, world.lead, world.collaborator):
        assert person is not None
        assert (
            prepare_programme_reviewer_selection(
                **common,
                email=person.email,
                expected_version=world.version,
                retry_key=uuid4(),
            )
            is None
        )
    original_version, retry = world.version, uuid4()
    selected = prepare_programme_reviewer_selection(
        **common,
        email=world.reviewer.email,
        expected_version=original_version,
        retry_key=retry,
    )
    assert selected is not None
    world.reviewer.email = "changed-reviewer@maru.invalid"
    world.reviewer.save(update_fields=("email",))
    retained = read_programme_reviewer_selection(
        **common,
        token=selected.token,
        expected_version=original_version,
        retry_key=retry,
    )
    assert retained.account_id == world.reviewer.id
    command = ProgrammeReviewCommandInput(
        ProgrammeReviewAction.REVIEWER_ASSIGNED,
        world.case_id,
        reference_id=retained.account_id,
    )
    assigned = world.command(
        world.call.manager.id,
        command,
        expected_version=original_version,
        retry_key=retry,
    )
    assert (
        list_programme_review_management_cases(
            request=request, authorizer=_AUTHORIZER, limit=1
        )
        .items[0]
        .case_id
        == world.case_id
    )
    context = get_programme_review_management(**common)
    assert [(row.account_id, row.state) for row in context.assignments] == [
        (world.reviewer.id, "pending")
    ]
    assert not hasattr(context, "answers")
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.CONFLICT_CLEARED,
            world.case_id,
            reference_id=assigned.target_id,
        ),
    )
    world.command(
        world.reviewer.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.SCORED,
            world.case_id,
            reference_id=assigned.target_id,
            scores=(("fit", 4),),
        ),
    )
    assign_and_score(world, world.peer.id)
    world.command(
        world.moderator.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.MODERATED,
            world.case_id,
        ),
    )
    world.command(
        world.decider.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.DECIDED,
            world.case_id,
            outcome="accepted",
            text="Synthetic accepted decision for late removal evidence.",
        ),
    )
    removal = world.command(
        world.call.manager.id,
        ProgrammeReviewCommandInput(
            ProgrammeReviewAction.REVIEWER_REMOVED,
            world.case_id,
            reference_id=assigned.target_id,
        ),
    )
    context = get_programme_review_management(**common)
    assert len(context.assignments) == 2
    assert (
        next(
            row for row in context.assignments if row.account_id == world.reviewer.id
        ).state
        == "removed"
    )
    world.reviewer.is_active = False
    world.reviewer.save(update_fields=("is_active",))
    retained = read_programme_reviewer_selection(
        **common,
        token=selected.token,
        expected_version=original_version,
        retry_key=retry,
    )
    assert retained.account_id == world.reviewer.id
    assert not retained.person_current
    assert retained.display_label == "Unavailable person"
    replay = world.command(
        world.call.manager.id,
        command,
        expected_version=original_version,
        retry_key=retry,
    )
    assert replay.replayed
    assert replay.receipt_id == assigned.receipt_id
    assert world.version == removal.version
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        get_programme_review_management(
            **(common | {"request": replace(request, department_id=uuid4())})
        )


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
