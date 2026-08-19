"""In-memory Logistics model shape and tenant-scope validation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.logistics.models import (
    Asset,
    AssetAgreement,
    EquipmentOffer,
    LogisticsCommandReceipt,
    LogisticsCurrentState,
    LogisticsEditionControl,
    LogisticsEvent,
    LogisticsLabel,
    LogisticsManifest,
    LogisticsManifestLine,
    LogisticsNode,
    LogisticsParty,
    PhysicalKey,
    RestrictedLogisticsAddress,
    ReusableKitLine,
    StockLot,
)


def _related(**values):
    return SimpleNamespace(id=values.pop("id", uuid4()), **values)


def _cache(instance, field: str, value) -> None:
    instance._state.fields_cache[field] = value


def _assert_invalid(instance, code: str) -> None:
    with pytest.raises(ValidationError) as raised:
        instance.clean()
    assert raised.value.code == code


def test_closed_records_cannot_delete_and_append_only_evidence_cannot_update() -> None:
    with pytest.raises(ValidationError, match="retained"):
        LogisticsParty().delete()

    receipt = LogisticsCommandReceipt()
    receipt._state.adding = False
    with pytest.raises(ValidationError, match="append-only"):
        receipt.save()

    party = LogisticsParty(public_name="External provider")
    assert str(party) == "External provider"


def test_restricted_address_offer_and_node_scopes_fail_closed() -> None:
    organization_id = uuid4()
    foreign_id = uuid4()

    _assert_invalid(
        RestrictedLogisticsAddress(
            organization_id=organization_id,
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
            lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
            postal_address="",
        ),
        "logistics_address_value_required",
    )
    address = RestrictedLogisticsAddress(
        organization_id=organization_id,
        edition_id=uuid4(),
        purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
        lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
        postal_address="Example address",
    )
    _cache(address, "edition", _related(organization_id=foreign_id))
    _assert_invalid(address, "logistics_address_scope_mismatch")

    address = RestrictedLogisticsAddress(
        organization_id=organization_id,
        party_id=uuid4(),
        purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
        lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
        postal_address="Example address",
    )
    _cache(address, "party", _related(organization_id=foreign_id))
    _assert_invalid(address, "logistics_address_scope_mismatch")

    address = RestrictedLogisticsAddress(
        organization_id=organization_id,
        party_id=uuid4(),
        subject_account_id=uuid4(),
        purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
        lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
        postal_address="Example address",
    )
    _cache(address, "party", _related(organization_id=organization_id))
    _assert_invalid(address, "logistics_address_subject_mismatch")

    offer = EquipmentOffer(
        organization_id=organization_id,
        edition_id=uuid4(),
    )
    _cache(offer, "edition", _related(organization_id=foreign_id))
    _assert_invalid(offer, "logistics_offer_scope_mismatch")

    offer = EquipmentOffer(
        organization_id=organization_id,
        edition_id=uuid4(),
        pickup_address_id=uuid4(),
        offered_by_id=uuid4(),
    )
    _cache(offer, "edition", _related(organization_id=organization_id))
    _cache(
        offer,
        "pickup_address",
        _related(
            organization_id=foreign_id,
            edition_id=offer.edition_id,
            subject_account_id=offer.offered_by_id,
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
        ),
    )
    _assert_invalid(offer, "logistics_offer_address_mismatch")

    offer = EquipmentOffer(
        organization_id=organization_id,
        edition_id=uuid4(),
        responsible_department_id=uuid4(),
    )
    _cache(offer, "edition", _related(organization_id=organization_id))
    _cache(
        offer,
        "responsible_department",
        _related(organization_id=organization_id, edition_id=uuid4()),
    )
    _assert_invalid(offer, "logistics_offer_department_mismatch")

    node = LogisticsNode(organization_id=organization_id, edition_id=uuid4())
    _cache(node, "edition", _related(organization_id=foreign_id))
    _assert_invalid(node, "logistics_node_scope_mismatch")

    node = LogisticsNode(
        organization_id=organization_id,
        storage_address_id=uuid4(),
    )
    _cache(
        node,
        "storage_address",
        _related(
            organization_id=organization_id,
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
            edition_id=None,
        ),
    )
    _assert_invalid(node, "logistics_node_address_mismatch")

    node = LogisticsNode(organization_id=organization_id, provider_id=uuid4())
    _cache(node, "provider", _related(organization_id=foreign_id))
    _assert_invalid(node, "logistics_node_party_mismatch")

    node = LogisticsNode(
        organization_id=organization_id,
        edition_id=uuid4(),
        venue_space_selection_id=uuid4(),
    )
    _cache(node, "edition", _related(organization_id=organization_id))
    selection = MagicMock()
    selection.exists.return_value = False
    with patch(
        "maru.venues.models.EditionSpaceSelection.objects.filter",
        return_value=selection,
    ):
        _assert_invalid(node, "logistics_node_venue_scope_mismatch")


def test_owned_inventory_and_key_relations_are_tenant_bound() -> None:
    organization_id = uuid4()
    foreign_id = uuid4()

    _assert_invalid(
        Asset(
            organization_id=organization_id,
            owner_kind=Asset.OwnerKind.ORGANIZATION,
            owner_account_id=uuid4(),
        ),
        "logistics_owner_shape_mismatch",
    )

    asset = Asset(
        organization_id=organization_id,
        owner_kind=Asset.OwnerKind.EXTERNAL_PARTY,
        owner_party_id=uuid4(),
    )
    _cache(asset, "owner_party", _related(organization_id=foreign_id))
    _assert_invalid(asset, "logistics_owner_scope_mismatch")

    asset = Asset(
        organization_id=organization_id,
        owner_kind=Asset.OwnerKind.ORGANIZATION,
        edition_allocation_id=uuid4(),
    )
    _cache(asset, "edition_allocation", _related(organization_id=foreign_id))
    _assert_invalid(asset, "logistics_asset_scope_mismatch")

    lot = StockLot(
        organization_id=organization_id,
        owner_kind=StockLot.OwnerKind.ORGANIZATION,
        edition_allocation_id=uuid4(),
    )
    _cache(lot, "edition_allocation", _related(organization_id=foreign_id))
    _assert_invalid(lot, "logistics_lot_scope_mismatch")

    key = PhysicalKey(
        organization_id=organization_id,
        opens_node_id=uuid4(),
    )
    _cache(key, "opens_node", _related(organization_id=foreign_id))
    _assert_invalid(key, "logistics_key_scope_mismatch")

    key = PhysicalKey(
        organization_id=organization_id,
        opens_node_id=uuid4(),
        provider_id=uuid4(),
    )
    _cache(key, "opens_node", _related(organization_id=organization_id))
    _cache(key, "provider", _related(organization_id=foreign_id))
    _assert_invalid(key, "logistics_key_scope_mismatch")


def _agreement(**overrides) -> AssetAgreement:
    values = {
        "organization_id": uuid4(),
        "asset_id": uuid4(),
        "provider_account_id": uuid4(),
    }
    values.update(overrides)
    return AssetAgreement(**values)


def test_agreement_and_kit_line_shapes_are_explicit() -> None:
    organization_id = uuid4()
    _assert_invalid(
        _agreement(asset_id=None),
        "logistics_agreement_subject_mismatch",
    )
    _assert_invalid(
        _agreement(provider_id=uuid4()),
        "logistics_agreement_provider_mismatch",
    )
    _assert_invalid(
        _agreement(provider_account_id=None),
        "logistics_agreement_provider_mismatch",
    )
    _assert_invalid(
        _agreement(borrower_account_id=uuid4(), borrower_party_id=uuid4()),
        "logistics_agreement_borrower_mismatch",
    )

    agreement = _agreement(
        organization_id=organization_id,
        provider_account_id=None,
        provider_id=uuid4(),
    )
    _cache(agreement, "provider", _related(organization_id=uuid4()))
    _assert_invalid(agreement, "logistics_agreement_scope_mismatch")

    agreement = _agreement(
        organization_id=organization_id,
        borrower_party_id=uuid4(),
    )
    _cache(agreement, "borrower_party", _related(organization_id=uuid4()))
    _assert_invalid(agreement, "logistics_agreement_scope_mismatch")

    agreement = _agreement(
        organization_id=organization_id,
        return_address_id=uuid4(),
    )
    _cache(
        agreement,
        "return_address",
        _related(
            organization_id=organization_id,
            purpose=RestrictedLogisticsAddress.Purpose.PICKUP,
        ),
    )
    _assert_invalid(agreement, "logistics_agreement_address_mismatch")

    _assert_invalid(
        ReusableKitLine(asset_id=None, stock_lot_id=None, physical_key_id=None),
        "logistics_kit_line_subject_mismatch",
    )
    _assert_invalid(
        ReusableKitLine(asset_id=uuid4(), quantity=2),
        "logistics_kit_line_quantity_mismatch",
    )


def test_manifest_and_line_shapes_bind_route_and_typed_subjects() -> None:
    organization_id = uuid4()
    edition_id = uuid4()

    manifest = LogisticsManifest(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    _cache(manifest, "edition", _related(organization_id=uuid4()))
    _assert_invalid(manifest, "logistics_manifest_scope_mismatch")

    manifest = LogisticsManifest(
        organization_id=organization_id,
        edition_id=edition_id,
        responsible_department_id=uuid4(),
    )
    _cache(manifest, "edition", _related(organization_id=organization_id))
    _cache(
        manifest,
        "responsible_department",
        _related(organization_id=organization_id, edition_id=uuid4()),
    )
    _assert_invalid(manifest, "logistics_manifest_scope_mismatch")

    manifest = LogisticsManifest(
        organization_id=organization_id,
        edition_id=edition_id,
        source_node_id=uuid4(),
    )
    _cache(manifest, "edition", _related(organization_id=organization_id))
    _cache(manifest, "source_node", _related(organization_id=uuid4()))
    _assert_invalid(manifest, "logistics_manifest_scope_mismatch")

    manifest = LogisticsManifest(
        organization_id=organization_id,
        edition_id=edition_id,
        vehicle_id=uuid4(),
    )
    _cache(manifest, "edition", _related(organization_id=organization_id))
    _cache(
        manifest,
        "vehicle",
        _related(organization_id=organization_id, kind=LogisticsNode.Kind.BOX),
    )
    _assert_invalid(manifest, "logistics_manifest_vehicle_mismatch")

    manifest = LogisticsManifest(
        organization_id=organization_id,
        edition_id=edition_id,
        provider_id=uuid4(),
    )
    _cache(manifest, "edition", _related(organization_id=organization_id))
    _cache(manifest, "provider", _related(organization_id=uuid4()))
    _assert_invalid(manifest, "logistics_manifest_scope_mismatch")

    _assert_invalid(
        LogisticsManifestLine(
            subject_kind=LogisticsManifestLine.SubjectKind.ASSET,
        ),
        "logistics_manifest_line_subject_mismatch",
    )
    _assert_invalid(
        LogisticsManifestLine(
            subject_kind=LogisticsManifestLine.SubjectKind.NODE,
            asset_id=uuid4(),
        ),
        "logistics_manifest_line_subject_mismatch",
    )
    _assert_invalid(
        LogisticsManifestLine(
            subject_kind=LogisticsManifestLine.SubjectKind.ASSET,
            asset_id=uuid4(),
            quantity=2,
        ),
        "logistics_manifest_line_quantity_mismatch",
    )
    line = LogisticsManifestLine(
        subject_kind=LogisticsManifestLine.SubjectKind.ASSET,
        asset_id=uuid4(),
        quantity=1,
        packed_in_node_id=uuid4(),
    )
    _cache(line, "packed_in_node", _related(kind=LogisticsNode.Kind.STORAGE_SITE))
    _assert_invalid(line, "logistics_manifest_pack_target_mismatch")


def test_label_event_and_current_state_shapes_match_their_typed_subject() -> None:
    _assert_invalid(LogisticsLabel(), "logistics_label_subject_mismatch")

    _assert_invalid(
        LogisticsEvent(subject_kind=LogisticsEvent.SubjectKind.ASSET),
        "logistics_event_subject_mismatch",
    )
    _assert_invalid(
        LogisticsEvent(
            subject_kind=LogisticsEvent.SubjectKind.NODE,
            asset_id=uuid4(),
        ),
        "logistics_event_subject_mismatch",
    )
    _assert_invalid(
        LogisticsEvent(
            subject_kind=LogisticsEvent.SubjectKind.ASSET,
            asset_id=uuid4(),
            from_custodian_account_id=uuid4(),
            from_custodian_party_id=uuid4(),
        ),
        "logistics_event_custody_mismatch",
    )
    _assert_invalid(
        LogisticsEvent(
            subject_kind=LogisticsEvent.SubjectKind.ASSET,
            asset_id=uuid4(),
            to_custodian_account_id=uuid4(),
            to_custodian_party_id=uuid4(),
        ),
        "logistics_event_custody_mismatch",
    )
    _assert_invalid(
        LogisticsEvent(
            subject_kind=LogisticsEvent.SubjectKind.STOCK_LOT,
            stock_lot_id=uuid4(),
            quantity=None,
        ),
        "logistics_event_quantity_required",
    )
    _assert_invalid(
        LogisticsEvent(
            subject_kind=LogisticsEvent.SubjectKind.ASSET,
            asset_id=uuid4(),
            quantity=2,
        ),
        "logistics_event_quantity_mismatch",
    )

    _assert_invalid(LogisticsCurrentState(), "logistics_state_subject_mismatch")
    _assert_invalid(
        LogisticsCurrentState(
            asset_id=uuid4(),
            custodian_account_id=uuid4(),
            custodian_party_id=uuid4(),
        ),
        "logistics_state_custody_mismatch",
    )
    _assert_invalid(
        LogisticsCurrentState(stock_lot_id=uuid4(), quantity_on_hand=None),
        "logistics_state_quantity_required",
    )
    _assert_invalid(
        LogisticsCurrentState(asset_id=uuid4(), quantity_on_hand=1),
        "logistics_state_quantity_mismatch",
    )
    state = LogisticsCurrentState(
        organization_id=uuid4(),
        asset_id=uuid4(),
        current_node_id=uuid4(),
    )
    _cache(state, "current_node", _related(organization_id=uuid4()))
    _assert_invalid(state, "logistics_containment_scope_mismatch")


def test_edition_control_is_bound_to_its_organization() -> None:
    control = LogisticsEditionControl(
        organization_id=uuid4(),
        edition_id=uuid4(),
    )
    _cache(control, "edition", _related(organization_id=uuid4()))
    _assert_invalid(control, "logistics_control_scope_mismatch")
