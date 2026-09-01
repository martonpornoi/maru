"""PostgreSQL coverage for ceilinged Programme projections."""

from dataclasses import FrozenInstanceError, asdict, dataclass, field, fields
from datetime import timedelta
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

import maru.effects.services as effect_services
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.events.models import EventEdition
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.catalogs import (
    PROGRAMME_DELIVERY_HISTORY_FIELD_CEILING,
    PROGRAMME_LAYER_FIELD_CEILINGS,
    PROGRAMME_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING,
    PROGRAMME_READINESS_HISTORY_FIELD_CEILING,
    PROGRAMME_WORKING_HISTORY_FIELD_CEILING,
    ProgrammeInformationLayer,
    ProgrammeReadinessConcern,
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
)
from maru.programme.commands import (
    append_programme_discussion,
    approve_programme_public_rendition,
    configure_programme_readiness,
    create_organizer_core_item,
    record_programme_readiness_evidence,
    revise_programme_delivery,
    revise_programme_working,
)
from maru.programme.models import ProgrammeItem
from maru.programme.queries import (
    PROGRAMME_QUERY_DELIVERY_HISTORY_FIELD_CEILING,
    PROGRAMME_QUERY_FIELD_CEILINGS,
    PROGRAMME_QUERY_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING,
    PROGRAMME_QUERY_READINESS_HISTORY_FIELD_CEILING,
    PROGRAMME_QUERY_WORKING_HISTORY_FIELD_CEILING,
    ProgrammeDeliveryHistoryEntryProjection,
    ProgrammeDeliveryProjection,
    ProgrammeDiscussionEntryProjection,
    ProgrammeItemProjection,
    ProgrammePublicCopyProjection,
    ProgrammePublicCopyReviewHistoryEntryProjection,
    ProgrammeQueryUnavailableError,
    ProgrammeReadinessConcernProjection,
    ProgrammeReadinessHistoryEntryProjection,
    ProgrammeWorkingHistoryEntryProjection,
    ProgrammeWorkingProjection,
    list_programme_delivery_history,
    list_programme_discussion,
    list_programme_private_items,
    list_programme_public_copy_review_history,
    list_programme_readiness_history,
    list_programme_working_history,
    load_programme_delivery,
    load_programme_private_item,
    load_programme_public_copy,
    load_programme_readiness,
    programme_query_field_ceiling,
)
from tests.factories import AccountFactory, EventEditionFactory

pytestmark = pytest.mark.django_db(transaction=True)


@dataclass
class _TrustedAuthorizer:
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
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="sealed_future_profile_harness",
        )


@dataclass
class _AllowThenDenyAuthorizer:
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
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code=("synthetic_allow" if self.calls == 1 else "synthetic_deny"),
        )


@pytest.fixture
def admits_exact_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        effect_services,
        "require_effect_delivery_allowed",
        lambda **_kwargs: None,
    )


def _projection_field_names(projection_type: type[object]) -> frozenset[str]:
    return frozenset(field_info.name for field_info in fields(projection_type))


def _create_layered_item(
    *,
    actor_id: UUID,
    authorizer: _TrustedAuthorizer,
    edition: EventEdition,
) -> ProgrammeItem:
    created = create_organizer_core_item(
        actor_id=actor_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind="announcement",
        internal_title="PRIVATE unreleased announcement",
        working_summary="PRIVATE organizer-only working summary.",
        expected_version=0,
        reason="Create private query evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=authorizer,
    )
    item = ProgrammeItem.objects.get(id=created.item_id)
    revise_programme_delivery(
        actor_id=actor_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        technical_requirements="PRIVATE radio channel 7.",
        accessibility_delivery="PRIVATE delivery coordination note.",
        expected_version=1,
        reason="Retain separate delivery evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=authorizer,
    )
    append_programme_discussion(
        actor_id=actor_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        body="PRIVATE Department discussion body.",
        expected_version=2,
        reason="Retain separate discussion evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=authorizer,
    )
    configure_programme_readiness(
        actor_id=actor_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=3,
        reason="Require reviewed copy.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=authorizer,
    )
    record_programme_readiness_evidence(
        actor_id=actor_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.PUBLIC_COPY,
        state=ProgrammeReadinessEvidenceState.SATISFIED,
        evidence_note="PRIVATE evidence note.",
        expected_version=4,
        reason="Confirm reviewed-copy readiness.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=authorizer,
    )
    source = item.working_revisions.get(sequence=1)
    approve_programme_public_rendition(
        actor_id=actor_id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        source_working_revision_id=source.id,
        public_title="Public Announcement",
        public_summary="Attendee-safe summary.",
        public_content_note="Reviewed public note.",
        expected_version=5,
        reason="Approve attendee-safe fields only.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=authorizer,
    )
    item.refresh_from_db()
    return item


def test_projection_types_match_separate_immutable_field_ceilings() -> None:
    """Prevent a generic projection from accumulating unrelated private fields."""
    assert isinstance(PROGRAMME_QUERY_FIELD_CEILINGS, MappingProxyType)
    assert PROGRAMME_QUERY_FIELD_CEILINGS is PROGRAMME_LAYER_FIELD_CEILINGS
    assert _projection_field_names(ProgrammeItemProjection) == (
        programme_query_field_ceiling(ProgrammeInformationLayer.ITEM.value)
    )
    assert _projection_field_names(ProgrammeWorkingProjection) == (
        programme_query_field_ceiling(ProgrammeInformationLayer.WORKING.value)
    )
    assert _projection_field_names(ProgrammeWorkingHistoryEntryProjection) == (
        PROGRAMME_WORKING_HISTORY_FIELD_CEILING
    )
    assert PROGRAMME_QUERY_WORKING_HISTORY_FIELD_CEILING is (
        PROGRAMME_WORKING_HISTORY_FIELD_CEILING
    )
    assert _projection_field_names(ProgrammeDeliveryProjection) == (
        programme_query_field_ceiling(ProgrammeInformationLayer.DELIVERY.value)
    )
    assert _projection_field_names(ProgrammeDeliveryHistoryEntryProjection) == (
        PROGRAMME_DELIVERY_HISTORY_FIELD_CEILING
    )
    assert PROGRAMME_QUERY_DELIVERY_HISTORY_FIELD_CEILING is (
        PROGRAMME_DELIVERY_HISTORY_FIELD_CEILING
    )
    assert _projection_field_names(ProgrammeDiscussionEntryProjection) == (
        programme_query_field_ceiling(
            ProgrammeInformationLayer.DEPARTMENT_DISCUSSION.value
        )
    )
    assert _projection_field_names(ProgrammeReadinessConcernProjection) == (
        programme_query_field_ceiling(ProgrammeInformationLayer.READINESS.value)
    )
    assert _projection_field_names(ProgrammeReadinessHistoryEntryProjection) == (
        PROGRAMME_READINESS_HISTORY_FIELD_CEILING
    )
    assert PROGRAMME_QUERY_READINESS_HISTORY_FIELD_CEILING is (
        PROGRAMME_READINESS_HISTORY_FIELD_CEILING
    )
    assert _projection_field_names(ProgrammePublicCopyProjection) == (
        programme_query_field_ceiling(ProgrammeInformationLayer.PUBLIC_RENDITION.value)
    )
    assert (
        _projection_field_names(ProgrammePublicCopyReviewHistoryEntryProjection)
        == PROGRAMME_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING
    )
    assert PROGRAMME_QUERY_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING is (
        PROGRAMME_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING
    )
    assert programme_query_field_ceiling("unknown") == frozenset()
    assert all(
        "percentage" not in ceiling and "score" not in ceiling
        for ceiling in PROGRAMME_QUERY_FIELD_CEILINGS.values()
    )


def test_public_copy_absence_is_uniform_and_never_probes_private_items(
    admits_exact_effect: None,
) -> None:
    """Make absent and out-of-scope item identifiers indistinguishable at C0."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    sibling_edition = EventEditionFactory(series__organization=edition.organization)
    foreign_edition = EventEditionFactory()
    setup_authorizer = _TrustedAuthorizer()

    def create_unapproved(source_edition: EventEdition) -> UUID:
        return create_organizer_core_item(
            actor_id=actor.id,
            organization_id=source_edition.organization_id,
            edition_id=source_edition.id,
            kind="announcement",
            internal_title="PRIVATE unapproved item",
            working_summary="PRIVATE working summary.",
            expected_version=0,
            reason="Create a public-copy indistinguishability fixture.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
            authorizer=setup_authorizer,
        ).item_id

    identifiers = (
        create_unapproved(edition),
        uuid4(),
        create_unapproved(sibling_edition),
        create_unapproved(foreign_edition),
    )
    query_authorizer = _TrustedAuthorizer()

    with CaptureQueriesContext(connection) as captured:
        results = tuple(
            load_programme_public_copy(
                actor_id=actor.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                item_id=item_id,
                authorizer=query_authorizer,
            )
            for item_id in identifiers
        )

    assert results == (None, None, None, None)
    programme_selects = [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].lstrip().upper().startswith("SELECT")
        and '"programme_' in query["sql"]
    ]
    assert len(programme_selects) == 4
    for sql in programme_selects:
        assert '"programme_programmepublicrendition"' in sql
        assert '"programme_programmeitem"' not in sql
        selected_columns = sql.partition(" FROM ")[0]
        assert selected_columns.count('"programme_programmepublicrendition".') == 4
        assert '"rendition_number"' in selected_columns
        assert '"public_title"' in selected_columns
        assert '"public_summary"' in selected_columns
        assert '"public_content_note"' in selected_columns
    assert len(query_authorizer.calls) == 8


def test_current_profile_query_denies_before_programme_disclosure() -> None:
    """Current manifests cannot discover item counts, identifiers, or status."""
    actor = AccountFactory()
    edition = EventEditionFactory()

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        list_programme_private_items(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            reason="Attempt current-profile discovery.",
        )

    audit = AuditEvent.objects.get(capability_code="programme.view_private")
    assert audit.outcome == AuditEvent.Outcome.DENY
    assert audit.target_id is None
    assert audit.safe_metadata == {"policy_version": "2026-08-31.1"}


def test_layer_queries_are_separate_reauthorized_audited_and_content_safe(  # noqa: PLR0915
    admits_exact_effect: None,
) -> None:
    """Release each private layer only through its own complete projection."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    authorizer = _TrustedAuthorizer()
    item = _create_layered_item(
        actor_id=actor.id,
        authorizer=authorizer,
        edition=edition,
    )
    authorizer.calls.clear()

    private = load_programme_private_item(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Edit private Programme copy.",
        authorizer=authorizer,
    )
    delivery = load_programme_delivery(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Coordinate approved delivery details.",
        authorizer=authorizer,
    )
    discussion = list_programme_discussion(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Review Department decisions.",
        authorizer=authorizer,
    )
    readiness = load_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Review evidence-backed readiness.",
        authorizer=authorizer,
    )
    working_history = list_programme_working_history(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Inspect retained working rationale.",
        limit=1,
        authorizer=authorizer,
    )
    delivery_history = list_programme_delivery_history(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Inspect retained delivery rationale.",
        limit=1,
        authorizer=authorizer,
    )
    public_review_history = list_programme_public_copy_review_history(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Inspect retained public-copy approval rationale.",
        limit=1,
        authorizer=authorizer,
    )
    with CaptureQueriesContext(connection) as public_queries:
        public = load_programme_public_copy(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item.id,
            authorizer=authorizer,
        )

    assert private.item.aggregate_version == 5
    assert private.working is not None
    assert private.working.internal_title == "PRIVATE unreleased announcement"
    assert delivery is not None
    assert delivery.technical_requirements == "PRIVATE radio channel 7."
    assert [entry.sequence for entry in discussion] == [1]
    assert discussion[0].body == "PRIVATE Department discussion body."
    assert discussion[0].reason == "Retain separate discussion evidence."
    assert [fact.concern for fact in readiness] == ["public_copy"]
    assert readiness[0].state == "satisfied"
    assert public is not None
    assert working_history[0].reason == "Create private query evidence."
    assert working_history[0].actor_id == actor.id
    assert delivery_history[0].reason == "Retain separate delivery evidence."
    assert delivery_history[0].actor_id == actor.id
    assert public_review_history[0].reason == "Approve attendee-safe fields only."
    assert public_review_history[0].source_item_version == 1
    assert public_review_history[0].actor_id == actor.id
    assert "source_working_revision_id" not in asdict(public_review_history[0])
    assert asdict(public) == {
        "rendition_number": 1,
        "public_title": "Public Announcement",
        "public_summary": "Attendee-safe summary.",
        "public_content_note": "Reviewed public note.",
    }
    serialized_public = repr(public)
    assert "PRIVATE" not in serialized_public
    assert "evidence note" not in serialized_public
    assert "Approve attendee-safe" not in serialized_public
    rendition_selects = [
        query["sql"]
        for query in public_queries.captured_queries
        if query["sql"].lstrip().upper().startswith("SELECT")
        and '"programme_programmepublicrendition"' in query["sql"]
    ]
    assert len(rendition_selects) == 1
    selected_columns = rendition_selects[0].partition(" FROM ")[0]
    for restricted_column in (
        "source_item_version",
        "source_working_revision_id",
        "supersedes_id",
        "reviewed_by_id",
        "reviewed_at",
        "review_reason",
    ):
        assert restricted_column not in selected_columns
    with pytest.raises(FrozenInstanceError):
        public.public_title = "Changed"  # type: ignore[misc]

    assert len(authorizer.calls) == 16
    assert ("programme.view_private", frozenset({"working_history"})) in (
        authorizer.calls
    )
    assert (
        "programme.view_private",
        frozenset({"public_copy_review_history"}),
    ) in authorizer.calls
    assert ("programme.view_delivery", frozenset({"delivery_history"})) in (
        authorizer.calls
    )
    query_audits = AuditEvent.objects.filter(operation__startswith="programme.query.")
    assert query_audits.count() == 7
    assert set(query_audits.values_list("outcome", flat=True)) == {
        AuditEvent.Outcome.ALLOW
    }
    assert all("audit_sensitive_read" in audit.obligations for audit in query_audits)
    assert not query_audits.filter(operation="programme.query.public_copy").exists()


def test_list_is_bounded_deterministic_and_reauthorized(
    admits_exact_effect: None,
) -> None:
    """Order tenant-first item projections and call policy before and after load."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    setup_authorizer = _TrustedAuthorizer()
    first = _create_layered_item(
        actor_id=actor.id,
        authorizer=setup_authorizer,
        edition=edition,
    )
    second = create_organizer_core_item(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        kind="break",
        internal_title="Second private item",
        expected_version=1,
        reason="Create another bounded item.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=setup_authorizer,
    )
    query_authorizer = _TrustedAuthorizer()

    with CaptureQueriesContext(connection) as captured:
        projections = list_programme_private_items(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            reason="Review the private item queue.",
            limit=2,
            authorizer=query_authorizer,
        )

    assert [projection.item.id for projection in projections] == [
        first.id,
        second.item_id,
    ]
    assert len(query_authorizer.calls) == 2
    programme_selects = [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].lstrip().upper().startswith("SELECT")
        and '"programme_' in query["sql"]
    ]
    assert len(programme_selects) == 1
    assert '"programme_programmeworkingrevision"' in programme_selects[0]
    assert len(captured) <= 16


def test_readiness_summary_is_explainable_stale_and_constant_query_count(
    admits_exact_effect: None,
) -> None:
    """Expose evidence cursors and project staleness without per-row queries."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    authorizer = _TrustedAuthorizer()
    item = _create_layered_item(
        actor_id=actor.id,
        authorizer=authorizer,
        edition=edition,
    )
    revise_programme_working(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        internal_title="Changed after readiness evidence",
        expected_version=5,
        reason="Invalidate only the dependent public-copy evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=authorizer,
    )
    configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.HOST_CONFIRMATION,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=6,
        reason="Add a second concern to exercise bounded projection.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=authorizer,
    )
    query_authorizer = _TrustedAuthorizer()

    with CaptureQueriesContext(connection) as captured:
        readiness = load_programme_readiness(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item.id,
            reason="Explain the stale readiness state.",
            authorizer=query_authorizer,
        )

    public_copy = next(fact for fact in readiness if fact.concern == "public_copy")
    assert public_copy.state == "stale"
    assert public_copy.requirement_version == 1
    assert public_copy.dependency_version == 6
    assert public_copy.evidence_requirement_version == 1
    assert public_copy.evidence_dependency_version == 1
    assert public_copy.source_code == "programme.evidence.operator-attestation@1"
    assert public_copy.source_version is None
    assert len(query_authorizer.calls) == 2
    programme_selects = [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].lstrip().upper().startswith("SELECT")
        and '"programme_' in query["sql"]
    ]
    assert len(programme_selects) == 2
    assert len(captured) <= 16


def test_readiness_history_is_separate_bounded_audited_and_rationale_complete(
    admits_exact_effect: None,
) -> None:
    """Return inspectable requirement/evidence history only on its own field."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    setup_authorizer = _TrustedAuthorizer()
    item = _create_layered_item(
        actor_id=actor.id,
        authorizer=setup_authorizer,
        edition=edition,
    )
    query_authorizer = _TrustedAuthorizer()

    with CaptureQueriesContext(connection) as captured:
        history = list_programme_readiness_history(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item.id,
            reason="Inspect the readiness rationale layer.",
            limit=2,
            authorizer=query_authorizer,
        )

    assert [entry.kind for entry in history] == [
        "evidence",
        "requirement_revision",
    ]
    evidence, requirement = history
    assert requirement.concern == "public_copy"
    assert requirement.requirement_version == 1
    assert requirement.disposition == "required"
    assert requirement.reason == "Require reviewed copy."
    assert requirement.note == ""
    assert evidence.concern == "public_copy"
    assert evidence.state == "satisfied"
    assert evidence.requirement_version == 1
    assert evidence.dependency_version == 1
    assert evidence.note == "PRIVATE evidence note."
    assert evidence.reason == "Confirm reviewed-copy readiness."
    assert "source_object_id" not in asdict(evidence)
    assert len(query_authorizer.calls) == 2
    programme_selects = [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].lstrip().upper().startswith(("SELECT", "WITH"))
        and "programme_" in query["sql"]
    ]
    assert len(programme_selects) == 1
    assert "UNION ALL" in programme_selects[0]
    assert "programme_programmereadinessrequirementrevision" in programme_selects[0]
    assert "programme_programmereadinessevidence" in programme_selects[0]
    audit = AuditEvent.objects.get(operation="programme.query.readiness_history")
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.safe_metadata["target_count"] == 2

    limited = list_programme_readiness_history(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Exercise the deterministic history limit.",
        limit=1,
        authorizer=_TrustedAuthorizer(),
    )
    assert limited == (evidence,)

    configure_programme_readiness(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        concern=ProgrammeReadinessConcern.HOST_CONFIRMATION,
        disposition=ProgrammeReadinessDisposition.REQUIRED,
        expected_version=5,
        reason="Record a later item version with an intentionally older clock.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        now=evidence.occurred_at - timedelta(days=1),
        authorizer=setup_authorizer,
    )
    newest = list_programme_readiness_history(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        item_id=item.id,
        reason="Order history by authoritative aggregate sequence.",
        limit=1,
        authorizer=_TrustedAuthorizer(),
    )
    assert newest[0].concern == "host_confirmation"
    assert newest[0].item_version == 6
    assert newest[0].occurred_at < evidence.occurred_at


def test_postauthorization_denial_releases_no_projection_or_allow_audit(
    admits_exact_effect: None,
) -> None:
    """Discard loaded private state when authority changes before disclosure."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    setup_authorizer = _TrustedAuthorizer()
    item = _create_layered_item(
        actor_id=actor.id,
        authorizer=setup_authorizer,
        edition=edition,
    )
    query_authorizer = _AllowThenDenyAuthorizer()

    with pytest.raises(ProgrammeAuthorizationDeniedError):
        load_programme_private_item(
            actor_id=actor.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            item_id=item.id,
            reason="Exercise disclosure-time reauthorization.",
            authorizer=query_authorizer,
        )

    assert query_authorizer.calls == 2
    audits = AuditEvent.objects.filter(operation="programme.query.private_item")
    assert audits.count() == 1
    assert audits.get().outcome == AuditEvent.Outcome.DENY


def test_foreign_item_identifier_returns_only_unavailable_shape(
    admits_exact_effect: None,
) -> None:
    """Do not disclose a foreign tenant's item through an authorized scope."""
    del admits_exact_effect
    actor = AccountFactory()
    edition_a = EventEditionFactory()
    edition_b = EventEditionFactory()
    setup_authorizer = _TrustedAuthorizer()
    foreign_item = _create_layered_item(
        actor_id=actor.id,
        authorizer=setup_authorizer,
        edition=edition_a,
    )
    query_authorizer = _TrustedAuthorizer()

    with pytest.raises(ProgrammeQueryUnavailableError) as raised:
        load_programme_private_item(
            actor_id=actor.id,
            organization_id=edition_b.organization_id,
            edition_id=edition_b.id,
            item_id=foreign_item.id,
            reason="Exercise exact tenant isolation.",
            authorizer=query_authorizer,
        )

    assert str(raised.value) == ""
    assert not AuditEvent.objects.filter(
        operation="programme.query.private_item"
    ).exists()


def test_list_and_detail_isolate_two_organizations_and_same_org_editions(
    admits_exact_effect: None,
) -> None:
    """Scope list and non-disclosing detail reads to one exact edition."""
    del admits_exact_effect
    actor = AccountFactory()
    edition = EventEditionFactory()
    sibling_edition = EventEditionFactory(series=edition.series)
    foreign_edition = EventEditionFactory()
    setup_authorizer = _TrustedAuthorizer()
    local = _create_layered_item(
        actor_id=actor.id,
        authorizer=setup_authorizer,
        edition=edition,
    )
    sibling = create_organizer_core_item(
        actor_id=actor.id,
        organization_id=sibling_edition.organization_id,
        edition_id=sibling_edition.id,
        kind="break",
        internal_title="SIBLING EDITION PRIVATE TITLE",
        expected_version=0,
        reason="Create a same-organization foreign-edition item.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=setup_authorizer,
    )
    foreign = create_organizer_core_item(
        actor_id=actor.id,
        organization_id=foreign_edition.organization_id,
        edition_id=foreign_edition.id,
        kind="break",
        internal_title="FOREIGN ORGANIZATION PRIVATE TITLE",
        expected_version=0,
        reason="Create a foreign-organization item.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="service",
        authorizer=setup_authorizer,
    )
    query_authorizer = _TrustedAuthorizer()

    listed = list_programme_private_items(
        actor_id=actor.id,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        reason="Review only this exact edition.",
        authorizer=query_authorizer,
    )

    assert [projection.item.id for projection in listed] == [local.id]
    for foreign_item_id in (sibling.item_id, foreign.item_id):
        with pytest.raises(ProgrammeQueryUnavailableError) as raised:
            load_programme_private_item(
                actor_id=actor.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                item_id=foreign_item_id,
                reason="Exercise non-disclosing exact-edition isolation.",
                authorizer=query_authorizer,
            )
        assert str(raised.value) == ""
        assert "PRIVATE TITLE" not in repr(raised.value)
        with pytest.raises(ProgrammeQueryUnavailableError) as history_raised:
            list_programme_working_history(
                actor_id=actor.id,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                item_id=foreign_item_id,
                reason="Exercise private-history exact-edition isolation.",
                authorizer=query_authorizer,
            )
        assert str(history_raised.value) == ""
