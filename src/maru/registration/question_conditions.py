"""Shared compatibility rules for conditional registration questions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maru.registration.models import QuestionFieldType

if TYPE_CHECKING:
    from collections.abc import Sequence

MIN_SIGNED_32_BIT_INTEGER = -(2**31)
MAX_SIGNED_32_BIT_INTEGER = (2**31) - 1


def condition_value_is_compatible(
    *,
    field_type: str,
    options: Sequence[str],
    value: str,
) -> bool:
    """Return whether ``value`` can be produced by the source question type.

    Conditional edges intentionally do not support multiple-choice sources:
    their answer is a set and cannot be represented by the v1 scalar condition
    value. Integer conditions use the same canonical signed 32-bit spelling as
    submitted integer answers, including rejecting ``-0`` and leading zeroes.

    Parameters
    ----------
    field_type : str
        The closed field type discriminator defined by the domain catalog.
    options : Sequence[str]
        The configured option codes valid for the source question.
    value : str
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    bool
        `True` when ``value`` can be produced by the source question type;
        otherwise `False`.

    Examples
    --------
    Canonical integers are accepted, while alternate spellings are rejected.

    >>> condition_value_is_compatible(
    ...     field_type=QuestionFieldType.INTEGER,
    ...     options=(),
    ...     value="12",
    ... )
    True
    >>> condition_value_is_compatible(
    ...     field_type=QuestionFieldType.INTEGER,
    ...     options=(),
    ...     value="012",
    ... )
    False
    """
    if field_type == QuestionFieldType.BOOLEAN:
        return value in {"true", "false"}
    if field_type == QuestionFieldType.INTEGER:
        try:
            integer_value = int(value)
        except (TypeError, ValueError):
            return False
        return (
            str(integer_value) == value
            and MIN_SIGNED_32_BIT_INTEGER <= integer_value <= MAX_SIGNED_32_BIT_INTEGER
        )
    if field_type == QuestionFieldType.SINGLE_CHOICE:
        return value in options
    if field_type == QuestionFieldType.MULTIPLE_CHOICE:
        return False
    return bool(value) and value.strip() == value


__all__ = [
    "MAX_SIGNED_32_BIT_INTEGER",
    "MIN_SIGNED_32_BIT_INTEGER",
    "condition_value_is_compatible",
]
