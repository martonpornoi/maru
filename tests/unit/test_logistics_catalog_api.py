from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from maru.identity.models import Account
from maru.logistics.catalog_api import (
    KeyholderAssignmentView,
    LogisticsPartyCollectionView,
    ManifestLineCollectionView,
    ManifestReceiptView,
    StockLotCollectionView,
)
from maru.logistics.services import (
    CATALOG_MANAGE_CAPABILITY,
    MANIFEST_MANAGE_CAPABILITY,
    LogisticsAuthorizationDeniedError,
    LogisticsCommandResult,
)


def _actor() -> Account:
    return Account(
        id=uuid4(),
        email="logistics-operator@example.test",
        is_active=True,
    )


def _result(*, replayed: bool = False, version: int = 1) -> LogisticsCommandResult:
    return LogisticsCommandResult(
        object_id=uuid4(),
        receipt_id=uuid4(),
        resulting_version=version,
        replayed=replayed,
    )


def _assert_private_no_store(response: Response) -> None:
    cache_control = response.headers["Cache-Control"]
    assert "private" in cache_control
    assert "no-store" in cache_control


def test_denied_party_command_authorizes_before_malformed_json_parse() -> None:
    organization_id = uuid4()
    actor = _actor()
    request = APIRequestFactory().generic(
        "POST",
        "/api/v1/organizations/denied/logistics/parties",
        data='{ "malformed":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.logistics.catalog_api.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ) as authorize,
        patch("maru.logistics.catalog_api.create_logistics_party") as command,
    ):
        response = LogisticsPartyCollectionView.as_view()(
            request,
            organization_id=organization_id,
        )

    assert response.status_code == 403
    authorize.assert_called_once_with(
        actor=actor,
        organization_id=organization_id,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        edition_id=None,
        manifest_id=None,
    )
    command.assert_not_called()
    _assert_private_no_store(response)


def test_denied_keyholder_command_resolves_exact_key_before_parse() -> None:
    organization_id = uuid4()
    key_id = uuid4()
    actor = _actor()
    request = APIRequestFactory().generic(
        "POST",
        "/api/v1/organizations/denied/logistics/physical-keys/foreign/keyholders",
        data='{ "malformed":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.logistics.catalog_api.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ) as authorize,
        patch("maru.logistics.catalog_api.assign_keyholder_responsibility") as command,
    ):
        response = KeyholderAssignmentView.as_view()(
            request,
            organization_id=organization_id,
            key_id=key_id,
        )

    assert response.status_code == 403
    authorize.assert_called_once_with(
        actor=actor,
        organization_id=organization_id,
        capability_code=CATALOG_MANAGE_CAPABILITY,
        edition_id=None,
        manifest_id=None,
        key_id=key_id,
    )
    command.assert_not_called()
    _assert_private_no_store(response)


def test_party_command_is_closed_idempotent_and_private() -> None:
    organization_id = uuid4()
    key = uuid4()
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/organizations/current/logistics/parties",
        data={
            "code": "example-provider",
            "profile": {
                "kind": "business",
                "role": "provider",
                "legal_name": "Example Provider Kft.",
                "public_name": "Example Provider",
                "website_url": "https://provider.example.test/",
            },
            "reason": "Register the approved transport provider.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )
    force_authenticate(request, user=actor)
    command_result = _result()

    with (
        patch("maru.logistics.catalog_api.authorize_logistics_api_scope"),
        patch(
            "maru.logistics.catalog_api.create_logistics_party",
            return_value=command_result,
        ) as command,
    ):
        response = LogisticsPartyCollectionView.as_view()(
            request,
            organization_id=organization_id,
        )

    assert response.status_code == 201
    assert response.data["object_id"] == str(command_result.object_id)
    kwargs = command.call_args.kwargs
    assert kwargs["actor"] is actor
    assert kwargs["organization_id"] == organization_id
    assert kwargs["idempotency_key"] == key
    assert kwargs["source_channel"] == "api"
    assert kwargs["profile"].website_url == "https://provider.example.test/"
    _assert_private_no_store(response)


def test_stock_command_rejects_unknown_nested_owner() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/organizations/current/editions/current/logistics/stock-lots",
        data={
            "catalog_code": "cable-ties",
            "name": "Reusable cable ties",
            "stock_type": "fastener",
            "unit": "piece",
            "initial_quantity": 40,
            "owner": {
                "kind": "account",
                "account_id": str(uuid4()).upper(),
                "tenant_override": str(uuid4()),
            },
            "reason": "Register the offered logistics stock.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    force_authenticate(request, user=actor)

    with (
        patch("maru.logistics.catalog_api.authorize_logistics_api_scope"),
        patch("maru.logistics.catalog_api.register_stock_lot") as command,
    ):
        response = StockLotCollectionView.as_view()(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
        )

    assert response.status_code == 400
    assert "owner" in response.data["errors"]
    assert "tenant_override" in response.data["errors"]["owner"]
    command.assert_not_called()
    _assert_private_no_store(response)


def test_manifest_line_uses_exact_manifest_preflight_and_expected_version() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    manifest_id = uuid4()
    subject_id = uuid4()
    key = uuid4()
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/organizations/current/editions/current/logistics/manifests/"
        "current/lines",
        data={
            "expected_version": 3,
            "line": {
                "subject": {"kind": "asset", "object_id": str(subject_id)},
                "quantity": 1,
                "notes": "Receive at stage dock.",
            },
            "reason": "Append the checked packing line.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )
    force_authenticate(request, user=actor)
    command_result = _result(version=4)

    with (
        patch("maru.logistics.catalog_api.authorize_logistics_api_scope") as authorize,
        patch(
            "maru.logistics.catalog_api.add_manifest_line",
            return_value=command_result,
        ) as command,
    ):
        response = ManifestLineCollectionView.as_view()(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
        )

    assert response.status_code == 200
    authorize.assert_called_once_with(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        manifest_id=manifest_id,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
    )
    kwargs = command.call_args.kwargs
    assert kwargs["organization_id"] == organization_id
    assert kwargs["edition_id"] == edition_id
    assert kwargs["manifest_id"] == manifest_id
    assert kwargs["expected_version"] == 3
    assert kwargs["idempotency_key"] == key
    assert kwargs["line"].subject.object_id == subject_id
    _assert_private_no_store(response)


def test_denied_foreign_manifest_is_hidden_before_body_or_header_validation() -> None:
    actor = _actor()
    request = APIRequestFactory().generic(
        "POST",
        "/api/v1/organizations/current/editions/current/logistics/manifests/"
        "foreign/lines?unexpected=1",
        data="not-json",
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="invalid",
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.logistics.catalog_api.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        patch("maru.logistics.catalog_api.add_manifest_line") as command,
    ):
        response = ManifestLineCollectionView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            manifest_id=uuid4(),
        )

    assert response.status_code == 403
    command.assert_not_called()
    _assert_private_no_store(response)


def test_denied_manifest_receipt_hides_malformed_body_and_header() -> None:
    actor = _actor()
    line_id = uuid4()
    request = APIRequestFactory().generic(
        "POST",
        "/api/v1/organizations/current/editions/current/logistics/manifests/"
        f"foreign/lines/{line_id}/receive?unexpected=1",
        data="not-json",
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="invalid",
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.logistics.catalog_api.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ) as authorize,
        patch("maru.logistics.catalog_api.record_manifest_receipt") as command,
    ):
        response = ManifestReceiptView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            manifest_id=uuid4(),
            line_id=line_id,
        )

    assert response.status_code == 403
    authorize.assert_called_once()
    command.assert_not_called()
    _assert_private_no_store(response)


def test_manifest_receipt_uses_exact_preflight_and_sequence() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    manifest_id = uuid4()
    line_id = uuid4()
    key = uuid4()
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/organizations/current/editions/current/logistics/manifests/"
        f"current/lines/{line_id}/receive",
        data={
            "expected_sequence": 2,
            "occurred_at": "2026-08-09T14:00:00+02:00",
            "condition_after": "Received intact",
            "reason": "Receive the checked Stage Tech box.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key),
    )
    force_authenticate(request, user=actor)
    command_result = _result(version=3)

    with (
        patch("maru.logistics.catalog_api.authorize_logistics_api_scope") as authorize,
        patch(
            "maru.logistics.catalog_api.record_manifest_receipt",
            return_value=command_result,
        ) as command,
    ):
        response = ManifestReceiptView.as_view()(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
            line_id=line_id,
        )

    assert response.status_code == 200
    authorize.assert_called_once_with(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        manifest_id=manifest_id,
        manifest_line_id=line_id,
        capability_code=MANIFEST_MANAGE_CAPABILITY,
    )
    kwargs = command.call_args.kwargs
    assert kwargs["manifest_id"] == manifest_id
    assert kwargs["line_id"] == line_id
    assert kwargs["expected_sequence"] == 2
    assert kwargs["idempotency_key"] == key
    assert kwargs["source_channel"] == "api"
    _assert_private_no_store(response)


@pytest.mark.parametrize(
    "invalid_key",
    [
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        " aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa ",
    ],
)
def test_noncanonical_idempotency_header_is_rejected_after_authorization(
    invalid_key: str,
) -> None:
    organization_id = uuid4()
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/organizations/current/logistics/parties",
        data={
            "code": "example-provider",
            "profile": {
                "kind": "business",
                "role": "provider",
                "legal_name": "Example Provider Kft.",
                "public_name": "Example Provider",
            },
            "reason": "Register provider.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=invalid_key,
    )
    force_authenticate(request, user=actor)

    with (
        patch("maru.logistics.catalog_api.authorize_logistics_api_scope"),
        patch("maru.logistics.catalog_api.create_logistics_party") as command,
    ):
        response = LogisticsPartyCollectionView.as_view()(
            request,
            organization_id=organization_id,
        )

    assert response.status_code == 400
    assert "Idempotency-Key" in response.data["errors"]
    command.assert_not_called()
    _assert_private_no_store(response)


def test_replayed_create_returns_ok_not_created() -> None:
    organization_id = uuid4()
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/organizations/current/logistics/parties",
        data={
            "code": "example-provider",
            "profile": {
                "kind": "business",
                "role": "provider",
                "legal_name": "Example Provider Kft.",
                "public_name": "Example Provider",
            },
            "reason": "Register provider.",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    force_authenticate(request, user=actor)

    with (
        patch("maru.logistics.catalog_api.authorize_logistics_api_scope"),
        patch(
            "maru.logistics.catalog_api.create_logistics_party",
            return_value=_result(replayed=True),
        ),
    ):
        response = LogisticsPartyCollectionView.as_view()(
            request,
            organization_id=organization_id,
        )

    assert response.status_code == 200
    assert response.data["replayed"] is True
    _assert_private_no_store(response)


def test_catalog_result_identifiers_remain_uuid_strings() -> None:
    result = _result()

    assert isinstance(result.object_id, UUID)
    assert isinstance(result.receipt_id, UUID)
