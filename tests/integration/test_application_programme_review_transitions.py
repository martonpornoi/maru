"""Adversarial role, stage, revision, and decision transitions on PostgreSQL."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.applications.models import (
    ProgrammeCommandReceipt,
    ProgrammeProposal,
    ProgrammeProposalCollaborator,
    ProgrammeReviewAssignment,
    ProgrammeReviewCase,
    ProgrammeReviewDecision,
    ProgrammeReviewPolicy,
    ProgrammeReviewReceipt,
)
from maru.applications.models import ProgrammeReviewAction as Action
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeIdempotencyConflictError,
    remove_programme_proposal_collaborator,
    reopen_programme_proposal,
    retire_programme_call,
    seal_programme_proposal,
    submit_programme_proposal,
    withdraw_programme_proposal,
)
from maru.applications.programme_review_authorization import REVIEW, VIEW_DECISION_SELF
from maru.applications.programme_review_commands import apply_programme_review_command
from maru.applications.programme_review_inputs import (
    ProgrammeReviewCommandInput as Intent,
)
from maru.applications.programme_review_queries import (
    list_programme_review_cases,
    list_self_programme_decisions,
)
from maru.applications.programme_review_rules import (
    ProgrammeReviewConflictError,
    accepted_review_is_effective,
)
from maru.workforce.structure_commands import retire_department
from tests.factories import AccountFactory
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _admit_future_programme_effects,
)
from tests.support.programme_review import assign_and_score, create_review_world
from tests.unit.test_application_programme_review_inputs import review_policy

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(_admit_future_programme_effects.__name__),
]


def _moderate(world):
    return world.command(world.moderator.id, Intent(Action.MODERATED, world.case_id))


def _ready(world):
    first = assign_and_score(world, world.reviewer.id)
    second = assign_and_score(world, world.peer.id)
    _moderate(world)
    return first, second


def _decide(world, outcome="accepted"):
    return world.command(
        world.decider.id,
        Intent(
            Action.DECIDED,
            world.case_id,
            outcome=outcome,
            text="A deliberate recipient-visible decision.",
        ),
    )


@pytest.mark.parametrize("role", ["lead", "opener", "moderator", "decider"])
def test_review_assignment_excludes_contributors_and_prior_approval_roles(role):
    world = create_review_world()
    if role in {"moderator", "decider"}:
        _ready(world)
    if role == "decider":
        _decide(world, "waitlisted")
        world.command(
            world.moderator.id, Intent(Action.STAGE_REOPENED, world.case_id, stage=0)
        )
    actor = world.call.manager if role == "opener" else getattr(world, role)
    before = world.version
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.call.manager.id,
            Intent(Action.REVIEWER_ASSIGNED, world.case_id, reference_id=actor.id),
        )
    assert world.version == before


@pytest.mark.parametrize(
    "action",
    [Action.CONFLICT_CLEARED, Action.REVIEWER_RECUSED, Action.SCORED, Action.DISCUSSED],
)
def test_reviewers_cannot_impersonate_another_assignment(action):
    world = create_review_world()
    assigned = assign_and_score(world, world.reviewer.id)
    extra = (
        {"scores": (("fit", 4),)}
        if action == Action.SCORED
        else {"text": "Peer note"}
        if action == Action.DISCUSSED
        else {}
    )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        world.command(
            world.peer.id, Intent(action, world.case_id, reference_id=assigned, **extra)
        )


@pytest.mark.parametrize("role", ["lead", "reviewer", "moderator"])
def test_final_decision_requires_a_distinct_independent_actor(role):
    world = create_review_world()
    _ready(world)
    before = world.version
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            getattr(world, role).id,
            Intent(
                Action.DECIDED,
                world.case_id,
                outcome="accepted",
                text="Not an independent decision.",
            ),
        )
    assert world.version == before


def test_repeated_scores_never_replace_required_independent_reviewers():
    world = create_review_world()
    assignment = assign_and_score(world, world.reviewer.id)
    world.command(
        world.reviewer.id,
        Intent(
            Action.SCORED, world.case_id, reference_id=assignment, scores=(("fit", 5),)
        ),
    )
    _moderate(world)
    with pytest.raises(ProgrammeReviewConflictError):
        _decide(world)
    assign_and_score(world, world.peer.id)
    with pytest.raises(ProgrammeReviewConflictError):
        _decide(world)
    _moderate(world)
    _decide(world)


def test_discussion_invalidates_moderation_until_independently_reviewed_again():
    world = create_review_world()
    assignment, _ = _ready(world)
    world.command(
        world.reviewer.id,
        Intent(
            Action.DISCUSSED,
            world.case_id,
            reference_id=assignment,
            text="Please consider this additional scheduling constraint.",
        ),
    )
    with pytest.raises(ProgrammeReviewConflictError):
        _decide(world)
    _moderate(world)
    _decide(world)


@pytest.mark.parametrize("action", [Action.SCORED, Action.DISCUSSED])
def test_content_work_requires_a_live_self_cleared_assignment(action):
    world = create_review_world()
    assignment = world.command(
        world.call.manager.id,
        Intent(Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id),
    )
    extra = (
        {"scores": (("fit", 4),)}
        if action == Action.SCORED
        else {"text": "Not cleared."}
    )
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.reviewer.id,
            Intent(action, world.case_id, reference_id=assignment.target_id, **extra),
        )


@pytest.mark.parametrize("action", [Action.REVIEWER_RECUSED, Action.REVIEWER_REMOVED])
def test_removed_or_recused_assignments_never_reactivate(action):
    world = create_review_world()
    assignment = assign_and_score(world, world.reviewer.id)
    actor = world.reviewer if action == Action.REVIEWER_RECUSED else world.call.manager
    world.command(actor.id, Intent(action, world.case_id, reference_id=assignment))
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        world.command(
            world.reviewer.id,
            Intent(Action.CONFLICT_CLEARED, world.case_id, reference_id=assignment),
        )
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.call.manager.id,
            Intent(
                Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id
            ),
        )
    assert ProgrammeReviewAssignment.objects.get(id=assignment).state in {
        "recused",
        "removed",
    }


def test_two_stages_require_all_evidence_and_explicit_reopening():
    policy = review_policy()
    policy = replace(
        policy, stages=(policy.stages[0], replace(policy.stages[0], code="delivery"))
    )
    world = create_review_world(policy=policy)
    _ready(world)
    with pytest.raises(ProgrammeReviewConflictError):
        _decide(world)
    world.command(world.moderator.id, Intent(Action.STAGE_ADVANCED, world.case_id))
    queue = list_programme_review_cases(
        request=world.read(
            world.reviewer.id, REVIEW, fields=frozenset({"review_context"})
        ),
        authorizer=_AUTHORIZER,
    )
    assert queue.items[0].own_assignment_id is None
    assert queue.items[0].own_assignments[0][1:] == (0, "active")
    _ready(world)
    world.command(
        world.moderator.id, Intent(Action.STAGE_REOPENED, world.case_id, stage=0)
    )
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(world.moderator.id, Intent(Action.STAGE_ADVANCED, world.case_id))
    _moderate(world)
    world.command(world.moderator.id, Intent(Action.STAGE_ADVANCED, world.case_id))
    with pytest.raises(ProgrammeReviewConflictError):
        _decide(world)
    _moderate(world)
    _decide(world)
    assert ProgrammeReviewCase.objects.get(id=world.case_id).state == "accepted"


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "revision_requested"])
def test_waitlist_has_one_explicit_final_successor_with_retained_messages(outcome):
    world = create_review_world()
    _ready(world)
    _decide(world, "waitlisted")
    with pytest.raises(ProgrammeReviewConflictError):
        _decide(world, "waitlisted")
    _decide(world, outcome)
    with pytest.raises(ProgrammeReviewConflictError):
        _decide(world, "accepted")
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.moderator.id, Intent(Action.STAGE_REOPENED, world.case_id, stage=0)
        )
    request = world.read(
        world.lead.id,
        VIEW_DECISION_SELF,
        fields=frozenset({"decision_message"}),
        self_access=True,
    )
    history = list_self_programme_decisions(request=request, authorizer=_AUTHORIZER)
    assert [row.outcome for row in history.items] == ["waitlisted", outcome]
    assert history.items[0].decision_version < history.items[1].decision_version
    first = list_self_programme_decisions(
        request=request, limit=1, authorizer=_AUTHORIZER
    )
    second = list_self_programme_decisions(
        request=request, after_id=first.next_cursor, limit=1, authorizer=_AUTHORIZER
    )
    assert first.items + second.items == history.items
    assert second.next_cursor is None
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        list_self_programme_decisions(
            request=request, after_id=uuid4(), authorizer=_AUTHORIZER
        )
    # Requesting revision is not authority to impersonate the proposal lead.
    assert ProgrammeProposal.objects.get(id=world.proposal_id).state == "submitted"


def test_withdrawal_invalidates_acceptance_but_keeps_exact_recipient_history():
    world = create_review_world()
    _ready(world)
    decision = _decide(world)
    proposal = ProgrammeProposal.objects.select_related("submission").get(
        id=world.proposal_id
    )
    withdraw_programme_proposal(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=proposal.submission.aggregate_version,
        reason="Withdraw this synthetic proposal.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    case = ProgrammeReviewCase.objects.select_related("proposal", "policy").get(
        id=world.case_id
    )
    assert not accepted_review_is_effective(case)
    request = world.read(
        world.lead.id,
        VIEW_DECISION_SELF,
        fields=frozenset({"decision_message", "own_acknowledgement"}),
        self_access=True,
    )
    assert (
        list_self_programme_decisions(request=request, authorizer=_AUTHORIZER)
        .items[0]
        .decision_id
        == decision.target_id
    )
    world.command(
        world.lead.id,
        Intent(Action.ACKNOWLEDGED, world.case_id, reference_id=decision.target_id),
        self_access=True,
    )


def test_exact_retry_replays_without_reacquiring_write_scope(monkeypatch):
    world = create_review_world()
    key = uuid4()
    intent = Intent(
        Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id
    )
    version = world.version
    result = world.command(
        world.call.manager.id, intent, expected_version=version, retry_key=key
    )

    def unexpected(**_kwargs):
        raise AssertionError("Replay attempted a new write lock")

    monkeypatch.setattr(
        "maru.applications.programme_review_commands.lock_programme_edition_write_scope",
        unexpected,
    )
    replay = world.command(
        world.call.manager.id, intent, expected_version=version, retry_key=key
    )
    assert replay == replace(result, replayed=True)
    with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
        world.command(
            world.call.manager.id,
            replace(intent, reference_id=world.peer.id),
            expected_version=version,
            retry_key=key,
        )


def test_stale_review_version_cannot_append_any_success_evidence():
    world = create_review_world()
    before = ProgrammeReviewReceipt.objects.count()
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.call.manager.id,
            Intent(
                Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id
            ),
            expected_version=0,
        )
    assert ProgrammeReviewReceipt.objects.count() == before


def test_current_profiles_still_deny_real_programme_review_admission():
    world = create_review_world()
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        apply_programme_review_command(
            actor_id=world.call.manager.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            department_id=world.call.department_id,
            command=Intent(
                Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id
            ),
            expected_version=world.version,
            retry_key=uuid4(),
            reason="Cannot activate a dormant profile.",
            correlation_id=uuid4(),
            source_channel="test",
        )


@pytest.mark.parametrize(
    "scores", [(("missing", 4),), (("fit", 6),), (("fit", 1), ("extra", 2))]
)
def test_scores_must_match_every_exact_rubric_bound(scores):
    world = create_review_world()
    assignment = assign_and_score(world, world.reviewer.id)
    with pytest.raises((ProgrammeReviewConflictError, ValidationError)):
        world.command(
            world.reviewer.id,
            Intent(
                Action.SCORED, world.case_id, reference_id=assignment, scores=scores
            ),
        )


def test_exact_included_collaborator_keeps_own_message_after_later_removal():
    world = create_review_world(with_collaborator=True)
    collaborator = world.collaborator
    assert collaborator is not None
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.call.manager.id,
            Intent(
                Action.REVIEWER_ASSIGNED, world.case_id, reference_id=collaborator.id
            ),
        )
    _ready(world)
    decision = _decide(world)
    fields = frozenset({"decision_message", "own_acknowledgement"})
    lead_request = world.read(
        world.lead.id, VIEW_DECISION_SELF, fields=fields, self_access=True
    )
    collaborator_request = world.read(
        collaborator.id, VIEW_DECISION_SELF, fields=fields, self_access=True
    )
    assert (
        list_self_programme_decisions(
            request=collaborator_request, authorizer=_AUTHORIZER
        )
        .items[0]
        .decision_id
        == decision.target_id
    )
    proposal = ProgrammeProposal.objects.select_related("submission").get(
        id=world.proposal_id
    )
    common = {
        "actor_id": world.lead.id,
        "organization_id": world.call.edition.organization_id,
        "edition_id": world.call.edition.id,
        "proposal_id": world.proposal_id,
        "reason": "Start a genuinely different contributor revision.",
        "source_channel": "test",
        "authorizer": _AUTHORIZER,
    }
    reopened = reopen_programme_proposal(
        **common,
        expected_version=proposal.submission.aggregate_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    remove_programme_proposal_collaborator(
        **common,
        collaborator_id=ProgrammeProposalCollaborator.objects.get(
            proposal_id=world.proposal_id, account_id=collaborator.id
        ).id,
        expected_version=reopened.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    world.command(
        collaborator.id,
        Intent(Action.ACKNOWLEDGED, world.case_id, reference_id=decision.target_id),
        self_access=True,
    )
    assert (
        list_self_programme_decisions(
            request=collaborator_request, authorizer=_AUTHORIZER
        )
        .items[0]
        .own_acknowledged
        is True
    )
    assert (
        list_self_programme_decisions(request=lead_request, authorizer=_AUTHORIZER)
        .items[0]
        .own_acknowledged
        is False
    )


def test_retired_department_revokes_staff_review_but_not_addressed_history():
    world = create_review_world()
    _ready(world)
    decision = _decide(world)
    retire_programme_call(
        actor_id=world.call.manager.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        call_id=world.call.call_id,
        owner_department_id=world.call.department_id,
        expected_version=2,
        reason="Finish the dormant call before Department retirement.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    retire_department(
        actor=AccountFactory(is_staff=True, is_superuser=True),
        organization_id=world.call.edition.organization_id,
        series_id=world.call.edition.series_id,
        edition_id=world.call.edition.id,
        department_id=world.call.department_id,
        expected_version=1,
        reason="Retire the resolved synthetic Programme Department.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        world.command(world.moderator.id, Intent(Action.MODERATED, world.case_id))
    world.command(
        world.lead.id,
        Intent(Action.ACKNOWLEDGED, world.case_id, reference_id=decision.target_id),
        self_access=True,
    )
    request = world.read(
        world.lead.id,
        VIEW_DECISION_SELF,
        fields=frozenset({"decision_message", "own_acknowledgement"}),
        self_access=True,
    )
    assert (
        list_self_programme_decisions(request=request, authorizer=_AUTHORIZER)
        .items[0]
        .own_acknowledged
        is True
    )


def test_programme_and_review_retry_namespaces_conflict_in_both_directions():
    world = create_review_world()

    existing = ProgrammeCommandReceipt.objects.filter(
        actor_id=world.call.manager.id, edition_id=world.call.edition.id
    ).first()
    with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
        world.command(
            world.call.manager.id,
            Intent(
                Action.REVIEWER_ASSIGNED, world.case_id, reference_id=world.reviewer.id
            ),
            retry_key=existing.retry_key,
        )
    review = ProgrammeReviewReceipt.objects.filter(case_id=world.case_id).get()
    with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
        retire_programme_call(
            actor_id=world.call.manager.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            call_id=world.call.call_id,
            owner_department_id=world.call.department_id,
            expected_version=2,
            reason="A retry key cannot cross workflows.",
            retry_key=review.retry_key,
            correlation_id=uuid4(),
            source_channel="test",
            authorizer=_AUTHORIZER,
        )


def test_new_policy_does_not_rewrite_case_and_unknown_question_policy_rolls_back():
    world = create_review_world()
    policy = review_policy()
    invalid = replace(
        policy, stages=(replace(policy.stages[0], question_keys=("foreign-key",)),)
    )
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.call.manager.id,
            Intent(Action.POLICY_CREATED, world.call.call_id, policy=invalid),
            expected_version=1,
        )
    assert ProgrammeReviewPolicy.objects.filter(call_id=world.call.call_id).count() == 1
    revised = replace(policy, stages=(replace(policy.stages[0], required_reviews=3),))
    result = world.command(
        world.call.manager.id,
        Intent(Action.POLICY_CREATED, world.call.call_id, policy=revised),
        expected_version=1,
    )
    assert result.version == 2
    case = ProgrammeReviewCase.objects.select_related("policy").get(id=world.case_id)
    assert case.policy_id == world.policy_id
    assert case.policy.stages[0]["required_reviews"] == 2


def test_new_submitted_seal_needs_a_new_case_without_rebinding_old_decision():
    world = create_review_world()
    _ready(world)
    decision = _decide(world)
    old_case = ProgrammeReviewCase.objects.get(id=world.case_id)
    proposal = ProgrammeProposal.objects.select_related("submission").get(
        id=world.proposal_id
    )
    common = {
        "actor_id": world.lead.id,
        "organization_id": world.call.edition.organization_id,
        "edition_id": world.call.edition.id,
        "proposal_id": world.proposal_id,
        "reason": "Deliberate new exact revision, never rewriting prior review.",
        "source_channel": "test",
        "authorizer": _AUTHORIZER,
    }
    reopened = reopen_programme_proposal(
        **common,
        expected_version=proposal.submission.aggregate_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    sealed = seal_programme_proposal(
        **common,
        expected_version=reopened.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    submit_programme_proposal(
        **common,
        expected_version=sealed.resulting_version,
        revision_id=sealed.target_id,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    opened = world.command(
        world.call.manager.id,
        Intent(Action.CASE_OPENED, world.proposal_id, policy_id=world.policy_id),
        expected_version=0,
    )
    assert opened.target_id != world.case_id
    assert (
        ProgrammeReviewCase.objects.get(id=opened.target_id).revision_id
        == sealed.target_id
    )
    old_case = ProgrammeReviewCase.objects.select_related("proposal", "policy").get(
        id=world.case_id
    )
    assert not accepted_review_is_effective(old_case)
    assert (
        ProgrammeReviewDecision.objects.get(id=decision.target_id).revision_id
        == old_case.revision_id
    )


def test_template_without_acknowledgement_keeps_bounded_message_and_refuses_receipt():
    policy = review_policy()
    policy = replace(
        policy,
        templates=tuple(
            replace(template, text="T" * 3000, acknowledgement_required=False)
            for template in policy.templates
        ),
    )
    world = create_review_world(policy=policy)
    _ready(world)
    result = world.command(
        world.decider.id,
        Intent(Action.DECIDED, world.case_id, outcome="accepted", text="M" * 3000),
    )
    decision = ProgrammeReviewDecision.objects.get(id=result.target_id)
    assert decision.message == "T" * 3000 + "\n\n" + "M" * 3000
    assert not decision.acknowledgement_required
    with pytest.raises(ProgrammeReviewConflictError):
        world.command(
            world.lead.id,
            Intent(Action.ACKNOWLEDGED, world.case_id, reference_id=result.target_id),
            self_access=True,
        )
