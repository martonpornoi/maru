"""Readiness detects drift in the dormant joint graph without domain disclosure."""

import pytest
from django.apps import apps
from django.db import connection, transaction

from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from maru.core.relation_schema_readiness import collect_relation_schema_fingerprints
from maru.scheduling.readiness import (
    SCHEDULING_INTEGRITY_CONTRACT,
    SCHEDULING_SCHEMA_SHA256,
    scheduling_database_integrity_is_ready,
)
from maru.venues.readiness import venues_database_integrity_is_ready

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize(
    "tamper",
    [
        "ALTER TABLE scheduling_schedulingcandidate ADD COLUMN hidden_copy text",
        "ALTER TABLE scheduling_schedulingcandidate ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE scheduling_schedulingcandidate "
        "ALTER COLUMN lifecycle DROP NOT NULL",
        "ALTER TABLE scheduling_schedulingcandidate "
        "ALTER COLUMN lifecycle SET DEFAULT 'draft'",
        "ALTER TABLE scheduling_schedulingcandidate "
        "DROP CONSTRAINT sch_candidate_shape",
        "CREATE INDEX scheduling_extra_index "
        "ON scheduling_schedulingcandidate (lifecycle)",
        "ALTER TABLE scheduling_schedulingcandidate DISABLE TRIGGER sch_5_row_guard",
        "CREATE TABLE scheduling_unreviewed_relation (id uuid PRIMARY KEY)",
        "CREATE SEQUENCE scheduling_unreviewed_sequence",
        "CREATE VIEW scheduling_unreviewed_view AS SELECT 1 AS example",
        "GRANT EXECUTE ON FUNCTION maru_scheduling_evidence_shape(jsonb) TO PUBLIC",
        "ALTER FUNCTION maru_scheduling_evidence_shape(jsonb) SECURITY DEFINER",
        "ALTER FUNCTION maru_scheduling_evidence_shape(jsonb) SET search_path = public",
        "DELETE FROM django_migrations WHERE app = 'scheduling' "
        "AND name = '0006_scheduling_downgrade_fence'",
    ],
)
def test_scheduling_readiness_rejects_schema_and_integrity_drift(tamper):
    catalog = inspect_database_integrity_catalog(SCHEDULING_INTEGRITY_CONTRACT)
    assert catalog.ready, catalog
    assert (
        collect_relation_schema_fingerprints(tuple(SCHEDULING_SCHEMA_SHA256))
        == SCHEDULING_SCHEMA_SHA256
    )
    assert scheduling_database_integrity_is_ready()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(tamper)
        assert not scheduling_database_integrity_is_ready()
        transaction.set_rollback(True)
    assert scheduling_database_integrity_is_ready()


@pytest.mark.parametrize(
    "tamper",
    [
        "ALTER TABLE venues_venueschedulingbinding ADD COLUMN private_source jsonb",
        "ALTER TABLE venues_venueschedulingbinding "
        "DISABLE TRIGGER venue_scheduling_binding_row",
        "ALTER TABLE venues_venueschedulingbinding "
        "ALTER COLUMN source_actor_id DROP NOT NULL",
        "GRANT EXECUTE ON FUNCTION "
        "maru_validate_scheduling_linked_booking(uuid) TO PUBLIC",
        "DELETE FROM django_migrations WHERE app = 'venues' "
        "AND name = '0005_scheduling_downgrade_fence'",
    ],
)
def test_venue_binding_readiness_rejects_drift(tamper):
    assert venues_database_integrity_is_ready()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(tamper)
        assert not venues_database_integrity_is_ready()
        transaction.set_rollback(True)
    assert venues_database_integrity_is_ready()


def test_schema_catalog_is_exactly_the_current_scheduling_model_graph():
    assert set(SCHEDULING_SCHEMA_SHA256) == {
        model._meta.db_table for model in apps.get_app_config("scheduling").get_models()
    }


@pytest.mark.parametrize("dropped_slots", [1, 2])
def test_release_key_readiness_rejects_reused_development_column_layout(dropped_slots):
    """Pin a clean migration shape, not a development drop-and-readd fingerprint."""
    assert scheduling_database_integrity_is_ready()
    with transaction.atomic(), connection.cursor() as cursor:
        for _ in range(dropped_slots):
            cursor.execute(
                "ALTER TABLE public.scheduling_schedulingreleasedependencykey "
                "DROP COLUMN initial_source_version"
            )
            cursor.execute(
                "ALTER TABLE public.scheduling_schedulingreleasedependencykey "
                "ADD COLUMN initial_source_version bigint NOT NULL "
                "CHECK (initial_source_version >= 0)"
            )
        # Names and types alone still match; physical retired slots do not.
        assert inspect_database_integrity_catalog(SCHEDULING_INTEGRITY_CONTRACT).ready
        assert not scheduling_database_integrity_is_ready()
        transaction.set_rollback(True)
    assert scheduling_database_integrity_is_ready()
