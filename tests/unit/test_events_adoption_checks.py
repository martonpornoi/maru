"""Unit coverage for exact adoption-manifest deployment checks."""

from dataclasses import replace
from types import MappingProxyType

import pytest
from django.core.checks import Tags, run_checks

from maru.events import adoption
from maru.events import checks as adoption_checks
from maru.events.adoption import (
    ADOPTION_PROFILES,
    SELECTABLE_ADOPTION_PROFILE_KEYS,
    AdoptionProfile,
    AdoptionProfileCode,
    adoption_profile,
    profile_adopts_module,
    profile_allows_adapter,
    profile_allows_catalog_entry,
    profile_allows_conflict_source,
    profile_allows_role,
)
from maru.events.adoption_contracts import AdoptionAdapterDescriptor


def _problem_codes_for_profile(profile: AdoptionProfile) -> tuple[str, ...]:
    """Validate one replacement profile inside the retained registry."""
    profiles = dict(ADOPTION_PROFILES)
    profiles[profile.key] = profile
    return adoption_checks.adoption_manifest_catalog_problem_codes(
        profiles=profiles,
        selectable_profile_keys=SELECTABLE_ADOPTION_PROFILE_KEYS,
        catalog=adoption_checks.current_adoption_catalog_snapshot(),
    )


def test_current_exact_manifests_resolve_against_independent_catalogs() -> None:
    """Keep every current exact reference registered without widening it."""
    snapshot = adoption_checks.current_adoption_catalog_snapshot()

    assert snapshot.registry_problem_codes == ()
    assert (
        adoption_checks.adoption_manifest_catalog_problem_codes(
            profiles=ADOPTION_PROFILES,
            selectable_profile_keys=SELECTABLE_ADOPTION_PROFILE_KEYS,
            catalog=snapshot,
        )
        == ()
    )
    assert adoption_checks.check_adoption_manifest_catalogs() == []


@pytest.mark.parametrize(
    ("field_name", "unregistered_code", "expected_problem"),
    [
        ("modules", "unregistered_module", "manifest.unregistered-module"),
        (
            "capability_codes",
            "workforce.future_registered_capability",
            "manifest.unregistered-capability",
        ),
        (
            "destination_codes",
            "future-workforce",
            "manifest.unregistered-staff-destination",
        ),
        (
            "shell_destination_kinds",
            "edition.workforce-roster",
            "manifest.unregistered-shell-destination",
        ),
        (
            "catalog_entries",
            "workforce.position-template.future@999",
            "manifest.unregistered-catalog-entry",
        ),
        (
            "adapter_codes",
            "workforce.future-adapter@999",
            "manifest.unregistered-adapter",
        ),
        (
            "conflict_source_codes",
            "workforce.future-conflict@999",
            "manifest.unregistered-conflict-source",
        ),
        (
            "root_role_codes",
            "future-controller",
            "manifest.unregistered-root-role",
        ),
    ],
)
def test_same_namespace_and_plausible_version_literals_do_not_self_register(
    field_name: str,
    unregistered_code: str,
    expected_problem: str,
) -> None:
    """Reject plausible-looking values that no independent owner registered."""
    full = adoption_profile("full_convention", 1)

    assert full is not None
    current_value = getattr(full, field_name)
    if isinstance(current_value, tuple):
        expanded_value = (*current_value, unregistered_code)
    else:
        expanded_value = frozenset((*current_value, unregistered_code))
    invalid = replace(full, **{field_name: expanded_value})

    assert expected_problem in _problem_codes_for_profile(invalid)


def test_primary_module_and_selectable_pairs_must_resolve_exactly() -> None:
    """Reject an unregistered primary module or a drifting selectable pair."""
    full = adoption_profile("full_convention", 1)

    assert full is not None
    invalid_primary = replace(
        full,
        modules=full.modules | {"unregistered_module"},
        primary_module="unregistered_module",
    )
    assert "manifest.unregistered-primary-module" in (
        _problem_codes_for_profile(invalid_primary)
    )

    mismatched_selection = dict(SELECTABLE_ADOPTION_PROFILE_KEYS)
    mismatched_selection[AdoptionProfileCode.FULL_CONVENTION] = (
        AdoptionProfileCode.WORKFORCE_ONLY.value,
        1,
    )
    problems = adoption_checks.adoption_manifest_catalog_problem_codes(
        profiles=ADOPTION_PROFILES,
        selectable_profile_keys=mismatched_selection,
        catalog=adoption_checks.current_adoption_catalog_snapshot(),
    )
    assert "selection.profile-code-mismatch" in problems

    missing_selection = dict(SELECTABLE_ADOPTION_PROFILE_KEYS)
    missing_selection[AdoptionProfileCode.FULL_CONVENTION] = (
        AdoptionProfileCode.FULL_CONVENTION.value,
        999,
    )
    problems = adoption_checks.adoption_manifest_catalog_problem_codes(
        profiles=ADOPTION_PROFILES,
        selectable_profile_keys=missing_selection,
        catalog=adoption_checks.current_adoption_catalog_snapshot(),
    )
    assert "selection.unregistered-profile" in problems


def test_registry_keys_and_versions_remain_exact_positive_integers() -> None:
    """Reject key drift and Python booleans masquerading as version one."""
    full = adoption_profile("full_convention", 1)

    assert full is not None
    keyed_as_v2 = dict(ADOPTION_PROFILES)
    keyed_as_v2.pop(full.key)
    keyed_as_v2[(full.code.value, 2)] = full
    problems = adoption_checks.adoption_manifest_catalog_problem_codes(
        profiles=keyed_as_v2,
        selectable_profile_keys=SELECTABLE_ADOPTION_PROFILE_KEYS,
        catalog=adoption_checks.current_adoption_catalog_snapshot(),
    )
    assert "manifest.registry-key-mismatch" in problems

    boolean_version = replace(full, version=True)
    assert "manifest.invalid-version" in _problem_codes_for_profile(boolean_version)
    assert adoption_profile("full_convention", version=True) is None
    with pytest.raises(RuntimeError, match="identity and modules"):
        adoption._validate_manifest(boolean_version)


def test_manifest_registry_and_database_guard_keys_must_match() -> None:
    """Require a migration-backed database key before a manifest can deploy."""
    snapshot = adoption_checks.current_adoption_catalog_snapshot()
    missing_database_key = replace(
        snapshot,
        persisted_profile_keys=frozenset({("full_convention", 1)}),
    )

    problems = adoption_checks.adoption_manifest_catalog_problem_codes(
        profiles=ADOPTION_PROFILES,
        selectable_profile_keys=SELECTABLE_ADOPTION_PROFILE_KEYS,
        catalog=missing_database_key,
    )

    assert "manifest.persistence-key-mismatch" in problems


def test_registered_members_still_require_an_adopted_owner_module() -> None:
    """Reject registered members whose owner module is outside the profile."""
    workforce = adoption_profile("workforce_only", 1)
    snapshot = adoption_checks.current_adoption_catalog_snapshot()
    registered_conflict = "registration.attendee-schedule@2"

    assert workforce is not None
    expanded_catalog = replace(
        snapshot,
        conflict_source_codes=(snapshot.conflict_source_codes | {registered_conflict}),
    )
    invalid = replace(
        workforce,
        conflict_source_codes=frozenset({registered_conflict}),
    )
    profiles = dict(ADOPTION_PROFILES)
    profiles[invalid.key] = invalid

    problems = adoption_checks.adoption_manifest_catalog_problem_codes(
        profiles=profiles,
        selectable_profile_keys=SELECTABLE_ADOPTION_PROFILE_KEYS,
        catalog=expanded_catalog,
    )
    assert "manifest.unregistered-conflict-source" not in problems
    assert "manifest.conflict-source-owner-not-adopted" in problems
    with pytest.raises(RuntimeError, match="belong to adopted modules"):
        adoption._validate_manifest(invalid)


def test_owner_registry_composition_preserves_cross_registry_defects() -> None:
    """Report duplicate typed codes instead of hiding them in a set union."""
    descriptor = AdoptionAdapterDescriptor(
        code="workforce.future-adapter@1",
        owner_module="workforce",
        kind="test-adapter",
        result_semantics="Returns one bounded test result.",
        failure_semantics="Returns no result when the test boundary is unavailable.",
    )
    registry = MappingProxyType({descriptor.code: descriptor})

    codes, problems = adoption_checks._collect_owned_descriptor_codes(
        registries=(
            ("workforce", registry),
            ("workforce", registry),
        ),
        registered_modules=frozenset({"workforce"}),
        registry_kind="adapter",
    )

    assert codes == {descriptor.code}
    assert problems == {"registry.duplicate-adapter"}


def test_catalog_entry_composition_preserves_source_integrity_defects() -> None:
    """Report duplicate, malformed, and wrong-owner entry declarations."""
    codes, problems = adoption_checks._collect_catalog_entry_codes(
        sources=(
            (
                "workforce",
                (
                    "workforce.position-template.future@1",
                    "applications.starter.future@1",
                    "not-versioned",
                ),
            ),
            ("workforce", ("workforce.position-template.future@1",)),
        ),
        registered_modules=frozenset({"workforce"}),
    )

    assert codes == {
        "applications.starter.future@1",
        "not-versioned",
        "workforce.position-template.future@1",
    }
    assert problems == {
        "registry.catalog-entry-owner-mismatch",
        "registry.duplicate-catalog-entry",
        "registry.malformed-catalog-entry",
    }


def test_registered_global_growth_does_not_widen_existing_manifests() -> None:
    """Allow additive catalog registration while every v1 helper remains closed."""
    snapshot = adoption_checks.current_adoption_catalog_snapshot()
    expanded = replace(
        snapshot,
        module_codes=snapshot.module_codes | {"scheduling"},
        catalog_entry_codes=(
            snapshot.catalog_entry_codes | {"workforce.position-template.future@2"}
        ),
        adapter_codes=snapshot.adapter_codes | {"workforce.future-adapter@2"},
        conflict_source_codes=(
            snapshot.conflict_source_codes | {"workforce.future-conflict@2"}
        ),
        root_role_codes=snapshot.root_role_codes | {"future-controller"},
    )

    assert (
        adoption_checks.adoption_manifest_catalog_problem_codes(
            profiles=ADOPTION_PROFILES,
            selectable_profile_keys=SELECTABLE_ADOPTION_PROFILE_KEYS,
            catalog=expanded,
        )
        == ()
    )
    for profile_code, profile_version in ADOPTION_PROFILES:
        assert not profile_adopts_module(profile_code, profile_version, "scheduling")
        assert not profile_allows_catalog_entry(
            profile_code,
            profile_version,
            "workforce.position-template.future@2",
        )
        assert not profile_allows_adapter(
            profile_code,
            profile_version,
            "workforce.future-adapter@2",
        )
        assert not profile_allows_conflict_source(
            profile_code,
            profile_version,
            "workforce.future-conflict@2",
        )
        assert not profile_allows_role(
            profile_code,
            profile_version,
            "future-controller",
        )


def test_system_check_returns_one_value_safe_error_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose only stable problem categories in one deployment error."""
    snapshot = adoption_checks.current_adoption_catalog_snapshot()
    monkeypatch.setattr(
        adoption_checks,
        "current_adoption_catalog_snapshot",
        lambda: replace(snapshot, capability_codes=frozenset()),
    )

    messages = adoption_checks.check_adoption_manifest_catalogs()

    assert len(messages) == 1
    assert messages[0].id == "events.E001"
    assert "manifest.unregistered-capability" in messages[0].hint
    assert "workforce.view_structure" not in messages[0].hint
    assert any(
        message.id == "events.E001" for message in run_checks(tags=[Tags.compatibility])
    )
