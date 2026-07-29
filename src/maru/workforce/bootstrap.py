"""One-shot trust-on-first-use organizer authority and starter templates."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization, OrganizationMembership
from maru.participation.models import Participation, ParticipationCapacity
from maru.workforce.models import (
    Department,
    Position,
    PositionAssignment,
    PositionTemplate,
)


@dataclass(frozen=True, slots=True)
class StarterPosition:
    code: str
    name: str
    description: str
    headcount: int
    capacity_codes: tuple[str, ...]
    capability_codes: tuple[str, ...]


COMMON_VIEW = (
    "events.view_basic",
    "participation.view_staff_summary",
    "workforce.view_structure",
)
COMMON_WORKFORCE = (
    *COMMON_VIEW,
    "workforce.manage_structure",
    "workforce.manage_applications",
    "workforce.manage_documents",
    "workforce.manage_assignments",
)
REGISTRATION_TEAM = (
    *COMMON_VIEW,
    "registration.view_service_summary",
    "registration.register_on_behalf",
    "registration.manage_exceptions",
    "registration.moderate_public_profile",
    "registration.view_attendee_reporting",
)
INITIAL_AUTHORITY_CAPABILITIES = (
    "authorization.delegate",
    "authorization.grant_direct",
    "authorization.revoke",
    "authorization.manage_roles",
)

STARTER_POSITIONS = (
    StarterPosition(
        "convention-chair",
        "Convention Chair",
        (
            "Accountable edition lead with organization, registration, and "
            "workforce control."
        ),
        1,
        ("staff", "volunteer"),
        (
            *COMMON_WORKFORCE,
            "events.transition",
            "authorization.delegate",
            "authorization.grant_direct",
            "authorization.revoke",
            "authorization.manage_roles",
            "registration.manage_configuration",
            "registration.view_service_summary",
            "registration.register_on_behalf",
            "registration.manage_exceptions",
            "registration.view_payment_summary",
            "registration.manage_finance",
            "registration.check_in",
            "registration.moderate_public_profile",
            "registration.view_attendee_reporting",
            "accreditation.issue",
            "accreditation.revoke",
        ),
    ),
    StarterPosition(
        "vice-chair",
        "Vice Chair",
        "Deputy edition lead and continuity owner.",
        1,
        ("staff", "volunteer"),
        (*COMMON_WORKFORCE, "events.transition", "authorization.manage_roles"),
    ),
    StarterPosition(
        "board-member",
        "Board Member",
        "Organizer governance and accountable review.",
        12,
        ("staff", "volunteer", "board-member"),
        (*COMMON_WORKFORCE, "registration.view_attendee_reporting"),
    ),
    StarterPosition(
        "department-lead",
        "Department Lead",
        "Leads one edition department and its people pipeline.",
        30,
        ("staff", "volunteer"),
        COMMON_WORKFORCE,
    ),
    StarterPosition(
        "registration-lead",
        "Registration Lead",
        "Owns registration configuration, attendee service, and exceptions.",
        4,
        ("staff", "volunteer"),
        (
            *REGISTRATION_TEAM,
            "registration.manage_configuration",
            "registration.view_payment_summary",
        ),
    ),
    StarterPosition(
        "front-desk",
        "Front Desk",
        "Serves confirmed attendees and performs reasoned check-in.",
        20,
        ("staff", "volunteer"),
        (
            *COMMON_VIEW,
            "registration.view_service_summary",
            "registration.check_in",
            "accreditation.issue",
        ),
    ),
    StarterPosition(
        "treasurer",
        "Treasurer",
        "Reviews payment evidence, finance operations, and reconciliation.",
        4,
        ("staff", "volunteer"),
        (
            *COMMON_VIEW,
            "registration.view_payment_summary",
            "registration.manage_finance",
            "registration.view_attendee_reporting",
        ),
    ),
    StarterPosition(
        "media-moderator",
        "Profile Media Moderator",
        "Reviews public attendee and fursuit images with recorded reasons.",
        8,
        ("staff", "volunteer"),
        (*COMMON_VIEW, "registration.moderate_public_profile"),
    ),
    StarterPosition(
        "staff-member",
        "Staff Member",
        "Contributes within a convention department.",
        250,
        ("staff", "volunteer"),
        COMMON_VIEW,
    ),
    StarterPosition(
        "volunteer",
        "Volunteer",
        "Contributes to the edition without broad staff access.",
        500,
        ("volunteer",),
        ("events.view_basic",),
    ),
)


def _membership(
    *,
    organization: Organization,
    account: Account,
    label: str,
) -> None:
    OrganizationMembership.objects.get_or_create(
        organization=organization,
        account=account,
        defaults={
            "state": OrganizationMembership.State.ACTIVE,
            "relationship_label": label,
            "started_at": timezone.now(),
        },
    )


def _participation(
    *,
    edition: EventEdition,
    account: Account,
    label: str,
    code: str,
) -> tuple[Participation, ParticipationCapacity]:
    participation, _ = Participation.objects.get_or_create(
        organization=edition.organization,
        edition=edition,
        account=account,
        defaults={
            "status": Participation.Status.ACTIVE,
            "edition_name_snapshot": edition.name,
            "series_name_snapshot": edition.series.name,
        },
    )
    capacity, _ = ParticipationCapacity.objects.get_or_create(
        participation=participation,
        code=code,
        defaults={
            "label_snapshot": label,
            "status": ParticipationCapacity.Status.ACTIVE,
            "started_at": timezone.now(),
        },
    )
    return participation, capacity


@transaction.atomic
def bootstrap_organization_workforce(
    *,
    organization: Organization,
    edition: EventEdition,
    controller: Account,
    chair: Account,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> dict[str, int]:
    """Establish the first two controllers and starter catalog exactly once."""

    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValidationError("A bootstrap reason is required.")
    if not controller.is_active or not controller.is_superuser:
        raise ValidationError("The bootstrap controller must be an active superuser.")
    if not chair.is_active or chair.id == controller.id:
        raise ValidationError("Choose a distinct active convention chair account.")
    if organization.lifecycle != Organization.Lifecycle.ACTIVE:
        raise ValidationError("The organization must be active.")
    if edition.organization_id != organization.id or edition.lifecycle in {
        EventEdition.Lifecycle.ARCHIVED,
        EventEdition.Lifecycle.CANCELLED,
    }:
        raise ValidationError("Choose a matching non-closed edition.")
    if (
        CapabilityGrant.objects.filter(organization=organization).exists()
        or RoleAssignment.objects.filter(organization=organization).exists()
        or RoleBundle.objects.filter(organization=organization).exists()
    ):
        raise ValidationError(
            "This organization already has authority records; use ordinary "
            "dual-control role management."
        )

    now = timezone.now()
    roles: dict[str, RoleBundle] = {}
    templates: dict[str, PositionTemplate] = {}
    authority_role = RoleBundle.objects.create(
        organization=organization,
        code="authority-controller",
        name="Authority Controller",
        version=1,
        capability_codes=list(INITIAL_AUTHORITY_CAPABILITIES),
        created_by=controller,
        approved_by=chair,
        reason=f"Initial authority bootstrap: {normalized_reason}"[:240],
    )
    for spec in STARTER_POSITIONS:
        role = RoleBundle.objects.create(
            organization=organization,
            code=spec.code,
            name=spec.name,
            version=1,
            capability_codes=list(dict.fromkeys(spec.capability_codes)),
            created_by=controller,
            approved_by=chair,
            reason=f"Initial authority bootstrap: {normalized_reason}"[:240],
        )
        roles[spec.code] = role
        templates[spec.code] = PositionTemplate.objects.create(
            organization=organization,
            code=spec.code,
            name=spec.name,
            version=1,
            description=spec.description,
            default_headcount=spec.headcount,
            default_capacity_codes=list(spec.capacity_codes),
            role_bundle=role,
            status=PositionTemplate.Status.PUBLISHED,
            created_by=controller,
        )

    controller_role = roles["convention-chair"]
    for recipient, approver in (
        (controller, chair),
        (chair, controller),
    ):
        RoleAssignment.objects.create(
            organization=organization,
            edition=None,
            principal=recipient,
            role_bundle=authority_role,
            effective_from=now,
            granted_by=controller,
            approved_by=approver,
            reason=f"Initial authority controller: {normalized_reason}"[:240],
        )
    for recipient, approver, assignment_reason in (
        (
            controller,
            chair,
            "Initial organization bootstrap controller",
        ),
        (
            chair,
            controller,
            "Initial convention chair",
        ),
    ):
        RoleAssignment.objects.create(
            organization=organization,
            edition=edition,
            principal=recipient,
            role_bundle=controller_role,
            effective_from=now,
            granted_by=controller,
            approved_by=approver,
            reason=f"{assignment_reason}: {normalized_reason}"[:240],
        )

    _membership(
        organization=organization,
        account=controller,
        label="Bootstrap controller",
    )
    _membership(
        organization=organization,
        account=chair,
        label="Convention Chair",
    )
    _participation(
        edition=edition,
        account=controller,
        label="Bootstrap Controller",
        code="bootstrap-controller",
    )
    _, chair_capacity = _participation(
        edition=edition,
        account=chair,
        label="Convention Chair",
        code="convention-chair",
    )
    leadership = Department.objects.create(
        organization=organization,
        edition=edition,
        code="convention-leadership",
        name="Convention Leadership",
        description="Edition leadership and accountable cross-department coordination.",
    )
    chair_position = Position.objects.create(
        organization=organization,
        edition=edition,
        template=templates["convention-chair"],
        department=leadership,
        role_bundle=roles["convention-chair"],
        code="convention-chair",
        title="Convention Chair",
        description=templates["convention-chair"].description,
        headcount=1,
        capacity_codes=["staff", "volunteer"],
        status=Position.Status.FILLED,
        created_by=controller,
    )
    chair_role_assignment = RoleAssignment.objects.get(
        organization=organization,
        edition=edition,
        principal=chair,
        role_bundle=controller_role,
    )
    PositionAssignment.objects.create(
        position=chair_position,
        organization=organization,
        edition=edition,
        account=chair,
        status=PositionAssignment.Status.ACTIVE,
        effective_from=now,
        proposed_by=controller,
        approved_by=chair,
        reason=f"Initial convention chair: {normalized_reason}"[:500],
        role_assignment=chair_role_assignment,
        participation_capacity=chair_capacity,
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=controller.id,
            principal_context_id=None,
            organization_id=organization.id,
            event_edition_id=edition.id,
            capability_code="authorization.manage_roles",
            operation="workforce.organization.bootstrap",
            target_type="organizations.organization",
            target_id=organization.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="initial_authority_bootstrap",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("reason", "audit", "approval"),
            changed_fields=(
                "initial_role_assignments",
                "position_templates",
                "workforce_structure",
            ),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-extended",
        )
    )
    return {
        "role_bundles": len(roles) + 1,
        "position_templates": len(templates),
        "departments": 1,
        "positions": 1,
        "role_assignments": 4,
        "position_assignments": 1,
    }
