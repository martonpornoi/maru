"""Fictional Workforce-only owner states built through retained domain commands."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from maru.workforce.assignment_commands import (
    approve_position_assignment,
    propose_position_assignment,
)
from maru.workforce.availability_commands import save_person_availability
from maru.workforce.availability_inputs import AvailabilityWindowInput
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PositionAssignment,
    ShiftCommitment,
    ShiftDemand,
)
from maru.workforce.shift_commands import (
    claim_shift,
    confirm_shift_commitment,
    create_shift_demand,
    open_shift_demand,
)
from tests.factories import AccountFactory, OrganizationMembershipFactory
from tests.integration.test_workforce_assignment_commands import _assignment_world
from tests.support.authority import grant_board_controllers_edition_capability

ANCHOR = datetime(2030, 8, 1, 6, tzinfo=UTC)


@dataclass(frozen=True)
class HomeWorld:
    """Separate synthetic organizers and one person, without attendee state."""

    base: object
    person: object

    @property
    def edition(self):
        return self.base.edition

    @property
    def manager(self):
        return self.base.proposer

    @property
    def reviewer(self):
        return self.base.approver

    @property
    def position(self):
        return self.base.position


def create_home_world():
    base = _assignment_world(headcount=4, adoption_profile_code="workforce_only")
    for code in [
        "events.view_basic",
        "workforce.manage_structure",
        "workforce.view_availability",
        "workforce.view_shifts",
        "workforce.manage_shifts",
    ]:
        grant_board_controllers_edition_capability(base.edition, code)
    person = AccountFactory(display_name="PRIVATE-HOME-VOLUNTEER")
    OrganizationMembershipFactory(
        organization=base.edition.organization,
        account=person,
        relationship_label="Workforce volunteer",
    )
    return HomeWorld(base, person)


def propose_home_assignment(world, *, expires_at=None):
    result = propose_position_assignment(
        actor=world.manager,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=world.position.id,
        account_id=world.person.id,
        effective_from=ANCHOR,
        expires_at=expires_at,
        reason="PRIVATE-HOME-PROPOSAL-REASON",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return PositionAssignment.objects.get(pk=result.assignment_id)


def approve_home_assignment(world, assignment):
    approve_position_assignment(
        actor=world.reviewer,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        assignment_id=assignment.id,
        expected_version=assignment.command_version,
        reason="PRIVATE-HOME-APPROVAL-REASON",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assignment.refresh_from_db()


def share_home_availability(world, *, status="submitted", empty=False):
    plan = PersonAvailabilityPlan.objects.filter(
        edition=world.edition, account=world.person
    ).first()
    windows = (
        ()
        if empty
        else (
            AvailabilityWindowInput(
                starts_at=ANCHOR,
                ends_at=ANCHOR + timedelta(hours=12),
                preference="available",
            ),
        )
    )
    return save_person_availability(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        expected_version=plan.command_version if plan else 0,
        status=status,
        windows=windows,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def create_home_shift(world, *, starts_at=None, ends_at=None, headcount=1):
    result = create_shift_demand(
        actor=world.manager,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=world.position.id,
        title="PRIVATE-HOME-SHIFT-NAME",
        location_label="Fictional volunteer desk",
        briefing="PRIVATE-HOME-BRIEFING",
        supervision_note="Fictional helper instructions.",
        starts_at=starts_at or ANCHOR + timedelta(hours=2),
        ends_at=ends_at or ANCHOR + timedelta(hours=4),
        required_headcount=headcount,
        break_minutes=0,
        minimum_rest_minutes=0,
        reason="PRIVATE-HOME-PLANNING-REASON",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return ShiftDemand.objects.get(pk=result.demand_id)


def home_transition_arguments(world, demand):
    demand.refresh_from_db()
    return {
        "actor": world.manager,
        "organization_id": world.edition.organization_id,
        "series_id": world.edition.series_id,
        "edition_id": world.edition.id,
        "demand_id": demand.id,
        "expected_version": demand.command_version,
        "reason": "Fictional operating-home transition through the owning command.",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


def open_home_shift(world, demand):
    open_shift_demand(**home_transition_arguments(world, demand))
    demand.refresh_from_db()


def claim_home_shift(world, demand):
    result = claim_shift(
        actor=world.person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        demand_id=demand.id,
        expected_version=demand.command_version,
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return ShiftCommitment.objects.get(pk=result.commitment_id)


def confirm_home_shift(world, commitment):
    confirm_shift_commitment(
        actor=world.reviewer,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        commitment_id=commitment.id,
        expected_version=commitment.command_version,
        reason="PRIVATE-HOME-CONFIRMATION-REASON",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    commitment.refresh_from_db()
