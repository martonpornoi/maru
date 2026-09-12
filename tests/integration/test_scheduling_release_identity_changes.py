from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent, AuditNativeMutationWitness
from maru.audit.mutation_evidence import audited_mutation
from maru.identity.models import Account
from maru.identity.services import deactivate_person_account_for_platform_emergency
from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.release_changes import record_identity_release_deactivation
from maru.scheduling.writer_boundary import scheduling_writer
from tests.factories import AccountFactory
from tests.integration.test_audit_mutation_evidence import _record

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def people():
    return AccountFactory(is_superuser=True, is_staff=True), AccountFactory()


def _track(account, **changes):
    fields = {"kind": "identity_account", "source_id": account.id}
    fields.update(changes)
    with scheduling_writer():
        return SchedulingReleaseDependencyKey.objects.create(**fields)


def _deactivate(people):
    return deactivate_person_account_for_platform_emergency(
        actor=people[0],
        account_id=people[1].id,
        reason="Synthetic emergency exercise",
        correlation_id=uuid4(),
    )


def _flush():
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def _raw_deactivate(account):
    Account.objects.filter(pk=account.id).update(is_active=False)
    _flush()


def _deactivate_and_flush(people):
    _deactivate(people)
    _flush()


def _raw_advance(key):
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE scheduling_schedulingreleasedependencykey "
            "SET generation = 2 WHERE id = %s",
            [key.id],
        )
    _flush()


def test_native_deactivation_advances_exact_global_dependency(people):
    key = _track(people[1])
    before = timezone.now()
    result = _deactivate(people)
    _flush()
    key.refresh_from_db()
    change = SchedulingReleaseDependencyChange.objects.get(dependency=key)
    assert not result.account.is_active
    assert key.generation == change.generation == 2
    assert change.organization_id is change.edition_id is None
    assert before <= change.recorded_at <= timezone.now()
    assert change.source_audit.target_id == people[1].id
    assert change.source_audit.operation == "identity.account.emergency_deactivate"
    assert AuditNativeMutationWitness.objects.filter(
        audit_event_id=change.source_audit_id
    ).exists()


def test_untracked_native_deactivation_creates_no_scheduling_state(people):
    _deactivate(people)
    _flush()
    assert not SchedulingReleaseDependencyKey.objects.exists()
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_untracked_raw_eligibility_change_is_not_a_release_dependency(people):
    Account.objects.filter(pk=people[1].id).update(is_active=False)
    _flush()
    assert not SchedulingReleaseDependencyKey.objects.exists()
    assert not AuditNativeMutationWitness.objects.exists()


def test_raw_tracked_change_cannot_commit_without_invalidation(people):
    key = _track(people[1])
    with (
        pytest.raises(IntegrityError, match="native release invalidation"),
        transaction.atomic(),
    ):
        _raw_deactivate(people[1])
    people[1].refresh_from_db()
    key.refresh_from_db()
    assert people[1].is_active
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_failed_required_join_rolls_back_native_account_and_audit(people):
    key = _track(people[1])
    with (
        patch(
            "maru.identity.services.record_identity_release_deactivation",
            side_effect=ValidationError("Synthetic journal unavailable"),
        ),
        pytest.raises(ValidationError, match="Synthetic journal unavailable"),
    ):
        _deactivate(people)
    _flush()
    people[1].refresh_from_db()
    key.refresh_from_db()
    assert people[1].is_active
    assert key.generation == 1
    assert not AuditEvent.objects.exists()
    assert not AuditNativeMutationWitness.objects.exists()
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_skipped_application_join_is_independently_rejected_by_database(people):
    _track(people[1])
    with (
        pytest.raises(IntegrityError, match="native release invalidation"),
        transaction.atomic(),
        patch("maru.identity.services.record_identity_release_deactivation"),
    ):
        _deactivate_and_flush(people)
    people[1].refresh_from_db()
    assert people[1].is_active
    assert not AuditEvent.objects.exists()


@pytest.mark.parametrize("generation", [0, 2, 100])
def test_tracking_cannot_invent_prior_generations(people, generation):
    with (
        pytest.raises(IntegrityError, match="locked native source"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO scheduling_schedulingreleasedependencykey "
            "(id, created_at, updated_at, kind, source_id, generation) "
            "VALUES (%s, clock_timestamp(), clock_timestamp(), "
            "'identity_account', %s, %s)",
            [uuid4(), people[1].id, generation],
        )


def test_tracking_rejects_missing_native_source(people):
    with (
        pytest.raises(IntegrityError, match="locked native source"),
        transaction.atomic(),
    ):
        _track(people[1], source_id=uuid4())


@pytest.mark.parametrize(
    "query",
    [
        "UPDATE scheduling_schedulingreleasedependencykey "
        "SET generation = generation + 2 WHERE id = %s",
        "UPDATE scheduling_schedulingreleasedependencykey "
        "SET source_id = gen_random_uuid() WHERE id = %s",
        "UPDATE scheduling_schedulingreleasedependencykey "
        "SET created_at = clock_timestamp() WHERE id = %s",
    ],
)
def test_raw_key_cannot_change_identity_or_skip_a_generation(people, query):
    key = _track(people[1])
    with (
        pytest.raises(IntegrityError, match="immutable-identity advance"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(query, [key.id])


def test_generation_advance_without_change_cannot_commit(people):
    key = _track(people[1])
    with (
        pytest.raises(IntegrityError, match="complete immutable journal"),
        transaction.atomic(),
    ):
        _raw_advance(key)
    key.refresh_from_db()
    assert key.generation == 1


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM scheduling_schedulingreleasedependencykey WHERE id = %s",
        "DELETE FROM scheduling_schedulingreleasedependencychange "
        "WHERE dependency_id = %s",
        "UPDATE scheduling_schedulingreleasedependencychange "
        "SET recorded_at = clock_timestamp() WHERE dependency_id = %s",
    ],
)
def test_retained_key_and_change_are_raw_dml_immutable(people, query):
    key = _track(people[1])
    _deactivate(people)
    _flush()
    with (
        pytest.raises(IntegrityError, match=r"retained|append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(query, [key.id])


def test_old_allowed_audit_does_not_substitute_for_native_source_mutation(people):
    _track(people[1])
    native_shape = replace(
        _record(),
        principal_id=people[0].id,
        organization_id=None,
        event_edition_id=None,
        capability_code="organizations.manage_representation",
        operation="identity.account.emergency_deactivate",
        target_type="identity.account",
        target_id=people[1].id,
        reason_code="platform_emergency_removal",
        changed_fields=("is_active", "sessions"),
    )
    with (
        pytest.raises(IntegrityError, match="exact current native mutation"),
        transaction.atomic(),
        audited_mutation(native_shape) as mutation,
    ):
        record_identity_release_deactivation(mutation)
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_journal_uses_database_time_not_backdated_owner_time(people):
    _track(people[1])
    actual_now = timezone.now()
    with patch(
        "maru.identity.services.timezone.now",
        return_value=actual_now - timedelta(days=10),
    ):
        _deactivate(people)
    _flush()
    change = SchedulingReleaseDependencyChange.objects.get()
    assert change.recorded_at >= actual_now
    assert change.source_audit.occurred_at == actual_now - timedelta(days=10)


def test_unrelated_tracked_account_edit_does_not_invalidate(people):
    key = _track(people[1])
    Account.objects.filter(pk=people[1].id).update(
        display_name="Synthetic updated label"
    )
    _flush()
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_reverification_time_refresh_does_not_change_current_eligibility(people):
    key = _track(people[1])
    Account.objects.filter(pk=people[1].id).update(email_verified_at=timezone.now())
    _flush()
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM identity_account WHERE id = %s",
        "UPDATE identity_account SET id = gen_random_uuid() WHERE id = %s",
    ],
)
def test_tracked_native_identity_cannot_be_removed_or_rekeyed(people, query):
    _track(people[1])
    with (
        pytest.raises(IntegrityError, match="source identity and ownership"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(query, [people[1].id])
    assert Account.objects.filter(pk=people[1].id).exists()
