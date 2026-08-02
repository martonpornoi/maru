from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest
from django.core.exceptions import ValidationError

from maru.workforce.structure_inputs import (
    MAX_DEPARTMENT_CODE_CANDIDATES,
    MAX_DEPARTMENT_CODE_LENGTH,
    canonical_request_digest,
    canonical_request_json,
    department_code_candidates,
    generate_department_code,
    normalize_department_description,
    normalize_department_name,
    normalize_structure_reason,
    validate_department_display_order,
    validate_exact_confirmation,
)


def _validation_code(error: ValidationError, field_name: str) -> str:
    return str(error.error_dict[field_name][0].code)


def test_department_name_is_nfc_trimmed_and_whitespace_collapsed() -> None:
    assert normalize_department_name("  Maid\u2003Cafe\u0301   Team  ") == (
        "Maid Café Team"
    )
    assert len(normalize_department_name("e\u0301" * 160)) == 160


def test_description_is_nfc_and_outer_trimmed_without_inner_rewriting() -> None:
    assert normalize_department_description("  Cafe\u0301  operations  ") == (
        "Café  operations"
    )
    assert normalize_department_description("   ") == ""


def test_reason_is_nfc_required_trimmed_and_whitespace_collapsed() -> None:
    assert normalize_structure_reason("  Move\u2003Cafe\u0301   under Art  ") == (
        "Move Café under Art"
    )
    with pytest.raises(ValidationError) as caught:
        normalize_structure_reason("   ")
    assert _validation_code(caught.value, "reason") == "structure_reason_required"


@pytest.mark.parametrize(
    ("normalizer", "field_name"),
    [
        (normalize_department_name, "name"),
        (normalize_department_description, "description"),
        (normalize_structure_reason, "reason"),
    ],
)
@pytest.mark.parametrize("control", ["\x00", "\n", "\t", "\x85"])
def test_controls_are_rejected_before_trim_or_normalization(
    normalizer: Any,
    field_name: str,
    control: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        normalizer(f"{control} otherwise valid {control}")
    assert _validation_code(caught.value, field_name) == ("structure_control_character")


@pytest.mark.parametrize(
    ("normalizer", "value", "field_name", "code"),
    [
        (normalize_department_name, " ", "name", "structure_name_required"),
        (
            normalize_department_name,
            "n" * 161,
            "name",
            "structure_name_too_long",
        ),
        (
            normalize_department_description,
            "d" * 1_001,
            "description",
            "structure_description_too_long",
        ),
        (
            normalize_structure_reason,
            "r" * 241,
            "reason",
            "structure_reason_too_long",
        ),
    ],
)
def test_text_bounds_have_stable_field_codes(
    normalizer: Any,
    value: str,
    field_name: str,
    code: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        normalizer(value)
    assert _validation_code(caught.value, field_name) == code


def test_exact_confirmation_is_not_trimmed_casefolded_or_nfc_normalized() -> None:
    exact = "  Café Edition  "
    assert validate_exact_confirmation(exact, expected=exact) == exact

    for changed in ("Café Edition", "  CAFÉ Edition  ", "  Cafe\u0301 Edition  "):
        with pytest.raises(ValidationError) as caught:
            validate_exact_confirmation(changed, expected=exact)
        assert _validation_code(caught.value, "confirmation_name") == (
            "structure_confirmation_mismatch"
        )


@pytest.mark.parametrize("value", [0, 1, 65_535])
def test_display_order_accepts_only_the_closed_integer_range(value: int) -> None:
    assert validate_department_display_order(value) == value


@pytest.mark.parametrize("value", [-1, 65_536, True, False, 1.0, "1"])
def test_display_order_rejects_out_of_range_or_non_strict_integers(
    value: Any,
) -> None:
    with pytest.raises(ValidationError) as caught:
        validate_department_display_order(value)
    assert _validation_code(caught.value, "display_order") == (
        "structure_display_order_invalid"
    )


def test_request_digest_uses_sorted_compact_utf8_canonical_json() -> None:
    first = {
        "reason": "Create Café",
        "display_order": 12,
        "parent_department_id": None,
    }
    reordered = {
        "parent_department_id": None,
        "display_order": 12,
        "reason": "Create Café",
    }
    canonical = canonical_request_json(first)

    assert canonical == (
        b'{"display_order":12,"parent_department_id":null,'
        b'"reason":"Create Caf\xc3\xa9"}'
    )
    assert canonical_request_digest(first) == canonical_request_digest(reordered)
    assert canonical_request_digest(first) == hashlib.sha256(canonical).hexdigest()
    assert canonical_request_digest(first) != canonical_request_digest(
        {**first, "display_order": 13}
    )


def test_request_json_rejects_non_json_and_non_finite_values() -> None:
    with pytest.raises(TypeError):
        canonical_request_json({"unsupported": object()})
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_request_json({"unsupported": float("nan")})


def test_department_code_candidates_are_slugged_bounded_and_deterministic() -> None:
    name = "A_B " + ("Very Long Department " * 7)
    first = department_code_candidates(name)
    second = department_code_candidates(name)

    assert first == second
    assert len(first) == MAX_DEPARTMENT_CODE_CANDIDATES
    assert first[0].startswith("a-b-very-long-department")
    assert first[1].endswith("-2")
    assert first[-1].endswith("-256")
    assert all(len(candidate) <= MAX_DEPARTMENT_CODE_LENGTH for candidate in first)
    assert all(
        re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", candidate) for candidate in first
    )


def test_department_code_falls_back_and_uses_first_available_candidate() -> None:
    assert generate_department_code("東京") == "department"
    assert (
        generate_department_code(
            "東京",
            existing_codes=("DEPARTMENT", "department-2"),
        )
        == "department-3"
    )
    assert (
        generate_department_code(
            "Cafe\u0301",
            existing_codes=("cafe",),
        )
        == "cafe-2"
    )


def test_department_code_exhaustion_has_a_stable_error() -> None:
    occupied = department_code_candidates("Operations")

    with pytest.raises(ValidationError) as caught:
        generate_department_code("Operations", existing_codes=occupied)
    assert _validation_code(caught.value, "name") == "structure_code_unavailable"
