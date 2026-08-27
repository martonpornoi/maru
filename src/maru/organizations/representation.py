"""Audited organization representation and activation commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.issuance import (
    create_executive_board_issuance,
    create_representation_issuance,
)
from maru.authorization.models import RoleAssignment, RoleBundle
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_organization_target,
)
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.models import Account
from maru.identity.policies import validate_convention_subject
from maru.identity.services import deactivate_person_account_for_platform_emergency
from maru.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation_catalog import (
    EXECUTIVE_BOARD,
    MARU_OPERATORS,
    RepresentationDefinition,
    representation_definition,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

MANAGE_REPRESENTATION = "organizations.manage_representation"
MINIMUM_REPRESENTATION_CONTROLLERS = 2
MINIMUM_EXECUTIVE_BOARD_CONTROLLERS = MINIMUM_REPRESENTATION_CONTROLLERS
MAX_REPRESENTATION_REASON_LENGTH = 240
EXECUTIVE_BOARD_ROLE_CODE = EXECUTIVE_BOARD.role_code
EXECUTIVE_BOARD_ROLE_NAME = EXECUTIVE_BOARD.role_name
EXECUTIVE_BOARD_ROLE_VERSION = EXECUTIVE_BOARD.role_version
EXECUTIVE_BOARD_MEMBERSHIP_LABEL = EXECUTIVE_BOARD.membership_label
MARU_OPERATOR_ROLE_CODE = MARU_OPERATORS.role_code
MARU_OPERATOR_ROLE_NAME = MARU_OPERATORS.role_name
MARU_OPERATOR_ROLE_VERSION = MARU_OPERATORS.role_version
MARU_OPERATOR_MEMBERSHIP_LABEL = MARU_OPERATORS.membership_label
REPRESENTATION_SUBJECT_LOCK_NAMESPACE = 0x13A2_91D7_0000_0000
OPEN_REPRESENTATION_APPOINTMENT_STATES = (
    RepresentationAppointment.State.INVITED,
    RepresentationAppointment.State.ACCEPTED,
    RepresentationAppointment.State.ACTIVE,
)
EXECUTIVE_BOARD_CAPABILITIES = EXECUTIVE_BOARD.capability_codes
MARU_OPERATOR_CAPABILITIES = MARU_OPERATORS.capability_codes


@dataclass(frozen=True, slots=True)
class RepresentationActivationResult:
    """Describe representation activation result.

    Attributes
    ----------
    representation
        The governed organization representation being evaluated.
    organization
        The organization that owns the requested resource.
    appointments
        The appointments retained in this immutable projection.
    """

    representation: OrganizationRepresentation
    organization: Organization
    appointments: tuple[RepresentationAppointment, ...]


@dataclass(frozen=True, slots=True)
class EmergencyControllerRemovalResult:
    """Describe emergency controller removal result.

    Attributes
    ----------
    representation
        The governed organization representation being evaluated.
    organization
        The organization that owns the requested resource.
    removed_appointment
        The removed appointment retained in this immutable projection.
    ended_appointments
        The ended appointments retained in this immutable projection.
    affected_representations
        The affected representations retained in this immutable projection.
    quorum_preserved
        The quorum preserved retained in this immutable projection.
    """

    representation: OrganizationRepresentation
    organization: Organization
    removed_appointment: RepresentationAppointment
    ended_appointments: tuple[RepresentationAppointment, ...]
    affected_representations: tuple[OrganizationRepresentation, ...]
    quorum_preserved: bool | None


@dataclass(frozen=True, slots=True)
class _EmergencyRepresentationPlan:
    representation: OrganizationRepresentation
    organization: Organization
    subject_appointment: RepresentationAppointment
    ended_appointments: tuple[RepresentationAppointment, ...]
    quorum_preserved: bool | None


@dataclass(frozen=True, slots=True)
class _EmergencyInventory:
    subject_id: UUID
    representations: tuple[OrganizationRepresentation, ...]
    organizations: dict[UUID, Organization]
    appointments: tuple[RepresentationAppointment, ...]


@dataclass(frozen=True, slots=True)
class _EmergencyEvidence:
    memberships: dict[tuple[UUID, UUID], OrganizationMembership]
    assignments: dict[UUID, RoleAssignment]


def _normalized_reason(reason: str) -> str:
    normalized = " ".join(reason.split())
    if not normalized:
        raise ValidationError(
            {
                "reason": ValidationError(
                    "Explain why this governance change is required.",
                    code="reason_required",
                )
            },
        )
    if len(normalized) > MAX_REPRESENTATION_REASON_LENGTH:
        raise ValidationError(
            {
                "reason": ValidationError(
                    "Ensure the reason has at most 240 characters.",
                    code="reason_too_long",
                )
            },
        )
    return normalized


def _representation_definition(
    representation: OrganizationRepresentation,
) -> RepresentationDefinition:
    definition = representation_definition(representation.code)
    if definition is None or representation.name != definition.name:
        raise ValidationError(
            "The accountable representation type is unsupported.",
            code="organization_representation_type_unsupported",
        )
    return definition


def _require_platform_administrator(actor: Account) -> None:
    if not actor.is_active or not actor.is_platform_administrator:
        raise PermissionDenied("Platform administration is required.")


def _lock_representation_subject(account_id: UUID) -> None:
    """Serialize lifecycle commands for one representation subject.

    The advisory lock is acquired before representation rows.  Row-level
    account locks remain the source-of-truth guard; this lock prevents a new
    invitation from appearing while an emergency command inventories every
    open relationship for the globally deactivated account.

    Parameters
    ----------
    account_id : UUID
        The platform account identifier within the requested scope.
    """
    subject_key = (
        account_id.int ^ REPRESENTATION_SUBJECT_LOCK_NAMESPACE
    ) & 0x7FFFFFFFFFFFFFFF
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [subject_key])


def _require_representation_manager(
    *, actor: Account, organization_id: UUID
) -> PolicyDecision:
    decision = decide(
        principal=actor,
        capability_code=MANAGE_REPRESENTATION,
        resource=resolve_organization_target(organization_id=organization_id),
    )
    if not decision.allowed:
        raise PermissionDenied("Organization representation authority is required.")
    return decision


def _audit(
    *,
    actor: Account,
    organization_id: UUID,
    operation: str,
    target_type: str,
    target_id: UUID,
    correlation_id: UUID,
    reason_code: str,
    obligations: tuple[str, ...],
    changed_fields: tuple[str, ...],
    source_channel: str,
) -> AuditEvent:
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=None,
            capability_code=MANAGE_REPRESENTATION,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=obligations,
            changed_fields=changed_fields,
            retention_class="security-extended",
        )
    )


def _publish_representation_change(
    *,
    representation: OrganizationRepresentation,
    action: str,
    state: str,
    actor: Account,
    correlation_id: UUID,
    causation_id: UUID,
) -> None:
    publish_domain_event(
        DomainEventRecord(
            event_name="organizations.representation.changed.v1",
            schema_version=1,
            organization_id=representation.organization_id,
            event_edition_id=None,
            aggregate_type="organizations.organization_representation",
            aggregate_id=representation.id,
            aggregate_version=representation.aggregate_version,
            payload={
                "action": action,
                "representation_code": representation.code,
                "state": state,
            },
            correlation_id=correlation_id,
            causation_id=causation_id,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="security-extended",
        ),
        workload_pool="core",
    )


@transaction.atomic
def provision_representation(
    *,
    actor: Account,
    organization_id: UUID,
    representation_code: str,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> OrganizationRepresentation:
    """Provision one code-owned representation root without enrolling the actor.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    representation_code : str
        The code-owned accountable representation type to establish.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    OrganizationRepresentation
        The resolved OrganizationRepresentation for provision executive board.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    _require_platform_administrator(actor)
    normalized_reason = _normalized_reason(reason)
    definition = representation_definition(representation_code)
    if definition is None:
        raise ValidationError(
            {"representation_code": "Choose a supported representation type."},
            code="organization_representation_type_unsupported",
        )
    organization = Organization.objects.select_for_update().get(id=organization_id)
    if organization.lifecycle != Organization.Lifecycle.DRAFT:
        raise ValidationError(
            "Only a Draft organization can provision its initial representation.",
            code="representation_parent_not_draft",
        )
    existing = OrganizationRepresentation.objects.filter(
        organization=organization
    ).first()
    if existing is not None:
        raise ValidationError(
            "This organization already has its accountable representation.",
            code="representation_exists",
        )

    representation = OrganizationRepresentation.objects.create(
        organization=organization,
        code=definition.code,
        name=definition.name,
        provisioned_by=actor,
        provisioning_reason=normalized_reason,
    )
    audit = _audit(
        actor=actor,
        organization_id=organization.id,
        operation="organizations.representation.provision",
        target_type="organizations.organization_representation",
        target_id=representation.id,
        correlation_id=correlation_id,
        reason_code="platform_administration",
        obligations=("reason", "audit"),
        changed_fields=("representation",),
        source_channel=source_channel,
    )
    _publish_representation_change(
        representation=representation,
        action="provisioned",
        state=representation.state,
        actor=actor,
        correlation_id=correlation_id,
        causation_id=audit.id,
    )
    return representation


def provision_executive_board(
    *,
    actor: Account,
    organization_id: UUID,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> OrganizationRepresentation:
    """Provision the real Executive Board representation compatibility path.

    Parameters
    ----------
    actor : Account
        The authenticated platform administrator.
    organization_id : UUID
        The organization identifier that owns the representation.
    reason : str
        The retained operator rationale.
    correlation_id : UUID
        The audit correlation identifier.
    source_channel : str, default='service'
        The closed channel code identifying the caller.

    Returns
    -------
    OrganizationRepresentation
        The newly provisioned Executive Board representation.
    """
    return provision_representation(
        actor=actor,
        organization_id=organization_id,
        representation_code=EXECUTIVE_BOARD.code,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def provision_maru_operators(
    *,
    actor: Account,
    organization_id: UUID,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> OrganizationRepresentation:
    """Provision accountable Maru operators without claiming legal office.

    Parameters
    ----------
    actor : Account
        The authenticated platform administrator.
    organization_id : UUID
        The organization identifier that owns the representation.
    reason : str
        The retained operator rationale.
    correlation_id : UUID
        The audit correlation identifier.
    source_channel : str, default='service'
        The closed channel code identifying the caller.

    Returns
    -------
    OrganizationRepresentation
        The newly provisioned Maru-operator representation.
    """
    return provision_representation(
        actor=actor,
        organization_id=organization_id,
        representation_code=MARU_OPERATORS.code,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


@transaction.atomic
def invite_representation_controller(
    *,
    actor: Account,
    representation_id: UUID,
    account_id: UUID,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> RepresentationAppointment:
    """Invite an exact active person account to a representation.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    representation_id : UUID
        The representation identifier within the requested scope.
    account_id : UUID
        The platform account identifier within the requested scope.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RepresentationAppointment
        The RepresentationAppointment produced by invite representation
        controller.

    Raises
    ------
    IntegrityError
        If a concurrent write violates a durable database invariant.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    normalized_reason = _normalized_reason(reason)
    _lock_representation_subject(account_id)
    representation = (
        OrganizationRepresentation.objects.select_for_update(of=("self",))
        .select_related("organization")
        .get(id=representation_id)
    )
    definition = _representation_definition(representation)
    organization = Organization.objects.select_for_update().get(
        id=representation.organization_id
    )
    decision = _require_representation_manager(
        actor=actor,
        organization_id=representation.organization_id,
    )
    if (
        representation.state != OrganizationRepresentation.State.PROVISIONING
        or organization.lifecycle != Organization.Lifecycle.DRAFT
    ):
        raise ValidationError(
            "Initial controller invitations require a Provisioning representation.",
            code="representation_not_provisioning",
        )
    membership = (
        OrganizationMembership.objects.select_for_update()
        .filter(organization=organization, account_id=account_id)
        .first()
    )
    account = Account.objects.select_for_update().get(id=account_id)
    if (
        not account.is_active
        or not account.has_verified_email
        or account.is_platform_administrator
    ):
        raise ValidationError(
            {
                "account": ValidationError(
                    "Choose an active account with a verified email address.",
                    code="representation_account_ineligible",
                )
            },
        )
    validate_convention_subject(account)
    if RepresentationAppointment.objects.filter(
        representation=representation,
        account=account,
        state__in=(
            RepresentationAppointment.State.INVITED,
            RepresentationAppointment.State.ACCEPTED,
            RepresentationAppointment.State.ACTIVE,
        ),
    ).exists():
        raise ValidationError(
            {
                "account": ValidationError(
                    f"This person already has an open {definition.name} term.",
                    code="representation_appointment_exists",
                )
            },
        )

    invited_at = timezone.now()
    try:
        with transaction.atomic():
            appointment = RepresentationAppointment.objects.create(
                representation=representation,
                account=account,
                invited_by=actor,
                invited_at=invited_at,
                reason=normalized_reason,
            )
    except IntegrityError as error:
        duplicate_exists = RepresentationAppointment.objects.filter(
            representation=representation,
            account=account,
            state__in=(
                RepresentationAppointment.State.INVITED,
                RepresentationAppointment.State.ACCEPTED,
                RepresentationAppointment.State.ACTIVE,
            ),
        ).exists()
        if duplicate_exists:
            raise ValidationError(
                {
                    "account": ValidationError(
                        f"This person already has an open {definition.name} term.",
                        code="representation_appointment_exists",
                    )
                },
            ) from error
        raise

    membership_created = False
    if membership is None:
        membership, membership_created = OrganizationMembership.objects.get_or_create(
            organization=organization,
            account=account,
            defaults={
                "state": OrganizationMembership.State.INVITED,
                "relationship_label": definition.membership_label,
            },
        )
    if membership.state == OrganizationMembership.State.SUSPENDED:
        raise ValidationError(
            {
                "account": ValidationError(
                    "A suspended organization membership must be resolved before "
                    "this person can be invited.",
                    code="representation_membership_suspended",
                )
            },
        )
    if (
        not membership_created
        and membership.state == OrganizationMembership.State.INVITED
        and membership.relationship_label != definition.membership_label
    ):
        raise ValidationError(
            {
                "account": ValidationError(
                    "An existing invited relationship must be reviewed before "
                    "this person can be invited.",
                    code="representation_membership_incompatible",
                )
            },
        )
    if (
        membership.state == OrganizationMembership.State.ENDED
        and membership.relationship_label == definition.membership_label
    ):
        membership.state = OrganizationMembership.State.INVITED
        membership.relationship_label = definition.membership_label
        membership.started_at = None
        membership.ended_at = None
        membership.save(
            update_fields=(
                "state",
                "relationship_label",
                "started_at",
                "ended_at",
                "updated_at",
            )
        )
    elif membership.state == OrganizationMembership.State.ENDED:
        raise ValidationError(
            {
                "account": ValidationError(
                    "An ended organization relationship must be reviewed before "
                    "this person can be invited.",
                    code="representation_membership_ended",
                )
            },
        )

    representation.aggregate_version += 1
    representation.save(update_fields=("aggregate_version", "updated_at"))
    audit = _audit(
        actor=actor,
        organization_id=representation.organization_id,
        operation="organizations.representation.invite",
        target_type="organizations.representation_appointment",
        target_id=appointment.id,
        correlation_id=correlation_id,
        reason_code=decision.reason_code,
        obligations=tuple(sorted(decision.obligations)),
        changed_fields=(
            ("appointment", "membership_invitation")
            if membership_created
            else ("appointment",)
        ),
        source_channel=source_channel,
    )
    _publish_representation_change(
        representation=representation,
        action="controller_invited",
        state=appointment.state,
        actor=actor,
        correlation_id=correlation_id,
        causation_id=audit.id,
    )
    return appointment


@transaction.atomic
def respond_to_representation_invitation(
    *,
    actor: Account,
    appointment_id: UUID,
    expected_version: int,
    accept: bool,
    correlation_id: UUID,
    source_channel: str = "service",
) -> RepresentationAppointment:
    """Accept or decline one invitation as its exact authenticated subject.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    appointment_id : UUID
        The appointment identifier within the requested scope.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    accept : bool
        The accept evaluated while respond to representation invitation.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RepresentationAppointment
        The RepresentationAppointment produced by respond to representation
        invitation.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    RepresentationAppointment.DoesNotExist
        If the operation encounters a does not exist condition.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    _lock_representation_subject(actor.id)
    representation_id = (
        RepresentationAppointment.objects.filter(id=appointment_id, account=actor)
        .values_list("representation_id", flat=True)
        .first()
    )
    if representation_id is None:
        raise RepresentationAppointment.DoesNotExist
    representation = (
        OrganizationRepresentation.objects.select_for_update(of=("self",))
        .select_related("organization")
        .get(id=representation_id)
    )
    definition = _representation_definition(representation)
    organization = Organization.objects.select_for_update().get(
        id=representation.organization_id
    )
    appointment = (
        RepresentationAppointment.objects.select_for_update(of=("self",))
        .select_related("account")
        .get(id=appointment_id, account=actor, representation=representation)
    )
    invited_membership = (
        OrganizationMembership.objects.select_for_update()
        .filter(
            organization_id=organization.id,
            account_id=actor.id,
            state=OrganizationMembership.State.INVITED,
            relationship_label=definition.membership_label,
        )
        .first()
    )
    locked_actor = Account.objects.select_for_update().get(id=actor.id)
    if (
        not locked_actor.is_active
        or not locked_actor.has_verified_email
        or locked_actor.is_platform_administrator
    ):
        raise PermissionDenied("This invitation response is unavailable.")
    if appointment.invitation_version != expected_version:
        raise ValidationError(
            "This invitation changed after the page was loaded. Reload and try again.",
            code="stale_representation_invitation",
        )
    if appointment.state != RepresentationAppointment.State.INVITED:
        raise ValidationError(
            "This invitation has already been answered.",
            code="representation_invitation_answered",
        )
    if (
        representation.state != OrganizationRepresentation.State.PROVISIONING
        or organization.lifecycle != Organization.Lifecycle.DRAFT
    ):
        raise ValidationError(
            "This representation no longer accepts invitation responses.",
            code="representation_not_provisioning",
        )

    responded_at = timezone.now()
    if accept:
        appointment.state = RepresentationAppointment.State.ACCEPTED
        action = "controller_accepted"
    else:
        appointment.state = RepresentationAppointment.State.DECLINED
        appointment.ended_at = responded_at
        action = "controller_declined"
        if invited_membership is not None:
            invited_membership.state = OrganizationMembership.State.ENDED
            invited_membership.ended_at = responded_at
            invited_membership.save(update_fields=("state", "ended_at", "updated_at"))
    appointment.responded_at = responded_at
    appointment.invitation_version += 1
    appointment.save(
        update_fields=(
            "state",
            "responded_at",
            "ended_at",
            "invitation_version",
            "updated_at",
        )
    )
    representation.aggregate_version += 1
    representation.save(update_fields=("aggregate_version", "updated_at"))
    audit = _audit(
        actor=actor,
        organization_id=representation.organization_id,
        operation=f"organizations.representation.{action}",
        target_type="organizations.representation_appointment",
        target_id=appointment.id,
        correlation_id=correlation_id,
        reason_code="self_relationship",
        obligations=("audit",),
        changed_fields=("appointment_state",),
        source_channel=source_channel,
    )
    _publish_representation_change(
        representation=representation,
        action=action,
        state=appointment.state,
        actor=actor,
        correlation_id=correlation_id,
        causation_id=audit.id,
    )
    return appointment


def _representation_bundle(
    *,
    representation: OrganizationRepresentation,
    actor: Account,
    controllers: Sequence[RepresentationAppointment],
    reason: str,
) -> RoleBundle:
    definition = _representation_definition(representation)
    if RoleBundle.objects.filter(
        organization_id=representation.organization_id,
        code=definition.role_code,
    ).exists():
        raise ValidationError(
            f"The reserved {definition.name} authority bundle already exists.",
            code=(
                "executive_board_role_conflict"
                if definition.code == EXECUTIVE_BOARD.code
                else "maru_operator_role_conflict"
            ),
        )
    return RoleBundle.objects.create(
        organization_id=representation.organization_id,
        code=definition.role_code,
        name=definition.role_name,
        version=definition.role_version,
        capability_codes=list(definition.capability_codes),
        created_by=actor,
        approved_by=controllers[0].account,
        reason=reason,
    )


def _lock_activation_memberships(
    *,
    organization: Organization,
    controllers: Sequence[RepresentationAppointment],
    definition: RepresentationDefinition,
) -> dict[UUID, OrganizationMembership]:
    controller_account_ids = [appointment.account_id for appointment in controllers]
    memberships = {
        membership.account_id: membership
        for membership in OrganizationMembership.objects.select_for_update()
        .filter(
            organization=organization,
            account_id__in=controller_account_ids,
        )
        .order_by("account_id")
    }
    if any(
        membership.state == OrganizationMembership.State.SUSPENDED
        for membership in memberships.values()
    ):
        raise ValidationError(
            "A suspended controller membership must be resolved before activation.",
            code="representation_membership_suspended",
        )
    if len(memberships) != len(controller_account_ids) or any(
        membership.state
        not in (
            OrganizationMembership.State.INVITED,
            OrganizationMembership.State.ACTIVE,
        )
        or (
            membership.state == OrganizationMembership.State.INVITED
            and membership.relationship_label != definition.membership_label
        )
        for membership in memberships.values()
    ):
        raise ValidationError(
            (
                "Every accepted controller must retain a compatible organization "
                "membership before activation."
            ),
            code="representation_membership_incompatible",
        )
    return memberships


def _record_initial_activation(
    *,
    representation: OrganizationRepresentation,
    organization: Organization,
    actor: Account,
    activated_at: datetime,
    reason: str,
) -> None:
    """Persist the code-owned activation facts before provenance controls.

    Parameters
    ----------
    representation : OrganizationRepresentation
        The governed organization representation being evaluated.
    organization : Organization
        The organization that owns the requested resource.
    actor : Account
        The authenticated account authorizing the operation.
    activated_at : datetime
        The timezone-aware timestamp for activated.
    reason : str
        The operator-supplied rationale recorded with the change.
    """
    representation.state = OrganizationRepresentation.State.ACTIVE
    representation.activated_by = actor
    representation.activated_at = activated_at
    representation.activation_reason = reason
    representation.aggregate_version += 1
    representation.save(
        update_fields=(
            "state",
            "activated_by",
            "activated_at",
            "activation_reason",
            "aggregate_version",
            "updated_at",
        )
    )
    organization.lifecycle = Organization.Lifecycle.ACTIVE
    organization.save(update_fields=("lifecycle", "updated_at"))


@transaction.atomic
def activate_representation(
    *,
    actor: Account,
    representation_id: UUID,
    expected_version: int,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> RepresentationActivationResult:
    """Activate two-person representation and canonical authority atomically.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    representation_id : UUID
        The representation identifier within the requested scope.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RepresentationActivationResult
        The resolved RepresentationActivationResult for activate executive board.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    _require_platform_administrator(actor)
    normalized_reason = _normalized_reason(reason)
    # Representation activation writes organization-scoped RoleAssignments.
    # Join the same global order as ordinary authority and structure writers
    # before taking subject, representation, or organization locks.
    lock_retired_department_authority_boundaries()
    activation_subject_ids = list(
        RepresentationAppointment.objects.filter(
            representation_id=representation_id,
            state=RepresentationAppointment.State.ACCEPTED,
        ).values_list("account_id", flat=True)
    )
    for account_id in sorted(set(activation_subject_ids), key=str):
        _lock_representation_subject(account_id)
    representation = (
        OrganizationRepresentation.objects.select_for_update(of=("self",))
        .select_related("organization")
        .get(id=representation_id)
    )
    definition = _representation_definition(representation)
    organization = Organization.objects.select_for_update().get(
        id=representation.organization_id
    )
    if representation.aggregate_version != expected_version:
        raise ValidationError(
            f"This {definition.name} changed after the page was loaded.",
            code="stale_representation",
        )
    if representation.state != OrganizationRepresentation.State.PROVISIONING:
        raise ValidationError(
            f"Only a Provisioning {definition.name} can be activated.",
            code="representation_not_provisioning",
        )
    if organization.lifecycle != Organization.Lifecycle.DRAFT:
        raise ValidationError(
            f"Initial {definition.name} activation requires a Draft organization.",
            code="representation_parent_not_draft",
        )
    controllers = list(
        RepresentationAppointment.objects.select_for_update(of=("self",))
        .select_related("account")
        .filter(
            representation=representation,
            role=RepresentationAppointment.Role.CONTROLLER,
            state=RepresentationAppointment.State.ACCEPTED,
        )
        .order_by("responded_at", "id")
    )
    if len(controllers) < MINIMUM_REPRESENTATION_CONTROLLERS:
        raise ValidationError(
            (
                "At least two distinct invited controllers must accept before "
                f"the {definition.name} can be activated."
            ),
            code="representation_controllers_incomplete",
        )
    if RepresentationAppointment.objects.filter(
        representation=representation,
        state=RepresentationAppointment.State.INVITED,
    ).exists():
        raise ValidationError(
            "Every open controller invitation must be answered before activation.",
            code="representation_invitations_pending",
        )
    memberships = _lock_activation_memberships(
        organization=organization,
        controllers=controllers,
        definition=definition,
    )
    controller_account_ids = [appointment.account_id for appointment in controllers]
    locked_accounts = {
        account.id: account
        for account in Account.objects.select_for_update()
        .filter(id__in=controller_account_ids)
        .order_by("id")
    }
    if len(locked_accounts) != len(controller_account_ids) or any(
        not account.is_active
        or not account.has_verified_email
        or account.is_platform_administrator
        for account in locked_accounts.values()
    ):
        raise ValidationError(
            "Every accepted controller must remain an eligible active account.",
            code="representation_controller_ineligible",
        )
    activated_at = timezone.now()
    role_bundle = _representation_bundle(
        representation=representation,
        actor=actor,
        controllers=controllers,
        reason=normalized_reason,
    )
    assignment_controls: list[tuple[RoleAssignment, RepresentationAppointment]] = []
    for index, appointment in enumerate(controllers):
        approver_appointment = controllers[(index + 1) % len(controllers)]
        approver = approver_appointment.account
        assignment = RoleAssignment.objects.create(
            organization=organization,
            edition=None,
            principal=appointment.account,
            role_bundle=role_bundle,
            effective_from=activated_at,
            expires_at=None,
            granted_by=actor,
            approved_by=approver,
            reason=normalized_reason,
        )
        membership = memberships[appointment.account_id]
        membership.state = OrganizationMembership.State.ACTIVE
        membership.relationship_label = definition.membership_label
        membership.started_at = membership.started_at or activated_at
        membership.ended_at = None
        membership.save(
            update_fields=(
                "state",
                "relationship_label",
                "started_at",
                "ended_at",
                "updated_at",
            )
        )
        appointment.state = RepresentationAppointment.State.ACTIVE
        appointment.activated_at = activated_at
        appointment.role_assignment = assignment
        appointment.invitation_version += 1
        appointment.save(
            update_fields=(
                "state",
                "activated_at",
                "role_assignment",
                "invitation_version",
                "updated_at",
            )
        )
        _audit(
            actor=actor,
            organization_id=organization.id,
            operation="organizations.representation.authority_assign",
            target_type="authorization.role_assignment",
            target_id=assignment.id,
            correlation_id=correlation_id,
            reason_code="initial_representation_bootstrap",
            obligations=("reason", "audit", "approval"),
            changed_fields=("role_assignment",),
            source_channel=source_channel,
        )
        assignment_controls.append((assignment, approver_appointment))

    _record_initial_activation(
        representation=representation,
        organization=organization,
        actor=actor,
        activated_at=activated_at,
        reason=normalized_reason,
    )
    issuance_writer = (
        create_executive_board_issuance
        if representation.code == EXECUTIVE_BOARD.code
        else create_representation_issuance
    )
    issuance_writer(
        target=role_bundle,
        representation=representation,
        actor=actor,
        approver_appointment=controllers[0],
        evaluated_at=activated_at,
    )
    for assignment, approver_appointment in assignment_controls:
        issuance_writer(
            target=assignment,
            representation=representation,
            actor=actor,
            approver_appointment=approver_appointment,
            evaluated_at=activated_at,
        )

    audit = _audit(
        actor=actor,
        organization_id=organization.id,
        operation="organizations.representation.activate",
        target_type="organizations.organization_representation",
        target_id=representation.id,
        correlation_id=correlation_id,
        reason_code="independent_controller_acceptance",
        obligations=("reason", "audit", "approval"),
        changed_fields=(
            "representation_state",
            "organization_lifecycle",
            "memberships",
            "role_assignments",
        ),
        source_channel=source_channel,
    )
    _publish_representation_change(
        representation=representation,
        action="activated",
        state=representation.state,
        actor=actor,
        correlation_id=correlation_id,
        causation_id=audit.id,
    )
    return RepresentationActivationResult(
        representation=representation,
        organization=organization,
        appointments=tuple(controllers),
    )


def activate_executive_board(
    *,
    actor: Account,
    representation_id: UUID,
    expected_version: int,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> RepresentationActivationResult:
    """Activate the compatibility Executive Board command path.

    Parameters
    ----------
    actor : Account
        The authenticated platform administrator.
    representation_id : UUID
        The exact representation identifier.
    expected_version : int
        The optimistic aggregate version.
    reason : str
        The retained activation rationale.
    correlation_id : UUID
        The audit correlation identifier.
    source_channel : str, default='service'
        The closed channel code identifying the caller.

    Returns
    -------
    RepresentationActivationResult
        The atomically activated representation and appointments.
    """
    return activate_representation(
        actor=actor,
        representation_id=representation_id,
        expected_version=expected_version,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def _resolve_emergency_subject(
    *, representation_id: UUID, appointment_id: UUID
) -> UUID:
    subject_id = (
        RepresentationAppointment.objects.filter(
            id=appointment_id,
            representation_id=representation_id,
            state__in=OPEN_REPRESENTATION_APPOINTMENT_STATES,
        )
        .values_list("account_id", flat=True)
        .first()
    )
    if subject_id is None:
        raise ValidationError(
            "The open controller relationship is unavailable.",
            code="representation_controller_not_open",
        )
    _lock_representation_subject(subject_id)
    return subject_id


def _lock_emergency_inventory(*, subject_id: UUID) -> _EmergencyInventory:
    representation_ids = list(
        RepresentationAppointment.objects.filter(
            account_id=subject_id,
            state__in=OPEN_REPRESENTATION_APPOINTMENT_STATES,
        )
        .order_by("representation_id")
        .values_list("representation_id", flat=True)
        .distinct()
    )
    representations = tuple(
        OrganizationRepresentation.objects.select_for_update(of=("self",))
        .filter(id__in=representation_ids)
        .order_by("id")
    )
    if {item.id for item in representations} != set(representation_ids):
        raise ValidationError(
            "The controller inventory changed; retry from a fresh page.",
            code="representation_inventory_changed",
        )
    organizations = {
        organization.id: organization
        for organization in Organization.objects.select_for_update()
        .filter(id__in=[item.organization_id for item in representations])
        .order_by("id")
    }
    appointments = tuple(
        RepresentationAppointment.objects.select_for_update(of=("self",))
        .filter(representation_id__in=representation_ids)
        .order_by("representation_id", "id")
    )
    return _EmergencyInventory(
        subject_id=subject_id,
        representations=representations,
        organizations=organizations,
        appointments=appointments,
    )


def _validate_primary_emergency_removal(
    *,
    inventory: _EmergencyInventory,
    representation_id: UUID,
    appointment_id: UUID,
    expected_version: int,
) -> RepresentationAppointment:
    representation = next(
        (item for item in inventory.representations if item.id == representation_id),
        None,
    )
    appointment = next(
        (
            item
            for item in inventory.appointments
            if item.id == appointment_id
            and item.account_id == inventory.subject_id
            and item.state in OPEN_REPRESENTATION_APPOINTMENT_STATES
        ),
        None,
    )
    if representation is None or appointment is None:
        raise ValidationError(
            "The open controller relationship is unavailable.",
            code="representation_controller_not_open",
        )
    organization = inventory.organizations[representation.organization_id]
    definition = _representation_definition(representation)
    if representation.aggregate_version != expected_version:
        raise ValidationError(
            f"This {definition.name} changed after the operation was prepared.",
            code="stale_representation",
        )
    provisioning_relationship = (
        representation.state == OrganizationRepresentation.State.PROVISIONING
        and organization.lifecycle == Organization.Lifecycle.DRAFT
        and appointment.state
        in (
            RepresentationAppointment.State.INVITED,
            RepresentationAppointment.State.ACCEPTED,
        )
    )
    active_relationship = (
        representation.state == OrganizationRepresentation.State.ACTIVE
        and organization.lifecycle == Organization.Lifecycle.ACTIVE
        and appointment.state == RepresentationAppointment.State.ACTIVE
    )
    if not provisioning_relationship and not active_relationship:
        raise ValidationError(
            "The open controller relationship requires recovery review.",
            code="representation_controller_evidence_incomplete",
        )
    return appointment


def _build_emergency_plans(
    *, inventory: _EmergencyInventory
) -> tuple[_EmergencyRepresentationPlan, ...]:
    plans: list[_EmergencyRepresentationPlan] = []
    for representation in inventory.representations:
        definition = _representation_definition(representation)
        organization = inventory.organizations[representation.organization_id]
        local_appointments = tuple(
            item
            for item in inventory.appointments
            if item.representation_id == representation.id
        )
        subject_appointment = next(
            (
                item
                for item in local_appointments
                if item.account_id == inventory.subject_id
                and item.state in OPEN_REPRESENTATION_APPOINTMENT_STATES
            ),
            None,
        )
        if subject_appointment is None:
            raise ValidationError(
                "The controller inventory changed; retry from a fresh page.",
                code="representation_inventory_changed",
            )
        if representation.state == OrganizationRepresentation.State.PROVISIONING:
            if (
                organization.lifecycle != Organization.Lifecycle.DRAFT
                or subject_appointment.state
                not in (
                    RepresentationAppointment.State.INVITED,
                    RepresentationAppointment.State.ACCEPTED,
                )
            ):
                raise ValidationError(
                    "A provisioning relationship requires recovery review.",
                    code="representation_controller_evidence_incomplete",
                )
            plans.append(
                _EmergencyRepresentationPlan(
                    representation,
                    organization,
                    subject_appointment,
                    (subject_appointment,),
                    None,
                )
            )
            continue
        if (
            representation.state != OrganizationRepresentation.State.ACTIVE
            or organization.lifecycle != Organization.Lifecycle.ACTIVE
            or subject_appointment.state != RepresentationAppointment.State.ACTIVE
        ):
            raise ValidationError(
                f"An open {definition.name} relationship requires recovery review.",
                code="representation_controller_evidence_incomplete",
            )
        active_appointments = tuple(
            item
            for item in local_appointments
            if item.state == RepresentationAppointment.State.ACTIVE
        )
        quorum_preserved = (
            len(active_appointments) - 1 >= MINIMUM_REPRESENTATION_CONTROLLERS
        )
        plans.append(
            _EmergencyRepresentationPlan(
                representation,
                organization,
                subject_appointment,
                ((subject_appointment,) if quorum_preserved else active_appointments),
                quorum_preserved,
            )
        )
    return tuple(plans)


def _lock_emergency_evidence(
    *, plans: Sequence[_EmergencyRepresentationPlan]
) -> _EmergencyEvidence:
    ended_appointments = tuple(
        appointment for plan in plans for appointment in plan.ended_appointments
    )
    membership_keys = {
        (plan.organization.id, appointment.account_id)
        for plan in plans
        for appointment in plan.ended_appointments
    }
    memberships = {
        (membership.organization_id, membership.account_id): membership
        for membership in OrganizationMembership.objects.select_for_update()
        .filter(
            organization_id__in={key[0] for key in membership_keys},
            account_id__in={key[1] for key in membership_keys},
        )
        .order_by("organization_id", "account_id")
    }
    assignment_ids = {
        appointment.role_assignment_id
        for appointment in ended_appointments
        if appointment.role_assignment_id is not None
    }
    assignments = {
        assignment.id: assignment
        for assignment in RoleAssignment.objects.select_for_update(of=("self",))
        .select_related("principal", "role_bundle")
        .filter(id__in=assignment_ids)
        .order_by("id")
    }
    return _EmergencyEvidence(memberships=memberships, assignments=assignments)


def _lock_subject_and_recheck_inventory(*, inventory: _EmergencyInventory) -> Account:
    subject = Account.objects.select_for_update().get(id=inventory.subject_id)
    locked_open_ids = {
        item.id
        for item in inventory.appointments
        if item.account_id == inventory.subject_id
        and item.state in OPEN_REPRESENTATION_APPOINTMENT_STATES
    }
    current_open_ids = set(
        RepresentationAppointment.objects.filter(
            account_id=inventory.subject_id,
            state__in=OPEN_REPRESENTATION_APPOINTMENT_STATES,
        ).values_list("id", flat=True)
    )
    if current_open_ids != locked_open_ids:
        raise ValidationError(
            "The controller inventory changed; retry from a fresh page.",
            code="representation_inventory_changed",
        )
    if (
        not subject.is_active
        or subject.is_platform_administrator
        or not subject.has_verified_email
    ):
        raise ValidationError(
            "The controller account is not eligible for this emergency path.",
            code="emergency_deactivation_subject_ineligible",
        )
    return subject


def _validate_emergency_evidence(
    *, plans: Sequence[_EmergencyRepresentationPlan], evidence: _EmergencyEvidence
) -> None:
    for plan in plans:
        definition = _representation_definition(plan.representation)
        for appointment in plan.ended_appointments:
            membership = evidence.memberships.get(
                (plan.organization.id, appointment.account_id)
            )
            if appointment.state == RepresentationAppointment.State.ACTIVE:
                assignment_id = appointment.role_assignment_id
                if (
                    assignment_id is None
                    or assignment_id not in evidence.assignments
                    or membership is None
                    or membership.state != OrganizationMembership.State.ACTIVE
                    or membership.relationship_label != definition.membership_label
                    or evidence.assignments[assignment_id].organization_id
                    != plan.organization.id
                    or evidence.assignments[assignment_id].principal_id
                    != appointment.account_id
                    or evidence.assignments[assignment_id].revoked_at is not None
                ):
                    raise ValidationError(
                        "The controller evidence changed and requires recovery review.",
                        code="representation_controller_evidence_incomplete",
                    )
            elif membership is not None and (
                membership.state == OrganizationMembership.State.INVITED
                and membership.relationship_label != definition.membership_label
            ):
                raise ValidationError(
                    "The invitation membership requires recovery review.",
                    code="representation_controller_evidence_incomplete",
                )


def _end_emergency_appointment(
    *,
    plan: _EmergencyRepresentationPlan,
    appointment: RepresentationAppointment,
    evidence: _EmergencyEvidence,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
    changed_at: datetime,
) -> None:
    definition = _representation_definition(plan.representation)
    assignment_id = appointment.role_assignment_id
    if assignment_id is not None:
        assignment = evidence.assignments[assignment_id]
        assignment.revoked_at = changed_at
        assignment.revoked_by = actor
        assignment.revocation_reason = reason
        assignment.save(
            update_fields=(
                "revoked_at",
                "revoked_by",
                "revocation_reason",
                "updated_at",
            )
        )
        _audit(
            actor=actor,
            organization_id=plan.organization.id,
            operation="organizations.representation.authority_revoke",
            target_type="authorization.role_assignment",
            target_id=assignment.id,
            correlation_id=correlation_id,
            reason_code="platform_emergency_removal",
            obligations=("reason", "audit"),
            changed_fields=("revoked_at",),
            source_channel=source_channel,
        )
    membership = evidence.memberships.get(
        (plan.organization.id, appointment.account_id)
    )
    should_end_membership = membership is not None and (
        appointment.state == RepresentationAppointment.State.ACTIVE
        or (
            membership.state == OrganizationMembership.State.INVITED
            and membership.relationship_label == definition.membership_label
        )
    )
    if should_end_membership and membership is not None:
        membership.state = OrganizationMembership.State.ENDED
        membership.ended_at = changed_at
        membership.save(update_fields=("state", "ended_at", "updated_at"))
    if appointment.responded_at is None:
        appointment.responded_at = changed_at
    appointment.state = RepresentationAppointment.State.ENDED
    appointment.ended_at = changed_at
    appointment.invitation_version += 1
    appointment.save(
        update_fields=(
            "state",
            "responded_at",
            "ended_at",
            "invitation_version",
            "updated_at",
        )
    )


def _apply_emergency_plan(
    *,
    plan: _EmergencyRepresentationPlan,
    evidence: _EmergencyEvidence,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
    changed_at: datetime,
) -> None:
    if plan.quorum_preserved is False:
        plan.organization.lifecycle = Organization.Lifecycle.SUSPENDED
        plan.organization.save(update_fields=("lifecycle", "updated_at"))
        plan.representation.state = OrganizationRepresentation.State.SUSPENDED
    for appointment in plan.ended_appointments:
        _end_emergency_appointment(
            plan=plan,
            appointment=appointment,
            evidence=evidence,
            actor=actor,
            reason=reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_at=changed_at,
        )


def _record_emergency_plan(
    *,
    plan: _EmergencyRepresentationPlan,
    actor: Account,
    correlation_id: UUID,
    source_channel: str,
) -> None:
    plan.representation.aggregate_version += 1
    plan.representation.save(update_fields=("state", "aggregate_version", "updated_at"))
    action: str
    changed_fields: tuple[str, ...]
    if plan.quorum_preserved is None:
        action = "controller_invitation_ended"
        changed_fields = (
            "account_state",
            "appointment_state",
            "membership_state",
        )
    elif plan.quorum_preserved:
        action = "controller_ended"
        changed_fields = (
            "account_state",
            "appointment_state",
            "membership_state",
            "role_assignment",
        )
    else:
        action = "representation_suspended"
        changed_fields = (
            "account_state",
            "appointment_state",
            "membership_state",
            "role_assignment",
            "organization_lifecycle",
            "representation_state",
            "board_terms",
        )
    audit = _audit(
        actor=actor,
        organization_id=plan.organization.id,
        operation="organizations.representation.emergency_controller_remove",
        target_type="organizations.organization_representation",
        target_id=plan.representation.id,
        correlation_id=correlation_id,
        reason_code="platform_emergency_removal",
        obligations=("reason", "audit"),
        changed_fields=changed_fields,
        source_channel=source_channel,
    )
    _publish_representation_change(
        representation=plan.representation,
        action=action,
        state=plan.representation.state,
        actor=actor,
        correlation_id=correlation_id,
        causation_id=audit.id,
    )


@transaction.atomic
def emergency_remove_executive_board_controller(
    *,
    actor: Account,
    representation_id: UUID,
    appointment_id: UUID,
    expected_version: int,
    reason: str,
    correlation_id: UUID,
    source_channel: str = "service",
) -> EmergencyControllerRemovalResult:
    """Contain one account across every open representation relationship.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    representation_id : UUID
        The representation identifier within the requested scope.
    appointment_id : UUID
        The appointment identifier within the requested scope.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    EmergencyControllerRemovalResult
        The EmergencyControllerRemovalResult produced by emergency remove
        executive board controller.
    """
    _require_platform_administrator(actor)
    normalized_reason = _normalized_reason(reason)
    # Emergency containment closes RoleAssignments after locking a broad
    # cross-organization inventory. Acquire the common writer boundary first
    # so a concurrent authority/structure writer cannot invert that order.
    lock_retired_department_authority_boundaries()
    subject_id = _resolve_emergency_subject(
        representation_id=representation_id,
        appointment_id=appointment_id,
    )
    inventory = _lock_emergency_inventory(subject_id=subject_id)
    removed_appointment = _validate_primary_emergency_removal(
        inventory=inventory,
        representation_id=representation_id,
        appointment_id=appointment_id,
        expected_version=expected_version,
    )
    plans = _build_emergency_plans(inventory=inventory)
    evidence = _lock_emergency_evidence(plans=plans)
    _lock_subject_and_recheck_inventory(inventory=inventory)
    _validate_emergency_evidence(plans=plans, evidence=evidence)
    changed_at = timezone.now()
    for plan in plans:
        _apply_emergency_plan(
            plan=plan,
            evidence=evidence,
            actor=actor,
            reason=normalized_reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_at=changed_at,
        )
    deactivate_person_account_for_platform_emergency(
        actor=actor,
        account_id=subject_id,
        reason=normalized_reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    for plan in plans:
        _record_emergency_plan(
            plan=plan,
            actor=actor,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
    primary_plan = next(
        plan for plan in plans if plan.representation.id == representation_id
    )
    return EmergencyControllerRemovalResult(
        representation=primary_plan.representation,
        organization=primary_plan.organization,
        removed_appointment=removed_appointment,
        ended_appointments=tuple(
            appointment for plan in plans for appointment in plan.ended_appointments
        ),
        affected_representations=tuple(plan.representation for plan in plans),
        quorum_preserved=primary_plan.quorum_preserved,
    )
