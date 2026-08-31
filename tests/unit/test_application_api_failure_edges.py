"""Failure-path contracts for Applications API adapters."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from maru.applications import api
from maru.applications.commands import ApplicationUnavailable
from maru.identity.models import Account

_FACTORY = APIRequestFactory()


def _actor() -> Account:
    return Account(id=uuid4(), email="application-api-failure@example.invalid")


def _request(method: str, data: object | None = None) -> object:
    request = getattr(_FACTORY, method)(
        "/",
        data=data,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid4()),
    )
    request.correlation_id = str(uuid4())
    force_authenticate(request, user=_actor())
    return request


def test_validated_runs_both_unknown_field_gates_and_serializer() -> None:
    serializer = MagicMock()
    serializer.fields = {"known": object()}
    serializer.validated_data = {"known": "value"}
    serializer_class = MagicMock(return_value=serializer)
    request = Request(
        _request("post", {"known": "value"}),
        parsers=[JSONParser()],
    )
    with patch.object(api, "reject_unknown_fields") as reject:
        assert api._validated(request, serializer_class) == {"known": "value"}
    assert reject.call_count == 2
    serializer.is_valid.assert_called_once_with(raise_exception=True)


def test_every_api_adapter_translates_dependency_failure() -> None:
    organization_id, edition_id = uuid4(), uuid4()
    definition_id, submission_id = uuid4(), uuid4()
    actor = _actor()
    get_specs = (
        (api.ApplicationStarterCatalogView, "application_starters", {}),
        (api.ApplicationDefinitionCollectionView, "definition_workspace", {}),
        (api.MyApplicationWorkspaceView, "available_applications", {}),
        (api.ApplicationReviewQueueView, "review_queue", {}),
    )
    for view, dependency, extra in get_specs:
        with (
            patch.object(api, "_actor", return_value=actor),
            patch.object(api, dependency, side_effect=ApplicationUnavailable()),
        ):
            response = view.as_view()(
                _request("get"),
                organization_id=organization_id,
                edition_id=edition_id,
                **extra,
            )
        assert response.status_code == 404

    post_specs = (
        (
            api.ApplicationDefinitionCollectionView,
            "create_definition_from_starter",
            {"starter_code": "volunteer", "reason": "Create."},
            {},
        ),
        (
            api.ApplicationSubmissionCreateView,
            "start_submission",
            {},
            {"definition_id": definition_id},
        ),
        (
            api.ApplicationAnswerRevisionView,
            "append_answer_revision",
            {"question_id": uuid4(), "expected_version": 1, "value": "answer"},
            {"submission_id": submission_id},
        ),
        (
            api.ApplicationSubmitView,
            "submit_application",
            {"expected_version": 1},
            {"submission_id": submission_id},
        ),
        (
            api.ApplicationReviewDecisionView,
            "record_review_decision",
            {"expected_version": 1, "decision": "accept", "reason": "Approve."},
            {"submission_id": submission_id},
        ),
    )
    for view, dependency, payload, extra in post_specs:
        with (
            patch.object(api, "_actor", return_value=actor),
            patch.object(api, "_preauthorize_edition", return_value=actor),
            patch.object(api, "_preauthorize_self", return_value=actor),
            patch.object(api, "_preauthorize_self_submission", return_value=actor),
            patch.object(api, "_preauthorize_review_submission", return_value=actor),
            patch.object(api, "_validated", return_value=dict(payload)),
            patch.object(api, dependency, side_effect=ApplicationUnavailable()),
        ):
            response = view.as_view()(
                _request("post", payload),
                organization_id=organization_id,
                edition_id=edition_id,
                **extra,
            )
        assert response.status_code == 404

    payload = {"operation": "definition.configure", "reason": "Configure."}
    with (
        patch.object(api, "_preauthorize_edition", return_value=actor),
        patch.object(api, "_actor", return_value=actor),
        patch.object(api, "_validated", return_value=dict(payload)),
        patch.object(api, "configure_definition", side_effect=ApplicationUnavailable()),
    ):
        response = api.ApplicationDefinitionCommandView.as_view()(
            _request("post", payload),
            organization_id=organization_id,
            edition_id=edition_id,
            definition_id=definition_id,
        )
    assert response.status_code == 404
