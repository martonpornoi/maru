"""Exact-scope coverage for Page 9 Department authority dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from maru.authorization.bindings import ensure_workforce_position_binding
from maru.authorization.queries import (
    DepartmentAuthorityDependencies,
    department_authority_dependencies,
)
from maru.workforce.models import Department, Position, PositionTemplate
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_for_test,
)

if TYPE_CHECKING:
    from maru.authorization.models import RoleBundle, ScopedResourceBinding
    from maru.events.models import EventEdition
    from maru.identity.models import Account

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _DepartmentScope:
    edition: EventEdition
    department: Department


def _department_scope(*, code: str = "operations") -> _DepartmentScope:
    edition = EventEditionFactory()
    department = create_department_for_test(
        edition=edition,
        name=code.replace("-", " ").title(),
        expected_code=code,
    )
    return _DepartmentScope(edition=edition, department=department)


def _position_binding(
    scope: _DepartmentScope,
    *,
    code: str,
) -> tuple[ScopedResourceBinding, RoleBundle]:
    creator: Account = AccountFactory()
    role_bundle = RoleBundleFactory(organization=scope.edition.organization)
    template = PositionTemplate.objects.create(
        organization=scope.edition.organization,
        code=f"{code}-template",
        name=f"{code.title()} template",
        description="Synthetic dependency-query template.",
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        created_by=creator,
    )
    position = save_position_for_test(
        position=Position(
            organization=scope.edition.organization,
            edition=scope.edition,
            template=template,
            department=scope.department,
            role_bundle=role_bundle,
            code=code,
            title=code.replace("-", " ").title(),
            description="Synthetic dependency-query position.",
            capacity_codes=["volunteer"],
            created_by=creator,
        )
    )
    return ensure_workforce_position_binding(position=position), role_bundle


def _query(
    scope: _DepartmentScope,
    *,
    at: datetime,
) -> DepartmentAuthorityDependencies:
    return department_authority_dependencies(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        department_id=scope.department.id,
        at=at,
    )


def test_dependency_query_counts_direct_and_resource_authority_in_exact_scope() -> None:
    at = datetime(2035, 2, 3, 12, tzinfo=UTC)
    target = _department_scope()
    binding, role_bundle = _position_binding(target, code="operations-lead")

    CapabilityGrantFactory(
        organization=target.edition.organization,
        edition=target.edition,
        department=target.department,
        effective_from=at - timedelta(days=1),
    )
    CapabilityGrantFactory(
        organization=target.edition.organization,
        edition=target.edition,
        department=target.department,
        resource_binding=binding,
        effective_from=at - timedelta(days=1),
    )
    RoleAssignmentFactory(
        role_bundle=role_bundle,
        edition=target.edition,
        department=target.department,
        effective_from=at - timedelta(days=1),
    )
    RoleAssignmentFactory(
        role_bundle=role_bundle,
        edition=target.edition,
        department=target.department,
        resource_binding=binding,
        effective_from=at - timedelta(days=1),
    )

    sibling = create_department_for_test(
        edition=target.edition,
        name="Logistics",
        expected_code="logistics",
    )
    sibling_scope = _DepartmentScope(
        edition=target.edition,
        department=sibling,
    )
    sibling_binding, sibling_role = _position_binding(
        sibling_scope,
        code="logistics-lead",
    )
    CapabilityGrantFactory(
        organization=target.edition.organization,
        edition=target.edition,
        department=sibling,
        resource_binding=sibling_binding,
        effective_from=at - timedelta(days=1),
    )
    RoleAssignmentFactory(
        role_bundle=sibling_role,
        edition=target.edition,
        department=sibling,
        effective_from=at - timedelta(days=1),
    )

    dependencies = _query(target, at=at)

    assert dependencies.resource_binding_count == 1
    assert dependencies.capability_grant_reference_count == 2
    assert dependencies.effective_capability_grant_count == 2
    assert dependencies.current_or_future_capability_grant_count == 2
    assert dependencies.role_assignment_reference_count == 2
    assert dependencies.effective_role_assignment_count == 2
    assert dependencies.current_or_future_role_assignment_count == 2
    assert dependencies.has_resource_binding_history is True
    assert dependencies.has_effective_capability_grant is True
    assert dependencies.has_effective_role_assignment is True
    assert dependencies.has_historical_authority_reference is True


def test_dependency_query_excludes_foreign_and_impossible_scope_tuples() -> None:
    at = datetime(2035, 2, 3, 12, tzinfo=UTC)
    target = _department_scope(code="target")
    foreign = _department_scope(code="foreign")
    foreign_binding, foreign_role = _position_binding(foreign, code="foreign-lead")
    CapabilityGrantFactory(
        organization=foreign.edition.organization,
        edition=foreign.edition,
        department=foreign.department,
        resource_binding=foreign_binding,
        effective_from=at - timedelta(days=1),
    )
    RoleAssignmentFactory(
        role_bundle=foreign_role,
        edition=foreign.edition,
        department=foreign.department,
        effective_from=at - timedelta(days=1),
    )

    target_dependencies = _query(target, at=at)
    impossible_dependencies = department_authority_dependencies(
        organization_id=target.edition.organization_id,
        edition_id=foreign.edition.id,
        department_id=foreign.department.id,
        at=at,
    )

    assert target_dependencies.resource_binding_count == 0
    assert target_dependencies.capability_grant_reference_count == 0
    assert target_dependencies.effective_capability_grant_count == 0
    assert target_dependencies.current_or_future_capability_grant_count == 0
    assert target_dependencies.role_assignment_reference_count == 0
    assert target_dependencies.effective_role_assignment_count == 0
    assert target_dependencies.current_or_future_role_assignment_count == 0
    assert impossible_dependencies == target_dependencies


def test_dependency_query_retains_history_but_excludes_noncurrent_terms() -> None:
    at = datetime(2035, 2, 3, 12, tzinfo=UTC)
    scope = _department_scope()
    role_bundle = RoleBundleFactory(organization=scope.edition.organization)

    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        department=scope.department,
        effective_from=at - timedelta(days=1),
    )
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        department=scope.department,
        effective_from=at - timedelta(days=2),
        expires_at=at,
    )
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        department=scope.department,
        effective_from=at - timedelta(days=2),
        revoked_at=at - timedelta(minutes=1),
    )
    CapabilityGrantFactory(
        organization=scope.edition.organization,
        edition=scope.edition,
        department=scope.department,
        effective_from=at + timedelta(minutes=1),
    )
    RoleAssignmentFactory(
        role_bundle=role_bundle,
        edition=scope.edition,
        department=scope.department,
        effective_from=at - timedelta(days=1),
    )
    RoleAssignmentFactory(
        role_bundle=role_bundle,
        edition=scope.edition,
        department=scope.department,
        effective_from=at - timedelta(days=2),
        expires_at=at,
    )
    RoleAssignmentFactory(
        role_bundle=role_bundle,
        edition=scope.edition,
        department=scope.department,
        effective_from=at - timedelta(days=2),
        revoked_at=at - timedelta(minutes=1),
    )
    RoleAssignmentFactory(
        role_bundle=role_bundle,
        edition=scope.edition,
        department=scope.department,
        effective_from=at + timedelta(minutes=1),
    )

    dependencies = _query(scope, at=at)

    assert dependencies.capability_grant_reference_count == 4
    assert dependencies.effective_capability_grant_count == 1
    assert dependencies.current_or_future_capability_grant_count == 2
    assert dependencies.role_assignment_reference_count == 4
    assert dependencies.effective_role_assignment_count == 1
    assert dependencies.current_or_future_role_assignment_count == 2
    assert dependencies.has_historical_authority_reference is True


def test_dependency_query_captures_default_evaluation_time_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = datetime(2035, 2, 3, 12, tzinfo=UTC)
    scope = _department_scope()
    calls = 0

    def now() -> datetime:
        nonlocal calls
        calls += 1
        return at

    monkeypatch.setattr("maru.authorization.queries.timezone.now", now)

    dependencies = department_authority_dependencies(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        department_id=scope.department.id,
    )

    assert calls == 1
    assert dependencies.has_historical_authority_reference is False


def test_dependency_query_rejects_a_naive_evaluation_time() -> None:
    scope = _department_scope()

    with pytest.raises(ValueError, match="must be aware"):
        department_authority_dependencies(
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            department_id=scope.department.id,
            at=datetime(2035, 2, 3, 12),  # noqa: DTZ001 - deliberate invalid input
        )
