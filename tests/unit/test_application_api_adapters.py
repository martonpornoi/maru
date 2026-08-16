"""Executable non-database contracts for the strict Applications API adapters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory, force_authenticate

from maru.applications import api
from maru.applications.api import (
    ApplicationAnswerRevisionView,
    ApplicationDefinitionCollectionView,
    ApplicationDefinitionCommandView,
    ApplicationReviewDecisionView,
    ApplicationReviewQueueView,
    ApplicationStarterCatalogView,
    ApplicationSubmissionCreateView,
    ApplicationSubmitView,
    MyApplicationWorkspaceView,
)
from maru.applications.commands import (
    ApplicationAuthorizationDenied,
    ApplicationCommandError,
    ApplicationCommandResult,
    ApplicationEligibilityDenied,
    ApplicationUnavailable,
)
from maru.applications.models import (
    ApplicationClassification,
    ApplicationDefinitionStatus,
    ApplicationEligibilityKind,
    ApplicationQuestionType,
    ApplicationTargetKind,
)
from maru.identity.models import Account

_FACTORY = APIRequestFactory()


def _actor() -> Account:
    return Account(id=uuid4(), email="application-api@example.invalid")


def _request(
    method: str,
    data: object | None = None,
    *,
    actor: Account | None = None,
    idempotency_key: str | None = None,
) -> object:
    headers = {}
    if idempotency_key is not None:
        headers["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
    request = getattr(_FACTORY, method)("/", data=data, format="json", **headers)
    request.correlation_id = str(uuid4())
    if actor is not None:
        force_authenticate(request, user=actor)
    return request


def _result(*, replayed: bool = False) -> ApplicationCommandResult:
    return ApplicationCommandResult(
        receipt_id=uuid4(),
        definition_id=uuid4(),
        submission_id=uuid4(),
        target_id=uuid4(),
        resulting_version=3,
        replayed=replayed,
    )


def _ids() -> tuple[object, object, object, object]:
    return uuid4(), uuid4(), uuid4(), uuid4()


def test_actor_retry_and_correlation_controls_are_canonical() -> None:
    actor = _actor()
    key = uuid4()
    raw = _request("post", {}, actor=actor, idempotency_key=str(key))
    request = Request(raw)
    assert api._actor(request) is actor
    assert api._retry_key(request) == key
    assert api._correlation(request) == UUID(raw.correlation_id)

    for invalid in (None, "not-a-uuid", str(key).upper(), f" {key}"):
        malformed = Request(_request("post", {}, actor=actor, idempotency_key=invalid))
        with pytest.raises(ValidationError) as caught:
            api._retry_key(malformed)
        assert caught.value.get_codes()["Idempotency-Key"][0] == (
            "invalid_idempotency_key"
        )

    with pytest.raises(PermissionDenied):
        api._actor(Request(_request("get")))


def test_preauthorization_helpers_translate_domain_denial_before_parsing() -> None:
    actor = _actor()
    request = Request(_request("post", {}, actor=actor))
    organization_id, edition_id, submission_id, _definition_id = _ids()
    helpers = (
        (
            api._preauthorize_edition,
            "authorize_application_edition_api_scope",
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "capability_code": "applications.manage_definitions",
            },
        ),
        (
            api._preauthorize_self,
            "authorize_application_self_api_scope",
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "capability_code": "applications.apply_self",
            },
        ),
        (
            api._preauthorize_self_submission,
            "authorize_application_self_submission_api_scope",
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "submission_id": submission_id,
            },
        ),
        (
            api._preauthorize_review_submission,
            "authorize_application_review_submission_api_scope",
            {
                "organization_id": organization_id,
                "edition_id": edition_id,
                "submission_id": submission_id,
            },
        ),
    )
    for helper, dependency_name, values in helpers:
        with patch.object(api, dependency_name) as dependency:
            assert helper(request, **values) is actor
            dependency.assert_called_once_with(actor=actor, **values)
        with (
            patch.object(
                api,
                dependency_name,
                side_effect=ApplicationAuthorizationDenied(),
            ),
            pytest.raises(PermissionDenied),
        ):
            helper(request, **values)


def test_failure_translation_closes_domain_and_validation_errors() -> None:
    for error, exception_type in (
        (ApplicationAuthorizationDenied(), PermissionDenied),
        (ApplicationUnavailable(), NotFound),
        (ApplicationEligibilityDenied(), PermissionDenied),
        (DjangoValidationError({"field": ["bad"]}), ValidationError),
        (DjangoValidationError("bad"), ValidationError),
        (ApplicationCommandError(), api.ApplicationConflict),
    ):
        with pytest.raises(exception_type):
            api._failure(error)

    unexpected = RuntimeError("unexpected")
    with pytest.raises(RuntimeError, match="unexpected"):
        api._failure(unexpected)


def test_result_response_distinguishes_creation_and_replay() -> None:
    created = api._result_response(_result(), created=True)
    assert created.status_code == 201
    assert created["Idempotent-Replay"] == "false"
    replay = api._result_response(_result(replayed=True), created=True)
    assert replay.status_code == 200
    assert replay["Idempotent-Replay"] == "true"
    ordinary = api._result_response(_result(), created=False)
    assert ordinary.status_code == 200


def _question(*, applicant_visible: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        key="motivation",
        field_type=ApplicationQuestionType.LONG_TEXT,
        label="Motivation",
        help_text="Explain why.",
        required=True,
        options=[],
        minimum_length=10,
        maximum_length=2_000,
        minimum_value=None,
        maximum_value=None,
        maximum_choices=None,
        condition={},
        applicant_writable=True,
        source_binding="",
        purpose="Volunteer placement",
        classification=ApplicationClassification.PERSONAL,
        applicant_visible=applicant_visible,
        staff_visible=True,
        staff_writable=False,
        reviewer_visible=True,
        public_after_approval=False,
        api_projection=True,
        retention_policy_code="application.retention.v1",
    )


def _definition() -> SimpleNamespace:
    visible = _question()
    hidden = _question(applicant_visible=False)
    section = SimpleNamespace(
        id=uuid4(),
        key="main",
        title="Main",
        help_text="Complete this section.",
        questions=MagicMock(),
    )
    section.questions.all.return_value = (visible, hidden)
    definition = SimpleNamespace(
        id=uuid4(),
        code="volunteer-application",
        version=1,
        aggregate_version=3,
        status=ApplicationDefinitionStatus.ACTIVE,
        target_adapter_kind=ApplicationTargetKind.VOLUNTEER,
        name="Volunteer application",
        description="Help the event.",
        purpose="Volunteer intake",
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind=ApplicationEligibilityKind.AUTHENTICATED_PERSON,
        max_submissions_per_person=1,
        opens_at=None,
        closes_at=None,
        applicant_edit_until=None,
        minimum_age=0,
        audience_policy_code="applications.audience.v1",
        retention_policy_code="applications.retention.v1",
        age_policy_code="",
        sections=MagicMock(),
        owner_department_links=MagicMock(),
        reviewer_roles=MagicMock(),
        reviewer_people=MagicMock(),
    )
    definition.sections.all.return_value = (section,)
    definition.owner_department_links.all.return_value = (
        SimpleNamespace(department_id=uuid4(), department=SimpleNamespace(name="HR")),
    )
    definition.reviewer_roles.all.return_value = (
        SimpleNamespace(
            role_bundle_id=uuid4(),
            role_bundle=SimpleNamespace(name="Reviewers", version=2),
        ),
    )
    definition.reviewer_people.all.return_value = (
        SimpleNamespace(
            account_id=uuid4(),
            account=SimpleNamespace(display_name="Synthetic Reviewer"),
        ),
    )
    return definition


def test_definition_projection_filters_applicant_fields_and_hidden_questions() -> None:
    definition = _definition()
    staff = api._definition_data(definition, applicant=False)
    assert staff["classification"] == ApplicationClassification.PERSONAL
    assert len(staff["sections"][0]["questions"]) == 2
    assert staff["owner_departments"][0]["name"] == "HR"

    applicant = api._definition_data(definition, applicant=True)
    assert "classification" not in applicant
    assert len(applicant["sections"][0]["questions"]) == 1
    assert "purpose" not in applicant["sections"][0]["questions"][0]


def test_submission_projection_adds_applicant_only_for_reviewers() -> None:
    definition = _definition()
    submission = SimpleNamespace(
        id=uuid4(),
        definition_id=definition.id,
        definition=definition,
        ordinal=1,
        state="submitted",
        aggregate_version=2,
        submitted_at=None,
        decided_at=None,
        account_id=uuid4(),
        account=SimpleNamespace(display_name="Synthetic Applicant"),
    )
    with (
        patch.object(
            api, "latest_answers", return_value={"motivation": "Help"}
        ) as latest,
        patch.object(api, "decision_history", return_value=[]),
    ):
        applicant = api._submission_data(submission)
        reviewer = api._submission_data(submission, reviewer=True)
    assert "applicant" not in applicant
    assert reviewer["applicant"]["display_name"] == "Synthetic Applicant"
    assert latest.call_args_list[0].kwargs["audience"] == "applicant"
    assert latest.call_args_list[1].kwargs["audience"] == "reviewer"


def test_starter_and_definition_get_adapters_project_bounded_rows() -> None:
    actor = _actor()
    organization_id, edition_id, _submission_id, _definition_id = _ids()
    starter_request = _request("get", actor=actor)
    with patch.object(api, "definition_workspace", return_value=()):
        response = ApplicationStarterCatalogView.as_view()(
            starter_request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    assert response.status_code == 200
    assert any(item["code"] == "registration" for item in response.data)

    definition = _definition()
    definition_request = _request("get", actor=actor)
    with patch.object(api, "definition_workspace", return_value=(definition,)):
        response = ApplicationDefinitionCollectionView.as_view()(
            definition_request,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    assert response.status_code == 200
    assert response.data[0]["id"] == str(definition.id)


def test_definition_creation_adapter_returns_created_and_replay_status() -> None:
    actor = _actor()
    organization_id, edition_id, _submission_id, _definition_id = _ids()
    payload = {"starter_code": "volunteer-application", "reason": "Create it."}
    for result, expected_status in ((_result(), 201), (_result(replayed=True), 200)):
        request = _request(
            "post",
            payload,
            actor=actor,
            idempotency_key=str(uuid4()),
        )
        with (
            patch.object(api, "_preauthorize_edition", return_value=actor),
            patch.object(api, "_validated", return_value=payload),
            patch.object(
                api, "create_definition_from_starter", return_value=result
            ) as command,
        ):
            response = ApplicationDefinitionCollectionView.as_view()(
                request,
                organization_id=organization_id,
                edition_id=edition_id,
            )
        assert response.status_code == expected_status
        assert command.call_args.kwargs["actor"] is actor


@pytest.mark.parametrize(
    ("operation", "dependency_name", "expected_status"),
    [
        ("definition.configure", "configure_definition", 200),
        ("section.add", "add_section", 201),
        ("question.add", "add_question", 201),
        ("definition.activate", "activate_definition", 200),
        ("definition.retire", "retire_definition", 200),
        ("definition.successor", "create_successor_definition", 201),
    ],
)
def test_definition_command_adapter_dispatches_closed_operations(
    operation: str,
    dependency_name: str,
    expected_status: int,
) -> None:
    actor = _actor()
    organization_id, edition_id, _submission_id, definition_id = _ids()
    request = _request(
        "post",
        {"operation": operation},
        actor=actor,
        idempotency_key=str(uuid4()),
    )
    payload = {"operation": operation, "reason": "Exercise dispatch."}
    with (
        patch.object(api, "_preauthorize_edition", return_value=actor),
        patch.object(api, "_validated", return_value=payload),
        patch.object(api, dependency_name, return_value=_result()) as command,
    ):
        response = ApplicationDefinitionCommandView.as_view()(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            definition_id=definition_id,
        )
    assert response.status_code == expected_status
    assert command.call_args.kwargs["definition_id"] == definition_id


@pytest.mark.parametrize("body", [["not-an-object"], {"operation": "future"}])
def test_definition_command_adapter_rejects_open_discriminators(body: object) -> None:
    actor = _actor()
    organization_id, edition_id, _submission_id, definition_id = _ids()
    request = _request(
        "post",
        body,
        actor=actor,
        idempotency_key=str(uuid4()),
    )
    with patch.object(api, "_preauthorize_edition", return_value=actor):
        response = ApplicationDefinitionCommandView.as_view()(
            request,
            organization_id=organization_id,
            edition_id=edition_id,
            definition_id=definition_id,
        )
    assert response.status_code == 400


def test_self_and_review_get_adapters_audit_before_projection() -> None:
    actor = _actor()
    organization_id, edition_id, _submission_id, _definition_id = _ids()
    definition = _definition()
    submission = SimpleNamespace(id=uuid4())
    with (
        patch.object(api, "available_applications", return_value=(definition,)),
        patch.object(api, "my_submissions", return_value=(submission,)),
        patch.object(api, "_definition_data", return_value={"definition": "safe"}),
        patch.object(api, "_submission_data", return_value={"submission": "safe"}),
        patch.object(api, "_audit_workspace_read") as audit,
    ):
        response = MyApplicationWorkspaceView.as_view()(
            _request("get", actor=actor),
            organization_id=organization_id,
            edition_id=edition_id,
        )
    assert response.status_code == 200
    assert response.data["available"] == [{"definition": "safe"}]
    assert audit.call_args.kwargs["record_count"] == 2

    with (
        patch.object(api, "review_queue", return_value=(submission,)),
        patch.object(
            api, "_submission_data", return_value={"review": "safe"}
        ) as projection,
        patch.object(api, "_audit_workspace_read") as audit,
    ):
        response = ApplicationReviewQueueView.as_view()(
            _request("get", actor=actor),
            organization_id=organization_id,
            edition_id=edition_id,
        )
    assert response.data == [{"review": "safe"}]
    assert projection.call_args.kwargs["reviewer"] is True
    assert audit.call_args.kwargs["record_count"] == 1


@pytest.mark.parametrize(
    ("view", "preauthorize_name", "command_name", "payload", "created"),
    [
        (
            ApplicationSubmissionCreateView,
            "_preauthorize_self",
            "start_submission",
            {},
            True,
        ),
        (
            ApplicationAnswerRevisionView,
            "_preauthorize_self_submission",
            "append_answer_revision",
            {"question_id": uuid4(), "expected_version": 1, "value": "answer"},
            True,
        ),
        (
            ApplicationSubmitView,
            "_preauthorize_self_submission",
            "submit_application",
            {"expected_version": 1},
            False,
        ),
        (
            ApplicationReviewDecisionView,
            "_preauthorize_review_submission",
            "record_review_decision",
            {"expected_version": 1, "decision": "accept", "reason": "Approve."},
            False,
        ),
    ],
)
def test_submission_mutation_adapters_call_shared_commands(
    view: type,
    preauthorize_name: str,
    command_name: str,
    payload: dict[str, object],
    created: bool,
) -> None:
    actor = _actor()
    organization_id, edition_id, submission_id, definition_id = _ids()
    kwargs = {"organization_id": organization_id, "edition_id": edition_id}
    if view is ApplicationSubmissionCreateView:
        kwargs["definition_id"] = definition_id
    else:
        kwargs["submission_id"] = submission_id
    request = _request(
        "post",
        payload,
        actor=actor,
        idempotency_key=str(uuid4()),
    )
    contexts = [
        patch.object(api, preauthorize_name, return_value=actor),
        patch.object(api, command_name, return_value=_result()),
    ]
    if view is not ApplicationSubmissionCreateView:
        contexts.append(patch.object(api, "_validated", return_value=payload))
    with contexts[0], contexts[1] as command:
        if len(contexts) == 3:
            with contexts[2]:
                response = view.as_view()(request, **kwargs)
        else:
            response = view.as_view()(request, **kwargs)
    assert response.status_code == (201 if created else 200)
    assert command.call_args.kwargs["actor"] is actor


def test_workspace_read_audit_is_minimized() -> None:
    actor = _actor()
    organization_id, edition_id, _submission_id, _definition_id = _ids()
    request = Request(_request("get", actor=actor))
    with patch.object(api, "append_audit") as append:
        api._audit_workspace_read(
            request=request,
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="applications.view_self",
            operation="applications.self_workspace.read",
            record_count=2,
        )
    record = append.call_args.args[0]
    assert record.safe_metadata == {"target_count": 2}
    assert record.obligations == ("audit_sensitive_read",)
