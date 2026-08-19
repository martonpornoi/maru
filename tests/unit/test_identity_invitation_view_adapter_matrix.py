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

from maru.identity import invitation_views as views
from maru.identity.invitation_commands import (
    InvitationAuthorizationDeniedError,
    InvitationChallengeInvalidError,
    InvitationDependencyUnavailableError,
    InvitationIdentityConflictError,
    InvitationRetryConflictError,
    InvitationStateConflictError,
    InvitationUnavailableError,
    InvitationVersionConflictError,
)
from maru.identity.invitation_queries import (
    AccountInventoryPage,
    PlatformAccountInventoryCursorStaleError,
    PlatformAccountInventoryDeniedError,
    PlatformAccountInventoryInputError,
    PlatformAccountInventoryLimitExceededError,
    PlatformAccountInventoryUnavailableError,
    PlatformAccountInvitationNotFoundError,
)


class StubForm:
    valid: ClassVar[bool] = True
    bound: ClassVar[bool] = True
    cleaned_template: ClassVar[dict[str, object]] = {
        "email": "invitee@example.invalid",
        "login_handle": "invitee",
        "display_name": "Synthetic Invitee",
        "preferred_language": "en",
        "reason": "Exercise the closed browser command adapter.",
        "expected_version": 3,
        "retry_key": UUID(int=7),
        "raw_token": "A" * 43,
        "new_password": "Synthetic-Password-7392!",
        "provider_reference": "provider-safe-reference",
    }

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.cleaned_data = dict(self.cleaned_template)
        self.is_bound = self.bound
        self.fields = {
            key: forms.CharField()
            for key in (
                "email",
                "login_handle",
                "display_name",
                "preferred_language",
                "reason",
                "expected_version",
                "retry_key",
                "raw_token",
                "new_password",
                "provider_reference",
            )
        }
        self.added_errors: list[tuple[str | None, object]] = []

    def is_valid(self) -> bool:
        return self.valid

    def add_error(self, field: str | None, error: object) -> None:
        self.added_errors.append((field, error))


def _response(*, status: int = 200, **values: object) -> HttpResponse:
    response = HttpResponse(status=status)
    response.adapter_values = values  # type: ignore[attr-defined]
    return response


def _raise(error: Exception):  # type: ignore[no-untyped-def]
    def raiser(*_args: object, **_kwargs: object) -> None:
        raise error

    return raiser


def _actor() -> SimpleNamespace:
    return SimpleNamespace(id=UUID(int=1), is_authenticated=True)


def _post_request(*, query: bool = False):  # type: ignore[no-untyped-def]
    suffix = "?unexpected=1" if query else ""
    request = RequestFactory().post(f"/accounts/invitations/action/{suffix}", data={})
    request.user = _actor()
    request.correlation_id = str(UUID(int=9))
    return request


def _get_request(*, query: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    request = RequestFactory().get("/accounts/invitations/", data=query or {})
    request.user = _actor()
    request.correlation_id = str(UUID(int=9))
    return request


def test_request_identifier_accepts_only_a_valid_uuid_string() -> None:
    valid = _get_request()
    valid.correlation_id = str(UUID(int=11))
    assert views._request_id(valid) == UUID(int=11)

    invalid = _get_request()
    invalid.correlation_id = "not-a-uuid"
    assert views._request_id(invalid) != UUID(int=11)

    absent = _get_request()
    del absent.correlation_id
    assert isinstance(views._request_id(absent), UUID)


def test_private_responses_set_all_required_non_cache_headers() -> None:
    response = views._private_no_store(HttpResponse())

    assert response["Cache-Control"] == "private, no-store"
    assert response["Pragma"] == "no-cache"
    assert response["X-Content-Type-Options"] == "nosniff"


def test_privileged_step_up_is_optional_but_always_can_force_it(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    settings.REQUIRE_PRIVILEGED_STEP_UP = False  # type: ignore[attr-defined]
    request = _get_request()
    actor = _actor()
    assert views._require_privileged_step_up(request, actor=actor) is None

    monkeypatch.setattr(
        views,
        "require_recent_step_up",
        lambda **_kwargs: (_ for _ in ()).throw(ValidationError("step-up required")),
    )
    monkeypatch.setattr(
        views,
        "_step_up_redirect",
        lambda *_args, **_kwargs: _response(status=302),
    )
    response = views._require_privileged_step_up(request, actor=actor, always=True)
    assert response is not None
    assert response.status_code == 302


class DomainForm(forms.Form):
    reason = forms.CharField()
    retry_key = forms.CharField(widget=forms.HiddenInput)
    new_password = forms.CharField()


def test_domain_validation_mapping_is_allowlisted_and_hides_hidden_fields() -> None:
    form = DomainForm(
        data={"reason": "valid", "retry_key": "valid", "new_password": "valid"}
    )
    assert form.is_valid()
    assert views._add_domain_validation_errors(
        form,
        ValidationError({"reason": ["Review reason."], "retry_key": ["Retry."]}),
        allowed_fields=frozenset({"reason", "retry_key"}),
    )
    assert "reason" in form.errors
    assert forms.forms.NON_FIELD_ERRORS in form.errors

    disallowed_form = DomainForm(
        data={"reason": "valid", "retry_key": "valid", "new_password": "valid"}
    )
    assert disallowed_form.is_valid()
    assert not views._add_domain_validation_errors(
        disallowed_form,
        ValidationError({"email": ["Must not disclose identity."]}),
        allowed_fields=frozenset({"reason"}),
    )

    password_form = DomainForm(
        data={"reason": "valid", "retry_key": "valid", "new_password": "valid"}
    )
    assert password_form.is_valid()
    assert views._add_domain_validation_errors(
        password_form,
        ValidationError("Password rejected."),
        allowed_fields=frozenset({"new_password"}),
    )
    assert "new_password" in password_form.errors


def test_inventory_pagination_preserves_only_closed_filter_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AccountInventoryPage(aggregate_version=3, items=(), next_cursor=None)
    assert views._inventory_next_url(page=page, cleaned={"search": "ignored"}) == ""

    monkeypatch.setattr(views, "reverse", lambda _name: "/accounts/")
    page = AccountInventoryPage(aggregate_version=3, items=(), next_cursor="cursor")
    url = views._inventory_next_url(
        page=page,
        cleaned={
            "search": "person",
            "search_mode": "prefix",
            "kind": "",
            "state": None,
            "forged": "must-not-survive",
        },
    )
    assert "search=person" in url
    assert "search_mode=prefix" in url
    assert "cursor=cursor" in url
    assert "forged" not in url


@pytest.mark.parametrize(
    ("error", "status", "state"),
    [
        (
            PlatformAccountInventoryInputError(
                field_name="search", detail_code="invalid"
            ),
            400,
            "invalid",
        ),
        (PlatformAccountInventoryCursorStaleError(), 409, "stale"),
        (PlatformAccountInventoryLimitExceededError(), 409, "limit_exceeded"),
        (PlatformAccountInventoryUnavailableError(), 503, "unavailable"),
    ],
)
def test_inventory_adapter_maps_bounded_query_failures_without_data_release(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
    state: str,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(views, "PlatformAccountInventoryFilterForm", StubForm)
    monkeypatch.setattr(views, "load_platform_account_inventory", _raise(error))
    monkeypatch.setattr(views, "_safe_dependency_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        views,
        "_inventory_error_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )

    response = inspect.unwrap(views.platform_account_inventory)(_get_request())

    assert response.status_code == status
    assert response.adapter_values["state"] == state  # type: ignore[attr-defined]


def test_inventory_adapter_preserves_denial_and_rejects_invalid_form_before_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(views, "PlatformAccountInventoryFilterForm", StubForm)
    monkeypatch.setattr(
        views,
        "_inventory_error_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    monkeypatch.setattr(
        views,
        "load_platform_account_inventory",
        _raise(PlatformAccountInventoryDeniedError()),
    )
    with pytest.raises(PermissionDenied):
        inspect.unwrap(views.platform_account_inventory)(_get_request())

    StubForm.valid = False
    try:
        response = inspect.unwrap(views.platform_account_inventory)(
            _get_request(query={"unknown": "value"})
        )
    finally:
        StubForm.valid = True
    assert response.status_code == 400


def test_inventory_adapter_returns_a_minimized_page_and_closed_next_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = AccountInventoryPage(aggregate_version=3, items=(), next_cursor="cursor")
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(views, "PlatformAccountInventoryFilterForm", StubForm)
    monkeypatch.setattr(
        views, "load_platform_account_inventory", lambda **_kwargs: page
    )
    monkeypatch.setattr(views, "_inventory_next_url", lambda **_kwargs: "/next/")
    monkeypatch.setattr(
        views,
        "_admin_response",
        lambda _request, _template, context, **kwargs: _response(
            context=context, **kwargs
        ),
    )

    response = inspect.unwrap(views.platform_account_inventory)(_get_request())

    context = response.adapter_values["context"]  # type: ignore[attr-defined]
    assert context["inventory"] is page
    assert context["account_inventory_state"] == "ready"
    assert context["next_page_url"] == "/next/"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvitationVersionConflictError(), ("changed after", True)),
        (InvitationRetryConflictError(), ("retry identifier", True)),
        (InvitationStateConflictError(), ("current state", True)),
        (RuntimeError(), ("safely", False)),
    ],
)
def test_invitation_action_conflicts_have_stable_non_disclosing_messages(
    error: Exception,
    expected: tuple[str, bool],
) -> None:
    message, reload_required = views._action_error_message(error)
    assert expected[0] in message
    assert reload_required is expected[1]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (InvitationVersionConflictError(), ("changed after", True)),
        (InvitationRetryConflictError(), ("retry identifier", True)),
        (InvitationStateConflictError(), ("current state", True)),
        (RuntimeError(), ("safely", False)),
    ],
)
def test_delivery_conflicts_have_stable_non_disclosing_messages(
    error: Exception,
    expected: tuple[str, bool],
) -> None:
    message, reload_required = views._delivery_reconciliation_error(error)
    assert expected[0] in message
    assert reload_required is expected[1]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (InvitationIdentityConflictError(), 409),
        (InvitationRetryConflictError(), 409),
        (InvitationStateConflictError(), 409),
        (InvitationVersionConflictError(), 409),
        (ValidationError({"reason": ["Review reason."]}), 400),
        (ValidationError({"unknown": ["Unsafe field."]}), 503),
        (InvitationDependencyUnavailableError(), 503),
        (DatabaseError(), 503),
    ],
)
def test_invitation_creation_maps_failures_without_enumerating_identity(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationForm", StubForm)
    monkeypatch.setattr(views, "create_platform_account_invitation", _raise(error))
    monkeypatch.setattr(views, "_safe_dependency_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        views,
        "_invitation_creation_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )

    response = inspect.unwrap(views.platform_account_invite)(_post_request())

    assert response.status_code == status


def test_invitation_creation_and_inventory_denials_remain_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationForm", StubForm)
    monkeypatch.setattr(
        views,
        "create_platform_account_invitation",
        _raise(InvitationAuthorizationDeniedError()),
    )
    with pytest.raises(PermissionDenied):
        inspect.unwrap(views.platform_account_invite)(_post_request())


def test_invitation_creation_rejects_query_and_invalid_form_before_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationForm", StubForm)
    monkeypatch.setattr(
        views,
        "_invitation_creation_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    response = inspect.unwrap(views.platform_account_invite)(
        _get_request(query={"email": "must-not-be-parsed@example.invalid"})
    )
    assert response.status_code == 400
    assert response.adapter_values["request_invalid"] is True  # type: ignore[attr-defined]

    StubForm.valid = False
    try:
        response = inspect.unwrap(views.platform_account_invite)(_post_request())
    finally:
        StubForm.valid = True
    assert response.status_code == 400


@pytest.mark.parametrize("replayed", [False, True])
def test_invitation_creation_reports_new_and_replayed_success(
    monkeypatch: pytest.MonkeyPatch,
    replayed: bool,
) -> None:
    invitation_id = uuid4()
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationForm", StubForm)
    monkeypatch.setattr(
        views,
        "create_platform_account_invitation",
        lambda **_kwargs: SimpleNamespace(
            replayed=replayed, invitation=SimpleNamespace(id=invitation_id)
        ),
    )
    success_messages: list[str] = []
    monkeypatch.setattr(
        views.messages,
        "success",
        lambda _request, message: success_messages.append(message),
    )

    response = inspect.unwrap(views.platform_account_invite)(_post_request())

    assert response.status_code == 302
    assert response["Cache-Control"] == "private, no-store"
    assert success_messages
    assert ("recovered" in success_messages[0]) is replayed


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PlatformAccountInventoryLimitExceededError(), 409),
        (PlatformAccountInventoryInputError(field_name="x", detail_code="x"), 400),
        (PlatformAccountInventoryCursorStaleError(), 400),
        (PlatformAccountInventoryUnavailableError(), 503),
    ],
)
def test_invitation_detail_maps_query_failures_without_partial_detail(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(views, "_load_invitation_detail", _raise(error))
    monkeypatch.setattr(views, "_safe_dependency_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        views,
        "_detail_error_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )

    response = views._render_invitation_detail(
        _get_request(), actor=_actor(), invitation_id=uuid4()
    )

    assert response.status_code == status


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (PlatformAccountInventoryDeniedError(), PermissionDenied),
        (PlatformAccountInvitationNotFoundError(), Http404),
    ],
)
def test_invitation_detail_preserves_denial_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    raised: type[Exception],
) -> None:
    monkeypatch.setattr(views, "_load_invitation_detail", _raise(error))
    with pytest.raises(raised):
        views._render_invitation_detail(
            _get_request(), actor=_actor(), invitation_id=uuid4()
        )


@pytest.mark.parametrize("reconciliation_required", [False, True])
def test_invitation_detail_builds_only_forms_allowed_by_current_delivery(
    monkeypatch: pytest.MonkeyPatch,
    reconciliation_required: bool,
) -> None:
    delivery = SimpleNamespace(
        aggregate_version=8,
        reconciliation_state=(
            views.PlatformIdentityDelivery.ReconciliationState.REQUIRED
            if reconciliation_required
            else "not_required"
        ),
    )
    detail = SimpleNamespace(invitation_version=4, current_delivery=delivery)
    monkeypatch.setattr(
        views, "_load_invitation_detail", lambda *_args, **_kwargs: detail
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationActionForm", StubForm)
    monkeypatch.setattr(views, "PlatformIdentityDeliveryDeliveredForm", StubForm)
    monkeypatch.setattr(views, "PlatformIdentityDeliveryRetryForm", StubForm)
    monkeypatch.setattr(
        views,
        "_admin_response",
        lambda _request, _template, context, **kwargs: _response(
            context=context, **kwargs
        ),
    )

    response = views._render_invitation_detail(
        _get_request(), actor=_actor(), invitation_id=uuid4()
    )

    context = response.adapter_values["context"]  # type: ignore[attr-defined]
    assert isinstance(context["reissue_form"], StubForm)
    assert isinstance(context["revoke_form"], StubForm)
    assert (context["delivery_delivered_form"] is not None) is reconciliation_required
    assert (context["delivery_retry_form"] is not None) is reconciliation_required


def test_invitation_detail_route_rejects_query_input_before_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views,
        "_detail_error_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    response = inspect.unwrap(views.platform_account_invitation_detail)(
        _get_request(query={"token": "must-not-be-read"}), uuid4()
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (InvitationVersionConflictError(), 409),
        (InvitationRetryConflictError(), 409),
        (InvitationStateConflictError(), 409),
        (ValidationError({"reason": ["Review reason."]}), 400),
        (ValidationError({"unknown": ["Unsafe field."]}), 503),
        (InvitationDependencyUnavailableError(), 503),
        (DatabaseError(), 503),
    ],
)
def test_invitation_lifecycle_action_maps_domain_and_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationActionForm", StubForm)
    monkeypatch.setattr(views, "_safe_dependency_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        views,
        "_render_invitation_detail",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    monkeypatch.setattr(
        views,
        "_detail_error_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )

    response = views._invitation_action(
        _post_request(),
        invitation_id=uuid4(),
        operation="reissue",
        command=_raise(error),
    )

    assert response.status_code == status


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (InvitationAuthorizationDeniedError(), PermissionDenied),
        (InvitationUnavailableError(), Http404),
    ],
)
def test_invitation_lifecycle_action_preserves_denial_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    raised: type[Exception],
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationActionForm", StubForm)
    with pytest.raises(raised):
        views._invitation_action(
            _post_request(),
            invitation_id=uuid4(),
            operation="revoke",
            command=_raise(error),
        )


def test_invitation_lifecycle_action_rejects_step_up_query_and_invalid_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationActionForm", StubForm)
    monkeypatch.setattr(
        views,
        "_detail_error_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    monkeypatch.setattr(
        views,
        "_render_invitation_detail",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    monkeypatch.setattr(
        views,
        "_require_privileged_step_up",
        lambda *_args, **_kwargs: _response(status=302),
    )
    response = views._invitation_action(
        _post_request(),
        invitation_id=uuid4(),
        operation="reissue",
        command=lambda **_: None,
    )
    assert response.status_code == 302

    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    response = views._invitation_action(
        _post_request(query=True),
        invitation_id=uuid4(),
        operation="reissue",
        command=lambda **_: None,
    )
    assert response.status_code == 400

    StubForm.valid = False
    try:
        response = views._invitation_action(
            _post_request(),
            invitation_id=uuid4(),
            operation="revoke",
            command=lambda **_: None,
        )
    finally:
        StubForm.valid = True
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("operation", "replayed"), [("reissue", False), ("revoke", True)]
)
def test_invitation_lifecycle_action_reports_success(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    replayed: bool,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "PlatformAccountInvitationActionForm", StubForm)
    success_messages: list[str] = []
    monkeypatch.setattr(
        views.messages,
        "success",
        lambda _request, message: success_messages.append(message),
    )
    response = views._invitation_action(
        _post_request(),
        invitation_id=uuid4(),
        operation=operation,
        command=lambda **_: SimpleNamespace(replayed=replayed),
    )
    assert response.status_code == 302
    assert success_messages


def test_reissue_and_revoke_routes_bind_only_their_closed_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def capture(_request: object, **kwargs: object) -> HttpResponse:
        calls.append((str(kwargs["operation"]), kwargs["command"]))
        return _response()

    monkeypatch.setattr(views, "_invitation_action", capture)
    inspect.unwrap(views.reissue_platform_account_invitation_view)(
        _post_request(), uuid4()
    )
    inspect.unwrap(views.revoke_platform_account_invitation_view)(
        _post_request(), uuid4()
    )
    assert calls == [
        ("reissue", views.reissue_platform_account_invitation),
        ("revoke", views.revoke_platform_account_invitation),
    ]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PlatformAccountInventoryLimitExceededError(), 409),
        (PlatformAccountInventoryInputError(field_name="x", detail_code="x"), 400),
        (PlatformAccountInventoryCursorStaleError(), 400),
        (PlatformAccountInventoryUnavailableError(), 503),
    ],
)
def test_delivery_reconciliation_preflight_maps_query_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "_load_invitation_detail", _raise(error))
    monkeypatch.setattr(views, "_safe_dependency_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        views,
        "_detail_error_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    response = views._delivery_reconciliation_preflight(
        _post_request(), actor=_actor(), invitation_id=uuid4(), delivery_id=uuid4()
    )
    assert isinstance(response, HttpResponse)
    assert response.status_code == status


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (PlatformAccountInventoryDeniedError(), PermissionDenied),
        (PlatformAccountInvitationNotFoundError(), Http404),
    ],
)
def test_delivery_reconciliation_preflight_preserves_denial_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    raised: type[Exception],
) -> None:
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(views, "_load_invitation_detail", _raise(error))
    with pytest.raises(raised):
        views._delivery_reconciliation_preflight(
            _post_request(), actor=_actor(), invitation_id=uuid4(), delivery_id=uuid4()
        )


def test_delivery_reconciliation_preflight_requires_current_exact_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery_id = uuid4()
    detail = SimpleNamespace(current_delivery=SimpleNamespace(delivery_id=delivery_id))
    monkeypatch.setattr(
        views, "_require_privileged_step_up", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        views, "_load_invitation_detail", lambda *_args, **_kwargs: detail
    )
    assert (
        views._delivery_reconciliation_preflight(
            _post_request(),
            actor=_actor(),
            invitation_id=uuid4(),
            delivery_id=delivery_id,
        )
        is detail
    )
    with pytest.raises(Http404):
        views._delivery_reconciliation_preflight(
            _post_request(),
            actor=_actor(),
            invitation_id=uuid4(),
            delivery_id=uuid4(),
        )


def _delivery_view(operation: str):  # type: ignore[no-untyped-def]
    return (
        views.resolve_platform_identity_delivery_as_delivered_view
        if operation == "delivery_delivered"
        else views.resolve_platform_identity_delivery_for_retry_view
    )


def _delivery_command_name(operation: str) -> str:
    return (
        "resolve_platform_identity_delivery_as_delivered"
        if operation == "delivery_delivered"
        else "resolve_platform_identity_delivery_for_retry"
    )


@pytest.mark.parametrize("operation", ["delivery_delivered", "delivery_retry"])
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (InvitationVersionConflictError(), 409),
        (InvitationRetryConflictError(), 409),
        (InvitationStateConflictError(), 409),
        (ValidationError({"reason": ["Review reason."]}), 400),
        (ValidationError({"unknown": ["Unsafe field."]}), 503),
        (InvitationDependencyUnavailableError(), 503),
        (DatabaseError(), 503),
    ],
)
def test_delivery_reconciliation_commands_map_failures(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    detail = SimpleNamespace(current_delivery=SimpleNamespace(aggregate_version=4))
    monkeypatch.setattr(
        views, "_delivery_reconciliation_preflight", lambda *_args, **_kwargs: detail
    )
    monkeypatch.setattr(views, "PlatformIdentityDeliveryDeliveredForm", StubForm)
    monkeypatch.setattr(views, "PlatformIdentityDeliveryRetryForm", StubForm)
    monkeypatch.setattr(views, _delivery_command_name(operation), _raise(error))
    monkeypatch.setattr(views, "_safe_dependency_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        views,
        "_render_invitation_detail",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    monkeypatch.setattr(
        views,
        "_detail_error_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )

    response = inspect.unwrap(_delivery_view(operation))(
        _post_request(), uuid4(), uuid4()
    )

    assert response.status_code == status


@pytest.mark.parametrize("operation", ["delivery_delivered", "delivery_retry"])
@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (InvitationAuthorizationDeniedError(), PermissionDenied),
        (InvitationUnavailableError(), Http404),
    ],
)
def test_delivery_reconciliation_commands_preserve_denial_and_not_found(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error: Exception,
    raised: type[Exception],
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    detail = SimpleNamespace(current_delivery=SimpleNamespace(aggregate_version=4))
    monkeypatch.setattr(
        views, "_delivery_reconciliation_preflight", lambda *_args, **_kwargs: detail
    )
    monkeypatch.setattr(views, "PlatformIdentityDeliveryDeliveredForm", StubForm)
    monkeypatch.setattr(views, "PlatformIdentityDeliveryRetryForm", StubForm)
    monkeypatch.setattr(views, _delivery_command_name(operation), _raise(error))
    with pytest.raises(raised):
        inspect.unwrap(_delivery_view(operation))(_post_request(), uuid4(), uuid4())


@pytest.mark.parametrize("operation", ["delivery_delivered", "delivery_retry"])
def test_delivery_reconciliation_rejects_preflight_and_invalid_form(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    monkeypatch.setattr(
        views,
        "_delivery_reconciliation_preflight",
        lambda *_args, **_kwargs: _response(status=302),
    )
    response = inspect.unwrap(_delivery_view(operation))(
        _post_request(), uuid4(), uuid4()
    )
    assert response.status_code == 302

    detail = SimpleNamespace(current_delivery=SimpleNamespace(aggregate_version=4))
    monkeypatch.setattr(
        views, "_delivery_reconciliation_preflight", lambda *_args, **_kwargs: detail
    )
    monkeypatch.setattr(views, "PlatformIdentityDeliveryDeliveredForm", StubForm)
    monkeypatch.setattr(views, "PlatformIdentityDeliveryRetryForm", StubForm)
    monkeypatch.setattr(
        views,
        "_render_invitation_detail",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    StubForm.valid = False
    try:
        response = inspect.unwrap(_delivery_view(operation))(
            _post_request(), uuid4(), uuid4()
        )
    finally:
        StubForm.valid = True
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("operation", "replayed"),
    [("delivery_delivered", False), ("delivery_retry", True)],
)
def test_delivery_reconciliation_reports_new_and_replayed_success(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    replayed: bool,
) -> None:
    monkeypatch.setattr(
        views, "_active_platform_administrator", lambda _request: _actor()
    )
    detail = SimpleNamespace(current_delivery=SimpleNamespace(aggregate_version=4))
    monkeypatch.setattr(
        views, "_delivery_reconciliation_preflight", lambda *_args, **_kwargs: detail
    )
    monkeypatch.setattr(views, "PlatformIdentityDeliveryDeliveredForm", StubForm)
    monkeypatch.setattr(views, "PlatformIdentityDeliveryRetryForm", StubForm)
    monkeypatch.setattr(
        views,
        _delivery_command_name(operation),
        lambda **_kwargs: SimpleNamespace(replayed=replayed),
    )
    success_messages: list[str] = []
    monkeypatch.setattr(
        views.messages,
        "success",
        lambda _request, message: success_messages.append(message),
    )
    response = inspect.unwrap(_delivery_view(operation))(
        _post_request(), uuid4(), uuid4()
    )
    assert response.status_code == 302
    assert success_messages


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (InvitationChallengeInvalidError(), 400),
        (InvitationStateConflictError(), 400),
        (InvitationUnavailableError(), 400),
        (InvitationRetryConflictError(), 409),
        (ValidationError({"new_password": ["Password rejected."]}), 400),
        (ValidationError({"unknown": ["Unsafe field."]}), 503),
        (InvitationDependencyUnavailableError(), 503),
        (DatabaseError(), 503),
    ],
)
def test_public_acceptance_maps_failures_without_reflecting_secret_input(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    monkeypatch.setattr(views, "AccountInvitationAcceptanceForm", StubForm)
    monkeypatch.setattr(views, "accept_platform_account_invitation", _raise(error))
    monkeypatch.setattr(
        views, "request_fingerprint", lambda _request: "safe-fingerprint"
    )
    monkeypatch.setattr(views, "_safe_dependency_log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        views,
        "_public_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    response = inspect.unwrap(views.accept_platform_account_invitation_view)(
        _post_request()
    )
    assert response.status_code == status


def test_public_acceptance_rejects_query_and_invalid_form_before_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(views, "AccountInvitationAcceptanceForm", StubForm)
    monkeypatch.setattr(
        views,
        "_public_response",
        lambda *_args, **kwargs: _response(**kwargs),
    )
    response = inspect.unwrap(views.accept_platform_account_invitation_view)(
        _get_request(query={"code": "must-not-be-reflected"})
    )
    assert response.status_code == 400
    assert response.adapter_values["request_invalid"] is True  # type: ignore[attr-defined]

    StubForm.valid = False
    try:
        response = inspect.unwrap(views.accept_platform_account_invitation_view)(
            _post_request()
        )
    finally:
        StubForm.valid = True
    assert response.status_code == 400


def test_public_acceptance_success_redirects_to_sign_in_without_secret_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(views, "AccountInvitationAcceptanceForm", StubForm)
    monkeypatch.setattr(
        views, "accept_platform_account_invitation", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        views, "request_fingerprint", lambda _request: "safe-fingerprint"
    )
    monkeypatch.setattr(views.messages, "success", lambda *_args, **_kwargs: None)
    response = inspect.unwrap(views.accept_platform_account_invitation_view)(
        _post_request()
    )
    assert response.status_code == 302
    assert response["Cache-Control"] == "private, no-store"
