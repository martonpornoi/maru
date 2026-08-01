"""Strict, domain-neutral request payload helpers."""

from __future__ import annotations

from collections.abc import Mapping

from rest_framework.exceptions import ValidationError

MAX_REPORTED_UNKNOWN_FIELDS = 5
MAX_REPORTED_FIELD_NAME_LENGTH = 60


def reject_unknown_fields(
    data: object,
    *,
    allowed_fields: frozenset[str],
) -> None:
    """Reject undeclared object keys rather than silently discarding them."""

    if not isinstance(data, Mapping):
        return
    unknown = sorted(
        str(field_name) for field_name in data if field_name not in allowed_fields
    )
    if not unknown:
        return
    visible = ", ".join(
        field_name[:MAX_REPORTED_FIELD_NAME_LENGTH]
        for field_name in unknown[:MAX_REPORTED_UNKNOWN_FIELDS]
    )
    if len(unknown) > MAX_REPORTED_UNKNOWN_FIELDS:
        visible = f"{visible}, and {len(unknown) - MAX_REPORTED_UNKNOWN_FIELDS} more"
    raise ValidationError(
        f"Remove unsupported input fields: {visible}.",
        code="unknown_input_field",
    )
