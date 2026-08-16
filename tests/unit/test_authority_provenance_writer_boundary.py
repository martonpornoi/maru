"""Stable application diagnostics for the provenance writer boundary."""

import importlib

from django.db import DatabaseError
from django.db.migrations.loader import MigrationLoader

from maru.authorization.provenance import (
    AuthorityProvenanceWriterBoundaryError,
    AuthorityProvenanceWriterRestartRequiredError,
)

_identity_page10_migration = importlib.import_module(
    "maru.identity.migrations.0011_platform_account_invitations"
)


def test_restart_required_error_is_retryable_without_a_fabricated_database_cause() -> (
    None
):
    error = AuthorityProvenanceWriterRestartRequiredError(
        "Synthetic stale writer used only to verify the public diagnostic."
    )

    assert isinstance(error, AuthorityProvenanceWriterBoundaryError)
    assert isinstance(error, DatabaseError)
    assert error.sqlstate == "40001"
    assert error.__cause__ is None


def test_identity_page10_guards_reverse_before_their_authority_helper() -> None:
    helper_migration = (
        "authorization",
        "0007_authority_provenance_activation_guards",
    )
    identity_migration = ("identity", "0011_platform_account_invitations")

    assert helper_migration in _identity_page10_migration.Migration.dependencies

    plan = MigrationLoader(None, ignore_no_migrations=True).graph.backwards_plan(
        helper_migration
    )
    assert plan.index(identity_migration) < plan.index(helper_migration)
