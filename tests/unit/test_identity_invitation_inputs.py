from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.identity.invitation_inputs import (
    DEFAULT_INVITATION_LANGUAGE_CODE,
    MAX_INVITATION_REASON_LENGTH,
    SUPPORTED_INVITATION_LANGUAGE_CODES,
    canonical_request_digest,
    canonical_request_json,
    invitation_login_handle_comparison_key,
    normalize_invitation_display_name,
    normalize_invitation_email,
    normalize_invitation_login_handle,
    normalize_invitation_preferred_language,
    normalize_invitation_reason,
    validate_correlation_id,
    validate_invitation_expected_version,
    validate_retry_key,
    validate_source_channel,
)


def _validation_code(error: ValidationError, field_name: str) -> str:
    return str(error.error_dict[field_name][0].code)


def test_email_uses_account_normalization_and_validates_unicode_domain() -> None:
    assert normalize_invitation_email("  PERSON@B\u00dcCHER.example  ") == (
        "person@b\u00fccher.example"
    )


@pytest.mark.parametrize("value", [None, True, 7, "", "not-an-email", "a@"])
def test_email_rejects_wrong_types_blank_and_invalid_values(value: object) -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_invitation_email(value)
    assert _validation_code(caught.value, "email") in {
        "invitation_email_required",
        "invitation_email_invalid",
    }


def test_email_bound_is_applied_after_trim_normalization() -> None:
    local = "a" * 64
    valid = f"{local}@{'b' * 63}.{'c' * 63}.{'d' * 61}"
    assert len(valid) == 254
    assert normalize_invitation_email(f" {valid.upper()} ") == valid

    with pytest.raises(ValidationError) as caught:
        normalize_invitation_email(f"{local}@{'b' * 63}.{'c' * 63}.{'d' * 62}")
    assert _validation_code(caught.value, "email") == "invitation_email_too_long"


def test_login_handle_preserves_unicode_display_spelling_and_casefolds_key() -> None:
    handle = "Stra\u00dfe / Caf\u00e9_Fox"
    assert normalize_invitation_login_handle(handle) == handle
    assert invitation_login_handle_comparison_key(handle) == (
        invitation_login_handle_comparison_key("STRASSE / CAF\u00c9_FOX")
    )
    assert normalize_invitation_login_handle(None) is None
    assert normalize_invitation_login_handle("") is None


@pytest.mark.parametrize(
    "value",
    [" Handle", "Handle ", "\u2003Handle", "Handle\u00a0"],
)
def test_login_handle_rejects_outer_whitespace_without_silent_trim(value: str) -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_invitation_login_handle(value)
    assert _validation_code(caught.value, "login_handle") == (
        "invitation_login_handle_outer_whitespace"
    )


@pytest.mark.parametrize("value", ["mail@example.invalid", "a" * 121])
def test_login_handle_rejects_ambiguity_and_bound(value: str) -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_invitation_login_handle(value)
    assert _validation_code(caught.value, "login_handle") in {
        "invitation_login_handle_email_ambiguity",
        "invitation_login_handle_too_long",
    }


@pytest.mark.parametrize("control", ["\x00", "\n", "\x85", "\u200b", "\ud800"])
@pytest.mark.parametrize(
    ("normalizer", "field_name"),
    [
        (normalize_invitation_login_handle, "login_handle"),
        (normalize_invitation_display_name, "display_name"),
        (normalize_invitation_reason, "reason"),
    ],
)
def test_identity_text_rejects_control_format_and_surrogate_characters(
    normalizer: Any,
    field_name: str,
    control: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        normalizer(f"valid{control}text")
    assert _validation_code(caught.value, field_name) == (
        "invitation_control_character"
    )


def test_display_name_and_reason_are_nfc_trimmed_and_whitespace_collapsed() -> None:
    assert normalize_invitation_display_name("  Cafe\u0301\u2003 Fox  ") == (
        "Caf\u00e9 Fox"
    )
    assert normalize_invitation_display_name("   ") is None
    assert normalize_invitation_reason("  Invite\u2003Cafe\u0301   lead  ") == (
        "Invite Caf\u00e9 lead"
    )


def test_display_name_and_reason_apply_normalized_character_bounds() -> None:
    assert normalize_invitation_display_name("e\u0301" * 120) == "\u00e9" * 120
    assert normalize_invitation_reason("e\u0301" * MAX_INVITATION_REASON_LENGTH) == (
        "\u00e9" * MAX_INVITATION_REASON_LENGTH
    )

    for normalizer, field_name, code, value in (
        (
            normalize_invitation_display_name,
            "display_name",
            "invitation_display_name_too_long",
            "n" * 121,
        ),
        (
            normalize_invitation_reason,
            "reason",
            "invitation_reason_too_long",
            "r" * 241,
        ),
    ):
        with pytest.raises(ValidationError) as caught:
            normalizer(value)
        assert _validation_code(caught.value, field_name) == code


def test_reason_is_required_and_strictly_textual() -> None:
    for value in ("", "   ", None, False, 12):
        with pytest.raises(ValidationError) as caught:
            normalize_invitation_reason(value)
        assert _validation_code(caught.value, "reason") in {
            "invitation_reason_required",
            "invitation_text_invalid",
        }


def test_preferred_language_uses_small_code_owned_catalog() -> None:
    assert SUPPORTED_INVITATION_LANGUAGE_CODES == ("en",)
    assert normalize_invitation_preferred_language(None) == (
        DEFAULT_INVITATION_LANGUAGE_CODE
    )
    assert normalize_invitation_preferred_language("") == "en"
    assert normalize_invitation_preferred_language(" EN ") == "en"

    with pytest.raises(ValidationError) as caught:
        normalize_invitation_preferred_language("hu")
    assert _validation_code(caught.value, "preferred_language") == (
        "invitation_preferred_language_unsupported"
    )


@pytest.mark.parametrize("value", [0, 1, 2**63])
def test_expected_version_accepts_exact_non_negative_integers(value: int) -> None:
    assert validate_invitation_expected_version(value) == value


@pytest.mark.parametrize("value", [True, False, -1, 1.0, "1", None])
def test_expected_version_rejects_bools_coercions_and_negative_values(
    value: object,
) -> None:
    with pytest.raises(ValidationError) as caught:
        validate_invitation_expected_version(value)
    assert _validation_code(caught.value, "expected_version") == (
        "invitation_expected_version_invalid"
    )


def test_retry_and_correlation_identifiers_must_already_be_uuid_objects() -> None:
    retry_key = uuid4()
    correlation_id = uuid4()
    assert validate_retry_key(retry_key) is retry_key
    assert validate_correlation_id(correlation_id) is correlation_id

    for validator, field_name, value in (
        (validate_retry_key, "retry_key", str(retry_key)),
        (validate_retry_key, "retry_key", True),
        (validate_correlation_id, "correlation_id", str(correlation_id)),
        (validate_correlation_id, "correlation_id", None),
    ):
        with pytest.raises(ValidationError) as caught:
            validator(value)
        assert _validation_code(caught.value, field_name) == (
            f"invitation_{field_name}_invalid"
        )


@pytest.mark.parametrize(
    "value",
    ["web", "api", "reference_client", "management-command", "a" * 40],
)
def test_source_channel_accepts_only_closed_safe_spelling(value: str) -> None:
    assert validate_source_channel(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "Web", " web", "web ", "web.channel", "web/channel", "a" * 41, True],
)
def test_source_channel_rejects_unsafe_or_noncanonical_values(value: object) -> None:
    with pytest.raises(ValidationError) as caught:
        validate_source_channel(value)
    assert _validation_code(caught.value, "source_channel") == (
        "invitation_source_channel_invalid"
    )


def test_request_digest_is_sorted_compact_utf8_and_uuid_deterministic() -> None:
    invitation_id = UUID("01234567-89ab-cdef-0123-456789abcdef")
    first = {
        "reason": "Invite Caf\u00e9 lead",
        "expected_version": 0,
        "invitation_id": invitation_id,
        "flags": [True, None, 3],
    }
    reordered = {
        "flags": [True, None, 3],
        "invitation_id": invitation_id,
        "expected_version": 0,
        "reason": "Invite Caf\u00e9 lead",
    }
    canonical = canonical_request_json(first)
    assert canonical == (
        b'{"expected_version":0,"flags":[true,null,3],'
        b'"invitation_id":"01234567-89ab-cdef-0123-456789abcdef",'
        b'"reason":"Invite Caf\xc3\xa9 lead"}'
    )
    assert canonical_request_digest(first) == canonical_request_digest(reordered)
    assert canonical_request_digest(first) == hashlib.sha256(canonical).hexdigest()


def test_request_digest_excludes_password_and_bearer_secrets_recursively() -> None:
    without_secrets = {"email": "person@example.invalid", "nested": {"keep": 1}}
    with_secrets = {
        "email": "person@example.invalid",
        "password": "must-not-be-digested",
        "Bearer-Token": "must-not-be-digested",
        "nested": {"keep": 1, "invitation_token": object()},
    }
    assert canonical_request_json(with_secrets) == canonical_request_json(
        without_secrets
    )
    assert b"must-not-be-digested" not in canonical_request_json(with_secrets)


@pytest.mark.parametrize(
    "value",
    [object(), b"bytes", 1.5, float("nan"), ("tuple",), {"set"}],
)
def test_request_json_rejects_unsupported_types_at_any_depth(value: object) -> None:
    with pytest.raises(TypeError, match="Unsupported request digest value type"):
        canonical_request_json({"nested": [value]})


def test_request_json_rejects_non_string_keys_and_circular_collections() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_request_json({1: "value"})  # type: ignore[dict-item]

    circular: list[object] = []
    circular.append(circular)
    with pytest.raises(TypeError, match="Circular lists"):
        canonical_request_json({"circular": circular})
