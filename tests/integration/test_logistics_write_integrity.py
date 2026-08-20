"""PostgreSQL correspondence and tamper coverage for Logistics evidence."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.authorization.models import ScopedResourceBinding
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.logistics.models import (
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
    OfflineOperationReceipt,
    OfflineScanBatch,
    OfflineScanOperation,
    PhysicalKey,
    RestrictedLogisticsAddress,
    ReusableKit,
    ReusableKitLine,
    StockLot,
)
from maru.logistics.queries import (
    can_submit_equipment_offer,
    list_logistics_activity,
    list_logistics_workspace,
    list_self_offers,
    manifest_for_workspace,
    my_equipment_offer_editions,
    prepare_restricted_contact_request,
    read_restricted_logistics_contact,
    stage_tech_receiving_manifests,
)
from maru.logistics.services import (
    CATALOG_MANAGE_CAPABILITY,
    MANIFEST_MANAGE_CAPABILITY,
    OFFER_REVIEW_CAPABILITY,
    OFFLINE_RECONCILE_CAPABILITY,
    OPERATIONS_MANAGE_CAPABILITY,
    RESTRICTED_CONTACT_CAPABILITY,
    WORKSPACE_VIEW_CAPABILITY,
    KitLineInput,
    LogisticsContainmentCycleError,
    ManifestLineInput,
    MovementInput,
    OfferItemInput,
    OfflineOperationInput,
    SubjectLocator,
    add_manifest_line,
    assign_keyholder_responsibility,
    change_manifest_state,
    create_logistics_label,
    create_logistics_manifest,
    create_logistics_node,
    create_reusable_kit,
    ingest_offline_scan_batch,
    record_logistics_event,
    record_manifest_receipt,
    register_physical_key,
    register_serialized_asset,
    register_stock_lot,
    review_equipment_offer,
    submit_equipment_offer,
    withdraw_equipment_offer,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from maru.identity.models import Account
    from maru.workforce.models import Department

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]

_integrity_migration = importlib.import_module(
    "maru.logistics.migrations.0002_logistics_write_integrity"
)


@dataclass(frozen=True, slots=True)
class _World:
    edition: EventEdition
    operator: Account
    offerer: Account
    department: Department


@dataclass(frozen=True, slots=True)
class _OfferWindow:
    available_from: datetime
    available_until: datetime
    return_due_at: datetime


def _world() -> _World:
    edition = EventEditionFactory()
    operator = AccountFactory()
    offerer = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=operator,
        capability_code="events.transition",
    )
    command_id = uuid4()
    edition = transition_edition(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        to_state=EventEdition.Lifecycle.PREPARING,
        actor=operator,
        reason="Prepare deterministic Logistics integrity coverage.",
        correlation_id=command_id,
        request_id=command_id,
        source_channel="test",
    )
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=None,
        principal=operator,
        capability_code=CATALOG_MANAGE_CAPABILITY,
    )
    for capability_code in (
        OPERATIONS_MANAGE_CAPABILITY,
        OFFER_REVIEW_CAPABILITY,
        OFFLINE_RECONCILE_CAPABILITY,
    ):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=operator,
            capability_code=capability_code,
        )
    department = create_department_for_test(
        edition=edition,
        name="Logistics Integrity",
        expected_code="logistics-integrity",
    )
    return _World(
        edition=edition,
        operator=operator,
        offerer=offerer,
        department=department,
    )


def _asset(world: _World, *, code: str, allocated: bool = True) -> Asset:
    result = register_serialized_asset(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id if allocated else None,
        catalog_code=code,
        name=f"Integrity asset {code}",
        asset_type="test_equipment",
        manufacturer="Synthetic Works",
        model_name="Integrity",
        serial_number=f"SERIAL-{code}",
        acquisition=Asset.Acquisition.OWNED,
        value_class="standard",
        owner_kind=Asset.OwnerKind.ORGANIZATION,
        owner_account_id=None,
        owner_party_id=None,
        reason="Register deterministic integrity-test inventory.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return Asset.objects.get(id=result.object_id)


def _stock_lot(world: _World, *, code: str, quantity: int = 10) -> StockLot:
    result = register_stock_lot(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        catalog_code=code,
        name=f"Integrity lot {code}",
        stock_type="test_stock",
        unit="item",
        initial_quantity=quantity,
        value_class="standard",
        owner_kind=StockLot.OwnerKind.ORGANIZATION,
        owner_account_id=None,
        owner_party_id=None,
        reason="Register deterministic integrity-test stock.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return StockLot.objects.get(id=result.object_id)


def _node(
    world: _World,
    *,
    code: str,
    kind: str = LogisticsNode.Kind.STAGING_AREA,
) -> LogisticsNode:
    result = create_logistics_node(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        kind=kind,
        code=code,
        name=f"Integrity node {code}",
        description="Synthetic physical location for trigger coverage.",
        edition_id=world.edition.id,
        storage_address_id=None,
        external_owner_id=None,
        provider_id=None,
        vehicle_registration="SYNTHETIC-1"
        if kind == LogisticsNode.Kind.VEHICLE
        else "",
        venue_space_selection_id=None,
        capacity_note="",
        reason="Register deterministic integrity-test location.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return LogisticsNode.objects.get(id=result.object_id)


def _label(
    world: _World,
    *,
    subject: SubjectLocator,
    code: str,
) -> LogisticsLabel:
    result = create_logistics_label(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        subject=subject,
        label_code=code,
        qr_identifier=f"integrity-{uuid4().hex}",
        reason="Create deterministic offline reconciliation label.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return LogisticsLabel.objects.get(id=result.object_id)


def _grant_manifest(world: _World, *, manifest_id: UUID) -> None:
    binding = ScopedResourceBinding.objects.get(
        resource_kind="logistics.manifest",
        resource_id=manifest_id,
    )
    CapabilityGrantFactory(
        organization=world.edition.organization,
        edition=world.edition,
        department=world.department,
        resource_binding=binding,
        principal=world.operator,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
    )


def _submit_offer(
    world: _World,
    *,
    items: tuple[OfferItemInput, ...],
    now,
) -> tuple[UUID, _OfferWindow]:
    available_from = now + timedelta(days=1)
    available_until = now + timedelta(days=4)
    return_due_at = now + timedelta(days=6)
    result = submit_equipment_offer(
        actor=world.offerer,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        title="Composite transaction offer",
        description="Synthetic offer for deferred history correspondence.",
        pickup_label="Synthetic workshop",
        pickup_recipient_name="Offer owner",
        pickup_postal_address="Example synthetic pickup address",
        pickup_access_instructions="Use the integrity-test entrance.",
        pickup_retention_until=return_due_at,
        available_from=available_from,
        available_until=available_until,
        requested_return_at=return_due_at,
        items=items,
        reason="Submit canonical offer evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now,
    )
    return result.object_id, _OfferWindow(
        available_from=available_from,
        available_until=available_until,
        return_due_at=return_due_at,
    )


def _record_event(
    world: _World,
    *,
    subject: SubjectLocator,
    event_type: str,
    expected_sequence: int,
    occurred_at,
    source_node_id: UUID | None = None,
    destination_node_id: UUID | None = None,
    quantity: int | None = None,
    condition_after: str = "",
    manifest_id: UUID | None = None,
):
    return record_logistics_event(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        movement=MovementInput(
            event_type=event_type,
            subject=subject,
            occurred_at=occurred_at,
            source_node_id=source_node_id,
            destination_node_id=destination_node_id,
            quantity=quantity,
            condition_after=condition_after,
            manifest_id=manifest_id,
        ),
        expected_sequence=expected_sequence,
        reason="Record deterministic custody evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def _assert_canonical_acceptance(
    *,
    acceptance: EquipmentOfferAcceptance,
    offer: EquipmentOffer,
    world: _World,
    window: _OfferWindow,
) -> None:
    item = acceptance.offer_item
    assert acceptance.accepted_by_id == world.operator.id
    assert acceptance.accepted_at == offer.reviewed_at
    agreement = AssetAgreement.objects.get(offer_acceptance=acceptance)
    assert agreement.kind == AssetAgreement.Kind.LOAN
    assert agreement.provider_account_id == world.offerer.id
    assert agreement.provider_id is None
    assert agreement.borrower_account_id is None
    assert agreement.borrower_party_id is None
    assert agreement.starts_at == window.available_from
    assert agreement.ends_at == window.available_until
    assert agreement.return_due_at == window.return_due_at
    assert agreement.created_by_id == world.operator.id
    if item.kind == EquipmentOfferItem.Kind.SERIALIZED:
        assert acceptance.asset_id is not None
        assert acceptance.stock_lot_id is None
        assert agreement.asset_id == acceptance.asset_id
        asset = acceptance.asset
        assert asset is not None
        assert asset.catalog_code == f"offer-{item.id.hex}"
        assert asset.acquisition == Asset.Acquisition.EQUIPMENT_OFFER
        assert asset.owner_account_id == world.offerer.id
        assert asset.created_by_id == world.operator.id
    else:
        assert acceptance.asset_id is None
        assert acceptance.stock_lot_id is not None
        assert agreement.stock_lot_id == acceptance.stock_lot_id
        lot = acceptance.stock_lot
        assert lot is not None
        assert lot.catalog_code == f"offer-{item.id.hex}"
        assert lot.initial_quantity == item.quantity
        assert lot.owner_account_id == world.offerer.id
        assert lot.created_by_id == world.operator.id


def _forge_mismatched_offline_duplicate(
    *,
    world: _World,
    canonical: OfflineScanOperation,
    expires_at: datetime,
) -> None:
    with transaction.atomic():
        forged_batch = OfflineScanBatch(
            organization=world.edition.organization,
            edition=world.edition,
            device_code="forged-duplicate",
            snapshot_version=2,
            policy_version="integrity-v1",
            expires_at=expires_at,
            operation_count=1,
            payload_digest="f" * 64,
            submitted_by=world.operator,
        )
        OfflineScanBatch.objects.bulk_create([forged_batch])
        OfflineScanOperation.objects.bulk_create(
            [
                OfflineScanOperation(
                    batch=forged_batch,
                    sequence=canonical.sequence,
                    idempotency_key=canonical.idempotency_key,
                    expected_subject_sequence=canonical.expected_subject_sequence,
                    action=canonical.action,
                    label_code=canonical.label_code,
                    source_label_code=canonical.source_label_code,
                    destination_label_code=canonical.destination_label_code,
                    quantity=canonical.quantity,
                    observed_condition="forged-condition",
                    occurred_at=canonical.occurred_at,
                    operation_digest=canonical.operation_digest,
                    result=OfflineScanOperation.Result.DUPLICATE,
                    reason_code="logistics_offline_duplicate",
                    applied_event_id=canonical.applied_event_id,
                    discrepancy_id=canonical.discrepancy_id,
                )
            ]
        )
        OfflineScanBatch.objects.filter(id=forged_batch.id).update(
            status=OfflineScanBatch.Status.APPLIED,
            aggregate_version=2,
            updated_at=timezone.now(),
        )


def test_submit_and_accept_compose_with_canonical_history_inventory_and_agreement() -> (
    None
):
    world = _world()
    now = timezone.now()
    items = (
        OfferItemInput(
            kind=EquipmentOfferItem.Kind.SERIALIZED,
            name="Offered lighting desk",
            condition="working",
            ownership_statement="I own this synthetic test desk.",
            quantity=1,
            manufacturer="Synthetic Works",
            model_name="Desk One",
            serial_number="OFFER-SERIAL-1",
            value_class="standard",
        ),
        OfferItemInput(
            kind=EquipmentOfferItem.Kind.BULK,
            name="Offered cable lot",
            condition="working",
            ownership_statement="I own this synthetic cable lot.",
            quantity=8,
            value_class="standard",
        ),
    )

    with transaction.atomic():
        offer_id, window = _submit_offer(world, items=items, now=now)
        reviewed = review_equipment_offer(
            actor=world.operator,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            offer_id=offer_id,
            expected_version=1,
            outcome=EquipmentOffer.Status.ACCEPTED,
            responsible_department_id=world.department.id,
            reason="Accept the complete synthetic offer.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now + timedelta(seconds=1),
        )

    assert reviewed.resulting_version == 2
    offer = EquipmentOffer.objects.get(id=offer_id)
    histories = list(
        EquipmentOfferHistory.objects.filter(offer=offer)
        .order_by("offer_version")
        .values_list("offer_version", "status", "actor_id")
    )
    assert histories == [
        (1, EquipmentOffer.Status.PENDING, world.offerer.id),
        (2, EquipmentOffer.Status.ACCEPTED, world.operator.id),
    ]
    assert offer.aggregate_version == 2
    assert offer.reviewed_by_id == world.operator.id
    assert offer.responsible_department_id == world.department.id

    offer_items = tuple(offer.items.order_by("created_at", "id"))
    assert len(offer_items) == 2
    acceptances = tuple(
        EquipmentOfferAcceptance.objects.filter(offer_item__offer=offer)
        .select_related("asset", "stock_lot", "offer_item")
        .order_by("offer_item_id")
    )
    assert len(acceptances) == len(offer_items)
    assert {acceptance.offer_item_id for acceptance in acceptances} == {
        item.id for item in offer_items
    }
    for acceptance in acceptances:
        _assert_canonical_acceptance(
            acceptance=acceptance,
            offer=offer,
            world=world,
            window=window,
        )


def test_submit_and_withdraw_compose_with_contiguous_history_only() -> None:
    world = _world()
    now = timezone.now()

    with transaction.atomic():
        offer_id, _window = _submit_offer(
            world,
            items=(
                OfferItemInput(
                    kind=EquipmentOfferItem.Kind.SERIALIZED,
                    name="Withdrawn synthetic item",
                    condition="working",
                    ownership_statement="I own this synthetic item.",
                ),
            ),
            now=now,
        )
        withdrawn = withdraw_equipment_offer(
            actor=world.offerer,
            organization_id=world.edition.organization_id,
            edition_id=world.edition.id,
            offer_id=offer_id,
            expected_version=1,
            reason="Withdraw the synthetic offer in the outer transaction.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
            now=now + timedelta(seconds=1),
        )

    assert withdrawn.resulting_version == 2
    offer = EquipmentOffer.objects.get(id=offer_id)
    assert list(
        EquipmentOfferHistory.objects.filter(offer=offer)
        .order_by("offer_version")
        .values_list("offer_version", "status", "actor_id")
    ) == [
        (1, EquipmentOffer.Status.PENDING, world.offerer.id),
        (2, EquipmentOffer.Status.WITHDRAWN, world.offerer.id),
    ]
    assert not EquipmentOfferAcceptance.objects.filter(offer_item__offer=offer).exists()
    assert not AssetAgreement.objects.filter(
        offer_acceptance__offer_item__offer=offer
    ).exists()


def test_offline_successors_exact_duplicates_and_discrepancy_review_compose() -> None:
    world = _world()
    lot = _stock_lot(world, code="offline-successor-lot")
    destination = _node(world, code="offline-destination")
    lot_label = _label(
        world,
        subject=SubjectLocator(
            kind=LogisticsEvent.SubjectKind.STOCK_LOT, object_id=lot.id
        ),
        code="offline-lot",
    )
    destination_label = _label(
        world,
        subject=SubjectLocator(
            kind=LogisticsEvent.SubjectKind.NODE, object_id=destination.id
        ),
        code="offline-destination",
    )
    received_at = timezone.now()
    expires_at = received_at + timedelta(hours=2)
    operations = (
        OfflineOperationInput(
            sequence=1,
            idempotency_key=uuid4(),
            expected_subject_sequence=0,
            action=LogisticsEvent.EventType.RECEIVE,
            label_code=lot_label.label_code,
            destination_label_code=destination_label.label_code,
            quantity=10,
            observed_condition="working",
            occurred_at=received_at - timedelta(minutes=2),
        ),
        OfflineOperationInput(
            sequence=2,
            idempotency_key=uuid4(),
            expected_subject_sequence=1,
            action=LogisticsEvent.EventType.COUNT,
            label_code=lot_label.label_code,
            quantity=8,
            occurred_at=received_at - timedelta(minutes=1),
        ),
    )

    first = ingest_offline_scan_batch(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        device_code="integrity-scanner-1",
        snapshot_version=0,
        policy_version="integrity-v1",
        expires_at=expires_at,
        operations=operations,
        reason="Apply two sequential offline observations.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=received_at,
    )
    first_batch = OfflineScanBatch.objects.get(id=first.object_id)
    first_operations = tuple(first_batch.operations.order_by("sequence"))
    assert first_batch.status == OfflineScanBatch.Status.REVIEW
    assert [operation.result for operation in first_operations] == [
        OfflineScanOperation.Result.APPLIED,
        OfflineScanOperation.Result.APPLIED,
    ]
    assert [
        operation.applied_event.event_sequence for operation in first_operations
    ] == [
        1,
        2,
    ]
    assert first_operations[0].discrepancy_id is None
    assert first_operations[1].discrepancy_id is not None
    state = LogisticsCurrentState.objects.get(stock_lot=lot)
    assert state.event_sequence == 2
    assert state.current_node_id == destination.id
    assert state.quantity_on_hand == 8
    assert (
        LogisticsEditionControl.objects.get(edition=world.edition).aggregate_version
        == 2
    )

    duplicate = ingest_offline_scan_batch(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        device_code="integrity-scanner-2",
        snapshot_version=2,
        policy_version="integrity-v1",
        expires_at=expires_at,
        operations=operations,
        reason="Replay the exact two offline observations.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=received_at,
    )
    duplicate_batch = OfflineScanBatch.objects.get(id=duplicate.object_id)
    duplicate_operations = tuple(duplicate_batch.operations.order_by("sequence"))
    assert duplicate_batch.status == OfflineScanBatch.Status.REVIEW
    assert [operation.result for operation in duplicate_operations] == [
        OfflineScanOperation.Result.DUPLICATE,
        OfflineScanOperation.Result.DUPLICATE,
    ]
    assert [operation.applied_event_id for operation in duplicate_operations] == [
        operation.applied_event_id for operation in first_operations
    ]
    assert duplicate_operations[1].discrepancy_id == first_operations[1].discrepancy_id
    assert LogisticsEvent.objects.filter(stock_lot=lot).count() == 2

    canonical = first_operations[0]
    with pytest.raises(
        IntegrityError,
        match="duplicate offline operation must reuse exact receipt evidence",
    ):
        _forge_mismatched_offline_duplicate(
            world=world,
            canonical=canonical,
            expires_at=expires_at,
        )


def test_manifest_key_kit_and_control_children_require_matching_parent_counts() -> None:
    world = _world()
    manifest_destination = _node(world, code="manifest-count-destination")
    manifest_assets = tuple(
        _asset(world, code=f"manifest-count-{index}") for index in range(3)
    )
    manifest_result = create_logistics_manifest(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        responsible_department_id=world.department.id,
        manifest_number="COUNT-CORRESPONDENCE",
        kind=LogisticsManifest.Kind.INBOUND,
        title="Manifest count correspondence",
        source_node_id=None,
        destination_node_id=manifest_destination.id,
        vehicle_id=None,
        provider_id=None,
        loading_starts_at=None,
        loading_ends_at=None,
        lines=(
            ManifestLineInput(
                subject=SubjectLocator(
                    kind=LogisticsEvent.SubjectKind.ASSET,
                    object_id=manifest_assets[0].id,
                )
            ),
        ),
        reason="Create the canonical manifest parent and first child.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    _grant_manifest(world, manifest_id=manifest_result.object_id)
    added = add_manifest_line(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        manifest_id=manifest_result.object_id,
        expected_version=1,
        line=ManifestLineInput(
            subject=SubjectLocator(
                kind=LogisticsEvent.SubjectKind.ASSET,
                object_id=manifest_assets[1].id,
            )
        ),
        reason="Append the canonical second manifest child.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    manifest = LogisticsManifest.objects.get(id=manifest_result.object_id)
    assert added.resulting_version == 2
    assert (manifest.aggregate_version, manifest.line_count) == (2, 2)
    with (
        pytest.raises(
            IntegrityError,
            match="manifest line requires its parent count update",
        ),
        transaction.atomic(),
    ):
        LogisticsManifestLine.objects.bulk_create(
            [
                LogisticsManifestLine(
                    manifest=manifest,
                    subject_kind=LogisticsManifestLine.SubjectKind.ASSET,
                    asset=manifest_assets[2],
                    quantity=1,
                    label_snapshot=manifest_assets[2].name,
                )
            ]
        )

    key_node = _node(world, code="key-count-node")
    key_result = register_physical_key(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        code="count-correspondence-key",
        label="Count correspondence key",
        opens_node_id=key_node.id,
        provider_id=None,
        reason="Create canonical key evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    key = PhysicalKey.objects.get(id=key_result.object_id)
    starts_at = timezone.now() + timedelta(hours=1)
    responsibility = assign_keyholder_responsibility(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        key_id=key.id,
        responsible_account_id=world.operator.id,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        expected_version=1,
        reason="Create canonical keyholder evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    key.refresh_from_db()
    assert responsibility.resulting_version == key.aggregate_version == 2
    with (
        pytest.raises(
            IntegrityError,
            match="keyholder evidence requires its parent version update",
        ),
        transaction.atomic(),
    ):
        KeyholderResponsibility.objects.bulk_create(
            [
                KeyholderResponsibility(
                    key=key,
                    responsible_account=world.operator,
                    starts_at=starts_at + timedelta(hours=2),
                    ends_at=starts_at + timedelta(hours=3),
                    assigned_by=world.operator,
                    reason="Forged child without a key version advance.",
                )
            ]
        )

    kit_assets = tuple(
        _asset(world, code=f"kit-count-{index}", allocated=False) for index in range(3)
    )
    kit_result = create_reusable_kit(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        code="count-correspondence-kit",
        name="Count correspondence kit",
        description="Synthetic kit with a closed declared count.",
        lines=tuple(
            KitLineInput(
                subject=SubjectLocator(
                    kind=LogisticsEvent.SubjectKind.ASSET,
                    object_id=asset.id,
                )
            )
            for asset in kit_assets[:2]
        ),
        reason="Create canonical kit child evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    kit = ReusableKit.objects.get(id=kit_result.object_id)
    assert kit.declared_line_count == kit.lines.count() == 2
    with (
        pytest.raises(
            IntegrityError,
            match="reusable kit line requires exact declared count",
        ),
        transaction.atomic(),
    ):
        ReusableKitLine.objects.bulk_create(
            [
                ReusableKitLine(
                    kit=kit,
                    asset=kit_assets[2],
                    quantity=1,
                    notes="Forged child beyond the declared count.",
                )
            ]
        )

    control_asset = _asset(world, code="control-count-asset")
    control_node = _node(world, code="control-count-node")
    _record_event(
        world,
        subject=SubjectLocator(
            kind=LogisticsEvent.SubjectKind.ASSET,
            object_id=control_asset.id,
        ),
        event_type=LogisticsEvent.EventType.RECEIVE,
        expected_sequence=0,
        occurred_at=timezone.now(),
        destination_node_id=control_node.id,
        condition_after="working",
    )
    control = LogisticsEditionControl.objects.get(edition=world.edition)
    assert control.aggregate_version == 1
    with (
        pytest.raises(
            IntegrityError,
            match="edition control version must match Logistics events",
        ),
        transaction.atomic(),
    ):
        LogisticsEditionControl.objects.filter(id=control.id).update(
            aggregate_version=2,
            updated_at=timezone.now(),
        )


def test_manifest_line_event_type_is_one_time_even_after_a_valid_route_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    asset = _asset(world, code="manifest-event-unique")
    source = _node(world, code="manifest-event-source")
    destination = _node(world, code="manifest-event-destination")
    vehicle = _node(
        world,
        code="manifest-event-vehicle",
        kind=LogisticsNode.Kind.VEHICLE,
    )
    subject = SubjectLocator(
        kind=LogisticsEvent.SubjectKind.ASSET,
        object_id=asset.id,
    )
    now = timezone.now()
    _record_event(
        world,
        subject=subject,
        event_type=LogisticsEvent.EventType.RECEIVE,
        expected_sequence=0,
        occurred_at=now,
        destination_node_id=source.id,
        condition_after="working",
    )
    created = create_logistics_manifest(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        responsible_department_id=world.department.id,
        manifest_number="EVENT-TYPE-UNIQUE",
        kind=LogisticsManifest.Kind.OUTBOUND,
        title="One-time manifested traversal",
        source_node_id=source.id,
        destination_node_id=destination.id,
        vehicle_id=vehicle.id,
        provider_id=None,
        loading_starts_at=None,
        loading_ends_at=None,
        lines=(ManifestLineInput(subject=subject),),
        reason="Create a route for one canonical load and unload.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    _grant_manifest(world, manifest_id=created.object_id)
    sealed = change_manifest_state(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        manifest_id=created.object_id,
        expected_version=1,
        action="seal",
        reason="Seal the one-time traversal evidence.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert sealed.resulting_version == 2
    _record_event(
        world,
        subject=subject,
        event_type=LogisticsEvent.EventType.LOAD,
        expected_sequence=1,
        occurred_at=now + timedelta(seconds=1),
        source_node_id=source.id,
        destination_node_id=vehicle.id,
        manifest_id=created.object_id,
    )
    _record_event(
        world,
        subject=subject,
        event_type=LogisticsEvent.EventType.UNLOAD,
        expected_sequence=2,
        occurred_at=now + timedelta(seconds=2),
        source_node_id=vehicle.id,
        destination_node_id=destination.id,
        manifest_id=created.object_id,
    )
    _record_event(
        world,
        subject=subject,
        event_type=LogisticsEvent.EventType.MOVE,
        expected_sequence=3,
        occurred_at=now + timedelta(seconds=3),
        source_node_id=destination.id,
        destination_node_id=source.id,
    )

    with monkeypatch.context() as patch:
        patch.setattr(
            LogisticsEvent,
            "full_clean",
            lambda *_args, **_kwargs: None,
        )
        with (
            pytest.raises(IntegrityError, match="log_manifest_event_line_type_uq"),
            transaction.atomic(),
        ):
            _record_event(
                world,
                subject=subject,
                event_type=LogisticsEvent.EventType.LOAD,
                expected_sequence=4,
                occurred_at=now + timedelta(seconds=4),
                source_node_id=source.id,
                destination_node_id=vehicle.id,
                manifest_id=created.object_id,
            )
    state = LogisticsCurrentState.objects.get(asset=asset)
    assert state.event_sequence == 4
    assert state.current_node_id == source.id


def test_raw_orphan_event_discrepancy_receipt_and_command_reuse_are_rejected() -> None:
    world = _world()
    asset = _asset(world, code="orphan-evidence-asset")
    node = _node(world, code="orphan-evidence-node")
    subject = SubjectLocator(
        kind=LogisticsEvent.SubjectKind.ASSET,
        object_id=asset.id,
    )
    _record_event(
        world,
        subject=subject,
        event_type=LogisticsEvent.EventType.RECEIVE,
        expected_sequence=0,
        occurred_at=timezone.now(),
        destination_node_id=node.id,
        condition_after="working",
    )

    with (
        pytest.raises(
            IntegrityError,
            match="Logistics event requires matching edition control version",
        ),
        transaction.atomic(),
    ):
        LogisticsEvent.objects.bulk_create(
            [
                LogisticsEvent(
                    organization=world.edition.organization,
                    edition=world.edition,
                    subject_kind=LogisticsEvent.SubjectKind.ASSET,
                    asset=asset,
                    event_type=LogisticsEvent.EventType.CONDITION,
                    event_sequence=2,
                    source_node=node,
                    actor=world.operator,
                    occurred_at=timezone.now(),
                    reason="Forged event without control or projection.",
                    condition_before="working",
                    condition_after="inspected",
                    source_channel="test",
                )
            ]
        )

    with (
        pytest.raises(
            IntegrityError,
            match="offline discrepancy requires one canonical operation",
        ),
        transaction.atomic(),
    ):
        LogisticsDiscrepancy.objects.bulk_create(
            [
                LogisticsDiscrepancy(
                    organization=world.edition.organization,
                    edition=world.edition,
                    kind=LogisticsDiscrepancy.Kind.OFFLINE_CONFLICT,
                    subject_kind=LogisticsEvent.SubjectKind.ASSET,
                    subject_id=asset.id,
                    description="Forged discrepancy without an offline operation.",
                )
            ]
        )

    with (
        pytest.raises(
            IntegrityError,
            match="offline receipt requires its canonical operation",
        ),
        transaction.atomic(),
    ):
        OfflineOperationReceipt.objects.bulk_create(
            [
                OfflineOperationReceipt(
                    organization=world.edition.organization,
                    edition=world.edition,
                    idempotency_key=uuid4(),
                    operation_digest="a" * 64,
                    result=OfflineScanOperation.Result.APPLIED,
                    reason_code="logistics_offline_applied",
                )
            ]
        )

    receipt = LogisticsCommandReceipt.objects.get(
        operation="asset.register",
        result_object_id=asset.id,
    )
    with (
        pytest.raises(IntegrityError, match="log_command_idempotency_uq"),
        transaction.atomic(),
    ):
        LogisticsCommandReceipt.objects.bulk_create(
            [
                LogisticsCommandReceipt(
                    organization_id=receipt.organization_id,
                    edition_id=receipt.edition_id,
                    operation=receipt.operation,
                    actor_id=receipt.actor_id,
                    idempotency_key=receipt.idempotency_key,
                    request_digest=receipt.request_digest,
                    resulting_version=receipt.resulting_version,
                    result_object_id=receipt.result_object_id,
                    correlation_id=uuid4(),
                    source_channel="forged",
                )
            ]
        )


def test_reverse_fence_allows_empty_schema_and_refuses_any_durable_evidence() -> None:
    with connection.schema_editor() as schema_editor:
        _integrity_migration.refuse_logistics_integrity_downgrade(
            django_apps,
            schema_editor,
        )

    world = _world()
    _asset(world, code="reverse-fence-evidence")
    with (
        pytest.raises(RuntimeError, match="Cannot remove Logistics database integrity"),
        connection.schema_editor() as schema_editor,
    ):
        _integrity_migration.refuse_logistics_integrity_downgrade(
            django_apps,
            schema_editor,
        )


def test_operational_queries_project_authorized_state_without_contact_leakage() -> None:
    """Compose the read model from canonical offer, manifest, and receipt evidence."""

    world = _world()
    for capability_code in (
        WORKSPACE_VIEW_CAPABILITY,
        RESTRICTED_CONTACT_CAPABILITY,
    ):
        CapabilityGrantFactory(
            organization=world.edition.organization,
            edition=world.edition,
            principal=world.operator,
            capability_code=capability_code,
        )

    now = timezone.now()
    offer_id, _window = _submit_offer(
        world,
        items=(
            OfferItemInput(
                kind=EquipmentOfferItem.Kind.SERIALIZED,
                name="Projection lighting desk",
                condition="working",
                ownership_statement="I own this projection-test desk.",
                quantity=1,
                manufacturer="Synthetic Works",
                model_name="Projection One",
                serial_number="PROJECTION-SERIAL-1",
                value_class="standard",
            ),
        ),
        now=now,
    )
    review_equipment_offer(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        offer_id=offer_id,
        expected_version=1,
        outcome=EquipmentOffer.Status.ACCEPTED,
        responsible_department_id=world.department.id,
        reason="Accept the projection-test equipment.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now + timedelta(seconds=1),
    )
    acceptance = EquipmentOfferAcceptance.objects.select_related("asset").get(
        offer_item__offer_id=offer_id
    )
    asset = acceptance.asset
    assert asset is not None
    destination = _node(world, code="projection-stage-receiving")
    created = create_logistics_manifest(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        responsible_department_id=world.department.id,
        manifest_number="PROJECTION-STAGE-1",
        kind=LogisticsManifest.Kind.STAGE_RECEIVING,
        title="Projection Stage Tech receiving",
        source_node_id=None,
        destination_node_id=destination.id,
        vehicle_id=None,
        provider_id=None,
        loading_starts_at=None,
        loading_ends_at=None,
        lines=(
            ManifestLineInput(
                subject=SubjectLocator(
                    kind=LogisticsEvent.SubjectKind.ASSET,
                    object_id=asset.id,
                )
            ),
        ),
        reason="Create a receiving manifest for projection coverage.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now + timedelta(seconds=2),
    )
    _grant_manifest(world, manifest_id=created.object_id)
    sealed = change_manifest_state(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        manifest_id=created.object_id,
        expected_version=1,
        action="seal",
        reason="Seal the exact receiving manifest.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now + timedelta(seconds=3),
    )
    assert sealed.resulting_version == 2
    line = LogisticsManifestLine.objects.get(manifest_id=created.object_id)
    receipt = record_manifest_receipt(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        manifest_id=created.object_id,
        line_id=line.id,
        expected_sequence=0,
        occurred_at=now + timedelta(seconds=4),
        condition_after="Received as described",
        reason="Receive the exact manifested asset.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=now + timedelta(seconds=4),
    )
    assert receipt.resulting_version == 1

    workspace = list_logistics_workspace(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    assert [offer.id for offer in workspace.offers] == [offer_id]
    assert [manifest.id for manifest in workspace.manifests] == [created.object_id]
    assert any(state.subject_id == asset.id for state in workspace.current_states)
    assert any(item.subject_id == asset.id for item in workspace.due_returns)
    assert any(choice.value == asset.id for choice in workspace.choices.assets)
    assert any(choice.value == destination.id for choice in workspace.choices.nodes)
    assert any(
        choice.value == created.object_id for choice in workspace.choices.manifests
    )

    exact_manifest = manifest_for_workspace(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        manifest_id=created.object_id,
    )
    assert exact_manifest.lines[0].current_sequence == 1
    assert exact_manifest.lines[0].current_state == LogisticsCurrentState.State.STORED
    receiving = stage_tech_receiving_manifests(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    assert [manifest.id for manifest in receiving] == [created.object_id]
    activity = list_logistics_activity(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    assert activity[0].subject_id == asset.id
    assert activity[0].event_type == LogisticsEvent.EventType.RECEIVE

    personal_offers = list_self_offers(
        actor=world.offerer,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    assert personal_offers[0].id == offer_id
    assert personal_offers[0].pickup_postal_address
    assert can_submit_equipment_offer(
        actor=world.offerer,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    personal_editions = my_equipment_offer_editions(actor=world.offerer)
    assert any(edition.offer_count == 1 for edition in personal_editions)

    offer = EquipmentOffer.objects.select_related("pickup_address").get(id=offer_id)
    access_request_id = prepare_restricted_contact_request(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        address_id=offer.pickup_address_id,
        purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
        access_purpose="pickup_coordination",
        correlation_id=uuid4(),
        source_channel="test",
    )
    contact = read_restricted_logistics_contact(
        actor=world.operator,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        address_id=offer.pickup_address_id,
        purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
        access_purpose="pickup_coordination",
        access_request_id=access_request_id,
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert contact.address_id == offer.pickup_address_id
    assert contact.postal_address == personal_offers[0].pickup_postal_address


def test_node_containment_rejects_self_and_indirect_cycles_atomically() -> None:
    world = _world()
    first = _node(world, code="cycle-box-first", kind=LogisticsNode.Kind.BOX)
    second = _node(world, code="cycle-box-second", kind=LogisticsNode.Kind.BOX)
    self_box = _node(world, code="cycle-box-self", kind=LogisticsNode.Kind.BOX)
    occurred_at = timezone.now()

    _record_event(
        world,
        subject=SubjectLocator(
            kind=LogisticsEvent.SubjectKind.NODE,
            object_id=first.id,
        ),
        event_type=LogisticsEvent.EventType.RECEIVE,
        expected_sequence=0,
        occurred_at=occurred_at,
        destination_node_id=second.id,
        condition_after="intact",
    )
    with pytest.raises(LogisticsContainmentCycleError):
        _record_event(
            world,
            subject=SubjectLocator(
                kind=LogisticsEvent.SubjectKind.NODE,
                object_id=second.id,
            ),
            event_type=LogisticsEvent.EventType.RECEIVE,
            expected_sequence=0,
            occurred_at=occurred_at + timedelta(seconds=1),
            destination_node_id=first.id,
            condition_after="intact",
        )
    with pytest.raises(LogisticsContainmentCycleError):
        _record_event(
            world,
            subject=SubjectLocator(
                kind=LogisticsEvent.SubjectKind.NODE,
                object_id=self_box.id,
            ),
            event_type=LogisticsEvent.EventType.RECEIVE,
            expected_sequence=0,
            occurred_at=occurred_at + timedelta(seconds=2),
            destination_node_id=self_box.id,
            condition_after="intact",
        )
    assert LogisticsEvent.objects.filter(node=first).count() == 1
    assert not LogisticsEvent.objects.filter(node__in=(second, self_box)).exists()
    assert not LogisticsCurrentState.objects.filter(
        node__in=(second, self_box)
    ).exists()


def test_offline_conflicts_remain_append_only_review_evidence() -> None:
    world = _world()
    now = timezone.now()
    asset = _asset(world, code="offline-review-asset")
    destination = _node(world, code="offline-review-destination")
    asset_label = _label(
        world,
        subject=SubjectLocator(
            kind=LogisticsEvent.SubjectKind.ASSET,
            object_id=asset.id,
        ),
        code="offline-review-asset",
    )
    destination_label = _label(
        world,
        subject=SubjectLocator(
            kind=LogisticsEvent.SubjectKind.NODE,
            object_id=destination.id,
        ),
        code="offline-review-destination",
    )

    common = {
        "actor": world.operator,
        "organization_id": world.edition.organization_id,
        "edition_id": world.edition.id,
        "device_code": "review-scanner",
        "snapshot_version": 0,
        "policy_version": "review-v1",
        "expires_at": now + timedelta(hours=1),
        "reason": "Retain conflicting scans for bounded review.",
        "idempotency_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
        "now": now,
    }
    with pytest.raises(ValidationError, match="snapshot has expired"):
        ingest_offline_scan_batch(
            **{
                **common,
                "expires_at": now,
                "operations": (),
            }
        )
    with pytest.raises(ValidationError, match="non-negative version"):
        ingest_offline_scan_batch(
            **{
                **common,
                "snapshot_version": True,
                "operations": (),
            }
        )
    with pytest.raises(ValidationError, match="Submit 1 to"):
        ingest_offline_scan_batch(**{**common, "operations": ()})

    operations = (
        OfflineOperationInput(
            sequence=1,
            idempotency_key=uuid4(),
            expected_subject_sequence=0,
            action=LogisticsEvent.EventType.RECEIVE,
            label_code="unknown-offline-label",
            destination_label_code=destination_label.label_code,
            occurred_at=now - timedelta(seconds=2),
            observed_condition="working",
        ),
        OfflineOperationInput(
            sequence=2,
            idempotency_key=uuid4(),
            expected_subject_sequence=1,
            action=LogisticsEvent.EventType.RECEIVE,
            label_code=asset_label.label_code,
            destination_label_code=destination_label.label_code,
            occurred_at=now - timedelta(seconds=1),
            observed_condition="working",
        ),
    )
    result = ingest_offline_scan_batch(**{**common, "operations": operations})
    batch = OfflineScanBatch.objects.get(id=result.object_id)
    reconciled = tuple(batch.operations.order_by("sequence"))
    assert batch.status == OfflineScanBatch.Status.REVIEW
    assert [operation.result for operation in reconciled] == [
        OfflineScanOperation.Result.REVIEW,
        OfflineScanOperation.Result.REVIEW,
    ]
    assert [operation.reason_code for operation in reconciled] == [
        "logistics_offline_label_unavailable",
        "logistics_offline_state_conflict",
    ]
    assert all(operation.discrepancy_id for operation in reconciled)
    assert not LogisticsEvent.objects.filter(asset=asset).exists()
