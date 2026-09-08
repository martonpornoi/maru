"""Real fresh conflict reports, calendar minimization and exact warning reasons."""

import json
from dataclasses import asdict, replace
from datetime import timedelta
from functools import partial
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import DatabaseError

from maru.audit.models import AuditEvent
from maru.authorization.policy import PolicyDecision
from maru.effects.models import DomainEvent, OutboxMessage
from maru.programme import scheduling_queries as programme_source
from maru.programme.host_commands import replace_programme_host_availability
from maru.programme.host_inputs import (
    ProgrammeHostAvailabilityInput,
    ProgrammeHostAvailabilityPeriod,
)
from maru.programme.models import ProgrammeHostRelationship
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.scheduling import authorization as scheduling_authorization
from maru.scheduling import (
    command_support,
    evaluation_sources,
    planning_actions,
    planning_preview,
    planning_queries,
)
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.candidate_commands import archive_scheduling_candidate
from maru.scheduling.command_support import (
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.evaluation_commands import (
    acknowledge_scheduling_warning,
    evaluate_scheduling_candidate,
)
from maru.scheduling.inputs import SchedulingOccurrenceInput
from maru.scheduling.models import (
    SchedulingCandidate,
    SchedulingConflict,
    SchedulingEditionControl,
    SchedulingEvaluation,
    SchedulingOccurrence,
    SchedulingWarningAcknowledgement,
)
from maru.scheduling.occurrence_commands import create_scheduling_occurrence
from maru.scheduling.planning_forms import PlanningPlacementForm, PlanningServiceDayForm
from maru.scheduling.planning_preview import preview_scheduling_candidate
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.venues import scheduling_queries as venue_source
from maru.venues.models import VenueBooking
from tests.integration.test_programme_commands import _TrustedProgrammeAuthorizer
from tests.integration.test_scheduling_days import TrustedSchedulingPolicy
from tests.integration.test_scheduling_placements import (
    START,
    moved,
    next_request,
    place,
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_scheduling_reservations import admit_reservations, reserve

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def admitted(world, monkeypatch):
    admit_reservations(world, monkeypatch)
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


def evaluate(world, placed, *, request=None):
    result = evaluate_scheduling_candidate(
        request or next_request(world),
        candidate_id=world.candidate.object_id,
        expected_version=placed.version,
        authorizer=world.policy,
    )
    return result, SchedulingEvaluation.objects.get(id=result.object_id)


def availability(world, *, state="shared", preference=True):
    host = ProgrammeHostRelationship.objects.select_related("item").get(
        id=world.placement.host_presences[0].host_id
    )
    periods = (
        (
            ProgrammeHostAvailabilityPeriod(START, START + timedelta(hours=1)),
            ProgrammeHostAvailabilityPeriod(
                START + timedelta(hours=1), START + timedelta(hours=2), "preferred"
            ),
        )
        if preference
        else (ProgrammeHostAvailabilityPeriod(START, START + timedelta(hours=2)),)
    )
    return replace_programme_host_availability(
        actor_id=host.account_id,
        organization_id=host.organization_id,
        edition_id=host.edition_id,
        item_id=host.item_id,
        availability=ProgrammeHostAvailabilityInput(
            host.id,
            state,
            () if state == "withdrawn" else periods,
            host.item.aggregate_version,
            host.version,
        ),
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
        authorizer=_TrustedProgrammeAuthorizer(),
    )


def test_unpinned_scheduling_source_cannot_record_a_passing_report(world):
    placed = place(world)
    with pytest.raises(SchedulingUnavailableError):
        evaluate(world, placed)
    assert not SchedulingEvaluation.objects.exists()


def test_complete_report_records_versions_without_personal_calendar_or_keys(
    world, admitted
):
    placed = place(world)
    request = next_request(world)
    result, report = evaluate(world, placed, request=request)
    assert report.is_complete
    assert report.conflict_count == 0
    assert report.conflicts.count() == 0
    serialized = json.dumps(report.source_evidence)
    assert str(world.placement.host_presences[0].host_id) in serialized
    for prohibited in (
        "periods",
        "starts_at",
        "ends_at",
        "person_key",
        "email",
        "Synthetic restriction",
        "Programme reservation",
    ):
        assert prohibited not in serialized
    assert len(report.source_evidence) == 3
    replay, same = evaluate(world, placed, request=request)
    assert replay.replayed
    assert same.id == result.object_id
    assert SchedulingEvaluation.objects.count() == 1


def test_blocker_is_complete_but_cannot_be_acknowledged(world, admitted):
    placed = place(world, intent=replace(world.placement, expected_attendance=9_000))
    _, report = evaluate(world, placed)
    assert report.is_complete
    blocker = report.conflicts.get(code="venue_capacity")
    assert blocker.severity == "blocker"
    with pytest.raises(SchedulingUnavailableError):
        acknowledge_scheduling_warning(
            next_request(world), conflict_id=blocker.id, authorizer=world.policy
        )
    assert not SchedulingWarningAcknowledgement.objects.exists()


def test_warning_acknowledgement_is_exact_reasoned_replayable_and_not_approval(
    world, admitted
):
    availability(world)
    placed = place(world)
    _, report = evaluate(world, placed)
    warning = report.conflicts.get(code="host_outside_preference")
    request = replace(
        next_request(world),
        reason="Person confirmed this available non-preferred slot is acceptable",
    )
    accepted = acknowledge_scheduling_warning(
        request, conflict_id=warning.id, authorizer=world.policy
    )
    acknowledgement = SchedulingWarningAcknowledgement.objects.get(
        id=accepted.object_id
    )
    assert acknowledgement.reason == request.reason
    assert acknowledgement.conflict_id == warning.id
    replay = acknowledge_scheduling_warning(
        request, conflict_id=warning.id, authorizer=world.policy
    )
    assert replay.replayed
    assert SchedulingWarningAcknowledgement.objects.count() == 1
    report.refresh_from_db()
    assert report.conflict_count == 1


def test_host_withdrawal_invalidates_old_warning_without_retaining_periods(
    world, admitted
):
    availability(world)
    placed = place(world)
    _, previous = evaluate(world, placed)
    warning = previous.conflicts.get(code="host_outside_preference")
    availability(world, state="withdrawn")
    with pytest.raises(SchedulingVersionConflictError):
        acknowledge_scheduling_warning(
            next_request(world), conflict_id=warning.id, authorizer=world.policy
        )
    _, current = evaluate(world, placed)
    assert current.dependency_digest != previous.dependency_digest
    assert not SchedulingWarningAcknowledgement.objects.exists()
    assert "not_shared" in json.dumps(current.source_evidence)
    assert "starts_at" not in json.dumps(previous.source_evidence)


def test_candidate_edit_makes_the_old_warning_ineligible(world, admitted):
    availability(world)
    placed = place(world)
    _, report = evaluate(world, placed)
    warning = report.conflicts.get(code="host_outside_preference")
    place(world, intent=moved(world), version=placed.version)
    with pytest.raises(SchedulingUnavailableError):
        acknowledge_scheduling_warning(
            next_request(world), conflict_id=warning.id, authorizer=world.policy
        )


@pytest.mark.parametrize("owner", ["programme", "venues"])
def test_missing_owner_evidence_is_unavailable_not_a_passing_check(
    world, admitted, monkeypatch, owner
):
    placed = place(world)

    def unavailable(**_kwargs):
        if owner == "programme":
            raise ProgrammeQueryUnavailableError
        raise venue_source.VenueSchedulingSourceUnavailableError

    source_name = "programme" if owner == "programme" else "venue"
    monkeypatch.setattr(
        evaluation_sources, f"load_{source_name}_scheduling_dependencies", unavailable
    )
    _, report = evaluate(world, placed)
    assert not report.is_complete
    assert report.conflicts.filter(severity="unavailable").exists()


def test_exact_physical_binding_does_not_conflict_with_itself(world, admitted):
    placed = place(world)
    _, reserved = reserve(world, placed=placed)
    _, report = evaluate(world, placed)
    assert report.is_complete
    assert report.conflict_count == 0
    assert str(reserved.target_booking_id) in json.dumps(report.source_evidence)
    changed = place(world, intent=moved(world), version=placed.version)
    _, stale = evaluate(world, changed)
    assert stale.conflicts.filter(code="reserved_room_overlap").exists()


def test_late_parent_failure_leaves_no_partial_report_or_findings(
    world, admitted, monkeypatch
):
    availability(world)
    placed = place(world)

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic evaluation evidence failure")

    monkeypatch.setattr(command_support, "publish_domain_event", fail)
    with pytest.raises(RuntimeError, match="synthetic evaluation"):
        evaluate(world, placed)
    assert not SchedulingEvaluation.objects.exists()
    assert not SchedulingConflict.objects.exists()


def preview_request(world):
    return SchedulingReadRequest(
        world.request.actor_id,
        world.request.organization_id,
        world.request.edition_id,
        uuid4(),
    )


def preview(world, *, version=1, intent=None, policy=None, request=None):
    return preview_scheduling_candidate(
        request or preview_request(world),
        candidate_id=world.candidate.object_id,
        expected_version=version,
        placement=intent,
        authorizer=policy or world.policy,
    )


def domain_state():
    # Preview may append read audits only: inspect every owned Scheduling
    # relation plus the cross-owner booking/event/outbox side effects.
    return (
        tuple(
            (model._meta.label, model.objects.count())
            for model in apps.get_app_config("scheduling").get_models()
        ),
        tuple(SchedulingCandidate.objects.values_list("id", "aggregate_version")),
        tuple(SchedulingEditionControl.objects.values_list("id", "aggregate_version")),
        VenueBooking.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )


def test_unsaved_preview_matches_saved_evaluator_without_domain_writes(world, admitted):
    intent = replace(world.placement, expected_attendance=9_000)
    before = domain_state()
    request = preview_request(world)
    result = preview(world, intent=intent, request=request)
    assert domain_state() == before
    assert result.complete
    assert all(source.available for source in result.sources)
    assert result.candidate_version == 1
    assert result.proposed_occurrence_id == world.occurrence.object_id
    assert result.not_evaluated == (
        "staffing",
        "rest",
        "accessibility_fit",
        "release_readiness",
    )
    assert {finding.code for finding in result.findings} == {"venue_capacity"}
    assert all(finding.severity == "blocker" for finding in result.findings)
    assert (
        AuditEvent.objects.filter(
            correlation_id=request.correlation_id,
            operation="scheduling.query.candidate_preview",
            outcome="allow",
        ).count()
        == 1
    )
    serialized = json.dumps(asdict(result), default=str)
    for prohibited in (
        "periods",
        "starts_at",
        "person_key",
        "email",
        "fingerprint",
        "digest",
        str(world.placement.host_presences[0].host_id),
        "Synthetic restriction",
    ):
        assert prohibited not in serialized
    placed = place(world, intent=intent)
    _, saved = evaluate(world, placed)
    assert set(saved.conflicts.values_list("code", "severity", "occurrence_id")) == {
        (finding.code, finding.severity, finding.occurrence_id)
        for finding in result.findings
    }


def test_current_preview_and_repeated_unsaved_move_do_not_self_overlap(world, admitted):
    placed = place(world)
    before = domain_state()
    current = preview(world, version=placed.version)
    assert current.proposed_occurrence_id is None
    assert current.complete
    assert not current.findings
    for _ in range(2):
        changed = preview(world, version=placed.version, intent=moved(world))
        assert changed.complete
        assert not changed.findings
    assert domain_state() == before


def test_unsaved_addition_is_compared_with_every_retained_occurrence(world, admitted):
    placed = place(world)
    original = SchedulingOccurrence.objects.get(id=world.occurrence.object_id)
    second = create_scheduling_occurrence(
        next_request(world),
        occurrence=SchedulingOccurrenceInput(original.programme_item_id),
        expected_control_version=4,
        authorizer=world.policy,
    )
    before = domain_state()
    result = preview(
        world,
        version=placed.version,
        intent=replace(world.placement, occurrence_id=second.object_id),
    )
    assert result.complete
    assert {finding.code for finding in result.findings} == {
        "candidate_room_overlap",
        "host_overlap",
    }
    assert all(
        {finding.occurrence_id, finding.other_occurrence_id}
        == {world.occurrence.object_id, second.object_id}
        for finding in result.findings
    )
    assert domain_state() == before


def test_archived_candidate_cannot_be_presented_as_an_editable_preview(world, admitted):
    archived = archive_scheduling_candidate(
        next_request(world),
        candidate_id=world.candidate.object_id,
        expected_version=1,
        authorizer=world.policy,
    )
    with pytest.raises(SchedulingLifecycleConflictError):
        preview(world, version=archived.version, intent=world.placement)


def test_preview_never_treats_a_new_draft_as_the_existing_physical_hold(
    world, admitted
):
    placed = place(world)
    _, reserved = reserve(world, placed=placed)
    before = domain_state()
    current = preview(world, version=placed.version)
    assert not current.findings
    for intent in (world.placement, moved(world)):
        changed = preview(world, version=placed.version, intent=intent)
        assert "reserved_room_overlap" in {finding.code for finding in changed.findings}
    assert VenueBooking.objects.filter(id=reserved.target_booking_id).exists()
    assert domain_state() == before


def test_current_profile_denies_preview_even_when_owners_are_admitted(world, admitted):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        preview_scheduling_candidate(
            preview_request(world),
            candidate_id=world.candidate.object_id,
            expected_version=1,
            placement=world.placement,
        )


@pytest.mark.parametrize("removed", sorted(planning_preview.PREVIEW_FIELDS))
def test_preview_fields_authorize_before_sources_or_input_normalization(
    world, admitted, monkeypatch, removed
):
    class PartialPolicy:
        def authorize(self, **kwargs):
            return PolicyDecision(
                allowed=True,
                fields=kwargs["requested_fields"] - {removed},
                obligations=frozenset(),
                reason_code="synthetic_missing_preview_field",
            )

    def forbidden(*args, **kwargs):
        pytest.fail("Denied conflict read reached dependency resolution")

    monkeypatch.setattr(planning_preview, "_require_source_adoption", forbidden)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        preview(world, intent=object(), policy=PartialPolicy())


def test_preview_final_revocation_rolls_back_all_owner_success_audits(world, admitted):
    request = preview_request(world)
    before = domain_state()
    with pytest.raises(SchedulingAuthorizationDeniedError):
        preview(
            world,
            intent=world.placement,
            request=request,
            policy=TrustedSchedulingPolicy(deny_at=2),
        )
    assert not AuditEvent.objects.filter(
        correlation_id=request.correlation_id, outcome="allow"
    ).exists()
    assert AuditEvent.objects.filter(
        correlation_id=request.correlation_id, outcome="deny"
    ).exists()
    assert domain_state() == before


def test_preview_required_audit_failure_withholds_result_and_rolls_back(
    world, admitted, monkeypatch
):
    request = preview_request(world)
    before = domain_state()

    def fail(*args, **kwargs):
        raise DatabaseError("Synthetic preview audit failure")

    monkeypatch.setattr(planning_queries, "append_audit", fail)
    with pytest.raises(SchedulingUnavailableError):
        preview(world, intent=world.placement, request=request)
    assert not AuditEvent.objects.filter(correlation_id=request.correlation_id).exists()
    assert domain_state() == before


@pytest.mark.parametrize("owner", ["programme", "venue"])
def test_preview_source_failure_remains_unavailable_not_passing(
    world, admitted, monkeypatch, owner
):
    def fail(**kwargs):
        if owner == "programme":
            raise ProgrammeQueryUnavailableError
        raise venue_source.VenueSchedulingSourceDeniedError

    monkeypatch.setattr(
        evaluation_sources, f"load_{owner}_scheduling_dependencies", fail
    )
    result = preview(world, intent=world.placement)
    assert not result.complete
    assert any(not source.available for source in result.sources)
    assert any(finding.severity == "unavailable" for finding in result.findings)
    assert not SchedulingEvaluation.objects.exists()


def test_preview_unpinned_scheduling_source_is_unavailable(world):
    with pytest.raises(SchedulingUnavailableError):
        preview(world, intent=world.placement)


def test_preview_stale_form_is_not_rebased_or_written(world, admitted):
    place(world)
    before = domain_state()
    with pytest.raises(SchedulingVersionConflictError):
        preview(world, intent=world.placement)
    assert domain_state() == before


@pytest.mark.parametrize(
    "field", ["day_id", "occurrence_id", "day_version", "occurrence_version"]
)
def test_preview_stale_or_foreign_structure_is_not_treated_as_current(
    world, admitted, field
):
    intent = replace(
        world.placement, **{field: 99 if field.endswith("version") else uuid4()}
    )
    with pytest.raises(SchedulingUnavailableError):
        preview(world, intent=intent)
    assert not SchedulingEvaluation.objects.exists()


@pytest.mark.parametrize("field", ["organization_id", "edition_id", "actor_id"])
def test_preview_foreign_scope_is_non_disclosing(world, admitted, field):
    request = replace(preview_request(world), **{field: uuid4()})
    with pytest.raises(SchedulingAuthorizationDeniedError):
        preview(world, intent=world.placement, request=request)


def test_preview_overflow_does_not_silently_truncate_placements(
    world, admitted, monkeypatch
):
    monkeypatch.setattr(planning_preview, "MAX_OCCURRENCES", 0)
    with pytest.raises(SchedulingLimitError):
        preview(world, intent=world.placement)


def test_preview_locks_complete_programme_people_before_final_actor(
    world, admitted, monkeypatch
):
    events = []
    resolve_people = programme_source.resolve_active_verified_person_references
    resolve_actor = scheduling_authorization.resolve_active_verified_person_reference

    def people(**kwargs):
        if kwargs.get("lock"):
            events.append(("people", kwargs["account_ids"]))
        return resolve_people(**kwargs)

    def actor(**kwargs):
        if kwargs.get("lock"):
            events.append(("actor", kwargs["account_id"]))
        return resolve_actor(**kwargs)

    monkeypatch.setattr(
        programme_source, "resolve_active_verified_person_references", people
    )
    monkeypatch.setattr(
        scheduling_authorization, "resolve_active_verified_person_reference", actor
    )
    preview(world, intent=world.placement)
    assert [event[0] for event in events] == ["people", "actor"]
    assert world.request.actor_id in events[0][1]
    assert len(events[0][1]) == 2


def placement_submission(world, *, action="preview_placement", key=None, version=1):
    intent = world.placement
    host = intent.host_presences[0]
    data = {
        "action": action,
        "retry_key": str(key or uuid4()),
        "candidate_id": str(world.candidate.object_id),
        "expected_version": str(version),
        "occurrence_id": str(intent.occurrence_id),
        "occurrence_version": str(intent.occurrence_version),
        "day_id": str(intent.day_id),
        "day_version": str(intent.day_version),
        "space_selection_id": str(intent.space_selection_id),
        "capacity_mode": intent.capacity_mode,
        "expected_attendance": str(intent.expected_attendance),
        "reason": "Explicit native-form placement"
        if action == "save_placement"
        else "",
        **{
            name: getattr(intent.envelope, name).isoformat(timespec="minutes")
            for name in (
                "setup_starts_at",
                "effective_starts_at",
                "effective_ends_at",
                "teardown_ends_at",
            )
        },
        f"host_{host.host_id.hex}_required": "required",
        f"host_{host.host_id.hex}_starts_at": host.starts_at.isoformat(
            timespec="minutes"
        ),
        f"host_{host.host_id.hex}_ends_at": host.ends_at.isoformat(timespec="minutes"),
    }
    return PlanningPlacementForm(
        data,
        zone_name="Europe/Budapest",
        occurrences=((intent.occurrence_id, "Opening panel"),),
        days=((intent.day_id, "Friday"),),
        spaces=((intent.space_selection_id, "Main Stage"),),
        hosts=((host.host_id, "Related host"),),
    )


def test_native_form_preview_save_and_exact_retry_use_real_owner_commands(
    world, admitted
):
    before = domain_state()
    form = placement_submission(world)
    result = planning_actions.submit_planning_placement(
        preview_request(world), form, authorizer=world.policy
    )
    assert result.complete
    assert not result.findings
    assert domain_state() == before
    assert form.placement_intent == world.placement
    saved_form = placement_submission(world, action="save_placement")
    saved = planning_actions.submit_planning_placement(
        preview_request(world), saved_form, authorizer=world.policy
    )
    assert saved.object_id == world.candidate.object_id
    assert saved.version == 2
    assert not saved.replayed
    after_save = domain_state()
    replay = planning_actions.submit_planning_placement(
        preview_request(world), saved_form, authorizer=world.policy
    )
    assert replay.replayed
    assert replay.receipt_id == saved.receipt_id
    assert domain_state() == after_save
    assert not VenueBooking.objects.exists()


def test_native_stale_submission_retains_input_and_creates_no_partial_state(
    world, admitted
):
    form = placement_submission(world, action="save_placement")
    place(world)
    before = domain_state()
    original = dict(form.data)
    with pytest.raises(SchedulingVersionConflictError):
        planning_actions.submit_planning_placement(
            preview_request(world), form, authorizer=world.policy
        )
    assert dict(form.data) == original
    assert form.data["expected_version"] == "1"
    assert domain_state() == before


def test_native_day_create_and_revision_reuse_real_day_commands(world):
    data = {
        "action": "create_day",
        "retry_key": str(uuid4()),
        "reason": "Add the second service day",
        "expected_version": "3",
        "label": "Saturday",
        "precision_minutes": "5",
        "starts_at": (START + timedelta(days=1)).isoformat(timespec="minutes"),
        "ends_at": (START + timedelta(days=1, hours=12)).isoformat(timespec="minutes"),
    }
    form = PlanningServiceDayForm(data, zone_name="Europe/Budapest")
    created = planning_actions.submit_planning_service_day(
        preview_request(world), form, authorizer=world.policy
    )
    assert created.version == 1
    revised = PlanningServiceDayForm(
        {
            **data,
            "action": "revise_day",
            "retry_key": str(uuid4()),
            "expected_version": "1",
            "day_id": str(created.object_id),
            "label": "Saturday operations",
        },
        zone_name="Europe/Budapest",
    )
    changed = planning_actions.submit_planning_service_day(
        preview_request(world), revised, authorizer=world.policy
    )
    assert changed.object_id == created.object_id
    assert changed.version == 2
