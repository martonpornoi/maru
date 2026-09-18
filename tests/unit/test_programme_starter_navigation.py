"""Mounted owner identity and current authority gate contextual starter entry."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.test import RequestFactory

from maru.identity.models import Account
from maru.workforce import programme_starter_navigation as navigation
from maru.workforce.programme_starter_inputs import ProgrammeStarterScope


@pytest.fixture
def entry(monkeypatch):
    request = RequestFactory().get("/")
    request.urlconf = "maru.workforce.programme_starter_urls"
    loader = Mock()
    monkeypatch.setattr(navigation, "load_programme_starter_creation", loader)
    return {
        "request": request,
        "actor": Account(id=UUID(int=4)),
        "scope": ProgrammeStarterScope(UUID(int=1), UUID(int=2), UUID(int=3)),
    }, loader


def test_real_joined_owner_is_audited_and_receives_original_actor_scope(entry):
    args, loader = entry
    url = navigation.programme_starter_entry_url(**args)
    assert url.endswith(f"/{args['scope'].edition_id}/")
    assert loader.call_args.kwargs["actor"] is args["actor"]
    assert loader.call_args.kwargs["scope"] == args["scope"]
    assert loader.call_args.kwargs["source_channel"] == "html"


def test_current_production_has_no_link_or_private_query(entry):
    args, loader = entry
    args["request"].urlconf = "maru.urls"
    assert navigation.programme_starter_entry_url(**args) == ""
    loader.assert_not_called()


def test_same_named_route_cannot_replace_real_owner(entry, monkeypatch):
    args, loader = entry
    monkeypatch.setattr(
        navigation, "resolve", lambda *_a, **_kw: SimpleNamespace(func=object())
    )
    assert navigation.programme_starter_entry_url(**args) == ""
    loader.assert_not_called()


@pytest.mark.parametrize(
    "error", [PermissionDenied(), ValidationError("drift"), DatabaseError()]
)
def test_unavailable_or_denied_owner_has_no_executable_link(entry, error):
    args, loader = entry
    loader.side_effect = error
    assert navigation.programme_starter_entry_url(**args) == ""
