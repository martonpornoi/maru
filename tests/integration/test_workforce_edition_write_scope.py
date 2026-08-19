"""Operational writer ordering around the Page 9 edition mutex."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from maru.authorization.models import RoleBundle, ScopedResourceBinding
from maru.workforce import services
from maru.workforce.admin import PositionAdmin, PositionAssignmentAdmin
from maru.workforce.edition_write_scope import (
    LockedWorkforceEditionWriteScope,
    lock_workforce_edition_write_scope,
)
from maru.workforce.models import (
    Department,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from maru.workforce.structure_commands import create_department, retire_department
from tests.factories import AccountFactory, EventEditionFactory, RoleBundleFactory
from tests.support.authority import (
    create_provenance_backed_role_bundle,
    grant_board_controllers_edition_capability,
)

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _PositionWorld:
    edition: EventEdition
    actor: Account
    role_bundle: RoleBundle
    department: Department
    template: PositionTemplate


def _world(*, retired: bool = False) -> _PositionWorld:
    edition = EventEditionFactory()
    actor = AccountFactory(is_staff=True, is_superuser=True)
    role_bundle = RoleBundleFactory(organization=edition.organization)
    creation = create_department(
        actor=actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        name="Operations",
        description="Synthetic operations.",
        parent_department_id=None,
        display_order=10,
        expected_version=0,
        reason="Create the synthetic operations Department.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    department = Department.objects.get(id=creation.department_id)
    if retired:
        retire_department(
            actor=actor,
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
            department_id=department.id,
            expected_version=creation.resulting_version,
            reason="Retire the unused synthetic Department.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        department.refresh_from_db()
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="operations",
        name="Operations",
        description="Synthetic operational position.",
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        created_by=actor,
    )
    return _PositionWorld(
        edition=edition,
        actor=actor,
        role_bundle=role_bundle,
        department=department,
        template=template,
    )


def _unsaved_position(world: _PositionWorld, *, code: str) -> Position:
    return Position(
        organization=world.edition.organization,
        edition=world.edition,
        template=world.template,
        department=world.department,
        role_bundle=world.role_bundle,
        code=code,
        title="Operations role",
        description="Synthetic operational position.",
        capacity_codes=["volunteer"],
    )


def _save_position_with_admin(
    world: _PositionWorld,
    *,
    code: str = "operations-role",
) -> Position:
    request = RequestFactory().post("/admin/workforce/position/add/")
    request.user = world.actor
    position = _unsaved_position(world, code=code)
    PositionAdmin(Position, admin.site).save_model(
        request,
        position,
        SimpleNamespace(),  # type: ignore[arg-type]
        change=False,
    )
    return position


def _query_index(sql: list[str], *needles: str) -> int:
    for index, statement in enumerate(sql):
        lowered = statement.lower()
        if all(needle.lower() in lowered for needle in needles):
            return index
    raise AssertionError(f"Missing query containing {needles!r}")


def _query_indices(sql: list[str], *needles: str) -> list[int]:
    return [
        index
        for index, statement in enumerate(sql)
        if all(needle.lower() in statement.lower() for needle in needles)
    ]


def test_edition_write_scope_locks_barriers_and_identifier_chain_in_order() -> None:
    edition = EventEditionFactory()

    with transaction.atomic(), CaptureQueriesContext(connection) as captured:
        scope = lock_workforce_edition_write_scope(
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
        )

    sql = [query["sql"] for query in captured.captured_queries]
    page_9 = _query_index(sql, "pg_advisory_xact_lock_shared", "4400460007")
    provenance = _query_index(sql, "maru_lock_authority_provenance_latch")
    retired = _query_index(sql, "pg_advisory_xact_lock", "4400450010")
    organization = _query_index(sql, "organizations_organization", "for update")
    series = _query_index(sql, "organizations_conventionseries", "for update")
    event_edition = _query_index(sql, "events_eventedition", "for update")
    edition_mutex = _query_index(sql, "hashtextextended", "pg_advisory_xact_lock")

    assert [
        page_9,
        provenance,
        retired,
        organization,
        series,
        event_edition,
        edition_mutex,
    ] == sorted(
        [
            page_9,
            provenance,
            retired,
            organization,
            series,
            event_edition,
            edition_mutex,
        ]
    )
    assert scope == LockedWorkforceEditionWriteScope(
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
    )
    for index in (organization, series, event_edition):
        assert '"name"' not in sql[index].lower()
        assert '"slug"' not in sql[index].lower()


def test_edition_write_scope_rechecks_series_tenant_without_disclosing_labels() -> None:
    edition = EventEditionFactory()
    foreign_edition = EventEditionFactory()

    with transaction.atomic(), pytest.raises(ValidationError) as error:
        lock_workforce_edition_write_scope(
            organization_id=edition.organization_id,
            series_id=foreign_edition.series_id,
            edition_id=edition.id,
        )

    assert error.value.code == "workforce_edition_scope_unavailable"
    message = str(error.value)
    assert edition.organization.name not in message
    assert foreign_edition.series.name not in message


def test_retired_department_target_is_rejected_before_position_write() -> None:
    world = _world(retired=True)
    position = _unsaved_position(world, code="retired-target")
    request = RequestFactory().post("/admin/workforce/position/add/")
    request.user = world.actor

    with pytest.raises(ValidationError) as error:
        PositionAdmin(Position, admin.site).save_model(
            request,
            position,
            SimpleNamespace(),  # type: ignore[arg-type]
            change=False,
        )

    assert error.value.code == "workforce_department_retired"
    assert not Position.objects.filter(code="retired-target").exists()
    assert not ScopedResourceBinding.objects.filter(resource_id=position.id).exists()


def test_position_admin_takes_edition_and_department_locks_before_insert() -> None:
    world = _world()
    request = RequestFactory().post("/admin/workforce/position/add/")
    request.user = world.actor
    position = _unsaved_position(world, code="ordered-position")

    with CaptureQueriesContext(connection) as captured:
        PositionAdmin(Position, admin.site).save_model(
            request,
            position,
            SimpleNamespace(),  # type: ignore[arg-type]
            change=False,
        )

    sql = [query["sql"] for query in captured.captured_queries]
    mutex = _query_index(sql, "hashtextextended", "pg_advisory_xact_lock")
    department = _query_index(sql, "workforce_department", "for update")
    insert = _query_index(sql, 'insert into "workforce_position"')
    binding = _query_index(sql, 'insert into "authorization_scopedresourcebinding"')
    assert mutex < department < insert < binding


def test_assignment_admin_locks_position_before_proposal_insert() -> None:
    world = _world()
    position = _save_position_with_admin(world)
    request = RequestFactory().post("/admin/workforce/positionassignment/add/")
    request.user = world.actor
    assignment = PositionAssignment(
        position=position,
        account=AccountFactory(),
        effective_from=timezone.now(),
        reason="Synthetic proposal.",
    )

    with CaptureQueriesContext(connection) as captured:
        PositionAssignmentAdmin(PositionAssignment, admin.site).save_model(
            request,
            assignment,
            SimpleNamespace(cleaned_data={"activate_now": False}),  # type: ignore[arg-type]
            change=False,
        )

    sql = [query["sql"] for query in captured.captured_queries]
    mutex = _query_index(sql, "hashtextextended", "pg_advisory_xact_lock")
    department = _query_index(sql, "workforce_department", "for update")
    position_lock = _query_index(sql, "workforce_position", "for update")
    insert = _query_index(sql, 'insert into "workforce_positionassignment"')
    assert mutex < department < position_lock < insert
    assignment.refresh_from_db()
    assert assignment.status == PositionAssignment.Status.PROPOSED


def test_activation_locks_scope_before_position_and_writes_no_closed_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    position = _save_position_with_admin(world)
    position.status = Position.Status.CLOSED
    request = RequestFactory().post("/admin/workforce/position/change/")
    request.user = world.actor
    PositionAdmin(Position, admin.site).save_model(
        request,
        position,
        SimpleNamespace(),  # type: ignore[arg-type]
        change=True,
    )
    monkeypatch.setattr(services, "_require", lambda **_kwargs: frozenset())

    with (
        CaptureQueriesContext(connection) as captured,
        pytest.raises(ValidationError) as error,
    ):
        services.activate_position_assignment(
            position_id=position.id,
            account=AccountFactory(),
            actor=AccountFactory(),
            approver=AccountFactory(),
            effective_from=timezone.now(),
            expires_at=None,
            reason="Closed target must remain unchanged.",
            correlation_id=uuid4(),
        )

    assert error.value.code == "position_closed"
    sql = [query["sql"] for query in captured.captured_queries]
    mutex = _query_index(sql, "hashtextextended", "pg_advisory_xact_lock")
    department = _query_index(sql, "workforce_department", "for update")
    position_lock = _query_index(sql, "workforce_position", "for update")
    assert mutex < department < position_lock
    assert not PositionAssignment.objects.filter(position=position).exists()


def test_assignment_admin_nested_activation_rejoins_held_outer_locks() -> None:
    world = _world()
    actor, approver = grant_board_controllers_edition_capability(
        world.edition,
        "workforce.manage_assignments",
    )
    _role_actor, _role_approver, assignment_role = create_provenance_backed_role_bundle(
        world.edition.organization,
        code="ordered-assignment",
        name="Ordered assignment",
        capability_codes=("workforce.view_structure",),
    )
    position = _unsaved_position(world, code="nested-activation")
    position.role_bundle = assignment_role
    position_request = RequestFactory().post("/admin/workforce/position/add/")
    position_request.user = world.actor
    PositionAdmin(Position, admin.site).save_model(
        position_request,
        position,
        SimpleNamespace(),  # type: ignore[arg-type]
        change=False,
    )
    assignment_request = RequestFactory().post(
        "/admin/workforce/positionassignment/add/"
    )
    assignment_request.user = actor
    assignment_request.correlation_id = str(uuid4())  # type: ignore[attr-defined]
    assignment = PositionAssignment(
        position=position,
        account=AccountFactory(),
        effective_from=timezone.now(),
        reason="Exercise nested activation ordering.",
    )

    with CaptureQueriesContext(connection) as captured:
        PositionAssignmentAdmin(PositionAssignment, admin.site).save_model(
            assignment_request,
            assignment,
            SimpleNamespace(
                cleaned_data={"activate_now": True, "approved_by": approver}
            ),  # type: ignore[arg-type]
            change=False,
        )

    sql = [query["sql"] for query in captured.captured_queries]
    mutexes = _query_indices(sql, "hashtextextended", "pg_advisory_xact_lock")
    assert len(mutexes) >= 2
    proposal_insert = _query_index(sql, 'insert into "workforce_positionassignment"')
    nested_assignment_locks = [
        index
        for index in _query_indices(
            sql,
            "workforce_positionassignment",
            "for update",
        )
        if index > mutexes[1]
    ]
    role_insert = _query_index(sql, 'insert into "authorization_roleassignment"')
    assignment_update = _query_index(sql, 'update "workforce_positionassignment"')
    assert mutexes[0] < proposal_insert < mutexes[1]
    # The first lock freezes the current active set for headcount/deactivation
    # races; the second locks the exact proposal before authority is issued.
    assert len(nested_assignment_locks) >= 2
    assert mutexes[1] < nested_assignment_locks[-1] < role_insert < assignment_update
    assignment.refresh_from_db()
    assert assignment.status == PositionAssignment.Status.ACTIVE
