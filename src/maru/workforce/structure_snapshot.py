"""Version-fenced, read-only snapshots for the Page 9 structure projection."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from django.db import DEFAULT_DB_ALIAS, connections, transaction

from maru.workforce.models import EditionStructureControl

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from uuid import UUID

    from django.db.backends.base.base import BaseDatabaseWrapper

MAX_STRUCTURE_SNAPSHOT_ATTEMPTS = 2
StructureSnapshotIsolation = Literal["REPEATABLE READ", "READ COMMITTED"]


class StructureSnapshotChangedError(RuntimeError):
    """The structure aggregate moved throughout both permitted read attempts."""


@dataclass(frozen=True, slots=True)
class StructureSnapshotRead[SnapshotT]:
    """A composed result and its exact in-snapshot aggregate fence.

    Attributes
    ----------
    value
        The untrusted input to normalize, validate, or compare.
    organization_id
        The organization identifier that owns the requested resource.
    edition_id
        The event edition identifier that scopes the operation.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    """

    value: SnapshotT
    organization_id: UUID
    edition_id: UUID
    aggregate_version: int


def _inside_django_testcase(connection: BaseDatabaseWrapper) -> bool:
    """Identify only Django's test-owned outer transaction.

    ``TestCase`` starts its transaction before application code runs, so
    PostgreSQL no longer permits changing its isolation level. Production code
    never takes this compatibility path: an unexpected caller-owned atomic
    block fails instead of silently weakening the snapshot contract.

    Parameters
    ----------
    connection : BaseDatabaseWrapper
        The connection evaluated while inside django testcase.

    Returns
    -------
    bool
        `True` when Identify only Django's test-owned outer transaction;
        otherwise `False`.
    """
    return any(
        bool(getattr(block, "_from_testcase", False))
        for block in connection.atomic_blocks
    )


@contextmanager
def _read_only_transaction(
    *,
    isolation_level: StructureSnapshotIsolation,
    using: str = DEFAULT_DB_ALIAS,
) -> Iterator[None]:
    connection = connections[using]
    if connection.in_atomic_block:
        if not _inside_django_testcase(connection):
            raise transaction.TransactionManagementError(
                "A structure snapshot must own its database transaction."
            )
        # Ordinary integration tests use Django TestCase's uncommitted fixture
        # transaction. A savepoint keeps their behavior test-local; dedicated
        # transaction tests exercise the real PostgreSQL isolation statement.
        with transaction.atomic(using=using):
            yield
        return

    with transaction.atomic(using=using):
        with connection.cursor() as cursor:
            cursor.execute(
                f"SET TRANSACTION ISOLATION LEVEL {isolation_level}, READ ONLY"
            )
        yield


@contextmanager
def repeatable_read_only_snapshot(*, using: str = DEFAULT_DB_ALIAS) -> Iterator[None]:
    """Open one short PostgreSQL repeatable-read, read-only transaction.

    Parameters
    ----------
    using : str, default=DEFAULT_DB_ALIAS
        The Django database alias on which to perform the operation.

    Yields
    ------
    None
        The resolved Iterator[None] for repeatable read only snapshot.

    Returns
    -------
    Iterator[None]
        An iterator that manages the repeatable-read snapshot.
    """
    with _read_only_transaction(isolation_level="REPEATABLE READ", using=using):
        yield


def current_structure_version(
    *,
    organization_id: UUID,
    edition_id: UUID,
    using: str = DEFAULT_DB_ALIAS,
) -> int:
    """Read the aggregate's current version in a fresh read-committed view.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    using : str, default=DEFAULT_DB_ALIAS
        The Django database alias on which to perform the operation.

    Returns
    -------
    int
        The resolved int for current structure version.
    """
    with _read_only_transaction(isolation_level="READ COMMITTED", using=using):
        version = (
            EditionStructureControl.objects.using(using)
            .filter(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .values_list("aggregate_version", flat=True)
            .first()
        )
    return int(version) if version is not None else 0


def load_version_fenced_snapshot[SnapshotT](
    *,
    load: Callable[[], StructureSnapshotRead[SnapshotT]],
    using: str = DEFAULT_DB_ALIAS,
) -> SnapshotT:
    """Load one coherent snapshot, retrying the whole read exactly once.

    The callback must perform every name-bearing and composed projection query
    and return the aggregate version observed in that same snapshot. Once the
    repeatable-read transaction has ended, a fresh read-committed probe detects
    both absent-to-present creation and every monotonic version movement.

    Parameters
    ----------
    load : Callable[[], StructureSnapshotRead[SnapshotT]]
        The callback invoked to load.
    using : str, default=DEFAULT_DB_ALIAS
        The Django database alias on which to perform the operation.

    Returns
    -------
    SnapshotT
        The resolved SnapshotT for the requested scope.

    Raises
    ------
    StructureSnapshotChangedError
        If the supplied aggregate version is stale.
    """
    for _attempt in range(MAX_STRUCTURE_SNAPSHOT_ATTEMPTS):
        with repeatable_read_only_snapshot(using=using):
            snapshot = load()
        if (
            current_structure_version(
                organization_id=snapshot.organization_id,
                edition_id=snapshot.edition_id,
                using=using,
            )
            == snapshot.aggregate_version
        ):
            return snapshot.value
    raise StructureSnapshotChangedError(
        "The workforce structure changed while its projection was being read."
    )
