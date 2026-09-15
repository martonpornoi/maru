"""Exact Shift route admission and Events metadata contracts without native SQL."""

from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.db import DatabaseError
from django.http import HttpResponse
from django.urls import path, resolve

from maru.authorization.policy import PolicyDecision
from maru.events import queries as events
from maru.workforce import programme_navigation as navigation


def destination(request, **kwargs):
    return HttpResponse("Synthetic destination, not owner acceptance")


def routes(*, shadow=False):
    config = ModuleType(f"synthetic_shift_links_{uuid4().hex}")
    route = (
        "admin/platform/organizations/<slug:organization_slug>/series/"
        "<slug:series_slug>/editions/<slug:edition_slug>/structure/shifts/<uuid:demand_id>/"
    )
    config.urlpatterns = [path(route, destination, name="organization-workforce-shift")]
    if shadow:
        config.urlpatterns.insert(0, path("<path:rest>", destination, name="shadow"))
    return config


@pytest.fixture
def world(monkeypatch):
    decision = PolicyDecision(
        allowed=True,
        fields=navigation.SHIFT_ORGANIZER_REQUIRED_FIELDS,
        obligations=frozenset(),
        reason_code="synthetic_exact_fields",
    )
    policy = Mock(return_value=decision)
    metadata = Mock(
        return_value=events.EditionRouteIdentity("con", "annual", "edition")
    )
    monkeypatch.setattr(navigation, "decide_verified_principal_exact_edition", policy)
    monkeypatch.setattr(navigation, "resolve_edition_route_identity", metadata)
    return SimpleNamespace(
        policy=policy,
        metadata=metadata,
        decision=decision,
        kwargs={
            "actor_id": uuid4(),
            "organization_id": uuid4(),
            "series_id": uuid4(),
            "edition_id": uuid4(),
            "demand_ids": (uuid4(), uuid4()),
            "urlconf": routes(),
        },
    )


def test_exact_existing_demands_have_real_slug_routes_and_complete_fields(world):
    links = navigation.programme_shift_links(**world.kwargs)
    assert set(links) == set(world.kwargs["demand_ids"])
    for demand, url in links.items():
        assert resolve(url, urlconf=world.kwargs["urlconf"]).kwargs == {
            "organization_slug": "con",
            "series_slug": "annual",
            "edition_slug": "edition",
            "demand_id": demand,
        }
        assert "?" not in url
    world.metadata.assert_called_once_with(
        **{
            key: world.kwargs[key]
            for key in ("organization_id", "series_id", "edition_id")
        }
    )
    assert world.policy.call_count == 2
    assert world.policy.call_args.kwargs == {
        "principal_id": world.kwargs["actor_id"],
        "organization_id": world.kwargs["organization_id"],
        "edition_id": world.kwargs["edition_id"],
        "capability_code": "workforce.view_shifts",
        "requested_fields": navigation.SHIFT_ORGANIZER_REQUIRED_FIELDS,
    }


@pytest.mark.parametrize("field", sorted(navigation.SHIFT_ORGANIZER_REQUIRED_FIELDS))
def test_minimized_coverage_is_not_organizer_permission(world, field):
    world.policy.return_value = PolicyDecision(
        allowed=True,
        fields=world.decision.fields - {field},
        obligations=frozenset(),
        reason_code="partial_fields",
    )
    assert navigation.programme_shift_links(**world.kwargs) == {}
    world.metadata.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        "denied",
        "malformed_decision",
        "revoked",
        "foreign",
        "database",
        "unavailable",
        "unmounted",
        "shadowed",
    ],
)
def test_unavailable_destinations_are_omitted_without_source_reads(world, failure):
    if failure in {"denied", "revoked"}:
        denied = PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="denied",
        )
        world.policy.side_effect = (
            [denied] if failure == "denied" else [world.decision, denied]
        )
    elif failure == "malformed_decision":
        world.policy.return_value = object()
    elif failure == "foreign":
        world.metadata.return_value = None
    elif failure in {"database", "unavailable"}:
        world.metadata.side_effect = (
            DatabaseError if failure == "database" else RuntimeError
        )
    elif failure == "unmounted":
        world.kwargs["urlconf"].urlpatterns = []
    else:
        world.kwargs["urlconf"] = routes(shadow=True)
    assert navigation.programme_shift_links(**world.kwargs) == {}
    if failure in {"denied", "malformed_decision", "unmounted"}:
        world.metadata.assert_not_called()


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "series_id", "edition_id", "demand_ids"]
)
def test_malformed_scope_never_resolves_metadata(world, field):
    world.kwargs[field] = ("bad",) if field == "demand_ids" else "bad"
    assert navigation.programme_shift_links(**world.kwargs) == {}
    world.policy.assert_not_called()
    world.metadata.assert_not_called()


@pytest.mark.parametrize("count", [0, navigation.MAX_SHIFT_DEMANDS + 1])
def test_empty_or_excessive_destinations_are_not_enumerated(world, count):
    world.kwargs["demand_ids"] = (uuid4(),) * count
    assert navigation.programme_shift_links(**world.kwargs) == {}
    world.policy.assert_not_called()


@pytest.mark.parametrize("available", [True, False])
def test_events_exact_chain_projection_contains_only_three_locators(
    monkeypatch, available
):
    manager = Mock()
    manager.filter.return_value.values_list.return_value.first.return_value = (
        ("con", "annual", "edition") if available else None
    )
    monkeypatch.setattr(events, "EventEdition", SimpleNamespace(objects=manager))
    scope = {key: uuid4() for key in ("organization_id", "series_id", "edition_id")}
    result = events.resolve_edition_route_identity(**scope)
    manager.filter.assert_called_once_with(
        id=scope["edition_id"],
        organization_id=scope["organization_id"],
        series_id=scope["series_id"],
        series__organization_id=scope["organization_id"],
    )
    manager.filter.return_value.values_list.assert_called_once_with(
        "organization__slug", "series__slug", "slug"
    )
    assert result == (
        events.EditionRouteIdentity("con", "annual", "edition") if available else None
    )


def test_events_malformed_chain_does_not_query(monkeypatch):
    manager = Mock()
    monkeypatch.setattr(events, "EventEdition", SimpleNamespace(objects=manager))
    assert (
        events.resolve_edition_route_identity(
            organization_id="bad", series_id=uuid4(), edition_id=uuid4()
        )
        is None
    )
    manager.filter.assert_not_called()
