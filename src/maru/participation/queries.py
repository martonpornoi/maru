"""Self-scoped participation queries."""

from django.db.models import QuerySet

from maru.identity.models import Account
from maru.participation.models import Participation


def participations_for_account(account: Account) -> QuerySet[Participation]:
    """Return participations for account visible to the caller.

    Parameters
    ----------
    account : Account
        The account used to constrain the tenant-scoped query.

    Returns
    -------
    QuerySet[Participation]
        The authorized participations for account records in deterministic order.
    """
    return (
        Participation.objects.filter(account=account)
        .select_related("organization", "edition__series")
        .prefetch_related("capacities")
        .order_by("-edition__starts_on", "edition_id")
    )


def archived_participations_for_account(
    account: Account,
) -> QuerySet[Participation]:
    """Return archived participations for account visible to the caller.

    Parameters
    ----------
    account : Account
        The account used to constrain the tenant-scoped query.

    Returns
    -------
    QuerySet[Participation]
        The account's archived participation records in deterministic order.
    """
    return participations_for_account(account).filter(edition__lifecycle="archived")
