"""Early joined downgrade refusal for bare Guides editions and Workspace roots."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from tests.factories import EventEditionFactory, OrganizationRepresentationFactory

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@pytest.mark.parametrize("retained", ["edition", "workspace"])
def test_bare_used_foundation_refuses_before_any_successor_recorder_changes(
    retained, restores_current_migration_graph
):
    if retained == "edition":
        EventEditionFactory(
            adoption_profile_code="guidance_only",
            adoption_profile_version=1,
            currency_codes=["XXX"],
        )
    else:
        OrganizationRepresentationFactory(
            code="workspace_operators", name="Workspace operators"
        )
    before = set(MigrationRecorder(connection).applied_migrations())
    # No outer rollback: a late refusal must expose any already reversed successor.
    with pytest.raises(RuntimeError, match="fix forward"):
        MigrationExecutor(connection).migrate(
            [("authorization", "0042_announcements_operator_lineage")]
        )
    assert set(MigrationRecorder(connection).applied_migrations()) == before
