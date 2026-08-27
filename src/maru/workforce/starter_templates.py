"""Governed starter Position templates for focused Workforce adoption."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.commands import create_role_bundle_version
from maru.authorization.models import RoleBundle
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.events.adoption import AdoptionProfileCode
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import (
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.workforce.edition_write_scope import lock_workforce_edition_write_scope
from maru.workforce.models import PositionTemplate

if TYPE_CHECKING:
    from uuid import UUID

WORKFORCE_VOLUNTEER_TEMPLATE_CODE = "workforce-volunteer"
WORKFORCE_VOLUNTEER_TEMPLATE_NAME = "Workforce volunteer"
WORKFORCE_VOLUNTEER_ROLE_CAPABILITIES = (
    "events.view_basic",
    "workforce.view_structure",
)
WORKFORCE_VOLUNTEER_CAPACITY_CODES = ("volunteer",)
MAX_WORKFORCE_STARTER_REASON_LENGTH = 240


class WorkforceStarterTemplateConflictError(ValidationError):
    """Signal that the reserved starter identity already has another meaning."""


@dataclass(frozen=True, slots=True)
class WorkforceStarterTemplateResult:
    """Describe a safely published Workforce starter template.

    Attributes
    ----------
    template
        The immutable published Position template.
    role_bundle
        The independently approved immutable role meaning pinned by the template.
    replayed
        Whether the exact starter already existed and no mutation was required.
    """

    template: PositionTemplate
    role_bundle: RoleBundle
    replayed: bool


def _active_controller(
    *,
    organization_id: UUID,
    account_id: UUID,
) -> bool:
    return RepresentationAppointment.objects.filter(
        representation__organization_id=organization_id,
        representation__state=OrganizationRepresentation.State.ACTIVE,
        account_id=account_id,
        role=RepresentationAppointment.Role.CONTROLLER,
        state=RepresentationAppointment.State.ACTIVE,
    ).exists()


def can_provision_workforce_starter_template(
    *,
    actor: Account,
    edition: EventEdition,
) -> bool:
    """Return whether an accountable controller may create the safe starter.

    Parameters
    ----------
    actor : Account
        The authenticated account evaluated for the guided action.
    edition : EventEdition
        The exact Workforce-only edition that needs a compatible template.

    Returns
    -------
    bool
        ``True`` only for a current accountable controller with both required
        organization and edition authority.
    """
    if (
        not actor.is_active
        or actor.is_platform_administrator
        or edition.adoption_profile_code != AdoptionProfileCode.WORKFORCE_ONLY
        or not _active_controller(
            organization_id=edition.organization_id,
            account_id=actor.id,
        )
    ):
        return False
    organization_target = resolve_organization_target(
        organization_id=edition.organization_id,
    )
    edition_target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    return bool(
        organization_target is not None
        and edition_target is not None
        and decide(
            principal=actor,
            capability_code="authorization.manage_roles",
            resource=organization_target,
        ).allowed
        and decide(
            principal=actor,
            capability_code="workforce.manage_structure",
            resource=edition_target,
        ).allowed
    )


def _existing_starter(
    *,
    organization_id: UUID,
) -> WorkforceStarterTemplateResult | None:
    templates = tuple(
        PositionTemplate.objects.select_related("role_bundle")
        .filter(
            organization_id=organization_id,
            code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
        )
        .order_by("version", "id")
    )
    roles = tuple(
        RoleBundle.objects.filter(
            organization_id=organization_id,
            code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
        ).order_by("version", "id")
    )
    if not templates and not roles:
        return None
    if (
        len(templates) == 1
        and len(roles) == 1
        and templates[0].role_bundle_id == roles[0].id
        and templates[0].version == 1
        and roles[0].version == 1
        and templates[0].name == WORKFORCE_VOLUNTEER_TEMPLATE_NAME
        and roles[0].name == WORKFORCE_VOLUNTEER_TEMPLATE_NAME
        and templates[0].description
        == "Contributes to one convention without organizer or attendee authority."
        and templates[0].default_headcount == 1
        and tuple(templates[0].default_capacity_codes)
        == WORKFORCE_VOLUNTEER_CAPACITY_CODES
        and tuple(roles[0].capability_codes) == WORKFORCE_VOLUNTEER_ROLE_CAPABILITIES
        and templates[0].status == PositionTemplate.Status.PUBLISHED
        and hasattr(roles[0], "authority_issuance")
    ):
        return WorkforceStarterTemplateResult(
            template=templates[0],
            role_bundle=roles[0],
            replayed=True,
        )
    raise WorkforceStarterTemplateConflictError(
        "The reserved Workforce volunteer starter already has another meaning.",
        code="workforce_starter_template_conflict",
    )


def _accountable_approver(
    *,
    organization_id: UUID,
    actor: Account,
    approver_email: str,
) -> Account:
    approver = (
        Account.objects.select_for_update()
        .filter(
            email__iexact=approver_email.strip(),
            is_active=True,
            account_kind=Account.Kind.PERSON,
            email_verified_at__isnull=False,
        )
        .order_by()
        .first()
    )
    if (
        approver is None
        or approver.id == actor.id
        or not _active_controller(
            organization_id=organization_id,
            account_id=approver.id,
        )
    ):
        raise ValidationError(
            {
                "approver_email": (
                    "Choose a different active accountable controller for this "
                    "organization."
                )
            },
            code="workforce_starter_approver_unavailable",
        )
    return approver


@transaction.atomic
def provision_workforce_starter_template(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    approver_email: str,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> WorkforceStarterTemplateResult:
    """Publish one minimal, independently approved Volunteer template.

    The starter defines future Position meaning but grants nobody access and
    creates no Position, assignment, Participation, Registration, or payment
    record. Relationship-derived self-service authority remains separate.

    Parameters
    ----------
    actor : Account
        The active accountable controller initiating the action.
    organization_id : UUID
        The exact organization that owns the reusable template.
    series_id : UUID
        The exact convention series in the locked route chain.
    edition_id : UUID
        The Workforce-only edition whose journey needs the starter.
    approver_email : str
        Exact email of a different active accountable controller.
    reason : str
        The retained administrative rationale.
    correlation_id : UUID
        The audit correlation identifier.
    request_id : UUID | None, default=None
        The incoming request identifier when distinct from correlation.
    source_channel : str, default='service'
        The closed channel code identifying the caller.

    Returns
    -------
    WorkforceStarterTemplateResult
        The immutable template, its role meaning, and replay state.

    Raises
    ------
    PermissionDenied
        If the actor is not a current accountable controller with both required
        capabilities.
    ValidationError
        If the profile, approver, reason, or retained starter is incompatible.
    """
    normalized_reason = " ".join(reason.split())
    if not normalized_reason:
        raise ValidationError(
            {"reason": "Explain why this starter is needed."},
            code="workforce_starter_reason_required",
        )
    if len(normalized_reason) > MAX_WORKFORCE_STARTER_REASON_LENGTH:
        raise ValidationError(
            {"reason": "Ensure the reason has at most 240 characters."},
            code="workforce_starter_reason_too_long",
        )

    scope = lock_workforce_edition_write_scope(
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    edition = EventEdition.objects.get(id=scope.edition_id)
    if edition.adoption_profile_code != AdoptionProfileCode.WORKFORCE_ONLY:
        raise ValidationError(
            "The safe starter is available only inside a Workforce-only edition.",
            code="workforce_starter_profile_required",
        )
    if not can_provision_workforce_starter_template(actor=actor, edition=edition):
        raise PermissionDenied(
            "Current accountable Workforce and role authority is required."
        )

    existing = _existing_starter(organization_id=scope.organization_id)
    if existing is not None:
        return existing
    approver = _accountable_approver(
        organization_id=scope.organization_id,
        actor=actor,
        approver_email=approver_email,
    )
    organization_target = resolve_organization_target(
        organization_id=scope.organization_id,
    )
    if organization_target is None:
        raise PermissionDenied("The accountable organization is unavailable.")

    role_bundle = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=organization_target,
        code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
        name=WORKFORCE_VOLUNTEER_TEMPLATE_NAME,
        capability_codes=WORKFORCE_VOLUNTEER_ROLE_CAPABILITIES,
        reason=normalized_reason,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )
    template = PositionTemplate.objects.create(
        organization_id=scope.organization_id,
        code=WORKFORCE_VOLUNTEER_TEMPLATE_CODE,
        name=WORKFORCE_VOLUNTEER_TEMPLATE_NAME,
        version=1,
        description=(
            "Contributes to one convention without organizer or attendee authority."
        ),
        default_headcount=1,
        default_capacity_codes=list(WORKFORCE_VOLUNTEER_CAPACITY_CODES),
        role_bundle=role_bundle,
        status=PositionTemplate.Status.PUBLISHED,
        created_by=actor,
    )
    occurred_at = timezone.now()
    actor_audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code="workforce.manage_structure",
            operation="workforce.position_template.starter_create",
            target_type="workforce.position_template",
            target_id=template.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="independent_approval",
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=("reason", "audit", "approval"),
            changed_fields=("position_template", "role_bundle"),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-restricted",
        ),
        occurred_at=occurred_at,
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=approver.id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code="authorization.manage_roles",
            operation="workforce.position_template.starter_approve",
            target_type="workforce.position_template",
            target_id=template.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="independent_approval",
            correlation_id=correlation_id,
            causation_id=actor_audit.id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=("reason", "audit", "approval"),
            changed_fields=(),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-restricted",
        ),
        occurred_at=occurred_at,
    )
    return WorkforceStarterTemplateResult(
        template=template,
        role_bundle=role_bundle,
        replayed=False,
    )
