"""Pure overlay/registration checks; no native execution or runtime activation."""

import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from django.db import migrations
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.writer import MigrationWriter

from maru.events import adoption, adoption_persistence
from tests.rehearsals import programme_candidate_schema as schema
from tests.rehearsals import programme_registration as registration
from tests.rehearsals.programme_candidate import PROGRAMME_REHEARSAL_PROFILE
from tests.rehearsals.programme_provisioning import ProgrammeProvisioningError
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)

RUN = "1234567890abcdef1234567890abcdef"
OVERLAY = "tests.rehearsals.programme_event_migrations"
LEAF = ("events", "0015_isolated_programme_candidate")


def _serialized_model(state):
    return MigrationWriter.serialize(
        (
            state.app_label,
            state.name,
            state.fields,
            state.options,
            state.bases,
            [(name, manager.deconstruct()) for name, manager in state.managers],
        )
    )[0]


def test_overlay_preserves_entire_real_graph_and_changes_only_candidate_state(settings):
    original = MigrationLoader(None)
    old_state = original.project_state()
    settings.MIGRATION_MODULES = {"events": OVERLAY}
    candidate = MigrationLoader(None)
    assert set(candidate.disk_migrations) == set(original.disk_migrations) | {LEAF}
    for key, migration in original.disk_migrations.items():
        loaded = candidate.disk_migrations[key]
        assert loaded.dependencies == migration.dependencies
        # Django loads the same owner file under the overlay package name;
        # RunPython function identities consequently differ, not their source.
        assert (
            Path(inspect.getfile(type(loaded))).resolve()
            == Path(inspect.getfile(type(migration))).resolve()
        )
    state = candidate.project_state()
    old = old_state.models["events", "eventedition"]
    new = state.models["events", "eventedition"]
    assert list(new.fields["adoption_profile_code"].choices) == [
        ("full_convention", "Full convention"),
        ("workforce_only", "Workforce only"),
        ("programme_operations", PROGRAMME_REHEARSAL_PROFILE.label),
    ]
    for key in state.models:
        if key != ("events", "eventedition"):
            assert _serialized_model(state.models[key]) == _serialized_model(
                old_state.models[key]
            )
    new.fields["adoption_profile_code"] = old.fields["adoption_profile_code"]
    constraints = {c.name: c for c in new.options["constraints"]}
    original_constraints = {c.name: c for c in old.options["constraints"]}
    profile_constraint = "edition_adoption_profile_supported"
    condition = constraints.pop(profile_constraint).condition
    assert condition.connector == "OR"
    assert [dict(child.children) for child in condition.children] == [
        {"adoption_profile_code": code, "adoption_profile_version": 1}
        for code in ("full_convention", "workforce_only", "programme_operations")
    ]
    original_constraints.pop(profile_constraint)
    assert constraints == original_constraints
    new.options["constraints"] = old.options["constraints"]
    assert _serialized_model(new) == _serialized_model(old)


def test_forward_and_reverse_fences_run_before_schema_changes():
    migration = importlib.import_module(
        f"{OVERLAY}.0015_isolated_programme_candidate"
    ).Migration
    assert migration.atomic is True
    assert migration.operations[0].code is schema.require_empty_current_schema
    assert (
        migration.operations[-1].reverse_code is schema.require_empty_candidate_schema
    )
    assert isinstance(migration.operations[1], migrations.RemoveConstraint)
    assert isinstance(migration.operations[2], migrations.AddConstraint)


@pytest.fixture
def guarded(monkeypatch):
    request = Mock(return_value=SimpleNamespace(run_id=RUN))
    monkeypatch.setattr(schema, "require_programme_rehearsal_request", request)
    environment = Mock()
    monkeypatch.setattr(schema, "require_provisioning_process_environment", environment)
    monkeypatch.setattr(
        schema,
        "os",
        SimpleNamespace(
            environ={
                "MARU_PROGRAMME_REHEARSAL_SCHEMA": "candidate-v1",
                "MARU_PROGRAMME_REHEARSAL_PROCESS": "maru_migration",
            }
        ),
    )
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (f"maru_programme_{RUN}", "maru_migration", "maru_migration", 170011),
        (False,),
    ]
    cursor.fetchall.return_value = [(True, True)]
    connection = SimpleNamespace(
        vendor="postgresql", in_atomic_block=True, cursor=MagicMock()
    )
    connection.cursor.return_value.__enter__.return_value = cursor
    return SimpleNamespace(
        request=request, environment=environment, cursor=cursor, connection=connection
    )


@pytest.mark.parametrize("candidate", [False, True])
def test_real_guard_sql_locks_checks_empty_and_compares_server_constraint(
    candidate, guarded
):
    schema._require_empty_schema(guarded, candidate=candidate)
    statements = [c.args[0] for c in guarded.cursor.execute.call_args_list]
    assert (
        statements[3]
        == "LOCK TABLE public.events_eventedition IN ACCESS EXCLUSIVE MODE"
    )
    assert statements[4] == "SELECT EXISTS (SELECT 1 FROM public.events_eventedition)"
    assert ("programme_operations" in statements[5]) is candidate
    assert "CROSS JOIN pg_catalog.pg_constraint expected" in statements[6]
    assert statements[-1] == "DROP TABLE pg_temp.maru_programme_profile_reference"


def test_schema_policy_refuses_before_environment_or_connection(guarded):
    guarded.request.side_effect = ProgrammeRehearsalEnvironmentError("deferred")
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        schema.require_empty_current_schema(None, guarded)
    guarded.environment.assert_not_called()
    guarded.connection.cursor.assert_not_called()


@pytest.mark.parametrize("change", ["vendor", "atomic", "mode", "role"])
def test_schema_rejects_foreign_process_context(change, guarded):
    if change == "vendor":
        guarded.connection.vendor = "sqlite"
    elif change == "atomic":
        guarded.connection.in_atomic_block = False
    elif change == "mode":
        schema.os.environ["MARU_PROGRAMME_REHEARSAL_SCHEMA"] = "other"
    else:
        schema.os.environ["MARU_PROGRAMME_REHEARSAL_PROCESS"] = "maru_runtime"
    with pytest.raises(ProgrammeProvisioningError, match="context_required"):
        schema.require_empty_current_schema(None, guarded)
    guarded.connection.cursor.assert_not_called()


@pytest.mark.parametrize(
    "identity",
    [
        None,
        ("foreign", "maru_migration", "maru_migration", 170011),
        (f"maru_programme_{RUN}", "postgres", "maru_migration", 170011),
        (f"maru_programme_{RUN}", "maru_migration", "postgres", 170011),
        (f"maru_programme_{RUN}", "maru_migration", "maru_migration", 160011),
    ],
)
def test_native_identity_must_be_exact_before_table_access(identity, guarded):
    guarded.cursor.fetchone.side_effect = [identity]
    with pytest.raises(ProgrammeProvisioningError, match="identity_mismatch"):
        schema.require_empty_current_schema(None, guarded)
    assert guarded.cursor.execute.call_count == 1


@pytest.mark.parametrize("candidate", [False, True])
def test_any_edition_blocks_installation_and_reversal(candidate, guarded):
    guarded.cursor.fetchone.side_effect = [
        (f"maru_programme_{RUN}", "maru_migration", "maru_migration", 170011),
        (True,),
    ]
    with pytest.raises(ProgrammeProvisioningError, match="empty_editions"):
        schema._require_empty_schema(guarded, candidate=candidate)
    assert guarded.cursor.execute.call_count == 5


@pytest.mark.parametrize(
    "rows", [[], [(False, True)], [(True, False)], [(True, True), (True, True)]]
)
def test_missing_weakened_unvalidated_or_ambiguous_constraint_fails(rows, guarded):
    guarded.cursor.fetchall.return_value = rows
    with pytest.raises(ProgrammeProvisioningError, match="constraint_drift"):
        schema.require_empty_current_schema(None, guarded)


@pytest.fixture
def registry_double(monkeypatch):
    # Never install into Django's real registry in the unit process.
    double = SimpleNamespace(
        **{
            name: getattr(adoption, name)
            for name in (
                "AdoptionProfileCode",
                "ADOPTION_PROFILES",
                "SELECTABLE_ADOPTION_PROFILE_KEYS",
                "PERSISTED_ADOPTION_PROFILE_CHOICES",
                "SELECTABLE_ADOPTION_PROFILE_CHOICES",
            )
        }
    )
    persistence = SimpleNamespace(
        PERSISTED_ADOPTION_PROFILE_KEYS=adoption_persistence.PERSISTED_ADOPTION_PROFILE_KEYS
    )
    fence = Mock()
    monkeypatch.setattr(registration, "adoption", double)
    monkeypatch.setattr(registration, "adoption_persistence", persistence)
    monkeypatch.setattr(registration, "require_programme_runtime_environment", fence)
    monkeypatch.setattr(registration, "apps", SimpleNamespace(apps_ready=False))
    monkeypatch.setattr(registration, "sys", SimpleNamespace(modules={}))
    return SimpleNamespace(adoption=double, persistence=persistence, fence=fence)


def test_explicit_registration_extends_doubles_without_changing_real_profiles(
    registry_double,
):
    before = dict(adoption.ADOPTION_PROFILES)
    registration.register_isolated_programme_candidate()
    target = registry_double.adoption
    assert tuple(target.ADOPTION_PROFILES) == (*before, ("programme_operations", 1))
    assert (
        target.ADOPTION_PROFILES["programme_operations", 1]
        is PROGRAMME_REHEARSAL_PROFILE
    )
    for key, profile in before.items():
        assert target.ADOPTION_PROFILES[key] is profile
    assert (
        target.AdoptionProfileCode("programme_operations").value
        == "programme_operations"
    )
    assert dict(adoption.ADOPTION_PROFILES) == before
    assert (
        "programme_operations",
        1,
    ) not in adoption_persistence.PERSISTED_ADOPTION_PROFILE_KEYS
    with pytest.raises(TypeError):
        target.ADOPTION_PROFILES["foreign", 1] = PROGRAMME_REHEARSAL_PROFILE
    with pytest.raises(
        registration.ProgrammeRegistrationError, match="baseline_changed"
    ):
        registration.register_isolated_programme_candidate()


def test_registration_policy_fails_before_any_mutation(registry_double):
    before = vars(registry_double.adoption).copy()
    registry_double.fence.side_effect = ProgrammeRehearsalEnvironmentError("deferred")
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        registration.register_isolated_programme_candidate()
    assert vars(registry_double.adoption) == before


@pytest.mark.parametrize(
    "module", ["maru.events.checks", "maru.events.models", "maru.programme.models"]
)
def test_registration_refuses_stale_consumers_before_mutation(module, registry_double):
    registration.sys.modules[module] = object()
    with pytest.raises(registration.ProgrammeRegistrationError, match="too_late"):
        registration.register_isolated_programme_candidate()


@pytest.mark.parametrize(
    "attribute",
    [
        "ADOPTION_PROFILES",
        "SELECTABLE_ADOPTION_PROFILE_KEYS",
        "PERSISTED_ADOPTION_PROFILE_CHOICES",
        "SELECTABLE_ADOPTION_PROFILE_CHOICES",
    ],
)
def test_changed_registry_baseline_cannot_be_overwritten(attribute, registry_double):
    setattr(registry_double.adoption, attribute, {})
    before = vars(registry_double.adoption).copy()
    with pytest.raises(
        registration.ProgrammeRegistrationError, match="baseline_changed"
    ):
        registration.register_isolated_programme_candidate()
    assert vars(registry_double.adoption) == before
