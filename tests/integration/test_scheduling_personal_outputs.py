"""Released own host presence requires both owner purposes and real self policy."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from maru.audit.models import AuditEvent
from maru.authorization import policy
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.participation.models import Participation
from maru.programme.models import ProgrammeHostRelationship
from maru.scheduling import personal_output_queries as composition
from maru.scheduling import personal_output_rendering as formats
from maru.scheduling import personal_release_references as outputs
from maru.scheduling import planning_queries
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.venues.personal_programme_queries import load_personal_host_room_wayfinding
from maru.venues.scheduling_queries import VenueSchedulingSourceUnavailableError
from maru.workforce.assignment_commands import approve_position_assignment
from maru.workforce.availability_commands import save_person_availability
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PositionAssignment,
    ShiftCommitment,
)
from tests.factories import (
    AccountFactory,
    OrganizationMembershipFactory,
    ParticipationFactory,
)
from tests.integration import test_workforce_assignment_commands as assignments
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_scheduling_public_outputs import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import end_copy
from tests.integration.test_scheduling_public_outputs import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    world as world,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_preflight import load as preflight
from tests.integration.test_scheduling_release_queries import approve, publish, withdraw
from tests.support.authority import grant_board_controllers_edition_capability

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def personal_scope(review_scope, monkeypatch):
    original = policy.profile_allows_capability

    def admitted(code, version, capability):
        return capability in {
            "programme.view_host_self",
            "scheduling.view_host_self",
        } or original(code, version, capability)

    monkeypatch.setattr(policy, "profile_allows_capability", admitted)
    monkeypatch.setattr(composition, "profile_allows_capability", admitted)
    return review_scope


def arguments(scope):
    host = ProgrammeHostRelationship.objects.get(
        id=scope.world.placement.host_presences[0].host_id
    )
    return {
        "actor_id": host.account_id,
        "organization_id": scope.request.organization_id,
        "edition_id": scope.request.edition_id,
        "correlation_id": uuid4(),
    }


def test_personal_presence_is_exact_released_work_not_full_envelope_or_public_copy(
    personal_scope,
):
    published = publish(personal_scope, approve(personal_scope))
    inputs = arguments(personal_scope)
    with CaptureQueriesContext(connection) as captured:
        result = outputs.load_personal_host_release_reference(**inputs)
    assert result.state == "available"
    assert result.release_id == published.object_id
    assert result.pointer_version == 1
    assert result.published_at is not None
    assert len(result.purposes) == len(result.presences) == 1
    (presence,) = result.presences
    expected = personal_scope.world.placement.host_presences[0]
    assert presence.host_id == expected.host_id
    assert presence.starts_at == expected.starts_at
    assert presence.ends_at == expected.ends_at
    assert presence.envelope == personal_scope.world.placement.envelope
    assert presence.starts_at > presence.envelope.setup_starts_at
    assert result.purposes[0].title == "Visible session"
    assert "Synthetic public opening" not in repr(result)
    statements = "\n".join(row["sql"] for row in captured)
    for excluded in (
        'FROM "participation_',
        'FROM "registration_',
        'FROM "workforce_shift',
        'FROM "programme_programmehostavailabilitywindow"',
        'FROM "programme_programmepublicrendition"',
    ):
        assert excluded not in statements
    assert AuditEvent.objects.filter(
        operation="scheduling.query.personal_host_release",
        outcome="allow",
        principal_id=inputs["actor_id"],
        capability_code="scheduling.view_host_self",
    ).exists()


def test_person_without_host_purpose_learns_no_release_existence(personal_scope):
    publish(personal_scope, approve(personal_scope))
    inputs = arguments(personal_scope) | {"actor_id": AccountFactory().id}
    with patch.object(outputs, "_manifest", side_effect=AssertionError("no lookup")):
        result = outputs.load_personal_host_release_reference(**inputs)
    assert result.state is None
    assert result.pointer_version is None
    assert result.release_id is None
    assert result.purposes == result.presences == ()


def test_confirmed_host_before_publication_has_truthful_absent_state(personal_scope):
    result = outputs.load_personal_host_release_reference(**arguments(personal_scope))
    assert result.state == "absent"
    assert result.pointer_version == 0
    assert result.purposes[0].state == "confirmed"
    assert result.presences == ()


@pytest.mark.parametrize("operation", ["copy", "release"])
def test_withdrawal_never_advertises_old_host_presence(personal_scope, operation):
    published = publish(personal_scope, approve(personal_scope))
    inputs = arguments(personal_scope)
    before = outputs.load_personal_host_release_reference(**inputs)
    if operation == "copy":
        manifest = outputs._manifest(
            organization_id=inputs["organization_id"],
            edition_id=inputs["edition_id"],
            release_id=None,
        )
        end_copy(personal_scope, manifest.selections[0].public_rendition_id)
    else:
        withdraw(personal_scope, published)
    after = outputs.load_personal_host_release_reference(**inputs)
    assert before.presences
    assert after.presences == ()
    assert after.purposes == before.purposes
    assert after.state == ("invalidated" if operation == "copy" else "withdrawn")


def test_profile_cannot_use_planner_permission_as_personal_access(
    review_scope,
):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        outputs.load_personal_host_release_reference(**arguments(review_scope))


def test_foreign_personal_scope_fails_before_release_disclosure(personal_scope):
    with pytest.raises(SchedulingAuthorizationDeniedError):
        outputs.load_personal_host_release_reference(
            **(arguments(personal_scope) | {"organization_id": uuid4()})
        )


def test_personal_composition_gets_own_room_and_keeps_empty_work_explicit(
    personal_scope,
):
    publish(personal_scope, approve(personal_scope))
    result = composition.load_personal_timetable(**arguments(personal_scope))
    assert result.hosting is not None
    assert result.hosting.reference.presences
    (room,) = result.hosting.rooms
    assert room.space_id == result.hosting.reference.presences[0].space_id
    assert room.room_name == "Main Stage"
    assert room.venue_name == "Convention Hotel"
    assert result.shifts == ()


def test_personal_room_source_cannot_use_caller_selected_release(personal_scope):
    publish(personal_scope, approve(personal_scope))
    with pytest.raises(VenueSchedulingSourceUnavailableError):
        load_personal_host_room_wayfinding(
            **arguments(personal_scope), expected_release_id=uuid4()
        )


def test_changed_manifest_withholds_materialized_personal_intervals(personal_scope):
    publish(personal_scope, approve(personal_scope))
    inputs = arguments(personal_scope)
    original = outputs._manifest
    count = 0

    def changing(**kwargs):
        nonlocal count
        count += 1
        result = original(**kwargs)
        return result if count == 1 else replace(result, pointer_version=2)

    with (
        patch.object(outputs, "_manifest", side_effect=changing),
        pytest.raises(SchedulingUnavailableError),
    ):
        outputs.load_personal_host_release_reference(**inputs)


def test_changed_owner_purpose_withholds_materialized_personal_intervals(
    personal_scope,
):
    publish(personal_scope, approve(personal_scope))
    inputs = arguments(personal_scope)
    original = outputs.load_personal_host_purposes
    count = 0

    def changing(**kwargs):
        nonlocal count
        count += 1
        result = original(**kwargs)
        return (
            result
            if count == 1
            else (replace(result[0], version=result[0].version + 1),)
        )

    with (
        patch.object(outputs, "load_personal_host_purposes", side_effect=changing),
        pytest.raises(SchedulingUnavailableError),
    ):
        outputs.load_personal_host_release_reference(**inputs)


def test_sensitive_scheduling_audit_failure_releases_no_personal_result(personal_scope):
    publish(personal_scope, approve(personal_scope))
    with (
        patch.object(
            planning_queries, "_audit", side_effect=RuntimeError("audit unavailable")
        ),
        pytest.raises(RuntimeError, match="audit unavailable"),
    ):
        outputs.load_personal_host_release_reference(**arguments(personal_scope))


def _accepted_independent_work(scope):
    person = Account.objects.get(id=arguments(scope)["actor_id"])
    edition = EventEdition.objects.get(id=scope.request.edition_id)
    # This fixture keeps the current full profile's real assignment requirements.
    # Workforce-only non-Participation is proved in test_personal_timetable_composition.
    OrganizationMembershipFactory(organization=edition.organization, account=person)
    ParticipationFactory(
        organization=edition.organization, edition=edition, account=person
    )
    with patch.object(assignments, "EventEditionFactory", return_value=edition):
        work = assignments._assignment_world()
    for capability in ("workforce.manage_shifts", "workforce.view_shifts"):
        grant_board_controllers_edition_capability(edition, capability)
    proposed = assignments._propose(work, candidate=person)
    approved = approve_position_assignment(
        actor=work.approver,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        assignment_id=proposed.assignment_id,
        expected_version=1,
        reason="Independent synthetic personal work",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    start = scope.world.placement.envelope.teardown_ends_at + timedelta(hours=2)
    end = start + timedelta(hours=4)
    save_person_availability(
        actor=person,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        expected_version=0,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=shifts._windows(starts_at=start.isoformat(), ends_at=end.isoformat()),
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    world = SimpleNamespace(
        planner=work.proposer,
        reviewer=work.approver,
        person=person,
        edition=edition,
        position=work.position,
        assignment=PositionAssignment.objects.get(id=approved.assignment_id),
    )
    demand = shifts._create_demand(
        world, starts_at=start.isoformat(), ends_at=end.isoformat()
    )
    shifts._open(world, demand)
    claimed = shifts._claim(world, demand)
    commitment = ShiftCommitment.objects.get(id=claimed.commitment_id)
    shifts._confirm(world, commitment)
    commitment.refresh_from_db()
    return commitment


def test_native_same_person_composition_preserves_work_after_release_withdrawal(
    personal_scope,
):
    commitment = _accepted_independent_work(personal_scope)
    personal_scope.release_selection = replace(
        personal_scope.release_selection,
        source_snapshot_digest=preflight(personal_scope).snapshot_digest,
    )
    released = publish(personal_scope, approve(personal_scope))
    inputs = arguments(personal_scope)
    prior_participation_count = Participation.objects.count()
    with CaptureQueriesContext(connection) as captured:
        before = composition.load_personal_timetable(**inputs)
    assert before.hosting.reference.presences
    assert len(before.shifts) == 1
    assert before.shifts[0].commitment_id == commitment.id
    assert before.shifts[0].starts_at == commitment.starts_at
    assert before.shifts[0].ends_at == commitment.ends_at
    assert b'"audience":"exact_person"' in formats.render_personal_timetable_json(
        before
    )
    assert b"CLASS:PRIVATE" in formats.render_personal_timetable_calendar(before)
    assert not any('FROM "participation_' in row["sql"] for row in captured)
    withdraw(personal_scope, released)
    after = composition.load_personal_timetable(**inputs)
    assert after.hosting.reference.state == "withdrawn"
    assert after.hosting.reference.presences == after.hosting.rooms == ()
    assert after.shifts == before.shifts
    assert b'"state":"withdrawn"' in formats.render_personal_timetable_json(after)
    with pytest.raises(formats.PersonalCalendarUnavailableError):
        formats.render_personal_timetable_calendar(after)
    assert Participation.objects.count() == prior_participation_count


@pytest.mark.parametrize("output_format", ["html", "print", "json", "calendar"])
def test_real_private_http_rechecks_owner_release_and_other_person(
    personal_scope, settings, client, output_format
):
    settings.ROOT_URLCONF = "tests.support.programme_output_urls"
    _accepted_independent_work(personal_scope)
    personal_scope.release_selection = replace(
        personal_scope.release_selection,
        source_snapshot_digest=preflight(personal_scope).snapshot_digest,
    )
    released = publish(personal_scope, approve(personal_scope))
    inputs = arguments(personal_scope)
    owner = Account.objects.get(id=inputs["actor_id"])
    edition = EventEdition.objects.get(id=inputs["edition_id"])
    url = (
        f"/my/{inputs['organization_id']}/{inputs['edition_id']}/timetable/"
        f"?format={output_format}"
    )
    client.force_login(owner)
    before = client.get(url)
    assert before.status_code == 200
    assert "private" in before["Cache-Control"]
    assert "no-store" in before["Cache-Control"]
    assert str(released.object_id).encode() in before.content
    if output_format in {"html", "print"}:
        assert edition.name.encode() in before.content
        assert b"Approved required host presence" in before.content
        assert b"Confirmed work" in before.content
        assert before.content.count(b"<h1>") == 1
    else:
        assert b"shift-" in before.content or b'"shifts":[' in before.content
    client.force_login(AccountFactory(email_verified_at=owner.email_verified_at))
    other = client.get(url)
    assert other.status_code == 200
    assert str(released.object_id).encode() not in other.content
    assert edition.name.encode() not in other.content
    assert b"Approved required host presence" not in other.content
    assert b"Confirmed work" not in other.content
    client.force_login(owner)
    withdraw(personal_scope, released)
    after = client.get(url)
    assert after.status_code == (409 if output_format == "calendar" else 200)
    assert b"Approved required host presence" not in after.content
    if output_format in {"html", "print"}:
        assert b"Confirmed work" in after.content
    assert "no-store" in after["Cache-Control"]
