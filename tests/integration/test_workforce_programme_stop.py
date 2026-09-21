"""Raw native Workforce terminal negatives; not a composed stop acceptance."""

from importlib import import_module
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from psycopg import sql

from maru.events.programme_stop_readiness import programme_stop_preparation_is_ready
from maru.workforce.programme_starter_readiness import (
    programme_starter_database_integrity_is_ready,
)
from tests.factories import EventEditionFactory
from tests.integration.test_scheduling_programme_stop import _terminal
from tests.support.programme_schema import admit_transaction_local_schema_candidate

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
GUARDS = import_module("maru.workforce.migrations.0030_programme_stop_boundary")


@pytest.mark.parametrize("prior", ["draft", "preparing"])
def test_native_direct_workforce_writers_refuse_terminal_programme(monkeypatch, prior):
    admit_transaction_local_schema_candidate(monkeypatch)
    edition = EventEditionFactory(adoption_profile_code="programme_operations")
    _terminal(edition, "archived", from_state=prior)
    for model in GUARDS.DIRECT_MODELS:
        with (
            connection.cursor() as cursor,
            pytest.raises(
                IntegrityError, match="Stopped Programme refuses ordinary Workforce"
            ),
            transaction.atomic(),
        ):
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {} (id, organization_id, edition_id) "
                    "VALUES (%s, %s, %s)"
                ).format(sql.Identifier("public", f"workforce_{model}")),
                [uuid4(), edition.organization_id, edition.id],
            )


@pytest.mark.parametrize("model", GUARDS.DERIVED_MODELS)
def test_native_derived_writers_fail_closed_without_exact_parent(model):
    with (
        connection.cursor() as cursor,
        pytest.raises(IntegrityError, match="exact parent scope"),
        transaction.atomic(),
    ):
        cursor.execute(
            sql.SQL("INSERT INTO {} (id) VALUES (%s)").format(
                sql.Identifier("public", f"workforce_{model}")
            ),
            [uuid4()],
        )


def test_preparation_and_starter_native_catalogs_require_the_stop_guard():
    assert programme_stop_preparation_is_ready()
    assert programme_starter_database_integrity_is_ready()
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE public.workforce_programmestarterrequest "
            "DISABLE TRIGGER a00_workforce_programme_stop_0"
        )
    assert not programme_stop_preparation_is_ready()
    assert not programme_starter_database_integrity_is_ready()
