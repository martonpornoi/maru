from __future__ import annotations

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.identity.models import PlatformInvitationSchedulerRun

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _delivery_run() -> PlatformInvitationSchedulerRun:
    run_id = uuid4()
    # Production scheduler writers use one database-clock observation. Keep
    # synthetic evidence on the same boundary so host/DB clock skew cannot
    # create a trigger-invalid future heartbeat.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH evidence AS MATERIALIZED (
                SELECT clock_timestamp() AS recorded_at
            )
            INSERT INTO identity_platforminvitationschedulerrun (
                id, created_at, updated_at, kind, generation, ran_at,
                processed_count, remaining_count,
                private_key_coverage_complete, policy_digest,
                inspected_count, blocked_count, held_count,
                retention_cursor_transition_at,
                retention_cursor_invitation_id
            )
            SELECT %s, recorded_at, recorded_at, 'delivery', 'delivery-v1',
                   recorded_at, 1, 2, true, '', 0, 0, 0, NULL, NULL
              FROM evidence
            """,
            [run_id],
        )
    return PlatformInvitationSchedulerRun.objects.get(id=run_id)


def _truncate_scheduler_runs_without_test_reset() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute("TRUNCATE identity_platforminvitationschedulerrun")


def test_scheduler_heartbeat_is_value_minimized_and_append_only() -> None:
    run = _delivery_run()
    assert run.processed_count == 1
    assert run.remaining_count == 2
    assert run.created_at == run.updated_at == run.ran_at
    assert not hasattr(run, "account_id")
    assert not hasattr(run, "invitation_id")

    run.remaining_count = 0
    with pytest.raises(ValidationError, match="append-only"):
        run.save()
    with pytest.raises(ValidationError, match="retention workflow"):
        run.delete()
    with (
        pytest.raises(IntegrityError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE identity_platforminvitationschedulerrun "
            "SET remaining_count = 0 WHERE id = %s",
            [run.id],
        )


def test_scheduler_heartbeat_database_rejects_forged_kind_evidence() -> None:
    now = timezone.now()
    with (
        pytest.raises(IntegrityError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO identity_platforminvitationschedulerrun (
                id, created_at, updated_at, kind, generation, ran_at,
                processed_count, remaining_count,
                private_key_coverage_complete
            ) VALUES (%s, %s, %s, %s, %s, %s, 0, 0, %s)
            """,
            [
                uuid4(),
                now,
                now,
                "expiry",
                "delivery-v1",
                now,
                True,
            ],
        )


def test_scheduler_heartbeat_database_rejects_delete_and_truncate() -> None:
    run = _delivery_run()

    with (
        pytest.raises(IntegrityError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM identity_platforminvitationschedulerrun WHERE id = %s",
            [run.id],
        )

    with pytest.raises(IntegrityError, match="append-only"):
        _truncate_scheduler_runs_without_test_reset()

    assert PlatformInvitationSchedulerRun.objects.filter(id=run.id).exists()
