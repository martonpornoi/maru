"""Close the Scheduling stop table inventory and exact source contract."""

from importlib import import_module

from django.apps import apps

from maru.scheduling.readiness import SCHEDULING_INTEGRITY_CONTRACT

GUARDS = import_module("maru.scheduling.migrations.0023_programme_stop_boundary")


def test_every_scheduling_relation_has_an_explicit_stop_disposition():
    owned = {
        model._meta.model_name
        for model in apps.get_app_config("scheduling").get_models()
    }
    invalidation = {
        "schedulingreleasedependencykey",
        "schedulingreleasedependencychange",
    }
    assert set(GUARDS.GUARDED_MODELS).isdisjoint(invalidation)
    assert set(GUARDS.GUARDED_MODELS) | invalidation == owned
    assert len(GUARDS.GUARDED_MODELS) == len(set(GUARDS.GUARDED_MODELS))


def test_stop_readiness_keeps_each_native_attachment_and_source_pin():
    contract = SCHEDULING_INTEGRITY_CONTRACT
    assert contract.source_contract_current
    assert (
        "scheduling",
        "0023_programme_stop_boundary",
    ) in contract.required_migrations
    assert {
        value.table
        for name, value in contract.triggers.items()
        if name.startswith("a00_sch_programme_stop_")
    } == {f"scheduling_{model}" for model in GUARDS.GUARDED_MODELS}
    function = contract.functions["maru_scheduling_programme_stop_guard()"]
    assert not function.security_definer
    assert function.configuration == ("search_path=pg_catalog, public, pg_temp",)
    assert (
        "maru_scheduling_programme_stop_guard()"
        not in contract.runtime_executable_functions
    )
