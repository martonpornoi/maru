"""Small contract tests for minimized authorization-owned query results."""

from dataclasses import FrozenInstanceError, fields

import pytest

from maru.authorization.queries import DepartmentAuthorityDependencies


def test_department_authority_dependencies_is_frozen_and_identifier_free() -> None:
    dependencies = DepartmentAuthorityDependencies(
        resource_binding_count=1,
        capability_grant_reference_count=2,
        effective_capability_grant_count=1,
        current_or_future_capability_grant_count=2,
        role_assignment_reference_count=3,
        effective_role_assignment_count=0,
        current_or_future_role_assignment_count=1,
    )

    assert tuple(field.name for field in fields(dependencies)) == (
        "resource_binding_count",
        "capability_grant_reference_count",
        "effective_capability_grant_count",
        "current_or_future_capability_grant_count",
        "role_assignment_reference_count",
        "effective_role_assignment_count",
        "current_or_future_role_assignment_count",
    )
    assert dependencies.has_resource_binding_history is True
    assert dependencies.has_effective_capability_grant is True
    assert dependencies.has_effective_role_assignment is False
    assert dependencies.has_current_or_future_capability_grant is True
    assert dependencies.has_current_or_future_role_assignment is True
    assert dependencies.has_historical_authority_reference is True
    assert not hasattr(dependencies, "reason")
    assert not hasattr(dependencies, "label")

    with pytest.raises(FrozenInstanceError):
        dependencies.resource_binding_count = 0  # type: ignore[misc]


def test_department_authority_dependency_flags_are_false_for_empty_counts() -> None:
    dependencies = DepartmentAuthorityDependencies(
        resource_binding_count=0,
        capability_grant_reference_count=0,
        effective_capability_grant_count=0,
        current_or_future_capability_grant_count=0,
        role_assignment_reference_count=0,
        effective_role_assignment_count=0,
        current_or_future_role_assignment_count=0,
    )

    assert dependencies.has_resource_binding_history is False
    assert dependencies.has_effective_capability_grant is False
    assert dependencies.has_effective_role_assignment is False
    assert dependencies.has_current_or_future_capability_grant is False
    assert dependencies.has_current_or_future_role_assignment is False
    assert dependencies.has_historical_authority_reference is False
