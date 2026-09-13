"""Real additive operator capability reversal preserves retained authority."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from maru.scheduling.operator_scope import OPERATOR_CAPABILITIES
from tests.factories import (
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleBundleFactory,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("restores_current_migration_graph"),
]
BEFORE = ("authorization", "0029_programme_release_capabilities")


def native_levels():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_authorization_capability_min_scope(code) "
            "FROM unnest(%s::text[]) AS code ORDER BY code",
            [sorted(OPERATOR_CAPABILITIES)],
        )
        return [row[0] for row in cursor.fetchall()]


def test_unused_operator_catalog_reverses_and_reapplies_through_real_migrations():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    assert native_levels() == [1] * 5
    try:
        executor.migrate([BEFORE])
        assert native_levels() == [-1] * 5
    finally:
        MigrationExecutor(connection).migrate(leaves)
    assert native_levels() == [1] * 5


@pytest.mark.parametrize("evidence", ["revoked_grant", "role_bundle"])
def test_operator_authority_history_refuses_downgrade_before_recorder_changes(evidence):
    edition = EventEditionFactory()
    code = "scheduling.view_operator_output"
    if evidence == "revoked_grant":
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            capability_code=code,
            revoked_at=timezone.now(),
        )
    else:
        RoleBundleFactory(organization=edition.organization, capability_codes=[code])
    before = set(MigrationRecorder(connection).applied_migrations())
    with pytest.raises(RuntimeError, match="retain it and fix forward"):
        MigrationExecutor(connection).migrate([BEFORE])
    assert set(MigrationRecorder(connection).applied_migrations()) == before
    assert native_levels() == [1] * 5
