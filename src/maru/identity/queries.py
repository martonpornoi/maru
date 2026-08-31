"""Read-only public identity label queries for authorized projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.identity.models import Account

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ActiveVerifiedAccountReference:
    """Retain only the identifier of one current verified account.

    Attributes
    ----------
    account_id
        The opaque identifier of the current active, email-verified account.
    """

    account_id: UUID


def resolve_active_verified_account_reference(
    *,
    account_id: UUID,
    lock: bool = False,
) -> ActiveVerifiedAccountReference | None:
    """Resolve one current verified account without releasing identity data.

    This is the purpose-limited cross-module principal boundary.  It proves
    current account and email-verification state while returning no account
    model, name, contact address, account kind, authentication timestamp, or
    other identity fact.  A command may request a row lock when it already
    owns the surrounding transaction.

    Parameters
    ----------
    account_id : UUID
        The exact opaque account identifier to resolve.
    lock : bool, default=False
        Whether to acquire a PostgreSQL row lock on the selected account.

    Returns
    -------
    ActiveVerifiedAccountReference | None
        The minimized immutable reference, or ``None`` when the exact current
        verified account is unavailable.
    """
    query = Account.objects.all()
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        resolved_id = (
            query.filter(
                id=account_id,
                is_active=True,
                email_verified_at__isnull=False,
            )
            .values_list("id", flat=True)
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        return None
    if resolved_id is None:
        return None
    return ActiveVerifiedAccountReference(account_id=resolved_id)


def account_display_labels(account_ids: Collection[UUID]) -> dict[UUID, str]:
    """Resolve bounded account IDs to safe display labels without contact data.

    Parameters
    ----------
    account_ids : Collection[UUID]
        The selected account identifiers.

    Returns
    -------
    dict[UUID, str]
        A mapping containing the resolved account display labels data.
    """
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

    Parameters
    ----------
    account_ids : Collection[UUID]
        The selected account identifiers.

    Returns
    -------
    dict[UUID, str]
        A mapping containing the resolved active person account display labels
        data.
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
