"""Audited platform commands for organization provisioning."""

from dataclasses import dataclass, replace
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils.text import slugify

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_organization_target,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization

MAX_ORGANIZATION_NAME_LENGTH = 160
MAX_ORGANIZATION_SLUG_LENGTH = 80
MAX_SERIES_NAME_LENGTH = 160
MAX_SERIES_DESCRIPTION_LENGTH = 2000
MAX_SERIES_SLUG_LENGTH = 80
MAX_SLUG_CANDIDATES = 10_000

ORGANIZATION_CREATION_FIELDS = (
    "name",
    "slug",
    "lifecycle",
    "description",
    "legal_name",
    "legal_address",
    "legal_representative",
    "registration_authority",
    "registration_identifier",
    "tax_identifier",
    "imprint_text",
    "website_url",
    "contact_email",
    "contact_phone",
    "country_code",
    "default_language_codes",
    "default_time_zone",
)

ORGANIZATION_PROFILE_FIELDS = tuple(
    field_name
    for field_name in ORGANIZATION_CREATION_FIELDS
    if field_name not in {"slug", "lifecycle"}
)

CONVENTION_SERIES_CREATION_FIELDS = (
    "organization",
    "name",
    "slug",
    "description",
    "website_url",
    "contact_email",
    "is_active",
    "profile_version",
)

CONVENTION_SERIES_PROFILE_FIELDS = (
    "name",
    "description",
    "website_url",
    "contact_email",
    "is_active",
)


@dataclass(frozen=True, slots=True)
class OrganizationCreationDetails:
    """Describe organization creation details.

    Attributes
    ----------
    name
        The human-readable name to normalize or persist.
    description
        The human-readable description shown to authorized readers.
    legal_name
        The human-readable legal name shown to authorized readers.
    legal_address
        The legal address retained in this immutable projection.
    legal_representative
        The legal representative retained in this immutable projection.
    registration_authority
        The registration authority retained in this immutable projection.
    registration_identifier
        The registration identifier retained in this immutable projection.
    tax_identifier
        The tax identifier retained in this immutable projection.
    imprint_text
        The imprint text retained in this immutable projection.
    website_url
        The validated absolute HTTPS website url.
    contact_email
        The normalized contact email used for delivery or identity matching.
    contact_phone
        The normalized international contact phone, when provided.
    country_code
        The stable country code from the relevant closed catalog.
    default_language_codes
        The default language codes retained in this immutable projection.
    default_time_zone
        The IANA time-zone name used for localization and validation.
    """

    name: str
    description: str = ""
    legal_name: str = ""
    legal_address: str = ""
    legal_representative: str = ""
    registration_authority: str = ""
    registration_identifier: str = ""
    tax_identifier: str = ""
    imprint_text: str = ""
    website_url: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    country_code: str = ""
    default_language_codes: tuple[str, ...] = ("en",)
    default_time_zone: str = "UTC"


@dataclass(frozen=True, slots=True)
class ConventionSeriesCreationDetails:
    """Describe convention series creation details.

    Attributes
    ----------
    name
        The human-readable name to normalize or persist.
    description
        The human-readable description shown to authorized readers.
    website_url
        The validated absolute HTTPS website url.
    contact_email
        The normalized contact email used for delivery or identity matching.
    is_active
        Whether to is active.
    """

    name: str
    description: str = ""
    website_url: str = ""
    contact_email: str = ""
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class OrganizationUpdateResult:
    """Describe organization update result.

    Attributes
    ----------
    organization
        The organization that owns the requested resource.
    changed_fields
        The canonical field names changed by the operation.
    """

    organization: Organization
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConventionSeriesUpdateResult:
    """Describe convention series update result.

    Attributes
    ----------
    series
        The series retained in this immutable projection.
    changed_fields
        The canonical field names changed by the operation.
    """

    series: ConventionSeries
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeletedOrganization:
    """Describe deleted organization.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    name
        The human-readable name to normalize or persist.
    """

    id: UUID
    name: str


def _require_organization_capability(
    *,
    actor: Account,
    organization_id: UUID,
    capability_code: str,
) -> PolicyDecision:
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=resolve_organization_target(organization_id=organization_id),
    )
    if not decision.allowed:
        raise PermissionDenied("Organization authority is required.")
    return decision


def _normalize_organization_name(name: str) -> str:
    normalized = " ".join(name.split())
    if not normalized:
        raise ValidationError(
            {"name": "Enter an organization name."},
            code="organization_name_required",
        )
    if len(normalized) > MAX_ORGANIZATION_NAME_LENGTH:
        raise ValidationError(
            {
                "name": (
                    "Ensure this value has at most "
                    f"{MAX_ORGANIZATION_NAME_LENGTH} characters."
                )
            },
            code="organization_name_too_long",
        )
    return normalized


def _slug_candidate(base: str, number: int) -> str:
    suffix = "" if number == 1 else f"-{number}"
    stem = base[: MAX_ORGANIZATION_SLUG_LENGTH - len(suffix)].rstrip("-")
    return f"{stem}{suffix}"


def _series_slug_candidate(base: str, number: int) -> str:
    suffix = "" if number == 1 else f"-{number}"
    stem = base[: MAX_SERIES_SLUG_LENGTH - len(suffix)].rstrip("-")
    return f"{stem}{suffix}"


def _create_with_generated_slug(
    *, details: OrganizationCreationDetails
) -> Organization:
    base = (
        slugify(details.name)[:MAX_ORGANIZATION_SLUG_LENGTH].strip("-")
        or "organization"
    )
    for number in range(1, MAX_SLUG_CANDIDATES + 1):
        candidate = _slug_candidate(base, number)
        if Organization.objects.filter(slug__iexact=candidate).exists():
            continue
        try:
            with transaction.atomic():
                return Organization.objects.create(
                    name=details.name,
                    slug=candidate,
                    lifecycle=Organization.Lifecycle.DRAFT,
                    description=details.description,
                    legal_name=details.legal_name,
                    legal_address=details.legal_address,
                    legal_representative=details.legal_representative,
                    registration_authority=details.registration_authority,
                    registration_identifier=details.registration_identifier,
                    tax_identifier=details.tax_identifier,
                    imprint_text=details.imprint_text,
                    website_url=details.website_url,
                    contact_email=details.contact_email,
                    contact_phone=details.contact_phone,
                    country_code=details.country_code,
                    default_language_codes=list(details.default_language_codes)
                    or ["en"],
                    default_time_zone=details.default_time_zone or "UTC",
                )
        except (IntegrityError, ValidationError):
            if Organization.objects.filter(slug__iexact=candidate).exists():
                continue
            raise
    raise ValidationError(
        {"name": "Maru could not generate an available organization URL name."},
        code="organization_slug_unavailable",
    )


def _normalize_series_details(
    details: ConventionSeriesCreationDetails,
) -> ConventionSeriesCreationDetails:
    name = " ".join(details.name.split())
    if not name:
        raise ValidationError(
            {"name": "Enter a convention series name."},
            code="series_name_required",
        )
    if len(name) > MAX_SERIES_NAME_LENGTH:
        raise ValidationError(
            {
                "name": (
                    "Ensure this value has at most "
                    f"{MAX_SERIES_NAME_LENGTH} characters."
                )
            },
            code="series_name_too_long",
        )
    description = details.description.strip()
    if len(description) > MAX_SERIES_DESCRIPTION_LENGTH:
        raise ValidationError(
            {
                "description": (
                    "Ensure this value has at most "
                    f"{MAX_SERIES_DESCRIPTION_LENGTH} characters."
                )
            },
            code="series_description_too_long",
        )
    return replace(
        details,
        name=name,
        description=description,
        website_url=details.website_url.strip(),
        contact_email=details.contact_email.strip(),
    )


def _create_series_with_generated_slug(
    *,
    organization: Organization,
    details: ConventionSeriesCreationDetails,
) -> ConventionSeries:
    base = slugify(details.name)[:MAX_SERIES_SLUG_LENGTH].strip("-") or "series"
    for number in range(1, MAX_SLUG_CANDIDATES + 1):
        candidate = _series_slug_candidate(base, number)
        scoped_slug = ConventionSeries.objects.filter(
            organization=organization,
            slug__iexact=candidate,
        )
        if scoped_slug.exists():
            continue
        try:
            with transaction.atomic():
                return ConventionSeries.objects.create(
                    organization=organization,
                    name=details.name,
                    slug=candidate,
                    description=details.description,
                    website_url=details.website_url,
                    contact_email=details.contact_email,
                    is_active=details.is_active,
                )
        except (IntegrityError, ValidationError):
            if scoped_slug.exists():
                continue
            raise
    raise ValidationError(
        {"name": "Maru could not generate an available series URL name."},
        code="series_slug_unavailable",
    )


@transaction.atomic
def create_convention_series(
    *,
    actor: Account,
    organization_id: UUID,
    details: ConventionSeriesCreationDetails,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ConventionSeries:
    """Create one recurring brand beneath a non-closed organization.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    details : ConventionSeriesCreationDetails
        The structured, disclosure-safe details recorded with the outcome.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    ConventionSeries
        The newly created ConventionSeries.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    decision = _require_organization_capability(
        actor=actor,
        organization_id=organization_id,
        capability_code="organizations.create_series",
    )

    organization = Organization.objects.select_for_update().get(id=organization_id)
    if organization.lifecycle == Organization.Lifecycle.CLOSED:
        raise ValidationError(
            "A Closed organization cannot create a convention series.",
            code="series_parent_closed",
        )
    normalized_details = _normalize_series_details(details)
    series = _create_series_with_generated_slug(
        organization=organization,
        details=normalized_details,
    )
    audit_event = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=None,
            capability_code="organizations.create_series",
            operation="organizations.convention_series.create",
            target_type="organizations.conventionseries",
            target_id=series.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(decision.obligations)),
            changed_fields=CONVENTION_SERIES_CREATION_FIELDS,
            retention_class="security-standard",
        )
    )
    publish_domain_event(
        DomainEventRecord(
            event_name="organizations.convention_series.created.v1",
            schema_version=1,
            organization_id=organization.id,
            event_edition_id=None,
            aggregate_type="organizations.convention_series",
            aggregate_id=series.id,
            aggregate_version=series.profile_version,
            payload={
                "availability": "active" if series.is_active else "inactive",
                "profile_version": str(series.profile_version),
            },
            correlation_id=correlation_id,
            causation_id=audit_event.id,
            actor_kind="account",
            actor_id=actor.id,
        ),
        workload_pool="core",
    )
    return series


@transaction.atomic
def update_convention_series(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    expected_profile_version: int,
    details: ConventionSeriesCreationDetails,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ConventionSeriesUpdateResult:
    """Update one scoped recurring brand without changing ownership or slug.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    expected_profile_version : int
        The expected expected profile version used to reject stale updates.
    details : ConventionSeriesCreationDetails
        The structured, disclosure-safe details recorded with the outcome.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    ConventionSeriesUpdateResult
        The updated ConventionSeriesUpdateResult after the transition is
        committed.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    decision = _require_organization_capability(
        actor=actor,
        organization_id=organization_id,
        capability_code="organizations.change_series",
    )

    organization = Organization.objects.select_for_update().get(id=organization_id)
    series = ConventionSeries.objects.select_for_update().get(
        id=series_id,
        organization=organization,
    )
    if organization.lifecycle == Organization.Lifecycle.CLOSED:
        raise ValidationError(
            "A Closed organization's convention series is retained read-only.",
            code="series_parent_closed",
        )
    if series.profile_version != expected_profile_version:
        raise ValidationError(
            {
                "expected_profile_version": ValidationError(
                    (
                        "This convention series changed after the page was "
                        "loaded. Reload it before saving your changes."
                    ),
                    code="stale_series_profile",
                )
            }
        )

    normalized = _normalize_series_details(details)
    values: dict[str, object] = {
        "name": normalized.name,
        "description": normalized.description,
        "website_url": normalized.website_url,
        "contact_email": normalized.contact_email,
        "is_active": normalized.is_active,
    }
    changed_fields = tuple(
        field_name
        for field_name in CONVENTION_SERIES_PROFILE_FIELDS
        if getattr(series, field_name) != values[field_name]
    )
    if not changed_fields:
        return ConventionSeriesUpdateResult(series=series, changed_fields=())

    for field_name in changed_fields:
        setattr(series, field_name, values[field_name])
    series.profile_version += 1
    series.save(
        update_fields=(*changed_fields, "profile_version", "updated_at"),
    )
    audited_fields = (*changed_fields, "profile_version")
    audit_event = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=None,
            capability_code="organizations.change_series",
            operation="organizations.convention_series.update",
            target_type="organizations.conventionseries",
            target_id=series.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(decision.obligations)),
            changed_fields=audited_fields,
            retention_class="security-standard",
        )
    )
    publish_domain_event(
        DomainEventRecord(
            event_name="organizations.convention_series.updated.v1",
            schema_version=1,
            organization_id=organization.id,
            event_edition_id=None,
            aggregate_type="organizations.convention_series",
            aggregate_id=series.id,
            aggregate_version=series.profile_version,
            payload={
                "availability": "active" if series.is_active else "inactive",
                "changed_fields": ",".join(changed_fields),
                "profile_version": str(series.profile_version),
            },
            correlation_id=correlation_id,
            causation_id=audit_event.id,
            actor_kind="account",
            actor_id=actor.id,
        ),
        workload_pool="core",
    )
    return ConventionSeriesUpdateResult(
        series=series,
        changed_fields=changed_fields,
    )


@transaction.atomic
def create_draft_organization(
    *,
    actor: Account,
    details: OrganizationCreationDetails,
    correlation_id: UUID,
    source_channel: str = "service",
) -> Organization:
    """Create one draft tenant without creating convention relationships.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    details : OrganizationCreationDetails
        The structured, disclosure-safe details recorded with the outcome.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    Organization
        The newly created Organization.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    if not actor.is_active or not actor.is_platform_administrator:
        raise PermissionDenied("Platform administration is required.")

    normalized_details = replace(
        details,
        name=_normalize_organization_name(details.name),
    )
    organization = _create_with_generated_slug(details=normalized_details)
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=None,
            capability_code="organizations.create",
            operation="organizations.organization.create",
            target_type="organizations.organization",
            target_id=organization.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="platform_administration",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            changed_fields=ORGANIZATION_CREATION_FIELDS,
            retention_class="security-standard",
        )
    )
    return organization


def _profile_values(details: OrganizationCreationDetails) -> dict[str, object]:
    return {
        "name": details.name,
        "description": details.description,
        "legal_name": details.legal_name,
        "legal_address": details.legal_address,
        "legal_representative": details.legal_representative,
        "registration_authority": details.registration_authority,
        "registration_identifier": details.registration_identifier,
        "tax_identifier": details.tax_identifier,
        "imprint_text": details.imprint_text,
        "website_url": details.website_url,
        "contact_email": details.contact_email,
        "contact_phone": details.contact_phone,
        "country_code": details.country_code,
        "default_language_codes": list(details.default_language_codes) or ["en"],
        "default_time_zone": details.default_time_zone or "UTC",
    }


@transaction.atomic
def update_organization_profile(
    *,
    actor: Account,
    organization_id: UUID,
    details: OrganizationCreationDetails,
    correlation_id: UUID,
    source_channel: str = "service",
) -> OrganizationUpdateResult:
    """Update code-independent profile fields without changing tenant identity.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    details : OrganizationCreationDetails
        The structured, disclosure-safe details recorded with the outcome.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    OrganizationUpdateResult
        The updated OrganizationUpdateResult after the transition is committed.
    """
    decision = _require_organization_capability(
        actor=actor,
        organization_id=organization_id,
        capability_code="organizations.change_profile",
    )

    organization = Organization.objects.select_for_update().get(id=organization_id)
    normalized_details = replace(
        details,
        name=_normalize_organization_name(details.name),
    )
    values = _profile_values(normalized_details)
    changed_fields = tuple(
        field_name
        for field_name in ORGANIZATION_PROFILE_FIELDS
        if getattr(organization, field_name) != values[field_name]
    )
    if not changed_fields:
        return OrganizationUpdateResult(
            organization=organization,
            changed_fields=(),
        )

    for field_name in changed_fields:
        setattr(organization, field_name, values[field_name])
    organization.save(update_fields=(*changed_fields, "updated_at"))
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=None,
            capability_code="organizations.change_profile",
            operation="organizations.organization.update",
            target_type="organizations.organization",
            target_id=organization.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(decision.obligations)),
            changed_fields=changed_fields,
            retention_class="security-standard",
        )
    )
    return OrganizationUpdateResult(
        organization=organization,
        changed_fields=changed_fields,
    )


@transaction.atomic
def delete_empty_draft_organization(
    *,
    actor: Account,
    organization_id: UUID,
    confirmation_name: str,
    acknowledged: bool,
    correlation_id: UUID,
    source_channel: str = "service",
) -> DeletedOrganization:
    """Delete one unused Draft; protected domain history always wins.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    confirmation_name : str
        The human-readable confirmation name shown to authorized readers.
    acknowledged : bool
        The acknowledged applied within the audited domain transition.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    DeletedOrganization
        The resolved DeletedOrganization for delete empty draft organization.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not actor.is_active or not actor.is_platform_administrator:
        raise PermissionDenied("Platform administration is required.")

    organization = Organization.objects.select_for_update().get(id=organization_id)
    if organization.lifecycle != Organization.Lifecycle.DRAFT:
        raise ValidationError(
            "Only an empty Draft organization can be deleted.",
            code="organization_delete_not_draft",
        )
    if confirmation_name != organization.name:
        raise ValidationError(
            "Enter the organization name exactly as shown above.",
            code="organization_delete_name_mismatch",
        )
    if not acknowledged:
        raise ValidationError(
            "Acknowledge the permanent deletion before continuing.",
            code="organization_delete_acknowledgement_required",
        )

    deleted = DeletedOrganization(id=organization.id, name=organization.name)
    try:
        organization.delete()
    except (ProtectedError, RestrictedError) as error:
        raise ValidationError(
            "This organization has related records and cannot be deleted. "
            "Keep it for history and use a later closure workflow.",
            code="organization_delete_protected",
        ) from error

    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=deleted.id,
            event_edition_id=None,
            capability_code="organizations.delete",
            operation="organizations.organization.delete",
            target_type="organizations.organization",
            target_id=deleted.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="empty_draft_removed",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            changed_fields=("record",),
            retention_class="security-standard",
        )
    )
    return deleted
