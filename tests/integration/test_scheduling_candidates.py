"""Stable occurrence and independent candidate-history transaction evidence."""

from dataclasses import replace
from functools import partial
from uuid import uuid4

import pytest

import maru.effects.services as effect_services
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.programme import scheduling_queries as programme_source
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import candidate_commands, occurrence_commands
from maru.scheduling.authorization import (
    VIEW_HISTORY,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.candidate_commands import (
    archive_scheduling_candidate,
    copy_scheduling_candidate,
    create_scheduling_candidate,
    restore_scheduling_candidate,
)
from maru.scheduling.command_support import (
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.inputs import SchedulingCommandRequest, SchedulingOccurrenceInput
from maru.scheduling.models import (
    SchedulingCandidate,
    SchedulingCandidateRevision,
    SchedulingCommandReceipt,
    SchedulingEditionControl,
    SchedulingOccurrence,
    SchedulingOccurrenceRevision,
)
from maru.scheduling.occurrence_commands import (
    create_scheduling_occurrence,
    retire_scheduling_occurrence,
    revise_scheduling_occurrence,
)
from maru.venues.models import VenueBooking
from tests.factories import AccountFactory, EventEditionFactory
from tests.integration.test_programme_commands import (
    _create,
    _TrustedProgrammeAuthorizer,
)
from tests.integration.test_scheduling_days import TrustedSchedulingPolicy

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(
        effect_services, "require_effect_delivery_allowed", lambda **_kwargs: None
    )
    actor, edition = AccountFactory(), EventEditionFactory()
    request = SchedulingCommandRequest(
        actor.id,
        edition.organization_id,
        edition.id,
        uuid4(),
        uuid4(),
        "Synthetic candidate planning",
        "test",
    )
    policy = TrustedSchedulingPolicy()
    return request, policy, actor, edition


def request(world):
    return replace(world[0], idempotency_key=uuid4(), correlation_id=uuid4())


def create(world, *, label="First draft", control=0):
    return create_scheduling_candidate(
        request(world),
        label=label,
        expected_control_version=control,
        authorizer=world[1],
    )


def revision(result):
    return SchedulingCandidateRevision.objects.get(
        candidate_id=result.object_id, sequence=result.version
    )


@pytest.fixture
def item(world, monkeypatch):
    programme_policy = _TrustedProgrammeAuthorizer()
    item, _, _ = _create(actor=world[2], edition=world[3], authorizer=programme_policy)
    monkeypatch.setattr(
        programme_source, "profile_allows_conflict_source", lambda *_args: True
    )
    monkeypatch.setattr(
        occurrence_commands,
        "load_programme_scheduling_dependencies",
        partial(
            programme_source.load_programme_scheduling_dependencies,
            authorizer=programme_policy,
        ),
    )
    return item.item_id


def test_empty_candidate_is_private_and_cannot_reserve_a_room(world):
    result = create(world)
    row = revision(result)
    assert row.placement_count == 0
    assert row.source_revision_id is None
    assert SchedulingCandidate.objects.get(id=result.object_id).lifecycle == "draft"
    assert not VenueBooking.objects.exists()


def test_copy_then_restore_retains_independent_identity_and_exact_source(world):
    original = create(world)
    source = revision(original)
    copied = copy_scheduling_candidate(
        request(world),
        source_revision_id=source.id,
        label="Alternative",
        expected_control_version=1,
        authorizer=world[1],
    )
    assert copied.object_id != original.object_id
    assert revision(copied).source_revision_id == source.id
    restored = restore_scheduling_candidate(
        request(world),
        candidate_id=copied.object_id,
        source_revision_id=revision(copied).id,
        expected_version=1,
        authorizer=world[1],
    )
    assert restored.version == 2
    assert SchedulingCandidate.objects.get(id=original.object_id).aggregate_version == 1
    assert SchedulingCandidateRevision.objects.get(id=source.id).label == "First draft"
    assert (
        AuditEvent.objects.filter(
            operation="scheduling.query.history_source", capability_code=VIEW_HISTORY
        ).count()
        == 2
    )


def test_restore_cannot_silently_replace_another_candidates_history(world):
    original = create(world)
    second = create(world, control=1)
    with pytest.raises(SchedulingUnavailableError):
        restore_scheduling_candidate(
            request(world),
            candidate_id=second.object_id,
            source_revision_id=revision(original).id,
            expected_version=1,
            authorizer=world[1],
        )
    assert SchedulingEditionControl.objects.get().aggregate_version == 2
    assert SchedulingCandidateRevision.objects.count() == 2


def test_archive_preserves_source_and_can_be_copied_to_a_new_draft(world):
    original = create(world)
    archived = archive_scheduling_candidate(
        request(world),
        candidate_id=original.object_id,
        expected_version=1,
        authorizer=world[1],
    )
    assert archived.version == 2
    assert (
        SchedulingCandidate.objects.get(id=original.object_id).lifecycle == "archived"
    )
    with pytest.raises(SchedulingLifecycleConflictError):
        restore_scheduling_candidate(
            request(world),
            candidate_id=original.object_id,
            source_revision_id=revision(original).id,
            expected_version=2,
            authorizer=world[1],
        )
    copied = copy_scheduling_candidate(
        request(world),
        source_revision_id=revision(archived).id,
        label="Recovered draft",
        expected_control_version=2,
        authorizer=world[1],
    )
    assert SchedulingCandidate.objects.get(id=copied.object_id).lifecycle == "draft"
    assert copied.object_id != original.object_id


def test_copy_requires_independent_history_field_authority(world):
    original = create(world)

    class MissingHistoryFields(TrustedSchedulingPolicy):
        def authorize(self, **kwargs):
            decision = super().authorize(**kwargs)
            return (
                replace(decision, fields=frozenset())
                if kwargs["capability_code"] == VIEW_HISTORY
                else decision
            )

    with pytest.raises(SchedulingAuthorizationDeniedError):
        copy_scheduling_candidate(
            request(world),
            source_revision_id=revision(original).id,
            label="Forbidden copy",
            expected_control_version=1,
            authorizer=MissingHistoryFields(),
        )
    assert SchedulingCandidate.objects.count() == 1


def test_foreign_history_source_is_not_copyable(world):
    original = create(world)
    other = EventEditionFactory()
    with pytest.raises(SchedulingUnavailableError):
        copy_scheduling_candidate(
            replace(
                request(world),
                organization_id=other.organization_id,
                edition_id=other.id,
            ),
            source_revision_id=revision(original).id,
            label="Foreign copy",
            expected_control_version=1,
            authorizer=world[1],
        )
    assert SchedulingCandidate.objects.count() == 1


def test_stale_copy_control_changes_neither_source_nor_target(world):
    original = create(world)
    with pytest.raises(SchedulingVersionConflictError):
        copy_scheduling_candidate(
            request(world),
            source_revision_id=revision(original).id,
            label="Stale copy",
            expected_control_version=2,
            authorizer=world[1],
        )
    assert SchedulingCandidate.objects.count() == 1
    assert SchedulingCommandReceipt.objects.count() == 1


def test_revision_bound_keeps_archive_available(world, monkeypatch):
    original = create(world)
    monkeypatch.setattr(candidate_commands, "MAX_CANDIDATE_REVISIONS", 1)
    with pytest.raises(SchedulingLimitError):
        restore_scheduling_candidate(
            request(world),
            candidate_id=original.object_id,
            source_revision_id=revision(original).id,
            expected_version=1,
            authorizer=world[1],
        )
    archived = archive_scheduling_candidate(
        request(world),
        candidate_id=original.object_id,
        expected_version=1,
        authorizer=world[1],
    )
    assert archived.version == 2


def test_candidate_history_read_audit_failure_rolls_back_copy(world, monkeypatch):
    original = create(world)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("Synthetic history audit unavailable")

    monkeypatch.setattr(candidate_commands, "append_audit", unavailable)
    with pytest.raises(RuntimeError, match="history audit unavailable"):
        copy_scheduling_candidate(
            request(world),
            source_revision_id=revision(original).id,
            label="Copy",
            expected_control_version=1,
            authorizer=world[1],
        )
    assert SchedulingCandidate.objects.count() == 1
    assert SchedulingEditionControl.objects.get().aggregate_version == 1


def test_repeat_occurrences_have_independent_identity_without_booking_or_hosts(
    world, item
):
    group = uuid4()
    results = [
        create_scheduling_occurrence(
            request(world),
            occurrence=SchedulingOccurrenceInput(item, group, index + 1),
            expected_control_version=index,
            authorizer=world[1],
        )
        for index in range(2)
    ]
    assert results[0].object_id != results[1].object_id
    assert list(
        SchedulingOccurrence.objects.values_list("programme_item_id", flat=True)
    ) == [item, item]
    assert SchedulingOccurrenceRevision.objects.count() == 2
    assert not VenueBooking.objects.exists()


def test_group_sequence_collision_is_rejected_without_partial_control(world, item):
    intent = SchedulingOccurrenceInput(item, uuid4(), 1)
    create_scheduling_occurrence(
        request(world),
        occurrence=intent,
        expected_control_version=0,
        authorizer=world[1],
    )
    with pytest.raises(SchedulingUnavailableError):
        create_scheduling_occurrence(
            request(world),
            occurrence=intent,
            expected_control_version=1,
            authorizer=world[1],
        )
    assert SchedulingOccurrence.objects.count() == 1
    assert SchedulingEditionControl.objects.get().aggregate_version == 1


def test_occurrence_group_correction_and_retirement_keep_identity(world, item):
    first = create_scheduling_occurrence(
        request(world),
        occurrence=SchedulingOccurrenceInput(item),
        expected_control_version=0,
        authorizer=world[1],
    )
    revised = revise_scheduling_occurrence(
        request(world),
        occurrence_id=first.object_id,
        occurrence=SchedulingOccurrenceInput(item, uuid4(), 1),
        expected_version=1,
        authorizer=world[1],
    )
    retired = retire_scheduling_occurrence(
        request(world),
        occurrence_id=first.object_id,
        expected_version=2,
        authorizer=world[1],
    )
    assert first.object_id == revised.object_id == retired.object_id
    assert list(
        SchedulingOccurrenceRevision.objects.order_by("sequence").values_list(
            "lifecycle", flat=True
        )
    ) == ["active", "active", "retired"]


def test_scheduling_authority_cannot_supply_programme_authority(
    world, item, monkeypatch
):
    monkeypatch.setattr(
        occurrence_commands,
        "load_programme_scheduling_dependencies",
        programme_source.load_programme_scheduling_dependencies,
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        create_scheduling_occurrence(
            request(world),
            occurrence=SchedulingOccurrenceInput(item),
            expected_control_version=0,
            authorizer=world[1],
        )
    assert not SchedulingOccurrence.objects.exists()


def test_late_history_field_revocation_is_denied(world):
    original = create(world)

    class RevokeHistory(TrustedSchedulingPolicy):
        reads = 0

        def authorize(self, **kwargs):
            if kwargs["capability_code"] == VIEW_HISTORY:
                self.reads += 1
                return PolicyDecision(
                    allowed=self.reads == 1,
                    fields=kwargs["requested_fields"],
                    obligations=frozenset({"audit"}),
                    reason_code="synthetic_history_revocation",
                )
            return super().authorize(**kwargs)

    with pytest.raises(SchedulingAuthorizationDeniedError):
        copy_scheduling_candidate(
            request(world),
            source_revision_id=revision(original).id,
            label="Copy",
            expected_control_version=1,
            authorizer=RevokeHistory(),
        )
    assert SchedulingCandidate.objects.count() == 1
