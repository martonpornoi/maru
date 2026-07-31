"""Audited platform commands for organization provisioning."""

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


def _create_with_generated_slug(*, name: str) -> Organization:
    base = slugify(name)[:MAX_ORGANIZATION_SLUG_LENGTH].strip("-") or "organization"
    for number in range(1, MAX_SLUG_CANDIDATES + 1):
        candidate = _slug_candidate(base, number)
        if Organization.objects.filter(slug__iexact=candidate).exists():
            continue
        try:
            with transaction.atomic():
                return Organization.objects.create(
                    name=name,
                    slug=candidate,
                    lifecycle=Organization.Lifecycle.DRAFT,
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
    name: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> Organization:
    """Create one draft tenant without creating convention relationships."""

    if not actor.is_active or not actor.is_platform_administrator:
        raise PermissionDenied("Platform administration is required.")

    normalized_name = _normalize_organization_name(name)
    organization = _create_with_generated_slug(name=normalized_name)
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
            changed_fields=("name", "slug", "lifecycle"),
            retention_class="security-standard",
        )
    )
    return organization
