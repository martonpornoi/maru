"""Database-free orchestration contracts; not PostgreSQL transaction proof."""

from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models

from maru.events import programme_setup as command
from maru.events.adoption import adoption_profile
from maru.events.programme_setup_inputs import ProgrammeSetupInput, ProgrammeSetupMode
from maru.events.programme_setup_writer import (
    _programme_setup_writer,
    _require_programme_setup_writer,
)
from maru.identity import queries as identity


def details(mode=ProgrammeSetupMode.NEW_FOUNDATION):
    return ProgrammeSetupInput(
        mode=mode,
        edition_name=" Synthetic 2030 ",
        department_name=" Programme ",
        starts_on=date(2030, 9, 1),
        ends_on=date(2030, 9, 3),
        time_zone="UTC",
        reason=" Synthetic setup. ",
        organization_name="Synthetic organizers"
        if mode == ProgrammeSetupMode.NEW_FOUNDATION
        else "",
        series_name="Synthetic series"
        if mode != ProgrammeSetupMode.EXISTING_SERIES
        else "",
        organization_id=None
        if mode == ProgrammeSetupMode.NEW_FOUNDATION
        else UUID(int=2),
        series_id=UUID(int=3) if mode == ProgrammeSetupMode.EXISTING_SERIES else None,
        foundation_fingerprint=""
        if mode == ProgrammeSetupMode.NEW_FOUNDATION
        else "a" * 64,
    )


@pytest.fixture
def world(monkeypatch):
    calls = []
    actor = SimpleNamespace(
        id=UUID(int=1), is_active=True, is_platform_administrator=True
    )
    profile = SimpleNamespace(key=("programme_operations", 1))
    manager = MagicMock()
    manager.filter.return_value.first.return_value = None
    manager.create.side_effect = command.ProgrammeAdoptionSetupReceipt
    monkeypatch.setattr(command.ProgrammeAdoptionSetupReceipt, "objects", manager)
    mocks = {}
    values = {
        "adoption_profile": profile,
        "selectable_adoption_profile": profile,
        "programme_setup_database_integrity_is_ready": True,
        "current_platform_administrator_is_available": True,
        "_lock_key": None,
        "lock_retired_department_authority_boundaries": None,
        "create_draft_organization": SimpleNamespace(
            id=UUID(int=2), default_language_codes=["en"]
        ),
        "create_convention_series": SimpleNamespace(id=UUID(int=3)),
        "provision_maru_operators": SimpleNamespace(
            id=UUID(int=4), aggregate_version=1
        ),
        "lock_programme_setup_foundation": SimpleNamespace(
            organization_id=UUID(int=2),
            default_language_codes=("hu",),
            representation_id=UUID(int=4),
            representation_version=7,
        ),
        "create_event_edition": SimpleNamespace(
            edition=SimpleNamespace(
                id=UUID(int=5),
                adoption_profile_code="programme_operations",
                adoption_profile_version=1,
            ),
            replayed=False,
        ),
        "create_department": SimpleNamespace(
            department_id=UUID(int=6),
            receipt_id=UUID(int=7),
            resulting_version=1,
            replayed=False,
        ),
        "append_audit": SimpleNamespace(id=UUID(int=8)),
    }
    for name, value in values.items():

        def invoke(*args, _name=name, _value=value, **kwargs):
            calls.append((_name, args, kwargs))
            return _value

        mocks[name] = MagicMock(side_effect=invoke)
        monkeypatch.setattr(command, name, mocks[name])
    editions = MagicMock()
    editions.get.return_value = SimpleNamespace(id=UUID(int=9))
    monkeypatch.setattr(command.EditionCreationReceipt, "objects", editions)

    @contextmanager
    def atomic():
        calls.append(("begin", (), {}))
        try:
            yield
        except Exception:
            calls.append(("rollback", (), {}))
            raise
        else:
            calls.append(("commit", (), {}))

    monkeypatch.setattr(command.transaction, "atomic", atomic)
    return SimpleNamespace(
        actor=actor, mocks=mocks, manager=manager, editions=editions, calls=calls
    )


def run(world, **changes):
    return command.setup_programme_foundation(
        **{
            "actor": world.actor,
            "details": details(),
            "idempotency_key": UUID(int=10),
            "correlation_id": UUID(int=11),
            "source_channel": "test",
            **changes,
        }
    )


def test_current_profiles_deny_before_any_database_or_transaction(world, monkeypatch):
    monkeypatch.setattr(command, "adoption_profile", adoption_profile)
    with pytest.raises(ValidationError, match="not available"):
        run(world)
    assert world.calls == []
    world.manager.filter.assert_not_called()


@pytest.mark.parametrize("field", ["is_active", "is_platform_administrator"])
def test_preliminary_admission_precedes_request_work(world, field):
    setattr(world.actor, field, False)
    with pytest.raises(PermissionDenied):
        run(world, details=None)
    assert world.calls == []


@pytest.mark.parametrize("field", ["idempotency_key", "correlation_id"])
@pytest.mark.parametrize("value", [None, False, 1, "uuid", UUID(int=0)])
def test_request_identifiers_are_typed_and_non_nil(world, field, value):
    with pytest.raises(ValidationError):
        run(world, **{field: value})
    assert world.calls == []


@pytest.mark.parametrize(
    "value", [None, False, "", "a" * 33, "Test", "test\n", "test space", "é"]
)
def test_request_channel_is_closed_and_bounded(world, value):
    with pytest.raises(ValidationError):
        run(world, source_channel=value)
    assert world.calls == []


@pytest.mark.parametrize("mode", list(ProgrammeSetupMode))
def test_all_modes_use_public_owners_and_one_atomic_evidence_chain(world, mode):
    result = run(world, details=details(mode))
    assert result.organization_id == UUID(int=2)
    assert result.series_id == UUID(int=3)
    assert result.edition_id == UUID(int=5)
    assert result.department_id == UUID(int=6)
    assert result.representation_id == UUID(int=4)
    assert result.created_organization == (mode == ProgrammeSetupMode.NEW_FOUNDATION)
    assert result.created_series == (mode != ProgrammeSetupMode.EXISTING_SERIES)
    assert not result.replayed
    assert {field.name for field in fields(result)} == {
        "receipt_id",
        "organization_id",
        "series_id",
        "edition_id",
        "department_id",
        "representation_id",
        "replayed",
        "created_organization",
        "created_series",
    }
    names = [name for name, _, _ in world.calls]
    assert (
        names.index("begin")
        < names.index("_lock_key")
        < names.index("lock_retired_department_authority_boundaries")
    )
    assert (
        names.index("create_event_edition")
        < names.index("create_department")
        < names.index("append_audit")
        < names.index("commit")
    )
    world.mocks["current_platform_administrator_is_available"].assert_called_with(
        account_id=world.actor.id, lock=True
    )
    edition = world.mocks["create_event_edition"].call_args.kwargs
    assert edition["details"].name == "Synthetic 2030"
    assert edition["details"].currency_codes == ("XXX",)
    assert edition["details"].language_codes == (
        ("en",) if mode == ProgrammeSetupMode.NEW_FOUNDATION else ("hu",)
    )
    assert edition["adoption_profile_code"] == "programme_operations"
    department = world.mocks["create_department"].call_args.kwargs
    assert department["expected_version"] == 0
    assert department["parent_department_id"] is None
    assert department["reason"] == "Synthetic setup."
    assert department["retry_key"] == edition["idempotency_key"] == UUID(int=10)
    receipt = world.manager.create.call_args.kwargs
    assert receipt["edition_creation_id"] == UUID(int=9)
    assert receipt["department_creation_id"] == UUID(int=7)
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.target_id == receipt["id"] == result.receipt_id
    assert audit.principal_id == world.actor.id
    assert audit.operation == "events.programme_adoption.setup"
    assert audit.reason_code == "platform_administration"
    assert audit.correlation_id == department["correlation_id"]
    assert world.mocks["create_draft_organization"].call_count == int(
        result.created_organization
    )
    assert world.mocks["create_convention_series"].call_count == int(
        result.created_series
    )
    assert world.mocks["provision_maru_operators"].call_count == int(
        result.created_organization
    )
    if mode != ProgrammeSetupMode.NEW_FOUNDATION:
        world.mocks["lock_programme_setup_foundation"].assert_called_once_with(
            organization_id=UUID(int=2),
            series_id=details(mode).series_id,
            expected_fingerprint="a" * 64,
        )


def test_missing_draft_representation_is_provisioned_without_activation(world):
    world.mocks["lock_programme_setup_foundation"].side_effect = None
    world.mocks["lock_programme_setup_foundation"].return_value = SimpleNamespace(
        organization_id=UUID(int=2),
        default_language_codes=("en",),
        representation_id=None,
        representation_version=None,
    )
    run(world, details=details(ProgrammeSetupMode.EXISTING_ORGANIZATION))
    world.mocks["provision_maru_operators"].assert_called_once()


def test_exact_retry_reauthorizes_but_never_replays_owner_commands(world):
    result = run(world)
    receipt = command.ProgrammeAdoptionSetupReceipt(
        **world.manager.create.call_args.kwargs
    )
    world.manager.filter.return_value.first.return_value = receipt
    for mock in world.mocks.values():
        mock.reset_mock()
    world.mocks["selectable_adoption_profile"].side_effect = AssertionError(
        "Selector retirement must not block retained retry"
    )
    replay = run(world, correlation_id=uuid4())
    assert replay == replace(result, replayed=True)
    world.mocks["current_platform_administrator_is_available"].assert_called_with(
        account_id=world.actor.id, lock=True
    )
    for name in (
        "create_department",
        "create_event_edition",
        "lock_programme_setup_foundation",
        "append_audit",
        "programme_setup_database_integrity_is_ready",
    ):
        world.mocks[name].assert_not_called()
    world.manager.filter.assert_called_with(
        actor_id=world.actor.id, idempotency_key=UUID(int=10)
    )


def test_changed_retry_rejected_after_current_admission(world):
    run(world)
    world.manager.filter.return_value.first.return_value = (
        command.ProgrammeAdoptionSetupReceipt(**world.manager.create.call_args.kwargs)
    )
    with pytest.raises(ValidationError) as caught:
        run(world, details=replace(details(), reason="Different intent."))
    assert caught.value.code == "programme_setup_idempotency_conflict"
    assert world.manager.create.call_count == 1


@pytest.mark.parametrize(
    "boundary",
    [
        "create_draft_organization",
        "provision_maru_operators",
        "create_convention_series",
        "create_event_edition",
        "create_department",
        "append_audit",
        "receipt",
    ],
)
def test_every_failure_propagates_through_outer_rollback(world, boundary):
    target = world.manager.create if boundary == "receipt" else world.mocks[boundary]
    target.side_effect = RuntimeError("Synthetic write failed")
    with pytest.raises(RuntimeError, match="Synthetic write failed"):
        run(world)
    assert world.calls[-1][0] == "rollback"
    assert not any(name == "commit" for name, _, _ in world.calls)
    with pytest.raises(ValidationError):
        _require_programme_setup_writer()


@pytest.mark.parametrize(
    "boundary",
    [
        "selectable_adoption_profile",
        "programme_setup_database_integrity_is_ready",
        "lock_programme_setup_foundation",
    ],
)
def test_unavailable_preconditions_prevent_edition_creation(world, boundary):
    world.mocks[boundary].side_effect = None
    world.mocks[boundary].return_value = None
    with pytest.raises(ValidationError):
        run(world, details=details(ProgrammeSetupMode.EXISTING_SERIES))
    world.mocks["create_event_edition"].assert_not_called()


@pytest.mark.parametrize("boundary", ["create_event_edition", "create_department"])
def test_child_replay_without_complete_setup_receipt_is_not_success(world, boundary):
    original = world.mocks[boundary](actor=world.actor)
    original.replayed = True
    with pytest.raises(ValidationError) as caught:
        run(world)
    assert caught.value.code == "programme_setup_child_conflict"
    world.manager.create.assert_not_called()


@pytest.mark.parametrize("at", ["preliminary", "final"])
def test_current_identity_revocation_fails_closed(world, at):
    world.mocks["current_platform_administrator_is_available"].side_effect = (
        [False] if at == "preliminary" else [True, False]
    )
    with pytest.raises(PermissionDenied):
        run(world)
    world.manager.create.assert_not_called()
    world.mocks["append_audit"].assert_not_called()


def test_identity_lock_requires_an_atomic_scope_and_exact_active_platform_query(
    monkeypatch,
):
    manager = MagicMock()
    monkeypatch.setattr(identity.Account, "objects", manager)
    monkeypatch.setattr(identity, "connection", SimpleNamespace(in_atomic_block=False))
    account_id = UUID(int=1)
    assert not identity.current_platform_administrator_is_available(
        account_id=account_id, lock=True
    )
    manager.filter.assert_not_called()
    identity.connection.in_atomic_block = True
    query = manager.filter.return_value.select_for_update.return_value
    query.order_by.return_value.values_list.return_value.first.return_value = account_id
    assert identity.current_platform_administrator_is_available(
        account_id=account_id, lock=True
    )
    manager.filter.assert_called_once_with(
        id=account_id, is_active=True, account_kind="platform_administrator"
    )
    manager.filter.return_value.select_for_update.assert_called_once_with(of=("self",))


def test_private_writer_is_nested_exception_safe_and_never_allows_updates(monkeypatch):
    save = MagicMock()
    clean = MagicMock()
    monkeypatch.setattr(models.Model, "save", save)
    monkeypatch.setattr(command.ProgrammeAdoptionSetupReceipt, "full_clean", clean)
    receipt = command.ProgrammeAdoptionSetupReceipt()
    with _programme_setup_writer():
        with pytest.raises(RuntimeError), _programme_setup_writer():
            raise RuntimeError("nested")
        receipt.save(force_insert=True)
        receipt._state.adding = False
        with pytest.raises(ValidationError, match="immutable"):
            receipt.save()
        with pytest.raises(ValidationError, match="retained"):
            receipt.delete()
    save.assert_called_once_with(force_insert=True)
    clean.assert_called_once()
    with pytest.raises(ValidationError):
        _require_programme_setup_writer()
