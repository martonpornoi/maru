from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.programme.catalogs import ProgrammeItemKind
from maru.programme.inputs import (
    canonical_digest,
    canonical_request_json,
    normalized_closed_code,
    normalized_reason,
    normalized_source_channel,
    normalized_text,
    require_expected_version,
    require_positive_version,
    require_sha256,
    require_uuid,
)


def test_text_normalization_is_nfc_bounded_and_explicit() -> None:
    assert (
        normalized_text(
            "  Cafe\u0301   opening  ",
            field="title",
            maximum=20,
            required=True,
            collapse=True,
        )
        == "Café opening"
    )
    assert (
        normalized_text(
            "  first   line  ",
            field="note",
            maximum=30,
        )
        == "first   line"
    )

    with pytest.raises(ValidationError) as control:
        normalized_text("safe\nunsafe", field="title", maximum=20)
    assert control.value.error_dict["title"][0].code == "programme_control_character"
    with pytest.raises(ValidationError) as empty:
        normalized_text("  ", field="title", maximum=20, required=True)
    assert empty.value.error_dict["title"][0].code == "programme_value_required"
    with pytest.raises(ValidationError) as long:
        normalized_text("abc", field="title", maximum=2)
    assert long.value.error_dict["title"][0].code == "programme_value_too_long"


def test_reason_and_source_channel_use_closed_normal_forms() -> None:
    assert normalized_reason("  Scheduling   changed ") == "Scheduling changed"
    assert normalized_source_channel("staff_console") == "staff_console"
    for invalid in ("Staff", "staff.console", " staff", "", "a" * 33):
        with pytest.raises(ValidationError):
            normalized_source_channel(invalid)


def test_closed_codes_and_typed_ids_are_not_free_form() -> None:
    assert (
        normalized_closed_code(
            "ceremony",
            field="kind",
            enum_type=ProgrammeItemKind,
        )
        is ProgrammeItemKind.CEREMONY
    )
    with pytest.raises(ValidationError):
        normalized_closed_code(
            "future_kind",
            field="kind",
            enum_type=ProgrammeItemKind,
        )
    identifier = uuid4()
    assert require_uuid(identifier, field="source_object_id") is identifier
    with pytest.raises(ValidationError):
        require_uuid(str(identifier), field="source_object_id")


def test_versions_are_strict_integers_with_first_control_v0() -> None:
    assert require_expected_version(0) == 0
    assert require_expected_version(4) == 4
    assert require_positive_version(1, field="source_version") == 1
    for invalid in (-1, True, 1.0):
        with pytest.raises(ValidationError):
            require_expected_version(invalid)
    for invalid in (0, -1, False):
        with pytest.raises(ValidationError):
            require_positive_version(invalid, field="source_version")


def test_canonical_digest_is_deterministic_and_lowercase() -> None:
    first = {"title": "Árvíz", "version": 1}
    second = {"version": 1, "title": "Árvíz"}
    assert canonical_request_json(first) == canonical_request_json(second)
    digest = canonical_digest(first)
    assert digest == canonical_digest(second)
    assert require_sha256(digest) == digest
    with pytest.raises(ValidationError):
        require_sha256(digest.upper())
