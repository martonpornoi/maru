"""Real ordinary controller stop and reciprocal Events native terminal evidence."""

# ruff: noqa: F811 -- Imported pytest fixtures are injected by their names.

from dataclasses import replace
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from maru.audit.models import AuditEvent
from maru.authorization.commands import revoke_capability_grant
from maru.authorization.policy import resolve_edition_target
from maru.authorization.services import AuthorizationDenied
from maru.events import programme_stop_commands as commands
from maru.events.models import EventEdition, ProgrammeStopReceipt
from maru.events.programme_stop_commands import stop_programme
from maru.events.programme_stop_composition import load_programme_stop_preview
from maru.events.programme_stop_inputs import ProgrammeStopInput
from maru.events.programme_stop_readiness import programme_stop_command_is_ready
from maru.events.programme_stop_receipt_queries import load_programme_stop_receipt
from maru.events.services import transition_edition
from tests.factories import AccountFactory
from tests.integration.test_programme_stop_controller import (
    _grant,
    reader,  # noqa: F401 - fixture
    world,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _confirm(world, reader):
    arguments = {
        "actor_id": reader[0].id,
        "organization_id": world[0].id,
        "edition_id": world[1].id,
        "correlation_id": uuid4(),
    }
    preview = load_programme_stop_preview(**arguments)
    details = ProgrammeStopInput(
        preview.aggregate_version,
        preview.lifecycle_version,
        preview.fingerprint,
        "Retain synthetic Programme history — árvíztűrő 🐱.",
    )
    return {**arguments, "details": details, "idempotency_key": uuid4()}


def _drain():
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def test_actual_controller_stops_directly_without_manufacturing_intermediate_states(
    world, reader
):
    assert programme_stop_command_is_ready()

    arguments = _confirm(world, reader)
    _drain()
    result = stop_programme(**arguments)
    _drain()
    edition = EventEdition.objects.get(id=world[1].id)
    assert edition.lifecycle == "archived"
    assert (
        edition.aggregate_version == arguments["details"].expected_aggregate_version + 1
    )
    assert (
        edition.lifecycle_version == arguments["details"].expected_lifecycle_version + 1
    )
    receipt = ProgrammeStopReceipt.objects.get(id=result.receipt_id)
    assert receipt.transition.from_state == world[1].lifecycle
    assert receipt.transition.to_state == "archived"
    assert receipt.actor_id == reader[0].id
    assert receipt.reason == arguments["details"].reason
    assert receipt.impact_document["withdrawal"] is None
    assert result.replayed is False
    retry = stop_programme(
        **{
            **arguments,
            "correlation_id": uuid4(),
            "source_channel": "another-transport",
        }
    )
    assert replace(result, replayed=True) == retry
    assert ProgrammeStopReceipt.objects.count() == 1
    _drain()


@pytest.mark.parametrize("field", ["reason", "preview_fingerprint"])
def test_changed_original_retry_intent_cannot_reopen_or_replace_stop(
    world, reader, field
):
    arguments = _confirm(world, reader)
    stop_programme(**arguments)
    changed = replace(
        arguments["details"],
        **{field: "Different synthetic intent." if field == "reason" else "f" * 64},
    )
    with pytest.raises(ValidationError) as failure:
        stop_programme(**{**arguments, "details": changed})
    assert failure.value.code == "programme_stop_idempotency_conflict"
    assert ProgrammeStopReceipt.objects.count() == 1
    _drain()


@pytest.mark.parametrize("state", ["archived", "cancelled"])
def test_raw_terminal_change_cannot_commit_without_accountable_stop(world, state):
    _drain()

    def write():
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "UPDATE public.events_eventedition SET lifecycle = %s, "
                "aggregate_version = aggregate_version + 1, "
                "lifecycle_version = lifecycle_version + 1 WHERE id = %s",
                [state, world[1].id],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    with pytest.raises(IntegrityError, match="Programme"):
        write()
    world[1].refresh_from_db()
    assert world[1].lifecycle == "draft"
    assert not ProgrammeStopReceipt.objects.exists()


@pytest.mark.parametrize("state", ["archived", "cancelled"])
def test_generic_transition_cannot_bypass_programme_confirmation(world, reader, state):
    with pytest.raises(ValidationError) as failure:
        transition_edition(
            actor=reader[0],
            organization_id=world[0].id,
            edition_id=world[1].id,
            to_state=state,
            reason="Synthetic generic bypass attempt.",
            correlation_id=uuid4(),
        )
    assert failure.value.code == "programme_stop_confirmation_required"
    assert not ProgrammeStopReceipt.objects.exists()


def test_false_original_preview_leaves_adoption_and_work_unchanged(world, reader):
    arguments = _confirm(world, reader)
    with pytest.raises(ValidationError) as failure:
        stop_programme(
            **{
                **arguments,
                "details": replace(arguments["details"], preview_fingerprint="f" * 64),
            }
        )
    assert failure.value.code == "programme_stop_preview_conflict"
    world[1].refresh_from_db()
    assert world[1].lifecycle == "draft"
    assert not ProgrammeStopReceipt.objects.exists()
    assert not AuditEvent.objects.filter(
        reason_code="programme_stop_confirmed"
    ).exists()


@pytest.mark.parametrize("which", [0, 1])
def test_original_receipt_never_replaces_current_controller_authority(
    world, reader, which
):
    arguments = _confirm(world, reader)
    stop_programme(**arguments)
    revoke_capability_grant(
        actor=world[2],
        target=resolve_edition_target(
            organization_id=world[0].id, edition_id=world[1].id
        ),
        grant_id=reader[1][which].id,
        reason="Withdraw one actual synthetic stop prerequisite.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    with pytest.raises(AuthorizationDenied):
        stop_programme(**arguments)
    assert ProgrammeStopReceipt.objects.count() == 1
    _drain()


def test_failure_after_terminal_mutation_rolls_back_every_stop_consequence(
    world, reader, monkeypatch
):
    arguments = _confirm(world, reader)
    _drain()
    before = (world[1].aggregate_version, world[1].lifecycle_version)

    def unavailable(*_, **__):
        raise RuntimeError("Synthetic internal event storage failure")

    monkeypatch.setattr(commands, "publish_domain_event", unavailable)
    with pytest.raises(RuntimeError, match="Synthetic internal event storage failure"):
        stop_programme(**arguments)
    _drain()
    world[1].refresh_from_db()
    assert world[1].lifecycle == "draft"
    assert before == (world[1].aggregate_version, world[1].lifecycle_version)
    assert not ProgrammeStopReceipt.objects.exists()
    assert not AuditEvent.objects.filter(
        reason_code="programme_stop_confirmed"
    ).exists()


@pytest.mark.parametrize("drift", ["lifecycle", "reciprocal", "extra_attachment"])
def test_exact_native_terminal_attachments_are_required_before_any_stop(
    world, reader, drift
):
    arguments = _confirm(world, reader)
    _drain()
    with connection.cursor() as cursor:
        if drift == "extra_attachment":
            cursor.execute(
                "CREATE TRIGGER unexpected_programme_stop_attachment "
                "BEFORE UPDATE ON public.events_eventedition "
                "FOR EACH ROW EXECUTE FUNCTION "
                "public.maru_validate_edition_lifecycle_version()"
            )
        elif drift == "lifecycle":
            cursor.execute(
                "ALTER TABLE public.events_eventedition "
                "DISABLE TRIGGER events_lifecycle_version_guard"
            )
        else:
            cursor.execute(
                "ALTER TABLE public.events_eventedition "
                "DISABLE TRIGGER events_programme_stop_transition"
            )
    assert not programme_stop_command_is_ready()
    with pytest.raises(ValidationError):
        stop_programme(**arguments)
    assert not ProgrammeStopReceipt.objects.exists()
    world[1].refresh_from_db()
    assert world[1].lifecycle == "draft"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reason", "A substituted unconfirmed reason."),
        ("request_digest", "f" * 64),
        ("preview_fingerprint", "f" * 64),
        ("impact_document", {"unsupported": True}),
        ("previous_lifecycle", "live"),
        ("expected_aggregate_version", 1000),
        ("expected_lifecycle_version", 1000),
        ("source_channel", "different-channel"),
    ],
)
def test_native_receipt_rejects_substituted_confirmation_evidence(
    world, reader, monkeypatch, field, value
):
    arguments = _confirm(world, reader)
    _drain()
    create = ProgrammeStopReceipt.objects.create

    def substituted(**kwargs):
        return create(**{**kwargs, field: value})

    monkeypatch.setattr(ProgrammeStopReceipt.objects, "create", substituted)
    with pytest.raises(IntegrityError, match="Programme stop"):
        stop_programme(**arguments)
    _drain()
    world[1].refresh_from_db()
    assert world[1].lifecycle == "draft"
    assert not ProgrammeStopReceipt.objects.exists()


def test_native_receipt_requires_actual_internal_event(world, reader, monkeypatch):
    arguments = _confirm(world, reader)
    _drain()
    monkeypatch.setattr(commands, "publish_domain_event", lambda *_a, **_kw: None)
    with pytest.raises(IntegrityError, match="same-transaction owner evidence"):
        stop_programme(**arguments)
    _drain()
    world[1].refresh_from_db()
    assert world[1].lifecycle == "draft"
    assert not ProgrammeStopReceipt.objects.exists()


def test_completed_stop_is_immutable_and_prevents_native_downgrade(world, reader):
    result = stop_programme(**_confirm(world, reader))
    _drain()

    def write(statement):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(statement, [result.receipt_id])

    for statement in (
        "DELETE FROM public.events_programmestopreceipt WHERE id = %s",
        "UPDATE public.events_programmestopreceipt SET reason = reason WHERE id = %s",
    ):
        with pytest.raises(IntegrityError, match="immutable"):
            write(statement)
    migration = import_module("maru.events.migrations.0016_programme_stop_integrity")
    with (
        connection.schema_editor(atomic=False) as editor,
        pytest.raises(RuntimeError, match="retain it and fix forward"),
    ):
        migration.refuse_used_stop_downgrade(apps, editor)
    assert ProgrammeStopReceipt.objects.filter(id=result.receipt_id).exists()
    assert programme_stop_command_is_ready()


def test_historical_receipt_is_original_actor_only_under_current_authority(
    world, reader
):
    other = AccountFactory()
    for capability in ("authorization.manage_roles", "events.transition"):
        _grant(world, other, capability)
    arguments = _confirm(world, reader)
    result = stop_programme(**arguments)
    _drain()
    scope = {
        "actor_id": reader[0].id,
        "organization_id": world[0].id,
        "edition_id": world[1].id,
        "receipt_id": result.receipt_id,
        "correlation_id": uuid4(),
    }
    detail = load_programme_stop_receipt(**scope)
    assert detail.reason == arguments["details"].reason
    assert detail.aggregate_version == result.aggregate_version
    assert not detail.release_withdrawn
    for changed in (
        {"actor_id": other.id},
        {"receipt_id": uuid4()},
        {"organization_id": uuid4()},
        {"edition_id": uuid4()},
    ):
        with pytest.raises(AuthorizationDenied):
            load_programme_stop_receipt(
                **{**scope, **changed, "correlation_id": uuid4()}
            )
    denials = AuditEvent.objects.filter(
        operation="events.programme_stop.receipt", outcome="deny"
    )
    assert denials.count() == 4
    assert not denials.exclude(target_id=None).exists()
