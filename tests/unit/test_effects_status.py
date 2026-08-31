"""Value-safety coverage for Effects operator status output."""

from unittest.mock import MagicMock

from maru.effects.management.commands.effects_status import (
    MAX_STATUS_ERROR_CODES,
    _quarantine_error_counts,
    safe_status_error_code,
)


def test_status_error_code_preserves_only_safe_codes() -> None:
    assert safe_status_error_code("effect_profile_not_allowed") == (
        "effect_profile_not_allowed"
    )
    assert safe_status_error_code("unsafe provider detail") == (
        "invalid_effect_error_code"
    )
    assert safe_status_error_code(object()) == "invalid_effect_error_code"


def test_quarantine_error_code_output_is_bounded_and_marks_truncation() -> None:
    messages = MagicMock()
    grouped = messages.filter.return_value.values.return_value
    annotated = grouped.annotate.return_value
    ordered = annotated.order_by.return_value
    ordered.__getitem__.return_value = [
        {"last_error_code": f"synthetic_failure_{index:03d}", "count": 1}
        for index in range(MAX_STATUS_ERROR_CODES + 1)
    ]

    counts, truncated = _quarantine_error_counts(messages)

    assert len(counts) == MAX_STATUS_ERROR_CODES
    assert truncated is True
    assert "synthetic_failure_064" not in counts
