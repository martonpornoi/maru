"""Closed browser forms for governed platform account invitations."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.identity.invitation_delivery_payload import INVITATION_TOKEN_LENGTH
from maru.identity.invitation_delivery_reconciliation import (
    MAX_PROVIDER_REFERENCE_LENGTH,
)
from maru.identity.invitation_inputs import (
    MAX_INVITATION_DISPLAY_NAME_LENGTH,
    MAX_INVITATION_EMAIL_LENGTH,
    MAX_INVITATION_LOGIN_HANDLE_LENGTH,
    MAX_INVITATION_REASON_LENGTH,
    SUPPORTED_INVITATION_LANGUAGE_CODES,
    normalize_invitation_display_name,
    normalize_invitation_email,
    normalize_invitation_login_handle,
    normalize_invitation_preferred_language,
    normalize_invitation_reason,
)
from maru.identity.invitation_queries import (
    ACCOUNT_INVENTORY_KINDS,
    ACCOUNT_INVENTORY_SEARCH_MODES,
    ACCOUNT_INVENTORY_STATES,
    MAX_ACCOUNT_INVENTORY_CURSOR_LENGTH,
    MAX_ACCOUNT_INVENTORY_SEARCH_LENGTH,
    normalize_account_inventory_search,
)

_INVITATION_TOKEN_PATTERN = re.compile(
    rf"[A-Za-z0-9_-]{{{INVITATION_TOKEN_LENGTH}}}\Z",
    flags=re.ASCII,
)


def _field_local_result(
    field_name: str,
    operation: Callable[[], str | None],
) -> str | None:
    """Translate a pure dict-shaped domain error to one browser field."""

    try:
        return operation()
    except ValidationError as error:
        field_errors = getattr(error, "error_dict", {}).get(field_name)
        if not field_errors:
            raise forms.ValidationError(
                "Review this value and try again.",
                code="account_invitation_field_invalid",
            ) from error
        raise forms.ValidationError(field_errors) from error


class NeverRedisplayTextInput(forms.TextInput):
    """Accept one submitted secret without reflecting it into response HTML."""

    def format_value(self, value: object) -> None:
        del value


class CanonicalUUIDHiddenInput(forms.HiddenInput):
    """Reflect only a parsed canonical UUID, never arbitrary submitted text."""

    def format_value(self, value: object) -> str | None:
        if isinstance(value, UUID):
            return str(value)
        if not isinstance(value, str):
            return None
        try:
            parsed = UUID(value)
        except ValueError:
            return None
        return value if str(parsed) == value else None


class PlatformAccountInventoryFilterForm(StrictInputForm):
    """Bounded GET filters; cursor is accepted but never rendered in the form."""

    search = forms.CharField(
        label="Search accounts",
        required=False,
        strip=False,
        max_length=MAX_ACCOUNT_INVENTORY_SEARCH_LENGTH,
        help_text=(
            "Enter at least 2 characters from an email address, username, or "
            "display name. Search is case-insensitive."
        ),
        widget=forms.SearchInput(
            attrs={
                "autocomplete": "off",
                "maxlength": MAX_ACCOUNT_INVENTORY_SEARCH_LENGTH,
            }
        ),
    )
    search_mode = forms.ChoiceField(
        label="Match",
        choices=(("prefix", "Starts with"), ("exact", "Exact")),
        initial="prefix",
    )
    kind = forms.ChoiceField(
        label="Account kind",
        required=False,
        choices=(
            ("", "All account kinds"),
            ("person", "Person"),
            ("platform_administrator", "Platform administrator"),
        ),
    )
    state = forms.ChoiceField(
        label="Account state",
        required=False,
        choices=(
            ("", "All states"),
            ("active", "Active"),
            ("inactive", "Inactive"),
        ),
    )
    cursor = forms.CharField(
        required=False,
        max_length=MAX_ACCOUNT_INVENTORY_CURSOR_LENGTH,
        widget=forms.HiddenInput,
    )

    def clean_search(self) -> str | None:
        return normalize_account_inventory_search(
            self.cleaned_data.get("search"),
        )

    def clean_search_mode(self) -> str:
        value = str(self.cleaned_data["search_mode"])
        if value not in ACCOUNT_INVENTORY_SEARCH_MODES:
            raise forms.ValidationError("Choose a supported match mode.")
        return value

    def clean_kind(self) -> str | None:
        value = str(self.cleaned_data.get("kind", ""))
        if not value:
            return None
        if value not in ACCOUNT_INVENTORY_KINDS:
            raise forms.ValidationError("Choose a supported account kind.")
        return value

    def clean_state(self) -> str | None:
        value = str(self.cleaned_data.get("state", ""))
        if not value:
            return None
        if value not in ACCOUNT_INVENTORY_STATES:
            raise forms.ValidationError("Choose a supported account state.")
        return value


class PlatformAccountInvitationForm(StrictInputForm):
    """Create only one inactive person identity for recipient-owned acceptance."""

    email = forms.EmailField(
        label="Email address",
        max_length=MAX_INVITATION_EMAIL_LENGTH,
        help_text=(
            "The invitation is sent to this address. Maru never reveals which "
            "submitted account detail conflicts with an existing identity."
        ),
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "maxlength": MAX_INVITATION_EMAIL_LENGTH,
            }
        ),
    )
    login_handle = forms.CharField(
        label="Username",
        required=False,
        strip=False,
        max_length=MAX_INVITATION_LOGIN_HANDLE_LENGTH,
        help_text=(
            "Optional sign-in name. Preserve the person's chosen spelling; do "
            "not use an email address or include @."
        ),
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "maxlength": MAX_INVITATION_LOGIN_HANDLE_LENGTH,
            }
        ),
    )
    display_name = forms.CharField(
        label="Display name",
        required=False,
        strip=False,
        max_length=MAX_INVITATION_DISPLAY_NAME_LENGTH,
        help_text=(
            "Optional account label. This does not create a convention person, "
            "membership, registration, or public profile."
        ),
        widget=forms.TextInput(
            attrs={
                "autocomplete": "name",
                "maxlength": MAX_INVITATION_DISPLAY_NAME_LENGTH,
            }
        ),
    )
    preferred_language = forms.ChoiceField(
        label="Interface language",
        choices=tuple(
            (code, "English" if code == "en" else code)
            for code in SUPPORTED_INVITATION_LANGUAGE_CODES
        ),
        initial="en",
        help_text="The language used for account-security messages.",
    )
    reason = forms.CharField(
        label="Administrative reason",
        strip=False,
        max_length=MAX_INVITATION_REASON_LENGTH,
        help_text=(
            "Explain why this platform identity is being reserved. The reason "
            "is retained for authorized identity operations and is not emailed."
        ),
        widget=forms.Textarea(
            attrs={"rows": 4, "maxlength": MAX_INVITATION_REASON_LENGTH}
        ),
    )
    expected_version = StrictBase10IntegerField(
        min_value=0,
        max_value=0,
        widget=forms.HiddenInput,
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("auto_id", "id_account_invite_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("preferred_language", "en")
        initial.setdefault("expected_version", 0)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_email(self) -> str:
        value = _field_local_result(
            "email",
            lambda: normalize_invitation_email(self.cleaned_data["email"]),
        )
        if value is None:
            raise forms.ValidationError("Enter an email address.")
        return value

    def clean_login_handle(self) -> str:
        value = _field_local_result(
            "login_handle",
            lambda: normalize_invitation_login_handle(
                self.cleaned_data.get("login_handle")
            ),
        )
        return value or ""

    def clean_display_name(self) -> str:
        value = _field_local_result(
            "display_name",
            lambda: normalize_invitation_display_name(
                self.cleaned_data.get("display_name")
            ),
        )
        return value or ""

    def clean_preferred_language(self) -> str:
        value = _field_local_result(
            "preferred_language",
            lambda: normalize_invitation_preferred_language(
                self.cleaned_data.get("preferred_language")
            ),
        )
        if value is None:
            raise forms.ValidationError("Choose a supported language.")
        return value

    def clean_reason(self) -> str:
        value = _field_local_result(
            "reason",
            lambda: normalize_invitation_reason(self.cleaned_data["reason"]),
        )
        if value is None:
            raise forms.ValidationError("Enter an administrative reason.")
        return value


class PlatformAccountInvitationActionForm(StrictInputForm):
    """Closed reason/version/idempotency input shared by reissue and revoke."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Administrative reason",
        strip=False,
        max_length=MAX_INVITATION_REASON_LENGTH,
        help_text=(
            "Record why this invitation lifecycle change is needed. The value "
            "is retained for authorized identity operations and is not emailed."
        ),
        widget=forms.Textarea(
            attrs={"rows": 3, "maxlength": MAX_INVITATION_REASON_LENGTH}
        ),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        retry_key: UUID | None = None,
        auto_id: str = "id_invitation_action_%s",
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("auto_id", auto_id)
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_reason(self) -> str:
        value = _field_local_result(
            "reason",
            lambda: normalize_invitation_reason(self.cleaned_data["reason"]),
        )
        if value is None:
            raise forms.ValidationError("Enter an administrative reason.")
        return value


class PlatformIdentityDeliveryRetryForm(StrictInputForm):
    """Closed reason/version/idempotency input for one controlled retry."""

    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Reconciliation reason",
        strip=False,
        max_length=MAX_INVITATION_REASON_LENGTH,
        help_text=(
            "Record how you confirmed that the provider did not accept the "
            "message before scheduling one controlled retry."
        ),
        widget=forms.Textarea(
            attrs={"rows": 3, "maxlength": MAX_INVITATION_REASON_LENGTH}
        ),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        retry_key: UUID | None = None,
        auto_id: str = "id_delivery_retry_%s",
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("auto_id", auto_id)
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_reason(self) -> str:
        value = _field_local_result(
            "reason",
            lambda: normalize_invitation_reason(self.cleaned_data["reason"]),
        )
        if value is None:
            raise forms.ValidationError("Enter a reconciliation reason.")
        return value


class PlatformIdentityDeliveryDeliveredForm(PlatformIdentityDeliveryRetryForm):
    """Closed confirmation input for a provider-accepted delivery."""

    provider_reference = forms.CharField(
        label="Provider reference",
        strip=False,
        max_length=MAX_PROVIDER_REFERENCE_LENGTH,
        help_text=(
            "Enter the exact non-secret reference shown by the delivery "
            "provider. Maru retains it as restricted operational evidence."
        ),
        widget=NeverRedisplayTextInput(
            attrs={
                "autocomplete": "off",
                "maxlength": MAX_PROVIDER_REFERENCE_LENGTH,
            }
        ),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("auto_id", "id_delivery_delivered_%s")
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            **kwargs,
        )

    def clean_provider_reference(self) -> str:
        value = str(self.cleaned_data["provider_reference"])
        if not value or not value.isprintable():
            raise forms.ValidationError("Enter a valid provider reference.")
        return value


class AccountInvitationAcceptanceForm(StrictInputForm):
    """Public single-use code and recipient-owned password input."""

    raw_token = forms.CharField(
        label="Invitation code",
        strip=False,
        min_length=INVITATION_TOKEN_LENGTH,
        max_length=INVITATION_TOKEN_LENGTH,
        help_text=(
            "Open the emailed link to fill this automatically, or paste the "
            "complete code. Maru never places the code in a URL query or path."
        ),
        widget=NeverRedisplayTextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
                "maxlength": INVITATION_TOKEN_LENGTH,
                "inputmode": "text",
                "data-invitation-code": "",
            }
        ),
    )
    new_password = forms.CharField(
        label="Password",
        strip=False,
        max_length=128,
        help_text=(
            "Choose a new password for this account. Administrators cannot see "
            "or choose it."
        ),
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "maxlength": 128},
            render_value=False,
        ),
    )
    confirm_password = forms.CharField(
        label="Confirm password",
        strip=False,
        max_length=128,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password", "maxlength": 128},
            render_value=False,
        ),
    )
    retry_key = CanonicalUUIDField(widget=CanonicalUUIDHiddenInput)

    def __init__(
        self,
        *args: Any,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("auto_id", "id_invitation_accept_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_raw_token(self) -> str:
        value = str(self.cleaned_data["raw_token"])
        if _INVITATION_TOKEN_PATTERN.fullmatch(value) is None:
            raise forms.ValidationError(
                "Enter the complete invitation code.",
                code="invitation_code_invalid",
            )
        return value

    def clean(self) -> dict[str, Any] | None:
        # This public C4 form deliberately bypasses StrictInputForm's helpful
        # field-name listing: an attacker could otherwise submit the bearer
        # code or password *as an unknown key* and make the error reflect it.
        cleaned = forms.Form.clean(self)
        getlist = getattr(self.data, "getlist", None)
        if getlist is not None and any(
            len(getlist(field_name)) > 1 for field_name in self.fields
        ):
            raise forms.ValidationError(
                "Submit each field exactly once.",
                code="invalid_input_cardinality",
            )
        if any(
            field_name not in self.fields
            and field_name not in self.transport_field_names
            for field_name in self.data
        ):
            raise forms.ValidationError(
                "Remove unsupported input fields.",
                code="unknown_input_field",
            )
        if not cleaned:
            return cleaned
        password = cleaned.get("new_password")
        confirmation = cleaned.get("confirm_password")
        if password and confirmation and password != confirmation:
            self.add_error(
                "confirm_password",
                "The passwords do not match.",
            )
        return cleaned


__all__ = [
    "AccountInvitationAcceptanceForm",
    "PlatformAccountInventoryFilterForm",
    "PlatformAccountInvitationActionForm",
    "PlatformAccountInvitationForm",
    "PlatformIdentityDeliveryDeliveredForm",
    "PlatformIdentityDeliveryRetryForm",
]
