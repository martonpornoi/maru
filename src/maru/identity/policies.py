"""Policies that keep platform operation separate from convention participation."""

from typing import Protocol

from django.core.exceptions import ValidationError


class ConventionSubject(Protocol):
    """Describe convention subject."""

    @property
    def is_platform_administrator(self) -> bool:
        """Return whether platform administrator.

        Returns
        -------
        bool
            `True` when platform administrator; otherwise `False`.
        """
        ...


def validate_convention_subject(
    account: ConventionSubject,
    *,
    field_name: str = "account",
) -> None:
    """Reject platform-only accounts from organizer and edition relationships.

    Parameters
    ----------
    account : ConventionSubject
        The platform account whose state or access is being evaluated.
    field_name : str, default='account'
        The canonical field name whose policy or value is requested.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if account.is_platform_administrator:
        raise ValidationError(
            {
                field_name: (
                    "A platform administrator cannot participate in a convention."
                )
            },
            code="platform_administrator_cannot_participate",
        )
