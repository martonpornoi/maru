"""Authorized, field-ceiling projections for private Programme layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4

from django.db import connection, transaction
from django.db.models import OuterRef, QuerySet, Subquery

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_DELIVERY,
    PROGRAMME_VIEW_DISCUSSION,
    PROGRAMME_VIEW_PRIVATE,
    PROGRAMME_VIEW_PUBLIC_COPY,
    PROGRAMME_VIEW_READINESS,
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDenied,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.catalogs import (
    PROGRAMME_DELIVERY_HISTORY_FIELD_CEILING,
    PROGRAMME_LAYER_FIELD_CEILINGS,
    PROGRAMME_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING,
    PROGRAMME_READINESS_HISTORY_FIELD_CEILING,
    PROGRAMME_WORKING_HISTORY_FIELD_CEILING,
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
)
from maru.programme.inputs import (
    normalized_source_channel,
    normalized_text,
    require_uuid,
)
from maru.programme.models import (
    ProgrammeDeliveryRevision,
    ProgrammeDepartmentDiscussionEntry,
    ProgrammeItem,
    ProgrammePublicRendition,
    ProgrammeReadinessEvidence,
    ProgrammeReadinessRequirement,
    ProgrammeWorkingRevision,
)
from maru.programme.readiness import project_readiness_state

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

MAX_PROGRAMME_QUERY_ITEMS: Final = 200
_MAX_AUDIT_PURPOSE_LENGTH: Final = 160

PROGRAMME_QUERY_FIELD_CEILINGS: Final = PROGRAMME_LAYER_FIELD_CEILINGS
PROGRAMME_QUERY_READINESS_HISTORY_FIELD_CEILING: Final = (
    PROGRAMME_READINESS_HISTORY_FIELD_CEILING
)
PROGRAMME_QUERY_WORKING_HISTORY_FIELD_CEILING: Final = (
    PROGRAMME_WORKING_HISTORY_FIELD_CEILING
)
PROGRAMME_QUERY_DELIVERY_HISTORY_FIELD_CEILING: Final = (
    PROGRAMME_DELIVERY_HISTORY_FIELD_CEILING
)
PROGRAMME_QUERY_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING: Final = (
    PROGRAMME_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING
)


class ProgrammeQueryError(RuntimeError):
    """Base class for stable, non-content Programme read failures."""


class ProgrammeQueryUnavailableError(ProgrammeQueryError):
    """Hide whether a requested tenant-scoped item or layer exists."""

    reason_code = "programme_query_unavailable"


@dataclass(frozen=True, slots=True)
class ProgrammeItemProjection:
    """Generic title-free item fields allowed by the item layer ceiling.

    Attributes
    ----------
    id
        The opaque Programme item identifier.
    kind
        The closed organizer or accepted-item kind.
    provenance_kind
        The immutable structural provenance kind.
    lifecycle
        The current closed item lifecycle.
    aggregate_version
        The current optimistic item version.
    """

    id: UUID
    kind: str
    provenance_kind: str
    lifecycle: str
    aggregate_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeWorkingProjection:
    """Latest private working fields, structurally separate from delivery.

    Attributes
    ----------
    internal_title
        The latest private working title.
    working_summary
        The latest private working summary.
    item_version
        The item version that produced this working revision.
    """

    internal_title: str
    working_summary: str
    item_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeWorkingHistoryEntryProjection:
    """One retained private working revision and its rationale.

    Attributes
    ----------
    sequence
        The contiguous working-revision sequence.
    internal_title
        The retained private working title.
    working_summary
        The retained private working summary.
    actor_id
        The opaque actor identifier for the revision.
    reason
        The retained reason for the revision.
    occurred_at
        The authoritative revision timestamp.
    item_version
        The item version that produced the revision.
    """

    sequence: int
    internal_title: str
    working_summary: str
    actor_id: UUID
    reason: str
    occurred_at: datetime
    item_version: int


@dataclass(frozen=True, slots=True)
class ProgrammePrivateItemProjection:
    """Combine separately ceilinged item and working projections.

    Attributes
    ----------
    item
        The generic title-free item projection.
    working
        The latest working projection when one exists.
    """

    item: ProgrammeItemProjection
    working: ProgrammeWorkingProjection | None


@dataclass(frozen=True, slots=True)
class ProgrammeDeliveryProjection:
    """Latest technical/accessibility delivery facts only.

    Attributes
    ----------
    technical_requirements
        The latest bounded technical-delivery facts.
    accessibility_delivery
        The latest delivery instruction without diagnosis data.
    media_consent_notes
        The latest bounded media-consent delivery note.
    item_version
        The item version that produced this delivery revision.
    """

    technical_requirements: str
    accessibility_delivery: str
    media_consent_notes: str
    item_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeDeliveryHistoryEntryProjection:
    """One retained delivery revision and its rationale.

    Attributes
    ----------
    sequence
        The contiguous delivery-revision sequence.
    technical_requirements
        The retained bounded technical-delivery facts.
    accessibility_delivery
        The retained accessibility-delivery instruction.
    media_consent_notes
        The retained bounded media-consent note.
    actor_id
        The opaque actor identifier for the revision.
    reason
        The retained reason for the revision.
    occurred_at
        The authoritative revision timestamp.
    item_version
        The item version that produced the revision.
    """

    sequence: int
    technical_requirements: str
    accessibility_delivery: str
    media_consent_notes: str
    actor_id: UUID
    reason: str
    occurred_at: datetime
    item_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeDiscussionEntryProjection:
    """One bounded Department discussion entry with retained rationale.

    Attributes
    ----------
    sequence
        The contiguous discussion-entry sequence.
    body
        The bounded decision-focused discussion body.
    actor_id
        The opaque actor identifier for the entry.
    reason
        The retained reason for the entry.
    occurred_at
        The authoritative entry timestamp.
    item_version
        The item version that produced the entry.
    """

    sequence: int
    body: str
    actor_id: UUID
    reason: str
    occurred_at: datetime
    item_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeReadinessConcernProjection:
    """One score-free readiness state and its current/source versions.

    Attributes
    ----------
    concern
        The closed readiness concern code.
    state
        The explainable projected readiness state.
    requirement_version
        The current positive requirement version.
    dependency_version
        The current non-negative dependency cursor.
    evidence_requirement_version
        The requirement version evaluated by the latest evidence.
    evidence_dependency_version
        The dependency version evaluated by the latest evidence.
    source_code
        The closed evidence-source code when evidence exists.
    source_version
        The source sequence or rendition number when evidence exists.
    """

    concern: str
    state: str
    requirement_version: int
    dependency_version: int
    evidence_requirement_version: int | None
    evidence_dependency_version: int | None
    source_code: str | None
    source_version: int | None


@dataclass(frozen=True, slots=True)
class ProgrammeReadinessHistoryEntryProjection:
    """One bounded rationale or evidence entry from readiness history.

    Attributes
    ----------
    concern
        The closed readiness concern code.
    kind
        Whether the entry is configuration or evidence history.
    sequence
        The concern-local contiguous history sequence.
    item_version
        The authoritative item version for global ordering.
    requirement_version
        The requirement version represented by the entry.
    dependency_version
        The dependency cursor represented by the entry, when applicable.
    disposition
        The retained requirement disposition, when applicable.
    state
        The retained evidence state, when applicable.
    source_code
        The retained closed evidence-source code, when applicable.
    source_version
        The retained source sequence or rendition number, when applicable.
    note
        The bounded evidence note, or an empty configuration note.
    actor_id
        The opaque actor identifier for the entry.
    reason
        The retained rationale for the entry.
    occurred_at
        The authoritative entry timestamp.
    """

    concern: str
    kind: str
    sequence: int
    item_version: int
    requirement_version: int
    dependency_version: int | None
    disposition: str | None
    state: str | None
    source_code: str | None
    source_version: int | None
    note: str
    actor_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ProgrammePublicCopyProjection:
    """Only fields explicitly approved in the latest public rendition.

    Attributes
    ----------
    rendition_number
        The latest immutable public-copy rendition number.
    public_title
        The explicitly approved public title.
    public_summary
        The explicitly approved public summary.
    public_content_note
        The explicitly approved bounded content note.
    """

    rendition_number: int
    public_title: str
    public_summary: str
    public_content_note: str


@dataclass(frozen=True, slots=True)
class ProgrammePublicCopyReviewHistoryEntryProjection:
    """One private public-copy review record and retained rationale.

    Attributes
    ----------
    rendition_number
        The immutable rendition number.
    source_item_version
        The item version reviewed for this rendition.
    public_title
        The approved title retained by the rendition.
    public_summary
        The approved summary retained by the rendition.
    public_content_note
        The approved bounded content note retained by the rendition.
    actor_id
        The opaque reviewer identifier.
    reason
        The retained review rationale.
    occurred_at
        The authoritative review timestamp.
    """

    rendition_number: int
    source_item_version: int
    public_title: str
    public_summary: str
    public_content_note: str
    actor_id: UUID
    reason: str
    occurred_at: datetime


def programme_query_field_ceiling(layer: str) -> frozenset[str]:
    """Return the immutable field ceiling for one information layer.

    Parameters
    ----------
    layer : str
        The closed Programme information-layer code.

    Returns
    -------
    frozenset[str]
        The immutable field ceiling, or an empty set for an unknown layer.
    """
    return PROGRAMME_QUERY_FIELD_CEILINGS.get(layer, frozenset())


def _bounded_limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_PROGRAMME_QUERY_ITEMS:
        raise ValueError(
            f"Programme query limit must be between 1 and {MAX_PROGRAMME_QUERY_ITEMS}."
        )
    return value


def _item_projection(item: ProgrammeItem) -> ProgrammeItemProjection:
    return ProgrammeItemProjection(
        id=item.id,
        kind=item.kind,
        provenance_kind=item.provenance_kind,
        lifecycle=item.lifecycle,
        aggregate_version=item.aggregate_version,
    )


def _private_item_queryset(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> QuerySet[ProgrammeItem]:
    latest_working = ProgrammeWorkingRevision.objects.filter(
        item_id=OuterRef("pk"),
        organization_id=organization_id,
        edition_id=edition_id,
    ).order_by("-sequence", "-id")
    return ProgrammeItem.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
    ).annotate(
        latest_working_internal_title=Subquery(
            latest_working.values("internal_title")[:1]
        ),
        latest_working_summary=Subquery(latest_working.values("working_summary")[:1]),
        latest_working_item_version=Subquery(latest_working.values("item_version")[:1]),
    )


def _private_item_projection(item: ProgrammeItem) -> ProgrammePrivateItemProjection:
    latest_item_version = item.latest_working_item_version  # type: ignore[attr-defined]
    working = (
        None
        if latest_item_version is None
        else ProgrammeWorkingProjection(
            internal_title=item.latest_working_internal_title,  # type: ignore[attr-defined]
            working_summary=item.latest_working_summary,  # type: ignore[attr-defined]
            item_version=latest_item_version,
        )
    )
    return ProgrammePrivateItemProjection(
        item=_item_projection(item),
        working=working,
    )


def _append_query_audit(
    *,
    scope: AuthorizedProgrammeScope,
    capability_code: str,
    operation: str,
    target_type: str,
    target_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    reason: str,
    target_count: int,
) -> None:
    obligations = frozenset(scope.decision.obligations) | {"audit_sensitive_read"}
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(obligations)),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": reason,
                "target_count": target_count,
            },
            retention_class="programme-restricted",
        )
    )


def _append_query_denial_audit(
    *,
    actor_id: object,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    operation: str,
    correlation_id: UUID,
    source_channel: str,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=(actor_id if isinstance(actor_id, UUID) else None),
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type="programme.scope",
            target_id=None,
            outcome="deny",
            reason_code=ProgrammeAuthorizationDenied.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="programme-restricted",
        )
    )


def _authorized_query[ProjectionT](
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    requested_fields: frozenset[str],
    operation: str,
    loader: Callable[[], ProjectionT],
    target_type: str,
    target_id: UUID,
    target_count: Callable[[ProjectionT], int],
    reason: str,
    correlation_id: UUID | None,
    source_channel: str,
    authorizer: ProgrammeAuthorizer,
    sensitive: bool = True,
) -> ProjectionT:
    organization_id = require_uuid(organization_id, field="organization_id")
    edition_id = require_uuid(edition_id, field="edition_id")
    correlation_id = (
        require_uuid(correlation_id, field="correlation_id")
        if correlation_id is not None
        else uuid4()
    )
    source_channel = normalized_source_channel(source_channel)
    try:
        authorize_programme_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            requested_fields=requested_fields,
            authorizer=authorizer,
        )
    except ProgrammeAuthorizationDenied:
        _append_query_denial_audit(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        raise
    normalized_purpose = (
        normalized_text(
            reason,
            field="reason",
            maximum=_MAX_AUDIT_PURPOSE_LENGTH,
            required=True,
            collapse=True,
        )
        if sensitive
        else "programme_public_copy"
    )
    try:
        with transaction.atomic():
            projection = loader()
            scope = authorize_programme_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=capability_code,
                requested_fields=requested_fields,
                authorizer=authorizer,
            )
            if sensitive:
                _append_query_audit(
                    scope=scope,
                    capability_code=capability_code,
                    operation=operation,
                    target_type=target_type,
                    target_id=target_id,
                    correlation_id=correlation_id,
                    source_channel=source_channel,
                    reason=normalized_purpose,
                    target_count=target_count(projection),
                )
            return projection
    except ProgrammeAuthorizationDenied:
        _append_query_denial_audit(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        raise


def list_programme_private_items(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    reason: str,
    limit: int = 100,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammePrivateItemProjection, ...]:
    """List private item summaries with only their latest working copy.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    reason : str
        The retained sensitive-read purpose.
    limit : int, default=100
        The bounded maximum number of projections.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    tuple[ProgrammePrivateItemProjection, ...]
        Deterministically ordered private item projections.
    """

    def load() -> tuple[ProgrammePrivateItemProjection, ...]:
        items = tuple(
            _private_item_queryset(
                organization_id=organization_id,
                edition_id=edition_id,
            ).order_by("created_at", "id")[: _bounded_limit(limit)]
        )
        return tuple(_private_item_projection(item) for item in items)

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=frozenset({"item_summaries", "working_information"}),
        operation="programme.query.private_items",
        loader=load,
        target_type="events.edition",
        target_id=edition_id,
        target_count=len,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def load_programme_private_item(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    reason: str,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammePrivateItemProjection:
    """Load one private item without adjacent-layer or tenant disclosure.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    reason : str
        The retained sensitive-read purpose.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammePrivateItemProjection
        The item and separately ceilinged latest working projection.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> ProgrammePrivateItemProjection:
        item = (
            _private_item_queryset(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .filter(id=item_id)
            .first()
        )
        if item is None:
            raise ProgrammeQueryUnavailableError
        return _private_item_projection(item)

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=frozenset({"item_summaries", "working_information"}),
        operation="programme.query.private_item",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda _projection: 1,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def load_programme_delivery(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    reason: str,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeDeliveryProjection | None:
    """Load only the latest separately authorized delivery revision.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    reason : str
        The retained sensitive-read purpose.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammeDeliveryProjection | None
        The latest delivery projection, or ``None`` when no revision exists.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> ProgrammeDeliveryProjection | None:
        if not ProgrammeItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).exists():
            raise ProgrammeQueryUnavailableError
        revision = (
            ProgrammeDeliveryRevision.objects.filter(
                item_id=item_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .order_by("-sequence", "-id")
            .first()
        )
        if revision is None:
            return None
        return ProgrammeDeliveryProjection(
            technical_requirements=revision.technical_requirements,
            accessibility_delivery=revision.accessibility_delivery,
            media_consent_notes=revision.media_consent_notes,
            item_version=revision.item_version,
        )

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_DELIVERY,
        requested_fields=frozenset({"delivery_information"}),
        operation="programme.query.delivery",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda projection: int(projection is not None),
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def list_programme_working_history(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    reason: str,
    limit: int = 100,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeWorkingHistoryEntryProjection, ...]:
    """List bounded private working revisions with retained rationale.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    reason : str
        The retained sensitive-read purpose.
    limit : int, default=100
        The bounded maximum number of history entries.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    tuple[ProgrammeWorkingHistoryEntryProjection, ...]
        Newest-first working revisions with retained rationale.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> tuple[ProgrammeWorkingHistoryEntryProjection, ...]:
        if not ProgrammeItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).exists():
            raise ProgrammeQueryUnavailableError
        revisions = ProgrammeWorkingRevision.objects.filter(
            item_id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("-sequence", "-id")[: _bounded_limit(limit)]
        return tuple(
            ProgrammeWorkingHistoryEntryProjection(
                sequence=revision.sequence,
                internal_title=revision.internal_title,
                working_summary=revision.working_summary,
                actor_id=revision.actor_id,
                reason=revision.reason,
                occurred_at=revision.occurred_at,
                item_version=revision.item_version,
            )
            for revision in revisions
        )

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=frozenset({"working_history"}),
        operation="programme.query.working_history",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=len,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def list_programme_delivery_history(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    reason: str,
    limit: int = 100,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeDeliveryHistoryEntryProjection, ...]:
    """List bounded delivery revisions with retained rationale.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    reason : str
        The retained sensitive-read purpose.
    limit : int, default=100
        The bounded maximum number of history entries.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    tuple[ProgrammeDeliveryHistoryEntryProjection, ...]
        Newest-first delivery revisions with retained rationale.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> tuple[ProgrammeDeliveryHistoryEntryProjection, ...]:
        if not ProgrammeItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).exists():
            raise ProgrammeQueryUnavailableError
        revisions = ProgrammeDeliveryRevision.objects.filter(
            item_id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("-sequence", "-id")[: _bounded_limit(limit)]
        return tuple(
            ProgrammeDeliveryHistoryEntryProjection(
                sequence=revision.sequence,
                technical_requirements=revision.technical_requirements,
                accessibility_delivery=revision.accessibility_delivery,
                media_consent_notes=revision.media_consent_notes,
                actor_id=revision.actor_id,
                reason=revision.reason,
                occurred_at=revision.occurred_at,
                item_version=revision.item_version,
            )
            for revision in revisions
        )

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_DELIVERY,
        requested_fields=frozenset({"delivery_history"}),
        operation="programme.query.delivery_history",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=len,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def list_programme_discussion(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    reason: str,
    limit: int = 100,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeDiscussionEntryProjection, ...]:
    """List bounded Department discussion with retained rationale.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    reason : str
        The retained sensitive-read purpose.
    limit : int, default=100
        The bounded maximum number of discussion entries.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    tuple[ProgrammeDiscussionEntryProjection, ...]
        Newest-first Department discussion entries with rationale.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> tuple[ProgrammeDiscussionEntryProjection, ...]:
        if not ProgrammeItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).exists():
            raise ProgrammeQueryUnavailableError
        entries = ProgrammeDepartmentDiscussionEntry.objects.filter(
            item_id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("-sequence", "-id")[: _bounded_limit(limit)]
        return tuple(
            ProgrammeDiscussionEntryProjection(
                sequence=entry.sequence,
                body=entry.body,
                actor_id=entry.actor_id,
                reason=entry.reason,
                occurred_at=entry.occurred_at,
                item_version=entry.item_version,
            )
            for entry in entries
        )

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_DISCUSSION,
        requested_fields=frozenset({"discussion_entries"}),
        operation="programme.query.discussion",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=len,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def load_programme_readiness(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    reason: str,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeReadinessConcernProjection, ...]:
    """Project every concern as a deterministic explainable state.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    reason : str
        The retained sensitive-read purpose.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    tuple[ProgrammeReadinessConcernProjection, ...]
        Concern-ordered readiness states with evidence/dependency cursors.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> tuple[ProgrammeReadinessConcernProjection, ...]:
        if not ProgrammeItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).exists():
            raise ProgrammeQueryUnavailableError
        latest_evidence = ProgrammeReadinessEvidence.objects.filter(
            requirement_id=OuterRef("pk"),
            item_id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("-sequence", "-id")
        requirements = (
            ProgrammeReadinessRequirement.objects.filter(
                item_id=item_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .annotate(
                latest_evidence_state=Subquery(latest_evidence.values("state")[:1]),
                latest_evidence_requirement_version=Subquery(
                    latest_evidence.values("requirement_version")[:1]
                ),
                latest_evidence_dependency_version=Subquery(
                    latest_evidence.values("dependency_version")[:1]
                ),
                latest_evidence_source_code=Subquery(
                    latest_evidence.values("source_code")[:1]
                ),
                latest_evidence_source_version=Subquery(
                    latest_evidence.values("source_version")[:1]
                ),
            )
            .order_by("concern", "id")
        )
        projections: list[ProgrammeReadinessConcernProjection] = []
        for requirement in requirements:
            evidence_state = requirement.latest_evidence_state
            evidence_requirement_version = (
                requirement.latest_evidence_requirement_version
            )
            evidence_dependency_version = requirement.latest_evidence_dependency_version
            projected = project_readiness_state(
                disposition=ProgrammeReadinessDisposition(requirement.disposition),
                requirement_version=requirement.requirement_version,
                dependency_version=requirement.dependency_version,
                evidence_state=(
                    ProgrammeReadinessEvidenceState(evidence_state)
                    if evidence_state is not None
                    else None
                ),
                evidence_requirement_version=evidence_requirement_version,
                evidence_dependency_version=evidence_dependency_version,
            )
            projections.append(
                ProgrammeReadinessConcernProjection(
                    concern=requirement.concern,
                    state=projected.state.value,
                    requirement_version=requirement.requirement_version,
                    dependency_version=requirement.dependency_version,
                    evidence_requirement_version=evidence_requirement_version,
                    evidence_dependency_version=evidence_dependency_version,
                    source_code=requirement.latest_evidence_source_code,
                    source_version=requirement.latest_evidence_source_version,
                )
            )
        return tuple(projections)

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_READINESS,
        requested_fields=frozenset({"readiness_summary"}),
        operation="programme.query.readiness",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=len,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def list_programme_readiness_history(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    reason: str,
    limit: int = 100,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeReadinessHistoryEntryProjection, ...]:
    """List readiness rationales and evidence without source identities.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    reason : str
        The retained sensitive-read purpose.
    limit : int, default=100
        The bounded maximum number of history entries.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    tuple[ProgrammeReadinessHistoryEntryProjection, ...]
        Newest-first requirement revisions and evidence with rationale.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> tuple[ProgrammeReadinessHistoryEntryProjection, ...]:
        bounded_limit = _bounded_limit(limit)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH scoped_item AS (
                    SELECT item.id
                      FROM public.programme_programmeitem AS item
                     WHERE item.id = %s
                       AND item.organization_id = %s
                       AND item.edition_id = %s
                )
                SELECT history.concern,
                       history.kind,
                       history.sequence,
                       history.item_version,
                       history.requirement_version,
                       history.dependency_version,
                       history.disposition,
                       history.state,
                       history.source_code,
                       history.source_version,
                       history.note,
                       history.actor_id,
                       history.reason,
                       history.occurred_at
                  FROM scoped_item
                  LEFT JOIN LATERAL (
                    SELECT combined.concern,
                           combined.kind,
                           combined.sequence,
                           combined.item_version,
                           combined.requirement_version,
                           combined.dependency_version,
                           combined.disposition,
                           combined.state,
                           combined.source_code,
                           combined.source_version,
                           combined.note,
                           combined.actor_id,
                           combined.reason,
                           combined.occurred_at
                      FROM (
                        SELECT requirement.concern,
                               'requirement_revision'::varchar AS kind,
                               revision.sequence,
                               revision.item_version,
                               revision.sequence AS requirement_version,
                               NULL::bigint AS dependency_version,
                               revision.disposition,
                               NULL::varchar AS state,
                               NULL::varchar AS source_code,
                               NULL::bigint AS source_version,
                               ''::text AS note,
                               revision.actor_id,
                               revision.reason,
                               revision.occurred_at,
                               revision.id AS stable_id
                          FROM public.programme_programmereadinessrequirementrevision
                               AS revision
                          JOIN public.programme_programmereadinessrequirement
                               AS requirement
                            ON requirement.id = revision.requirement_id
                         WHERE revision.item_id = scoped_item.id
                           AND revision.organization_id = %s
                           AND revision.edition_id = %s
                        UNION ALL
                        SELECT requirement.concern,
                               'evidence'::varchar AS kind,
                               evidence.sequence,
                               evidence.item_version,
                               evidence.requirement_version,
                               evidence.dependency_version,
                               NULL::varchar AS disposition,
                               evidence.state,
                               evidence.source_code,
                               evidence.source_version,
                               evidence.evidence_note AS note,
                               evidence.actor_id,
                               evidence.reason,
                               evidence.occurred_at,
                               evidence.id AS stable_id
                          FROM public.programme_programmereadinessevidence AS evidence
                          JOIN public.programme_programmereadinessrequirement
                               AS requirement
                            ON requirement.id = evidence.requirement_id
                         WHERE evidence.item_id = scoped_item.id
                           AND evidence.organization_id = %s
                           AND evidence.edition_id = %s
                      ) AS combined
                     ORDER BY combined.item_version DESC,
                              combined.concern DESC,
                              combined.kind DESC,
                              combined.sequence DESC,
                              combined.stable_id DESC
                     LIMIT %s
                  ) AS history ON TRUE
                """,
                [
                    item_id,
                    organization_id,
                    edition_id,
                    organization_id,
                    edition_id,
                    organization_id,
                    edition_id,
                    bounded_limit,
                ],
            )
            rows = cursor.fetchall()
        if not rows:
            raise ProgrammeQueryUnavailableError
        if rows[0][1] is None:
            return ()
        return tuple(ProgrammeReadinessHistoryEntryProjection(*row) for row in rows)

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_READINESS,
        requested_fields=frozenset({"readiness_history"}),
        operation="programme.query.readiness_history",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=len,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def list_programme_public_copy_review_history(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    reason: str,
    limit: int = 100,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammePublicCopyReviewHistoryEntryProjection, ...]:
    """List bounded private public-copy reviews with retained rationale.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    reason : str
        The retained sensitive-read purpose.
    limit : int, default=100
        The bounded maximum number of review entries.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    tuple[ProgrammePublicCopyReviewHistoryEntryProjection, ...]
        Newest-first private approval records with rationale.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> tuple[ProgrammePublicCopyReviewHistoryEntryProjection, ...]:
        if not ProgrammeItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).exists():
            raise ProgrammeQueryUnavailableError
        renditions = (
            ProgrammePublicRendition.objects.filter(
                item_id=item_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .order_by("-rendition_number", "-id")
            .values(
                "rendition_number",
                "source_item_version",
                "public_title",
                "public_summary",
                "public_content_note",
                "reviewed_by_id",
                "review_reason",
                "reviewed_at",
            )[: _bounded_limit(limit)]
        )
        return tuple(
            ProgrammePublicCopyReviewHistoryEntryProjection(
                rendition_number=rendition["rendition_number"],
                source_item_version=rendition["source_item_version"],
                public_title=rendition["public_title"],
                public_summary=rendition["public_summary"],
                public_content_note=rendition["public_content_note"],
                actor_id=rendition["reviewed_by_id"],
                reason=rendition["review_reason"],
                occurred_at=rendition["reviewed_at"],
            )
            for rendition in renditions
        )

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=frozenset({"public_copy_review_history"}),
        operation="programme.query.public_copy_review_history",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=len,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )


def load_programme_public_copy(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    correlation_id: UUID | None = None,
    source_channel: str = "service",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammePublicCopyProjection | None:
    """Load approved copy without private working or review fields.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    correlation_id : UUID | None, default=None
        Optional trace identifier; a server UUID is generated when absent.
    source_channel : str, default="service"
        The normalized calling channel.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammePublicCopyProjection | None
        Latest approved public fields, or the uniform absent result.
    """
    item_id = require_uuid(item_id, field="item_id")

    def load() -> ProgrammePublicCopyProjection | None:
        rendition = (
            ProgrammePublicRendition.objects.filter(
                item_id=item_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .order_by("-rendition_number", "-id")
            .values(
                "rendition_number",
                "public_title",
                "public_summary",
                "public_content_note",
            )
            .first()
        )
        if rendition is None:
            return None
        return ProgrammePublicCopyProjection(
            rendition_number=rendition["rendition_number"],
            public_title=rendition["public_title"],
            public_summary=rendition["public_summary"],
            public_content_note=rendition["public_content_note"],
        )

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_PUBLIC_COPY,
        requested_fields=frozenset({"latest_public_rendition"}),
        operation="programme.query.public_copy",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda projection: int(projection is not None),
        reason="programme_public_copy",
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
        sensitive=False,
    )


__all__ = [
    "MAX_PROGRAMME_QUERY_ITEMS",
    "PROGRAMME_QUERY_DELIVERY_HISTORY_FIELD_CEILING",
    "PROGRAMME_QUERY_FIELD_CEILINGS",
    "PROGRAMME_QUERY_PUBLIC_COPY_REVIEW_HISTORY_FIELD_CEILING",
    "PROGRAMME_QUERY_READINESS_HISTORY_FIELD_CEILING",
    "PROGRAMME_QUERY_WORKING_HISTORY_FIELD_CEILING",
    "ProgrammeDeliveryHistoryEntryProjection",
    "ProgrammeDeliveryProjection",
    "ProgrammeDiscussionEntryProjection",
    "ProgrammeItemProjection",
    "ProgrammePrivateItemProjection",
    "ProgrammePublicCopyProjection",
    "ProgrammePublicCopyReviewHistoryEntryProjection",
    "ProgrammeQueryError",
    "ProgrammeQueryUnavailableError",
    "ProgrammeReadinessConcernProjection",
    "ProgrammeReadinessHistoryEntryProjection",
    "ProgrammeWorkingHistoryEntryProjection",
    "ProgrammeWorkingProjection",
    "list_programme_delivery_history",
    "list_programme_discussion",
    "list_programme_private_items",
    "list_programme_public_copy_review_history",
    "list_programme_readiness_history",
    "list_programme_working_history",
    "load_programme_delivery",
    "load_programme_private_item",
    "load_programme_public_copy",
    "load_programme_readiness",
    "programme_query_field_ceiling",
]
