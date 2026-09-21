"""Real empty joined-fence reversal must refuse readiness until exact restoration."""

from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.events.programme_stop_readiness import programme_stop_command_is_ready
from tests.factories import RoleBundleFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.mark.usefixtures("restores_current_migration_graph")
@pytest.mark.parametrize("unrelated_role", [False, True])
def test_unused_exit_fence_reverses_and_restores_complete_readiness(unrelated_role):
    if unrelated_role:
        RoleBundleFactory(capability_codes=["events.view_basic"])
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    assert programme_stop_command_is_ready()
    try:
        executor.migrate([("events", "0016_programme_stop_integrity")])
        assert not programme_stop_command_is_ready()
        applied = MigrationExecutor(connection).loader.applied_migrations
        assert ("events", "0017_programme_exit_recovery_fence") not in applied
        assert ("events", "0018_programme_retained_recovery_fence") not in applied
    finally:
        MigrationExecutor(connection).migrate(leaves)
    assert programme_stop_command_is_ready()


@pytest.mark.parametrize(
    ("migration", "constant"),
    [
        ("0020_programme_capabilities", "PROGRAMME_CAPABILITIES"),
        ("0021_applications_programme_capabilities", "DEPARTMENT_CAPABILITIES"),
        ("0022_programme_import_capabilities", "IMPORT_CAPABILITIES"),
        ("0023_programme_department_ownership_recovery", "RECOVERY_CAPABILITY"),
        ("0024_programme_review_capabilities", "REVIEW_CAPABILITIES"),
        ("0025_programme_conversion_capability", "CONVERSION_CAPABILITY"),
        ("0026_programme_host_capabilities", "HOST_CAPABILITIES"),
        ("0027_scheduling_capabilities", "SCHEDULING_CAPABILITIES"),
        ("0027_scheduling_capabilities", "PHYSICAL_CAPABILITIES"),
        ("0028_programme_staffing_capabilities", "STAFFING_CAPABILITIES"),
        ("0029_programme_release_capabilities", "RELEASE_CAPABILITIES"),
        ("0030_programme_operator_capabilities", "OPERATOR_CAPABILITIES"),
        (
            "0031_programme_change_communication_capabilities",
            "CHANGE_COMMUNICATION_CAPABILITIES",
        ),
        ("0037_programme_archive_capability", "ARCHIVE_CAPABILITY"),
    ],
)
@pytest.mark.usefixtures("restores_current_migration_graph")
def test_each_retained_authority_family_fences_the_whole_exit_generation(
    migration, constant
):
    vocabulary = getattr(
        import_module(f"maru.authorization.migrations.{migration}"), constant
    )
    code = vocabulary if isinstance(vocabulary, str) else vocabulary[0]
    retained = RoleBundleFactory(capability_codes=[code])
    before = set(MigrationRecorder(connection).applied_migrations())
    with pytest.raises(RuntimeError, match="fix forward"):
        MigrationExecutor(connection).migrate(
            [("events", "0017_programme_exit_recovery_fence")]
        )
    assert set(MigrationRecorder(connection).applied_migrations()) == before
    assert type(retained).objects.get(pk=retained.pk).capability_codes == [code]
    assert programme_stop_command_is_ready()
