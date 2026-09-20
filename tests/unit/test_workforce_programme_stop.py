"""Keep the Workforce terminal inventory explicit, complete and source-pinned."""

from importlib import import_module

from django.apps import apps

from maru.events.programme_stop_readiness import PROGRAMME_STOP_PREPARATION_CONTRACT
from maru.workforce.programme_starter_readiness import (
    PROGRAMME_STARTER_INTEGRITY_CONTRACT,
)

GUARDS = import_module("maru.workforce.migrations.0030_programme_stop_boundary")


def test_workforce_inventory_accounts_for_all_direct_derived_and_shared_scopes():
    models = tuple(apps.get_app_config("workforce").get_models())
    direct = {
        m._meta.model_name
        for m in models
        if any(f.name == "edition" for f in m._meta.fields)
    }
    assert set(GUARDS.DIRECT_MODELS) == direct
    assert set(GUARDS.GUARDED_MODELS) | {"positiontemplate"} == {
        m._meta.model_name for m in models
    }
    assert len(GUARDS.GUARDED_MODELS) == len(set(GUARDS.GUARDED_MODELS))


def test_preparation_contract_preserves_exact_native_stop_attachments():
    contract = PROGRAMME_STOP_PREPARATION_CONTRACT
    assert contract.source_contract_current
    assert ("workforce", "0030_programme_stop_boundary") in contract.required_migrations
    assert {
        value.table
        for name, value in contract.supporting_triggers.items()
        if name.startswith("a00_workforce_programme_stop_")
    } == {f"workforce_{model}" for model in GUARDS.GUARDED_MODELS}
    assert not contract.functions[
        "maru_workforce_programme_stop_guard()"
    ].security_definer
    assert not contract.runtime_executable_functions


def test_starter_readiness_keeps_both_additive_stop_attachments():
    contract = PROGRAMME_STARTER_INTEGRITY_CONTRACT
    assert contract.source_contract_current
    assert {
        value.table
        for name, value in contract.triggers.items()
        if name.startswith("a00_workforce_programme_stop_")
    } == {"workforce_programmestarterrequest", "workforce_programmestarterdecision"}
