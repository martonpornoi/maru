"""Unit coverage for dormant Programme proposal adoption boundaries."""

from django.core.checks.registry import registry

from maru.applications.adoption import (
    APPLICATIONS_ADOPTION_ADAPTERS,
    TARGET_ADAPTER_CODES,
)
from maru.applications.programme_adoption import (
    APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
    APPLICATION_PROGRAMME_ITEM_TARGET_KIND,
    APPLICATION_PROGRAMME_SELF_ADAPTER,
    profile_allows_application_programme_self,
)
from maru.applications.programme_authorization import (
    APPLICATIONS_PROGRAMME_CAPABILITY_CODES,
)
from maru.applications.programme_checks import (
    check_applications_programme_dormancy,
)
from maru.events.adoption import (
    ADOPTION_PROFILES,
    profile_allows_adapter,
    profile_allows_capability,
)


def test_programme_proposal_adapters_are_registered_but_never_currently_pinned() -> (
    None
):
    """Keep new purpose and target adapters inert in both literal v1 profiles."""
    assert TARGET_ADAPTER_CODES[APPLICATION_PROGRAMME_ITEM_TARGET_KIND] == (
        APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER
    )
    assert {
        APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
        APPLICATION_PROGRAMME_SELF_ADAPTER,
    } <= set(APPLICATIONS_ADOPTION_ADAPTERS)

    for profile_code, profile_version in ADOPTION_PROFILES:
        assert not profile_allows_application_programme_self(
            profile_code,
            profile_version,
        )
        assert not profile_allows_adapter(
            profile_code,
            profile_version,
            APPLICATION_PROGRAMME_ITEM_TARGET_ADAPTER,
        )
        for capability_code in APPLICATIONS_PROGRAMME_CAPABILITY_CODES:
            assert not profile_allows_capability(
                profile_code,
                profile_version,
                capability_code,
            )


def test_applications_config_import_registers_programme_compatibility_check() -> None:
    """Keep deployment protection mounted through ApplicationsConfig.ready."""
    assert check_applications_programme_dormancy in registry.registered_checks
