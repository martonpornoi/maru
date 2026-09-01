"""Dormant Programme declarations must not widen an executable profile."""

from maru.authorization.catalog import ScopeLevel, require_capability
from maru.effects.handlers import built_in_handler_registry
from maru.effects.registry import event_definition
from maru.events.adoption import (
    ADOPTION_MODULE_NAMESPACE_CATALOG,
    ADOPTION_PROFILES,
    profile_adopts_module,
    profile_allows_adapter,
    profile_allows_capability,
    profile_allows_effect,
)
from maru.events.checks import current_adoption_catalog_snapshot
from maru.programme.adoption import (
    PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER,
)

PROGRAMME_CAPABILITIES = frozenset(
    {
        "programme.view_private",
        "programme.manage_items",
        "programme.view_readiness",
        "programme.manage_readiness",
        "programme.view_delivery",
        "programme.manage_delivery",
        "programme.view_discussion",
        "programme.view_public_copy",
        "programme.approve_public_copy",
    }
)


def test_programme_catalog_is_registered_but_every_current_profile_is_closed() -> None:
    snapshot = current_adoption_catalog_snapshot()

    assert "programme" in ADOPTION_MODULE_NAMESPACE_CATALOG
    assert "programme" in snapshot.module_codes
    assert snapshot.capability_codes >= PROGRAMME_CAPABILITIES
    assert PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER in snapshot.adapter_codes

    for profile_code, profile_version in ADOPTION_PROFILES:
        assert not profile_adopts_module(profile_code, profile_version, "programme")
        assert not profile_allows_adapter(
            profile_code,
            profile_version,
            PROGRAMME_ACCEPTED_APPLICATION_SOURCE_ADAPTER,
        )
        assert not profile_allows_effect(
            profile_code,
            profile_version,
            "programme.item.changed.v1",
            "internal",
        )
        for capability_code in PROGRAMME_CAPABILITIES:
            assert not profile_allows_capability(
                profile_code,
                profile_version,
                capability_code,
            )


def test_programme_capabilities_are_exact_edition_and_layer_bounded() -> None:
    private_view = require_capability("programme.view_private")
    readiness_view = require_capability("programme.view_readiness")
    delivery_view = require_capability("programme.view_delivery")
    discussion_view = require_capability("programme.view_discussion")
    public_view = require_capability("programme.view_public_copy")

    assert all(
        require_capability(code).maximum_scope is ScopeLevel.EDITION
        for code in PROGRAMME_CAPABILITIES
    )
    assert private_view.field_ceiling == frozenset(
        {
            "item_summaries",
            "working_information",
            "working_history",
            "public_copy_review_history",
        }
    )
    assert readiness_view.field_ceiling == frozenset(
        {"readiness_summary", "readiness_history"}
    )
    assert delivery_view.field_ceiling == frozenset(
        {"delivery_information", "delivery_history"}
    )
    assert discussion_view.field_ceiling == frozenset({"discussion_entries"})
    assert public_view.field_ceiling == frozenset({"latest_public_rendition"})


def test_programme_event_is_registered_without_current_route() -> None:
    definition = event_definition("programme.item.changed.v1")
    handlers = built_in_handler_registry()

    assert definition is not None
    assert definition.schema_version == 1
    assert (
        handlers.resolve(
            event_name="programme.item.changed.v1",
            destination="internal",
        )
        is None
    )
    assert (
        handlers.resolve(
            event_name="programme.item.changed.v1",
            destination="notifications",
        )
        is None
    )
