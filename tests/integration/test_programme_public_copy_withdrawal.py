"""Exact copy withdrawal retains evidence and governs only that rendition."""

from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent, OutboxMessage
from maru.programme.commands import (
    ProgrammeUnavailableError,
    ProgrammeVersionConflictError,
)
from maru.programme.models import (
    ProgrammePublicRendition,
    ProgrammePublicRenditionWithdrawal,
)
from maru.programme.public_copy_commands import withdraw_programme_public_rendition
from maru.programme.queries import (
    list_programme_public_copy_review_history,
    load_programme_public_copy,
)
from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.writer_boundary import scheduling_writer
from tests.integration.test_programme_operational_public_review import (
    admits_exact_effect as admits_exact_effect,  # noqa: PLC0414
)
from tests.integration.test_programme_operational_public_review import advance, review
from tests.integration.test_programme_operational_public_review import (
    review_world as review_world,  # noqa: PLC0414
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def withdraw(scope, rendition_id, *, retry=None, **overrides):
    return withdraw_programme_public_rendition(
        **(
            {
                "actor_id": scope.reviewer.id,
                "organization_id": scope.edition.organization_id,
                "edition_id": scope.edition.id,
                "item_id": scope.item.id,
                "rendition_id": rendition_id,
                "expected_version": scope.item.aggregate_version,
                "reason": "Withdraw this exact synthetic public copy",
                "idempotency_key": retry or uuid4(),
                "correlation_id": uuid4(),
                "source_channel": "test",
                "authorizer": scope.policy,
            }
            | overrides
        ),
    )


def test_exact_withdrawal_and_retry_retain_copy_and_atomic_native_evidence(
    review_world,
):
    approved = review(review_world)
    rendition = ProgrammePublicRendition.objects.get(id=approved.result_object_id)
    retry = uuid4()
    result = withdraw(review_world, rendition.id, retry=retry)
    withdrawal = ProgrammePublicRenditionWithdrawal.objects.get(
        id=result.result_object_id
    )
    assert withdrawal.rendition_id == rendition.id
    assert withdrawal.item_version == result.resulting_item_version == 1
    event = DomainEvent.objects.get(aggregate_type="programme.public_copy_withdrawal")
    assert event.aggregate_id == rendition.id
    assert event.payload["action"] == "withdraw_public_copy"
    assert AuditEvent.objects.filter(id=event.causation_id, outcome="allow").exists()
    assert OutboxMessage.objects.filter(event=event).exists()
    assert withdraw(review_world, rendition.id, retry=retry) == replace(
        result, replayed=True
    )
    assert ProgrammePublicRenditionWithdrawal.objects.count() == 1
    assert (
        ProgrammePublicRendition.objects.get(id=rendition.id).public_title
        == rendition.public_title
    )
    assert not SchedulingReleaseDependencyKey.objects.exists()


@pytest.mark.parametrize("state", ["ready", "live", "closing", "archived"])
def test_historical_copy_can_be_withdrawn_after_operational_freeze(review_world, state):
    approved = review(review_world)
    advance(review_world, state)
    result = withdraw(review_world, approved.result_object_id)
    assert result.resulting_item_version == 1
    assert ProgrammePublicRenditionWithdrawal.objects.count() == 1
    assert review_world.item.working_revisions.count() == 1


def test_withdrawing_older_copy_does_not_withdraw_newer_reviewed_copy(review_world):
    first = review(review_world)
    second = review(review_world)
    withdraw(review_world, first.result_object_id)
    assert ProgrammePublicRenditionWithdrawal.objects.filter(
        rendition_id=first.result_object_id
    ).exists()
    assert not ProgrammePublicRenditionWithdrawal.objects.filter(
        rendition_id=second.result_object_id
    ).exists()


def test_new_retry_key_cannot_withdraw_same_copy_twice(review_world):
    approved = review(review_world)
    withdraw(review_world, approved.result_object_id)
    with pytest.raises(ProgrammeVersionConflictError):
        withdraw(review_world, approved.result_object_id)
    assert ProgrammePublicRenditionWithdrawal.objects.count() == 1


@pytest.mark.parametrize("field", ["item_id", "rendition_id"])
def test_missing_exact_target_cannot_withdraw_another_copy(review_world, field):
    approved = review(review_world)
    overrides = {field: uuid4()}
    target = overrides.pop("rendition_id", approved.result_object_id)
    with pytest.raises(ProgrammeUnavailableError):
        withdraw(review_world, target, **overrides)
    assert not ProgrammePublicRenditionWithdrawal.objects.exists()


def test_late_effect_failure_rolls_back_copy_withdrawal(review_world):
    approved = review(review_world)
    with (
        patch(
            "maru.programme.commands.publish_domain_event",
            side_effect=RuntimeError("Synthetic copy event failure"),
        ),
        pytest.raises(RuntimeError, match="Synthetic copy event failure"),
    ):
        withdraw(review_world, approved.result_object_id)
    assert not ProgrammePublicRenditionWithdrawal.objects.exists()


def test_raw_withdrawal_without_receipt_audit_and_effects_is_rejected(review_world):
    approved = review(review_world)
    with (
        pytest.raises(IntegrityError, match="exact new receipt audit and effects"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO public.programme_programmepublicrenditionwithdrawal "
            "(id, created_at, updated_at, item_version, reason, occurred_at, actor_id, "
            "organization_id, edition_id, item_id, rendition_id) "
            "VALUES (%s, now(), now(), 1, 'Synthetic unreceipted withdrawal', now(), "
            "%s, %s, %s, %s, %s)",
            [
                uuid4(),
                review_world.reviewer.id,
                review_world.edition.organization_id,
                review_world.edition.id,
                review_world.item.id,
                approved.result_object_id,
            ],
        )
    assert not ProgrammePublicRenditionWithdrawal.objects.exists()


def test_withdrawn_current_copy_has_no_fallback_and_retains_private_explanation(
    review_world,
):
    first = review(review_world)
    second = review(review_world)
    common = {
        "actor_id": review_world.reviewer.id,
        "organization_id": review_world.edition.organization_id,
        "edition_id": review_world.edition.id,
        "item_id": review_world.item.id,
        "authorizer": review_world.policy,
    }
    assert load_programme_public_copy(**common).rendition_number == 2
    withdraw(review_world, second.result_object_id)
    assert load_programme_public_copy(**common) is None
    history = list_programme_public_copy_review_history(
        **common, reason="Review the exact synthetic withdrawal history"
    )
    assert history[0].withdrawn_at is not None
    assert history[0].withdrawn_by_id == review_world.reviewer.id
    assert history[0].withdrawal_reason == "Withdraw this exact synthetic public copy"
    assert history[1].withdrawn_at is None
    assert ProgrammePublicRendition.objects.filter(id=first.result_object_id).exists()


def track_copy(scope, identifier):
    with transaction.atomic(), scheduling_writer():
        return SchedulingReleaseDependencyKey.objects.create(
            kind="programme_public_copy",
            source_id=identifier,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
        )


def test_native_withdrawal_changes_only_exact_tracked_copy_once(review_world):
    first, second = review(review_world), review(review_world)
    old_key = track_copy(review_world, first.result_object_id)
    new_key = track_copy(review_world, second.result_object_id)
    retry = uuid4()
    withdraw(review_world, first.result_object_id, retry=retry)
    withdraw(review_world, first.result_object_id, retry=retry)
    old_key.refresh_from_db()
    new_key.refresh_from_db()
    assert old_key.generation == 2
    assert new_key.generation == 1
    change = SchedulingReleaseDependencyChange.objects.get()
    assert change.dependency_id == old_key.id
    assert (
        change.source_audit.operation == "programme.command.public_rendition_withdraw"
    )
    assert change.source_audit.target_id == review_world.item.id


def test_skipped_native_join_cannot_commit_tracked_copy_withdrawal(review_world):
    approved = review(review_world)
    key = track_copy(review_world, approved.result_object_id)
    with (
        patch("maru.programme.commands.record_programme_release_change"),
        pytest.raises(IntegrityError, match="native release invalidation"),
    ):
        withdraw(review_world, approved.result_object_id)
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()
    assert not ProgrammePublicRenditionWithdrawal.objects.exists()


def test_late_effect_failure_rolls_back_native_disclosure_generation(review_world):
    approved = review(review_world)
    key = track_copy(review_world, approved.result_object_id)
    with (
        patch(
            "maru.programme.commands.publish_domain_event",
            side_effect=RuntimeError("Synthetic late copy failure"),
        ),
        pytest.raises(RuntimeError, match="Synthetic late copy failure"),
    ):
        withdraw(review_world, approved.result_object_id)
    key.refresh_from_db()
    assert key.generation == 1
    assert not ProgrammePublicRenditionWithdrawal.objects.exists()
    assert not SchedulingReleaseDependencyChange.objects.exists()
