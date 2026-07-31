"""Policy-narrow organizer relationship and platform inventory queries."""

from django.db.models import Count, QuerySet

from maru.identity.models import Account
from maru.organizations.models import Organization, OrganizationMembership


def platform_organization_inventory() -> QuerySet[Organization]:
    """Return the C1 organizer inventory for the platform administration page."""

    return Organization.objects.annotate(
        series_count=Count("convention_series", distinct=True),
        edition_count=Count("event_editions", distinct=True),
    ).order_by("name", "id")


def memberships_for_account(
    account: Account,
) -> QuerySet[OrganizationMembership]:
    return (
        OrganizationMembership.objects.filter(account=account)
        .select_related("organization")
        .order_by("organization__name", "organization_id")
    )
