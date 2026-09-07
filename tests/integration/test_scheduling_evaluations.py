"""Real fresh conflict reports, calendar minimization and exact warning reasons."""

import json
from dataclasses import replace
from datetime import timedelta
from functools import partial
from uuid import uuid4

import pytest

from maru.programme import scheduling_queries as programme_source
from maru.programme.host_commands import replace_programme_host_availability
from maru.programme.host_inputs import (
    ProgrammeHostAvailabilityInput,
    ProgrammeHostAvailabilityPeriod,
)
from maru.programme.models import ProgrammeHostRelationship
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.scheduling import command_support, evaluation_sources
from maru.scheduling.command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.evaluation_commands import (
    acknowledge_scheduling_warning,
    evaluate_scheduling_candidate,
)
from maru.scheduling.models import (
    SchedulingConflict,
    SchedulingEvaluation,
    SchedulingWarningAcknowledgement,
)
from maru.venues import scheduling_queries as venue_source
from tests.integration.test_programme_commands import _TrustedProgrammeAuthorizer
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
