"""Policies that keep platform operation separate from convention participation."""

from typing import Protocol

from django.core.exceptions import ValidationError


class ConventionSubject(Protocol):
    @property
    def is_platform_administrator(self) -> bool: ...


def validate_convention_subject(
    account: ConventionSubject,
    *,
    field_name: str = "account",
) -> None:
    """Reject platform-only accounts from organizer and edition relationships."""

    if account.is_platform_administrator:
        raise ValidationError(
            {
                field_name: (
                    "A platform administrator cannot participate in a convention."
                )
            },
            code="platform_administrator_cannot_participate",
        )
