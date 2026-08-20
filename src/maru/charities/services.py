"""Closed idempotent commands for charity partner and selection governance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    ResolvedAuthorizationTarget,
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.organizations.models import Organization
from maru.workforce.models import Department

from .authorization import resolve_charity_selection_target
from .bindings import ensure_charity_selection_binding
from .inputs import (
    canonical_digest,
    normalized_private_comment,
    normalized_reason,
    normalized_slug,
    normalized_source_channel,
    normalized_text,
)
from .models import (
    MAX_PUBLIC_MEDIA_REFERENCES,
    CharityCommandReceipt,
    CharityPartner,
    CharityPartnerMedia,
    CharityPublicationSnapshot,
    CharitySelection,
    CharitySelectionTimelineEntry,
)
from .writer_boundary import charity_writer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from maru.identity.models import Account

PARTNER_VIEW_CAPABILITY = "charities.view_partners"
PARTNER_MANAGE_CAPABILITY = "charities.manage_partners"
QUEUE_VIEW_CAPABILITY = "charities.view_review_queue"
SELECTION_PROPOSE_CAPABILITY = "charities.propose_selection"
SELECTION_VIEW_CAPABILITY = "charities.view_selection"
SELECTION_REVIEW_CAPABILITY = "charities.review_selection"
SELECTION_COMMENT_CAPABILITY = "charities.comment_selection"
SELECTION_PUBLISH_CAPABILITY = "charities.publish_selection"


class CharityCommandError(RuntimeError):
    """Signal charity command."""

    reason_code = "charity_command_failed"

    def __init__(
        self, message: str = "The charity command could not complete."
    ) -> None:
        """Initialize the CharityCommandError instance.

        Parameters
        ----------
        message : str, default='The charity command could not complete.'
            The disclosure-safe message associated with the outcome.
        """
        super().__init__(message)


class CharityAuthorizationDeniedError(CharityCommandError):
    """Signal charity authorization denied."""

    reason_code = "charity_authorization_denied"


class CharityResourceUnavailableError(CharityCommandError):
    """Signal charity resource unavailable."""

    reason_code = "charity_resource_unavailable"


class CharityVersionConflictError(CharityCommandError):
    """Signal charity version conflict."""

    reason_code = "charity_version_conflict"


class CharityRetryConflictError(CharityCommandError):
    """Signal charity retry conflict."""

    reason_code = "charity_retry_conflict"


class CharityStateConflictError(CharityCommandError):
    """Signal charity state conflict."""

    reason_code = "charity_state_conflict"


class CharityIndependentApprovalError(CharityCommandError):
    """Signal charity independent approval."""

    reason_code = "charity_independent_approval_required"


@dataclass(frozen=True, slots=True)
class CharityCommandResult:
    """Describe charity command result.

    Attributes
    ----------
    object_id
        The object identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    replayed
        The replayed retained in this immutable projection.
    """

    object_id: UUID
    receipt_id: UUID
    resulting_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class CharityPartnerProfile:
    """Describe charity partner profile.

    Attributes
    ----------
    legal_name
        The human-readable legal name shown to authorized readers.
    public_name
        The human-readable public name shown to authorized readers.
    imprint_name
        The human-readable imprint name shown to authorized readers.
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
    """

    legal_name: str
    public_name: str
    imprint_name: str = ""
    short_description: str = ""
    description: str = ""
    location_name: str = ""
    postal_address: str = ""
    country_code: str = ""
    website_url: str = ""
    contact_email: str = ""
    contact_phone: str = ""


@dataclass(frozen=True, slots=True)
class _AuthorizedSelection:
    selection_id: UUID
    department_id: UUID
    target: ResolvedAuthorizationTarget
    decision: PolicyDecision


_PARTNER_PROFILE_LIMITS: dict[str, int] = {
    "legal_name": 240,
    "imprint_name": 240,
    "public_name": 200,
    "short_description": 500,
    "description": 5_000,
    "location_name": 240,
    "postal_address": 1_000,
    "country_code": 2,
    "website_url": 2_000,
    "contact_email": 254,
    "contact_phone": 16,
}
_REQUIRED_PROFILE_FIELDS = frozenset({"legal_name", "public_name"})
_PARTNER_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    CharityPartner.Lifecycle.DRAFT: frozenset(
        {CharityPartner.Lifecycle.ACTIVE, CharityPartner.Lifecycle.RETIRED}
    ),
    CharityPartner.Lifecycle.ACTIVE: frozenset({CharityPartner.Lifecycle.RETIRED}),
    CharityPartner.Lifecycle.RETIRED: frozenset(),
}


def _require_uuid(value: UUID, *, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValidationError(
            {field: ValidationError("Enter a valid UUID.", code="charity_uuid_invalid")}
        )
    return value


def _require_expected_version(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValidationError(
            {
                "expected_version": ValidationError(
                    "Enter a positive current version.",
                    code="charity_expected_version_invalid",
                )
            }
        )
    return value


def _normalize_profile(profile: CharityPartnerProfile) -> dict[str, str]:
    values: dict[str, str] = {}
    for field_name, maximum in _PARTNER_PROFILE_LIMITS.items():
        value = getattr(profile, field_name)
        values[field_name] = normalized_text(
            value,
            field=field_name,
            maximum=maximum,
            required=field_name in _REQUIRED_PROFILE_FIELDS,
            collapse=field_name not in {"description", "postal_address"},
        )
    values["country_code"] = values["country_code"].upper()
    return values


def _require_actor(actor: Account) -> None:
    if actor.pk is None or not actor.is_active:
        raise CharityAuthorizationDeniedError


def _require_decision(
    *,
    actor: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget | None,
    at: datetime,
) -> PolicyDecision:
    _require_actor(actor)
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=target,
        at=at,
    )
    if not decision.allowed:
        raise CharityAuthorizationDeniedError
    return decision


def _organization_decision(
    *, actor: Account, organization_id: UUID, capability_code: str, at: datetime
) -> PolicyDecision:
    return _require_decision(
        actor=actor,
        capability_code=capability_code,
        target=resolve_organization_target(organization_id=organization_id),
        at=at,
    )


def _edition_decision(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    at: datetime,
) -> PolicyDecision:
    return _require_decision(
        actor=actor,
        capability_code=capability_code,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        at=at,
    )


def _selection_decision(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    capability_code: str,
    at: datetime,
) -> _AuthorizedSelection:
    row = (
        CharitySelection.objects.filter(
            id=selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .order_by()
        .values("id", "responsible_department_id")
        .first()
    )
    if row is None:
        raise CharityAuthorizationDeniedError
    target = resolve_charity_selection_target(
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
    )
    decision = _require_decision(
        actor=actor,
        capability_code=capability_code,
        target=target,
        at=at,
    )
    if target is None:
        raise CharityAuthorizationDeniedError
    return _AuthorizedSelection(
        selection_id=row["id"],
        department_id=row["responsible_department_id"],
        target=target,
        decision=decision,
    )


def _request_key_hash(idempotency_key: UUID) -> str:
    return hashlib.sha256(str(idempotency_key).encode("ascii")).hexdigest()


def _existing_receipt(
    *,
    actor: Account,
    operation: str,
    idempotency_key: UUID,
    organization_id: UUID,
    request_digest: str,
) -> CharityCommandReceipt | None:
    receipt = (
        CharityCommandReceipt.objects.select_for_update()
        .filter(
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        .first()
    )
    if receipt is None:
        return None
    if (
        receipt.organization_id != organization_id
        or receipt.request_digest != request_digest
    ):
        raise CharityRetryConflictError
    return receipt


def _replayed_result(receipt: CharityCommandReceipt) -> CharityCommandResult:
    return CharityCommandResult(
        object_id=receipt.result_object_id,
        receipt_id=receipt.id,
        resulting_version=receipt.resulting_version,
        replayed=True,
    )


def _command_result(
    *, object_id: UUID, receipt_id: UUID, resulting_version: int
) -> CharityCommandResult:
    return CharityCommandResult(
        object_id=object_id,
        receipt_id=receipt_id,
        resulting_version=resulting_version,
        replayed=False,
    )


def _append_evidence(
    *,
    actor: Account,
    organization: Organization,
    edition: EventEdition | None,
    partner: CharityPartner | None,
    selection: CharitySelection | None,
    operation: str,
    idempotency_key: UUID,
    request_digest: str,
    result_object_id: UUID,
    resulting_version: int,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    capability_code: str,
    decision: PolicyDecision,
    changed_fields: Sequence[str],
    aggregate_type: str,
    aggregate_id: UUID,
    event_name: str,
    event_payload: dict[str, object],
    occurred_at: datetime,
) -> CharityCommandReceipt:
    with charity_writer():
        receipt = CharityCommandReceipt.objects.create(
            organization=organization,
            edition=edition,
            partner=partner,
            selection=selection,
            operation=operation,
            actor=actor,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            resulting_version=resulting_version,
            result_object_id=result_object_id,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=edition.id if edition else None,
            capability_code=capability_code,
            operation=f"charities.{operation}",
            target_type=aggregate_type,
            target_id=aggregate_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            idempotency_key_hash=_request_key_hash(idempotency_key),
            source_channel=source_channel,
            obligations=tuple(sorted(decision.obligations)),
            changed_fields=tuple(sorted(set(changed_fields))),
            safe_metadata={
                "policy_version": POLICY_VERSION,
            },
            retention_class="charity-restricted",
        ),
        occurred_at=occurred_at,
    )
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=organization.id,
            event_edition_id=edition.id if edition else None,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=resulting_version,
            payload=event_payload,
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="charity-restricted",
        ),
        occurred_at=occurred_at,
    )
    return receipt


def _validate_command_ids(
    *, idempotency_key: UUID, correlation_id: UUID
) -> tuple[UUID, UUID]:
    return (
        _require_uuid(idempotency_key, field="idempotency_key"),
        _require_uuid(correlation_id, field="correlation_id"),
    )


@transaction.atomic
def create_charity_partner(
    *,
    actor: Account,
    organization_id: UUID,
    slug: str,
    profile: CharityPartnerProfile,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Create charity partner.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    slug : str
        The stable URL slug identifying the slug.
    profile : CharityPartnerProfile
        The governed profile data.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    CharityAuthorizationDeniedError
        If the actor lacks the required scoped capability.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    values = _normalize_profile(profile)
    slug = normalized_slug(slug, fallback=values["public_name"])
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "slug": slug,
            "profile": values,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    organization = (
        Organization.objects.select_for_update()
        .filter(
            id=organization_id,
            lifecycle__in=(
                Organization.Lifecycle.DRAFT,
                Organization.Lifecycle.ACTIVE,
            ),
        )
        .first()
    )
    if organization is None:
        raise CharityAuthorizationDeniedError
    if receipt := _existing_receipt(
        actor=actor,
        operation=CharityCommandReceipt.Operation.PARTNER_CREATE,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    with charity_writer():
        partner = CharityPartner.objects.create(
            organization=organization,
            slug=slug,
            **values,
            lifecycle=CharityPartner.Lifecycle.DRAFT,
            aggregate_version=1,
            created_by=actor,
            last_modified_by=actor,
        )
    receipt = _append_evidence(
        actor=actor,
        organization=organization,
        edition=None,
        partner=partner,
        selection=None,
        operation=CharityCommandReceipt.Operation.PARTNER_CREATE,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=partner.id,
        resulting_version=partner.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("profile", "lifecycle"),
        aggregate_type="charities.partner",
        aggregate_id=partner.id,
        event_name="charities.partner.changed.v1",
        event_payload={"action": "created", "lifecycle": partner.lifecycle},
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=partner.id,
        receipt_id=receipt.id,
        resulting_version=1,
    )


@transaction.atomic
def update_charity_partner(  # noqa: PLR0912
    *,
    actor: Account,
    organization_id: UUID,
    partner_id: UUID,
    expected_version: int,
    changes: Mapping[str, str],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Update charity partner.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    partner_id : UUID
        The identifier of the partner.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    changes : Mapping[str, str]
        The changes applied within the audited domain transition.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    CharityResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    CharityStateConflictError
        If the target lifecycle state does not permit the transition.
    CharityVersionConflictError
        If the supplied aggregate version is stale.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    allowed = frozenset({"slug", "lifecycle", *_PARTNER_PROFILE_LIMITS})
    if not changes or not set(changes).issubset(allowed):
        raise ValidationError(
            {
                "changes": ValidationError(
                    "Choose supported profile fields.", code="charity_changes_invalid"
                )
            }
        )
    normalized: dict[str, str] = {}
    for field_name, raw_value in changes.items():
        if field_name == "slug":
            normalized[field_name] = normalized_slug(raw_value)
        elif field_name == "lifecycle":
            if raw_value not in CharityPartner.Lifecycle.values:
                raise ValidationError({"lifecycle": "Choose a supported lifecycle."})
            normalized[field_name] = raw_value
        else:
            normalized[field_name] = normalized_text(
                raw_value,
                field=field_name,
                maximum=_PARTNER_PROFILE_LIMITS[field_name],
                required=field_name in _REQUIRED_PROFILE_FIELDS,
                collapse=field_name not in {"description", "postal_address"},
            )
    if "country_code" in normalized:
        normalized["country_code"] = normalized["country_code"].upper()
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "partner_id": partner_id,
            "expected_version": expected_version,
            "changes": normalized,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=CharityCommandReceipt.Operation.PARTNER_UPDATE,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    partner = (
        CharityPartner.objects.select_for_update()
        .select_related("organization")
        .filter(id=partner_id, organization_id=organization_id)
        .first()
    )
    if partner is None:
        raise CharityResourceUnavailableError
    if partner.aggregate_version != expected_version:
        raise CharityVersionConflictError
    if partner.lifecycle == CharityPartner.Lifecycle.RETIRED:
        raise CharityStateConflictError
    lifecycle = normalized.get("lifecycle")
    if (
        lifecycle is not None
        and lifecycle != partner.lifecycle
        and lifecycle not in _PARTNER_LIFECYCLE_TRANSITIONS[partner.lifecycle]
    ):
        raise CharityStateConflictError
    actual_changes = {
        field_name: value
        for field_name, value in normalized.items()
        if getattr(partner, field_name) != value
    }
    if not actual_changes:
        raise ValidationError(
            {
                "changes": ValidationError(
                    "Change at least one value.", code="charity_no_changes"
                )
            }
        )
    for field_name, value in actual_changes.items():
        setattr(partner, field_name, value)
    partner.aggregate_version += 1
    partner.last_modified_by = actor
    with charity_writer():
        partner.save()
    receipt = _append_evidence(
        actor=actor,
        organization=partner.organization,
        edition=None,
        partner=partner,
        selection=None,
        operation=CharityCommandReceipt.Operation.PARTNER_UPDATE,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=partner.id,
        resulting_version=partner.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=tuple(actual_changes),
        aggregate_type="charities.partner",
        aggregate_id=partner.id,
        event_name="charities.partner.changed.v1",
        event_payload={"action": "updated", "lifecycle": partner.lifecycle},
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=partner.id,
        receipt_id=receipt.id,
        resulting_version=partner.aggregate_version,
    )


@transaction.atomic
def add_charity_partner_media(
    *,
    actor: Account,
    organization_id: UUID,
    partner_id: UUID,
    kind: str,
    source_reference: str,
    owner_name: str,
    license_basis: str,
    usage_scope: str,
    attribution: str,
    expires_at: datetime | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Add charity partner media.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    partner_id : UUID
        The identifier of the partner.
    kind : str
        The closed kind code.
    source_reference : str
        The source-system reference.
    owner_name : str
        The human-readable owner name shown to authorized readers.
    license_basis : str
        The license basis applied within the audited domain transition.
    usage_scope : str
        The usage scope applied within the audited domain transition.
    attribution : str
        The attribution applied within the audited domain transition.
    expires_at : datetime | None
        The time at which the value expires.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.

    Raises
    ------
    CharityResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    CharityStateConflictError
        If the target lifecycle state does not permit the transition.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    if kind not in CharityPartnerMedia.Kind.values:
        raise ValidationError({"kind": "Choose a supported charity media kind."})
    values = {
        "source_reference": normalized_text(
            source_reference,
            field="source_reference",
            maximum=1_000,
            required=True,
        ),
        "owner_name": normalized_text(
            owner_name,
            field="owner_name",
            maximum=240,
            required=True,
            collapse=True,
        ),
        "license_basis": normalized_text(
            license_basis,
            field="license_basis",
            maximum=500,
            required=True,
        ),
        "usage_scope": normalized_text(
            usage_scope,
            field="usage_scope",
            maximum=500,
            required=True,
        ),
        "attribution": normalized_text(
            attribution,
            field="attribution",
            maximum=500,
        ),
    }
    if expires_at is not None and not timezone.is_aware(expires_at):
        raise ValidationError({"expires_at": "Enter a timezone-aware expiry."})
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "partner_id": partner_id,
            "kind": kind,
            **values,
            "expires_at": expires_at,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=CharityCommandReceipt.Operation.MEDIA_ADD,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    partner = (
        CharityPartner.objects.select_for_update()
        .select_related("organization")
        .filter(id=partner_id, organization_id=organization_id)
        .first()
    )
    if partner is None:
        raise CharityResourceUnavailableError
    if partner.lifecycle == CharityPartner.Lifecycle.RETIRED:
        raise CharityStateConflictError
    with charity_writer():
        media = CharityPartnerMedia.objects.create(
            partner=partner,
            organization=partner.organization,
            kind=kind,
            **values,
            expires_at=expires_at,
            review_status=CharityPartnerMedia.ReviewStatus.PENDING,
            aggregate_version=1,
            submitted_by=actor,
        )
    receipt = _append_evidence(
        actor=actor,
        organization=partner.organization,
        edition=None,
        partner=partner,
        selection=None,
        operation=CharityCommandReceipt.Operation.MEDIA_ADD,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=media.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("media_reference",),
        aggregate_type="charities.partner_media",
        aggregate_id=media.id,
        event_name="charities.media.changed.v1",
        event_payload={
            "action": "added",
            "kind": media.kind,
            "review_status": media.review_status,
        },
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=media.id,
        receipt_id=receipt.id,
        resulting_version=1,
    )


def _media_review_command(
    *,
    actor: Account,
    organization_id: UUID,
    partner_id: UUID,
    media_id: UUID,
    expected_version: int,
    action: str,
    public_reference: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
) -> CharityCommandResult:
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    if action == "approve":
        public_reference = normalized_text(
            public_reference,
            field="public_reference",
            maximum=1_000,
            required=True,
        )
        operation = CharityCommandReceipt.Operation.MEDIA_APPROVE
    elif action == "withdraw":
        public_reference = ""
        operation = CharityCommandReceipt.Operation.MEDIA_WITHDRAW
    else:
        raise ValueError("Unsupported media review action.")
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "partner_id": partner_id,
            "media_id": media_id,
            "expected_version": expected_version,
            "action": action,
            "public_reference": public_reference,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=operation,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    media = (
        CharityPartnerMedia.objects.select_for_update()
        .select_related("partner", "organization")
        .filter(
            id=media_id,
            partner_id=partner_id,
            organization_id=organization_id,
        )
        .first()
    )
    if media is None:
        raise CharityResourceUnavailableError
    if media.aggregate_version != expected_version:
        raise CharityVersionConflictError
    if action == "approve":
        if media.review_status != CharityPartnerMedia.ReviewStatus.PENDING:
            raise CharityStateConflictError
        if media.submitted_by_id == actor.id:
            raise CharityIndependentApprovalError
        if media.expires_at is not None and media.expires_at <= evaluated_at:
            raise CharityStateConflictError
        media.review_status = CharityPartnerMedia.ReviewStatus.APPROVED
        media.public_reference = public_reference
    else:
        if media.review_status != CharityPartnerMedia.ReviewStatus.APPROVED:
            raise CharityStateConflictError
        media.review_status = CharityPartnerMedia.ReviewStatus.WITHDRAWN
        media.public_reference = ""
    media.reviewed_by = actor
    media.reviewed_at = evaluated_at
    media.aggregate_version += 1
    with charity_writer():
        media.save()
    receipt = _append_evidence(
        actor=actor,
        organization=media.organization,
        edition=None,
        partner=media.partner,
        selection=None,
        operation=operation,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=media.id,
        resulting_version=media.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("public_reference", "review_status"),
        aggregate_type="charities.partner_media",
        aggregate_id=media.id,
        event_name="charities.media.changed.v1",
        event_payload={
            "action": action,
            "kind": media.kind,
            "review_status": media.review_status,
        },
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=media.id,
        receipt_id=receipt.id,
        resulting_version=media.aggregate_version,
    )


@transaction.atomic
def approve_charity_partner_media(
    *,
    actor: Account,
    organization_id: UUID,
    partner_id: UUID,
    media_id: UUID,
    expected_version: int,
    public_reference: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Approve charity partner media.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    partner_id : UUID
        The identifier of the partner.
    media_id : UUID
        The identifier of the media.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    public_reference : str
        The provider or source public reference retained for reconciliation.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.
    """
    return _media_review_command(
        actor=actor,
        organization_id=organization_id,
        partner_id=partner_id,
        media_id=media_id,
        expected_version=expected_version,
        action="approve",
        public_reference=public_reference,
        reason=reason,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )


@transaction.atomic
def withdraw_charity_partner_media(
    *,
    actor: Account,
    organization_id: UUID,
    partner_id: UUID,
    media_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Withdraw charity partner media.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    partner_id : UUID
        The identifier of the partner.
    media_id : UUID
        The identifier of the media.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.
    """
    return _media_review_command(
        actor=actor,
        organization_id=organization_id,
        partner_id=partner_id,
        media_id=media_id,
        expected_version=expected_version,
        action="withdraw",
        public_reference="",
        reason=reason,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )


def _selection_event_payload(
    selection: CharitySelection,
    *,
    action: str,
) -> dict[str, object]:
    return {
        "action": action,
        "status": selection.status,
        "publication_state": selection.publication_state,
    }


def _append_selection_timeline(
    *,
    selection: CharitySelection,
    actor: Account,
    occurred_at: datetime,
    kind: str,
    from_status: str = "",
    to_status: str = "",
    from_publication_state: str = "",
    to_publication_state: str = "",
    reason: str = "",
    private_comment: str = "",
) -> CharitySelectionTimelineEntry:
    with charity_writer():
        return CharitySelectionTimelineEntry.objects.create(
            selection=selection,
            organization_id=selection.organization_id,
            edition_id=selection.edition_id,
            sequence=selection.aggregate_version,
            kind=kind,
            actor=actor,
            occurred_at=occurred_at,
            from_status=from_status,
            to_status=to_status,
            from_publication_state=from_publication_state,
            to_publication_state=to_publication_state,
            reason=reason,
            private_comment=private_comment,
        )


@transaction.atomic
def propose_charity_selection(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    partner_id: UUID,
    responsible_department_id: UUID,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Propose charity selection.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    partner_id : UUID
        The identifier of the partner.
    responsible_department_id : UUID
        The identifier of the responsible department.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.

    Raises
    ------
    CharityAuthorizationDeniedError
        If the actor lacks the required scoped capability.
    CharityResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    CharityStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "partner_id": partner_id,
            "responsible_department_id": responsible_department_id,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=SELECTION_PROPOSE_CAPABILITY,
        at=evaluated_at,
    )
    organization = (
        Organization.objects.select_for_update().filter(id=organization_id).first()
    )
    edition = (
        EventEdition.objects.select_for_update()
        .filter(id=edition_id, organization_id=organization_id)
        .first()
    )
    if organization is None or edition is None:
        raise CharityAuthorizationDeniedError
    if edition.lifecycle in {
        EventEdition.Lifecycle.ARCHIVED,
        EventEdition.Lifecycle.CANCELLED,
    }:
        raise CharityStateConflictError
    if receipt := _existing_receipt(
        actor=actor,
        operation=CharityCommandReceipt.Operation.SELECTION_PROPOSE,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    department = (
        Department.objects.select_for_update()
        .filter(
            id=responsible_department_id,
            organization_id=organization_id,
            edition_id=edition_id,
            retired_at__isnull=True,
        )
        .first()
    )
    partner = (
        CharityPartner.objects.select_for_update()
        .filter(
            id=partner_id,
            organization_id=organization_id,
            lifecycle__in=(
                CharityPartner.Lifecycle.DRAFT,
                CharityPartner.Lifecycle.ACTIVE,
            ),
        )
        .first()
    )
    if department is None or partner is None:
        raise CharityResourceUnavailableError
    with charity_writer():
        selection = CharitySelection.objects.create(
            organization=organization,
            edition=edition,
            responsible_department=department,
            partner=partner,
            status=CharitySelection.Status.PROPOSED,
            publication_state=CharitySelection.PublicationState.UNPUBLISHED,
            aggregate_version=1,
            proposed_by=actor,
        )
    ensure_charity_selection_binding(selection=selection)
    _append_selection_timeline(
        selection=selection,
        actor=actor,
        occurred_at=evaluated_at,
        kind=CharitySelectionTimelineEntry.Kind.PROPOSED,
        to_status=selection.status,
        reason=reason,
    )
    receipt = _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        partner=partner,
        selection=selection,
        operation=CharityCommandReceipt.Operation.SELECTION_PROPOSE,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=selection.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SELECTION_PROPOSE_CAPABILITY,
        decision=decision,
        changed_fields=("selection", "status"),
        aggregate_type="charities.selection",
        aggregate_id=selection.id,
        event_name="charities.selection.changed.v1",
        event_payload=_selection_event_payload(selection, action="proposed"),
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=selection.id,
        receipt_id=receipt.id,
        resulting_version=1,
    )


@transaction.atomic
def submit_charity_selection(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Submit charity selection.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    selection_id : UUID
        The identifier of the selection.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.

    Raises
    ------
    CharityResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    CharityStateConflictError
        If the target lifecycle state does not permit the transition.
    CharityVersionConflictError
        If the supplied aggregate version is stale.
    """
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "selection_id": selection_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=SELECTION_PROPOSE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=CharityCommandReceipt.Operation.SELECTION_SUBMIT,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    selection = (
        CharitySelection.objects.select_for_update()
        .select_related("organization", "edition", "partner")
        .filter(
            id=selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .first()
    )
    if selection is None:
        raise CharityResourceUnavailableError
    if selection.aggregate_version != expected_version:
        raise CharityVersionConflictError
    if (
        selection.status != CharitySelection.Status.PROPOSED
        or selection.partner.lifecycle != CharityPartner.Lifecycle.ACTIVE
    ):
        raise CharityStateConflictError
    previous = selection.status
    selection.status = CharitySelection.Status.SUBMITTED
    selection.submitted_at = evaluated_at
    selection.aggregate_version += 1
    with charity_writer():
        selection.save()
    _append_selection_timeline(
        selection=selection,
        actor=actor,
        occurred_at=evaluated_at,
        kind=CharitySelectionTimelineEntry.Kind.STATUS,
        from_status=previous,
        to_status=selection.status,
        reason=reason,
    )
    receipt = _append_evidence(
        actor=actor,
        organization=selection.organization,
        edition=selection.edition,
        partner=selection.partner,
        selection=selection,
        operation=CharityCommandReceipt.Operation.SELECTION_SUBMIT,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=selection.id,
        resulting_version=selection.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SELECTION_PROPOSE_CAPABILITY,
        decision=decision,
        changed_fields=("status", "submitted_at"),
        aggregate_type="charities.selection",
        aggregate_id=selection.id,
        event_name="charities.selection.changed.v1",
        event_payload=_selection_event_payload(selection, action="submitted"),
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=selection.id,
        receipt_id=receipt.id,
        resulting_version=selection.aggregate_version,
    )


def _review_charity_selection(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    expected_version: int,
    decision_state: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
) -> CharityCommandResult:
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    if decision_state == CharitySelection.Status.CONFIRMED:
        operation = CharityCommandReceipt.Operation.SELECTION_CONFIRM
        action = "confirmed"
    elif decision_state == CharitySelection.Status.REJECTED:
        operation = CharityCommandReceipt.Operation.SELECTION_REJECT
        action = "rejected"
    else:
        raise ValueError("Unsupported charity review decision.")
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "selection_id": selection_id,
            "expected_version": expected_version,
            "decision_state": decision_state,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _selection_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
        capability_code=SELECTION_REVIEW_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=operation,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    selection = (
        CharitySelection.objects.select_for_update()
        .select_related("organization", "edition", "partner")
        .filter(
            id=authorized.selection_id,
            responsible_department_id=authorized.department_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .first()
    )
    if selection is None:
        raise CharityResourceUnavailableError
    if selection.aggregate_version != expected_version:
        raise CharityVersionConflictError
    if selection.status != CharitySelection.Status.SUBMITTED:
        raise CharityStateConflictError
    previous = selection.status
    selection.status = decision_state
    selection.decided_at = evaluated_at
    selection.aggregate_version += 1
    with charity_writer():
        selection.save()
    _append_selection_timeline(
        selection=selection,
        actor=actor,
        occurred_at=evaluated_at,
        kind=CharitySelectionTimelineEntry.Kind.STATUS,
        from_status=previous,
        to_status=selection.status,
        reason=reason,
    )
    receipt = _append_evidence(
        actor=actor,
        organization=selection.organization,
        edition=selection.edition,
        partner=selection.partner,
        selection=selection,
        operation=operation,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=selection.id,
        resulting_version=selection.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SELECTION_REVIEW_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("decided_at", "status"),
        aggregate_type="charities.selection",
        aggregate_id=selection.id,
        event_name="charities.selection.changed.v1",
        event_payload=_selection_event_payload(selection, action=action),
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=selection.id,
        receipt_id=receipt.id,
        resulting_version=selection.aggregate_version,
    )


@transaction.atomic
def confirm_charity_selection(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Confirm charity selection.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    selection_id : UUID
        The identifier of the selection.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.
    """
    return _review_charity_selection(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
        expected_version=expected_version,
        decision_state=CharitySelection.Status.CONFIRMED,
        reason=reason,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )


@transaction.atomic
def reject_charity_selection(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Reject charity selection.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    selection_id : UUID
        The identifier of the selection.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.
    """
    return _review_charity_selection(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
        expected_version=expected_version,
        decision_state=CharitySelection.Status.REJECTED,
        reason=reason,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )


@transaction.atomic
def add_charity_selection_private_comment(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    expected_version: int,
    private_comment: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Add charity selection private comment.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    selection_id : UUID
        The identifier of the selection.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    private_comment : str
        The private comment applied within the audited domain transition.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.

    Raises
    ------
    CharityResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    CharityVersionConflictError
        If the supplied aggregate version is stale.
    """
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    private_comment = normalized_private_comment(private_comment)
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "selection_id": selection_id,
            "expected_version": expected_version,
            "private_comment": private_comment,
        }
    )
    evaluated_at = timezone.now()
    authorized = _selection_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
        capability_code=SELECTION_COMMENT_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=CharityCommandReceipt.Operation.SELECTION_COMMENT,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    selection = (
        CharitySelection.objects.select_for_update()
        .select_related("organization", "edition", "partner")
        .filter(
            id=selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department_id=authorized.department_id,
        )
        .first()
    )
    if selection is None:
        raise CharityResourceUnavailableError
    if selection.aggregate_version != expected_version:
        raise CharityVersionConflictError
    selection.aggregate_version += 1
    with charity_writer():
        selection.save()
    _append_selection_timeline(
        selection=selection,
        actor=actor,
        occurred_at=evaluated_at,
        kind=CharitySelectionTimelineEntry.Kind.PRIVATE_COMMENT,
        private_comment=private_comment,
    )
    receipt = _append_evidence(
        actor=actor,
        organization=selection.organization,
        edition=selection.edition,
        partner=selection.partner,
        selection=selection,
        operation=CharityCommandReceipt.Operation.SELECTION_COMMENT,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=selection.id,
        resulting_version=selection.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SELECTION_COMMENT_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("private_comment",),
        aggregate_type="charities.selection",
        aggregate_id=selection.id,
        event_name="charities.selection.changed.v1",
        event_payload=_selection_event_payload(selection, action="commented"),
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=selection.id,
        receipt_id=receipt.id,
        resulting_version=selection.aggregate_version,
    )


@transaction.atomic
def publish_charity_selection(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    expected_version: int,
    media_ids: Sequence[UUID],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Publish charity selection.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    selection_id : UUID
        The identifier of the selection.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    media_ids : Sequence[UUID]
        The selected media identifiers.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.

    Raises
    ------
    CharityIndependentApprovalError
        If the actor is not independent from the proposal being approved.
    CharityResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    CharityStateConflictError
        If the target lifecycle state does not permit the transition.
    CharityVersionConflictError
        If the supplied aggregate version is stale.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    normalized_media_ids = tuple(sorted(set(media_ids), key=str))
    if (
        len(normalized_media_ids) != len(tuple(media_ids))
        or len(normalized_media_ids) > MAX_PUBLIC_MEDIA_REFERENCES
    ):
        raise ValidationError(
            {
                "media_ids": ValidationError(
                    "Choose a bounded set of unique approved media references.",
                    code="charity_public_media_invalid",
                )
            }
        )
    if any(not isinstance(media_id, UUID) for media_id in normalized_media_ids):
        raise ValidationError({"media_ids": "Choose valid media identifiers."})
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "selection_id": selection_id,
            "expected_version": expected_version,
            "media_ids": [str(media_id) for media_id in normalized_media_ids],
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _selection_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
        capability_code=SELECTION_PUBLISH_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=CharityCommandReceipt.Operation.SELECTION_PUBLISH,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    selection = (
        CharitySelection.objects.select_for_update()
        .select_related("organization", "edition", "partner")
        .filter(
            id=selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department_id=authorized.department_id,
        )
        .first()
    )
    if selection is None:
        raise CharityResourceUnavailableError
    if selection.aggregate_version != expected_version:
        raise CharityVersionConflictError
    if (
        selection.status != CharitySelection.Status.CONFIRMED
        or selection.publication_state != CharitySelection.PublicationState.UNPUBLISHED
        or selection.partner.lifecycle != CharityPartner.Lifecycle.ACTIVE
    ):
        raise CharityStateConflictError
    confirmation = (
        CharitySelectionTimelineEntry.objects.select_for_update()
        .filter(
            selection=selection,
            kind=CharitySelectionTimelineEntry.Kind.STATUS,
            to_status=CharitySelection.Status.CONFIRMED,
        )
        .order_by("-sequence")
        .first()
    )
    if confirmation is None or confirmation.actor_id == actor.id:
        raise CharityIndependentApprovalError
    media = tuple(
        CharityPartnerMedia.objects.select_for_update()
        .filter(
            id__in=normalized_media_ids,
            partner=selection.partner,
            organization_id=organization_id,
            review_status=CharityPartnerMedia.ReviewStatus.APPROVED,
        )
        .order_by("id")
    )
    valid_media_ids = {
        item.id
        for item in media
        if item.public_reference
        and (item.expires_at is None or item.expires_at > evaluated_at)
    }
    if valid_media_ids != set(normalized_media_ids):
        raise CharityStateConflictError
    previous_publication = selection.publication_state
    selection.publication_state = CharitySelection.PublicationState.PUBLISHED
    selection.publication_number += 1
    selection.published_at = evaluated_at
    selection.aggregate_version += 1
    with charity_writer():
        selection.save()
        CharityPublicationSnapshot.objects.create(
            selection=selection,
            organization=selection.organization,
            edition=selection.edition,
            publication_number=selection.publication_number,
            approved_by=actor,
            approved_at=evaluated_at,
            public_name=selection.partner.public_name,
            imprint_name=selection.partner.imprint_name,
            short_description=selection.partner.short_description,
            location_name=selection.partner.location_name,
            country_code=selection.partner.country_code,
            website_url=selection.partner.website_url,
            media_ids=list(normalized_media_ids),
        )
    _append_selection_timeline(
        selection=selection,
        actor=actor,
        occurred_at=evaluated_at,
        kind=CharitySelectionTimelineEntry.Kind.PUBLICATION,
        from_publication_state=previous_publication,
        to_publication_state=selection.publication_state,
        reason=reason,
    )
    receipt = _append_evidence(
        actor=actor,
        organization=selection.organization,
        edition=selection.edition,
        partner=selection.partner,
        selection=selection,
        operation=CharityCommandReceipt.Operation.SELECTION_PUBLISH,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=selection.id,
        resulting_version=selection.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SELECTION_PUBLISH_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("publication_snapshot", "publication_state"),
        aggregate_type="charities.selection",
        aggregate_id=selection.id,
        event_name="charities.selection.changed.v1",
        event_payload=_selection_event_payload(selection, action="published"),
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=selection.id,
        receipt_id=receipt.id,
        resulting_version=selection.aggregate_version,
    )


@transaction.atomic
def withdraw_charity_selection_publication(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CharityCommandResult:
    """Withdraw charity selection publication.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    selection_id : UUID
        The identifier of the selection.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CharityCommandResult
        The charity command result.

    Raises
    ------
    CharityResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    CharityStateConflictError
        If the target lifecycle state does not permit the transition.
    CharityVersionConflictError
        If the supplied aggregate version is stale.
    """
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "selection_id": selection_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _selection_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        selection_id=selection_id,
        capability_code=SELECTION_PUBLISH_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=CharityCommandReceipt.Operation.SELECTION_WITHDRAW,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    selection = (
        CharitySelection.objects.select_for_update()
        .select_related("organization", "edition", "partner")
        .filter(
            id=selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department_id=authorized.department_id,
        )
        .first()
    )
    if selection is None:
        raise CharityResourceUnavailableError
    if selection.aggregate_version != expected_version:
        raise CharityVersionConflictError
    if selection.publication_state != CharitySelection.PublicationState.PUBLISHED:
        raise CharityStateConflictError
    previous = selection.publication_state
    selection.publication_state = CharitySelection.PublicationState.UNPUBLISHED
    selection.published_at = None
    selection.aggregate_version += 1
    with charity_writer():
        selection.save()
    _append_selection_timeline(
        selection=selection,
        actor=actor,
        occurred_at=evaluated_at,
        kind=CharitySelectionTimelineEntry.Kind.PUBLICATION,
        from_publication_state=previous,
        to_publication_state=selection.publication_state,
        reason=reason,
    )
    receipt = _append_evidence(
        actor=actor,
        organization=selection.organization,
        edition=selection.edition,
        partner=selection.partner,
        selection=selection,
        operation=CharityCommandReceipt.Operation.SELECTION_WITHDRAW,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=selection.id,
        resulting_version=selection.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SELECTION_PUBLISH_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("publication_state",),
        aggregate_type="charities.selection",
        aggregate_id=selection.id,
        event_name="charities.selection.changed.v1",
        event_payload=_selection_event_payload(selection, action="unpublished"),
        occurred_at=evaluated_at,
    )
    return _command_result(
        object_id=selection.id,
        receipt_id=receipt.id,
        resulting_version=selection.aggregate_version,
    )
