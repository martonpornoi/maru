from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.bindings import ensure_workforce_position_binding
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
    EditionStructureControl,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from maru.workforce.structure_commands import (
    StructureVersionConflictError,
    update_department,
)
from tests.factories import AccountFactory, EventEditionFactory, RoleBundleFactory
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_assignment_for_test,
    save_position_for_test,
)

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


@dataclass(frozen=True)
class HistoricalWorkforceGraph:
    organization_id: UUID
    edition_id: UUID
    actor_id: UUID
    role_bundle_id: UUID
    department: Any
    position: Any


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _create_graph() -> WorkforceGraph:
    actor = AccountFactory(is_staff=True, is_superuser=True)
    edition = EventEditionFactory()
    role_bundle = RoleBundleFactory(
        organization=edition.organization,
        capability_codes=["organizations.view_basic"],
    )
    department_suffix = uuid4().hex[:8]
    department = create_department_for_test(
        edition=edition,
        name=f"Synthetic Operations {department_suffix}",
        expected_code=f"synthetic-operations-{department_suffix}",
        actor=actor,
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
    position = save_position_for_test(
        position=Position(
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
    )
    return WorkforceGraph(
        organization=edition.organization,
        edition=edition,
        actor=actor,
        role_bundle=role_bundle,
        department=department,
        position=position,
    )


def _create_historical_graph(
    apps: Any,
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor_id: UUID,
) -> HistoricalWorkforceGraph:
    """Build fixtures with the model state that matches workforce 0003."""

    historical_department = apps.get_model("workforce", "Department")
    historical_position = apps.get_model("workforce", "Position")
    historical_template = apps.get_model("workforce", "PositionTemplate")
    historical_role_bundle = apps.get_model("authorization", "RoleBundle")
    suffix = uuid4().hex[:8]
    role_bundle = historical_role_bundle.objects.create(
        organization_id=organization_id,
        code=f"historical-role-{suffix}",
        name="Historical workforce role",
        version=1,
        capability_codes=["organizations.view_basic"],
    )
    department = historical_department.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        code=f"historical-operations-{suffix}",
        name="Historical synthetic operations",
    )
    template = historical_template.objects.create(
        organization_id=organization_id,
        code=f"historical-operator-{suffix}",
        name="Historical synthetic operator",
        description="Historical scope-v2 integrity position template.",
        default_capacity_codes=["staff"],
        role_bundle_id=role_bundle.id,
        created_by_id=actor_id,
    )
    position = historical_position.objects.create(
        organization_id=organization_id,
        edition_id=edition_id,
        template_id=template.id,
        department_id=department.id,
        role_bundle_id=role_bundle.id,
        code=f"historical-operator-{suffix}",
        title="Historical synthetic operator",
        description="Historical position for migration containment tests.",
        capacity_codes=["staff"],
        created_by_id=actor_id,
    )
    return HistoricalWorkforceGraph(
        organization_id=organization_id,
        edition_id=edition_id,
        actor_id=actor_id,
        role_bundle_id=role_bundle.id,
        department=department,
        position=position,
    )


def _advance_structure_control_for_raw_probe(department: Department) -> int:
    """Advance control evidence so a malicious raw update reaches row guards."""

    control = EditionStructureControl.objects.select_for_update().get(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
    )
    next_version = control.aggregate_version + 1
    EditionStructureControl.objects.filter(pk=control.pk).update(
        aggregate_version=next_version
    )
    return next_version


def _raw_reparent_for_probe(*, department: Department, parent: Department) -> None:
    next_version = _advance_structure_control_for_raw_probe(department)
    Department.objects.filter(pk=department.pk).update(
        parent=parent,
        last_changed_in_structure_version=next_version,
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
    child = create_department_for_test(
        edition=graph.edition,
        parent=graph.department,
        name="Synthetic child team",
        expected_code="synthetic-child-team",
        actor=graph.actor,
    )
    other_edition = EventEditionFactory(
        organization=graph.organization,
        series=graph.edition.series,
    )
    foreign_parent = create_department_for_test(
        edition=other_edition,
        name="Synthetic foreign parent",
        expected_code="synthetic-foreign-parent",
        actor=graph.actor,
    )

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match=r"parent (?:scope mismatch|must be active in the exact edition)",
        ),
    ):
        _raw_reparent_for_probe(department=child, parent=foreign_parent)

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match=(
                r"hierarchy (?:cannot contain a cycle|"
                r"exceeds the acyclic depth bound)"
            ),
        ),
    ):
        _raw_reparent_for_probe(department=graph.department, parent=child)


def test_concurrent_department_reparenting_cannot_create_write_skew_cycle() -> None:
    graph = _create_graph()
    peer = create_department_for_test(
        edition=graph.edition,
        name="Synthetic peer team",
        expected_code="synthetic-peer-team",
        actor=graph.actor,
    )
    start = Barrier(2)
    expected_version = EditionStructureControl.objects.values_list(
        "aggregate_version", flat=True
    ).get(
        organization_id=graph.organization.id,
        edition_id=graph.edition.id,
    )

    def reparent(department: Department, parent: Department) -> str:
        close_old_connections()
        try:
            start.wait(timeout=5)
            update_department(
                actor=graph.actor,
                organization_id=graph.organization.id,
                series_id=graph.edition.series_id,
                edition_id=graph.edition.id,
                department_id=department.id,
                name=department.name,
                description=department.description,
                parent_department_id=parent.id,
                display_order=department.display_order,
                expected_version=expected_version,
                reason="Probe concurrent cycle containment.",
                correlation_id=uuid4(),
                source_channel="test",
            )
        except StructureVersionConflictError:
            return "version_conflict"
        finally:
            close_old_connections()
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            executor.submit(reparent, graph.department, peer),
            executor.submit(reparent, peer, graph.department),
        ]

    assert sorted(result.result(timeout=10) for result in results) == [
        "committed",
        "version_conflict",
    ]
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
    foreign_department = create_department_for_test(
        edition=other_edition,
        name="Synthetic foreign position team",
        expected_code="synthetic-foreign-position-team",
        actor=graph.actor,
    )

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match=r"(?i)position department scope mismatch",
        ),
    ):
        Position.objects.filter(pk=graph.position.pk).update(
            department=foreign_department
        )


def test_position_guard_rejects_raw_reporting_cycle() -> None:
    graph = _create_graph()
    report = save_position_for_test(
        position=Position(
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
    scoped_department = create_department_for_test(
        edition=graph.edition,
        name=f"Synthetic scoped authority {authority_kind}",
        expected_code=f"synthetic-scoped-authority-{authority_kind}",
        actor=graph.actor,
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
    create_department_for_test(
        edition=other_edition,
        name=f"Synthetic target scope {authority_kind}",
        expected_code=f"synthetic-target-scope-{authority_kind}",
        actor=graph.actor,
    )

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match=(
                r"orphan scoped authority|"
                r"identity, scope, code, and creation are immutable"
            ),
        ),
    ):
        Department.objects.filter(pk=scoped_department.pk).update(edition=other_edition)


def test_bound_position_scope_cannot_move_through_bulk_update() -> None:
    graph = _create_graph()
    sibling = create_department_for_test(
        edition=graph.edition,
        name="Synthetic sibling team",
        expected_code="synthetic-sibling-team",
        actor=graph.actor,
    )
    ensure_workforce_position_binding(position=graph.position)

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
        binding = ensure_workforce_position_binding(position=graph.position)
    role_assignment = _role_assignment(
        graph,
        principal=account,
        edition=graph.edition,
        department=department,
        resource_binding=binding,
    )

    save_position_assignment_for_test(
        assignment=_proposed_assignment(
            graph,
            account=account,
            role_assignment=role_assignment,
        )
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
        department = create_department_for_test(
            edition=graph.edition,
            name="Synthetic wrong evidence team",
            expected_code="synthetic-wrong-evidence-team",
            actor=graph.actor,
        )
    elif invalid_scope == "sibling_resource":
        edition = graph.edition
        department = graph.department
        other_position = save_position_for_test(
            position=Position(
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
        )
        binding = ensure_workforce_position_binding(position=other_position)
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
    sibling = create_department_for_test(
        edition=graph.edition,
        name="Synthetic wrong linked team",
        expected_code="synthetic-wrong-linked-team",
        actor=graph.actor,
    )
    role_assignment = _role_assignment(
        graph,
        principal=account,
        edition=graph.edition,
    )
    save_position_assignment_for_test(
        assignment=_proposed_assignment(
            graph,
            account=account,
            role_assignment=role_assignment,
        )
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
    actor = AccountFactory()
    edition = EventEditionFactory()
    account = AccountFactory()
    executor = _migrate(AUTHORIZATION_SCHEMA, WORKFORCE_BEFORE)
    historical_apps = executor.loader.project_state(
        [AUTHORIZATION_SCHEMA, WORKFORCE_BEFORE]
    ).apps
    graph = _create_historical_graph(
        historical_apps,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor_id=actor.id,
    )
    historical_role_assignment = historical_apps.get_model(
        "authorization", "RoleAssignment"
    )
    historical_assignment = historical_apps.get_model("workforce", "PositionAssignment")
    role_assignment = historical_role_assignment.objects.create(
        organization_id=graph.organization_id,
        edition_id=graph.edition_id,
        principal_id=account.id,
        role_bundle_id=graph.role_bundle_id,
        effective_from=timezone.now(),
        granted_by_id=graph.actor_id,
        reason="Historical edition-wide workforce role evidence.",
    )
    assignment = historical_assignment.objects.create(
        position_id=graph.position.id,
        organization_id=graph.organization_id,
        edition_id=graph.edition_id,
        account_id=account.id,
        effective_from=timezone.now(),
        proposed_by_id=graph.actor_id,
        reason="Historical proposed workforce assignment.",
        role_assignment_id=role_assignment.id,
    )

    executor = _migrate(WORKFORCE_AFTER)
    after_apps = executor.loader.project_state(
        [AUTHORIZATION_SCHEMA, WORKFORCE_AFTER]
    ).apps
    historical_assignment_after = after_apps.get_model(
        "workforce", "PositionAssignment"
    )
    historical_role_assignment_after = after_apps.get_model(
        "authorization", "RoleAssignment"
    )
    historical_department_after = after_apps.get_model("workforce", "Department")

    assignment_after = historical_assignment_after.objects.get(pk=assignment.id)
    role_assignment_after = historical_role_assignment_after.objects.get(
        pk=role_assignment.id
    )
    assert assignment_after.role_assignment_id == role_assignment_after.id
    assert role_assignment_after.edition_id == graph.edition_id
    assert role_assignment_after.department_id is None
    assert role_assignment_after.resource_binding_id is None

    sibling = historical_department_after.objects.create(
        organization_id=graph.organization_id,
        edition_id=graph.edition_id,
        code="migration-reverse-boundary",
        name="Synthetic migration reverse boundary",
    )
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="no longer matches workforce evidence"),
    ):
        historical_role_assignment_after.objects.filter(
            pk=role_assignment_after.pk
        ).update(department_id=sibling.id)


def test_migration_preflight_rejects_existing_department_cycle() -> None:
    actor = AccountFactory()
    edition = EventEditionFactory()
    executor = _migrate(AUTHORIZATION_SCHEMA, WORKFORCE_BEFORE)
    historical_apps = executor.loader.project_state(
        [AUTHORIZATION_SCHEMA, WORKFORCE_BEFORE]
    ).apps
    graph = _create_historical_graph(
        historical_apps,
        organization_id=edition.organization_id,
        edition_id=edition.id,
        actor_id=actor.id,
    )
    historical_department = historical_apps.get_model("workforce", "Department")
    child = historical_department.objects.create(
        organization_id=graph.organization_id,
        edition_id=graph.edition_id,
        parent=graph.department,
        code="preflight-child",
        name="Synthetic preflight child",
    )
    historical_department.objects.filter(pk=graph.department.pk).update(
        parent_id=child.id
    )

    try:
        with pytest.raises(IntegrityError, match="ADR 0041 workforce blockers"):
            _migrate(WORKFORCE_AFTER)
    finally:
        historical_department.objects.filter(pk=graph.department.pk).update(
            parent_id=None
        )
        _migrate(WORKFORCE_AFTER)
