from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError
from django.utils import timezone
from rest_framework.test import APIClient

from maru.audit.models import AuditEvent
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.models import AuthorityIssuance
from maru.authorization.policy import (
    PolicyDecision,
    current_role_assignment_ids,
    decide,
)
from maru.organizations.queries import executive_board_governance_anchor
from maru.participation.models import Participation
from maru.workforce.models import (
    Department,
    Position,
    PositionAssignment,
    PositionTemplate,
)
from maru.workforce.queries import (
    WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
    StructureProjectionIntegrityError,
    project_edition_structure,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationRepresentationFactory,
    ParticipationCapacityFactory,
    ParticipationFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
    ScopedResourceBindingFactory,
)
from tests.workforce_helpers import (
    apply_builtin_structure_template_for_test,
    create_department_for_test,
    retire_department_for_test,
    save_position_assignment_for_test,
    save_position_for_test,
    update_position_for_test,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _platform_administrator() -> object:
    return AccountFactory(
        display_name="Platform administrator",
        is_staff=True,
        is_superuser=True,
    )


def _url(*, organization_id: UUID, edition_id: UUID) -> str:
    return (
        f"/api/v1/organizations/{organization_id}/"
        f"editions/{edition_id}/workforce/structure"
    )


def _authenticated_client(account: object) -> APIClient:
    client = APIClient()
    client.force_authenticate(account)
    return client


def _create_position(
    *,
    edition: object,
    department: Department,
    actor: object,
    code: str,
    title: str,
    reports_to: Position | None = None,
) -> Position:
    role_bundle = RoleBundleFactory(
        organization=edition.organization,
        code=f"{code}-role",
        name=f"{title} role",
        capability_codes=["workforce.view_structure"],
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code=code,
        name=title,
        description=f"Synthetic {title} template.",
        default_capacity_codes=["staff"],
        role_bundle=role_bundle,
        created_by=actor,
    )
    return save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            reports_to=reports_to,
            role_bundle=role_bundle,
            code=code,
            title=title,
            description=f"Synthetic {title} position.",
            headcount=3,
            capacity_codes=["staff"],
            status=Position.Status.OPEN,
            created_by=actor,
        )
    )


def _assign_position(
    *,
    position: Position,
    account: object,
    actor: object,
    effective_from: object,
    expires_at: object | None = None,
    role_effective_from: object | None = None,
    role_expires_at: object | None = None,
    role_revoked_at: object | None = None,
    role_department: Department | None = None,
    role_resource_binding: object | None = None,
) -> PositionAssignment:
    participation = Participation.objects.filter(
        organization=position.organization,
        edition=position.edition,
        account=account,
    ).first()
    if participation is None:
        participation = ParticipationFactory(
            organization=position.organization,
            edition=position.edition,
            account=account,
        )
    capacity = ParticipationCapacityFactory(
        participation=participation,
        code=position.code,
        label_snapshot=position.title,
    )
    role_assignment = RoleAssignmentFactory(
        organization=position.organization,
        edition=position.edition,
        principal=account,
        role_bundle=position.role_bundle,
        department=role_department,
        resource_binding=role_resource_binding,
        effective_from=role_effective_from or effective_from,
        expires_at=role_expires_at,
        revoked_at=role_revoked_at,
    )
    return save_position_assignment_for_test(
        assignment=PositionAssignment(
            position=position,
            organization=position.organization,
            edition=position.edition,
            account=account,
            status=PositionAssignment.Status.ACTIVE,
            effective_from=effective_from,
            expires_at=expires_at,
            proposed_by=actor,
            approved_by=AccountFactory(),
            reason="Synthetic effective holder evidence.",
            role_assignment=role_assignment,
            participation_capacity=capacity,
        )
    )


def test_structure_projection_composes_minimized_governance_and_nested_tree() -> None:
    platform = _platform_administrator()
    edition = EventEditionFactory(
        name="Marucon 2030",
        series__organization__name="Marucon Organizers",
        series__organization__lifecycle="draft",
    )
    OrganizationRepresentationFactory(
        organization=edition.organization,
        provisioned_by=platform,
    )
    helper = create_department_for_test(
        edition=edition,
        name="Helper Board",
        expected_code="helper-board",
        display_order=10,
        actor=platform,
    )
    later = create_department_for_test(
        edition=edition,
        parent=helper,
        name="Z Later",
        expected_code="z-later",
        display_order=20,
        actor=platform,
    )
    earlier = create_department_for_test(
        edition=edition,
        parent=helper,
        name="A Earlier",
        expected_code="a-earlier",
        display_order=5,
        actor=platform,
    )

    response = _authenticated_client(platform).get(
        _url(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["organization_name"] == "Marucon Organizers"
    assert payload["series_name"] == edition.series.name
    assert payload["edition_name"] == "Marucon 2030"
    assert payload["governance"] == {
        "kind": "governance",
        "label": "Executive Board",
        "state": "provisioning",
    }
    assert payload["structure"]["state"] == "complete"
    assert payload["structure"]["aggregate_version"] == 3
    assert payload["structure"]["source"] == {"kind": "manual"}
    assert len(payload["structure"]["departments"]) == 1
    helper_node = payload["structure"]["departments"][0]
    assert helper_node == {
        "id": str(helper.id),
        "parent_id": None,
        "code": "helper-board",
        "name": "Helper Board",
        "description": "Synthetic current-schema fixture.",
        "display_order": 10,
        "state": "active",
        "positions": [],
        "children": [
            {
                "id": str(earlier.id),
                "parent_id": str(helper.id),
                "code": "a-earlier",
                "name": "A Earlier",
                "description": "Synthetic current-schema fixture.",
                "display_order": 5,
                "state": "active",
                "positions": [],
                "children": [],
            },
            {
                "id": str(later.id),
                "parent_id": str(helper.id),
                "code": "z-later",
                "name": "Z Later",
                "description": "Synthetic current-schema fixture.",
                "display_order": 20,
                "state": "active",
                "positions": [],
                "children": [],
            },
        ],
    }
    assert "appointment" not in str(payload).lower()
    assert "controller" not in str(payload).lower()
    audit = AuditEvent.objects.get(operation="workforce.structure.read")
    assert audit.principal_id == platform.id
    assert audit.organization_id == edition.organization_id
    assert audit.event_edition_id == edition.id
    assert audit.target_id == edition.id
    assert audit.source_channel == "api"
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.safe_metadata == {
        "policy_version": POLICY_VERSION,
        "route_name": "workforce-structure",
        "http_method": "GET",
    }
    assert "audit_sensitive_read" in audit.obligations
    assert "private" in response.headers["Cache-Control"]
    assert "no-store" in response.headers["Cache-Control"]


def test_structure_head_read_audit_records_the_actual_http_method() -> None:
    platform = _platform_administrator()
    edition = EventEditionFactory()

    response = _authenticated_client(platform).head(
        _url(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    )

    assert response.status_code == 200
    assert response.content == b""
    assert "no-store" in response.headers["Cache-Control"]
    audit = AuditEvent.objects.get(operation="workforce.structure.read")
    assert audit.safe_metadata["http_method"] == "HEAD"


def test_builtin_source_is_minimized_and_department_state_is_explicit() -> None:
    platform = _platform_administrator()
    edition = EventEditionFactory(name="Synthetic sourced structure")
    apply_builtin_structure_template_for_test(edition=edition, actor=platform)
    retired = Department.objects.get(edition=edition, code="charity")
    retire_department_for_test(department=retired, actor=platform)

    response = _authenticated_client(platform).get(
        _url(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    )

    assert response.status_code == 200
    structure = response.json()["structure"]
    assert structure["aggregate_version"] == 2
    assert structure["source"] == {
        "kind": "builtin_template",
        "template_code": "marucon-reference",
        "template_version": 1,
    }
    assert "template_digest" not in str(structure)
    child_states = {
        department["code"]: department["state"]
        for department in structure["departments"][0]["children"]
    }
    assert child_states["charity"] == "retired"
    assert child_states["registration"] == "active"


def test_manual_control_source_exposes_no_template_fields() -> None:
    edition = EventEditionFactory()
    actor = _platform_administrator()
    for index in range(3):
        create_department_for_test(
            actor=actor,
            edition=edition,
            name=f"Manual Department {index + 1}",
            expected_code=f"manual-department-{index + 1}",
        )

    projection = project_edition_structure(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )

    assert projection.aggregate_version == 3
    assert asdict(projection.source) == {"kind": "manual"}


def test_incomplete_builtin_source_provenance_fails_closed_without_names() -> None:
    edition = EventEditionFactory(name="Private invalid source")
    platform = _platform_administrator()
    apply_builtin_structure_template_for_test(edition=edition, actor=platform)

    with patch(
        "maru.workforce.queries.EditionStructureCommandReceipt.objects.filter"
    ) as receipt_query:
        ordered_receipts = receipt_query.return_value.values.return_value.order_by
        ordered_receipts.return_value.__getitem__.return_value = []
        response = _authenticated_client(platform).get(
            _url(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            )
        )

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert "Private invalid source" not in response.content.decode()


def test_projection_includes_only_effective_holders_and_display_names() -> None:
    now = timezone.now()
    platform = _platform_administrator()
    edition = EventEditionFactory(name="Minimized holders")
    helper = create_department_for_test(
        edition=edition,
        name="Helper Board",
        expected_code="helper-board",
        actor=platform,
    )
    operations = create_department_for_test(
        edition=edition,
        parent=helper,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    current = AccountFactory(
        email="private-current@example.invalid",
        login_handle="SecretCurrentHandle",
        display_name="Current Helper",
    )
    lead = _create_position(
        edition=edition,
        department=operations,
        actor=platform,
        code="operations-lead",
        title="Operations Lead",
    )
    deputy = _create_position(
        edition=edition,
        department=operations,
        actor=platform,
        code="operations-deputy",
        title="Operations Deputy",
        reports_to=lead,
    )
    _assign_position(
        position=lead,
        account=current,
        actor=platform,
        effective_from=now - timedelta(days=1),
    )
    _assign_position(
        position=deputy,
        account=current,
        actor=platform,
        effective_from=now - timedelta(days=1),
    )

    future = AccountFactory(display_name="Future Helper")
    _assign_position(
        position=_create_position(
            edition=edition,
            department=operations,
            actor=platform,
            code="future-helper",
            title="Future Helper",
        ),
        account=future,
        actor=platform,
        effective_from=now + timedelta(days=1),
    )
    expired = AccountFactory(display_name="Expired Helper")
    _assign_position(
        position=_create_position(
            edition=edition,
            department=operations,
            actor=platform,
            code="expired-helper",
            title="Expired Helper",
        ),
        account=expired,
        actor=platform,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    inactive = AccountFactory(display_name="Inactive Helper", is_active=False)
    _assign_position(
        position=_create_position(
            edition=edition,
            department=operations,
            actor=platform,
            code="inactive-helper",
            title="Inactive Helper",
        ),
        account=inactive,
        actor=platform,
        effective_from=now - timedelta(days=1),
    )
    revoked_role = AccountFactory(display_name="Revoked Role Helper")
    _assign_position(
        position=_create_position(
            edition=edition,
            department=operations,
            actor=platform,
            code="revoked-role-helper",
            title="Revoked Role Helper",
        ),
        account=revoked_role,
        actor=platform,
        effective_from=now - timedelta(days=2),
        role_revoked_at=now - timedelta(days=1),
    )

    projection = project_edition_structure(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        at=now,
    )

    operations_node = projection.departments[0].children[0]
    positions = {position.code: position for position in operations_node.positions}
    lead_holder = positions["operations-lead"].holders[0]
    deputy_holder = positions["operations-deputy"].holders[0]
    assert asdict(lead_holder) == {
        "display_name": "Current Helper",
        "other_roles": (
            {
                "department_name": "Operations",
                "position_title": "Operations Deputy",
            },
        ),
    }
    assert asdict(deputy_holder) == {
        "display_name": "Current Helper",
        "other_roles": (
            {
                "department_name": "Operations",
                "position_title": "Operations Lead",
            },
        ),
    }
    assert positions["operations-deputy"].reports_to_id == lead.id
    assert positions["operations-deputy"].reports_to_title == "Operations Lead"
    holder_names = [
        holder.display_name
        for position in operations_node.positions
        for holder in position.holders
    ]
    assert holder_names == ["Current Helper", "Current Helper"]
    rendered = str(asdict(projection))
    assert "private-current@example.invalid" not in rendered
    assert "SecretCurrentHandle" not in rendered
    assert "Synthetic effective holder evidence" not in rendered


def test_identity_labels_are_resolved_only_after_current_role_validation() -> None:
    now = timezone.now()
    platform = _platform_administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    position = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="helper",
        title="Helper",
    )
    _assign_position(
        position=position,
        account=AccountFactory(display_name="Must stay unread"),
        actor=platform,
        effective_from=now - timedelta(minutes=1),
    )

    with (
        patch(
            "maru.workforce.queries.current_role_assignment_ids",
            return_value=frozenset(),
        ),
        patch("maru.workforce.queries.active_person_account_display_labels") as labels,
    ):
        projection = project_edition_structure(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            at=now,
        )

    labels.assert_not_called()
    assert not projection.departments[0].positions[0].holders


def test_effective_time_intervals_are_half_open_at_one_captured_instant() -> None:
    now = timezone.now()
    platform = _platform_administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    exact_start = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="exact-start",
        title="Exact Start",
    )
    assignment_expiry = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="assignment-expiry",
        title="Assignment Expiry",
    )
    role_expiry = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="role-expiry",
        title="Role Expiry",
    )
    _assign_position(
        position=exact_start,
        account=AccountFactory(display_name="Included at start"),
        actor=platform,
        effective_from=now,
        role_effective_from=now,
    )
    _assign_position(
        position=assignment_expiry,
        account=AccountFactory(display_name="Excluded at assignment expiry"),
        actor=platform,
        effective_from=now - timedelta(minutes=1),
        expires_at=now,
    )
    _assign_position(
        position=role_expiry,
        account=AccountFactory(display_name="Excluded at role expiry"),
        actor=platform,
        effective_from=now - timedelta(minutes=1),
        role_expires_at=now,
    )

    projection = project_edition_structure(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        at=now,
    )

    positions = {
        position.code: position for position in projection.departments[0].positions
    }
    assert [holder.display_name for holder in positions["exact-start"].holders] == [
        "Included at start"
    ]
    assert not positions["assignment-expiry"].holders
    assert not positions["role-expiry"].holders


def test_holder_evidence_accepts_only_the_supported_exact_scope_shapes() -> None:
    now = timezone.now()
    platform = _platform_administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    edition_position = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="edition-role",
        title="Edition role",
    )
    department_position = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="department-role",
        title="Department role",
    )
    resource_position = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="resource-role",
        title="Resource role",
    )
    resource_binding = ScopedResourceBindingFactory(
        department=department,
        resource_id=resource_position.id,
    )
    for position, label, role_department, role_binding in (
        (edition_position, "Edition holder", None, None),
        (department_position, "Department holder", department, None),
        (resource_position, "Resource holder", department, resource_binding),
    ):
        _assign_position(
            position=position,
            account=AccountFactory(display_name=label),
            actor=platform,
            effective_from=now - timedelta(minutes=1),
            role_department=role_department,
            role_resource_binding=role_binding,
        )

    projection = project_edition_structure(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        at=now,
    )

    positions = {
        position.code: position for position in projection.departments[0].positions
    }
    assert positions["edition-role"].holders[0].display_name == "Edition holder"
    assert positions["department-role"].holders[0].display_name == ("Department holder")
    assert positions["resource-role"].holders[0].display_name == "Resource holder"


def test_depth_and_expanded_role_edges_fail_without_partial_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = _platform_administrator()
    edition = EventEditionFactory()
    parent: Department | None = None
    for index in range(3):
        parent = create_department_for_test(
            edition=edition,
            parent=parent,
            name=f"Level {index + 1}",
            expected_code=f"level-{index + 1}",
            display_order=index,
            actor=platform,
        )
    complete = project_edition_structure(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    assert complete.state == "complete"
    monkeypatch.setattr("maru.workforce.queries.MAX_STRUCTURE_DEPTH", 2)
    too_deep = project_edition_structure(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    assert asdict(too_deep) == {
        "state": "structure_limit_exceeded",
        "aggregate_version": 3,
        "source": {"kind": "manual"},
        "departments": (),
    }

    roles_edition = EventEditionFactory()
    department = create_department_for_test(
        edition=roles_edition,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    holder = AccountFactory(display_name="Bounded multi-role holder")
    for index in range(3):
        position = _create_position(
            edition=roles_edition,
            department=department,
            actor=platform,
            code=f"role-{index + 1}",
            title=f"Role {index + 1}",
        )
        _assign_position(
            position=position,
            account=holder,
            actor=platform,
            effective_from=timezone.now() - timedelta(minutes=1),
        )
    monkeypatch.setattr("maru.workforce.queries.MAX_STRUCTURE_OTHER_ROLE_LINKS", 5)
    expanded = project_edition_structure(
        organization_id=roles_edition.organization_id,
        edition_id=roles_edition.id,
    )
    assert asdict(expanded) == {
        "state": "structure_limit_exceeded",
        "aggregate_version": 1,
        "source": {"kind": "manual"},
        "departments": (),
    }
    assert "Bounded multi-role holder" not in str(asdict(expanded))


def test_closed_reporting_parent_remains_in_the_complete_position_graph() -> None:
    platform = _platform_administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    manager = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="manager",
        title="Manager",
    )
    child = _create_position(
        edition=edition,
        department=department,
        actor=platform,
        code="helper",
        title="Helper",
        reports_to=manager,
    )
    manager.status = Position.Status.CLOSED
    update_position_for_test(
        position=manager,
        update_fields=("status", "updated_at"),
    )

    projection = project_edition_structure(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )

    positions = {
        position.code: position for position in projection.departments[0].positions
    }
    assert positions["manager"].status == Position.Status.CLOSED
    assert positions["helper"].reports_to_id == child.reports_to_id
    assert positions["helper"].reports_to_title == "Manager"


def test_reporting_graph_depth_is_bounded_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    platform = _platform_administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    parent: Position | None = None
    for index in range(3):
        parent = _create_position(
            edition=edition,
            department=department,
            actor=platform,
            code=f"reporting-level-{index + 1}",
            title=f"Reporting level {index + 1}",
            reports_to=parent,
        )
    monkeypatch.setattr("maru.workforce.queries.MAX_STRUCTURE_DEPTH", 2)

    projection = project_edition_structure(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )

    assert asdict(projection) == {
        "state": "structure_limit_exceeded",
        "aggregate_version": 1,
        "source": {"kind": "manual"},
        "departments": (),
    }


def test_structure_projection_query_count_is_row_count_independent(
    django_assert_max_num_queries: Callable[[int], AbstractContextManager[None]],
) -> None:
    empty = EventEditionFactory()
    with django_assert_max_num_queries(3):
        empty_projection = project_edition_structure(
            organization_id=empty.organization_id,
            edition_id=empty.id,
        )
    assert empty_projection.state == "complete"
    assert asdict(empty_projection.source) == {"kind": "empty"}
    assert empty_projection.aggregate_version == 0

    now = timezone.now()
    platform = _platform_administrator()
    populated = EventEditionFactory()
    department = create_department_for_test(
        edition=populated,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    holder = AccountFactory(display_name="Multi-role query holder")
    for index in range(3):
        position = _create_position(
            edition=populated,
            department=department,
            actor=platform,
            code=f"query-role-{index + 1}",
            title=f"Query role {index + 1}",
        )
        _assign_position(
            position=position,
            account=holder,
            actor=platform,
            effective_from=now - timedelta(minutes=1),
        )
    with django_assert_max_num_queries(12):
        populated_projection = project_edition_structure(
            organization_id=populated.organization_id,
            edition_id=populated.id,
            at=now,
        )
    assert populated_projection.state == "complete"
    assert (
        sum(
            len(position.holders)
            for position in populated_projection.departments[0].positions
        )
        == 3
    )


def test_structure_access_matrix_is_exact_and_department_scope_is_too_narrow() -> None:
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    viewer = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=viewer,
        capability_code="workforce.view_structure",
    )
    department_only = AccountFactory()
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        principal=department_only,
        capability_code="workforce.view_structure",
    )
    inactive = AccountFactory(is_active=False)
    CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=inactive,
        capability_code="workforce.view_structure",
    )
    url = _url(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )

    assert _authenticated_client(_platform_administrator()).get(url).status_code == 200
    assert _authenticated_client(viewer).get(url).status_code == 200
    assert _authenticated_client(department_only).get(url).status_code == 403
    assert _authenticated_client(inactive).get(url).status_code == 403
    assert _authenticated_client(AccountFactory()).get(url).status_code == 403
    assert APIClient().get(url).status_code == 403
    assert (
        _authenticated_client(_platform_administrator())
        .get(_url(organization_id=uuid4(), edition_id=edition.id))
        .status_code
        == 403
    )


def test_denial_happens_before_name_queries_and_success_repeats_exact_decision() -> (
    None
):
    edition = EventEditionFactory(name="Must not be disclosed")
    outsider = AccountFactory()
    url = _url(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    with patch.object(
        EventEditionFactory._meta.model.objects, "select_related"
    ) as load:
        response = _authenticated_client(outsider).get(url)
    assert response.status_code == 403
    load.assert_not_called()
    assert "Must not be disclosed" not in response.content.decode()

    platform = _platform_administrator()
    with patch("maru.workforce.api.decide", wraps=decide) as repeated:
        success = _authenticated_client(platform).get(url)
    assert success.status_code == 200
    assert repeated.call_count == 2


def test_incomplete_abstract_field_ceiling_fails_closed_before_projection() -> None:
    edition = EventEditionFactory()
    platform = _platform_administrator()
    incomplete = PolicyDecision(
        allowed=True,
        fields=frozenset({"departments", "positions"}),
        obligations=frozenset(),
        reason_code="synthetic_incomplete_ceiling",
    )
    with (
        patch("maru.workforce.api.decide", return_value=incomplete),
        patch("maru.workforce.api.project_edition_structure") as projector,
    ):
        response = _authenticated_client(platform).get(
            _url(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            )
        )

    assert response.status_code == 403
    assert response.json()["code"] == "field_projection_denied"
    projector.assert_not_called()
    assert (
        frozenset(
            {
                "departments",
                "positions",
                "assignment_counts",
                "holder_display_labels",
                "structure_control",
            }
        )
        == WORKFORCE_STRUCTURE_REQUIRED_FIELDS
    )


@pytest.mark.parametrize(
    ("ceiling_name", "setup_kind"),
    [
        ("MAX_STRUCTURE_DEPARTMENTS", "department"),
        ("MAX_STRUCTURE_POSITIONS", "position"),
        ("MAX_STRUCTURE_EFFECTIVE_HOLDERS", "holder"),
    ],
)
def test_each_code_owned_ceiling_returns_generic_overflow_without_partial_rows(
    monkeypatch: pytest.MonkeyPatch,
    ceiling_name: str,
    setup_kind: str,
) -> None:
    platform = _platform_administrator()
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
        actor=platform,
    )
    if setup_kind in {"position", "holder"}:
        position = _create_position(
            edition=edition,
            department=department,
            actor=platform,
            code="helper",
            title="Helper",
        )
        if setup_kind == "holder":
            _assign_position(
                position=position,
                account=AccountFactory(display_name="Hidden by overflow"),
                actor=platform,
                effective_from=timezone.now() - timedelta(minutes=1),
            )
    monkeypatch.setattr(f"maru.workforce.queries.{ceiling_name}", 0)

    response = _authenticated_client(platform).get(
        _url(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    )

    assert response.status_code == 200
    assert response.json()["structure"] == {
        "state": "structure_limit_exceeded",
        "aggregate_version": 1,
        "source": {"kind": "manual"},
        "departments": [],
    }
    assert "Hidden by overflow" not in response.content.decode()


def test_projection_integrity_and_database_failures_use_safe_503_problem() -> None:
    edition = EventEditionFactory(name="Private tenant edition")
    platform = _platform_administrator()
    url = _url(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    for failure in (
        StructureProjectionIntegrityError("private hierarchy detail"),
        DatabaseError("private database detail"),
    ):
        with patch(
            "maru.workforce.api.project_edition_structure",
            side_effect=failure,
        ):
            response = _authenticated_client(platform).get(url)
        assert response.status_code == 503
        assert response.headers["Content-Type"].startswith("application/problem+json")
        assert response.json()["code"] == "service_unavailable"
        rendered = response.content.decode()
        assert "Private tenant edition" not in rendered
        assert "private hierarchy detail" not in rendered
        assert "private database detail" not in rendered


def test_structure_audit_failure_prevents_api_projection_release() -> None:
    edition = EventEditionFactory(name="Private unaudited edition")
    platform = _platform_administrator()

    with patch(
        "maru.workforce.api.append_structure_read_audit",
        side_effect=DatabaseError("private audit detail"),
    ):
        response = _authenticated_client(platform).get(
            _url(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            )
        )

    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("application/problem+json")
    assert response.json()["code"] == "service_unavailable"
    rendered = response.content.decode()
    assert "Private unaudited edition" not in rendered
    assert "private audit detail" not in rendered


def test_structure_get_rejects_unknown_query_fields() -> None:
    edition = EventEditionFactory()
    response = _authenticated_client(_platform_administrator()).get(
        _url(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
        {"include_private": "true"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "unknown_input_field"
    assert "private" in response.headers["Cache-Control"]
    assert "no-store" in response.headers["Cache-Control"]


def test_second_structure_version_movement_returns_503_without_audit_or_names() -> None:
    edition = EventEditionFactory(name="Private moving structure")
    platform = _platform_administrator()
    with (
        patch(
            "maru.workforce.structure_snapshot.current_structure_version",
            side_effect=(1, 2),
        ) as probe,
        patch(
            "maru.workforce.api.project_edition_structure",
            wraps=project_edition_structure,
        ) as projector,
        patch("maru.workforce.api.append_structure_read_audit") as audit,
    ):
        response = _authenticated_client(platform).get(
            _url(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            )
        )

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert "Private moving structure" not in response.content.decode()
    assert probe.call_count == 2
    assert projector.call_count == 2
    audit.assert_not_called()


def test_api_uses_one_projection_instant_and_fresh_final_authorization() -> None:
    edition = EventEditionFactory()
    platform = _platform_administrator()
    projection_at = timezone.now()
    response_check_at = projection_at + timedelta(milliseconds=1)

    with (
        patch(
            "maru.workforce.api.timezone_now",
            side_effect=(projection_at, response_check_at),
        ),
        patch(
            "maru.workforce.api.project_edition_structure",
            wraps=project_edition_structure,
        ) as projector,
        patch("maru.workforce.api.decide", wraps=decide) as policy,
    ):
        response = _authenticated_client(platform).get(
            _url(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            )
        )

    assert response.status_code == 200
    assert projector.call_args.kwargs["at"] == projection_at
    assert [call.kwargs["at"] for call in policy.call_args_list] == [
        projection_at,
        response_check_at,
    ]


def test_structure_openapi_is_recursive_bounded_and_problem_typed() -> None:
    response = _authenticated_client(_platform_administrator()).get(
        "/api/v1/schema",
        HTTP_ACCEPT="application/vnd.oai.openapi+json",
    )

    assert response.status_code == 200
    schema = response.json()
    operation = schema["paths"][
        (
            "/api/v1/organizations/{organization_id}/editions/{edition_id}/"
            "workforce/structure"
        )
    ]["get"]
    assert set(operation["responses"]) == {"200", "400", "403", "503"}
    for status in ("400", "403", "503"):
        problem = operation["responses"][status]["content"]["application/problem+json"][
            "schema"
        ]
        assert problem == {"$ref": "#/components/schemas/WorkforceProblem"}

    components = schema["components"]["schemas"]
    department = components["WorkforceStructureDepartment"]
    assert department["properties"]["children"] == {
        "type": "array",
        "items": {
            "$ref": "#/components/schemas/WorkforceStructureDepartment",
        },
        "readOnly": True,
    }

    def enum_values(property_schema: dict[str, object]) -> set[str]:
        if "enum" in property_schema:
            return set(property_schema["enum"])  # type: ignore[arg-type]
        reference = property_schema.get("$ref")
        if reference is None:
            reference = property_schema["allOf"][0]["$ref"]  # type: ignore[index]
        component_name = str(reference).rsplit("/", maxsplit=1)[-1]
        return set(components[component_name]["enum"])

    assert enum_values(
        components["WorkforceStructureGovernance"]["properties"]["state"]
    ) == {"absent", "provisioning", "active", "suspended"}
    assert enum_values(
        components["WorkforceStructureProjection"]["properties"]["state"]
    ) == {"complete", "structure_limit_exceeded"}
    assert enum_values(
        components["WorkforceStructureGovernance"]["properties"]["kind"]
    ) == {"governance"}
    assert enum_values(
        components["WorkforceStructurePosition"]["properties"]["status"]
    ) == set(Position.Status.values)
    assert enum_values(
        components["WorkforceStructureDepartment"]["properties"]["state"]
    ) == {"active", "retired"}
    source = components["WorkforceStructureSource"]
    source_variants = {
        "empty": "WorkforceStructureEmptySource",
        "manual": "WorkforceStructureManualSource",
        "legacy_existing": "WorkforceStructureLegacySource",
        "builtin_template": "WorkforceStructureBuiltinTemplateSource",
    }
    assert source["oneOf"] == [
        {"$ref": f"#/components/schemas/{component_name}"}
        for component_name in source_variants.values()
    ]
    assert source["discriminator"] == {
        "propertyName": "kind",
        "mapping": {
            kind: f"#/components/schemas/{component_name}"
            for kind, component_name in source_variants.items()
        },
    }
    for kind, component_name in source_variants.items():
        variant = components[component_name]
        expected_properties = (
            {"kind", "template_code", "template_version"}
            if kind == "builtin_template"
            else {"kind"}
        )
        assert set(variant["properties"]) == expected_properties
        assert set(variant["required"]) == expected_properties
        assert enum_values(variant["properties"]["kind"]) == {kind}
    assert (
        components["WorkforceStructureBuiltinTemplateSource"]["properties"][
            "template_version"
        ]["minimum"]
        == 1
    )
    assert components["WorkforceStructureProjection"]["properties"]["source"] == {
        "$ref": "#/components/schemas/WorkforceStructureSource"
    }
    assert {
        "state",
        "aggregate_version",
        "source",
        "departments",
    }.issubset(components["WorkforceStructureProjection"]["required"])


def test_governance_anchor_is_absent_or_fixed_and_identity_free() -> None:
    edition = EventEditionFactory(series__organization__lifecycle="draft")
    assert asdict(
        executive_board_governance_anchor(
            organization_id=edition.organization_id,
        )
    ) == {
        "kind": "governance",
        "label": "Executive Board",
        "state": "absent",
    }
    representation = OrganizationRepresentationFactory(
        organization=edition.organization,
        provisioned_by=_platform_administrator(),
        provisioning_reason="Private reason that must not leave the module.",
    )
    assert asdict(
        executive_board_governance_anchor(
            organization_id=edition.organization_id,
        )
    ) == {
        "kind": "governance",
        "label": "Executive Board",
        "state": "provisioning",
    }
    assert representation.provisioning_reason not in str(
        executive_board_governance_anchor(
            organization_id=edition.organization_id,
        )
    )


def test_public_role_currentness_query_supports_dormant_and_malformed_fences() -> None:
    now = timezone.now()
    organization = EventEditionFactory().organization
    current = RoleAssignmentFactory(
        organization=organization,
        role_bundle=RoleBundleFactory(organization=organization),
        effective_from=now - timedelta(minutes=5),
    )
    future = RoleAssignmentFactory(
        organization=organization,
        role_bundle=RoleBundleFactory(organization=organization),
        effective_from=now + timedelta(minutes=5),
    )
    with patch(
        "maru.authorization.policy._exact_lineage_policy_state",
        return_value=(False, False),
    ):
        assert current_role_assignment_ids(
            assignment_ids=(current.id, future.id),
            at=now,
        ) == frozenset({current.id})
    with patch(
        "maru.authorization.policy._exact_lineage_policy_state",
        return_value=(True, False),
    ):
        assert not current_role_assignment_ids(
            assignment_ids=(current.id,),
            at=now,
        )


def test_public_role_currentness_query_batches_exact_pinned_issuances() -> None:
    now = timezone.now()
    edition = EventEditionFactory()
    assignment = RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        role_bundle=RoleBundleFactory(
            organization=edition.organization,
            capability_codes=["workforce.view_structure"],
        ),
        effective_from=now - timedelta(minutes=5),
    )
    issuance = AuthorityIssuance.objects.create(
        role_assignment=assignment,
        policy_version=POLICY_VERSION,
        evaluated_at=now,
    )
    with (
        patch(
            "maru.authorization.policy._exact_lineage_policy_state",
            return_value=(True, True),
        ),
        patch(
            "maru.authorization.policy.authority_issuances_are_current",
            return_value=(True,),
        ) as validator,
    ):
        result = current_role_assignment_ids(
            assignment_ids=(assignment.id,),
            at=now,
        )

    assert result == frozenset({assignment.id})
    validator.assert_called_once()
    check = validator.call_args.kwargs["checks"][0]
    assert check.issuance_ordinal == issuance.ordinal
    assert check.principal_id == assignment.principal_id
    assert check.capability_code == "workforce.view_structure"
