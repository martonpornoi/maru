from types import SimpleNamespace
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.handlers.wsgi import WSGIRequest
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from maru.applications.api import (
    ApplicationAnswerRevisionView,
    ApplicationDefinitionCollectionView,
    ApplicationReviewDecisionView,
    ApplicationSubmissionCreateView,
)
from maru.applications.commands import ApplicationAuthorizationDenied
from maru.applications.serializers import (
    QuestionConditionSerializer,
    QuestionOptionSerializer,
)
from maru.authorization.services import AuthorizationDenied
from maru.catalog.api import (
    CatalogActivityApi,
    CatalogDetailApi,
    CatalogOrderCollectionApi,
    CatalogPaymentCreateApi,
)
from maru.charities.api import (
    CharityMediaCommandView,
    CharityPartnerCollectionView,
    CharitySelectionCommandView,
    PublicCharityListView,
)
from maru.identity.models import Account
from maru.registration.api import (
    MyAdmissionTierReplacementView,
    MyRegistrationDemoPaymentView,
    RegistrationCapacityAdjustmentView,
)


def _actor() -> Account:
    return Account(
        id=uuid4(),
        email="api-preflight-operator@example.test",
        is_active=True,
    )


def _malformed_post(path: str, *, actor: Account) -> WSGIRequest:
    request = APIRequestFactory().generic(
        "POST",
        path,
        data='{ "malformed":',
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    force_authenticate(request, user=actor)
    return cast("WSGIRequest", request)


def _assert_private_no_store(response: Response) -> None:
    cache_control = response.headers["Cache-Control"]
    assert "private" in cache_control
    assert "no-store" in cache_control


@pytest.mark.parametrize(
    ("view", "preflight_path", "command_path"),
    [
        (
            ApplicationAnswerRevisionView,
            "maru.applications.api.authorize_application_self_submission_api_scope",
            "maru.applications.api.append_answer_revision",
        ),
        (
            ApplicationReviewDecisionView,
            "maru.applications.api.authorize_application_review_submission_api_scope",
            "maru.applications.api.record_review_decision",
        ),
    ],
)
def test_application_exact_submission_denial_precedes_malformed_input(
    view: type[APIView], preflight_path: str, command_path: str
) -> None:
    actor = _actor()
    request = _malformed_post("/api/v1/applications/foreign", actor=actor)

    with (
        patch(preflight_path, side_effect=ApplicationAuthorizationDenied),
        patch(command_path) as command,
    ):
        response = view.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            submission_id=uuid4(),
        )

    assert response.status_code == 403
    command.assert_not_called()
    _assert_private_no_store(response)


def test_application_success_response_is_private_no_store() -> None:
    actor = _actor()
    request = APIRequestFactory().get("/api/v1/applications/definitions")
    force_authenticate(request, user=actor)

    with patch("maru.applications.api.definition_workspace", return_value=()):
        response = ApplicationDefinitionCollectionView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    assert response.status_code == 200
    _assert_private_no_store(response)


def test_application_submission_start_denial_precedes_unknown_query_input() -> None:
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/applications/definitions/foreign/submissions?unknown=1",
        data={},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    force_authenticate(request, user=actor)

    with (
        patch(
            "maru.applications.api.authorize_application_self_api_scope",
            side_effect=ApplicationAuthorizationDenied,
        ),
        patch("maru.applications.api.start_submission") as command,
    ):
        response = ApplicationSubmissionCreateView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            definition_id=uuid4(),
        )

    assert response.status_code == 403
    command.assert_not_called()
    _assert_private_no_store(response)


def test_application_submission_start_rejects_unknown_query_after_authorization() -> (
    None
):
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/applications/definitions/current/submissions?unknown=1",
        data={},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    force_authenticate(request, user=actor)

    with (
        patch("maru.applications.api.authorize_application_self_api_scope"),
        patch("maru.applications.api.start_submission") as command,
    ):
        response = ApplicationSubmissionCreateView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            definition_id=uuid4(),
        )

    assert response.status_code == 400
    command.assert_not_called()
    _assert_private_no_store(response)


@pytest.mark.parametrize(
    ("serializer_class", "payload"),
    [
        (
            QuestionOptionSerializer,
            {"code": "main", "label": "Main", "unsupported": True},
        ),
        (
            QuestionConditionSerializer,
            {
                "question_key": "participates",
                "operator": "equals",
                "value": True,
                "unsupported": True,
            },
        ),
    ],
)
def test_application_nested_question_inputs_reject_unknown_fields(
    serializer_class: type[QuestionOptionSerializer | QuestionConditionSerializer],
    payload: dict[str, object],
) -> None:
    serializer = serializer_class(data=payload)

    assert serializer.is_valid() is False
    assert "unsupported" in str(serializer.errors)


def test_catalog_exact_order_denial_precedes_malformed_input() -> None:
    actor = _actor()
    request = _malformed_post("/api/v1/catalog/orders/foreign/payment", actor=actor)

    with (
        patch(
            "maru.catalog.api.authorize_catalog_order_api_scope",
            side_effect=AuthorizationDenied(
                "The catalog operation is unavailable.",
                reason_code="catalog_order_unavailable",
            ),
        ),
        patch("maru.catalog.api.create_payment_intent") as command,
    ):
        response = CatalogPaymentCreateApi.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            order_id=uuid4(),
        )

    assert response.status_code == 403
    command.assert_not_called()
    _assert_private_no_store(response)


@pytest.mark.parametrize(
    ("view", "authorization_query"),
    [
        (CatalogDetailApi, "maru.catalog.api.available_products_for_actor"),
        (CatalogOrderCollectionApi, "maru.catalog.api.own_orders"),
        (CatalogActivityApi, "maru.catalog.api.catalog_activity"),
    ],
)
def test_catalog_get_authorizes_before_rejecting_unknown_query_fields(
    view: type[APIView], authorization_query: str
) -> None:
    actor = _actor()
    request = APIRequestFactory().get("/api/v1/catalog/current?unknown=1")
    force_authenticate(request, user=actor)
    with patch(
        authorization_query,
        side_effect=AuthorizationDenied(
            "The catalog operation is unavailable.",
            reason_code="catalog_scope_denied",
        ),
    ):
        response = view.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    assert response.status_code == 403
    _assert_private_no_store(response)


def test_catalog_validation_and_success_responses_are_private_no_store() -> None:
    actor = _actor()
    invalid = APIRequestFactory().post(
        "/api/v1/catalog/orders/current/payment",
        data={"provider": "demo", "unknown": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    force_authenticate(invalid, user=actor)
    with patch("maru.catalog.api.authorize_catalog_order_api_scope"):
        invalid_response = CatalogPaymentCreateApi.as_view()(
            invalid,
            organization_id=uuid4(),
            edition_id=uuid4(),
            order_id=uuid4(),
        )
    assert invalid_response.status_code == 400
    _assert_private_no_store(invalid_response)

    success = APIRequestFactory().get("/api/v1/catalog/current")
    force_authenticate(success, user=actor)
    catalog = SimpleNamespace(aggregate_version=1, currency="EUR")
    with (
        patch("maru.catalog.api.available_products_for_actor", return_value=()),
        patch("maru.catalog.api.EditionCatalog.objects.get", return_value=catalog),
    ):
        success_response = CatalogDetailApi.as_view()(
            success,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )
    assert success_response.status_code == 200
    _assert_private_no_store(success_response)


def test_charity_private_is_no_store_but_public_list_remains_cacheable() -> None:
    actor = _actor()
    private_request = APIRequestFactory().get("/api/v1/charities/partners")
    force_authenticate(private_request, user=actor)
    with (
        patch("maru.charities.api._authorize_organization", return_value=actor),
        patch("maru.charities.api.list_charity_partners", return_value=()),
    ):
        private_response = CharityPartnerCollectionView.as_view()(
            private_request,
            organization_id=uuid4(),
        )
    assert private_response.status_code == 200
    _assert_private_no_store(private_response)

    public_request = APIRequestFactory().get("/api/v1/public/charities")
    with patch("maru.charities.api.public_charities_for_edition", return_value=()):
        public_response = PublicCharityListView.as_view()(
            public_request,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )
    assert public_response.status_code == 200
    assert "no-store" not in public_response.headers.get("Cache-Control", "")


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        ("approve", {"expected_version": 1, "reason": "Approve reviewed media."}),
        (
            "withdraw",
            {
                "expected_version": 1,
                "public_reference": "https://cdn.example.test/withdrawn.webp",
                "reason": "Withdraw obsolete media.",
            },
        ),
    ],
)
def test_charity_media_commands_use_action_specific_closed_inputs(
    action: str,
    payload: dict[str, object],
) -> None:
    actor = _actor()
    request = APIRequestFactory().post(
        f"/api/v1/charities/media/commands/{action}",
        data=payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    force_authenticate(request, user=actor)

    with (
        patch("maru.charities.api._authorize_organization", return_value=actor),
        patch("maru.charities.api.approve_charity_partner_media") as approve,
        patch("maru.charities.api.withdraw_charity_partner_media") as withdraw,
    ):
        response = CharityMediaCommandView.as_view()(
            request,
            organization_id=uuid4(),
            partner_id=uuid4(),
            media_id=uuid4(),
            action=action,
        )

    assert response.status_code == 400
    approve.assert_not_called()
    withdraw.assert_not_called()
    _assert_private_no_store(response)


def test_charity_mutation_rejects_whitespace_padded_idempotency_key() -> None:
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/charities/partners",
        data={},
        format="json",
        HTTP_IDEMPOTENCY_KEY=f" {uuid4()} ",
    )
    force_authenticate(request, user=actor)

    with (
        patch("maru.charities.api._authorize_organization", return_value=actor),
        patch("maru.charities.api.create_charity_partner") as command,
    ):
        response = CharityPartnerCollectionView.as_view()(
            request,
            organization_id=uuid4(),
        )

    assert response.status_code == 400
    command.assert_not_called()
    _assert_private_no_store(response)


def test_charity_selection_denial_precedes_unknown_action_validation() -> None:
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/charities/selections/foreign/commands/unsupported",
        data={"unsupported": True},
        format="json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )
    force_authenticate(request, user=actor)

    with patch(
        "maru.charities.api._authorize_selection",
        side_effect=PermissionDenied("The charity selection is unavailable."),
    ):
        response = CharitySelectionCommandView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            selection_id=uuid4(),
            action="unsupported",
        )

    assert response.status_code == 403
    _assert_private_no_store(response)


def test_charity_selection_unknown_action_is_hidden_after_authorization() -> None:
    actor = _actor()
    request = APIRequestFactory().post(
        "/api/v1/charities/selections/current/commands/unsupported",
        data={},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    force_authenticate(request, user=actor)

    with patch("maru.charities.api._authorize_selection", return_value=actor):
        response = CharitySelectionCommandView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            selection_id=uuid4(),
            action="unsupported",
        )

    assert response.status_code == 404
    _assert_private_no_store(response)


def test_foreign_self_registration_denial_precedes_malformed_input() -> None:
    actor = _actor()
    request = _malformed_post("/api/v1/registrations/foreign/upgrade", actor=actor)

    with (
        patch(
            "maru.registration.api.authorize_tier_replacement_api_scope",
            side_effect=AuthorizationDenied(
                "The admission upgrade is unavailable.",
                reason_code="registration_owned_scope_denied",
            ),
        ),
        patch("maru.registration.api.reserve_admission_tier_replacement") as command,
    ):
        response = MyAdmissionTierReplacementView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            registration_id=uuid4(),
        )

    assert response.status_code == 404
    command.assert_not_called()
    _assert_private_no_store(response)


def test_foreign_demo_payment_denial_precedes_malformed_input() -> None:
    actor = _actor()
    request = _malformed_post("/api/v1/registrations/foreign/payment", actor=actor)

    with (
        patch(
            "maru.registration.api.authorize_owned_registration_api_scope",
            side_effect=AuthorizationDenied(
                "The registration is unavailable.",
                reason_code="registration_owned_scope_denied",
            ),
        ),
        patch("maru.registration.api.confirm_demo_payment") as command,
    ):
        response = MyRegistrationDemoPaymentView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
            registration_id=uuid4(),
        )

    assert response.status_code == 404
    command.assert_not_called()
    _assert_private_no_store(response)


def test_denied_registration_staff_scope_precedes_malformed_input() -> None:
    actor = _actor()
    request = _malformed_post("/api/v1/registrations/capacity", actor=actor)

    with (
        patch(
            "maru.registration.api.authorize_registration_commerce_edition_api_scope",
            side_effect=AuthorizationDenied(
                "The commerce operation is unavailable.",
                reason_code="registration_scope_denied",
            ),
        ),
        patch("maru.registration.api.adjust_registration_capacity") as command,
    ):
        response = RegistrationCapacityAdjustmentView.as_view()(
            request,
            organization_id=uuid4(),
            edition_id=uuid4(),
        )

    assert response.status_code == 403
    command.assert_not_called()
    _assert_private_no_store(response)
