"""Read-only public identity label queries for authorized projections."""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from maru.identity.models import Account


def account_display_labels(account_ids: Collection[UUID]) -> dict[UUID, str]:
    """Resolve bounded account IDs to safe display labels without contact data."""

    return {
        account.id: account.display_name.strip() or "Maru account"
        for account in Account.objects.filter(id__in=account_ids).only(
            "id",
            "display_name",
        )
    }


def active_person_account_display_labels(
    account_ids: Collection[UUID],
) -> dict[UUID, str]:
    """Resolve only active human accounts to minimized display labels.

    Callers provide an already authorized, bounded relationship set. Identity
    owns both the account-lifecycle filter and the only name-bearing read, so a
    stale, inactive, or non-person relationship never releases an identity
    label across the module boundary.
    """

    return {
        account.id: account.display_name.strip() or "Maru account"
        for account in Account.objects.filter(
            id__in=account_ids,
            is_active=True,
            account_kind=Account.Kind.PERSON,
        ).only(
            "id",
            "display_name",
        )
    }
