"""Audited platform commands for organization provisioning."""

from dataclasses import dataclass, replace
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.text import slugify

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.identity.models import Account
from maru.organizations.models import Organization

MAX_ORGANIZATION_NAME_LENGTH = 160
MAX_ORGANIZATION_SLUG_LENGTH = 80
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


@dataclass(frozen=True, slots=True)
class OrganizationCreationDetails:
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


@transaction.atomic
def create_draft_organization(
    *,
    actor: Account,
    details: OrganizationCreationDetails,
    correlation_id: UUID,
    source_channel: str = "service",
) -> Organization:
    """Create one draft tenant without creating convention relationships."""

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
