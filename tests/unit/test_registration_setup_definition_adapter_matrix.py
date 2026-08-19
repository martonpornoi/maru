from __future__ import annotations

# Test doubles intentionally accept the production call signatures.
# ruff: noqa: ARG005
import inspect
from types import SimpleNamespace
from typing import ClassVar
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.test import RequestFactory

from maru.events.models import EventEdition
from maru.organizations.models import Organization
from maru.registration import setup_definition_views as views
from maru.registration.models import ProfileExtensionStatus
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupCommandError,
    RegistrationSetupDependencyError,
)
from maru.registration.setup_definition_commands import (
    RegistrationSetupProductDependencyError,
    RegistrationSetupProductUnavailableError,
    RegistrationSetupProfileFieldImmutableError,
    RegistrationSetupProfileFieldUnavailableError,
    RegistrationSetupQuestionDependencyError,
    RegistrationSetupQuestionUnavailableError,
)
from maru.registration.setup_forms import (
    RegistrationDefinitionDeleteForm,
    RegistrationProductCreateForm,
    RegistrationProductMoveForm,
    RegistrationProductUpdateForm,
    RegistrationProfileFieldCreateForm,
    RegistrationProfileFieldMoveForm,
    RegistrationProfileFieldUpdateForm,
    RegistrationQuestionCreateForm,
    RegistrationQuestionMoveForm,
    RegistrationQuestionUpdateForm,
)


def _read() -> SimpleNamespace:
    questions = (
        SimpleNamespace(id=uuid4(), key="badge_name", label="Badge name"),
        SimpleNamespace(id=uuid4(), key="notes", label="Notes"),
    )
    products = (
        SimpleNamespace(id=uuid4(), name="Attendee"),
        SimpleNamespace(id=uuid4(), name="Sponsor"),
    )
    fields = (
        SimpleNamespace(
            id=uuid4(),
            key="arrival_note",
            label="Arrival note",
            status=ProfileExtensionStatus.DRAFT,
        ),
        SimpleNamespace(
            id=uuid4(),
            key="staff_check",
            label="Staff check",
            status=ProfileExtensionStatus.ACTIVE,
        ),
    )
    workspace = SimpleNamespace(
        aggregate_version=7,
        current_configuration=SimpleNamespace(id=uuid4()),
        sections=(SimpleNamespace(id=uuid4(), title="Basics"),),
        questions=questions,
        products=products,
        profile_fields=fields,
        active_capacity_codes=("attendee", "volunteer"),
        prior_configurations=(),
        published_templates=(),
        minor_policy=None,
    )
    return SimpleNamespace(
        organization=SimpleNamespace(
            id=uuid4(), lifecycle=Organization.Lifecycle.ACTIVE
        ),
        series=SimpleNamespace(id=uuid4()),
        edition=SimpleNamespace(
            id=uuid4(),
            name="Synthetic 2027",
            time_zone="Europe/Budapest",
            lifecycle=EventEdition.Lifecycle.DRAFT,
        ),
        workspace=workspace,
    )


def _command_form() -> SimpleNamespace:
    return SimpleNamespace(
        cleaned_data={
            "expected_version": 7,
            "reason": "Keep the registration definition current.",
            "retry_key": uuid4(),
            "key": "arrival_note",
            "label": "Arrival note",
            "help_text": "A minimized current detail.",
            "field_type": "short_text",
            "required": False,
            "options": [],
            "purpose": "Coordinate arrival.",
            "visibility": "attendee_and_staff",
            "classification": "C2",
            "condition_question_key": "",
            "condition_value": "",
            "section_id": None,
            "after_question_id": None,
            "code": "supporter",
            "name": "Supporter",
            "description": "Supporter admission.",
            "price_minor": 12_000,
            "capacity": 50,
            "capacity_ceiling": 60,
            "entitlement_code": "supporter",
            "entitlement_name": "Supporter",
            "sales_open_at": None,
            "sales_close_at": None,
            "required_capacity_codes": [],
            "eligibility_explanation": "",
            "waitlist_enabled": True,
            "payment_window_minutes": 30,
            "after_product_id": None,
            "audience_policy": "self",
            "audience_department_id": None,
            "writer_policy": "attendee_and_staff",
            "source_template_id": None,
            "source_prior_edition_id": None,
            "after_field_id": None,
        }
    )


@pytest.mark.parametrize(
    ("lookup", "collection", "attribute"),
    [
        (views._question_by_id, "questions", "label"),
        (views._product_by_id, "products", "name"),
        (views._profile_field_by_id, "profile_fields", "label"),
    ],
)
def test_definition_lookup_is_exact_and_non_disclosing(
    lookup: object,
    collection: str,
    attribute: str,
) -> None:
    read = _read()
    item = getattr(read.workspace, collection)[1]

    found, ordinal = lookup(read, item.id)  # type: ignore[operator]

    assert found is item
    assert ordinal == 2
    assert getattr(found, attribute)
    with pytest.raises(Http404):
        lookup(read, uuid4())  # type: ignore[operator]


@pytest.mark.parametrize(
    (
        "aggregate_version",
        "organization_lifecycle",
        "edition_lifecycle",
        "allowed",
        "reason",
    ),
    [
        (
            0,
            Organization.Lifecycle.ACTIVE,
            EventEdition.Lifecycle.DRAFT,
            False,
            "Start",
        ),
        (
            7,
            Organization.Lifecycle.CLOSED,
            EventEdition.Lifecycle.DRAFT,
            False,
            "organization",
        ),
        (7, Organization.Lifecycle.ACTIVE, EventEdition.Lifecycle.LIVE, False, "Draft"),
        (
            7,
            Organization.Lifecycle.DRAFT,
            EventEdition.Lifecycle.PREPARING,
            True,
            "read-only",
        ),
    ],
)
def test_profile_mutation_lifecycle_explains_every_fail_closed_state(
    aggregate_version: int,
    organization_lifecycle: str,
    edition_lifecycle: str,
    allowed: bool,
    reason: str,
) -> None:
    read = _read()
    read.workspace.aggregate_version = aggregate_version
    read.organization.lifecycle = organization_lifecycle
    read.edition.lifecycle = edition_lifecycle

    assert views._profile_mutations_allowed(read) is allowed
    assert reason in views._profile_mutation_blocked_reason(read)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            RegistrationSetupQuestionDependencyError(),
            "conditional question",
        ),
        (
            RegistrationSetupProductDependencyError(),
            "commercial evidence",
        ),
        (
            RegistrationSetupProfileFieldImmutableError(),
            "immutable",
        ),
    ],
)
def test_definition_errors_explain_protected_dependencies(
    error: RegistrationSetupCommandError,
    expected: str,
) -> None:
    assert expected in views._definition_error_message(error)


def test_definition_error_falls_back_to_shared_conflict_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(views, "_command_conflict_message", lambda error: "shared")
    assert views._definition_error_message(RegistrationSetupCommandError()) == "shared"


@pytest.mark.parametrize(
    ("kind", "action", "form_type"),
    [
        ("question", "create", RegistrationQuestionCreateForm),
        ("question", "update", RegistrationQuestionUpdateForm),
        ("question", "move", RegistrationQuestionMoveForm),
        ("question", "remove", RegistrationDefinitionDeleteForm),
        ("product", "create", RegistrationProductCreateForm),
        ("product", "update", RegistrationProductUpdateForm),
        ("product", "move", RegistrationProductMoveForm),
        ("product", "remove", RegistrationDefinitionDeleteForm),
    ],
)
def test_configuration_form_dispatch_is_closed(
    kind: str,
    action: str,
    form_type: type,
) -> None:
    read = _read()
    request = RequestFactory().post("/registration/", data={})
    target_id = (
        None if action == "create" else getattr(read.workspace, f"{kind}s")[0].id
    )

    form, heading, submit_label, invalid_message = views._configuration_post_form(
        request=request,
        read=read,
        kind=kind,
        action=action,
        target_id=target_id,
    )

    assert isinstance(form, form_type)
    assert kind in heading.lower() or action in heading.lower()
    assert submit_label
    assert invalid_message.startswith(("No ", "The "))


@pytest.mark.parametrize("kind", ["question", "product"])
def test_configuration_form_dispatch_requires_a_target(kind: str) -> None:
    with pytest.raises(Http404):
        views._configuration_post_form(
            request=RequestFactory().post("/registration/", data={}),
            read=_read(),
            kind=kind,
            action="update",
            target_id=None,
        )


def test_configuration_form_dispatch_rejects_unknown_operations() -> None:
    with pytest.raises(Http404):
        views._configuration_post_form(
            request=RequestFactory().post("/registration/", data={}),
            read=_read(),
            kind="question",
            action="publish",
            target_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("kind", "action", "command_name"),
    [
        ("question", "create", "create_registration_question"),
        ("question", "update", "update_registration_question"),
        ("question", "move", "move_registration_question"),
        ("question", "remove", "delete_registration_question"),
        ("product", "create", "create_admission_product"),
        ("product", "update", "update_admission_product"),
        ("product", "move", "move_admission_product"),
        ("product", "remove", "delete_admission_product"),
    ],
)
def test_configuration_command_dispatch_preserves_the_closed_action(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    action: str,
    command_name: str,
) -> None:
    read = _read()
    target_id = None if action == "create" else uuid4()
    captured: dict[str, object] = {}

    def command(**kwargs: object) -> str:
        captured.update(kwargs)
        return "result"

    monkeypatch.setattr(views, command_name, command)
    result = views._run_configuration_command(
        actor=SimpleNamespace(id=uuid4()),
        read=read,
        configuration_id=read.workspace.current_configuration.id,
        kind=kind,
        action=action,
        target_id=target_id,
        form=_command_form(),
        correlation_id=uuid4(),
    )

    assert result == "result"
    assert captured["source_channel"] == "web"
    assert captured["expected_version"] == 7
    if action != "create":
        assert captured[f"{kind}_id"] == target_id


def test_configuration_command_dispatch_rejects_unknown_operations() -> None:
    with pytest.raises(Http404):
        views._run_configuration_command(
            actor=SimpleNamespace(id=uuid4()),
            read=_read(),
            configuration_id=uuid4(),
            kind="question",
            action="publish",
            target_id=uuid4(),
            form=_command_form(),
            correlation_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("action", "form_type"),
    [
        ("create", RegistrationProfileFieldCreateForm),
        ("update", RegistrationProfileFieldUpdateForm),
        ("move", RegistrationProfileFieldMoveForm),
        ("retire", RegistrationDefinitionDeleteForm),
    ],
)
def test_profile_form_dispatch_is_closed(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    form_type: type,
) -> None:
    read = _read()
    monkeypatch.setattr(views, "_profile_department_choices", lambda read: ())
    field_id = None if action == "create" else read.workspace.profile_fields[0].id

    form, heading, submit_label = views._profile_post_form(
        request=RequestFactory().post("/registration/", data={}),
        read=read,
        action=action,
        field_id=field_id,
    )

    assert isinstance(form, form_type)
    assert "profile" in heading.lower()
    assert submit_label


def test_profile_form_dispatch_requires_known_target_and_action() -> None:
    request = RequestFactory().post("/registration/", data={})
    with pytest.raises(Http404):
        views._profile_post_form(
            request=request,
            read=_read(),
            action="update",
            field_id=None,
        )
    with pytest.raises(Http404):
        views._profile_post_form(
            request=request,
            read=_read(),
            action="publish",
            field_id=uuid4(),
        )


@pytest.mark.parametrize(
    ("action", "command_name"),
    [
        ("create", "create_registration_profile_extension_field"),
        ("update", "update_registration_profile_extension_field"),
        ("move", "move_registration_profile_extension_field"),
        ("retire", "retire_registration_profile_extension_field"),
    ],
)
def test_profile_command_dispatch_preserves_the_closed_action(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    command_name: str,
) -> None:
    captured: dict[str, object] = {}

    def command(**kwargs: object) -> str:
        captured.update(kwargs)
        return "result"

    monkeypatch.setattr(views, command_name, command)
    field_id = None if action == "create" else uuid4()
    result = views._run_profile_command(
        actor=SimpleNamespace(id=uuid4()),
        read=_read(),
        action=action,
        field_id=field_id,
        form=_command_form(),
        correlation_id=uuid4(),
    )

    assert result == "result"
    assert captured["source_channel"] == "web"
    if action != "create":
        assert captured["field_id"] == field_id


def test_profile_command_dispatch_rejects_unknown_operations() -> None:
    with pytest.raises(Http404):
        views._run_profile_command(
            actor=SimpleNamespace(id=uuid4()),
            read=_read(),
            action="publish",
            field_id=uuid4(),
            form=_command_form(),
            correlation_id=uuid4(),
        )


class _StubForm:
    fields: ClassVar[dict[str, object]] = {"key": object()}
    cleaned_data: ClassVar[dict[str, object]] = {"key": "arrival_note"}

    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid

    def is_valid(self) -> bool:
        return self.valid


def _patch_configuration_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    form: _StubForm,
) -> tuple[SimpleNamespace, list[str]]:
    read = _read()
    messages: list[str] = []
    monkeypatch.setattr(
        views,
        "_preflight_post",
        lambda *args, **kwargs: (SimpleNamespace(id=uuid4()), read),
    )
    monkeypatch.setattr(views, "_configuration_for_route", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        views,
        "_configuration_post_form",
        lambda **kwargs: (form, "Edit question", "Save", "No question was changed."),
    )
    monkeypatch.setattr(
        views, "_configuration_location", lambda *args, **kwargs: "/back"
    )
    monkeypatch.setattr(views, "_request_id", lambda request: uuid4())
    monkeypatch.setattr(
        views,
        "_render_definition_form",
        lambda request, **kwargs: HttpResponse(status=kwargs["status"]),
    )
    monkeypatch.setattr(
        views,
        "_registration_dependency_failure",
        lambda request: HttpResponse(status=503),
    )
    monkeypatch.setattr(
        views, "_registration_bad_request", lambda request: HttpResponse(status=400)
    )
    monkeypatch.setattr(
        views,
        "_handle_command_error",
        lambda request, **kwargs: HttpResponse(status=409),
    )
    monkeypatch.setattr(views, "_private_no_store", lambda response: response)
    monkeypatch.setattr(
        views,
        "redirect",
        lambda location: HttpResponse(status=302, headers={"Location": location}),
    )
    monkeypatch.setattr(
        views.messages, "success", lambda request, message: messages.append(message)
    )
    return read, messages


def _configuration_post() -> HttpResponse:
    return views._configuration_definition_post(
        RequestFactory().post("/registration/", data={}),
        organization_slug="synthetic",
        series_slug="series",
        edition_slug="edition",
        configuration_id=uuid4(),
        kind="question",
        action="update",
        target_id=None,
    )


def test_configuration_adapter_returns_bound_form_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_configuration_adapter(monkeypatch, form=_StubForm(valid=False))
    assert _configuration_post().status_code == 400


@pytest.mark.parametrize(
    ("error", "status", "add_errors"),
    [
        (ValidationError({"key": "Invalid."}), 400, True),
        (ValidationError("Unsafe unmapped failure."), 503, False),
        (RegistrationSetupCommandError(), 409, True),
        (RegistrationSetupDependencyError(), 503, True),
        (DatabaseError("down"), 503, True),
        (RuntimeError("down"), 503, True),
    ],
)
def test_configuration_adapter_maps_domain_failures_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    add_errors: bool,
) -> None:
    _patch_configuration_adapter(monkeypatch, form=_StubForm())
    monkeypatch.setattr(
        views, "_add_domain_validation_errors", lambda *args, **kwargs: add_errors
    )
    monkeypatch.setattr(
        views,
        "_run_configuration_command",
        lambda **kwargs: (_ for _ in ()).throw(error),
    )
    assert _configuration_post().status_code == status


@pytest.mark.parametrize(
    "error",
    [
        RegistrationSetupQuestionUnavailableError(),
        RegistrationSetupProductUnavailableError(),
    ],
)
def test_configuration_adapter_hides_unavailable_targets(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    _patch_configuration_adapter(monkeypatch, form=_StubForm())
    monkeypatch.setattr(
        views,
        "_run_configuration_command",
        lambda **kwargs: (_ for _ in ()).throw(error),
    )
    with pytest.raises(Http404):
        _configuration_post()


def test_configuration_adapter_preserves_permission_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_configuration_adapter(monkeypatch, form=_StubForm())
    monkeypatch.setattr(
        views,
        "_run_configuration_command",
        lambda **kwargs: (_ for _ in ()).throw(
            RegistrationSetupAuthorizationDeniedError()
        ),
    )
    with pytest.raises(PermissionDenied):
        _configuration_post()


@pytest.mark.parametrize("replayed", [False, True])
def test_configuration_adapter_reports_new_and_replayed_success(
    monkeypatch: pytest.MonkeyPatch,
    replayed: bool,
) -> None:
    _, messages = _patch_configuration_adapter(monkeypatch, form=_StubForm())
    monkeypatch.setattr(
        views,
        "_run_configuration_command",
        lambda **kwargs: SimpleNamespace(replayed=replayed),
    )
    response = _configuration_post()
    assert response.status_code == 302
    assert response.headers["Location"] == "/back"
    assert ("already recorded" in messages[0]) is replayed


def test_configuration_adapter_rejects_query_and_dependency_before_form_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = RequestFactory().post("/registration/", data={})
    monkeypatch.setattr(
        views, "_registration_bad_request", lambda request: HttpResponse(status=400)
    )
    monkeypatch.setattr(
        views,
        "_registration_dependency_failure",
        lambda request: HttpResponse(status=503),
    )
    for error, status in [
        (views._RegistrationPostQueryParametersUnsupportedError(), 400),
        (RegistrationSetupDependencyError(), 503),
    ]:
        monkeypatch.setattr(
            views,
            "_preflight_post",
            lambda *args, _error=error, **kwargs: (_ for _ in ()).throw(_error),
        )
        response = views._configuration_definition_post(
            request,
            organization_slug="synthetic",
            series_slug="series",
            edition_slug="edition",
            configuration_id=uuid4(),
            kind="question",
            action="create",
            target_id=None,
        )
        assert response.status_code == status


def _patch_profile_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    form: _StubForm,
) -> list[str]:
    read = _read()
    messages: list[str] = []
    monkeypatch.setattr(
        views,
        "_preflight_post",
        lambda *args, **kwargs: (SimpleNamespace(id=uuid4()), read),
    )
    monkeypatch.setattr(
        views,
        "_profile_post_form",
        lambda **kwargs: (form, "Edit profile extension", "Save"),
    )
    monkeypatch.setattr(views, "_profile_location", lambda read: "/profiles")
    monkeypatch.setattr(views, "_request_id", lambda request: uuid4())
    monkeypatch.setattr(
        views,
        "_render_definition_form",
        lambda request, **kwargs: HttpResponse(status=kwargs["status"]),
    )
    monkeypatch.setattr(
        views,
        "_registration_dependency_failure",
        lambda request: HttpResponse(status=503),
    )
    monkeypatch.setattr(
        views, "_registration_bad_request", lambda request: HttpResponse(status=400)
    )
    monkeypatch.setattr(
        views,
        "_handle_command_error",
        lambda request, **kwargs: HttpResponse(status=409),
    )
    monkeypatch.setattr(views, "_private_no_store", lambda response: response)
    monkeypatch.setattr(
        views,
        "redirect",
        lambda location: HttpResponse(status=302, headers={"Location": location}),
    )
    monkeypatch.setattr(
        views.messages, "success", lambda request, message: messages.append(message)
    )
    return messages


def _profile_post() -> HttpResponse:
    return views._profile_definition_post(
        RequestFactory().post("/registration/", data={}),
        organization_slug="synthetic",
        series_slug="series",
        edition_slug="edition",
        action="create",
        field_id=None,
    )


@pytest.mark.parametrize(
    ("outcome", "status", "add_errors"),
    [
        (ValidationError({"key": "Invalid."}), 400, True),
        (ValidationError("Unsafe unmapped failure."), 503, False),
        (RegistrationSetupCommandError(), 409, True),
        (RegistrationSetupDependencyError(), 503, True),
        (DatabaseError("down"), 503, True),
        (RuntimeError("down"), 503, True),
    ],
)
def test_profile_adapter_maps_domain_failures_without_disclosure(
    monkeypatch: pytest.MonkeyPatch,
    outcome: Exception,
    status: int,
    add_errors: bool,
) -> None:
    _patch_profile_adapter(monkeypatch, form=_StubForm())
    monkeypatch.setattr(
        views, "_add_domain_validation_errors", lambda *args, **kwargs: add_errors
    )
    monkeypatch.setattr(
        views, "_run_profile_command", lambda **kwargs: (_ for _ in ()).throw(outcome)
    )
    assert _profile_post().status_code == status


def test_profile_adapter_rejects_invalid_form(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_profile_adapter(monkeypatch, form=_StubForm(valid=False))
    assert _profile_post().status_code == 400


def test_profile_adapter_hides_unavailable_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_profile_adapter(monkeypatch, form=_StubForm())
    monkeypatch.setattr(
        views,
        "_run_profile_command",
        lambda **kwargs: (_ for _ in ()).throw(
            RegistrationSetupProfileFieldUnavailableError()
        ),
    )
    with pytest.raises(Http404):
        _profile_post()


def test_profile_adapter_preserves_permission_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_profile_adapter(monkeypatch, form=_StubForm())
    monkeypatch.setattr(
        views,
        "_run_profile_command",
        lambda **kwargs: (_ for _ in ()).throw(
            RegistrationSetupAuthorizationDeniedError()
        ),
    )
    with pytest.raises(PermissionDenied):
        _profile_post()


@pytest.mark.parametrize("replayed", [False, True])
def test_profile_adapter_reports_new_and_replayed_success(
    monkeypatch: pytest.MonkeyPatch,
    replayed: bool,
) -> None:
    messages = _patch_profile_adapter(monkeypatch, form=_StubForm())
    monkeypatch.setattr(
        views,
        "_run_profile_command",
        lambda **kwargs: SimpleNamespace(replayed=replayed),
    )
    response = _profile_post()
    assert response.status_code == 302
    assert response.headers["Location"] == "/profiles"
    assert ("already recorded" in messages[0]) is replayed


@pytest.mark.parametrize("operation", ["set", "remove"])
def test_minor_policy_dependency_failures_remain_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    read = _read()
    read.workspace.minor_policy = SimpleNamespace(enabled=True)
    form = _StubForm()
    form.cleaned_data = {
        "enabled": True,
        "minor_age_threshold": 18,
        "guardian_notice_version": "guardian-v1",
        "jurisdiction_code": "HU",
        "review_reference": "review-1",
        "expected_version": 7,
        "reason": "Keep the minor policy current.",
        "retry_key": uuid4(),
    }
    monkeypatch.setattr(
        views,
        "_preflight_post",
        lambda *args, **kwargs: (SimpleNamespace(id=uuid4()), read),
    )
    monkeypatch.setattr(
        views,
        "_configuration_for_route",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(views, "_minor_form", lambda *args, **kwargs: form)
    monkeypatch.setattr(
        views,
        "RegistrationDefinitionDeleteForm",
        lambda *args, **kwargs: form,
    )
    monkeypatch.setattr(
        views,
        "_registration_dependency_failure",
        lambda request: HttpResponse(status=503),
    )
    monkeypatch.setattr(
        views,
        (
            "set_minor_registration_policy"
            if operation == "set"
            else "remove_minor_registration_policy"
        ),
        lambda **kwargs: (_ for _ in ()).throw(RegistrationSetupDependencyError()),
    )
    endpoint = inspect.unwrap(
        views.set_registration_setup_minor_policy
        if operation == "set"
        else views.remove_registration_setup_minor_policy
    )

    response = endpoint(
        RequestFactory().post("/registration/", data={}),
        organization_slug="synthetic",
        series_slug="series",
        edition_slug="edition",
        configuration_id=uuid4(),
    )

    assert response.status_code == 503
