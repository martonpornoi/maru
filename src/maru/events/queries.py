"""Explicit read contracts owned by the events module."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final
from uuid import UUID

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
