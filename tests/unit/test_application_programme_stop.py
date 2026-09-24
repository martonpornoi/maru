"""Closed Applications root/derived scope and explicit retained cleanup admission."""

from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.apps import apps

from maru.applications import programme_commands as commands
from maru.applications.readiness import APPLICATIONS_INTEGRITY_CONTRACT
from maru.events.programme_stop_queries import ProgrammeStopReference
from maru.events.programme_stop_readiness import PROGRAMME_STOP_PREPARATION_CONTRACT

GUARDS = import_module("maru.applications.migrations.0023_programme_stop_boundary")


def test_every_application_model_has_an_explicit_native_stop_scope():
    models = tuple(apps.get_app_config("applications").get_models())
    direct = {
        model._meta.model_name
        for model in models
        if any(field.name == "edition" for field in model._meta.fields)
    }
    assert set(GUARDS.DIRECT_MODELS) == direct
    assert set(GUARDS.GUARDED_MODELS) == {model._meta.model_name for model in models}
    assert len(GUARDS.GUARDED_MODELS) == len(set(GUARDS.GUARDED_MODELS))
    assert set(GUARDS.CLEANUP_MODELS) <= set(GUARDS.GUARDED_MODELS)


def test_all_application_stop_attachments_are_pinned_without_new_execute_rights():
    for contract in (
        APPLICATIONS_INTEGRITY_CONTRACT,
        PROGRAMME_STOP_PREPARATION_CONTRACT,
    ):
        assert contract.source_contract_current
        assert (
            "applications",
            "0023_programme_stop_boundary",
        ) in contract.required_migrations
        triggers = {**contract.triggers, **contract.supporting_triggers}
        assert {
            value.table
            for name, value in triggers.items()
            if name.startswith("a00_applications_programme_stop_")
        } == {f"applications_{model}" for model in GUARDS.GUARDED_MODELS}
        name = "maru_applications_programme_stop_cleanup()"
        assert not contract.functions[name].security_definer
        assert name not in contract.runtime_executable_functions


@pytest.mark.parametrize(
    "reference",
    [
        None,
        ProgrammeStopReference(applies=False, is_stopped=False, version=1),
        ProgrammeStopReference(applies=True, is_stopped=False, version=1),
        ProgrammeStopReference(applies=True, is_stopped=True, version=1),
    ],
)
@pytest.mark.parametrize("cleanup", [False, True])
def test_only_explicit_cleanup_can_admit_exact_stopped_profile(
    monkeypatch, reference, cleanup
):
    scope = SimpleNamespace(
        organization_id=uuid4(),
        edition_id=uuid4(),
        accepts_private_planning_writes=False,
    )
    monkeypatch.setattr(
        commands, "resolve_programme_stop_reference", lambda **_: reference
    )
    if cleanup and reference is not None and reference.applies and reference.is_stopped:
        commands._require_private_writes(scope, retained_cleanup=cleanup)
    else:
        with pytest.raises(commands.ApplicationsProgrammeStateConflictError):
            commands._require_private_writes(scope, retained_cleanup=cleanup)
