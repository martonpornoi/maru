"""Concurrency regressions for authority and Page 9 writer lock ordering."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

import maru.authorization.services as delegation_services
from maru.authorization.commands import grant_capability_direct
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.services import delegate_capability
from maru.identity.models import Account
from maru.workforce.structure_commands import create_department, update_department
from tests.factories import AccountFactory, EventEditionFactory
from tests.support.authority import activate_synthetic_board

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _wait_for_advisory_lock(*, backend_pid: int, timeout: float = 10.0) -> None:
    deadline = monotonic() + timeout
    last_observation: tuple[object, ...] | None = None
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT activity.wait_event_type, activity.wait_event
                  FROM pg_catalog.pg_stat_activity AS activity
                 WHERE activity.pid = %s
                """,
                [backend_pid],
            )
            last_observation = cursor.fetchone()
        if last_observation == ("Lock", "advisory"):
            return
        sleep(0.025)
    raise AssertionError(
        "Concurrent structure writer did not wait at the canonical advisory "
        f"boundary; last observation was {last_observation!r}."
    )


def _delegate_while_target_locked(
    *,
    actor_id: UUID,
    recipient_id: UUID,
    parent_grant_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
) -> UUID:
    close_old_connections()
    try:
        actor = Account.objects.get(id=actor_id)
        recipient = Account.objects.get(id=recipient_id)
        target = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        assert target is not None
        delegated = delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent_grant_id,
            target=target,
            effective_from=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=4),
            reason="Exercise canonical authority and structure writer ordering.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        return delegated.id
    finally:
        connection.close()


def _update_structure(
    *,
    backend_ready: Event,
    backend_pid: list[int],
    actor_id: UUID,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    expected_version: int,
) -> int:
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.pg_backend_pid()")
            backend_pid.append(int(cursor.fetchone()[0]))
        backend_ready.set()
        result = update_department(
            actor=Account.objects.get(id=actor_id),
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            department_id=department_id,
            name="Operations",
            description="Updated after a concurrent delegated authority write.",
            parent_department_id=None,
            display_order=10,
            expected_version=expected_version,
            reason="Exercise canonical authority and structure writer ordering.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        return result.resulting_version
    finally:
        backend_ready.set()
        connection.close()


def test_delegation_holds_canonical_boundary_before_target_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A structure writer waits on the boundary, never behind target row locks.

    Without the explicit boundary in ``delegate_capability``, this schedule is
    the former deadlock: delegation owns Organization/Edition rows, structure
    owns the retirement advisory lock, and each then waits for the other.
    """

    edition = EventEditionFactory()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    created = create_department(
        actor=administrator,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        name="Operations",
        description="Synthetic writer-order target.",
        parent_department_id=None,
        display_order=10,
        expected_version=0,
        reason="Create a synthetic writer-order target.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    actor, approver = activate_synthetic_board(edition.organization)
    organization_target = resolve_organization_target(
        organization_id=edition.organization_id
    )
    assert organization_target is not None
    now = timezone.now()
    parent = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=actor,
        capability_code="events.view_basic",
        target=organization_target,
        effective_from=now,
        expires_at=now + timedelta(days=1),
        reason="Create a parent for the writer-order regression.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    recipient = AccountFactory()

    target_rows_locked = Event()
    release_delegation = Event()
    original_lock_target = delegation_services._lock_target

    def paused_lock_target(
        target: ResolvedAuthorizationTarget,
    ) -> ResolvedAuthorizationTarget:
        locked = original_lock_target(target)
        target_rows_locked.set()
        assert release_delegation.wait(timeout=10)
        return locked

    monkeypatch.setattr(delegation_services, "_lock_target", paused_lock_target)
    structure_backend_ready = Event()
    structure_backend_pid: list[int] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        delegation: Future[UUID] = executor.submit(
            _delegate_while_target_locked,
            actor_id=actor.id,
            recipient_id=recipient.id,
            parent_grant_id=parent.id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        assert target_rows_locked.wait(timeout=10)
        structure: Future[int] = executor.submit(
            _update_structure,
            backend_ready=structure_backend_ready,
            backend_pid=structure_backend_pid,
            actor_id=administrator.id,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            department_id=created.department_id,
            expected_version=created.resulting_version,
        )
        assert structure_backend_ready.wait(timeout=10)
        assert len(structure_backend_pid) == 1
        try:
            _wait_for_advisory_lock(backend_pid=structure_backend_pid[0])
        finally:
            release_delegation.set()

        assert delegation.result(timeout=15)
        assert structure.result(timeout=15) == created.resulting_version + 1
