"""Deployment checks for exact adoption-manifest catalog compatibility."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from django.core.checks import CheckMessage, Error, Tags, register

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from django.apps import AppConfig

    from maru.events.adoption import AdoptionProfile, AdoptionProfileCode


_MODULE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
_VERSIONED_CODE_PATTERN = re.compile(
    r"[a-z][a-z0-9_]*(?:[.-][a-z0-9_]+)*@[1-9][0-9]*\Z"
)
_ROLE_CODE_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class _OwnedAdoptionDescriptor(Protocol):
    """Expose the catalog identity shared by typed adoption descriptors."""

    @property
    def code(self) -> str:
        """Return the canonical exact-version descriptor code."""
        ...

    @property
    def owner_module(self) -> str:
        """Return the module that owns the descriptor contract."""
        ...


@dataclass(frozen=True, slots=True)
class AdoptionCatalogSnapshot:
    """Freeze every independent registry consumed by adoption manifests.

    Attributes
    ----------
    module_codes
        Module namespaces eligible for explicit adoption.
    capability_codes
        Authorization capabilities declared by the policy catalog.
    staff_console_destination_codes
        Server-owned Staff Console destinations.
    shell_destination_kinds
        Identifier-free shell destination kinds.
    catalog_entry_codes
        Versioned code-owned starter and template entries.
    adapter_codes
        Versioned module-owned adapter contracts.
    conflict_source_codes
        Versioned module-owned scheduling-conflict sources.
    root_role_codes
        Reserved accountable representation roles.
    persisted_profile_keys
        Exact manifest pairs admitted by the current database constraint.
    registry_problem_codes
        Stable deployment problem categories found while composing registries.
    """

    module_codes: frozenset[str]
    capability_codes: frozenset[str]
    staff_console_destination_codes: frozenset[str]
    shell_destination_kinds: frozenset[str]
    catalog_entry_codes: frozenset[str]
    adapter_codes: frozenset[str]
    conflict_source_codes: frozenset[str]
    root_role_codes: frozenset[str]
    persisted_profile_keys: frozenset[tuple[str, int]]
    registry_problem_codes: tuple[str, ...] = ()


def _collect_owned_descriptor_codes(
    *,
    registries: tuple[
        tuple[str, Mapping[str, _OwnedAdoptionDescriptor]],
        ...,
    ],
    registered_modules: frozenset[str],
    registry_kind: str,
) -> tuple[frozenset[str], set[str]]:
    """Compose typed owner registries without normalizing defects away.

    Parameters
    ----------
    registries : tuple[tuple[str, Mapping[str, _OwnedAdoptionDescriptor]], ...]
        Expected owner and immutable descriptor-registry pairs.
    registered_modules : frozenset[str]
        Module namespaces allowed to own adoption descriptors.
    registry_kind : str
        Stable problem-code suffix for this descriptor family.

    Returns
    -------
    tuple[frozenset[str], set[str]]
        Unique descriptor codes and retained registry problem categories.
    """
    codes: set[str] = set()
    problem_codes: set[str] = set()
    for expected_owner, registry in registries:
        for key, descriptor in registry.items():
            if key in codes:
                problem_codes.add(f"registry.duplicate-{registry_kind}")
            codes.add(key)
            if descriptor.code != key:
                problem_codes.add(f"registry.{registry_kind}-key-mismatch")
            if descriptor.owner_module != expected_owner:
                problem_codes.add(f"registry.{registry_kind}-owner-mismatch")
            if descriptor.owner_module not in registered_modules:
                problem_codes.add(f"registry.unregistered-{registry_kind}-owner")
    return frozenset(codes), problem_codes


def _collect_catalog_entry_codes(
    *,
    sources: tuple[tuple[str, tuple[str, ...]], ...],
    registered_modules: frozenset[str],
) -> tuple[frozenset[str], set[str]]:
    """Compose code-owned entries while retaining duplicate and owner evidence.

    Parameters
    ----------
    sources : tuple[tuple[str, tuple[str, ...]], ...]
        Expected owner and source-order versioned catalog-code pairs.
    registered_modules : frozenset[str]
        Module namespaces allowed to own catalog entries.

    Returns
    -------
    tuple[frozenset[str], set[str]]
        Unique entry codes and retained registry problem categories.
    """
    codes: set[str] = set()
    problem_codes: set[str] = set()
    for expected_owner, source_codes in sources:
        for code in source_codes:
            if code in codes:
                problem_codes.add("registry.duplicate-catalog-entry")
            codes.add(code)
            if _VERSIONED_CODE_PATTERN.fullmatch(code) is None:
                problem_codes.add("registry.malformed-catalog-entry")
            if not code.startswith(f"{expected_owner}."):
                problem_codes.add("registry.catalog-entry-owner-mismatch")
            if expected_owner not in registered_modules:
                problem_codes.add("registry.unregistered-catalog-entry-owner")
    return frozenset(codes), problem_codes


def current_adoption_catalog_snapshot() -> AdoptionCatalogSnapshot:
    """Compose the current independent adoption registries lazily.

    Returns
    -------
    AdoptionCatalogSnapshot
        Immutable codes and deterministic registry-integrity problem categories.
    """
    from maru.accreditation.adoption import (  # noqa: PLC0415
        ACCREDITATION_ADOPTION_ADAPTERS,
        ACCREDITATION_ADOPTION_CONFLICT_SOURCES,
    )
    from maru.applications.adoption import (  # noqa: PLC0415
        APPLICATIONS_ADOPTION_ADAPTERS,
        APPLICATIONS_ADOPTION_CONFLICT_SOURCES,
        application_starter_entry_code,
    )
    from maru.applications.starters import STARTERS  # noqa: PLC0415
    from maru.authorization.catalog import CAPABILITIES  # noqa: PLC0415
    from maru.events.adoption import (  # noqa: PLC0415
        ADOPTION_MODULE_NAMESPACE_CATALOG,
        SHELL_DESTINATION_KIND_CATALOG,
        STAFF_CONSOLE_DESTINATION_CATALOG,
    )
    from maru.events.adoption_contracts import (  # noqa: PLC0415
        FOUNDATION_ADOPTION_ADAPTERS,
        FOUNDATION_ADOPTION_CONFLICT_SOURCES,
    )
    from maru.events.adoption_persistence import (  # noqa: PLC0415
        PERSISTED_ADOPTION_PROFILE_KEYS,
    )
    from maru.organizations.representation_catalog import (  # noqa: PLC0415
        REPRESENTATION_DEFINITIONS,
        REPRESENTATION_ROLE_CODES,
    )
    from maru.participation.adoption import (  # noqa: PLC0415
        PARTICIPATION_ADOPTION_ADAPTERS,
        PARTICIPATION_ADOPTION_CONFLICT_SOURCES,
    )
    from maru.registration.adoption import (  # noqa: PLC0415
        REGISTRATION_ADOPTION_ADAPTERS,
        REGISTRATION_ADOPTION_CONFLICT_SOURCES,
        registration_starter_entry_code,
    )
    from maru.registration.starter_catalog import (  # noqa: PLC0415
        platform_registration_starters,
    )
    from maru.venues.adoption import (  # noqa: PLC0415
        VENUES_ADOPTION_ADAPTERS,
        VENUES_ADOPTION_CONFLICT_SOURCES,
    )
    from maru.workforce.adoption import (  # noqa: PLC0415
        WORKFORCE_ADOPTION_ADAPTERS,
        WORKFORCE_ADOPTION_CONFLICT_SOURCES,
    )
    from maru.workforce.starter_templates import (  # noqa: PLC0415
        WORKFORCE_VOLUNTEER_CATALOG_ENTRY,
    )
    from maru.workforce.structure_templates import (  # noqa: PLC0415
        BUILTIN_STRUCTURE_TEMPLATES,
        structure_template_entry_code,
    )

    module_codes = ADOPTION_MODULE_NAMESPACE_CATALOG
    registry_problem_codes: set[str] = set()
    if any(_MODULE_CODE_PATTERN.fullmatch(code) is None for code in module_codes):
        registry_problem_codes.add("registry.malformed-module")

    adapter_codes, adapter_problems = _collect_owned_descriptor_codes(
        registries=(
            ("foundation", FOUNDATION_ADOPTION_ADAPTERS),
            ("accreditation", ACCREDITATION_ADOPTION_ADAPTERS),
            ("applications", APPLICATIONS_ADOPTION_ADAPTERS),
            ("participation", PARTICIPATION_ADOPTION_ADAPTERS),
            ("registration", REGISTRATION_ADOPTION_ADAPTERS),
            ("venues", VENUES_ADOPTION_ADAPTERS),
            ("workforce", WORKFORCE_ADOPTION_ADAPTERS),
        ),
        registered_modules=module_codes,
        registry_kind="adapter",
    )
    conflict_source_codes, conflict_problems = _collect_owned_descriptor_codes(
        registries=(
            ("foundation", FOUNDATION_ADOPTION_CONFLICT_SOURCES),
            ("accreditation", ACCREDITATION_ADOPTION_CONFLICT_SOURCES),
            ("applications", APPLICATIONS_ADOPTION_CONFLICT_SOURCES),
            ("participation", PARTICIPATION_ADOPTION_CONFLICT_SOURCES),
            ("registration", REGISTRATION_ADOPTION_CONFLICT_SOURCES),
            ("venues", VENUES_ADOPTION_CONFLICT_SOURCES),
            ("workforce", WORKFORCE_ADOPTION_CONFLICT_SOURCES),
        ),
        registered_modules=module_codes,
        registry_kind="conflict-source",
    )
    catalog_entry_codes, catalog_problems = _collect_catalog_entry_codes(
        sources=(
            (
                "applications",
                tuple(
                    application_starter_entry_code(starter.code) for starter in STARTERS
                ),
            ),
            (
                "registration",
                tuple(
                    registration_starter_entry_code(starter.code, starter.version)
                    for starter in platform_registration_starters()
                ),
            ),
            ("workforce", (WORKFORCE_VOLUNTEER_CATALOG_ENTRY,)),
            (
                "workforce",
                tuple(
                    structure_template_entry_code(template.identifier)
                    for template in BUILTIN_STRUCTURE_TEMPLATES.values()
                ),
            ),
        ),
        registered_modules=module_codes,
    )
    registry_problem_codes.update(adapter_problems)
    registry_problem_codes.update(conflict_problems)
    registry_problem_codes.update(catalog_problems)
    if adapter_codes & conflict_source_codes:
        registry_problem_codes.add("registry.adapter-conflict-source-overlap")
    if catalog_entry_codes & adapter_codes:
        registry_problem_codes.add("registry.catalog-entry-adapter-overlap")
    if catalog_entry_codes & conflict_source_codes:
        registry_problem_codes.add("registry.catalog-entry-conflict-source-overlap")

    declared_root_roles = tuple(
        definition.role_code for definition in REPRESENTATION_DEFINITIONS.values()
    )
    root_role_codes = frozenset(declared_root_roles)
    if len(root_role_codes) != len(declared_root_roles):
        registry_problem_codes.add("registry.duplicate-root-role")
    if root_role_codes != REPRESENTATION_ROLE_CODES:
        registry_problem_codes.add("registry.root-role-catalog-mismatch")
    if any(
        _ROLE_CODE_PATTERN.fullmatch(role_code) is None for role_code in root_role_codes
    ):
        registry_problem_codes.add("registry.malformed-root-role")

    return AdoptionCatalogSnapshot(
        module_codes=module_codes,
        capability_codes=frozenset(CAPABILITIES),
        staff_console_destination_codes=STAFF_CONSOLE_DESTINATION_CATALOG,
        shell_destination_kinds=SHELL_DESTINATION_KIND_CATALOG,
        catalog_entry_codes=catalog_entry_codes,
        adapter_codes=adapter_codes,
        conflict_source_codes=conflict_source_codes,
        root_role_codes=root_role_codes,
        persisted_profile_keys=frozenset(PERSISTED_ADOPTION_PROFILE_KEYS),
        registry_problem_codes=tuple(sorted(registry_problem_codes)),
    )


def _is_positive_integer_version(value: object) -> bool:
    """Return whether a version is an integer but not Python's boolean subtype.

    Parameters
    ----------
    value : object
        Runtime value proposed as one exact profile version.

    Returns
    -------
    bool
        ``True`` only for a strictly positive non-boolean integer.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _profile_catalog_problem_codes(
    *,
    key: tuple[str, int],
    profile: AdoptionProfile,
    catalog: AdoptionCatalogSnapshot,
) -> set[str]:
    """Validate one retained manifest against one independent snapshot.

    Parameters
    ----------
    key : tuple[str, int]
        Exact registry key retaining the manifest.
    profile : AdoptionProfile
        Immutable manifest to resolve.
    catalog : AdoptionCatalogSnapshot
        Independently composed code-owned catalog snapshot.

    Returns
    -------
    set[str]
        Stable problem categories for this manifest.
    """
    problem_codes: set[str] = set()
    if key != profile.key:
        problem_codes.add("manifest.registry-key-mismatch")
    if not _is_positive_integer_version(profile.version) or not (
        _is_positive_integer_version(key[1])
    ):
        problem_codes.add("manifest.invalid-version")
    if profile.primary_module not in profile.modules:
        problem_codes.add("manifest.primary-module-not-adopted")
    if profile.primary_module not in catalog.module_codes:
        problem_codes.add("manifest.unregistered-primary-module")

    membership_checks = (
        ("manifest.unregistered-module", profile.modules, catalog.module_codes),
        (
            "manifest.unregistered-capability",
            profile.capability_codes,
            catalog.capability_codes,
        ),
        (
            "manifest.unregistered-staff-destination",
            frozenset(profile.destination_codes),
            catalog.staff_console_destination_codes,
        ),
        (
            "manifest.unregistered-shell-destination",
            profile.shell_destination_kinds,
            catalog.shell_destination_kinds,
        ),
        (
            "manifest.unregistered-catalog-entry",
            profile.catalog_entries,
            catalog.catalog_entry_codes,
        ),
        (
            "manifest.unregistered-adapter",
            profile.adapter_codes,
            catalog.adapter_codes,
        ),
        (
            "manifest.unregistered-conflict-source",
            profile.conflict_source_codes,
            catalog.conflict_source_codes,
        ),
        (
            "manifest.unregistered-root-role",
            profile.root_role_codes,
            catalog.root_role_codes,
        ),
    )
    for problem_code, declared_codes, registered_codes in membership_checks:
        if not declared_codes <= registered_codes:
            problem_codes.add(problem_code)

    owner_checks = (
        (
            "manifest.capability-owner-not-adopted",
            profile.capability_codes,
        ),
        (
            "manifest.catalog-entry-owner-not-adopted",
            profile.catalog_entries,
        ),
        ("manifest.adapter-owner-not-adopted", profile.adapter_codes),
        (
            "manifest.conflict-source-owner-not-adopted",
            profile.conflict_source_codes,
        ),
    )
    for problem_code, declared_codes in owner_checks:
        if any(
            code.partition(".")[0] not in profile.modules for code in declared_codes
        ):
            problem_codes.add(problem_code)
    return problem_codes


def _selection_catalog_problem_codes(
    *,
    selectable_code: AdoptionProfileCode,
    key: tuple[str, int],
    profiles: Mapping[tuple[str, int], AdoptionProfile],
) -> set[str]:
    """Validate one currently offered profile against retained exact pairs.

    Parameters
    ----------
    selectable_code : AdoptionProfileCode
        Profile code offered by setup.
    key : tuple[str, int]
        Exact manifest pair selected for that code.
    profiles : Mapping[tuple[str, int], AdoptionProfile]
        Every retained immutable exact-version manifest.

    Returns
    -------
    set[str]
        Stable problem categories for this selectable pair.
    """
    problem_codes: set[str] = set()
    if not _is_positive_integer_version(key[1]):
        problem_codes.add("selection.invalid-version")
    if selectable_code.value != key[0]:
        problem_codes.add("selection.profile-code-mismatch")
    if key not in profiles:
        problem_codes.add("selection.unregistered-profile")
    return problem_codes


def adoption_manifest_catalog_problem_codes(
    *,
    profiles: Mapping[tuple[str, int], AdoptionProfile],
    selectable_profile_keys: Mapping[AdoptionProfileCode, tuple[str, int]],
    catalog: AdoptionCatalogSnapshot,
) -> tuple[str, ...]:
    """Return stable categories for unresolved manifest registry references.

    Parameters
    ----------
    profiles : Mapping[tuple[str, int], AdoptionProfile]
        Every retained immutable exact-version manifest.
    selectable_profile_keys : Mapping[AdoptionProfileCode, tuple[str, int]]
        The one currently selectable exact pair for each offered profile code.
    catalog : AdoptionCatalogSnapshot
        Independently composed code-owned catalog snapshot.

    Returns
    -------
    tuple[str, ...]
        Sorted, duplicate-free deployment problem categories.
    """
    problem_codes = set(catalog.registry_problem_codes)
    if frozenset(profiles) != catalog.persisted_profile_keys:
        problem_codes.add("manifest.persistence-key-mismatch")
    for key, profile in profiles.items():
        problem_codes.update(
            _profile_catalog_problem_codes(
                key=key,
                profile=profile,
                catalog=catalog,
            )
        )
    for selectable_code, key in selectable_profile_keys.items():
        problem_codes.update(
            _selection_catalog_problem_codes(
                selectable_code=selectable_code,
                key=key,
                profiles=profiles,
            )
        )
    return tuple(sorted(problem_codes))


@register(Tags.compatibility)
def check_adoption_manifest_catalogs(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[CheckMessage]:
    """Validate exact manifests against their independently owned catalogs.

    Parameters
    ----------
    app_configs : Iterable[AppConfig] | None, default=None
        Installed Django application configurations supplied by the check runner.
    **kwargs : object
        Keyword arguments forwarded by Django's check framework.

    Returns
    -------
    list[CheckMessage]
        A value-safe deployment error when any exact reference is unresolved.
    """
    del app_configs, kwargs

    from maru.events.adoption import (  # noqa: PLC0415
        ADOPTION_PROFILES,
        SELECTABLE_ADOPTION_PROFILE_KEYS,
    )

    problem_codes = adoption_manifest_catalog_problem_codes(
        profiles=ADOPTION_PROFILES,
        selectable_profile_keys=SELECTABLE_ADOPTION_PROFILE_KEYS,
        catalog=current_adoption_catalog_snapshot(),
    )
    if not problem_codes:
        return []
    return [
        Error(
            "An exact adoption manifest does not resolve against its catalogs.",
            hint=(
                "Repair the code-owned registry or publish a reviewed new manifest "
                "version before deployment. Problem categories: "
                f"{', '.join(problem_codes)}."
            ),
            id="events.E001",
        )
    ]


__all__ = [
    "AdoptionCatalogSnapshot",
    "adoption_manifest_catalog_problem_codes",
    "check_adoption_manifest_catalogs",
    "current_adoption_catalog_snapshot",
]
