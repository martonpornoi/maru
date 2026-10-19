"""Ownership contracts for shared-history session database initialization."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import connection

from tests import conftest


def _item(fixtures=(), marker=None):
    return SimpleNamespace(
        fixturenames=fixtures,
        get_closest_marker=lambda name: marker if name == "django_db" else None,
    )


@pytest.fixture
def session_setup(monkeypatch):
    configuration = object()
    setup = Mock(return_value=configuration)
    teardown = Mock()
    monkeypatch.setattr(conftest, "setup_databases", setup)
    monkeypatch.setattr(conftest, "teardown_databases", teardown)

    def exercise(items):
        request = SimpleNamespace(session=SimpleNamespace(items=items))
        blocker = SimpleNamespace(unblock=nullcontext)
        return conftest._shared_history_database.__wrapped__(None, blocker, request)

    return SimpleNamespace(
        exercise=exercise,
        setup=setup,
        teardown=teardown,
        configuration=configuration,
    )


@pytest.mark.parametrize("configured_name", ["maru", "test_demo"])
def test_standalone_history_creates_database_even_when_configured_name_is_prefixed(
    monkeypatch, session_setup, configured_name
):
    monkeypatch.setitem(connection.settings_dict, "NAME", configured_name)
    fixture = session_setup.exercise([_item(("historical_baseline",))])
    next(fixture)
    session_setup.setup.assert_called_once_with(
        verbosity=0,
        interactive=False,
        aliases={"default"},
        serialized_aliases=set(),
        keepdb=False,
    )
    session_setup.teardown.assert_not_called()
    fixture.close()
    session_setup.teardown.assert_called_once_with(
        session_setup.configuration, verbosity=0, keepdb=False
    )


@pytest.mark.parametrize(
    "database_item",
    [
        _item(("db",)),
        _item(("transactional_db",)),
        _item(marker=pytest.mark.django_db().mark),
        _item(marker=pytest.mark.django_db(databases=["default"]).mark),
    ],
    ids=["db-fixture", "transactional-fixture", "default-marker", "explicit-alias"],
)
def test_mixed_selection_retains_the_ordinary_session_owner(
    monkeypatch, session_setup, database_item
):
    monkeypatch.setitem(connection.settings_dict, "NAME", "test_demo")
    fixture = session_setup.exercise([_item(("historical_baseline",)), database_item])
    next(fixture)
    fixture.close()
    session_setup.setup.assert_not_called()
    session_setup.teardown.assert_not_called()


def test_another_alias_does_not_claim_default_database_initialization(session_setup):
    fixture = session_setup.exercise(
        [_item(marker=pytest.mark.django_db(databases=["other"]).mark)]
    )
    next(fixture)
    fixture.close()
    assert session_setup.setup.call_args.kwargs["aliases"] == {"default"}
    session_setup.teardown.assert_called_once_with(
        session_setup.configuration, verbosity=0, keepdb=False
    )


def test_owned_session_teardown_runs_when_a_history_fails(session_setup):
    fixture = session_setup.exercise([_item()])
    next(fixture)
    with pytest.raises(RuntimeError, match="synthetic history failure"):
        fixture.throw(RuntimeError("synthetic history failure"))
    session_setup.teardown.assert_called_once_with(
        session_setup.configuration, verbosity=0, keepdb=False
    )


def test_setup_failure_never_yields_an_unowned_database(session_setup):
    session_setup.setup.side_effect = RuntimeError("synthetic setup failure")
    fixture = session_setup.exercise([_item()])
    with pytest.raises(RuntimeError, match="synthetic setup failure"):
        next(fixture)
    session_setup.teardown.assert_not_called()


def test_owned_teardown_failure_is_not_hidden(session_setup):
    session_setup.teardown.side_effect = RuntimeError("synthetic teardown failure")
    fixture = session_setup.exercise([_item()])
    next(fixture)
    with pytest.raises(RuntimeError, match="synthetic teardown failure"):
        fixture.close()
