"""Closed idempotent commands for venue catalogs and operational scheduling."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from itertools import pairwise
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from psycopg.types.range import Range

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
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import Department

from .authorization import resolve_edition_space_target
from .bindings import ensure_edition_space_binding
from .inputs import (
    canonical_digest,
    normalized_reason,
    normalized_slug,
    normalized_source_channel,
    normalized_text,
)
from .models import (
    AccommodationNightInventory,
    AccommodationRoomType,
    EditionSpaceAvailabilityWindow,
    EditionSpaceMember,
    EditionSpaceSelection,
    EditionVenueSelection,
    VenueBooking,
    VenueBookingHistory,
    VenueBookingOccupancy,
    VenueBuilding,
    VenueCommandReceipt,
    VenueLayoutVersion,
    VenueProperty,
    VenuePropertyMedia,
    VenueSite,
    VenueSpace,
    VenueSpaceCombination,
    VenueSpaceCombinationMember,
    VenueSpaceConfiguration,
)
from .writer_boundary import venue_writer

PROPERTY_VIEW_CAPABILITY = "venues.view_properties"
PROPERTY_MANAGE_CAPABILITY = "venues.manage_properties"
ACCOMMODATION_MANAGE_CAPABILITY = "venues.manage_accommodation"
WORKSPACE_VIEW_CAPABILITY = "venues.view_workspace"
EDITION_SELECT_CAPABILITY = "venues.select_for_edition"
SPACE_VIEW_CAPABILITY = "venues.view_space_schedule"
SPACE_MANAGE_CAPABILITY = "venues.manage_space_schedule"
SPACE_PUBLISH_CAPABILITY = "venues.publish_space_schedule"
MINIMUM_COMBINATION_MEMBERS = 2
MAXIMUM_AVAILABILITY_WINDOWS = 256


class VenueCommandError(RuntimeError):
    reason_code = "venue_command_failed"


class VenueAuthorizationDeniedError(VenueCommandError):
    reason_code = "venue_authorization_denied"


class VenueResourceUnavailableError(VenueCommandError):
    reason_code = "venue_resource_unavailable"


class VenueVersionConflictError(VenueCommandError):
    reason_code = "venue_version_conflict"


class VenueRetryConflictError(VenueCommandError):
    reason_code = "venue_retry_conflict"


class VenueStateConflictError(VenueCommandError):
    reason_code = "venue_state_conflict"


class VenueAvailabilityConflictError(VenueCommandError):
    reason_code = "venue_hard_availability_conflict"


class VenueCapacityConflictError(VenueCommandError):
    reason_code = "venue_capacity_conflict"


class VenueBookingOverlapError(VenueCommandError):
    reason_code = "venue_booking_overlap"


class VenueIndependentApprovalError(VenueCommandError):
    reason_code = "venue_independent_approval_required"


@dataclass(frozen=True, slots=True)
class VenueCommandResult:
    object_id: UUID
    receipt_id: UUID
    resulting_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class VenuePropertyProfile:
    kind: str
    legal_name: str
    public_name: str
    provider_name: str = ""
    public_description: str = ""
    internal_notes: str = ""
    location_name: str = ""
    postal_address: str = ""
    country_code: str = ""
    website_url: str = ""
    public_contact: str = ""
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""


@dataclass(frozen=True, slots=True)
class VenueSpaceCatalogInput:
    site_code: str
    site_name: str
    building_code: str
    building_name: str
    space_code: str
    space_name: str
    space_kind: str
    configuration_code: str
    configuration_name: str
    seated_capacity: int
    standing_capacity: int
    table_capacity: int
    fire_capacity: int
    public_description: str = ""
    accessibility_features: str = ""
    known_barriers: str = ""
    equipment_facts: str = ""


@dataclass(frozen=True, slots=True)
class VenueCapacityProfile:
    configuration_name: str
    seated_capacity: int
    standing_capacity: int
    table_capacity: int
    fire_capacity: int


@dataclass(frozen=True, slots=True)
class VenueAvailabilityInterval:
    starts_at: datetime
    ends_at: datetime
    opening_restriction: str = ""


@dataclass(frozen=True, slots=True)
class VenueBookingEnvelope:
    setup_starts_at: datetime
    effective_starts_at: datetime
    effective_ends_at: datetime
    teardown_ends_at: datetime


@dataclass(frozen=True, slots=True)
class _AuthorizedSpace:
    space_selection_id: UUID
    department_id: UUID
    target: ResolvedAuthorizationTarget
    decision: PolicyDecision


_PROPERTY_PROFILE_LIMITS: dict[str, int] = {
    "legal_name": 240,
    "public_name": 200,
    "provider_name": 240,
    "public_description": 5_000,
    "internal_notes": 5_000,
    "location_name": 240,
    "postal_address": 1_000,
    "country_code": 2,
    "website_url": 2_000,
    "public_contact": 240,
    "contact_name": 240,
    "contact_email": 254,
    "contact_phone": 16,
}


def _require_uuid(value: UUID, *, field: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValidationError({field: "Enter a valid UUID."})
    return value


def _require_expected_version(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValidationError({"expected_version": "Enter a positive version."})
    return value


def _validate_command_ids(
    *, idempotency_key: UUID, correlation_id: UUID
) -> tuple[UUID, UUID]:
    return (
        _require_uuid(idempotency_key, field="idempotency_key"),
        _require_uuid(correlation_id, field="correlation_id"),
    )


def _normalize_profile(profile: VenuePropertyProfile) -> dict[str, str]:
    if profile.kind not in VenueProperty.Kind.values:
        raise ValidationError({"kind": "Select a supported property kind."})
    values = {"kind": profile.kind}
    for field_name, maximum in _PROPERTY_PROFILE_LIMITS.items():
        values[field_name] = normalized_text(
            getattr(profile, field_name),
            field=field_name,
            maximum=maximum,
            required=field_name
            in {
                "legal_name",
                "public_name",
                "location_name",
                "postal_address",
                "country_code",
            },
            collapse=field_name
            not in {"public_description", "internal_notes", "postal_address"},
        )
    values["country_code"] = values["country_code"].upper()
    return values


def _require_actor(actor: Account) -> None:
    if actor.pk is None or not actor.is_active:
        raise VenueAuthorizationDeniedError()


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
        raise VenueAuthorizationDeniedError()
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


def _space_decision(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    capability_code: str,
    at: datetime,
) -> _AuthorizedSpace:
    row = (
        EditionSpaceSelection.objects.filter(
            id=space_selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .order_by()
        .values("id", "responsible_department_id")
        .first()
    )
    if row is None:
        raise VenueAuthorizationDeniedError()
    target = resolve_edition_space_target(
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
    )
    decision = _require_decision(
        actor=actor,
        capability_code=capability_code,
        target=target,
        at=at,
    )
    if target is None:
        raise VenueAuthorizationDeniedError()
    return _AuthorizedSpace(
        space_selection_id=row["id"],
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
) -> VenueCommandReceipt | None:
    receipt = (
        VenueCommandReceipt.objects.select_for_update()
        .filter(actor=actor, operation=operation, idempotency_key=idempotency_key)
        .first()
    )
    if receipt is None:
        return None
    if (
        receipt.organization_id != organization_id
        or receipt.request_digest != request_digest
    ):
        raise VenueRetryConflictError()
    return receipt


def _replayed_result(receipt: VenueCommandReceipt) -> VenueCommandResult:
    return VenueCommandResult(
        object_id=receipt.result_object_id,
        receipt_id=receipt.id,
        resulting_version=receipt.resulting_version,
        replayed=True,
    )


def _result(
    *, object_id: UUID, receipt: VenueCommandReceipt, resulting_version: int
) -> VenueCommandResult:
    return VenueCommandResult(
        object_id=object_id,
        receipt_id=receipt.id,
        resulting_version=resulting_version,
        replayed=False,
    )


def _append_evidence(
    *,
    actor: Account,
    organization: Organization,
    edition: EventEdition | None,
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
    action: str,
    occurred_at: datetime,
) -> VenueCommandReceipt:
    with venue_writer():
        receipt = VenueCommandReceipt.objects.create(
            organization=organization,
            edition=edition,
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
            operation=f"venues.{operation}",
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
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="venue-operational",
        ),
        occurred_at=occurred_at,
    )
    publish_domain_event(
        DomainEventRecord(
            event_name="venues.record.changed.v1",
            schema_version=1,
            organization_id=organization.id,
            event_edition_id=edition.id if edition else None,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=resulting_version,
            payload={
                "action": action,
                "record_type": aggregate_type,
                "record_id": str(aggregate_id),
            },
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="venue-operational",
        ),
        occurred_at=occurred_at,
    )
    return receipt


@transaction.atomic
def create_venue_property(
    *,
    actor: Account,
    organization_id: UUID,
    slug: str,
    profile: VenuePropertyProfile,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
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
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.PROPERTY_CREATE,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    organization = (
        Organization.objects.select_for_update().filter(id=organization_id).first()
    )
    if organization is None:
        raise VenueResourceUnavailableError()
    with venue_writer():
        property_record = VenueProperty.objects.create(
            organization=organization,
            slug=slug,
            lifecycle=VenueProperty.Lifecycle.DRAFT,
            aggregate_version=1,
            created_by=actor,
            last_modified_by=actor,
            **values,
        )
    receipt = _append_evidence(
        actor=actor,
        organization=organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.PROPERTY_CREATE,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=property_record.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("created",),
        aggregate_type="venues.property",
        aggregate_id=property_record.id,
        action="created",
        occurred_at=evaluated_at,
    )
    return _result(object_id=property_record.id, receipt=receipt, resulting_version=1)


@transaction.atomic
def update_venue_property(
    *,
    actor: Account,
    organization_id: UUID,
    property_id: UUID,
    expected_version: int,
    changes: Mapping[str, str],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    allowed = set(_PROPERTY_PROFILE_LIMITS) | {"lifecycle"}
    if not changes or not set(changes) <= allowed:
        raise ValidationError({"changes": "Provide supported property changes."})
    normalized: dict[str, str] = {}
    for field_name, value in changes.items():
        if field_name == "lifecycle":
            if value not in VenueProperty.Lifecycle.values:
                raise ValidationError({"lifecycle": "Select a valid lifecycle."})
            normalized[field_name] = value
        else:
            normalized[field_name] = normalized_text(
                value,
                field=field_name,
                maximum=_PROPERTY_PROFILE_LIMITS[field_name],
                required=field_name
                in {
                    "legal_name",
                    "public_name",
                    "location_name",
                    "postal_address",
                    "country_code",
                },
                collapse=field_name
                not in {"public_description", "internal_notes", "postal_address"},
            )
    if "country_code" in normalized:
        normalized["country_code"] = normalized["country_code"].upper()
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "property_id": property_id,
            "expected_version": expected_version,
            "changes": normalized,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.CATALOG_ADD,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    property_record = (
        VenueProperty.objects.select_for_update()
        .select_related("organization")
        .filter(id=property_id, organization_id=organization_id)
        .first()
    )
    if property_record is None:
        raise VenueResourceUnavailableError()
    if property_record.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if property_record.lifecycle == VenueProperty.Lifecycle.RETIRED:
        raise VenueStateConflictError()
    actual = {
        field_name: value
        for field_name, value in normalized.items()
        if getattr(property_record, field_name) != value
    }
    if not actual:
        raise ValidationError({"changes": "Change at least one property value."})
    for field_name, value in actual.items():
        setattr(property_record, field_name, value)
    property_record.aggregate_version += 1
    property_record.last_modified_by = actor
    with venue_writer():
        property_record.save()
    receipt = _append_evidence(
        actor=actor,
        organization=property_record.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.CATALOG_ADD,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=property_record.id,
        resulting_version=property_record.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=tuple(actual),
        aggregate_type="venues.property",
        aggregate_id=property_record.id,
        action="updated",
        occurred_at=evaluated_at,
    )
    return _result(
        object_id=property_record.id,
        receipt=receipt,
        resulting_version=property_record.aggregate_version,
    )


@transaction.atomic
def create_venue_space_catalog_path(
    *,
    actor: Account,
    organization_id: UUID,
    property_id: UUID,
    catalog: VenueSpaceCatalogInput,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    if catalog.space_kind not in VenueSpace.Kind.values:
        raise ValidationError({"space_kind": "Select a supported space kind."})
    capacities = (
        catalog.seated_capacity,
        catalog.standing_capacity,
        catalog.table_capacity,
        catalog.fire_capacity,
    )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in capacities
    ):
        raise ValidationError({"capacity": "Capacities must be non-negative integers."})
    if catalog.fire_capacity < 1:
        raise ValidationError({"fire_capacity": "Enter a positive fire capacity."})
    normalized_catalog = {
        "site_code": normalized_slug(catalog.site_code),
        "site_name": normalized_text(
            catalog.site_name,
            field="site_name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "building_code": normalized_slug(catalog.building_code),
        "building_name": normalized_text(
            catalog.building_name,
            field="building_name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "space_code": normalized_slug(catalog.space_code),
        "space_name": normalized_text(
            catalog.space_name,
            field="space_name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "space_kind": catalog.space_kind,
        "configuration_code": normalized_slug(catalog.configuration_code),
        "configuration_name": normalized_text(
            catalog.configuration_name,
            field="configuration_name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "public_description": normalized_text(
            catalog.public_description, field="public_description", maximum=2_000
        ),
        "accessibility_features": normalized_text(
            catalog.accessibility_features,
            field="accessibility_features",
            maximum=2_000,
        ),
        "known_barriers": normalized_text(
            catalog.known_barriers, field="known_barriers", maximum=2_000
        ),
        "equipment_facts": normalized_text(
            catalog.equipment_facts, field="equipment_facts", maximum=2_000
        ),
    }
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "property_id": property_id,
            "catalog": {**normalized_catalog, "capacities": capacities},
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.CATALOG_ADD,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    property_record = (
        VenueProperty.objects.select_for_update()
        .select_related("organization")
        .filter(id=property_id, organization_id=organization_id)
        .first()
    )
    if (
        property_record is None
        or property_record.lifecycle == VenueProperty.Lifecycle.RETIRED
    ):
        raise VenueResourceUnavailableError()
    with venue_writer():
        site = VenueSite.objects.create(
            organization=property_record.organization,
            property=property_record,
            code=normalized_catalog["site_code"],
            name=normalized_catalog["site_name"],
            access_facts=normalized_catalog["accessibility_features"],
        )
        building = VenueBuilding.objects.create(
            organization=property_record.organization,
            property=property_record,
            site=site,
            code=normalized_catalog["building_code"],
            name=normalized_catalog["building_name"],
            access_facts=normalized_catalog["accessibility_features"],
        )
        space = VenueSpace.objects.create(
            organization=property_record.organization,
            property=property_record,
            site=site,
            building=building,
            code=normalized_catalog["space_code"],
            name=normalized_catalog["space_name"],
            kind=normalized_catalog["space_kind"],
            public_description=normalized_catalog["public_description"],
            accessibility_features=normalized_catalog["accessibility_features"],
            known_barriers=normalized_catalog["known_barriers"],
            equipment_facts=normalized_catalog["equipment_facts"],
        )
        VenueSpaceConfiguration.objects.create(
            organization=property_record.organization,
            space=space,
            code=normalized_catalog["configuration_code"],
            version=1,
            name=normalized_catalog["configuration_name"],
            seated_capacity=catalog.seated_capacity,
            standing_capacity=catalog.standing_capacity,
            table_capacity=catalog.table_capacity,
            fire_capacity=catalog.fire_capacity,
            accessibility_features=normalized_catalog["accessibility_features"],
            equipment_facts=normalized_catalog["equipment_facts"],
            lifecycle=VenueSpaceConfiguration.Lifecycle.ACTIVE,
        )
    receipt = _append_evidence(
        actor=actor,
        organization=property_record.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.CATALOG_ADD,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=space.id,
        resulting_version=space.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("site", "building", "space", "configuration"),
        aggregate_type="venues.space",
        aggregate_id=space.id,
        action="catalog_path_created",
        occurred_at=evaluated_at,
    )
    return _result(object_id=space.id, receipt=receipt, resulting_version=1)


@transaction.atomic
def create_venue_space_combination(
    *,
    actor: Account,
    organization_id: UUID,
    property_id: UUID,
    code: str,
    name: str,
    member_space_ids: Sequence[UUID],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    code = normalized_slug(code, fallback=name)
    name = normalized_text(
        name,
        field="name",
        maximum=200,
        required=True,
        collapse=True,
    )
    member_ids = tuple(sorted(set(member_space_ids), key=str))
    if len(member_ids) < MINIMUM_COMBINATION_MEMBERS or any(
        not isinstance(value, UUID) for value in member_ids
    ):
        raise ValidationError(
            {"member_space_ids": "Select at least two distinct physical spaces."}
        )
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "property_id": property_id,
            "code": code,
            "name": name,
            "member_space_ids": member_ids,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.CATALOG_ADD,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    property_record = (
        VenueProperty.objects.select_for_update()
        .select_related("organization")
        .filter(
            id=property_id,
            organization_id=organization_id,
            lifecycle=VenueProperty.Lifecycle.ACTIVE,
        )
        .first()
    )
    if property_record is None:
        raise VenueResourceUnavailableError()
    spaces = tuple(
        VenueSpace.objects.select_for_update()
        .filter(
            id__in=member_ids,
            organization_id=organization_id,
            property_id=property_id,
            is_active=True,
        )
        .order_by("id")
    )
    if len(spaces) != len(member_ids):
        raise VenueResourceUnavailableError()
    with venue_writer():
        combination = VenueSpaceCombination.objects.create(
            organization=property_record.organization,
            property=property_record,
            code=code,
            name=name,
        )
        VenueSpaceCombinationMember.objects.bulk_create(
            [
                VenueSpaceCombinationMember(
                    organization=property_record.organization,
                    combination=combination,
                    space=space,
                )
                for space in spaces
            ]
        )
    receipt = _append_evidence(
        actor=actor,
        organization=property_record.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.CATALOG_ADD,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=combination.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("combination", "members"),
        aggregate_type="venues.space_combination",
        aggregate_id=combination.id,
        action="created",
        occurred_at=evaluated_at,
    )
    return _result(object_id=combination.id, receipt=receipt, resulting_version=1)


@transaction.atomic
def add_venue_property_media(
    *,
    actor: Account,
    organization_id: UUID,
    property_id: UUID,
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
) -> VenueCommandResult:
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    if kind not in VenuePropertyMedia.Kind.values:
        raise ValidationError({"kind": "Select a supported media kind."})
    values = {
        "source_reference": normalized_text(
            source_reference,
            field="source_reference",
            maximum=1_000,
            required=True,
        ),
        "owner_name": normalized_text(
            owner_name, field="owner_name", maximum=240, required=True, collapse=True
        ),
        "license_basis": normalized_text(
            license_basis, field="license_basis", maximum=500, required=True
        ),
        "usage_scope": normalized_text(
            usage_scope, field="usage_scope", maximum=500, required=True
        ),
        "attribution": normalized_text(attribution, field="attribution", maximum=500),
    }
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "property_id": property_id,
            "kind": kind,
            "values": values,
            "expires_at": expires_at,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.MEDIA_ADD,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    property_record = (
        VenueProperty.objects.select_for_update()
        .select_related("organization")
        .filter(id=property_id, organization_id=organization_id)
        .exclude(lifecycle=VenueProperty.Lifecycle.RETIRED)
        .first()
    )
    if property_record is None:
        raise VenueResourceUnavailableError()
    with venue_writer():
        media = VenuePropertyMedia.objects.create(
            organization=property_record.organization,
            property=property_record,
            kind=kind,
            expires_at=expires_at,
            submitted_by=actor,
            **values,
        )
    receipt = _append_evidence(
        actor=actor,
        organization=property_record.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.MEDIA_ADD,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=media.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("media",),
        aggregate_type="venues.property_media",
        aggregate_id=media.id,
        action="submitted",
        occurred_at=evaluated_at,
    )
    return _result(object_id=media.id, receipt=receipt, resulting_version=1)


@transaction.atomic
def approve_venue_property_media(
    *,
    actor: Account,
    organization_id: UUID,
    property_id: UUID,
    media_id: UUID,
    expected_version: int,
    public_reference: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    public_reference = normalized_text(
        public_reference,
        field="public_reference",
        maximum=1_000,
        required=True,
    )
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "property_id": property_id,
            "media_id": media_id,
            "expected_version": expected_version,
            "public_reference": public_reference,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.MEDIA_REVIEW,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    media = (
        VenuePropertyMedia.objects.select_for_update()
        .select_related("organization")
        .filter(
            id=media_id,
            property_id=property_id,
            organization_id=organization_id,
        )
        .first()
    )
    if media is None:
        raise VenueResourceUnavailableError()
    if media.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if media.review_status != VenuePropertyMedia.ReviewStatus.PENDING:
        raise VenueStateConflictError()
    if media.submitted_by_id == actor.id:
        raise VenueIndependentApprovalError()
    media.public_reference = public_reference
    media.review_status = VenuePropertyMedia.ReviewStatus.APPROVED
    media.reviewed_by = actor
    media.reviewed_at = evaluated_at
    media.aggregate_version += 1
    with venue_writer():
        media.save()
    receipt = _append_evidence(
        actor=actor,
        organization=media.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.MEDIA_REVIEW,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=media.id,
        resulting_version=media.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("public_reference", "review_status"),
        aggregate_type="venues.property_media",
        aggregate_id=media.id,
        action="approved",
        occurred_at=evaluated_at,
    )
    return _result(
        object_id=media.id,
        receipt=receipt,
        resulting_version=media.aggregate_version,
    )


@transaction.atomic
def add_venue_layout_version(
    *,
    actor: Account,
    organization_id: UUID,
    space_id: UUID,
    layout_code: str,
    version: int,
    title: str,
    visibility: str,
    source_reference: str,
    checksum_sha256: str,
    notes: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    if visibility not in VenueLayoutVersion.Visibility.values:
        raise ValidationError({"visibility": "Select a supported layout audience."})
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValidationError({"version": "Enter a positive layout version."})
    layout_code = normalized_slug(layout_code, fallback=title)
    values = {
        "title": normalized_text(
            title, field="title", maximum=200, required=True, collapse=True
        ),
        "source_reference": normalized_text(
            source_reference,
            field="source_reference",
            maximum=1_000,
            required=True,
        ),
        "checksum_sha256": normalized_text(
            checksum_sha256,
            field="checksum_sha256",
            maximum=64,
            required=True,
            collapse=True,
        ).lower(),
        "notes": normalized_text(notes, field="notes", maximum=2_000),
    }
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "space_id": space_id,
            "layout_code": layout_code,
            "version": version,
            "visibility": visibility,
            "values": values,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.LAYOUT_ADD,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    space = (
        VenueSpace.objects.select_for_update()
        .select_related("organization")
        .filter(id=space_id, organization_id=organization_id, is_active=True)
        .first()
    )
    if space is None:
        raise VenueResourceUnavailableError()
    with venue_writer():
        layout = VenueLayoutVersion.objects.create(
            organization=space.organization,
            space=space,
            layout_code=layout_code,
            version=version,
            visibility=visibility,
            submitted_by=actor,
            **values,
        )
    receipt = _append_evidence(
        actor=actor,
        organization=space.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.LAYOUT_ADD,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=layout.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("layout_version",),
        aggregate_type="venues.layout",
        aggregate_id=layout.id,
        action="submitted",
        occurred_at=evaluated_at,
    )
    return _result(object_id=layout.id, receipt=receipt, resulting_version=1)


@transaction.atomic
def approve_venue_layout_version(
    *,
    actor: Account,
    organization_id: UUID,
    layout_id: UUID,
    expected_version: int,
    approved_reference: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    approved_reference = normalized_text(
        approved_reference,
        field="approved_reference",
        maximum=1_000,
    )
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "layout_id": layout_id,
            "expected_version": expected_version,
            "approved_reference": approved_reference,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.LAYOUT_REVIEW,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    layout = (
        VenueLayoutVersion.objects.select_for_update()
        .select_related("organization")
        .filter(id=layout_id, organization_id=organization_id)
        .first()
    )
    if layout is None:
        raise VenueResourceUnavailableError()
    if layout.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if layout.review_status != VenueLayoutVersion.ReviewStatus.PENDING:
        raise VenueStateConflictError()
    if layout.submitted_by_id == actor.id:
        raise VenueIndependentApprovalError()
    if (
        layout.visibility == VenueLayoutVersion.Visibility.PUBLIC
        and not approved_reference
    ):
        raise ValidationError(
            {"approved_reference": "Approve one public-safe rendition reference."}
        )
    layout.approved_reference = approved_reference
    layout.review_status = VenueLayoutVersion.ReviewStatus.APPROVED
    layout.reviewed_by = actor
    layout.reviewed_at = evaluated_at
    layout.aggregate_version += 1
    with venue_writer():
        layout.save()
    receipt = _append_evidence(
        actor=actor,
        organization=layout.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.LAYOUT_REVIEW,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=layout.id,
        resulting_version=layout.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=PROPERTY_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("approved_reference", "review_status"),
        aggregate_type="venues.layout",
        aggregate_id=layout.id,
        action="approved",
        occurred_at=evaluated_at,
    )
    return _result(
        object_id=layout.id,
        receipt=receipt,
        resulting_version=layout.aggregate_version,
    )


@transaction.atomic
def create_accommodation_room_type(
    *,
    actor: Account,
    organization_id: UUID,
    property_id: UUID,
    code: str,
    public_name: str,
    description: str,
    accessible_features: str,
    minimum_occupants: int,
    maximum_occupants: int,
    provider_reference: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    code = normalized_slug(code, fallback=public_name)
    values = {
        "public_name": normalized_text(
            public_name,
            field="public_name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "description": normalized_text(description, field="description", maximum=2_000),
        "accessible_features": normalized_text(
            accessible_features,
            field="accessible_features",
            maximum=2_000,
        ),
        "provider_reference": normalized_text(
            provider_reference,
            field="provider_reference",
            maximum=240,
            collapse=True,
        ),
    }
    if (
        not isinstance(minimum_occupants, int)
        or not isinstance(maximum_occupants, int)
        or isinstance(minimum_occupants, bool)
        or isinstance(maximum_occupants, bool)
        or minimum_occupants < 1
        or maximum_occupants < minimum_occupants
    ):
        raise ValidationError({"occupants": "Enter a valid occupant range."})
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "property_id": property_id,
            "code": code,
            "values": values,
            "minimum_occupants": minimum_occupants,
            "maximum_occupants": maximum_occupants,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=ACCOMMODATION_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.CATALOG_ADD,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    property_record = (
        VenueProperty.objects.select_for_update()
        .select_related("organization")
        .filter(id=property_id, organization_id=organization_id)
        .exclude(kind=VenueProperty.Kind.VENUE)
        .exclude(lifecycle=VenueProperty.Lifecycle.RETIRED)
        .first()
    )
    if property_record is None:
        raise VenueResourceUnavailableError()
    with venue_writer():
        room_type = AccommodationRoomType.objects.create(
            organization=property_record.organization,
            property=property_record,
            code=code,
            minimum_occupants=minimum_occupants,
            maximum_occupants=maximum_occupants,
            **values,
        )
    receipt = _append_evidence(
        actor=actor,
        organization=property_record.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.CATALOG_ADD,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=room_type.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=ACCOMMODATION_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("room_type",),
        aggregate_type="venues.accommodation_room_type",
        aggregate_id=room_type.id,
        action="created",
        occurred_at=evaluated_at,
    )
    return _result(object_id=room_type.id, receipt=receipt, resulting_version=1)


@transaction.atomic
def set_accommodation_night_inventory(
    *,
    actor: Account,
    organization_id: UUID,
    room_type_id: UUID,
    night: date,
    room_capacity: int,
    release_at: datetime,
    provider_reference: str,
    expected_version: int | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    if expected_version is not None:
        expected_version = _require_expected_version(expected_version)
    if (
        not isinstance(room_capacity, int)
        or isinstance(room_capacity, bool)
        or room_capacity < 0
    ):
        raise ValidationError({"room_capacity": "Enter a non-negative room count."})
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    provider_reference = normalized_text(
        provider_reference,
        field="provider_reference",
        maximum=240,
        collapse=True,
    )
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "room_type_id": room_type_id,
            "night": night,
            "room_capacity": room_capacity,
            "release_at": release_at,
            "provider_reference": provider_reference,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _organization_decision(
        actor=actor,
        organization_id=organization_id,
        capability_code=ACCOMMODATION_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.ROOM_INVENTORY_SET,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    room_type = (
        AccommodationRoomType.objects.select_for_update()
        .select_related("organization")
        .filter(id=room_type_id, organization_id=organization_id, is_active=True)
        .first()
    )
    if room_type is None:
        raise VenueResourceUnavailableError()
    inventory = (
        AccommodationNightInventory.objects.select_for_update()
        .filter(room_type=room_type, night=night, organization_id=organization_id)
        .first()
    )
    with venue_writer():
        if inventory is None:
            if expected_version is not None:
                raise VenueVersionConflictError()
            inventory = AccommodationNightInventory.objects.create(
                organization=room_type.organization,
                room_type=room_type,
                night=night,
                room_capacity=room_capacity,
                release_at=release_at,
                provider_reference=provider_reference,
            )
        else:
            if inventory.aggregate_version != expected_version:
                raise VenueVersionConflictError()
            inventory.room_capacity = room_capacity
            inventory.release_at = release_at
            inventory.provider_reference = provider_reference
            inventory.aggregate_version += 1
            inventory.save()
    receipt = _append_evidence(
        actor=actor,
        organization=room_type.organization,
        edition=None,
        operation=VenueCommandReceipt.Operation.ROOM_INVENTORY_SET,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=inventory.id,
        resulting_version=inventory.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=ACCOMMODATION_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("night", "room_capacity", "release_at"),
        aggregate_type="venues.accommodation_night_inventory",
        aggregate_id=inventory.id,
        action="set",
        occurred_at=evaluated_at,
    )
    return _result(
        object_id=inventory.id,
        receipt=receipt,
        resulting_version=inventory.aggregate_version,
    )


def _normalized_capacity(profile: VenueCapacityProfile) -> VenueCapacityProfile:
    values = (
        profile.seated_capacity,
        profile.standing_capacity,
        profile.table_capacity,
        profile.fire_capacity,
    )
    if (
        any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in values
        )
        or profile.fire_capacity < 1
    ):
        raise ValidationError({"capacity": "Enter valid non-negative capacities."})
    return VenueCapacityProfile(
        configuration_name=normalized_text(
            profile.configuration_name,
            field="configuration_name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        seated_capacity=profile.seated_capacity,
        standing_capacity=profile.standing_capacity,
        table_capacity=profile.table_capacity,
        fire_capacity=profile.fire_capacity,
    )


@transaction.atomic
def select_venue_for_edition(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    property_id: UUID,
    responsible_department_id: UUID,
    local_name: str,
    public_description_override: str,
    public_contact_override: str,
    opening_restrictions: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    values = {
        "local_name": normalized_text(
            local_name,
            field="local_name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "public_description_override": normalized_text(
            public_description_override,
            field="public_description_override",
            maximum=2_000,
        ),
        "public_contact_override": normalized_text(
            public_contact_override,
            field="public_contact_override",
            maximum=240,
            collapse=True,
        ),
        "opening_restrictions": normalized_text(
            opening_restrictions,
            field="opening_restrictions",
            maximum=2_000,
        ),
    }
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "property_id": property_id,
            "responsible_department_id": responsible_department_id,
            "values": values,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=EDITION_SELECT_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.EDITION_SELECT,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    edition = (
        EventEdition.objects.select_for_update()
        .select_related("organization")
        .filter(id=edition_id, organization_id=organization_id)
        .first()
    )
    property_record = (
        VenueProperty.objects.select_for_update()
        .filter(
            id=property_id,
            organization_id=organization_id,
            lifecycle=VenueProperty.Lifecycle.ACTIVE,
        )
        .first()
    )
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
    if edition is None or property_record is None or department is None:
        raise VenueResourceUnavailableError()
    with venue_writer():
        selection = EditionVenueSelection.objects.create(
            organization=edition.organization,
            edition=edition,
            property=property_record,
            responsible_department=department,
            created_by=actor,
            last_modified_by=actor,
            **values,
        )
    receipt = _append_evidence(
        actor=actor,
        organization=edition.organization,
        edition=edition,
        operation=VenueCommandReceipt.Operation.EDITION_SELECT,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=selection.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=EDITION_SELECT_CAPABILITY,
        decision=decision,
        changed_fields=("property", "responsible_department", "overrides"),
        aggregate_type="venues.edition_selection",
        aggregate_id=selection.id,
        action="selected",
        occurred_at=evaluated_at,
    )
    return _result(object_id=selection.id, receipt=receipt, resulting_version=1)


@transaction.atomic
def select_space_for_edition(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    venue_selection_id: UUID,
    source_space_id: UUID | None,
    source_combination_id: UUID | None,
    selected_configuration_id: UUID | None,
    local_name: str,
    capacity: VenueCapacityProfile | None,
    public_access_info: str,
    opening_restrictions: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    if (source_space_id is None) == (source_combination_id is None):
        raise ValidationError(
            {"source": "Select exactly one physical space or combination."}
        )
    local_name = normalized_text(
        local_name,
        field="local_name",
        maximum=200,
        required=True,
        collapse=True,
    )
    public_access_info = normalized_text(
        public_access_info,
        field="public_access_info",
        maximum=2_000,
    )
    opening_restrictions = normalized_text(
        opening_restrictions,
        field="opening_restrictions",
        maximum=2_000,
    )
    if capacity is not None:
        capacity = _normalized_capacity(capacity)
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "venue_selection_id": venue_selection_id,
            "source_space_id": source_space_id,
            "source_combination_id": source_combination_id,
            "selected_configuration_id": selected_configuration_id,
            "local_name": local_name,
            "capacity": asdict(capacity) if capacity else None,
            "public_access_info": public_access_info,
            "opening_restrictions": opening_restrictions,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    decision = _edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=EDITION_SELECT_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.SPACE_SELECT,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    venue_selection = (
        EditionVenueSelection.objects.select_for_update()
        .select_related("organization", "edition", "responsible_department")
        .filter(
            id=venue_selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
            lifecycle=EditionVenueSelection.Lifecycle.ACTIVE,
        )
        .first()
    )
    if venue_selection is None:
        raise VenueResourceUnavailableError()
    configuration: VenueSpaceConfiguration | None = None
    source_space: VenueSpace | None = None
    source_combination: VenueSpaceCombination | None = None
    members: tuple[VenueSpace, ...]
    if source_space_id is not None:
        if selected_configuration_id is None:
            raise ValidationError(
                {"selected_configuration_id": "Select one active configuration."}
            )
        source_space = (
            VenueSpace.objects.select_for_update()
            .filter(
                id=source_space_id,
                organization_id=organization_id,
                property_id=venue_selection.property_id,
                is_active=True,
            )
            .first()
        )
        configuration = (
            VenueSpaceConfiguration.objects.select_for_update()
            .filter(
                id=selected_configuration_id,
                organization_id=organization_id,
                space_id=source_space_id,
                lifecycle=VenueSpaceConfiguration.Lifecycle.ACTIVE,
            )
            .first()
        )
        if source_space is None or configuration is None or capacity is not None:
            raise VenueResourceUnavailableError()
        capacity = VenueCapacityProfile(
            configuration_name=configuration.name,
            seated_capacity=configuration.seated_capacity,
            standing_capacity=configuration.standing_capacity,
            table_capacity=configuration.table_capacity,
            fire_capacity=configuration.fire_capacity,
        )
        members = (source_space,)
    else:
        if (
            source_combination_id is None
            or selected_configuration_id is not None
            or capacity is None
        ):
            raise ValidationError(
                {"capacity": "Combined spaces require an edition capacity snapshot."}
            )
        source_combination = (
            VenueSpaceCombination.objects.select_for_update()
            .filter(
                id=source_combination_id,
                organization_id=organization_id,
                property_id=venue_selection.property_id,
                is_active=True,
            )
            .first()
        )
        if source_combination is None:
            raise VenueResourceUnavailableError()
        members = tuple(
            VenueSpace.objects.select_for_update()
            .filter(
                combination_memberships__combination=source_combination,
                organization_id=organization_id,
                is_active=True,
            )
            .distinct()
            .order_by("id")
        )
        if len(members) < MINIMUM_COMBINATION_MEMBERS:
            raise VenueStateConflictError()
    if capacity is None:
        raise VenueStateConflictError()
    with venue_writer():
        space_selection = EditionSpaceSelection.objects.create(
            organization=venue_selection.organization,
            edition=venue_selection.edition,
            venue_selection=venue_selection,
            responsible_department=venue_selection.responsible_department,
            source_space=source_space,
            source_combination=source_combination,
            selected_configuration=configuration,
            local_name=local_name,
            configuration_name=capacity.configuration_name,
            seated_capacity=capacity.seated_capacity,
            standing_capacity=capacity.standing_capacity,
            table_capacity=capacity.table_capacity,
            fire_capacity=capacity.fire_capacity,
            public_access_info=public_access_info,
            opening_restrictions=opening_restrictions,
        )
        EditionSpaceMember.objects.bulk_create(
            [
                EditionSpaceMember(
                    organization=venue_selection.organization,
                    edition=venue_selection.edition,
                    space_selection=space_selection,
                    source_space=member,
                )
                for member in members
            ]
        )
    ensure_edition_space_binding(space_selection=space_selection)
    receipt = _append_evidence(
        actor=actor,
        organization=venue_selection.organization,
        edition=venue_selection.edition,
        operation=VenueCommandReceipt.Operation.SPACE_SELECT,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=space_selection.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=EDITION_SELECT_CAPABILITY,
        decision=decision,
        changed_fields=("source", "configuration", "members", "local_overrides"),
        aggregate_type="venues.edition_space",
        aggregate_id=space_selection.id,
        action="selected",
        occurred_at=evaluated_at,
    )
    return _result(
        object_id=space_selection.id,
        receipt=receipt,
        resulting_version=1,
    )


def _normalized_availability(
    intervals: Sequence[VenueAvailabilityInterval],
) -> tuple[VenueAvailabilityInterval, ...]:
    if not intervals or len(intervals) > MAXIMUM_AVAILABILITY_WINDOWS:
        raise ValidationError(
            {"intervals": "Provide between one and 256 availability windows."}
        )
    normalized: list[VenueAvailabilityInterval] = []
    for interval in intervals:
        if (
            not isinstance(interval.starts_at, datetime)
            or not isinstance(interval.ends_at, datetime)
            or not timezone.is_aware(interval.starts_at)
            or not timezone.is_aware(interval.ends_at)
            or interval.starts_at >= interval.ends_at
        ):
            raise ValidationError(
                {"intervals": "Availability windows require ordered aware times."}
            )
        normalized.append(
            VenueAvailabilityInterval(
                starts_at=interval.starts_at,
                ends_at=interval.ends_at,
                opening_restriction=normalized_text(
                    interval.opening_restriction,
                    field="opening_restriction",
                    maximum=500,
                ),
            )
        )
    normalized.sort(key=lambda value: (value.starts_at, value.ends_at))
    for previous, current in pairwise(normalized):
        if current.starts_at < previous.ends_at:
            raise ValidationError(
                {"intervals": "Hard availability windows may not overlap."}
            )
    return tuple(normalized)


@transaction.atomic
def set_edition_space_availability(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    expected_version: int,
    intervals: Sequence[VenueAvailabilityInterval],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    normalized = _normalized_availability(intervals)
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "space_selection_id": space_selection_id,
            "expected_version": expected_version,
            "intervals": [asdict(interval) for interval in normalized],
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _space_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
        capability_code=SPACE_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.AVAILABILITY_SET,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    space_selection = (
        EditionSpaceSelection.objects.select_for_update()
        .select_related("organization", "edition")
        .filter(
            id=authorized.space_selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department_id=authorized.department_id,
            lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
        )
        .first()
    )
    if space_selection is None:
        raise VenueResourceUnavailableError()
    if space_selection.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if VenueBooking.objects.filter(
        space_selection=space_selection,
        lifecycle=VenueBooking.Lifecycle.ACTIVE,
    ).exists():
        for booking in VenueBooking.objects.filter(
            space_selection=space_selection,
            lifecycle=VenueBooking.Lifecycle.ACTIVE,
        ).only("setup_starts_at", "teardown_ends_at"):
            if not any(
                interval.starts_at <= booking.setup_starts_at
                and interval.ends_at >= booking.teardown_ends_at
                for interval in normalized
            ):
                raise VenueAvailabilityConflictError()
    availability_version = space_selection.current_availability_version + 1
    space_selection.current_availability_version = availability_version
    space_selection.aggregate_version += 1
    with venue_writer():
        space_selection.save()
        EditionSpaceAvailabilityWindow.objects.bulk_create(
            [
                EditionSpaceAvailabilityWindow(
                    organization=space_selection.organization,
                    edition=space_selection.edition,
                    space_selection=space_selection,
                    availability_version=availability_version,
                    starts_at=interval.starts_at,
                    ends_at=interval.ends_at,
                    opening_restriction=interval.opening_restriction,
                )
                for interval in normalized
            ]
        )
    receipt = _append_evidence(
        actor=actor,
        organization=space_selection.organization,
        edition=space_selection.edition,
        operation=VenueCommandReceipt.Operation.AVAILABILITY_SET,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=space_selection.id,
        resulting_version=space_selection.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SPACE_MANAGE_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("current_availability_version", "availability_windows"),
        aggregate_type="venues.edition_space",
        aggregate_id=space_selection.id,
        action="availability_replaced",
        occurred_at=evaluated_at,
    )
    return _result(
        object_id=space_selection.id,
        receipt=receipt,
        resulting_version=space_selection.aggregate_version,
    )


def _normalized_booking_envelope(
    envelope: VenueBookingEnvelope,
) -> VenueBookingEnvelope:
    values = (
        envelope.setup_starts_at,
        envelope.effective_starts_at,
        envelope.effective_ends_at,
        envelope.teardown_ends_at,
    )
    if any(
        not isinstance(value, datetime) or not timezone.is_aware(value)
        for value in values
    ):
        raise ValidationError(
            {"schedule": "Booking intervals require timezone-aware timestamps."}
        )
    if not (
        envelope.setup_starts_at
        <= envelope.effective_starts_at
        < envelope.effective_ends_at
        <= envelope.teardown_ends_at
    ):
        raise ValidationError(
            {"schedule": "Use an ordered setup, effective, and teardown envelope."}
        )
    return envelope


def _normalized_booking_values(
    *,
    kind: str,
    external_reference: str,
    internal_title: str,
    public_title: str,
    public_description: str,
    capacity_mode: str,
    expected_attendance: int,
) -> dict[str, object]:
    if kind not in VenueBooking.Kind.values:
        raise ValidationError({"kind": "Select a supported booking kind."})
    if capacity_mode not in VenueBooking.CapacityMode.values:
        raise ValidationError({"capacity_mode": "Select a supported capacity mode."})
    if (
        not isinstance(expected_attendance, int)
        or isinstance(expected_attendance, bool)
        or expected_attendance < 1
    ):
        raise ValidationError(
            {"expected_attendance": "Enter a positive expected attendance."}
        )
    return {
        "kind": kind,
        "external_reference": normalized_text(
            external_reference,
            field="external_reference",
            maximum=240,
            collapse=True,
        ),
        "internal_title": normalized_text(
            internal_title,
            field="internal_title",
            maximum=240,
            required=True,
            collapse=True,
        ),
        "public_title": normalized_text(
            public_title,
            field="public_title",
            maximum=240,
            collapse=True,
        ),
        "public_description": normalized_text(
            public_description,
            field="public_description",
            maximum=2_000,
        ),
        "capacity_mode": capacity_mode,
        "expected_attendance": expected_attendance,
    }


def _capacity_limit(
    *, space_selection: EditionSpaceSelection, capacity_mode: str
) -> int:
    by_mode: dict[str, int] = {
        VenueBooking.CapacityMode.SEATED: space_selection.seated_capacity,
        VenueBooking.CapacityMode.STANDING: space_selection.standing_capacity,
        VenueBooking.CapacityMode.TABLE: space_selection.table_capacity,
    }
    configured_limit = by_mode[capacity_mode]
    if configured_limit < 1:
        raise VenueCapacityConflictError()
    return min(configured_limit, space_selection.fire_capacity)


def _require_available_capacity(
    *,
    space_selection: EditionSpaceSelection,
    envelope: VenueBookingEnvelope,
    capacity_mode: str,
    expected_attendance: int,
) -> None:
    if expected_attendance > _capacity_limit(
        space_selection=space_selection,
        capacity_mode=capacity_mode,
    ):
        raise VenueCapacityConflictError()
    if space_selection.current_availability_version < 1:
        raise VenueAvailabilityConflictError()
    contained = EditionSpaceAvailabilityWindow.objects.filter(
        organization_id=space_selection.organization_id,
        edition_id=space_selection.edition_id,
        space_selection=space_selection,
        availability_version=space_selection.current_availability_version,
        starts_at__lte=envelope.setup_starts_at,
        ends_at__gte=envelope.teardown_ends_at,
    ).exists()
    if not contained:
        raise VenueAvailabilityConflictError()


def _locked_space_selection(
    *,
    authorized: _AuthorizedSpace,
    organization_id: UUID,
    edition_id: UUID,
) -> EditionSpaceSelection:
    space_selection = (
        EditionSpaceSelection.objects.select_for_update()
        .select_related("organization", "edition", "responsible_department")
        .filter(
            id=authorized.space_selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department_id=authorized.department_id,
            lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
            venue_selection__lifecycle=EditionVenueSelection.Lifecycle.ACTIVE,
        )
        .first()
    )
    if space_selection is None:
        raise VenueResourceUnavailableError()
    return space_selection


def _validate_public_layout(
    *,
    organization_id: UUID,
    space_selection: EditionSpaceSelection,
    public_layout_id: UUID | None,
) -> VenueLayoutVersion | None:
    if public_layout_id is None:
        return None
    member_ids = EditionSpaceMember.objects.filter(
        space_selection=space_selection,
        organization_id=organization_id,
        edition_id=space_selection.edition_id,
    ).values_list("source_space_id", flat=True)
    layout = (
        VenueLayoutVersion.objects.filter(
            id=public_layout_id,
            organization_id=organization_id,
            space_id__in=member_ids,
            visibility=VenueLayoutVersion.Visibility.PUBLIC,
            review_status=VenueLayoutVersion.ReviewStatus.APPROVED,
        )
        .exclude(approved_reference="")
        .first()
    )
    if layout is None:
        raise VenueResourceUnavailableError()
    return layout


def _append_booking_history(
    *,
    booking: VenueBooking,
    actor: Account,
    action: str,
    reason: str,
    occurred_at: datetime,
    old_envelope: VenueBookingEnvelope | None = None,
    old_review_state: str = "",
    old_publication_state: str = "",
    old_lifecycle: str = "",
) -> None:
    with venue_writer():
        VenueBookingHistory.objects.create(
            booking=booking,
            organization=booking.organization,
            edition=booking.edition,
            sequence=booking.aggregate_version,
            booking_version=booking.aggregate_version,
            action=action,
            actor=actor,
            occurred_at=occurred_at,
            reason=reason,
            old_setup_starts_at=(
                old_envelope.setup_starts_at if old_envelope else None
            ),
            old_effective_starts_at=(
                old_envelope.effective_starts_at if old_envelope else None
            ),
            old_effective_ends_at=(
                old_envelope.effective_ends_at if old_envelope else None
            ),
            old_teardown_ends_at=(
                old_envelope.teardown_ends_at if old_envelope else None
            ),
            new_setup_starts_at=booking.setup_starts_at,
            new_effective_starts_at=booking.effective_starts_at,
            new_effective_ends_at=booking.effective_ends_at,
            new_teardown_ends_at=booking.teardown_ends_at,
            from_review_state=old_review_state,
            to_review_state=booking.review_state,
            from_publication_state=old_publication_state,
            to_publication_state=booking.publication_state,
            from_lifecycle=old_lifecycle,
            to_lifecycle=booking.lifecycle,
        )


def _write_booking_occupancy(*, booking: VenueBooking) -> None:
    member_ids = tuple(
        EditionSpaceMember.objects.filter(
            space_selection=booking.space_selection,
            organization=booking.organization,
            edition=booking.edition,
        )
        .order_by("source_space_id")
        .values_list("source_space_id", flat=True)
    )
    if not member_ids:
        raise VenueStateConflictError()
    rows: list[VenueBookingOccupancy] = []
    for source_space_id in member_ids:
        rows.extend(
            (
                VenueBookingOccupancy(
                    booking=booking,
                    organization=booking.organization,
                    edition=booking.edition,
                    source_space_id=source_space_id,
                    conflict_group=(
                        VenueBookingOccupancy.ConflictGroup.SETUP_EFFECTIVE
                    ),
                    occupied_range=Range(
                        booking.setup_starts_at,
                        booking.effective_ends_at,
                        bounds="[)",
                    ),
                    booking_version=booking.aggregate_version,
                ),
                VenueBookingOccupancy(
                    booking=booking,
                    organization=booking.organization,
                    edition=booking.edition,
                    source_space_id=source_space_id,
                    conflict_group=(
                        VenueBookingOccupancy.ConflictGroup.EFFECTIVE_TEARDOWN
                    ),
                    occupied_range=Range(
                        booking.effective_starts_at,
                        booking.teardown_ends_at,
                        bounds="[)",
                    ),
                    booking_version=booking.aggregate_version,
                ),
            )
        )
    try:
        with transaction.atomic(), venue_writer():
            VenueBookingOccupancy.objects.bulk_create(rows)
    except IntegrityError as error:
        raise VenueBookingOverlapError() from error


def _booking_envelope(booking: VenueBooking) -> VenueBookingEnvelope:
    return VenueBookingEnvelope(
        setup_starts_at=booking.setup_starts_at,
        effective_starts_at=booking.effective_starts_at,
        effective_ends_at=booking.effective_ends_at,
        teardown_ends_at=booking.teardown_ends_at,
    )


@transaction.atomic
def create_venue_booking(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    kind: str,
    external_reference: str,
    internal_title: str,
    public_title: str,
    public_description: str,
    capacity_mode: str,
    expected_attendance: int,
    envelope: VenueBookingEnvelope,
    public_layout_id: UUID | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    envelope = _normalized_booking_envelope(envelope)
    values = _normalized_booking_values(
        kind=kind,
        external_reference=external_reference,
        internal_title=internal_title,
        public_title=public_title,
        public_description=public_description,
        capacity_mode=capacity_mode,
        expected_attendance=expected_attendance,
    )
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "space_selection_id": space_selection_id,
            "booking": values,
            "envelope": asdict(envelope),
            "public_layout_id": public_layout_id,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _space_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
        capability_code=SPACE_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.BOOKING_CREATE,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    space_selection = _locked_space_selection(
        authorized=authorized,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    _require_available_capacity(
        space_selection=space_selection,
        envelope=envelope,
        capacity_mode=capacity_mode,
        expected_attendance=expected_attendance,
    )
    public_layout = _validate_public_layout(
        organization_id=organization_id,
        space_selection=space_selection,
        public_layout_id=public_layout_id,
    )
    with venue_writer():
        booking = VenueBooking.objects.create(
            organization=space_selection.organization,
            edition=space_selection.edition,
            space_selection=space_selection,
            responsible_department=space_selection.responsible_department,
            setup_starts_at=envelope.setup_starts_at,
            effective_starts_at=envelope.effective_starts_at,
            effective_ends_at=envelope.effective_ends_at,
            teardown_ends_at=envelope.teardown_ends_at,
            public_layout=public_layout,
            created_by=actor,
            last_modified_by=actor,
            **values,
        )
    _append_booking_history(
        booking=booking,
        actor=actor,
        action=VenueBookingHistory.Action.CREATED,
        reason=reason,
        occurred_at=evaluated_at,
    )
    _write_booking_occupancy(booking=booking)
    receipt = _append_evidence(
        actor=actor,
        organization=booking.organization,
        edition=booking.edition,
        operation=VenueCommandReceipt.Operation.BOOKING_CREATE,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=booking.id,
        resulting_version=booking.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SPACE_MANAGE_CAPABILITY,
        decision=authorized.decision,
        changed_fields=(
            "created",
            "schedule",
            "capacity",
            "physical_occupancy",
        ),
        aggregate_type="venues.booking",
        aggregate_id=booking.id,
        action="created",
        occurred_at=evaluated_at,
    )
    return _result(
        object_id=booking.id,
        receipt=receipt,
        resulting_version=booking.aggregate_version,
    )


@transaction.atomic
def reschedule_venue_booking(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    booking_id: UUID,
    expected_version: int,
    kind: str,
    external_reference: str,
    internal_title: str,
    public_title: str,
    public_description: str,
    capacity_mode: str,
    expected_attendance: int,
    envelope: VenueBookingEnvelope,
    public_layout_id: UUID | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
    expected_version = _require_expected_version(expected_version)
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    source_channel = normalized_source_channel(source_channel)
    reason = normalized_reason(reason)
    envelope = _normalized_booking_envelope(envelope)
    values = _normalized_booking_values(
        kind=kind,
        external_reference=external_reference,
        internal_title=internal_title,
        public_title=public_title,
        public_description=public_description,
        capacity_mode=capacity_mode,
        expected_attendance=expected_attendance,
    )
    digest = canonical_digest(
        {
            "organization_id": organization_id,
            "edition_id": edition_id,
            "space_selection_id": space_selection_id,
            "booking_id": booking_id,
            "expected_version": expected_version,
            "booking": values,
            "envelope": asdict(envelope),
            "public_layout_id": public_layout_id,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _space_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
        capability_code=SPACE_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.BOOKING_RESCHEDULE,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    space_selection = _locked_space_selection(
        authorized=authorized,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    booking = (
        VenueBooking.objects.select_for_update()
        .filter(
            id=booking_id,
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection=space_selection,
            responsible_department_id=authorized.department_id,
        )
        .first()
    )
    if booking is None:
        raise VenueResourceUnavailableError()
    if booking.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if booking.lifecycle != VenueBooking.Lifecycle.ACTIVE:
        raise VenueStateConflictError()
    _require_available_capacity(
        space_selection=space_selection,
        envelope=envelope,
        capacity_mode=capacity_mode,
        expected_attendance=expected_attendance,
    )
    public_layout = _validate_public_layout(
        organization_id=organization_id,
        space_selection=space_selection,
        public_layout_id=public_layout_id,
    )
    old_envelope = _booking_envelope(booking)
    old_review_state = booking.review_state
    old_publication_state = booking.publication_state
    old_lifecycle = booking.lifecycle
    with venue_writer():
        VenueBookingOccupancy.objects.filter(booking=booking, active=True).update(
            active=False
        )
        for field_name, value in values.items():
            setattr(booking, field_name, value)
        booking.setup_starts_at = envelope.setup_starts_at
        booking.effective_starts_at = envelope.effective_starts_at
        booking.effective_ends_at = envelope.effective_ends_at
        booking.teardown_ends_at = envelope.teardown_ends_at
        booking.public_layout = public_layout
        booking.review_state = VenueBooking.ReviewState.DRAFT
        booking.publication_state = VenueBooking.PublicationState.UNPUBLISHED
        booking.approved_by = None
        booking.approved_at = None
        booking.published_by = None
        booking.published_at = None
        booking.last_modified_by = actor
        booking.aggregate_version += 1
        booking.save()
    _append_booking_history(
        booking=booking,
        actor=actor,
        action=VenueBookingHistory.Action.RESCHEDULED,
        reason=reason,
        occurred_at=evaluated_at,
        old_envelope=old_envelope,
        old_review_state=old_review_state,
        old_publication_state=old_publication_state,
        old_lifecycle=old_lifecycle,
    )
    _write_booking_occupancy(booking=booking)
    receipt = _append_evidence(
        actor=actor,
        organization=booking.organization,
        edition=booking.edition,
        operation=VenueCommandReceipt.Operation.BOOKING_RESCHEDULE,
        idempotency_key=idempotency_key,
        request_digest=digest,
        result_object_id=booking.id,
        resulting_version=booking.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SPACE_MANAGE_CAPABILITY,
        decision=authorized.decision,
        changed_fields=(
            "schedule",
            "capacity",
            "public_projection",
            "review_state",
            "publication_state",
            "physical_occupancy",
        ),
        aggregate_type="venues.booking",
        aggregate_id=booking.id,
        action="rescheduled",
        occurred_at=evaluated_at,
    )
    return _result(
        object_id=booking.id,
        receipt=receipt,
        resulting_version=booking.aggregate_version,
    )


def _locked_booking(
    *,
    authorized: _AuthorizedSpace,
    organization_id: UUID,
    edition_id: UUID,
    booking_id: UUID,
) -> VenueBooking:
    booking = (
        VenueBooking.objects.select_for_update()
        .select_related("organization", "edition")
        .filter(
            id=booking_id,
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id=authorized.space_selection_id,
            responsible_department_id=authorized.department_id,
        )
        .first()
    )
    if booking is None:
        raise VenueResourceUnavailableError()
    return booking


def _record_booking_state_change(
    *,
    actor: Account,
    booking: VenueBooking,
    action: str,
    reason: str,
    occurred_at: datetime,
    old_review_state: str,
    old_publication_state: str,
    old_lifecycle: str,
    operation: str,
    idempotency_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    capability_code: str,
    decision: PolicyDecision,
    changed_fields: Sequence[str],
) -> VenueCommandResult:
    _append_booking_history(
        booking=booking,
        actor=actor,
        action=action,
        reason=reason,
        occurred_at=occurred_at,
        old_envelope=_booking_envelope(booking),
        old_review_state=old_review_state,
        old_publication_state=old_publication_state,
        old_lifecycle=old_lifecycle,
    )
    receipt = _append_evidence(
        actor=actor,
        organization=booking.organization,
        edition=booking.edition,
        operation=operation,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=booking.id,
        resulting_version=booking.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=capability_code,
        decision=decision,
        changed_fields=changed_fields,
        aggregate_type="venues.booking",
        aggregate_id=booking.id,
        action=action,
        occurred_at=occurred_at,
    )
    return _result(
        object_id=booking.id,
        receipt=receipt,
        resulting_version=booking.aggregate_version,
    )


@transaction.atomic
def approve_venue_booking(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    booking_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
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
            "space_selection_id": space_selection_id,
            "booking_id": booking_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _space_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
        capability_code=SPACE_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.BOOKING_APPROVE,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    booking = _locked_booking(
        authorized=authorized,
        organization_id=organization_id,
        edition_id=edition_id,
        booking_id=booking_id,
    )
    if booking.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if (
        booking.lifecycle != VenueBooking.Lifecycle.ACTIVE
        or booking.review_state != VenueBooking.ReviewState.DRAFT
    ):
        raise VenueStateConflictError()
    if actor.id in {booking.created_by_id, booking.last_modified_by_id}:
        raise VenueIndependentApprovalError()
    old_review_state = booking.review_state
    old_publication_state = booking.publication_state
    old_lifecycle = booking.lifecycle
    with venue_writer():
        booking.review_state = VenueBooking.ReviewState.APPROVED
        booking.approved_by = actor
        booking.approved_at = evaluated_at
        booking.last_modified_by = actor
        booking.aggregate_version += 1
        booking.save()
    return _record_booking_state_change(
        actor=actor,
        booking=booking,
        action=VenueBookingHistory.Action.APPROVED,
        reason=reason,
        occurred_at=evaluated_at,
        old_review_state=old_review_state,
        old_publication_state=old_publication_state,
        old_lifecycle=old_lifecycle,
        operation=VenueCommandReceipt.Operation.BOOKING_APPROVE,
        idempotency_key=idempotency_key,
        request_digest=digest,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SPACE_MANAGE_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("review_state", "approved_by", "approved_at"),
    )


@transaction.atomic
def publish_venue_booking(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    booking_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
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
            "space_selection_id": space_selection_id,
            "booking_id": booking_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _space_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
        capability_code=SPACE_PUBLISH_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.BOOKING_PUBLISH,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    booking = _locked_booking(
        authorized=authorized,
        organization_id=organization_id,
        edition_id=edition_id,
        booking_id=booking_id,
    )
    if booking.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if (
        booking.lifecycle != VenueBooking.Lifecycle.ACTIVE
        or booking.review_state != VenueBooking.ReviewState.APPROVED
        or booking.publication_state == VenueBooking.PublicationState.PUBLISHED
        or booking.kind == VenueBooking.Kind.PRIVATE
        or not booking.public_title
    ):
        raise VenueStateConflictError()
    if booking.approved_by_id == actor.id:
        raise VenueIndependentApprovalError()
    if booking.public_layout_id and (
        booking.public_layout is None
        or booking.public_layout.visibility != VenueLayoutVersion.Visibility.PUBLIC
        or booking.public_layout.review_status
        != VenueLayoutVersion.ReviewStatus.APPROVED
        or not booking.public_layout.approved_reference
    ):
        raise VenueStateConflictError()
    old_review_state = booking.review_state
    old_publication_state = booking.publication_state
    old_lifecycle = booking.lifecycle
    with venue_writer():
        booking.publication_state = VenueBooking.PublicationState.PUBLISHED
        booking.published_by = actor
        booking.published_at = evaluated_at
        booking.last_modified_by = actor
        booking.aggregate_version += 1
        booking.save()
    return _record_booking_state_change(
        actor=actor,
        booking=booking,
        action=VenueBookingHistory.Action.PUBLISHED,
        reason=reason,
        occurred_at=evaluated_at,
        old_review_state=old_review_state,
        old_publication_state=old_publication_state,
        old_lifecycle=old_lifecycle,
        operation=VenueCommandReceipt.Operation.BOOKING_PUBLISH,
        idempotency_key=idempotency_key,
        request_digest=digest,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SPACE_PUBLISH_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("publication_state", "published_by", "published_at"),
    )


@transaction.atomic
def withdraw_venue_booking_publication(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    booking_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
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
            "space_selection_id": space_selection_id,
            "booking_id": booking_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _space_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
        capability_code=SPACE_PUBLISH_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.BOOKING_WITHDRAW,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    booking = _locked_booking(
        authorized=authorized,
        organization_id=organization_id,
        edition_id=edition_id,
        booking_id=booking_id,
    )
    if booking.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if (
        booking.lifecycle != VenueBooking.Lifecycle.ACTIVE
        or booking.publication_state != VenueBooking.PublicationState.PUBLISHED
    ):
        raise VenueStateConflictError()
    old_review_state = booking.review_state
    old_publication_state = booking.publication_state
    old_lifecycle = booking.lifecycle
    with venue_writer():
        booking.publication_state = VenueBooking.PublicationState.WITHDRAWN
        booking.last_modified_by = actor
        booking.aggregate_version += 1
        booking.save()
    return _record_booking_state_change(
        actor=actor,
        booking=booking,
        action=VenueBookingHistory.Action.WITHDRAWN,
        reason=reason,
        occurred_at=evaluated_at,
        old_review_state=old_review_state,
        old_publication_state=old_publication_state,
        old_lifecycle=old_lifecycle,
        operation=VenueCommandReceipt.Operation.BOOKING_WITHDRAW,
        idempotency_key=idempotency_key,
        request_digest=digest,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SPACE_PUBLISH_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("publication_state",),
    )


@transaction.atomic
def cancel_venue_booking(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
    booking_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> VenueCommandResult:
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
            "space_selection_id": space_selection_id,
            "booking_id": booking_id,
            "expected_version": expected_version,
            "reason": reason,
        }
    )
    evaluated_at = timezone.now()
    authorized = _space_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        space_selection_id=space_selection_id,
        capability_code=SPACE_MANAGE_CAPABILITY,
        at=evaluated_at,
    )
    if receipt := _existing_receipt(
        actor=actor,
        operation=VenueCommandReceipt.Operation.BOOKING_CANCEL,
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=digest,
    ):
        return _replayed_result(receipt)
    booking = _locked_booking(
        authorized=authorized,
        organization_id=organization_id,
        edition_id=edition_id,
        booking_id=booking_id,
    )
    if booking.aggregate_version != expected_version:
        raise VenueVersionConflictError()
    if booking.lifecycle != VenueBooking.Lifecycle.ACTIVE:
        raise VenueStateConflictError()
    old_review_state = booking.review_state
    old_publication_state = booking.publication_state
    old_lifecycle = booking.lifecycle
    with venue_writer():
        VenueBookingOccupancy.objects.filter(booking=booking, active=True).update(
            active=False
        )
        booking.lifecycle = VenueBooking.Lifecycle.CANCELLED
        if booking.publication_state == VenueBooking.PublicationState.PUBLISHED:
            booking.publication_state = VenueBooking.PublicationState.WITHDRAWN
        booking.last_modified_by = actor
        booking.aggregate_version += 1
        booking.save()
    return _record_booking_state_change(
        actor=actor,
        booking=booking,
        action=VenueBookingHistory.Action.CANCELLED,
        reason=reason,
        occurred_at=evaluated_at,
        old_review_state=old_review_state,
        old_publication_state=old_publication_state,
        old_lifecycle=old_lifecycle,
        operation=VenueCommandReceipt.Operation.BOOKING_CANCEL,
        idempotency_key=idempotency_key,
        request_digest=digest,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        capability_code=SPACE_MANAGE_CAPABILITY,
        decision=authorized.decision,
        changed_fields=("lifecycle", "publication_state", "physical_occupancy"),
    )
