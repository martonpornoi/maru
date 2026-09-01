"""End-to-end service acceptance for Applications-owned Programme proposals."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from time import monotonic, sleep
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from maru.applications import programme_queries as programme_query_services
from maru.applications.models import (
    ApplicationDefinition,
    ApplicationQuestion,
    ProgrammeCall,
    ProgrammeCallFormat,
    ProgrammeCallTrack,
    ProgrammeCommandReceipt,
    ProgrammeProposal,
    ProgrammeProposalCollaborator,
    ProgrammeProposalRevision,
    ProgrammeProposalRevisionContributor,
    ProgrammeProposalState,
)
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeCompletenessError,
    ApplicationsProgrammeIdempotencyConflictError,
    ApplicationsProgrammeStateConflictError,
    ApplicationsProgrammeUnavailableError,
    accept_programme_proposal_invitation,
    activate_programme_call,
    append_programme_proposal_answer,
    configure_programme_call,
    create_programme_call,
    create_programme_call_successor,
    decline_programme_proposal_invitation,
    invite_programme_proposal_collaborator,
    leave_programme_proposal,
    reinvite_programme_proposal_collaborator,
    remove_programme_proposal_collaborator,
    reopen_programme_proposal,
    respond_to_programme_proposal_revision,
    retire_programme_call,
    revise_programme_contributor_profile,
    revise_programme_proposal_selection,
    seal_programme_proposal,
    start_programme_proposal,
    submit_programme_proposal,
    withdraw_programme_proposal,
)
from maru.applications.programme_inputs import (
    ProgrammeCallClassification,
    ProgrammeCallConfigurationInput,
    ProgrammeCallContributorFieldInput,
    ProgrammeCallDefinitionInput,
    ProgrammeCallFormatInput,
    ProgrammeCallQuestionInput,
    ProgrammeCallQuestionType,
    ProgrammeCallSectionInput,
    ProgrammeCallTrackInput,
    ProgrammeContributorFieldCode,
    ProgrammeContributorFieldRequirement,
    ProgrammeProposalContributorProfileInput,
    ProgrammeProposalInvitationInput,
    ProgrammeProposalRevisionResponseDecision,
    ProgrammeProposalRevisionResponseInput,
    ProgrammeProposalSelectionInput,
)
from maru.applications.programme_queries import (
    available_programme_calls,
    get_managed_programme_call_configuration,
    get_self_programme_proposal_detail,
    list_managed_programme_calls,
    list_self_programme_proposals,
)
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.workforce.models import Department, EditionStructureControl
from maru.workforce.structure_commands import (
    StructureDependencyConflictError,
    delete_unused_department,
)
from tests.factories import AccountFactory, EventEditionFactory
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from maru.audit.services import AuditRecord

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@dataclass(frozen=True, slots=True)
class _AllowExactProgrammeAuthorizer:
    """Return complete decisions only after production resolvers prove scope."""

    def authorize_department(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        department_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Allow an exact current Department test scope."""
        del (
            principal_id,
            organization_id,
            edition_id,
            department_id,
            capability_code,
        )
        return self._decision(requested_fields)

    def authorize_self(
        self,
        *,
        principal_id: UUID,
        owner_account_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Allow an Applications-proven exact self relationship."""
        del (
            principal_id,
            owner_account_id,
            organization_id,
            edition_id,
            capability_code,
        )
        return self._decision(requested_fields)

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Allow a retained receipt lookup after exact retry-scope proof."""
        del principal_id, organization_id, edition_id
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="sealed_programme_retry_test",
        )

    @staticmethod
    def _decision(requested_fields: frozenset[str] | None) -> PolicyDecision:
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit", "audit_sensitive_read"}),
            reason_code="sealed_programme_service_test",
        )


_AUTHORIZER = _AllowExactProgrammeAuthorizer()
_CONSENT_POLICY = "applications.programme.contributor-consent.v1"


def _database_now() -> datetime:
    """Return PostgreSQL's authoritative wall clock for expiry assertions."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_catalog.clock_timestamp()")
        row = cursor.fetchone()
    assert row is not None
    assert isinstance(row[0], datetime)
    return row[0]


def _wait_until_database_after(instant: datetime) -> datetime:
    """Wait boundedly until PostgreSQL observes a derived invitation expiry."""
    deadline = monotonic() + 10
    while monotonic() < deadline:
        current = _database_now()
        if current > instant:
            return current
        sleep(0.05)
    raise AssertionError("PostgreSQL did not advance past the invitation expiry.")


@dataclass(frozen=True, slots=True)
class _ActiveCallWorld:
    edition: object
    manager: object
    department_id: UUID
    call_id: UUID
    definition_id: UUID
    question_id: UUID
    track_id: UUID
    format_id: UUID
    now: object


@dataclass(frozen=True, slots=True)
class _ProposalWorld:
    call: _ActiveCallWorld
    lead: object
    proposal_id: UUID
    version: int


@pytest.fixture(autouse=True)
def _admit_future_programme_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mount only the otherwise-dormant effect admission needed by service tests."""

    def allow(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "maru.effects.services.require_effect_delivery_allowed",
        allow,
    )


def _definition(now: object, *, code: str) -> ProgrammeCallDefinitionInput:
    question = ProgrammeCallQuestionInput(
        key="session-title",
        field_type=ProgrammeCallQuestionType.SHORT_TEXT,
        label="Session title",
        help_text="Use the title attendees will recognize.",
        position=1,
        required=True,
        options=(),
        minimum_length=3,
        maximum_length=160,
        minimum_value=None,
        maximum_value=None,
        maximum_choices=None,
        reference_kind="",
        condition=None,
        purpose="Collect the title required for an immutable proposal revision.",
        classification=ProgrammeCallClassification.PERSONAL,
        retention_policy_code="",
    )
    return ProgrammeCallDefinitionInput(
        code=code,
        name="Programme proposals",
        description="Collaborative session proposals for the on-site timetable.",
        purpose="Collect complete, acknowledged Programme proposals.",
        classification=ProgrammeCallClassification.PERSONAL,
        maximum_submissions_per_person=4,
        opens_at=now - timedelta(days=1),
        applicant_edit_until=now + timedelta(days=6),
        closes_at=now + timedelta(days=7),
        audience_policy_code="applications.programme.audience.v1",
        retention_policy_code="applications.programme.retention.v1",
        sections=(
            ProgrammeCallSectionInput(
                key="proposal",
                title="Proposal",
                help_text="Describe the proposed session.",
                position=1,
                questions=(question,),
            ),
        ),
    )


def _configuration(department_id: UUID) -> ProgrammeCallConfigurationInput:
    return ProgrammeCallConfigurationInput(
        owner_department_id=department_id,
        maximum_collaborators=4,
        content_policy_code="applications.programme.content.v1",
        contributor_consent_policy_code=_CONSENT_POLICY,
        collaboration_retention_policy_code=(
            "applications.programme.collaboration-retention.v1"
        ),
        tracks=(
            ProgrammeCallTrackInput(
                code="general",
                label="General Programme",
                description="General sessions.",
                position=1,
            ),
        ),
        formats=(
            ProgrammeCallFormatInput(
                code="session",
                label="Session",
                description="One facilitated session.",
                position=1,
                minimum_duration_minutes=30,
                default_duration_minutes=60,
                maximum_duration_minutes=90,
            ),
        ),
        contributor_fields=(
            ProgrammeCallContributorFieldInput(
                field_code=ProgrammeContributorFieldCode.PUBLIC_NAME,
                lead_requirement=ProgrammeContributorFieldRequirement.REQUIRED,
                collaborator_requirement=ProgrammeContributorFieldRequirement.REQUIRED,
                position=1,
            ),
        ),
    )


def _profile(name: str) -> ProgrammeProposalContributorProfileInput:
    return ProgrammeProposalContributorProfileInput(
        public_name=name,
        biography="",
        pronouns="",
        website="",
        proposed_for_publication=True,
        consent_acknowledged=True,
        consent_policy_code=_CONSENT_POLICY,
    )


def _active_call(
    *,
    code: str = "programme-service",
    edition: object | None = None,
) -> _ActiveCallWorld:
    edition = edition or EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    created = create_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        definition_input=_definition(now, code=code),
        configuration=_configuration(department.id),
        expected_version=0,
        reason="Create a complete Programme call for service acceptance.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
    )
    activated = activate_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=created.target_id,
        owner_department_id=department.id,
        expected_version=created.resulting_version,
        reason="Activate the complete Programme call.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
    )
    assert activated.resulting_version == 2
    return _ActiveCallWorld(
        edition=edition,
        manager=manager,
        department_id=department.id,
        call_id=created.target_id,
        definition_id=created.definition_id,
        question_id=ApplicationQuestion.objects.get(
            definition_id=created.definition_id
        ).id,
        track_id=ProgrammeCallTrack.objects.get(call_id=created.target_id).id,
        format_id=ProgrammeCallFormat.objects.get(call_id=created.target_id).id,
        now=now,
    )


def _start_proposal(
    call: _ActiveCallWorld,
    *,
    lead: object | None = None,
) -> _ProposalWorld:
    actor = lead or AccountFactory(display_name="Programme lead")
    started = start_programme_proposal(
        actor_id=actor.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        call_id=call.call_id,
        selection=ProgrammeProposalSelectionInput(
            track_id=call.track_id,
            format_id=call.format_id,
            requested_duration_minutes=60,
        ),
        lead_profile=_profile("Programme lead"),
        expected_version=0,
        reason="Start a complete collaborative Programme proposal.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    return _ProposalWorld(
        call=call,
        lead=actor,
        proposal_id=started.target_id,
        version=started.resulting_version,
    )


def test_programme_call_protects_its_owner_department_from_hard_delete() -> None:
    """Leave #64 retirement work open while honoring the installed FK."""
    world = _active_call(code="programme-department-protect")
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    with pytest.raises(StructureDependencyConflictError):
        delete_unused_department(
            actor=administrator,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            department_id=world.department_id,
            expected_version=1,
            confirmation_name="Programme",
            reason="Prove a Programme-call owner is retained.",
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert Department.objects.filter(id=world.department_id).exists()
    assert ProgrammeCall.objects.filter(
        id=world.call_id,
        owner_department_id=world.department_id,
    ).exists()
    assert (
        EditionStructureControl.objects.get(
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
        ).aggregate_version
        == 1
    )


def _respond(
    *,
    world: _ProposalWorld,
    actor: object,
    revision_id: UUID,
    expected_version: int,
    decision: ProgrammeProposalRevisionResponseDecision = (
        ProgrammeProposalRevisionResponseDecision.ACKNOWLEDGED
    ),
) -> int:
    contributor = ProgrammeProposalRevisionContributor.objects.get(
        revision_id=revision_id,
        account_id=actor.id,
    )
    result = respond_to_programme_proposal_revision(
        actor_id=actor.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        response=ProgrammeProposalRevisionResponseInput(
            revision_id=revision_id,
            contributor_id=contributor.id,
            profile_revision_id=contributor.profile_revision_id,
            decision=decision,
        ),
        expected_version=expected_version,
        reason="Acknowledge the exact immutable proposal revision.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    return result.resulting_version


def test_invitation_expiry_cannot_outlive_the_inclusive_edit_window() -> None:
    """Prevent an invitation from permanently stranding a draft at cutoff."""
    call = _active_call(code="programme-invitation-window")
    world = _start_proposal(call)
    invitee = AccountFactory(display_name="Bounded invitee")
    edit_until = ApplicationDefinition.objects.get(
        id=call.definition_id
    ).applicant_edit_until
    after_edit_window = edit_until + timedelta(microseconds=1)

    with pytest.raises(ApplicationsProgrammeStateConflictError):
        invite_programme_proposal_collaborator(
            actor_id=world.lead.id,
            organization_id=call.edition.organization_id,
            edition_id=call.edition.id,
            proposal_id=world.proposal_id,
            invitation=ProgrammeProposalInvitationInput(
                invitee_email=invitee.email,
                expires_at=after_edit_window,
            ),
            expected_version=world.version,
            reason="Reject an invitation beyond the draft edit window.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=call.now,
            authorizer=_AUTHORIZER,
        )
    assert not ProgrammeProposalCollaborator.objects.filter(
        proposal_id=world.proposal_id,
        account_id=invitee.id,
    ).exists()

    invited = invite_programme_proposal_collaborator(
        actor_id=world.lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        invitation=ProgrammeProposalInvitationInput(
            invitee_email=invitee.email,
            expires_at=edit_until,
        ),
        expected_version=world.version,
        reason="Allow an invitation through the exact inclusive cutoff.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    declined = decline_programme_proposal_invitation(
        actor_id=invitee.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=invited.resulting_version,
        reason="Decline before testing the reinvitation boundary.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )

    with pytest.raises(ApplicationsProgrammeStateConflictError):
        reinvite_programme_proposal_collaborator(
            actor_id=world.lead.id,
            organization_id=call.edition.organization_id,
            edition_id=call.edition.id,
            proposal_id=world.proposal_id,
            invitation=ProgrammeProposalInvitationInput(
                invitee_email=invitee.email,
                expires_at=after_edit_window,
            ),
            expected_version=declined.resulting_version,
            reason="Reject a reinvitation beyond the draft edit window.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=call.now,
            authorizer=_AUTHORIZER,
        )

    reinvited = reinvite_programme_proposal_collaborator(
        actor_id=world.lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        invitation=ProgrammeProposalInvitationInput(
            invitee_email=invitee.email,
            expires_at=edit_until,
        ),
        expected_version=declined.resulting_version,
        reason="Allow reinvitation through the exact inclusive cutoff.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    collaborator = ProgrammeProposalCollaborator.objects.get(
        proposal_id=world.proposal_id,
        account_id=invitee.id,
    )
    assert collaborator.generation == 2
    assert collaborator.invite_expires_at == edit_until
    assert reinvited.resulting_version == declined.resulting_version + 1


def test_manager_configuration_queries_and_retired_successor_copy() -> None:
    """Configure, inspect, retire, and copy one exact call graph without proposals."""
    edition = EventEditionFactory()
    manager = AccountFactory(display_name="Programme manager")
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()
    definition_input = _definition(now, code="programme-lineage")
    configuration = _configuration(department.id)
    created = create_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        definition_input=definition_input,
        configuration=configuration,
        expected_version=0,
        reason="Create a draft for complete manager configuration acceptance.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
    )
    configured_input = replace(
        definition_input,
        name="Configured Programme proposals",
        description="The complete replacement graph copied into a successor.",
    )
    configured = configure_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=created.target_id,
        owner_department_id=department.id,
        definition_input=configured_input,
        configuration=configuration,
        expected_version=created.resulting_version,
        reason="Replace the complete draft graph through its dedicated writer.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
    )
    workspace = get_managed_programme_call_configuration(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        department_id=department.id,
        call_id=created.target_id,
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    assert workspace.summary.aggregate_version == configured.resulting_version
    assert workspace.summary.name == configured_input.name
    assert workspace.sections[0].questions[0].help_text
    assert workspace.tracks[0].code == "general"
    activated = activate_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=created.target_id,
        owner_department_id=department.id,
        expected_version=configured.resulting_version,
        reason="Activate the configured call before retiring its lineage head.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
    )
    retired = retire_programme_call(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=created.target_id,
        owner_department_id=department.id,
        expected_version=activated.resulting_version,
        reason="Retire the exact lineage head before copy-on-write.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
    )
    successor = create_programme_call_successor(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=created.target_id,
        owner_department_id=department.id,
        expected_version=retired.resulting_version,
        reason="Create the only exact successor from the retired lineage head.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
        authorizer=_AUTHORIZER,
    )

    source = ProgrammeCall.objects.select_related("definition").get(
        id=created.target_id
    )
    copied = ProgrammeCall.objects.select_related("definition").get(
        id=successor.target_id
    )
    assert copied.definition.code == source.definition.code
    assert copied.definition.version == source.definition.version + 1
    assert copied.definition.aggregate_version == 1
    assert copied.definition.status == "draft"
    definition_fields = (
        "name",
        "description",
        "purpose",
        "classification",
        "eligibility_kind",
        "max_submissions_per_person",
        "opens_at",
        "closes_at",
        "applicant_edit_until",
        "minimum_age",
        "audience_policy_code",
        "retention_policy_code",
        "age_policy_code",
        "target_adapter_kind",
    )
    assert tuple(getattr(copied.definition, field) for field in definition_fields) == (
        tuple(getattr(source.definition, field) for field in definition_fields)
    )
    call_fields = (
        "owner_department_id",
        "max_collaborators",
        "content_policy_code",
        "contributor_consent_policy_code",
        "collaboration_retention_policy_code",
    )
    assert tuple(getattr(copied, field) for field in call_fields) == tuple(
        getattr(source, field) for field in call_fields
    )
    question_fields = (
        "key",
        "field_type",
        "label",
        "help_text",
        "position",
        "required",
        "options",
        "minimum_length",
        "maximum_length",
        "minimum_value",
        "maximum_value",
        "maximum_choices",
        "reference_kind",
        "source_binding",
        "condition",
        "purpose",
        "classification",
        "applicant_visible",
        "applicant_writable",
        "staff_visible",
        "staff_writable",
        "reviewer_visible",
        "public_after_approval",
        "api_projection",
        "retention_policy_code",
    )
    source_question = source.definition.questions.get()
    copied_question = copied.definition.questions.get()
    assert tuple(getattr(copied_question, field) for field in question_fields) == tuple(
        getattr(source_question, field) for field in question_fields
    )
    managed = list_managed_programme_calls(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        department_id=department.id,
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    assert {row.call_id for row in managed} == {source.id, copied.id}
    copied_workspace = get_managed_programme_call_configuration(
        actor_id=manager.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        department_id=department.id,
        call_id=copied.id,
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    assert copied_workspace.summary.name == configured_input.name
    assert tuple(
        (
            section.key,
            section.title,
            section.help_text,
            section.position,
            tuple(
                (
                    question.key,
                    question.field_type,
                    question.label,
                    question.help_text,
                    question.required,
                    question.options,
                    question.condition,
                    question.purpose,
                    question.classification,
                    question.retention_policy_code,
                )
                for question in section.questions
            ),
        )
        for section in copied_workspace.sections
    ) == tuple(
        (
            section.key,
            section.title,
            section.help_text,
            section.position,
            tuple(
                (
                    question.key,
                    question.field_type,
                    question.label,
                    question.help_text,
                    question.required,
                    question.options,
                    question.condition,
                    question.purpose,
                    question.classification,
                    question.retention_policy_code,
                )
                for question in section.questions
            ),
        )
        for section in workspace.sections
    )


def test_managed_call_reads_append_complete_sensitive_read_audit() -> None:
    """Persist exact allow evidence before releasing managed call projections."""
    world = _active_call(code="programme-managed-audit")
    list_correlation = uuid4()
    detail_correlation = uuid4()

    summaries = list_managed_programme_calls(
        actor_id=world.manager.id,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        department_id=world.department_id,
        correlation_id=list_correlation,
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    configuration = get_managed_programme_call_configuration(
        actor_id=world.manager.id,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        department_id=world.department_id,
        call_id=world.call_id,
        correlation_id=detail_correlation,
        source_channel="test",
        authorizer=_AUTHORIZER,
    )

    assert tuple(row.call_id for row in summaries) == (world.call_id,)
    assert configuration.summary.call_id == world.call_id
    list_audit = AuditEvent.objects.get(correlation_id=list_correlation)
    detail_audit = AuditEvent.objects.get(correlation_id=detail_correlation)
    for audit in (list_audit, detail_audit):
        assert audit.principal_kind == "account"
        assert audit.principal_id == world.manager.id
        assert audit.organization_id == world.edition.organization_id
        assert audit.event_edition_id == world.edition.id
        assert audit.capability_code == "applications.manage_programme_calls"
        assert audit.outcome == AuditEvent.Outcome.ALLOW
        assert audit.reason_code == "sealed_programme_service_test"
        assert audit.source_channel == "test"
        assert audit.request_id == audit.correlation_id
        assert audit.obligations == ["audit", "audit_sensitive_read"]
        assert timezone.is_aware(audit.occurred_at)
    assert list_audit.operation == "applications.programme.query.managed_call_list"
    assert list_audit.target_type == "applications.programme_call.collection"
    assert list_audit.target_id == world.department_id
    assert list_audit.safe_metadata == {"target_count": 1}
    assert detail_audit.operation == (
        "applications.programme.query.managed_call_configuration"
    )
    assert detail_audit.target_type == "applications.programme_call"
    assert detail_audit.target_id == world.call_id
    assert detail_audit.safe_metadata == {"target_count": 1}


def test_managed_call_read_rejects_invalid_audit_input_before_scope_or_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validate audit identity before authorization or restricted data access."""

    def unexpected(**_kwargs: object) -> None:
        raise AssertionError("Invalid audit input reached protected query work.")

    monkeypatch.setattr(
        programme_query_services,
        "authorize_programme_call_scope",
        unexpected,
    )
    monkeypatch.setattr(programme_query_services, "_call_query", unexpected)
    correlation_id = uuid4()
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        list_managed_programme_calls(
            actor_id=uuid4(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            department_id=uuid4(),
            correlation_id=correlation_id,
            source_channel="Invalid Channel",
            authorizer=_AUTHORIZER,
        )

    assert not AuditEvent.objects.filter(correlation_id=correlation_id).exists()


def test_managed_call_read_hides_cross_tenant_and_cross_edition_targets() -> None:
    """Make foreign-tenant, foreign-edition, and absent calls indistinguishable."""
    local = _active_call(code="programme-managed-local")
    sibling_edition = EventEditionFactory(series=local.edition.series)
    sibling = _active_call(
        code="programme-managed-sibling",
        edition=sibling_edition,
    )
    foreign = _active_call(code="programme-managed-foreign")
    hidden_call_ids = (sibling.call_id, foreign.call_id, uuid4())
    denial_shapes: list[tuple[object, ...]] = []

    for hidden_call_id in hidden_call_ids:
        correlation_id = uuid4()
        with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
            get_managed_programme_call_configuration(
                actor_id=local.manager.id,
                organization_id=local.edition.organization_id,
                edition_id=local.edition.id,
                department_id=local.department_id,
                call_id=hidden_call_id,
                correlation_id=correlation_id,
                source_channel="test",
                authorizer=_AUTHORIZER,
            )
        audit = AuditEvent.objects.get(correlation_id=correlation_id)
        denial_shapes.append(
            (
                audit.principal_id,
                audit.organization_id,
                audit.event_edition_id,
                audit.capability_code,
                audit.operation,
                audit.target_type,
                audit.target_id,
                audit.outcome,
                audit.reason_code,
                audit.source_channel,
                audit.obligations,
                audit.safe_metadata,
            )
        )

    assert sibling.edition.organization_id == local.edition.organization_id
    assert sibling.edition.id != local.edition.id
    assert foreign.edition.organization_id != local.edition.organization_id
    assert denial_shapes[0] == denial_shapes[1] == denial_shapes[2]
    assert denial_shapes[0][5:] == (
        "applications.programme_call.scope",
        None,
        AuditEvent.Outcome.DENY,
        "applications_programme_authorization_denied",
        "test",
        ["audit"],
        {},
    )


def test_managed_call_read_audit_failure_releases_no_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when mandatory managed-read audit evidence cannot persist."""
    world = _active_call(code="programme-managed-audit-failure")
    correlation_id = uuid4()
    real_append_audit = programme_query_services.append_audit

    def unavailable(
        record: AuditRecord,
        *,
        occurred_at: datetime | None = None,
    ) -> None:
        real_append_audit(record, occurred_at=occurred_at)
        raise RuntimeError("Synthetic managed-read audit outage.")

    monkeypatch.setattr(programme_query_services, "append_audit", unavailable)
    with pytest.raises(RuntimeError, match="managed-read audit outage"):
        list_managed_programme_calls(
            actor_id=world.manager.id,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            department_id=world.department_id,
            correlation_id=correlation_id,
            source_channel="test",
            authorizer=_AUTHORIZER,
        )

    assert not AuditEvent.objects.filter(correlation_id=correlation_id).exists()


def test_complete_collaborative_lifecycle_and_disclosure_boundaries() -> None:  # noqa: PLR0915
    """Build, acknowledge, reopen, resubmit, and withdraw exact revisions."""
    call = _active_call()
    lead = AccountFactory(display_name="Lead label")
    collaborator_a = AccountFactory(display_name="Collaborator A")
    collaborator_b = AccountFactory(display_name="Collaborator B")

    available = available_programme_calls(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    assert tuple(row.summary.call_id for row in available) == (call.call_id,)
    assert available[0].contributor_consent_policy_code == _CONSENT_POLICY
    assert tuple(row.field_code for row in available[0].contributor_fields) == (
        ProgrammeContributorFieldCode.PUBLIC_NAME,
    )

    world = _start_proposal(call, lead=lead)
    answered = append_programme_proposal_answer(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        question_id=call.question_id,
        value="A complete collaborative session",
        expected_version=world.version,
        reason="Complete the required Programme answer.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    first_seal = seal_programme_proposal(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=answered.resulting_version,
        reason="Seal the lead-only baseline revision.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    reopened = reopen_programme_proposal(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=first_seal.resulting_version,
        reason="Reopen the baseline to include collaborators.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    version = reopened.resulting_version
    for collaborator in (collaborator_a, collaborator_b):
        invited = invite_programme_proposal_collaborator(
            actor_id=lead.id,
            organization_id=call.edition.organization_id,
            edition_id=call.edition.id,
            proposal_id=world.proposal_id,
            invitation=ProgrammeProposalInvitationInput(
                invitee_email=collaborator.email,
                expires_at=call.now + timedelta(days=1),
            ),
            expected_version=version,
            reason="Invite an exact existing contributor.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=call.now,
            authorizer=_AUTHORIZER,
        )
        version = invited.resulting_version

    invited_detail = get_self_programme_proposal_detail(
        actor_id=collaborator_a.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        requested_fields=frozenset({"proposal_summary", "selection", "own_invitation"}),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    assert invited_detail.summary is not None
    assert invited_detail.summary.relationship == "invited"
    assert invited_detail.answers is None
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        get_self_programme_proposal_detail(
            actor_id=collaborator_a.id,
            organization_id=call.edition.organization_id,
            edition_id=call.edition.id,
            proposal_id=world.proposal_id,
            requested_fields=frozenset({"answers"}),
            correlation_id=uuid4(),
            source_channel="test",
            now=call.now,
            authorizer=_AUTHORIZER,
        )

    for index, collaborator in enumerate((collaborator_a, collaborator_b), start=1):
        accepted = accept_programme_proposal_invitation(
            actor_id=collaborator.id,
            organization_id=call.edition.organization_id,
            edition_id=call.edition.id,
            proposal_id=world.proposal_id,
            expected_version=version,
            reason="Accept the exact current Programme invitation.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=call.now,
            authorizer=_AUTHORIZER,
        )
        version = accepted.resulting_version
        profiled = revise_programme_contributor_profile(
            actor_id=collaborator.id,
            organization_id=call.edition.organization_id,
            edition_id=call.edition.id,
            proposal_id=world.proposal_id,
            profile=_profile(f"Collaborator {index}"),
            expected_version=version,
            reason="Add the collaborator's own acknowledged profile.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=call.now,
            authorizer=_AUTHORIZER,
        )
        version = profiled.resulting_version

    second_seal = seal_programme_proposal(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=version,
        reason="Seal the exact collaborative proposal revision.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    version = _respond(
        world=world,
        actor=collaborator_a,
        revision_id=second_seal.target_id,
        expected_version=second_seal.resulting_version,
    )
    fields = frozenset(
        {
            "proposal_summary",
            "answers",
            "contributors",
            "contributor_profiles",
            "revision_history",
            "revision_responses",
        }
    )
    lead_detail = get_self_programme_proposal_detail(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        requested_fields=fields,
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    collaborator_detail = get_self_programme_proposal_detail(
        actor_id=collaborator_a.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        requested_fields=fields,
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    assert lead_detail.revisions is not None
    assert tuple(row.revision_id for row in lead_detail.revisions) == (
        first_seal.target_id,
        second_seal.target_id,
    )
    assert collaborator_detail.revisions is not None
    assert tuple(row.revision_id for row in collaborator_detail.revisions) == (
        second_seal.target_id,
    )
    assert lead_detail.responses is not None
    assert len(lead_detail.responses) == 2
    assert collaborator_detail.responses is not None
    assert len(collaborator_detail.responses) == 1
    assert collaborator_detail.responses[0].account_id == collaborator_a.id
    assert collaborator_detail.answers is not None
    assert collaborator_detail.answers[0].question.help_text
    assert collaborator_detail.answers[0].question.minimum_length == 3
    assert collaborator_detail.contributors is not None
    assert {row.display_label for row in collaborator_detail.contributors} == {
        "Collaborator A",
        "Lead label",
    }

    version = _respond(
        world=world,
        actor=collaborator_b,
        revision_id=second_seal.target_id,
        expected_version=version,
    )
    submitted = submit_programme_proposal(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        revision_id=second_seal.target_id,
        expected_version=version,
        reason="Submit the fully acknowledged exact revision.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    reopened = reopen_programme_proposal(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=submitted.resulting_version,
        reason="Reopen the submitted proposal for an exact resubmission.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    proposal = ProgrammeProposal.objects.get(id=world.proposal_id)
    assert proposal.state == ProgrammeProposalState.DRAFT
    assert proposal.sealed_revision_id is None
    assert proposal.submitted_revision_id is None
    assert ProgrammeProposalRevision.objects.filter(proposal=proposal).count() == 2

    third_seal = seal_programme_proposal(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=reopened.resulting_version,
        reason="Seal a successor immutable revision after reopening.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    version = third_seal.resulting_version
    for collaborator in (collaborator_a, collaborator_b):
        version = _respond(
            world=world,
            actor=collaborator,
            revision_id=third_seal.target_id,
            expected_version=version,
        )
    resubmitted = submit_programme_proposal(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        revision_id=third_seal.target_id,
        expected_version=version,
        reason="Submit the replacement fully acknowledged revision.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    withdrawn = withdraw_programme_proposal(
        actor_id=lead.id,
        organization_id=call.edition.organization_id,
        edition_id=call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=resubmitted.resulting_version,
        reason="Withdraw while retaining every immutable revision.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=call.now,
        authorizer=_AUTHORIZER,
    )
    proposal.refresh_from_db()
    assert withdrawn.resulting_version == 20
    assert proposal.state == ProgrammeProposalState.WITHDRAWN
    assert ProgrammeProposalRevision.objects.filter(proposal=proposal).count() == 3
    assert (
        ProgrammeCommandReceipt.objects.filter(edition_id=call.edition.id).count() == 22
    )
    assert (
        DomainEvent.objects.filter(
            event_edition_id=call.edition.id,
            event_name__in=(
                "applications.programme_call.changed.v1",
                "applications.programme_proposal.changed.v1",
            ),
        ).count()
        == 22
    )
    assert (
        OutboxMessage.objects.filter(
            event__event_edition_id=call.edition.id,
            event__event_name__startswith="applications.programme_",
        ).count()
        == 22
    )


def test_exact_revision_decline_blocks_submission_without_partial_success() -> None:
    """Retain the decline while refusing submit evidence for that exact revision."""
    world = _start_proposal(_active_call(code="programme-decline"))
    collaborator = AccountFactory(display_name="Declining collaborator")
    answered = append_programme_proposal_answer(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        question_id=world.call.question_id,
        value="A proposal requiring explicit collaborator consent",
        expected_version=world.version,
        reason="Complete the required answer before collaborator review.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    invited = invite_programme_proposal_collaborator(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        invitation=ProgrammeProposalInvitationInput(
            invitee_email=collaborator.email,
            expires_at=world.call.now + timedelta(days=1),
        ),
        expected_version=answered.resulting_version,
        reason="Invite the collaborator whose decline must bind the seal.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    accepted = accept_programme_proposal_invitation(
        actor_id=collaborator.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=invited.resulting_version,
        reason="Accept before reviewing the exact sealed revision.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    profiled = revise_programme_contributor_profile(
        actor_id=collaborator.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        profile=_profile("Declining collaborator"),
        expected_version=accepted.resulting_version,
        reason="Bind the collaborator's own profile to the future seal.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    sealed = seal_programme_proposal(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        expected_version=profiled.resulting_version,
        reason="Seal the exact revision offered for acknowledgement.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    declined_version = _respond(
        world=world,
        actor=collaborator,
        revision_id=sealed.target_id,
        expected_version=sealed.resulting_version,
        decision=ProgrammeProposalRevisionResponseDecision.DECLINED,
    )
    receipts_before = ProgrammeCommandReceipt.objects.filter(
        edition_id=world.call.edition.id
    ).count()
    events_before = DomainEvent.objects.filter(
        event_edition_id=world.call.edition.id,
        event_name="applications.programme_proposal.changed.v1",
    ).count()

    with pytest.raises(ApplicationsProgrammeCompletenessError):
        submit_programme_proposal(
            actor_id=world.lead.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            proposal_id=world.proposal_id,
            revision_id=sealed.target_id,
            expected_version=declined_version,
            reason="A declined exact revision must never submit.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=world.call.now,
            authorizer=_AUTHORIZER,
        )

    proposal = ProgrammeProposal.objects.get(id=world.proposal_id)
    assert proposal.state == ProgrammeProposalState.SEALED
    assert proposal.submitted_revision_id is None
    assert (
        ProgrammeCommandReceipt.objects.filter(edition_id=world.call.edition.id).count()
        == receipts_before
    )
    assert (
        DomainEvent.objects.filter(
            event_edition_id=world.call.edition.id,
            event_name="applications.programme_proposal.changed.v1",
        ).count()
        == events_before
    )
    failure = AuditEvent.objects.get(
        event_edition_id=world.call.edition.id,
        operation="applications.programme.command.proposal_submitted",
        outcome=AuditEvent.Outcome.ERROR,
    )
    assert failure.reason_code == "applications_programme_incomplete"
    assert failure.target_id is None


def test_relationship_changing_commands_replay_before_current_membership() -> None:
    """Replay accept, decline, and leave after each success changed the relationship."""
    world = _start_proposal(_active_call(code="programme-replay"))
    revised = revise_programme_proposal_selection(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        selection=ProgrammeProposalSelectionInput(
            track_id=world.call.track_id,
            format_id=world.call.format_id,
            requested_duration_minutes=75,
        ),
        expected_version=world.version,
        reason="Revise the lead-owned Programme selection.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    version = revised.resulting_version
    self_list = list_self_programme_proposals(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        correlation_id=uuid4(),
        source_channel="test",
        now=world.call.now,
        authorizer=_AUTHORIZER,
    )
    assert tuple(row.summary.proposal_id for row in self_list) == (world.proposal_id,)
    assert self_list[0].selection is not None
    assert self_list[0].selection.requested_duration_minutes == 75
    accepted_actor = AccountFactory()
    declined_actor = AccountFactory()
    leaving_actor = AccountFactory()

    for actor, terminal in (
        (accepted_actor, "accept"),
        (declined_actor, "decline"),
        (leaving_actor, "leave"),
    ):
        invited = invite_programme_proposal_collaborator(
            actor_id=world.lead.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            proposal_id=world.proposal_id,
            invitation=ProgrammeProposalInvitationInput(
                invitee_email=actor.email,
                expires_at=world.call.now + timedelta(days=1),
            ),
            expected_version=version,
            reason="Invite a replay-test collaborator.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=world.call.now,
            authorizer=_AUTHORIZER,
        )
        version = invited.resulting_version
        retry_key = uuid4()
        correlation_id = uuid4()
        response_command = (
            accept_programme_proposal_invitation
            if terminal in {"accept", "leave"}
            else decline_programme_proposal_invitation
        )
        response = response_command(
            actor_id=actor.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            proposal_id=world.proposal_id,
            expected_version=version,
            reason=f"{terminal.title()} the replay-test invitation.",
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel="test",
            now=world.call.now,
            authorizer=_AUTHORIZER,
        )
        replay = response_command(
            actor_id=actor.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            proposal_id=world.proposal_id,
            expected_version=version,
            reason=f"{terminal.title()} the replay-test invitation.",
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel="test",
            now=world.call.now,
            authorizer=_AUTHORIZER,
        )
        assert replay.replayed is True
        assert replay.receipt_id == response.receipt_id
        with pytest.raises(ApplicationsProgrammeIdempotencyConflictError):
            response_command(
                actor_id=actor.id,
                organization_id=world.call.edition.organization_id,
                edition_id=world.call.edition.id,
                proposal_id=world.proposal_id,
                expected_version=version,
                reason="A changed intent must collide.",
                retry_key=retry_key,
                correlation_id=correlation_id,
                source_channel="test",
                now=world.call.now,
                authorizer=_AUTHORIZER,
            )
        version = response.resulting_version
        if terminal == "decline":
            reinvited = reinvite_programme_proposal_collaborator(
                actor_id=world.lead.id,
                organization_id=world.call.edition.organization_id,
                edition_id=world.call.edition.id,
                proposal_id=world.proposal_id,
                invitation=ProgrammeProposalInvitationInput(
                    invitee_email=actor.email,
                    expires_at=world.call.now + timedelta(days=2),
                ),
                expected_version=version,
                reason="Reinvite after the retained terminal decline.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=world.call.now,
                authorizer=_AUTHORIZER,
            )
            collaborator = ProgrammeProposalCollaborator.objects.get(
                proposal_id=world.proposal_id,
                account_id=actor.id,
            )
            removed = remove_programme_proposal_collaborator(
                actor_id=world.lead.id,
                organization_id=world.call.edition.organization_id,
                edition_id=world.call.edition.id,
                proposal_id=world.proposal_id,
                collaborator_id=collaborator.id,
                expected_version=reinvited.resulting_version,
                reason="Remove the reinvited collaborator as the exact lead.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=world.call.now,
                authorizer=_AUTHORIZER,
            )
            version = removed.resulting_version
            continue
        if terminal != "leave":
            continue
        leave_key = uuid4()
        leave_correlation = uuid4()
        left = leave_programme_proposal(
            actor_id=actor.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            proposal_id=world.proposal_id,
            expected_version=version,
            reason="Leave the replay-test proposal.",
            retry_key=leave_key,
            correlation_id=leave_correlation,
            source_channel="test",
            now=world.call.now,
            authorizer=_AUTHORIZER,
        )
        leave_replay = leave_programme_proposal(
            actor_id=actor.id,
            organization_id=world.call.edition.organization_id,
            edition_id=world.call.edition.id,
            proposal_id=world.proposal_id,
            expected_version=version,
            reason="Leave the replay-test proposal.",
            retry_key=leave_key,
            correlation_id=leave_correlation,
            source_channel="test",
            now=world.call.now,
            authorizer=_AUTHORIZER,
        )
        assert leave_replay.replayed is True
        assert leave_replay.receipt_id == left.receipt_id
        version = left.resulting_version

    expired_actor = AccountFactory()
    invitation_now = _database_now()
    invitation_expiry = invitation_now + timedelta(seconds=2)
    invited = invite_programme_proposal_collaborator(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        invitation=ProgrammeProposalInvitationInput(
            invitee_email=expired_actor.email,
            expires_at=invitation_expiry,
        ),
        expected_version=version,
        reason="Create an invitation that expires before reinvitation.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=invitation_now,
        authorizer=_AUTHORIZER,
    )
    later = _wait_until_database_after(invitation_expiry)
    reinvited = reinvite_programme_proposal_collaborator(
        actor_id=world.lead.id,
        organization_id=world.call.edition.organization_id,
        edition_id=world.call.edition.id,
        proposal_id=world.proposal_id,
        invitation=ProgrammeProposalInvitationInput(
            invitee_email=expired_actor.email,
            expires_at=later + timedelta(days=1),
        ),
        expected_version=invited.resulting_version,
        reason="Reinvite after the derived expiry released its roster slot.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=later,
        authorizer=_AUTHORIZER,
    )
    assert (
        ProgrammeProposalCollaborator.objects.get(
            proposal_id=world.proposal_id,
            account_id=expired_actor.id,
        ).generation
        == 2
    )
    assert reinvited.resulting_version == invited.resulting_version + 1

    assert (
        ProgrammeProposalCollaborator.objects.filter(
            proposal_id=world.proposal_id,
            state__in=("removed", "left"),
        ).count()
        == 2
    )


def test_effect_failure_rolls_back_state_and_keeps_only_minimized_error_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep failure evidence after the whole success transaction rolls back."""
    edition = EventEditionFactory()
    manager = AccountFactory()
    department = create_department_for_test(
        edition=edition,
        name="Programme",
        expected_code="programme",
    )
    now = timezone.now()

    def reject(**_kwargs: object) -> None:
        raise ValidationError(
            "Synthetic effect admission failure.",
            code="synthetic_effect_failure",
        )

    monkeypatch.setattr(
        "maru.effects.services.require_effect_delivery_allowed",
        reject,
    )
    with pytest.raises(ValidationError):
        create_programme_call(
            actor_id=manager.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            definition_input=_definition(now, code="programme-rollback"),
            configuration=_configuration(department.id),
            expected_version=0,
            reason="Prove Programme success evidence rolls back atomically.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now,
            authorizer=_AUTHORIZER,
        )

    assert not ApplicationDefinition.objects.filter(edition_id=edition.id).exists()
    assert not ProgrammeCall.objects.filter(edition_id=edition.id).exists()
    assert not ProgrammeCommandReceipt.objects.filter(edition_id=edition.id).exists()
    assert not DomainEvent.objects.filter(
        event_edition_id=edition.id,
        event_name="applications.programme_call.changed.v1",
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_edition_id=edition.id,
        event__event_name="applications.programme_call.changed.v1",
    ).exists()
    audit = AuditEvent.objects.get(
        event_edition_id=edition.id,
        operation="applications.programme.command.call_created",
    )
    assert audit.outcome == AuditEvent.Outcome.ERROR
    assert audit.reason_code == "applications_programme_dependency_error"
    assert audit.target_type == "applications.programme.scope"
    assert audit.target_id is None
    assert audit.changed_fields == []


def test_foreign_and_missing_calls_have_indistinguishable_failure_evidence() -> None:
    """Do not disclose whether an unavailable call exists in another tenant."""
    foreign = _active_call(code="programme-foreign")
    local_edition = EventEditionFactory()
    actor = AccountFactory()
    profile = _profile("Scoped lead")
    selection = ProgrammeProposalSelectionInput(
        track_id=foreign.track_id,
        format_id=foreign.format_id,
        requested_duration_minutes=60,
    )

    for call_id in (foreign.call_id, uuid4()):
        with pytest.raises(ApplicationsProgrammeUnavailableError):
            start_programme_proposal(
                actor_id=actor.id,
                organization_id=local_edition.organization_id,
                edition_id=local_edition.id,
                call_id=call_id,
                selection=selection,
                lead_profile=profile,
                expected_version=0,
                reason="Exercise the non-disclosing unavailable-call boundary.",
                retry_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
                now=foreign.now,
                authorizer=_AUTHORIZER,
            )

    audits = tuple(
        AuditEvent.objects.filter(
            event_edition_id=local_edition.id,
            operation="applications.programme.command.proposal_started",
        ).order_by("occurred_at", "id")
    )
    assert len(audits) == 2
    assert {row.outcome for row in audits} == {AuditEvent.Outcome.ERROR}
    assert {row.reason_code for row in audits} == {"applications_programme_unavailable"}
    assert {row.target_type for row in audits} == {"applications.programme.scope"}
    assert {row.target_id for row in audits} == {None}
    assert not ProgrammeCommandReceipt.objects.filter(
        edition_id=local_edition.id
    ).exists()
    assert not DomainEvent.objects.filter(event_edition_id=local_edition.id).exists()
