"""Policy-scoped staff reads and minimized public charity projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)

from .authorization import resolve_charity_selection_target
from .inputs import normalized_reason, normalized_source_channel
from .models import (
    CharityPartner,
    CharityPartnerMedia,
    CharityPublicationSnapshot,
    CharitySelection,
    CharitySelectionTimelineEntry,
)
from .services import (
    PARTNER_VIEW_CAPABILITY,
    QUEUE_VIEW_CAPABILITY,
    SELECTION_VIEW_CAPABILITY,
    CharityAuthorizationDeniedError,
    CharityResourceUnavailableError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from maru.identity.models import Account


@dataclass(frozen=True, slots=True)
class PublicCharityMedia:
    """Describe public charity media.

    Attributes
    ----------
    kind
        The closed discriminator selecting the requested behavior.
    reference
        The reference retained in this immutable projection.
    attribution
        The attribution retained in this immutable projection.
    """

    kind: str
    reference: str
    attribution: str


@dataclass(frozen=True, slots=True)
class PublicCharity:
    """Describe public charity.

    Attributes
    ----------
    selection_id
        The selection identifier within the requested scope.
    public_name
        The human-readable public name shown to authorized readers.
    imprint_name
        The human-readable imprint name shown to authorized readers.
    short_description
        The bounded short description retained for authorized readers.
    location_name
        The human-readable location name shown to authorized readers.
    country_code
        The stable country code from the relevant closed catalog.
    website_url
        The validated absolute HTTPS website url.
    media
        The media retained in this immutable projection.
    """

    selection_id: UUID
    public_name: str
    imprint_name: str
    short_description: str
    location_name: str
    country_code: str
    website_url: str
    media: tuple[PublicCharityMedia, ...]


@dataclass(frozen=True, slots=True)
class CharityPartnerMediaSummary:
    """Describe charity partner media summary.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    kind
        The closed discriminator selecting the requested behavior.
    source_reference
        The provider or source source reference retained for reconciliation.
    public_reference
        The provider or source public reference retained for reconciliation.
    owner_name
        The human-readable owner name shown to authorized readers.
    license_basis
        The license basis retained in this immutable projection.
    usage_scope
        The usage scope retained in this immutable projection.
    attribution
        The attribution retained in this immutable projection.
    expires_at
        The timezone-aware timestamp for expires.
    review_status
        The closed review status discriminator defined by the domain catalog.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    """

    id: UUID
    kind: str
    source_reference: str
    public_reference: str
    owner_name: str
    license_basis: str
    usage_scope: str
    attribution: str
    expires_at: datetime | None
    review_status: str
    aggregate_version: int


@dataclass(frozen=True, slots=True)
class CharityPartnerSummary:
    """Describe charity partner summary.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    slug
        The stable URL slug identifying the slug.
    legal_name
        The human-readable legal name shown to authorized readers.
    imprint_name
        The human-readable imprint name shown to authorized readers.
    public_name
        The human-readable public name shown to authorized readers.
    short_description
        The bounded short description retained for authorized readers.
    description
        The human-readable description shown to authorized readers.
    location_name
        The human-readable location name shown to authorized readers.
    postal_address
        The postal address retained in this immutable projection.
    country_code
        The stable country code from the relevant closed catalog.
    website_url
        The validated absolute HTTPS website url.
    contact_email
        The normalized contact email used for delivery or identity matching.
    contact_phone
        The normalized international contact phone, when provided.
    lifecycle
        The lifecycle retained in this immutable projection.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    media
        The media retained in this immutable projection.
    """

    id: UUID
    slug: str
    legal_name: str
    imprint_name: str
    public_name: str
    short_description: str
    description: str
    location_name: str
    postal_address: str
    country_code: str
    website_url: str
    contact_email: str
    contact_phone: str
    lifecycle: str
    aggregate_version: int
    media: tuple[CharityPartnerMediaSummary, ...]


@dataclass(frozen=True, slots=True)
class CharitySelectionSummary:
    """Describe charity selection summary.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    partner_id
        The partner identifier within the requested scope.
    partner_name
        The human-readable partner name shown to authorized readers.
    responsible_department_id
        The responsible department identifier within the requested scope.
    responsible_department_name
        The human-readable responsible department name shown to authorized readers.
    status
        The closed status value to evaluate or expose.
    publication_state
        The closed publication state discriminator defined by the domain catalog.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    """

    id: UUID
    partner_id: UUID
    partner_name: str
    responsible_department_id: UUID
    responsible_department_name: str
    status: str
    publication_state: str
    aggregate_version: int


@dataclass(frozen=True, slots=True)
class CharityTimelineProjection:
    """Describe charity timeline projection.

    Attributes
    ----------
    sequence
        The sequence retained in this immutable projection.
    kind
        The closed discriminator selecting the requested behavior.
    actor_id
        The immutable identifier of the account authorizing the operation.
    actor_label
        The human-readable actor label shown to authorized readers.
    occurred_at
        The timezone-aware timestamp for occurred.
    from_status
        The closed from status discriminator defined by the domain catalog.
    to_status
        The closed to status discriminator defined by the domain catalog.
    from_publication_state
        The closed from publication state discriminator defined by the domain catalog.
    to_publication_state
        The closed to publication state discriminator defined by the domain catalog.
    reason
        The operator-supplied rationale recorded with the change.
    private_comment
        The private comment retained in this immutable projection.
    """

    sequence: int
    kind: str
    actor_id: UUID
    actor_label: str
    occurred_at: datetime
    from_status: str
    to_status: str
    from_publication_state: str
    to_publication_state: str
    reason: str
    private_comment: str


@dataclass(frozen=True, slots=True)
class CharitySelectionReview:
    """Describe charity selection review.

    Attributes
    ----------
    summary
        The summary retained in this immutable projection.
    timeline
        The timeline retained in this immutable projection.
    """

    summary: CharitySelectionSummary
    timeline: tuple[CharityTimelineProjection, ...]


def _active_account(actor: Account) -> None:
    if actor.pk is None or not actor.is_active:
        raise CharityAuthorizationDeniedError


def public_charities_for_edition(
    *,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime | None = None,
) -> tuple[PublicCharity, ...]:
    """Return only current confirmed + explicitly published immutable snapshots.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    tuple[PublicCharity, ...]
        The matching public charities for edition records in deterministic
        order.
    """
    evaluated_at = at or timezone.now()
    selections = tuple(
        CharitySelection.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=CharitySelection.Status.CONFIRMED,
            publication_state=CharitySelection.PublicationState.PUBLISHED,
            publication_number__gt=0,
            partner__lifecycle=CharityPartner.Lifecycle.ACTIVE,
        )
        .order_by("partner__public_name", "id")
        .values("id", "partner_id", "publication_number")
    )
    if not selections:
        return ()
    selection_ids = [row["id"] for row in selections]
    publication_number_by_selection = {
        row["id"]: row["publication_number"] for row in selections
    }
    partner_id_by_selection = {row["id"]: row["partner_id"] for row in selections}
    snapshots = tuple(
        CharityPublicationSnapshot.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            selection_id__in=selection_ids,
        ).order_by("selection_id", "publication_number")
    )
    current_snapshots = {
        snapshot.selection_id: snapshot
        for snapshot in snapshots
        if snapshot.publication_number
        == publication_number_by_selection[snapshot.selection_id]
    }
    media_ids = {
        media_id
        for snapshot in current_snapshots.values()
        for media_id in snapshot.media_ids
    }
    media_by_id = {
        media.id: media
        for media in CharityPartnerMedia.objects.filter(
            id__in=media_ids,
            organization_id=organization_id,
            review_status=CharityPartnerMedia.ReviewStatus.APPROVED,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=evaluated_at))
        .exclude(public_reference="")
        .order_by("id")
    }
    projected: list[PublicCharity] = []
    for selection in selections:
        snapshot = current_snapshots.get(selection["id"])
        if snapshot is None:
            continue
        projected.append(
            PublicCharity(
                selection_id=snapshot.selection_id,
                public_name=snapshot.public_name,
                imprint_name=snapshot.imprint_name,
                short_description=snapshot.short_description,
                location_name=snapshot.location_name,
                country_code=snapshot.country_code,
                website_url=snapshot.website_url,
                media=tuple(
                    PublicCharityMedia(
                        kind=media.kind,
                        reference=media.public_reference,
                        attribution=media.attribution,
                    )
                    for media_id in snapshot.media_ids
                    if (media := media_by_id.get(media_id)) is not None
                    and media.partner_id
                    == partner_id_by_selection[snapshot.selection_id]
                ),
            )
        )
    return tuple(projected)


@transaction.atomic
def list_charity_partners(
    *,
    actor: Account,
    organization_id: UUID,
    reason: str = "charity_partner_management",
    correlation_id: UUID | None = None,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> tuple[CharityPartnerSummary, ...]:
    """List charity partners.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    reason : str, default='charity_partner_management'
        The operator-supplied reason for the operation.
    correlation_id : UUID | None, default=None
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    tuple[CharityPartnerSummary, ...]
        The ordered charity partners collection.

    Raises
    ------
    CharityAuthorizationDeniedError
        If the actor lacks the required scoped capability.
    """
    _active_account(actor)
    target = resolve_organization_target(organization_id=organization_id)
    decision = decide(
        principal=actor,
        capability_code=PARTNER_VIEW_CAPABILITY,
        resource=target,
    )
    if not decision.allowed:
        raise CharityAuthorizationDeniedError
    projection = tuple(
        CharityPartnerSummary(
            id=partner.id,
            slug=partner.slug,
            legal_name=partner.legal_name,
            imprint_name=partner.imprint_name,
            public_name=partner.public_name,
            short_description=partner.short_description,
            description=partner.description,
            location_name=partner.location_name,
            postal_address=partner.postal_address,
            country_code=partner.country_code,
            website_url=partner.website_url,
            contact_email=partner.contact_email,
            contact_phone=partner.contact_phone,
            lifecycle=partner.lifecycle,
            aggregate_version=partner.aggregate_version,
            media=tuple(
                CharityPartnerMediaSummary(
                    id=media.id,
                    kind=media.kind,
                    source_reference=media.source_reference,
                    public_reference=media.public_reference,
                    owner_name=media.owner_name,
                    license_basis=media.license_basis,
                    usage_scope=media.usage_scope,
                    attribution=media.attribution,
                    expires_at=media.expires_at,
                    review_status=media.review_status,
                    aggregate_version=media.aggregate_version,
                )
                for media in partner.media_references.all()
            ),
        )
        for partner in CharityPartner.objects.filter(organization_id=organization_id)
        .prefetch_related("media_references")
        .order_by("public_name", "id")
    )
    evaluated_at = timezone.now()
    correlation_id = correlation_id or uuid4()
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=None,
            capability_code=PARTNER_VIEW_CAPABILITY,
            operation="charities.partner_restricted_directory.read",
            target_type="organizations.organization",
            target_id=organization_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=normalized_source_channel(source_channel),
            obligations=tuple(sorted(decision.obligations)),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": normalized_reason(reason),
            },
            retention_class="charity-restricted",
        ),
        occurred_at=evaluated_at,
    )
    return projection


def list_charity_selection_queue(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[CharitySelectionSummary, ...]:
    """List charity selection queue.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    tuple[CharitySelectionSummary, ...]
        The ordered charity selection queue collection.

    Raises
    ------
    CharityAuthorizationDeniedError
        If the actor lacks the required scoped capability.
    """
    _active_account(actor)
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    decision = decide(
        principal=actor,
        capability_code=QUEUE_VIEW_CAPABILITY,
        resource=target,
    )
    if not decision.allowed:
        raise CharityAuthorizationDeniedError
    return tuple(
        CharitySelectionSummary(
            id=selection.id,
            partner_id=selection.partner_id,
            partner_name=selection.partner.public_name,
            responsible_department_id=selection.responsible_department_id,
            responsible_department_name=selection.responsible_department.name,
            status=selection.status,
            publication_state=selection.publication_state,
            aggregate_version=selection.aggregate_version,
        )
        for selection in CharitySelection.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related("partner", "responsible_department")
        .order_by("partner__public_name", "id")
    )


@transaction.atomic
def load_charity_selection_review(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    reason: str,
    correlation_id: UUID | None = None,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharitySelectionReview:
    """Read purpose-scoped private review evidence and audit that sensitive read.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    selection_id : UUID
        The selection identifier within the requested scope.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID | None, default=None
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    CharitySelectionReview
        The resolved CharitySelectionReview for the requested scope.

    Raises
    ------
    CharityAuthorizationDeniedError
        If the actor lacks the required scoped capability.
    CharityResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    """
    _active_account(actor)
    target = resolve_charity_selection_target(
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
    )
    decision = decide(
        principal=actor,
        capability_code=SELECTION_VIEW_CAPABILITY,
        resource=target,
    )
    if not decision.allowed:
        raise CharityAuthorizationDeniedError
    selection = (
        CharitySelection.objects.filter(
            id=selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related("partner", "responsible_department")
        .first()
    )
    if selection is None:
        raise CharityResourceUnavailableError
    timeline = tuple(
        CharityTimelineProjection(
            sequence=entry.sequence,
            kind=entry.kind,
            actor_id=entry.actor_id,
            actor_label=entry.actor.display_name or "Authorized account",
            occurred_at=entry.occurred_at,
            from_status=entry.from_status,
            to_status=entry.to_status,
            from_publication_state=entry.from_publication_state,
            to_publication_state=entry.to_publication_state,
            reason=entry.reason,
            private_comment=entry.private_comment,
        )
        for entry in CharitySelectionTimelineEntry.objects.filter(
            selection=selection,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related("actor")
        .order_by("sequence", "id")
    )
    evaluated_at = timezone.now()
    correlation_id = correlation_id or uuid4()
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=SELECTION_VIEW_CAPABILITY,
            operation="charities.selection_private_review.read",
            target_type="charities.selection",
            target_id=selection.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(decision.obligations)),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": reason,
            },
            retention_class="charity-restricted",
        ),
        occurred_at=evaluated_at,
    )
    return CharitySelectionReview(
        summary=CharitySelectionSummary(
            id=selection.id,
            partner_id=selection.partner_id,
            partner_name=selection.partner.public_name,
            responsible_department_id=selection.responsible_department_id,
            responsible_department_name=selection.responsible_department.name,
            status=selection.status,
            publication_state=selection.publication_state,
            aggregate_version=selection.aggregate_version,
        ),
        timeline=timeline,
    )
