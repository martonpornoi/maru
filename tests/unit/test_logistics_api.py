from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from maru.core.problems import DependencyUnavailable
from maru.identity.models import Account
from maru.logistics import api as logistics_api
from maru.logistics.api import (
    EquipmentOfferReviewView,
    LogisticsActivityView,
    LogisticsManifestCollectionView,
    LogisticsManifestDetailView,
    LogisticsManifestStateView,
    LogisticsMovementView,
    LogisticsWorkspaceView,
    MyEquipmentOfferCollectionView,
    MyEquipmentOfferWithdrawView,
    OfflineScanBatchView,
    RestrictedLogisticsContactView,
    StageTechReceivingView,
)
from maru.logistics.queries import (
    ActivityProjection,
    LogisticsFormChoices,
    LogisticsWorkspaceProjection,
    ManifestProjection,
    RestrictedContactProjection,
    authorize_self_offer_history_api_scope,
)
from maru.logistics.services import (
    MANIFEST_MANAGE_CAPABILITY,
    MANIFEST_VIEW_CAPABILITY,
    RESTRICTED_CONTACT_CAPABILITY,
    SELF_OFFER_CAPABILITY,
    WORKSPACE_VIEW_CAPABILITY,
    LogisticsAuthorizationDeniedError,
    LogisticsCommandError,
    LogisticsCommandResult,
    LogisticsContainmentCycleError,
    LogisticsResourceUnavailableError,
    LogisticsRetryConflictError,
    LogisticsStateConflictError,
    LogisticsVersionConflictError,
)


def _actor(*, active: bool = True) -> Account:
    return Account(
        id=uuid4(),
        email="logistics-api-operator@example.test",
        is_active=active,
    )


def _assert_private_no_store(response: Response) -> None:
    cache_control = response.headers["Cache-Control"]
    assert "private" in cache_control
    assert "no-store" in cache_control


def _result(*, replayed: bool = False) -> LogisticsCommandResult:
    return LogisticsCommandResult(
        object_id=uuid4(),
        receipt_id=uuid4(),
        resulting_version=2,
        replayed=replayed,
    )


def _empty_choices() -> LogisticsFormChoices:
    return LogisticsFormChoices(
        departments=(),
        parties=(),
        addresses=(),
        nodes=(),
        packing_nodes=(),
        vehicles=(),
        venue_rooms=(),
        venue_space_selections=(),
        assets=(),
        stock_lots=(),
        physical_keys=(),
        tracked_subjects=(),
        people=(),
        manifests=(),
        labels=(),
    )


def _manifest() -> ManifestProjection:
    return ManifestProjection(
        id=uuid4(),
        manifest_number="IN-API-1",
        kind="inbound",
        title="API manifest",
        status="draft",
        responsible_department_id=uuid4(),
        source_node_id=None,
        source_name="",
        destination_node_id=None,
        destination_name="",
        vehicle_id=None,
        vehicle_name="",
        loading_starts_at=None,
        loading_ends_at=None,
        box_count=0,
        line_count=0,
        aggregate_version=1,
        lines=(),
    )


def _workspace(
    *, manifest: ManifestProjection | None = None
) -> LogisticsWorkspaceProjection:
    return LogisticsWorkspaceProjection(
        offers=(),
        manifests=() if manifest is None else (manifest,),
        current_states=(),
        due_returns=(),
        discrepancies=(),
        choices=_empty_choices(),
    )


def test_denied_self_offer_authorizes_before_body_and_header_parse() -> None:
    actor = _actor()
    request = APIRequestFactory().generic(
        "POST",
        "/api/v1/logistics/offers?unknown=1",
        data='{ "malformed":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.logistics.api.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ) as authorize,
        patch("maru.logistics.api.submit_equipment_offer") as command,
    ):
        response = MyEquipmentOfferCollectionView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    assert response.status_code == 403
    assert authorize.call_args.kwargs["capability_code"] == SELF_OFFER_CAPABILITY
    assert authorize.call_args.kwargs["require_self_offer_open"] is True
    command.assert_not_called()
    _assert_private_no_store(response)


def test_withdraw_preauthorizes_exact_owned_offer_before_parse() -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    offer_id = uuid4()
    request = APIRequestFactory().generic(
        "POST",
        "/api/v1/logistics/offers/foreign/withdraw",
        data="not-json",
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="invalid",
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.logistics.api.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ) as authorize,
        patch("maru.logistics.api.withdraw_equipment_offer") as command,
    ):
        response = MyEquipmentOfferWithdrawView.as_view()(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            offer_id=offer_id,
        )

    assert response.status_code == 403
    authorize.assert_called_once_with(
        actor=actor,
        organization_id=organization_id,
        capability_code=SELF_OFFER_CAPABILITY,
        edition_id=edition_id,
        manifest_id=None,
        offer_id=offer_id,
        address_id=None,
        require_self_offer_open=False,
    )
    command.assert_not_called()
    _assert_private_no_store(response)


@pytest.mark.parametrize(
    ("view", "capability_code", "exact_kwarg"),
    [
        (LogisticsWorkspaceView, WORKSPACE_VIEW_CAPABILITY, {}),
        (
            LogisticsManifestDetailView,
            MANIFEST_VIEW_CAPABILITY,
            {"manifest_id": uuid4()},
        ),
    ],
)
def test_denied_get_preauthorizes_before_unknown_query_validation(
    view: type,
    capability_code: str,
    exact_kwarg: dict[str, object],
) -> None:
    actor = _actor()
    request = APIRequestFactory().get("/api/v1/logistics/current?unknown=1")
    force_authenticate(request, user=actor)

    with patch(
        "maru.logistics.api.authorize_logistics_api_scope",
        side_effect=LogisticsAuthorizationDeniedError,
    ) as authorize:
        response = view.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            **exact_kwarg,
        )

    assert response.status_code == 403
    assert authorize.call_args.kwargs["capability_code"] == capability_code
    for key, value in exact_kwarg.items():
        assert authorize.call_args.kwargs[key] == value
    _assert_private_no_store(response)


def test_manifest_state_denial_uses_exact_manifest_before_parse() -> None:
    actor = _actor()
    manifest_id = uuid4()
    request = APIRequestFactory().generic(
        "POST",
        "/api/v1/logistics/manifests/foreign/state",
        data="not-json",
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="invalid",
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.logistics.api.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ) as authorize,
        patch("maru.logistics.api.change_manifest_state") as command,
    ):
        response = LogisticsManifestStateView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            manifest_id=manifest_id,
        )

    assert response.status_code == 403
    assert authorize.call_args.kwargs["manifest_id"] == manifest_id
    assert authorize.call_args.kwargs["capability_code"] == (MANIFEST_MANAGE_CAPABILITY)
    command.assert_not_called()
    _assert_private_no_store(response)


def test_restricted_contact_denial_uses_exact_address_before_purpose_parse() -> None:
    actor = _actor()
    address_id = uuid4()
    request = APIRequestFactory().generic(
        "POST",
        "/api/v1/logistics/contacts/foreign",
        data='{ "access_purpose": "arbitrary",',
        content_type="application/json",
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.logistics.api.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ) as authorize,
        patch("maru.logistics.api.read_restricted_logistics_contact") as query,
    ):
        response = RestrictedLogisticsContactView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            address_id=address_id,
        )

    assert response.status_code == 403
    assert authorize.call_args.kwargs["address_id"] == address_id
    assert authorize.call_args.kwargs["capability_code"] == (
        RESTRICTED_CONTACT_CAPABILITY
    )
    query.assert_not_called()
    _assert_private_no_store(response)


def test_inactive_offer_owner_history_preflight_denies_before_owned_offer_lookup() -> (
    None
):
    actor = _actor(active=False)

    with (
        patch("maru.logistics.queries.EquipmentOffer.objects.filter") as offers,
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        authorize_self_offer_history_api_scope(
            actor=actor,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    offers.assert_not_called()


def _raised(error: Exception) -> None:
    raise error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LogisticsAuthorizationDeniedError(), PermissionDenied),
        (LogisticsResourceUnavailableError(), NotFound),
        (LogisticsVersionConflictError(), logistics_api.LogisticsConflict),
        (LogisticsRetryConflictError(), logistics_api.LogisticsConflict),
        (LogisticsStateConflictError(), logistics_api.LogisticsConflict),
        (LogisticsContainmentCycleError(), logistics_api.LogisticsConflict),
        (
            IntegrityError("synthetic integrity conflict"),
            logistics_api.LogisticsConflict,
        ),
        (DatabaseError("synthetic dependency outage"), DependencyUnavailable),
        (LogisticsCommandError("synthetic command dependency"), DependencyUnavailable),
    ],
)
def test_execute_maps_closed_domain_failures_without_leaking_details(
    error: Exception,
    expected: type[Exception],
) -> None:
    with pytest.raises(expected) as raised:
        logistics_api._execute(lambda: _raised(error))

    assert "synthetic" not in str(raised.value)


def test_execute_preserves_structured_and_generic_django_validation() -> None:
    with pytest.raises(ValidationError) as structured:
        logistics_api._execute(
            lambda: _raised(DjangoValidationError({"field": ["Invalid value."]}))
        )
    assert "field" in structured.value.detail

    with pytest.raises(ValidationError) as generic:
        logistics_api._execute(
            lambda: _raised(DjangoValidationError("private validator detail"))
        )
    assert generic.value.get_codes()["non_field_errors"][0] == (
        "logistics_input_invalid"
    )
    assert "private validator detail" not in str(generic.value.detail)


@pytest.mark.parametrize(
    "header",
    [None, "", " " + "a" * 36, "a" * 129, "not-a-uuid"],
)
def test_main_api_idempotency_boundary_rejects_missing_or_noncanonical_values(
    header: str | None,
) -> None:
    request = APIRequestFactory().post(
        "/api/v1/logistics/test",
        data={},
        format="json",
        **({} if header is None else {"HTTP_IDEMPOTENCY_KEY": header}),
    )

    with pytest.raises(ValidationError):
        logistics_api._idempotency_key(Request(request))


def test_correlation_id_accepts_uuid_text_and_falls_back_safely() -> None:
    expected = uuid4()
    request = Request(APIRequestFactory().get("/api/v1/logistics/test"))
    request.correlation_id = str(expected)  # type: ignore[attr-defined]
    assert logistics_api._correlation_id(request) == expected

    request.correlation_id = object()  # type: ignore[attr-defined]
    assert isinstance(logistics_api._correlation_id(request), type(expected))


def test_successful_query_adapters_return_purpose_limited_projections() -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    manifest = _manifest()
    activity = ActivityProjection(
        id=uuid4(),
        sequence=1,
        event_type="receive",
        subject_kind="asset",
        subject_id=uuid4(),
        source_node_id=None,
        destination_node_id=uuid4(),
        from_custodian_account_id=None,
        to_custodian_account_id=None,
        quantity=None,
        condition_before="",
        condition_after="intact",
        occurred_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
        actor_id=actor.id,
    )
    contact = RestrictedContactProjection(
        address_id=uuid4(),
        purpose="pickup",
        label="Stage dock",
        recipient_name="Synthetic Recipient",
        contact_email="recipient@example.test",
        contact_phone="+3610000000",
        postal_address="Synthetic address",
        access_instructions="Use the signed entrance.",
        retention_until=datetime(2026, 8, 10, 12, tzinfo=UTC),
        subject_account_id=None,
        party_id=None,
    )

    def request() -> object:
        value = APIRequestFactory().get("/api/v1/logistics/current")
        force_authenticate(value, user=actor)
        return value

    with (
        patch("maru.logistics.api._preauthorize_self_history", return_value=actor),
        patch("maru.logistics.api.list_self_offers", return_value=()) as offers,
    ):
        response = MyEquipmentOfferCollectionView.as_view()(
            request(), organization_id=organization_id, edition_id=edition_id
        )
    assert response.status_code == 200
    assert response.data == []
    offers.assert_called_once()

    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch(
            "maru.logistics.api.list_logistics_workspace",
            return_value=_workspace(manifest=manifest),
        ),
    ):
        workspace = LogisticsWorkspaceView.as_view()(
            request(), organization_id=organization_id, edition_id=edition_id
        )
        manifests = LogisticsManifestCollectionView.as_view()(
            request(), organization_id=organization_id, edition_id=edition_id
        )
    assert workspace.status_code == 200
    assert workspace.data["choices"]["labels"] == ()
    assert manifests.data[0]["id"] == manifest.id

    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api.manifest_for_workspace", return_value=manifest),
    ):
        detail = LogisticsManifestDetailView.as_view()(
            request(),
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest.id,
        )
    assert detail.data["manifest_number"] == "IN-API-1"

    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch(
            "maru.logistics.api.stage_tech_receiving_manifests",
            return_value=(manifest,),
        ),
    ):
        stage = StageTechReceivingView.as_view()(
            request(), organization_id=organization_id, edition_id=edition_id
        )
    assert stage.data[0]["id"] == manifest.id

    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api.list_logistics_activity", return_value=(activity,)),
    ):
        activity_response = LogisticsActivityView.as_view()(
            request(), organization_id=organization_id, edition_id=edition_id
        )
    assert activity_response.data[0]["event_type"] == "receive"

    post_request = APIRequestFactory().post(
        "/api/v1/logistics/contact",
        data={
            "purpose": "pickup",
            "access_purpose": "pickup_coordination",
        },
        format="json",
    )
    force_authenticate(post_request, user=actor)
    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch(
            "maru.logistics.api.read_restricted_logistics_contact",
            return_value=contact,
        ) as restricted_read,
    ):
        contact_response = RestrictedLogisticsContactView.as_view()(
            post_request,
            organization_id=organization_id,
            edition_id=edition_id,
            address_id=contact.address_id,
        )
    assert contact_response.data["contact_email"] == "recipient@example.test"
    assert restricted_read.call_args.kwargs["access_purpose"] == "pickup_coordination"


def test_offer_and_review_command_adapters_preserve_closed_inputs() -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    offer_id = uuid4()
    idempotency_key = uuid4()
    request = APIRequestFactory().post(
        "/api/v1/logistics/command", data={}, format="json"
    )
    force_authenticate(request, user=actor)
    offer_values: dict[str, object] = {
        "title": "Lighting desk offer",
        "description": "One synthetic desk.",
        "pickup_label": "Synthetic warehouse",
        "pickup_recipient_name": "Synthetic Recipient",
        "pickup_postal_address": "Synthetic address",
        "pickup_access_instructions": "Call on arrival.",
        "pickup_retention_until": datetime(2026, 8, 20, tzinfo=UTC),
        "available_from": datetime(2026, 8, 10, tzinfo=UTC),
        "available_until": datetime(2026, 8, 12, tzinfo=UTC),
        "requested_return_at": datetime(2026, 8, 13, tzinfo=UTC),
        "items": [
            {
                "kind": "serialized",
                "name": "Lighting desk",
                "description": "Synthetic equipment",
                "quantity": 1,
                "manufacturer": "Example",
                "model_name": "LX-1",
                "serial_number": "SYNTHETIC-1",
                "condition": "intact",
                "value_class": "high",
                "ownership_statement": "Owned by the offerer.",
            }
        ],
        "reason": "Offer equipment for the edition.",
    }
    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api._validated", return_value=offer_values),
        patch("maru.logistics.api._idempotency_key", return_value=idempotency_key),
        patch("maru.logistics.api._correlation_id", return_value=uuid4()),
        patch(
            "maru.logistics.api.submit_equipment_offer", return_value=_result()
        ) as submit,
    ):
        response = MyEquipmentOfferCollectionView.as_view()(
            request, organization_id=organization_id, edition_id=edition_id
        )
    assert response.status_code == 201
    assert submit.call_args.kwargs["items"][0].serial_number == "SYNTHETIC-1"

    versioned = {"expected_version": 2, "reason": "Withdraw the pending offer."}
    request = APIRequestFactory().post(
        "/api/v1/logistics/command", data={}, format="json"
    )
    force_authenticate(request, user=actor)
    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api._validated", return_value=versioned),
        patch("maru.logistics.api._idempotency_key", return_value=idempotency_key),
        patch("maru.logistics.api._correlation_id", return_value=uuid4()),
        patch(
            "maru.logistics.api.withdraw_equipment_offer", return_value=_result()
        ) as withdraw,
    ):
        response = MyEquipmentOfferWithdrawView.as_view()(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            offer_id=offer_id,
        )
    assert response.status_code == 200
    assert withdraw.call_args.kwargs["expected_version"] == 2

    review_values = {
        "expected_version": 3,
        "outcome": "accepted",
        "responsible_department_id": uuid4(),
        "reason": "Accept the governed offer.",
    }
    request = APIRequestFactory().post(
        "/api/v1/logistics/command", data={}, format="json"
    )
    force_authenticate(request, user=actor)
    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api._validated", return_value=review_values),
        patch("maru.logistics.api._idempotency_key", return_value=idempotency_key),
        patch("maru.logistics.api._correlation_id", return_value=uuid4()),
        patch(
            "maru.logistics.api.review_equipment_offer", return_value=_result()
        ) as review,
    ):
        response = EquipmentOfferReviewView.as_view()(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            offer_id=offer_id,
        )
    assert response.status_code == 200
    assert review.call_args.kwargs["outcome"] == "accepted"


def test_movement_manifest_and_offline_adapters_build_typed_commands() -> None:
    actor = _actor()
    organization_id = uuid4()
    edition_id = uuid4()
    manifest_id = uuid4()
    subject_id = uuid4()
    source_node_id = uuid4()
    destination_node_id = uuid4()
    idempotency_key = uuid4()

    def request() -> object:
        value = APIRequestFactory().post(
            "/api/v1/logistics/command", data={}, format="json"
        )
        force_authenticate(value, user=actor)
        return value

    movement_values = {
        "movement": {
            "event_type": "move",
            "subject": {"kind": "asset", "object_id": subject_id},
            "occurred_at": datetime(2026, 8, 9, 12, tzinfo=UTC),
            "source_node_id": source_node_id,
            "destination_node_id": destination_node_id,
            "condition_before": "intact",
            "condition_after": "intact",
            "manifest_id": manifest_id,
            "evidence_reference": "dock-scan-1",
        },
        "expected_sequence": 1,
        "reason": "Move the checked asset.",
    }
    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api._idempotency_key", return_value=idempotency_key),
        patch("maru.logistics.api._correlation_id", return_value=uuid4()),
        patch("maru.logistics.api._validated", return_value=movement_values),
        patch(
            "maru.logistics.api.record_logistics_event", return_value=_result()
        ) as move,
    ):
        response = LogisticsMovementView.as_view()(
            request(), organization_id=organization_id, edition_id=edition_id
        )
    assert response.status_code == 201
    assert move.call_args.kwargs["movement"].subject.object_id == subject_id

    manifest_values = {
        "responsible_department_id": uuid4(),
        "manifest_number": "IN-ADAPTER-1",
        "kind": "inbound",
        "title": "Adapter manifest",
        "source_node_id": source_node_id,
        "destination_node_id": destination_node_id,
        "vehicle_id": None,
        "provider_id": None,
        "loading_starts_at": None,
        "loading_ends_at": None,
        "lines": [
            {
                "subject": {"kind": "asset", "object_id": subject_id},
                "quantity": 1,
                "packed_in_node_id": None,
                "notes": "Synthetic line",
            }
        ],
        "reason": "Create the checked manifest.",
    }
    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api._idempotency_key", return_value=idempotency_key),
        patch("maru.logistics.api._correlation_id", return_value=uuid4()),
        patch("maru.logistics.api._validated", return_value=manifest_values),
        patch(
            "maru.logistics.api.create_logistics_manifest", return_value=_result()
        ) as create,
    ):
        response = LogisticsManifestCollectionView.as_view()(
            request(), organization_id=organization_id, edition_id=edition_id
        )
    assert response.status_code == 201
    assert create.call_args.kwargs["lines"][0].subject.object_id == subject_id

    state_values = {
        "expected_version": 2,
        "action": "seal",
        "reason": "Seal the checked manifest.",
    }
    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api._idempotency_key", return_value=idempotency_key),
        patch("maru.logistics.api._correlation_id", return_value=uuid4()),
        patch("maru.logistics.api._validated", return_value=state_values),
        patch(
            "maru.logistics.api.change_manifest_state", return_value=_result()
        ) as state,
    ):
        response = LogisticsManifestStateView.as_view()(
            request(),
            organization_id=organization_id,
            edition_id=edition_id,
            manifest_id=manifest_id,
        )
    assert response.status_code == 200
    assert state.call_args.kwargs["action"] == "seal"

    operation_key = uuid4()
    offline_values = {
        "device_code": "stage-scanner-1",
        "snapshot_version": 3,
        "policy_version": "offline-v1",
        "expires_at": datetime(2026, 8, 10, 12, tzinfo=UTC),
        "operations": [
            {
                "sequence": 1,
                "idempotency_key": operation_key,
                "expected_subject_sequence": 0,
                "action": "receive",
                "label_code": "asset-label-1",
                "occurred_at": datetime(2026, 8, 9, 12, tzinfo=UTC),
                "destination_label_code": "dock-label",
                "quantity": 1,
                "observed_condition": "intact",
            }
        ],
        "reason": "Reconcile the bounded offline batch.",
    }
    with (
        patch("maru.logistics.api._preauthorize", return_value=actor),
        patch("maru.logistics.api._idempotency_key", return_value=idempotency_key),
        patch("maru.logistics.api._correlation_id", return_value=uuid4()),
        patch("maru.logistics.api._validated", return_value=offline_values),
        patch(
            "maru.logistics.api.ingest_offline_scan_batch", return_value=_result()
        ) as ingest,
    ):
        response = OfflineScanBatchView.as_view()(
            request(), organization_id=organization_id, edition_id=edition_id
        )
    assert response.status_code == 201
    operation = ingest.call_args.kwargs["operations"][0]
    assert operation.idempotency_key == operation_key
    assert ingest.call_args.kwargs["source_channel"] == "offline"
