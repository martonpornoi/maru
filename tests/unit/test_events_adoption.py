"""Unit coverage for immutable exact-version adoption manifests."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace

import pytest
from django.db.models import Q

from maru.accreditation.adoption import (
    IDENTITY_RESTRICTION_CREDENTIAL_CONSEQUENCE_ADAPTER,
)
from maru.authorization.catalog import CAPABILITIES
from maru.effects.handlers import built_in_handler_registry
from maru.effects.registry import event_definition
from maru.events import adoption
from maru.events.adoption import (
    ADOPTION_PROFILES,
    PERSISTED_ADOPTION_PROFILE_CHOICES,
    SELECTABLE_ADOPTION_PROFILE_CHOICES,
    SHELL_DESTINATION_KIND_CATALOG,
    STAFF_CONSOLE_DESTINATION_CATALOG,
    adoption_profile,
    profile_adopts_module,
    profile_allows_adapter,
    profile_allows_capabilities,
    profile_allows_capability,
    profile_allows_catalog_entry,
    profile_allows_conflict_source,
    profile_allows_destination,
    profile_allows_effect,
    profile_allows_role,
    profile_allows_shell_destination,
    profile_keys_for_module,
)
from maru.events.adoption_persistence import PERSISTED_ADOPTION_PROFILE_KEYS
from maru.events.forms import RetainedAdoptionProfileChoiceField as FormProfileField
from maru.events.models import EventEdition
from maru.events.queries import (
    adoption_profile_filter_for_adapter,
    adoption_profile_filter_for_capabilities,
)
from maru.events.serializers import (
    RetainedAdoptionProfileChoiceField as SerializerProfileField,
)
from maru.participation.serializers import EditionContextSerializer
from maru.registration.adoption import IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER

_EXPECTED_FULL_V1_DESTINATIONS = (
    "today",
    "my-registration",
    "people",
    "workforce",
    "commerce",
    "reports",
    "setup",
    "security",
)

_EXPECTED_WORKFORCE_ONLY_V1_DESTINATIONS = (
    "today",
    "workforce",
    "setup",
    "security",
)

_EXPECTED_FULL_V1_SHELL_DESTINATION_KINDS = frozenset(
    {
        "edition.application-review",
        "edition.application-studio",
        "edition.catalog",
        "edition.charities",
        "edition.logistics",
        "edition.overview",
        "edition.registration",
        "edition.registration-commerce",
        "edition.structure",
        "edition.venues",
        "my.applications",
        "my.catalog",
        "my.equipment-offers",
        "my.registrations",
        "my.schedule",
        "my.workforce",
        "work.attendee-service",
        "work.people",
        "work.reports",
        "work.security",
        "work.setup",
        "work.today",
        "work.workforce",
    }
)

_EXPECTED_WORKFORCE_ONLY_V1_SHELL_DESTINATION_KINDS = frozenset(
    {
        "edition.overview",
        "edition.structure",
        "my.workforce",
        "work.security",
        "work.setup",
        "work.today",
        "work.workforce",
    }
)

_EXPECTED_MANIFEST_LITERAL_FINGERPRINTS = {
    ("full_convention", 1): (
        "e0081b116f8af045fd5a9195c1f4f3295b20d3c57163e8ef0a3547f86861df81"
    ),
    ("workforce_only", 1): (
        "66ad0e96a641d99e163d735d612dd2138c96ef0af619cfac57839695d09c2ad0"
    ),
}


def _manifest_literal_fingerprint(profile: adoption.AdoptionProfile) -> str:
    """Hash every independently ordered or sorted literal in one manifest."""
    snapshot = {
        "adapter_codes": sorted(profile.adapter_codes),
        "capability_codes": sorted(profile.capability_codes),
        "catalog_entries": sorted(profile.catalog_entries),
        "code": profile.code.value,
        "conflict_source_codes": sorted(profile.conflict_source_codes),
        "description": profile.description,
        "destination_codes": list(profile.destination_codes),
        "effect_routes": sorted(
            (route.event_name, route.destination) for route in profile.effect_routes
        ),
        "label": profile.label,
        "modules": sorted(profile.modules),
        "primary_module": profile.primary_module,
        "root_role_codes": sorted(profile.root_role_codes),
        "shell_destination_kinds": sorted(profile.shell_destination_kinds),
        "version": profile.version,
    }
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_v1_manifest_literal_snapshots_are_exact_and_independent() -> None:
    """Require a new version instead of mutating any full/workforce v1 literal."""
    assert {
        key: _manifest_literal_fingerprint(profile)
        for key, profile in ADOPTION_PROFILES.items()
    } == _EXPECTED_MANIFEST_LITERAL_FINGERPRINTS


def test_full_v1_alone_pins_both_identity_restriction_consequences() -> None:
    """Keep Registration and credential consequences independently adopted."""
    for adapter_code in (
        IDENTITY_RESTRICTION_CONSEQUENCE_ADAPTER,
        IDENTITY_RESTRICTION_CREDENTIAL_CONSEQUENCE_ADAPTER,
    ):
        assert profile_allows_adapter("full_convention", 1, adapter_code)
        assert not profile_allows_adapter("workforce_only", 1, adapter_code)
        assert not profile_allows_adapter("full_convention", 2, adapter_code)


def test_workforce_v1_keeps_identity_restriction_notifications_unadopted() -> None:
    """Keep Communications persistence outside the Workforce-only profile."""
    event_name = "identity.account_restriction.applied.v1"

    assert profile_allows_effect(
        "workforce_only",
        1,
        event_name,
        "internal",
    )
    assert not profile_allows_effect(
        "workforce_only",
        1,
        event_name,
        "notifications",
    )
    assert profile_allows_effect(
        "full_convention",
        1,
        event_name,
        "notifications",
    )


def test_retained_profile_choices_are_independent_from_new_selection() -> None:
    """Keep models, reads, and retries valid after one code retires from setup."""
    retired_selection = (SELECTABLE_ADOPTION_PROFILE_CHOICES[0],)
    retained_codes = {code for code, _label in PERSISTED_ADOPTION_PROFILE_CHOICES}

    assert retained_codes == {"full_convention", "workforce_only"}
    assert tuple(EventEdition._meta.get_field("adoption_profile_code").choices) == (
        PERSISTED_ADOPTION_PROFILE_CHOICES
    )

    form_field = FormProfileField(choices=retired_selection)
    assert tuple(form_field.choices) == retired_selection
    assert form_field.clean("workforce_only") == "workforce_only"

    serializer_field = SerializerProfileField(choices=retired_selection)
    assert tuple(serializer_field.choices.items()) == retired_selection
    assert serializer_field.run_validation("workforce_only") == "workforce_only"

    read_field = EditionContextSerializer().fields["adoption_profile_code"]
    assert "workforce_only" in read_field.choices


def test_current_manifest_identities_and_catalogs_are_exact() -> None:
    """Pin current profile versions, capability counts, and module selection."""
    full = adoption_profile("full_convention", 1)
    workforce = adoption_profile("workforce_only", 1)

    assert full is not None
    assert workforce is not None
    expected_foundation_modules = frozenset(
        {
            "audit",
            "authorization",
            "effects",
            "events",
            "identity",
            "organizations",
            "privacy",
        }
    )
    assert full.modules == expected_foundation_modules | {
        "accreditation",
        "applications",
        "catalog",
        "charities",
        "communications",
        "logistics",
        "participation",
        "registration",
        "venues",
        "workforce",
    }
    assert workforce.modules == expected_foundation_modules | {"workforce"}
    assert PERSISTED_ADOPTION_PROFILE_KEYS == (
        ("full_convention", 1),
        ("workforce_only", 1),
    )
    assert len(full.capability_codes) == 85
    assert len(workforce.capability_codes) == 29
    assert full.capability_codes <= CAPABILITIES.keys()
    assert workforce.capability_codes <= CAPABILITIES.keys()
    assert full.destination_codes == _EXPECTED_FULL_V1_DESTINATIONS
    assert workforce.destination_codes == _EXPECTED_WORKFORCE_ONLY_V1_DESTINATIONS
    assert frozenset(full.destination_codes) <= STAFF_CONSOLE_DESTINATION_CATALOG
    assert frozenset(workforce.destination_codes) <= (STAFF_CONSOLE_DESTINATION_CATALOG)
    assert full.shell_destination_kinds == _EXPECTED_FULL_V1_SHELL_DESTINATION_KINDS
    assert workforce.shell_destination_kinds == (
        _EXPECTED_WORKFORCE_ONLY_V1_SHELL_DESTINATION_KINDS
    )
    assert all(
        profile.shell_destination_kinds <= SHELL_DESTINATION_KIND_CATALOG
        for profile in ADOPTION_PROFILES.values()
    )
    assert "my.equipment-offers" in SHELL_DESTINATION_KIND_CATALOG
    assert "my.equipment_offers" not in SHELL_DESTINATION_KIND_CATALOG
    assert "work.my-registration" not in SHELL_DESTINATION_KIND_CATALOG
    assert profile_keys_for_module("registration") == (("full_convention", 1),)
    assert profile_keys_for_module("workforce") == (
        ("full_convention", 1),
        ("workforce_only", 1),
    )


@pytest.mark.parametrize(
    "declaration",
    [
        "modules",
        "capabilities",
        "shell destinations",
        "catalog entries",
        "adapters",
        "conflict sources",
        "root roles",
    ],
)
def test_set_declarations_reject_duplicates_before_freezing(
    declaration: str,
) -> None:
    """Keep every set-valued manifest source duplicate-sensitive."""
    with pytest.raises(RuntimeError, match="contains duplicate declarations"):
        adoption._freeze_unique(
            ("workforce.example@1", "workforce.example@1"),
            declaration=declaration,
        )


def test_ordered_and_registry_builders_reject_duplicate_sources() -> None:
    """Reject duplicate destinations and exact manifest keys before building."""
    full = adoption_profile("full_convention", 1)
    workforce = adoption_profile("workforce_only", 1)

    assert full is not None
    assert workforce is not None
    with pytest.raises(RuntimeError, match="contains duplicate declarations"):
        adoption._build_unique_tuple(
            ("today", "today"),
            declaration="Staff Console destinations",
        )
    with pytest.raises(RuntimeError, match="contains duplicate declarations"):
        adoption._build_unique_mapping(
            ((full.key, full), (full.key, workforce)),
            declaration="Adoption profile registry keys",
        )


def test_staff_console_destinations_must_resolve_in_server_catalog() -> None:
    """Fail import-time manifest validation for an unregistered destination."""
    full = adoption_profile("full_convention", 1)

    assert full is not None
    invalid = replace(
        full,
        destination_codes=(*full.destination_codes, "future-workspace"),
    )
    with pytest.raises(RuntimeError, match="server-owned catalog"):
        adoption._validate_manifest(invalid)


def test_registered_catalog_growth_does_not_expand_v1_manifests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep new same-namespace members out of both frozen v1 profiles."""
    profiles_before = {
        key: (
            profile.modules,
            profile.capability_codes,
            profile.destination_codes,
            profile.shell_destination_kinds,
        )
        for key, profile in ADOPTION_PROFILES.items()
    }
    future_module = "scheduling"
    future_capability = "workforce.future_registered_capability"
    future_destination = "future-workforce"
    future_shell_destination = "edition.workforce-roster"
    expanded_capabilities = adoption._freeze_unique(
        (*tuple(CAPABILITIES), future_capability),
        declaration="Expanded capability catalog",
    )
    expanded_modules = adoption._freeze_unique(
        (*tuple(adoption.ADOPTION_MODULE_NAMESPACE_CATALOG), future_module),
        declaration="Expanded module namespace catalog",
    )
    expanded_destinations = adoption._freeze_unique(
        (*tuple(STAFF_CONSOLE_DESTINATION_CATALOG), future_destination),
        declaration="Expanded Staff Console destination catalog",
    )
    expanded_shell_destinations = adoption._freeze_unique(
        (*tuple(SHELL_DESTINATION_KIND_CATALOG), future_shell_destination),
        declaration="Expanded shell destination catalog",
    )

    monkeypatch.setattr(
        adoption,
        "ADOPTION_MODULE_NAMESPACE_CATALOG",
        expanded_modules,
    )
    monkeypatch.setattr(
        adoption,
        "STAFF_CONSOLE_DESTINATION_CATALOG",
        expanded_destinations,
    )
    monkeypatch.setattr(
        adoption,
        "SHELL_DESTINATION_KIND_CATALOG",
        expanded_shell_destinations,
    )

    assert future_module in adoption.ADOPTION_MODULE_NAMESPACE_CATALOG
    assert future_capability in expanded_capabilities
    assert future_destination in adoption.STAFF_CONSOLE_DESTINATION_CATALOG
    assert future_shell_destination in adoption.SHELL_DESTINATION_KIND_CATALOG
    assert {
        key: (
            profile.modules,
            profile.capability_codes,
            profile.destination_codes,
            profile.shell_destination_kinds,
        )
        for key, profile in ADOPTION_PROFILES.items()
    } == profiles_before
    for profile_code, profile_version in ADOPTION_PROFILES:
        assert not profile_allows_capability(
            profile_code,
            profile_version,
            future_capability,
        )
        assert not profile_allows_destination(
            profile_code,
            profile_version,
            future_destination,
        )
        assert not profile_allows_shell_destination(
            profile_code,
            profile_version,
            future_shell_destination,
        )


@pytest.mark.parametrize(
    ("profile_code", "profile_version"),
    [
        ("full_convention", 2),
        ("workforce_only", 2),
        ("unknown", 1),
        ("full_convention", 0),
    ],
)
def test_unknown_exact_profile_pairs_fail_closed(
    profile_code: str,
    profile_version: int,
) -> None:
    """Reject unsupported pairs without falling back to a code or namespace."""
    assert adoption_profile(profile_code, profile_version) is None
    assert not profile_allows_capability(
        profile_code,
        profile_version,
        "workforce.view_structure",
    )


def test_capability_admission_never_expands_by_namespace() -> None:
    """Require literal capability pins and a non-empty complete role set."""
    assert profile_allows_capability(
        "workforce_only",
        1,
        "workforce.view_structure",
    )
    assert not profile_allows_capability(
        "workforce_only",
        1,
        "workforce.future_unpinned_capability",
    )
    assert profile_allows_capabilities(
        "workforce_only",
        1,
        ("workforce.view_structure", "workforce.manage_structure"),
    )
    assert not profile_allows_capabilities("workforce_only", 1, ())


@pytest.mark.parametrize(
    ("consumer", "value"),
    [
        (profile_adopts_module, "workforce"),
        (profile_allows_destination, "workforce"),
        (profile_allows_shell_destination, "work.workforce"),
        (
            profile_allows_catalog_entry,
            "workforce.structure-template.marucon-reference@1",
        ),
        (profile_allows_adapter, "workforce.self@1"),
        (profile_allows_conflict_source, "workforce.synthetic@1"),
        (profile_allows_role, "maru-operators"),
    ],
)
def test_every_manifest_helper_fails_closed_for_unknown_version(
    consumer: Callable[[str, int, str], bool],
    value: str,
) -> None:
    """Keep non-capability manifest consumers exact-version fail closed."""
    assert not consumer("workforce_only", 2, value)


def test_adapter_query_filter_is_exact_and_unknown_adapters_are_empty() -> None:
    """Build relation-safe query predicates from literal manifest pins only."""
    assert adoption_profile_filter_for_adapter(
        "venues.attendee-schedule@1",
        field_prefix="edition",
    ) == (
        Q(edition__adoption_profile_code__in=())
        | Q(
            edition__adoption_profile_code="full_convention",
            edition__adoption_profile_version=1,
        )
    )
    assert adoption_profile_filter_for_adapter("future.unknown@1") == Q(
        adoption_profile_code__in=()
    )


def test_capability_query_filter_is_exact_and_unknown_capabilities_are_empty() -> None:
    """Select only exact manifests that pin a requested capability."""
    assert adoption_profile_filter_for_capabilities(
        {"applications.review"},
        field_prefix="edition",
    ) == (
        Q(edition__adoption_profile_code__in=())
        | Q(
            edition__adoption_profile_code="full_convention",
            edition__adoption_profile_version=1,
        )
    )
    assert adoption_profile_filter_for_capabilities({"future.unknown"}) == Q(
        adoption_profile_code__in=()
    )
    assert adoption_profile_filter_for_capabilities(set()) == Q(
        adoption_profile_code__in=()
    )


def test_every_manifest_effect_route_resolves_a_registered_handler() -> None:
    """Keep every pinned event/destination pair executable."""
    handlers = built_in_handler_registry()

    assert {
        profile.key: len(profile.effect_routes)
        for profile in ADOPTION_PROFILES.values()
    } == {
        ("full_convention", 1): 65,
        ("workforce_only", 1): 24,
    }
    for profile in ADOPTION_PROFILES.values():
        for route in profile.effect_routes:
            assert event_definition(route.event_name) is not None
            assert (
                handlers.resolve(
                    event_name=route.event_name,
                    destination=route.destination,
                )
                is not None
            )


def test_effect_route_builder_rejects_duplicate_literal_pins() -> None:
    """Reject duplicate declarations before immutable-set normalization."""
    with pytest.raises(RuntimeError, match="effect routes must be unique"):
        adoption._build_effect_routes(
            internal_event_names=(
                "system.effect.probe_requested.v1",
                "system.effect.probe_requested.v1",
            )
        )
