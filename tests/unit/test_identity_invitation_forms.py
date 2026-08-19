from __future__ import annotations

from uuid import uuid4

import pytest
from django.http import QueryDict

from maru.identity.invitation_forms import (
    AccountInvitationAcceptanceForm,
    PlatformAccountInventoryFilterForm,
    PlatformAccountInvitationActionForm,
    PlatformAccountInvitationForm,
)


def test_account_inventory_filter_is_closed_and_normalizes_search() -> None:
    form = PlatformAccountInventoryFilterForm(
        {
            "search": "  CAFE\u0301  ",
            "search_mode": "prefix",
            "kind": "person",
            "state": "inactive",
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data == {
        "search": "caf\u00e9",
        "search_mode": "prefix",
        "kind": "person",
        "state": "inactive",
        "cursor": "",
    }

    forged = PlatformAccountInventoryFilterForm(
        {"search_mode": "prefix", "contains": "private@example.invalid"}
    )
    assert not forged.is_valid()
    assert forged.errors.as_data()["__all__"][0].code == "unknown_input_field"


def test_invitation_creation_form_normalizes_and_keeps_a_server_retry_key() -> None:
    retry_key = uuid4()
    form = PlatformAccountInvitationForm(
        {
            "email": "  RECIPIENT@EXAMPLE.INVALID  ",
            "login_handle": "Caf\u00e9Fox",
            "display_name": "  Cafe\u0301   Fox  ",
            "preferred_language": "en",
            "reason": "  Synthetic   Page 10 rehearsal.  ",
            "expected_version": "0",
            "retry_key": str(retry_key),
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["email"] == "recipient@example.invalid"
    assert form.cleaned_data["login_handle"] == "Caf\u00e9Fox"
    assert form.cleaned_data["display_name"] == "Caf\u00e9 Fox"
    assert form.cleaned_data["reason"] == "Synthetic Page 10 rehearsal."
    assert form.cleaned_data["expected_version"] == 0
    assert form.cleaned_data["retry_key"] == retry_key


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("organization_id", str(uuid4())),
        ("account_kind", "platform_administrator"),
        ("password", "administrator-chosen-password"),
    ],
)
def test_invitation_creation_form_rejects_client_owned_fields(
    field_name: str,
    value: str,
) -> None:
    data = {
        "email": "recipient@example.invalid",
        "preferred_language": "en",
        "reason": "Synthetic Page 10 rehearsal.",
        "expected_version": "0",
        "retry_key": str(uuid4()),
        field_name: value,
    }
    form = PlatformAccountInvitationForm(data)

    assert not form.is_valid()
    assert form.errors.as_data()["__all__"][0].code == "unknown_input_field"


def test_invitation_action_form_requires_positive_version_reason_and_uuid() -> None:
    retry_key = uuid4()
    form = PlatformAccountInvitationActionForm(
        {
            "expected_version": "7",
            "retry_key": str(retry_key),
            "reason": "  Recipient requested a fresh code.  ",
        },
        expected_version=1,
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["expected_version"] == 7
    assert form.cleaned_data["retry_key"] == retry_key
    assert form.cleaned_data["reason"] == "Recipient requested a fresh code."

    invalid = PlatformAccountInvitationActionForm(
        {
            "expected_version": "0",
            "retry_key": str(retry_key),
            "reason": "",
        },
        expected_version=1,
    )
    assert not invalid.is_valid()
    assert set(invalid.errors) == {"expected_version", "reason"}


def test_acceptance_form_never_redisplays_code_or_passwords() -> None:
    raw_token = "A" * 43
    password = "Synthetic-Secret-That-Must-Not-Render-1!"
    form = AccountInvitationAcceptanceForm(
        {
            "raw_token": raw_token,
            "new_password": password,
            "confirm_password": "Different-Synthetic-Secret-2!",
            "retry_key": str(uuid4()),
        }
    )

    assert not form.is_valid()
    rendered = form.as_div()
    assert raw_token not in rendered
    assert password not in rendered
    assert "The passwords do not match" in rendered
    assert 'value=""' not in rendered


def test_acceptance_unknown_field_names_and_invalid_retry_are_generic() -> None:
    raw_token = "B" * 43
    password = "Synthetic-Secret-That-Must-Not-Render-2!"
    form = AccountInvitationAcceptanceForm(
        {
            "raw_token": raw_token,
            "new_password": password,
            "confirm_password": password,
            "retry_key": raw_token,
            raw_token: "unknown field value",
        }
    )

    assert not form.is_valid()
    rendered = form.as_div()
    assert raw_token not in rendered
    assert password not in rendered
    assert "Remove unsupported input fields." in rendered
    assert "Remove unsupported input fields:" not in rendered


def test_acceptance_duplicate_values_are_rejected_without_naming_a_secret() -> None:
    payload = QueryDict(mutable=True)
    payload.setlist("raw_token", ["C" * 43, "D" * 43])
    payload["new_password"] = "Synthetic-Secret-3!"
    payload["confirm_password"] = "Synthetic-Secret-3!"
    payload["retry_key"] = str(uuid4())
    form = AccountInvitationAcceptanceForm(payload)

    assert not form.is_valid()
    rendered = form.as_div()
    assert "C" * 43 not in rendered
    assert "D" * 43 not in rendered
    assert "Synthetic-Secret-3!" not in rendered
    assert "Submit each field exactly once." in rendered
