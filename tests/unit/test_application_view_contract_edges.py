"""Non-database branch contracts for Applications browser adapters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.test import RequestFactory

from maru.applications import views
from maru.applications.commands import (
    ApplicationAuthorizationDenied,
    ApplicationCommandError,
    ApplicationEligibilityDenied,
    ApplicationStateConflict,
    ApplicationUnavailable,
)
from maru.applications.models import (
    ApplicationClassification,
    ApplicationState,
    ReviewDecisionKind,
)
from maru.identity.models import Account

_FACTORY = RequestFactory()


def _actor(*, active: bool = True) -> Account:
    return Account(
        id=uuid4(),
        email="application-browser@example.invalid",
        is_active=active,
    )


def _request(method: str = "get", data: dict[str, object] | None = None):
    request = getattr(_FACTORY, method)("/", data=data or {})
    request.user = _actor()
    request.correlation_id = str(uuid4())
    return request


def _edition() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        organization=SimpleNamespace(slug="organizer"),
        series=SimpleNamespace(slug="series"),
        time_zone="Europe/Budapest",
    )


def _definition() -> SimpleNamespace:
    relation = MagicMock()
    relation.values_list.return_value = ()
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        edition=_edition(),
        aggregate_version=2,
        name="Volunteer application",
        description="Help the event.",
        purpose="Volunteer intake",
        classification=ApplicationClassification.PERSONAL,
        eligibility_kind="authenticated_person",
        max_submissions_per_person=1,
        opens_at=None,
        closes_at=None,
        applicant_edit_until=None,
        minimum_age=0,
        audience_policy_code="audience.v1",
        retention_policy_code="retention.v1",
        age_policy_code="",
        is_sensitive=False,
        owner_department_links=relation,
        reviewer_roles=relation,
        reviewer_people=relation,
    )


def _form(*, valid: bool = True) -> MagicMock:
    form = MagicMock()
    form.is_valid.return_value = valid
    form.cleaned_data = {
        "retry_key": uuid4(),
        "expected_version": 2,
        "reason": "Exercise the browser adapter.",
        "name": "Application",
        "description": "Description",
        "purpose": "Purpose",
        "classification": ApplicationClassification.PERSONAL,
        "eligibility_kind": "authenticated_person",
        "maximum_submissions": 1,
        "opens_at": None,
        "closes_at": None,
        "applicant_edit_until": None,
        "minimum_age": 0,
        "audience_policy_code": "audience.v1",
        "retention_policy_code": "retention.v1",
        "age_policy_code": "",
        "owner_department_ids": (),
        "reviewer_role_bundle_ids": (),
        "key": "motivation",
        "title": "Motivation",
        "help_text": "Explain why.",
        "section_id": uuid4(),
        "field_type": "long_text",
        "label": "Motivation",
        "required": True,
        "options_text": (),
        "reference_kind": "",
        "applicant_visible": True,
        "applicant_writable": True,
        "staff_visible": True,
        "staff_writable": False,
        "reviewer_visible": True,
        "public_after_approval": False,
        "api_projection": True,
        "question_id": uuid4(),
        "value": "I can help.",
        "decision": ReviewDecisionKind.ACCEPT,
    }
    form.reviewer_account_ids = ()
    form.condition = {}
    return form


def test_request_context_edition_and_strict_query_boundaries() -> None:
    request = _request()
    assert views._actor(request) is request.user
    request.user = _actor(active=False)
    with pytest.raises(PermissionDenied):
        views._actor(request)

    queryset = MagicMock()
    queryset.select_related.return_value.filter.return_value.first.return_value = None
    with (
        patch.object(views.EventEdition, "objects", queryset),
        pytest.raises(Http404),
    ):
        views._edition(uuid4(), uuid4())

    assert views._strict_get(_request()) is None
    assert views._strict_get(_request("get", {"future": "value"})).status_code == 400
    with patch.object(views.admin.site, "each_context", return_value={}):
        context = views._context(
            request,
            edition=_edition(),
            personal=True,
            title="Applications",
        )
    assert context["maru_personal_surface"] is True


def test_command_errors_preserve_closed_http_meanings() -> None:
    form = forms.Form()
    form.fields["name"] = forms.CharField()
    form.cleaned_data = {}
    assert views._add_command_error(form, ValidationError({"name": ["Bad"]})) == 400
    assert views._add_command_error(form, ValidationError("Bad")) == 400
    assert views._add_command_error(form, ApplicationCommandError()) == 409
    for error, exception_type in (
        (ApplicationAuthorizationDenied(), PermissionDenied),
        (ApplicationUnavailable(), Http404),
        (ApplicationEligibilityDenied(), PermissionDenied),
    ):
        with pytest.raises(exception_type):
            views._add_command_error(form, error)
    with pytest.raises(RuntimeError, match="unexpected"):
        views._add_command_error(form, RuntimeError("unexpected"))


def test_department_and_reviewer_queries_are_scope_and_sensitivity_aware() -> None:
    definition = _definition()
    departments = MagicMock()
    departments.filter.return_value.order_by.return_value = ()
    with patch.object(views.Department, "objects", departments):
        assert views._departments(definition) == ()

    ordinary = SimpleNamespace(capability_codes=("applications.review",))
    sensitive = SimpleNamespace(
        capability_codes=("applications.review", "applications.review_sensitive")
    )
    roles = MagicMock()
    roles.filter.return_value.order_by.return_value = (ordinary, sensitive)
    with patch.object(views.RoleBundle, "objects", roles):
        assert views._reviewer_roles(definition) == (ordinary, sensitive)
        definition.is_sensitive = True
        assert views._reviewer_roles(definition) == (sensitive,)


@pytest.mark.parametrize(
    ("endpoint", "extra"),
    [
        (views.application_definition_workspace, (uuid4(), uuid4())),
        (views.application_starter_copy_page, (uuid4(), uuid4(), "starter")),
        (views.application_definition_detail, (uuid4(), uuid4(), uuid4())),
        (views.my_application_index, ()),
        (views.my_application_workspace, (uuid4(), uuid4())),
        (views.my_application_detail, (uuid4(), uuid4(), uuid4())),
        (views.application_review_workspace, (uuid4(), uuid4())),
        (views.application_review_detail, (uuid4(), uuid4(), uuid4())),
    ],
)
def test_all_get_pages_reject_unknown_query_parameters(
    endpoint,
    extra: tuple[object, ...],
) -> None:
    response = endpoint(_request("get", {"future": "value"}), *extra)
    assert response.status_code == 400


def test_get_queries_translate_domain_denial() -> None:
    organization_id, edition_id, object_id = uuid4(), uuid4(), uuid4()
    specs = (
        (
            views.application_definition_workspace,
            "definition_workspace",
            (organization_id, edition_id),
        ),
        (
            views.application_definition_detail,
            "definition_detail",
            (organization_id, edition_id, object_id),
        ),
        (views.my_application_index, "my_application_editions", ()),
        (
            views.my_application_workspace,
            "available_applications",
            (organization_id, edition_id),
        ),
        (
            views.my_application_detail,
            "my_submission_detail",
            (organization_id, edition_id, object_id),
        ),
        (
            views.application_review_workspace,
            "review_queue",
            (organization_id, edition_id),
        ),
        (
            views.application_review_detail,
            "review_submission_detail",
            (organization_id, edition_id, object_id),
        ),
    )
    for endpoint, dependency, args in specs:
        with (
            patch.object(
                views, dependency, side_effect=ApplicationAuthorizationDenied()
            ),
            pytest.raises(PermissionDenied),
        ):
            endpoint(_request(), *args)


def test_unknown_or_external_starters_are_not_copyable() -> None:
    organization_id, edition_id = uuid4(), uuid4()
    for starter in (None, SimpleNamespace(is_external=True)):
        with (
            patch.object(views, "definition_workspace", return_value=()),
            patch.object(views, "application_starter", return_value=starter),
            pytest.raises(Http404),
        ):
            views.application_starter_copy_page(
                _request(), organization_id, edition_id, "future"
            )
        with (
            patch.object(views, "definition_workspace", return_value=()),
            patch.object(views, "application_starter", return_value=starter),
            pytest.raises(Http404),
        ):
            views.application_starter_copy(
                _request("post"), organization_id, edition_id, "future"
            )


def test_definition_mutations_render_conflicts_on_the_active_form() -> None:
    actor, edition, definition = _actor(), _edition(), _definition()
    request = _request("post")
    form = _form()
    ids = (uuid4(), uuid4(), uuid4())
    specs = (
        (
            views.application_definition_configure,
            "DefinitionConfigureForm",
            "configure_definition",
        ),
        (views.application_section_add, "SectionAddForm", "add_section"),
        (views.application_question_add, "QuestionAddForm", "add_question"),
        (
            views.application_definition_successor,
            "DefinitionSuccessorForm",
            "create_successor_definition",
        ),
    )
    for endpoint, form_name, command_name in specs:
        with (
            patch.object(
                views, "_definition_for_post", return_value=(actor, edition, definition)
            ),
            patch.object(views, "_departments", return_value=()),
            patch.object(views, "_reviewer_roles", return_value=()),
            patch.object(views, form_name, return_value=form),
            patch.object(views, command_name, side_effect=ApplicationStateConflict()),
            patch.object(views, "_add_command_error", return_value=409),
            patch.object(
                views,
                "_definition_response",
                return_value=HttpResponse("conflict", status=409),
            ),
        ):
            response = endpoint(request, *ids)
        assert response.status_code == 409

    for operation in ("activate", "retire"):
        with (
            patch.object(
                views, "_definition_for_post", return_value=(actor, edition, definition)
            ),
            patch.object(views, "DefinitionLifecycleForm", return_value=form),
            patch.object(
                views, f"{operation}_definition", side_effect=ApplicationStateConflict()
            ),
            patch.object(views, "_add_command_error", return_value=409),
            patch.object(
                views,
                "_definition_response",
                return_value=HttpResponse("conflict", status=409),
            ),
        ):
            response = views._lifecycle_command(
                request,
                organization_id=ids[0],
                edition_id=ids[1],
                definition_id=ids[2],
                operation=operation,
            )
        assert response.status_code == 409


def test_submission_and_review_mutations_close_malformed_and_conflict_paths() -> None:
    actor = _actor()
    organization_id, edition_id, submission_id = uuid4(), uuid4(), uuid4()
    invalid_form = _form(valid=False)
    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "StartSubmissionForm", return_value=invalid_form),
    ):
        response = views.application_submission_start(
            _request("post"), organization_id, edition_id, uuid4()
        )
    assert response.status_code == 400

    valid_form = _form()
    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "StartSubmissionForm", return_value=valid_form),
        patch.object(views, "start_submission", side_effect=ApplicationStateConflict()),
        patch.object(views, "_add_command_error", return_value=409),
    ):
        response = views.application_submission_start(
            _request("post"), organization_id, edition_id, uuid4()
        )
    assert response.status_code == 409

    submission = SimpleNamespace(
        id=submission_id,
        definition=SimpleNamespace(questions=MagicMock()),
    )
    submission.definition.questions.all.return_value = ()
    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(views, "_owned_submission_for_post", return_value=submission),
        pytest.raises(Http404),
    ):
        views.application_answer_append(
            _request("post", {"question_id": str(uuid4())}),
            organization_id,
            edition_id,
            submission_id,
        )

    with (
        patch.object(
            views, "my_submission_detail", side_effect=ApplicationAuthorizationDenied()
        ),
        pytest.raises(PermissionDenied),
    ):
        views._owned_submission_for_post(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )

    with (
        patch.object(views, "_actor", return_value=actor),
        patch.object(
            views,
            "review_submission_detail",
            side_effect=ApplicationAuthorizationDenied(),
        ),
        pytest.raises(PermissionDenied),
    ):
        views.application_review_decision(
            _request("post"), organization_id, edition_id, submission_id
        )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ApplicationState.SUBMITTED, 4),
        (ApplicationState.UNDER_REVIEW, 3),
        (ApplicationState.CHANGES_REQUESTED, 2),
        (ApplicationState.ACCEPTED, 0),
    ],
)
def test_review_forms_expose_only_legal_state_transitions(
    state: str,
    expected: int,
) -> None:
    submission = SimpleNamespace(state=state, aggregate_version=2)
    assert len(views._review_forms(submission)) == expected
