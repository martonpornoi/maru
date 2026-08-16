from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpResponse
from django.test import RequestFactory

from maru.events.models import EventEdition
from maru.organizations.models import Organization
from maru.registration import setup_views as views
from maru.registration.models import ConfigurationStatus, RegistrationSetupOrigin
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupDependencyError,
    RegistrationSetupLifecycleConflictError,
    RegistrationSetupLimitExceededError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupSourceUnavailableError,
    RegistrationSetupStateConflictError,
    RegistrationSetupVersionConflictError,
)
from maru.registration.setup_section_commands import (
    RegistrationSetupConfigurationUnavailableError,
    RegistrationSetupSectionDependencyError,
    RegistrationSetupSectionUnavailableError,
)


class StubSectionForm:
    valid: ClassVar[bool] = True

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.cleaned_data: dict[str, object] = {
            "key": "contact",
            "title": "Contact",
            "description": "Synthetic section used by the adapter boundary.",
            "after_section_id": None,
            "expected_version": 5,
            "reason": "Exercise the closed browser section command.",
            "retry_key": UUID(int=8),
        }
        self.fields = {
            key: forms.CharField()
            for key in (
                "key",
                "title",
                "description",
                "after_section_id",
                "expected_version",
                "reason",
                "retry_key",
            )
        }
        self.added_errors: list[tuple[str | None, object]] = []

    def is_valid(self) -> bool:
        return self.valid

    def add_error(self, field: str | None, error: object) -> None:
        self.added_errors.append((field, error))


def _request(*, query: bool = False):  # type: ignore[no-untyped-def]
    suffix = "?forged=1" if query else ""
    request = RequestFactory().post(f"/registration/setup/{suffix}", data={})
    request.user = SimpleNamespace(is_authenticated=True)
    request.correlation_id = str(UUID(int=9))
    return request


def _response(*, status: int = 200, **values: object) -> HttpResponse:
    response = HttpResponse(status=status)
    response.adapter_values = values  # type: ignore[attr-defined]
    return response


def _raise(error: Exception):  # type: ignore[no-untyped-def]
    def raiser(*_args: object, **_kwargs: object) -> None:
        raise error

    return raiser


def _read() -> SimpleNamespace:
    return SimpleNamespace(
        organization=SimpleNamespace(
            id=UUID(int=1),
            slug="organization",
            lifecycle=Organization.Lifecycle.ACTIVE,
        ),
        series=SimpleNamespace(id=UUID(int=2), slug="series"),
        edition=SimpleNamespace(
            id=UUID(int=3),
            slug="edition",
            lifecycle=EventEdition.Lifecycle.PREPARING,
        ),
        workspace=SimpleNamespace(aggregate_version=5, sections=()),
    )


def _invoke(action: str, request: object) -> HttpResponse:
    function = {
        "update": views.update_registration_setup_section,
        "move": views.move_registration_setup_section,
        "delete": views.remove_registration_setup_section,
    }[action]
    return inspect.unwrap(function)(
        request,
        "organization",
        "series",
        "edition",
        UUID(int=4),
        UUID(int=5),
    )


def _command_name(action: str) -> str:
    return {
        "update": "update_registration_section",
        "move": "move_registration_section",
        "delete": "delete_registration_section",
    }[action]


def _form_name(action: str) -> str:
    return {
        "update": "RegistrationSectionUpdateForm",
        "move": "RegistrationSectionMoveForm",
        "delete": "RegistrationSectionDeleteForm",
    }[action]


def _patch_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    action: str,
    command: object,
) -> None:
    monkeypatch.setattr(
        views,
        "_section_action_preflight",
        lambda *_args, **_kwargs: (SimpleNamespace(id=UUID(int=1)), _read(), 1),
    )
    monkeypatch.setattr(views, _form_name(action), StubSectionForm)
    monkeypatch.setattr(views, _command_name(action), command)
    monkeypatch.setattr(
        views,
        "_section_failure_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    monkeypatch.setattr(
        views,
        "_registration_dependency_failure",
        lambda *_args, **_kwargs: _response(status=503),
    )
    monkeypatch.setattr(
        views,
        "_registration_bad_request",
        lambda *_args, **_kwargs: _response(status=400),
    )
    monkeypatch.setattr(views, "_configuration_location", lambda *_args: "/setup/")
    monkeypatch.setattr(views.messages, "success", lambda *_args, **_kwargs: None)


def test_request_id_and_private_headers_are_closed() -> None:
    request = _request()
    assert views._request_id(request) == UUID(int=9)
    request.correlation_id = "invalid"
    assert views._request_id(request) != UUID(int=9)

    response = views._private_no_store(HttpResponse())
    assert response["Cache-Control"] == "private, no-store"
    assert response["Pragma"] == "no-cache"
    assert response["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize(
    ("configuration", "organization_lifecycle", "edition_lifecycle", "allowed"),
    [
        (None, Organization.Lifecycle.ACTIVE, EventEdition.Lifecycle.PREPARING, False),
        (
            SimpleNamespace(status=ConfigurationStatus.ACTIVE),
            Organization.Lifecycle.ACTIVE,
            EventEdition.Lifecycle.PREPARING,
            False,
        ),
        (
            SimpleNamespace(status=ConfigurationStatus.DRAFT),
            Organization.Lifecycle.SUSPENDED,
            EventEdition.Lifecycle.PREPARING,
            False,
        ),
        (
            SimpleNamespace(status=ConfigurationStatus.DRAFT),
            Organization.Lifecycle.ACTIVE,
            EventEdition.Lifecycle.LIVE,
            False,
        ),
        (
            SimpleNamespace(status=ConfigurationStatus.DRAFT),
            Organization.Lifecycle.ACTIVE,
            EventEdition.Lifecycle.PREPARING,
            True,
        ),
    ],
)
def test_mutation_gate_requires_draft_setup_and_mutable_parent_lifecycles(
    configuration: object | None,
    organization_lifecycle: str,
    edition_lifecycle: str,
    allowed: bool,
) -> None:
    read = _read()
    read.workspace.current_configuration = configuration
    read.organization.lifecycle = organization_lifecycle
    read.edition.lifecycle = edition_lifecycle
    assert views._mutations_allowed(read) is allowed


@pytest.mark.parametrize(
    ("configuration", "organization_lifecycle", "edition_lifecycle", "message"),
    [
        (
            None,
            Organization.Lifecycle.ACTIVE,
            EventEdition.Lifecycle.PREPARING,
            "Start",
        ),
        (
            SimpleNamespace(status=ConfigurationStatus.ACTIVE),
            Organization.Lifecycle.ACTIVE,
            EventEdition.Lifecycle.PREPARING,
            "immutable",
        ),
        (
            SimpleNamespace(status=ConfigurationStatus.DRAFT),
            Organization.Lifecycle.SUSPENDED,
            EventEdition.Lifecycle.PREPARING,
            "organization lifecycle",
        ),
        (
            SimpleNamespace(status=ConfigurationStatus.DRAFT),
            Organization.Lifecycle.ACTIVE,
            EventEdition.Lifecycle.LIVE,
            "Draft or Preparing",
        ),
        (
            SimpleNamespace(status=ConfigurationStatus.DRAFT),
            Organization.Lifecycle.ACTIVE,
            EventEdition.Lifecycle.PREPARING,
            "read-only",
        ),
    ],
)
def test_mutation_gate_explains_each_fail_closed_state(
    configuration: object | None,
    organization_lifecycle: str,
    edition_lifecycle: str,
    message: str,
) -> None:
    read = _read()
    read.workspace.current_configuration = configuration
    read.organization.lifecycle = organization_lifecycle
    read.edition.lifecycle = edition_lifecycle
    assert message in views._mutation_blocked_reason(read)


def test_source_choice_builder_preserves_origin_kind_and_stable_order() -> None:
    platform_id, template_id, prior_id = uuid4(), uuid4(), uuid4()
    workspace = SimpleNamespace(
        platform_starters=(
            SimpleNamespace(source_id=platform_id, name="Starter", version=1),
        ),
        published_templates=(
            SimpleNamespace(source_id=template_id, name="Template", version=2),
        ),
        prior_configurations=(
            SimpleNamespace(
                source_id=prior_id,
                source_edition_name="Prior Edition",
                name="Prior setup",
                version=3,
            ),
        ),
    )
    choices, kinds = views._source_choices(workspace)
    assert [choice[0] for choice in choices] == [
        str(platform_id),
        str(template_id),
        str(prior_id),
    ]
    assert kinds == {
        platform_id: RegistrationSetupOrigin.PLATFORM_STARTER,
        template_id: RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
        prior_id: RegistrationSetupOrigin.PRIOR_EDITION,
    }


def test_section_lookup_ordinal_and_predecessor_are_exact() -> None:
    first = SimpleNamespace(id=uuid4(), title="First")
    second = SimpleNamespace(id=uuid4(), title="Second")
    workspace = SimpleNamespace(sections=(first, second))
    assert views._find_section(workspace, second.id) is second
    assert views._section_ordinal(workspace, second.id) == 2
    assert views._section_predecessor(workspace, first.id) == ""
    assert views._section_predecessor(workspace, second.id) == str(first.id)
    placement = views._placement_choices(workspace, exclude_section_id=second.id)
    assert placement[0][0] == str(first.id)
    assert "After First" in placement[0][1]
    assert "current section 1" in placement[0][1]
    for helper in (
        views._find_section,
        views._section_ordinal,
        views._section_predecessor,
    ):
        with pytest.raises(Http404):
            helper(workspace, uuid4())


def test_domain_validation_mapping_rejects_scalar_or_unknown_fields() -> None:
    form = StubSectionForm()
    assert not views._add_domain_validation_errors(
        form,
        ValidationError("Unsafe scalar error."),
        allowed_fields=frozenset(form.fields),
    )
    assert not views._add_domain_validation_errors(
        form,
        ValidationError({"unknown": ["Unsafe field."]}),
        allowed_fields=frozenset(form.fields),
    )
    assert views._add_domain_validation_errors(
        form,
        ValidationError({"reason": ["Review reason."]}),
        allowed_fields=frozenset(form.fields),
    )
    assert form.added_errors


@pytest.mark.parametrize(
    ("error", "message", "reload_required"),
    [
        (RegistrationSetupVersionConflictError(), "changed after", True),
        (RegistrationSetupRetryConflictError(), "retry identifier", True),
        (RegistrationSetupLifecycleConflictError(), "read-only", True),
        (RegistrationSetupSectionDependencyError(), "referenced", False),
        (RegistrationSetupLimitExceededError(), "safety limit", True),
        (RegistrationSetupSourceUnavailableError(), "source", True),
        (RegistrationSetupStateConflictError(), "stored", True),
        (RegistrationSetupDependencyError(), "safely", False),
    ],
)
def test_command_conflict_messages_and_reload_policy_are_stable(
    error: object,
    message: str,
    reload_required: bool,
) -> None:
    assert message in views._command_conflict_message(error)  # type: ignore[arg-type]
    assert views._reload_required(error) is reload_required  # type: ignore[arg-type]


def test_post_preflight_rejects_query_before_loading_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(views, "_active_account", lambda _request: SimpleNamespace())
    monkeypatch.setattr(
        views,
        "_authorize_registration_route",
        lambda **_kwargs: (None, None, None, None),
    )
    with pytest.raises(views._RegistrationPostQueryParametersUnsupportedError):
        views._preflight_post(
            _request(query=True),
            organization_slug="organization",
            series_slug="series",
            edition_slug="edition",
        )


@pytest.mark.parametrize("action", ["update", "move", "delete"])
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (views._RegistrationPostQueryParametersUnsupportedError(), 400),
        (DatabaseError(), 503),
        (RegistrationSetupDependencyError(), 503),
        (RuntimeError(), 503),
    ],
)
def test_section_adapters_reject_preflight_failures_before_form_parsing(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    error: Exception,
    status: int,
) -> None:
    _patch_adapter(monkeypatch, action=action, command=lambda **_kwargs: None)
    monkeypatch.setattr(views, "_section_action_preflight", _raise(error))
    response = _invoke(action, _request())
    assert response.status_code == status


@pytest.mark.parametrize("action", ["update", "move", "delete"])
def test_section_adapters_return_bound_form_errors_without_calling_command(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    called = False

    def command(**_kwargs: object) -> None:
        nonlocal called
        called = True

    _patch_adapter(monkeypatch, action=action, command=command)
    StubSectionForm.valid = False
    try:
        response = _invoke(action, _request())
    finally:
        StubSectionForm.valid = True
    assert response.status_code == 400
    assert not called


@pytest.mark.parametrize("action", ["update", "move", "delete"])
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (RegistrationSetupVersionConflictError(), 409),
        (RegistrationSetupRetryConflictError(), 409),
        (RegistrationSetupLifecycleConflictError(), 409),
        (RegistrationSetupStateConflictError(), 409),
        (RegistrationSetupLimitExceededError(), 409),
        (ValidationError({"reason": ["Review reason."]}), 400),
        (ValidationError({"unknown": ["Unsafe field."]}), 503),
        (RegistrationSetupDependencyError(), 503),
        (DatabaseError(), 503),
        (RuntimeError(), 503),
    ],
)
def test_section_adapters_map_domain_and_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    error: Exception,
    status: int,
) -> None:
    _patch_adapter(monkeypatch, action=action, command=_raise(error))
    response = _invoke(action, _request())
    assert response.status_code == status


@pytest.mark.parametrize("action", ["update", "move", "delete"])
@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (RegistrationSetupAuthorizationDeniedError(), PermissionDenied),
        (RegistrationSetupConfigurationUnavailableError(), Http404),
        (RegistrationSetupSectionUnavailableError(), Http404),
    ],
)
def test_section_adapters_preserve_denial_and_non_disclosing_not_found(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    error: Exception,
    raised: type[Exception],
) -> None:
    _patch_adapter(monkeypatch, action=action, command=_raise(error))
    with pytest.raises(raised):
        _invoke(action, _request())


def test_delete_adapter_explains_a_protected_section_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_adapter(
        monkeypatch,
        action="delete",
        command=_raise(RegistrationSetupSectionDependencyError()),
    )
    response = _invoke("delete", _request())
    assert response.status_code == 409
    assert "referenced" in response.adapter_values["action_error"]  # type: ignore[attr-defined]


@pytest.mark.parametrize("action", ["update", "move", "delete"])
@pytest.mark.parametrize("replayed", [False, True])
def test_section_adapters_report_new_and_replayed_success(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    replayed: bool,
) -> None:
    _patch_adapter(
        monkeypatch,
        action=action,
        command=lambda **_kwargs: SimpleNamespace(replayed=replayed),
    )
    response = _invoke(action, _request())
    assert response.status_code == 302
    assert response["Cache-Control"] == "private, no-store"
