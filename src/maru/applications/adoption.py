"""Exact adoption-manifest keys consumed by the Applications module."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from maru.applications.programme_adoption import (
    APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
    APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
    APPLICATION_PROGRAMME_SELF_ADAPTER,
)
from maru.events.adoption import (
    profile_allows_adapter,
    profile_allows_capabilities,
    profile_allows_catalog_entry,
)
from maru.events.adoption_contracts import (
    AdoptionAdapterDescriptor,
    build_adoption_adapter_registry,
    build_adoption_conflict_source_registry,
)

if TYPE_CHECKING:
    from collections.abc import Collection

APPLICATION_SELF_ADAPTER = "applications.self@1"
APPLICATION_STARTER_CATALOG_VERSION = 1

ELIGIBILITY_ADAPTER_CODES = MappingProxyType(
    {
        "active_volunteer": "applications.eligibility.active_volunteer@1",
        "authenticated_person": "applications.eligibility.authenticated_person@1",
        "confirmed_attendee": "applications.eligibility.confirmed_attendee@1",
        "edition_participant": "applications.eligibility.edition_participant@1",
        "registered_attendee": "applications.eligibility.registered_attendee@1",
    }
)

SOURCE_ADAPTER_CODES = MappingProxyType(
    {
        "account.display_name": "applications.source.account.display_name@1",
        "registration.telegram": "applications.source.registration.telegram@1",
    }
)

TARGET_ADAPTER_CODES = MappingProxyType(
    {
        "merch_submission": "applications.target.merch_submission@1",
        "dj_set": "applications.target.dj_set@1",
        "fursuit_dance_competition": (
            "applications.target.fursuit_dance_competition@1"
        ),
        "maid_cafe": "applications.target.maid_cafe@1",
        "adult_fursuit_striptease": ("applications.target.adult_fursuit_striptease@1"),
        "volunteer": "applications.target.volunteer@1",
        "feedback": "applications.target.feedback@1",
        "idea": "applications.target.idea@1",
        "damage_report": "applications.target.damage_report@1",
        "helper": "applications.target.helper@1",
        APPLICATION_PROGRAMME_ITEM_TARGET_KIND: (
            APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER
        ),
    }
)

APPLICATIONS_ADOPTION_ADAPTERS = build_adoption_adapter_registry(
    owner_module="applications",
    descriptors=(
        AdoptionAdapterDescriptor(
            code=APPLICATION_SELF_ADAPTER,
            owner_module="applications",
            kind="self-discovery",
            result_semantics=(
                "Discovers person-owned Applications surfaces for an exact edition."
            ),
            failure_semantics=(
                "Returns no Applications self-service surface when the exact adapter "
                "is unavailable or unpinned."
            ),
        ),
        AdoptionAdapterDescriptor(
            code=APPLICATION_PROGRAMME_SELF_ADAPTER,
            owner_module="applications",
            kind="self-discovery",
            result_semantics=(
                "Discovers relationship-owned Programme proposal surfaces for one "
                "exact edition without exposing proposal content."
            ),
            failure_semantics=(
                "Returns no Programme proposal self-service surface when the exact "
                "adapter is unavailable or unpinned."
            ),
        ),
        *(
            AdoptionAdapterDescriptor(
                code=adapter_code,
                owner_module="applications",
                kind="eligibility-provider",
                result_semantics=(
                    "Returns whether an applicant satisfies the declared eligibility "
                    f"kind {eligibility_kind}."
                ),
                failure_semantics=(
                    "Rejects eligibility-provider use when the exact adapter for "
                    f"{eligibility_kind} is unavailable or unpinned."
                ),
            )
            for eligibility_kind, adapter_code in ELIGIBILITY_ADAPTER_CODES.items()
        ),
        *(
            AdoptionAdapterDescriptor(
                code=adapter_code,
                owner_module="applications",
                kind="source-binding",
                result_semantics=(
                    "Returns the purpose-bounded value for application source "
                    f"binding {source_binding}."
                ),
                failure_semantics=(
                    "Rejects the source binding without copying or disclosing a value "
                    f"when the exact {source_binding} adapter is unavailable."
                ),
            )
            for source_binding, adapter_code in SOURCE_ADAPTER_CODES.items()
        ),
        *(
            AdoptionAdapterDescriptor(
                code=adapter_code,
                owner_module="applications",
                kind="accepted-target",
                result_semantics=(
                    "Admits the immutable accepted-application transition for "
                    f"target kind {target_kind}."
                ),
                failure_semantics=(
                    "Rejects the accepted transition and creates no target record "
                    f"when the exact {target_kind} adapter is unavailable."
                ),
            )
            for target_kind, adapter_code in TARGET_ADAPTER_CODES.items()
            if target_kind != APPLICATION_PROGRAMME_ITEM_TARGET_KIND
        ),
        AdoptionAdapterDescriptor(
            code=APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
            owner_module="applications",
            kind="programme-proposal-target",
            result_semantics=(
                "Classifies one Applications-owned Programme proposal submission "
                "without enabling generic acceptance or Programme item creation."
            ),
            failure_semantics=(
                "Creates no proposal, acceptance target, or Programme item when the "
                "exact adapter is unavailable or unpinned."
            ),
        ),
    ),
)
APPLICATIONS_ADOPTION_CONFLICT_SOURCES = build_adoption_conflict_source_registry(
    owner_module="applications",
    descriptors=(),
)


def application_starter_entry_code(starter_code: str) -> str:
    """Return the exact manifest key for one Applications starter.

    Parameters
    ----------
    starter_code : str
        The stable starter code from the Applications-owned catalog.

    Returns
    -------
    str
        The exact versioned manifest entry.
    """
    return f"applications.starter.{starter_code}@{APPLICATION_STARTER_CATALOG_VERSION}"


def profile_allows_application_starter(
    profile_code: str,
    profile_version: int,
    starter_code: str,
) -> bool:
    """Return whether an exact profile pins one starter catalog entry.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    profile_version : int
        The persisted adoption-profile version.
    starter_code : str
        The stable Applications starter code.

    Returns
    -------
    bool
        ``True`` only when the exact manifest includes the starter version.
    """
    return profile_allows_catalog_entry(
        profile_code,
        profile_version,
        application_starter_entry_code(starter_code),
    )


def profile_allows_application_self(
    profile_code: str,
    profile_version: int,
) -> bool:
    """Return whether an exact profile admits Applications self-service.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    profile_version : int
        The persisted adoption-profile version.

    Returns
    -------
    bool
        ``True`` only when the exact manifest pins the self-purpose adapter.
    """
    return profile_allows_adapter(
        profile_code,
        profile_version,
        APPLICATION_SELF_ADAPTER,
    )


def profile_allows_application_eligibility(
    profile_code: str,
    profile_version: int,
    eligibility_kind: str,
) -> bool:
    """Return whether an exact profile admits one eligibility provider.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    profile_version : int
        The persisted adoption-profile version.
    eligibility_kind : str
        The closed Applications eligibility discriminator.

    Returns
    -------
    bool
        ``True`` only when the kind resolves to a pinned adapter.
    """
    adapter_code = ELIGIBILITY_ADAPTER_CODES.get(eligibility_kind)
    return adapter_code is not None and profile_allows_adapter(
        profile_code,
        profile_version,
        adapter_code,
    )


def profile_allows_application_source(
    profile_code: str,
    profile_version: int,
    source_binding: str,
) -> bool:
    """Return whether an exact profile admits one question-source provider.

    Empty source bindings do not invoke a provider and are therefore admitted.
    Unknown non-empty bindings fail closed.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    profile_version : int
        The persisted adoption-profile version.
    source_binding : str
        The closed Applications source-binding discriminator.

    Returns
    -------
    bool
        ``True`` when no provider is needed or the exact adapter is pinned.
    """
    if not source_binding:
        return True
    adapter_code = SOURCE_ADAPTER_CODES.get(source_binding)
    return adapter_code is not None and profile_allows_adapter(
        profile_code,
        profile_version,
        adapter_code,
    )


def profile_allows_application_target(
    profile_code: str,
    profile_version: int,
    target_adapter_kind: str,
) -> bool:
    """Return whether an exact profile admits one accepted-target adapter.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    profile_version : int
        The persisted adoption-profile version.
    target_adapter_kind : str
        The closed Applications target-adapter discriminator.

    Returns
    -------
    bool
        ``True`` only when the kind resolves to an exact pinned adapter.
    """
    adapter_code = TARGET_ADAPTER_CODES.get(target_adapter_kind)
    return adapter_code is not None and profile_allows_adapter(
        profile_code,
        profile_version,
        adapter_code,
    )


def profile_allows_application_reviewer_role(
    profile_code: str,
    profile_version: int,
    capability_codes: Collection[str],
    *,
    sensitive: bool,
) -> bool:
    """Return whether one complete immutable role may review this definition.

    A reviewer queue is a purpose relationship in addition to the caller's
    independent ``applications.review`` authority. The role must therefore
    contain the definition's required review capabilities and every capability
    in the immutable bundle must be pinned by the edition's exact manifest.

    Parameters
    ----------
    profile_code : str
        The persisted adoption-profile code.
    profile_version : int
        The persisted adoption-profile version.
    capability_codes : Collection[str]
        The complete capability set of the immutable reviewer role version.
    sensitive : bool
        Whether the definition also requires sensitive-review authority.

    Returns
    -------
    bool
        ``True`` only when the required and complete role sets are admitted.
    """
    role_capabilities = frozenset(capability_codes)
    required = {"applications.review"}
    if sensitive:
        required.add("applications.review_sensitive")
    return required <= role_capabilities and profile_allows_capabilities(
        profile_code,
        profile_version,
        role_capabilities,
    )


__all__ = [
    "APPLICATIONS_ADOPTION_ADAPTERS",
    "APPLICATIONS_ADOPTION_CONFLICT_SOURCES",
    "APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER",
    "APPLICATION_PROGRAMME_ITEM_TARGET_KIND",
    "APPLICATION_PROGRAMME_SELF_ADAPTER",
    "APPLICATION_SELF_ADAPTER",
    "APPLICATION_STARTER_CATALOG_VERSION",
    "ELIGIBILITY_ADAPTER_CODES",
    "SOURCE_ADAPTER_CODES",
    "TARGET_ADAPTER_CODES",
    "application_starter_entry_code",
    "profile_allows_application_eligibility",
    "profile_allows_application_reviewer_role",
    "profile_allows_application_self",
    "profile_allows_application_source",
    "profile_allows_application_starter",
    "profile_allows_application_target",
]
