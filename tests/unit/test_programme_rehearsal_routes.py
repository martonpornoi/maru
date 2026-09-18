"""Database-free joined routing checks, not page or native journey acceptance."""

import importlib
from uuid import UUID

import pytest
from django.conf import settings
from django.db.backends.base.base import BaseDatabaseWrapper
from django.urls import Resolver404, get_resolver, resolve, reverse
from django.urls.converters import IntConverter, UUIDConverter

from maru.events import adoption
from tests.rehearsals.programme_urls import OWNER_URLCONFS

URLCONF = "tests.rehearsals.programme_urls"
OWNER_PATTERNS = tuple(
    pattern
    for module in OWNER_URLCONFS
    for pattern in importlib.import_module(module).urlpatterns
)


def route_inputs(pattern):
    return {
        key: (
            UUID(int=index + 1)
            if isinstance(converter, UUIDConverter)
            else 1
            if isinstance(converter, IntConverter)
            else "synthetic"
        )
        for index, (key, converter) in enumerate(pattern.pattern.converters.items())
    }


@pytest.mark.parametrize("pattern", OWNER_PATTERNS, ids=lambda p: p.name)
def test_every_owner_route_round_trips_without_shadowing_or_replaced_handlers(pattern):
    values = route_inputs(pattern)
    url = reverse(pattern.name, kwargs=values, urlconf=URLCONF)
    match = resolve(url, urlconf=URLCONF)
    assert match.url_name == pattern.name
    assert match.func is pattern.callback
    assert match.kwargs == values | pattern.default_args


def test_joined_route_names_are_unique_and_preserve_all_existing_routes():
    names = [pattern.name for pattern in OWNER_PATTERNS]
    assert len(names) == len(set(names))
    current = get_resolver("maru.urls")
    joined = get_resolver(URLCONF)
    assert all(name in joined.reverse_dict for name in current.reverse_dict)
    assert not set(names) & set(current.reverse_dict)


@pytest.mark.parametrize("pattern", OWNER_PATTERNS, ids=lambda p: p.name)
@pytest.mark.parametrize("urlconf", ["maru.urls", "maru.baseline_urls"])
def test_preparation_never_mounts_dormant_handlers_in_current_urlconfs(
    pattern, urlconf
):
    url = reverse(pattern.name, kwargs=route_inputs(pattern), urlconf=URLCONF)
    try:
        match = resolve(url, urlconf=urlconf)
    except Resolver404:
        return
    assert match.func is not pattern.callback


def test_import_does_not_select_routes_mutate_profiles_or_open_database(monkeypatch):
    def forbidden(_connection):
        pytest.fail("Route preparation attempted a database connection")

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", forbidden)
    original_urlconf = settings.ROOT_URLCONF
    original_profiles = dict(adoption.ADOPTION_PROFILES)
    current = tuple(get_resolver("maru.urls").url_patterns)
    importlib.reload(importlib.import_module(URLCONF))
    assert original_urlconf == settings.ROOT_URLCONF
    assert original_profiles == adoption.ADOPTION_PROFILES
    assert tuple(get_resolver("maru.urls").url_patterns) == current
