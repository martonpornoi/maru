"""Stable application diagnostics for the provenance writer boundary."""

from django.db import DatabaseError

from maru.authorization.provenance import (
    AuthorityProvenanceWriterBoundaryError,
    AuthorityProvenanceWriterRestartRequiredError,
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
