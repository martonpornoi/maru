from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.models import (
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
    ScopedResourceBinding,
)
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import (
    Department,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from tests.factories import AccountFactory, EventEditionFactory, RoleBundleFactory

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_SCHEMA = ("authorization", "0004_scope_v2_schema")
WORKFORCE_BEFORE = ("workforce", "0003_idn011_convention_subject_guards")
WORKFORCE_AFTER = ("workforce", "0004_scope_v2_integrity")


@dataclass(frozen=True)
class WorkforceGraph:
    organization: Organization
    edition: EventEdition
    actor: Account
    role_bundle: RoleBundle
    department: Department
    position: Position


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _create_graph() -> WorkforceGraph:
    actor = AccountFactory()
    edition = EventEditionFactory()
    role_bundle = RoleBundleFactory(
        organization=edition.organization,
        capability_codes=["organizations.view_basic"],
    )
    department = Department.objects.create(
        organization=edition.organization,
        edition=edition,
        code=f"operations-{uuid4().hex[:8]}",
        name="Synthetic Operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code=f"operator-{uuid4().hex[:8]}",
        name="Synthetic operator",
        description="Synthetic scope-v2 integrity position template.",
        default_capacity_codes=["staff"],
        role_bundle=role_bundle,
        created_by=actor,
    )
    position = Position.objects.create(
        organization=edition.organization,
        edition=edition,
        template=template,
        department=department,
        role_bundle=role_bundle,
        code=f"operator-{uuid4().hex[:8]}",
        title="Synthetic operator",
        description="Synthetic position for database containment tests.",
        capacity_codes=["staff"],
        created_by=actor,
    )
    return WorkforceGraph(
        organization=edition.organization,
        edition=edition,
        actor=actor,
        role_bundle=role_bundle,
        department=department,
        position=position,
    )


def _role_assignment(
    graph: WorkforceGraph,
    *,
    principal: Account,
    edition: EventEdition | None,
    department: Department | None = None,
    resource_binding: ScopedResourceBinding | None = None,
) -> RoleAssignment:
    return RoleAssignment.objects.create(
        organization=graph.organization,
        edition=edition,
        department=department,
        resource_binding=resource_binding,
        principal=principal,
        role_bundle=graph.role_bundle,
        effective_from=timezone.now(),
        granted_by=graph.actor,
        reason="Synthetic workforce role evidence.",
    )


def _proposed_assignment(
    graph: WorkforceGraph,
    *,
    account: Account,
    role_assignment: RoleAssignment,
) -> PositionAssignment:
    return PositionAssignment(
        position=graph.position,
        organization=graph.organization,
        edition=graph.edition,
        account=account,
        effective_from=timezone.now(),
        proposed_by=graph.actor,
        reason="Synthetic proposed workforce assignment.",
        role_assignment=role_assignment,
    )


def test_department_guard_rejects_raw_cross_scope_parent_and_cycle() -> None:
    graph = _create_graph()
    child = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        parent=graph.department,
        code="child-team",
        name="Synthetic child team",
    )
    other_edition = EventEditionFactory(
        organization=graph.organization,
        series=graph.edition.series,
    )
    foreign_parent = Department.objects.create(
        organization=graph.organization,
        edition=other_edition,
        code="foreign-parent",
        name="Synthetic foreign parent",
    )

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="department parent scope mismatch"),
    ):
        Department.objects.filter(pk=child.pk).update(parent=foreign_parent)

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="hierarchy cannot contain a cycle"),
    ):
        Department.objects.filter(pk=graph.department.pk).update(parent=child)


def test_concurrent_department_reparenting_cannot_create_write_skew_cycle() -> None:
    graph = _create_graph()
    peer = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        code="peer-team",
        name="Synthetic peer team",
    )
    start = Barrier(2)

    def reparent(department_id: UUID, parent_id: UUID) -> bool:
        close_old_connections()
        try:
            with transaction.atomic():
                start.wait(timeout=5)
                Department.objects.filter(pk=department_id).update(parent_id=parent_id)
        except IntegrityError:
            return False
        finally:
            close_old_connections()
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            executor.submit(reparent, graph.department.id, peer.id),
            executor.submit(reparent, peer.id, graph.department.id),
        ]

    assert sorted(result.result(timeout=10) for result in results) == [False, True]
    graph.department.refresh_from_db()
    peer.refresh_from_db()
    assert not (
        graph.department.parent_id == peer.id and peer.parent_id == graph.department.id
    )


def test_position_guard_rejects_raw_department_scope_mismatch() -> None:
    graph = _create_graph()
    other_edition = EventEditionFactory(
        organization=graph.organization,
        series=graph.edition.series,
    )
    foreign_department = Department.objects.create(
        organization=graph.organization,
        edition=other_edition,
        code="foreign-position-team",
        name="Synthetic foreign position team",
    )

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="position department scope mismatch"),
    ):
        Position.objects.filter(pk=graph.position.pk).update(
            department=foreign_department
        )


def test_position_guard_rejects_raw_reporting_cycle() -> None:
    graph = _create_graph()
    report = Position.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        template=graph.position.template,
        department=graph.department,
        reports_to=graph.position,
        role_bundle=graph.role_bundle,
        code="reporting-cycle-peer",
        title="Synthetic reporting peer",
        description="Synthetic position used to test reporting cycles.",
        capacity_codes=["staff"],
        created_by=graph.actor,
    )

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="reporting hierarchy cannot contain"),
    ):
        Position.objects.filter(pk=graph.position.pk).update(reports_to=report)


@pytest.mark.parametrize("authority_kind", ["grant", "role"])
def test_department_move_cannot_orphan_scoped_authority(
    authority_kind: str,
) -> None:
    graph = _create_graph()
    scoped_department = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        code=f"scoped-authority-{authority_kind}",
        name="Synthetic scoped authority department",
    )
    principal = AccountFactory()
    if authority_kind == "grant":
        CapabilityGrant.objects.create(
            organization=graph.organization,
            edition=graph.edition,
            department=scoped_department,
            principal=principal,
            capability_code="organizations.view_basic",
            effective_from=timezone.now(),
            granted_by=graph.actor,
            reason="Synthetic department grant.",
        )
    else:
        _role_assignment(
            graph,
            principal=principal,
            edition=graph.edition,
            department=scoped_department,
        )
    other_edition = EventEditionFactory(
        organization=graph.organization,
        series=graph.edition.series,
    )

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="orphan scoped authority"),
    ):
        Department.objects.filter(pk=scoped_department.pk).update(edition=other_edition)


def test_bound_position_scope_cannot_move_through_bulk_update() -> None:
    graph = _create_graph()
    sibling = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        code="sibling-team",
        name="Synthetic sibling team",
    )
    ScopedResourceBinding.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        department=graph.department,
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
        resource_id=graph.position.id,
    )

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="immutable after resource binding"),
    ):
        Position.objects.filter(pk=graph.position.pk).update(department=sibling)


@pytest.mark.parametrize("scope", ["edition", "department", "resource"])
def test_position_assignment_accepts_exact_or_legacy_edition_role_evidence(
    scope: str,
) -> None:
    graph = _create_graph()
    account = AccountFactory()
    binding = None
    department = None
    if scope == "department":
        department = graph.department
    elif scope == "resource":
        department = graph.department
        binding = ScopedResourceBinding.objects.create(
            organization=graph.organization,
            edition=graph.edition,
            department=graph.department,
            resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
            resource_id=graph.position.id,
        )
    role_assignment = _role_assignment(
        graph,
        principal=account,
        edition=graph.edition,
        department=department,
        resource_binding=binding,
    )

    PositionAssignment.objects.bulk_create(
        [
            _proposed_assignment(
                graph,
                account=account,
                role_assignment=role_assignment,
            )
        ]
    )

    assert PositionAssignment.objects.filter(
        position=graph.position,
        account=account,
        role_assignment=role_assignment,
    ).exists()


@pytest.mark.parametrize(
    "invalid_scope",
    ["organization", "sibling_department", "sibling_resource"],
)
def test_position_assignment_rejects_broader_or_wrong_exact_role_evidence(
    invalid_scope: str,
) -> None:
    graph = _create_graph()
    account = AccountFactory()
    department = None
    edition = None
    binding = None
    if invalid_scope == "sibling_department":
        edition = graph.edition
        department = Department.objects.create(
            organization=graph.organization,
            edition=graph.edition,
            code="wrong-evidence-team",
            name="Synthetic wrong evidence team",
        )
    elif invalid_scope == "sibling_resource":
        edition = graph.edition
        department = graph.department
        other_position = Position.objects.create(
            organization=graph.organization,
            edition=graph.edition,
            template=graph.position.template,
            department=graph.department,
            role_bundle=graph.role_bundle,
            code="wrong-evidence-position",
            title="Synthetic wrong evidence position",
            description="Synthetic sibling position for exact binding checks.",
            capacity_codes=["staff"],
            created_by=graph.actor,
        )
        binding = ScopedResourceBinding.objects.create(
            organization=graph.organization,
            edition=graph.edition,
            department=graph.department,
            resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
            resource_id=other_position.id,
        )
    role_assignment = _role_assignment(
        graph,
        principal=account,
        edition=edition,
        department=department,
        resource_binding=binding,
    )

    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="role evidence scope mismatch"),
    ):
        PositionAssignment.objects.bulk_create(
            [
                _proposed_assignment(
                    graph,
                    account=account,
                    role_assignment=role_assignment,
                )
            ]
        )


def test_linked_role_assignment_cannot_move_to_a_sibling_department() -> None:
    graph = _create_graph()
    account = AccountFactory()
    sibling = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        code="wrong-linked-team",
        name="Synthetic wrong linked team",
    )
    role_assignment = _role_assignment(
        graph,
        principal=account,
        edition=graph.edition,
    )
    PositionAssignment.objects.bulk_create(
        [
            _proposed_assignment(
                graph,
                account=account,
                role_assignment=role_assignment,
            )
        ]
    )

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match=r"issuance is immutable|no longer matches workforce evidence",
        ),
    ):
        RoleAssignment.objects.filter(pk=role_assignment.pk).update(department=sibling)


def test_migration_preserves_legacy_edition_wide_role_evidence() -> None:
    _migrate(AUTHORIZATION_SCHEMA, WORKFORCE_BEFORE)
    graph = _create_graph()
    account = AccountFactory()
    role_assignment = _role_assignment(
        graph,
        principal=account,
        edition=graph.edition,
    )
    assignment = _proposed_assignment(
        graph,
        account=account,
        role_assignment=role_assignment,
    )
    assignment.save()

    _migrate(WORKFORCE_AFTER)

    assignment.refresh_from_db()
    role_assignment.refresh_from_db()
    assert assignment.role_assignment_id == role_assignment.id
    assert role_assignment.edition_id == graph.edition.id
    assert role_assignment.department_id is None
    assert role_assignment.resource_binding_id is None

    sibling = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        code="migration-reverse-boundary",
        name="Synthetic migration reverse boundary",
    )
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="no longer matches workforce evidence"),
    ):
        RoleAssignment.objects.filter(pk=role_assignment.pk).update(department=sibling)


def test_migration_preflight_rejects_existing_department_cycle() -> None:
    _migrate(AUTHORIZATION_SCHEMA, WORKFORCE_BEFORE)
    graph = _create_graph()
    child = Department.objects.create(
        organization=graph.organization,
        edition=graph.edition,
        parent=graph.department,
        code="preflight-child",
        name="Synthetic preflight child",
    )
    Department.objects.filter(pk=graph.department.pk).update(parent=child)

    try:
        with pytest.raises(IntegrityError, match="ADR 0041 workforce blockers"):
            _migrate(WORKFORCE_AFTER)
    finally:
        Department.objects.filter(pk=graph.department.pk).update(parent=None)
        _migrate(WORKFORCE_AFTER)
