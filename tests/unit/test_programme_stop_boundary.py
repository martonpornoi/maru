"""Programme stop scope inventory and distinct requester-bound archive custody."""

from importlib import import_module

from django.apps import apps

from maru.events.programme_stop_readiness import PROGRAMME_STOP_PREPARATION_CONTRACT
from maru.programme.readiness import PROGRAMME_INTEGRITY_CONTRACT

GUARDS = import_module("maru.programme.migrations.0022_programme_stop_boundary")


def test_stop_scope_is_closed_and_archive_custody_is_separate():
    models = {
        model._meta.model_name
        for model in apps.get_app_config("programme").get_models()
    }
    assert set(GUARDS.GUARDED_MODELS).isdisjoint(GUARDS.ARCHIVE_MODELS)
    assert set(GUARDS.GUARDED_MODELS) | set(GUARDS.ARCHIVE_MODELS) == models
    assert set(GUARDS.PRIVACY_MODELS) <= set(GUARDS.GUARDED_MODELS)
    assert set(GUARDS.ARCHIVE_MODELS) == {
        "programmearchivetask",
        "programmearchivetaskevent",
        "programmearchivechunk",
    }
    assert len(GUARDS.GUARDED_MODELS) == len(set(GUARDS.GUARDED_MODELS))


def test_native_stop_guards_remain_source_pinned_and_not_callable_by_runtime():
    for contract in (PROGRAMME_INTEGRITY_CONTRACT, PROGRAMME_STOP_PREPARATION_CONTRACT):
        assert contract.source_contract_current
        assert (
            "programme",
            "0022_programme_stop_boundary",
        ) in contract.required_migrations
        triggers = {**contract.triggers, **contract.supporting_triggers}
        assert {
            value.table
            for name, value in triggers.items()
            if name.startswith("a00_programme_stop_")
        } == {f"programme_{model}" for model in GUARDS.GUARDED_MODELS}
        for name in (
            "maru_programme_stop_guard()",
            "maru_programme_stop_privacy_evidence()",
        ):
            assert not contract.functions[name].security_definer
            assert name not in contract.runtime_executable_functions
