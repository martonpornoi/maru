"""Keep the joined exit-generation downgrade fence explicit and source-pinned."""

from importlib import import_module
from unittest.mock import Mock

import pytest
from django.db import migrations
from django.db.migrations.loader import MigrationLoader

from maru.events.programme_stop_readiness import PROGRAMME_STOP_PREPARATION_CONTRACT

fence = import_module("maru.events.migrations.0017_programme_exit_recovery_fence")
retained = import_module(
    "maru.events.migrations.0018_programme_retained_recovery_fence"
)


def test_fence_is_required_by_exact_stop_readiness_and_reverses_first():
    assert PROGRAMME_STOP_PREPARATION_CONTRACT.source_contract_current
    assert ("events", "0017_programme_exit_recovery_fence") in (
        PROGRAMME_STOP_PREPARATION_CONTRACT.required_migrations
    )
    assert fence.Migration.dependencies == [("events", "0016_programme_stop_integrity")]
    assert len(fence.Migration.operations) == 1
    operation = fence.Migration.operations[0]
    assert isinstance(operation, migrations.RunPython)
    assert operation.code is migrations.RunPython.noop
    assert operation.reverse_code is fence.refuse_used_exit_generation_downgrade


@pytest.mark.parametrize(
    ("witness", "key"), [(False, False), (True, False), (False, True)]
)
def test_existing_native_attribution_refuses_before_any_successor_can_reverse(
    witness, key
):
    models = {
        ("audit", "AuditNativeMutationWitness"): Mock(),
        ("scheduling", "SchedulingReleaseDependencyKey"): Mock(),
    }
    schema = Mock()
    for target, exists in zip(models.values(), (witness, key), strict=True):
        target.objects.exists.side_effect = lambda result=exists: (
            schema.execute.assert_called_once(),
            result,
        )[1]
    apps = Mock()
    apps.get_model.side_effect = lambda *args: models[args]
    if witness or key:
        with pytest.raises(RuntimeError, match="retain its execution boundary"):
            fence.refuse_used_exit_generation_downgrade(apps, schema)
    else:
        fence.refuse_used_exit_generation_downgrade(apps, schema)
    schema.execute.assert_called_once_with(
        "LOCK TABLE public.audit_auditnativemutationwitness, "
        "public.scheduling_schedulingreleasedependencykey IN ACCESS EXCLUSIVE MODE"
    )


def test_retained_fence_is_pinned_and_calls_only_frozen_ancestor_preflights():
    terminal = ("events", "0018_programme_retained_recovery_fence")
    assert PROGRAMME_STOP_PREPARATION_CONTRACT.source_contract_current
    assert terminal in PROGRAMME_STOP_PREPARATION_CONTRACT.required_migrations
    ancestors = set(MigrationLoader(None).graph.forwards_plan(terminal))
    assert len(retained.PREFLIGHTS) == 30
    assert len(set(retained.PREFLIGHTS)) == 30
    assert retained.PREFLIGHTS[0] == (
        "events.0017_programme_exit_recovery_fence",
        "refuse_used_exit_generation_downgrade",
    )
    for reference, name in retained.PREFLIGHTS:
        owner, migration = reference.split(".", 1)
        assert (owner, migration) in ancestors
        assert callable(
            getattr(import_module(f"maru.{owner}.migrations.{migration}"), name)
        )
    operation = retained.Migration.operations[0]
    assert len(retained.Migration.operations) == 1
    assert operation.code is migrations.RunPython.noop
    assert operation.reverse_code is retained.refuse_retained_programme_downgrade


@pytest.mark.parametrize("failed_index", [None, *range(30)])
def test_retained_fence_preserves_order_and_never_swallows_owner_refusal(
    monkeypatch, failed_index
):
    calls = []
    apps, schema = object(), object()

    def load(path):
        index = len(calls)
        reference, name = retained.PREFLIGHTS[index]
        owner, migration = reference.split(".", 1)
        assert path == f"maru.{owner}.migrations.{migration}"

        def check(received_apps, received_schema):
            assert received_apps is apps
            assert received_schema is schema
            calls.append(reference)
            if index == failed_index:
                raise RuntimeError("original_owner_refusal")

        return type("FrozenOwner", (), {name: staticmethod(check)})

    monkeypatch.setattr(retained, "import_module", load)
    if failed_index is None:
        retained.refuse_retained_programme_downgrade(apps, schema)
        assert len(calls) == 30
    else:
        with pytest.raises(RuntimeError, match=r"^original_owner_refusal$"):
            retained.refuse_retained_programme_downgrade(apps, schema)
        assert len(calls) == failed_index + 1
