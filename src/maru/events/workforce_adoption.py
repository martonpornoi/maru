"""Guided, idempotent Workforce-only adoption orchestration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.events.adoption import (
    WORKFORCE_ONLY_PROFILE_VERSION,
    AdoptionProfileCode,
    adoption_profile,
)
from maru.events.models import EventEdition, WorkforceAdoptionSetupReceipt
from maru.events.services import EventEditionDetails, create_event_edition
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationRepresentation,
)

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID

    from maru.identity.models import Account
from maru.organizations.representation import provision_maru_operators
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    OrganizationCreationDetails,
    create_convention_series,
    create_draft_organization,
)

WORKFORCE_SETUP_LOCK_NAMESPACE = 0x57F0_ACE0_0000_0000


@dataclass(frozen=True, slots=True)
class WorkforceAdoptionSetupInput:
    """Describe one complete guided Workforce foundation request.

    Attributes
    ----------
    mode
        Whether to create or reuse each foundation level.
    organization_id
        The selected organization for a reuse mode.
    series_id
        The selected convention series for a reuse mode.
    organization_name
        The new organization name when creating the whole foundation.
    series_name
        The new series name when its level is not reused.
    edition_name
        The recognizable dated convention-edition name.
    starts_on
        The first official convention date.
    ends_on
        The final official convention date.
    time_zone
        The IANA time zone used by Workforce scheduling.
    """

    mode: str
    organization_id: UUID | None
    series_id: UUID | None
    organization_name: str
    series_name: str
    edition_name: str
    starts_on: date
    ends_on: date
    time_zone: str


@dataclass(frozen=True, slots=True)
class WorkforceAdoptionSetupResult:
    """Describe the durable outcome of guided Workforce setup.

    Attributes
    ----------
    edition
        The exact Workforce-only event edition.
    representation
        The retained accountable representation for the organization.
    replayed
        Whether an exact idempotent retry reused the prior outcome.
    created_organization
        Whether this request created the organization.
    created_series
        Whether this request created the convention series.
    created_edition
        Whether this request created the event edition.
    """

    edition: EventEdition
    representation: OrganizationRepresentation
    replayed: bool
    created_organization: bool
    created_series: bool
    created_edition: bool


def _request_digest(details: WorkforceAdoptionSetupInput) -> str:
    payload: dict[str, str | None] = {
        "edition_name": " ".join(details.edition_name.split()),
        "ends_on": details.ends_on.isoformat(),
        "mode": details.mode,
        "starts_on": details.starts_on.isoformat(),
        "time_zone": details.time_zone.strip(),
    }
    if details.mode == WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION:
        payload.update(
            {
                "organization_name": " ".join(details.organization_name.split()),
                "series_name": " ".join(details.series_name.split()),
            }
        )
    elif details.mode == WorkforceAdoptionSetupReceipt.Mode.EXISTING_ORGANIZATION:
        payload.update(
            {
                "organization_id": (
                    str(details.organization_id) if details.organization_id else None
                ),
                "series_name": " ".join(details.series_name.split()),
            }
        )
    elif details.mode == WorkforceAdoptionSetupReceipt.Mode.EXISTING_SERIES:
        payload["series_id"] = str(details.series_id) if details.series_id else None
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _lock_setup_key(idempotency_key: UUID) -> None:
    lock_key = (
        idempotency_key.int ^ WORKFORCE_SETUP_LOCK_NAMESPACE
    ) & 0x7FFFFFFFFFFFFFFF
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_key])


def _resolve_foundation(
    *,
    actor: Account,
    details: WorkforceAdoptionSetupInput,
    correlation_id: UUID,
    source_channel: str,
) -> tuple[Organization, ConventionSeries, bool, bool]:
    if details.mode == WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION:
        organization = create_draft_organization(
            actor=actor,
            details=OrganizationCreationDetails(
                name=details.organization_name,
                default_language_codes=("en",),
                default_time_zone=details.time_zone,
            ),
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        series = create_convention_series(
            actor=actor,
            organization_id=organization.id,
            details=ConventionSeriesCreationDetails(name=details.series_name),
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        return organization, series, True, True

    if details.mode == WorkforceAdoptionSetupReceipt.Mode.EXISTING_ORGANIZATION:
        if details.organization_id is None:
            raise ValidationError(
                {"organization": "Choose the organization to reuse."},
                code="workforce_setup_organization_required",
            )
        organization = Organization.objects.select_for_update().get(
            id=details.organization_id,
        )
        if organization.lifecycle not in {
            Organization.Lifecycle.DRAFT,
            Organization.Lifecycle.ACTIVE,
        }:
            raise ValidationError(
                "Only a Draft or Active organization can add Workforce.",
                code="workforce_setup_organization_unavailable",
            )
        if (
            organization.lifecycle == Organization.Lifecycle.ACTIVE
            and not OrganizationRepresentation.objects.filter(
                organization=organization
            ).exists()
        ):
            raise ValidationError(
                "An Active organization must already have accountable access "
                "before it can be reused for Workforce setup.",
                code="workforce_setup_representation_required",
            )
        series = create_convention_series(
            actor=actor,
            organization_id=organization.id,
            details=ConventionSeriesCreationDetails(name=details.series_name),
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        return organization, series, False, True

    if details.mode == WorkforceAdoptionSetupReceipt.Mode.EXISTING_SERIES:
        if details.series_id is None:
            raise ValidationError(
                {"series": "Choose the convention series to reuse."},
                code="workforce_setup_series_required",
            )
        series = (
            ConventionSeries.objects.select_for_update()
            .select_related("organization")
            .get(id=details.series_id, is_active=True)
        )
        organization = Organization.objects.select_for_update().get(
            id=series.organization_id,
            lifecycle__in=(
                Organization.Lifecycle.DRAFT,
                Organization.Lifecycle.ACTIVE,
            ),
        )
        if (
            organization.lifecycle == Organization.Lifecycle.ACTIVE
            and not OrganizationRepresentation.objects.filter(
                organization=organization
            ).exists()
        ):
            raise ValidationError(
                "This series belongs to an Active organization without "
                "accountable Maru access and cannot be reused yet.",
                code="workforce_setup_representation_required",
            )
        return organization, series, False, False

    raise ValidationError(
        {"mode": "Choose how Maru should establish the Workforce foundation."},
        code="workforce_setup_mode_unsupported",
    )


def _setup_result_from_receipt(
    receipt: WorkforceAdoptionSetupReceipt,
) -> WorkforceAdoptionSetupResult:
    representation = OrganizationRepresentation.objects.get(
        organization_id=receipt.organization_id,
    )
    return WorkforceAdoptionSetupResult(
        edition=receipt.edition,
        representation=representation,
        replayed=True,
        created_organization=receipt.created_organization,
        created_series=receipt.created_series,
        created_edition=receipt.created_edition,
    )


@transaction.atomic
def set_up_workforce_adoption(
    *,
    actor: Account,
    details: WorkforceAdoptionSetupInput,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "service",
) -> WorkforceAdoptionSetupResult:
    """Create or reuse the minimum foundation for Workforce-only adoption.

    The transaction deliberately creates no attendee Registration, payment,
    attendance, catalog, application, or unrelated module records. If the
    organization has no representation, it provisions truthful Maru operators
    and leaves invitations and activation as explicit human steps.

    Parameters
    ----------
    actor : Account
        The authenticated platform administrator authorizing setup.
    details : WorkforceAdoptionSetupInput
        The complete normalized guided-setup request.
    idempotency_key : UUID
        The stable key used to serialize and replay an exact request.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    WorkforceAdoptionSetupResult
        The exact retained foundation and replay metadata.

    Raises
    ------
    PermissionDenied
        If the caller is not an active platform administrator.
    ValidationError
        If the mode, retry, or selected foundation violates the contract.
    """
    if not actor.is_active or not actor.is_platform_administrator:
        raise PermissionDenied("Platform administration is required.")

    _lock_setup_key(idempotency_key)
    digest = _request_digest(details)
    existing = (
        WorkforceAdoptionSetupReceipt.objects.select_related("edition")
        .filter(actor_id=actor.id, idempotency_key=idempotency_key)
        .first()
    )
    if existing is not None:
        if existing.request_digest != digest:
            raise ValidationError(
                {
                    "idempotency_key": ValidationError(
                        "This setup key was already used with different details.",
                        code="workforce_setup_idempotency_conflict",
                    )
                }
            )
        return _setup_result_from_receipt(existing)

    organization, series, created_organization, created_series = _resolve_foundation(
        actor=actor,
        details=details,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    edition_result = create_event_edition(
        actor=actor,
        organization_id=organization.id,
        series_id=series.id,
        details=EventEditionDetails(
            name=details.edition_name,
            time_zone=details.time_zone,
            language_codes=tuple(organization.default_language_codes) or ("en",),
            currency_codes=("XXX",),
            starts_on=details.starts_on,
            ends_on=details.ends_on,
        ),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        request_id=correlation_id,
        source_channel=source_channel,
        adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY,
    )
    edition = edition_result.edition
    profile = adoption_profile(
        edition.adoption_profile_code,
        edition.adoption_profile_version,
    )
    if profile is None or profile.key != (
        AdoptionProfileCode.WORKFORCE_ONLY.value,
        WORKFORCE_ONLY_PROFILE_VERSION,
    ):
        raise ValidationError(
            "The retained edition does not match Workforce-only setup.",
            code="workforce_setup_profile_conflict",
        )

    representation = (
        OrganizationRepresentation.objects.select_for_update()
        .filter(organization=organization)
        .first()
    )
    if representation is None:
        representation = provision_maru_operators(
            actor=actor,
            organization_id=organization.id,
            reason=(
                "Establish accountable Maru operators for Workforce-only adoption."
            ),
            correlation_id=correlation_id,
            source_channel=source_channel,
        )

    receipt = WorkforceAdoptionSetupReceipt.objects.create(
        edition=edition,
        organization_id=organization.id,
        series_id=series.id,
        actor_id=actor.id,
        idempotency_key=idempotency_key,
        request_digest=digest,
        mode=details.mode,
        representation_code=representation.code,
        created_organization=created_organization,
        created_series=created_series,
        created_edition=not edition_result.replayed,
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=edition.id,
            capability_code="events.create",
            operation="events.workforce_adoption.setup",
            target_type="events.workforce_adoption_setup_receipt",
            target_id=receipt.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="platform_administration",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            changed_fields=(
                "adoption_profile",
                "foundation",
                "representation",
            ),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-standard",
        )
    )
    return WorkforceAdoptionSetupResult(
        edition=edition,
        representation=representation,
        replayed=False,
        created_organization=created_organization,
        created_series=created_series,
        created_edition=not edition_result.replayed,
    )
