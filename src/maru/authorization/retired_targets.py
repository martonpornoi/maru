"""Transaction ordering for retired-Department authority writers."""

from django.db import connection
from django.db.transaction import TransactionManagementError

from maru.authorization.provenance import lock_authority_provenance_writer_boundary
from maru.workforce.writer_boundary import lock_page_9_structure_writer_boundary

RETIRED_DEPARTMENT_AUTHORITY_LOCK_KEY = 4_400_450_010


def lock_retired_department_authority_writer() -> None:
    """Serialize authority issuance with Department retirement before row locks.

    Raises
    ------
    TransactionManagementError
        If the operation encounters a transaction management condition.
    """
    if connection.get_autocommit() or not connection.in_atomic_block:
        raise TransactionManagementError(
            "The retired-Department authority lock requires an atomic transaction."
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(%s)",
            [RETIRED_DEPARTMENT_AUTHORITY_LOCK_KEY],
        )


def lock_retired_department_authority_boundaries() -> None:
    """Join structure, provenance, and retirement fences in canonical order."""
    lock_page_9_structure_writer_boundary()
    lock_authority_provenance_writer_boundary()
    lock_retired_department_authority_writer()
