"""Native proof of the rehearsal inspector's count and read-only boundaries."""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import partial
from uuid import uuid4

import pytest
import time_machine
from django.apps import apps
from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext
from scripts import inspect_workforce_rehearsal as inspector

from maru.events.adoption import (
    ADOPTION_MODULE_NAMESPACE_CATALOG,
    WORKFORCE_ONLY_MODULES,
)
from maru.workforce.assignment_commands import end_position_assignment
from maru.workforce.models import (
    EditionStructureControl,
    PositionAssignment,
    ShiftCommitment,
    VolunteerOpportunity,
)
from maru.workforce.services import submit_volunteer_application
from maru.workforce.shift_commands import complete_shift_demand, lock_shift_demand
from maru.workforce.structure_commands import update_position_opportunity
from tests.factories import AccountFactory, EventEditionFactory
from tests.integration import test_workforce_assignment_commands as assignment_fixture
from tests.integration.test_workforce_shifts import (
    _claim,
    _confirm,
    _create_demand,
    _open,
    _shift_world,
)
from tests.support import workforce_home as fixture

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_empty_dedicated_rehearsal_inventory_reads_every_unadopted_model():
    platform = AccountFactory(
        email="workforce-platform@example.invalid", is_staff=True, is_superuser=True
    )
    with CaptureQueriesContext(connection) as queries:
        report = inspector._read_snapshot(
            phase="baseline",
            platform_email=platform.email,
            edition_id=None,
            volunteer_email=None,
        )
    assert inspector.evaluate(report, None) == []
    unadopted = ADOPTION_MODULE_NAMESPACE_CATALOG - WORKFORCE_ONLY_MODULES
    expected = {
        model._meta.label_lower
        for namespace in unadopted
        for model in apps.get_app_config(namespace).get_models(
            include_auto_created=True
        )
        if not model._meta.proxy
    }
    assert set(report["model_counts"]) == expected
    assert all(value == 0 for value in report["model_counts"].values())
    assert "knowledge.guidanceitem" in expected
    assert not any('"password"' in query["sql"] for query in queries)
    assert connection.get_autocommit()


def test_native_read_only_transaction_rejects_an_accidental_write(monkeypatch):
    platform = AccountFactory(
        email="workforce-platform@example.invalid", is_staff=True, is_superuser=True
    )

    def accidental_write(_namespaces):
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE maru_inspector_must_not_create (id integer)")
        return {}

    monkeypatch.setattr(inspector, "_inventory", accidental_write)
    with pytest.raises(DatabaseError, match="read-only"):
        inspector._read_snapshot(
            phase="baseline",
            platform_email=platform.email,
            edition_id=None,
            volunteer_email=None,
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.maru_inspector_must_not_create')")
        assert cursor.fetchone()[0] is None
    assert connection.get_autocommit()


def test_non_synthetic_account_blocks_baseline_without_disclosing_its_identity():
    platform = AccountFactory(
        email="workforce-platform@example.invalid", is_staff=True, is_superuser=True
    )
    # Reserved example.org is fictional too; the tool deliberately requires .invalid.
    AccountFactory(email="fictional-person@example.org")
    report = inspector._read_snapshot(
        phase="baseline",
        platform_email=platform.email,
        edition_id=None,
        volunteer_email=None,
    )
    assert "only_reserved_synthetic_accounts" in inspector.evaluate(report, None)
    assert "fictional-person" not in str(report)


def test_completed_other_profile_is_rejected_and_final_relations_are_readable():
    platform = AccountFactory(
        email="workforce-platform@example.invalid", is_staff=True, is_superuser=True
    )
    baseline = inspector._read_snapshot(
        phase="baseline",
        platform_email=platform.email,
        edition_id=None,
        volunteer_email=None,
    )
    assert inspector.evaluate(baseline, None) == []
    baseline.update(status="passed", failures=[])
    # Real owner commands under the deliberately unaccepted full-convention profile.
    world = _shift_world(position_headcount=1)
    demand = _create_demand(world)
    _open(world, demand)
    claim = _claim(world, demand)
    commitment = ShiftCommitment.objects.get(pk=claim.commitment_id)
    _confirm(world, commitment)
    common = {
        "organization_id": world.edition.organization_id,
        "series_id": world.edition.series_id,
        "edition_id": world.edition.id,
        "source_channel": "test",
    }
    locked = lock_shift_demand(
        **common,
        actor=world.planner,
        demand_id=demand.pk,
        expected_version=demand.command_version,
        allow_understaffed=False,
        reason="Lock the complete synthetic coverage.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    with time_machine.travel("2030-08-01T14:00:00+02:00"):
        complete_shift_demand(
            **common,
            actor=world.planner,
            demand_id=demand.pk,
            expected_version=locked.resulting_version,
            reason="Complete the ended synthetic period.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
        )
    assignment = PositionAssignment.objects.get(pk=world.assignment.pk)
    end_position_assignment(
        **common,
        actor=world.reviewer,
        assignment_id=assignment.pk,
        expected_version=assignment.command_version,
        reason="End the synthetic responsibility after completed work.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    with CaptureQueriesContext(connection) as queries:
        report = inspector._read_snapshot(
            phase="final",
            platform_email=platform.email,
            edition_id=world.edition.pk,
            volunteer_email=world.person.email,
        )
    assert report["checks"]["assignment_ended"]
    assert report["checks"]["linked_authority_revoked"]
    assert report["checks"]["commitment_completed"]
    assert report["checks"]["independent_assignment_decision"]
    assert report["checks"]["independent_shift_confirmation"]
    failed = inspector.evaluate(report, baseline)
    assert "exact_workforce_only_profile" in failed
    assert "assignment_has_no_participation_capacity" in failed
    assert "nonzero:participation.participation" in failed
    assert not any('"password"' in query["sql"] for query in queries)
    assert world.person.email not in str(report)


def test_complete_workforce_only_outcome_passes_exact_baseline_and_all_absence_checks(
    monkeypatch,
):
    platform = AccountFactory(
        email="workforce-platform@example.invalid", is_staff=True, is_superuser=True
    )
    baseline = inspector._read_snapshot(
        phase="baseline",
        platform_email=platform.email,
        edition_id=None,
        volunteer_email=None,
    )
    assert inspector.evaluate(baseline, None) == []
    baseline.update(status="passed", failures=[])
    # Controlled clocks belong to this owner-command regression, never browser
    # evidence. Past synthetic dates also test the independent PostgreSQL clock.
    anchor = datetime(2020, 8, 1, 6, tzinfo=UTC)
    monkeypatch.setattr(fixture, "ANCHOR", anchor)
    monkeypatch.setattr(
        assignment_fixture,
        "EventEditionFactory",
        partial(
            EventEditionFactory,
            starts_on=date(2020, 8, 1),
            ends_on=date(2020, 8, 4),
        ),
    )
    with time_machine.travel(anchor, tick=False):
        world = fixture.create_home_world()
        scope = {
            "organization_id": world.edition.organization_id,
            "series_id": world.edition.series_id,
            "edition_id": world.edition.pk,
            "source_channel": "test",
        }
        update_position_opportunity(
            **scope,
            actor=world.manager,
            position_id=world.position.pk,
            status="published",
            headline="A fictional welcome responsibility",
            description="Practice welcoming synthetic volunteers.",
            applications_open_at=None,
            applications_close_at=None,
            visible_when_filled=True,
            expected_version=EditionStructureControl.objects.get(
                edition=world.edition
            ).aggregate_version,
            reason="Open the synthetic opportunity for this inspector regression.",
            correlation_id=uuid4(),
        )
        opportunity = VolunteerOpportunity.objects.get(position=world.position)
        submit_volunteer_application(
            actor=world.person,
            opportunity_id=opportunity.pk,
            motivation="Practice this fictional responsibility.",
            correlation_id=uuid4(),
        )
        assignment = fixture.propose_home_assignment(world)
        fixture.approve_home_assignment(world, assignment)
        fixture.share_home_availability(world)
        demand = fixture.create_home_shift(world)
        fixture.open_home_shift(world, demand)
        commitment = fixture.claim_home_shift(world, demand)
        fixture.confirm_home_shift(world, commitment)
        lock_shift_demand(
            allow_understaffed=False,
            **fixture.home_transition_arguments(world, demand),
        )
    with time_machine.travel(demand.ends_at, tick=False):
        complete_shift_demand(**fixture.home_transition_arguments(world, demand))
        assignment.refresh_from_db()
        end_position_assignment(
            **scope,
            actor=world.reviewer,
            assignment_id=assignment.pk,
            expected_version=assignment.command_version,
            reason="End the completed fictional responsibility.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
        )
    report = inspector._read_snapshot(
        phase="final",
        platform_email=platform.email,
        edition_id=world.edition.pk,
        volunteer_email=world.person.email,
    )
    assert inspector.evaluate(report, baseline) == []
    assert all(value is True for value in report["checks"].values())
    assert all(value == 0 for value in report["model_counts"].values())
    assert report["fixture_identity"] == baseline["fixture_identity"]
    assert world.person.email not in str(report)
