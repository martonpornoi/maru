"""An active pointer needs real withdrawal even when its current output is stale."""

from uuid import uuid4

import pytest

from maru.scheduling import programme_stop_queries as queries


@pytest.mark.parametrize("active", [None, uuid4()])
@pytest.mark.parametrize("allowed", [False, True])
def test_exact_stored_pointer_not_output_freshness_determines_withdrawal_check(
    monkeypatch, active, allowed
):
    scope = {"actor_id": uuid4(), "organization_id": uuid4(), "edition_id": uuid4()}
    calls = []

    def authorize(**kwargs):
        calls.append(kwargs)
        if not allowed:
            raise queries.SchedulingAuthorizationDeniedError

    monkeypatch.setattr(queries, "authorize_scheduling_scope", authorize)
    assert queries._withdrawal_is_authorized(**scope, active_release_id=active) == (
        active is not None and allowed
    )
    assert calls == (
        [{**scope, "capability_code": queries.WITHDRAW_RELEASE}] if active else []
    )


def test_dependency_failure_is_not_reported_as_granted_withdrawal(monkeypatch):
    def unavailable(**_):
        raise RuntimeError("Synthetic unavailable policy")

    monkeypatch.setattr(queries, "authorize_scheduling_scope", unavailable)
    with pytest.raises(RuntimeError, match="Synthetic unavailable policy"):
        queries._withdrawal_is_authorized(
            actor_id=uuid4(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            active_release_id=uuid4(),
        )
