"""Stable occurrence and independent candidate-history transaction evidence."""

from dataclasses import asdict, replace
from datetime import timedelta
from functools import partial
from uuid import uuid4

import pytest
from django.conf import settings
from django.db import DatabaseError
from django.http import QueryDict
from django.middleware.csrf import get_token
from django.test import RequestFactory

import maru.effects.services as effect_services
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.identity.models import Account
from maru.programme import host_queries as programme_hosts
from maru.programme import queries as programme_queries
from maru.programme import scheduling_queries as programme_source
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import (
    candidate_commands,
    evaluation_sources,
    occurrence_commands,
    planning_hosts,
    planning_inspector,
)
from maru.scheduling import planning_queries as queries
from maru.scheduling import planning_views as planning_http
from maru.scheduling import planning_workspace as workspace
from maru.scheduling.authorization import (
    VIEW_HISTORY,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.candidate_commands import (
    archive_scheduling_candidate,
    copy_scheduling_candidate,
    create_scheduling_candidate,
    remove_scheduling_placement,
    restore_scheduling_candidate,
)
from maru.scheduling.catalogs import SchedulingOperation
from maru.scheduling.command_support import (
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.day_commands import revise_scheduling_service_day
from maru.scheduling.inputs import (
    SchedulingCommandRequest,
    SchedulingOccurrenceInput,
    SchedulingServiceDayInput,
)
from maru.scheduling.models import (
    SchedulingCandidate,
    SchedulingCandidateRevision,
    SchedulingCommandReceipt,
    SchedulingEditionControl,
    SchedulingOccurrence,
    SchedulingOccurrenceRevision,
    SchedulingServiceDay,
)
from maru.scheduling.occurrence_commands import (
    create_scheduling_occurrence,
    retire_scheduling_occurrence,
    revise_scheduling_occurrence,
)
from maru.scheduling.planning_board import build_scheduling_planning_board
from maru.scheduling.planning_controls import build_planning_control
from maru.scheduling.planning_hosts import load_scheduling_host_requirements
from maru.scheduling.planning_inspector import (
    PlanningItemLayer,
    load_scheduling_item_inspector,
)
from maru.scheduling.planning_queries import (
    SchedulingReadRequest,
    list_scheduling_candidate_history,
    load_scheduling_historical_manifest,
    load_scheduling_planning,
)
from maru.scheduling.planning_record_actions import submit_planning_record
from maru.scheduling.planning_record_forms import PlanningRecordForm
from maru.scheduling.planning_selection import PlanningSelection
from maru.scheduling.planning_views import scheduling_planning_view
from maru.venues.models import VenueBooking
from maru.venues.timetable_queries import list_venue_timetable_spaces
from tests.factories import AccountFactory, CapabilityGrantFactory, EventEditionFactory
from tests.integration import test_scheduling_placements as planning_helpers
from tests.integration.test_programme_commands import (
    _create,
    _TrustedProgrammeAuthorizer,
)
from tests.integration.test_scheduling_days import TrustedSchedulingPolicy
from tests.integration.test_scheduling_placements import (
    candidate_revision,
    next_request,
    place,
)

planning_world = planning_helpers.world

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


def read_request(planning_world):
    request = planning_world.request
    return SchedulingReadRequest(
        request.actor_id, request.organization_id, request.edition_id, uuid4()
    )


def record_form(operation, *, choices=None, **values):
    return PlanningRecordForm(
        {
            "action": operation.value,
            "retry_key": str(uuid4()),
            "reason": "Explicit synthetic record change",
            **{key: str(value) for key, value in values.items()},
        },
        operation=operation,
        choices=choices,
    )


def test_native_candidate_history_round_trip_retains_exact_source(planning_world):
    scope = read_request(planning_world)
    policy = planning_world.policy
    placed = place(planning_world)
    source = candidate_revision(placed)
    removed = submit_planning_record(
        scope,
        record_form(
            SchedulingOperation.PLACEMENT_REMOVE,
            candidate_id=placed.object_id,
            occurrence_id=planning_world.occurrence.object_id,
            expected_version=placed.version,
            confirm="confirmed",
        ),
        authorizer=policy,
    )
    assert candidate_revision(removed).placement_count == 0
    restore = record_form(
        SchedulingOperation.CANDIDATE_RESTORE,
        candidate_id=placed.object_id,
        source_revision_id=source.id,
        expected_version=removed.version,
        confirm="confirmed",
    )
    restored = submit_planning_record(scope, restore, authorizer=policy)
    assert candidate_revision(restored).source_revision_id == source.id
    assert candidate_revision(restored).placement_count == 1
    assert candidate_revision(placed).placement_count == 1
    replay = submit_planning_record(scope, restore, authorizer=policy)
    assert replay.replayed
    assert replay.receipt_id == restored.receipt_id
    archived = submit_planning_record(
        scope,
        record_form(
            SchedulingOperation.CANDIDATE_ARCHIVE,
            candidate_id=placed.object_id,
            expected_version=restored.version,
            confirm="confirmed",
        ),
        authorizer=policy,
    )
    assert (
        SchedulingCandidate.objects.get(id=archived.object_id).lifecycle == "archived"
    )
    current_control = load_scheduling_planning(scope, authorizer=policy).control_version
    assert current_control == 7
    copied = submit_planning_record(
        scope,
        record_form(
            SchedulingOperation.CANDIDATE_COPY,
            label="Recovered alternative",
            source_revision_id=source.id,
            expected_version=current_control,
        ),
        authorizer=policy,
    )
    assert copied.object_id != placed.object_id
    assert candidate_revision(copied).source_revision_id == source.id
    assert candidate_revision(copied).placement_count == 1
    assert not VenueBooking.objects.exists()


def test_native_occurrence_repetition_group_revision_and_retirement(world, item):
    command, policy, _, _ = world
    scope = SchedulingReadRequest(
        command.actor_id, command.organization_id, command.edition_id, uuid4()
    )
    group = uuid4()
    choices = {
        "item_id": ((item, "Opening"),),
        "group_key": ((group, "Opening group"),),
    }
    results = [
        submit_planning_record(
            scope,
            record_form(
                SchedulingOperation.OCCURRENCE_CREATE,
                choices=choices,
                item_id=item,
                group_key=group,
                group_sequence=sequence,
                expected_version=sequence - 1,
            ),
            authorizer=policy,
        )
        for sequence in (1, 2)
    ]
    assert results[0].object_id != results[1].object_id
    assert SchedulingOccurrence.objects.filter(programme_item_id=item).count() == 2
    revised = submit_planning_record(
        scope,
        record_form(
            SchedulingOperation.OCCURRENCE_REVISE,
            choices=choices,
            item_id=item,
            occurrence_id=results[1].object_id,
            group_key="",
            group_sequence="",
            expected_version=1,
        ),
        authorizer=policy,
    )
    retired = submit_planning_record(
        scope,
        record_form(
            SchedulingOperation.OCCURRENCE_RETIRE,
            occurrence_id=revised.object_id,
            expected_version=revised.version,
            confirm="confirmed",
        ),
        authorizer=policy,
    )
    assert retired.version == 3
    assert SchedulingOccurrence.objects.get(id=retired.object_id).lifecycle == "retired"
    assert (
        SchedulingOccurrenceRevision.objects.filter(
            occurrence_id=retired.object_id
        ).count()
        == 3
    )
    assert (
        SchedulingOccurrenceRevision.objects.get(
            occurrence_id=retired.object_id, sequence=1
        ).group_key
        == group
    )
    assert not VenueBooking.objects.exists()


def test_native_record_read_authority_does_not_grant_mutation(world):
    command, _, _, _ = world
    scope = SchedulingReadRequest(
        command.actor_id, command.organization_id, command.edition_id, uuid4()
    )
    form = record_form(
        SchedulingOperation.CANDIDATE_CREATE, label="Private", expected_version=0
    )
    with pytest.raises(SchedulingAuthorizationDeniedError):
        submit_planning_record(
            scope, form, authorizer=TrustedSchedulingPolicy(deny_at=2)
        )
    assert not SchedulingCandidate.objects.exists()
    assert not SchedulingCommandReceipt.objects.exists()
    assert form.data["label"] == "Private"


def test_native_candidate_create_and_stale_control_do_not_rebase(world):
    command, policy, _, _ = world
    scope = SchedulingReadRequest(
        command.actor_id, command.organization_id, command.edition_id, uuid4()
    )
    form = record_form(
        SchedulingOperation.CANDIDATE_CREATE, label="First", expected_version=0
    )
    created = submit_planning_record(scope, form, authorizer=policy)
    assert created.version == 1
    stale = record_form(
        SchedulingOperation.CANDIDATE_CREATE, label="Second", expected_version=0
    )
    original = dict(stale.data)
    with pytest.raises(SchedulingVersionConflictError):
        submit_planning_record(scope, stale, authorizer=policy)
    assert dict(stale.data) == original
    assert SchedulingCandidate.objects.count() == 1
    assert SchedulingCommandReceipt.objects.count() == 1


@pytest.mark.parametrize("foreign_organization", [False, True])
def test_native_record_identifier_cannot_cross_trusted_scope(
    world, foreign_organization
):
    command, policy, _, edition = world
    candidate = create(world)
    other = (
        EventEditionFactory()
        if foreign_organization
        else EventEditionFactory(
            organization=edition.organization, series=edition.series
        )
    )
    scope = SchedulingReadRequest(
        command.actor_id, other.organization_id, other.id, uuid4()
    )
    form = record_form(
        SchedulingOperation.CANDIDATE_ARCHIVE,
        candidate_id=candidate.object_id,
        expected_version=1,
        confirm="confirmed",
    )
    with pytest.raises(SchedulingUnavailableError):
        submit_planning_record(scope, form, authorizer=policy)
    assert SchedulingCandidate.objects.get(id=candidate.object_id).lifecycle == "draft"
    assert SchedulingCommandReceipt.objects.count() == 1


def test_native_copy_still_requires_independent_history_authority(world):
    command, _, _, _ = world
    candidate = create(world)

    class DenyHistory(TrustedSchedulingPolicy):
        def authorize(self, **kwargs):
            if kwargs["capability_code"] == VIEW_HISTORY:
                return PolicyDecision(
                    allowed=False,
                    fields=frozenset(),
                    obligations=frozenset(),
                    reason_code="synthetic_history_denial",
                )
            return super().authorize(**kwargs)

    scope = SchedulingReadRequest(
        command.actor_id, command.organization_id, command.edition_id, uuid4()
    )
    form = record_form(
        SchedulingOperation.CANDIDATE_COPY,
        source_revision_id=revision(candidate).id,
        expected_version=1,
        label="Cannot copy without history",
    )
    with pytest.raises(SchedulingAuthorizationDeniedError):
        submit_planning_record(scope, form, authorizer=DenyHistory())
    assert SchedulingCandidate.objects.count() == 1
    assert SchedulingCommandReceipt.objects.count() == 1


def test_current_planning_does_not_imply_history_or_private_owner_layers(
    planning_world,
):
    place(planning_world)
    before = SchedulingCommandReceipt.objects.count()
    snapshot = load_scheduling_planning(
        read_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        authorizer=planning_world.policy,
    )
    assert snapshot.control_version == 4
    assert (
        len(snapshot.days) == len(snapshot.occurrences) == len(snapshot.candidates) == 1
    )
    assert snapshot.candidates[0].version == 2
    assert snapshot.placements[0].envelope == planning_world.placement.envelope
    assert snapshot.occurrences[0].id == planning_world.occurrence.object_id
    assert snapshot.days[0].id == planning_world.day.object_id
    assert snapshot.days[0].label == "Friday"
    assert (
        snapshot.placements[0].space_id == planning_world.placement.space_selection_id
    )
    output = repr(asdict(snapshot))
    for excluded in ("reason", "actor_id", "host", "availability", "working_summary"):
        assert excluded not in output
    assert str(planning_world.placement.host_presences[0].host_id) not in output
    assert SchedulingCommandReceipt.objects.count() == before
    audit = AuditEvent.objects.get(operation="scheduling.query.planning")
    assert audit.outcome == "allow"
    assert audit.safe_metadata["access_purpose"] == "planning"
    assert "First draft" not in repr(audit.safe_metadata)


def test_real_owner_board_keeps_placement_under_a_revised_stable_day(planning_world):
    placed = place(planning_world)
    scope = read_request(planning_world)
    original = load_scheduling_planning(
        scope, candidate_id=placed.object_id, authorizer=planning_world.policy
    )
    day = original.days[0]
    revise_scheduling_service_day(
        next_request(planning_world),
        day_id=day.id,
        expected_version=day.version,
        day=SchedulingServiceDayInput(
            "Revised Friday", day.window, day.precision_minutes
        ),
        authorizer=planning_world.policy,
    )
    edition = EventEdition.objects.select_related("organization").get(
        id=scope.edition_id
    )
    actor = Account.objects.get(id=scope.actor_id)
    CapabilityGrantFactory(
        principal=actor,
        organization=edition.organization,
        edition=edition,
        capability_code="venues.view_workspace",
    )
    before = SchedulingCommandReceipt.objects.count()
    snapshot = load_scheduling_planning(
        scope, candidate_id=placed.object_id, authorizer=planning_world.policy
    )
    items = programme_queries.list_programme_timetable_items(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        correlation_id=scope.correlation_id,
        authorizer=_TrustedProgrammeAuthorizer(),
    )
    spaces = list_venue_timetable_spaces(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        correlation_id=scope.correlation_id,
    )
    board = build_scheduling_planning_board(snapshot, items=items, spaces=spaces)
    assert len(board.lanes) == 1
    assert board.lanes[0].day.id == day.id
    assert board.lanes[0].day.label == "Revised Friday"
    assert board.lanes[0].entries[0].metadata_changed
    assert (
        board.lanes[0].entries[0].placement.envelope
        == planning_world.placement.envelope
    )
    assert SchedulingCommandReceipt.objects.count() == before
    assert not VenueBooking.objects.exists()


def test_no_selected_candidate_does_not_silently_pick_the_first(planning_world):
    place(planning_world)
    snapshot = load_scheduling_planning(
        read_request(planning_world), authorizer=planning_world.policy
    )
    assert len(snapshot.candidates) == 1
    assert snapshot.selected_candidate_id is None
    assert snapshot.placements == ()


def test_current_profiles_deny_all_planning_and_history_reads(planning_world):
    request = read_request(planning_world)
    calls = (
        lambda: load_scheduling_planning(request),
        lambda: list_scheduling_candidate_history(
            request, candidate_id=planning_world.candidate.object_id
        ),
        lambda: load_scheduling_historical_manifest(
            request, revision_id=candidate_revision(planning_world.candidate).id
        ),
    )
    for call in calls:
        with pytest.raises(SchedulingAuthorizationDeniedError):
            call()
    assert (
        AuditEvent.objects.filter(
            operation__startswith="scheduling.query.", outcome="deny"
        ).count()
        == 3
    )


def test_history_authority_is_separate_from_planning_authority(planning_world):
    class PlanningOnly:
        def authorize(self, **kwargs):
            return PolicyDecision(
                allowed=kwargs["capability_code"] != VIEW_HISTORY,
                fields=kwargs["requested_fields"],
                obligations=frozenset(),
                reason_code="synthetic_planning_only",
            )

    policy = PlanningOnly()
    assert load_scheduling_planning(
        read_request(planning_world), authorizer=policy
    ).candidates
    with pytest.raises(SchedulingAuthorizationDeniedError):
        list_scheduling_candidate_history(
            read_request(planning_world),
            candidate_id=planning_world.candidate.object_id,
            authorizer=policy,
        )


@pytest.mark.parametrize("removed", sorted(queries.PLANNING_FIELDS))
def test_each_missing_planning_field_denies_before_loading_labels(
    planning_world, monkeypatch, removed
):
    class MissingField:
        def authorize(self, **kwargs):
            return PolicyDecision(
                allowed=True,
                fields=kwargs["requested_fields"] - {removed},
                obligations=frozenset(),
                reason_code="synthetic_partial_projection",
            )

    def forbidden(*args, **kwargs):
        pytest.fail("A denied request reached the identifying loader")

    monkeypatch.setattr(queries, "_snapshot", forbidden)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_scheduling_planning(
            read_request(planning_world), authorizer=MissingField()
        )


def test_final_revocation_releases_neither_labels_nor_success_audit(planning_world):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_scheduling_planning(
            read_request(planning_world), authorizer=TrustedSchedulingPolicy(deny_at=2)
        )
    assert not AuditEvent.objects.filter(
        operation="scheduling.query.planning", outcome="allow"
    ).exists()
    assert AuditEvent.objects.filter(
        operation="scheduling.query.planning", outcome="deny"
    ).exists()


@pytest.mark.parametrize("field", ["organization_id", "edition_id", "actor_id"])
def test_foreign_or_missing_scope_is_non_disclosing(planning_world, field):
    request = replace(read_request(planning_world), **{field: uuid4()})
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_scheduling_planning(request, authorizer=planning_world.policy)


@pytest.mark.parametrize("same_organization", [False, True])
def test_missing_or_foreign_candidate_has_the_same_unavailable_shape(
    planning_world, same_organization
):
    current = EventEdition.objects.get(id=planning_world.request.edition_id)
    other_edition = EventEditionFactory(
        **({"series": current.series} if same_organization else {})
    )
    other_actor = AccountFactory()
    other = create_scheduling_candidate(
        SchedulingCommandRequest(
            other_actor.id,
            other_edition.organization_id,
            other_edition.id,
            uuid4(),
            uuid4(),
            "Foreign private reason",
            "test",
        ),
        label="Foreign private candidate",
        expected_control_version=0,
        authorizer=planning_world.policy,
    )
    for candidate in (uuid4(), other.object_id):
        with pytest.raises(SchedulingUnavailableError):
            load_scheduling_planning(
                read_request(planning_world),
                candidate_id=candidate,
                authorizer=planning_world.policy,
            )
        with pytest.raises(SchedulingUnavailableError):
            list_scheduling_candidate_history(
                read_request(planning_world),
                candidate_id=candidate,
                authorizer=planning_world.policy,
            )
    with pytest.raises(SchedulingUnavailableError):
        load_scheduling_historical_manifest(
            read_request(planning_world),
            revision_id=candidate_revision(other).id,
            authorizer=planning_world.policy,
        )
    snapshot = load_scheduling_planning(
        read_request(planning_world), authorizer=planning_world.policy
    )
    assert len(snapshot.candidates) == 1
    assert "Foreign private" not in repr(snapshot)


@pytest.mark.parametrize("lifecycle", ["draft", "closing", "archived", "cancelled"])
def test_empty_edition_is_truthful_and_closed_lifecycle_is_read_only(lifecycle):
    actor, edition = AccountFactory(), EventEditionFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=actor,
        capability_code="events.transition",
    )
    path = (
        ("cancelled",)
        if lifecycle == "cancelled"
        else ("preparing", "ready", "live", "closing", "archived")
    )
    for state in path:
        if edition.lifecycle == lifecycle:
            break
        edition = transition_edition(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            to_state=state,
            actor=actor,
            reason="Synthetic closed-edition read acceptance",
            correlation_id=uuid4(),
        )
    request = SchedulingReadRequest(
        actor.id, edition.organization_id, edition.id, uuid4()
    )
    snapshot = load_scheduling_planning(request, authorizer=TrustedSchedulingPolicy())
    assert snapshot.control_version == 0
    assert snapshot.days == snapshot.occurrences == snapshot.candidates == ()
    assert snapshot.accepts_writes is (lifecycle == "draft")
    assert not SchedulingEditionControl.objects.filter(edition_id=edition.id).exists()


def test_history_retains_reason_and_old_geometry_after_unplacement(planning_world):
    placed = place(planning_world)
    old = candidate_revision(placed)
    remove_scheduling_placement(
        next_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        occurrence_id=planning_world.occurrence.object_id,
        expected_version=2,
        authorizer=planning_world.policy,
    )
    current = load_scheduling_planning(
        read_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        authorizer=planning_world.policy,
    )
    retained = load_scheduling_historical_manifest(
        read_request(planning_world),
        revision_id=old.id,
        authorizer=planning_world.policy,
    )
    assert current.placements == ()
    assert len(current.occurrences) == 1
    assert retained.entry.reason == planning_world.request.reason
    assert retained.entry.version == 2
    assert retained.entry.actor_id == planning_world.request.actor_id
    assert retained.placements[0].envelope == planning_world.placement.envelope
    page = list_scheduling_candidate_history(
        read_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        authorizer=planning_world.policy,
    )
    assert [entry.version for entry in page.entries] == [3, 2, 1]
    assert page.next_before_version is None


def test_history_cursor_is_explicit_and_does_not_repeat_entries(
    planning_world, monkeypatch
):
    place(planning_world)
    monkeypatch.setattr(queries, "HISTORY_PAGE_SIZE", 1)
    first = list_scheduling_candidate_history(
        read_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        authorizer=planning_world.policy,
    )
    assert first.entries[0].version == first.next_before_version == 2
    second = list_scheduling_candidate_history(
        read_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        before_version=first.next_before_version,
        authorizer=planning_world.policy,
    )
    assert second.entries[0].version == 1
    assert second.next_before_version is None
    end = list_scheduling_candidate_history(
        read_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        before_version=1,
        authorizer=planning_world.policy,
    )
    assert end.entries == ()


def test_archive_remains_inspectable_but_is_never_an_approval(planning_world):
    archive_scheduling_candidate(
        next_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        expected_version=1,
        authorizer=planning_world.policy,
    )
    snapshot = load_scheduling_planning(
        read_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        authorizer=planning_world.policy,
    )
    assert snapshot.candidates[0].lifecycle == "archived"
    assert "approved" not in repr(asdict(snapshot))


@pytest.mark.parametrize(
    "bound", ["MAX_CANDIDATES", "MAX_OCCURRENCES", "MAX_RETAINED_SERVICE_DAYS"]
)
def test_overflow_is_unavailable_not_a_partial_passing_inventory(
    planning_world, monkeypatch, bound
):
    monkeypatch.setattr(queries, bound, 0)
    with pytest.raises(SchedulingLimitError):
        load_scheduling_planning(
            read_request(planning_world), authorizer=planning_world.policy
        )
    assert not AuditEvent.objects.filter(operation="scheduling.query.planning").exists()


def test_audit_failure_cannot_release_a_successful_projection(
    planning_world, monkeypatch
):
    def broken_audit(*args, **kwargs):
        raise DatabaseError("Synthetic audit failure")

    control = SchedulingEditionControl.objects.get(
        edition_id=planning_world.request.edition_id
    )
    monkeypatch.setattr(queries, "append_audit", broken_audit)
    with pytest.raises(SchedulingUnavailableError):
        load_scheduling_planning(
            read_request(planning_world), authorizer=planning_world.policy
        )
    control.refresh_from_db()
    assert control.aggregate_version == 3


def test_independent_alternatives_never_merge_their_manifests(planning_world):
    place(planning_world)
    other = create_scheduling_candidate(
        next_request(planning_world),
        label="Alternative",
        expected_control_version=4,
        authorizer=planning_world.policy,
    )
    snapshot = load_scheduling_planning(
        read_request(planning_world),
        candidate_id=other.object_id,
        authorizer=planning_world.policy,
    )
    assert len(snapshot.candidates) == 2
    assert snapshot.placements == ()
    original = load_scheduling_planning(
        read_request(planning_world),
        candidate_id=planning_world.candidate.object_id,
        authorizer=planning_world.policy,
    )
    assert len(original.placements) == 1


@pytest.fixture
def host_inspection_admitted(monkeypatch):
    monkeypatch.setattr(
        planning_hosts,
        "load_programme_host_roster",
        partial(
            programme_hosts.load_programme_host_roster,
            authorizer=_TrustedProgrammeAuthorizer(),
        ),
    )


def host_requirements(world, *, version=1, policy=None, occurrence=None):
    return load_scheduling_host_requirements(
        read_request(world),
        candidate_id=world.candidate.object_id,
        expected_version=version,
        occurrence_id=occurrence or world.occurrence.object_id,
        authorizer=policy or world.policy,
    )


def test_host_requirements_retain_explicit_times_not_availability(
    planning_world, host_inspection_admitted
):
    placed = place(planning_world)
    result = host_requirements(planning_world, version=placed.version)
    assert result.presences == planning_world.placement.host_presences
    assert result.roster.entries[0].display_label
    assert result.roster.entries[0].relationship.state == "confirmed"
    assert "availability" not in str(asdict(result))
    assert "email" not in str(asdict(result))
    assert AuditEvent.objects.filter(
        operation="programme.query.host_roster", outcome="allow"
    ).exists()
    assert AuditEvent.objects.filter(
        operation="scheduling.query.host_requirements", outcome="allow"
    ).exists()


def test_unplaced_host_requirements_are_empty_without_inventing_host_presence(
    planning_world, host_inspection_admitted
):
    result = host_requirements(planning_world)
    assert result.placement_id is None
    assert result.presences == ()
    assert len(result.roster.entries) == 1


def test_host_requirements_require_independent_programme_roster_authority(
    planning_world,
):
    place(planning_world)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        host_requirements(planning_world, version=2)
    assert not AuditEvent.objects.filter(
        operation="scheduling.query.host_requirements", outcome="allow"
    ).exists()
    assert AuditEvent.objects.filter(
        operation="scheduling.query.host_requirements", outcome="deny"
    ).exists()


def test_host_requirements_final_scheduling_revocation_withholds_names_and_times(
    planning_world, host_inspection_admitted
):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        host_requirements(planning_world, policy=TrustedSchedulingPolicy(deny_at=2))
    assert not AuditEvent.objects.filter(
        operation="programme.query.host_roster", outcome="allow"
    ).exists()
    assert AuditEvent.objects.filter(
        operation="scheduling.query.host_requirements", outcome="deny"
    ).exists()


def test_host_requirements_do_not_rebase_a_stale_candidate(
    planning_world, host_inspection_admitted
):
    place(planning_world)
    with pytest.raises(SchedulingVersionConflictError):
        host_requirements(planning_world)


def test_host_requirements_unknown_occurrence_is_unavailable(
    planning_world, host_inspection_admitted
):
    with pytest.raises(SchedulingUnavailableError):
        host_requirements(planning_world, occurrence=uuid4())


def test_host_requirements_overflow_is_not_a_partial_roster(
    planning_world, host_inspection_admitted, monkeypatch
):
    place(planning_world)
    monkeypatch.setattr(planning_hosts, "MAX_HOSTS_PER_OCCURRENCE", 0)
    with pytest.raises(SchedulingUnavailableError):
        host_requirements(planning_world, version=2)


def test_host_requirements_verify_manifest_occurrence_before_owner_disclosure(
    planning_world, host_inspection_admitted, monkeypatch
):
    placed = place(planning_world)
    first = SchedulingOccurrence.objects.get(id=planning_world.occurrence.object_id)
    second = create_scheduling_occurrence(
        next_request(planning_world),
        occurrence=SchedulingOccurrenceInput(first.programme_item_id),
        expected_control_version=4,
        authorizer=planning_world.policy,
    )
    placement_id = candidate_revision(placed).members.get().placement_id
    monkeypatch.setattr(
        planning_hosts,
        "_load_manifest",
        lambda _revision: ((second.object_id, placement_id),),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("Incoherent placement reached Programme roster disclosure")

    monkeypatch.setattr(planning_hosts, "load_programme_host_roster", forbidden)
    with pytest.raises(SchedulingUnavailableError):
        host_requirements(planning_world, version=2, occurrence=second.object_id)


INSPECTOR_LOADERS = {
    PlanningItemLayer.WORKING: (programme_queries, "load_programme_private_item"),
    PlanningItemLayer.PUBLIC_COPY: (programme_queries, "load_programme_public_copy"),
    PlanningItemLayer.DELIVERY: (programme_queries, "load_programme_delivery"),
    PlanningItemLayer.READINESS: (programme_queries, "load_programme_readiness"),
    PlanningItemLayer.HOSTS: (programme_hosts, "load_programme_host_roster"),
    PlanningItemLayer.SHARED_AVAILABILITY: (
        programme_hosts,
        "load_programme_host_dependencies",
    ),
}


@pytest.mark.parametrize("layer", list(PlanningItemLayer))
def test_inspector_loads_only_the_explicit_real_owner_layer(
    planning_world, layer, monkeypatch
):
    item = SchedulingOccurrence.objects.get(
        id=planning_world.occurrence.object_id
    ).programme_item_id
    calls = []

    def admit(selected_layer, original):
        def load(*args, **kwargs):
            calls.append(selected_layer)
            return original(*args, **kwargs, authorizer=_TrustedProgrammeAuthorizer())

        return load

    for selected, (module, name) in INSPECTOR_LOADERS.items():
        monkeypatch.setattr(module, name, admit(selected, getattr(module, name)))
    result = load_scheduling_item_inspector(
        read_request(planning_world),
        item_id=item,
        layer=layer,
        authorizer=planning_world.policy,
    )
    assert calls == [layer]
    assert result.layer is layer
    assert result.item_id == item
    assert AuditEvent.objects.filter(
        operation=f"scheduling.query.item_layer_{layer.value}", outcome="allow"
    ).exists()


@pytest.mark.parametrize("layer", list(PlanningItemLayer))
def test_inspector_never_uses_scheduling_permission_to_admit_a_programme_layer(
    planning_world, layer
):
    item = SchedulingOccurrence.objects.get(
        id=planning_world.occurrence.object_id
    ).programme_item_id
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_scheduling_item_inspector(
            read_request(planning_world),
            item_id=item,
            layer=layer,
            authorizer=planning_world.policy,
        )
    assert not AuditEvent.objects.filter(
        operation=f"scheduling.query.item_layer_{layer.value}", outcome="allow"
    ).exists()


def test_inspector_default_scheduling_policy_denies_before_owner_lookup(
    planning_world, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Denied Scheduling read reached a Programme owner")

    monkeypatch.setattr(planning_inspector, "_owner_layer", forbidden)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        load_scheduling_item_inspector(
            read_request(planning_world),
            item_id=uuid4(),
            layer=PlanningItemLayer.WORKING,
        )


def native_control_data(form, *, reason):
    data = QueryDict(mutable=True)
    for field in form:
        if field.name != "action":
            value = field.value()
            data[field.name] = "" if value is None else str(value)
    data["action"] = SchedulingOperation.OCCURRENCE_CREATE
    data["reason"] = reason
    return data


def test_native_factory_starts_then_extends_one_explicit_group_without_replay_writes(
    planning_world,
):
    scope = read_request(planning_world)
    items = programme_queries.list_programme_timetable_items(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        correlation_id=scope.correlation_id,
        authorizer=_TrustedProgrammeAuthorizer(),
    )
    edition = EventEdition.objects.get(id=scope.edition_id)
    CapabilityGrantFactory(
        principal=Account.objects.get(id=scope.actor_id),
        organization=edition.organization,
        edition=edition,
        capability_code="venues.view_workspace",
    )
    spaces = list_venue_timetable_spaces(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        correlation_id=scope.correlation_id,
    )
    snapshot = load_scheduling_planning(
        scope,
        candidate_id=planning_world.candidate.object_id,
        authorizer=planning_world.policy,
    )
    selection = PlanningSelection(
        candidate_id=snapshot.selected_candidate_id,
        item_id=snapshot.occurrences[0].item_id,
        mode=SchedulingOperation.OCCURRENCE_CREATE,
    )
    board = build_scheduling_planning_board(snapshot, items=items, spaces=spaces)
    before_occurrences = SchedulingOccurrence.objects.count()
    before_receipts = SchedulingCommandReceipt.objects.count()
    fresh = build_planning_control(snapshot, board, selection).form
    assert fresh is not None
    data = native_control_data(
        fresh, reason="Start an explicit two-part workshop group"
    )
    data["start_group"] = "new"
    data["group_sequence"] = "1"
    bound = build_planning_control(snapshot, board, selection, data=data).form
    assert isinstance(bound, PlanningRecordForm)
    first = submit_planning_record(scope, bound, authorizer=planning_world.policy)
    assert first is not None
    replay = submit_planning_record(scope, bound, authorizer=planning_world.policy)
    assert replay.replayed
    assert replay.receipt_id == first.receipt_id
    assert SchedulingOccurrence.objects.count() == before_occurrences + 1
    assert SchedulingCommandReceipt.objects.count() == before_receipts + 1
    group_key = bound.occurrence_intent.group_key

    latest = load_scheduling_planning(
        scope,
        candidate_id=selection.candidate_id,
        authorizer=planning_world.policy,
    )
    latest_board = build_scheduling_planning_board(latest, items=items, spaces=spaces)
    second_form = build_planning_control(latest, latest_board, selection).form
    assert second_form.initial["expected_version"] == first.control_version
    second_data = native_control_data(
        second_form, reason="Add the explicit second part"
    )
    second_data["start_group"] = ""
    second_data["group_key"] = str(group_key)
    second_data["group_sequence"] = "2"
    second_bound = build_planning_control(
        latest, latest_board, selection, data=second_data
    ).form
    assert isinstance(second_bound, PlanningRecordForm)
    second = submit_planning_record(
        scope, second_bound, authorizer=planning_world.policy
    )
    assert second is not None
    assert second.object_id != first.object_id
    assert SchedulingOccurrence.objects.count() == before_occurrences + 2
    assert SchedulingCommandReceipt.objects.count() == before_receipts + 2
    revisions = SchedulingOccurrenceRevision.objects.filter(group_key=group_key)
    assert set(revisions.values_list("group_sequence", flat=True)) == {1, 2}
    assert revisions.count() == 2
    assert (
        SchedulingCandidate.objects.get(id=selection.candidate_id).aggregate_version
        == 1
    )
    assert not VenueBooking.objects.exists()


@pytest.fixture
def native_http_world(planning_world, monkeypatch):
    """Compose real owner reads using only the existing isolated-test admission."""
    scope = read_request(planning_world)
    edition = EventEdition.objects.get(id=scope.edition_id)
    CapabilityGrantFactory(
        principal=Account.objects.get(id=scope.actor_id),
        organization=edition.organization,
        edition=edition,
        capability_code="venues.view_workspace",
    )
    monkeypatch.setattr(
        workspace,
        "list_programme_timetable_items",
        partial(
            programme_queries.list_programme_timetable_items,
            authorizer=_TrustedProgrammeAuthorizer(),
        ),
    )
    return planning_world


def native_http_request(world, data=None, *, admitted=True, valid_csrf=True):
    """Exercise the unmounted server adapter with an actual valid CSRF token."""
    factory = RequestFactory()
    seed = factory.get("/synthetic-component/")
    token = get_token(seed)
    if data is None:
        http_request = seed
    else:
        posted = data.copy()
        posted["csrfmiddlewaretoken"] = token if valid_csrf else "invalid"
        http_request = factory.post(
            "/synthetic-component/",
            data=posted.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
        http_request.COOKIES[settings.CSRF_COOKIE_NAME] = seed.META["CSRF_COOKIE"]
    http_request.user = Account.objects.get(id=world.request.actor_id)
    response = scheduling_planning_view(
        http_request,
        organization_id=world.request.organization_id,
        edition_id=world.request.edition_id,
        edition_label="Synthetic private edition",
        **({"authorizer": world.policy} if admitted else {}),
    )
    if hasattr(response, "render"):
        response.render()
    return response


def native_http_selection(world, *, mode="overview", **changes):
    selection = PlanningSelection(
        candidate_id=world.candidate.object_id,
        day_id=world.day.object_id,
        occurrence_id=world.occurrence.object_id,
        mode=mode,
    )
    data = QueryDict(mutable=True)
    for name, value in replace(selection, **changes).hidden_values():
        data[name] = value
    data["action"] = "select"
    return data


def native_http_intent(response, *, action, **values):
    assert response.status_code == 200, response.content.decode()
    form = response.context_data["control"].form
    assert form is not None
    data = QueryDict(mutable=True)
    for name, value in response.context_data["selection_state"]:
        data[name] = value
    for field in form:
        if field.name != "action":
            value = field.value()
            data[field.name] = "" if value is None else str(value)
    data["action"] = action
    data["reason"] = "Explicit synthetic HTTP planning intent"
    for name, value in values.items():
        data[name] = str(value)
    return data


@pytest.mark.parametrize(
    ("action", "model", "selected_field"),
    [
        (SchedulingOperation.CANDIDATE_CREATE, SchedulingCandidate, "candidate_id"),
        (SchedulingOperation.OCCURRENCE_CREATE, SchedulingOccurrence, "occurrence_id"),
        ("create_day", SchedulingServiceDay, "day_id"),
    ],
)
def test_native_http_real_create_reload_and_exact_replay(
    native_http_world, action, model, selected_field
):
    world = native_http_world
    opened = native_http_request(world, native_http_selection(world, mode=action))
    values = {"label": "Second private draft"}
    if action == SchedulingOperation.OCCURRENCE_CREATE:
        values = {"start_group": "new", "group_sequence": "1"}
    elif action == "create_day":
        end = opened.context_data["snapshot"].days[0].window.ends_at
        values = {
            "label": "Evening programme",
            "starts_at": end.isoformat(timespec="minutes"),
            "ends_at": (end + timedelta(hours=1)).isoformat(timespec="minutes"),
            "precision_minutes": "5",
        }
    data = native_http_intent(opened, action=action, **values)
    before_ids = set(model.objects.values_list("id", flat=True))
    before_receipts = SchedulingCommandReceipt.objects.count()
    saved = native_http_request(world, data)
    assert saved.status_code == 200, saved.content.decode()
    added_ids = set(model.objects.values_list("id", flat=True)) - before_ids
    assert len(added_ids) == 1
    assert getattr(saved.context_data["selection"], selected_field) in added_ids
    assert "Command completed" in saved.context_data["status_message"]
    replay = native_http_request(world, data)
    assert replay.status_code == 200, replay.content.decode()
    assert "no duplicate change" in replay.context_data["status_message"]
    assert model.objects.count() == len(before_ids) + 1
    assert SchedulingCommandReceipt.objects.count() == before_receipts + 1
    assert not VenueBooking.objects.exists()
    assert (
        SchedulingCandidate.objects.get(id=world.candidate.object_id).aggregate_version
        == 1
    )
    if action == SchedulingOperation.OCCURRENCE_CREATE:
        revision = SchedulingOccurrenceRevision.objects.get(
            occurrence_id=added_ids.pop()
        )
        assert str(revision.group_key) == data["new_group_key"]
        assert revision.group_sequence == 1


def test_native_http_get_audits_owner_reads_without_choosing_a_draft(native_http_world):
    response = native_http_request(native_http_world)
    assert response.status_code == 200
    assert response.context_data["snapshot"].selected_candidate_id is None
    assert response.context_data["snapshot"].placements == ()
    assert "no-store" in response["Cache-Control"]
    for operation in (
        "scheduling.query.planning",
        "programme.query.timetable_items",
        "venues.query.timetable_spaces",
    ):
        assert AuditEvent.objects.filter(operation=operation, outcome="allow").exists()


def test_native_http_history_comparison_copy_and_restore_keep_exact_sources(
    native_http_world,
):
    world = native_http_world
    first_revision = candidate_revision(world.candidate)
    placed = place(world)
    placed_revision = candidate_revision(placed)
    selection = native_http_selection(
        world,
        mode="history",
        history_id=first_revision.id,
        compare_id=placed_revision.id,
    )
    history = native_http_request(world, selection)
    assert history.status_code == 200, history.content.decode()
    assert history.context_data["manifest"].placements == ()
    assert len(history.context_data["comparison"].placements) == 1
    assert len(history.context_data["changes"]) == 1
    assert history.context_data["changes"][0].status == "added"
    assert b"Immutable revision comparison" in history.content
    assert b"Current labels are not historical item content" in history.content
    assert len(history.context_data["history"].entries) == 2

    selection["ui_mode"] = SchedulingOperation.CANDIDATE_COPY
    copy_form = native_http_request(world, selection)
    copied = native_http_request(
        world,
        native_http_intent(
            copy_form,
            action=SchedulingOperation.CANDIDATE_COPY,
            label="Copy of exact empty source",
        ),
    )
    assert copied.status_code == 200, copied.content.decode()
    copied_id = copied.context_data["selection"].candidate_id
    copied_revision = SchedulingCandidateRevision.objects.get(candidate_id=copied_id)
    assert copied_id != world.candidate.object_id
    assert copied_revision.placement_count == 0
    assert copied_revision.source_revision_id == first_revision.id

    selection["ui_mode"] = SchedulingOperation.CANDIDATE_RESTORE
    restore_form = native_http_request(world, selection)
    restored = native_http_request(
        world,
        native_http_intent(
            restore_form,
            action=SchedulingOperation.CANDIDATE_RESTORE,
            confirm="confirmed",
        ),
    )
    assert restored.status_code == 200, restored.content.decode()
    assert restored.context_data["snapshot"].placements == ()
    versions = SchedulingCandidateRevision.objects.filter(
        candidate_id=world.candidate.object_id
    ).order_by("sequence")
    assert list(versions.values_list("placement_count", flat=True)) == [0, 1, 0]
    assert versions.last().source_revision_id == first_revision.id
    assert versions[1].id == placed_revision.id
    assert not VenueBooking.objects.exists()


def test_native_http_venue_labels_need_independent_real_permission(
    planning_world, monkeypatch
):
    monkeypatch.setattr(
        workspace,
        "list_programme_timetable_items",
        partial(
            programme_queries.list_programme_timetable_items,
            authorizer=_TrustedProgrammeAuthorizer(),
        ),
    )
    response = native_http_request(planning_world)
    assert response.status_code == 403
    assert set(response.context_data) == {"failure_message"}
    assert b"Synthetic private edition" not in response.content
    assert b"First draft" not in response.content
    assert not AuditEvent.objects.filter(
        operation="venues.query.timetable_spaces", outcome="allow"
    ).exists()


@pytest.mark.parametrize("other_tenant", [False, True])
def test_native_http_foreign_candidate_never_enters_rendered_context(
    native_http_world, other_tenant
):
    world = native_http_world
    edition = EventEditionFactory(
        **(
            {}
            if other_tenant
            else {
                "series": EventEdition.objects.get(id=world.request.edition_id).series
            }
        )
    )
    foreign = create_scheduling_candidate(
        replace(
            next_request(world),
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
        label="Other scope private candidate",
        expected_control_version=0,
        authorizer=world.policy,
    )
    before = SchedulingCommandReceipt.objects.count()
    response = native_http_request(
        world,
        native_http_selection(world, candidate_id=foreign.object_id),
    )
    assert response.status_code == 503
    assert set(response.context_data) == {"failure_message"}
    assert b"Other scope private candidate" not in response.content
    assert b"Synthetic private edition" not in response.content
    assert str(foreign.object_id).encode() not in response.content
    assert SchedulingCommandReceipt.objects.count() == before


def test_native_http_invalid_csrf_precedes_all_private_reads(native_http_world):
    before = AuditEvent.objects.count()
    response = native_http_request(
        native_http_world,
        native_http_selection(native_http_world),
        valid_csrf=False,
    )
    assert response.status_code == 403
    assert AuditEvent.objects.count() == before
    assert b"Synthetic private edition" not in response.content
    assert b"First draft" not in response.content


def test_native_http_default_profile_denies_before_parsing_or_owner_reads(
    native_http_world, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Current-profile denial reached private selection or owner reads")

    monkeypatch.setattr(workspace, "list_programme_timetable_items", forbidden)
    monkeypatch.setattr(workspace, "list_venue_timetable_spaces", forbidden)
    monkeypatch.setattr("maru.scheduling.planning_views._selection", forbidden)
    response = native_http_request(
        native_http_world, QueryDict("action=unknown&private=unparsed"), admitted=False
    )
    assert response.status_code == 403
    assert set(response.context_data) == {"failure_message"}
    assert b"Synthetic private edition" not in response.content
    assert b"First draft" not in response.content
    assert AuditEvent.objects.filter(
        operation="scheduling.query.planning", outcome="deny"
    ).exists()


def test_native_http_inspector_does_not_inherit_owner_layer_authority(
    native_http_world,
):
    response = native_http_request(
        native_http_world,
        native_http_selection(native_http_world, layer=PlanningItemLayer.WORKING),
    )
    assert response.status_code == 403
    assert set(response.context_data) == {"failure_message"}
    assert b"Synthetic private edition" not in response.content
    assert b"First draft" not in response.content
    assert not AuditEvent.objects.filter(
        operation="scheduling.query.item_layer_working", outcome="allow"
    ).exists()


def test_native_http_stale_create_retains_exact_pending_input(native_http_world):
    world = native_http_world
    action = SchedulingOperation.CANDIDATE_CREATE
    opened = native_http_request(world, native_http_selection(world, mode=action))
    data = native_http_intent(opened, action=action, label="Still unsaved alternative")
    create_scheduling_candidate(
        next_request(world),
        label="Concurrent alternative",
        expected_control_version=opened.context_data["snapshot"].control_version,
        authorizer=world.policy,
    )
    before = SchedulingCommandReceipt.objects.count()
    response = native_http_request(world, data)
    assert response.status_code == 409, response.content.decode()
    bound = response.context_data["control"].form
    for name in ("label", "reason", "expected_version", "retry_key"):
        assert bound[name].value() == data[name]
    assert "nothing was automatically rebased" in response.context_data["action_error"]
    assert SchedulingCommandReceipt.objects.count() == before
    assert not SchedulingCandidateRevision.objects.filter(
        label="Still unsaved alternative"
    ).exists()


def test_native_http_lost_success_refresh_can_replay_the_committed_intent(
    native_http_world, monkeypatch
):
    world = native_http_world
    action = SchedulingOperation.CANDIDATE_CREATE
    opened = native_http_request(world, native_http_selection(world, mode=action))
    data = native_http_intent(opened, action=action, label="Committed before read loss")
    actual_read = planning_http.load_scheduling_planning
    calls = 0

    def lose_success_refresh(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise DatabaseError("Synthetic lost connection after commit")
        return actual_read(*args, **kwargs)

    monkeypatch.setattr(planning_http, "load_scheduling_planning", lose_success_refresh)
    before = SchedulingCommandReceipt.objects.count()
    response = native_http_request(world, data)
    assert response.status_code == 503
    assert set(response.context_data) == {"failure_message"}
    assert b"Do not assume a submitted change failed" in response.content
    assert b"Synthetic lost connection" not in response.content
    assert SchedulingCommandReceipt.objects.count() == before + 1
    assert (
        SchedulingCandidateRevision.objects.filter(
            label="Committed before read loss"
        ).count()
        == 1
    )
    monkeypatch.setattr(planning_http, "load_scheduling_planning", actual_read)
    replay = native_http_request(world, data)
    assert replay.status_code == 200, replay.content.decode()
    assert "no duplicate change" in replay.context_data["status_message"]
    assert SchedulingCommandReceipt.objects.count() == before + 1


def test_native_http_placement_preview_save_and_retry_share_real_commands(
    native_http_world, host_inspection_admitted, monkeypatch
):
    world = native_http_world
    monkeypatch.setattr(
        evaluation_sources, "profile_allows_conflict_source", lambda *_args: True
    )
    monkeypatch.setattr(
        evaluation_sources,
        "load_programme_scheduling_dependencies",
        partial(
            programme_source.load_programme_scheduling_dependencies,
            authorizer=_TrustedProgrammeAuthorizer(),
        ),
    )
    opened = native_http_request(world, native_http_selection(world, mode="placement"))
    data = native_http_intent(
        opened,
        action="preview_placement",
        space_selection_id=world.placement.space_selection_id,
        capacity_mode=world.placement.capacity_mode,
        expected_attendance=world.placement.expected_attendance,
    )
    for name, value in asdict(world.placement.envelope).items():
        data[name] = value.isoformat(timespec="minutes")
    for host in world.placement.host_presences:
        prefix = f"host_{host.host_id.hex}"
        data[f"{prefix}_required"] = "required"
        data[f"{prefix}_starts_at"] = host.starts_at.isoformat(timespec="minutes")
        data[f"{prefix}_ends_at"] = host.ends_at.isoformat(timespec="minutes")
    before = SchedulingCommandReceipt.objects.count()
    preview = native_http_request(world, data)
    assert preview.status_code == 200, preview.content.decode()
    assert preview.context_data["preview"].complete
    assert "Preview only" in preview.context_data["status_message"]
    assert SchedulingCommandReceipt.objects.count() == before
    assert (
        SchedulingCandidateRevision.objects.filter(
            candidate_id=world.candidate.object_id
        ).count()
        == 1
    )
    data["action"] = "save_placement"
    saved = native_http_request(world, data)
    assert saved.status_code == 200, saved.content.decode()
    assert (
        saved.context_data["snapshot"].placements[0].envelope
        == world.placement.envelope
    )
    assert saved.context_data["selection"].occurrence_id == world.occurrence.object_id
    replay = native_http_request(world, data)
    assert replay.status_code == 200, replay.content.decode()
    assert "no duplicate change" in replay.context_data["status_message"]
    assert SchedulingCommandReceipt.objects.count() == before + 1
    assert (
        SchedulingCandidateRevision.objects.filter(
            candidate_id=world.candidate.object_id
        ).count()
        == 2
    )
    assert not VenueBooking.objects.exists()


def test_native_http_destination_query_uses_fresh_versions_and_does_not_write(
    native_http_world, host_inspection_admitted
):
    world = native_http_world
    page = native_http_request(world, native_http_selection(world))
    assert page.status_code == 200
    assert page.context_data["can_start_placement"]
    assert b"Open placement form" in page.content
    selected = QueryDict(mutable=True)
    for name, value in page.context_data["placement_start_state"]:
        selected[name] = value
    selected["action"] = "select"
    selected["ui_occurrence_id"] = str(world.occurrence.object_id)
    selected["ui_day_id"] = str(world.day.object_id)
    selected["ui_space_id"] = str(world.placement.space_selection_id)
    placed = place(world)
    before = SchedulingCommandReceipt.objects.count()
    response = native_http_request(world, selected)
    assert response.status_code == 200, response.content.decode()
    form = response.context_data["control"].form
    assert form is not None
    assert not form.is_bound
    assert form["expected_version"].value() == placed.version
    assert form["occurrence_id"].value() == world.occurrence.object_id
    assert form["day_id"].value() == world.day.object_id
    assert form["space_selection_id"].value() == world.placement.space_selection_id
    assert SchedulingCommandReceipt.objects.count() == before
    assert not VenueBooking.objects.exists()
