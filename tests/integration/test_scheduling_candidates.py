"""Stable occurrence and independent candidate-history transaction evidence."""

from dataclasses import asdict, replace
from functools import partial
from uuid import uuid4

import pytest
from django.db import DatabaseError

import maru.effects.services as effect_services
from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.events.models import EventEdition
from maru.events.services import transition_edition
from maru.programme import scheduling_queries as programme_source
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import candidate_commands, occurrence_commands
from maru.scheduling import planning_queries as queries
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
from maru.scheduling.planning_queries import (
    SchedulingReadRequest,
    list_scheduling_candidate_history,
    load_scheduling_historical_manifest,
    load_scheduling_planning,
)
from maru.venues.models import VenueBooking
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
