"""Static parity and safety contracts for Programme application migrations."""

from importlib import import_module

from django.db import migrations

from maru.authorization.catalog import CAPABILITIES


def test_programme_schema_depends_on_earliest_complete_workforce_shape() -> None:
    """Keep Registration history independent of the later Workforce tail."""
    migration_module = import_module(
        "maru.applications.migrations.0004_programme_calls_and_proposals"
    )
    workforce_shape = import_module(
        "maru.workforce.migrations.0006_edition_structure_schema"
    )
    integrity = import_module(
        "maru.applications.migrations.0005_programme_integrity_guards"
    )

    assert tuple(migration_module.Migration.dependencies) == (
        ("applications", "0003_integrity_function_execute_boundary"),
        ("events", "0010_workforce_adoption_profile"),
        ("organizations", "0014_purpose_bounded_representation"),
        ("workforce", "0006_edition_structure_schema"),
        ("identity", "__first__"),
    )
    assert any(
        isinstance(operation, migrations.AddField)
        and operation.model_name == "department"
        and operation.name == "retired_at"
        for operation in workforce_shape.Migration.operations
    )
    assert "department.retired_at" in integrity.FORWARD_SQL


def test_authorization_min_scope_is_prior_catalog_plus_exact_department_code() -> None:
    """Prevent the replacement SQL function from dropping an existing code."""
    previous = import_module(
        "maru.authorization.migrations.0020_programme_capabilities"
    )
    current = import_module(
        "maru.authorization.migrations.0021_applications_programme_capabilities"
    )

    assert current.ORGANIZATION_CAPABILITIES == previous.ORGANIZATION_CAPABILITIES
    assert current.EDITION_CAPABILITIES == (
        previous.EDITION_CAPABILITIES + previous.PROGRAMME_CAPABILITIES
    )
    assert current.RESOURCE_CAPABILITIES == previous.RESOURCE_CAPABILITIES
    assert current.DEPARTMENT_CAPABILITIES == ("applications.manage_programme_calls",)
    listed = {
        *current.ORGANIZATION_CAPABILITIES,
        *current.EDITION_CAPABILITIES,
        *current.DEPARTMENT_CAPABILITIES,
        *current.RESOURCE_CAPABILITIES,
    }
    assert listed == {
        code for code, definition in CAPABILITIES.items() if definition.persistable
    }


def test_authorization_reverse_fence_runs_before_scope_contraction() -> None:
    """Fence durable grants before reverse SQL removes the min-scope code."""
    migration_module = import_module(
        "maru.authorization.migrations.0021_applications_programme_capabilities"
    )
    operations = migration_module.Migration.operations

    assert isinstance(operations[0], migrations.RunSQL)
    assert isinstance(operations[1], migrations.RunPython)
    assert operations[1].reverse_code is (
        migration_module.refuse_used_applications_programme_capability_downgrade
    )


def test_identity_person_guards_lock_rows_and_are_owner_only() -> None:
    """Close account-kind races without fencing deactivation or verification."""
    migration_module = import_module(
        "maru.identity.migrations.0020_programme_proposal_person_guard"
    )
    forward_sql = migration_module.FORWARD_SQL
    reverse_sql = migration_module.REVERSE_SQL

    assert forward_sql.count("DEFERRABLE INITIALLY DEFERRED") == 5
    assert forward_sql.count("REVOKE ALL ON FUNCTION") == 5
    assert forward_sql.count("FOR UPDATE OF account") >= 4
    assert "AFTER UPDATE OF account_kind" in forward_sql
    assert "UPDATE OF is_active" not in forward_sql
    assert "UPDATE OF email_verified_at" not in forward_sql
    assert reverse_sql.index("cannot remove Programme person guards") < (
        reverse_sql.index("DROP TRIGGER")
    )
