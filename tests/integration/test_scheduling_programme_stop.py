"""Native stop admission, not an integrated terminal command or profile promotion."""

from contextlib import contextmanager
from importlib import import_module
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from psycopg import sql

from maru.scheduling.readiness import scheduling_database_integrity_is_ready
from tests.factories import EventEditionFactory
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
GUARDS = import_module("maru.scheduling.migrations.0023_programme_stop_boundary")


def _terminal(edition, state):
    states = (
        ["cancelled"]
        if state == "cancelled"
        else ["preparing", "ready", "live", "closing", "archived"]
    )
    with connection.cursor() as cursor:
        for destination in states:
            cursor.execute(
                "UPDATE public.events_eventedition SET lifecycle = %s, "
                "lifecycle_version = lifecycle_version + 1, "
                "aggregate_version = aggregate_version + 1 WHERE id = %s",
                [destination, edition.id],
            )


@pytest.mark.parametrize("model", GUARDS.GUARDED_MODELS)
@pytest.mark.parametrize("state", ["archived", "cancelled"])
def test_every_native_operational_insert_refuses_terminal_programme(
    monkeypatch, model, state
):
    admit_transaction_local_schema_candidate(monkeypatch)
    edition = EventEditionFactory(adoption_profile_code="programme_operations")
    _terminal(edition, state)
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="Stopped Programme refuses"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, organization_id, edition_id) VALUES (%s, %s, %s)"
            ).format(sql.Identifier("public", f"scheduling_{model}")),
            [uuid4(), edition.organization_id, edition.id],
        )


@pytest.mark.parametrize(
    "profile", ["full_convention", "workforce_only", "programme_operations"]
)
def test_open_parent_remains_admitted_by_the_new_guard(monkeypatch, profile):
    admit_transaction_local_schema_candidate(monkeypatch)
    edition = EventEditionFactory(adoption_profile_code=profile)
    # Existing owner shape guards still refuse this deliberately incomplete row.
    # Reaching them proves this fence did not reinterpret an open parent.
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError) as caught,
        transaction.atomic(),
    ):
        cursor.execute(
            "INSERT INTO public.scheduling_schedulingeditioncontrol "
            "(id, organization_id, edition_id) VALUES (%s, %s, %s)",
            [uuid4(), edition.organization_id, edition.id],
        )
    assert "Stopped Programme" not in str(caught.value)
    assert "stop boundary" not in str(caught.value)


def test_native_stop_readiness_requires_the_exact_guard():
    assert scheduling_database_integrity_is_ready()
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE public.scheduling_schedulingeditioncontrol "
            "DISABLE TRIGGER a00_sch_programme_stop_0"
        )
    assert not scheduling_database_integrity_is_ready()


@pytest.mark.parametrize("operation", ["update", "delete", "move_out", "move_in"])
def test_native_stop_guard_checks_source_and_destination_even_before_graph_commit(
    monkeypatch, operation
):
    admit_transaction_local_schema_candidate(monkeypatch)
    stopped = EventEditionFactory(adoption_profile_code="programme_operations")
    other = EventEditionFactory(series=stopped.series)
    source = other if operation == "move_in" else stopped
    destination = stopped if operation == "move_in" else other
    identity = uuid4()
    if operation == "delete":
        statement = (
            "DELETE FROM public.scheduling_schedulingeditioncontrol WHERE id = %s"
        )
        parameters = [identity]
    elif operation == "update":
        statement = (
            "UPDATE public.scheduling_schedulingeditioncontrol "
            "SET aggregate_version = 2 WHERE id = %s"
        )
        parameters = [identity]
    else:
        statement = (
            "UPDATE public.scheduling_schedulingeditioncontrol "
            "SET edition_id = %s WHERE id = %s"
        )
        parameters = [destination.id, identity]
    with _staged_control(source, identity):
        _terminal(stopped, "archived")
        with (
            connection.cursor() as cursor,
            pytest.raises(IntegrityError, match="Stopped Programme refuses"),
            transaction.atomic(),
        ):
            cursor.execute(statement, parameters)


@contextmanager
def _staged_control(source, identity):
    # Keep the original deferred evidence guard enabled and prove this staged
    # row cannot commit. Roll it back before Django checks fixture constraints.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO public.scheduling_schedulingeditioncontrol "
                "(id, organization_id, edition_id, aggregate_version, "
                "created_at, updated_at) VALUES (%s, %s, %s, 1, now(), now())",
                [identity, source.organization_id, source.id],
            )
        yield
        with (
            connection.cursor() as cursor,
            pytest.raises(
                IntegrityError, match="control lacks its exact command receipt"
            ),
            transaction.atomic(),
        ):
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        transaction.set_rollback(True)


def test_native_stop_guard_refuses_unknown_or_cross_organization_parent(monkeypatch):
    admit_transaction_local_schema_candidate(monkeypatch)
    edition = EventEditionFactory(adoption_profile_code="programme_operations")
    other = EventEditionFactory()
    for organization, parent in (
        (other.organization_id, edition.id),
        (edition.organization_id, uuid4()),
    ):
        with (
            connection.cursor() as cursor,
            pytest.raises(IntegrityError, match="exact edition scope"),
            transaction.atomic(),
        ):
            cursor.execute(
                "INSERT INTO public.scheduling_schedulingeditioncontrol "
                "(id, organization_id, edition_id) VALUES (%s, %s, %s)",
                [uuid4(), organization, parent],
            )
