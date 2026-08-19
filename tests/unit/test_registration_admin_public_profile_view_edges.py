"""Non-database adapter coverage for Registration public and profile surfaces."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.test import RequestFactory

from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account
from maru.registration import admin as registration_admin
from maru.registration import profile_extension_views, public_views
from maru.registration.models import (
    ConfigurationStatus,
    FinancialLedgerEntry,
    PaymentAttempt,
    Registration,
    TemplateStatus,
)
from maru.registration.profile_extension_values import (
    ProfileExtensionValueEvidenceConflictError,
    ProfileExtensionValueLimitExceededError,
    ProfileExtensionValueSequenceConflictError,
)


class StubForm:
    """Small form double that preserves validation and error behavior."""

    def __init__(
        self,
        *,
        valid: bool = True,
        cleaned_data: dict[str, object] | None = None,
    ) -> None:
        self._valid = valid
        self.cleaned_data = cleaned_data or {
            "value": "Quiet room requested",
            "expected_sequence": 2,
            "retry_key": UUID(int=40),
            "reason": "Attendee requested an update.",
            "target_product_id": UUID(int=41),
            "expected_registration_version": 3,
            "idempotency_key": UUID(int=42),
            "provider_account_id": UUID(int=43),
        }
        self.fields = {"value": object(), "reason": object()}
        self.added_errors: list[tuple[str | None, object]] = []

    def is_valid(self) -> bool:
        return self._valid

    def add_error(self, field: str | None, error: object) -> None:
        self.added_errors.append((field, error))


class StubQuery:
    """Chainable read-only queryset double for view boundary tests."""

    def __init__(self, *, first: object = None, rows: tuple[object, ...] = ()) -> None:
        self._first = first
        self._rows = rows

    def filter(self, *_args: object, **_kwargs: object) -> StubQuery:
        return self

    def exclude(self, *_args: object, **_kwargs: object) -> StubQuery:
        return self

    def select_related(self, *_args: object, **_kwargs: object) -> StubQuery:
        return self

    def prefetch_related(self, *_args: object, **_kwargs: object) -> StubQuery:
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> StubQuery:
        return self

    def first(self) -> object:
        return self._first

    def count(self) -> int:
        return len(self._rows)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._rows)


def _actor(*, identifier: int = 1) -> Account:
    return Account(
        id=UUID(int=identifier),
        email=f"registration-view-{identifier}@example.test",
        is_active=True,
        account_kind=Account.Kind.PERSON,
    )


def _request(
    method: str = "post",
    data: dict[str, object] | None = None,
    *,
    user: object | None = None,
) -> HttpRequest:
    request = getattr(RequestFactory(), method)("/registration/", data=data or {})
    request.user = user if user is not None else _actor()  # type: ignore[attr-defined]
    request.correlation_id = str(UUID(int=90))  # type: ignore[attr-defined]
    request.session = {}  # type: ignore[attr-defined]
    request._messages = FallbackStorage(request)  # type: ignore[attr-defined]
    return request


def _registration(*, actor: Account | None = None) -> SimpleNamespace:
    account = actor or _actor()
    return SimpleNamespace(
        id=UUID(int=10),
        account=account,
        account_id=account.id,
        organization_id=UUID(int=11),
        edition_id=UUID(int=12),
        aggregate_version=3,
    )


def _authorization_denied() -> AuthorizationDenied:
    return AuthorizationDenied("Denied.", reason_code="permission_absent")


def _raise(error: Exception):  # type: ignore[no-untyped-def]
    def raiser(*_args: object, **_kwargs: object) -> None:
        raise error

    return raiser


def _message_texts(request: HttpRequest) -> list[str]:
    return [str(message) for message in get_messages(request)]


def test_admin_answer_and_empty_projection_helpers_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert registration_admin._display_answer([]) == "Not answered"
    assert registration_admin._display_answer(["red", "blue"]) == "red, blue"
    assert registration_admin._display_answer({"size": "large"}) == "size: large"
    assert "No submitted form" in str(registration_admin._submitted_answers_table(None))
    assert str(registration_admin._linked_list([])) == "<span>None</span>"

    generated = UUID(int=99)
    monkeypatch.setattr(registration_admin, "uuid4", lambda: generated)
    assert (
        registration_admin._request_correlation_id(
            SimpleNamespace(correlation_id="not-a-uuid")
        )
        == generated
    )


def test_admin_profile_value_link_policy_fails_closed_for_self_or_non_account() -> None:
    actor = _actor()
    registration = _registration(actor=actor)

    assert not registration_admin._can_open_profile_extension_values(
        SimpleNamespace(user=actor), registration
    )
    assert not registration_admin._can_open_profile_extension_values(
        SimpleNamespace(user=SimpleNamespace(id=UUID(int=2))), registration
    )


@pytest.mark.parametrize(
    ("inline_type", "draft_status"),
    [
        (registration_admin.TemplateSectionInline, TemplateStatus.DRAFT),
        (registration_admin.TemplateQuestionInline, TemplateStatus.DRAFT),
        (registration_admin.TemplateProductInline, TemplateStatus.DRAFT),
        (registration_admin.RegistrationQuestionInline, ConfigurationStatus.DRAFT),
        (registration_admin.AdmissionProductInline, ConfigurationStatus.DRAFT),
        (registration_admin.RegistrationSectionInline, ConfigurationStatus.DRAFT),
    ],
)
def test_admin_inline_fields_freeze_outside_draft(
    inline_type: type,
    draft_status: str,
) -> None:
    receiver = SimpleNamespace(fields=inline_type.fields)
    request = SimpleNamespace()

    assert (
        inline_type.get_readonly_fields(
            receiver, request, SimpleNamespace(status="active")
        )
        == inline_type.fields
    )
    assert (
        inline_type.get_readonly_fields(
            receiver, request, SimpleNamespace(status=draft_status)
        )
        == ()
    )


def test_admin_registration_summary_helpers_cover_account_and_payment_states() -> None:
    receiver = SimpleNamespace()
    account = SimpleNamespace(
        is_active=False,
        restrictions=MagicMock(),
    )
    account.restrictions.filter.return_value.exists.return_value = False
    registration = SimpleNamespace(
        account=account,
        price_minor_snapshot=12_345,
        currency_snapshot="HUF",
    )

    assert registration_admin.RegistrationAdmin.person(receiver, registration)
    assert (
        registration_admin.RegistrationAdmin.price(receiver, registration)
        == "123.45 HUF"
    )
    assert (
        registration_admin.RegistrationAdmin.account_state(receiver, registration)
        == "Inactive"
    )

    account.is_active = True
    account.restrictions.filter.return_value.exists.return_value = True
    assert (
        registration_admin.RegistrationAdmin.account_state(receiver, registration)
        == "Restricted"
    )
    account.restrictions.filter.return_value.exists.return_value = False
    assert (
        registration_admin.RegistrationAdmin.account_state(receiver, registration)
        == "Active"
    )

    entitlements = MagicMock()
    entitlements.filter.return_value.exists.return_value = True
    assert registration_admin.RegistrationAdmin.is_infinity_holder(
        receiver, SimpleNamespace(entitlements=entitlements)
    )

    paid = SimpleNamespace(
        financial_ledger=SimpleNamespace(all=lambda: ()),
        payment_attempts=SimpleNamespace(
            all=lambda: (
                SimpleNamespace(
                    amount_minor=2_500,
                    status=PaymentAttempt.Status.SUCCEEDED,
                ),
                SimpleNamespace(amount_minor=999, status=PaymentAttempt.Status.PENDING),
            )
        ),
        currency_snapshot="HUF",
    )
    assert (
        registration_admin.RegistrationAdmin.paid_amount(receiver, paid) == "25.00 HUF"
    )

    ledger_paid = SimpleNamespace(
        financial_ledger=SimpleNamespace(
            all=lambda: (
                SimpleNamespace(
                    amount_minor=3_000,
                    kind=FinancialLedgerEntry.Kind.PAYMENT,
                    direction=FinancialLedgerEntry.Direction.INFLOW,
                ),
            )
        ),
        payment_attempts=SimpleNamespace(all=lambda: ()),
        currency_snapshot="HUF",
    )
    assert (
        registration_admin.RegistrationAdmin.paid_amount(receiver, ledger_paid)
        == "30.00 HUF"
    )


def test_profile_extension_helpers_use_safe_request_and_error_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = UUID(int=91)
    monkeypatch.setattr(profile_extension_views, "uuid4", lambda: generated)
    assert (
        profile_extension_views._request_id(
            SimpleNamespace(correlation_id="not-a-correlation-id")
        )
        == generated
    )

    response = profile_extension_views._plain_error("Unavailable", status=503)
    assert response.status_code == 503
    assert response["Cache-Control"] == "private, no-store"
    assert response["Pragma"] == "no-cache"
    assert response["X-Content-Type-Options"] == "nosniff"

    with pytest.raises(Http404):
        profile_extension_views._active_person(
            SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
        )


def test_profile_extension_staff_lookup_hides_unknown_edition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = StubQuery(first=None)
    monkeypatch.setattr(
        profile_extension_views,
        "EventEdition",
        SimpleNamespace(objects=query),
    )

    with pytest.raises(Http404):
        profile_extension_views._staff_registration(
            organization_slug="hidden",
            series_slug="hidden",
            edition_slug="hidden",
            registration_id=UUID(int=1),
        )


def test_profile_extension_command_validation_maps_known_and_unknown_fields() -> None:
    form = StubForm()
    profile_extension_views._add_command_errors(
        form,  # type: ignore[arg-type]
        ValidationError({"value": ["Invalid value."], "server_owned": ["Rejected."]}),
    )
    assert form.added_errors == [
        ("value", "Invalid value."),
        (None, "Rejected."),
    ]

    list_form = StubForm()
    profile_extension_views._add_command_errors(
        list_form,  # type: ignore[arg-type]
        ValidationError(["First error.", "Second error."]),
    )
    assert list_form.added_errors == [
        (None, "First error."),
        (None, "Second error."),
    ]


def _append_boundary_values(
    *,
    form: StubForm,
    staff: bool = False,
) -> dict[str, object]:
    return {
        "request": _request(),
        "actor": _actor(),
        "registration": _registration(),
        "workspace": SimpleNamespace(fields=()),
        "projection": SimpleNamespace(field_id=UUID(int=31)),
        "form": form,
        "staff": staff,
        "correlation_id": UUID(int=32),
    }


def test_profile_extension_invalid_form_renders_the_bound_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    form = StubForm(valid=False)
    seen: dict[str, object] = {}

    def respond(_request: HttpRequest, **kwargs: object) -> HttpResponse:
        seen.update(kwargs)
        return HttpResponse("invalid", status=400)

    monkeypatch.setattr(profile_extension_views, "_self_response", respond)
    response = profile_extension_views._append_or_render_error(
        **_append_boundary_values(form=form)  # type: ignore[arg-type]
    )

    assert response is not None
    assert response.status_code == 400
    assert seen["bound_form"] is form
    assert seen["bound_field_id"] == UUID(int=31)


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ValidationError({"value": ["Rejected by the command."]}), 400),
        (ProfileExtensionValueSequenceConflictError("stale"), 409),
        (DatabaseError("dependency unavailable"), 503),
        (ProfileExtensionValueEvidenceConflictError("incomplete evidence"), 503),
    ],
)
def test_profile_extension_append_errors_are_minimized_and_actionable(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
) -> None:
    form = StubForm()
    monkeypatch.setattr(
        profile_extension_views,
        "append_profile_extension_value",
        _raise(error),
    )
    monkeypatch.setattr(
        profile_extension_views,
        "_self_response",
        lambda *_args, **kwargs: HttpResponse("form", status=kwargs["status"]),
    )

    response = profile_extension_views._append_or_render_error(
        **_append_boundary_values(form=form)  # type: ignore[arg-type]
    )

    assert response is not None
    assert response.status_code == expected_status
    if expected_status == 503:
        assert response.content == b"Profile extensions are temporarily unavailable."
        assert response["Cache-Control"] == "private, no-store"


def test_profile_extension_append_hides_authorization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        profile_extension_views,
        "append_profile_extension_value",
        _raise(_authorization_denied()),
    )

    with pytest.raises(Http404):
        profile_extension_views._append_or_render_error(
            **_append_boundary_values(form=StubForm())  # type: ignore[arg-type]
        )


def _patch_profile_read_scope(
    monkeypatch: pytest.MonkeyPatch,
    *,
    staff: bool = False,
) -> tuple[Account, SimpleNamespace]:
    actor = _actor()
    registration = _registration(actor=actor)
    monkeypatch.setattr(
        profile_extension_views, "_active_person", lambda _request: actor
    )
    lookup = "_staff_registration" if staff else "_owned_registration"
    monkeypatch.setattr(
        profile_extension_views,
        lookup,
        lambda **_kwargs: registration,
    )
    return actor, registration


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ProfileExtensionValueLimitExceededError("limit"), 409),
        (DatabaseError("database"), 503),
    ],
)
def test_self_profile_extension_read_maps_bounded_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
) -> None:
    _patch_profile_read_scope(monkeypatch)
    monkeypatch.setattr(profile_extension_views, "_read_workspace", _raise(error))

    response = profile_extension_views.my_profile_extension_values(
        _request("get"), UUID(int=12)
    )

    assert response.status_code == expected_status
    assert "no-store" in response["Cache-Control"]


def test_self_profile_extension_read_rejects_query_input_before_scope_lookup() -> None:
    response = profile_extension_views.my_profile_extension_values(
        _request("get", {"registration_id": "client-owned"}),
        UUID(int=12),
    )

    assert response.status_code == 400
    assert response.content == b"Unsupported query parameters."
    assert "no-store" in response["Cache-Control"]


def test_self_profile_extension_read_hides_authorization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_profile_read_scope(monkeypatch)
    monkeypatch.setattr(
        profile_extension_views,
        "_read_workspace",
        _raise(_authorization_denied()),
    )

    with pytest.raises(Http404):
        profile_extension_views.my_profile_extension_values(
            _request("get"), UUID(int=12)
        )


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ProfileExtensionValueLimitExceededError("limit"), 409),
        (DatabaseError("database"), 503),
    ],
)
def test_staff_profile_extension_read_maps_bounded_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
) -> None:
    _patch_profile_read_scope(monkeypatch, staff=True)
    monkeypatch.setattr(profile_extension_views, "_read_workspace", _raise(error))

    response = profile_extension_views.staff_profile_extension_values(
        _request("get"),
        "org",
        "series",
        "edition",
        UUID(int=10),
    )

    assert response.status_code == expected_status
    assert "no-store" in response["Cache-Control"]


def test_staff_profile_extension_read_rejects_query_input_before_scope_lookup() -> None:
    response = profile_extension_views.staff_profile_extension_values(
        _request("get", {"account_id": "client-owned"}),
        "org",
        "series",
        "edition",
        UUID(int=10),
    )

    assert response.status_code == 400
    assert response.content == b"Unsupported query parameters."


@pytest.mark.parametrize("staff", [False, True])
def test_profile_extension_update_maps_scope_dependency_failures(
    monkeypatch: pytest.MonkeyPatch,
    staff: bool,
) -> None:
    _patch_profile_read_scope(monkeypatch, staff=staff)
    monkeypatch.setattr(
        profile_extension_views,
        "authorize_profile_extension_value_write_scope",
        _raise(DatabaseError("database")),
    )

    if staff:
        response = profile_extension_views.update_staff_profile_extension_value(
            _request(),
            "org",
            "series",
            "edition",
            UUID(int=10),
            UUID(int=31),
        )
    else:
        response = profile_extension_views.update_my_profile_extension_value(
            _request(), UUID(int=12), UUID(int=31)
        )

    assert response.status_code == 503
    assert response.content == b"Profile extensions are temporarily unavailable."


def test_self_profile_extension_update_hides_denied_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_profile_read_scope(monkeypatch)
    monkeypatch.setattr(
        profile_extension_views,
        "authorize_profile_extension_value_write_scope",
        _raise(_authorization_denied()),
    )

    with pytest.raises(Http404):
        profile_extension_views.update_my_profile_extension_value(
            _request(), UUID(int=12), UUID(int=31)
        )


def test_staff_profile_extension_update_returns_bound_form_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_profile_read_scope(monkeypatch, staff=True)
    workspace = SimpleNamespace(fields=())
    projection = SimpleNamespace(field_id=UUID(int=31))
    expected = HttpResponse("stale", status=409)
    monkeypatch.setattr(
        profile_extension_views,
        "authorize_profile_extension_value_write_scope",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        profile_extension_views,
        "_read_workspace",
        lambda **_kwargs: workspace,
    )
    monkeypatch.setattr(
        profile_extension_views,
        "_projection_for_write",
        lambda *_args, **_kwargs: projection,
    )
    monkeypatch.setattr(
        profile_extension_views,
        "StaffProfileExtensionValueForm",
        lambda *_args, **_kwargs: StubForm(),
    )
    monkeypatch.setattr(
        profile_extension_views,
        "_append_or_render_error",
        lambda **_kwargs: expected,
    )

    response = profile_extension_views.update_staff_profile_extension_value(
        _request(),
        "org",
        "series",
        "edition",
        UUID(int=10),
        UUID(int=31),
    )

    assert response is expected


def test_local_demo_payment_fails_closed_for_method_actor_and_form(
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
) -> None:
    settings.DEMO_PAYMENT_ADAPTER_ENABLED = True
    with pytest.raises(Http404):
        public_views.confirm_local_demo_payment(_request("get"), UUID(int=12))

    non_account = SimpleNamespace(is_authenticated=True)
    with pytest.raises(Http404):
        public_views.confirm_local_demo_payment(
            _request(user=non_account), UUID(int=12)
        )

    monkeypatch.setattr(
        public_views, "get_object_or_404", lambda *_a, **_kw: _registration()
    )
    monkeypatch.setattr(
        public_views,
        "DemoPaymentForm",
        lambda *_args, **_kwargs: StubForm(valid=False),
    )
    with pytest.raises(Http404):
        public_views.confirm_local_demo_payment(
            _request(data={"unexpected": "field"}), UUID(int=12)
        )


def test_local_demo_payment_hides_service_validation(
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
) -> None:
    settings.DEMO_PAYMENT_ADAPTER_ENABLED = True
    monkeypatch.setattr(
        public_views, "get_object_or_404", lambda *_a, **_kw: _registration()
    )
    monkeypatch.setattr(
        public_views,
        "DemoPaymentForm",
        lambda *_args, **_kwargs: StubForm(),
    )
    monkeypatch.setattr(
        public_views,
        "confirm_demo_payment",
        _raise(ValidationError("stale payment")),
    )

    with pytest.raises(Http404):
        public_views.confirm_local_demo_payment(
            _request(data={"idempotency_key": str(UUID(int=42))}),
            UUID(int=12),
        )


def test_tier_replacement_fails_closed_and_reports_stale_offer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(Http404):
        public_views.reserve_local_tier_replacement(_request("get"), UUID(int=12))
    with pytest.raises(Http404):
        public_views.reserve_local_tier_replacement(
            _request(user=SimpleNamespace(is_authenticated=True)), UUID(int=12)
        )

    monkeypatch.setattr(
        public_views, "get_object_or_404", lambda *_a, **_kw: _registration()
    )
    monkeypatch.setattr(
        public_views,
        "TierReplacementReservationForm",
        lambda *_args, **_kwargs: StubForm(),
    )
    monkeypatch.setattr(
        public_views,
        "reserve_admission_tier_replacement",
        _raise(ObjectDoesNotExist("offer unavailable")),
    )
    request = _request()

    response = public_views.reserve_local_tier_replacement(request, UUID(int=12))

    assert response.status_code == 302
    assert _message_texts(request) == ["That admission upgrade is no longer available."]


def _patch_hosted_payment_form(
    monkeypatch: pytest.MonkeyPatch,
    form: StubForm,
) -> None:
    monkeypatch.setattr(
        public_views, "get_object_or_404", lambda *_a, **_kw: _registration()
    )
    monkeypatch.setattr(
        public_views,
        "HostedPaymentStartForm",
        lambda *_args, **_kwargs: form,
    )


def test_hosted_payment_fails_closed_for_method_and_actor() -> None:
    with pytest.raises(Http404):
        public_views.create_local_hosted_payment(_request("get"), UUID(int=12))
    with pytest.raises(Http404):
        public_views.create_local_hosted_payment(
            _request(user=SimpleNamespace(is_authenticated=True)), UUID(int=12)
        )


def test_hosted_payment_invalid_form_uses_prg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hosted_payment_form(monkeypatch, StubForm(valid=False))
    request = _request(data={"provider_account_id": "bad"})

    response = public_views.create_local_hosted_payment(request, UUID(int=12))

    assert response.status_code == 302
    assert _message_texts(request) == ["The payment request was invalid."]


def test_hosted_payment_hides_unavailable_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hosted_payment_form(monkeypatch, StubForm())
    monkeypatch.setattr(
        public_views,
        "create_payment_intent",
        _raise(ValidationError("provider secret detail")),
    )
    request = _request()

    response = public_views.create_local_hosted_payment(request, UUID(int=12))

    assert response.status_code == 302
    assert _message_texts(request) == ["Hosted payment is not available right now."]


@pytest.mark.parametrize(
    ("checkout_url", "expected_location", "expected_message"),
    [
        (
            "",
            "/register/00000000-0000-0000-0000-00000000000c/profile/",
            "Hosted payment is waiting for reconciliation.",
        ),
        (
            "https://payments.example.test/checkout/1",
            "https://payments.example.test/checkout/1",
            None,
        ),
    ],
)
def test_hosted_payment_redirects_only_to_a_confirmed_checkout_url(
    monkeypatch: pytest.MonkeyPatch,
    checkout_url: str,
    expected_location: str,
    expected_message: str | None,
) -> None:
    _patch_hosted_payment_form(monkeypatch, StubForm())
    monkeypatch.setattr(
        public_views,
        "create_payment_intent",
        lambda **_kwargs: SimpleNamespace(checkout_url=checkout_url),
    )
    request = _request()

    response = public_views.create_local_hosted_payment(request, UUID(int=12))

    assert response.status_code == 302
    assert response["Location"] == expected_location
    assert _message_texts(request) == ([expected_message] if expected_message else [])


def test_tier_replacement_options_skip_policy_denial_and_full_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied_product = SimpleNamespace(id=UUID(int=51), price_minor=20_000)
    full_product = SimpleNamespace(id=UUID(int=52), price_minor=25_000)
    products = MagicMock()
    products.filter.return_value.order_by.return_value = (denied_product, full_product)
    registration = SimpleNamespace(
        state=Registration.State.CONFIRMED,
        confirmation_basis=Registration.ConfirmationBasis.PROVIDER,
        configuration=SimpleNamespace(products=products),
        product=SimpleNamespace(price_minor=10_000),
        aggregate_version=4,
    )
    monkeypatch.setattr(
        public_views,
        "assess_product_availability",
        lambda *, product, **_kwargs: SimpleNamespace(
            selectable=False,
            code="not_eligible" if product is denied_product else "capacity_reached",
        ),
    )
    registration_query = StubQuery(rows=(object(), object()))
    monkeypatch.setattr(
        public_views,
        "Registration",
        SimpleNamespace(
            State=Registration.State,
            ConfirmationBasis=Registration.ConfirmationBasis,
            objects=registration_query,
        ),
    )
    monkeypatch.setattr(
        public_views, "pending_target_capacity_holds", lambda *_a, **_kw: 1
    )
    monkeypatch.setattr(public_views, "effective_product_capacity", lambda _product: 3)

    assert (
        public_views._tier_replacement_options(
            registration=registration,
            account=_actor(),
        )
        == ()
    )


def test_submitted_groups_ignore_non_object_legacy_schema_entries() -> None:
    registration = SimpleNamespace(
        submission=SimpleNamespace(
            schema_snapshot=(
                "legacy-row",
                {
                    "key": "quiet_room",
                    "label": "Quiet room",
                    "section": {"key": "access", "title": "Access"},
                },
            ),
            answers={"quiet_room": True},
        )
    )

    assert public_views._submitted_groups(registration) == [
        {
            "title": "Access",
            "description": "",
            "answers": [{"label": "Quiet room", "value": "Yes"}],
        }
    ]


def test_profile_edit_hides_unknown_profile_and_maps_command_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_query = StubQuery(first=None)
    monkeypatch.setattr(
        public_views,
        "AttendeeRegistrationProfile",
        SimpleNamespace(objects=missing_query),
    )
    with pytest.raises(Http404):
        public_views.edit_attendee_profile(_request("get"), UUID(int=12))

    profile = SimpleNamespace(
        organization_id=UUID(int=11),
        edition_id=UUID(int=12),
        registration=SimpleNamespace(configuration=SimpleNamespace()),
        brings_fursuits=False,
    )
    monkeypatch.setattr(
        public_views,
        "AttendeeRegistrationProfile",
        SimpleNamespace(objects=StubQuery(first=profile)),
    )
    monkeypatch.setattr(public_views, "profile_is_editable", lambda _profile: True)
    monkeypatch.setattr(public_views, "_profile_initial", lambda *_a, **_kw: {})
    monkeypatch.setattr(public_views, "_fursuit_initial", lambda *_a, **_kw: [])
    form = StubForm(valid=True)
    formset = SimpleNamespace(is_valid=lambda: True)
    monkeypatch.setattr(
        public_views,
        "AttendeeProfileForm",
        lambda *_args, **_kwargs: form,
    )
    monkeypatch.setattr(
        public_views,
        "attendee_fursuit_formset",
        lambda *_args, **_kwargs: formset,
    )
    monkeypatch.setattr(public_views, "_profile_input", lambda *_args: "profile-input")
    monkeypatch.setattr(
        public_views,
        "update_attendee_profile",
        _raise(ValidationError("Profile version changed.")),
    )

    response = public_views.edit_attendee_profile(_request(), UUID(int=12))

    assert response.status_code == 200
    assert form.added_errors == [(None, "Profile version changed.")]


def test_profile_edit_rejects_non_account_before_query() -> None:
    with pytest.raises(Http404):
        public_views.edit_attendee_profile(
            _request("get", user=SimpleNamespace(is_authenticated=True)), UUID(int=12)
        )


def test_public_directory_dependency_failure_releases_no_extension_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edition = SimpleNamespace(id=UUID(int=12), organization_id=UUID(int=11))
    monkeypatch.setattr(public_views, "get_object_or_404", lambda *_a, **_kw: edition)
    monkeypatch.setattr(
        public_views,
        "AttendeeRegistrationProfile",
        SimpleNamespace(objects=StubQuery(rows=())),
    )
    monkeypatch.setattr(
        public_views,
        "read_directory_profile_extension_values",
        _raise(DatabaseError("database")),
    )

    response = public_views.public_attendee_directory(_request("get"), edition.id)

    assert response.context_data["public_profiles"] == []


def test_moderator_preview_requires_current_policy_and_audits_allow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = _actor()
    audits: list[object] = []
    monkeypatch.setattr(
        public_views,
        "decide",
        lambda **_kwargs: SimpleNamespace(
            allowed=True,
            reason_code="exact_edition_grant",
            obligations=frozenset({"audit"}),
        ),
    )
    monkeypatch.setattr(
        public_views,
        "resolve_edition_target",
        lambda **_kwargs: "edition-target",
    )
    monkeypatch.setattr(public_views, "append_audit", audits.append)

    assert public_views._moderator_access(
        request=_request("get", user=actor),
        organization_id=UUID(int=11),
        edition_id=UUID(int=12),
        target_type="registration.attendee_profile",
        target_id=UUID(int=13),
    )
    assert len(audits) == 1


@pytest.mark.parametrize(
    ("view", "model_name", "identifier_name"),
    [
        (
            public_views.protected_profile_photo,
            "AttendeeRegistrationProfile",
            "profile_id",
        ),
        (public_views.protected_fursuit_photo, "AttendeeFursuit", "fursuit_id"),
    ],
)
def test_protected_media_hides_missing_records(
    monkeypatch: pytest.MonkeyPatch,
    view: object,
    model_name: str,
    identifier_name: str,
) -> None:
    monkeypatch.setattr(
        public_views,
        model_name,
        SimpleNamespace(objects=StubQuery(first=None)),
    )

    with pytest.raises(Http404):
        view(_request("get"), **{identifier_name: uuid4()})  # type: ignore[operator]
