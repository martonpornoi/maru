"""Account-owned navigation preferences with no authorization semantics."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.identity.models import Account, NavigationPin

MAX_NAVIGATION_PINS = 24


def navigation_pin_codes(*, account: Account) -> tuple[str, ...]:
    """Return only the signed-in account's stable destination codes.

    Parameters
    ----------
    account : Account
        The platform account whose state or access is being evaluated.

    Returns
    -------
    tuple[str, ...]
        The matching navigation pin codes records in deterministic order.
    """
    return tuple(
        NavigationPin.objects.filter(account=account)
        .order_by("created_at", "id")
        .values_list("destination_code", flat=True)
    )


@transaction.atomic
def pin_navigation_destination(*, account: Account, destination_code: str) -> None:
    """Store a shortcut preference; the destination is reauthorized on reads.

    Parameters
    ----------
    account : Account
        The platform account whose state or access is being evaluated.
    destination_code : str
        The stable destination code from the relevant closed catalog.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    locked_account = Account.objects.select_for_update().get(id=account.id)
    normalized_code = destination_code.strip()
    existing = NavigationPin.objects.filter(
        account=locked_account,
        destination_code=normalized_code,
    ).first()
    if existing is not None:
        return
    if (
        NavigationPin.objects.filter(account=locked_account).count()
        >= MAX_NAVIGATION_PINS
    ):
        raise ValidationError(
            f"You can pin up to {MAX_NAVIGATION_PINS} destinations.",
            code="navigation_pin_limit_reached",
        )
    NavigationPin.objects.create(
        account=locked_account,
        destination_code=normalized_code,
    )


@transaction.atomic
def unpin_navigation_destination(*, account: Account, destination_code: str) -> None:
    """Remove one shortcut without touching the destination or its authority.

    Parameters
    ----------
    account : Account
        The platform account whose state or access is being evaluated.
    destination_code : str
        The stable destination code from the relevant closed catalog.
    """
    locked_account = Account.objects.select_for_update().get(id=account.id)
    NavigationPin.objects.filter(
        account=locked_account,
        destination_code=destination_code.strip(),
    ).delete()
