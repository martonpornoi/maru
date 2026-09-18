"""Replay uses the shared retry lock, never write locks on immutable receipts."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from maru.applications import commands, programme_commands, programme_import_commands

MODELS = (
    "ApplicationCommandReceipt",
    "ProgrammeCommandReceipt",
    "ProgrammeImportCommandReceipt",
    "ProgrammeReviewReceipt",
    "ProgrammeAcceptedTransition",
)
CASES = (
    (commands, MODELS[0], commands.ApplicationIdempotencyConflict),
    (
        programme_commands,
        MODELS[1],
        programme_commands.ApplicationsProgrammeIdempotencyConflictError,
    ),
    (
        programme_import_commands,
        MODELS[2],
        programme_import_commands.ApplicationsProgrammeImportIdempotencyConflictError,
    ),
)


@pytest.fixture(params=CASES, ids=("generic", "programme", "import"))
def replay_boundary(request, monkeypatch):
    module, own_model, conflict_error = request.param
    actor_id, edition_id, retry_key, organization_id = (uuid4() for _ in range(4))
    filters = {"edition_id": edition_id, "actor_id": actor_id, "retry_key": retry_key}
    events = []
    state = SimpleNamespace(receipt=None, collision=None)

    def lock(**kwargs):
        assert kwargs == filters
        events.append("lock")

    class ReadOnlyManager:
        def __init__(self, model_name):
            self.model_name = model_name

        def select_for_update(self, **_kwargs):
            pytest.fail("Immutable receipt reads must not require UPDATE permission")

        def filter(self, **kwargs):
            assert events
            assert events[0] == "lock"
            assert kwargs == filters
            events.append(self.model_name)
            return self

        def first(self):
            assert self.model_name == own_model
            return state.receipt

        def exists(self):
            return state.collision == self.model_name

    monkeypatch.setattr(module, "lock_applications_retry_namespace", lock)
    result_name = (
        "_command_result" if module is programme_import_commands else "_result"
    )
    monkeypatch.setattr(
        module, result_name, lambda value, *, replayed: (value, replayed)
    )
    for model_name in MODELS:
        monkeypatch.setattr(
            getattr(module, model_name), "objects", ReadOnlyManager(model_name)
        )
    arguments = {
        "edition_id": edition_id,
        "retry_key": retry_key,
        "request_digest": "exact",
    }
    if module is commands:
        arguments["actor"] = SimpleNamespace(id=actor_id)
    else:
        arguments.update(
            actor_id=actor_id, organization_id=organization_id, authorizer=object()
        )
        admission = (
            "authorize_programme_retry_scope"
            if module is programme_commands
            else "authorize_programme_import_retry_scope"
        )

        def admit(**kwargs):
            assert not events
            assert kwargs["actor_id"] == actor_id
            assert kwargs["organization_id"] == organization_id
            assert kwargs["edition_id"] == edition_id

        monkeypatch.setattr(module, admission, admit)
    return SimpleNamespace(
        run=lambda: module._replay(**arguments),
        state=state,
        events=events,
        own_model=own_model,
        conflict_error=conflict_error,
    )


def test_empty_retry_reads_all_five_families_under_shared_lock(replay_boundary):
    assert replay_boundary.run() is None
    assert replay_boundary.events[0] == "lock"
    assert set(replay_boundary.events[1:]) == set(MODELS)
    assert len(replay_boundary.events) == 6


def test_exact_retry_recovers_only_original_receipt(replay_boundary):
    receipt = SimpleNamespace(request_digest="exact")
    replay_boundary.state.receipt = receipt
    assert replay_boundary.run() == (receipt, True)
    assert replay_boundary.events == ["lock", replay_boundary.own_model]


def test_changed_retry_keeps_original_conflict(replay_boundary):
    replay_boundary.state.receipt = SimpleNamespace(request_digest="changed")
    with pytest.raises(replay_boundary.conflict_error):
        replay_boundary.run()
    assert replay_boundary.events == ["lock", replay_boundary.own_model]


@pytest.mark.parametrize("other_index", range(4))
def test_cross_family_collision_still_conflicts(replay_boundary, other_index):
    other = [name for name in MODELS if name != replay_boundary.own_model][other_index]
    replay_boundary.state.collision = other
    with pytest.raises(replay_boundary.conflict_error):
        replay_boundary.run()
    assert replay_boundary.events[0] == "lock"
    assert replay_boundary.events[-1] == other
