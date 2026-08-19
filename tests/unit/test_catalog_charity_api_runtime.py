from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from maru.authorization.services import AuthorizationDenied
from maru.catalog.api import (
    CatalogActivateApi,
    CatalogActivityApi,
    CatalogDetailApi,
    CatalogOrderCollectionApi,
    CatalogPaymentCreateApi,
    CatalogPaymentReconcileApi,
    CatalogProductCollectionApi,
    CatalogStockAdjustApi,
    CatalogVariantCollectionApi,
)
from maru.catalog.api import _actor as catalog_actor
from maru.catalog.api import _correlation_id as catalog_correlation_id
from maru.catalog.api import (
    _execute as execute_catalog,
)
from maru.catalog.api import _idempotency_key as catalog_idempotency_key
from maru.catalog.api import _preauthorize_payment as preauthorize_catalog_payment
from maru.catalog.forms import (
    CatalogEditionLocalDateTimeField,
    CatalogProductAddForm,
    CatalogVariantAddForm,
)
from maru.catalog.models import (
    CatalogProduct,
    CatalogStockAdjustment,
    CatalogVariant,
    EditionCatalog,
)
from maru.catalog.serializers import (
    CatalogVariantAddSerializer,
)
from maru.catalog.services import CatalogActivity, CatalogCommandResult
from maru.catalog.views import _execute_staff_command, start_catalog_hosted_payment_page
from maru.charities.api import (
    CharityConflict,
    CharityMediaCollectionView,
    CharityMediaCommandView,
    CharityPartnerCollectionView,
    CharityPartnerDetailView,
    CharitySelectionCollectionView,
    CharitySelectionCommandView,
    CharitySelectionDetailView,
    PublicCharityListView,
)
from maru.charities.api import _authorize_edition as authorize_charity_edition
from maru.charities.api import (
    _authorize_selection as authorize_charity_selection,
)
from maru.charities.api import _correlation_id as charity_correlation_id
from maru.charities.api import (
    _execute as execute_charity,
)
from maru.charities.api import _idempotency_key as charity_idempotency_key
from maru.charities.forms import CharityEditionLocalDateTimeField
from maru.charities.inputs import (
    canonical_digest,
    normalized_reason,
    normalized_slug,
    normalized_source_channel,
    normalized_text,
)
from maru.charities.models import (
    CharityPartner,
    CharityPartnerMedia,
    CharitySelection,
    CharitySelectionTimelineEntry,
)
from maru.charities.serializers import CharityPartnerUpdateSerializer
from maru.charities.services import (
    CharityAuthorizationDeniedError,
    CharityCommandError,
    CharityCommandResult,
    CharityIndependentApprovalError,
    CharityPartnerProfile,
    CharityResourceUnavailableError,
    CharityRetryConflictError,
    CharityStateConflictError,
    CharityVersionConflictError,
    _media_review_command,
    _normalize_profile,
    _require_actor,
    _require_decision,
    _require_expected_version,
    _require_uuid,
    _review_charity_selection,
    add_charity_partner_media,
    publish_charity_selection,
    update_charity_partner,
)
from maru.charities.views import _execute_command
from maru.core.problems import DependencyUnavailable
from maru.identity.models import Account


def _actor() -> Account:
    return Account(
        id=uuid4(),
        email="domain-api-operator@example.test",
        is_active=True,
    )


def _request(
    method: str,
    payload: dict[str, object] | None = None,
    *,
    idempotency_key: UUID | None = None,
) -> Any:
    factory = APIRequestFactory()
    if method == "get":
        request = factory.get("/api/v1/domain")
    else:
        request_builder = getattr(factory, method)
        request = request_builder(
            "/api/v1/domain",
            data=payload or {},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(idempotency_key or uuid4()),
        )
    force_authenticate(request, user=_actor())
    return request


def _message_request() -> Any:
    request = cast(Any, APIRequestFactory().get("/admin/platform/domain"))
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


@dataclass(frozen=True)
class _CatalogMutationCase:
    view: type[APIView]
    command: str
    preauthorization: str
    payload: dict[str, object]
    route_ids: tuple[str, ...] = ()
    created: bool = False


@pytest.mark.parametrize(
    "case",
    [
        _CatalogMutationCase(
            CatalogDetailApi,
            "create_catalog",
            "_preauthorize_edition",
            {"currency": "EUR", "reason": "Open the bounded catalog."},
            created=True,
        ),
        _CatalogMutationCase(
            CatalogProductCollectionApi,
            "add_product",
            "_preauthorize_edition",
            {
                "expected_version": 1,
                "reason": "Add the convention shirt.",
                "code": "shirt",
                "kind": "merchandise",
                "name": "Convention shirt",
            },
            created=True,
        ),
        _CatalogMutationCase(
            CatalogVariantCollectionApi,
            "add_variant",
            "_preauthorize_edition",
            {
                "expected_version": 1,
                "reason": "Add a medium variant.",
                "sku": "SHIRT-M",
                "name": "Medium",
                "price_minor": 2500,
                "initial_stock": 10,
                "stock_ceiling": 10,
            },
            ("product_id",),
            created=True,
        ),
        _CatalogMutationCase(
            CatalogActivateApi,
            "activate_catalog",
            "_preauthorize_edition",
            {"expected_version": 1, "reason": "Publish the catalog."},
        ),
        _CatalogMutationCase(
            CatalogStockAdjustApi,
            "adjust_stock",
            "_preauthorize_edition",
            {
                "expected_version": 1,
                "reason": "Record the verified count.",
                "new_stock": 9,
            },
            ("variant_id",),
        ),
        _CatalogMutationCase(
            CatalogOrderCollectionApi,
            "place_order",
            "_preauthorize_self",
            {
                "expected_version": 1,
                "lines": [{"variant_id": str(uuid4()), "quantity": 2}],
            },
            created=True,
        ),
        _CatalogMutationCase(
            CatalogPaymentCreateApi,
            "create_payment_intent",
            "_preauthorize_order",
            {
                "expected_catalog_version": 1,
                "expected_order_version": 1,
                "provider": "demo",
            },
            ("order_id",),
            created=True,
        ),
        _CatalogMutationCase(
            CatalogPaymentReconcileApi,
            "reconcile_payment",
            "_preauthorize_payment",
            {
                "expected_catalog_version": 1,
                "expected_order_version": 1,
                "provider_event_id": "demo-event-1",
                "result": "succeeded",
                "reason": "Record the verified provider result.",
            },
            ("intent_id",),
        ),
    ],
)
def test_catalog_mutation_adapters_dispatch_validated_commands(
    case: _CatalogMutationCase,
) -> None:
    target_id = uuid4()
    result = CatalogCommandResult(
        target_id=target_id,
        resulting_version=2,
        replayed=False,
    )
    route_kwargs = {
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        **{name: uuid4() for name in case.route_ids},
    }

    with (
        patch(f"maru.catalog.api.{case.preauthorization}"),
        patch(f"maru.catalog.api.{case.command}", return_value=result) as command,
    ):
        response = case.view.as_view()(
            _request("post", case.payload),
            **route_kwargs,
        )

    assert response.status_code == (201 if case.created else 200)
    assert response.data == {
        "target_id": target_id,
        "resulting_version": 2,
        "replayed": False,
    }
    command.assert_called_once()


def test_catalog_query_adapters_project_current_data() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    catalog = SimpleNamespace(aggregate_version=3, currency="EUR")
    activity = CatalogActivity(
        action="catalog.activated",
        actor_label="Catalog operator",
        occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
        target_count=1,
    )

    with (
        patch("maru.catalog.api.available_products_for_actor", return_value=()),
        patch("maru.catalog.api.EditionCatalog.objects.get", return_value=catalog),
    ):
        detail = CatalogDetailApi.as_view()(
            _request("get"),
            organization_id=organization_id,
            edition_id=edition_id,
        )
    with patch("maru.catalog.api.own_orders", return_value=()):
        orders = CatalogOrderCollectionApi.as_view()(
            _request("get"),
            organization_id=organization_id,
            edition_id=edition_id,
        )
    with patch("maru.catalog.api.catalog_activity", return_value=(activity,)):
        timeline = CatalogActivityApi.as_view()(
            _request("get"),
            organization_id=organization_id,
            edition_id=edition_id,
        )

    assert detail.data == {
        "catalog_version": 3,
        "currency": "EUR",
        "products": [],
    }
    assert orders.data == {"orders": []}
    assert timeline.data["activity"][0]["action"] == "catalog.activated"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthorizationDenied("denied", reason_code="denied"), PermissionDenied),
        (ObjectDoesNotExist(), NotFound),
        (ValidationError({"field": ["invalid"]}), ApiValidationError),
        (ValidationError("invalid"), ApiValidationError),
    ],
)
def test_catalog_execute_maps_domain_failures(error: Exception, expected: type) -> None:
    def fail() -> None:
        raise error

    with pytest.raises(expected):
        execute_catalog(fail)


@dataclass(frozen=True)
class _CharityMutationCase:
    view: type[APIView]
    command: str
    payload: dict[str, object]
    route_ids: tuple[str, ...] = ()
    action: str | None = None
    created: bool = False


@pytest.mark.parametrize(
    "case",
    [
        _CharityMutationCase(
            CharityPartnerCollectionView,
            "create_charity_partner",
            {
                "slug": "river-aid",
                "legal_name": "River Aid Foundation",
                "public_name": "River Aid",
                "reason": "Add a verified charity partner.",
            },
            created=True,
        ),
        _CharityMutationCase(
            CharityPartnerDetailView,
            "update_charity_partner",
            {
                "expected_version": 1,
                "public_name": "River Aid Europe",
                "reason": "Use the current public name.",
            },
            ("partner_id",),
        ),
        _CharityMutationCase(
            CharityMediaCollectionView,
            "add_charity_partner_media",
            {
                "kind": "logo",
                "source_reference": "s3://charity/logo.webp",
                "owner_name": "River Aid Foundation",
                "license_basis": "Written permission",
                "usage_scope": "Convention charity promotion",
                "reason": "Add reviewed source evidence.",
            },
            ("partner_id",),
            created=True,
        ),
        _CharityMutationCase(
            CharityMediaCommandView,
            "approve_charity_partner_media",
            {
                "expected_version": 1,
                "public_reference": "https://cdn.example.test/river-aid.webp",
                "reason": "Approve reviewed media.",
            },
            ("partner_id", "media_id"),
            "approve",
        ),
        _CharityMutationCase(
            CharityMediaCommandView,
            "withdraw_charity_partner_media",
            {"expected_version": 1, "reason": "Withdraw obsolete media."},
            ("partner_id", "media_id"),
            "withdraw",
        ),
        _CharityMutationCase(
            CharitySelectionCollectionView,
            "propose_charity_selection",
            {
                "partner_id": str(uuid4()),
                "responsible_department_id": str(uuid4()),
                "reason": "Propose the verified partner.",
            },
            created=True,
        ),
    ],
)
def test_charity_mutation_adapters_dispatch_validated_commands(
    case: _CharityMutationCase,
) -> None:
    object_id = uuid4()
    result = CharityCommandResult(
        object_id=object_id,
        receipt_id=uuid4(),
        resulting_version=2,
        replayed=False,
    )
    route_kwargs: dict[str, object] = {"organization_id": uuid4()}
    if case.view in {CharitySelectionCollectionView, CharitySelectionCommandView}:
        route_kwargs["edition_id"] = uuid4()
    route_kwargs.update({name: uuid4() for name in case.route_ids})
    if case.action is not None:
        route_kwargs["action"] = case.action

    with ExitStack() as stack:
        stack.enter_context(
            patch("maru.charities.api._authorize_organization", return_value=_actor())
        )
        stack.enter_context(
            patch("maru.charities.api._authorize_edition", return_value=_actor())
        )
        command = stack.enter_context(
            patch(f"maru.charities.api.{case.command}", return_value=result)
        )
        response = case.view.as_view()(
            _request(
                "patch" if case.view is CharityPartnerDetailView else "post",
                case.payload,
            ),
            **route_kwargs,
        )

    assert response.status_code == (201 if case.created else 200)
    assert response.data["object_id"] == str(object_id)
    command.assert_called_once()


@pytest.mark.parametrize(
    ("action", "command", "payload"),
    [
        (
            "submit",
            "submit_charity_selection",
            {"expected_version": 1, "reason": "Submit."},
        ),
        (
            "confirm",
            "confirm_charity_selection",
            {"expected_version": 1, "reason": "Confirm."},
        ),
        (
            "reject",
            "reject_charity_selection",
            {"expected_version": 1, "reason": "Reject."},
        ),
        (
            "comment",
            "add_charity_selection_private_comment",
            {"expected_version": 1, "private_comment": "Internal review note."},
        ),
        (
            "publish",
            "publish_charity_selection",
            {"expected_version": 1, "media_ids": [], "reason": "Publish."},
        ),
        (
            "withdraw",
            "withdraw_charity_selection_publication",
            {"expected_version": 1, "reason": "Withdraw."},
        ),
    ],
)
def test_charity_selection_command_actions_are_dispatched(
    action: str,
    command: str,
    payload: dict[str, object],
) -> None:
    result = CharityCommandResult(
        object_id=uuid4(),
        receipt_id=uuid4(),
        resulting_version=3,
        replayed=False,
    )
    with (
        patch("maru.charities.api._authorize_edition", return_value=_actor()),
        patch("maru.charities.api._authorize_selection", return_value=_actor()),
        patch(f"maru.charities.api.{command}", return_value=result) as dispatch,
    ):
        response = CharitySelectionCommandView.as_view()(
            _request("post", payload),
            organization_id=uuid4(),
            edition_id=uuid4(),
            selection_id=uuid4(),
            action=action,
        )

    assert response.status_code == 200
    dispatch.assert_called_once()


def test_charity_query_adapters_return_minimized_projections() -> None:
    identifiers = {
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "selection_id": uuid4(),
    }
    with patch("maru.charities.api.public_charities_for_edition", return_value=()):
        public = PublicCharityListView.as_view()(
            _request("get"),
            organization_id=identifiers["organization_id"],
            edition_id=identifiers["edition_id"],
        )
    with (
        patch("maru.charities.api._authorize_organization", return_value=_actor()),
        patch("maru.charities.api.list_charity_partners", return_value=()),
    ):
        partners = CharityPartnerCollectionView.as_view()(
            _request("get"), organization_id=identifiers["organization_id"]
        )
    with (
        patch("maru.charities.api._authorize_edition", return_value=_actor()),
        patch("maru.charities.api.list_charity_selection_queue", return_value=()),
    ):
        selections = CharitySelectionCollectionView.as_view()(
            _request("get"),
            organization_id=identifiers["organization_id"],
            edition_id=identifiers["edition_id"],
        )
    review = {
        "summary": {
            "id": identifiers["selection_id"],
            "partner_id": uuid4(),
            "partner_name": "River Aid",
            "responsible_department_id": uuid4(),
            "responsible_department_name": "Charity",
            "status": "submitted",
            "publication_state": "private",
            "aggregate_version": 2,
        },
        "timeline": [],
    }
    with (
        patch("maru.charities.api._authorize_selection", return_value=_actor()),
        patch("maru.charities.api.load_charity_selection_review", return_value=review),
    ):
        detail = CharitySelectionDetailView.as_view()(
            _request("get"),
            **identifiers,
        )

    assert public.data == []
    assert partners.data == []
    assert selections.data == []
    assert detail.data["summary"]["id"] == str(identifiers["selection_id"])


@pytest.mark.parametrize(
    ("error", "expected_exception"),
    [
        (CharityAuthorizationDeniedError(), PermissionDenied),
        (CharityResourceUnavailableError(), NotFound),
        (CharityStateConflictError(), CharityConflict),
        (ValidationError({"field": ["invalid"]}), ApiValidationError),
        (ValidationError("invalid"), ApiValidationError),
        (CharityCommandError(), DependencyUnavailable),
    ],
)
def test_charity_execute_maps_domain_failures(
    error: Exception,
    expected_exception: type[APIException],
) -> None:
    def fail() -> None:
        raise error

    with pytest.raises(expected_exception):
        execute_charity(fail)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "expected_version": 1,
            "reason": "Pair finite stock.",
            "sku": "FINITE-1",
            "name": "Finite",
            "price_minor": 100,
            "initial_stock": 1,
        },
        {
            "expected_version": 1,
            "reason": "Pair finite stock.",
            "sku": "FINITE-2",
            "name": "Finite",
            "price_minor": 100,
            "stock_ceiling": 1,
        },
    ],
)
def test_catalog_finite_stock_requires_both_bounds(
    payload: dict[str, object],
) -> None:
    serializer = CatalogVariantAddSerializer(data=payload)

    assert serializer.is_valid() is False
    assert "stock" in serializer.errors


def test_charity_partner_update_requires_a_business_change() -> None:
    serializer = CharityPartnerUpdateSerializer(
        data={"expected_version": 1, "reason": "No effective change."}
    )

    assert serializer.is_valid() is False
    assert "changes" in serializer.errors


@pytest.mark.parametrize(
    ("value", "kwargs"),
    [
        (cast(str, 42), {"field": "name", "maximum": 20}),
        ("bad\u0000value", {"field": "name", "maximum": 20}),
        ("   ", {"field": "name", "maximum": 20, "required": True}),
        ("too long", {"field": "name", "maximum": 3}),
    ],
)
def test_charity_text_normalization_rejects_invalid_values(
    value: str,
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        normalized_text(value, **cast(Any, kwargs))


def test_charity_text_normalization_is_canonical_and_bounded() -> None:
    assert normalized_reason("  Reviewed   by both controllers.  ") == (
        "Reviewed by both controllers."
    )
    assert normalized_slug(" River Aid ") == "river-aid"
    assert normalized_slug("", fallback="Fallback Charity") == "fallback-charity"
    with pytest.raises(ValidationError):
        normalized_slug("!!!")

    assert normalized_source_channel("browser") == "browser"
    for invalid in ("", "Browser", "contains space", "x" * 33):
        with pytest.raises(ValidationError):
            normalized_source_channel(invalid)

    first = canonical_digest({"b": 2, "a": 1})
    second = canonical_digest({"a": 1, "b": 2})
    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_exception"),
    [
        (None, 302, None),
        (CharityAuthorizationDeniedError(), None, DjangoPermissionDenied),
        (CharityResourceUnavailableError(), None, Http404),
        (CharityVersionConflictError(), 302, None),
        (CharityRetryConflictError(), 302, None),
        (CharityIndependentApprovalError(), 302, None),
        (CharityStateConflictError(), 302, None),
        (ValidationError("invalid"), 302, None),
        (CharityCommandError(), 302, None),
        (DatabaseError(), 503, None),
    ],
)
def test_charity_browser_command_boundary_maps_every_domain_outcome(
    error: Exception | None,
    expected_status: int | None,
    expected_exception: type[Exception] | None,
) -> None:
    def command() -> None:
        if error is not None:
            raise error

    with patch(
        "maru.charities.views._redirect_location",
        return_value=HttpResponse(status=302),
    ):
        if expected_exception is not None:
            with pytest.raises(expected_exception):
                _execute_command(
                    _message_request(),
                    command=command,
                    success_message="The command completed.",
                    location=("admin:index", ()),
                )
            return
        response = _execute_command(
            _message_request(),
            command=command,
            success_message="The command completed.",
            location=("admin:index", ()),
        )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_exception"),
    [
        (None, 302, None),
        (
            AuthorizationDenied("denied", reason_code="denied"),
            None,
            Http404,
        ),
        (ObjectDoesNotExist(), None, Http404),
        (ValidationError("invalid"), 302, None),
        (DatabaseError(), 503, None),
    ],
)
def test_catalog_browser_command_boundary_maps_every_domain_outcome(
    error: Exception | None,
    expected_status: int | None,
    expected_exception: type[Exception] | None,
) -> None:
    def command() -> None:
        if error is not None:
            raise error

    edition = SimpleNamespace()
    with patch("maru.catalog.views._staff_location", return_value="/staff/catalog/"):
        if expected_exception is not None:
            with pytest.raises(expected_exception):
                _execute_staff_command(
                    _message_request(),
                    command=command,
                    success_message="The command completed.",
                    edition=cast(Any, edition),
                )
            return
        response = _execute_staff_command(
            _message_request(),
            command=command,
            success_message="The command completed.",
            edition=cast(Any, edition),
        )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "field",
    [CatalogEditionLocalDateTimeField(), CharityEditionLocalDateTimeField()],
)
def test_domain_local_datetime_fields_reject_impossible_dates_and_prepare_values(
    field: CatalogEditionLocalDateTimeField | CharityEditionLocalDateTimeField,
) -> None:
    with pytest.raises(ValidationError):
        field.clean("2026-02-30T12:00")

    aware = datetime(2026, 8, 11, 10, 30, tzinfo=UTC)
    naive = aware.replace(tzinfo=None)
    assert field.prepare_value(naive) == "2026-08-11T10:30"
    assert field.prepare_value(aware) == "2026-08-11T10:30"
    marker = object()
    assert field.prepare_value(marker) is marker


def test_catalog_browser_forms_enforce_windows_and_stock_shapes() -> None:
    common_product = {
        "expected_version": "1",
        "idempotency_key": str(uuid4()),
        "reason": "Exercise the bounded product policy.",
        "code": "bounded-product",
        "kind": CatalogProduct.Kind.MERCHANDISE,
        "name": "Bounded product",
        "description": "",
        "beneficiary": CatalogProduct.Beneficiary.CONVENTION,
        "charity_selection_id": "",
        "sale_opens_at": "2026-08-11T12:00",
        "sale_closes_at": "2026-08-11T11:00",
        "fulfilment_mode": CatalogProduct.Fulfilment.PICKUP,
        "per_order_limit": "10",
    }
    product_form = CatalogProductAddForm(
        common_product,
        edition_time_zone="UTC",
        charity_selections=CharitySelection.objects.none(),
    )
    assert product_form.is_valid() is False
    assert "sale_closes_at" in product_form.errors

    base_variant = {
        "expected_version": "1",
        "idempotency_key": str(uuid4()),
        "reason": "Exercise the bounded stock policy.",
        "sku": "BOUND-1",
        "name": "Bounded",
        "price_minor": "100",
        "initial_stock": "1",
        "stock_ceiling": "",
    }
    partial_stock = CatalogVariantAddForm(
        base_variant,
        product_kind=CatalogProduct.Kind.MERCHANDISE,
    )
    assert partial_stock.is_valid() is False
    assert "stock_ceiling" in partial_stock.errors

    donation_stock = CatalogVariantAddForm(
        {**base_variant, "stock_ceiling": "1"},
        product_kind=CatalogProduct.Kind.DONATION,
    )
    assert donation_stock.is_valid() is False
    assert "initial_stock" in donation_stock.errors


def test_closed_domain_models_protect_retained_and_append_only_rows() -> None:
    with pytest.raises(ValidationError):
        EditionCatalog().delete()
    with pytest.raises(ValidationError):
        CharityPartner().delete()

    stock_evidence = CatalogStockAdjustment()
    stock_evidence._state.adding = False
    with pytest.raises(ValidationError):
        stock_evidence.save()

    charity_evidence = CharitySelectionTimelineEntry()
    charity_evidence._state.adding = False
    with pytest.raises(ValidationError):
        charity_evidence.save()


def test_catalog_product_and_variant_model_policy_checks_are_fail_closed() -> None:
    donation = CatalogProduct(
        kind=CatalogProduct.Kind.DONATION,
        fulfilment_mode=CatalogProduct.Fulfilment.PICKUP,
        preorder_allowed=False,
    )
    with pytest.raises(ValidationError):
        donation.clean()

    supporter = CatalogProduct(
        kind=CatalogProduct.Kind.SUPPORTER,
        fulfilment_mode=CatalogProduct.Fulfilment.PICKUP,
        preorder_allowed=True,
    )
    with pytest.raises(ValidationError):
        supporter.clean()

    catalog = EditionCatalog(currency="EUR")
    product = CatalogProduct(catalog=catalog, kind=CatalogProduct.Kind.MERCHANDISE)
    mismatched_currency = CatalogVariant(product=product, currency="USD")
    with pytest.raises(ValidationError):
        mismatched_currency.clean()

    assert CatalogVariant(initial_stock=None).is_stock_limited is False
    assert CatalogVariant(initial_stock=0).is_stock_limited is True


def test_charity_partner_string_uses_the_public_name() -> None:
    assert str(CharityPartner(public_name="River Aid")) == "River Aid"


@pytest.mark.parametrize("allowed", [True, False])
def test_charity_exact_authorization_helpers_use_the_resolved_target(
    allowed: bool,
) -> None:
    actor = _actor()
    request = cast(Any, SimpleNamespace(user=actor))
    decision = SimpleNamespace(allowed=allowed)
    organization_id = uuid4()
    edition_id = uuid4()
    selection_id = uuid4()

    with (
        patch(
            "maru.charities.api.resolve_edition_target", return_value="edition"
        ) as edition_target,
        patch(
            "maru.charities.api.resolve_charity_selection_target",
            return_value="selection",
        ) as selection_target,
        patch("maru.charities.api.decide", return_value=decision) as decide,
    ):
        if allowed:
            assert (
                authorize_charity_edition(
                    request,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    capability_code="charities.selection.propose",
                )
                is actor
            )
            assert (
                authorize_charity_selection(
                    request,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    selection_id=selection_id,
                    capability_code="charities.selection.review",
                )
                is actor
            )
        else:
            with pytest.raises(PermissionDenied):
                authorize_charity_edition(
                    request,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    capability_code="charities.selection.propose",
                )
            with pytest.raises(PermissionDenied):
                authorize_charity_selection(
                    request,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    selection_id=selection_id,
                    capability_code="charities.selection.review",
                )

    edition_target.assert_called()
    selection_target.assert_called()
    assert decide.call_count >= 2


def test_charity_request_identifiers_are_exact_and_safe() -> None:
    key = uuid4()
    assert (
        charity_idempotency_key(
            cast(Any, SimpleNamespace(headers={"Idempotency-Key": str(key)}))
        )
        == key
    )
    for raw in (None, "", "not-a-uuid", str(key).upper(), "x" * 65):
        headers = {} if raw is None else {"Idempotency-Key": raw}
        with pytest.raises(ApiValidationError):
            charity_idempotency_key(cast(Any, SimpleNamespace(headers=headers)))

    assert charity_correlation_id(cast(Any, SimpleNamespace(correlation_id=key))) == key
    assert (
        charity_correlation_id(cast(Any, SimpleNamespace(correlation_id=str(key))))
        == key
    )
    assert isinstance(
        charity_correlation_id(cast(Any, SimpleNamespace(correlation_id="invalid"))),
        UUID,
    )


def test_catalog_request_identity_and_identifiers_are_exact() -> None:
    actor = _actor()
    assert catalog_actor(cast(Any, SimpleNamespace(user=actor))) is actor
    with patch("maru.catalog.api.authorize_catalog_payment_api_scope") as authorize:
        assert (
            preauthorize_catalog_payment(
                cast(Any, SimpleNamespace(user=actor)),
                organization_id=uuid4(),
                edition_id=uuid4(),
                intent_id=uuid4(),
            )
            is actor
        )
    authorize.assert_called_once()
    with pytest.raises(PermissionDenied):
        catalog_actor(cast(Any, SimpleNamespace(user=SimpleNamespace(is_active=True))))
    actor.is_active = False
    with pytest.raises(PermissionDenied):
        catalog_actor(cast(Any, SimpleNamespace(user=actor)))

    key = uuid4()
    assert (
        catalog_idempotency_key(
            cast(Any, SimpleNamespace(headers={"Idempotency-Key": str(key)}))
        )
        == key
    )
    for raw in ("", "not-a-uuid", str(key).upper()):
        with pytest.raises(ApiValidationError):
            catalog_idempotency_key(
                cast(Any, SimpleNamespace(headers={"Idempotency-Key": raw}))
            )

    assert (
        catalog_correlation_id(cast(Any, SimpleNamespace(correlation_id=str(key))))
        == key
    )
    assert isinstance(
        catalog_correlation_id(cast(Any, SimpleNamespace(correlation_id="invalid"))),
        UUID,
    )


def _hosted_payment_request(data: dict[str, object]) -> Any:
    request = cast(
        Any,
        APIRequestFactory().post("/my/catalog/payment", data=data),
    )
    request.user = _actor()
    request.correlation_id = uuid4()
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _payment_form_payload() -> dict[str, object]:
    return {
        "expected_catalog_version": "1",
        "expected_order_version": "2",
        "idempotency_key": str(uuid4()),
    }


@pytest.mark.parametrize(
    ("command_error", "checkout_url", "expected_location"),
    [
        (
            None,
            "https://payments.example.test/session",
            "https://payments.example.test/session",
        ),
        (None, "", None),
        (ValidationError("stale"), "", None),
    ],
)
def test_hosted_payment_browser_boundary_handles_success_and_safe_failure(
    command_error: Exception | None,
    checkout_url: str,
    expected_location: str | None,
) -> None:
    edition_id = uuid4()
    order_id = uuid4()
    order = SimpleNamespace(id=order_id, organization_id=uuid4())
    result = CatalogCommandResult(
        target_id=uuid4(),
        resulting_version=3,
        replayed=False,
    )

    command_patch = (
        patch("maru.catalog.views.create_payment_intent", side_effect=command_error)
        if command_error is not None
        else patch("maru.catalog.views.create_payment_intent", return_value=result)
    )
    with (
        patch("maru.catalog.views._owned_order", return_value=order),
        command_patch,
        patch(
            "maru.catalog.views.CatalogPaymentIntent.objects.get",
            return_value=SimpleNamespace(checkout_url=checkout_url),
        ),
    ):
        response = start_catalog_hosted_payment_page(
            _hosted_payment_request(_payment_form_payload()),
            edition_id=edition_id,
            order_id=order_id,
        )

    assert response.status_code == 302
    if expected_location is not None:
        assert response.headers["Location"] == expected_location


def test_hosted_payment_browser_boundary_rejects_invalid_form() -> None:
    edition_id = uuid4()
    order_id = uuid4()
    order = SimpleNamespace(id=order_id, organization_id=uuid4())
    with (
        patch("maru.catalog.views._owned_order", return_value=order),
        patch("maru.catalog.views.create_payment_intent") as command,
    ):
        response = start_catalog_hosted_payment_page(
            _hosted_payment_request({}),
            edition_id=edition_id,
            order_id=order_id,
        )

    assert response.status_code == 302
    command.assert_not_called()


def test_charity_service_scalar_and_actor_invariants_fail_closed() -> None:
    identifier = uuid4()
    assert _require_uuid(identifier, field="selection_id") == identifier
    with pytest.raises(ValidationError):
        _require_uuid(cast(UUID, "not-a-uuid"), field="selection_id")

    assert _require_expected_version(1) == 1
    for invalid in (0, -1, True):
        with pytest.raises(ValidationError):
            _require_expected_version(invalid)

    persisted = _actor()
    _require_actor(persisted)
    unsaved = Account(email="unsaved@example.test", is_active=True)
    unsaved.id = None
    for invalid_actor in (
        unsaved,
        Account(id=uuid4(), email="inactive@example.test", is_active=False),
    ):
        with pytest.raises(CharityAuthorizationDeniedError):
            _require_actor(invalid_actor)


@pytest.mark.parametrize("allowed", [True, False])
def test_charity_service_policy_decision_is_enforced(allowed: bool) -> None:
    decision = SimpleNamespace(allowed=allowed)
    with patch("maru.charities.services.decide", return_value=decision):
        if allowed:
            assert (
                cast(
                    Any,
                    (
                        _require_decision(
                            actor=_actor(),
                            capability_code="charities.partner.manage",
                            target=cast(Any, "target"),
                            at=datetime(2026, 8, 11, tzinfo=UTC),
                        )
                    ),
                )
                is decision
            )
        else:
            with pytest.raises(CharityAuthorizationDeniedError):
                _require_decision(
                    actor=_actor(),
                    capability_code="charities.partner.manage",
                    target=cast(Any, "target"),
                    at=datetime(2026, 8, 11, tzinfo=UTC),
                )


def test_charity_partner_profile_normalization_is_stable() -> None:
    normalized = _normalize_profile(
        CharityPartnerProfile(
            legal_name="  River   Aid Foundation ",
            public_name=" River Aid ",
            country_code="hu",
        )
    )

    assert normalized["legal_name"] == "River Aid Foundation"
    assert normalized["public_name"] == "River Aid"
    assert normalized["country_code"] == "HU"


def _charity_command_ids() -> dict[str, object]:
    return {
        "actor": _actor(),
        "organization_id": uuid4(),
        "idempotency_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "service",
    }


def test_charity_partner_update_rejects_unsupported_and_invalid_changes() -> None:
    common = {
        **_charity_command_ids(),
        "partner_id": uuid4(),
        "expected_version": 1,
        "reason": "Validate the bounded update.",
    }
    update = cast(Any, update_charity_partner).__wrapped__
    for changes in ({}, {"unsupported": "value"}, {"lifecycle": "unknown"}):
        with pytest.raises(ValidationError):
            update(**common, changes=changes)


def test_charity_media_and_publication_inputs_reject_invalid_shapes() -> None:
    add_media = cast(Any, add_charity_partner_media).__wrapped__
    common_media = {
        **_charity_command_ids(),
        "partner_id": uuid4(),
        "source_reference": "s3://charity/source.webp",
        "owner_name": "River Aid",
        "license_basis": "Written permission",
        "usage_scope": "Convention promotion",
        "attribution": "River Aid",
        "reason": "Validate reviewed media.",
    }
    with pytest.raises(ValidationError):
        add_media(**common_media, kind="unsupported", expires_at=None)
    with pytest.raises(ValidationError):
        add_media(
            **common_media,
            kind=CharityPartnerMedia.Kind.LOGO,
            expires_at=datetime(2026, 8, 12, tzinfo=UTC).replace(tzinfo=None),
        )

    publish = cast(Any, publish_charity_selection).__wrapped__
    common_publish = {
        **_charity_command_ids(),
        "edition_id": uuid4(),
        "selection_id": uuid4(),
        "expected_version": 1,
        "reason": "Validate the publication evidence.",
    }
    duplicate = uuid4()
    with pytest.raises(ValidationError):
        publish(**common_publish, media_ids=(duplicate, duplicate))
    with pytest.raises(ValidationError):
        publish(**common_publish, media_ids=(cast(UUID, "invalid"),))


def test_charity_private_dispatchers_reject_unknown_actions_before_storage() -> None:
    common = {
        **_charity_command_ids(),
        "partner_id": uuid4(),
        "media_id": uuid4(),
        "expected_version": 1,
        "public_reference": "",
        "reason": "Validate the closed media action.",
        "request_id": None,
    }
    with pytest.raises(ValueError, match="Unsupported media review action"):
        cast(Any, _media_review_command)(**common, action="unsupported")

    review_common = {
        **_charity_command_ids(),
        "edition_id": uuid4(),
        "selection_id": uuid4(),
        "expected_version": 1,
        "reason": "Validate the closed decision.",
        "request_id": None,
    }
    with pytest.raises(ValueError, match="Unsupported charity review decision"):
        cast(Any, _review_charity_selection)(
            **review_common,
            decision_state="unsupported",
        )
