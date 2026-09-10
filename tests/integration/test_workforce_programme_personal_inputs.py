"""Personal Shift inputs stay independent of Participation and private candidates.

Uses the real Workforce-only profile, not a future Programme profile substitute.
Bound-demand integration is covered separately; this proves its unchanged personal
owner boundary using the exact Programme work-term input contract.
"""

import re
from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.apps import apps
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from maru.events.adoption import AdoptionProfileCode
from maru.programme.staffing_inputs import ProgrammeStaffingExpectation
from maru.workforce.assignment_commands import (
    approve_position_assignment,
    end_position_assignment,
)
from maru.workforce.availability_commands import save_person_availability
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PositionAssignment,
    ShiftCommitment,
    ShiftDemand,
)
from maru.workforce.shift_commands import create_shift_demand, lock_shift_demand
from maru.workforce.shift_queries import load_my_shift_overview
from tests.factories import AccountFactory, OrganizationMembershipFactory
from tests.integration import test_workforce_shifts as shifts
from tests.integration.test_workforce_assignment_commands import (
    _assignment_world,
    _propose,
)
from tests.support.authority import grant_board_controllers_edition_capability

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def excluded_counts():
    return {
        model._meta.label: model.objects.count()
        for label in (
            "participation",
            "registration",
            "catalog",
            "accreditation",
            "communications",
            "logistics",
            "charities",
            "programme",
            "scheduling",
        )
        for model in apps.get_app_config(label).get_models()
    }


def test_personal_work_terms_claim_confirmation_and_history_need_no_participation():
    world = _assignment_world(adoption_profile_code=AdoptionProfileCode.WORKFORCE_ONLY)
    person = AccountFactory()
    other = AccountFactory()
    OrganizationMembershipFactory(
        organization=world.edition.organization,
        account=person,
        relationship_label="Synthetic Workforce volunteer",
    )
    for code in ("workforce.manage_shifts", "workforce.view_shifts"):
        grant_board_controllers_edition_capability(world.edition, code)
    proposed = _propose(world, candidate=person)
    attribution = {
        "actor": world.approver,
        "organization_id": world.edition.organization_id,
        "series_id": world.edition.series_id,
        "edition_id": world.edition.id,
        "reason": "Independent synthetic work readiness review",
        "retry_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }
    approved = approve_position_assignment(
        **attribution, assignment_id=proposed.assignment_id, expected_version=1
    )
    assignment = PositionAssignment.objects.get(id=approved.assignment_id)
    assert assignment.participation_capacity_id is None
    save_person_availability(
        actor=person,
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
        expected_version=0,
        status=PersonAvailabilityPlan.Status.SUBMITTED,
        windows=shifts._windows(),
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    baseline = excluded_counts()
    assert all(value == 0 for value in baseline.values())
    terms = ProgrammeStaffingExpectation(
        world.position.id,
        "Explicit stage work",
        "Synthetic stage entrance",
        "Report at preparation start; leave equipment isolated for the next team.",
        "Check with the synthetic stage lead.",
        datetime.fromisoformat("2030-08-01T09:00:00+02:00"),
        datetime.fromisoformat("2030-08-01T13:00:00+02:00"),
        1,
        30,
        60,
    ).normalized()
    created = create_shift_demand(
        **{**attribution, "retry_key": uuid4()}, **asdict(terms)
    )
    demand = ShiftDemand.objects.get(id=created.demand_id)
    actor_scope = SimpleNamespace(
        planner=world.proposer,
        reviewer=world.approver,
        person=person,
        edition=world.edition,
        position=world.position,
        assignment=assignment,
    )
    shifts._open(actor_scope, demand)
    before = load_my_shift_overview(account=person, edition=world.edition)
    assert [row.demand.id for row in before.suitable] == [demand.id]
    claim = shifts._claim(actor_scope, demand)
    commitment = ShiftCommitment.objects.get(id=claim.commitment_id)
    shifts._confirm(actor_scope, commitment)
    lock_shift_demand(
        **{**attribution, "retry_key": uuid4()},
        demand_id=demand.id,
        expected_version=demand.command_version,
        allow_understaffed=False,
    )
    with CaptureQueriesContext(connection) as captured:
        owned = load_my_shift_overview(account=person, edition=world.edition)
    assert [row.commitment.id for row in owned.commitments] == [commitment.id]
    assert owned.commitments[0].demand.briefing == terms.briefing
    selects = " ".join(
        row["sql"]
        for row in captured
        if row["sql"].lstrip().upper().startswith("SELECT")
    )
    selected_tables = re.findall(r'(?:FROM|JOIN)\s+"([^\"]+)"', selects)
    assert not any(
        table.startswith(
            ("participation_", "programme_", "scheduling_", "registration_")
        )
        for table in selected_tables
    ), selected_tables
    assert (
        load_my_shift_overview(account=other, edition=world.edition).commitments == ()
    )
    end_position_assignment(
        **{**attribution, "actor": world.proposer, "retry_key": uuid4()},
        assignment_id=assignment.id,
        expected_version=assignment.command_version,
    )
    browser = Client()
    browser.force_login(person)
    route = reverse(
        "my-workforce-shifts",
        args=(
            world.edition.organization.slug,
            world.edition.series.slug,
            world.edition.slug,
        ),
    )
    page = browser.get(route)
    assert page.status_code == 200
    assert terms.briefing.encode() in page.content
    assert b"Registration &amp; tickets" not in page.content
    browser.force_login(other)
    denied = browser.get(route)
    assert denied.status_code in (403, 404)
    assert terms.briefing.encode() not in denied.content
    assert excluded_counts() == baseline
