"""PostgreSQL integration coverage for dormant Programme commands."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import (
    DatabaseError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import override_settings
from django.utils import timezone

import maru.effects.services as effect_services
import maru.programme.commands as programme_commands
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.adoption import (
    FULL_CONVENTION_PROFILE_VERSION,
    WORKFORCE_ONLY_PROFILE_VERSION,
    AdoptionProfileCode,
)
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.identity.models import Account
from maru.programme.authorization import (
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
)
from maru.programme.catalogs import (
    PROGRAMME_DELIVERY_REVISION_SOURCE,
    PROGRAMME_OPERATOR_ATTESTATION_SOURCE,
    PROGRAMME_PUBLIC_RENDITION_SOURCE,
    PROGRAMME_WORKING_REVISION_SOURCE,
    ProgrammeReadinessConcern,
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
)
from maru.programme.commands import (
    ProgrammeCommandResult,
    ProgrammeIdempotencyConflictError,
    ProgrammeLifecycleConflictError,
    ProgrammeUnavailableError,
    ProgrammeVersionConflictError,
    append_programme_discussion,
    approve_programme_public_rendition,
    configure_programme_readiness,
    create_organizer_core_item,
    record_programme_readiness_evidence,
    revise_programme_delivery,
    revise_programme_working,
)
from maru.programme.models import (
    ProgrammeCommandReceipt,
    ProgrammeDeliveryRevision,
    ProgrammeDepartmentDiscussionEntry,
    ProgrammeEditionControl,
    ProgrammeItem,
    ProgrammeItemSourceBinding,
    ProgrammePublicRendition,
    ProgrammeReadinessEvidence,
    ProgrammeReadinessRequirement,
    ProgrammeReadinessRequirementRevision,
    ProgrammeWorkingRevision,
)
from maru.programme.queries import list_programme_private_items
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

_EXCLUDED_PROGRAMME_APP_LABELS = (
    "applications",
    "participation",
    "registration",
    "accreditation",
    "catalog",
    "charities",
    "communications",
    "venues",
    "logistics",
    "workforce",
)


@dataclass
class _TrustedProgrammeAuthorizer:
    """Substitute only the not-yet-active exact-profile policy decision."""

    calls: list[tuple[str, frozenset[str] | None]] = field(default_factory=list)

    def authorize(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id
        self.calls.append((capability_code, requested_fields))
        return PolicyDecision(
            allowed=True,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit", "reason"}),
            reason_code="sealed_future_profile_harness",
        )


@dataclass
class _AllowThenDenyProgrammeAuthorizer:
    """Model authority becoming stale between admission and commit."""

    calls: int = 0

    def authorize(
        self,
        *,
        principal_id: UUID,
        organization_id: UUID,
        edition_id: UUID,
        capability_code: str,
        requested_fields: frozenset[str] | None,
    ) -> PolicyDecision:
        del principal_id, organization_id, edition_id, capability_code
        self.calls += 1
        return PolicyDecision(
            allowed=self.calls == 1,
            fields=requested_fields or frozenset(),
            obligations=frozenset({"audit", "reason"}),
            reason_code=(
                "synthetic_current_authority"
                if self.calls == 1
                else "synthetic_stale_authority"
            ),
        )


@pytest.fixture
def trusted_authorizer() -> _TrustedProgrammeAuthorizer:
    return _TrustedProgrammeAuthorizer()


@pytest.fixture
def admits_exact_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch only the future exact-profile effect-admission decision."""
    monkeypatch.setattr(
        effect_services,
        "require_effect_delivery_allowed",
        lambda **_kwargs: None,
    )


def _create(
    *,
    actor: Account,
    edition: EventEdition,
    authorizer: ProgrammeAuthorizer,
    title: str = "Opening ceremony working title",
    idempotency_key: UUID | None = None,
    correlation_id: UUID | None = None,
) -> tuple[ProgrammeCommandResult, UUID, UUID]:
    retry_key = idempotency_key or uuid4()
    correlation = correlation_id or uuid4()
    result = create_organizer_core_item(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind="ceremony",
        internal_title=title,
        working_summary="Private organizer notes.",
        expected_version=0,
        reason="Create the organizer-owned opening item.",
        idempotency_key=retry_key,
        correlation_id=correlation,
        source_channel="service",
        authorizer=authorizer,
    )
    return result, retry_key, correlation


def _assert_no_programme_domain_state() -> None:
    for model in (
        ProgrammeEditionControl,
        ProgrammeItem,
        ProgrammeItemSourceBinding,
        ProgrammeWorkingRevision,
        ProgrammeDeliveryRevision,
        ProgrammeDepartmentDiscussionEntry,
        ProgrammeReadinessRequirement,
        ProgrammeReadinessRequirementRevision,
        ProgrammeReadinessEvidence,
        ProgrammePublicRendition,
        ProgrammeCommandReceipt,
    ):
        assert model.objects.count() == 0


def _excluded_module_counts() -> dict[str, int]:
    return {
        model._meta.label_lower: model._default_manager.count()
        for app_label in _EXCLUDED_PROGRAMME_APP_LABELS
        for model in apps.get_app_config(app_label).get_models()
        if not model._meta.proxy
    }


def test_current_profile_denies_with_only_minimized_denial_audit() -> None:
    """Keep the real command core unreachable from every current profile."""
    actor = AccountFactory()
    edition = EventEditionFactory()

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        create_organizer_core_item(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            kind="break",
            internal_title="Private break",
            expected_version=0,
            reason="Create a bounded organizer break.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
        )

    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    audit = AuditEvent.objects.get(capability_code="programme.manage_items")
    assert audit.outcome == AuditEvent.Outcome.DENY
    assert audit.target_id is None
    assert audit.changed_fields == []
    assert audit.safe_metadata == {"policy_version": "2026-08-31.1"}


@pytest.mark.parametrize(
    ("profile_code", "profile_version"),
    [
        (
            AdoptionProfileCode.FULL_CONVENTION,
            FULL_CONVENTION_PROFILE_VERSION,
        ),
        (
            AdoptionProfileCode.WORKFORCE_ONLY,
            WORKFORCE_ONLY_PROFILE_VERSION,
        ),
    ],
)
def test_current_profile_ceiling_denies_exact_grants_before_command_or_query(
    profile_code: AdoptionProfileCode,
    profile_version: int,
) -> None:
    """Prove profile dormancy even when exact-edition authority is current."""
    actor = AccountFactory()
    edition = EventEditionFactory(
        adoption_profile_code=profile_code,
        adoption_profile_version=profile_version,
    )
    for capability_code in (
        "programme.manage_items",
        "programme.view_private",
    ):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=actor,
            capability_code=capability_code,
        )

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        create_organizer_core_item(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            kind="break",
            internal_title="Private current-grant item",
            expected_version=0,
            reason="Exercise the unsupported current profile ceiling.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
        )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        list_programme_private_items(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            reason="Attempt discovery under an unsupported current profile.",
        )

    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    audits = AuditEvent.objects.filter(
        capability_code__in=(
            "programme.manage_items",
            "programme.view_private",
        )
    )
    assert audits.count() == 2
    assert set(audits.values_list("outcome", flat=True)) == {AuditEvent.Outcome.DENY}
    assert all(audit.target_id is None for audit in audits)


def test_stale_authority_at_commit_rolls_back_before_success_evidence(
    admits_exact_effect: None,
) -> None:
    """Reauthorize inside the transaction and retain only a denial audit."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    authorizer = _AllowThenDenyProgrammeAuthorizer()

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        _create(actor=actor, edition=edition, authorizer=authorizer)

    assert authorizer.calls == 2
    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    audits = AuditEvent.objects.filter(capability_code="programme.manage_items")
    assert audits.count() == 1
    assert audits.get().outcome == AuditEvent.Outcome.DENY


@override_settings(MARU_ALLOW_PROGRAMME_TEST_AUTHORIZER=False)
def test_permissive_authorizer_is_sealed_without_test_only_setting() -> None:
    """Reject the complete-policy test seam before any read or write."""
    actor = AccountFactory()
    edition = EventEditionFactory()
    authorizer = _TrustedProgrammeAuthorizer()

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        _create(actor=actor, edition=edition, authorizer=authorizer)
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        list_programme_private_items(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            reason="Attempt a sealed test-authorizer disclosure.",
            authorizer=authorizer,
        )

    assert authorizer.calls == []
    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    assert AuditEvent.objects.filter(outcome=AuditEvent.Outcome.DENY).count() == 2


def test_real_current_profile_effect_gate_rolls_back_trusted_command_seam(
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Keep the real Effects profile gate authoritative over the test seam."""
    actor = AccountFactory()
    edition = EventEditionFactory()

    with pytest.raises(ValidationError) as raised:
        _create(
            actor=actor,
            edition=edition,
            authorizer=trusted_authorizer,
        )

    assert raised.value.code == "effect_profile_not_allowed"
    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    audit = AuditEvent.objects.get(capability_code="programme.manage_items")
    assert audit.outcome == AuditEvent.Outcome.ERROR
    assert audit.reason_code == "programme_dependency_error"


def test_create_exact_replay_precedes_stale_and_key_reuse_fails(
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Reauthorize, replay exactly, then reject different normalized input."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    first, retry_key, _correlation = _create(
        actor=actor,
        edition=edition,
        authorizer=trusted_authorizer,
    )

    replay = create_organizer_core_item(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind="ceremony",
        internal_title="Opening ceremony working title",
        working_summary="Private organizer notes.",
        expected_version=0,
        reason="Create the organizer-owned opening item.",
        idempotency_key=retry_key,
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )

    assert replay.replayed
    assert replay.receipt_id == first.receipt_id
    assert ProgrammeEditionControl.objects.get().aggregate_version == 1
    assert ProgrammeItem.objects.count() == 1
    assert ProgrammeCommandReceipt.objects.count() == 1
    assert (
        DomainEvent.objects.filter(event_name="programme.item.changed.v1").count() == 1
    )

    with pytest.raises(ProgrammeIdempotencyConflictError):
        create_organizer_core_item(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            kind="ceremony",
            internal_title="A different normalized title",
            working_summary="Private organizer notes.",
            expected_version=0,
            reason="Create the organizer-owned opening item.",
            idempotency_key=retry_key,
            correlation_id=uuid4(),
            source_channel="service",
            authorizer=trusted_authorizer,
        )

    assert ProgrammeItem.objects.count() == 1
    assert ProgrammeCommandReceipt.objects.count() == 1
    assert (
        AuditEvent.objects.filter(
            operation="programme.command.item_create",
            outcome=AuditEvent.Outcome.ERROR,
            reason_code="programme_idempotency_conflict",
        ).count()
        == 1
    )
    assert len(trusted_authorizer.calls) == 6


def test_concurrent_same_key_replays_one_canonical_programme_result(
    admits_exact_effect: None,
) -> None:
    """Serialize concurrent retries on the exact locked edition scope."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    idempotency_key = uuid4()
    start = Barrier(2)

    def invoke() -> ProgrammeCommandResult:
        close_old_connections()
        try:
            start.wait(timeout=5)
            result, _key, _correlation = _create(
                actor=actor,
                edition=edition,
                authorizer=_TrustedProgrammeAuthorizer(),
                idempotency_key=idempotency_key,
            )
            return result
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result()
            for future in [executor.submit(invoke) for _index in range(2)]
        ]

    assert sorted(result.replayed for result in results) == [False, True]
    assert len({result.item_id for result in results}) == 1
    assert len({result.receipt_id for result in results}) == 1
    assert ProgrammeItem.objects.count() == 1
    assert ProgrammeCommandReceipt.objects.count() == 1
    assert (
        DomainEvent.objects.filter(event_name="programme.item.changed.v1").count() == 1
    )
    assert (
        OutboxMessage.objects.filter(
            event__event_name="programme.item.changed.v1"
        ).count()
        == 1
    )
    assert (
        AuditEvent.objects.filter(
            operation="programme.command.item_create",
            outcome=AuditEvent.Outcome.ALLOW,
        ).count()
        == 1
    )


def test_programme_success_creates_no_excluded_module_rows(
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Snapshot representative excluded modules around a Programme command."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    before = _excluded_module_counts()

    _create(
        actor=actor,
        edition=edition,
        authorizer=trusted_authorizer,
    )

    after = _excluded_module_counts()
    assert after == before


def test_every_operation_obeys_guards_and_public_approval_is_non_mutating(  # noqa: PLR0915
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Exercise all seven operations through real PostgreSQL integrity guards."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    created, _key, _correlation = _create(
        actor=actor,
        edition=edition,
        authorizer=trusted_authorizer,
    )
    item = ProgrammeItem.objects.get(id=created.item_id)
    assert created.result_object_id == item.id

    configured_public = configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=1,
        reason="Require approved public copy.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    public_requirement = ProgrammeReadinessRequirement.objects.get(
        item=item,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY.value,
    )
    assert configured_public.result_object_id == public_requirement.revisions.get().id

    public_evidence = record_programme_readiness_evidence(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        state=ProgrammeReadinessEvidenceState.SATISFIED,
        evidence_note="Copy owner confirmed a draft exists.",
        source_code=PROGRAMME_OPERATOR_ATTESTATION_SOURCE,
        expected_version=2,
        reason="Record current public-copy evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    assert (
        public_evidence.result_object_id == public_requirement.evidence_entries.get().id
    )

    working = revise_programme_working(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        internal_title="Opening ceremony revised working title",
        working_summary="Updated private copy.",
        expected_version=3,
        reason="Revise the working layer.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    assert working.result_object_id == item.working_revisions.get(sequence=2).id
    public_requirement.refresh_from_db()
    assert public_requirement.requirement_version == 1
    assert public_requirement.dependency_version == 4
    assert public_requirement.item_version == 4

    first_technical_config = configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=4,
        reason="Require a technical delivery review.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    technical_requirement = ProgrammeReadinessRequirement.objects.get(
        item=item,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS.value,
    )
    assert (
        first_technical_config.result_object_id
        == technical_requirement.revisions.get(sequence=1).id
    )

    second_technical_config = configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=5,
        reason="Reconfirm the requirement with updated rationale.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    technical_requirement.refresh_from_db()
    assert technical_requirement.requirement_version == 2
    assert technical_requirement.dependency_version == 0
    assert (
        second_technical_config.result_object_id
        == technical_requirement.revisions.get(sequence=2).id
    )

    technical_evidence = record_programme_readiness_evidence(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
        state=ProgrammeReadinessEvidenceState.SATISFIED,
        evidence_note="Technical lead confirmed the current requirements.",
        expected_version=6,
        reason="Record technical readiness evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    assert (
        technical_evidence.result_object_id
        == technical_requirement.evidence_entries.get().id
    )

    delivery = revise_programme_delivery(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        technical_requirements="Two wired microphones and a lectern.",
        accessibility_delivery="Keep the front aisle clear.",
        expected_version=7,
        reason="Update exact delivery facts.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    assert delivery.result_object_id == item.delivery_revisions.get().id
    technical_requirement.refresh_from_db()
    public_requirement.refresh_from_db()
    assert technical_requirement.requirement_version == 2
    assert technical_requirement.dependency_version == 8
    assert technical_requirement.item_version == 8
    assert public_requirement.dependency_version == 4

    discussion = append_programme_discussion(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        body="Confirm the opening cue with the stage manager.",
        expected_version=8,
        reason="Retain the Programme Department decision trail.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    assert discussion.result_object_id == item.department_discussion_entries.get().id

    item.refresh_from_db()
    assert item.aggregate_version == 9
    latest_working = item.working_revisions.order_by("-sequence").first()
    assert latest_working is not None
    readiness_before = tuple(
        item.readiness_requirements.order_by("concern").values_list(
            "id",
            "requirement_version",
            "dependency_version",
            "item_version",
            "updated_at",
        )
    )
    item_updated_before = item.updated_at

    first_public = approve_programme_public_rendition(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        source_working_revision_id=latest_working.id,
        public_title="Opening Ceremony",
        public_summary="Welcome to the convention.",
        public_content_note="Reviewed attendee-facing copy.",
        expected_version=9,
        reason="Approve the first public rendition.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    second_public = approve_programme_public_rendition(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        source_working_revision_id=latest_working.id,
        public_title="Opening Ceremony and Welcome",
        public_summary="Join us as the convention begins.",
        public_content_note="Superseding reviewed copy.",
        expected_version=9,
        reason="Approve a superseding public rendition.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )

    item.refresh_from_db()
    assert item.aggregate_version == 9
    assert item.updated_at == item_updated_before
    assert (
        tuple(
            item.readiness_requirements.order_by("concern").values_list(
                "id",
                "requirement_version",
                "dependency_version",
                "item_version",
                "updated_at",
            )
        )
        == readiness_before
    )
    renditions = tuple(item.public_renditions.order_by("rendition_number"))
    assert [rendition.rendition_number for rendition in renditions] == [1, 2]
    assert renditions[1].supersedes_id == renditions[0].id
    assert first_public.result_object_id == renditions[0].id
    assert second_public.result_object_id == renditions[1].id
    assert first_public.resulting_item_version == 9
    assert second_public.resulting_item_version == 9
    public_receipts = ProgrammeCommandReceipt.objects.filter(
        operation="public_rendition_record"
    ).order_by("created_at")
    assert [
        (receipt.expected_version, receipt.resulting_item_version)
        for receipt in public_receipts
    ] == [(9, 9), (9, 9)]
    public_events = DomainEvent.objects.filter(
        event_name="programme.item.changed.v1",
        aggregate_type="programme.public_rendition",
    ).order_by("aggregate_version")
    assert [event.aggregate_id for event in public_events] == [item.id, item.id]
    assert [event.aggregate_version for event in public_events] == [1, 2]
    assert all(
        set(event.payload)
        == {"action", "layer", "item_kind", "provenance", "lifecycle", "concern"}
        for event in DomainEvent.objects.filter(event_name="programme.item.changed.v1")
    )


def test_malformed_and_stale_failures_append_only_error_audit(
    admits_exact_effect: None,
    caplog: pytest.LogCaptureFixture,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Classify failures without partial state or private error disclosure."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    private_marker = "PRIVATE-PROGRAMME-NOTE-DO-NOT-DISCLOSE"

    with pytest.raises(ValidationError) as malformed:
        create_organizer_core_item(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            kind="ceremony",
            internal_title=private_marker + ("x" * 241),
            expected_version=0,
            reason="Attempt malformed private input.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
            authorizer=trusted_authorizer,
        )

    assert private_marker not in str(malformed.value)
    assert private_marker not in repr(malformed.value)
    assert private_marker not in caplog.text
    _assert_no_programme_domain_state()
    assert (
        AuditEvent.objects.filter(
            outcome=AuditEvent.Outcome.ERROR,
            reason_code="programme_input_invalid",
        ).count()
        == 1
    )

    created, _key, _correlation = _create(
        actor=actor,
        edition=edition,
        authorizer=trusted_authorizer,
    )
    with pytest.raises(ProgrammeVersionConflictError) as stale:
        revise_programme_working(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=created.item_id,
            internal_title=f"{private_marker} stale attempted title",
            expected_version=0,
            reason="Exercise stale optimistic state.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
            authorizer=trusted_authorizer,
        )

    assert private_marker not in str(stale.value)
    assert private_marker not in repr(stale.value)
    assert private_marker not in caplog.text
    item = ProgrammeItem.objects.get(id=created.item_id)
    assert item.aggregate_version == 1
    assert item.working_revisions.count() == 1
    assert (
        AuditEvent.objects.filter(
            outcome=AuditEvent.Outcome.ERROR,
            reason_code="programme_version_conflict",
        ).count()
        == 1
    )


def test_readiness_source_versions_use_source_sequences_not_item_versions(
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Keep source cursors distinct after intervening aggregate commands."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    created, _key, _correlation = _create(
        actor=actor,
        edition=edition,
        authorizer=trusted_authorizer,
    )
    item = ProgrammeItem.objects.get(id=created.item_id)
    append_programme_discussion(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        body="Intervening discussion before a second working revision.",
        expected_version=1,
        reason="Separate source sequence from aggregate version.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=2,
        reason="Require source-version evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    revise_programme_working(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        internal_title="Second working revision",
        expected_version=3,
        reason="Create a divergent working source cursor.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    working_source = item.working_revisions.get(sequence=2)
    assert working_source.item_version == 4
    record_programme_readiness_evidence(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        state=ProgrammeReadinessEvidenceState.SATISFIED,
        source_code=PROGRAMME_WORKING_REVISION_SOURCE,
        source_object_id=working_source.id,
        source_version=2,
        expected_version=4,
        reason="Reference working sequence two, not item version four.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=5,
        reason="Require delivery-source evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    revise_programme_delivery(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        technical_requirements="One projector.",
        expected_version=6,
        reason="Create a divergent delivery source cursor.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    delivery_source = item.delivery_revisions.get(sequence=1)
    assert delivery_source.item_version == 7
    record_programme_readiness_evidence(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
        state=ProgrammeReadinessEvidenceState.SATISFIED,
        source_code=PROGRAMME_DELIVERY_REVISION_SOURCE,
        source_object_id=delivery_source.id,
        source_version=1,
        expected_version=7,
        reason="Reference delivery sequence one, not item version seven.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    approved = approve_programme_public_rendition(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        source_working_revision_id=working_source.id,
        public_title="Second Working Revision",
        expected_version=8,
        reason="Approve a source for readiness evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    rendition = ProgrammePublicRendition.objects.get(id=approved.result_object_id)
    assert rendition.rendition_number == 1
    assert rendition.source_item_version == 4
    record_programme_readiness_evidence(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        state=ProgrammeReadinessEvidenceState.SATISFIED,
        source_code=PROGRAMME_PUBLIC_RENDITION_SOURCE,
        source_object_id=rendition.id,
        source_version=1,
        expected_version=8,
        reason="Reference rendition number one, not source item version four.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )

    assert list(
        ProgrammeReadinessEvidence.objects.order_by("created_at").values_list(
            "source_code",
            "source_version",
        )
    ) == [
        (PROGRAMME_WORKING_REVISION_SOURCE, 2),
        (PROGRAMME_DELIVERY_REVISION_SOURCE, 1),
        (PROGRAMME_PUBLIC_RENDITION_SOURCE, 1),
    ]


def test_readiness_typed_sources_reject_wrong_concerns_and_old_dependencies(
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Bind typed evidence to both its concern and current dependency cursor."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    created, _key, _correlation = _create(
        actor=actor,
        edition=edition,
        authorizer=trusted_authorizer,
    )
    item = ProgrammeItem.objects.get(id=created.item_id)
    configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=1,
        reason="Configure working-copy readiness.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    revise_programme_working(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        internal_title="Current working dependency",
        expected_version=2,
        reason="Advance the public-copy dependency cursor.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=3,
        reason="Configure delivery readiness.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    revise_programme_delivery(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        technical_requirements="First delivery dependency",
        expected_version=4,
        reason="Create the first delivery dependency.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    revise_programme_delivery(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        technical_requirements="Current delivery dependency",
        expected_version=5,
        reason="Supersede the first delivery dependency.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    old_working = item.working_revisions.get(sequence=1)
    current_working = item.working_revisions.get(sequence=2)
    old_delivery = item.delivery_revisions.get(sequence=1)

    with pytest.raises(ProgrammeVersionConflictError):
        record_programme_readiness_evidence(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item.id,
            concern=ProgrammeReadinessConcern.PUBLIC_COPY,
            state=ProgrammeReadinessEvidenceState.SATISFIED,
            source_code=PROGRAMME_WORKING_REVISION_SOURCE,
            source_object_id=old_working.id,
            source_version=old_working.sequence,
            expected_version=6,
            reason="Reject an old working dependency.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
            authorizer=trusted_authorizer,
        )
    with pytest.raises(ProgrammeVersionConflictError):
        record_programme_readiness_evidence(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item.id,
            concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
            state=ProgrammeReadinessEvidenceState.SATISFIED,
            source_code=PROGRAMME_DELIVERY_REVISION_SOURCE,
            source_object_id=old_delivery.id,
            source_version=old_delivery.sequence,
            expected_version=6,
            reason="Reject an old delivery dependency.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
            authorizer=trusted_authorizer,
        )
    with pytest.raises(ValidationError) as wrong_concern:
        record_programme_readiness_evidence(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item.id,
            concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
            state=ProgrammeReadinessEvidenceState.SATISFIED,
            source_code=PROGRAMME_WORKING_REVISION_SOURCE,
            source_object_id=current_working.id,
            source_version=current_working.sequence,
            expected_version=6,
            reason="Reject a working source for a delivery concern.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
            authorizer=trusted_authorizer,
        )

    assert wrong_concern.value.code == "programme_evidence_source_concern_invalid"
    item.refresh_from_db()
    assert item.aggregate_version == 6
    assert not ProgrammeReadinessEvidence.objects.exists()
    assert ProgrammeCommandReceipt.objects.count() == 6
    error_audits = AuditEvent.objects.filter(
        operation="programme.command.readiness_record",
        outcome=AuditEvent.Outcome.ERROR,
    )
    assert error_audits.filter(reason_code="programme_version_conflict").count() == 2
    assert error_audits.filter(reason_code="programme_input_invalid").count() == 1


def test_new_requirements_bind_existing_working_and_delivery_sources(
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Permit typed evidence immediately after configure-after-source."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    created, _key, _correlation = _create(
        actor=actor,
        edition=edition,
        authorizer=trusted_authorizer,
    )
    item = ProgrammeItem.objects.get(id=created.item_id)
    working = item.working_revisions.get(sequence=1)
    configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=1,
        reason="Configure after the current working source exists.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    public_requirement = ProgrammeReadinessRequirement.objects.get(
        item=item,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
    )
    assert public_requirement.dependency_version == working.item_version == 1
    record_programme_readiness_evidence(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        state=ProgrammeReadinessEvidenceState.SATISFIED,
        source_code=PROGRAMME_WORKING_REVISION_SOURCE,
        source_object_id=working.id,
        source_version=working.sequence,
        expected_version=2,
        reason="Use the source current when the concern was configured.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    revise_programme_delivery(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        technical_requirements="Existing projector plan",
        expected_version=3,
        reason="Create delivery information before configuring its concern.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    delivery = item.delivery_revisions.get(sequence=1)
    configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=4,
        reason="Configure after the current delivery source exists.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )
    technical_requirement = ProgrammeReadinessRequirement.objects.get(
        item=item,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
    )
    assert technical_requirement.dependency_version == delivery.item_version == 4
    record_programme_readiness_evidence(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.TECHNICAL_NEEDS,
        state=ProgrammeReadinessEvidenceState.SATISFIED,
        source_code=PROGRAMME_DELIVERY_REVISION_SOURCE,
        source_object_id=delivery.id,
        source_version=delivery.sequence,
        expected_version=5,
        reason="Use the delivery source current at configuration.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )

    assert ProgrammeReadinessEvidence.objects.filter(item=item).count() == 2


def test_closed_edition_and_foreign_item_do_not_mutate_programme(
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Enforce lifecycle and exact tenant/edition item ownership independently."""
    del admits_exact_effect
    actor = AccountFactory()
    closed_edition = EventEditionFactory()
    CapabilityGrantFactory(
        organization=closed_edition.organization,
        edition=closed_edition,
        principal=actor,
        capability_code="events.transition",
    )
    for state in (
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
    ):
        closed_edition = transition_edition(
            organization_id=closed_edition.organization_id,
            edition_id=closed_edition.id,
            to_state=state,
            actor=actor,
            reason=f"Advance to {state} for the Programme lifecycle guard.",
            correlation_id=uuid4(),
        )

    with pytest.raises(ProgrammeLifecycleConflictError):
        _create(
            actor=actor,
            edition=closed_edition,
            authorizer=trusted_authorizer,
        )
    _assert_no_programme_domain_state()

    edition_a = EventEditionFactory()
    same_org_edition = EventEditionFactory(series=edition_a.series)
    foreign_org_edition = EventEditionFactory()
    created, _key, _correlation = _create(
        actor=actor,
        edition=edition_a,
        authorizer=trusted_authorizer,
    )
    for target_edition in (same_org_edition, foreign_org_edition):
        with pytest.raises(ProgrammeUnavailableError):
            revise_programme_working(
                actor_id=actor.id,
                organization_id=target_edition.organization_id,
                edition_id=target_edition.id,
                item_id=created.item_id,
                internal_title="Foreign attempted title",
                expected_version=1,
                reason="Exercise exact scope isolation.",
                idempotency_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="service",
                authorizer=trusted_authorizer,
            )
    item = ProgrammeItem.objects.get(id=created.item_id)
    assert item.aggregate_version == 1
    assert item.working_revisions.count() == 1


def test_publish_failure_rolls_back_success_and_keeps_error_audit(
    monkeypatch: pytest.MonkeyPatch,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Rollback item, receipt, success audit, event, and outbox as one unit."""
    actor = AccountFactory()
    edition = EventEditionFactory()

    def fail_effect_admission(**_kwargs: object) -> None:
        raise ValidationError(
            "Synthetic exact effect admission failure.",
            code="synthetic_effect_failure",
        )

    monkeypatch.setattr(
        effect_services,
        "require_effect_delivery_allowed",
        fail_effect_admission,
    )
    with pytest.raises(ValidationError) as raised:
        _create(
            actor=actor,
            edition=edition,
            authorizer=trusted_authorizer,
        )

    assert raised.value.code == "synthetic_effect_failure"
    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    audits = AuditEvent.objects.filter(capability_code="programme.manage_items")
    assert audits.count() == 1
    assert audits.get().outcome == AuditEvent.Outcome.ERROR
    assert audits.get().reason_code == "programme_dependency_error"


def test_domain_event_create_failure_rolls_back_the_complete_command(
    admits_exact_effect: None,
    monkeypatch: pytest.MonkeyPatch,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Rollback before an outbox row when DomainEvent persistence fails."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()

    def fail_event_create(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic_domain_event_unavailable")

    monkeypatch.setattr(DomainEvent.objects, "create", fail_event_create)
    with pytest.raises(RuntimeError, match="synthetic_domain_event_unavailable"):
        _create(
            actor=actor,
            edition=edition,
            authorizer=trusted_authorizer,
        )

    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    audit = AuditEvent.objects.get(capability_code="programme.manage_items")
    assert audit.outcome == AuditEvent.Outcome.ERROR
    assert audit.reason_code == "programme_dependency_error"


def test_outbox_create_failure_rolls_back_event_and_complete_command(
    admits_exact_effect: None,
    monkeypatch: pytest.MonkeyPatch,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Rollback the already-created event when outbox persistence fails."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()

    def fail_outbox_create(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic_outbox_unavailable")

    monkeypatch.setattr(OutboxMessage.objects, "create", fail_outbox_create)
    with pytest.raises(RuntimeError, match="synthetic_outbox_unavailable"):
        _create(
            actor=actor,
            edition=edition,
            authorizer=trusted_authorizer,
        )

    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    audit = AuditEvent.objects.get(capability_code="programme.manage_items")
    assert audit.outcome == AuditEvent.Outcome.ERROR
    assert audit.reason_code == "programme_dependency_error"


def test_audit_failure_rolls_back_and_preserves_original_failure(
    admits_exact_effect: None,
    monkeypatch: pytest.MonkeyPatch,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Do not replace the failing audit dependency with a partial success."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()

    def fail_audit(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic_audit_unavailable")

    monkeypatch.setattr(programme_commands, "append_audit", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic_audit_unavailable"):
        _create(
            actor=actor,
            edition=edition,
            authorizer=trusted_authorizer,
        )

    _assert_no_programme_domain_state()
    assert not DomainEvent.objects.filter(
        event_name="programme.item.changed.v1"
    ).exists()
    assert not OutboxMessage.objects.filter(
        event__event_name="programme.item.changed.v1"
    ).exists()
    assert not AuditEvent.objects.filter(
        capability_code="programme.manage_items"
    ).exists()


def test_inactive_actor_is_denied_before_trusted_policy() -> None:
    """The sealed profile harness cannot bypass current identity state."""
    actor = AccountFactory(is_active=False)
    edition = EventEditionFactory()
    authorizer = _TrustedProgrammeAuthorizer()

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        _create(actor=actor, edition=edition, authorizer=authorizer)

    _assert_no_programme_domain_state()
    assert authorizer.calls == []
    assert (
        AuditEvent.objects.filter(
            capability_code="programme.manage_items",
            outcome=AuditEvent.Outcome.DENY,
        ).count()
        == 1
    )


def test_inactive_historical_creator_does_not_freeze_later_item_updates(
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Validate the current modifier without reauthorizing historical actors."""
    del admits_exact_effect
    creator = AccountFactory()
    modifier = AccountFactory()
    edition = EventEditionFactory()
    created, _key, _correlation = _create(
        actor=creator,
        edition=edition,
        authorizer=trusted_authorizer,
    )
    creator.is_active = False
    creator.save(update_fields=("is_active",))

    revised = revise_programme_working(
        actor_id=modifier.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=created.item_id,
        internal_title="Updated after the original coordinator left",
        expected_version=1,
        reason="Keep Programme work transferable between coordinators.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=trusted_authorizer,
    )

    item = ProgrammeItem.objects.get(id=created.item_id)
    assert revised.resulting_item_version == 2
    assert item.created_by_id == creator.id
    assert item.last_modified_by_id == modifier.id
    assert item.aggregate_version == 2


def test_database_guard_rejects_over_limit_private_text_atomically(
    admits_exact_effect: None,
    trusted_authorizer: _TrustedProgrammeAuthorizer,
) -> None:
    """Enforce TextField ceilings even when SQL bypasses command validation."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    created, _key, _correlation = _create(
        actor=actor,
        edition=edition,
        authorizer=trusted_authorizer,
    )
    now = timezone.now()

    def attempt_over_limit_insert() -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE public.programme_programmeitem
                   SET aggregate_version = 2,
                       last_modified_by_id = %s,
                       updated_at = %s
                 WHERE id = %s
                """,
                [actor.id, now, created.item_id],
            )
            cursor.execute(
                """
                INSERT INTO public.programme_programmeworkingrevision(
                    id, created_at, updated_at, item_id, organization_id,
                    edition_id, sequence, item_version, internal_title,
                    working_summary, actor_id, reason, occurred_at
                ) VALUES (%s, %s, %s, %s, %s, %s, 2, 2, %s, %s, %s, %s, %s)
                """,
                [
                    uuid4(),
                    now,
                    now,
                    created.item_id,
                    edition.organization_id,
                    edition.id,
                    "Bounded title",
                    "x" * 2001,
                    actor.id,
                    "Exercise the database-owned text ceiling.",
                    now,
                ],
            )

    with pytest.raises(DatabaseError, match="exceeds its text ceiling"):
        attempt_over_limit_insert()

    item = ProgrammeItem.objects.get(id=created.item_id)
    assert item.aggregate_version == 1
    assert item.working_revisions.count() == 1
