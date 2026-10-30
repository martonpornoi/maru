"""Explicit read contracts owned by the events module."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet

from maru.events.adoption import ADOPTION_PROFILES, profile_keys_for_module
from maru.events.models import EventEdition

_PRIVATE_PLANNING_WRITE_LIFECYCLES: Final = frozenset(
    {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
    }
)


@dataclass(frozen=True, slots=True)
class EditionWorkPhaseReference:
    """Expose coherent owner lifecycle metadata for admitted home guidance.

    Attributes
    ----------
    edition_id, organization_id
        Exact owning scope, not a discovery or permission result.
    aggregate_version
        Current owner revision fencing lifecycle and time-zone changes.
    phase
        Planning/operation, cleanup-only closing, or retained review.
    time_zone
        IANA zone for authorized Shift decision boundaries.
    """

    edition_id: UUID
    organization_id: UUID
    aggregate_version: int
    phase: Literal["planning", "closing", "retained"]
    time_zone: str


def resolve_edition_work_phase_reference(
    *, organization_id: UUID, edition_id: UUID
) -> EditionWorkPhaseReference | None:
    """Read minimal phase metadata after the caller admits its complete fields.

    Parameters
    ----------
    organization_id : UUID
        Independently authorized owner of both edition and series.
    edition_id : UUID
        Exact authorized edition, never authority inferred from selection.

    Returns
    -------
    EditionWorkPhaseReference | None
        Coherent version/phase/zone, or no reference for invalid owner state.
        This seam grants no authority and is not a public lookup endpoint.
    """
    row = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .values_list(
            "id", "organization_id", "aggregate_version", "lifecycle", "time_zone"
        )
        .first()
    )
    if row is None:
        return None
    phase: Literal["planning", "closing", "retained"]
    if row[3] in {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
    }:
        phase = "planning"
    elif row[3] == EventEdition.Lifecycle.CLOSING:
        phase = "closing"
    elif row[3] in {EventEdition.Lifecycle.ARCHIVED, EventEdition.Lifecycle.CANCELLED}:
        phase = "retained"
    else:
        return None
    try:
        ZoneInfo(row[4])
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return EditionWorkPhaseReference(row[0], row[1], row[2], phase, row[4])


@dataclass(frozen=True, slots=True)
class PrivatePlanningEditionReference:
    """Project the exact edition scope used by private planning writers.

    Attributes
    ----------
    edition_id
        The exact event edition identifier.
    organization_id
        The organization that owns both the edition and its series.
    accepts_private_planning_writes
        Whether the current edition lifecycle admits private planning writes.
    """

    edition_id: UUID
    organization_id: UUID
    accepts_private_planning_writes: bool


def resolve_edition_series_identity(
    *, organization_id: UUID, edition_id: UUID
) -> UUID | None:
    """Resolve only the series ID needed to acquire canonical edition write locks.

    Parameters
    ----------
    organization_id : UUID
        Expected owner of both edition and series.
    edition_id : UUID
        Exact edition selected by an independently authorized command.

    Returns
    -------
    UUID | None
        Opaque candidate series ID, or unavailable for malformed or foreign scope.
        This unlocked discovery grants no authority; the writer must lock and
        recheck the entire chain before acquiring narrower owner rows.
    """
    try:
        return (
            EventEdition.objects.filter(
                id=edition_id,
                organization_id=organization_id,
                series__organization_id=organization_id,
            )
            .values_list("series_id", flat=True)
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        return None


@dataclass(frozen=True, slots=True)
class EditionRouteIdentity:
    """Exact owner route locators, not labels, source content or authority.

    Attributes
    ----------
    organization_slug
        Current organization route locator.
    series_slug
        Current coherent series route locator.
    edition_slug
        Current exact edition route locator.
    """

    organization_slug: str
    series_slug: str
    edition_slug: str


def resolve_edition_route_identity(
    *, organization_id: UUID, series_id: UUID, edition_id: UUID
) -> EditionRouteIdentity | None:
    """Resolve a coherent slug chain for an independently admitted destination.

    Parameters
    ----------
    organization_id : UUID
        Expected owner of both edition and series.
    series_id : UUID
        Exact expected parent, never inferred from selected shell context.
    edition_id : UUID
        Exact edition admitted by the caller's owning task policy.

    Returns
    -------
    EditionRouteIdentity | None
        Only the three current locators, or no coherent exact chain.

    Notes
    -----
    Internal metadata seam, not a directory or browser authorization API. Callers
    admit their complete destination policy before and after lookup, validate the
    resolved route, and repeat after rendering. No owner inventory is read.
    """
    if any(
        not isinstance(value, UUID)
        for value in (organization_id, series_id, edition_id)
    ):
        return None
    row = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series_id=series_id,
            series__organization_id=organization_id,
        )
        .values_list("organization__slug", "series__slug", "slug")
        .first()
    )
    return EditionRouteIdentity(*row) if row is not None else None


def resolve_private_planning_edition_reference(
    *,
    organization_id: UUID,
    edition_id: UUID,
    lock: bool = False,
) -> PrivatePlanningEditionReference | None:
    """Resolve exact tenant coherence and private-planning lifecycle state.

    This purpose-limited cross-module boundary returns no event model, series
    identifier, label, date, profile, or lifecycle value.  The boolean is
    derived by Events from the current lifecycle catalog, so consuming domain
    modules do not import private event models or duplicate that rule.  A
    command may request a row lock when it already owns the surrounding
    transaction.

    Parameters
    ----------
    organization_id : UUID
        The organization expected to own both the edition and its series.
    edition_id : UUID
        The exact event edition identifier to resolve.
    lock : bool, default=False
        Whether to acquire a PostgreSQL row lock on the selected edition.

    Returns
    -------
    PrivatePlanningEditionReference | None
        The minimized immutable scope, or ``None`` when the exact coherent
        tenant-owned edition is unavailable.
    """
    query = EventEdition.objects.all()
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        row = (
            query.filter(
                id=edition_id,
                organization_id=organization_id,
                series__organization_id=organization_id,
            )
            .values_list("id", "organization_id", "lifecycle")
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        return None
    if row is None:
        return None
    resolved_edition_id, resolved_organization_id, lifecycle = row
    return PrivatePlanningEditionReference(
        edition_id=resolved_edition_id,
        organization_id=resolved_organization_id,
        accepts_private_planning_writes=(
            lifecycle in _PRIVATE_PLANNING_WRITE_LIFECYCLES
        ),
    )


@dataclass(frozen=True, slots=True)
class EditionTimeEnvelopeReference:
    """Minimize the versioned edition-local date envelope to absolute instants.

    Attributes
    ----------
    edition_id
        Exact edition whose current dates were resolved.
    organization_id
        Organization owning the edition and its series.
    version
        Edition aggregate version that owns these date and time-zone facts.
    starts_at
        Inclusive start of the first local date, represented in UTC.
    ends_at
        Exclusive start of the day after the final local date, in UTC.
    """

    edition_id: UUID
    organization_id: UUID
    version: int
    starts_at: datetime
    ends_at: datetime


def resolve_edition_time_envelope_reference(
    *,
    organization_id: UUID,
    edition_id: UUID,
    lock: bool = False,
) -> EditionTimeEnvelopeReference | None:
    """Resolve bounded time facts after the caller independently authorizes scope.

    Parameters
    ----------
    organization_id : UUID
        Organization expected to own both the edition and its series.
    edition_id : UUID
        Exact edition requested by an independently authorized domain caller.
    lock : bool, default=False
        Whether to lock the owning edition inside the surrounding transaction.

    Returns
    -------
    EditionTimeEnvelopeReference | None
        Versioned absolute bounds, or unavailable for absent, incoherent or
        unrepresentable scope. No edition label or profile is disclosed.
    """
    query = EventEdition.objects.all()
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        row = (
            query.filter(
                id=edition_id,
                organization_id=organization_id,
                series__organization_id=organization_id,
            )
            .values_list("aggregate_version", "starts_on", "ends_on", "time_zone")
            .first()
        )
        if row is None:
            return None
        version, starts_on, ends_on, zone_name = row
        zone = ZoneInfo(zone_name)
        first_local = datetime.combine(starts_on, time.min, tzinfo=zone)
        final_local = datetime.combine(
            ends_on + timedelta(days=1), time.min, tzinfo=zone
        )
        start, end = first_local.astimezone(UTC), final_local.astimezone(UTC)
        if (
            version < 1
            or end <= start
            or start.astimezone(zone).replace(tzinfo=None)
            != first_local.replace(tzinfo=None)
            or end.astimezone(zone).replace(tzinfo=None)
            != final_local.replace(tzinfo=None)
            or first_local.utcoffset() != first_local.replace(fold=1).utcoffset()
            or final_local.utcoffset() != final_local.replace(fold=1).utcoffset()
        ):
            return None
    except (
        TypeError,
        ValueError,
        OverflowError,
        ValidationError,
        ZoneInfoNotFoundError,
    ):
        return None
    return EditionTimeEnvelopeReference(
        edition_id, organization_id, version, start, end
    )


@dataclass(frozen=True, slots=True)
class EditionAdoptionProfileReference:
    """Project the immutable adoption identity of one exact edition.

    Attributes
    ----------
    code
        The persisted adoption-profile code.
    version
        The persisted adoption-profile version.
    """

    code: str
    version: int


def adoption_profile_filter_for_module(
    module_code: str,
    *,
    field_prefix: str = "",
) -> Q:
    """Build an exact profile-code/version filter for an adopted module.

    Parameters
    ----------
    module_code : str
        Module whose explicitly pinned profile manifests may be selected.
    field_prefix : str, default=""
        Optional Django relation path before the edition profile fields, such
        as ``"edition"`` when filtering an edition-owned model.

    Returns
    -------
    Q
        A disjunction of exact code/version pairs. An unadopted module returns
        an always-empty profile-code condition rather than a permissive query.
    """
    lookup_prefix = f"{field_prefix}__" if field_prefix else ""
    profile_filter = Q(
        **{f"{lookup_prefix}adoption_profile_code__in": ()},
    )
    for profile_code, profile_version in profile_keys_for_module(module_code):
        profile_filter |= Q(
            **{
                f"{lookup_prefix}adoption_profile_code": profile_code,
                f"{lookup_prefix}adoption_profile_version": profile_version,
            }
        )
    return profile_filter


def adoption_profile_filter_for_capabilities(
    capability_codes: Collection[str],
    *,
    field_prefix: str = "",
) -> Q:
    """Build an exact profile filter for any requested capability.

    Parameters
    ----------
    capability_codes : Collection[str]
        Capability codes accepted by the calling route or projection.
    field_prefix : str, default=""
        Optional Django relation path before the edition profile fields.

    Returns
    -------
    Q
        A disjunction of exact manifest pairs that pin at least one requested
        capability. An empty or unknown set returns an always-empty
        profile-code condition.
    """
    lookup_prefix = f"{field_prefix}__" if field_prefix else ""
    profile_filter = Q(
        **{f"{lookup_prefix}adoption_profile_code__in": ()},
    )
    requested_capabilities = frozenset(capability_codes)
    for profile in ADOPTION_PROFILES.values():
        if not requested_capabilities.intersection(profile.capability_codes):
            continue
        profile_filter |= Q(
            **{
                f"{lookup_prefix}adoption_profile_code": profile.code.value,
                f"{lookup_prefix}adoption_profile_version": profile.version,
            }
        )
    return profile_filter


def adoption_profile_filter_for_adapter(
    adapter_code: str,
    *,
    field_prefix: str = "",
) -> Q:
    """Build an exact profile-code/version filter for one pinned adapter.

    Parameters
    ----------
    adapter_code : str
        Exact versioned purpose or cross-module adapter code.
    field_prefix : str, default=""
        Optional Django relation path before the edition profile fields.

    Returns
    -------
    Q
        A disjunction of exact manifest pairs that pin the adapter. An unknown
        adapter returns an always-empty profile-code condition.
    """
    lookup_prefix = f"{field_prefix}__" if field_prefix else ""
    profile_filter = Q(
        **{f"{lookup_prefix}adoption_profile_code__in": ()},
    )
    for profile in ADOPTION_PROFILES.values():
        if adapter_code not in profile.adapter_codes:
            continue
        profile_filter |= Q(
            **{
                f"{lookup_prefix}adoption_profile_code": profile.code.value,
                f"{lookup_prefix}adoption_profile_version": profile.version,
            }
        )
    return profile_filter


def edition_adoption_profile_reference(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> EditionAdoptionProfileReference | None:
    """Resolve an edition's adoption identity through its exact tenant.

    Parameters
    ----------
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact edition identifier.

    Returns
    -------
    EditionAdoptionProfileReference | None
        The minimized immutable profile reference, or ``None`` when the exact
        tenant-owned edition is unavailable.
    """
    row = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
        )
        .values_list("adoption_profile_code", "adoption_profile_version")
        .first()
    )
    if row is None:
        return None
    return EditionAdoptionProfileReference(code=row[0], version=row[1])


def platform_editions() -> QuerySet[EventEdition]:
    """Return edition identity for an already-authorized platform projection.

    Returns
    -------
    QuerySet[EventEdition]
        The matching platform editions records in deterministic order.
    """
    return (
        EventEdition.objects.filter(adoption_profile_filter_for_module("events"))
        .select_related("organization", "series")
        .order_by(
            "-starts_on",
            "name",
            "id",
        )
    )


@dataclass(frozen=True, slots=True)
class EditionRotaReference:
    """Project exact edition metadata for an independently admitted rota read.

    Attributes
    ----------
    id, organization_id, series_id
        Coherent owning identity, not authority or a directory.
    name, lifecycle, aggregate_version
        Edition label, retained lifecycle and source revision.
    starts_on, ends_on, time_zone
        Local date envelope and IANA time zone used for printed work.
    profile_code, profile_version
        Exact immutable adoption boundary; callers must admit it independently.
    """

    id: UUID
    organization_id: UUID
    series_id: UUID
    name: str
    lifecycle: str
    aggregate_version: int
    starts_on: date
    ends_on: date
    time_zone: str
    profile_code: str
    profile_version: int


def resolve_edition_rota_reference(
    *, organization_id: UUID, edition_id: UUID
) -> EditionRotaReference | None:
    """Read minimized owner metadata after independent full-field authorization.

    Parameters
    ----------
    organization_id : UUID
        Exact organization owning the operation.
    edition_id : UUID
        Exact trusted scope, never an inferred browser selection.

    Returns
    -------
    EditionRotaReference | None
        Coherent metadata or no reference. This internal owner seam grants no
        authorization and cannot be exposed as a public lookup adapter.
    """
    row = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .values_list(
            "id",
            "organization_id",
            "series_id",
            "name",
            "lifecycle",
            "aggregate_version",
            "starts_on",
            "ends_on",
            "time_zone",
            "adoption_profile_code",
            "adoption_profile_version",
        )
        .first()
    )
    return EditionRotaReference(*row) if row is not None else None
