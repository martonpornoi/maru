"""Closed idempotent commands for offers, custody, and physical logistics."""
# ruff: noqa: PLR0912, PLR0915

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    ResolvedAuthorizationTarget,
    decide,
    resolve_edition_target,
    resolve_organization_target,
    resolve_self_target,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.venues.models import EditionSpaceSelection
from maru.workforce.models import Department, PositionAssignment

from .authorization import resolve_logistics_manifest_target
from .bindings import ensure_logistics_manifest_binding
from .inputs import (
    canonical_digest,
    normalized_code,
    normalized_label_code,
    normalized_reason,
    normalized_source_channel,
    normalized_text,
)
from .models import (
    MAX_OFFLINE_OPERATIONS,
    Asset,
    AssetAgreement,
    EquipmentOffer,
    EquipmentOfferAcceptance,
    EquipmentOfferHistory,
    EquipmentOfferItem,
    KeyholderResponsibility,
    LogisticsCommandReceipt,
    LogisticsCurrentState,
    LogisticsDiscrepancy,
    LogisticsEditionControl,
    LogisticsEvent,
    LogisticsLabel,
    LogisticsManifest,
    LogisticsManifestLine,
    LogisticsNode,
    LogisticsParty,
    OfflineOperationReceipt,
    OfflineScanBatch,
    OfflineScanOperation,
    PhysicalKey,
    RestrictedLogisticsAddress,
    ReusableKit,
    ReusableKitLine,
    StockLot,
)
from .writer_boundary import logistics_writer

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SELF_OFFER_CAPABILITY = "logistics.offer_self"
CATALOG_MANAGE_CAPABILITY = "logistics.manage_catalog"
RESTRICTED_CONTACT_CAPABILITY = "logistics.view_restricted_contacts"
WORKSPACE_VIEW_CAPABILITY = "logistics.view_workspace"
OPERATIONS_MANAGE_CAPABILITY = "logistics.manage_operations"
OFFER_REVIEW_CAPABILITY = "logistics.review_offers"
OFFLINE_RECONCILE_CAPABILITY = "logistics.reconcile_offline"
MANIFEST_VIEW_CAPABILITY = "logistics.view_manifest"
MANIFEST_MANAGE_CAPABILITY = "logistics.manage_manifest"
MAX_CONTAINMENT_DEPTH = 128
MAX_OFFER_ITEMS = 100
MAX_OFFER_QUANTITY = 1_000_000
MAX_TRACKED_QUANTITY = 1_000_000_000
MAX_MANIFEST_LINES = 500
MAX_KIT_LINES = 200
MIN_QR_IDENTIFIER_LENGTH = 24
SELF_OFFER_EDITION_LIFECYCLES = frozenset(
    {
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
    }
)


class LogisticsCommandError(RuntimeError):
    """Signal logistics command."""

    reason_code = "logistics_command_failed"


class LogisticsAuthorizationDeniedError(LogisticsCommandError):
    """Signal logistics authorization denied."""

    reason_code = "logistics_authorization_denied"


class LogisticsResourceUnavailableError(LogisticsCommandError):
    """Signal logistics resource unavailable."""

    reason_code = "logistics_resource_unavailable"


class LogisticsVersionConflictError(LogisticsCommandError):
    """Signal logistics version conflict."""

    reason_code = "logistics_version_conflict"


class LogisticsRetryConflictError(LogisticsCommandError):
    """Signal logistics retry conflict."""

    reason_code = "logistics_retry_conflict"


class LogisticsStateConflictError(LogisticsCommandError):
    """Signal logistics state conflict."""

    reason_code = "logistics_state_conflict"


class LogisticsContainmentCycleError(LogisticsCommandError):
    """Signal logistics containment cycle."""

    reason_code = "logistics_containment_cycle"


@dataclass(frozen=True, slots=True)
class LogisticsCommandResult:
    """Describe logistics command result.

    Attributes
    ----------
    object_id
        The object identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    replayed
        The replayed retained in this immutable projection.
    """

    object_id: UUID
    receipt_id: UUID
    resulting_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class PartyProfile:
    """Describe party profile.

    Attributes
    ----------
    kind
        The closed discriminator selecting the requested behavior.
    role
        The immutable or edition-owned role evaluated for authority.
    legal_name
        The human-readable legal name shown to authorized readers.
    public_name
        The human-readable public name shown to authorized readers.
    provider_reference
        The provider or source provider reference retained for reconciliation.
    website_url
        The validated absolute HTTPS website url.
    """

    kind: str
    role: str
    legal_name: str
    public_name: str
    provider_reference: str = ""
    website_url: str = ""


@dataclass(frozen=True, slots=True)
class OfferItemInput:
    """Describe offer item input.

    Attributes
    ----------
    kind
        The closed discriminator selecting the requested behavior.
    name
        The human-readable name to normalize or persist.
    condition
        The configured condition evaluated against the submitted answer.
    ownership_statement
        The ownership statement retained in this immutable projection.
    quantity
        The positive number of inventory or entitlement units requested.
    description
        The human-readable description shown to authorized readers.
    manufacturer
        The manufacturer retained in this immutable projection.
    model_name
        The human-readable model name shown to authorized readers.
    serial_number
        The serial number retained in this immutable projection.
    value_class
        The value class retained in this immutable projection.
    """

    kind: str
    name: str
    condition: str
    ownership_statement: str
    quantity: int = 1
    description: str = ""
    manufacturer: str = ""
    model_name: str = ""
    serial_number: str = ""
    value_class: str = ""


@dataclass(frozen=True, slots=True)
class SubjectLocator:
    """Describe subject locator.

    Attributes
    ----------
    kind
        The closed discriminator selecting the requested behavior.
    object_id
        The object identifier within the requested scope.
    """

    kind: str
    object_id: UUID


@dataclass(frozen=True, slots=True)
class MovementInput:
    """Describe movement input.

    Attributes
    ----------
    event_type
        The closed event type discriminator defined by the domain catalog.
    subject
        The tenant-scoped person or resource governed by the operation.
    occurred_at
        The timezone-aware timestamp for occurred.
    source_node_id
        The source node identifier within the requested scope.
    destination_node_id
        The destination node identifier within the requested scope.
    to_custodian_account_id
        The to custodian account identifier within the requested scope.
    to_custodian_party_id
        The to custodian party identifier within the requested scope.
    quantity
        The positive number of inventory or entitlement units requested.
    condition_before
        The timezone-aware boundary for condition before.
    condition_after
        The timezone-aware boundary for condition after.
    manifest_id
        The manifest identifier within the requested scope.
    evidence_reference
        The provider or source evidence reference retained for reconciliation.
    """

    event_type: str
    subject: SubjectLocator
    occurred_at: datetime
    source_node_id: UUID | None = None
    destination_node_id: UUID | None = None
    to_custodian_account_id: UUID | None = None
    to_custodian_party_id: UUID | None = None
    quantity: int | None = None
    condition_before: str = ""
    condition_after: str = ""
    manifest_id: UUID | None = None
    evidence_reference: str = ""


@dataclass(frozen=True, slots=True)
class ManifestLineInput:
    """Describe manifest line input.

    Attributes
    ----------
    subject
        The tenant-scoped person or resource governed by the operation.
    quantity
        The positive number of inventory or entitlement units requested.
    packed_in_node_id
        The packed in node identifier within the requested scope.
    notes
        The bounded operator notes retained with the domain record.
    """

    subject: SubjectLocator
    quantity: int = 1
    packed_in_node_id: UUID | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class OfflineOperationInput:
    """Describe offline operation input.

    Attributes
    ----------
    sequence
        The sequence retained in this immutable projection.
    idempotency_key
        The stable key that makes an exact retry idempotent.
    expected_subject_sequence
        The expected expected subject sequence used to reject stale updates.
    action
        The stable action code describing the requested transition.
    label_code
        The stable label code from the relevant closed catalog.
    occurred_at
        The timezone-aware timestamp for occurred.
    source_label_code
        The stable source label code from the relevant closed catalog.
    destination_label_code
        The stable destination label code from the relevant closed catalog.
    quantity
        The positive number of inventory or entitlement units requested.
    observed_condition
        The observed condition retained in this immutable projection.
    """

    sequence: int
    idempotency_key: UUID
    expected_subject_sequence: int
    action: str
    label_code: str
    occurred_at: datetime
    source_label_code: str = ""
    destination_label_code: str = ""
    quantity: int | None = None
    observed_condition: str = ""


@dataclass(frozen=True, slots=True)
class KitLineInput:
    """Describe kit line input.

    Attributes
    ----------
    subject
        The tenant-scoped person or resource governed by the operation.
    quantity
        The positive number of inventory or entitlement units requested.
    notes
        The bounded operator notes retained with the domain record.
    """

    subject: SubjectLocator
    quantity: int = 1
    notes: str = ""


TrackedSubject = Asset | StockLot | PhysicalKey | LogisticsNode


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


def _require_actor(actor: Account, *, person_only: bool = False) -> Account:
    current = (
        Account.objects.select_for_update().filter(pk=actor.pk, is_active=True).first()
    )
    if (
        current is None
        or current.is_platform_administrator
        or (person_only and current.account_kind != Account.Kind.PERSON)
    ):
        raise LogisticsAuthorizationDeniedError
    return current


def _lock_eligible_logistics_person(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    account_id: UUID,
    extra_eligible_ids: frozenset[UUID] = frozenset(),
) -> Account:
    """Resolve one convention subject; an active platform identity is insufficient.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID | None
        The event edition identifier that scopes the operation.
    account_id : UUID
        The platform account identifier within the requested scope.
    extra_eligible_ids : frozenset[UUID], default=frozenset()
        The selected extra eligible identifiers.

    Returns
    -------
    Account
        The resolved Account for lock eligible logistics person.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    """
    person = (
        Account.objects.select_for_update()
        .filter(
            id=account_id,
            is_active=True,
            account_kind=Account.Kind.PERSON,
        )
        .first()
    )
    if person is None or person.is_platform_administrator:
        raise LogisticsResourceUnavailableError
    eligible = account_id == actor.id or account_id in extra_eligible_ids
    assignment_scope = PositionAssignment.objects.filter(
        account_id=account_id,
        organization_id=organization_id,
        status=PositionAssignment.Status.ACTIVE,
    )
    offer_scope = EquipmentOffer.objects.filter(
        offered_by_id=account_id,
        organization_id=organization_id,
    )
    if edition_id is not None:
        assignment_scope = assignment_scope.filter(edition_id=edition_id)
        offer_scope = offer_scope.filter(edition_id=edition_id)
    eligible = eligible or assignment_scope.exists() or offer_scope.exists()
    if not eligible:
        raise LogisticsResourceUnavailableError
    return person


def _require_decision(
    *,
    actor: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget | None,
    at: datetime,
) -> PolicyDecision:
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=target,
        at=at,
    )
    if not decision.allowed:
        raise LogisticsAuthorizationDeniedError
    return decision


def _organization_context(
    *, actor: Account, organization_id: UUID, capability_code: str, at: datetime
) -> tuple[Account, Organization, PolicyDecision]:
    current = _require_actor(actor)
    organization = (
        Organization.objects.select_for_update().filter(pk=organization_id).first()
    )
    target = resolve_organization_target(organization_id=organization_id)
    if organization is None or target is None:
        raise LogisticsAuthorizationDeniedError
    return (
        current,
        organization,
        _require_decision(
            actor=current,
            capability_code=capability_code,
            target=target,
            at=at,
        ),
    )


def _edition_context(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    at: datetime,
) -> tuple[Account, Organization, EventEdition, PolicyDecision]:
    current = _require_actor(actor)
    edition = (
        EventEdition.objects.select_for_update()
        .select_related("organization", "series")
        .filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .first()
    )
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if edition is None or target is None:
        raise LogisticsAuthorizationDeniedError
    decision = _require_decision(
        actor=current,
        capability_code=capability_code,
        target=target,
        at=at,
    )
    return current, edition.organization, edition, decision


def _catalog_context(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    at: datetime,
) -> tuple[Account, Organization, EventEdition | None, PolicyDecision]:
    """Authorize catalog work at the exact route allocation scope.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID | None
        The event edition identifier that scopes the operation.
    at : datetime
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    tuple[Account, Organization, EventEdition | None, PolicyDecision]
        The matching catalog context records in deterministic order.
    """
    if edition_id is not None:
        return _edition_context(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=CATALOG_MANAGE_CAPABILITY,
            at=at,
        )
    current, organization, decision = _organization_context(
        actor=actor,
        organization_id=organization_id,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        at=at,
    )
    return current, organization, None, decision


def _self_context(
    *, actor: Account, organization_id: UUID, edition_id: UUID, at: datetime
) -> tuple[Account, Organization, EventEdition, PolicyDecision]:
    current = _require_actor(actor, person_only=True)
    edition = (
        EventEdition.objects.select_for_update()
        .select_related("organization", "series")
        .filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .first()
    )
    target = resolve_self_target(
        principal=current,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if edition is None or target is None:
        raise LogisticsAuthorizationDeniedError
    decision = _require_decision(
        actor=current,
        capability_code=SELF_OFFER_CAPABILITY,
        target=target,
        at=at,
    )
    return current, edition.organization, edition, decision


def _manifest_context(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    manifest_id: UUID,
    capability_code: str,
    at: datetime,
) -> tuple[Account, Organization, EventEdition, PolicyDecision]:
    current = _require_actor(actor)
    edition = (
        EventEdition.objects.select_for_update()
        .select_related("organization", "series")
        .filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .first()
    )
    target = resolve_logistics_manifest_target(
        organization_id=organization_id,
        edition_id=edition_id,
        manifest_id=manifest_id,
    )
    if edition is None or target is None:
        raise LogisticsAuthorizationDeniedError
    decision = _require_decision(
        actor=current,
        capability_code=capability_code,
        target=target,
        at=at,
    )
    return current, edition.organization, edition, decision


def _request_key_hash(idempotency_key: UUID) -> str:
    return hashlib.sha256(str(idempotency_key).encode("ascii")).hexdigest()


def _existing_receipt(
    *,
    actor: Account,
    operation: str,
    idempotency_key: UUID,
    organization_id: UUID,
    request_digest: str,
) -> LogisticsCommandReceipt | None:
    receipt = (
        LogisticsCommandReceipt.objects.select_for_update()
        .filter(actor=actor, operation=operation, idempotency_key=idempotency_key)
        .first()
    )
    if receipt is None:
        return None
    if (
        receipt.organization_id != organization_id
        or receipt.request_digest != request_digest
    ):
        raise LogisticsRetryConflictError
    return receipt


def _command_result(
    receipt: LogisticsCommandReceipt, *, replayed: bool
) -> LogisticsCommandResult:
    return LogisticsCommandResult(
        object_id=receipt.result_object_id,
        receipt_id=receipt.id,
        resulting_version=receipt.resulting_version,
        replayed=replayed,
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
) -> LogisticsCommandResult:
    with logistics_writer():
        receipt = LogisticsCommandReceipt.objects.create(
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
            operation=f"logistics.{operation}",
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
            retention_class="logistics-operational",
        ),
        occurred_at=occurred_at,
    )
    publish_domain_event(
        DomainEventRecord(
            event_name="logistics.record.changed.v1",
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
            retention_class="logistics-operational",
        ),
        occurred_at=occurred_at,
    )
    return _command_result(receipt, replayed=False)


def _subject_kwargs(subject: TrackedSubject) -> dict[str, TrackedSubject]:
    if isinstance(subject, Asset):
        return {"asset": subject}
    if isinstance(subject, StockLot):
        return {"stock_lot": subject}
    if isinstance(subject, PhysicalKey):
        return {"physical_key": subject}
    return {"node": subject}


def _subject_kind(subject: TrackedSubject) -> str:
    if isinstance(subject, Asset):
        return LogisticsEvent.SubjectKind.ASSET
    if isinstance(subject, StockLot):
        return LogisticsEvent.SubjectKind.STOCK_LOT
    if isinstance(subject, PhysicalKey):
        return LogisticsEvent.SubjectKind.KEY
    return LogisticsEvent.SubjectKind.NODE


def _subject_allocation_id(subject: TrackedSubject) -> UUID | None:
    if isinstance(subject, LogisticsNode):
        return subject.edition_id
    return subject.edition_allocation_id


def _require_subject_available_in_edition(
    *, subject: TrackedSubject, edition_id: UUID
) -> None:
    if _subject_allocation_id(subject) not in {None, edition_id}:
        raise LogisticsResourceUnavailableError


def _lock_subject(*, organization_id: UUID, locator: SubjectLocator) -> TrackedSubject:
    model_by_kind: Mapping[str, type[TrackedSubject]] = {
        LogisticsEvent.SubjectKind.ASSET: Asset,
        LogisticsEvent.SubjectKind.STOCK_LOT: StockLot,
        LogisticsEvent.SubjectKind.KEY: PhysicalKey,
        LogisticsEvent.SubjectKind.NODE: LogisticsNode,
    }
    model = model_by_kind.get(locator.kind)
    if model is None:
        raise ValidationError({"subject.kind": "Select a supported tracked kind."})
    subject = (
        model.objects.select_for_update()
        .filter(
            id=locator.object_id,
            organization_id=organization_id,
        )
        .first()
    )
    if subject is None:
        raise LogisticsResourceUnavailableError
    return subject


def _lock_current_state(subject: TrackedSubject) -> LogisticsCurrentState | None:
    return (
        LogisticsCurrentState.objects.select_for_update()
        .filter(**{f"{next(iter(_subject_kwargs(subject)))}_id": subject.id})
        .first()
    )


def _lock_containment_graph(organization_id: UUID) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"maru.logistics.containment:{organization_id}"],
        )


def _assert_acyclic_destination(
    *, subject: TrackedSubject, destination: LogisticsNode | None
) -> None:
    if not isinstance(subject, LogisticsNode) or destination is None:
        return
    if destination.id == subject.id:
        raise LogisticsContainmentCycleError
    visited = {subject.id}
    cursor_id: UUID | None = destination.id
    for _ in range(MAX_CONTAINMENT_DEPTH):
        if cursor_id is None:
            return
        if cursor_id in visited:
            raise LogisticsContainmentCycleError
        visited.add(cursor_id)
        row = (
            LogisticsCurrentState.objects.filter(node_id=cursor_id)
            .order_by()
            .values("current_node_id")
            .first()
        )
        cursor_id = row["current_node_id"] if row else None
    raise LogisticsContainmentCycleError


def _owner_values(
    *,
    actor: Account,
    organization: Organization,
    edition_id: UUID | None,
    owner_kind: str,
    owner_account_id: UUID | None,
    owner_party_id: UUID | None,
) -> dict[str, object]:
    if owner_kind == Asset.OwnerKind.ORGANIZATION:
        if owner_account_id or owner_party_id:
            raise ValidationError(
                {"owner": "Organizer ownership has no person or party."}
            )
        return {"owner_kind": owner_kind}
    if owner_kind == Asset.OwnerKind.ACCOUNT:
        if owner_account_id is None or owner_party_id:
            raise LogisticsResourceUnavailableError
        account = _lock_eligible_logistics_person(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition_id,
            account_id=owner_account_id,
        )
        return {"owner_kind": owner_kind, "owner_account": account}
    if owner_kind == Asset.OwnerKind.EXTERNAL_PARTY:
        party = (
            LogisticsParty.objects.select_for_update()
            .filter(
                id=cast("UUID", owner_party_id),
                organization=organization,
                lifecycle=LogisticsParty.Lifecycle.ACTIVE,
                role__in=(
                    LogisticsParty.Role.OWNER,
                    LogisticsParty.Role.MIXED,
                ),
            )
            .first()
        )
        if party is None or owner_account_id:
            raise LogisticsResourceUnavailableError
        return {"owner_kind": owner_kind, "owner_party": party}
    raise ValidationError({"owner_kind": "Select a supported ownership source."})


@transaction.atomic
def create_logistics_party(
    *,
    actor: Account,
    organization_id: UUID,
    code: str,
    profile: PartyProfile,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Create logistics party.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    code : str
        The stable machine-readable code.
    profile : PartyProfile
        The governed profile data.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, decision = _organization_context(
        actor=actor,
        organization_id=organization_id,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        at=occurred_at,
    )
    if profile.kind not in LogisticsParty.Kind.values:
        raise ValidationError({"kind": "Select a supported party kind."})
    if profile.role not in LogisticsParty.Role.values:
        raise ValidationError({"role": "Select a supported party role."})
    normalized: dict[str, object] = {
        "kind": profile.kind,
        "role": profile.role,
        "code": normalized_code(code),
    }
    for field_name, maximum, required in (
        ("legal_name", 240, True),
        ("public_name", 200, True),
        ("provider_reference", 240, False),
        ("website_url", 2_000, False),
    ):
        normalized[field_name] = normalized_text(
            getattr(profile, field_name),
            field=field_name,
            maximum=maximum,
            required=required,
            collapse=True,
        )
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest({**normalized, "reason": normalized_reason_value})
    replay = _existing_receipt(
        actor=actor,
        operation="party.create",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        party = LogisticsParty.objects.create(
            organization=organization,
            created_by=actor,
            last_modified_by=actor,
            **normalized,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=None,
        operation="party.create",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=party.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("profile", "provider_reference"),
        aggregate_type="logistics.party",
        aggregate_id=party.id,
        action="created",
        occurred_at=occurred_at,
    )


@transaction.atomic
def create_restricted_logistics_address(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    subject_account_id: UUID | None,
    party_id: UUID | None,
    purpose: str,
    label: str,
    recipient_name: str,
    postal_address: str,
    access_instructions: str,
    retention_until: datetime | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    contact_email: str = "",
    contact_phone: str = "",
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Create a purpose- and retention-bound address outside containment.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID | None
        The event edition identifier that scopes the operation.
    subject_account_id : UUID | None
        The subject account identifier within the requested scope.
    party_id : UUID | None
        The party identifier within the requested scope.
    purpose : str
        The documented purpose constraining collection and processing.
    label : str
        The human-readable label shown to authorized readers.
    recipient_name : str
        The human-readable recipient name shown to authorized readers.
    postal_address : str
        The postal address applied within the audited domain transition.
    access_instructions : str
        The access instructions applied within the audited domain transition.
    retention_until : datetime | None
        The timezone-aware boundary for retention until.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    contact_email : str, default=''
        The normalized contact email used for delivery or identity matching.
    contact_phone : str, default=''
        The normalized international contact phone, when provided.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='web'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The newly created LogisticsCommandResult.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _catalog_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=occurred_at,
    )
    if purpose not in RestrictedLogisticsAddress.Purpose.values:
        raise ValidationError({"purpose": "Select a supported address purpose."})
    if subject_account_id and party_id:
        raise ValidationError({"subject": "Name at most one address subject."})
    subject_account = None
    if subject_account_id:
        if edition is None or retention_until is None:
            raise LogisticsResourceUnavailableError
        subject_account = _lock_eligible_logistics_person(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition.id,
            account_id=subject_account_id,
        )
    party = None
    if party_id:
        party = (
            LogisticsParty.objects.select_for_update()
            .filter(
                id=party_id,
                organization=organization,
                lifecycle=LogisticsParty.Lifecycle.ACTIVE,
            )
            .first()
        )
        if party is None:
            raise LogisticsResourceUnavailableError
    if retention_until is not None and retention_until <= occurred_at:
        raise ValidationError({"retention_until": "Use a future retention time."})
    values = {
        "purpose": purpose,
        "label": normalized_text(
            label, field="label", maximum=200, required=True, collapse=True
        ),
        "recipient_name": normalized_text(
            recipient_name,
            field="recipient_name",
            maximum=240,
            collapse=True,
        ),
        "contact_email": normalized_text(
            contact_email,
            field="contact_email",
            maximum=254,
            collapse=True,
        ),
        "contact_phone": normalized_text(
            contact_phone,
            field="contact_phone",
            maximum=16,
            collapse=True,
        ),
        "postal_address": normalized_text(
            postal_address,
            field="postal_address",
            maximum=1_000,
            required=True,
        ),
        "access_instructions": normalized_text(
            access_instructions,
            field="access_instructions",
            maximum=5_000,
        ),
    }
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            **values,
            "edition_id": str(edition_id) if edition_id else None,
            "subject_account_id": str(subject_account_id)
            if subject_account_id
            else None,
            "party_id": str(party_id) if party_id else None,
            "retention_until": retention_until,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="restricted_address.create",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        address = RestrictedLogisticsAddress.objects.create(
            organization=organization,
            edition=edition,
            subject_account=subject_account,
            party=party,
            retention_until=retention_until,
            created_by=actor,
            **values,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="restricted_address.create",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=address.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("purpose", "subject", "address", "retention"),
        aggregate_type="logistics.restricted_address",
        aggregate_id=address.id,
        action="created",
        occurred_at=occurred_at,
    )


@transaction.atomic
def create_logistics_node(
    *,
    actor: Account,
    organization_id: UUID,
    kind: str,
    code: str,
    name: str,
    description: str,
    edition_id: UUID | None,
    storage_address_id: UUID | None,
    external_owner_id: UUID | None,
    provider_id: UUID | None,
    vehicle_registration: str,
    venue_space_selection_id: UUID | None,
    capacity_note: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Create logistics node.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    kind : str
        The closed kind code.
    code : str
        The stable machine-readable code.
    name : str
        The human-readable name.
    description : str
        The human-readable description.
    edition_id : UUID | None
        The identifier of the event edition that scopes the operation.
    storage_address_id : UUID | None
        The identifier of the storage address.
    external_owner_id : UUID | None
        The identifier of the external owner.
    provider_id : UUID | None
        The identifier of the provider.
    vehicle_registration : str
        The vehicle registration applied within the audited domain transition.
    venue_space_selection_id : UUID | None
        The identifier of the venue space selection.
    capacity_note : str
        The capacity note applied within the audited domain transition.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _catalog_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=occurred_at,
    )
    if kind not in LogisticsNode.Kind.values:
        raise ValidationError({"kind": "Select a supported logistics node kind."})
    address = None
    if storage_address_id:
        address = (
            RestrictedLogisticsAddress.objects.select_for_update()
            .filter(
                id=storage_address_id,
                organization=organization,
                purpose=RestrictedLogisticsAddress.Purpose.STORAGE,
                lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
            )
            .first()
        )
        if (
            address is None
            or (
                address.retention_until is not None
                and address.retention_until < occurred_at
            )
            or (
                address.edition_id
                not in ({None, edition.id} if edition is not None else {None})
            )
        ):
            raise LogisticsResourceUnavailableError
    venue_space = None
    if venue_space_selection_id is not None:
        if kind != LogisticsNode.Kind.VENUE_ROOM or edition is None:
            raise LogisticsResourceUnavailableError
        venue_space = (
            EditionSpaceSelection.objects.select_for_update()
            .filter(
                id=venue_space_selection_id,
                organization=organization,
                edition=edition,
                lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
            )
            .only("id")
            .first()
        )
        if venue_space is None:
            raise LogisticsResourceUnavailableError
    parties = {
        party.id: party
        for party in LogisticsParty.objects.select_for_update().filter(
            organization=organization,
            id__in={
                party_id
                for party_id in (external_owner_id, provider_id)
                if party_id is not None
            },
            lifecycle=LogisticsParty.Lifecycle.ACTIVE,
        )
    }
    if external_owner_id and external_owner_id not in parties:
        raise LogisticsResourceUnavailableError
    if provider_id and provider_id not in parties:
        raise LogisticsResourceUnavailableError
    external_owner = parties.get(cast("UUID", external_owner_id))
    if external_owner is not None and external_owner.role not in {
        LogisticsParty.Role.OWNER,
        LogisticsParty.Role.MIXED,
    }:
        raise LogisticsResourceUnavailableError
    provider = parties.get(cast("UUID", provider_id))
    if provider is not None and provider.role not in {
        LogisticsParty.Role.OWNER,
        LogisticsParty.Role.PROVIDER,
        LogisticsParty.Role.RENTAL_BUSINESS,
        LogisticsParty.Role.MIXED,
    }:
        raise LogisticsResourceUnavailableError
    values: dict[str, object] = {
        "kind": kind,
        "code": normalized_code(code),
        "name": normalized_text(
            name,
            field="name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "description": normalized_text(
            description,
            field="description",
            maximum=2_000,
        ),
        "vehicle_registration": normalized_text(
            vehicle_registration,
            field="vehicle_registration",
            maximum=40,
            collapse=True,
        ),
        "capacity_note": normalized_text(
            capacity_note,
            field="capacity_note",
            maximum=500,
            collapse=True,
        ),
    }
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            **values,
            "edition_id": str(edition_id) if edition_id else None,
            "storage_address_id": str(storage_address_id)
            if storage_address_id
            else None,
            "external_owner_id": str(external_owner_id) if external_owner_id else None,
            "provider_id": str(provider_id) if provider_id else None,
            "venue_space_selection_id": (
                str(venue_space_selection_id) if venue_space_selection_id else None
            ),
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="node.create",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        node = LogisticsNode.objects.create(
            organization=organization,
            edition=edition,
            storage_address=address,
            external_owner=parties.get(cast("UUID", external_owner_id)),
            provider=parties.get(cast("UUID", provider_id)),
            venue_space_selection_id=(venue_space.id if venue_space else None),
            created_by=actor,
            last_modified_by=actor,
            **values,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="node.create",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=node.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("identity", "type", "provider", "edition_allocation"),
        aggregate_type="logistics.node",
        aggregate_id=node.id,
        action="created",
        occurred_at=occurred_at,
    )


def _inventory_context(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    at: datetime,
) -> tuple[Account, Organization, EventEdition | None, PolicyDecision]:
    return _catalog_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=at,
    )


@transaction.atomic
def register_serialized_asset(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    catalog_code: str,
    name: str,
    asset_type: str,
    manufacturer: str,
    model_name: str,
    serial_number: str,
    acquisition: str,
    value_class: str,
    owner_kind: str,
    owner_account_id: UUID | None,
    owner_party_id: UUID | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Register serialized asset.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID | None
        The identifier of the event edition that scopes the operation.
    catalog_code : str
        The stable catalog code from the relevant closed catalog.
    name : str
        The human-readable name.
    asset_type : str
        The closed asset type discriminator defined by the domain catalog.
    manufacturer : str
        The manufacturer applied within the audited domain transition.
    model_name : str
        The human-readable model name shown to authorized readers.
    serial_number : str
        The serial number applied within the audited domain transition.
    acquisition : str
        The acquisition applied within the audited domain transition.
    value_class : str
        The value class applied within the audited domain transition.
    owner_kind : str
        The closed owner kind discriminator defined by the domain catalog.
    owner_account_id : UUID | None
        The identifier of the owner account.
    owner_party_id : UUID | None
        The identifier of the owner party.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The logistics command result.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _inventory_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=occurred_at,
    )
    if acquisition not in Asset.Acquisition.values:
        raise ValidationError({"acquisition": "Select a supported acquisition kind."})
    owner_values = _owner_values(
        actor=actor,
        organization=organization,
        edition_id=edition_id,
        owner_kind=owner_kind,
        owner_account_id=owner_account_id,
        owner_party_id=owner_party_id,
    )
    values = {
        "catalog_code": normalized_code(catalog_code, field="catalog_code"),
        "name": normalized_text(
            name, field="name", maximum=200, required=True, collapse=True
        ),
        "asset_type": normalized_text(
            asset_type,
            field="asset_type",
            maximum=120,
            required=True,
            collapse=True,
        ),
        "manufacturer": normalized_text(
            manufacturer, field="manufacturer", maximum=160, collapse=True
        ),
        "model_name": normalized_text(
            model_name, field="model_name", maximum=160, collapse=True
        ),
        "serial_number": normalized_text(
            serial_number, field="serial_number", maximum=200, collapse=True
        ),
        "acquisition": acquisition,
        "value_class": normalized_text(
            value_class, field="value_class", maximum=32, collapse=True
        ),
    }
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            **values,
            "edition_id": str(edition_id) if edition_id else None,
            "owner_kind": owner_kind,
            "owner_account_id": str(owner_account_id) if owner_account_id else None,
            "owner_party_id": str(owner_party_id) if owner_party_id else None,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="asset.register",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        asset = Asset.objects.create(
            organization=organization,
            edition_allocation=edition,
            created_by=actor,
            **owner_values,
            **values,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="asset.register",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=asset.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("identity", "ownership", "edition_allocation"),
        aggregate_type="logistics.asset",
        aggregate_id=asset.id,
        action="registered",
        occurred_at=occurred_at,
    )


@transaction.atomic
def register_stock_lot(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    catalog_code: str,
    name: str,
    stock_type: str,
    unit: str,
    initial_quantity: int,
    value_class: str,
    owner_kind: str,
    owner_account_id: UUID | None,
    owner_party_id: UUID | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Register stock lot.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID | None
        The identifier of the event edition that scopes the operation.
    catalog_code : str
        The stable catalog code from the relevant closed catalog.
    name : str
        The human-readable name.
    stock_type : str
        The closed stock type discriminator defined by the domain catalog.
    unit : str
        The unit applied within the audited domain transition.
    initial_quantity : int
        The non-negative hard limit or requested amount for initial quantity.
    value_class : str
        The value class applied within the audited domain transition.
    owner_kind : str
        The closed owner kind discriminator defined by the domain catalog.
    owner_account_id : UUID | None
        The identifier of the owner account.
    owner_party_id : UUID | None
        The identifier of the owner party.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The logistics command result.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _inventory_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=occurred_at,
    )
    if (
        not isinstance(initial_quantity, int)
        or isinstance(initial_quantity, bool)
        or not 1 <= initial_quantity <= MAX_TRACKED_QUANTITY
    ):
        raise ValidationError(
            {"initial_quantity": "Enter a bounded positive quantity."}
        )
    owner_values = _owner_values(
        actor=actor,
        organization=organization,
        edition_id=edition_id,
        owner_kind=owner_kind,
        owner_account_id=owner_account_id,
        owner_party_id=owner_party_id,
    )
    values = {
        "catalog_code": normalized_code(catalog_code, field="catalog_code"),
        "name": normalized_text(
            name, field="name", maximum=200, required=True, collapse=True
        ),
        "stock_type": normalized_text(
            stock_type,
            field="stock_type",
            maximum=120,
            required=True,
            collapse=True,
        ),
        "unit": normalized_text(
            unit, field="unit", maximum=40, required=True, collapse=True
        ),
        "initial_quantity": initial_quantity,
        "value_class": normalized_text(
            value_class, field="value_class", maximum=32, collapse=True
        ),
    }
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            **values,
            "edition_id": str(edition_id) if edition_id else None,
            "owner_kind": owner_kind,
            "owner_account_id": str(owner_account_id) if owner_account_id else None,
            "owner_party_id": str(owner_party_id) if owner_party_id else None,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="stock_lot.register",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        stock_lot = StockLot.objects.create(
            organization=organization,
            edition_allocation=edition,
            created_by=actor,
            **owner_values,
            **values,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="stock_lot.register",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=stock_lot.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("identity", "ownership", "registered_quantity"),
        aggregate_type="logistics.stock_lot",
        aggregate_id=stock_lot.id,
        action="registered",
        occurred_at=occurred_at,
    )


@transaction.atomic
def register_physical_key(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    code: str,
    label: str,
    opens_node_id: UUID,
    provider_id: UUID | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Register a physical key without granting its holder software access.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID | None
        The event edition identifier that scopes the operation.
    code : str
        The stable domain code to resolve or validate.
    label : str
        The human-readable label shown to authorized readers.
    opens_node_id : UUID
        The opens node identifier within the requested scope.
    provider_id : UUID | None
        The provider identifier within the requested scope.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='web'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The resolved LogisticsCommandResult for register physical key.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _inventory_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=occurred_at,
    )
    opens_node = (
        LogisticsNode.objects.select_for_update()
        .filter(id=opens_node_id, organization=organization)
        .first()
    )
    if opens_node is None or opens_node.edition_id not in {None, edition_id}:
        raise LogisticsResourceUnavailableError
    provider = None
    if provider_id:
        provider = (
            LogisticsParty.objects.select_for_update()
            .filter(
                id=provider_id,
                organization=organization,
                lifecycle=LogisticsParty.Lifecycle.ACTIVE,
                role__in=(
                    LogisticsParty.Role.OWNER,
                    LogisticsParty.Role.PROVIDER,
                    LogisticsParty.Role.RENTAL_BUSINESS,
                    LogisticsParty.Role.MIXED,
                ),
            )
            .first()
        )
        if provider is None:
            raise LogisticsResourceUnavailableError
    values = {
        "code": normalized_code(code),
        "label": normalized_text(
            label,
            field="label",
            maximum=200,
            required=True,
            collapse=True,
        ),
    }
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            **values,
            "edition_id": str(edition_id) if edition_id else None,
            "opens_node_id": str(opens_node_id),
            "provider_id": str(provider_id) if provider_id else None,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="physical_key.register",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        key = PhysicalKey.objects.create(
            organization=organization,
            edition_allocation=edition,
            opens_node=opens_node,
            provider=provider,
            created_by=actor,
            **values,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="physical_key.register",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=key.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("identity", "lock", "provider", "edition_allocation"),
        aggregate_type="logistics.physical_key",
        aggregate_id=key.id,
        action="registered",
        occurred_at=occurred_at,
    )


@transaction.atomic
def create_logistics_label(
    *,
    actor: Account,
    organization_id: UUID,
    subject: SubjectLocator,
    label_code: str,
    qr_identifier: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Create a public label while retaining only the QR token digest.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    subject : SubjectLocator
        The tenant-scoped person or resource governed by the operation.
    label_code : str
        The stable label code from the relevant closed catalog.
    qr_identifier : str
        The qr identifier applied within the audited domain transition.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='web'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The newly created LogisticsCommandResult.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, decision = _organization_context(
        actor=actor,
        organization_id=organization_id,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        at=occurred_at,
    )
    tracked = _lock_subject(organization_id=organization_id, locator=subject)
    normalized_label = normalized_label_code(label_code)
    normalized_qr = normalized_text(
        qr_identifier,
        field="qr_identifier",
        maximum=512,
        required=True,
    )
    if len(normalized_qr) < MIN_QR_IDENTIFIER_LENGTH:
        raise ValidationError(
            {
                "qr_identifier": (
                    "Use an unguessable identifier of at least 24 characters."
                )
            }
        )
    qr_digest = hashlib.sha256(normalized_qr.encode("utf-8")).hexdigest()
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "subject": asdict(subject),
            "label_code": normalized_label,
            "qr_identifier_digest": qr_digest,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="label.create",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        label = LogisticsLabel.objects.create(
            organization=organization,
            label_code=normalized_label,
            qr_identifier_digest=qr_digest,
            created_by=actor,
            **_subject_kwargs(tracked),
        )
    edition = getattr(tracked, "edition_allocation", None) or getattr(
        tracked, "edition", None
    )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="label.create",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=label.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("label_code", "qr_identifier_digest", "subject"),
        aggregate_type="logistics.label",
        aggregate_id=label.id,
        action="created",
        occurred_at=occurred_at,
    )


@transaction.atomic
def assign_keyholder_responsibility(
    *,
    actor: Account,
    organization_id: UUID,
    key_id: UUID,
    responsible_account_id: UUID,
    starts_at: datetime,
    ends_at: datetime | None,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Record physical-key responsibility; this never changes authorization.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    key_id : UUID
        The key identifier within the requested scope.
    responsible_account_id : UUID
        The responsible account identifier within the requested scope.
    starts_at : datetime
        The timezone-aware timestamp for starts.
    ends_at : datetime | None
        The timezone-aware timestamp for ends.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='web'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The resolved LogisticsCommandResult for assign keyholder responsibility.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    LogisticsStateConflictError
        If the target lifecycle state does not permit the transition.
    LogisticsVersionConflictError
        If the supplied aggregate version is stale.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    expected_version = _require_expected_version(expected_version)
    occurred_at = now or timezone.now()
    actor, organization, decision = _organization_context(
        actor=actor,
        organization_id=organization_id,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        at=occurred_at,
    )
    key = (
        PhysicalKey.objects.select_for_update(of=("self",))
        .select_related("edition_allocation")
        .filter(id=key_id, organization=organization)
        .first()
    )
    if key is None:
        raise LogisticsResourceUnavailableError
    if key.aggregate_version != expected_version:
        raise LogisticsVersionConflictError
    responsible = _lock_eligible_logistics_person(
        actor=actor,
        organization_id=organization_id,
        edition_id=key.edition_allocation_id,
        account_id=responsible_account_id,
    )
    if ends_at is not None and ends_at <= starts_at:
        raise ValidationError({"ends_at": "The end must follow the start."})
    overlapping_responsibilities = (
        KeyholderResponsibility.objects.select_for_update()
        .filter(
            key=key,
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=starts_at))
    )
    if ends_at is not None:
        overlapping_responsibilities = overlapping_responsibilities.filter(
            starts_at__lt=ends_at
        )
    if overlapping_responsibilities.exists():
        raise LogisticsStateConflictError
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "key_id": str(key_id),
            "responsible_account_id": str(responsible_account_id),
            "starts_at": starts_at,
            "ends_at": ends_at,
            "expected_version": expected_version,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="keyholder.assign",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        KeyholderResponsibility.objects.create(
            key=key,
            responsible_account=responsible,
            starts_at=starts_at,
            ends_at=ends_at,
            assigned_by=actor,
            reason=normalized_reason_value,
        )
        key.aggregate_version += 1
        key.save(update_fields=("aggregate_version", "updated_at"))
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=key.edition_allocation,
        operation="keyholder.assign",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=key.id,
        resulting_version=key.aggregate_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("physical_responsibility",),
        aggregate_type="logistics.physical_key",
        aggregate_id=key.id,
        action="responsibility_assigned",
        occurred_at=occurred_at,
    )


def _agreement_party_values(
    *,
    actor: Account,
    organization: Organization,
    edition_id: UUID | None,
    extra_eligible_ids: frozenset[UUID],
    provider_account_id: UUID | None,
    provider_party_id: UUID | None,
    borrower_account_id: UUID | None,
    borrower_party_id: UUID | None,
) -> dict[str, object]:
    if bool(provider_account_id) == bool(provider_party_id):
        raise ValidationError({"provider": "Name exactly one provider."})
    if borrower_account_id and borrower_party_id:
        raise ValidationError({"borrower": "Name at most one external borrower."})
    account_ids = {
        account_id
        for account_id in (provider_account_id, borrower_account_id)
        if account_id is not None
    }
    accounts = {
        account_id: _lock_eligible_logistics_person(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition_id,
            account_id=account_id,
            extra_eligible_ids=extra_eligible_ids,
        )
        for account_id in account_ids
    }
    party_ids = {
        party_id
        for party_id in (provider_party_id, borrower_party_id)
        if party_id is not None
    }
    parties = {
        party.id: party
        for party in LogisticsParty.objects.select_for_update().filter(
            id__in=party_ids,
            organization=organization,
            lifecycle=LogisticsParty.Lifecycle.ACTIVE,
        )
    }
    if any(party_id not in parties for party_id in party_ids):
        raise LogisticsResourceUnavailableError
    provider_party = parties.get(cast("UUID", provider_party_id))
    if provider_party is not None and provider_party.role not in {
        LogisticsParty.Role.OWNER,
        LogisticsParty.Role.PROVIDER,
        LogisticsParty.Role.RENTAL_BUSINESS,
        LogisticsParty.Role.MIXED,
    }:
        raise LogisticsResourceUnavailableError
    borrower_party = parties.get(cast("UUID", borrower_party_id))
    if borrower_party is not None and borrower_party.role not in {
        LogisticsParty.Role.BORROWER,
        LogisticsParty.Role.MIXED,
    }:
        raise LogisticsResourceUnavailableError
    return {
        "provider_account": accounts.get(cast("UUID", provider_account_id)),
        "provider": provider_party,
        "borrower_account": accounts.get(cast("UUID", borrower_account_id)),
        "borrower_party": borrower_party,
    }


@transaction.atomic
def record_asset_agreement(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    subject: SubjectLocator,
    kind: str,
    provider_account_id: UUID | None,
    provider_party_id: UUID | None,
    borrower_account_id: UUID | None,
    borrower_party_id: UUID | None,
    starts_at: datetime,
    ends_at: datetime,
    return_due_at: datetime,
    return_address_id: UUID | None,
    provider_reference: str,
    terms_reference: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Record asset agreement.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID | None
        The identifier of the event edition that scopes the operation.
    subject : SubjectLocator
        The tenant-scoped person or resource governed by the operation.
    kind : str
        The closed kind code.
    provider_account_id : UUID | None
        The identifier of the provider account.
    provider_party_id : UUID | None
        The identifier of the provider party.
    borrower_account_id : UUID | None
        The identifier of the borrower account.
    borrower_party_id : UUID | None
        The identifier of the borrower party.
    starts_at : datetime
        The timezone-aware timestamp for starts.
    ends_at : datetime
        The timezone-aware timestamp for ends.
    return_due_at : datetime
        The timezone-aware timestamp for return due.
    return_address_id : UUID | None
        The identifier of the return address.
    provider_reference : str
        The provider-owned external reference.
    terms_reference : str
        The provider or source terms reference retained for reconciliation.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The logistics command result.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    LogisticsStateConflictError
        If the target lifecycle state does not permit the transition.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _inventory_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=occurred_at,
    )
    if kind not in AssetAgreement.Kind.values:
        raise ValidationError({"kind": "Select loan or rental."})
    if ends_at <= starts_at or return_due_at < starts_at:
        raise ValidationError({"interval": "Enter a valid agreement interval."})
    tracked = _lock_subject(organization_id=organization_id, locator=subject)
    subject_edition_id = getattr(tracked, "edition_allocation_id", None) or getattr(
        tracked, "edition_id", None
    )
    if subject_edition_id and subject_edition_id != edition_id:
        raise LogisticsResourceUnavailableError
    subject_field = next(iter(_subject_kwargs(tracked)))
    overlapping_agreements = (
        AssetAgreement.objects.select_for_update()
        .filter(
            **{subject_field: tracked},
            starts_at__lt=ends_at,
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=starts_at))
    )
    if overlapping_agreements.exists():
        raise LogisticsStateConflictError
    party_values = _agreement_party_values(
        actor=actor,
        organization=organization,
        edition_id=edition_id,
        extra_eligible_ids=frozenset(
            account_id
            for account_id in (getattr(tracked, "owner_account_id", None),)
            if account_id is not None
        ),
        provider_account_id=provider_account_id,
        provider_party_id=provider_party_id,
        borrower_account_id=borrower_account_id,
        borrower_party_id=borrower_party_id,
    )
    return_address = None
    if return_address_id:
        return_address = (
            RestrictedLogisticsAddress.objects.select_for_update()
            .filter(
                id=return_address_id,
                organization=organization,
                purpose=RestrictedLogisticsAddress.Purpose.RETURN,
                lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
                retention_until__gte=return_due_at,
            )
            .first()
        )
        if return_address is None or (
            return_address.edition_id and return_address.edition_id != edition_id
        ):
            raise LogisticsResourceUnavailableError
    values = {
        "provider_reference": normalized_text(
            provider_reference,
            field="provider_reference",
            maximum=240,
            collapse=True,
        ),
        "terms_reference": normalized_text(
            terms_reference,
            field="terms_reference",
            maximum=1_000,
        ),
    }
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "edition_id": str(edition_id) if edition_id else None,
            "subject": asdict(subject),
            "kind": kind,
            "provider_account_id": str(provider_account_id)
            if provider_account_id
            else None,
            "provider_party_id": str(provider_party_id) if provider_party_id else None,
            "borrower_account_id": str(borrower_account_id)
            if borrower_account_id
            else None,
            "borrower_party_id": str(borrower_party_id) if borrower_party_id else None,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "return_due_at": return_due_at,
            "return_address_id": str(return_address_id) if return_address_id else None,
            **values,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="agreement.record",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        agreement = AssetAgreement.objects.create(
            organization=organization,
            edition=edition,
            kind=kind,
            starts_at=starts_at,
            ends_at=ends_at,
            return_due_at=return_due_at,
            return_address=return_address,
            created_by=actor,
            **_subject_kwargs(tracked),
            **party_values,
            **values,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="agreement.record",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=agreement.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("subject", "provider", "borrower", "interval", "return_due"),
        aggregate_type="logistics.agreement",
        aggregate_id=agreement.id,
        action="recorded",
        occurred_at=occurred_at,
    )


@transaction.atomic
def create_reusable_kit(
    *,
    actor: Account,
    organization_id: UUID,
    code: str,
    name: str,
    description: str,
    lines: Sequence[KitLineInput],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Create reusable kit.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    code : str
        The stable machine-readable code.
    name : str
        The human-readable name.
    description : str
        The human-readable description.
    lines : Sequence[KitLineInput]
        The ordered line items to process.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, decision = _organization_context(
        actor=actor,
        organization_id=organization_id,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        at=occurred_at,
    )
    if not 1 <= len(lines) <= MAX_KIT_LINES:
        raise ValidationError(
            {"lines": f"Provide between 1 and {MAX_KIT_LINES} kit lines."}
        )
    normalized_lines: list[tuple[TrackedSubject, int, str]] = []
    seen: set[tuple[str, UUID]] = set()
    for index, line in enumerate(lines):
        if line.subject.kind == LogisticsEvent.SubjectKind.NODE:
            raise ValidationError(
                {f"lines.{index}.subject": "Kits contain items, not locations."}
            )
        subject = _lock_subject(
            organization_id=organization_id,
            locator=line.subject,
        )
        subject_key = (line.subject.kind, subject.id)
        if subject_key in seen:
            raise ValidationError({f"lines.{index}": "Duplicate kit item."})
        seen.add(subject_key)
        if (
            not isinstance(line.quantity, int)
            or isinstance(line.quantity, bool)
            or not 1 <= line.quantity <= MAX_TRACKED_QUANTITY
        ):
            raise ValidationError(
                {f"lines.{index}.quantity": "Enter a bounded positive quantity."}
            )
        if not isinstance(subject, StockLot) and line.quantity != 1:
            raise ValidationError(
                {f"lines.{index}.quantity": "Serialized kit items have quantity one."}
            )
        normalized_lines.append(
            (
                subject,
                line.quantity,
                normalized_text(
                    line.notes,
                    field=f"lines.{index}.notes",
                    maximum=500,
                ),
            )
        )
    values = {
        "code": normalized_code(code),
        "name": normalized_text(
            name,
            field="name",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "description": normalized_text(
            description,
            field="description",
            maximum=2_000,
        ),
    }
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            **values,
            "lines": [
                {
                    "kind": _subject_kind(subject),
                    "object_id": str(subject.id),
                    "quantity": quantity,
                    "notes": notes,
                }
                for subject, quantity, notes in normalized_lines
            ],
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="kit.create",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        kit = ReusableKit.objects.create(
            organization=organization,
            created_by=actor,
            declared_line_count=len(normalized_lines),
            **values,
        )
        for subject, quantity, notes in normalized_lines:
            ReusableKitLine.objects.create(
                kit=kit,
                quantity=quantity,
                notes=notes,
                **_subject_kwargs(subject),
            )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=None,
        operation="kit.create",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=kit.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("identity", "contents"),
        aggregate_type="logistics.kit",
        aggregate_id=kit.id,
        action="created",
        occurred_at=occurred_at,
    )


def _manifest_subject_values(subject: TrackedSubject) -> dict[str, TrackedSubject]:
    return _subject_kwargs(subject)


def _subject_display_label(subject: TrackedSubject) -> str:
    if isinstance(subject, Asset):
        return subject.name
    if isinstance(subject, StockLot):
        return subject.name
    if isinstance(subject, PhysicalKey):
        return subject.label
    return subject.name


def _state_within_node(*, state: LogisticsCurrentState, expected_node_id: UUID) -> bool:
    cursor_id = state.current_node_id
    visited: set[UUID] = set()
    for _ in range(MAX_CONTAINMENT_DEPTH):
        if cursor_id is None:
            return False
        if cursor_id == expected_node_id:
            return True
        if cursor_id in visited:
            return False
        visited.add(cursor_id)
        row = (
            LogisticsCurrentState.objects.filter(node_id=cursor_id)
            .order_by()
            .values("current_node_id")
            .first()
        )
        cursor_id = row["current_node_id"] if row else None
    return False


@transaction.atomic
def create_logistics_manifest(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    responsible_department_id: UUID,
    manifest_number: str,
    kind: str,
    title: str,
    source_node_id: UUID | None,
    destination_node_id: UUID | None,
    vehicle_id: UUID | None,
    provider_id: UUID | None,
    loading_starts_at: datetime | None,
    loading_ends_at: datetime | None,
    lines: Sequence[ManifestLineInput],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Create logistics manifest.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    responsible_department_id : UUID
        The identifier of the responsible department.
    manifest_number : str
        The manifest number applied within the audited domain transition.
    kind : str
        The closed kind code.
    title : str
        The human-readable title.
    source_node_id : UUID | None
        The identifier of the source node.
    destination_node_id : UUID | None
        The identifier of the destination node.
    vehicle_id : UUID | None
        The identifier of the vehicle.
    provider_id : UUID | None
        The identifier of the provider.
    loading_starts_at : datetime | None
        The timezone-aware timestamp for loading starts.
    loading_ends_at : datetime | None
        The timezone-aware timestamp for loading ends.
    lines : Sequence[ManifestLineInput]
        The ordered line items to process.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The persisted record after validation and transaction commit.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _edition_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
        at=occurred_at,
    )
    if kind not in LogisticsManifest.Kind.values:
        raise ValidationError({"kind": "Select a supported manifest kind."})
    if not 1 <= len(lines) <= MAX_MANIFEST_LINES:
        raise ValidationError(
            {"lines": f"Create a manifest with 1 to {MAX_MANIFEST_LINES} lines."}
        )
    department = (
        Department.objects.select_for_update()
        .filter(
            id=responsible_department_id,
            organization=organization,
            edition=edition,
            retired_at__isnull=True,
        )
        .first()
    )
    if department is None:
        raise LogisticsResourceUnavailableError
    node_ids = {
        value
        for value in (source_node_id, destination_node_id, vehicle_id)
        if value is not None
    }
    nodes = {
        node.id: node
        for node in LogisticsNode.objects.select_for_update()
        .filter(id__in=node_ids, organization=organization)
        .order_by("id")
    }
    if len(nodes) != len(node_ids) or any(
        node.edition_id not in {None, edition_id} for node in nodes.values()
    ):
        raise LogisticsResourceUnavailableError
    vehicle = nodes.get(cast("UUID", vehicle_id))
    if vehicle is not None and vehicle.kind != LogisticsNode.Kind.VEHICLE:
        raise ValidationError({"vehicle_id": "Select a tracked vehicle node."})
    provider = None
    if provider_id:
        provider = (
            LogisticsParty.objects.select_for_update()
            .filter(
                id=provider_id,
                organization=organization,
                lifecycle=LogisticsParty.Lifecycle.ACTIVE,
                role__in=(
                    LogisticsParty.Role.OWNER,
                    LogisticsParty.Role.PROVIDER,
                    LogisticsParty.Role.RENTAL_BUSINESS,
                    LogisticsParty.Role.MIXED,
                ),
            )
            .first()
        )
        if provider is None:
            raise LogisticsResourceUnavailableError
    if (loading_starts_at is None) != (loading_ends_at is None):
        raise ValidationError(
            {"loading_window": "Enter both loading times or neither."}
        )
    if (
        loading_starts_at is not None
        and loading_ends_at is not None
        and loading_ends_at <= loading_starts_at
    ):
        raise ValidationError({"loading_ends_at": "End loading after it starts."})
    normalized_number = normalized_text(
        manifest_number,
        field="manifest_number",
        maximum=96,
        required=True,
        collapse=True,
    )
    normalized_title = normalized_text(
        title,
        field="title",
        maximum=200,
        required=True,
        collapse=True,
    )
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    line_values: list[tuple[TrackedSubject, LogisticsNode | None, int, str]] = []
    seen_subjects: set[tuple[str, UUID]] = set()
    for position, line in enumerate(lines):
        subject = _lock_subject(
            organization_id=organization_id,
            locator=line.subject,
        )
        _require_subject_available_in_edition(
            subject=subject,
            edition_id=edition_id,
        )
        key = (_subject_kind(subject), subject.id)
        if key in seen_subjects:
            raise ValidationError(
                {f"lines.{position}.subject": "A manifest subject appears once."}
            )
        seen_subjects.add(key)
        if (
            not isinstance(line.quantity, int)
            or isinstance(line.quantity, bool)
            or line.quantity < 1
            or line.quantity > MAX_TRACKED_QUANTITY
            or (not isinstance(subject, StockLot) and line.quantity != 1)
        ):
            raise ValidationError(
                {f"lines.{position}.quantity": "Enter a valid manifest quantity."}
            )
        packed_in = None
        if line.packed_in_node_id:
            packed_in = (
                LogisticsNode.objects.select_for_update()
                .filter(
                    id=line.packed_in_node_id,
                    organization=organization,
                    kind__in=(
                        LogisticsNode.Kind.BOX,
                        LogisticsNode.Kind.CONTAINER,
                        LogisticsNode.Kind.VEHICLE,
                    ),
                )
                .first()
            )
            if packed_in is None:
                raise LogisticsResourceUnavailableError
            if packed_in.edition_id not in {None, edition_id}:
                raise LogisticsResourceUnavailableError
        line_values.append(
            (
                subject,
                packed_in,
                line.quantity,
                normalized_text(
                    line.notes,
                    field=f"lines.{position}.notes",
                    maximum=500,
                    collapse=True,
                ),
            )
        )
    request_digest = canonical_digest(
        {
            "edition_id": str(edition_id),
            "department_id": str(responsible_department_id),
            "manifest_number": normalized_number,
            "kind": kind,
            "title": normalized_title,
            "source_node_id": str(source_node_id) if source_node_id else None,
            "destination_node_id": (
                str(destination_node_id) if destination_node_id else None
            ),
            "vehicle_id": str(vehicle_id) if vehicle_id else None,
            "provider_id": str(provider_id) if provider_id else None,
            "loading_starts_at": (
                loading_starts_at.isoformat() if loading_starts_at else None
            ),
            "loading_ends_at": (
                loading_ends_at.isoformat() if loading_ends_at else None
            ),
            "lines": [
                {
                    "subject_kind": _subject_kind(subject),
                    "subject_id": str(subject.id),
                    "quantity": quantity,
                    "packed_in_node_id": str(packed_in.id) if packed_in else None,
                    "notes": notes,
                }
                for subject, packed_in, quantity, notes in line_values
            ],
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="manifest.create",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        manifest = LogisticsManifest.objects.create(
            organization=organization,
            edition=edition,
            responsible_department=department,
            manifest_number=normalized_number,
            kind=kind,
            title=normalized_title,
            line_count=len(line_values),
            source_node=nodes.get(cast("UUID", source_node_id)),
            destination_node=nodes.get(cast("UUID", destination_node_id)),
            vehicle=vehicle,
            provider=provider,
            loading_starts_at=loading_starts_at,
            loading_ends_at=loading_ends_at,
            created_by=actor,
            last_modified_by=actor,
        )
        for subject, packed_in, quantity, notes in line_values:
            LogisticsManifestLine.objects.create(
                manifest=manifest,
                subject_kind=_subject_kind(subject),
                packed_in_node=packed_in,
                quantity=quantity,
                label_snapshot=_subject_display_label(subject),
                notes=notes,
                **_manifest_subject_values(subject),
            )
    ensure_logistics_manifest_binding(manifest=manifest)
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="manifest.create",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=manifest.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("identity", "route", "loading_window", "lines"),
        aggregate_type="logistics.manifest",
        aggregate_id=manifest.id,
        action="created",
        occurred_at=occurred_at,
    )


@transaction.atomic
def add_manifest_line(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    manifest_id: UUID,
    expected_version: int,
    line: ManifestLineInput,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Append one subject to a draft manifest and advance its version.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    manifest_id : UUID
        The manifest identifier within the requested scope.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    line : ManifestLineInput
        The line applied within the audited domain transition.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='web'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The resolved LogisticsCommandResult for add manifest line.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    LogisticsStateConflictError
        If the target lifecycle state does not permit the transition.
    LogisticsVersionConflictError
        If the supplied aggregate version is stale.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    expected_version = _require_expected_version(expected_version)
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _manifest_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        manifest_id=manifest_id,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
        at=occurred_at,
    )
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    if (
        not isinstance(line.quantity, int)
        or isinstance(line.quantity, bool)
        or line.quantity < 1
        or line.quantity > MAX_TRACKED_QUANTITY
    ):
        raise ValidationError({"line.quantity": "Enter a valid manifest quantity."})
    notes = normalized_text(
        line.notes,
        field="line.notes",
        maximum=500,
        collapse=True,
    )
    request_digest = canonical_digest(
        {
            "manifest_id": str(manifest_id),
            "expected_version": expected_version,
            "line": {
                "subject_kind": line.subject.kind,
                "subject_id": str(line.subject.object_id),
                "quantity": line.quantity,
                "packed_in_node_id": (
                    str(line.packed_in_node_id) if line.packed_in_node_id else None
                ),
                "notes": notes,
            },
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="manifest.line.add",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    manifest = (
        LogisticsManifest.objects.select_for_update()
        .filter(id=manifest_id, organization=organization, edition=edition)
        .first()
    )
    if manifest is None:
        raise LogisticsResourceUnavailableError
    if manifest.aggregate_version != expected_version:
        raise LogisticsVersionConflictError
    if manifest.status != LogisticsManifest.Status.DRAFT:
        raise LogisticsStateConflictError
    if manifest.line_count >= MAX_MANIFEST_LINES:
        raise LogisticsStateConflictError
    subject = _lock_subject(
        organization_id=organization_id,
        locator=line.subject,
    )
    _require_subject_available_in_edition(
        subject=subject,
        edition_id=edition_id,
    )
    if not isinstance(subject, StockLot) and line.quantity != 1:
        raise ValidationError(
            {"line.quantity": "Serialized manifest items have quantity one."}
        )
    subject_values = _manifest_subject_values(subject)
    subject_field = next(iter(subject_values))
    if LogisticsManifestLine.objects.filter(
        manifest=manifest,
        **{f"{subject_field}_id": subject.id},
    ).exists():
        raise LogisticsStateConflictError
    packed_in = None
    if line.packed_in_node_id is not None:
        packed_in = (
            LogisticsNode.objects.select_for_update()
            .filter(
                id=line.packed_in_node_id,
                organization=organization,
                kind__in=(
                    LogisticsNode.Kind.BOX,
                    LogisticsNode.Kind.CONTAINER,
                    LogisticsNode.Kind.VEHICLE,
                ),
            )
            .first()
        )
        if packed_in is None or packed_in.edition_id not in {None, edition_id}:
            raise LogisticsResourceUnavailableError
    new_version = expected_version + 1
    with logistics_writer():
        LogisticsManifestLine.objects.create(
            manifest=manifest,
            subject_kind=_subject_kind(subject),
            packed_in_node=packed_in,
            quantity=line.quantity,
            label_snapshot=_subject_display_label(subject),
            notes=notes,
            **subject_values,
        )
        manifest.aggregate_version = new_version
        manifest.line_count += 1
        manifest.last_modified_by = actor
        manifest.save(
            update_fields=(
                "aggregate_version",
                "line_count",
                "last_modified_by",
                "updated_at",
            )
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="manifest.line.add",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=manifest.id,
        resulting_version=new_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("lines",),
        aggregate_type="logistics.manifest",
        aggregate_id=manifest.id,
        action="line_added",
        occurred_at=occurred_at,
    )


@transaction.atomic
def change_manifest_state(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    manifest_id: UUID,
    expected_version: int,
    action: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Change manifest state.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    manifest_id : UUID
        The identifier of the manifest.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    action : str
        The requested lifecycle action.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The logistics command result.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    LogisticsStateConflictError
        If the target lifecycle state does not permit the transition.
    LogisticsVersionConflictError
        If the supplied aggregate version is stale.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    expected_version = _require_expected_version(expected_version)
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _manifest_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        manifest_id=manifest_id,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
        at=occurred_at,
    )
    transitions = {
        "seal": (LogisticsManifest.Status.DRAFT, LogisticsManifest.Status.SEALED),
        "complete": (
            LogisticsManifest.Status.SEALED,
            LogisticsManifest.Status.COMPLETED,
        ),
        "cancel_draft": (
            LogisticsManifest.Status.DRAFT,
            LogisticsManifest.Status.CANCELLED,
        ),
        "cancel_sealed": (
            LogisticsManifest.Status.SEALED,
            LogisticsManifest.Status.CANCELLED,
        ),
    }
    transition = transitions.get(action)
    if transition is None:
        raise ValidationError({"action": "Select a supported manifest action."})
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "manifest_id": str(manifest_id),
            "expected_version": expected_version,
            "action": action,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="manifest.state",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    manifest = (
        LogisticsManifest.objects.select_for_update()
        .prefetch_related("lines")
        .filter(id=manifest_id, organization=organization, edition=edition)
        .first()
    )
    if manifest is None:
        raise LogisticsResourceUnavailableError
    if manifest.aggregate_version != expected_version:
        raise LogisticsVersionConflictError
    if manifest.status != transition[0]:
        raise LogisticsStateConflictError
    if action == "seal":
        lines = tuple(manifest.lines.all())
        if not lines:
            raise LogisticsStateConflictError
        for route_node in (
            manifest.source_node,
            manifest.destination_node,
            manifest.vehicle,
        ):
            if route_node is not None and route_node.edition_id not in {
                None,
                edition_id,
            }:
                raise LogisticsResourceUnavailableError
        line_subjects: list[TrackedSubject] = []
        for line in lines:
            if line.packed_in_node is not None and (
                line.packed_in_node.edition_id not in {None, edition_id}
            ):
                raise LogisticsResourceUnavailableError
            subject = _lock_subject(
                organization_id=organization_id,
                locator=SubjectLocator(
                    kind=line.subject_kind,
                    object_id=cast(
                        "UUID",
                        line.node_id
                        or line.asset_id
                        or line.stock_lot_id
                        or line.physical_key_id,
                    ),
                ),
            )
            _require_subject_available_in_edition(
                subject=subject,
                edition_id=edition_id,
            )
            line_subjects.append(subject)
        if manifest.kind not in {
            LogisticsManifest.Kind.INBOUND,
            LogisticsManifest.Kind.STAGE_RECEIVING,
        }:
            for line, subject in zip(lines, line_subjects, strict=True):
                state = _lock_current_state(subject)
                if state is None:
                    raise LogisticsStateConflictError
                if isinstance(subject, StockLot) and (
                    line.quantity != state.quantity_on_hand
                ):
                    raise LogisticsStateConflictError
                if manifest.source_node_id and not _state_within_node(
                    state=state,
                    expected_node_id=manifest.source_node_id,
                ):
                    raise LogisticsStateConflictError
    new_version = expected_version + 1
    with logistics_writer():
        manifest.status = transition[1]
        manifest.aggregate_version = new_version
        manifest.last_modified_by = actor
        manifest.save(
            update_fields=(
                "status",
                "aggregate_version",
                "last_modified_by",
                "updated_at",
            )
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="manifest.state",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=manifest.id,
        resulting_version=new_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("status",),
        aggregate_type="logistics.manifest",
        aggregate_id=manifest.id,
        action=action,
        occurred_at=occurred_at,
    )


def _label_subject(label: LogisticsLabel) -> TrackedSubject:
    subject = label.node or label.asset or label.stock_lot or label.physical_key
    if subject is None:
        raise LogisticsResourceUnavailableError
    return subject


@transaction.atomic
def ingest_offline_scan_batch(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    device_code: str,
    snapshot_version: int,
    policy_version: str,
    expires_at: datetime,
    operations: Sequence[OfflineOperationInput],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "offline",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Reconcile a bounded append-only scan batch without last-write-wins.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    device_code : str
        The public relay-device code within the edition scope.
    snapshot_version : int
        The expected snapshot version used to reject stale updates.
    policy_version : str
        The expected policy version used to reject stale updates.
    expires_at : datetime
        The timezone-aware timestamp for expires.
    operations : Sequence[OfflineOperationInput]
        The operations applied within the audited domain transition.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='offline'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The resolved LogisticsCommandResult for ingest offline scan batch.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    received_at = now or timezone.now()
    actor, organization, edition, decision = _edition_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=OFFLINE_RECONCILE_CAPABILITY,
        at=received_at,
    )
    if not isinstance(expires_at, datetime) or expires_at <= received_at:
        raise ValidationError({"expires_at": "The offline snapshot has expired."})
    if (
        not isinstance(snapshot_version, int)
        or isinstance(snapshot_version, bool)
        or snapshot_version < 0
    ):
        raise ValidationError({"snapshot_version": "Enter a non-negative version."})
    if not 1 <= len(operations) <= MAX_OFFLINE_OPERATIONS:
        raise ValidationError(
            {"operations": f"Submit 1 to {MAX_OFFLINE_OPERATIONS} operations."}
        )
    sequences = [operation.sequence for operation in operations]
    if sequences != list(range(1, len(operations) + 1)):
        raise ValidationError(
            {
                "operations": (
                    "Offline operation sequences must be contiguous and ordered."
                )
            }
        )
    normalized_device = normalized_text(
        device_code,
        field="device_code",
        maximum=96,
        required=True,
        collapse=True,
    )
    normalized_policy = normalized_text(
        policy_version,
        field="policy_version",
        maximum=64,
        required=True,
        collapse=True,
    )
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    normalized_operations: list[OfflineOperationInput] = []
    for index, operation in enumerate(operations):
        _require_uuid(
            operation.idempotency_key,
            field=f"operations.{index}.idempotency_key",
        )
        if (
            not isinstance(operation.expected_subject_sequence, int)
            or isinstance(operation.expected_subject_sequence, bool)
            or operation.expected_subject_sequence < 0
        ):
            raise ValidationError(
                {
                    f"operations.{index}.expected_subject_sequence": (
                        "Enter a non-negative subject sequence."
                    )
                }
            )
        if operation.action not in LogisticsEvent.EventType.values:
            raise ValidationError(
                {f"operations.{index}.action": "Select a supported scan action."}
            )
        if not isinstance(operation.occurred_at, datetime):
            raise ValidationError(
                {f"operations.{index}.occurred_at": "Enter a date and time."}
            )
        if operation.occurred_at > received_at:
            raise ValidationError(
                {
                    f"operations.{index}.occurred_at": (
                        "Offline time cannot be in the future."
                    )
                }
            )
        if operation.quantity is not None and (
            not isinstance(operation.quantity, int)
            or isinstance(operation.quantity, bool)
            or not 0 <= operation.quantity <= MAX_TRACKED_QUANTITY
        ):
            raise ValidationError(
                {f"operations.{index}.quantity": "Enter a bounded quantity."}
            )
        normalized_operations.append(
            OfflineOperationInput(
                sequence=operation.sequence,
                idempotency_key=operation.idempotency_key,
                expected_subject_sequence=operation.expected_subject_sequence,
                action=operation.action,
                label_code=normalized_label_code(operation.label_code),
                occurred_at=operation.occurred_at,
                source_label_code=(
                    normalized_label_code(operation.source_label_code)
                    if operation.source_label_code
                    else ""
                ),
                destination_label_code=(
                    normalized_label_code(operation.destination_label_code)
                    if operation.destination_label_code
                    else ""
                ),
                quantity=operation.quantity,
                observed_condition=normalized_text(
                    operation.observed_condition,
                    field=f"operations.{index}.observed_condition",
                    maximum=120,
                    collapse=True,
                ),
            )
        )
    payload = {
        "edition_id": str(edition_id),
        "device_code": normalized_device,
        "snapshot_version": snapshot_version,
        "policy_version": normalized_policy,
        "expires_at": expires_at.isoformat(),
        "operations": [asdict(operation) for operation in normalized_operations],
        "reason": normalized_reason_value,
    }
    request_digest = canonical_digest(payload)
    replay = _existing_receipt(
        actor=actor,
        operation="offline.ingest",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    control = (
        LogisticsEditionControl.objects.select_for_update()
        .filter(edition=edition)
        .first()
    )
    if control is None:
        with logistics_writer():
            control = LogisticsEditionControl.objects.create(
                organization=organization,
                edition=edition,
            )
    if snapshot_version > control.aggregate_version:
        raise ValidationError(
            {"snapshot_version": "The snapshot version is not known centrally."}
        )
    with logistics_writer():
        batch = OfflineScanBatch.objects.create(
            organization=organization,
            edition=edition,
            device_code=normalized_device,
            snapshot_version=snapshot_version,
            policy_version=normalized_policy,
            expires_at=expires_at,
            operation_count=len(normalized_operations),
            payload_digest=request_digest,
            submitted_by=actor,
        )
    needs_review = False
    for operation in normalized_operations:
        operation_payload = asdict(operation)
        operation_digest = canonical_digest(operation_payload)
        prior = (
            OfflineOperationReceipt.objects.select_for_update()
            .filter(idempotency_key=operation.idempotency_key)
            .first()
        )
        if prior is not None:
            if (
                prior.organization_id == organization_id
                and prior.edition_id == edition_id
                and prior.operation_digest == operation_digest
            ):
                result = OfflineScanOperation.Result.DUPLICATE
                reason_code = "logistics_offline_duplicate"
                event = prior.applied_event
                discrepancy = prior.discrepancy
                if discrepancy is not None:
                    needs_review = True
            else:
                result = OfflineScanOperation.Result.REVIEW
                reason_code = "logistics_offline_idempotency_conflict"
                label = LogisticsLabel.objects.filter(
                    organization=organization,
                    label_code=operation.label_code,
                    lifecycle=LogisticsLabel.Lifecycle.ACTIVE,
                ).first()
                subject = _label_subject(label) if label else None
                with logistics_writer():
                    discrepancy = LogisticsDiscrepancy.objects.create(
                        organization=organization,
                        edition=edition,
                        kind=LogisticsDiscrepancy.Kind.OFFLINE_CONFLICT,
                        subject_kind=(
                            _subject_kind(subject)
                            if subject
                            else LogisticsEvent.SubjectKind.NODE
                        ),
                        subject_id=subject.id if subject else batch.id,
                        description=(
                            "Offline idempotency evidence conflicts with prior use."
                        ),
                    )
                event = None
                needs_review = True
        else:
            label = (
                LogisticsLabel.objects.select_for_update(of=("self",))
                .select_related("node", "asset", "stock_lot", "physical_key")
                .filter(
                    organization=organization,
                    label_code=operation.label_code,
                    lifecycle=LogisticsLabel.Lifecycle.ACTIVE,
                )
                .first()
            )
            subject = _label_subject(label) if label else None
            source_label = None
            destination_label = None
            if operation.source_label_code:
                source_label = (
                    LogisticsLabel.objects.select_for_update()
                    .select_related("node")
                    .filter(
                        organization=organization,
                        label_code=operation.source_label_code,
                        node__isnull=False,
                        lifecycle=LogisticsLabel.Lifecycle.ACTIVE,
                    )
                    .first()
                )
            if operation.destination_label_code:
                destination_label = (
                    LogisticsLabel.objects.select_for_update()
                    .select_related("node")
                    .filter(
                        organization=organization,
                        label_code=operation.destination_label_code,
                        node__isnull=False,
                        lifecycle=LogisticsLabel.Lifecycle.ACTIVE,
                    )
                    .first()
                )
            references_valid = (
                subject is not None
                and (not operation.source_label_code or source_label is not None)
                and (
                    not operation.destination_label_code
                    or destination_label is not None
                )
            )
            if references_valid and subject is not None:
                movement = MovementInput(
                    event_type=operation.action,
                    subject=SubjectLocator(
                        kind=_subject_kind(subject),
                        object_id=subject.id,
                    ),
                    occurred_at=operation.occurred_at,
                    source_node_id=(source_label.node_id if source_label else None),
                    destination_node_id=(
                        destination_label.node_id if destination_label else None
                    ),
                    quantity=operation.quantity,
                    condition_after=operation.observed_condition,
                )
                try:
                    event, discrepancy = _append_movement_event(
                        actor=actor,
                        organization=organization,
                        edition=edition,
                        movement=movement,
                        expected_sequence=operation.expected_subject_sequence,
                        reason=normalized_reason_value,
                        source_channel="offline",
                    )
                except (
                    LogisticsContainmentCycleError,
                    LogisticsResourceUnavailableError,
                    LogisticsStateConflictError,
                    LogisticsVersionConflictError,
                    ValidationError,
                ):
                    event = None
                    with logistics_writer():
                        discrepancy = LogisticsDiscrepancy.objects.create(
                            organization=organization,
                            edition=edition,
                            kind=LogisticsDiscrepancy.Kind.OFFLINE_CONFLICT,
                            subject_kind=_subject_kind(subject),
                            subject_id=subject.id,
                            description=(
                                "Offline scan conflicts with the current subject "
                                "projection."
                            ),
                        )
                    result = OfflineScanOperation.Result.REVIEW
                    reason_code = "logistics_offline_state_conflict"
                    needs_review = True
                else:
                    result = OfflineScanOperation.Result.APPLIED
                    reason_code = "logistics_offline_applied"
                    if discrepancy is not None:
                        needs_review = True
            else:
                event = None
                with logistics_writer():
                    discrepancy = LogisticsDiscrepancy.objects.create(
                        organization=organization,
                        edition=edition,
                        kind=LogisticsDiscrepancy.Kind.OFFLINE_CONFLICT,
                        subject_kind=(
                            _subject_kind(subject)
                            if subject
                            else LogisticsEvent.SubjectKind.NODE
                        ),
                        subject_id=subject.id if subject else batch.id,
                        description=(
                            "Offline scan contains an unknown or invalid label."
                        ),
                    )
                result = OfflineScanOperation.Result.REVIEW
                reason_code = "logistics_offline_label_unavailable"
                needs_review = True
            with logistics_writer():
                OfflineOperationReceipt.objects.create(
                    organization=organization,
                    edition=edition,
                    idempotency_key=operation.idempotency_key,
                    operation_digest=operation_digest,
                    result=result,
                    reason_code=reason_code,
                    applied_event=event,
                    discrepancy=discrepancy,
                )
        with logistics_writer():
            OfflineScanOperation.objects.create(
                batch=batch,
                sequence=operation.sequence,
                idempotency_key=operation.idempotency_key,
                expected_subject_sequence=operation.expected_subject_sequence,
                action=operation.action,
                label_code=operation.label_code,
                source_label_code=operation.source_label_code,
                destination_label_code=operation.destination_label_code,
                quantity=operation.quantity,
                observed_condition=operation.observed_condition,
                occurred_at=operation.occurred_at,
                operation_digest=operation_digest,
                result=result,
                reason_code=reason_code,
                applied_event=event,
                discrepancy=discrepancy,
            )
    with logistics_writer():
        batch.status = (
            OfflineScanBatch.Status.REVIEW
            if needs_review
            else OfflineScanBatch.Status.APPLIED
        )
        batch.aggregate_version = 2
        batch.save(update_fields=("status", "aggregate_version", "updated_at"))
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="offline.ingest",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=batch.id,
        resulting_version=2,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=OFFLINE_RECONCILE_CAPABILITY,
        decision=decision,
        changed_fields=("offline_operations", "reconciliation_status"),
        aggregate_type="logistics.offline_batch",
        aggregate_id=batch.id,
        action=batch.status,
        occurred_at=received_at,
    )


@transaction.atomic
def submit_equipment_offer(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    title: str,
    description: str,
    pickup_label: str,
    pickup_recipient_name: str,
    pickup_postal_address: str,
    pickup_access_instructions: str,
    pickup_retention_until: datetime,
    available_from: datetime,
    available_until: datetime,
    requested_return_at: datetime | None,
    items: Sequence[OfferItemInput],
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Create one private self-owned offer without accepting operational custody.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    title : str
        The human-readable title shown to authorized readers.
    description : str
        The human-readable description shown to authorized readers.
    pickup_label : str
        The human-readable pickup label shown to authorized readers.
    pickup_recipient_name : str
        The human-readable pickup recipient name shown to authorized readers.
    pickup_postal_address : str
        The pickup postal address applied within the audited domain transition.
    pickup_access_instructions : str
        The pickup access instructions applied within the audited domain transition.
    pickup_retention_until : datetime
        The timezone-aware boundary for pickup retention until.
    available_from : datetime
        The timezone-aware boundary for available from.
    available_until : datetime
        The timezone-aware boundary for available until.
    requested_return_at : datetime | None
        The timezone-aware timestamp for requested return.
    items : Sequence[OfferItemInput]
        The items applied within the audited domain transition.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='web'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The resolved LogisticsCommandResult for submit equipment offer.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _self_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=occurred_at,
    )
    if edition.lifecycle not in SELF_OFFER_EDITION_LIFECYCLES:
        raise LogisticsResourceUnavailableError
    normalized_title = normalized_text(
        title,
        field="title",
        maximum=200,
        required=True,
        collapse=True,
    )
    normalized_description = normalized_text(
        description,
        field="description",
        maximum=5_000,
    )
    address_values = {
        "label": normalized_text(
            pickup_label,
            field="pickup_label",
            maximum=200,
            required=True,
            collapse=True,
        ),
        "recipient_name": normalized_text(
            pickup_recipient_name,
            field="pickup_recipient_name",
            maximum=240,
            collapse=True,
        ),
        "postal_address": normalized_text(
            pickup_postal_address,
            field="pickup_postal_address",
            maximum=1_000,
            required=True,
        ),
        "access_instructions": normalized_text(
            pickup_access_instructions,
            field="pickup_access_instructions",
            maximum=5_000,
        ),
    }
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    if not isinstance(pickup_retention_until, datetime):
        raise ValidationError({"pickup_retention_until": "Enter a date and time."})
    if (
        not isinstance(available_from, datetime)
        or not isinstance(available_until, datetime)
        or available_until <= available_from
    ):
        raise ValidationError({"available_until": "End availability after it starts."})
    required_contact_horizon = max(
        value for value in (available_until, requested_return_at) if value is not None
    )
    if pickup_retention_until < required_contact_horizon:
        raise ValidationError(
            {
                "pickup_retention_until": (
                    "Retain the pickup address through availability and return."
                )
            }
        )
    if requested_return_at is not None and requested_return_at < available_from:
        raise ValidationError(
            {"requested_return_at": "Return cannot precede availability."}
        )
    if not 1 <= len(items) <= MAX_OFFER_ITEMS:
        raise ValidationError(
            {"items": f"Offer between 1 and {MAX_OFFER_ITEMS} item lines."}
        )
    normalized_items: list[dict[str, object]] = []
    for position, item in enumerate(items):
        if item.kind not in EquipmentOfferItem.Kind.values:
            raise ValidationError({f"items.{position}.kind": "Select an item kind."})
        if (
            not isinstance(item.quantity, int)
            or isinstance(item.quantity, bool)
            or item.quantity < 1
            or item.quantity > MAX_OFFER_QUANTITY
            or (item.kind == EquipmentOfferItem.Kind.SERIALIZED and item.quantity != 1)
        ):
            raise ValidationError(
                {f"items.{position}.quantity": "Enter a valid item quantity."}
            )
        values: dict[str, object] = {
            "kind": item.kind,
            "quantity": item.quantity,
        }
        for field_name, maximum, required in (
            ("name", 200, True),
            ("description", 2_000, False),
            ("manufacturer", 160, False),
            ("model_name", 160, False),
            ("serial_number", 200, False),
            ("condition", 120, True),
            ("value_class", 32, False),
            ("ownership_statement", 500, True),
        ):
            values[field_name] = normalized_text(
                getattr(item, field_name),
                field=f"items.{position}.{field_name}",
                maximum=maximum,
                required=required,
                collapse=True,
            )
        normalized_items.append(values)
    payload: dict[str, object] = {
        "edition_id": str(edition_id),
        "title": normalized_title,
        "description": normalized_description,
        "address": address_values,
        "pickup_retention_until": pickup_retention_until.isoformat(),
        "available_from": available_from.isoformat(),
        "available_until": available_until.isoformat(),
        "requested_return_at": (
            requested_return_at.isoformat() if requested_return_at else None
        ),
        "items": normalized_items,
        "reason": normalized_reason_value,
    }
    request_digest = canonical_digest(payload)
    replay = _existing_receipt(
        actor=actor,
        operation="offer.submit",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    with logistics_writer():
        address = RestrictedLogisticsAddress.objects.create(
            organization=organization,
            edition=edition,
            subject_account=actor,
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
            retention_until=pickup_retention_until,
            created_by=actor,
            **address_values,
        )
        offer = EquipmentOffer.objects.create(
            organization=organization,
            edition=edition,
            offered_by=actor,
            pickup_address=address,
            title=normalized_title,
            description=normalized_description,
            available_from=available_from,
            available_until=available_until,
            requested_return_at=requested_return_at,
        )
        for values in normalized_items:
            EquipmentOfferItem.objects.create(offer=offer, **values)
        EquipmentOfferHistory.objects.create(
            offer=offer,
            organization=organization,
            edition=edition,
            status=EquipmentOffer.Status.PENDING,
            offer_version=1,
            actor=actor,
            reason=normalized_reason_value,
            occurred_at=occurred_at,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="offer.submit",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=offer.id,
        resulting_version=1,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=SELF_OFFER_CAPABILITY,
        decision=decision,
        changed_fields=("status", "items", "purpose_bound_pickup_address"),
        aggregate_type="logistics.equipment_offer",
        aggregate_id=offer.id,
        action="submitted",
        occurred_at=occurred_at,
    )


@transaction.atomic
def withdraw_equipment_offer(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    offer_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Withdraw equipment offer.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    offer_id : UUID
        The identifier of the offer.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The logistics command result.

    Raises
    ------
    LogisticsAuthorizationDeniedError
        If the actor lacks the required scoped capability.
    LogisticsStateConflictError
        If the target lifecycle state does not permit the transition.
    LogisticsVersionConflictError
        If the supplied aggregate version is stale.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    expected_version = _require_expected_version(expected_version)
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _self_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        at=occurred_at,
    )
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "offer_id": str(offer_id),
            "expected_version": expected_version,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="offer.withdraw",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    offer = (
        EquipmentOffer.objects.select_for_update()
        .filter(
            id=offer_id,
            organization=organization,
            edition=edition,
            offered_by=actor,
        )
        .first()
    )
    if offer is None:
        raise LogisticsAuthorizationDeniedError
    if offer.aggregate_version != expected_version:
        raise LogisticsVersionConflictError
    if offer.status != EquipmentOffer.Status.PENDING:
        raise LogisticsStateConflictError
    new_version = expected_version + 1
    with logistics_writer():
        offer.status = EquipmentOffer.Status.WITHDRAWN
        offer.aggregate_version = new_version
        offer.save(update_fields=("status", "aggregate_version", "updated_at"))
        EquipmentOfferHistory.objects.create(
            offer=offer,
            organization=organization,
            edition=edition,
            status=offer.status,
            offer_version=new_version,
            actor=actor,
            reason=normalized_reason_value,
            occurred_at=occurred_at,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="offer.withdraw",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=offer.id,
        resulting_version=new_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=SELF_OFFER_CAPABILITY,
        decision=decision,
        changed_fields=("status",),
        aggregate_type="logistics.equipment_offer",
        aggregate_id=offer.id,
        action="withdrawn",
        occurred_at=occurred_at,
    )


@transaction.atomic
def review_equipment_offer(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    offer_id: UUID,
    expected_version: int,
    outcome: str,
    responsible_department_id: UUID | None,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Review equipment offer.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    offer_id : UUID
        The identifier of the offer.
    expected_version : int
        The aggregate version required for optimistic concurrency.
    outcome : str
        The outcome applied within the audited domain transition.
    responsible_department_id : UUID | None
        The identifier of the responsible department.
    reason : str
        The operator-supplied reason for the operation.
    idempotency_key : UUID
        The stable key used to replay the request safely.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='web'
        The trusted channel that initiated the operation.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    LogisticsCommandResult
        The logistics command result.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    LogisticsStateConflictError
        If the target lifecycle state does not permit the transition.
    LogisticsVersionConflictError
        If the supplied aggregate version is stale.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    expected_version = _require_expected_version(expected_version)
    occurred_at = now or timezone.now()
    actor, organization, edition, decision = _edition_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=OFFER_REVIEW_CAPABILITY,
        at=occurred_at,
    )
    if outcome not in {
        EquipmentOffer.Status.ACCEPTED,
        EquipmentOffer.Status.REJECTED,
    }:
        raise ValidationError({"outcome": "Accept or reject the pending offer."})
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "offer_id": str(offer_id),
            "expected_version": expected_version,
            "outcome": outcome,
            "responsible_department_id": (
                str(responsible_department_id) if responsible_department_id else None
            ),
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="offer.review",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    offer = (
        EquipmentOffer.objects.select_for_update()
        .select_related("offered_by")
        .prefetch_related("items")
        .filter(id=offer_id, organization=organization, edition=edition)
        .first()
    )
    if offer is None:
        raise LogisticsResourceUnavailableError
    if offer.aggregate_version != expected_version:
        raise LogisticsVersionConflictError
    if offer.status != EquipmentOffer.Status.PENDING:
        raise LogisticsStateConflictError
    department: Department | None = None
    if outcome == EquipmentOffer.Status.ACCEPTED:
        department = (
            Department.objects.select_for_update()
            .filter(
                id=cast("UUID", responsible_department_id),
                organization=organization,
                edition=edition,
                retired_at__isnull=True,
            )
            .first()
        )
        if department is None:
            raise LogisticsResourceUnavailableError
    elif responsible_department_id is not None:
        raise ValidationError(
            {
                "responsible_department_id": (
                    "A rejected offer has no custodian Department."
                )
            }
        )
    new_version = expected_version + 1
    with logistics_writer():
        if outcome == EquipmentOffer.Status.ACCEPTED:
            for item in offer.items.all():
                code = f"offer-{item.id.hex}"
                subject: Asset | StockLot
                if item.kind == EquipmentOfferItem.Kind.SERIALIZED:
                    subject = Asset.objects.create(
                        organization=organization,
                        edition_allocation=edition,
                        catalog_code=code,
                        name=item.name,
                        asset_type="offered_equipment",
                        manufacturer=item.manufacturer,
                        model_name=item.model_name,
                        serial_number=item.serial_number,
                        acquisition=Asset.Acquisition.EQUIPMENT_OFFER,
                        value_class=item.value_class,
                        owner_kind=Asset.OwnerKind.ACCOUNT,
                        owner_account=offer.offered_by,
                        created_by=actor,
                    )
                    acceptance_values: dict[str, Asset | StockLot] = {"asset": subject}
                else:
                    subject = StockLot.objects.create(
                        organization=organization,
                        edition_allocation=edition,
                        catalog_code=code,
                        name=item.name,
                        stock_type="offered_stock",
                        unit="item",
                        initial_quantity=item.quantity,
                        value_class=item.value_class,
                        owner_kind=StockLot.OwnerKind.ACCOUNT,
                        owner_account=offer.offered_by,
                        created_by=actor,
                    )
                    acceptance_values = {"stock_lot": subject}
                acceptance = EquipmentOfferAcceptance.objects.create(
                    offer_item=item,
                    accepted_by=actor,
                    accepted_at=occurred_at,
                    **acceptance_values,
                )
                return_due_at = offer.requested_return_at or offer.available_until
                AssetAgreement.objects.create(
                    organization=organization,
                    edition=edition,
                    kind=AssetAgreement.Kind.LOAN,
                    offer_acceptance=acceptance,
                    provider_account=offer.offered_by,
                    starts_at=offer.available_from,
                    ends_at=offer.available_until,
                    return_due_at=return_due_at,
                    created_by=actor,
                    **acceptance_values,
                )
        offer.status = outcome
        offer.aggregate_version = new_version
        offer.reviewed_by = actor
        offer.reviewed_at = occurred_at
        offer.review_reason = normalized_reason_value
        offer.responsible_department = department
        offer.save(
            update_fields=(
                "status",
                "aggregate_version",
                "reviewed_by",
                "reviewed_at",
                "review_reason",
                "responsible_department",
                "updated_at",
            )
        )
        EquipmentOfferHistory.objects.create(
            offer=offer,
            organization=organization,
            edition=edition,
            status=outcome,
            offer_version=new_version,
            actor=actor,
            reason=normalized_reason_value,
            occurred_at=occurred_at,
        )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="offer.review",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=offer.id,
        resulting_version=new_version,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=OFFER_REVIEW_CAPABILITY,
        decision=decision,
        changed_fields=("status", "review", "accepted_inventory"),
        aggregate_type="logistics.equipment_offer",
        aggregate_id=offer.id,
        action=outcome,
        occurred_at=occurred_at,
    )


_NODE_PARENT_KINDS: Mapping[str, frozenset[str]] = {
    LogisticsNode.Kind.STORAGE_SITE: frozenset(),
    LogisticsNode.Kind.STORAGE_AREA: frozenset(
        {LogisticsNode.Kind.STORAGE_SITE, LogisticsNode.Kind.VENUE_ROOM}
    ),
    LogisticsNode.Kind.RACK: frozenset(
        {LogisticsNode.Kind.STORAGE_AREA, LogisticsNode.Kind.CONTAINER}
    ),
    LogisticsNode.Kind.CONTAINER: frozenset(
        {
            LogisticsNode.Kind.STORAGE_SITE,
            LogisticsNode.Kind.STORAGE_AREA,
            LogisticsNode.Kind.VEHICLE,
            LogisticsNode.Kind.LOADING_ZONE,
            LogisticsNode.Kind.STAGING_AREA,
            LogisticsNode.Kind.VENUE_ROOM,
        }
    ),
    LogisticsNode.Kind.BOX: frozenset(
        {
            LogisticsNode.Kind.STORAGE_AREA,
            LogisticsNode.Kind.RACK,
            LogisticsNode.Kind.CONTAINER,
            LogisticsNode.Kind.BOX,
            LogisticsNode.Kind.VEHICLE,
            LogisticsNode.Kind.LOADING_ZONE,
            LogisticsNode.Kind.STAGING_AREA,
            LogisticsNode.Kind.VENUE_ROOM,
        }
    ),
    LogisticsNode.Kind.VEHICLE: frozenset(
        {
            LogisticsNode.Kind.STORAGE_SITE,
            LogisticsNode.Kind.LOADING_ZONE,
            LogisticsNode.Kind.STAGING_AREA,
        }
    ),
    LogisticsNode.Kind.LOADING_ZONE: frozenset(
        {LogisticsNode.Kind.STORAGE_SITE, LogisticsNode.Kind.VENUE_ROOM}
    ),
    LogisticsNode.Kind.STAGING_AREA: frozenset(
        {
            LogisticsNode.Kind.STORAGE_SITE,
            LogisticsNode.Kind.LOADING_ZONE,
            LogisticsNode.Kind.VENUE_ROOM,
        }
    ),
    LogisticsNode.Kind.VENUE_ROOM: frozenset(),
}


def _validate_parent_kind(
    *, subject: TrackedSubject, destination: LogisticsNode | None
) -> None:
    if not isinstance(subject, LogisticsNode) or destination is None:
        return
    if destination.kind not in _NODE_PARENT_KINDS[subject.kind]:
        raise ValidationError(
            {"destination_node_id": "That node type cannot contain this subject."}
        )


def _event_state(event_type: str, current_state: str | None) -> str:
    if event_type == LogisticsEvent.EventType.LOAD:
        return LogisticsCurrentState.State.IN_TRANSIT
    if event_type == LogisticsEvent.EventType.HANDOVER:
        return LogisticsCurrentState.State.ISSUED
    if event_type == LogisticsEvent.EventType.RETURN:
        return LogisticsCurrentState.State.RETURNED
    if event_type in {
        LogisticsEvent.EventType.RECEIVE,
        LogisticsEvent.EventType.PACK,
        LogisticsEvent.EventType.UNPACK,
        LogisticsEvent.EventType.MOVE,
        LogisticsEvent.EventType.UNLOAD,
    }:
        return LogisticsCurrentState.State.STORED
    return current_state or LogisticsCurrentState.State.RECEIVED


def _normalized_movement(movement: MovementInput) -> MovementInput:
    if movement.event_type not in LogisticsEvent.EventType.values:
        raise ValidationError({"event_type": "Select a supported logistics event."})
    if movement.subject.kind not in LogisticsEvent.SubjectKind.values:
        raise ValidationError({"subject.kind": "Select a supported tracked kind."})
    _require_uuid(movement.subject.object_id, field="subject.object_id")
    if not isinstance(movement.occurred_at, datetime):
        raise ValidationError({"occurred_at": "Enter a date and time."})
    for field_name in (
        "source_node_id",
        "destination_node_id",
        "to_custodian_account_id",
        "to_custodian_party_id",
        "manifest_id",
    ):
        value = getattr(movement, field_name)
        if value is not None:
            _require_uuid(value, field=field_name)
    if movement.to_custodian_account_id and movement.to_custodian_party_id:
        raise ValidationError(
            {"custodian": "Select a person or external party, not both."}
        )
    if movement.quantity is not None and (
        not isinstance(movement.quantity, int)
        or isinstance(movement.quantity, bool)
        or movement.quantity < 0
        or movement.quantity > MAX_TRACKED_QUANTITY
    ):
        raise ValidationError({"quantity": "Enter a bounded non-negative quantity."})
    return MovementInput(
        event_type=movement.event_type,
        subject=movement.subject,
        occurred_at=movement.occurred_at,
        source_node_id=movement.source_node_id,
        destination_node_id=movement.destination_node_id,
        to_custodian_account_id=movement.to_custodian_account_id,
        to_custodian_party_id=movement.to_custodian_party_id,
        quantity=movement.quantity,
        condition_before=normalized_text(
            movement.condition_before,
            field="condition_before",
            maximum=120,
            collapse=True,
        ),
        condition_after=normalized_text(
            movement.condition_after,
            field="condition_after",
            maximum=120,
            collapse=True,
        ),
        manifest_id=movement.manifest_id,
        evidence_reference=normalized_text(
            movement.evidence_reference,
            field="evidence_reference",
            maximum=1_000,
        ),
    )


def _canonical_manifest_movement(
    *,
    movement: MovementInput,
    organization_id: UUID,
    edition_id: UUID,
) -> MovementInput:
    if movement.manifest_id is None:
        return movement
    subject_field_by_kind: dict[str, str] = {
        LogisticsEvent.SubjectKind.NODE: "node_id",
        LogisticsEvent.SubjectKind.ASSET: "asset_id",
        LogisticsEvent.SubjectKind.STOCK_LOT: "stock_lot_id",
        LogisticsEvent.SubjectKind.KEY: "physical_key_id",
    }
    subject_field = subject_field_by_kind.get(movement.subject.kind)
    if subject_field is None:
        raise LogisticsResourceUnavailableError
    line_id = (
        LogisticsManifestLine.objects.filter(
            manifest_id=movement.manifest_id,
            manifest__organization_id=organization_id,
            manifest__edition_id=edition_id,
            **{subject_field: movement.subject.object_id},
        )
        .order_by()
        .values_list("id", flat=True)
        .first()
    )
    if line_id is None:
        raise LogisticsResourceUnavailableError
    return replace(
        movement,
        evidence_reference=f"manifest-line:{line_id}",
    )


def _append_movement_event(
    *,
    actor: Account,
    organization: Organization,
    edition: EventEdition | None,
    movement: MovementInput,
    expected_sequence: int,
    reason: str,
    source_channel: str,
) -> tuple[LogisticsEvent, LogisticsDiscrepancy | None]:
    subject = _lock_subject(
        organization_id=organization.id,
        locator=movement.subject,
    )
    if edition is not None:
        _require_subject_available_in_edition(
            subject=subject,
            edition_id=edition.id,
        )
    current = _lock_current_state(subject)
    if current is not None and current.current_node_id is not None:
        current_node_scope = (
            LogisticsNode.objects.filter(
                id=current.current_node_id,
                organization=organization,
            )
            .order_by()
            .values("edition_id")
            .first()
        )
        if current_node_scope is None or (
            edition is not None
            and current_node_scope["edition_id"] not in {None, edition.id}
        ):
            raise LogisticsResourceUnavailableError

    node_ids = {
        value
        for value in (movement.source_node_id, movement.destination_node_id)
        if value is not None
    }
    nodes = {
        node.id: node
        for node in LogisticsNode.objects.select_for_update()
        .filter(organization=organization, id__in=node_ids)
        .order_by("id")
    }
    if len(nodes) != len(node_ids) or any(
        edition is not None and node.edition_id not in {None, edition.id}
        for node in nodes.values()
    ):
        raise LogisticsResourceUnavailableError
    actual_sequence = current.event_sequence if current else 0
    if expected_sequence != actual_sequence:
        raise LogisticsVersionConflictError
    if current is None and movement.event_type != LogisticsEvent.EventType.RECEIVE:
        raise LogisticsStateConflictError
    if current is not None and movement.event_type == LogisticsEvent.EventType.RECEIVE:
        raise LogisticsStateConflictError
    source_node = nodes.get(cast("UUID", movement.source_node_id))
    destination_node = nodes.get(cast("UUID", movement.destination_node_id))
    prior_node_id = current.current_node_id if current else None
    if movement.source_node_id is not None and movement.source_node_id != prior_node_id:
        raise LogisticsStateConflictError
    movement_events = {
        LogisticsEvent.EventType.RECEIVE,
        LogisticsEvent.EventType.PACK,
        LogisticsEvent.EventType.UNPACK,
        LogisticsEvent.EventType.MOVE,
        LogisticsEvent.EventType.LOAD,
        LogisticsEvent.EventType.UNLOAD,
    }
    if movement.event_type in movement_events and destination_node is None:
        raise ValidationError(
            {"destination_node_id": "This event requires a destination."}
        )
    if movement.event_type in {
        LogisticsEvent.EventType.COUNT,
        LogisticsEvent.EventType.CONDITION,
        LogisticsEvent.EventType.DAMAGE,
        LogisticsEvent.EventType.HANDOVER,
    } and (movement.source_node_id or movement.destination_node_id):
        raise ValidationError(
            {"destination_node_id": "This event does not move the tracked subject."}
        )
    has_recipient = bool(
        movement.to_custodian_account_id or movement.to_custodian_party_id
    )
    if movement.event_type == LogisticsEvent.EventType.HANDOVER and not has_recipient:
        raise ValidationError({"custodian": "Handover requires one recipient."})
    if (
        movement.event_type == LogisticsEvent.EventType.RETURN
        and destination_node is None
        and not has_recipient
    ):
        raise ValidationError(
            {"destination_node_id": "Return requires a destination or recipient."}
        )
    _lock_containment_graph(organization.id)
    _validate_parent_kind(subject=subject, destination=destination_node)
    _assert_acyclic_destination(subject=subject, destination=destination_node)

    if movement.to_custodian_account_id:
        owner_account_id = getattr(subject, "owner_account_id", None)
        custodian_account = _lock_eligible_logistics_person(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id if edition else None,
            account_id=movement.to_custodian_account_id,
            extra_eligible_ids=(
                frozenset({owner_account_id})
                if owner_account_id is not None
                else frozenset()
            ),
        )
    else:
        custodian_account = None
    if movement.to_custodian_party_id:
        custodian_party = (
            LogisticsParty.objects.select_for_update()
            .filter(
                id=movement.to_custodian_party_id,
                organization=organization,
                lifecycle=LogisticsParty.Lifecycle.ACTIVE,
            )
            .first()
        )
        if custodian_party is None:
            raise LogisticsResourceUnavailableError
    else:
        custodian_party = None

    manifest: LogisticsManifest | None = None
    if movement.manifest_id is not None:
        manifest = (
            LogisticsManifest.objects.select_for_update()
            .filter(
                id=movement.manifest_id,
                organization=organization,
                edition_id=edition.id if edition else None,
                status__in=(
                    LogisticsManifest.Status.SEALED,
                    LogisticsManifest.Status.COMPLETED,
                ),
            )
            .first()
        )
        if manifest is None:
            raise LogisticsResourceUnavailableError
        manifest_line = (
            manifest.lines.filter(**_manifest_subject_values(subject))
            .only("packed_in_node_id")
            .first()
        )
        if manifest_line is None:
            raise LogisticsResourceUnavailableError
        if movement.evidence_reference != f"manifest-line:{manifest_line.id}":
            raise LogisticsResourceUnavailableError
        manifest_destination_id = (
            manifest_line.packed_in_node_id or manifest.destination_node_id
        )
        route_matches = (
            (
                movement.event_type == LogisticsEvent.EventType.RECEIVE
                and manifest.kind
                in {
                    LogisticsManifest.Kind.INBOUND,
                    LogisticsManifest.Kind.STAGE_RECEIVING,
                }
                and movement.source_node_id is None
                and manifest_destination_id is not None
                and movement.destination_node_id == manifest_destination_id
            )
            or (
                movement.event_type == LogisticsEvent.EventType.LOAD
                and manifest.kind
                in {
                    LogisticsManifest.Kind.OUTBOUND,
                    LogisticsManifest.Kind.TRANSFER,
                    LogisticsManifest.Kind.RETURN,
                }
                and manifest.source_node_id is not None
                and manifest.vehicle_id is not None
                and (source_node or (current.current_node if current else None))
                == manifest.source_node
                and movement.destination_node_id == manifest.vehicle_id
            )
            or (
                movement.event_type == LogisticsEvent.EventType.UNLOAD
                and manifest.kind
                in {
                    LogisticsManifest.Kind.OUTBOUND,
                    LogisticsManifest.Kind.TRANSFER,
                    LogisticsManifest.Kind.RETURN,
                }
                and manifest.vehicle_id is not None
                and manifest_destination_id is not None
                and (source_node or (current.current_node if current else None))
                == manifest.vehicle
                and movement.destination_node_id == manifest_destination_id
            )
            or (
                movement.event_type == LogisticsEvent.EventType.RETURN
                and manifest.kind == LogisticsManifest.Kind.RETURN
                and manifest.source_node_id is not None
                and manifest_destination_id is not None
                and (source_node or (current.current_node if current else None))
                == manifest.source_node
                and movement.destination_node_id == manifest_destination_id
            )
        )
        if not route_matches:
            raise LogisticsResourceUnavailableError

    prior_condition = current.condition if current else ""
    if movement.condition_before and movement.condition_before != prior_condition:
        raise LogisticsStateConflictError
    new_condition = movement.condition_after or prior_condition
    if current is None and not new_condition:
        raise ValidationError({"condition_after": "Receiving requires a condition."})
    if (
        movement.event_type == LogisticsEvent.EventType.DAMAGE
        and not movement.condition_after
    ):
        raise ValidationError({"condition_after": "Damage requires the new condition."})

    if isinstance(subject, StockLot):
        prior_quantity = current.quantity_on_hand if current else None
        if movement.quantity is None:
            raise ValidationError({"quantity": "Stock-lot events require a quantity."})
        if movement.event_type == LogisticsEvent.EventType.RECEIVE:
            if movement.quantity > subject.initial_quantity:
                raise ValidationError(
                    {"quantity": "Received quantity exceeds the registered lot."}
                )
            new_quantity = movement.quantity
        elif movement.event_type == LogisticsEvent.EventType.COUNT:
            new_quantity = movement.quantity
        else:
            if movement.quantity != prior_quantity:
                raise ValidationError(
                    {
                        "quantity": (
                            "Move the complete lot or create a separately tracked lot."
                        )
                    }
                )
            new_quantity = prior_quantity
    else:
        if movement.quantity not in {None, 1}:
            raise ValidationError({"quantity": "Serialized items have quantity one."})
        prior_quantity = None
        new_quantity = None

    if (
        movement.event_type in movement_events
        or movement.event_type == LogisticsEvent.EventType.RETURN
    ):
        new_node = destination_node
    else:
        new_node = current.current_node if current else None
    if (
        movement.event_type
        in {
            LogisticsEvent.EventType.HANDOVER,
            LogisticsEvent.EventType.RETURN,
        }
        or custodian_account is not None
        or custodian_party is not None
    ):
        new_custodian_account = custodian_account
        new_custodian_party = custodian_party
    else:
        new_custodian_account = current.custodian_account if current else None
        new_custodian_party = current.custodian_party if current else None

    sequence = actual_sequence + 1
    with logistics_writer():
        event = LogisticsEvent.objects.create(
            organization=organization,
            edition=edition,
            subject_kind=_subject_kind(subject),
            event_type=movement.event_type,
            event_sequence=sequence,
            source_node=source_node or (current.current_node if current else None),
            destination_node=destination_node,
            from_custodian_account=(current.custodian_account if current else None),
            to_custodian_account=new_custodian_account,
            from_custodian_party=(current.custodian_party if current else None),
            to_custodian_party=new_custodian_party,
            quantity=movement.quantity,
            condition_before=prior_condition,
            condition_after=new_condition,
            manifest=manifest,
            actor=actor,
            occurred_at=movement.occurred_at,
            reason=reason,
            evidence_reference=movement.evidence_reference,
            source_channel=source_channel,
            **_subject_kwargs(subject),
        )
        state_values: dict[str, object] = {
            "organization": organization,
            "current_node": new_node,
            "custodian_account": new_custodian_account,
            "custodian_party": new_custodian_party,
            "quantity_on_hand": new_quantity,
            "condition": new_condition,
            "state": _event_state(
                movement.event_type,
                current.state if current else None,
            ),
            "event_sequence": sequence,
            "last_event": event,
        }
        if current is None:
            LogisticsCurrentState.objects.create(
                **state_values,
                **_subject_kwargs(subject),
            )
        else:
            for field_name, value in state_values.items():
                setattr(current, field_name, value)
            current.save(
                update_fields=(*tuple(state_values), "updated_at"),
            )
        discrepancy: LogisticsDiscrepancy | None = None
        discrepancy_kind: str | None = None
        discrepancy_description = ""
        if (
            movement.event_type == LogisticsEvent.EventType.COUNT
            and prior_quantity is not None
            and new_quantity != prior_quantity
        ):
            discrepancy_kind = LogisticsDiscrepancy.Kind.COUNT
            discrepancy_description = (
                "Observed stock count differs from prior projection."
            )
        elif movement.event_type == LogisticsEvent.EventType.DAMAGE:
            discrepancy_kind = LogisticsDiscrepancy.Kind.DAMAGE
            discrepancy_description = "Damage was recorded during logistics handling."
        if discrepancy_kind:
            discrepancy = LogisticsDiscrepancy.objects.create(
                organization=organization,
                edition=edition,
                kind=discrepancy_kind,
                subject_kind=_subject_kind(subject),
                subject_id=subject.id,
                expected_quantity=prior_quantity,
                observed_quantity=new_quantity,
                description=discrepancy_description,
                detected_event=event,
            )
        if edition is not None:
            control, _ = (
                LogisticsEditionControl.objects.select_for_update().get_or_create(
                    edition=edition,
                    defaults={"organization": organization},
                )
            )
            control.aggregate_version += 1
            control.save(update_fields=("aggregate_version", "updated_at"))
    return event, discrepancy


@transaction.atomic
def record_logistics_event(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    movement: MovementInput,
    expected_sequence: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Append one custody/location fact and advance only its derived projection.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    movement : MovementInput
        The movement applied within the audited domain transition.
    expected_sequence : int
        The expected expected sequence used to reject stale updates.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='web'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The resolved LogisticsCommandResult for record logistics event.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    if (
        not isinstance(expected_sequence, int)
        or isinstance(expected_sequence, bool)
        or expected_sequence < 0
    ):
        raise ValidationError({"expected_sequence": "Enter a non-negative sequence."})
    authorized_at = now or timezone.now()
    actor, organization, edition, decision = _edition_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
        at=authorized_at,
    )
    movement = _normalized_movement(movement)
    movement = _canonical_manifest_movement(
        movement=movement,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    request_digest = canonical_digest(
        {
            "edition_id": str(edition_id),
            "movement": asdict(movement),
            "expected_sequence": expected_sequence,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="event.record",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    event, _ = _append_movement_event(
        actor=actor,
        organization=organization,
        edition=edition,
        movement=movement,
        expected_sequence=expected_sequence,
        reason=normalized_reason_value,
        source_channel=normalized_source,
    )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="event.record",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=event.id,
        resulting_version=event.event_sequence,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("location", "custody", "condition", "quantity"),
        aggregate_type="logistics.event",
        aggregate_id=event.id,
        action=movement.event_type,
        occurred_at=authorized_at,
    )


@transaction.atomic
def record_manifest_receipt(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    manifest_id: UUID,
    line_id: UUID,
    expected_sequence: int,
    occurred_at: datetime,
    condition_after: str,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "web",
    now: datetime | None = None,
) -> LogisticsCommandResult:
    """Receive one exact manifest line with exact-manifest authority.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    manifest_id : UUID
        The manifest identifier within the requested scope.
    line_id : UUID
        The line identifier within the requested scope.
    expected_sequence : int
        The expected expected sequence used to reject stale updates.
    occurred_at : datetime
        The timezone-aware timestamp for occurred.
    condition_after : str
        The timezone-aware boundary for condition after.
    reason : str
        The operator-supplied rationale recorded with the change.
    idempotency_key : UUID
        The stable key that makes an exact retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='web'
        The closed channel code identifying where the request originated.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    LogisticsCommandResult
        The resolved LogisticsCommandResult for record manifest receipt.

    Raises
    ------
    LogisticsResourceUnavailableError
        If the scoped target does not exist or cannot be disclosed.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    idempotency_key, correlation_id = _validate_command_ids(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    if (
        not isinstance(expected_sequence, int)
        or isinstance(expected_sequence, bool)
        or expected_sequence < 0
    ):
        raise ValidationError({"expected_sequence": "Enter a non-negative sequence."})
    authorized_at = now or timezone.now()
    actor, organization, edition, decision = _manifest_context(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        manifest_id=manifest_id,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
        at=authorized_at,
    )
    manifest = (
        LogisticsManifest.objects.select_for_update()
        .filter(
            id=manifest_id,
            organization=organization,
            edition=edition,
            kind__in=(
                LogisticsManifest.Kind.INBOUND,
                LogisticsManifest.Kind.STAGE_RECEIVING,
            ),
            status__in=(
                LogisticsManifest.Status.SEALED,
                LogisticsManifest.Status.COMPLETED,
            ),
        )
        .first()
    )
    if manifest is None:
        raise LogisticsResourceUnavailableError
    line = (
        LogisticsManifestLine.objects.select_for_update()
        .filter(id=line_id, manifest=manifest)
        .first()
    )
    if line is None:
        raise LogisticsResourceUnavailableError
    subject_id_by_kind: dict[str, UUID | None] = {
        LogisticsManifestLine.SubjectKind.NODE: line.node_id,
        LogisticsManifestLine.SubjectKind.ASSET: line.asset_id,
        LogisticsManifestLine.SubjectKind.STOCK_LOT: line.stock_lot_id,
        LogisticsManifestLine.SubjectKind.KEY: line.physical_key_id,
    }
    subject_id = subject_id_by_kind.get(line.subject_kind)
    destination_node_id = line.packed_in_node_id or manifest.destination_node_id
    if subject_id is None or destination_node_id is None:
        raise LogisticsResourceUnavailableError
    normalized_condition = normalized_text(
        condition_after,
        field="condition_after",
        maximum=120,
        required=True,
        collapse=True,
    )
    normalized_reason_value = normalized_reason(reason)
    normalized_source = normalized_source_channel(source_channel)
    movement = MovementInput(
        event_type=LogisticsEvent.EventType.RECEIVE,
        subject=SubjectLocator(kind=line.subject_kind, object_id=subject_id),
        occurred_at=occurred_at,
        destination_node_id=destination_node_id,
        quantity=(
            line.quantity
            if line.subject_kind == LogisticsManifestLine.SubjectKind.STOCK_LOT
            else None
        ),
        condition_after=normalized_condition,
        manifest_id=manifest.id,
        evidence_reference=f"manifest-line:{line.id}",
    )
    request_digest = canonical_digest(
        {
            "manifest_id": str(manifest.id),
            "line_id": str(line.id),
            "expected_sequence": expected_sequence,
            "occurred_at": occurred_at,
            "condition_after": normalized_condition,
            "reason": normalized_reason_value,
        }
    )
    replay = _existing_receipt(
        actor=actor,
        operation="manifest.receive",
        idempotency_key=idempotency_key,
        organization_id=organization_id,
        request_digest=request_digest,
    )
    if replay is not None:
        return _command_result(replay, replayed=True)
    event, _ = _append_movement_event(
        actor=actor,
        organization=organization,
        edition=edition,
        movement=movement,
        expected_sequence=expected_sequence,
        reason=normalized_reason_value,
        source_channel=normalized_source,
    )
    return _append_evidence(
        actor=actor,
        organization=organization,
        edition=edition,
        operation="manifest.receive",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        result_object_id=event.id,
        resulting_version=event.event_sequence,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=normalized_source,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("manifest_line", "location", "condition", "quantity"),
        aggregate_type="logistics.event",
        aggregate_id=event.id,
        action=LogisticsEvent.EventType.RECEIVE,
        occurred_at=authorized_at,
    )
