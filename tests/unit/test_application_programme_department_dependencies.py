"""Unit contract for opaque Programme Department retirement dependencies."""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.applications.models import (
    ApplicationDefinitionStatus,
    ProgrammeCall,
    ProgrammeImportBatch,
    ProgrammeImportBatchState,
    ProgrammeImportItemState,
)
from maru.applications.programme_department_dependencies import (
    ProgrammeDepartmentDependencyState,
    _programme_call_dependency_state,
    _programme_import_dependency_state,
    programme_department_retirement_dependency_state,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000101")
_EDITION_ID = UUID("00000000-0000-0000-0000-000000000102")
_DEPARTMENT_ID = UUID("00000000-0000-0000-0000-000000000103")
_SCOPE = {
    "organization_id": _ORGANIZATION_ID,
    "edition_id": _EDITION_ID,
    "department_id": _DEPARTMENT_ID,
}


@pytest.mark.parametrize(
    ("call_state", "import_state", "expected"),
    [
        (
            ProgrammeDepartmentDependencyState.CLEAR,
            ProgrammeDepartmentDependencyState.CLEAR,
            ProgrammeDepartmentDependencyState.CLEAR,
        ),
        (
            ProgrammeDepartmentDependencyState.CLEAR,
            ProgrammeDepartmentDependencyState.BLOCKED,
            ProgrammeDepartmentDependencyState.BLOCKED,
        ),
        (
            ProgrammeDepartmentDependencyState.CLEAR,
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
        ),
        (
            ProgrammeDepartmentDependencyState.BLOCKED,
            ProgrammeDepartmentDependencyState.CLEAR,
            ProgrammeDepartmentDependencyState.BLOCKED,
        ),
        (
            ProgrammeDepartmentDependencyState.BLOCKED,
            ProgrammeDepartmentDependencyState.BLOCKED,
            ProgrammeDepartmentDependencyState.BLOCKED,
        ),
        (
            ProgrammeDepartmentDependencyState.BLOCKED,
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
            ProgrammeDepartmentDependencyState.BLOCKED,
        ),
        (
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
            ProgrammeDepartmentDependencyState.CLEAR,
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
        ),
        (
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
            ProgrammeDepartmentDependencyState.BLOCKED,
            ProgrammeDepartmentDependencyState.BLOCKED,
        ),
        (
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
            ProgrammeDepartmentDependencyState.UNAVAILABLE,
        ),
    ],
)
def test_dependency_aggregate_is_closed_and_always_runs_both_probes(
    call_state: ProgrammeDepartmentDependencyState,
    import_state: ProgrammeDepartmentDependencyState,
    expected: ProgrammeDepartmentDependencyState,
) -> None:
    """Known blockers win while either unavailable probe otherwise fails closed."""
    with (
        patch(
            "maru.applications.programme_department_dependencies."
            "_programme_call_dependency_state",
            return_value=call_state,
        ) as call_probe,
        patch(
            "maru.applications.programme_department_dependencies."
            "_programme_import_dependency_state",
            return_value=import_state,
        ) as import_probe,
    ):
        result = programme_department_retirement_dependency_state(**_SCOPE)

    assert result is expected
    call_probe.assert_called_once_with(**_SCOPE)
    import_probe.assert_called_once_with(**_SCOPE)


def test_call_probe_uses_only_exact_scope_and_current_call_states() -> None:
    """The call probe must not widen its tenant, edition, owner, or lifecycle scope."""
    queryset = Mock()
    queryset.exists.return_value = True
    with (
        patch(
            "maru.applications.programme_department_dependencies.transaction.atomic",
            return_value=nullcontext(),
        ),
        patch.object(
            ProgrammeCall.objects,
            "filter",
            return_value=queryset,
        ) as query,
    ):
        result = _programme_call_dependency_state(**_SCOPE)

    assert result is ProgrammeDepartmentDependencyState.BLOCKED
    query.assert_called_once_with(
        organization_id=_ORGANIZATION_ID,
        edition_id=_EDITION_ID,
        owner_department_id=_DEPARTMENT_ID,
        definition__status__in=(
            ApplicationDefinitionStatus.DRAFT,
            ApplicationDefinitionStatus.ACTIVE,
        ),
    )


def test_import_probe_uses_only_exact_scope_and_unresolved_staging() -> None:
    """Expiry must not hide a staged batch that still retains private payloads."""
    queryset = Mock()
    queryset.exists.return_value = True
    with (
        patch(
            "maru.applications.programme_department_dependencies.transaction.atomic",
            return_value=nullcontext(),
        ),
        patch.object(
            ProgrammeImportBatch.objects,
            "filter",
            return_value=queryset,
        ) as query,
    ):
        result = _programme_import_dependency_state(**_SCOPE)

    assert result is ProgrammeDepartmentDependencyState.BLOCKED
    query.assert_called_once_with(
        organization_id=_ORGANIZATION_ID,
        edition_id=_EDITION_ID,
        owner_department_id=_DEPARTMENT_ID,
        state=ProgrammeImportBatchState.STAGED,
        items__state=ProgrammeImportItemState.STAGED,
    )


@pytest.mark.parametrize(
    ("probe", "manager_path"),
    [
        (_programme_call_dependency_state, ProgrammeCall.objects),
        (_programme_import_dependency_state, ProgrammeImportBatch.objects),
    ],
)
def test_each_database_probe_closes_its_own_failure(
    probe: Callable[..., ProgrammeDepartmentDependencyState],
    manager_path: object,
) -> None:
    """A database failure becomes an opaque unavailable result, never detail."""
    with (
        patch(
            "maru.applications.programme_department_dependencies.transaction.atomic",
            return_value=nullcontext(),
        ),
        patch.object(
            manager_path,
            "filter",
            side_effect=DatabaseError("private dependency detail"),
        ),
    ):
        result = probe(**_SCOPE)

    assert result is ProgrammeDepartmentDependencyState.UNAVAILABLE
