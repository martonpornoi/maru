"""Adversarial PostgreSQL coverage for Applications Programme integrity."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import import_module
from threading import Barrier
from time import sleep
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from django.apps import apps
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.utils import timezone

from maru.applications.models import (
    AnswerSource,
    ApplicationAnswerRevision,
    ApplicationClassification,
    ApplicationCommandReceipt,
    ApplicationDefinition,
    ApplicationDefinitionStatus,
    ApplicationEligibilityKind,
    ApplicationOwnerDepartment,
    ApplicationQuestion,
    ApplicationQuestionType,
    ApplicationReviewDecision,
    ApplicationSection,
    ApplicationState,
    ApplicationSubmission,
    ApplicationTargetKind,
    ApplicationTargetRecord,
    ProgrammeCall,
    ProgrammeCallContributorField,
    ProgrammeCallFormat,
    ProgrammeCallTrack,
    ProgrammeCollaboratorState,
    ProgrammeCommandAction,
    ProgrammeCommandAggregateKind,
    ProgrammeCommandReceipt,
    ProgrammeCommandResultKind,
    ProgrammeContributorFieldCode,
    ProgrammeContributorRequirement,
    ProgrammeContributorRole,
    ProgrammeProposal,
    ProgrammeProposalCollaborator,
    ProgrammeProposalCollaboratorTransition,
    ProgrammeProposalContributorProfileRevision,
    ProgrammeProposalRevision,
    ProgrammeProposalRevisionAnswer,
    ProgrammeProposalRevisionContributor,
    ProgrammeProposalSelectionRevision,
    ReviewDecisionKind,
    ReviewerBasis,
)
from maru.applications.programme_writer_boundary import (
    programme_application_database_writer,
    programme_application_writer,
)
from maru.applications.readiness import (
    APPLICATIONS_INTEGRITY_CONTRACT,
    applications_database_integrity_is_ready,
)
from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from tests.factories import AccountFactory, EventEditionFactory
from tests.workforce_helpers import (
    create_department_for_test,
    retire_department_for_test,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from maru.identity.models import Account
    from maru.workforce.models import Department

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _DraftCall:
    actor: Account
    definition: ApplicationDefinition
    department: Department
    call: ProgrammeCall
    receipt: ProgrammeCommandReceipt


@dataclass(frozen=True, slots=True)
class _ActiveCall:
    draft: _DraftCall
    section: ApplicationSection
    question: ApplicationQuestion
    track: ProgrammeCallTrack
    format: ProgrammeCallFormat
    contributor_field: ProgrammeCallContributorField


@dataclass(frozen=True, slots=True)
class _Proposal:
    call: _ActiveCall
    submission: ApplicationSubmission
    proposal: ProgrammeProposal
    selection: ProgrammeProposalSelectionRevision
    profile: ProgrammeProposalContributorProfileRevision


@contextmanager
def _raw_programme_writer() -> Iterator[None]:
    """Activate both writer factors without issuing cleanup SQL on failure."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.set_config("
            "'maru.applications_programme_writer', 'on', true)"
        )
    with programme_application_writer():
        yield


def _create_draft_call(
    *,
    max_collaborators: int = 2,
    opens_at_offset: timedelta = -timedelta(days=1),
    applicant_edit_offset: timedelta = timedelta(days=29),
    closes_at_offset: timedelta = timedelta(days=30),
    reference_now: datetime | None = None,
) -> _DraftCall:
    edition = EventEditionFactory()
    actor = AccountFactory()
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = reference_now or timezone.now()
    retry_key = uuid4()
    with transaction.atomic(), programme_application_database_writer():
        definition = ApplicationDefinition.objects.create(
            organization=edition.organization,
            edition=edition,
            code="programme-call",
            version=1,
            aggregate_version=1,
            status=ApplicationDefinitionStatus.DRAFT,
            target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
            name="Programme call",
            description="Integrity-test call.",
            purpose="Collect collaborative Programme proposals.",
            classification=ApplicationClassification.PERSONAL,
            eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
            max_submissions_per_person=4,
            opens_at=now + opens_at_offset,
            closes_at=now + closes_at_offset,
            applicant_edit_until=now + applicant_edit_offset,
            minimum_age=0,
            audience_policy_code="applications.programme.audience.v1",
            retention_policy_code="applications.programme.retention.v1",
            age_policy_code="applications.programme.person.v1",
            created_by=actor,
        )
        ApplicationOwnerDepartment.objects.create(
            definition=definition,
            department=department,
        )
        call = ProgrammeCall.objects.create(
            organization=edition.organization,
            edition=edition,
            definition=definition,
            owner_department=department,
            max_collaborators=max_collaborators,
            content_policy_code="applications.programme.content.v1",
            contributor_consent_policy_code=(
                "applications.programme.contributor-consent.v1"
            ),
            collaboration_retention_policy_code=(
                "applications.programme.collaboration-retention.v1"
            ),
        )
        receipt = ProgrammeCommandReceipt.objects.create(
            organization=edition.organization,
            edition=edition,
            actor=actor,
            aggregate_kind=ProgrammeCommandAggregateKind.CALL,
            action=ProgrammeCommandAction.CALL_CREATED,
            retry_key=retry_key,
            request_digest="a" * 64,
            reason="Create a complete draft-call integrity fixture.",
            correlation_id=uuid4(),
            source_channel="test",
            definition=definition,
            submission=None,
            target_id=call.id,
            result_kind=ProgrammeCommandResultKind.CALL,
            expected_version=0,
            resulting_version=1,
        )
    return _DraftCall(actor, definition, department, call, receipt)


def _create_generic_definition(world: _DraftCall) -> ApplicationDefinition:
    now = timezone.now()
    return ApplicationDefinition.objects.create(
        organization=world.definition.organization,
        edition=world.definition.edition,
        code=f"generic-{uuid4().hex[:12]}",
        version=1,
        aggregate_version=1,
        status=ApplicationDefinitionStatus.DRAFT,
        target_adapter_kind=ApplicationTargetKind.IDEA,
        name="Generic application",
        description="Control definition for retry namespace tests.",
        purpose="Exercise generic Applications receipt isolation.",
        classification=ApplicationClassification.INTERNAL,
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        max_submissions_per_person=1,
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=2),
        applicant_edit_until=now + timedelta(days=1),
        minimum_age=0,
        audience_policy_code="",
        retention_policy_code="",
        age_policy_code="",
        created_by=world.actor,
    )


def _insert_generic_receipt(
    world: _DraftCall,
    *,
    definition: ApplicationDefinition,
    retry_key: UUID,
) -> ApplicationCommandReceipt:
    return ApplicationCommandReceipt.objects.create(
        organization=world.definition.organization,
        edition=world.definition.edition,
        actor=world.actor,
        action=ApplicationCommandReceipt.Action.DEFINITION_CREATED,
        retry_key=retry_key,
        request_digest="6" * 64,
        correlation_id=uuid4(),
        source_channel="test",
        definition=definition,
        submission=None,
        target_id=definition.id,
        resulting_version=1,
    )


def _configure_call_receipt(
    world: _DraftCall,
    *,
    retry_key: UUID,
) -> ProgrammeCommandReceipt:
    definition = ApplicationDefinition.objects.select_for_update().get(
        id=world.definition.id
    )
    definition.name = "Programme call revision"
    definition.aggregate_version = 2
    definition.save()
    return ProgrammeCommandReceipt.objects.create(
        organization=definition.organization,
        edition=definition.edition,
        actor=world.actor,
        aggregate_kind=ProgrammeCommandAggregateKind.CALL,
        action=ProgrammeCommandAction.CALL_CONFIGURED,
        retry_key=retry_key,
        request_digest="7" * 64,
        reason="Configure the call under the shared retry namespace.",
        correlation_id=uuid4(),
        source_channel="test",
        definition=definition,
        submission=None,
        target_id=world.call.id,
        result_kind=ProgrammeCommandResultKind.CALL,
        expected_version=1,
        resulting_version=2,
    )


def _activate_call(
    world: _DraftCall,
    *,
    condition: dict[str, object] | None = None,
    source_type: str = ApplicationQuestionType.SHORT_TEXT,
    source_options: list[dict[str, str]] | None = None,
    source_position: int = 1,
    conditional_position: int = 2,
    include_public_name: bool = True,
    question_tamper: dict[str, object] | None = None,
) -> _ActiveCall:
    now = timezone.now()
    with transaction.atomic(), _raw_programme_writer():
        section = ApplicationSection.objects.create(
            definition=world.definition,
            key="proposal",
            title="Proposal",
            position=1,
        )
        question = ApplicationQuestion.objects.create(
            definition=world.definition,
            section=section,
            key="source",
            field_type=source_type,
            label="Source",
            position=source_position,
            required=False,
            options=source_options or [],
            maximum_choices=(
                2 if source_type == ApplicationQuestionType.MULTIPLE_CHOICE else None
            ),
            purpose="Exercise the Programme integrity graph.",
            classification=ApplicationClassification.INTERNAL,
            staff_visible=False,
            reviewer_visible=False,
            api_projection=False,
        )
        if condition is not None:
            ApplicationQuestion.objects.create(
                definition=world.definition,
                section=section,
                key="conditional",
                field_type=ApplicationQuestionType.SHORT_TEXT,
                label="Conditional",
                position=conditional_position,
                required=False,
                condition=condition,
                purpose="Exercise one closed Programme condition.",
                classification=ApplicationClassification.INTERNAL,
                staff_visible=False,
                reviewer_visible=False,
                api_projection=False,
            )
        if question_tamper:
            ApplicationQuestion.objects.filter(id=question.id).update(**question_tamper)
        track = ProgrammeCallTrack.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            call=world.call,
            code="general",
            label="General",
            description="",
            position=1,
        )
        programme_format = ProgrammeCallFormat.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            call=world.call,
            code="panel",
            label="Panel",
            description="",
            position=1,
            min_duration_minutes=30,
            default_duration_minutes=60,
            max_duration_minutes=120,
        )
        if include_public_name:
            contributor_field = ProgrammeCallContributorField.objects.create(
                organization=world.definition.organization,
                edition=world.definition.edition,
                call=world.call,
                field_code=ProgrammeContributorFieldCode.PUBLIC_NAME,
                lead_requirement=ProgrammeContributorRequirement.REQUIRED,
                collaborator_requirement=ProgrammeContributorRequirement.OPTIONAL,
                position=1,
            )
        else:
            contributor_field = ProgrammeCallContributorField(
                organization=world.definition.organization,
                edition=world.definition.edition,
                call=world.call,
                field_code=ProgrammeContributorFieldCode.PUBLIC_NAME,
                lead_requirement=ProgrammeContributorRequirement.REQUIRED,
                collaborator_requirement=ProgrammeContributorRequirement.OPTIONAL,
                position=1,
            )
        world.definition.status = ApplicationDefinitionStatus.ACTIVE
        world.definition.aggregate_version = 2
        world.definition.activated_at = now
        world.definition.activated_by = world.actor
        world.definition.save()
        ProgrammeCommandReceipt.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            actor=world.actor,
            aggregate_kind=ProgrammeCommandAggregateKind.CALL,
            action=ProgrammeCommandAction.CALL_ACTIVATED,
            retry_key=uuid4(),
            request_digest="b" * 64,
            reason="Activate the complete integrity-test Programme call.",
            correlation_id=uuid4(),
            source_channel="test",
            definition=world.definition,
            submission=None,
            target_id=world.call.id,
            result_kind=ProgrammeCommandResultKind.CALL,
            expected_version=1,
            resulting_version=2,
        )
    world.definition.refresh_from_db()
    return _ActiveCall(
        world,
        section,
        question,
        track,
        programme_format,
        contributor_field,
    )


def _start_proposal(
    active: _ActiveCall,
    *,
    actor: Account | None = None,
    receipt_result_kind: str = ProgrammeCommandResultKind.PROPOSAL,
    receipt_target_id: UUID | None = None,
) -> _Proposal:
    world = active.draft
    proposal_actor = actor or world.actor
    with transaction.atomic(), _raw_programme_writer():
        submission = ApplicationSubmission.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            definition=world.definition,
            account=proposal_actor,
            ordinal=(
                ApplicationSubmission.objects.filter(
                    definition=world.definition,
                    account=proposal_actor,
                ).count()
                + 1
            ),
            state=ApplicationState.DRAFT,
            aggregate_version=1,
        )
        proposal = ProgrammeProposal.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            submission=submission,
            call=world.call,
            state="draft",
        )
        selection = ProgrammeProposalSelectionRevision.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            proposal=proposal,
            sequence=1,
            track=active.track,
            format=active.format,
            requested_duration_minutes=60,
            actor=proposal_actor,
            source_version=0,
            resulting_version=1,
        )
        profile = ProgrammeProposalContributorProfileRevision.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            proposal=proposal,
            account=proposal_actor,
            sequence=1,
            predecessor=None,
            public_name="Programme Lead",
            biography="",
            pronouns="",
            website="",
            proposed_for_publication=True,
            consent_policy_code=world.call.contributor_consent_policy_code,
            consent_acknowledged=True,
            actor=proposal_actor,
            digest="c" * 64,
            source_version=0,
            resulting_version=1,
        )
        ProgrammeCommandReceipt.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            actor=proposal_actor,
            aggregate_kind=ProgrammeCommandAggregateKind.PROPOSAL,
            action=ProgrammeCommandAction.PROPOSAL_STARTED,
            retry_key=uuid4(),
            request_digest="d" * 64,
            reason="Start the integrity-test Programme proposal.",
            correlation_id=uuid4(),
            source_channel="test",
            definition=world.definition,
            submission=submission,
            target_id=receipt_target_id or proposal.id,
            result_kind=receipt_result_kind,
            expected_version=0,
            resulting_version=1,
        )
    return _Proposal(active, submission, proposal, selection, profile)


def _invite_collaborator(
    proposal_world: _Proposal,
    *,
    account: Account,
    expires_at: datetime | None = None,
) -> ProgrammeProposalCollaborator:
    submission = proposal_world.submission
    proposal = proposal_world.proposal
    world = proposal_world.call.draft
    source_version = submission.aggregate_version
    expiry = expires_at or timezone.now() + timedelta(days=2)
    with transaction.atomic(), _raw_programme_writer():
        collaborator = ProgrammeProposalCollaborator.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            proposal=proposal,
            account=account,
            state=ProgrammeCollaboratorState.INVITED,
            generation=1,
            invite_expires_at=expiry,
        )
        transition_row = ProgrammeProposalCollaboratorTransition.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            proposal=proposal,
            collaborator=collaborator,
            sequence=1,
            generation=1,
            from_state=None,
            to_state=ProgrammeCollaboratorState.INVITED,
            actor=world.actor,
            reason="Invite one current collaborator.",
            invite_expires_at=expiry,
            source_version=source_version,
            resulting_version=source_version + 1,
        )
        submission.aggregate_version = source_version + 1
        submission.save()
        ProgrammeCommandReceipt.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            actor=world.actor,
            aggregate_kind=ProgrammeCommandAggregateKind.PROPOSAL,
            action=ProgrammeCommandAction.COLLABORATOR_INVITED,
            retry_key=uuid4(),
            request_digest="e" * 64,
            reason="Invite one current collaborator.",
            correlation_id=uuid4(),
            source_channel="test",
            definition=world.definition,
            submission=submission,
            target_id=transition_row.id,
            result_kind=ProgrammeCommandResultKind.COLLABORATOR_TRANSITION,
            expected_version=source_version,
            resulting_version=source_version + 1,
        )
    submission.refresh_from_db()
    return collaborator


def _insert_initial_invitation_raw(
    proposal_world: _Proposal,
    *,
    account: Account,
    current_expiry: datetime,
    transition_expiry: datetime,
) -> tuple[UUID, UUID]:
    collaborator_id = uuid4()
    transition_id = uuid4()
    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.applications_programmeproposalcollaborator (
                id, created_at, updated_at, organization_id, edition_id,
                proposal_id, account_id, state, generation, invite_expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'invited', 1, %s)
            """,
            [
                collaborator_id,
                now,
                now,
                proposal_world.proposal.organization_id,
                proposal_world.proposal.edition_id,
                proposal_world.proposal.id,
                account.id,
                current_expiry,
            ],
        )
        cursor.execute(
            """
            INSERT INTO public.applications_programmeproposalcollaboratortransition (
                id, created_at, updated_at, organization_id, edition_id,
                proposal_id, collaborator_id, sequence, generation,
                from_state, to_state, actor_id, reason, invite_expires_at,
                source_version, resulting_version
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, 1, 1,
                NULL, 'invited', %s, %s, %s, 1, 2
            )
            """,
            [
                transition_id,
                now,
                now,
                proposal_world.proposal.organization_id,
                proposal_world.proposal.edition_id,
                proposal_world.proposal.id,
                collaborator_id,
                proposal_world.call.draft.actor.id,
                "Exercise the authoritative invitation-expiry boundary.",
                transition_expiry,
            ],
        )
    return collaborator_id, transition_id


def _decline_collaborator(
    proposal_world: _Proposal,
    *,
    collaborator: ProgrammeProposalCollaborator,
) -> None:
    submission = proposal_world.submission
    world = proposal_world.call.draft
    source_version = submission.aggregate_version
    with transaction.atomic(), _raw_programme_writer():
        ProgrammeProposalCollaborator.objects.filter(id=collaborator.id).update(
            state=ProgrammeCollaboratorState.DECLINED
        )
        transition_row = ProgrammeProposalCollaboratorTransition.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            proposal=proposal_world.proposal,
            collaborator=collaborator,
            sequence=2,
            generation=1,
            from_state=ProgrammeCollaboratorState.INVITED,
            to_state=ProgrammeCollaboratorState.DECLINED,
            actor=collaborator.account,
            reason="Decline the current invitation.",
            invite_expires_at=None,
            source_version=source_version,
            resulting_version=source_version + 1,
        )
        submission.aggregate_version = source_version + 1
        submission.save()
        ProgrammeCommandReceipt.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            actor=collaborator.account,
            aggregate_kind=ProgrammeCommandAggregateKind.PROPOSAL,
            action=ProgrammeCommandAction.COLLABORATOR_DECLINED,
            retry_key=uuid4(),
            request_digest="f" * 64,
            reason="Decline the current invitation.",
            correlation_id=uuid4(),
            source_channel="test",
            definition=world.definition,
            submission=submission,
            target_id=transition_row.id,
            result_kind=ProgrammeCommandResultKind.COLLABORATOR_TRANSITION,
            expected_version=source_version,
            resulting_version=source_version + 1,
        )
    submission.refresh_from_db()


def _revise_selection(proposal_world: _Proposal) -> None:
    submission = proposal_world.submission
    world = proposal_world.call.draft
    source_version = submission.aggregate_version
    with transaction.atomic(), _raw_programme_writer():
        selection = ProgrammeProposalSelectionRevision.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            proposal=proposal_world.proposal,
            sequence=(
                ProgrammeProposalSelectionRevision.objects.filter(
                    proposal=proposal_world.proposal
                ).count()
                + 1
            ),
            track=proposal_world.call.track,
            format=proposal_world.call.format,
            requested_duration_minutes=90,
            actor=submission.account,
            source_version=source_version,
            resulting_version=source_version + 1,
        )
        submission.aggregate_version = source_version + 1
        submission.save()
        ProgrammeCommandReceipt.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            actor=submission.account,
            aggregate_kind=ProgrammeCommandAggregateKind.PROPOSAL,
            action=ProgrammeCommandAction.PROPOSAL_SELECTION_REVISED,
            retry_key=uuid4(),
            request_digest="2" * 64,
            reason="Revise the retained proposal selection.",
            correlation_id=uuid4(),
            source_channel="test",
            definition=world.definition,
            submission=submission,
            target_id=selection.id,
            result_kind=ProgrammeCommandResultKind.SELECTION_REVISION,
            expected_version=source_version,
            resulting_version=source_version + 1,
        )
    submission.refresh_from_db()


def _seal_proposal(proposal_world: _Proposal) -> ProgrammeProposalRevision:
    submission = proposal_world.submission
    proposal = proposal_world.proposal
    world = proposal_world.call.draft
    source_version = submission.aggregate_version
    with transaction.atomic(), _raw_programme_writer():
        revision = ProgrammeProposalRevision.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            proposal=proposal,
            sequence=1,
            predecessor=None,
            definition_version=world.definition.version,
            selection_revision=proposal_world.selection,
            source_version=source_version,
            resulting_version=source_version + 1,
            digest="3" * 64,
            created_by=submission.account,
            sealed_at=timezone.now(),
        )
        ProgrammeProposalRevisionAnswer.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            revision=revision,
            question=proposal_world.call.question,
            answer_revision=None,
            question_key=proposal_world.call.question.key,
            question_type=proposal_world.call.question.field_type,
            classification=proposal_world.call.question.classification,
        )
        ProgrammeProposalRevisionContributor.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            revision=revision,
            account=submission.account,
            role=ProgrammeContributorRole.LEAD,
            accepted_transition=None,
            profile_revision=proposal_world.profile,
        )
        ProgrammeProposal.objects.filter(id=proposal.id).update(
            state="sealed",
            sealed_revision=revision,
        )
        submission.aggregate_version = source_version + 1
        submission.save()
        ProgrammeCommandReceipt.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            actor=submission.account,
            aggregate_kind=ProgrammeCommandAggregateKind.PROPOSAL,
            action=ProgrammeCommandAction.PROPOSAL_SEALED,
            retry_key=uuid4(),
            request_digest="4" * 64,
            reason="Seal the integrity-test Programme proposal.",
            correlation_id=uuid4(),
            source_channel="test",
            definition=world.definition,
            submission=submission,
            target_id=revision.id,
            result_kind=ProgrammeCommandResultKind.PROPOSAL_REVISION,
            expected_version=source_version,
            resulting_version=source_version + 1,
        )
    submission.refresh_from_db()
    proposal.refresh_from_db()
    return revision


def _reopen_proposal(proposal_world: _Proposal) -> None:
    submission = proposal_world.submission
    proposal = proposal_world.proposal
    world = proposal_world.call.draft
    source_version = submission.aggregate_version
    with transaction.atomic(), _raw_programme_writer():
        ProgrammeProposal.objects.filter(id=proposal.id).update(
            state="draft",
            sealed_revision=None,
            submitted_revision=None,
        )
        submission.aggregate_version = source_version + 1
        submission.save()
        ProgrammeCommandReceipt.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            actor=submission.account,
            aggregate_kind=ProgrammeCommandAggregateKind.PROPOSAL,
            action=ProgrammeCommandAction.PROPOSAL_REOPENED,
            retry_key=uuid4(),
            request_digest="5" * 64,
            reason="Reopen the integrity-test Programme proposal.",
            correlation_id=uuid4(),
            source_channel="test",
            definition=world.definition,
            submission=submission,
            target_id=proposal.id,
            result_kind=ProgrammeCommandResultKind.PROPOSAL,
            expected_version=source_version,
            resulting_version=source_version + 1,
        )
    submission.refresh_from_db()
    proposal.refresh_from_db()


def _insert_track_raw(world: _DraftCall, *, position: int = 1) -> None:
    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.applications_programmecalltrack(
                id, created_at, updated_at, organization_id, edition_id,
                call_id, code, label, description, position
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '', %s)
            """,
            [
                uuid4(),
                now,
                now,
                world.call.organization_id,
                world.call.edition_id,
                world.call.id,
                f"track-{position}",
                f"Track {position}",
                position,
            ],
        )


def _insert_invalid_long_format(world: _DraftCall) -> None:
    now = timezone.now()
    with transaction.atomic(), _raw_programme_writer(), connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO public.applications_programmecallformat(
                id, created_at, updated_at, organization_id, edition_id,
                call_id, code, label, description, position,
                min_duration_minutes, default_duration_minutes,
                max_duration_minutes
            ) VALUES (%s, %s, %s, %s, %s, %s, 'day-long', 'Day long', '',
                      1, 30, 60, 1441)
            """,
            [
                uuid4(),
                now,
                now,
                world.call.organization_id,
                world.call.edition_id,
                world.call.id,
            ],
        )


def _truncate_programme_receipts_without_test_escape() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.set_config("
            "'maru.authority_provenance_test_reset', 'off', true)"
        )
        cursor.execute("TRUNCATE public.applications_programmecommandreceipt CASCADE")


def test_complete_draft_call_and_catalog_readiness_are_accepted() -> None:
    world = _create_draft_call()
    catalog = inspect_database_integrity_catalog(APPLICATIONS_INTEGRITY_CONTRACT)

    assert ProgrammeCall.objects.filter(id=world.call.id).exists()
    assert catalog.ready, catalog
    assert applications_database_integrity_is_ready()


def test_raw_programme_configuration_requires_database_writer_latch() -> None:
    world = _create_draft_call()

    with pytest.raises(DatabaseError, match="writer latch"), transaction.atomic():
        _insert_track_raw(world)

    assert not ProgrammeCallTrack.objects.filter(call=world.call).exists()


def test_programme_receipts_reject_raw_update_delete_and_single_truncate() -> None:
    world = _create_draft_call()

    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            UPDATE public.applications_programmecommandreceipt
               SET request_digest = %s
             WHERE id = %s
            """,
            ["b" * 64, world.receipt.id],
        )
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM public.applications_programmecommandreceipt WHERE id = %s",
            [world.receipt.id],
        )
    with pytest.raises(DatabaseError, match="governed retention"), transaction.atomic():
        _truncate_programme_receipts_without_test_escape()

    assert ProgrammeCommandReceipt.objects.filter(id=world.receipt.id).exists()


def test_retry_key_cannot_cross_generic_and_programme_receipt_tables() -> None:
    world = _create_draft_call()

    with pytest.raises(DatabaseError, match="already retained"), transaction.atomic():
        ApplicationCommandReceipt.objects.create(
            organization=world.definition.organization,
            edition=world.definition.edition,
            actor=world.actor,
            action=ApplicationCommandReceipt.Action.DEFINITION_CREATED,
            retry_key=world.receipt.retry_key,
            request_digest="c" * 64,
            correlation_id=uuid4(),
            source_channel="test",
            definition=world.definition,
            submission=None,
            target_id=world.definition.id,
            resulting_version=1,
        )


def test_retry_key_collision_is_rejected_in_programme_after_generic_direction() -> None:
    world = _create_draft_call()
    generic = _create_generic_definition(world)
    retry_key = uuid4()
    _insert_generic_receipt(world, definition=generic, retry_key=retry_key)

    with (
        pytest.raises(DatabaseError, match="another Applications command family"),
        transaction.atomic(),
        _raw_programme_writer(),
    ):
        _configure_call_receipt(world, retry_key=retry_key)

    world.definition.refresh_from_db()
    assert world.definition.aggregate_version == 1


def test_concurrent_cross_table_retry_collision_commits_exactly_one_owner() -> None:
    world = _create_draft_call()
    generic = _create_generic_definition(world)
    retry_key = uuid4()
    start = Barrier(2)

    def generic_worker() -> str:
        close_old_connections()
        try:
            with transaction.atomic():
                start.wait(timeout=10)
                _insert_generic_receipt(
                    world,
                    definition=generic,
                    retry_key=retry_key,
                )
        except DatabaseError:
            return "rejected"
        else:
            return "generic"
        finally:
            connections.close_all()

    def programme_worker() -> str:
        close_old_connections()
        try:
            with transaction.atomic(), _raw_programme_writer():
                start.wait(timeout=10)
                _configure_call_receipt(world, retry_key=retry_key)
        except DatabaseError:
            return "rejected"
        else:
            return "programme"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        generic_future = executor.submit(generic_worker)
        programme_future = executor.submit(programme_worker)
        outcomes = {
            generic_future.result(timeout=20),
            programme_future.result(timeout=20),
        }

    assert outcomes in ({"generic", "rejected"}, {"programme", "rejected"})
    assert (
        ApplicationCommandReceipt.objects.filter(
            edition=world.definition.edition,
            actor=world.actor,
            retry_key=retry_key,
        ).count()
        + ProgrammeCommandReceipt.objects.filter(
            edition=world.definition.edition,
            actor=world.actor,
            retry_key=retry_key,
        ).count()
        == 1
    )


def test_raw_format_duration_above_closed_bound_is_rejected() -> None:
    world = _create_draft_call()

    with pytest.raises(DatabaseError, match=r"1\.\.1440"):
        _insert_invalid_long_format(world)

    assert not ProgrammeCallFormat.objects.filter(call=world.call).exists()


def test_activation_requires_one_lead_public_name_field() -> None:
    world = _create_draft_call()

    with pytest.raises(DatabaseError, match="lead public name"):
        _activate_call(world, include_public_name=False)

    world.definition.refresh_from_db()
    assert world.definition.status == ApplicationDefinitionStatus.DRAFT


@pytest.mark.parametrize(
    (
        "source_type",
        "source_options",
        "source_position",
        "conditional_position",
        "condition",
    ),
    [
        pytest.param(
            ApplicationQuestionType.MULTIPLE_CHOICE,
            [{"code": "one", "label": "One"}, {"code": "two", "label": "Two"}],
            2,
            1,
            {"question_key": "source", "operator": "contains", "value": "one"},
            id="later-question",
        ),
        pytest.param(
            ApplicationQuestionType.SHORT_TEXT,
            [],
            1,
            2,
            {"question_key": "source", "operator": "contains", "value": "one"},
            id="contains-scalar",
        ),
        pytest.param(
            ApplicationQuestionType.BOOLEAN,
            [],
            1,
            2,
            {"question_key": "source", "operator": "equals", "value": "true"},
            id="boolean-string",
        ),
        pytest.param(
            ApplicationQuestionType.SINGLE_CHOICE,
            [{"code": "one", "label": "One"}, {"code": "two", "label": "Two"}],
            1,
            2,
            {"question_key": "source", "operator": "equals", "value": "three"},
            id="choice-outside-options",
        ),
    ],
)
def test_activation_rejects_raw_invalid_condition_graphs(
    source_type: str,
    source_options: list[dict[str, str]],
    source_position: int,
    conditional_position: int,
    condition: dict[str, object],
) -> None:
    world = _create_draft_call()

    with pytest.raises(DatabaseError, match="condition graph"):
        _activate_call(
            world,
            source_type=source_type,
            source_options=source_options,
            source_position=source_position,
            conditional_position=conditional_position,
            condition=condition,
        )


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"staff_visible": True}, id="generic-staff-disclosure"),
        pytest.param({"source_binding": "account.email"}, id="generic-source-binding"),
        pytest.param({"position": 2}, id="noncontiguous-position"),
        pytest.param({"maximum_length": 65_537}, id="oversized-text-bound"),
        pytest.param(
            {
                "field_type": ApplicationQuestionType.SINGLE_CHOICE,
                "options": [
                    {"code": "same", "label": "One"},
                    {"code": "same", "label": "Two"},
                ],
            },
            id="duplicate-choice-code",
        ),
    ],
)
def test_activation_rejects_raw_invalid_programme_question_shapes(
    tamper: dict[str, object],
) -> None:
    world = _create_draft_call()

    with pytest.raises(DatabaseError, match=r"question graph shape|question policy"):
        _activate_call(world, question_tamper=tamper)


def test_proposal_start_requires_the_inclusive_applicant_edit_window() -> None:
    expired = _activate_call(
        _create_draft_call(
            applicant_edit_offset=-timedelta(hours=1),
            closes_at_offset=timedelta(days=1),
        )
    )

    with pytest.raises(DatabaseError, match="edit window"):
        _start_proposal(expired)

    assert not ProgrammeProposal.objects.filter(call=expired.draft.call).exists()


def test_proposal_start_accepts_exact_inclusive_window_boundaries() -> None:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.transaction_timestamp()")
            row = cursor.fetchone()
        assert row is not None
        transaction_time = row[0]
        world = _create_draft_call(
            opens_at_offset=timedelta(0),
            applicant_edit_offset=timedelta(0),
            closes_at_offset=timedelta(days=1),
            reference_now=transaction_time,
        )
        proposal = _start_proposal(_activate_call(world))
        _seal_proposal(proposal)
        _reopen_proposal(proposal)

    assert ProgrammeProposal.objects.filter(id=proposal.proposal.id).exists()
    assert proposal.proposal.state == "draft"


def test_valid_active_call_and_proposal_start_cross_the_authoritative_boundary() -> (
    None
):
    proposal = _start_proposal(_activate_call(_create_draft_call()))

    assert proposal.proposal.state == "draft"
    assert proposal.submission.aggregate_version == 1


@pytest.mark.parametrize(
    ("result_kind", "target_id"),
    [
        pytest.param(ProgrammeCommandResultKind.CALL, None, id="wrong-result-kind"),
        pytest.param(
            ProgrammeCommandResultKind.PROPOSAL,
            uuid4(),
            id="arbitrary-target",
        ),
    ],
)
def test_proposal_start_receipt_requires_exact_action_result_proof(
    result_kind: str,
    target_id: UUID | None,
) -> None:
    active = _activate_call(_create_draft_call())

    with pytest.raises(DatabaseError, match="proposal start"):
        _start_proposal(
            active,
            receipt_result_kind=result_kind,
            receipt_target_id=target_id,
        )


@pytest.mark.parametrize(
    "source",
    [AnswerSource.SYSTEM_SOURCE, AnswerSource.STAFF_CORRECTION],
)
def test_programme_answers_reject_generic_source_and_staff_writers(source: str) -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))

    with (
        pytest.raises(DatabaseError, match="Programme answer writer"),
        transaction.atomic(),
        _raw_programme_writer(),
    ):
        ApplicationAnswerRevision.objects.create(
            submission=proposal.submission,
            question=proposal.call.question,
            sequence=1,
            question_key=proposal.call.question.key,
            question_type=proposal.call.question.field_type,
            classification=proposal.call.question.classification,
            value="smuggled",
            source=source,
            actor=proposal.call.draft.actor,
            reason="Synthetic generic writer probe."
            if source == AnswerSource.STAFF_CORRECTION
            else "",
            source_version=1,
            resulting_version=2,
        )


def test_generic_review_and_target_tables_reject_programme_proposals() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))
    actor = proposal.call.draft.actor

    with pytest.raises(DatabaseError, match="generic review"), transaction.atomic():
        ApplicationReviewDecision.objects.bulk_create(
            [
                ApplicationReviewDecision(
                    submission=proposal.submission,
                    sequence=1,
                    decision=ReviewDecisionKind.START_REVIEW,
                    from_state=ApplicationState.DRAFT,
                    to_state=ApplicationState.UNDER_REVIEW,
                    reviewer=actor,
                    reviewer_basis=ReviewerBasis.NAMED_PERSON,
                    reviewer_role_bundle=None,
                    reason="Attempt the forbidden generic review seam.",
                )
            ]
        )
    with pytest.raises(DatabaseError, match="later adapter"), transaction.atomic():
        ApplicationTargetRecord.objects.bulk_create(
            [
                ApplicationTargetRecord(
                    submission=proposal.submission,
                    adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
                    created_by=actor,
                )
            ]
        )


@pytest.mark.parametrize(
    "account_update",
    [{"is_active": False}, {"email_verified_at": None}],
    ids=("inactive", "unverified"),
)
def test_lead_cannot_append_evidence_after_identity_revocation(
    account_update: dict[str, object],
) -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))
    actor = proposal.call.draft.actor
    type(actor).objects.filter(id=actor.id).update(**account_update)

    with (
        pytest.raises(DatabaseError, match="active verified"),
        transaction.atomic(),
        _raw_programme_writer(),
    ):
        ProgrammeProposalSelectionRevision.objects.create(
            organization=proposal.call.draft.definition.organization,
            edition=proposal.call.draft.definition.edition,
            proposal=proposal.proposal,
            sequence=2,
            track=proposal.call.track,
            format=proposal.call.format,
            requested_duration_minutes=60,
            actor=actor,
            source_version=1,
            resulting_version=2,
        )


@pytest.mark.parametrize(
    "account_update",
    [{"is_active": False}, {"email_verified_at": None}],
    ids=("inactive", "unverified"),
)
def test_collaborator_cannot_continue_after_identity_revocation(
    account_update: dict[str, object],
) -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))
    collaborator_account = AccountFactory()
    collaborator = _invite_collaborator(proposal, account=collaborator_account)
    type(collaborator_account).objects.filter(id=collaborator_account.id).update(
        **account_update
    )

    with (
        pytest.raises(DatabaseError, match="active verified"),
        transaction.atomic(),
        _raw_programme_writer(),
    ):
        ProgrammeProposalCollaborator.objects.filter(id=collaborator.id).update(
            state=ProgrammeCollaboratorState.ACCEPTED
        )


def test_terminal_collaborator_history_does_not_consume_current_capacity() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call(max_collaborators=1)))
    first = _invite_collaborator(proposal, account=AccountFactory())
    _decline_collaborator(proposal, collaborator=first)

    replacement = _invite_collaborator(proposal, account=AccountFactory())

    assert replacement.state == ProgrammeCollaboratorState.INVITED
    assert (
        ProgrammeProposalCollaborator.objects.filter(
            proposal=proposal.proposal,
            state=ProgrammeCollaboratorState.DECLINED,
        ).count()
        == 1
    )
    assert (
        ProgrammeProposalCollaborator.objects.filter(
            proposal=proposal.proposal,
            state=ProgrammeCollaboratorState.INVITED,
        ).count()
        == 1
    )


def test_concurrent_invitations_cannot_exceed_the_current_roster_cap() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call(max_collaborators=1)))
    accounts = (AccountFactory(), AccountFactory())
    start = Barrier(2)

    def invite_worker(account: Account) -> str:
        close_old_connections()
        try:
            start.wait(timeout=10)
            _invite_collaborator(proposal, account=account)
        except DatabaseError:
            return "rejected"
        else:
            return "committed"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invite_worker, account) for account in accounts]
        outcomes = [future.result(timeout=20) for future in futures]

    assert sorted(outcomes) == ["committed", "rejected"]
    assert (
        ProgrammeProposalCollaborator.objects.filter(
            proposal=proposal.proposal,
            state=ProgrammeCollaboratorState.INVITED,
        ).count()
        == 1
    )


def test_derived_expired_invitation_does_not_consume_current_roster_capacity() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call(max_collaborators=1)))
    expiry = timezone.now() + timedelta(seconds=2)
    expired = _invite_collaborator(
        proposal,
        account=AccountFactory(),
        expires_at=expiry,
    )
    sleep(max(0.0, (expiry - timezone.now()).total_seconds() + 0.1))

    replacement = _invite_collaborator(proposal, account=AccountFactory())

    expired.refresh_from_db()
    assert expired.state == ProgrammeCollaboratorState.INVITED
    assert replacement.state == ProgrammeCollaboratorState.INVITED


def test_raw_current_invitation_rejects_expiry_after_applicant_edit_deadline() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))
    account = AccountFactory()
    deadline = proposal.call.draft.definition.applicant_edit_until
    now = timezone.now()

    with (
        pytest.raises(DatabaseError, match="applicant edit deadline"),
        transaction.atomic(),
        _raw_programme_writer(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO public.applications_programmeproposalcollaborator (
                id, created_at, updated_at, organization_id, edition_id,
                proposal_id, account_id, state, generation, invite_expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'invited', 1, %s)
            """,
            [
                uuid4(),
                now,
                now,
                proposal.proposal.organization_id,
                proposal.proposal.edition_id,
                proposal.proposal.id,
                account.id,
                deadline + timedelta(microseconds=1),
            ],
        )

    assert not ProgrammeProposalCollaborator.objects.filter(
        proposal=proposal.proposal,
        account=account,
    ).exists()


def test_raw_transition_rejects_expiry_after_applicant_edit_deadline() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))
    account = AccountFactory()
    deadline = proposal.call.draft.definition.applicant_edit_until

    with (
        pytest.raises(DatabaseError, match="applicant edit deadline"),
        transaction.atomic(),
        _raw_programme_writer(),
    ):
        _insert_initial_invitation_raw(
            proposal,
            account=account,
            current_expiry=deadline,
            transition_expiry=deadline + timedelta(microseconds=1),
        )

    assert not ProgrammeProposalCollaborator.objects.filter(
        proposal=proposal.proposal,
        account=account,
    ).exists()


def test_exact_applicant_edit_deadline_is_accepted_for_invitation_expiry() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))
    deadline = proposal.call.draft.definition.applicant_edit_until
    account = AccountFactory()
    now = timezone.now()

    with transaction.atomic(), _raw_programme_writer():
        collaborator_id, transition_id = _insert_initial_invitation_raw(
            proposal,
            account=account,
            current_expiry=deadline,
            transition_expiry=deadline,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.applications_applicationsubmission
                   SET aggregate_version = 2, updated_at = %s
                 WHERE id = %s
                """,
                [now, proposal.submission.id],
            )
            cursor.execute(
                """
                INSERT INTO public.applications_programmecommandreceipt (
                    id, created_at, updated_at, organization_id, edition_id,
                    actor_id, aggregate_kind, action, retry_key,
                    request_digest, reason, correlation_id, source_channel,
                    definition_id, submission_id, target_id, result_kind,
                    expected_version, resulting_version
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, 'proposal',
                    'collaborator_invited', %s, %s, %s, %s, 'test',
                    %s, %s, %s, 'collaborator_transition', 1, 2
                )
                """,
                [
                    uuid4(),
                    now,
                    now,
                    proposal.proposal.organization_id,
                    proposal.proposal.edition_id,
                    proposal.call.draft.actor.id,
                    uuid4(),
                    "9" * 64,
                    "Accept an invitation exactly at the applicant edit deadline.",
                    uuid4(),
                    proposal.call.draft.definition.id,
                    proposal.submission.id,
                    transition_id,
                ],
            )

    collaborator = ProgrammeProposalCollaborator.objects.get(id=collaborator_id)
    transition_row = ProgrammeProposalCollaboratorTransition.objects.get(
        id=transition_id,
    )
    assert collaborator.invite_expires_at == deadline
    assert transition_row.invite_expires_at == deadline


def test_profile_evidence_rejects_values_for_absent_or_hidden_call_fields() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))
    actor = proposal.call.draft.actor

    with (
        pytest.raises(DatabaseError, match="not collected"),
        transaction.atomic(),
        _raw_programme_writer(),
    ):
        ProgrammeProposalContributorProfileRevision.objects.create(
            organization=proposal.call.draft.definition.organization,
            edition=proposal.call.draft.definition.edition,
            proposal=proposal.proposal,
            account=actor,
            sequence=2,
            predecessor=proposal.profile,
            public_name="Programme Lead",
            biography="Private biography smuggled into a hidden field.",
            pronouns="",
            website="",
            proposed_for_publication=True,
            consent_policy_code=(
                proposal.call.draft.call.contributor_consent_policy_code
            ),
            consent_acknowledged=True,
            actor=actor,
            digest="1" * 64,
            source_version=1,
            resulting_version=2,
        )


def test_raw_proposal_evidence_rejects_cross_tenant_scope() -> None:
    proposal = _start_proposal(_activate_call(_create_draft_call()))
    other = EventEditionFactory()

    with (
        pytest.raises(DatabaseError, match="scope"),
        transaction.atomic(),
        _raw_programme_writer(),
    ):
        ProgrammeProposalSelectionRevision.objects.create(
            organization=other.organization,
            edition=proposal.call.draft.definition.edition,
            proposal=proposal.proposal,
            sequence=2,
            track=proposal.call.track,
            format=proposal.call.format,
            requested_duration_minutes=60,
            actor=proposal.call.draft.actor,
            source_version=1,
            resulting_version=2,
        )


def test_raw_call_owner_rejects_cross_edition_department() -> None:
    world = _create_draft_call()
    other_edition = EventEditionFactory(
        organization=world.definition.organization,
        series=world.definition.edition.series,
    )
    other_department = create_department_for_test(
        edition=other_edition,
        name="Other Programme",
        expected_code="other-programme",
    )

    with (
        pytest.raises(DatabaseError, match="scope or owner"),
        transaction.atomic(),
        _raw_programme_writer(),
    ):
        ProgrammeCall.objects.filter(id=world.call.id).update(
            owner_department=other_department
        )


def test_department_retirement_blocks_new_starts_but_not_existing_self_history() -> (
    None
):
    active = _activate_call(_create_draft_call())
    existing = _start_proposal(active)
    retire_department_for_test(department=active.draft.department)

    _revise_selection(existing)

    with pytest.raises(DatabaseError, match="proposal start"):
        _start_proposal(active, actor=AccountFactory())
    assert existing.submission.aggregate_version == 2


def test_reopen_requires_the_active_inclusive_applicant_edit_window() -> None:
    active = _activate_call(
        _create_draft_call(
            applicant_edit_offset=timedelta(seconds=3),
            closes_at_offset=timedelta(days=1),
        )
    )
    proposal = _start_proposal(active)
    _seal_proposal(proposal)
    delay = max(
        0.0,
        (active.draft.definition.applicant_edit_until - timezone.now()).total_seconds()
        + 0.1,
    )
    sleep(delay)

    with pytest.raises(DatabaseError, match="edit window"):
        _reopen_proposal(proposal)

    proposal.proposal.refresh_from_db()
    assert proposal.proposal.state == "sealed"


def test_populated_0006_fence_refuses_contract_removal() -> None:
    world = _create_draft_call()
    fence = import_module(
        "maru.applications.migrations.0006_programme_populated_downgrade_fence"
    )

    with pytest.raises(RuntimeError, match="Cannot remove"), transaction.atomic():
        fence.refuse_used_applications_programme_downgrade(
            apps,
            connection.schema_editor(),
        )

    assert ProgrammeCall.objects.filter(id=world.call.id).exists()


def test_profile_publication_constraint_is_authoritative_sql() -> None:
    constraint = next(
        item
        for item in ProgrammeProposalContributorProfileRevision._meta.constraints
        if item.name == "applications_prg_profile_public_consent"
    )

    assert "public_name" in str(constraint.condition)
    assert "proposed_for_publication" in str(constraint.condition)
