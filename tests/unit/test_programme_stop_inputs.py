"""Stop confirmation binds exact intent without creating operational authority."""

from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.events.adoption import ADOPTION_PROFILES
from maru.events.programme_stop_inputs import (
    ProgrammeStopInput,
    normalize_programme_stop_input,
    programme_stop_request_digest,
)


def intent(**changes):
    return replace(
        ProgrammeStopInput(7, 0, "a" * 64, "  Retain   the synthetic history.  "),
        **changes,
    )


def attribution(**changes):
    return {
        "actor_id": UUID(int=1),
        "organization_id": UUID(int=2),
        "edition_id": UUID(int=3),
        "idempotency_key": UUID(int=4),
        **changes,
    }


def test_normalization_preserves_original_and_registers_no_profile():
    submitted = intent()
    normalized = normalize_programme_stop_input(submitted)
    assert normalized.reason == "Retain the synthetic history."
    assert submitted.reason.startswith("  ")
    assert normalize_programme_stop_input(normalized) == normalized
    with pytest.raises(FrozenInstanceError):
        normalized.reason = "Different"
    assert ("programme_operations", 1) not in ADOPTION_PROFILES


@pytest.mark.parametrize("details", [None, {}, True, "stop"])
def test_unknown_input_container_is_a_closed_validation_error(details):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_stop_input(details)
    assert set(failure.value.error_dict) == {"intent"}


@pytest.mark.parametrize(
    "field", ["expected_aggregate_version", "expected_lifecycle_version"]
)
@pytest.mark.parametrize("value", [None, True, False, "1", 1.0, -1, 2_147_483_648])
def test_versions_reject_coercion_and_integer_overflow(field, value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_stop_input(intent(**{field: value}))
    assert set(failure.value.error_dict) == {field}


def test_zero_lifecycle_is_valid_but_zero_aggregate_is_not():
    assert normalize_programme_stop_input(intent()).expected_lifecycle_version == 0
    with pytest.raises(ValidationError):
        normalize_programme_stop_input(intent(expected_aggregate_version=0))


@pytest.mark.parametrize(
    "value", [None, True, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n"]
)
def test_preview_identity_is_exact_not_trimmed_or_coerced(value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_stop_input(intent(preview_fingerprint=value))
    assert set(failure.value.error_dict) == {"preview_fingerprint"}


@pytest.mark.parametrize(
    "value",
    [
        None,
        False,
        "",
        "  ",
        "x" * 241,
        "x" * 4097,
        "x\x00y",
        "x\ny",
        "x\ty",
        "x\u202ey",
        "x\ud800y",
    ],
)
def test_reason_is_required_bounded_and_control_free(value):
    with pytest.raises(ValidationError) as failure:
        normalize_programme_stop_input(intent(reason=value))
    assert set(failure.value.error_dict) == {"reason"}


def test_reason_boundary_and_canonical_unicode():
    assert normalize_programme_stop_input(intent(reason="x" * 240)).reason == "x" * 240
    assert programme_stop_request_digest(
        intent(reason="Cafe\u0301"), **attribution()
    ) == programme_stop_request_digest(intent(reason="Café"), **attribution())


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "idempotency_key"]
)
@pytest.mark.parametrize("value", [None, False, 1, UUID(int=0), str(UUID(int=1))])
def test_attribution_requires_actual_typed_non_nil_identity(field, value):
    with pytest.raises(ValidationError) as failure:
        programme_stop_request_digest(intent(), **attribution(**{field: value}))
    assert set(failure.value.error_dict) == {field}


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "idempotency_key"]
)
def test_each_identity_is_part_of_original_intent(field):
    original = programme_stop_request_digest(intent(), **attribution())
    changed = programme_stop_request_digest(
        intent(), **attribution(**{field: UUID(int=9)})
    )
    assert changed != original


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_aggregate_version", 8),
        ("expected_lifecycle_version", 1),
        ("preview_fingerprint", "b" * 64),
        ("reason", "A different accountable reason."),
    ],
)
def test_every_confirmation_field_changes_the_digest(field, value):
    assert programme_stop_request_digest(
        intent(**{field: value}), **attribution()
    ) != programme_stop_request_digest(intent(), **attribution())


def test_normalized_identical_retry_has_identical_digest():
    digest = programme_stop_request_digest(intent(), **attribution())
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")
    assert digest == programme_stop_request_digest(
        normalize_programme_stop_input(intent()), **attribution()
    )


def test_digest_does_not_bypass_validation():
    with pytest.raises(ValidationError):
        programme_stop_request_digest(intent(reason=""), **attribution())
