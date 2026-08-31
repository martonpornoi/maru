"""Browser Logistics route authorization, PRG, and projection adapters."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from maru.identity.models import Account
from maru.logistics import views
from maru.logistics.models import LogisticsManifest, RestrictedLogisticsAddress
from maru.logistics.queries import (
    LogisticsFormChoices,
    LogisticsWorkspaceProjection,
    ManifestLineProjection,
    ManifestProjection,
    NamedLogisticsChoice,
    PersonalOfferEditionProjection,
    RestrictedContactProjection,
    SelfOfferProjection,
)
from maru.logistics.services import (
    LogisticsAuthorizationDeniedError,
    LogisticsCommandResult,
    LogisticsResourceUnavailableError,
    LogisticsStateConflictError,
)


def _actor(*, active: bool = True) -> Account:
    return Account(
        id=uuid4(),
        email="logistics-browser@example.test",
        is_active=active,
        account_kind=Account.Kind.PERSON,
    )


def _request(method: str = "get", data: dict[str, object] | None = None):
    factory = RequestFactory()
    request = getattr(factory, method)("/logistics/", data=data or {})
    request.user = _actor()
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _scope() -> views._EditionRouteScope:
    return views._EditionRouteScope(organization_id=uuid4(), edition_id=uuid4())


def _edition(scope: views._EditionRouteScope):
    return SimpleNamespace(
        id=scope.edition_id,
        organization_id=scope.organization_id,
        organization=SimpleNamespace(slug="org", name="Test Org"),
        series=SimpleNamespace(slug="series", name="Test Series"),
        name="Test Edition",
        time_zone="UTC",
    )


def _choices(*, address: NamedLogisticsChoice | None = None) -> LogisticsFormChoices:
    empty: tuple[NamedLogisticsChoice, ...] = ()
    return LogisticsFormChoices(
        departments=empty,
        parties=empty,
        addresses=(address,) if address else empty,
        nodes=empty,
        packing_nodes=empty,
        vehicles=empty,
        venue_rooms=empty,
        venue_space_selections=empty,
        assets=empty,
        stock_lots=empty,
        physical_keys=empty,
        tracked_subjects=empty,
        people=empty,
        manifests=empty,
        labels=(),
    )


def _manifest(
    *,
    kind: str = LogisticsManifest.Kind.STAGE_RECEIVING,
    status: str = LogisticsManifest.Status.SEALED,
    sequence: int = 0,
) -> ManifestProjection:
    return ManifestProjection(
        id=uuid4(),
        manifest_number="STAGE-1",
        kind=kind,
        title="Stage receiving",
        status=status,
        responsible_department_id=uuid4(),
        source_node_id=None,
        source_name="",
        destination_node_id=uuid4(),
        destination_name="Stage",
        vehicle_id=None,
        vehicle_name="",
        loading_starts_at=None,
        loading_ends_at=None,
        box_count=0,
        line_count=1,
        aggregate_version=2,
        lines=(
            ManifestLineProjection(
                id=uuid4(),
                subject_kind="asset",
                subject_id=uuid4(),
                label_snapshot="Lighting desk",
                quantity=1,
                packed_in_node_id=None,
                packed_in_label="",
                notes="",
                current_sequence=sequence,
                current_state="unreceived" if sequence == 0 else "stored",
            ),
        ),
    )


def _workspace(
    *, manifest: ManifestProjection | None = None
) -> LogisticsWorkspaceProjection:
    return LogisticsWorkspaceProjection(
        offers=(),
        manifests=(manifest,) if manifest else (),
        current_states=(),
        due_returns=(),
        discrepancies=(),
        choices=_choices(),
    )


def _self_offer() -> SelfOfferProjection:
    now = timezone.now()
    return SelfOfferProjection(
        id=uuid4(),
        title="Cables",
        description="A personal equipment offer.",
        available_from=now + timedelta(days=1),
        available_until=now + timedelta(days=2),
        requested_return_at=now + timedelta(days=3),
        status="pending",
        review_reason="",
        aggregate_version=1,
        pickup_label="Workshop",
        pickup_recipient_name="Offer owner",
        pickup_postal_address="Example address",
        pickup_access_instructions="Call on arrival",
        pickup_retention_until=now + timedelta(days=3),
        items=(),
    )


def test_actor_and_route_helpers_fail_closed_without_disclosing_scope() -> None:
    anonymous_request = _request()
    anonymous_request.user = SimpleNamespace(is_active=True)
    with pytest.raises(PermissionDenied):
        views._actor(anonymous_request)

    inactive_request = _request()
    inactive_request.user = _actor(active=False)
    with pytest.raises(PermissionDenied):
        views._actor(inactive_request)

    with patch("maru.logistics.views.EventEdition.objects.filter") as filtered:
        query = filtered.return_value.order_by.return_value.values.return_value
        query.first.return_value = None
        with pytest.raises(LogisticsAuthorizationDeniedError):
            views._edition_route_scope(
                organization_slug="hidden",
                series_slug="hidden",
                edition_slug="hidden",
            )


def test_manifest_helpers_enable_only_exact_receivable_lines() -> None:
    manifest = _manifest(sequence=0)
    rows = views._manifest_receipt_rows(
        manifest=manifest,
        zone_name="UTC",
        can_manage=True,
    )
    assert rows[0]["receipt_form"] is not None

    for blocked in (
        _manifest(sequence=1),
        _manifest(kind=LogisticsManifest.Kind.OUTBOUND),
        _manifest(status=LogisticsManifest.Status.DRAFT),
    ):
        assert (
            views._manifest_receipt_rows(
                manifest=blocked,
                zone_name="UTC",
                can_manage=True,
            )[0]["receipt_form"]
            is None
        )
    assert (
        views._manifest_receipt_rows(
            manifest=manifest,
            zone_name="UTC",
            can_manage=False,
        )[0]["receipt_form"]
        is None
    )

    with patch(
        "maru.logistics.views.authorize_logistics_api_scope",
        side_effect=LogisticsAuthorizationDeniedError,
    ):
        assert not views._can_manage_manifest(
            actor=_actor(),
            edition=_edition(_scope()),
            manifest_id=manifest.id,
        )


def test_staff_action_preauthorization_binds_capabilities_and_route_objects() -> None:
    actor = _actor()
    scope = _scope()
    object_id = uuid4()
    calls: list[dict[str, object]] = []

    def authorize(**kwargs) -> None:
        calls.append(kwargs)

    with patch(
        "maru.logistics.views.authorize_logistics_api_scope", side_effect=authorize
    ):
        views._preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action="offer-review",
            object_id=object_id,
        )
        views._preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action="manifest-state",
            object_id=object_id,
        )
        views._preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action="manifest-line-add",
            object_id=object_id,
        )
        views._preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action="manifest-create",
            object_id=None,
        )
        views._preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action="offline-reconcile",
            object_id=None,
        )
    assert [call["capability_code"] for call in calls] == [
        views.OFFER_REVIEW_CAPABILITY,
        views.MANIFEST_MANAGE_CAPABILITY,
        views.MANIFEST_MANAGE_CAPABILITY,
        views.OPERATIONS_MANAGE_CAPABILITY,
        views.OFFLINE_RECONCILE_CAPABILITY,
    ]
    assert calls[0]["offer_id"] == object_id
    assert calls[1]["manifest_id"] == object_id

    with pytest.raises(LogisticsAuthorizationDeniedError):
        views._preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action="party-create",
            object_id=object_id,
        )
    with pytest.raises(LogisticsAuthorizationDeniedError):
        views._preauthorize_staff_action(
            actor=actor,
            scope=scope,
            action="unknown",
            object_id=None,
        )


def test_catalog_preauthorization_falls_back_only_to_organization_scope() -> None:
    calls: list[dict[str, object]] = []

    def authorize(**kwargs) -> None:
        calls.append(kwargs)
        if kwargs.get("edition_id") is not None:
            raise LogisticsAuthorizationDeniedError

    with patch(
        "maru.logistics.views.authorize_logistics_api_scope", side_effect=authorize
    ):
        views._preauthorize_staff_action(
            actor=_actor(),
            scope=_scope(),
            action="node-create",
            object_id=None,
        )
    assert len(calls) == 2
    assert "edition_id" in calls[0]
    assert "edition_id" not in calls[1]
    assert {call["capability_code"] for call in calls} == {
        views.CATALOG_MANAGE_CAPABILITY
    }


def test_workspace_authorizes_before_query_or_query_parameter_parsing() -> None:
    scope = _scope()
    edition = _edition(scope)
    order: list[str] = []

    def authorize(**_kwargs) -> None:
        order.append("authorize")

    def query(**_kwargs):
        order.append("query")
        return _workspace()

    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch(
            "maru.logistics.views.authorize_logistics_api_scope", side_effect=authorize
        ),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch("maru.logistics.views.list_logistics_workspace", side_effect=query),
        patch("maru.logistics.views.staff_command_forms", return_value=()),
        patch("maru.logistics.views.offer_review_forms", return_value=()),
        patch("maru.logistics.views.manifest_state_forms", return_value=()),
        patch("maru.logistics.views.manifest_line_forms", return_value=()),
        patch("maru.logistics.views._restricted_contact_rows", return_value=()),
        patch("maru.logistics.views._page_context", return_value={}),
        patch("maru.logistics.views._edition_access_spec", return_value=object()),
    ):
        response = views.logistics_workspace(_request(), "org", "series", "edition")
    assert response.status_code == 200
    assert response.context_data["workspace"] == {
        "offers": (),
        "manifests": (),
        "current_states": (),
        "due_returns": (),
        "discrepancies": (),
        "choices": response.context_data["workspace"]["choices"],
    }
    assert order == ["authorize", "query"]

    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch(
            "maru.logistics.views.authorize_logistics_api_scope", side_effect=authorize
        ),
        patch("maru.logistics.views.list_logistics_workspace") as hidden_query,
    ):
        response = views.logistics_workspace(
            _request(data={"unexpected": "value"}), "org", "series", "edition"
        )
    assert response.status_code == 400
    hidden_query.assert_not_called()


def test_manifest_and_stage_pages_project_only_preauthorized_rows() -> None:
    scope = _scope()
    edition = _edition(scope)
    manifest = _manifest()
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch("maru.logistics.views._page_context", return_value={}),
        patch("maru.logistics.views._manifest_access_spec", return_value=object()),
        patch("maru.logistics.views._can_manage_manifest", return_value=True),
        patch("maru.logistics.views._authorize_manifest_page") as authorize_manifest,
        patch("maru.logistics.views.manifest_for_workspace", return_value=manifest),
    ):
        detail = views.logistics_manifest_detail(
            _request(), "org", "series", "edition", manifest.id
        )
    assert detail.status_code == 200
    assert detail.context_data["receipt_rows"][0]["receipt_form"] is not None
    authorize_manifest.assert_called_once()

    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch("maru.logistics.views._page_context", return_value={}),
        patch("maru.logistics.views._edition_access_spec", return_value=object()),
        patch("maru.logistics.views._can_manage_manifest", return_value=True),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch(
            "maru.logistics.views.stage_tech_receiving_manifests",
            return_value=(manifest,),
        ),
    ):
        stage = views.stage_tech_receiving_page(_request(), "org", "series", "edition")
    assert stage.status_code == 200
    assert stage.context_data["manifests"][0]["manifest"]["id"] == manifest.id


class _SyntheticForm:
    def __init__(self, cleaned_data: dict[str, object], *, valid: bool = True) -> None:
        self.cleaned_data = cleaned_data
        self._valid = valid
        self.errors: list[tuple[object, str]] = []

    def is_valid(self) -> bool:
        return self._valid

    def add_error(self, field: object, error: str) -> None:
        self.errors.append((field, error))


def test_staff_command_checks_route_identity_then_executes_browser_command() -> None:
    scope = _scope()
    edition = _edition(scope)
    object_id = uuid4()
    form = _SyntheticForm({"manifest_id": object_id})
    definition = SimpleNamespace(
        form_class=lambda *_args, **_kwargs: form,
        title="Change manifest state",
    )
    redirect_response = HttpResponse(status=303)
    with (
        patch.dict(
            views.STAFF_COMMAND_BY_ACTION,
            {"manifest-state": definition},
            clear=True,
        ),
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views._preauthorize_staff_action") as preauthorize,
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.list_logistics_workspace", return_value=_workspace()
        ),
        patch("maru.logistics.views.configure_staff_form_choices", return_value=form),
        patch(
            "maru.logistics.views.execute_staff_command",
            return_value=LogisticsCommandResult(
                object_id=object_id,
                receipt_id=uuid4(),
                resulting_version=2,
                replayed=False,
            ),
        ) as execute,
        patch("maru.logistics.views.redirect", return_value=redirect_response),
    ):
        response = views.logistics_staff_command(
            _request("post"),
            "org",
            "series",
            "edition",
            "manifest-state",
            object_id,
        )
    assert response.status_code == 303
    preauthorize.assert_called_once()
    execute.assert_called_once()
    assert execute.call_args.kwargs["action"] == "manifest-state"
    assert execute.call_args.kwargs["data"] == {"manifest_id": object_id}

    form.cleaned_data["manifest_id"] = uuid4()
    with (
        patch.dict(
            views.STAFF_COMMAND_BY_ACTION,
            {"manifest-state": definition},
            clear=True,
        ),
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views._preauthorize_staff_action"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.list_logistics_workspace", return_value=_workspace()
        ),
        patch("maru.logistics.views.configure_staff_form_choices", return_value=form),
        patch("maru.logistics.views.execute_staff_command") as hidden_execute,
        patch("maru.logistics.views.redirect", return_value=redirect_response),
    ):
        views.logistics_staff_command(
            _request("post"),
            "org",
            "series",
            "edition",
            "manifest-state",
            object_id,
        )
    hidden_execute.assert_not_called()


@pytest.mark.parametrize(
    ("valid", "command_error"),
    [
        (False, None),
        (True, LogisticsStateConflictError()),
        (True, ValidationError("invalid")),
    ],
)
def test_staff_command_returns_to_workspace_on_closed_failures(
    valid: bool, command_error: Exception | None
) -> None:
    scope = _scope()
    edition = _edition(scope)
    form = _SyntheticForm({}, valid=valid)
    definition = SimpleNamespace(
        form_class=lambda *_args, **_kwargs: form, title="Event"
    )
    with (
        patch.dict(
            views.STAFF_COMMAND_BY_ACTION,
            {"event-record": definition},
            clear=True,
        ),
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views._preauthorize_staff_action"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.list_logistics_workspace", return_value=_workspace()
        ),
        patch("maru.logistics.views.configure_staff_form_choices", return_value=form),
        patch(
            "maru.logistics.views.execute_staff_command",
            side_effect=command_error,
        ) as execute,
        patch(
            "maru.logistics.views.redirect",
            return_value=HttpResponse(status=303),
        ),
    ):
        response = views.logistics_staff_command(
            _request("post"), "org", "series", "edition", "event-record"
        )
    assert response.status_code == 303
    assert execute.called is valid


def test_manifest_receipt_preauthorizes_exact_line_and_records_valid_form() -> None:
    scope = _scope()
    edition = _edition(scope)
    manifest_id = uuid4()
    line_id = uuid4()
    occurred_at = timezone.now()
    data = {
        "expected_sequence": 0,
        "occurred_at": occurred_at,
        "condition_after": "Received as described",
        "reason": "Receive exact line",
        "idempotency_key": uuid4(),
    }
    form = _SyntheticForm(data)
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope") as authorize,
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch("maru.logistics.views.ManifestReceiptForm", return_value=form),
        patch(
            "maru.logistics.views.record_manifest_receipt",
            return_value=LogisticsCommandResult(
                object_id=manifest_id,
                receipt_id=uuid4(),
                resulting_version=1,
                replayed=False,
            ),
        ) as record,
        patch(
            "maru.logistics.views.redirect",
            return_value=HttpResponse(status=303),
        ),
    ):
        response = views.logistics_manifest_receipt(
            _request("post"),
            "org",
            "series",
            "edition",
            manifest_id,
            line_id,
        )
    assert response.status_code == 303
    assert authorize.call_args.kwargs["manifest_line_id"] == line_id
    assert authorize.call_args.kwargs["manifest_id"] == manifest_id
    assert record.call_args.kwargs["source_channel"] == "browser"


def test_restricted_contact_request_uses_opaque_single_use_prg_token() -> None:
    scope = _scope()
    edition = _edition(scope)
    address_id = uuid4()
    access_request_id = uuid4()
    request = _request(
        "post",
        {
            "address_id": str(address_id),
            "purpose": RestrictedLogisticsAddress.Purpose.PICKUP,
            "access_purpose": "pickup_coordination",
        },
    )
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope") as authorize,
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.prepare_restricted_contact_request",
            return_value=access_request_id,
        ) as prepare,
        patch(
            "maru.logistics.views.reverse",
            return_value="/logistics/restricted-contact/result/",
        ),
    ):
        response = views.restricted_contact_request(
            request, "org", "series", "edition", address_id
        )
    assert response.status_code == 302
    query = parse_qs(urlparse(response["Location"]).query)
    assert set(query) == {"token"}
    assert signing.loads(
        query["token"][0], salt=views.CONTACT_SIGNING_NAMESPACE
    ) == str(access_request_id)
    assert str(address_id) not in response["Location"]
    assert authorize.call_args.kwargs["address_id"] == address_id
    assert prepare.call_args.kwargs["source_channel"] == "browser"


def test_restricted_contact_result_binds_token_to_actor_and_sets_no_store_headers() -> (
    None
):
    scope = _scope()
    edition = _edition(scope)
    access_request_id = uuid4()
    address_id = uuid4()
    request = _request(
        data={
            "token": signing.dumps(
                str(access_request_id),
                salt=views.CONTACT_SIGNING_NAMESPACE,
                compress=False,
            )
        }
    )
    access_request = SimpleNamespace(
        id=access_request_id,
        target_id=address_id,
        operation="logistics.restricted_contact.request.pickup",
        safe_metadata={"access_purpose": "pickup_coordination"},
        correlation_id=uuid4(),
    )
    audit_query = MagicMock()
    audit_query.only.return_value.first.return_value = access_request
    contact = RestrictedContactProjection(
        address_id=address_id,
        purpose="pickup",
        label="Workshop",
        recipient_name="Provider",
        contact_email="private@example.test",
        contact_phone="+3612345678",
        postal_address="Example address",
        access_instructions="Call on arrival",
        retention_until=timezone.now() + timedelta(days=1),
        subject_account_id=None,
        party_id=uuid4(),
    )
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.AuditEvent.objects.filter", return_value=audit_query
        ),
        patch(
            "maru.logistics.views.read_restricted_logistics_contact",
            return_value=contact,
        ) as read,
        patch("maru.logistics.views._page_context", return_value={}),
        patch("maru.logistics.views._edition_access_spec", return_value=object()),
    ):
        response = views.restricted_contact_result(request, "org", "series", "edition")
    assert response.status_code == 200
    assert response.context_data["contact"]["contact_email"] == "private@example.test"
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert "max-age=0" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "no-referrer"
    assert read.call_args.kwargs["access_request_id"] == access_request_id
    assert read.call_args.kwargs["address_id"] == address_id

    malformed = _request(data={"token": "not-signed"})
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        pytest.raises(Http404),
    ):
        views.restricted_contact_result(malformed, "org", "series", "edition")


def test_personal_offer_index_and_edition_page_project_only_own_records() -> None:
    request = _request()
    edition_projection = PersonalOfferEditionProjection(
        organization_slug="org",
        organization_name="Test Org",
        series_slug="series",
        series_name="Test Series",
        edition_slug="edition",
        edition_name="Test Edition",
        adoption_profile_code="full_convention",
        adoption_profile_version=1,
        edition_starts_on=date(2027, 1, 1),
        offer_count=1,
        pending_offer_count=1,
        can_submit=True,
    )
    with (
        patch(
            "maru.logistics.views.authorize_personal_logistics_index_scope"
        ) as authorize,
        patch(
            "maru.logistics.views.my_equipment_offer_editions",
            return_value=(edition_projection,),
        ),
        patch("maru.logistics.views.admin.site.each_context", return_value={}),
        patch("maru.logistics.views._personal_access_spec", return_value=object()),
    ):
        response = views.my_logistics_offers_index(request)
    assert response.status_code == 200
    assert response.context_data["offer_editions"][0]["offer_count"] == 1
    assert response.context_data["maru_personal_profile_pairs"] == (
        ("full_convention", 1),
    )
    authorize.assert_called_once_with(actor=request.user)

    scope = _scope()
    edition = _edition(scope)
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_self_offer_history_api_scope") as history,
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch("maru.logistics.views.can_submit_equipment_offer", return_value=True),
        patch("maru.logistics.views.list_self_offers", return_value=(_self_offer(),)),
        patch("maru.logistics.views._page_context", return_value={}),
    ):
        response = views.my_logistics_offers(_request(), "org", "series", "edition")
    assert response.status_code == 200
    assert response.context_data["can_submit"] is True
    assert response.context_data["offers"][0]["title"] == "Cables"
    history.assert_called_once()


def test_personal_offer_post_maps_closed_form_data_to_one_item() -> None:
    scope = _scope()
    edition = _edition(scope)
    now = timezone.now()
    data = {
        "title": "Cables",
        "description": "Personal cables",
        "pickup_label": "Workshop",
        "pickup_recipient_name": "Offer owner",
        "pickup_postal_address": "Example address",
        "pickup_access_instructions": "Call",
        "pickup_retention_until": now + timedelta(days=4),
        "available_from": now + timedelta(days=1),
        "available_until": now + timedelta(days=2),
        "requested_return_at": now + timedelta(days=3),
        "item_kind": "bulk",
        "item_name": "XLR cable",
        "item_description": "Balanced audio cable",
        "item_quantity": 4,
        "manufacturer": "",
        "model_name": "",
        "serial_number": "",
        "condition": "working",
        "value_class": "standard",
        "ownership_statement": "I own these cables",
        "reason": "Offer equipment",
        "idempotency_key": uuid4(),
    }
    form = _SyntheticForm(data)
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_self_offer_history_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch("maru.logistics.views.can_submit_equipment_offer", return_value=True),
        patch("maru.logistics.views.EquipmentOfferForm", return_value=form),
        patch(
            "maru.logistics.views.submit_equipment_offer",
            return_value=LogisticsCommandResult(
                object_id=uuid4(),
                receipt_id=uuid4(),
                resulting_version=1,
                replayed=False,
            ),
        ) as submit,
        patch(
            "maru.logistics.views.redirect",
            return_value=HttpResponse(status=303),
        ) as redirect_to,
    ):
        response = views.my_logistics_offers(
            _request("post"), "org", "series", "edition"
        )
    assert response.status_code == 303
    item = submit.call_args.kwargs["items"][0]
    assert item.name == "XLR cable"
    assert item.quantity == 4
    assert submit.call_args.kwargs["source_channel"] == "browser"
    redirect_to.assert_called_once_with(
        "my-logistics-offers",
        "org",
        "series",
        "edition",
    )


def test_contact_and_manifest_authorization_errors_are_non_disclosing() -> None:
    scope = _scope()
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch(
            "maru.logistics.views.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        pytest.raises(PermissionDenied, match="restricted contact is unavailable"),
    ):
        views.restricted_contact_request(
            _request("post"), "org", "series", "edition", uuid4()
        )

    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch(
            "maru.logistics.views._authorize_manifest_page",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        pytest.raises(PermissionDenied, match="manifest is unavailable"),
    ):
        views.logistics_manifest_detail(_request(), "org", "series", "edition", uuid4())


def test_restricted_contact_request_handles_expired_target_without_echoing_data() -> (
    None
):
    scope = _scope()
    edition = _edition(scope)
    address_id = uuid4()
    request = _request(
        "post",
        {
            "address_id": str(address_id),
            "purpose": RestrictedLogisticsAddress.Purpose.RETURN,
            "access_purpose": "return_coordination",
        },
    )
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.prepare_restricted_contact_request",
            side_effect=LogisticsResourceUnavailableError,
        ),
        patch("maru.logistics.views.redirect", return_value=HttpResponse(status=303)),
    ):
        response = views.restricted_contact_request(
            request, "org", "series", "edition", address_id
        )
    assert response.status_code == 303


def test_route_context_and_access_helpers_preserve_exact_scope() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    route_query = MagicMock()
    route_query.order_by.return_value.values.return_value.first.return_value = {
        "organization_id": organization_id,
        "id": edition_id,
    }
    with patch(
        "maru.logistics.views.EventEdition.objects.filter",
        return_value=route_query,
    ):
        scope = views._edition_route_scope(
            organization_slug="org",
            series_slug="series",
            edition_slug="edition",
        )
    assert scope == views._EditionRouteScope(organization_id, edition_id)

    edition = _edition(scope)
    edition_query = MagicMock()
    edition_query.filter.return_value.first.return_value = edition
    with patch(
        "maru.logistics.views.EventEdition.objects.select_related",
        return_value=edition_query,
    ):
        assert (
            views._edition_route(
                scope=scope,
                organization_slug="org",
                series_slug="series",
                edition_slug="edition",
            )
            is edition
        )
    edition_query.filter.return_value.first.return_value = None
    with (
        patch(
            "maru.logistics.views.EventEdition.objects.select_related",
            return_value=edition_query,
        ),
        pytest.raises(LogisticsAuthorizationDeniedError),
    ):
        views._edition_route(
            scope=scope,
            organization_slug="org",
            series_slug="series",
            edition_slug="edition",
        )

    request = _request()
    personal_access = object()
    with (
        patch("maru.logistics.views.admin.site.each_context", return_value={}),
        patch(
            "maru.logistics.views._personal_access_spec",
            return_value=personal_access,
        ),
    ):
        context = views._page_context(request, edition, personal=True)
    assert context["has_permission"] is True
    assert context["maru_personal_surface"] is True
    assert context["maru_page_access_spec"] is personal_access

    explicit_access = object()
    with patch("maru.logistics.views.admin.site.each_context", return_value={}):
        context = views._page_context(
            request,
            edition,
            personal=False,
            access_spec=explicit_access,
        )
    assert context["maru_page_access_spec"] is explicit_access

    with (
        patch("maru.logistics.views.resolve_edition_target", return_value=object()),
        patch(
            "maru.logistics.views.scoped_page_access",
            return_value=explicit_access,
        ) as scoped,
    ):
        assert (
            views._edition_access_spec(
                edition=edition,
                scope_label="Exact edition",
                intents=(),
            )
            is explicit_access
        )
    assert scoped.call_args.kwargs["scope_label"] == "Exact edition"

    with (
        patch(
            "maru.logistics.views.resolve_logistics_manifest_target",
            return_value=object(),
        ),
        patch(
            "maru.logistics.views.scoped_page_access",
            return_value=explicit_access,
        ),
    ):
        assert (
            views._manifest_access_spec(
                edition=edition,
                manifest_id=uuid4(),
                title="Exact manifest",
            )
            is explicit_access
        )


def test_manifest_and_staff_helper_authorization_fallbacks_are_closed() -> None:
    actor = _actor()
    scope = _scope()
    manifest_id = uuid4()
    with patch("maru.logistics.views.authorize_logistics_api_scope") as authorize:
        views._authorize_manifest_page(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            manifest_id=manifest_id,
        )
        assert views._can_manage_manifest(
            actor=actor,
            edition=_edition(scope),
            manifest_id=manifest_id,
        )
    assert authorize.call_count == 2

    with patch(
        "maru.logistics.views.authorize_logistics_api_scope",
        side_effect=(LogisticsAuthorizationDeniedError(), None),
    ) as authorize:
        views._authorize_manifest_page(
            actor=actor,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            manifest_id=manifest_id,
        )
    assert [call.kwargs["capability_code"] for call in authorize.call_args_list] == [
        views.MANIFEST_VIEW_CAPABILITY,
        views.MANIFEST_MANAGE_CAPABILITY,
    ]

    with patch("maru.logistics.views._preauthorize_staff_action"):
        assert views._can_run_staff_action(
            actor=actor,
            scope=scope,
            action="event-record",
        )
    with patch(
        "maru.logistics.views._preauthorize_staff_action",
        side_effect=LogisticsAuthorizationDeniedError,
    ):
        assert not views._can_run_staff_action(
            actor=actor,
            scope=scope,
            action="event-record",
        )

    fake_form = SimpleNamespace(fields={"address_id": object()})
    with (
        patch("maru.logistics.views.RestrictedContactReadForm", return_value=fake_form),
        pytest.raises(TypeError, match="closed choice"),
    ):
        views._restricted_contact_form(
            address_id=uuid4(),
            address_label="Hidden contact",
            zone_name="UTC",
        )


def test_restricted_contact_rows_omit_each_unauthorized_address() -> None:
    scope = _scope()
    edition = _edition(scope)
    allowed = NamedLogisticsChoice(uuid4(), "Allowed contact")
    denied = NamedLogisticsChoice(uuid4(), "Denied contact")
    with (
        patch(
            "maru.logistics.views.authorize_logistics_api_scope",
            side_effect=(None, LogisticsAuthorizationDeniedError()),
        ),
        patch(
            "maru.logistics.views._restricted_contact_form",
            return_value=object(),
        ),
    ):
        rows = views._restricted_contact_rows(
            actor=_actor(),
            edition=edition,
            addresses=(allowed, denied),
        )
    assert [row["address_id"] for row in rows] == [allowed.value]


def test_workspace_manifest_and_stage_pages_map_closed_failures() -> None:
    scope = _scope()
    edition = _edition(scope)
    manifest_id = uuid4()
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch(
            "maru.logistics.views.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        pytest.raises(PermissionDenied, match="workspace is unavailable"),
    ):
        views.logistics_workspace(_request(), "org", "series", "edition")

    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.list_logistics_workspace",
            side_effect=DatabaseError,
        ),
    ):
        assert (
            views.logistics_workspace(
                _request(), "org", "series", "edition"
            ).status_code
            == 503
        )

    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views._authorize_manifest_page"),
    ):
        assert (
            views.logistics_manifest_detail(
                _request(data={"unexpected": "1"}),
                "org",
                "series",
                "edition",
                manifest_id,
            ).status_code
            == 400
        )

    for error, status in (
        (LogisticsResourceUnavailableError(), 404),
        (DatabaseError(), 503),
    ):
        with (
            patch("maru.logistics.views._edition_route_scope", return_value=scope),
            patch("maru.logistics.views._authorize_manifest_page"),
            patch("maru.logistics.views._edition_route", return_value=edition),
            patch(
                "maru.logistics.views.manifest_for_workspace",
                side_effect=error,
            ),
        ):
            if status == 404:
                with pytest.raises(Http404):
                    views.logistics_manifest_detail(
                        _request(), "org", "series", "edition", manifest_id
                    )
            else:
                response = views.logistics_manifest_detail(
                    _request(), "org", "series", "edition", manifest_id
                )
                assert response.status_code == status

    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
    ):
        assert (
            views.stage_tech_receiving_page(
                _request(data={"unexpected": "1"}),
                "org",
                "series",
                "edition",
            ).status_code
            == 400
        )
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.stage_tech_receiving_manifests",
            side_effect=DatabaseError,
        ),
    ):
        assert (
            views.stage_tech_receiving_page(
                _request(), "org", "series", "edition"
            ).status_code
            == 503
        )


def _command_route_context(form: _SyntheticForm, *, action: str):
    scope = _scope()
    edition = _edition(scope)
    definition = SimpleNamespace(
        form_class=lambda *_args, **_kwargs: form,
        title="Synthetic command",
    )
    return scope, edition, definition, action


@pytest.mark.parametrize(
    "error",
    [
        LogisticsAuthorizationDeniedError(),
        DatabaseError(),
    ],
)
def test_staff_command_maps_late_authorization_and_database_failures(
    error: Exception,
) -> None:
    form = _SyntheticForm({})
    scope, edition, definition, action = _command_route_context(
        form, action="event-record"
    )
    with (
        patch.dict(views.STAFF_COMMAND_BY_ACTION, {action: definition}, clear=True),
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views._preauthorize_staff_action"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.list_logistics_workspace", return_value=_workspace()
        ),
        patch("maru.logistics.views.configure_staff_form_choices", return_value=form),
        patch("maru.logistics.views.execute_staff_command", side_effect=error),
        patch("maru.logistics.views.redirect", return_value=HttpResponse(status=303)),
    ):
        if isinstance(error, LogisticsAuthorizationDeniedError):
            with pytest.raises(PermissionDenied):
                views.logistics_staff_command(
                    _request("post"), "org", "series", "edition", action
                )
        else:
            assert (
                views.logistics_staff_command(
                    _request("post"), "org", "series", "edition", action
                ).status_code
                == 303
            )


def test_contact_result_rejects_malformed_audit_and_maps_read_failures() -> None:
    scope = _scope()
    edition = _edition(scope)
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
    ):
        assert (
            views.restricted_contact_result(
                _request(data={"token": ["a", "b"]}),
                "org",
                "series",
                "edition",
            ).status_code
            == 400
        )

    non_uuid = signing.dumps(
        "not-a-uuid",
        salt=views.CONTACT_SIGNING_NAMESPACE,
        compress=False,
    )
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        pytest.raises(Http404),
    ):
        views.restricted_contact_result(
            _request(data={"token": non_uuid}), "org", "series", "edition"
        )

    request_id = uuid4()
    token = signing.dumps(
        str(request_id),
        salt=views.CONTACT_SIGNING_NAMESPACE,
        compress=False,
    )
    audit_query = MagicMock()
    audit_query.only.return_value.first.return_value = None
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.AuditEvent.objects.filter", return_value=audit_query
        ),
        pytest.raises(Http404),
    ):
        views.restricted_contact_result(
            _request(data={"token": token}), "org", "series", "edition"
        )

    audit = SimpleNamespace(
        id=request_id,
        target_id=uuid4(),
        operation="logistics.restricted_contact.request.pickup",
        safe_metadata={"access_purpose": 123},
        correlation_id=uuid4(),
    )
    audit_query.only.return_value.first.return_value = audit
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch(
            "maru.logistics.views.AuditEvent.objects.filter", return_value=audit_query
        ),
        pytest.raises(Http404),
    ):
        views.restricted_contact_result(
            _request(data={"token": token}), "org", "series", "edition"
        )

    audit.safe_metadata = {"access_purpose": "pickup_coordination"}
    for error, expected in (
        (LogisticsAuthorizationDeniedError(), PermissionDenied),
        (LogisticsResourceUnavailableError(), Http404),
        (ValueError(), Http404),
        (DatabaseError(), 503),
    ):
        with (
            patch("maru.logistics.views._edition_route_scope", return_value=scope),
            patch("maru.logistics.views.authorize_logistics_api_scope"),
            patch("maru.logistics.views._edition_route", return_value=edition),
            patch(
                "maru.logistics.views.AuditEvent.objects.filter",
                return_value=audit_query,
            ),
            patch(
                "maru.logistics.views.read_restricted_logistics_contact",
                side_effect=error,
            ),
        ):
            if isinstance(expected, type):
                with pytest.raises(expected):
                    views.restricted_contact_result(
                        _request(data={"token": token}),
                        "org",
                        "series",
                        "edition",
                    )
            else:
                response = views.restricted_contact_result(
                    _request(data={"token": token}),
                    "org",
                    "series",
                    "edition",
                )
                assert response.status_code == expected


def test_personal_offer_pages_reject_queries_and_map_dependencies() -> None:
    with patch("maru.logistics.views.authorize_personal_logistics_index_scope"):
        assert (
            views.my_logistics_offers_index(
                _request(data={"unexpected": "1"})
            ).status_code
            == 400
        )
    with (
        patch(
            "maru.logistics.views.authorize_personal_logistics_index_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        pytest.raises(PermissionDenied),
    ):
        views.my_logistics_offers_index(_request())
    with (
        patch("maru.logistics.views.authorize_personal_logistics_index_scope"),
        patch(
            "maru.logistics.views.my_equipment_offer_editions",
            side_effect=DatabaseError,
        ),
    ):
        assert views.my_logistics_offers_index(_request()).status_code == 503

    scope = _scope()
    edition = _edition(scope)
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_self_offer_history_api_scope"),
    ):
        assert (
            views.my_logistics_offers(
                _request(data={"unexpected": "1"}), "org", "series", "edition"
            ).status_code
            == 400
        )
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_self_offer_history_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch("maru.logistics.views.can_submit_equipment_offer", return_value=False),
        pytest.raises(PermissionDenied, match="New equipment offers"),
    ):
        views.my_logistics_offers(_request("post"), "org", "series", "edition")
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_self_offer_history_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=edition),
        patch("maru.logistics.views.can_submit_equipment_offer", return_value=False),
        patch("maru.logistics.views.list_self_offers", side_effect=DatabaseError),
    ):
        assert (
            views.my_logistics_offers(
                _request(), "org", "series", "edition"
            ).status_code
            == 503
        )


def test_manifest_receipt_rejects_scope_and_invalid_form_before_write() -> None:
    scope = _scope()
    manifest_id = uuid4()
    line_id = uuid4()
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch(
            "maru.logistics.views.authorize_logistics_api_scope",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        pytest.raises(PermissionDenied, match="receipt is unavailable"),
    ):
        views.logistics_manifest_receipt(
            _request("post"),
            "org",
            "series",
            "edition",
            manifest_id,
            line_id,
        )

    invalid_form = _SyntheticForm({}, valid=False)
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=_edition(scope)),
        patch("maru.logistics.views.ManifestReceiptForm", return_value=invalid_form),
        patch("maru.logistics.views.record_manifest_receipt") as hidden_record,
        patch("maru.logistics.views.redirect", return_value=HttpResponse(status=303)),
    ):
        response = views.logistics_manifest_receipt(
            _request("post"),
            "org",
            "series",
            "edition",
            manifest_id,
            line_id,
        )
    assert response.status_code == 303
    hidden_record.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        LogisticsAuthorizationDeniedError(),
        LogisticsStateConflictError(),
        ValidationError("invalid receipt"),
        DatabaseError(),
    ],
)
def test_manifest_receipt_maps_expected_late_failures(error: Exception) -> None:
    scope = _scope()
    manifest_id = uuid4()
    form = _SyntheticForm(
        {
            "expected_sequence": 0,
            "occurred_at": timezone.now(),
            "condition_after": "Received as described",
            "reason": "Receive exact line",
            "idempotency_key": uuid4(),
        }
    )
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=_edition(scope)),
        patch("maru.logistics.views.ManifestReceiptForm", return_value=form),
        patch("maru.logistics.views.record_manifest_receipt", side_effect=error),
        patch("maru.logistics.views.redirect", return_value=HttpResponse(status=303)),
    ):
        if isinstance(error, LogisticsAuthorizationDeniedError):
            with pytest.raises(PermissionDenied):
                views.logistics_manifest_receipt(
                    _request("post"),
                    "org",
                    "series",
                    "edition",
                    manifest_id,
                    uuid4(),
                )
        else:
            response = views.logistics_manifest_receipt(
                _request("post"),
                "org",
                "series",
                "edition",
                manifest_id,
                uuid4(),
            )
            assert response.status_code == 303


def test_restricted_contact_invalid_form_returns_without_preparing_access() -> None:
    scope = _scope()
    address_id = uuid4()
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=scope),
        patch("maru.logistics.views.authorize_logistics_api_scope"),
        patch("maru.logistics.views._edition_route", return_value=_edition(scope)),
        patch(
            "maru.logistics.views.prepare_restricted_contact_request"
        ) as hidden_prepare,
        patch("maru.logistics.views.redirect", return_value=HttpResponse(status=303)),
    ):
        response = views.restricted_contact_request(
            _request("post", {"address_id": str(address_id)}),
            "org",
            "series",
            "edition",
            address_id,
        )
    assert response.status_code == 303
    hidden_prepare.assert_not_called()


def test_staff_command_preauthorization_denial_is_non_disclosing() -> None:
    with (
        patch("maru.logistics.views._edition_route_scope", return_value=_scope()),
        patch(
            "maru.logistics.views._preauthorize_staff_action",
            side_effect=LogisticsAuthorizationDeniedError,
        ),
        pytest.raises(PermissionDenied, match="command is unavailable"),
    ):
        views.logistics_staff_command(
            _request("post"),
            "org",
            "series",
            "edition",
            "event-record",
        )
