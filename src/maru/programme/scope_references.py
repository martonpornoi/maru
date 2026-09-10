"""Programme scope references share staffing's canonical parent lock order."""

from uuid import UUID

from django.core.exceptions import ValidationError

from maru.events.queries import (
    PrivatePlanningEditionReference,
)
from maru.events.queries import (
    resolve_private_planning_edition_reference as resolve_events_planning_reference,
)
from maru.workforce.programme_references import lock_programme_staffing_scope


def resolve_private_planning_edition_reference(
    *, organization_id: UUID, edition_id: UUID, lock: bool = False
) -> PrivatePlanningEditionReference | None:
    """Resolve Events-owned planning facts with canonical parents before row locks.

    Parameters
    ----------
    organization_id : UUID
        Exact expected owner, not a discovery filter or authority grant.
    edition_id : UUID
        Exact edition whose Programme and Workforce state share the write scope.
    lock : bool, default=False
        Acquire shared parents and edition inside the existing transaction, then
        read the protected Events facts. Ordinary preauthorization stays read-only.

    Returns
    -------
    PrivatePlanningEditionReference | None
        Unchanged minimized Events facts, or unavailable for incoherent scope.

    Notes
    -----
    Every locking Programme item, host, readiness and staffing path must use this
    owner seam. An edition-first source command can otherwise deadlock with a
    staffing binding's parent locks when deferred receipt foreign keys commit.
    This changes no profile admission, lifecycle, person lock order or authority.
    """
    if lock:
        try:
            lock_programme_staffing_scope(
                organization_id=organization_id, edition_id=edition_id
            )
        except ValidationError:
            return None
    return resolve_events_planning_reference(
        organization_id=organization_id, edition_id=edition_id, lock=False
    )
