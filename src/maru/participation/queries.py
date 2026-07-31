"""Self-scoped participation queries."""

from django.db.models import QuerySet

from maru.identity.models import Account
from maru.participation.models import Participation


def participations_for_account(account: Account) -> QuerySet[Participation]:
    return (
        Participation.objects.filter(account=account)
        .select_related("organization", "edition__series")
        .prefetch_related("capacities")
        .order_by("-edition__starts_on", "edition_id")
    )


def archived_participations_for_account(
    account: Account,
) -> QuerySet[Participation]:
    return participations_for_account(account).filter(edition__lifecycle="archived")
