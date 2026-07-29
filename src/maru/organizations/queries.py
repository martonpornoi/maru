"""Policy-narrow self queries for organizer relationships."""

from django.db.models import QuerySet

from maru.identity.models import Account
from maru.organizations.models import OrganizationMembership


def memberships_for_account(
    account: Account,
) -> QuerySet[OrganizationMembership]:
    return (
        OrganizationMembership.objects.filter(account=account)
        .select_related("organization")
        .order_by("organization__name", "organization_id")
    )
