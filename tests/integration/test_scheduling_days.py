"""Real owner transactions for service-day revisions, retries and concurrency."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections

import maru.effects.services as effect_services
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.scheduling import command_support, day_commands
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import (
    SchedulingIdempotencyConflictError,
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.day_commands import (
    create_scheduling_service_day,
    retire_scheduling_service_day,
    revise_scheduling_service_day,
)
from maru.scheduling.inputs import SchedulingCommandRequest, SchedulingServiceDayInput
from maru.scheduling.models import (
    SchedulingCommandReceipt,
    SchedulingEditionControl,
    SchedulingServiceDay,
    SchedulingServiceDayRevision,
)
from maru.scheduling.time_rules import SchedulingWindow
from tests.factories import AccountFactory, EventEditionFactory

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@dataclass
class TrustedSchedulingPolicy:
    calls: int = 0
    deny_at: int | None = None

    def authorize(self, **kwargs):
        self.calls += 1
        return PolicyDecision(
            allowed=self.deny_at is None or self.calls < self.deny_at,
            fields=kwargs["requested_fields"] or frozenset(),
            obligations=frozenset({"audit", "reason"}),
            reason_code="sealed_future_profile_harness",
        )


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(
        effect_services, "require_effect_delivery_allowed", lambda **_kwargs: None
    )
    person, edition = AccountFactory(), EventEditionFactory()
    request = SchedulingCommandRequest(
        person.id,
        edition.organization_id,
        edition.id,
        uuid4(),
        uuid4(),
        "Set up the synthetic service day",
        "test",
    )
    return request, TrustedSchedulingPolicy()


def day(*, start=8, end=20):
    return SchedulingServiceDayInput(
        "Friday",
        SchedulingWindow(
            datetime(2030, 8, 2, start, tzinfo=UTC),
            datetime(2030, 8, 2, end, tzinfo=UTC),
        ),
        5,
    )


def create(world, *, intent=None, control=0, request=None):
    return create_scheduling_service_day(
        request or world[0],
        day=intent or day(),
        expected_control_version=control,
        authorizer=world[1],
    )


def next_request(world):
    return replace(world[0], idempotency_key=uuid4(), correlation_id=uuid4())


def test_real_profile_denies_without_creating_control(world):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        create_scheduling_service_day(world[0], day=day(), expected_control_version=0)
    assert not SchedulingEditionControl.objects.exists()
    assert (
        AuditEvent.objects.get(operation="scheduling.command.day_create").outcome
        == "deny"
    )


def test_day_create_retains_matching_receipt_audit_event_and_outbox(world):
    result = create(world)
    revision = SchedulingServiceDayRevision.objects.get(day_id=result.object_id)
    assert revision.sequence == result.version == result.control_version == 1
    assert revision.actor_id == world[0].actor_id
    receipt = SchedulingCommandReceipt.objects.get(id=result.receipt_id)
    audit = AuditEvent.objects.get(
        operation="scheduling.command.day_create", outcome="allow"
    )
    event = DomainEvent.objects.get(event_name="scheduling.planning.changed.v1")
    assert event.aggregate_id == world[0].edition_id
    assert event.aggregate_version == receipt.control_version
    assert event.causation_id == audit.id
    assert event.payload == {"operation": "day_create"}
    assert OutboxMessage.objects.filter(event=event).count() == 1


def test_exact_retry_ignores_new_trace_but_retains_original_evidence(world):
    original = create(world)
    replay = create(world, request=replace(world[0], correlation_id=uuid4()))
    assert replay == replace(original, replayed=True)
    assert SchedulingServiceDayRevision.objects.count() == 1
    assert SchedulingCommandReceipt.objects.count() == 1


def test_same_retry_key_cannot_change_day_or_reason(world):
    create(world)
    with pytest.raises(SchedulingIdempotencyConflictError):
        create(world, intent=day(end=19))
    with pytest.raises(SchedulingIdempotencyConflictError):
        create(world, request=replace(world[0], reason="Different rationale"))
    assert SchedulingCommandReceipt.objects.count() == 1


def test_revise_retains_previous_window_and_exact_revision_versions(world):
    original = create(world)
    revised = revise_scheduling_service_day(
        next_request(world),
        day_id=original.object_id,
        day=day(end=21),
        expected_version=1,
        authorizer=world[1],
    )
    assert revised.object_id == original.object_id
    assert revised.version == revised.control_version == 2
    revisions = list(SchedulingServiceDayRevision.objects.order_by("sequence"))
    assert [row.ends_at.hour for row in revisions] == [20, 21]


def test_overlap_fails_but_adjacent_days_are_distinct(world):
    first = create(world, intent=day(end=15))
    with pytest.raises(SchedulingUnavailableError):
        create(world, intent=day(start=14), control=1, request=next_request(world))
    second = create(world, intent=day(start=15), control=1, request=next_request(world))
    assert first.object_id != second.object_id
    assert SchedulingServiceDay.objects.count() == 2


def test_overnight_window_is_not_split_into_calendar_days(world):
    intent = SchedulingServiceDayInput(
        "Friday night",
        SchedulingWindow(
            datetime(2030, 8, 2, 20, tzinfo=UTC), datetime(2030, 8, 3, 3, tzinfo=UTC)
        ),
        15,
    )
    result = create(world, intent=intent)
    revision = SchedulingServiceDayRevision.objects.get(day_id=result.object_id)
    assert revision.starts_at.day == 2
    assert revision.ends_at.day == 3
    assert SchedulingServiceDay.objects.count() == 1


def test_day_outside_current_edition_is_rejected_atomically(world):
    intent = replace(
        day(),
        window=SchedulingWindow(
            datetime(2029, 8, 2, 8, tzinfo=UTC), datetime(2029, 8, 2, 10, tzinfo=UTC)
        ),
    )
    with pytest.raises(SchedulingUnavailableError):
        create(world, intent=intent)
    assert not SchedulingEditionControl.objects.exists()


def test_retirement_preserves_history_and_allows_replacement_window(world):
    first = create(world)
    retired = retire_scheduling_service_day(
        next_request(world),
        day_id=first.object_id,
        expected_version=1,
        authorizer=world[1],
    )
    assert retired.version == 2
    assert list(
        SchedulingServiceDayRevision.objects.order_by("sequence").values_list(
            "lifecycle", flat=True
        )
    ) == ["active", "retired"]
    replacement = create(world, control=2, request=next_request(world))
    assert replacement.object_id != first.object_id
    with pytest.raises(SchedulingLifecycleConflictError):
        revise_scheduling_service_day(
            next_request(world),
            day_id=first.object_id,
            expected_version=2,
            day=day(),
            authorizer=world[1],
        )


def test_stale_version_rolls_back_control_increment(world):
    first = create(world)
    with pytest.raises(SchedulingVersionConflictError):
        create(world, control=0, request=next_request(world))
    with pytest.raises(SchedulingVersionConflictError):
        revise_scheduling_service_day(
            next_request(world),
            day_id=first.object_id,
            expected_version=2,
            day=day(),
            authorizer=world[1],
        )
    assert SchedulingEditionControl.objects.get().aggregate_version == 1
    assert SchedulingCommandReceipt.objects.count() == 1


def test_foreign_day_cannot_be_revised_with_another_editions_authority(world):
    first = create(world)
    other = EventEditionFactory()
    with pytest.raises(SchedulingUnavailableError):
        revise_scheduling_service_day(
            replace(
                next_request(world),
                organization_id=other.organization_id,
                edition_id=other.id,
            ),
            day_id=first.object_id,
            expected_version=1,
            day=day(),
            authorizer=world[1],
        )
    assert SchedulingEditionControl.objects.count() == 1


@pytest.mark.parametrize("sink", ["append_audit", "publish_domain_event"])
def test_late_evidence_failure_rolls_back_every_owned_success(world, monkeypatch, sink):
    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic evidence failure")

    monkeypatch.setattr(command_support, sink, fail)
    with pytest.raises(RuntimeError, match="evidence failure"):
        create(world)
    assert not SchedulingServiceDay.objects.exists()
    assert not SchedulingEditionControl.objects.exists()
    assert not SchedulingCommandReceipt.objects.exists()
    assert not DomainEvent.objects.filter(
        event_name="scheduling.planning.changed.v1"
    ).exists()
    assert not AuditEvent.objects.filter(
        operation="scheduling.command.day_create", outcome="allow"
    ).exists()


def test_late_authority_revocation_rolls_back_draft(world):
    world[1].deny_at = 4
    with pytest.raises(SchedulingAuthorizationDeniedError):
        create(world)
    assert not SchedulingServiceDay.objects.exists()
    assert not SchedulingCommandReceipt.objects.exists()


def test_metadata_bound_leaves_retirement_available(world, monkeypatch):
    first = create(world)
    monkeypatch.setattr(day_commands, "MAX_REVISIONS", 1)
    with pytest.raises(SchedulingLimitError):
        revise_scheduling_service_day(
            next_request(world),
            day_id=first.object_id,
            expected_version=1,
            day=day(),
            authorizer=world[1],
        )
    retired = retire_scheduling_service_day(
        next_request(world),
        day_id=first.object_id,
        expected_version=1,
        authorizer=world[1],
    )
    assert retired.version == 2


def test_same_key_concurrent_create_commits_once(world):
    barrier = Barrier(2)

    def compete():
        close_old_connections()
        try:
            barrier.wait(timeout=20)
            return create(world)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: compete(), range(2)))
    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].object_id == results[1].object_id
    assert SchedulingCommandReceipt.objects.count() == 1


def test_competing_day_revisions_have_one_winner(world):
    first = create(world)
    barrier = Barrier(2)

    def compete(end):
        close_old_connections()
        try:
            barrier.wait(timeout=20)
            try:
                revise_scheduling_service_day(
                    next_request(world),
                    day_id=first.object_id,
                    expected_version=1,
                    day=day(end=end),
                    authorizer=world[1],
                )
            except SchedulingVersionConflictError:
                return "stale"
            else:
                return "changed"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(compete, (21, 22)))
    assert sorted(outcomes) == ["changed", "stale"]
    assert SchedulingServiceDayRevision.objects.count() == 2
    assert SchedulingCommandReceipt.objects.count() == 2
