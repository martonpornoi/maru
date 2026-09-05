"""Synthetic exact-revision Programme review worlds using real owner commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from maru.applications.models import ProgrammeReviewAction, ProgrammeReviewCase
from maru.applications.programme_commands import (
    accept_programme_proposal_invitation,
    append_programme_proposal_answer,
    invite_programme_proposal_collaborator,
    revise_programme_contributor_profile,
    seal_programme_proposal,
    submit_programme_proposal,
)
from maru.applications.programme_inputs import ProgrammeProposalInvitationInput
from maru.applications.programme_review_commands import (
    ProgrammeReviewResult,
    apply_programme_review_command,
)
from maru.applications.programme_review_inputs import (
    ProgrammeReviewCommandInput,
    ProgrammeReviewPolicyInput,
)
from maru.applications.programme_review_queries import ProgrammeReviewReadRequest
from tests.factories import AccountFactory
from tests.integration.test_application_programme_services import (
    _AUTHORIZER,
    _active_call,
    _ActiveCallWorld,
    _profile,
    _respond,
    _start_proposal,
)
from tests.unit.test_application_programme_review_inputs import review_policy

if TYPE_CHECKING:
    from maru.identity.models import Account


@dataclass(frozen=True)
class ReviewWorld:
    """Keep exact synthetic proposal, policy, and named-role test identities."""

    call: _ActiveCallWorld
    lead: Account
    reviewer: Account
    peer: Account
    moderator: Account
    decider: Account
    proposal_id: UUID
    policy_id: UUID
    case_id: UUID
    collaborator: Account | None = None

    @property
    def version(self) -> int:
        """Read the real review cursor between independent test commands."""
        return ProgrammeReviewCase.objects.get(id=self.case_id).version

    def command(
        self,
        actor_id: UUID,
        command: ProgrammeReviewCommandInput,
        *,
        expected_version: int | None = None,
        self_access: bool = False,
        retry_key: UUID | None = None,
    ) -> ProgrammeReviewResult:
        """Exercise the real atomic boundary with the existing guarded test policy."""
        return apply_programme_review_command(
            actor_id=actor_id,
            organization_id=self.call.edition.organization_id,
            edition_id=self.call.edition.id,
            department_id=None if self_access else self.call.department_id,
            command=command,
            expected_version=self.version
            if expected_version is None
            else expected_version,
            retry_key=retry_key or uuid4(),
            reason="Synthetic accountable review action.",
            correlation_id=uuid4(),
            source_channel="test",
            authorizer=_AUTHORIZER,
        )

    def read(
        self,
        actor_id: UUID,
        capability: str,
        *,
        fields: frozenset[str] = frozenset(
            {"review_context", "review_answers", "review_evidence"}
        ),
        self_access: bool = False,
    ) -> ProgrammeReviewReadRequest:
        """Build an explicit projection request without carrying any authority."""
        return ProgrammeReviewReadRequest(
            actor_id=actor_id,
            organization_id=self.call.edition.organization_id,
            edition_id=self.call.edition.id,
            department_id=None if self_access else self.call.department_id,
            capability_code=capability,
            requested_fields=fields,
            correlation_id=uuid4(),
            source_channel="test",
        )


def create_review_world(
    *, policy: ProgrammeReviewPolicyInput | None = None, with_collaborator: bool = False
) -> ReviewWorld:
    """Create and submit a lead-only exact seal, then open its review case."""
    call = _active_call(code="review-" + uuid4().hex[:12])
    lead = AccountFactory(display_name="Synthetic proposal lead")
    proposal = _start_proposal(call, lead=lead)
    common = {
        "actor_id": lead.id,
        "organization_id": call.edition.organization_id,
        "edition_id": call.edition.id,
        "proposal_id": proposal.proposal_id,
        "reason": "Synthetic submitted review source.",
        "source_channel": "test",
        "now": call.now,
        "authorizer": _AUTHORIZER,
    }
    version = proposal.version
    collaborator = (
        AccountFactory(display_name="Synthetic included collaborator")
        if with_collaborator
        else None
    )
    if collaborator is not None:
        invited = invite_programme_proposal_collaborator(
            **common,
            invitation=ProgrammeProposalInvitationInput(
                invitee_email=collaborator.email,
                expires_at=call.now + timedelta(days=1),
            ),
            expected_version=version,
            retry_key=uuid4(),
            correlation_id=uuid4(),
        )
        personal = {**common, "actor_id": collaborator.id}
        accepted = accept_programme_proposal_invitation(
            **personal,
            expected_version=invited.resulting_version,
            retry_key=uuid4(),
            correlation_id=uuid4(),
        )
        profiled = revise_programme_contributor_profile(
            **personal,
            profile=_profile("Included collaborator"),
            expected_version=accepted.resulting_version,
            retry_key=uuid4(),
            correlation_id=uuid4(),
        )
        version = profiled.resulting_version
    answer = append_programme_proposal_answer(
        **common,
        question_id=call.question_id,
        value="A sealed session description",
        expected_version=version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    sealed = seal_programme_proposal(
        **common,
        expected_version=answer.resulting_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    version = sealed.resulting_version
    if collaborator is not None:
        version = _respond(
            world=proposal,
            actor=collaborator,
            revision_id=sealed.target_id,
            expected_version=version,
        )
    submit_programme_proposal(
        **common,
        expected_version=version,
        revision_id=sealed.target_id,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    review_common = {
        "actor_id": call.manager.id,
        "organization_id": call.edition.organization_id,
        "edition_id": call.edition.id,
        "department_id": call.department_id,
        "reason": "Pin explicit synthetic review policy.",
        "source_channel": "test",
        "authorizer": _AUTHORIZER,
    }
    configured = apply_programme_review_command(
        **review_common,
        command=ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.POLICY_CREATED,
            target_id=call.call_id,
            policy=policy or review_policy(),
        ),
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    opened = apply_programme_review_command(
        **review_common,
        command=ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.CASE_OPENED,
            target_id=proposal.proposal_id,
            policy_id=configured.target_id,
        ),
        expected_version=0,
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    return ReviewWorld(
        call,
        lead,
        AccountFactory(),
        AccountFactory(),
        AccountFactory(),
        AccountFactory(),
        proposal.proposal_id,
        configured.target_id,
        opened.target_id,
        collaborator,
    )


def assign_and_score(world: ReviewWorld, actor_id: UUID, *, score: int = 4) -> UUID:
    """Assign, self-clear conflicts, and submit one complete real rubric entry."""
    assigned = world.command(
        world.call.manager.id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.REVIEWER_ASSIGNED,
            target_id=world.case_id,
            reference_id=actor_id,
        ),
    )
    world.command(
        actor_id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.CONFLICT_CLEARED,
            target_id=world.case_id,
            reference_id=assigned.target_id,
        ),
    )
    world.command(
        actor_id,
        ProgrammeReviewCommandInput(
            action=ProgrammeReviewAction.SCORED,
            target_id=world.case_id,
            reference_id=assigned.target_id,
            scores=(("fit", score),),
        ),
    )
    return assigned.target_id
