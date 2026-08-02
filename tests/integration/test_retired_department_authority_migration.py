import pytest
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations.special import RunSQL
from django.utils import timezone

from maru.authorization.models import CapabilityGrant
from maru.workforce.models import Department
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_BEFORE = (
    "authorization",
    "0009_runtime_executable_function_contract",
)
AUTHORIZATION_AFTER = (
    "authorization",
    "0010_retired_department_authority_guards",
)
WORKFORCE_TARGET = ("workforce", "0006_edition_structure_schema")


def _migrate(authorization_target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([authorization_target, WORKFORCE_TARGET])
    return executor


def test_guard_installation_precedes_the_count_only_preflight() -> None:
    executor = MigrationExecutor(connection)
    migration = executor.loader.disk_migrations[AUTHORIZATION_AFTER]
    install, preflight = migration.operations[:2]
    assert isinstance(install, RunSQL)
    assert isinstance(preflight, RunSQL)
    assert "CREATE TRIGGER" in install.sql
    assert "preflight failed" in preflight.sql
    assert "retired_binding_count" not in preflight.sql


def test_preflight_and_reverse_fence_preserve_closed_authority() -> None:
    _migrate(AUTHORIZATION_BEFORE)
    edition = EventEditionFactory()
    actor = AccountFactory()
    department = Department.objects.create(
        organization=edition.organization,
        edition=edition,
        code="migration-operations",
        name="Migration Operations",
    )
    now = timezone.now()
    Department.objects.filter(pk=department.pk).update(
        created_in_structure_version=1,
        last_changed_in_structure_version=1,
        retired_at=now,
        retired_by=actor,
        retired_in_structure_version=1,
    )
    grant = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        capability_code="workforce.view_structure",
    )

    with pytest.raises(DatabaseError, match="preflight failed"):
        _migrate(AUTHORIZATION_AFTER)

    CapabilityGrant.objects.filter(pk=grant.pk).update(
        revoked_at=now,
        revoked_by=actor,
        revocation_reason="Close migration authority.",
    )
    _migrate(AUTHORIZATION_AFTER)

    with pytest.raises(RuntimeError, match="Cannot remove retired-Department"):
        _migrate(AUTHORIZATION_BEFORE)

    Department.objects.filter(pk=department.pk).update(
        created_in_structure_version=None,
        last_changed_in_structure_version=None,
        retired_at=None,
        retired_by=None,
        retired_in_structure_version=None,
    )
    _migrate(AUTHORIZATION_BEFORE)
    _migrate(AUTHORIZATION_AFTER)
