"""Operational writer ordering around the Page 9 edition mutex."""

from __future__ import annotations

from dataclasses import dataclass
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
from maru.workforce.assignment_commands import (
    approve_position_assignment,
    propose_position_assignment,
)
from maru.workforce.edition_write_scope import (
    LockedWorkforceEditionWriteScope,
    lock_workforce_edition_write_scope,
)
from maru.workforce.models import (
    Department,
    EditionStructureControl,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from maru.workforce.structure_commands import (
    StructureDepartmentUnavailableError,
    close_position,
    create_department,
    create_position,
    retire_department,
)
from tests.factories import AccountFactory, EventEditionFactory, ParticipationFactory
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
    _role_actor, _role_approver, role_bundle = create_provenance_backed_role_bundle(
        edition.organization,
        code="operations",
        name="Operations",
        capability_codes=("workforce.view_structure",),
    )
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
        status=PositionTemplate.Status.PUBLISHED,
        created_by=actor,
    )
    return _PositionWorld(
        edition=edition,
        actor=actor,
        role_bundle=role_bundle,
        department=department,
        template=template,
    )


def _create_position(
    world: _PositionWorld,
    *,
    title: str = "Operations role",
) -> Position:
    current_version = EditionStructureControl.objects.values_list(
        "aggregate_version", flat=True
    ).get(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    result = create_position(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        template_id=world.template.id,
        department_id=world.department.id,
        reports_to_id=None,
        title=title,
        description="Synthetic operational position.",
        headcount=1,
        expected_version=current_version,
        reason="Create a governed Position for lock-order verification.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    return Position.objects.get(id=result.position_id)


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


def test_edition_write_scope_rejects_an_unresolvable_exact_profile_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the shared Workforce write boundary closed for retained unknown pairs."""
    edition = EventEditionFactory(name="Retained Unsupported Workforce Edition")
    monkeypatch.setattr("maru.events.adoption.ADOPTION_PROFILES", {})

    with transaction.atomic(), pytest.raises(ValidationError) as error:
        lock_workforce_edition_write_scope(
            organization_id=edition.organization_id,
            series_id=edition.series_id,
            edition_id=edition.id,
        )

    assert error.value.code == "workforce_edition_scope_unavailable"
    assert edition.name not in str(error.value)
    assert not EditionStructureControl.objects.filter(edition=edition).exists()


def test_retired_department_target_is_rejected_before_position_write() -> None:
    world = _world(retired=True)

    with pytest.raises(StructureDepartmentUnavailableError):
        _create_position(world, title="Retired target")

    assert not Position.objects.filter(edition=world.edition).exists()
    assert not ScopedResourceBinding.objects.filter(
        organization=world.edition.organization,
        edition=world.edition,
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
    ).exists()


def test_position_command_takes_edition_and_department_locks_before_insert() -> None:
    world = _world()
    request = RequestFactory().post("/admin/workforce/position/add/")
    request.user = world.actor
    position_admin = PositionAdmin(Position, admin.site)
    assert not position_admin.has_add_permission(request)
    assert not position_admin.has_change_permission(request)
    assert not position_admin.has_delete_permission(request)

    with CaptureQueriesContext(connection) as captured:
        _create_position(world, title="Ordered Position")

    sql = [query["sql"] for query in captured.captured_queries]
    mutex = _query_index(sql, "hashtextextended", "pg_advisory_xact_lock")
    department = _query_index(sql, "workforce_department", "for update")
    insert = _query_index(sql, 'insert into "workforce_position"')
    binding = _query_index(sql, 'insert into "authorization_scopedresourcebinding"')
    assert mutex < department < insert < binding


def test_assignment_admin_is_inspection_only() -> None:
    world = _world()
    _create_position(world)
    request = RequestFactory().get("/admin/workforce/positionassignment/")
    request.user = world.actor
    assignment_admin = PositionAssignmentAdmin(PositionAssignment, admin.site)

    assert assignment_admin.has_view_permission(request)
    assert not assignment_admin.has_add_permission(request)
    assert not assignment_admin.has_change_permission(request)
    assert not assignment_admin.has_delete_permission(request)


def test_activation_locks_scope_before_position_and_writes_no_closed_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world()
    position = _create_position(world)
    current_version = EditionStructureControl.objects.values_list(
        "aggregate_version", flat=True
    ).get(
        organization_id=world.edition.organization_id,
        edition_id=world.edition.id,
    )
    close_position(
        actor=world.actor,
        organization_id=world.edition.organization_id,
        series_id=world.edition.series_id,
        edition_id=world.edition.id,
        position_id=position.id,
        expected_version=current_version,
        confirmation_name=position.title,
        reason="Close the governed Position before assignment verification.",
        correlation_id=uuid4(),
        source_channel="test",
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


def test_assignment_commands_rejoin_held_outer_locks() -> None:
    world = _world()
    actor: Account | None = None
    approver: Account | None = None
    for capability_code in (
        "workforce.view_structure",
        "workforce.manage_assignments",
        "authorization.manage_roles",
    ):
        actor, approver = grant_board_controllers_edition_capability(
            world.edition,
            capability_code,
        )
    assert actor is not None
    assert approver is not None
    position = _create_position(world, title="Nested activation")
    candidate = AccountFactory()
    ParticipationFactory(
        account=candidate,
        organization=world.edition.organization,
        edition=world.edition,
    )

    with CaptureQueriesContext(connection) as proposal_queries:
        proposal = propose_position_assignment(
            actor=actor,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            position_id=position.id,
            account_id=candidate.id,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Exercise governed proposal ordering.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    proposal_sql = [query["sql"] for query in proposal_queries.captured_queries]
    proposal_mutex = _query_index(
        proposal_sql,
        "hashtextextended",
        "pg_advisory_xact_lock",
    )
    proposal_department = _query_index(
        proposal_sql,
        "workforce_department",
        "for update",
    )
    proposal_position = _query_index(
        proposal_sql,
        "workforce_position",
        "for update",
    )
    proposal_insert = _query_index(
        proposal_sql,
        'insert into "workforce_positionassignment"',
    )
    assert proposal_mutex < proposal_department < proposal_position < proposal_insert

    with CaptureQueriesContext(connection) as captured:
        result = approve_position_assignment(
            actor=approver,
            organization_id=world.edition.organization_id,
            series_id=world.edition.series_id,
            edition_id=world.edition.id,
            assignment_id=proposal.assignment_id,
            expected_version=proposal.resulting_version,
            reason="Approve through a different current controller.",
            retry_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )

    assignment = PositionAssignment.objects.get(pk=result.assignment_id)
    assert assignment.status == PositionAssignment.Status.ACTIVE
    assert assignment.approved_by == approver

    sql = [query["sql"] for query in captured.captured_queries]
    mutexes = _query_indices(sql, "hashtextextended", "pg_advisory_xact_lock")
    assert len(mutexes) >= 2
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
    assert len(nested_assignment_locks) >= 2
    assert mutexes[1] < nested_assignment_locks[-1] < role_insert < assignment_update
