"""Minimized Events-owned stop observation, not a permission or stop command."""

from dataclasses import dataclass
from uuid import UUID

from maru.events.adoption import adoption_profile
from maru.events.models import EventEdition


@dataclass(frozen=True, slots=True)
class ProgrammeStopReference:
    """Expose only the exact Programme stop consequence and source version.

    Attributes
    ----------
    applies
        Whether this edition has the exact Programme Operations version-one pair.
    is_stopped
        Whether that pair is terminal; never a statement about another profile.
    version
        Events aggregate version observed under the caller's ownership locks.
    """

    applies: bool
    is_stopped: bool
    version: int


def resolve_programme_stop_reference(
    *, organization_id: UUID, edition_id: UUID
) -> ProgrammeStopReference | None:
    """Observe one coherent scope without disclosing labels or widening adoption.

    Parameters
    ----------
    organization_id : UUID
        Independently admitted organization owning both edition and series.
    edition_id : UUID
        Exact independently admitted edition, not a discovery input.

    Returns
    -------
    ProgrammeStopReference | None
        Minimal known state, or unavailable for invalid scope, missing profile or
        unknown lifecycle. Other registered profiles do not acquire Programme rules.

    Notes
    -----
    Writers must first hold the canonical Organization, Series and Edition locks
    and retain them through commit. Readers retain their own source rechecks and
    field policy. A non-stopped result grants no operation: every owner must still
    enforce its existing authority, lifecycle, native integrity and purpose rules.
    A future Programme version is unavailable until separately reviewed here.
    """
    if any(
        type(value) is not UUID or value.int == 0
        for value in (organization_id, edition_id)
    ):
        return None
    row = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .order_by()
        .values_list(
            "adoption_profile_code",
            "adoption_profile_version",
            "lifecycle",
            "aggregate_version",
        )
        .first()
    )
    if row is None:
        return None
    code, profile_version, lifecycle, aggregate_version = row
    if (
        adoption_profile(code, profile_version) is None
        or lifecycle not in EventEdition.Lifecycle.values
        or type(aggregate_version) is not int
        or aggregate_version < 1
        or (code == "programme_operations" and profile_version != 1)
    ):
        return None
    applies = (code, profile_version) == ("programme_operations", 1)
    return ProgrammeStopReference(
        applies=applies,
        is_stopped=applies and lifecycle in {"archived", "cancelled"},
        version=aggregate_version,
    )
