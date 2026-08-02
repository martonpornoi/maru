"""Pure complete-tree checks used by the Page 9a.1 command boundary."""

from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.workforce.models import Department
from maru.workforce.structure_commands import (
    StructureLimitConflictError,
    _has_deletion_dependencies,
    _validate_resulting_hierarchy,
)


def _department(*, parent_id=None):  # type: ignore[no-untyped-def]
    return Department(id=uuid4(), parent_id=parent_id)


def test_complete_hierarchy_rejects_a_cycle() -> None:
    first = _department()
    second = _department(parent_id=first.id)
    first.parent_id = second.id

    with pytest.raises(ValidationError) as caught:
        _validate_resulting_hierarchy((first, second))

    assert caught.value.error_dict["parent_department_id"][0].code == (
        "structure_department_cycle"
    )


def test_complete_hierarchy_rejects_depth_above_the_projection_ceiling() -> None:
    departments: list[Department] = []
    parent_id = None
    for _index in range(33):
        department = _department(parent_id=parent_id)
        departments.append(department)
        parent_id = department.id

    with pytest.raises(StructureLimitConflictError) as caught:
        _validate_resulting_hierarchy(tuple(departments))

    assert caught.value.reason_code == "structure_limit_exceeded"


def test_complete_hierarchy_rejects_more_than_256_departments() -> None:
    departments = tuple(_department() for _index in range(257))

    with pytest.raises(StructureLimitConflictError) as caught:
        _validate_resulting_hierarchy(departments)

    assert caught.value.reason_code == "structure_limit_exceeded"


def test_legacy_department_without_creation_evidence_is_never_deletable() -> None:
    legacy = _department()

    assert _has_deletion_dependencies(object(), legacy) is True  # type: ignore[arg-type]
