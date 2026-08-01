"""Report organization representation migration blockers without changing data."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Count, Q

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.effects.models import DomainEvent
from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    EXECUTIVE_BOARD_CAPABILITIES,
    EXECUTIVE_BOARD_ROLE_CODE,
    MINIMUM_EXECUTIVE_BOARD_CONTROLLERS,
)

MAXIMUM_REPORTED_ORGANIZATIONS = 20

BLOCKER_KEYS = (
    "active_board_appointment_mismatch",
    "active_board_insufficient_controllers",
    "active_board_pending_appointments",
    "active_representation_organization_not_active",
    "emergency_board_evidence_mismatch",
    "governed_board_activation_evidence_mismatch",
    "governed_representation_activation_provenance_mismatch",
    "non_draft_without_active_representation",
    "platform_principal_capability_grants",
    "platform_principal_role_assignments",
    "provisioning_appointment_subject_ineligible",
    "reserved_executive_board_bundle_mismatch",
    "reserved_executive_board_cardinality",
    "stray_active_executive_board_membership",
    "suspended_representation_organization_not_suspended",
    "unlinked_live_executive_board_assignments",
)


def _organization_ids(values: Any) -> set[UUID]:
    return set(values)


def _event_payload(event: DomainEvent | None) -> dict[str, object]:
    if event is None or not isinstance(event.payload, dict):
        return {}
    return event.payload


def _current_representation_event(
    representation: OrganizationRepresentation,
) -> DomainEvent | None:
    """Return the exact current-version event only when an in-scope outbox exists."""

    return (
        DomainEvent.objects.filter(
            organization_id=representation.organization_id,
            event_name="organizations.representation.changed.v1",
            aggregate_type="organizations.organization_representation",
            aggregate_id=representation.id,
            aggregate_version=representation.aggregate_version,
            outbox_messages__organization_id=representation.organization_id,
        )
        .order_by("-occurred_at", "-id")
        .first()
    )


def _is_emergency_governed_state(
    representation: OrganizationRepresentation,
    current_event: DomainEvent | None,
) -> bool:
    if representation.state == OrganizationRepresentation.State.SUSPENDED:
        return True
    return _event_payload(current_event).get("action") == "controller_ended"


def _reserved_bundle(
    representation: OrganizationRepresentation,
) -> RoleBundle | None:
    bundles = list(
        RoleBundle.objects.filter(
            organization_id=representation.organization_id,
            code=EXECUTIVE_BOARD_ROLE_CODE,
        ).order_by("id")[:2]
    )
    return bundles[0] if len(bundles) == 1 else None


def _has_controller_approver(
    *,
    representation: OrganizationRepresentation,
    account_id: UUID | None,
    emergency_state: bool,
) -> bool:
    if account_id is None:
        return False
    appointments = RepresentationAppointment.objects.filter(
        representation=representation,
        account_id=account_id,
    )
    if not emergency_state:
        return appointments.filter(
            state=RepresentationAppointment.State.ACTIVE,
        ).exists()
    return appointments.filter(
        Q(state=RepresentationAppointment.State.ACTIVE)
        | Q(
            state=RepresentationAppointment.State.ENDED,
            ended_at__isnull=False,
        ),
        activated_at=representation.activated_at,
    ).exists()


def _reserved_bundle_mismatches() -> set[UUID]:
    mismatches: set[UUID] = set()
    expected_capabilities = sorted(EXECUTIVE_BOARD_CAPABILITIES)
    for representation in OrganizationRepresentation.objects.filter(
        state__in=(
            OrganizationRepresentation.State.ACTIVE,
            OrganizationRepresentation.State.SUSPENDED,
        )
    ).order_by("organization_id"):
        bundle = _reserved_bundle(representation)
        if bundle is None:
            continue
        current_event = _current_representation_event(representation)
        emergency_state = _is_emergency_governed_state(
            representation,
            current_event,
        )
        capabilities = list(bundle.capability_codes)
        if (
            bundle.version != 1
            or bundle.name != "Executive Board"
            or len(capabilities) != len(EXECUTIVE_BOARD_CAPABILITIES)
            or sorted(capabilities) != expected_capabilities
            or bundle.created_by_id != representation.activated_by_id
            or bundle.reason != representation.activation_reason
            or not _has_controller_approver(
                representation=representation,
                account_id=bundle.approved_by_id,
                emergency_state=emergency_state,
            )
        ):
            mismatches.add(representation.organization_id)
    return mismatches


def _appointment_has_exact_membership(
    appointment: RepresentationAppointment,
) -> bool:
    return OrganizationMembership.objects.filter(
        organization_id=appointment.representation.organization_id,
        account_id=appointment.account_id,
        state=OrganizationMembership.State.ACTIVE,
        relationship_label="Executive Board controller",
        started_at__isnull=False,
        ended_at__isnull=True,
    ).exists()


def _active_appointment_is_exact(
    *,
    appointment: RepresentationAppointment,
    representation: OrganizationRepresentation,
    bundle: RoleBundle,
    emergency_state: bool,
) -> bool:
    account = appointment.account
    if (
        appointment.activated_at != representation.activated_at
        or account.account_kind != Account.Kind.PERSON
        or not account.is_active
        or account.email_verified_at is None
        or not _appointment_has_exact_membership(appointment)
        or appointment.role_assignment_id is None
    ):
        return False
    assignment = RoleAssignment.objects.filter(
        id=appointment.role_assignment_id
    ).first()
    if assignment is None:
        return False
    return (
        assignment.organization_id == representation.organization_id
        and assignment.edition_id is None
        and assignment.principal_id == appointment.account_id
        and assignment.role_bundle_id == bundle.id
        and assignment.effective_from == representation.activated_at
        and assignment.expires_at is None
        and assignment.revoked_at is None
        and assignment.granted_by_id == representation.activated_by_id
        and assignment.approved_by_id is not None
        and assignment.approved_by_id != assignment.principal_id
        and assignment.reason == representation.activation_reason
        and _has_controller_approver(
            representation=representation,
            account_id=assignment.approved_by_id,
            emergency_state=emergency_state,
        )
    )


def _active_board_appointment_mismatches() -> set[UUID]:
    """Find active Board appointments missing their exact canonical evidence."""

    mismatches: set[UUID] = set()
    for representation in OrganizationRepresentation.objects.filter(
        state=OrganizationRepresentation.State.ACTIVE,
    ).order_by("organization_id"):
        bundle = _reserved_bundle(representation)
        if bundle is None:
            continue
        current_event = _current_representation_event(representation)
        emergency_state = _is_emergency_governed_state(
            representation,
            current_event,
        )
        appointments = RepresentationAppointment.objects.filter(
            representation=representation,
            state=RepresentationAppointment.State.ACTIVE,
        ).select_related("account", "representation")
        if any(
            not _active_appointment_is_exact(
                appointment=appointment,
                representation=representation,
                bundle=bundle,
                emergency_state=emergency_state,
            )
            for appointment in appointments
        ):
            mismatches.add(representation.organization_id)
    return mismatches


def _unlinked_live_assignment_mismatches() -> set[UUID]:
    mismatches: set[UUID] = set()
    for representation in OrganizationRepresentation.objects.filter(
        state__in=(
            OrganizationRepresentation.State.ACTIVE,
            OrganizationRepresentation.State.SUSPENDED,
        )
    ).order_by("organization_id"):
        bundle = _reserved_bundle(representation)
        if bundle is None:
            continue
        linked_assignment_ids: Any = ()
        if representation.state == OrganizationRepresentation.State.ACTIVE:
            linked_assignment_ids = RepresentationAppointment.objects.filter(
                representation=representation,
                state=RepresentationAppointment.State.ACTIVE,
                role_assignment_id__isnull=False,
            ).values_list("role_assignment_id", flat=True)
        if (
            RoleAssignment.objects.filter(
                role_bundle=bundle,
                revoked_at__isnull=True,
            )
            .exclude(id__in=linked_assignment_ids)
            .exists()
        ):
            mismatches.add(representation.organization_id)
    return mismatches


def _stray_board_memberships() -> set[UUID]:
    mismatches: set[UUID] = set()
    for representation in OrganizationRepresentation.objects.filter(
        state__in=(
            OrganizationRepresentation.State.ACTIVE,
            OrganizationRepresentation.State.SUSPENDED,
        )
    ).order_by("organization_id"):
        membership_states: tuple[str, ...] = (OrganizationMembership.State.ACTIVE,)
        if representation.state == OrganizationRepresentation.State.SUSPENDED:
            membership_states = (
                OrganizationMembership.State.INVITED,
                OrganizationMembership.State.ACTIVE,
            )
        memberships = OrganizationMembership.objects.filter(
            organization_id=representation.organization_id,
            relationship_label="Executive Board controller",
            state__in=membership_states,
        )
        active_controller_ids: Any = ()
        if representation.state == OrganizationRepresentation.State.ACTIVE:
            active_controller_ids = RepresentationAppointment.objects.filter(
                representation=representation,
                state=RepresentationAppointment.State.ACTIVE,
            ).values_list("account_id", flat=True)
        if memberships.exclude(account_id__in=active_controller_ids).exists():
            mismatches.add(representation.organization_id)
    return mismatches


def _latest_activation_audit(
    representation: OrganizationRepresentation,
) -> AuditEvent | None:
    return (
        AuditEvent.objects.filter(
            organization_id=representation.organization_id,
            operation="organizations.representation.activate",
            target_type="organizations.organization_representation",
            target_id=representation.id,
            principal_id=representation.activated_by_id,
            outcome=AuditEvent.Outcome.ALLOW,
        )
        .order_by("-occurred_at", "-id")
        .first()
    )


def _has_original_activation_event(
    *,
    representation: OrganizationRepresentation,
    activation_audit: AuditEvent,
    emergency_state: bool,
) -> bool:
    events = DomainEvent.objects.filter(
        organization_id=representation.organization_id,
        event_name="organizations.representation.changed.v1",
        aggregate_type="organizations.organization_representation",
        aggregate_id=representation.id,
        correlation_id=activation_audit.correlation_id,
        causation_id=activation_audit.id,
        actor_id=representation.activated_by_id,
        payload__action="activated",
        payload__representation_code="executive_board",
        payload__state="active",
        outbox_messages__organization_id=representation.organization_id,
    )
    if emergency_state:
        return events.filter(
            aggregate_version__lte=representation.aggregate_version,
        ).exists()
    return events.filter(
        aggregate_version=representation.aggregate_version,
    ).exists()


def _has_assignment_audits(
    *,
    representation: OrganizationRepresentation,
    activation_audit: AuditEvent,
) -> bool:
    for appointment in RepresentationAppointment.objects.filter(
        representation=representation,
        state=RepresentationAppointment.State.ACTIVE,
    ):
        if appointment.role_assignment_id is None:
            return False
        if not AuditEvent.objects.filter(
            organization_id=representation.organization_id,
            operation="organizations.representation.authority_assign",
            target_type="authorization.role_assignment",
            target_id=appointment.role_assignment_id,
            principal_id=representation.activated_by_id,
            outcome=AuditEvent.Outcome.ALLOW,
            correlation_id=activation_audit.correlation_id,
        ).exists():
            return False
    return True


def _activation_evidence_mismatches() -> set[UUID]:
    mismatches: set[UUID] = set()
    for representation in OrganizationRepresentation.objects.filter(
        state__in=(
            OrganizationRepresentation.State.ACTIVE,
            OrganizationRepresentation.State.SUSPENDED,
        )
    ).order_by("organization_id"):
        current_event = _current_representation_event(representation)
        emergency_state = _is_emergency_governed_state(
            representation,
            current_event,
        )
        activation_audit = _latest_activation_audit(representation)
        if (
            activation_audit is None
            or not _has_original_activation_event(
                representation=representation,
                activation_audit=activation_audit,
                emergency_state=emergency_state,
            )
            or not _has_assignment_audits(
                representation=representation,
                activation_audit=activation_audit,
            )
        ):
            mismatches.add(representation.organization_id)
    return mismatches


def _revoked_assignments_have_audits(
    *,
    representation: OrganizationRepresentation,
    bundle: RoleBundle,
) -> bool:
    for assignment_id in RoleAssignment.objects.filter(
        role_bundle=bundle,
        revoked_at__isnull=False,
    ).values_list("id", flat=True):
        if not AuditEvent.objects.filter(
            organization_id=representation.organization_id,
            operation="organizations.representation.authority_revoke",
            target_type="authorization.role_assignment",
            target_id=assignment_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="platform_emergency_removal",
        ).exists():
            return False
    return True


def _ended_appointments_have_memberships(
    representation: OrganizationRepresentation,
) -> bool:
    for appointment in RepresentationAppointment.objects.filter(
        representation=representation,
        state=RepresentationAppointment.State.ENDED,
        activated_at__isnull=False,
    ):
        if not OrganizationMembership.objects.filter(
            organization_id=representation.organization_id,
            account_id=appointment.account_id,
            state=OrganizationMembership.State.ENDED,
            relationship_label="Executive Board controller",
            started_at__isnull=False,
            ended_at__isnull=False,
        ).exists():
            return False
    return True


def _emergency_evidence_is_exact(  # noqa: PLR0911
    *,
    representation: OrganizationRepresentation,
    current_event: DomainEvent | None,
    bundle: RoleBundle | None,
) -> bool:
    if current_event is None or bundle is None:
        return False
    expected_action = (
        "representation_suspended"
        if representation.state == OrganizationRepresentation.State.SUSPENDED
        else "controller_ended"
    )
    payload = _event_payload(current_event)
    if (
        payload.get("action") != expected_action
        or payload.get("state") != representation.state
        or current_event.causation_id is None
        or current_event.actor_id is None
    ):
        return False
    current_audit = AuditEvent.objects.filter(
        id=current_event.causation_id,
        organization_id=representation.organization_id,
        operation="organizations.representation.emergency_controller_remove",
        target_type="organizations.organization_representation",
        target_id=representation.id,
        principal_id=current_event.actor_id,
        outcome=AuditEvent.Outcome.ALLOW,
        reason_code="platform_emergency_removal",
        correlation_id=current_event.correlation_id,
    ).first()
    if current_audit is None or "reason" not in current_audit.obligations:
        return False
    if not Account.objects.filter(
        id=current_event.actor_id,
        account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
    ).exists():
        return False
    identity_audit_targets = list(
        AuditEvent.objects.filter(
            organization_id__isnull=True,
            operation="identity.account.emergency_deactivate",
            target_type="identity.account",
            principal_id=current_event.actor_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="platform_emergency_removal",
            correlation_id=current_event.correlation_id,
        ).values_list("target_id", flat=True)
    )
    if len(identity_audit_targets) != 1 or identity_audit_targets[0] is None:
        return False
    removed_subject_id = identity_audit_targets[0]
    if not Account.objects.filter(
        id=removed_subject_id,
        account_kind=Account.Kind.PERSON,
        is_active=False,
    ).exists():
        return False
    if not RepresentationAppointment.objects.filter(
        representation=representation,
        account_id=removed_subject_id,
        state=RepresentationAppointment.State.ENDED,
        ended_at__isnull=False,
    ).exists():
        return False
    if not _revoked_assignments_have_audits(
        representation=representation,
        bundle=bundle,
    ) or not _ended_appointments_have_memberships(representation):
        return False
    if representation.state != OrganizationRepresentation.State.SUSPENDED:
        return True
    return not (
        RepresentationAppointment.objects.filter(
            representation=representation,
            state__in=(
                RepresentationAppointment.State.INVITED,
                RepresentationAppointment.State.ACCEPTED,
                RepresentationAppointment.State.ACTIVE,
            ),
        ).exists()
        or RoleAssignment.objects.filter(
            role_bundle=bundle,
            revoked_at__isnull=True,
        ).exists()
        or OrganizationMembership.objects.filter(
            organization_id=representation.organization_id,
            relationship_label="Executive Board controller",
            state__in=(
                OrganizationMembership.State.INVITED,
                OrganizationMembership.State.ACTIVE,
            ),
        ).exists()
    )


def _emergency_evidence_mismatches() -> set[UUID]:
    mismatches: set[UUID] = set()
    for representation in OrganizationRepresentation.objects.filter(
        state__in=(
            OrganizationRepresentation.State.ACTIVE,
            OrganizationRepresentation.State.SUSPENDED,
        )
    ).order_by("organization_id"):
        current_event = _current_representation_event(representation)
        if not _is_emergency_governed_state(representation, current_event):
            continue
        if not _emergency_evidence_is_exact(
            representation=representation,
            current_event=current_event,
            bundle=_reserved_bundle(representation),
        ):
            mismatches.add(representation.organization_id)
    return mismatches


def _activation_provenance_mismatches() -> set[UUID]:
    return _organization_ids(
        OrganizationRepresentation.objects.filter(
            state__in=(
                OrganizationRepresentation.State.ACTIVE,
                OrganizationRepresentation.State.SUSPENDED,
            )
        )
        .exclude(
            activated_by__account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
        )
        .values_list("organization_id", flat=True)
    )


def _collect_blockers() -> dict[str, set[UUID]]:
    governed_representation_organizations = OrganizationRepresentation.objects.filter(
        Q(
            state=OrganizationRepresentation.State.ACTIVE,
            organization__lifecycle=Organization.Lifecycle.ACTIVE,
        )
        | Q(
            state=OrganizationRepresentation.State.SUSPENDED,
            organization__lifecycle=Organization.Lifecycle.SUSPENDED,
        )
    ).values("organization_id")

    non_draft_without_active_representation = _organization_ids(
        Organization.objects.exclude(lifecycle=Organization.Lifecycle.DRAFT)
        .exclude(id__in=governed_representation_organizations)
        .values_list("id", flat=True)
    )
    active_representation_organization_not_active = _organization_ids(
        OrganizationRepresentation.objects.filter(
            state=OrganizationRepresentation.State.ACTIVE
        )
        .exclude(organization__lifecycle=Organization.Lifecycle.ACTIVE)
        .values_list("organization_id", flat=True)
    )
    suspended_representation_organization_not_suspended = _organization_ids(
        OrganizationRepresentation.objects.filter(
            state=OrganizationRepresentation.State.SUSPENDED
        )
        .exclude(organization__lifecycle=Organization.Lifecycle.SUSPENDED)
        .values_list("organization_id", flat=True)
    )

    active_representations_with_counts = OrganizationRepresentation.objects.filter(
        state=OrganizationRepresentation.State.ACTIVE
    ).annotate(
        active_controller_count=Count(
            "appointments",
            filter=Q(appointments__state=RepresentationAppointment.State.ACTIVE),
            distinct=True,
        )
    )
    active_board_insufficient_controllers = _organization_ids(
        active_representations_with_counts.filter(
            active_controller_count__lt=MINIMUM_EXECUTIVE_BOARD_CONTROLLERS
        ).values_list("organization_id", flat=True)
    )
    active_board_pending_appointments = _organization_ids(
        OrganizationRepresentation.objects.filter(
            state=OrganizationRepresentation.State.ACTIVE,
            appointments__state__in=(
                RepresentationAppointment.State.INVITED,
                RepresentationAppointment.State.ACCEPTED,
            ),
        ).values_list("organization_id", flat=True)
    )

    organizations_with_board_artifacts = Organization.objects.annotate(
        reserved_bundle_count=Count(
            "role_bundles",
            filter=Q(role_bundles__code=EXECUTIVE_BOARD_ROLE_CODE),
            distinct=True,
        ),
        governed_representation_count=Count(
            "representation",
            filter=Q(
                representation__state__in=(
                    OrganizationRepresentation.State.ACTIVE,
                    OrganizationRepresentation.State.SUSPENDED,
                )
            ),
            distinct=True,
        ),
    ).filter(Q(reserved_bundle_count__gt=0) | Q(governed_representation_count__gt=0))
    reserved_executive_board_cardinality = _organization_ids(
        organizations_with_board_artifacts.exclude(
            reserved_bundle_count=1,
            governed_representation_count=1,
        ).values_list("id", flat=True)
    )
    provisioning_appointment_subject_ineligible = _organization_ids(
        RepresentationAppointment.objects.filter(
            representation__state=OrganizationRepresentation.State.PROVISIONING,
            state__in=(
                RepresentationAppointment.State.INVITED,
                RepresentationAppointment.State.ACCEPTED,
            ),
        )
        .exclude(
            account__account_kind=Account.Kind.PERSON,
            account__is_active=True,
            account__email_verified_at__isnull=False,
        )
        .values_list("representation__organization_id", flat=True)
    )

    return {
        "active_board_appointment_mismatch": (_active_board_appointment_mismatches()),
        "active_board_insufficient_controllers": (
            active_board_insufficient_controllers
        ),
        "active_board_pending_appointments": active_board_pending_appointments,
        "active_representation_organization_not_active": (
            active_representation_organization_not_active
        ),
        "emergency_board_evidence_mismatch": (_emergency_evidence_mismatches()),
        "governed_board_activation_evidence_mismatch": (
            _activation_evidence_mismatches()
        ),
        "governed_representation_activation_provenance_mismatch": (
            _activation_provenance_mismatches()
        ),
        "non_draft_without_active_representation": (
            non_draft_without_active_representation
        ),
        "platform_principal_capability_grants": _organization_ids(
            CapabilityGrant.objects.filter(
                principal__account_kind=Account.Kind.PLATFORM_ADMINISTRATOR
            ).values_list("organization_id", flat=True)
        ),
        "platform_principal_role_assignments": _organization_ids(
            RoleAssignment.objects.filter(
                principal__account_kind=Account.Kind.PLATFORM_ADMINISTRATOR
            ).values_list("organization_id", flat=True)
        ),
        "provisioning_appointment_subject_ineligible": (
            provisioning_appointment_subject_ineligible
        ),
        "reserved_executive_board_bundle_mismatch": (_reserved_bundle_mismatches()),
        "reserved_executive_board_cardinality": (reserved_executive_board_cardinality),
        "stray_active_executive_board_membership": (_stray_board_memberships()),
        "suspended_representation_organization_not_suspended": (
            suspended_representation_organization_not_suspended
        ),
        "unlinked_live_executive_board_assignments": (
            _unlinked_live_assignment_mismatches()
        ),
    }


def _build_report() -> dict[str, Any]:
    blockers = _collect_blockers()
    blocked_organization_ids = set().union(*blockers.values())
    organization_slugs = sorted(
        Organization.objects.filter(id__in=blocked_organization_ids).values_list(
            "slug",
            flat=True,
        )
    )
    return {
        "status": "blocked" if blocked_organization_ids else "ready",
        "blocker_counts": {key: len(blockers[key]) for key in BLOCKER_KEYS},
        "blocked_organization_count": len(blocked_organization_ids),
        "organization_slugs": organization_slugs[:MAXIMUM_REPORTED_ORGANIZATIONS],
        "organization_slugs_truncated": (
            len(organization_slugs) > MAXIMUM_REPORTED_ORGANIZATIONS
        ),
    }


class Command(BaseCommand):
    help = (
        "Inspect organization representation data for migration blockers and emit "
        "a privacy-minimized JSON report."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help=(
                "Return a successful process status even when blockers exist; the "
                "JSON status and counts are unchanged."
            ),
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        report = _build_report()
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] == "blocked" and not options["no_fail"]:
            raise CommandError(
                "Representation readiness blockers detected; inspect the JSON report."
            )
