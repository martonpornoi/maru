"""Actual independent stop-purpose metadata reads, not full stop acceptance."""

# ruff: noqa: F811 -- Imported pytest fixtures are injected by their names.

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from maru.applications import programme_commands as commands
from maru.applications import programme_stop_queries as queries
from maru.audit.models import AuditEvent
from maru.authorization.services import AuthorizationDenied
from maru.effects.programme_stop_queries import load_programme_stop_effects
from maru.events.programme_stop_composition import load_programme_stop_preview
from maru.programme import programme_stop_queries as content_queries
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER
from maru.scheduling.day_commands import create_scheduling_service_day
from maru.scheduling.inputs import SchedulingCommandRequest, SchedulingServiceDayInput
from maru.scheduling.programme_stop_queries import load_programme_stop_scheduling
from maru.scheduling.time_rules import SchedulingWindow
from maru.venues.programme_stop_queries import load_programme_stop_venues
from maru.workforce.programme_stop_queries import load_programme_stop_workforce
from tests.factories import AccountFactory
from tests.integration.test_application_programme_stop import (
    call,  # noqa: F401 - fixture
)
from tests.integration.test_programme_commands import _create
from tests.integration.test_programme_hosts import invite
from tests.integration.test_programme_role_schema import _foundation
from tests.integration.test_programme_stop_controller import (
    _grant,
    reader,  # noqa: F401 - fixture
    world,  # noqa: F401 - fixture
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


@pytest.fixture
def candidate(world):
    return world[1]


def _read(world, reader, **changes):
    return queries.load_programme_stop_applications(
        **{
            "actor_id": reader[0].id,
            "organization_id": world[0].id,
            "edition_id": world[1].id,
            "correlation_id": uuid4(),
            **changes,
        }
    )


def _preview(world, reader, **changes):
    return load_programme_stop_preview(
        **{
            "actor_id": reader[0].id,
            "organization_id": world[0].id,
            "edition_id": world[1].id,
            "correlation_id": uuid4(),
            **changes,
        }
    )


def test_composed_preview_binds_all_seven_owners_without_mutating_work(
    world, reader, call
):
    before = (
        world[1].lifecycle,
        world[1].aggregate_version,
        world[1].lifecycle_version,
    )
    trace = uuid4()
    original = _preview(world, reader, correlation_id=trace)
    assert tuple(row.owner for row in original.inventories) == (
        "applications",
        "programme",
        "workforce",
        "venues",
        "effects",
    )
    assert original.scheduling.inventory.owner == "scheduling"
    assert len(original.authority.assignments) >= 2
    assert original.scheduling.active_release_id is None
    assert original.scheduling.pointer_version == 0
    assert original == _preview(world, reader)
    assert len(original.fingerprint) == 64
    assert str(call.active.target_id) not in repr(original)
    world[1].refresh_from_db()
    assert before == (
        world[1].lifecycle,
        world[1].aggregate_version,
        world[1].lifecycle_version,
    )
    assert AuditEvent.objects.filter(correlation_id=trace, outcome="allow").count() == 8


def test_composed_original_confirmation_changes_when_an_owner_changes(
    world, reader, call
):
    original = _preview(world, reader)
    commands.retire_programme_call(
        **call.common,
        call_id=call.active.target_id,
        owner_department_id=call.department.id,
        expected_version=call.active.resulting_version,
        reason="Synthetic owner change after complete stop preview.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    fresh = _preview(world, reader)
    assert original.aggregate_version == fresh.aggregate_version
    assert original.fingerprint != fresh.fingerprint


def test_composed_denial_has_no_owner_inventory_or_target_disclosure(world, reader):
    trace = uuid4()
    with pytest.raises(AuthorizationDenied):
        _preview(world, reader, actor_id=world[2].id, correlation_id=trace)
    event = AuditEvent.objects.get(correlation_id=trace)
    assert event.operation == "events.query.programme_stop"
    assert event.outcome == "deny"
    assert event.target_id is None
    assert event.safe_metadata == {}


def test_composed_source_failure_rolls_back_partial_disclosure_evidence(world, reader):
    trace = uuid4()
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE public.programme_programmeitem "
            "DISABLE TRIGGER programme_stop_privacy_0"
        )
    with pytest.raises(ValidationError):
        _preview(world, reader, correlation_id=trace)
    assert not AuditEvent.objects.filter(correlation_id=trace, outcome="allow").exists()


def test_real_controller_sees_complete_counts_without_applicant_source_rights(
    world, reader, call
):
    trace = uuid4()
    result = _read(world, reader, correlation_id=trace)
    counts = {row.code: row for row in result.collections}
    assert len(counts) == 43
    assert counts["applicationdefinition"].states == (("active", 1),)
    assert counts["programmecall"].total == 1
    assert counts["programmecommandreceipt"].total == 2
    assert counts["programmefilecontent"].total == 0
    assert str(call.active.target_id) not in repr(result)
    assert AuditEvent.objects.get(correlation_id=trace).outcome == "allow"
    assert result == _read(world, reader)


def test_actual_owner_change_invalidates_the_original_metadata_preview(
    world, reader, call
):
    original = _read(world, reader)
    commands.retire_programme_call(
        **call.common,
        call_id=call.active.target_id,
        owner_department_id=call.department.id,
        expected_version=call.active.resulting_version,
        reason="Retire synthetic intake before an explicit stop preview.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
    )
    fresh = _read(world, reader)
    assert fresh.source_fingerprint != original.source_fingerprint
    assert next(
        row for row in fresh.collections if row.code == "applicationdefinition"
    ).states == (("retired", 1),)


def test_ordinary_call_manager_has_no_stop_impact_permission(world, reader, call):
    trace = uuid4()
    with pytest.raises(AuthorizationDenied):
        _read(world, reader, actor_id=call.common["actor_id"], correlation_id=trace)
    denied = AuditEvent.objects.get(correlation_id=trace)
    assert denied.outcome == "deny"
    assert denied.target_id is None
    assert denied.safe_metadata == {}


def test_native_source_readiness_failure_releases_no_impact(world, reader):
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE public.applications_programmecall "
            "DISABLE TRIGGER a00_applications_programme_stop_4"
        )
    with pytest.raises(ValidationError, match="source is unavailable"):
        _read(world, reader)


def _read_content(world, reader):
    return content_queries.load_programme_stop_content(
        actor_id=reader[0].id,
        organization_id=world[0].id,
        edition_id=world[1].id,
        correlation_id=uuid4(),
    )


def test_actual_content_and_pending_host_impact_uses_no_private_read_grant(
    world, reader
):
    manager, host = AccountFactory(), AccountFactory()
    for capability in ("programme.manage_items", "programme.manage_hosts"):
        _grant(world, manager, capability)
    item, _, _ = _create(
        actor=manager,
        edition=world[1],
        authorizer=DEFAULT_PROGRAMME_AUTHORIZER,
    )
    original = _read_content(world, reader)
    counts = {row.code: row for row in original.collections}
    assert len(counts) == 22
    assert counts["programmeitem"].total == 1
    assert counts["programmehostrelationship"].total == 0
    assert counts["programmearchivetask"].total == 0
    assert counts["programmearchivechunk"].total == 0
    assert str(item.item_id) not in repr(original)
    invite(
        (
            manager,
            host,
            {
                "organization_id": world[0].id,
                "edition_id": world[1].id,
                "item_id": item.item_id,
                "authorizer": DEFAULT_PROGRAMME_AUTHORIZER,
                "source_channel": "test",
            },
        )
    )
    fresh = _read_content(world, reader)
    assert fresh.source_fingerprint != original.source_fingerprint
    assert next(
        row for row in fresh.collections if row.code == "programmehostrelationship"
    ).states == (("invited", 1),)
    assert str(host.id) not in repr(fresh)
    assert fresh == _read_content(world, reader)


def test_missing_native_privacy_guard_withholds_content_impact(world, reader):
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE public.programme_programmeitem "
            "DISABLE TRIGGER programme_stop_privacy_0"
        )
    with pytest.raises(ValidationError, match="source is unavailable"):
        _read_content(world, reader)


@pytest.mark.parametrize(
    ("load", "count"),
    [
        (load_programme_stop_venues, 9),
        (load_programme_stop_workforce, 22),
        (load_programme_stop_effects, 4),
    ],
)
def test_remaining_owner_counts_are_complete_without_additional_content_rights(
    world, reader, call, load, count
):
    arguments = {
        "actor_id": reader[0].id,
        "organization_id": world[0].id,
        "edition_id": world[1].id,
        "correlation_id": uuid4(),
    }
    result = load(**arguments)
    assert len(result.collections) == count
    assert str(call.department.id) not in repr(result)
    if result.owner == "workforce":
        assert (
            next(row for row in result.collections if row.code == "department").total
            == 1
        )
    if result.owner == "effects":
        assert (
            next(row for row in result.collections if row.code == "domainevent").total
            > 0
        )
    assert result == load(**{**arguments, "correlation_id": uuid4()})
    assert (
        AuditEvent.objects.get(correlation_id=arguments["correlation_id"]).outcome
        == "allow"
    )


def test_scheduling_preview_preserves_never_published_state_and_tracks_actual_planning(
    world, reader
):
    arguments = {
        "actor_id": reader[0].id,
        "organization_id": world[0].id,
        "edition_id": world[1].id,
        "correlation_id": uuid4(),
    }
    original = load_programme_stop_scheduling(**arguments)
    assert original.active_release_id is None
    assert original.pointer_version == 0
    assert not original.withdrawal_authorized
    assert len(original.inventory.collections) == 27
    manager = AccountFactory()
    _grant(world, manager, "scheduling.manage_service_days")
    created = create_scheduling_service_day(
        SchedulingCommandRequest(
            manager.id,
            world[0].id,
            world[1].id,
            uuid4(),
            uuid4(),
            "Create a synthetic planning day before a stop preview.",
        ),
        day=SchedulingServiceDayInput(
            "Private synthetic day title",
            SchedulingWindow(
                datetime(2030, 9, 6, 8, tzinfo=UTC),
                datetime(2030, 9, 6, 22, tzinfo=UTC),
            ),
            15,
        ),
        expected_control_version=0,
    )
    fresh = load_programme_stop_scheduling(**{**arguments, "correlation_id": uuid4()})
    assert fresh.inventory.source_fingerprint != original.inventory.source_fingerprint
    assert (
        next(
            row
            for row in fresh.inventory.collections
            if row.code == "schedulingserviceday"
        ).total
        == 1
    )
    assert str(created.object_id) not in repr(fresh)
    assert "Private synthetic day title" not in repr(fresh)


@pytest.mark.parametrize(
    "load",
    [
        queries.load_programme_stop_applications,
        content_queries.load_programme_stop_content,
        load_programme_stop_scheduling,
        load_programme_stop_venues,
        load_programme_stop_workforce,
        load_programme_stop_effects,
    ],
)
def test_real_foreign_adoption_cannot_release_any_owner_counts(world, reader, load):
    foreign = _foundation("programme_operations")
    trace = uuid4()
    with pytest.raises(AuthorizationDenied):
        load(
            actor_id=reader[0].id,
            organization_id=foreign[0].id,
            edition_id=foreign[1].id,
            correlation_id=trace,
        )
    denied = AuditEvent.objects.get(correlation_id=trace)
    assert denied.outcome == "deny"
    assert denied.target_id is None
    assert denied.safe_metadata == {}
