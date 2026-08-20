"""Adversarial Logistics command, retention, scope, and custody coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.logistics.models import (
    Asset,
    AssetAgreement,
    EquipmentOffer,
    KeyholderResponsibility,
    LogisticsCommandReceipt,
    LogisticsCurrentState,
    LogisticsDiscrepancy,
    LogisticsEvent,
    LogisticsManifest,
    LogisticsNode,
    LogisticsParty,
    PhysicalKey,
    RestrictedLogisticsAddress,
    StockLot,
)
from maru.logistics.retention import dispose_expired_restricted_addresses
from maru.logistics.services import (
    CATALOG_MANAGE_CAPABILITY,
    OPERATIONS_MANAGE_CAPABILITY,
    LogisticsAuthorizationDeniedError,
    LogisticsResourceUnavailableError,
    LogisticsStateConflictError,
    ManifestLineInput,
    MovementInput,
    OfferItemInput,
    PartyProfile,
    SubjectLocator,
    assign_keyholder_responsibility,
    create_logistics_manifest,
    create_logistics_node,
    create_logistics_party,
    create_restricted_logistics_address,
    record_asset_agreement,
    record_logistics_event,
    register_physical_key,
    register_serialized_asset,
    register_stock_lot,
    submit_equipment_offer,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.workforce_helpers import create_department_for_test

if TYPE_CHECKING:
    from maru.identity.models import Account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _Scope:
    edition: EventEdition
    actor: Account


def _scope(*, lifecycle: str = EventEdition.Lifecycle.PREPARING) -> _Scope:
    edition = EventEditionFactory()
    actor = AccountFactory()
    if lifecycle == EventEdition.Lifecycle.PREPARING:
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=actor,
            capability_code="events.transition",
        )
        command_id = uuid4()
        edition = transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=EventEdition.Lifecycle.PREPARING,
            actor=actor,
            reason="Prepare the edition for Logistics integration coverage.",
            correlation_id=command_id,
            request_id=command_id,
            source_channel="test",
        )
    elif lifecycle != EventEdition.Lifecycle.DRAFT:
        raise ValueError("The Logistics integration scope supports Draft or Preparing.")
    return _Scope(edition=edition, actor=actor)


def _grant_catalog(scope: _Scope, *, organization_scope: bool = False) -> None:
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=None if organization_scope else scope.edition,
        principal=scope.actor,
        capability_code=CATALOG_MANAGE_CAPABILITY,
    )


def _register_asset(scope: _Scope, *, code: str = "lighting-desk") -> Asset:
    result = register_serialized_asset(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        catalog_code=code,
        name="Lighting desk",
        asset_type="control-desk",
        manufacturer="Example Manufacturer",
        model_name="LX-1",
        serial_number=f"SERIAL-{code}",
        acquisition=Asset.Acquisition.OWNED,
        value_class="high",
        owner_kind=Asset.OwnerKind.ORGANIZATION,
        owner_account_id=None,
        owner_party_id=None,
        reason="Register the serialized convention asset.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return Asset.objects.get(id=result.object_id)


def _register_node(
    scope: _Scope,
    *,
    code: str = "stage-store",
    edition_specific: bool = True,
) -> LogisticsNode:
    result = create_logistics_node(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        kind=LogisticsNode.Kind.STORAGE_AREA,
        code=code,
        name="Stage storage",
        description="Governed stage equipment storage.",
        edition_id=scope.edition.id if edition_specific else None,
        storage_address_id=None,
        external_owner_id=None,
        provider_id=None,
        vehicle_registration="",
        venue_space_selection_id=None,
        capacity_note="",
        reason="Register a physical storage area.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return LogisticsNode.objects.get(id=result.object_id)


def _register_stock(scope: _Scope, *, code: str = "stage-cables") -> StockLot:
    result = register_stock_lot(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        catalog_code=code,
        name="Stage cables",
        stock_type="cable",
        unit="item",
        initial_quantity=10,
        value_class="",
        owner_kind=StockLot.OwnerKind.ORGANIZATION,
        owner_account_id=None,
        owner_party_id=None,
        reason="Register bounded Stage Tech stock.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return StockLot.objects.get(id=result.object_id)


def _create_provider(scope: _Scope) -> LogisticsParty:
    result = create_logistics_party(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        code="example-provider",
        profile=PartyProfile(
            kind=LogisticsParty.Kind.BUSINESS,
            role=LogisticsParty.Role.PROVIDER,
            legal_name="Example Provider Kft.",
            public_name="Example Provider",
            provider_reference="SUP-1",
            website_url="https://provider.example.test/",
        ),
        reason="Register the external provider identity.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return LogisticsParty.objects.get(id=result.object_id)


def _attempt_forbidden_receipt_truncate() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute("TRUNCATE TABLE public.logistics_logisticscommandreceipt")


def test_catalog_commands_honor_exact_organization_or_edition_authority() -> None:
    scope = _scope()
    _grant_catalog(scope)

    address = create_restricted_logistics_address(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        subject_account_id=None,
        party_id=None,
        purpose=RestrictedLogisticsAddress.Purpose.STORAGE,
        label="Edition storage",
        recipient_name="",
        contact_email="",
        contact_phone="",
        postal_address="Example edition address",
        access_instructions="",
        retention_until=timezone.now() + timedelta(days=30),
        reason="Register edition-scoped storage contact.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    node = _register_node(scope)
    asset = _register_asset(scope)
    starts_at = timezone.now() + timedelta(days=1)
    agreement = record_asset_agreement(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        subject=SubjectLocator(kind="asset", object_id=asset.id),
        kind=AssetAgreement.Kind.LOAN,
        provider_account_id=scope.actor.id,
        provider_party_id=None,
        borrower_account_id=None,
        borrower_party_id=None,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(days=2),
        return_due_at=starts_at + timedelta(days=2),
        return_address_id=None,
        provider_reference="",
        terms_reference="",
        reason="Record the edition loan agreement.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    assert RestrictedLogisticsAddress.objects.filter(id=address.object_id).exists()
    assert node.edition_id == scope.edition.id
    assert AssetAgreement.objects.filter(id=agreement.object_id).exists()

    with pytest.raises(LogisticsAuthorizationDeniedError):
        create_restricted_logistics_address(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=None,
            subject_account_id=None,
            party_id=None,
            purpose=RestrictedLogisticsAddress.Purpose.STORAGE,
            label="Global storage",
            recipient_name="",
            contact_email="",
            contact_phone="",
            postal_address="Global address",
            access_instructions="",
            retention_until=timezone.now() + timedelta(days=30),
            reason="This actor lacks organization-global authority.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    global_scope = _scope()
    _grant_catalog(global_scope, organization_scope=True)
    global_asset = register_serialized_asset(
        actor=global_scope.actor,
        organization_id=global_scope.edition.organization_id,
        edition_id=None,
        catalog_code="global-projector",
        name="Reusable projector",
        asset_type="projector",
        manufacturer="",
        model_name="",
        serial_number="GLOBAL-PROJECTOR-1",
        acquisition=Asset.Acquisition.OWNED,
        value_class="",
        owner_kind=Asset.OwnerKind.ORGANIZATION,
        owner_account_id=None,
        owner_party_id=None,
        reason="Register reusable organization equipment.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert Asset.objects.get(id=global_asset.object_id).edition_allocation_id is None


def _submit_offer(
    *,
    scope: _Scope,
    retention_until,
    requested_return_at,
):
    available_from = timezone.now() + timedelta(days=1)
    available_until = available_from + timedelta(days=2)
    return submit_equipment_offer(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        title="Stage cables",
        description="Cables offered for the convention.",
        pickup_label="Workshop",
        pickup_recipient_name="Offer owner",
        pickup_postal_address="Example pickup address",
        pickup_access_instructions="Call on arrival.",
        pickup_retention_until=retention_until,
        available_from=available_from,
        available_until=available_until,
        requested_return_at=requested_return_at,
        items=(
            OfferItemInput(
                kind="bulk",
                name="XLR cables",
                condition="working",
                ownership_statement="I own these cables.",
                quantity=8,
            ),
        ),
        reason="Offer equipment to Logistics.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_offer_lifecycle_and_return_contact_horizon_are_closed() -> None:
    draft = _scope(lifecycle=EventEdition.Lifecycle.DRAFT)
    return_at = timezone.now() + timedelta(days=10)
    with pytest.raises(LogisticsResourceUnavailableError):
        _submit_offer(
            scope=draft,
            retention_until=return_at,
            requested_return_at=return_at,
        )

    scope = _scope()
    result = _submit_offer(
        scope=scope,
        retention_until=return_at,
        requested_return_at=return_at,
    )
    assert (
        EquipmentOffer.objects.get(id=result.object_id).offered_by_id == scope.actor.id
    )

    with pytest.raises(ValidationError):
        _submit_offer(
            scope=scope,
            retention_until=return_at - timedelta(seconds=1),
            requested_return_at=return_at,
        )


def test_platform_administrator_is_not_a_logistics_convention_subject() -> None:
    scope = _scope()
    platform = AccountFactory(is_staff=True, is_superuser=True)
    scope = _Scope(edition=scope.edition, actor=platform)
    return_at = timezone.now() + timedelta(days=10)

    with pytest.raises(LogisticsAuthorizationDeniedError):
        _submit_offer(
            scope=scope,
            retention_until=return_at,
            requested_return_at=return_at,
        )


def test_expired_restricted_contact_disposal_redacts_and_is_idempotent() -> None:
    scope = _scope()
    evaluated_at = timezone.now()
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=None,
        principal=scope.actor,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        effective_from=evaluated_at - timedelta(days=3),
    )
    provider = _create_provider(scope)
    created = create_restricted_logistics_address(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=None,
        subject_account_id=None,
        party_id=provider.id,
        purpose=RestrictedLogisticsAddress.Purpose.PROVIDER,
        label="Provider return desk",
        recipient_name="Private recipient",
        contact_email="private@example.test",
        contact_phone="+3612345678",
        postal_address="Private provider address",
        access_instructions="Private access instructions",
        retention_until=evaluated_at - timedelta(days=1),
        reason="Store provider contact for one bounded operation.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        now=evaluated_at - timedelta(days=2),
    )
    address = RestrictedLogisticsAddress.objects.get(id=created.object_id)
    correlation_id = uuid4()

    disposed = dispose_expired_restricted_addresses(
        organization_id=scope.edition.organization_id,
        edition_id=None,
        correlation_id=correlation_id,
        now=evaluated_at,
    )

    assert disposed == (address.id,)
    address.refresh_from_db()
    assert address.lifecycle == RestrictedLogisticsAddress.Lifecycle.DISPOSED
    assert address.aggregate_version == 2
    assert address.party_id is None
    assert address.recipient_name == ""
    assert address.contact_email == ""
    assert address.contact_phone == ""
    assert address.postal_address == ""
    assert address.access_instructions == ""
    audit = AuditEvent.objects.get(
        correlation_id=correlation_id,
        operation="logistics.restricted_address.dispose",
    )
    assert audit.safe_metadata == {
        "policy_version": audit.safe_metadata["policy_version"],
        "target_count": 1,
    }
    event = DomainEvent.objects.get(causation_id=audit.id)
    assert event.payload == {
        "action": "disposed",
        "record_type": "logistics.restricted_address",
        "record_id": str(address.id),
    }
    assert OutboxMessage.objects.filter(event=event).exists()

    assert (
        dispose_expired_restricted_addresses(
            organization_id=scope.edition.organization_id,
            edition_id=None,
            correlation_id=uuid4(),
            now=evaluated_at,
        )
        == ()
    )


def test_disposal_waits_for_live_return_horizon() -> None:
    scope = _scope()
    _grant_catalog(scope)
    asset = _register_asset(scope, code="loaned-projector")
    return_due = timezone.now() + timedelta(days=5)
    created = create_restricted_logistics_address(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        subject_account_id=None,
        party_id=None,
        purpose=RestrictedLogisticsAddress.Purpose.RETURN,
        label="Return desk",
        recipient_name="",
        contact_email="",
        contact_phone="",
        postal_address="Example return address",
        access_instructions="",
        retention_until=return_due,
        reason="Retain return coordination through the agreement.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    starts_at = timezone.now() + timedelta(hours=1)
    record_asset_agreement(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        subject=SubjectLocator(kind="asset", object_id=asset.id),
        kind=AssetAgreement.Kind.LOAN,
        provider_account_id=scope.actor.id,
        provider_party_id=None,
        borrower_account_id=None,
        borrower_party_id=None,
        starts_at=starts_at,
        ends_at=return_due,
        return_due_at=return_due,
        return_address_id=created.object_id,
        provider_reference="",
        terms_reference="",
        reason="Record the return obligation.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    evaluated_at = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        RestrictedLogisticsAddress.objects.filter(id=created.object_id).update(
            retention_until=evaluated_at - timedelta(seconds=1)
        )

    assert (
        dispose_expired_restricted_addresses(
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            correlation_id=uuid4(),
            now=evaluated_at,
        )
        == ()
    )
    assert (
        RestrictedLogisticsAddress.objects.get(id=created.object_id).lifecycle
        == RestrictedLogisticsAddress.Lifecycle.ACTIVE
    )


def test_keyholder_and_agreement_intervals_reject_overlap_but_allow_adjacency() -> None:
    scope = _scope()
    _grant_catalog(scope, organization_scope=True)
    node = _register_node(scope, code="key-cabinet")
    key_result = register_physical_key(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        code="main-stage-key",
        label="Main Stage key",
        opens_node_id=node.id,
        provider_id=None,
        reason="Register one physical key copy.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    key = PhysicalKey.objects.get(id=key_result.object_id)
    starts_at = timezone.now() + timedelta(hours=1)
    ends_at = starts_at + timedelta(hours=2)
    first = assign_keyholder_responsibility(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        key_id=key.id,
        responsible_account_id=scope.actor.id,
        starts_at=starts_at,
        ends_at=ends_at,
        expected_version=1,
        reason="Assign the tracked key for setup.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(LogisticsStateConflictError):
        assign_keyholder_responsibility(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            key_id=key.id,
            responsible_account_id=scope.actor.id,
            starts_at=starts_at + timedelta(minutes=30),
            ends_at=ends_at + timedelta(minutes=30),
            expected_version=first.resulting_version,
            reason="Overlapping responsibility is invalid.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    adjacent = assign_keyholder_responsibility(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        key_id=key.id,
        responsible_account_id=scope.actor.id,
        starts_at=ends_at,
        ends_at=ends_at + timedelta(hours=2),
        expected_version=first.resulting_version,
        reason="Hand the key over at the interval boundary.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert adjacent.resulting_version == 3
    assert KeyholderResponsibility.objects.filter(key=key).count() == 2

    asset = _register_asset(scope, code="agreement-asset")
    first_agreement = record_asset_agreement(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        subject=SubjectLocator(kind="asset", object_id=asset.id),
        kind=AssetAgreement.Kind.RENTAL,
        provider_account_id=scope.actor.id,
        provider_party_id=None,
        borrower_account_id=None,
        borrower_party_id=None,
        starts_at=starts_at,
        ends_at=ends_at,
        return_due_at=ends_at,
        return_address_id=None,
        provider_reference="RENT-1",
        terms_reference="",
        reason="Record the first rental interval.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(LogisticsStateConflictError):
        record_asset_agreement(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            subject=SubjectLocator(kind="asset", object_id=asset.id),
            kind=AssetAgreement.Kind.RENTAL,
            provider_account_id=scope.actor.id,
            provider_party_id=None,
            borrower_account_id=None,
            borrower_party_id=None,
            starts_at=starts_at + timedelta(minutes=1),
            ends_at=ends_at + timedelta(hours=1),
            return_due_at=ends_at + timedelta(hours=1),
            return_address_id=None,
            provider_reference="RENT-OVERLAP",
            terms_reference="",
            reason="Overlapping agreement is invalid.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    adjacent_agreement = record_asset_agreement(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        subject=SubjectLocator(kind="asset", object_id=asset.id),
        kind=AssetAgreement.Kind.RENTAL,
        provider_account_id=scope.actor.id,
        provider_party_id=None,
        borrower_account_id=None,
        borrower_party_id=None,
        starts_at=ends_at,
        ends_at=ends_at + timedelta(hours=2),
        return_due_at=ends_at + timedelta(hours=2),
        return_address_id=None,
        provider_reference="RENT-2",
        terms_reference="",
        reason="Adjacent agreement is valid.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert first_agreement.object_id != adjacent_agreement.object_id


def test_foreign_active_people_cannot_become_logistics_subjects() -> None:
    scope = _scope()
    _grant_catalog(scope, organization_scope=True)
    foreign = AccountFactory()

    with pytest.raises(LogisticsResourceUnavailableError):
        create_restricted_logistics_address(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            subject_account_id=foreign.id,
            party_id=None,
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
            label="Foreign pickup",
            recipient_name="",
            contact_email="",
            contact_phone="",
            postal_address="Foreign address",
            access_instructions="",
            retention_until=timezone.now() + timedelta(days=5),
            reason="A foreign active identity is not a convention subject.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    with pytest.raises(LogisticsResourceUnavailableError):
        register_serialized_asset(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            catalog_code="foreign-owned",
            name="Foreign-owned asset",
            asset_type="equipment",
            manufacturer="",
            model_name="",
            serial_number="FOREIGN-OWNER-1",
            acquisition=Asset.Acquisition.LOAN,
            value_class="",
            owner_kind=Asset.OwnerKind.ACCOUNT,
            owner_account_id=foreign.id,
            owner_party_id=None,
            reason="Foreign owner must be rejected.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    node = _register_node(scope, code="foreign-key-cabinet")
    key_result = register_physical_key(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        code="foreign-keyholder-key",
        label="Foreign keyholder test key",
        opens_node_id=node.id,
        provider_id=None,
        reason="Register a test key.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(LogisticsResourceUnavailableError):
        assign_keyholder_responsibility(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            key_id=key_result.object_id,
            responsible_account_id=foreign.id,
            starts_at=timezone.now() + timedelta(hours=1),
            ends_at=timezone.now() + timedelta(hours=2),
            expected_version=1,
            reason="Foreign keyholder must be rejected.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    asset = _register_asset(scope, code="foreign-agreement-asset")
    with pytest.raises(LogisticsResourceUnavailableError):
        record_asset_agreement(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            subject=SubjectLocator(kind="asset", object_id=asset.id),
            kind=AssetAgreement.Kind.LOAN,
            provider_account_id=foreign.id,
            provider_party_id=None,
            borrower_account_id=None,
            borrower_party_id=None,
            starts_at=timezone.now() + timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=1),
            return_due_at=timezone.now() + timedelta(days=1),
            return_address_id=None,
            provider_reference="",
            terms_reference="",
            reason="Foreign provider must be rejected.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_movement_and_manifest_commands_reject_foreign_edition_subjects() -> None:
    scope = _scope()
    _grant_catalog(scope)
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        principal=scope.actor,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
    )
    department = create_department_for_test(
        edition=scope.edition,
        name="Logistics",
        expected_code="logistics",
    )
    local_asset = _register_asset(scope, code="local-console")
    local_node = _register_node(scope, code="local-stage-store")

    foreign_edition = EventEditionFactory(series=scope.edition.series)
    foreign_scope = _Scope(edition=foreign_edition, actor=scope.actor)
    _grant_catalog(foreign_scope)
    foreign_asset = _register_asset(foreign_scope, code="foreign-console")
    foreign_node = _register_node(foreign_scope, code="foreign-stage-store")

    with pytest.raises(LogisticsResourceUnavailableError):
        record_logistics_event(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            movement=MovementInput(
                event_type=LogisticsEvent.EventType.RECEIVE,
                subject=SubjectLocator(kind="asset", object_id=foreign_asset.id),
                occurred_at=timezone.now(),
                destination_node_id=local_node.id,
            ),
            expected_sequence=0,
            reason="A foreign-edition asset is unavailable.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    with pytest.raises(LogisticsResourceUnavailableError):
        record_logistics_event(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            movement=MovementInput(
                event_type=LogisticsEvent.EventType.RECEIVE,
                subject=SubjectLocator(kind="asset", object_id=local_asset.id),
                occurred_at=timezone.now(),
                destination_node_id=foreign_node.id,
            ),
            expected_sequence=0,
            reason="A foreign-edition destination is unavailable.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    with pytest.raises(LogisticsResourceUnavailableError):
        create_logistics_manifest(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            responsible_department_id=department.id,
            manifest_number="IN-FOREIGN-SUBJECT",
            kind=LogisticsManifest.Kind.INBOUND,
            title="Foreign subject manifest",
            source_node_id=None,
            destination_node_id=local_node.id,
            vehicle_id=None,
            provider_id=None,
            loading_starts_at=None,
            loading_ends_at=None,
            lines=(
                ManifestLineInput(
                    subject=SubjectLocator(
                        kind="asset",
                        object_id=foreign_asset.id,
                    ),
                ),
            ),
            reason="Foreign subject must remain unavailable.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    with pytest.raises(LogisticsResourceUnavailableError):
        create_logistics_manifest(
            actor=scope.actor,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            responsible_department_id=department.id,
            manifest_number="IN-FOREIGN-NODE",
            kind=LogisticsManifest.Kind.INBOUND,
            title="Foreign route manifest",
            source_node_id=None,
            destination_node_id=foreign_node.id,
            vehicle_id=None,
            provider_id=None,
            loading_starts_at=None,
            loading_ends_at=None,
            lines=(
                ManifestLineInput(
                    subject=SubjectLocator(kind="asset", object_id=local_asset.id),
                ),
            ),
            reason="Foreign route node must remain unavailable.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )


def test_handover_and_return_require_a_physical_destination_or_recipient() -> None:
    scope = _scope()
    _grant_catalog(scope)
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        principal=scope.actor,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
    )
    asset = _register_asset(scope, code="handover-console")
    node = _register_node(scope, code="handover-store")
    received = record_logistics_event(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        movement=MovementInput(
            event_type=LogisticsEvent.EventType.RECEIVE,
            subject=SubjectLocator(kind="asset", object_id=asset.id),
            occurred_at=timezone.now(),
            destination_node_id=node.id,
            condition_after="working",
        ),
        expected_sequence=0,
        reason="Receive the tracked asset.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert received.resulting_version == 1

    for event_type in (
        LogisticsEvent.EventType.HANDOVER,
        LogisticsEvent.EventType.RETURN,
    ):
        with pytest.raises(ValidationError):
            record_logistics_event(
                actor=scope.actor,
                organization_id=scope.edition.organization_id,
                edition_id=scope.edition.id,
                movement=MovementInput(
                    event_type=event_type,
                    subject=SubjectLocator(kind="asset", object_id=asset.id),
                    occurred_at=timezone.now(),
                    source_node_id=node.id,
                ),
                expected_sequence=1,
                reason="A tracked handoff cannot point nowhere.",
                idempotency_key=uuid4(),
                correlation_id=uuid4(),
                source_channel="test",
            )


def test_database_guards_protect_event_state_receipt_and_truncation() -> None:
    scope = _scope()
    _grant_catalog(scope)
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        principal=scope.actor,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
    )
    asset = _register_asset(scope, code="tamper-guard-asset")
    node = _register_node(scope, code="tamper-guard-node")
    key_result = register_physical_key(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        code="tamper-guard-key",
        label="Tamper guard key",
        opens_node_id=node.id,
        provider_id=None,
        reason="Register a versioned subject for database guard coverage.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    received = record_logistics_event(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        movement=MovementInput(
            event_type=LogisticsEvent.EventType.RECEIVE,
            subject=SubjectLocator(kind="asset", object_id=asset.id),
            occurred_at=timezone.now(),
            destination_node_id=node.id,
            condition_after="working",
        ),
        expected_sequence=0,
        reason="Create canonical custody evidence for tamper coverage.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    event = LogisticsEvent.objects.get(id=received.object_id)
    state = LogisticsCurrentState.objects.get(asset=asset)
    receipt = LogisticsCommandReceipt.objects.get(result_object_id=event.id)

    with pytest.raises(IntegrityError), transaction.atomic():
        LogisticsEvent.objects.filter(id=event.id).update(reason="tampered")
    with pytest.raises(IntegrityError), transaction.atomic():
        LogisticsEvent.objects.filter(id=event.id).delete()
    with pytest.raises(IntegrityError), transaction.atomic():
        LogisticsCurrentState.objects.filter(id=state.id).update(condition="tampered")
    with pytest.raises(IntegrityError), transaction.atomic():
        LogisticsCurrentState.objects.filter(id=state.id).update(
            state=LogisticsCurrentState.State.LOST
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        LogisticsCommandReceipt.objects.filter(id=receipt.id).delete()
    with pytest.raises(IntegrityError), transaction.atomic():
        PhysicalKey.objects.filter(id=key_result.object_id).update(aggregate_version=99)
    with pytest.raises(IntegrityError):
        _attempt_forbidden_receipt_truncate()


def test_count_event_updates_projection_and_requires_discrepancy_evidence() -> None:
    scope = _scope()
    _grant_catalog(scope)
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        principal=scope.actor,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
    )
    lot = _register_stock(scope)
    node = _register_node(scope, code="count-stock-node")
    record_logistics_event(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        movement=MovementInput(
            event_type=LogisticsEvent.EventType.RECEIVE,
            subject=SubjectLocator(kind="stock_lot", object_id=lot.id),
            occurred_at=timezone.now(),
            destination_node_id=node.id,
            quantity=10,
            condition_after="working",
        ),
        expected_sequence=0,
        reason="Receive the complete stock lot.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    counted = record_logistics_event(
        actor=scope.actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        movement=MovementInput(
            event_type=LogisticsEvent.EventType.COUNT,
            subject=SubjectLocator(kind="stock_lot", object_id=lot.id),
            occurred_at=timezone.now(),
            quantity=8,
        ),
        expected_sequence=1,
        reason="Record the observed count discrepancy.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )

    state = LogisticsCurrentState.objects.get(stock_lot=lot)
    discrepancy = LogisticsDiscrepancy.objects.get(
        detected_event_id=counted.object_id,
        kind=LogisticsDiscrepancy.Kind.COUNT,
    )
    assert state.event_sequence == 2
    assert state.quantity_on_hand == 8
    assert discrepancy.expected_quantity == 10
    assert discrepancy.observed_quantity == 8
