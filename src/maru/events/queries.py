"""Explicit read contracts owned by the events module."""

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from django.db.models import Q, QuerySet

from maru.events.adoption import ADOPTION_PROFILES, profile_keys_for_module
from maru.events.models import EventEdition


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
