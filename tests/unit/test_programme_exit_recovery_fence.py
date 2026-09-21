"""Keep the joined exit-generation downgrade fence explicit and source-pinned."""

from importlib import import_module
from unittest.mock import Mock

import pytest
from django.db import migrations

from maru.events.programme_stop_readiness import PROGRAMME_STOP_PREPARATION_CONTRACT

fence = import_module("maru.events.migrations.0017_programme_exit_recovery_fence")


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
