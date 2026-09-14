"""Creation metadata uses manage authority, not a private Programme inventory."""

from types import SimpleNamespace

import pytest

from maru.programme import creation_queries as creation
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.queries import ProgrammeQueryUnavailableError
from tests.unit import test_programme_workbench_queries as workbench


@pytest.fixture
def query(monkeypatch):
    base = workbench.query.__wrapped__(monkeypatch)
    base.admitted.accepts_private_planning_writes = True
    monkeypatch.setattr(creation, "authorize_programme_scope", base.auth)
    return base


def test_creation_state_is_audited_under_manage_without_private_inventory(query):
    result = creation.load_programme_creation_state(query.scope)
    assert result == creation.ProgrammeCreationState(3, writable=True)
    assert query.events[:2] == ["authorize", "lock"]
    assert query.events[-2:] == ["authorize", "audit"]
    assert all(
        entry.kwargs["capability_code"] == "programme.manage_items"
        and entry.kwargs["requested_fields"] == frozenset()
        for entry in query.auth.call_args_list
    )
    query.storage["ProgrammeItem"][0].assert_not_called()
    query.storage["ProgrammeWorkingRevision"][0].assert_not_called()
    assert query.audit.call_args.args[0].operation == "programme.query.creation_state"
    assert "Private label" not in repr(result)


def test_absent_unused_control_is_zero_but_missing_used_control_is_unavailable(query):
    query.storage["ProgrammeEditionControl"][1].first.return_value = None
    items = query.storage["ProgrammeItem"][1]
    items.exists.return_value = False
    assert creation.load_programme_creation_state(query.scope).control_version == 0
    items.exists.return_value = True
    with pytest.raises(ProgrammeQueryUnavailableError):
        creation.load_programme_creation_state(query.scope)


def test_closed_planning_keeps_cursor_but_never_claims_fresh_write(query):
    query.admitted.accepts_private_planning_writes = False
    query.storage["ProgrammeEditionControl"][1].first.return_value = SimpleNamespace(
        aggregate_version=9
    )
    assert creation.load_programme_creation_state(
        query.scope
    ) == creation.ProgrammeCreationState(9, writable=False)


def test_denial_precedes_storage_and_failed_audit_releases_no_cursor(query):
    query.auth.side_effect = ProgrammeAuthorizationDeniedError
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        creation.load_programme_creation_state(query.scope)
    query.storage["ProgrammeEditionControl"][0].assert_not_called()
    query.auth.side_effect = lambda **_kwargs: query.admitted
    query.audit.side_effect = ProgrammeAuthorizationDeniedError
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        creation.load_programme_creation_state(query.scope)
