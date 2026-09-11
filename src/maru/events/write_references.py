"""Profile-neutral canonical ownership locks, without adoption or write authority."""

from uuid import UUID

from django.db import transaction

from maru.organizations.write_references import lock_series_ownership

from .models import EventEdition
from .queries import resolve_edition_series_identity


def lock_edition_ownership(*, organization_id: UUID, edition_id: UUID) -> bool:
    """Lock Organization, Series and Edition before person or native owner rows.

    Parameters
    ----------
    organization_id : UUID
        Independently authorized owner of both series and edition.
    edition_id : UUID
        Exact edition, never a discovered foreign pointer from a narrower lock.

    Returns
    -------
    bool
        Complete locked ownership in an active transaction, or unavailable.

    Notes
    -----
    This creates no module state and admits no lifecycle, profile or capability.
    In particular a Venue caller does not acquire Workforce adoption requirements
    merely to share the canonical parent order with a Programme publication.
    """
    if (
        not transaction.get_connection().in_atomic_block
        or not isinstance(organization_id, UUID)
        or not isinstance(edition_id, UUID)
    ):
        return False
    series_id = resolve_edition_series_identity(
        organization_id=organization_id, edition_id=edition_id
    )
    if series_id is None or not lock_series_ownership(
        organization_id=organization_id, series_id=series_id
    ):
        return False
    return (
        EventEdition.objects.select_for_update(of=("self",))
        .filter(id=edition_id, organization_id=organization_id, series_id=series_id)
        .order_by()
        .values_list("id", flat=True)
        .first()
    ) is not None
