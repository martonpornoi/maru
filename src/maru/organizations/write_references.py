"""Identifier-only parent locks for independently authorized native writers."""

from uuid import UUID

from django.db import transaction

from .models import ConventionSeries, Organization


def lock_organization_ownership(*, organization_id: UUID) -> bool:
    """Lock an exact owning organization without granting lifecycle or authority.

    Parameters
    ----------
    organization_id : UUID
        Independently authorized owner identity, before narrower locks.

    Returns
    -------
    bool
        Whether the exact identity exists in the caller's active transaction.
    """
    if not transaction.get_connection().in_atomic_block or not isinstance(
        organization_id, UUID
    ):
        return False
    return (
        Organization.objects.select_for_update()
        .filter(id=organization_id)
        .order_by()
        .values_list("id", flat=True)
        .first()
    ) is not None


def lock_series_ownership(*, organization_id: UUID, series_id: UUID) -> bool:
    """Lock and recheck Organization then exact Convention Series ownership.

    Parameters
    ----------
    organization_id : UUID
        Expected independently authorized parent organization.
    series_id : UUID
        Opaque series identity discovered before acquiring narrower rows.

    Returns
    -------
    bool
        Complete locked parent ownership, without labels or adoption permission.
    """
    if not isinstance(series_id, UUID) or not lock_organization_ownership(
        organization_id=organization_id
    ):
        return False
    return (
        ConventionSeries.objects.select_for_update()
        .filter(id=series_id, organization_id=organization_id)
        .order_by()
        .values_list("id", flat=True)
        .first()
    ) is not None
