"""Read-only public identity label queries for authorized projections."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from maru.identity.managers import AccountManager
from maru.identity.models import Account

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID

MAX_LOGIN_EMAIL_LENGTH = 254


def normalized_exact_login_email(value: object) -> str | None:
    """Return Identity's validated canonical login-email spelling.

    Parameters
    ----------
    value : object
        Untrusted value proposed for an exact login-email lookup.

    Returns
    -------
    str | None
        The NFC-normalized, case-folded login spelling, or ``None`` when the
        value cannot be an Identity login email.
    """
    if not isinstance(value, str):
        return None
    normalized = AccountManager.normalize_login_email(
        unicodedata.normalize("NFC", value)
    )
    if not normalized or len(normalized) > MAX_LOGIN_EMAIL_LENGTH:
        return None
    try:
        validate_email(normalized)
    except ValidationError:
        return None
    return normalized


@dataclass(frozen=True, slots=True)
class ActiveVerifiedAccountReference:
    """Retain only the identifier of one current verified account.

    Attributes
    ----------
    account_id
        The opaque identifier of the current active, email-verified account.
    """

    account_id: UUID


@dataclass(frozen=True, slots=True)
class ActiveVerifiedPersonReference:
    """Retain only the identifier of one current verified person account.

    Attributes
    ----------
    account_id
        The opaque identifier of the current active, email-verified person.
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


def resolve_active_verified_person_reference(
    *,
    account_id: UUID,
    lock: bool = False,
) -> ActiveVerifiedPersonReference | None:
    """Resolve one current verified person without releasing identity data.

    Parameters
    ----------
    account_id : UUID
        The exact opaque account identifier to resolve.
    lock : bool, default=False
        Whether to acquire a PostgreSQL row lock on the selected account.

    Returns
    -------
    ActiveVerifiedPersonReference | None
        The identifier-only reference, or ``None`` for every unavailable,
        inactive, unverified, non-person, or malformed lookup.
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
                account_kind=Account.Kind.PERSON,
            )
            .values_list("id", flat=True)
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        return None
    if resolved_id is None:
        return None
    return ActiveVerifiedPersonReference(account_id=resolved_id)


def resolve_active_verified_person_reference_by_email(
    *,
    email: object,
    lock: bool = False,
) -> ActiveVerifiedPersonReference | None:
    """Resolve one normalized exact login email to an identifier-only person.

    Invalid input, an unknown address, and every unusable account state all
    return the same empty result so callers cannot turn this purpose-limited
    invitation seam into a richer account-enumeration oracle.

    Parameters
    ----------
    email : object
        Untrusted invitation address to normalize with Identity's login rules.
    lock : bool, default=False
        Whether to acquire a PostgreSQL row lock on the selected account.

    Returns
    -------
    ActiveVerifiedPersonReference | None
        The identifier-only reference, or ``None`` for every non-match.
    """
    normalized = normalized_exact_login_email(email)
    if normalized is None:
        return None
    query = Account.objects.all()
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        resolved_id = (
            query.filter(
                email=normalized,
                is_active=True,
                email_verified_at__isnull=False,
                account_kind=Account.Kind.PERSON,
            )
            .values_list("id", flat=True)
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        return None
    if resolved_id is None:
        return None
    return ActiveVerifiedPersonReference(account_id=resolved_id)


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


def active_verified_person_account_display_labels(
    account_ids: Collection[UUID],
) -> dict[UUID, str]:
    """Resolve active verified human accounts to minimized display labels.

    Callers provide an already authorized, bounded relationship set. Identity
    owns the account-kind, lifecycle, and verification filters so Programme
    can fail closed to a neutral label when a relationship identity becomes
    unusable.

    Parameters
    ----------
    account_ids : Collection[UUID]
        The selected account identifiers.

    Returns
    -------
    dict[UUID, str]
        A mapping containing the resolved active verified person display
        labels.
    """
    return {
        account.id: account.display_name.strip() or "Maru account"
        for account in Account.objects.filter(
            id__in=account_ids,
            is_active=True,
            email_verified_at__isnull=False,
            account_kind=Account.Kind.PERSON,
        ).only(
            "id",
            "display_name",
        )
    }
