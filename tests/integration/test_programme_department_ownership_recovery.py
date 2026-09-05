"""Historical-orphan acceptance for Programme Department ownership recovery."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.applications import programme_commands as programme_command_services
from maru.applications.models import (
    ApplicationDefinition,
    ApplicationOwnerDepartment,
    ProgrammeCall,
    ProgrammeCommandReceipt,
)
from maru.applications.programme_commands import (
    activate_programme_call,
    create_programme_call,
    recover_orphaned_programme_call_reassignment,
    recover_orphaned_programme_call_retirement,
)
from maru.applications.programme_department_dependencies import (
    ProgrammeDepartmentDependencyState,
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
)
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent
from maru.workforce import structure_commands as workforce_structure_commands
from tests.factories import AccountFactory, EventEditionFactory
from tests.workforce_helpers import (
    create_department_for_test,
    retire_department_for_test,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

_WORKFORCE_BEFORE_OWNERSHIP_CONTRACT = (
    "workforce",
    "0017_programme_import_department_fk_contract",
)
_WORKFORCE_OWNERSHIP_CONTRACT = (
    "workforce",
    "0018_programme_department_ownership_contract",
)
_RECOVERY_CAPABILITY = "applications.recover_programme_department_ownership"


@dataclass(frozen=True, slots=True)
class _AllowExactRecoveryAuthorizer:
    """Prove recovery and destination management through distinct seams."""

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
        """Allow an exact current Department after production resolution."""
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
        """Retain the complete protocol without granting a recovery shortcut."""
        del (
            principal_id,
            owner_account_id,
            organization_id,
            edition_id,
            capability_code,
        )
        return self._decision(requested_fields)

    def authorize_recovery(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        """Allow the separate exact-Edition break-glass factor."""
        del principal_id, organization_id, edition_id
        return self._decision(requested_fields)

    def authorize_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Allow ordinary receipt replay for setup commands."""
        del principal_id, organization_id, edition_id
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="sealed_programme_retry_test",
        )

    def authorize_recovery_retry(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
    ) -> PolicyDecision:
        """Re-prove recovery authority before reading a retained receipt."""
        del principal_id, organization_id, edition_id
        return PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset({"audit"}),
            reason_code="sealed_programme_recovery_retry_test",
        )

    @staticmethod
    def _decision(requested_fields: frozenset[str] | None) -> PolicyDecision:
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit", "audit_sensitive_read"}),
            reason_code="sealed_programme_recovery_test",
        )


_AUTHORIZER = _AllowExactRecoveryAuthorizer()


@pytest.fixture(autouse=True)
def _admit_future_programme_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mount only the dormant effect route needed by command acceptance."""

    def allow(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "maru.effects.services.require_effect_delivery_allowed",
        allow,
    )


@dataclass(frozen=True, slots=True)
class _HistoricalOrphanWorld:
    """Identifiers retained after advancing the historical schema to current."""

    organization_id: UUID
    edition_id: UUID
    actor_id: UUID
    source_department_id: UUID
    destination_department_id: UUID
    draft_call_id: UUID
    draft_definition_id: UUID
    draft_version: int
    active_call_id: UUID
    active_definition_id: UUID
    active_version: int


def _definition(*, code: str) -> ProgrammeCallDefinitionInput:
    now = timezone.now()
    return ProgrammeCallDefinitionInput(
        code=code,
        name="Programme proposals",
        description="Historical orphan recovery fixture.",
        purpose="Exercise exact-ID Programme ownership recovery.",
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
                questions=(
                    ProgrammeCallQuestionInput(
                        key="session-title",
                        field_type=ProgrammeCallQuestionType.SHORT_TEXT,
                        label="Session title",
                        help_text="Use the attendee-facing title.",
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
                        purpose="Collect the title required for review.",
                        classification=ProgrammeCallClassification.PERSONAL,
                        retention_policy_code="",
                    ),
                ),
            ),
        ),
    )


def _configuration(department_id: UUID) -> ProgrammeCallConfigurationInput:
    return ProgrammeCallConfigurationInput(
        owner_department_id=department_id,
        maximum_collaborators=4,
        content_policy_code="applications.programme.content.v1",
        contributor_consent_policy_code=(
            "applications.programme.contributor-consent.v1"
        ),
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
                collaborator_requirement=(
                    ProgrammeContributorFieldRequirement.REQUIRED
                ),
                position=1,
            ),
        ),
    )


def _migrate_workforce(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor


def _seed_historical_orphans(
    monkeypatch: pytest.MonkeyPatch,
) -> _HistoricalOrphanWorld:
    edition = EventEditionFactory()
    actor = AccountFactory(display_name="Programme recovery operator")
    source = create_department_for_test(
        edition=edition,
        name="Historical Programme",
        expected_code="historical-programme",
    )
    destination = create_department_for_test(
        edition=edition,
        name="Current Events",
        expected_code="current-events",
    )

    historical_executor = _migrate_workforce(_WORKFORCE_BEFORE_OWNERSHIP_CONTRACT)
    historical_apps = historical_executor.loader.project_state(
        [_WORKFORCE_BEFORE_OWNERSHIP_CONTRACT]
    ).apps
    assert (
        _WORKFORCE_OWNERSHIP_CONTRACT
        not in MigrationExecutor(connection).loader.applied_migrations
    )

    draft = create_programme_call(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        definition_input=_definition(code="historical-draft-orphan"),
        configuration=_configuration(source.id),
        expected_version=0,
        reason="Create the draft before the retirement backstop existed.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    active = create_programme_call(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        definition_input=_definition(code="historical-active-orphan"),
        configuration=_configuration(source.id),
        expected_version=0,
        reason="Create the active call before the retirement backstop existed.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    activated = activate_programme_call(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        call_id=active.target_id,
        owner_department_id=source.id,
        expected_version=active.resulting_version,
        reason="Activate the historical recovery fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_AUTHORIZER,
    )

    monkeypatch.setattr(
        workforce_structure_commands,
        "programme_department_retirement_dependency_state",
        lambda **_kwargs: ProgrammeDepartmentDependencyState.CLEAR,
    )
    retired_source = retire_department_for_test(department=source)
    historical_department = historical_apps.get_model("workforce", "Department")
    assert retired_source.retired_at is not None
    assert historical_department.objects.get(id=source.id).retired_at is not None

    _migrate_workforce(_WORKFORCE_OWNERSHIP_CONTRACT)
    assert (
        _WORKFORCE_OWNERSHIP_CONTRACT
        in MigrationExecutor(connection).loader.applied_migrations
    )
    return _HistoricalOrphanWorld(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor_id=actor.id,
        source_department_id=source.id,
        destination_department_id=destination.id,
        draft_call_id=draft.target_id,
        draft_definition_id=draft.definition_id,
        draft_version=draft.resulting_version,
        active_call_id=active.target_id,
        active_definition_id=active.definition_id,
        active_version=activated.resulting_version,
    )


def _assert_recovery_evidence(
    *,
    action: str,
    correlation_id: UUID,
    receipt_id: UUID,
    call_id: UUID,
    resulting_version: int,
    lifecycle: str,
    source_department_id: UUID,
    destination_department_id: UUID | None,
) -> None:
    receipt = ProgrammeCommandReceipt.objects.get(id=receipt_id)
    assert receipt.action == action
    assert receipt.source_department_id == source_department_id
    assert receipt.destination_department_id == destination_department_id
    audit = AuditEvent.objects.get(
        operation=f"applications.programme.command.{action}",
        correlation_id=correlation_id,
    )
    assert audit.capability_code == _RECOVERY_CAPABILITY
    assert audit.break_glass is True
    event = DomainEvent.objects.get(
        event_name="applications.programme_call.changed.v1",
        correlation_id=correlation_id,
    )
    assert event.payload == {
        "action": action,
        "call_id": str(call_id),
        "lifecycle": lifecycle,
        "resulting_version": str(resulting_version),
    }


def test_historical_orphans_recover_by_exact_id_with_break_glass_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _seed_historical_orphans(monkeypatch)
    draft_retry_key = uuid4()
    draft_correlation_id = uuid4()
    draft_reason = "Recover the exact draft into the current Events Department."
    recovered_draft = recover_orphaned_programme_call_reassignment(
        actor_id=world.actor_id,
        organization_id=world.organization_id,
        edition_id=world.edition_id,
        call_id=world.draft_call_id,
        source_department_id=world.source_department_id,
        destination_department_id=world.destination_department_id,
        expected_version=world.draft_version,
        reason=draft_reason,
        retry_key=draft_retry_key,
        correlation_id=draft_correlation_id,
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    moved_draft = ProgrammeCall.objects.select_related("definition").get(
        id=world.draft_call_id
    )
    assert moved_draft.owner_department_id == world.destination_department_id
    assert moved_draft.definition.status == "draft"
    assert moved_draft.definition.aggregate_version == world.draft_version + 1
    assert (
        ApplicationOwnerDepartment.objects.get(
            definition_id=world.draft_definition_id
        ).department_id
        == world.destination_department_id
    )
    _assert_recovery_evidence(
        action="recovery_call_reassigned",
        correlation_id=draft_correlation_id,
        receipt_id=recovered_draft.receipt_id,
        call_id=world.draft_call_id,
        resulting_version=recovered_draft.resulting_version,
        lifecycle="draft",
        source_department_id=world.source_department_id,
        destination_department_id=world.destination_department_id,
    )

    retirement_retry_key = uuid4()
    retirement_correlation_id = uuid4()
    retirement_reason = "Retire the exact active orphan without reopening it."
    retired_call = recover_orphaned_programme_call_retirement(
        actor_id=world.actor_id,
        organization_id=world.organization_id,
        edition_id=world.edition_id,
        call_id=world.active_call_id,
        source_department_id=world.source_department_id,
        expected_version=world.active_version,
        reason=retirement_reason,
        retry_key=retirement_retry_key,
        correlation_id=retirement_correlation_id,
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    retired_definition = ApplicationDefinition.objects.get(
        id=world.active_definition_id
    )
    assert retired_definition.status == "retired"
    assert retired_definition.aggregate_version == world.active_version + 1
    assert ProgrammeCall.objects.get(id=world.active_call_id).owner_department_id == (
        world.source_department_id
    )
    _assert_recovery_evidence(
        action="recovery_call_retired",
        correlation_id=retirement_correlation_id,
        receipt_id=retired_call.receipt_id,
        call_id=world.active_call_id,
        resulting_version=retired_call.resulting_version,
        lifecycle="retired",
        source_department_id=world.source_department_id,
        destination_department_id=None,
    )

    def unexpected_scope_lock(**_kwargs: object) -> None:
        raise AssertionError("successful recovery replay reacquired the edition mutex")

    monkeypatch.setattr(
        programme_command_services,
        "_lock_programme_write_scope",
        unexpected_scope_lock,
    )
    replayed_draft = recover_orphaned_programme_call_reassignment(
        actor_id=world.actor_id,
        organization_id=world.organization_id,
        edition_id=world.edition_id,
        call_id=world.draft_call_id,
        source_department_id=world.source_department_id,
        destination_department_id=world.destination_department_id,
        expected_version=world.draft_version,
        reason=draft_reason,
        retry_key=draft_retry_key,
        correlation_id=draft_correlation_id,
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    replayed_retirement = recover_orphaned_programme_call_retirement(
        actor_id=world.actor_id,
        organization_id=world.organization_id,
        edition_id=world.edition_id,
        call_id=world.active_call_id,
        source_department_id=world.source_department_id,
        expected_version=world.active_version,
        reason=retirement_reason,
        retry_key=retirement_retry_key,
        correlation_id=retirement_correlation_id,
        source_channel="test",
        authorizer=_AUTHORIZER,
    )
    assert replayed_draft == replace(recovered_draft, replayed=True)
    assert replayed_retirement == replace(retired_call, replayed=True)
    assert (
        ProgrammeCommandReceipt.objects.filter(
            action__in=("recovery_call_reassigned", "recovery_call_retired"),
            definition_id__in=(
                world.draft_definition_id,
                world.active_definition_id,
            ),
        ).count()
        == 2
    )
