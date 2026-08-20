"""Governed live admission capacity, waitlist batches, and tier replacement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import append_audit
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_owned_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.queries import account_display_labels
from maru.registration.availability import (
    OCCUPIED_REGISTRATION_STATES,
    assess_product_availability,
)
from maru.registration.models import (
    AdmissionProduct,
    AdmissionTierReplacement,
    Entitlement,
    Registration,
    RegistrationAdjustment,
    RegistrationCapacityAdjustment,
    RegistrationCommerceCommandReceipt,
    RegistrationCommerceControl,
    RegistrationConfiguration,
    RegistrationTimelineEntry,
    WaitlistBatchOffer,
)
from maru.registration.setup_content import canonical_digest

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from django.db.models import QuerySet

    from maru.identity.models import Account

MANAGE_EXCEPTIONS = "registration.manage_exceptions"
REGISTER_SELF = "registration.register_self"
MAX_WAITLIST_BATCH_SIZE = 100
MAX_COMMERCE_ACTIVITY_ITEMS = 100
MAX_COMMERCE_REASON_LENGTH = 500


@dataclass(frozen=True, slots=True)
class TierReplacementCommandResult:
    """Describe tier replacement command result.

    Attributes
    ----------
    replacement
        The replacement retained in this immutable projection.
    control_version
        The expected control version used to reject stale updates.
    replayed
        The replayed retained in this immutable projection.
    """

    replacement: AdmissionTierReplacement
    control_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class CapacityAdjustmentCommandResult:
    """Describe capacity adjustment command result.

    Attributes
    ----------
    adjustment
        The adjustment retained in this immutable projection.
    control_version
        The expected control version used to reject stale updates.
    replayed
        The replayed retained in this immutable projection.
    """

    adjustment: RegistrationCapacityAdjustment
    control_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class WaitlistBatchCommandResult:
    """Describe waitlist batch command result.

    Attributes
    ----------
    batch
        The batch retained in this immutable projection.
    offered_registration_ids
        The selected offered registration identifiers.
    control_version
        The expected control version used to reject stale updates.
    replayed
        The replayed retained in this immutable projection.
    """

    batch: WaitlistBatchOffer
    offered_registration_ids: tuple[UUID, ...]
    control_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class RegistrationCommerceActivity:
    """Describe registration commerce activity.

    Attributes
    ----------
    event_name
        The human-readable event name shown to authorized readers.
    action
        The stable action code describing the requested transition.
    actor_label
        The human-readable actor label shown to authorized readers.
    occurred_at
        The timezone-aware timestamp for occurred.
    target_count
        The bounded number of target records.
    """

    event_name: str
    action: str
    actor_label: str
    occurred_at: datetime
    target_count: int


_ACTIVITY_LABELS = {
    "registration.admission_tier_replacement.reserved.v1": (
        "Reserved an admission-tier upgrade"
    ),
    "registration.admission_tier_replacement.completed.v1": (
        "Completed an admission-tier upgrade"
    ),
    "registration.admission_tier_replacement.expired.v1": (
        "Released an expired admission-tier upgrade"
    ),
    "registration.capacity.adjusted.v1": "Adjusted registration capacity",
    "registration.waitlist.batch_offered.v1": "Offered a strict FIFO waitlist batch",
}


def authorize_owned_registration_api_scope(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
) -> None:
    """Authorize exact self-registration ownership before parsing API input.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    registration_id : UUID
        The attendee registration identifier within the edition scope.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    owned = Registration.objects.filter(
        id=registration_id,
        organization_id=organization_id,
        edition_id=edition_id,
        account_id=actor.id,
    ).first()
    decision = decide(
        principal=actor,
        capability_code=REGISTER_SELF,
        resource=resolve_owned_target(resource=owned) if owned is not None else None,
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "The registration operation is unavailable.",
            reason_code=decision.reason_code,
        )


def authorize_tier_replacement_api_scope(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
) -> None:
    """Compatibility-named exact preflight for admission-tier replacement.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    registration_id : UUID
        The attendee registration identifier within the edition scope.
    """
    authorize_owned_registration_api_scope(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        registration_id=registration_id,
    )


def authorize_registration_commerce_edition_api_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> None:
    """Authorize edition commerce operations before parsing API input.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    decision = decide(
        principal=actor,
        capability_code=MANAGE_EXCEPTIONS,
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "The registration commerce operation is unavailable.",
            reason_code=decision.reason_code,
        )


def configuration_capacity_ceiling(configuration: RegistrationConfiguration) -> int:
    """Return configuration capacity ceiling.

    Parameters
    ----------
    configuration : RegistrationConfiguration
        The versioned configuration governing validation and behavior.

    Returns
    -------
    int
        The effective numeric value for configuration capacity ceiling.
    """
    return int(configuration.capacity_ceiling or configuration.capacity)


def product_capacity_ceiling(product: AdmissionProduct) -> int:
    """Return product capacity ceiling.

    Parameters
    ----------
    product : AdmissionProduct
        The edition-owned product whose policy or capacity is evaluated.

    Returns
    -------
    int
        The effective numeric value for product capacity ceiling.
    """
    return int(product.capacity_ceiling or product.capacity)


def effective_configuration_capacity(
    configuration: RegistrationConfiguration,
) -> int:
    """Return effective configuration capacity.

    Parameters
    ----------
    configuration : RegistrationConfiguration
        The versioned configuration governing validation and behavior.

    Returns
    -------
    int
        The effective numeric value for effective configuration capacity.
    """
    latest = (
        RegistrationCapacityAdjustment.objects.filter(
            configuration=configuration,
            scope=RegistrationCapacityAdjustment.Scope.OVERALL,
            product__isnull=True,
        )
        .order_by("-control_version", "-id")
        .values_list("new_capacity", flat=True)
        .first()
    )
    return int(latest if latest is not None else configuration.capacity)


def effective_product_capacity(product: AdmissionProduct) -> int:
    """Return effective product capacity.

    Parameters
    ----------
    product : AdmissionProduct
        The edition-owned product whose policy or capacity is evaluated.

    Returns
    -------
    int
        The effective numeric value for effective product capacity.
    """
    latest = (
        RegistrationCapacityAdjustment.objects.filter(
            configuration=product.configuration,
            product=product,
            scope=RegistrationCapacityAdjustment.Scope.PRODUCT,
        )
        .order_by("-control_version", "-id")
        .values_list("new_capacity", flat=True)
        .first()
    )
    return int(latest if latest is not None else product.capacity)


def pending_target_capacity_holds(
    product: AdmissionProduct,
    *,
    at: datetime | None = None,
) -> int:
    """Return pending target capacity holds.

    Parameters
    ----------
    product : AdmissionProduct
        The edition-owned product whose policy or capacity is evaluated.
    at : datetime | None, default=None
        The point in time used for the operation.

    Returns
    -------
    int
        The effective numeric value for pending target capacity holds.
    """
    evaluated_at = at or timezone.now()
    return AdmissionTierReplacement.objects.filter(
        target_product=product,
        status=AdmissionTierReplacement.Status.PAYMENT_PENDING,
        payment_due_at__gt=evaluated_at,
    ).count()


def _reason(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError(
            {"reason": "A reason is required."}, code="reason_required"
        )
    if len(normalized) > MAX_COMMERCE_REASON_LENGTH:
        raise ValidationError(
            {"reason": "Use no more than 500 characters."},
            code="reason_too_long",
        )
    return normalized


def _lock_control(
    configuration: RegistrationConfiguration,
) -> RegistrationCommerceControl:
    control = (
        RegistrationCommerceControl.objects.select_for_update()
        .filter(configuration=configuration)
        .first()
    )
    if control is None:
        RegistrationCommerceControl.objects.create(
            configuration=configuration,
            organization_id=configuration.organization_id,
            edition_id=configuration.edition_id,
            aggregate_version=1,
        )
        control = RegistrationCommerceControl.objects.select_for_update().get(
            configuration=configuration
        )
    return control


def _existing_receipt(
    *,
    control: RegistrationCommerceControl,
    actor: Account,
    idempotency_key: UUID,
    operation: str,
    request_digest: str,
) -> RegistrationCommerceCommandReceipt | None:
    receipt = RegistrationCommerceCommandReceipt.objects.filter(
        control=control,
        actor=actor,
        idempotency_key=idempotency_key,
    ).first()
    if receipt is None:
        return None
    if receipt.operation != operation or receipt.request_digest != request_digest:
        raise ValidationError(
            "The idempotency key belongs to another commerce command.",
            code="registration_commerce_idempotency_conflict",
        )
    return receipt


def _advance_control(control: RegistrationCommerceControl) -> int:
    control.aggregate_version += 1
    control.save(update_fields=("aggregate_version", "updated_at"))
    return int(control.aggregate_version)


def _publish_commerce_event(
    *,
    event_name: str,
    organization_id: UUID,
    edition_id: UUID,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int,
    payload: dict[str, object],
    correlation_id: UUID,
    causation_id: UUID,
    actor_kind: str,
    actor_id: UUID | None,
) -> None:
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=organization_id,
            event_edition_id=edition_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            actor_kind=actor_kind,
            actor_id=actor_id,
            retention_class="registration-operational",
        ),
        workload_pool="core",
    )


def _occupied_registrations(
    configuration: RegistrationConfiguration,
) -> QuerySet[Registration]:
    return Registration.objects.filter(
        configuration=configuration,
        state__in=OCCUPIED_REGISTRATION_STATES,
    )


def reserve_admission_tier_replacement(
    *,
    organization_id: UUID,
    edition_id: UUID,
    registration_id: UUID,
    target_product_id: UUID,
    actor: Account,
    expected_registration_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
) -> TierReplacementCommandResult:
    """Hold the target tier while retaining the paid source admission.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    registration_id : UUID
        The attendee registration identifier within the edition scope.
    target_product_id : UUID
        The target product identifier within the requested scope.
    actor : Account
        The authenticated account authorizing the operation.
    expected_registration_version : int
        The expected expected registration version used to reject stale updates.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='api'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    TierReplacementCommandResult
        The TierReplacementCommandResult produced by reserve admission tier
        replacement.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    from maru.registration.services import (  # noqa: PLC0415
        _append_timeline,
        _audit_record,
        _payment_deadline,
        _require_decision,
    )

    owned = Registration.objects.filter(
        id=registration_id,
        organization_id=organization_id,
        edition_id=edition_id,
        account=actor,
    ).first()
    obligations = _require_decision(
        actor=actor,
        capability_code=REGISTER_SELF,
        target=resolve_owned_target(resource=owned) if owned is not None else None,
        operation="registration.admission_tier_replacement.reserve",
        target_type="registration.admission_tier_replacement",
        target_id=None,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    if (
        type(expected_registration_version) is not int
        or expected_registration_version < 1
    ):
        raise ValidationError(
            {"expected_registration_version": "Use a positive version."},
            code="registration_version_invalid",
        )
    reserved_at = now or timezone.now()
    digest = canonical_digest(
        {
            "operation": "tier_replacement_reserved",
            "organization_id": organization_id,
            "edition_id": edition_id,
            "registration_id": registration_id,
            "target_product_id": target_product_id,
            "actor_id": actor.id,
            "expected_registration_version": expected_registration_version,
        }
    )
    with transaction.atomic():
        configuration = RegistrationConfiguration.objects.select_for_update().get(
            organization_id=organization_id,
            edition_id=edition_id,
            status="active",
        )
        control = _lock_control(configuration)
        receipt = _existing_receipt(
            control=control,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=RegistrationCommerceCommandReceipt.Operation.TIER_REPLACEMENT_RESERVED,
            request_digest=digest,
        )
        if receipt is not None:
            return TierReplacementCommandResult(
                replacement=AdmissionTierReplacement.objects.get(id=receipt.result_id),
                control_version=int(receipt.resulting_version),
                replayed=True,
            )
        registration = (
            Registration.objects.select_for_update()
            .select_related("product", "configuration")
            .get(
                id=registration_id,
                organization_id=organization_id,
                edition_id=edition_id,
                account=actor,
                configuration=configuration,
            )
        )
        if registration.aggregate_version != expected_registration_version:
            raise ValidationError(
                "The registration changed; reload it before requesting an upgrade.",
                code="registration_version_conflict",
            )
        if (
            registration.state
            not in {
                Registration.State.CONFIRMED,
                Registration.State.CHECKED_IN,
            }
            or registration.confirmation_basis
            != Registration.ConfirmationBasis.PROVIDER
        ):
            raise ValidationError(
                "Only a provider-paid admission can be upgraded.",
                code="tier_replacement_source_not_paid",
            )
        if (
            AdmissionTierReplacement.objects.select_for_update()
            .filter(
                registration=registration,
                status=AdmissionTierReplacement.Status.PAYMENT_PENDING,
            )
            .exists()
        ):
            raise ValidationError(
                "This registration already has an upgrade awaiting payment.",
                code="tier_replacement_already_pending",
            )
        target = (
            AdmissionProduct.objects.select_for_update()
            .select_related("configuration")
            .get(
                id=target_product_id,
                configuration=configuration,
                status=AdmissionProduct.Status.AVAILABLE,
            )
        )
        availability = assess_product_availability(
            product=target,
            account=actor,
            at=reserved_at,
        )
        if not availability.selectable and availability.code != "capacity_reached":
            raise ValidationError(availability.explanation, code=availability.code)
        source = registration.product
        if target.id == source.id or target.price_minor <= source.price_minor:
            raise ValidationError(
                "Choose a currently configured higher-priced admission tier.",
                code="tier_replacement_target_not_higher",
            )
        occupied_target = (
            _occupied_registrations(configuration).filter(product=target).count()
        )
        held_target = pending_target_capacity_holds(target, at=reserved_at)
        if occupied_target + held_target >= effective_product_capacity(target):
            raise ValidationError(
                "The requested admission tier has no available capacity.",
                code="tier_replacement_target_full",
            )
        payment_due_at = _payment_deadline(
            configuration=configuration,
            product=target,
            starts_at=reserved_at,
        )
        replacement = AdmissionTierReplacement.objects.create(
            registration=registration,
            organization_id=organization_id,
            edition_id=edition_id,
            source_product=source,
            target_product=target,
            source_product_name_snapshot=source.name,
            target_product_name_snapshot=target.name,
            source_price_minor_snapshot=source.price_minor,
            target_price_minor_snapshot=target.price_minor,
            amount_due_minor=target.price_minor - source.price_minor,
            currency=configuration.currency,
            source_entitlement_code=source.entitlement_code,
            target_entitlement_code=target.entitlement_code,
            target_entitlement_name_snapshot=target.entitlement_name,
            expected_registration_version=registration.aggregate_version,
            reserved_at=reserved_at,
            payment_due_at=payment_due_at,
            actor=actor,
        )
        _append_timeline(
            registration=registration,
            kind="admission_tier_replacement_reserved",
            title="Admission upgrade reserved",
            summary=(
                f"{target.name} is held until {payment_due_at.isoformat()}. "
                "Your current admission remains active unless the upgrade "
                "payment succeeds."
            ),
            occurred_at=reserved_at,
            actor_kind="account",
            actor_id=actor.id,
            correlation_id=correlation_id,
        )
        audit = append_audit(
            _audit_record(
                actor=actor,
                capability_code=REGISTER_SELF,
                operation="registration.admission_tier_replacement.reserve",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.admission_tier_replacement",
                target_id=replacement.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="attendee_tier_replacement_reserved",
                obligations=obligations,
                changed_fields=("target_capacity_hold", "timeline"),
                source_channel=source_channel,
            )
        )
        _publish_commerce_event(
            event_name="registration.admission_tier_replacement.reserved.v1",
            organization_id=organization_id,
            edition_id=edition_id,
            aggregate_type="registration.admission_tier_replacement",
            aggregate_id=replacement.id,
            aggregate_version=1,
            payload={
                "registration_id": str(registration.id),
                "target_product_id": str(target.id),
                "status": replacement.status,
            },
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=actor.id,
        )
        previous_control_version = int(control.aggregate_version)
        result_version = _advance_control(control)
        RegistrationCommerceCommandReceipt.objects.create(
            control=control,
            registration=registration,
            actor=actor,
            operation=(
                RegistrationCommerceCommandReceipt.Operation.TIER_REPLACEMENT_RESERVED
            ),
            idempotency_key=idempotency_key,
            request_digest=digest,
            expected_version=previous_control_version,
            resulting_version=result_version,
            result_id=replacement.id,
        )
        return TierReplacementCommandResult(
            replacement=replacement,
            control_version=result_version,
            replayed=False,
        )


def adjust_registration_capacity(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    new_capacity: int,
    reason: str,
    expected_control_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    product_id: UUID | None = None,
    source_channel: str = "api",
    now: datetime | None = None,
) -> CapacityAdjustmentCommandResult:
    """Append one effective capacity value without editing active definitions.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    actor : Account
        The authenticated account authorizing the operation.
    new_capacity : int
        The non-negative hard limit or requested amount for new capacity.
    reason : str
        The operator-supplied rationale recorded with the change.
    expected_control_version : int
        The expected expected control version used to reject stale updates.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    product_id : UUID | None, default=None
        The product identifier within the requested scope.
    source_channel : str, default='api'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    CapacityAdjustmentCommandResult
        The CapacityAdjustmentCommandResult produced by adjust registration
        capacity.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    from maru.registration.services import (  # noqa: PLC0415
        _audit_record,
        _require_decision,
    )

    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_EXCEPTIONS,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.capacity.adjust",
        target_type="registration.capacity",
        target_id=product_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _reason(reason)
    if type(new_capacity) is not int or new_capacity < 1:
        raise ValidationError(
            {"new_capacity": "Use a positive capacity."},
            code="registration_capacity_invalid",
        )
    adjusted_at = now or timezone.now()
    scope = (
        RegistrationCapacityAdjustment.Scope.PRODUCT
        if product_id is not None
        else RegistrationCapacityAdjustment.Scope.OVERALL
    )
    operation = (
        RegistrationCommerceCommandReceipt.Operation.PRODUCT_CAPACITY_ADJUSTED
        if product_id is not None
        else RegistrationCommerceCommandReceipt.Operation.OVERALL_CAPACITY_ADJUSTED
    )
    digest = canonical_digest(
        {
            "operation": operation,
            "organization_id": organization_id,
            "edition_id": edition_id,
            "product_id": product_id,
            "new_capacity": new_capacity,
            "reason": normalized_reason,
            "actor_id": actor.id,
            "expected_control_version": expected_control_version,
        }
    )
    with transaction.atomic():
        configuration = RegistrationConfiguration.objects.select_for_update().get(
            organization_id=organization_id,
            edition_id=edition_id,
            status="active",
        )
        control = _lock_control(configuration)
        receipt = _existing_receipt(
            control=control,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=operation,
            request_digest=digest,
        )
        if receipt is not None:
            return CapacityAdjustmentCommandResult(
                adjustment=RegistrationCapacityAdjustment.objects.get(
                    id=receipt.result_id
                ),
                control_version=int(receipt.resulting_version),
                replayed=True,
            )
        if control.aggregate_version != expected_control_version:
            raise ValidationError(
                "Registration commerce settings changed; reload before "
                "adjusting capacity.",
                code="registration_commerce_version_conflict",
            )
        product = None
        if product_id is not None:
            product = AdmissionProduct.objects.select_for_update().get(
                id=product_id,
                configuration=configuration,
            )
            previous = effective_product_capacity(product)
            ceiling = product_capacity_ceiling(product)
            occupied = _occupied_registrations(configuration).filter(
                product=product
            ).count() + pending_target_capacity_holds(product, at=adjusted_at)
        else:
            previous = effective_configuration_capacity(configuration)
            ceiling = configuration_capacity_ceiling(configuration)
            occupied = _occupied_registrations(configuration).count()
        if new_capacity > ceiling:
            raise ValidationError(
                "The requested capacity exceeds the configured hard ceiling.",
                code="registration_capacity_ceiling_exceeded",
            )
        if new_capacity < occupied:
            raise ValidationError(
                "Capacity cannot be reduced below current reservations and holds.",
                code="registration_capacity_below_occupied",
            )
        if new_capacity == previous:
            raise ValidationError(
                "Choose a capacity different from the current effective value.",
                code="registration_capacity_unchanged",
            )
        previous_control_version = int(control.aggregate_version)
        result_version = _advance_control(control)
        adjustment = RegistrationCapacityAdjustment.objects.create(
            control=control,
            configuration=configuration,
            product=product,
            organization_id=organization_id,
            edition_id=edition_id,
            scope=scope,
            previous_capacity=previous,
            new_capacity=new_capacity,
            hard_ceiling=ceiling,
            control_version=result_version,
            actor=actor,
            reason=normalized_reason,
            occurred_at=adjusted_at,
        )
        audit = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_EXCEPTIONS,
                operation="registration.capacity.adjust",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.capacity",
                target_id=product.id if product is not None else configuration.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="registration_capacity_adjusted",
                obligations=obligations,
                changed_fields=("effective_capacity", "capacity_adjustment"),
                source_channel=source_channel,
            )
        )
        _publish_commerce_event(
            event_name="registration.capacity.adjusted.v1",
            organization_id=organization_id,
            edition_id=edition_id,
            aggregate_type="registration.commerce_control",
            aggregate_id=control.id,
            aggregate_version=result_version,
            payload={
                "scope": scope,
                "target_id": str(
                    product.id if product is not None else configuration.id
                ),
                "previous_capacity": str(previous),
                "new_capacity": str(new_capacity),
            },
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=actor.id,
        )
        RegistrationCommerceCommandReceipt.objects.create(
            control=control,
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=digest,
            expected_version=previous_control_version,
            resulting_version=result_version,
            result_id=adjustment.id,
        )
        return CapacityAdjustmentCommandResult(
            adjustment=adjustment,
            control_version=result_version,
            replayed=False,
        )


def _offer_waitlisted_registration(
    *,
    registration: Registration,
    actor: Account,
    offered_at: datetime,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
) -> None:
    from maru.registration.services import (  # noqa: PLC0415
        _append_timeline,
        _audit_record,
        _grant_product_entitlement,
        _payment_deadline,
        _publish_registration_transition,
        _record_adjustment,
    )

    previous_state = registration.state
    registration.offered_at = offered_at
    if registration.price_minor_snapshot == 0:
        registration.state = Registration.State.CONFIRMED
        registration.confirmed_at = offered_at
        registration.confirmation_basis = Registration.ConfirmationBasis.FREE
        registration.payment_due_at = None
    else:
        registration.state = Registration.State.PAYMENT_PENDING
        registration.payment_due_at = _payment_deadline(
            configuration=registration.configuration,
            product=registration.product,
            starts_at=offered_at,
        )
    registration.aggregate_version += 1
    registration.save(
        update_fields=(
            "state",
            "offered_at",
            "payment_due_at",
            "confirmed_at",
            "confirmation_basis",
            "aggregate_version",
            "updated_at",
        )
    )
    if registration.state == Registration.State.CONFIRMED:
        _grant_product_entitlement(registration=registration, granted_at=offered_at)
    _record_adjustment(
        registration=registration,
        kind=RegistrationAdjustment.Kind.WAITLIST_PROMOTED,
        reason=reason,
        occurred_at=offered_at,
        actor_kind="account",
        actor_id=actor.id,
        from_state=previous_state,
        to_state=registration.state,
        new_deadline=registration.payment_due_at,
    )
    _append_timeline(
        registration=registration,
        kind="waitlist_place_offered",
        title="A registration place is available",
        summary=(
            f"Complete payment by {registration.payment_due_at.isoformat()} to keep "
            "the offered place."
            if registration.payment_due_at is not None
            else "The no-cost registration is now confirmed."
        ),
        occurred_at=offered_at,
        actor_kind="account",
        actor_id=actor.id,
        correlation_id=correlation_id,
    )
    audit = append_audit(
        _audit_record(
            actor=actor,
            capability_code=MANAGE_EXCEPTIONS,
            operation="registration.waitlist.batch_offer_item",
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
            target_type="registration.registration",
            target_id=registration.id,
            correlation_id=correlation_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="strict_fifo_waitlist_batch_offered",
            changed_fields=("state", "offered_at", "payment_due_at", "timeline"),
            source_channel=source_channel,
        )
    )
    _publish_registration_transition(
        registration=registration,
        event_name="registration.waitlist.offered.v1",
        from_state=previous_state,
        correlation_id=correlation_id,
        actor_kind="account",
        actor_id=actor.id,
        causation_id=audit.id,
    )


def offer_next_waitlist_batch(
    *,
    organization_id: UUID,
    edition_id: UUID,
    product_id: UUID,
    actor: Account,
    batch_size: int,
    reason: str,
    expected_control_version: int,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "api",
    now: datetime | None = None,
) -> WaitlistBatchCommandResult:
    """Offer capacity to the first N eligible rows; callers cannot select people.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    product_id : UUID
        The product identifier within the requested scope.
    actor : Account
        The authenticated account authorizing the operation.
    batch_size : int
        The batch size evaluated while offer next waitlist batch.
    reason : str
        The operator-supplied rationale recorded with the change.
    expected_control_version : int
        The expected expected control version used to reject stale updates.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='api'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    WaitlistBatchCommandResult
        The resolved WaitlistBatchCommandResult for offer next waitlist batch.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    from maru.registration.services import (  # noqa: PLC0415
        _audit_record,
        _require_decision,
    )

    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_EXCEPTIONS,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.waitlist.batch_offer",
        target_type="registration.waitlist_batch",
        target_id=None,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    normalized_reason = _reason(reason)
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_WAITLIST_BATCH_SIZE:
        raise ValidationError(
            {"batch_size": f"Choose 1 through {MAX_WAITLIST_BATCH_SIZE}."},
            code="waitlist_batch_size_invalid",
        )
    offered_at = now or timezone.now()
    digest = canonical_digest(
        {
            "operation": "waitlist_batch_offered",
            "organization_id": organization_id,
            "edition_id": edition_id,
            "product_id": product_id,
            "batch_size": batch_size,
            "reason": normalized_reason,
            "actor_id": actor.id,
            "expected_control_version": expected_control_version,
        }
    )
    with transaction.atomic():
        configuration = RegistrationConfiguration.objects.select_for_update().get(
            organization_id=organization_id,
            edition_id=edition_id,
            status="active",
        )
        product = (
            AdmissionProduct.objects.select_for_update()
            .select_related("configuration")
            .get(id=product_id, configuration=configuration)
        )
        control = _lock_control(configuration)
        operation = RegistrationCommerceCommandReceipt.Operation.WAITLIST_BATCH_OFFERED
        receipt = _existing_receipt(
            control=control,
            actor=actor,
            idempotency_key=idempotency_key,
            operation=operation,
            request_digest=digest,
        )
        if receipt is not None:
            batch = WaitlistBatchOffer.objects.get(
                id=receipt.result_id,
                control=control,
                configuration=configuration,
                product=product,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            registration_ids = tuple(
                RegistrationTimelineEntry.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    registration__configuration=configuration,
                    correlation_id=receipt.idempotency_key,
                    kind="waitlist_place_offered",
                    actor_kind="account",
                    actor_id=actor.id,
                ).values_list("registration_id", flat=True)
            )
            return WaitlistBatchCommandResult(
                batch=batch,
                offered_registration_ids=registration_ids,
                control_version=int(receipt.resulting_version),
                replayed=True,
            )
        if control.aggregate_version != expected_control_version:
            raise ValidationError(
                "Registration commerce settings changed; reload the waitlist.",
                code="registration_commerce_version_conflict",
            )
        if (
            not configuration.waitlist_enabled
            or not product.waitlist_enabled
            or offered_at >= configuration.closes_at
            or (
                product.sales_close_at is not None
                and offered_at >= product.sales_close_at
            )
        ):
            raise ValidationError(
                "This product's waitlist is not open for offers.",
                code="waitlist_offers_closed",
            )
        occupied = _occupied_registrations(configuration)
        overall_slots = max(
            effective_configuration_capacity(configuration) - occupied.count(),
            0,
        )
        product_slots = max(
            effective_product_capacity(product)
            - occupied.filter(product=product).count()
            - pending_target_capacity_holds(product, at=offered_at),
            0,
        )
        offer_count = min(batch_size, overall_slots, product_slots)
        registrations = tuple(
            Registration.objects.select_for_update()
            .select_related("product", "configuration")
            .filter(
                product=product,
                state=Registration.State.WAITLISTED,
                account__is_active=True,
            )
            .order_by("waitlisted_at", "submitted_at", "id")[:offer_count]
        )
        command_correlation_id = idempotency_key
        for registration in registrations:
            _offer_waitlisted_registration(
                registration=registration,
                actor=actor,
                offered_at=offered_at,
                reason=normalized_reason,
                correlation_id=command_correlation_id,
                source_channel=source_channel,
            )
        previous_control_version = int(control.aggregate_version)
        result_version = _advance_control(control)
        batch = WaitlistBatchOffer.objects.create(
            control=control,
            configuration=configuration,
            product=product,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_size=batch_size,
            offered_count=len(registrations),
            control_version=result_version,
            actor=actor,
            reason=normalized_reason,
            occurred_at=offered_at,
        )
        audit = append_audit(
            _audit_record(
                actor=actor,
                capability_code=MANAGE_EXCEPTIONS,
                operation="registration.waitlist.batch_offer",
                organization_id=organization_id,
                edition_id=edition_id,
                target_type="registration.waitlist_batch",
                target_id=batch.id,
                correlation_id=correlation_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="strict_fifo_waitlist_batch_offered",
                obligations=obligations,
                changed_fields=("registrations", "batch_evidence"),
                source_channel=source_channel,
                target_count=len(registrations),
            )
        )
        _publish_commerce_event(
            event_name="registration.waitlist.batch_offered.v1",
            organization_id=organization_id,
            edition_id=edition_id,
            aggregate_type="registration.commerce_control",
            aggregate_id=control.id,
            aggregate_version=result_version,
            payload={
                "product_id": str(product.id),
                "requested_size": str(batch_size),
                "offered_count": str(len(registrations)),
            },
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=actor.id,
        )
        RegistrationCommerceCommandReceipt.objects.create(
            control=control,
            actor=actor,
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=digest,
            expected_version=previous_control_version,
            resulting_version=result_version,
            result_id=batch.id,
            result_count=len(registrations),
        )
        return WaitlistBatchCommandResult(
            batch=batch,
            offered_registration_ids=tuple(item.id for item in registrations),
            control_version=result_version,
            replayed=False,
        )


def complete_admission_tier_replacement(
    *,
    replacement_id: UUID,
    correlation_id: UUID,
    completed_at: datetime,
) -> AdmissionTierReplacement:
    """Atomically replace the product after verified price-difference payment.

    Parameters
    ----------
    replacement_id : UUID
        The replacement identifier within the requested scope.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    completed_at : datetime
        The timezone-aware timestamp for completed.

    Returns
    -------
    AdmissionTierReplacement
        The AdmissionTierReplacement produced by complete admission tier
        replacement.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    from maru.registration.services import (  # noqa: PLC0415
        _append_timeline,
        _system_audit,
    )

    replacement = (
        AdmissionTierReplacement.objects.select_for_update()
        .select_related("registration", "source_product", "target_product")
        .get(id=replacement_id)
    )
    if replacement.status != AdmissionTierReplacement.Status.PAYMENT_PENDING:
        raise ValidationError(
            "The admission upgrade is no longer awaiting payment.",
            code="tier_replacement_not_pending",
        )
    if completed_at >= replacement.payment_due_at:
        raise ValidationError(
            "The admission upgrade payment arrived after its capacity hold expired.",
            code="tier_replacement_payment_late",
        )
    registration = (
        Registration.objects.select_for_update()
        .select_related("product")
        .get(id=replacement.registration_id)
    )
    if (
        registration.product_id != replacement.source_product_id
        or registration.state
        not in {Registration.State.CONFIRMED, Registration.State.CHECKED_IN}
    ):
        raise ValidationError(
            "The source admission changed before the upgrade completed.",
            code="tier_replacement_source_changed",
        )
    active_entitlements = list(
        Entitlement.objects.select_for_update().filter(
            registration=registration,
            status=Entitlement.Status.ACTIVE,
        )
    )
    source_entitlement = next(
        (
            entitlement
            for entitlement in active_entitlements
            if entitlement.code == replacement.source_entitlement_code
        ),
        None,
    )
    if source_entitlement is None:
        raise ValidationError(
            "The paid source admission entitlement is unavailable.",
            code="tier_replacement_source_entitlement_missing",
        )
    registration.product = replacement.target_product
    registration.product_name_snapshot = replacement.target_product_name_snapshot
    registration.price_minor_snapshot = replacement.target_price_minor_snapshot
    registration.aggregate_version += 1
    registration.save(
        update_fields=(
            "product",
            "product_name_snapshot",
            "price_minor_snapshot",
            "aggregate_version",
            "updated_at",
        )
    )
    if replacement.target_entitlement_code != source_entitlement.code:
        source_entitlement.status = Entitlement.Status.REVOKED
        source_entitlement.save(update_fields=("status", "updated_at"))
        Entitlement.objects.create(
            registration=registration,
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
            code=replacement.target_entitlement_code,
            label_snapshot=replacement.target_entitlement_name_snapshot,
            granted_at=completed_at,
        )
    replacement.status = AdmissionTierReplacement.Status.COMPLETED
    replacement.aggregate_version += 1
    replacement.resulting_registration_version = registration.aggregate_version
    replacement.completed_at = completed_at
    replacement.save(
        update_fields=(
            "status",
            "aggregate_version",
            "resulting_registration_version",
            "completed_at",
            "updated_at",
        )
    )
    _append_timeline(
        registration=registration,
        kind="admission_tier_replacement_completed",
        title="Admission upgraded",
        summary=(
            f"Payment for the price difference was confirmed. "
            f"{replacement.target_product_name_snapshot} is now active."
        ),
        occurred_at=completed_at,
        actor_kind="provider",
        actor_id=None,
        correlation_id=correlation_id,
    )
    audit = _system_audit(
        registration=registration,
        operation="registration.admission_tier_replacement.complete",
        reason_code="tier_replacement_payment_reconciled",
        correlation_id=correlation_id,
        changed_fields=(
            "product",
            "product_name_snapshot",
            "price_minor_snapshot",
            "entitlement",
            "tier_replacement",
            "timeline",
        ),
    )
    _publish_commerce_event(
        event_name="registration.admission_tier_replacement.completed.v1",
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        aggregate_type="registration.admission_tier_replacement",
        aggregate_id=replacement.id,
        aggregate_version=replacement.aggregate_version,
        payload={
            "registration_id": str(registration.id),
            "target_product_id": str(replacement.target_product_id),
            "status": replacement.status,
        },
        correlation_id=correlation_id,
        causation_id=audit.id,
        actor_kind="provider",
        actor_id=None,
    )
    return replacement


def expire_admission_tier_replacements(
    *,
    edition_id: UUID | None = None,
    now: datetime | None = None,
) -> int:
    """Release expired target holds while retaining every source admission.

    Parameters
    ----------
    edition_id : UUID | None, default=None
        The event edition identifier that scopes the operation.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    int
        The resolved int for expire admission tier replacements.
    """
    from maru.registration.services import (  # noqa: PLC0415
        _append_timeline,
        _system_audit,
    )

    expired_at = now or timezone.now()
    candidates = AdmissionTierReplacement.objects.filter(
        status=AdmissionTierReplacement.Status.PAYMENT_PENDING,
        payment_due_at__lte=expired_at,
    )
    if edition_id is not None:
        candidates = candidates.filter(edition_id=edition_id)
    candidate_ids = list(
        candidates.order_by("payment_due_at", "id").values_list("id", flat=True)
    )
    expired_count = 0
    for replacement_id in candidate_ids:
        with transaction.atomic():
            replacement = (
                AdmissionTierReplacement.objects.select_for_update()
                .select_related("registration")
                .filter(
                    id=replacement_id,
                    status=AdmissionTierReplacement.Status.PAYMENT_PENDING,
                    payment_due_at__lte=expired_at,
                )
                .first()
            )
            if replacement is None:
                continue
            replacement.status = AdmissionTierReplacement.Status.EXPIRED
            replacement.aggregate_version += 1
            replacement.expired_at = expired_at
            replacement.save(
                update_fields=(
                    "status",
                    "aggregate_version",
                    "expired_at",
                    "updated_at",
                )
            )
            registration = replacement.registration
            correlation_id = replacement.id
            _append_timeline(
                registration=registration,
                kind="admission_tier_replacement_expired",
                title="Admission upgrade hold expired",
                summary=(
                    "The higher-tier capacity hold was released. Your existing "
                    "admission and entitlement remain active."
                ),
                occurred_at=expired_at,
                actor_kind="workload",
                actor_id=None,
                correlation_id=correlation_id,
            )
            audit = _system_audit(
                registration=registration,
                operation="registration.admission_tier_replacement.expire",
                reason_code="tier_replacement_payment_deadline_passed",
                correlation_id=correlation_id,
                changed_fields=("target_capacity_hold", "tier_replacement", "timeline"),
            )
            _publish_commerce_event(
                event_name="registration.admission_tier_replacement.expired.v1",
                organization_id=registration.organization_id,
                edition_id=registration.edition_id,
                aggregate_type="registration.admission_tier_replacement",
                aggregate_id=replacement.id,
                aggregate_version=replacement.aggregate_version,
                payload={
                    "registration_id": str(registration.id),
                    "target_product_id": str(replacement.target_product_id),
                    "status": replacement.status,
                },
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor_kind="workload",
                actor_id=None,
            )
            expired_count += 1
    return expired_count


def registration_commerce_activity(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
    correlation_id: UUID,
    source_channel: str = "api",
    limit: int = 50,
) -> tuple[RegistrationCommerceActivity, ...]:
    """Return an allowlisted operational projection, never the security audit log.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    actor : Account
        The authenticated account authorizing the operation.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    source_channel : str, default='api'
        The closed channel code identifying where the request originated.
    limit : int, default=50
        The maximum number of records to return.

    Returns
    -------
    tuple[RegistrationCommerceActivity, ...]
        The matching registration commerce activity records in deterministic
        order.
    """
    from maru.registration.services import (  # noqa: PLC0415
        _audit_record,
        _require_decision,
    )

    obligations = _require_decision(
        actor=actor,
        capability_code=MANAGE_EXCEPTIONS,
        target=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        operation="registration.commerce_activity.list",
        target_type="registration.commerce_activity",
        target_id=edition_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    bounded_limit = min(max(int(limit), 1), MAX_COMMERCE_ACTIVITY_ITEMS)
    events = tuple(
        DomainEvent.objects.filter(
            organization_id=organization_id,
            event_edition_id=edition_id,
            event_name__in=_ACTIVITY_LABELS,
        ).order_by("-occurred_at", "-id")[:bounded_limit]
    )
    append_audit(
        _audit_record(
            actor=actor,
            capability_code=MANAGE_EXCEPTIONS,
            operation="registration.commerce_activity.list",
            organization_id=organization_id,
            edition_id=edition_id,
            target_type="registration.commerce_activity",
            target_id=edition_id,
            correlation_id=correlation_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="purpose_scoped_registration_activity",
            obligations=obligations,
            source_channel=source_channel,
            target_count=len(events),
        )
    )
    labels = account_display_labels(
        {event.actor_id for event in events if event.actor_id is not None}
    )
    return tuple(
        RegistrationCommerceActivity(
            event_name=event.event_name,
            action=_ACTIVITY_LABELS[event.event_name],
            actor_label=(
                labels.get(event.actor_id, "Maru account")
                if event.actor_id is not None
                else "Maru automation"
            ),
            occurred_at=event.occurred_at,
            target_count=int(
                str(
                    event.payload.get(
                        "offered_count",
                        "1",
                    )
                )
            ),
        )
        for event in events
    )
