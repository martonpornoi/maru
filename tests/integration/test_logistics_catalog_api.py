"""Installed-route coverage for strict Logistics catalog command APIs."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from maru.authorization.models import ScopedResourceBinding
from maru.logistics.models import (
    Asset,
    AssetAgreement,
    KeyholderResponsibility,
    LogisticsCurrentState,
    LogisticsEvent,
    LogisticsLabel,
    LogisticsManifest,
    LogisticsManifestLine,
    LogisticsNode,
    LogisticsParty,
    PhysicalKey,
    RestrictedLogisticsAddress,
    ReusableKit,
    StockLot,
)
from maru.logistics.services import (
    CATALOG_MANAGE_CAPABILITY,
    MANIFEST_MANAGE_CAPABILITY,
    OPERATIONS_MANAGE_CAPABILITY,
    ManifestLineInput,
    SubjectLocator,
    change_manifest_state,
    create_logistics_manifest,
)
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.workforce_helpers import create_department_for_test

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _org_path(organization_id: UUID, suffix: str) -> str:
    return f"/api/v1/organizations/{organization_id}/logistics/{suffix}"


def _edition_path(organization_id: UUID, edition_id: UUID, suffix: str) -> str:
    return (
        f"/api/v1/organizations/{organization_id}/editions/{edition_id}/"
        f"logistics/{suffix}"
    )


def _post(
    api: APIClient,
    path: str,
    payload: dict[str, object],
    *,
    idempotency_key: UUID | None = None,
) -> Response:
    return api.post(
        path,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(idempotency_key or uuid4()),
    )


def _created_id(response: Response, *, status_code: int = 201) -> UUID:
    assert response.status_code == status_code, response.data
    _assert_private_no_store(response)
    return UUID(response.data["object_id"])


def _assert_private_no_store(response: Response) -> None:
    cache_control = response.headers["Cache-Control"]
    assert "private" in cache_control
    assert "no-store" in cache_control


def _grant_catalog(*, actor, edition=None, organization=None) -> None:
    scoped_organization = organization or edition.organization
    CapabilityGrantFactory(
        organization=scoped_organization,
        edition=edition,
        principal=actor,
        capability_code=CATALOG_MANAGE_CAPABILITY,
    )


def test_installed_catalog_routes_execute_every_governed_command() -> None:  # noqa: PLR0915
    edition = EventEditionFactory()
    organization = edition.organization
    organization_actor = AccountFactory()
    edition_actor = AccountFactory()
    manifest_actor = AccountFactory()
    _grant_catalog(actor=organization_actor, organization=organization)
    _grant_catalog(actor=edition_actor, edition=edition)
    api = APIClient()

    party_payload: dict[str, object] = {
        "code": "example-haulage",
        "profile": {
            "kind": "business",
            "role": "provider",
            "legal_name": "Example Haulage Kft.",
            "public_name": "Example Haulage",
            "provider_reference": "PROVIDER-42",
            "website_url": "https://haulage.example.test/",
        },
        "reason": "Register the approved transport provider.",
    }
    party_key = uuid4()
    api.force_authenticate(user=organization_actor)
    party_response = _post(
        api,
        _org_path(organization.id, "parties"),
        party_payload,
        idempotency_key=party_key,
    )
    party_id = _created_id(party_response)
    assert LogisticsParty.objects.filter(
        id=party_id, organization=organization
    ).exists()

    replay = _post(
        api,
        _org_path(organization.id, "parties"),
        party_payload,
        idempotency_key=party_key,
    )
    assert _created_id(replay, status_code=200) == party_id
    assert replay.data["replayed"] is True
    assert LogisticsParty.objects.filter(organization=organization).count() == 1

    api.force_authenticate(user=edition_actor)
    retention_until = timezone.now() + timedelta(days=90)
    address_id = _created_id(
        _post(
            api,
            _edition_path(organization.id, edition.id, "restricted-addresses"),
            {
                "purpose": "storage",
                "party_id": str(party_id),
                "label": "Off-site storage",
                "recipient_name": "Example Haulage receiving",
                "postal_address": "Synthetic Logistics Park 1, Budapest",
                "access_instructions": "Call the provider reference at the gate.",
                "retention_until": retention_until.isoformat(),
                "reason": "Record the approved storage contact for this edition.",
            },
        )
    )
    assert RestrictedLogisticsAddress.objects.filter(
        id=address_id,
        organization=organization,
        edition=edition,
    ).exists()

    node_id = _created_id(
        _post(
            api,
            _edition_path(organization.id, edition.id, "nodes"),
            {
                "kind": "storage_area",
                "code": "off-site-store",
                "name": "Off-site convention storage",
                "description": "Edition-scoped storage area.",
                "storage_address_id": str(address_id),
                "provider_id": str(party_id),
                "capacity_note": "Synthetic capacity only.",
                "reason": "Register the physical storage node.",
            },
        )
    )
    assert LogisticsNode.objects.filter(
        id=node_id,
        organization=organization,
        edition=edition,
    ).exists()

    asset_id = _created_id(
        _post(
            api,
            _edition_path(organization.id, edition.id, "assets"),
            {
                "catalog_code": "lighting-desk",
                "name": "Lighting desk",
                "asset_type": "control-desk",
                "manufacturer": "Synthetic Manufacturer",
                "model_name": "LX-1",
                "serial_number": "SYNTHETIC-LX-1",
                "acquisition": "owned",
                "value_class": "high",
                "owner": {"kind": "organization"},
                "reason": "Register the serialized stage asset.",
            },
        )
    )
    assert Asset.objects.filter(
        id=asset_id,
        organization=organization,
        edition_allocation=edition,
    ).exists()

    stock_lot_id = _created_id(
        _post(
            api,
            _edition_path(organization.id, edition.id, "stock-lots"),
            {
                "catalog_code": "cable-ties",
                "name": "Reusable cable ties",
                "stock_type": "fastener",
                "unit": "piece",
                "initial_quantity": 120,
                "value_class": "low",
                "owner": {"kind": "organization"},
                "reason": "Register counted convention stock.",
            },
        )
    )
    assert StockLot.objects.filter(
        id=stock_lot_id,
        organization=organization,
        edition_allocation=edition,
    ).exists()

    key_id = _created_id(
        _post(
            api,
            _edition_path(organization.id, edition.id, "physical-keys"),
            {
                "code": "off-site-store-key",
                "label": "Off-site store key",
                "opens_node_id": str(node_id),
                "provider_id": str(party_id),
                "reason": "Register the tracked physical key.",
            },
        )
    )
    assert PhysicalKey.objects.filter(
        id=key_id,
        organization=organization,
        edition_allocation=edition,
    ).exists()

    api.force_authenticate(user=organization_actor)
    starts_at = timezone.now() + timedelta(hours=1)
    ends_at = starts_at + timedelta(hours=2)
    keyholder_result_id = _created_id(
        _post(
            api,
            _org_path(organization.id, f"physical-keys/{key_id}/keyholders"),
            {
                "responsible_account_id": str(organization_actor.id),
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "expected_version": 1,
                "reason": "Assign physical custody for setup.",
            },
        ),
        status_code=200,
    )
    assert keyholder_result_id == key_id
    assert KeyholderResponsibility.objects.filter(
        key_id=key_id,
        responsible_account=organization_actor,
    ).exists()

    label_id = _created_id(
        _post(
            api,
            _org_path(organization.id, "labels"),
            {
                "subject": {"kind": "asset", "object_id": str(asset_id)},
                "label_code": "lighting-desk-label",
                "qr_identifier": "synthetic-logistics-label-token-000001",
                "reason": "Create the public asset label.",
            },
        )
    )
    assert LogisticsLabel.objects.filter(
        id=label_id,
        organization=organization,
        asset_id=asset_id,
    ).exists()

    api.force_authenticate(user=edition_actor)
    agreement_id = _created_id(
        _post(
            api,
            _edition_path(organization.id, edition.id, "agreements"),
            {
                "subject": {"kind": "asset", "object_id": str(asset_id)},
                "kind": "rental",
                "provider": {"party_id": str(party_id)},
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "return_due_at": ends_at.isoformat(),
                "provider_reference": "RENTAL-42",
                "terms_reference": "synthetic://agreement/42",
                "reason": "Record the bounded provider agreement.",
            },
        )
    )
    assert AssetAgreement.objects.filter(
        id=agreement_id,
        organization=organization,
        edition=edition,
        provider_id=party_id,
    ).exists()

    api.force_authenticate(user=organization_actor)
    kit_id = _created_id(
        _post(
            api,
            _org_path(organization.id, "kits"),
            {
                "code": "stage-control-kit",
                "name": "Stage control kit",
                "description": "Reusable tracked stage items.",
                "lines": [
                    {
                        "subject": {"kind": "asset", "object_id": str(asset_id)},
                        "quantity": 1,
                    },
                    {
                        "subject": {
                            "kind": "stock_lot",
                            "object_id": str(stock_lot_id),
                        },
                        "quantity": 12,
                    },
                    {
                        "subject": {"kind": "key", "object_id": str(key_id)},
                        "quantity": 1,
                    },
                ],
                "reason": "Register the reusable stage kit.",
            },
        )
    )
    assert ReusableKit.objects.filter(id=kit_id, organization=organization).exists()

    department = create_department_for_test(
        edition=edition,
        name="Logistics",
        expected_code="logistics",
    )
    operations_actor = AccountFactory()
    CapabilityGrantFactory(
        organization=organization,
        edition=edition,
        principal=operations_actor,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
    )
    manifest_result = create_logistics_manifest(
        actor=operations_actor,
        organization_id=organization.id,
        edition_id=edition.id,
        responsible_department_id=department.id,
        manifest_number="IN-API-PARITY",
        kind=LogisticsManifest.Kind.STAGE_RECEIVING,
        title="API parity manifest",
        source_node_id=None,
        destination_node_id=node_id,
        vehicle_id=None,
        provider_id=party_id,
        loading_starts_at=None,
        loading_ends_at=None,
        lines=(
            ManifestLineInput(
                subject=SubjectLocator(kind="asset", object_id=asset_id),
            ),
        ),
        reason="Create a manifest before exact line delegation.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    manifest = LogisticsManifest.objects.get(id=manifest_result.object_id)
    binding = ScopedResourceBinding.objects.get(
        resource_kind=ScopedResourceBinding.ResourceKind.LOGISTICS_MANIFEST,
        resource_id=manifest.id,
    )
    CapabilityGrantFactory(
        organization=organization,
        edition=edition,
        department=department,
        resource_binding=binding,
        principal=manifest_actor,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
    )

    api.force_authenticate(user=manifest_actor)
    manifest_line_result_id = _created_id(
        _post(
            api,
            _edition_path(
                organization.id,
                edition.id,
                f"manifests/{manifest.id}/lines",
            ),
            {
                "expected_version": 1,
                "line": {
                    "subject": {
                        "kind": "stock_lot",
                        "object_id": str(stock_lot_id),
                    },
                    "quantity": 12,
                    "notes": "Count at stage receiving.",
                },
                "reason": "Append the independently delegated manifest line.",
            },
        ),
        status_code=200,
    )
    assert manifest_line_result_id == manifest.id
    added_line = LogisticsManifestLine.objects.get(
        manifest=manifest,
        stock_lot_id=stock_lot_id,
    )
    assert added_line.label_snapshot == "Reusable cable ties"
    manifest.refresh_from_db()
    assert manifest.aggregate_version == 2

    change_manifest_state(
        actor=manifest_actor,
        organization_id=organization.id,
        edition_id=edition.id,
        manifest_id=manifest.id,
        expected_version=2,
        action="seal",
        reason="Seal the checked Stage Tech receiving manifest.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    asset_line = LogisticsManifestLine.objects.get(
        manifest=manifest,
        asset_id=asset_id,
    )
    receipt_key = uuid4()
    receipt_payload: dict[str, object] = {
        "expected_sequence": 0,
        "occurred_at": timezone.now().isoformat(),
        "condition_after": "Received intact",
        "reason": "Record the Stage Tech handover at receiving.",
    }
    receipt_path = _edition_path(
        organization.id,
        edition.id,
        f"manifests/{manifest.id}/lines/{asset_line.id}/receive",
    )
    receipt_response = _post(
        api,
        receipt_path,
        receipt_payload,
        idempotency_key=receipt_key,
    )
    event_id = _created_id(receipt_response, status_code=200)
    event = LogisticsEvent.objects.get(id=event_id)
    assert event.event_type == LogisticsEvent.EventType.RECEIVE
    assert event.manifest_id == manifest.id
    assert event.evidence_reference == f"manifest-line:{asset_line.id}"
    assert LogisticsCurrentState.objects.filter(
        asset_id=asset_id,
        last_event=event,
        current_node_id=node_id,
    ).exists()

    replayed_receipt = _post(
        api,
        receipt_path,
        receipt_payload,
        idempotency_key=receipt_key,
    )
    assert _created_id(replayed_receipt, status_code=200) == event_id
    assert replayed_receipt.data["replayed"] is True
    assert LogisticsEvent.objects.filter(id=event_id).count() == 1


def test_catalog_routes_hide_foreign_scopes_before_malformed_input_parsing() -> None:
    edition = EventEditionFactory()
    organization = edition.organization
    actor = AccountFactory()
    _grant_catalog(actor=actor, edition=edition)
    api = APIClient()
    api.force_authenticate(user=actor)

    foreign_organization_edition = EventEditionFactory()
    foreign_edition = EventEditionFactory(series=edition.series)
    malformed = '{"not":'

    for path in (
        _org_path(organization.id, "parties"),
        _org_path(foreign_organization_edition.organization_id, "parties"),
        _edition_path(organization.id, foreign_edition.id, "nodes"),
    ):
        response = api.generic(
            "POST",
            path,
            data=malformed,
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY="not-a-canonical-uuid",
        )
        assert response.status_code == 403
        _assert_private_no_store(response)

    assert not LogisticsParty.objects.filter(
        organization=foreign_organization_edition.organization
    ).exists()
    assert not LogisticsParty.objects.filter(organization=organization).exists()
    assert not LogisticsNode.objects.filter(edition=foreign_edition).exists()

    inactive = AccountFactory(is_active=False)
    api.force_authenticate(user=inactive)
    inactive_response = api.generic(
        "POST",
        _org_path(organization.id, "parties"),
        data=malformed,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-canonical-uuid",
    )
    assert inactive_response.status_code == 403
    _assert_private_no_store(inactive_response)
    assert not LogisticsParty.objects.filter(organization=organization).exists()

    operations_actor = AccountFactory()
    CapabilityGrantFactory(
        organization=organization,
        edition=edition,
        principal=operations_actor,
        capability_code=OPERATIONS_MANAGE_CAPABILITY,
    )
    department = create_department_for_test(
        edition=edition,
        name="Security Logistics",
        expected_code="security-logistics",
    )
    _grant_catalog(actor=operations_actor, edition=edition)
    api = APIClient()
    api.force_authenticate(user=operations_actor)
    asset_id = _created_id(
        _post(
            api,
            _edition_path(organization.id, edition.id, "assets"),
            {
                "catalog_code": "manifest-security-asset",
                "name": "Manifest security asset",
                "asset_type": "test-equipment",
                "acquisition": "owned",
                "owner": {"kind": "organization"},
                "reason": "Create a subject for exact-scope testing.",
            },
        )
    )

    manifests: list[LogisticsManifest] = []
    for sequence in (1, 2):
        result = create_logistics_manifest(
            actor=operations_actor,
            organization_id=organization.id,
            edition_id=edition.id,
            responsible_department_id=department.id,
            manifest_number=f"IN-EXACT-{sequence}",
            kind=LogisticsManifest.Kind.INBOUND,
            title=f"Exact manifest {sequence}",
            source_node_id=None,
            destination_node_id=None,
            vehicle_id=None,
            provider_id=None,
            loading_starts_at=None,
            loading_ends_at=None,
            lines=(
                ManifestLineInput(
                    subject=SubjectLocator(kind="asset", object_id=asset_id),
                ),
            ),
            reason="Create an exact-scope authorization fixture.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
        manifests.append(LogisticsManifest.objects.get(id=result.object_id))

    allowed_binding = ScopedResourceBinding.objects.get(
        resource_kind=ScopedResourceBinding.ResourceKind.LOGISTICS_MANIFEST,
        resource_id=manifests[0].id,
    )
    CapabilityGrantFactory(
        organization=organization,
        edition=edition,
        department=department,
        resource_binding=allowed_binding,
        principal=actor,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
    )
    api.force_authenticate(user=actor)
    response = api.generic(
        "POST",
        _edition_path(
            organization.id,
            edition.id,
            f"manifests/{manifests[1].id}/lines",
        ),
        data=malformed,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-canonical-uuid",
    )
    assert response.status_code == 403
    _assert_private_no_store(response)
    assert manifests[1].lines.count() == 1

    foreign_line = manifests[1].lines.get()
    foreign_line_response = api.generic(
        "POST",
        _edition_path(
            organization.id,
            edition.id,
            f"manifests/{manifests[0].id}/lines/{foreign_line.id}/receive",
        ),
        data=malformed,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-canonical-uuid",
    )
    assert foreign_line_response.status_code == 403
    _assert_private_no_store(foreign_line_response)
