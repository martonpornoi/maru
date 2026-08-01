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
