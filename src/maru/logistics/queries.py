"""Policy-scoped logistics reads and purpose-minimized projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID, uuid4

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_edition_target,
    resolve_organization_target,
    resolve_self_target,
)
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.venues.models import EditionSpaceSelection
from maru.workforce.models import Department, PositionAssignment

from .authorization import resolve_logistics_manifest_target
from .inputs import normalized_source_channel
from .models import (
    Asset,
    AssetAgreement,
    EquipmentOffer,
    EquipmentOfferItem,
    LogisticsCurrentState,
    LogisticsDiscrepancy,
    LogisticsEvent,
    LogisticsLabel,
    LogisticsManifest,
    LogisticsManifestLine,
    LogisticsNode,
    LogisticsParty,
    PhysicalKey,
    RestrictedLogisticsAddress,
    StockLot,
)
from .services import (
    CATALOG_MANAGE_CAPABILITY,
    MANIFEST_MANAGE_CAPABILITY,
    MANIFEST_VIEW_CAPABILITY,
    RESTRICTED_CONTACT_CAPABILITY,
    SELF_OFFER_CAPABILITY,
    SELF_OFFER_EDITION_LIFECYCLES,
    WORKSPACE_VIEW_CAPABILITY,
    LogisticsAuthorizationDeniedError,
    LogisticsResourceUnavailableError,
)

MAX_WORKSPACE_ROWS = 2_000
MAX_ACTIVITY_ROWS = 1_000
MAX_PERSONAL_EDITION_CANDIDATES = 500
RESTRICTED_ACCESS_PURPOSES = frozenset(
    {
        "pickup_coordination",
        "provider_contact",
        "return_coordination",
        "inventory_verification",
        "incident_response",
    }
)


@dataclass(frozen=True, slots=True)
class OfferItemProjection:
    id: UUID
    kind: str
    name: str
    description: str
    quantity: int
    manufacturer: str
    model_name: str
    serial_number: str
    condition: str
    value_class: str
    ownership_statement: str


@dataclass(frozen=True, slots=True)
class SelfOfferProjection:
    id: UUID
    title: str
    description: str
    available_from: datetime
    available_until: datetime
    requested_return_at: datetime | None
    status: str
    review_reason: str
    aggregate_version: int
    pickup_label: str
    pickup_recipient_name: str
    pickup_postal_address: str
    pickup_access_instructions: str
    pickup_retention_until: datetime | None
    items: tuple[OfferItemProjection, ...]


@dataclass(frozen=True, slots=True)
class PersonalOfferEditionProjection:
    organization_slug: str
    organization_name: str
    series_slug: str
    series_name: str
    edition_slug: str
    edition_name: str
    edition_starts_on: date
    offer_count: int
    pending_offer_count: int
    can_submit: bool


@dataclass(frozen=True, slots=True)
class OfferQueueProjection:
    id: UUID
    offered_by_id: UUID
    title: str
    status: str
    item_count: int
    total_units: int
    available_from: datetime
    available_until: datetime
    requested_return_at: datetime | None
    responsible_department_id: UUID | None
    aggregate_version: int


@dataclass(frozen=True, slots=True)
class ManifestLineProjection:
    id: UUID
    subject_kind: str
    subject_id: UUID
    label_snapshot: str
    quantity: int
    packed_in_node_id: UUID | None
    packed_in_label: str
    notes: str
    current_sequence: int
    current_state: str


@dataclass(frozen=True, slots=True)
class ManifestProjection:
    id: UUID
    manifest_number: str
    kind: str
    title: str
    status: str
    responsible_department_id: UUID
    source_node_id: UUID | None
    source_name: str
    destination_node_id: UUID | None
    destination_name: str
    vehicle_id: UUID | None
    vehicle_name: str
    loading_starts_at: datetime | None
    loading_ends_at: datetime | None
    box_count: int
    line_count: int
    aggregate_version: int
    lines: tuple[ManifestLineProjection, ...]


@dataclass(frozen=True, slots=True)
class CurrentStateProjection:
    subject_kind: str
    subject_id: UUID
    subject_label: str
    current_node_id: UUID | None
    current_node_name: str
    custodian_account_id: UUID | None
    custodian_party_id: UUID | None
    condition: str
    quantity: int | None
    last_event_sequence: int
    last_occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ReturnProjection:
    agreement_id: UUID
    kind: str
    subject_kind: str
    subject_id: UUID
    provider_kind: str
    provider_id: UUID
    return_due_at: datetime
    returned: bool
    overdue: bool


@dataclass(frozen=True, slots=True)
class DiscrepancyProjection:
    id: UUID
    kind: str
    subject_kind: str
    subject_id: UUID
    expected_quantity: int | None
    observed_quantity: int | None
    description: str
    status: str
    aggregate_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActivityProjection:
    id: UUID
    sequence: int
    event_type: str
    subject_kind: str
    subject_id: UUID
    source_node_id: UUID | None
    destination_node_id: UUID | None
    from_custodian_account_id: UUID | None
    to_custodian_account_id: UUID | None
    quantity: int | None
    condition_before: str
    condition_after: str
    occurred_at: datetime
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class RestrictedContactProjection:
    address_id: UUID
    purpose: str
    label: str
    recipient_name: str
    contact_email: str
    contact_phone: str
    postal_address: str
    access_instructions: str
    retention_until: datetime | None
    subject_account_id: UUID | None
    party_id: UUID | None


@dataclass(frozen=True, slots=True)
class NamedLogisticsChoice:
    value: UUID
    label: str


@dataclass(frozen=True, slots=True)
class NamedLogisticsCodeChoice:
    value: str
    label: str


@dataclass(frozen=True, slots=True)
class LogisticsFormChoices:
    departments: tuple[NamedLogisticsChoice, ...]
    parties: tuple[NamedLogisticsChoice, ...]
    addresses: tuple[NamedLogisticsChoice, ...]
    nodes: tuple[NamedLogisticsChoice, ...]
    packing_nodes: tuple[NamedLogisticsChoice, ...]
    vehicles: tuple[NamedLogisticsChoice, ...]
    venue_rooms: tuple[NamedLogisticsChoice, ...]
    venue_space_selections: tuple[NamedLogisticsChoice, ...]
    assets: tuple[NamedLogisticsChoice, ...]
    stock_lots: tuple[NamedLogisticsChoice, ...]
    physical_keys: tuple[NamedLogisticsChoice, ...]
    tracked_subjects: tuple[NamedLogisticsChoice, ...]
    people: tuple[NamedLogisticsChoice, ...]
    manifests: tuple[NamedLogisticsChoice, ...]
    labels: tuple[NamedLogisticsCodeChoice, ...]


@dataclass(frozen=True, slots=True)
class LogisticsWorkspaceProjection:
    offers: tuple[OfferQueueProjection, ...]
    manifests: tuple[ManifestProjection, ...]
    current_states: tuple[CurrentStateProjection, ...]
    due_returns: tuple[ReturnProjection, ...]
    discrepancies: tuple[DiscrepancyProjection, ...]
    choices: LogisticsFormChoices


def _active_account(actor: Account, *, person_only: bool = False) -> None:
    if actor.pk is None or not actor.is_active or actor.is_platform_administrator:
        raise LogisticsAuthorizationDeniedError()
    if person_only and (
        actor.account_kind != Account.Kind.PERSON or actor.is_platform_administrator
    ):
        raise LogisticsAuthorizationDeniedError()


def _require_edition_decision(
    *, actor: Account, organization_id: UUID, edition_id: UUID, capability: str
) -> PolicyDecision:
    _active_account(actor)
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if target is None:
        raise LogisticsAuthorizationDeniedError()
    decision = decide(
        principal=actor,
        capability_code=capability,
        resource=target,
        at=timezone.now(),
    )
    if not decision.allowed:
        raise LogisticsAuthorizationDeniedError()
    return decision


def _require_self_decision(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> PolicyDecision:
    _active_account(actor, person_only=True)
    target = resolve_self_target(
        principal=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if target is None:
        raise LogisticsAuthorizationDeniedError()
    decision = decide(
        principal=actor,
        capability_code=SELF_OFFER_CAPABILITY,
        resource=target,
        at=timezone.now(),
    )
    if not decision.allowed:
        raise LogisticsAuthorizationDeniedError()
    return decision


def _append_operational_read_audit(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    decision: PolicyDecision,
    operation: str,
    target_count: int,
) -> None:
    correlation_id = uuid4()
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
            operation=operation,
            target_type="events.event_edition",
            target_id=edition_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="query",
            obligations=tuple(sorted(decision.obligations)),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "target_count": target_count,
            },
            retention_class="logistics-operational-read",
        ),
        occurred_at=timezone.now(),
    )


def authorize_logistics_api_scope(  # noqa: PLR0912
    *,
    actor: Account,
    organization_id: UUID,
    capability_code: str,
    edition_id: UUID | None = None,
    manifest_id: UUID | None = None,
    manifest_line_id: UUID | None = None,
    key_id: UUID | None = None,
    offer_id: UUID | None = None,
    address_id: UUID | None = None,
    require_self_offer_open: bool = False,
) -> None:
    """Preauthorize a scalar route scope before parsing any request-controlled input."""

    _active_account(actor)
    exact_resource_count = sum(
        value is not None for value in (manifest_id, key_id, offer_id, address_id)
    )
    if exact_resource_count > 1 or (
        manifest_line_id is not None and manifest_id is None
    ):
        raise LogisticsAuthorizationDeniedError()
    if require_self_offer_open and (
        capability_code != SELF_OFFER_CAPABILITY
        or edition_id is None
        or not EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            lifecycle__in=SELF_OFFER_EDITION_LIFECYCLES,
        ).exists()
    ):
        raise LogisticsAuthorizationDeniedError()
    if manifest_id is not None:
        if edition_id is None or capability_code not in {
            MANIFEST_MANAGE_CAPABILITY,
            MANIFEST_VIEW_CAPABILITY,
        }:
            raise LogisticsAuthorizationDeniedError()
        target = resolve_logistics_manifest_target(
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
        )
        if (
            manifest_line_id is not None
            and not LogisticsManifestLine.objects.filter(
                id=manifest_line_id,
                manifest_id=manifest_id,
                manifest__organization_id=organization_id,
                manifest__edition_id=edition_id,
            ).exists()
        ):
            raise LogisticsAuthorizationDeniedError()
    elif key_id is not None:
        if capability_code != CATALOG_MANAGE_CAPABILITY or edition_id is not None:
            raise LogisticsAuthorizationDeniedError()
        if (
            not PhysicalKey.objects.filter(
                id=key_id,
                organization_id=organization_id,
            )
            .only("id")
            .exists()
        ):
            raise LogisticsAuthorizationDeniedError()
        target = resolve_organization_target(organization_id=organization_id)
    elif offer_id is not None:
        if edition_id is None:
            raise LogisticsAuthorizationDeniedError()
        offer_scope = EquipmentOffer.objects.filter(
            id=offer_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if capability_code == SELF_OFFER_CAPABILITY:
            offer_scope = offer_scope.filter(offered_by=actor)
        if not offer_scope.only("id").exists():
            raise LogisticsAuthorizationDeniedError()
        target = (
            resolve_self_target(
                principal=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            if capability_code == SELF_OFFER_CAPABILITY
            else resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            )
        )
    elif address_id is not None:
        if edition_id is None or capability_code != RESTRICTED_CONTACT_CAPABILITY:
            raise LogisticsAuthorizationDeniedError()
        if not (
            RestrictedLogisticsAddress.objects.filter(
                Q(edition_id=edition_id) | Q(edition__isnull=True),
                id=address_id,
                organization_id=organization_id,
                lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
            )
            .filter(
                Q(retention_until__isnull=True) | Q(retention_until__gte=timezone.now())
            )
            .only("id")
            .exists()
        ):
            raise LogisticsAuthorizationDeniedError()
        target = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
    elif capability_code == SELF_OFFER_CAPABILITY:
        if edition_id is None:
            raise LogisticsAuthorizationDeniedError()
        target = resolve_self_target(
            principal=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    elif edition_id is not None:
        target = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
    else:
        target = resolve_organization_target(organization_id=organization_id)
    if target is None:
        raise LogisticsAuthorizationDeniedError()
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=target,
        at=timezone.now(),
    )
    if not decision.allowed:
        raise LogisticsAuthorizationDeniedError()


def authorize_self_offer_history_api_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> None:
    """Allow self policy or an existing owned offer, without loading scope labels."""

    _active_account(actor, person_only=True)
    try:
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=SELF_OFFER_CAPABILITY,
        )
    except LogisticsAuthorizationDeniedError:
        if (
            not EquipmentOffer.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                offered_by=actor,
            )
            .only("id")
            .exists()
        ):
            raise


def authorize_personal_logistics_index_scope(*, actor: Account) -> None:
    """Prove an active person before personal-index query parameters are read."""

    _active_account(actor, person_only=True)


def _line_subject_id(line: LogisticsManifestLine) -> UUID:
    value = line.node_id or line.asset_id or line.stock_lot_id or line.physical_key_id
    if value is None:
        raise LogisticsResourceUnavailableError()
    return value


def _line_current_state(
    line: LogisticsManifestLine,
) -> tuple[int, str]:
    subject: LogisticsNode | Asset | StockLot | PhysicalKey | None
    if line.subject_kind == LogisticsEvent.SubjectKind.NODE:
        subject = line.node
    elif line.subject_kind == LogisticsEvent.SubjectKind.ASSET:
        subject = line.asset
    elif line.subject_kind == LogisticsEvent.SubjectKind.STOCK_LOT:
        subject = line.stock_lot
    elif line.subject_kind == LogisticsEvent.SubjectKind.KEY:
        subject = line.physical_key
    else:
        raise LogisticsResourceUnavailableError()
    if subject is None:
        raise LogisticsResourceUnavailableError()
    state = getattr(subject, "current_state", None)
    if state is None:
        return 0, "unreceived"
    return state.event_sequence, state.state


def _state_subject(state: LogisticsCurrentState) -> tuple[str, UUID, str]:
    if state.asset_id:
        asset = state.asset
        if asset is None:
            raise LogisticsResourceUnavailableError()
        return LogisticsEvent.SubjectKind.ASSET, state.asset_id, asset.name
    if state.stock_lot_id:
        stock_lot = state.stock_lot
        if stock_lot is None:
            raise LogisticsResourceUnavailableError()
        return (
            LogisticsEvent.SubjectKind.STOCK_LOT,
            state.stock_lot_id,
            stock_lot.name,
        )
    if state.physical_key_id:
        physical_key = state.physical_key
        if physical_key is None:
            raise LogisticsResourceUnavailableError()
        return (
            LogisticsEvent.SubjectKind.KEY,
            state.physical_key_id,
            physical_key.label,
        )
    if state.node_id:
        node = state.node
        if node is None:
            raise LogisticsResourceUnavailableError()
        return LogisticsEvent.SubjectKind.NODE, state.node_id, node.name
    raise LogisticsResourceUnavailableError()


def list_self_offers(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[SelfOfferProjection, ...]:
    """Return one person's own offers, including only their own pickup address."""
    _active_account(actor, person_only=True)
    try:
        _require_self_decision(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    except LogisticsAuthorizationDeniedError:
        if not EquipmentOffer.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            offered_by=actor,
        ).exists():
            raise
    offers = (
        EquipmentOffer.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            offered_by=actor,
        )
        .select_related("pickup_address")
        .prefetch_related("items")
        .order_by("-created_at", "id")[:MAX_WORKSPACE_ROWS]
    )
    evaluated_at = timezone.now()
    projected: list[SelfOfferProjection] = []
    for offer in offers:
        address = offer.pickup_address
        contact_visible = (
            address.lifecycle == RestrictedLogisticsAddress.Lifecycle.ACTIVE
            and (
                address.retention_until is None
                or address.retention_until >= evaluated_at
            )
        )
        projected.append(
            SelfOfferProjection(
                id=offer.id,
                title=offer.title,
                description=offer.description,
                available_from=offer.available_from,
                available_until=offer.available_until,
                requested_return_at=offer.requested_return_at,
                status=offer.status,
                review_reason=offer.review_reason,
                aggregate_version=offer.aggregate_version,
                pickup_label=(
                    address.label if contact_visible else "Pickup details expired"
                ),
                pickup_recipient_name=(
                    address.recipient_name if contact_visible else ""
                ),
                pickup_postal_address=(
                    address.postal_address if contact_visible else ""
                ),
                pickup_access_instructions=(
                    address.access_instructions if contact_visible else ""
                ),
                pickup_retention_until=address.retention_until,
                items=tuple(
                    OfferItemProjection(
                        id=item.id,
                        kind=item.kind,
                        name=item.name,
                        description=item.description,
                        quantity=item.quantity,
                        manufacturer=item.manufacturer,
                        model_name=item.model_name,
                        serial_number=item.serial_number,
                        condition=item.condition,
                        value_class=item.value_class,
                        ownership_statement=item.ownership_statement,
                    )
                    for item in offer.items.all()
                ),
            )
        )
    return tuple(projected)


def can_submit_equipment_offer(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> bool:
    if not EventEdition.objects.filter(
        id=edition_id,
        organization_id=organization_id,
        lifecycle__in=SELF_OFFER_EDITION_LIFECYCLES,
    ).exists():
        return False
    try:
        _require_self_decision(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    except LogisticsAuthorizationDeniedError:
        return False
    return True


def my_equipment_offer_editions(
    *, actor: Account
) -> tuple[PersonalOfferEditionProjection, ...]:
    """Discover only authorized or self-owned offer scopes without admin context."""
    _active_account(actor, person_only=True)
    own_counts = {
        (row["organization_id"], row["edition_id"]): (
            row["offer_count"],
            row["pending_count"],
        )
        for row in EquipmentOffer.objects.filter(offered_by=actor)
        .values("organization_id", "edition_id")
        .annotate(
            offer_count=Count("id"),
            pending_count=Count(
                "id",
                filter=Q(status=EquipmentOffer.Status.PENDING),
            ),
        )[:MAX_PERSONAL_EDITION_CANDIDATES]
    }
    available_scopes: set[tuple[UUID, UUID]] = set()
    candidate_scopes = (
        EventEdition.objects.filter(lifecycle__in=SELF_OFFER_EDITION_LIFECYCLES)
        .order_by("-starts_on", "organization_id", "id")
        .values_list("organization_id", "id")
    )
    for organization_id, edition_id in candidate_scopes.iterator(chunk_size=256):
        if can_submit_equipment_offer(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        ):
            available_scopes.add((organization_id, edition_id))
            if len(available_scopes) >= MAX_PERSONAL_EDITION_CANDIDATES:
                break
    visible_scopes = set(own_counts) | available_scopes
    can_submit_by_scope = {scope: scope in available_scopes for scope in visible_scopes}
    edition_by_scope = {
        (edition.organization_id, edition.id): edition
        for edition in EventEdition.objects.filter(
            id__in={edition_id for _, edition_id in visible_scopes}
        )
        .select_related("organization", "series")
        .order_by("-starts_on", "name", "id")
    }
    projected: list[PersonalOfferEditionProjection] = []
    for scope, edition in edition_by_scope.items():
        can_submit = can_submit_by_scope.get(scope, False)
        counts = own_counts.get(scope, (0, 0))
        if not can_submit and counts[0] == 0:
            continue
        projected.append(
            PersonalOfferEditionProjection(
                organization_slug=edition.organization.slug,
                organization_name=edition.organization.name,
                series_slug=edition.series.slug,
                series_name=edition.series.name,
                edition_slug=edition.slug,
                edition_name=edition.name,
                edition_starts_on=edition.starts_on,
                offer_count=counts[0],
                pending_offer_count=counts[1],
                can_submit=can_submit,
            )
        )
    return tuple(
        sorted(
            projected,
            key=lambda item: (
                item.edition_starts_on,
                item.edition_name,
                item.organization_name,
            ),
            reverse=True,
        )
    )


def _manifest_projection(
    manifest: LogisticsManifest, *, include_lines: bool
) -> ManifestProjection:
    lines = tuple(manifest.lines.all())
    box_ids = {
        line.node_id
        for line in lines
        if line.node_id and line.node and line.node.kind == line.node.Kind.BOX
    }
    box_ids.update(
        line.packed_in_node_id
        for line in lines
        if line.packed_in_node_id
        and line.packed_in_node
        and line.packed_in_node.kind == line.packed_in_node.Kind.BOX
    )
    projected_lines: tuple[ManifestLineProjection, ...] = ()
    if include_lines:
        projected_lines = tuple(
            ManifestLineProjection(
                id=line.id,
                subject_kind=line.subject_kind,
                subject_id=_line_subject_id(line),
                label_snapshot=line.label_snapshot,
                quantity=line.quantity,
                packed_in_node_id=line.packed_in_node_id,
                packed_in_label=(
                    line.packed_in_node.name if line.packed_in_node else ""
                ),
                notes=line.notes,
                current_sequence=_line_current_state(line)[0],
                current_state=_line_current_state(line)[1],
            )
            for line in lines
        )
    return ManifestProjection(
        id=manifest.id,
        manifest_number=manifest.manifest_number,
        kind=manifest.kind,
        title=manifest.title,
        status=manifest.status,
        responsible_department_id=manifest.responsible_department_id,
        source_node_id=manifest.source_node_id,
        source_name=manifest.source_node.name if manifest.source_node else "",
        destination_node_id=manifest.destination_node_id,
        destination_name=(
            manifest.destination_node.name if manifest.destination_node else ""
        ),
        vehicle_id=manifest.vehicle_id,
        vehicle_name=manifest.vehicle.name if manifest.vehicle else "",
        loading_starts_at=manifest.loading_starts_at,
        loading_ends_at=manifest.loading_ends_at,
        box_count=len(box_ids),
        line_count=len(lines),
        aggregate_version=manifest.aggregate_version,
        lines=projected_lines,
    )


def _manifest_queryset(
    *, organization_id: UUID, edition_id: UUID
) -> QuerySet[LogisticsManifest]:
    return (
        LogisticsManifest.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related(
            "responsible_department",
            "source_node",
            "destination_node",
            "vehicle",
        )
        .prefetch_related(
            "lines__node",
            "lines__node__current_state",
            "lines__asset",
            "lines__asset__current_state",
            "lines__stock_lot",
            "lines__stock_lot__current_state",
            "lines__physical_key",
            "lines__physical_key__current_state",
            "lines__packed_in_node",
        )
    )


def _return_subject(agreement: AssetAgreement) -> tuple[str, UUID]:
    if agreement.asset_id:
        return LogisticsEvent.SubjectKind.ASSET, agreement.asset_id
    if agreement.stock_lot_id:
        return LogisticsEvent.SubjectKind.STOCK_LOT, agreement.stock_lot_id
    if agreement.physical_key_id:
        return LogisticsEvent.SubjectKind.KEY, agreement.physical_key_id
    if agreement.node_id:
        return LogisticsEvent.SubjectKind.NODE, agreement.node_id
    raise LogisticsResourceUnavailableError()


def _subject_state_filter(subject_kind: str, subject_id: UUID) -> Q:
    field_by_kind: dict[str, str] = {
        LogisticsEvent.SubjectKind.ASSET: "asset_id",
        LogisticsEvent.SubjectKind.STOCK_LOT: "stock_lot_id",
        LogisticsEvent.SubjectKind.KEY: "physical_key_id",
        LogisticsEvent.SubjectKind.NODE: "node_id",
    }
    field = field_by_kind.get(subject_kind)
    if field is None:
        raise LogisticsResourceUnavailableError()
    return Q(**{field: subject_id})


def _return_projection(
    agreement: AssetAgreement, *, evaluated_at: datetime
) -> ReturnProjection:
    subject_kind, subject_id = _return_subject(agreement)
    state = (
        LogisticsCurrentState.objects.filter(
            _subject_state_filter(subject_kind, subject_id)
        )
        .select_related("last_event")
        .first()
    )
    returned = bool(
        state
        and state.last_event.event_type == LogisticsEvent.EventType.RETURN
        and state.last_event.occurred_at >= agreement.starts_at
    )
    provider_kind = "account" if agreement.provider_account_id else "party"
    provider_id = agreement.provider_account_id or agreement.provider_id
    if provider_id is None:
        raise LogisticsResourceUnavailableError()
    return ReturnProjection(
        agreement_id=agreement.id,
        kind=agreement.kind,
        subject_kind=subject_kind,
        subject_id=subject_id,
        provider_kind=provider_kind,
        provider_id=provider_id,
        return_due_at=agreement.return_due_at,
        returned=returned,
        overdue=not returned and agreement.return_due_at < evaluated_at,
    )


def _form_choices(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    evaluated_at: datetime,
) -> LogisticsFormChoices:
    departments = tuple(
        NamedLogisticsChoice(value=row.id, label=row.name)
        for row in Department.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            retired_at__isnull=True,
        ).order_by("display_order", "name", "id")[:MAX_WORKSPACE_ROWS]
    )
    parties = tuple(
        NamedLogisticsChoice(
            value=row.id,
            label=f"{row.public_name} ({row.get_role_display()})",
        )
        for row in LogisticsParty.objects.filter(
            organization_id=organization_id,
            lifecycle=LogisticsParty.Lifecycle.ACTIVE,
        ).order_by("public_name", "id")[:MAX_WORKSPACE_ROWS]
    )
    addresses = tuple(
        NamedLogisticsChoice(
            value=row.id,
            label=f"{row.label} ({row.get_purpose_display()})",
        )
        for row in RestrictedLogisticsAddress.objects.filter(
            Q(edition_id=edition_id) | Q(edition__isnull=True),
            Q(retention_until__isnull=True) | Q(retention_until__gte=evaluated_at),
            organization_id=organization_id,
            lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
        ).order_by("purpose", "label", "id")[:MAX_WORKSPACE_ROWS]
    )
    node_rows = tuple(
        LogisticsNode.objects.filter(
            Q(edition_id=edition_id) | Q(edition__isnull=True),
            organization_id=organization_id,
            lifecycle=LogisticsNode.Lifecycle.ACTIVE,
        ).order_by("kind", "name", "id")[:MAX_WORKSPACE_ROWS]
    )
    nodes = tuple(
        NamedLogisticsChoice(
            value=row.id,
            label=f"{row.name} ({row.get_kind_display()})",
        )
        for row in node_rows
    )
    packing_nodes = tuple(
        choice
        for row, choice in zip(node_rows, nodes, strict=True)
        if row.kind
        in {
            LogisticsNode.Kind.BOX,
            LogisticsNode.Kind.CONTAINER,
            LogisticsNode.Kind.VEHICLE,
        }
    )
    vehicles = tuple(
        choice
        for row, choice in zip(node_rows, nodes, strict=True)
        if row.kind == LogisticsNode.Kind.VEHICLE
    )
    venue_rooms = tuple(
        choice
        for row, choice in zip(node_rows, nodes, strict=True)
        if row.kind == LogisticsNode.Kind.VENUE_ROOM
    )
    venue_space_selections = tuple(
        NamedLogisticsChoice(value=row.id, label=row.local_name)
        for row in EditionSpaceSelection.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
        ).order_by("local_name", "id")[:MAX_WORKSPACE_ROWS]
    )
    asset_rows = tuple(
        Asset.objects.filter(
            Q(edition_allocation_id=edition_id) | Q(edition_allocation__isnull=True),
            organization_id=organization_id,
            lifecycle=Asset.Lifecycle.ACTIVE,
        ).order_by("name", "id")[:MAX_WORKSPACE_ROWS]
    )
    assets = tuple(
        NamedLogisticsChoice(value=row.id, label=f"{row.name} (asset)")
        for row in asset_rows
    )
    stock_rows = tuple(
        StockLot.objects.filter(
            Q(edition_allocation_id=edition_id) | Q(edition_allocation__isnull=True),
            organization_id=organization_id,
            lifecycle=StockLot.Lifecycle.ACTIVE,
        ).order_by("name", "id")[:MAX_WORKSPACE_ROWS]
    )
    stock_lots = tuple(
        NamedLogisticsChoice(value=row.id, label=f"{row.name} (stock lot)")
        for row in stock_rows
    )
    key_rows = tuple(
        PhysicalKey.objects.filter(
            Q(edition_allocation_id=edition_id) | Q(edition_allocation__isnull=True),
            organization_id=organization_id,
            lifecycle=PhysicalKey.Lifecycle.ACTIVE,
        ).order_by("label", "id")[:MAX_WORKSPACE_ROWS]
    )
    physical_keys = tuple(
        NamedLogisticsChoice(value=row.id, label=f"{row.label} (physical key)")
        for row in key_rows
    )
    tracked_subjects = assets + stock_lots + physical_keys + nodes
    account_ids = set(
        PositionAssignment.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=PositionAssignment.Status.ACTIVE,
        ).values_list("account_id", flat=True)
    )
    account_ids.update(
        EquipmentOffer.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        ).values_list("offered_by_id", flat=True)
    )
    account_ids.add(actor.id)
    people = tuple(
        NamedLogisticsChoice(value=row.id, label=str(row))
        for row in Account.objects.filter(
            id__in=account_ids,
            is_active=True,
            account_kind=Account.Kind.PERSON,
        ).order_by("display_name", "login_handle", "id")[:MAX_WORKSPACE_ROWS]
        if not row.is_platform_administrator
    )
    manifests = tuple(
        NamedLogisticsChoice(
            value=row.id,
            label=f"{row.manifest_number} - {row.title} ({row.status})",
        )
        for row in LogisticsManifest.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("manifest_number", "id")[:MAX_WORKSPACE_ROWS]
    )
    labels = tuple(
        NamedLogisticsCodeChoice(value=row.label_code, label=row.label_code)
        for row in LogisticsLabel.objects.filter(
            Q(node__edition_id=edition_id)
            | Q(node__edition__isnull=True)
            | Q(asset__edition_allocation_id=edition_id)
            | Q(asset__edition_allocation__isnull=True)
            | Q(stock_lot__edition_allocation_id=edition_id)
            | Q(stock_lot__edition_allocation__isnull=True)
            | Q(physical_key__edition_allocation_id=edition_id)
            | Q(physical_key__edition_allocation__isnull=True),
            organization_id=organization_id,
            lifecycle=LogisticsLabel.Lifecycle.ACTIVE,
        )
        .distinct()
        .order_by("label_code", "id")[:MAX_WORKSPACE_ROWS]
    )
    return LogisticsFormChoices(
        departments=departments,
        parties=parties,
        addresses=addresses,
        nodes=nodes,
        packing_nodes=packing_nodes,
        vehicles=vehicles,
        venue_rooms=venue_rooms,
        venue_space_selections=venue_space_selections,
        assets=assets,
        stock_lots=stock_lots,
        physical_keys=physical_keys,
        tracked_subjects=tracked_subjects,
        people=people,
        manifests=manifests,
        labels=labels,
    )


def list_logistics_workspace(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> LogisticsWorkspaceProjection:
    """Return operational metadata without pickup addresses or party contacts."""
    decision = _require_edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability=WORKSPACE_VIEW_CAPABILITY,
    )
    offer_rows = (
        EquipmentOffer.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .annotate(item_count_value=Count("items"))
        .order_by("status", "available_from", "id")[:MAX_WORKSPACE_ROWS]
    )
    offers = tuple(
        OfferQueueProjection(
            id=offer.id,
            offered_by_id=offer.offered_by_id,
            title=offer.title,
            status=offer.status,
            item_count=offer.item_count_value,
            total_units=sum(
                EquipmentOfferItem.objects.filter(offer=offer).values_list(
                    "quantity", flat=True
                )
            ),
            available_from=offer.available_from,
            available_until=offer.available_until,
            requested_return_at=offer.requested_return_at,
            responsible_department_id=offer.responsible_department_id,
            aggregate_version=offer.aggregate_version,
        )
        for offer in offer_rows
    )
    manifests = tuple(
        _manifest_projection(manifest, include_lines=False)
        for manifest in _manifest_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("status", "manifest_number", "id")[:MAX_WORKSPACE_ROWS]
    )
    states = tuple(
        LogisticsCurrentState.objects.filter(
            organization_id=organization_id,
            last_event__edition_id=edition_id,
        )
        .select_related(
            "node",
            "asset",
            "stock_lot",
            "physical_key",
            "current_node",
            "last_event",
        )
        .order_by("last_event__occurred_at", "id")[:MAX_WORKSPACE_ROWS]
    )
    current_states: list[CurrentStateProjection] = []
    for state in states:
        subject_kind, subject_id, subject_label = _state_subject(state)
        current_states.append(
            CurrentStateProjection(
                subject_kind=subject_kind,
                subject_id=subject_id,
                subject_label=subject_label,
                current_node_id=state.current_node_id,
                current_node_name=(
                    state.current_node.name if state.current_node else ""
                ),
                custodian_account_id=state.custodian_account_id,
                custodian_party_id=state.custodian_party_id,
                condition=state.condition,
                quantity=state.quantity_on_hand,
                last_event_sequence=state.event_sequence,
                last_occurred_at=state.last_event.occurred_at,
            )
        )
    evaluated_at = timezone.now()
    due_returns = tuple(
        _return_projection(agreement, evaluated_at=evaluated_at)
        for agreement in AssetAgreement.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .select_related("provider", "provider_account")
        .order_by("return_due_at", "id")[:MAX_WORKSPACE_ROWS]
    )
    discrepancies = tuple(
        DiscrepancyProjection(
            id=row.id,
            kind=row.kind,
            subject_kind=row.subject_kind,
            subject_id=row.subject_id,
            expected_quantity=row.expected_quantity,
            observed_quantity=row.observed_quantity,
            description=row.description,
            status=row.status,
            aggregate_version=row.aggregate_version,
            created_at=row.created_at,
        )
        for row in LogisticsDiscrepancy.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=LogisticsDiscrepancy.Status.OPEN,
        ).order_by("created_at", "id")[:MAX_WORKSPACE_ROWS]
    )
    choices = _form_choices(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        evaluated_at=evaluated_at,
    )
    projection = LogisticsWorkspaceProjection(
        offers=offers,
        manifests=manifests,
        current_states=tuple(current_states),
        due_returns=due_returns,
        discrepancies=discrepancies,
        choices=choices,
    )
    _append_operational_read_audit(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        decision=decision,
        operation="logistics.workspace.read",
        target_count=(
            len(offers)
            + len(manifests)
            + len(current_states)
            + len(due_returns)
            + len(discrepancies)
            + len(choices.people)
        ),
    )
    return projection


def manifest_for_workspace(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    manifest_id: UUID,
) -> ManifestProjection:
    """Return one exact manifest only after typed-resource authorization."""
    try:
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            capability_code=MANIFEST_VIEW_CAPABILITY,
        )
    except LogisticsAuthorizationDeniedError:
        authorize_logistics_api_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            capability_code=MANIFEST_MANAGE_CAPABILITY,
        )
    manifest = (
        _manifest_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .filter(id=manifest_id)
        .first()
    )
    if manifest is None:
        raise LogisticsResourceUnavailableError()
    return _manifest_projection(manifest, include_lines=True)


def stage_tech_receiving_manifests(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[ManifestProjection, ...]:
    _require_edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability=WORKSPACE_VIEW_CAPABILITY,
    )
    manifests = (
        _manifest_queryset(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .filter(
            kind=LogisticsManifest.Kind.STAGE_RECEIVING,
            status__in=(
                LogisticsManifest.Status.SEALED,
                LogisticsManifest.Status.COMPLETED,
            ),
        )
        .order_by("loading_starts_at", "manifest_number", "id")[:MAX_WORKSPACE_ROWS]
    )
    return tuple(
        _manifest_projection(manifest, include_lines=True) for manifest in manifests
    )


def list_logistics_activity(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> tuple[ActivityProjection, ...]:
    decision = _require_edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability=WORKSPACE_VIEW_CAPABILITY,
    )
    activity = tuple(
        ActivityProjection(
            id=event.id,
            sequence=event.event_sequence,
            event_type=event.event_type,
            subject_kind=event.subject_kind,
            subject_id=(
                cast(
                    UUID,
                    event.node_id
                    or event.asset_id
                    or event.stock_lot_id
                    or event.physical_key_id,
                )
            ),
            source_node_id=event.source_node_id,
            destination_node_id=event.destination_node_id,
            from_custodian_account_id=event.from_custodian_account_id,
            to_custodian_account_id=event.to_custodian_account_id,
            quantity=event.quantity,
            condition_before=event.condition_before,
            condition_after=event.condition_after,
            occurred_at=event.occurred_at,
            actor_id=event.actor_id,
        )
        for event in LogisticsEvent.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        ).order_by("-occurred_at", "-created_at", "id")[:MAX_ACTIVITY_ROWS]
    )
    _append_operational_read_audit(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        decision=decision,
        operation="logistics.activity.read",
        target_count=len(activity),
    )
    return activity


def read_restricted_logistics_contact(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    address_id: UUID,
    purpose: str,
    access_purpose: str,
    access_request_id: UUID | None = None,
    correlation_id: UUID | None = None,
    request_id: UUID | None = None,
    source_channel: str = "web",
) -> RestrictedContactProjection:
    """Read one active purpose-bound address and audit the sensitive access."""
    if purpose not in RestrictedLogisticsAddress.Purpose.values:
        raise LogisticsResourceUnavailableError()
    if access_purpose not in RESTRICTED_ACCESS_PURPOSES:
        raise LogisticsResourceUnavailableError()
    decision = _require_edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability=RESTRICTED_CONTACT_CAPABILITY,
    )
    evaluated_at = timezone.now()
    address = (
        RestrictedLogisticsAddress.objects.filter(
            Q(edition_id=edition_id) | Q(edition__isnull=True),
            id=address_id,
            organization_id=organization_id,
            purpose=purpose,
            lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
        )
        .filter(Q(retention_until__isnull=True) | Q(retention_until__gte=evaluated_at))
        .first()
    )
    if address is None:
        raise LogisticsResourceUnavailableError()
    normalized_source = normalized_source_channel(source_channel)
    audit_correlation_id = correlation_id or uuid4()
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=RESTRICTED_CONTACT_CAPABILITY,
            operation="logistics.restricted_contact.read",
            target_type="logistics.restricted_address",
            target_id=address.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=audit_correlation_id,
            causation_id=access_request_id,
            request_id=request_id or audit_correlation_id,
            source_channel=normalized_source,
            obligations=tuple(sorted(decision.obligations)),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": access_purpose,
            },
            retention_class="logistics-restricted-contact",
        ),
        occurred_at=evaluated_at,
    )
    return RestrictedContactProjection(
        address_id=address.id,
        purpose=address.purpose,
        label=address.label,
        recipient_name=address.recipient_name,
        contact_email=address.contact_email,
        contact_phone=address.contact_phone,
        postal_address=address.postal_address,
        access_instructions=address.access_instructions,
        retention_until=address.retention_until,
        subject_account_id=address.subject_account_id,
        party_id=address.party_id,
    )


def prepare_restricted_contact_request(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    address_id: UUID,
    purpose: str,
    access_purpose: str,
    correlation_id: UUID | None = None,
    request_id: UUID | None = None,
    source_channel: str = "web",
) -> UUID:
    """Authorize an opaque PRG request without reading contact fields."""
    if (
        purpose not in RestrictedLogisticsAddress.Purpose.values
        or access_purpose not in RESTRICTED_ACCESS_PURPOSES
    ):
        raise LogisticsResourceUnavailableError()
    decision = _require_edition_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability=RESTRICTED_CONTACT_CAPABILITY,
    )
    evaluated_at = timezone.now()
    address_exists = (
        RestrictedLogisticsAddress.objects.filter(
            Q(edition_id=edition_id) | Q(edition__isnull=True),
            id=address_id,
            organization_id=organization_id,
            purpose=purpose,
            lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
        )
        .filter(Q(retention_until__isnull=True) | Q(retention_until__gte=evaluated_at))
        .only("id")
        .exists()
    )
    if not address_exists:
        raise LogisticsResourceUnavailableError()
    audit_correlation_id = correlation_id or uuid4()
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=RESTRICTED_CONTACT_CAPABILITY,
            operation=f"logistics.restricted_contact.request.{purpose}",
            target_type="logistics.restricted_address",
            target_id=address_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=audit_correlation_id,
            request_id=request_id or audit_correlation_id,
            source_channel=normalized_source_channel(source_channel),
            obligations=tuple(sorted(decision.obligations)),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": access_purpose,
            },
            retention_class="logistics-restricted-contact",
        ),
        occurred_at=evaluated_at,
    )
    return audit.id
