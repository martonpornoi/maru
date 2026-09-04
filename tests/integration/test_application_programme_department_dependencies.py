"""PostgreSQL acceptance for opaque Programme retirement dependency probes."""

from __future__ import annotations

from typing import Never
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection

from maru.applications import programme_department_dependencies as dependencies
from maru.applications.models import ProgrammeCall, ProgrammeImportBatch
from maru.applications.programme_department_dependencies import (
    ProgrammeDepartmentDependencyState,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _fail_filter_inside_database(**_kwargs: object) -> Never:
    """Mark the active savepoint failed with a real PostgreSQL error."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 / 0")
    raise AssertionError("PostgreSQL division by zero unexpectedly succeeded.")


def _assert_connection_is_usable() -> None:
    """Prove the failed probe rolled back only its private savepoint."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)


def test_call_database_failure_does_not_skip_the_import_probe() -> None:
    """A failed call probe must not poison or skip the independent import probe."""
    scope = {
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "department_id": uuid4(),
    }
    with (
        patch.object(
            ProgrammeCall.objects,
            "filter",
            side_effect=_fail_filter_inside_database,
        ),
        patch.object(
            dependencies,
            "_programme_import_dependency_state",
            wraps=dependencies._programme_import_dependency_state,
        ) as import_probe,
    ):
        result = dependencies.programme_department_retirement_dependency_state(
            **scope,
        )

    assert result is ProgrammeDepartmentDependencyState.UNAVAILABLE
    import_probe.assert_called_once_with(**scope)
    _assert_connection_is_usable()


def test_import_database_failure_follows_a_completed_call_probe() -> None:
    """A failed import probe must retain the call result and close unavailable."""
    scope = {
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "department_id": uuid4(),
    }
    with (
        patch.object(
            dependencies,
            "_programme_call_dependency_state",
            wraps=dependencies._programme_call_dependency_state,
        ) as call_probe,
        patch.object(
            ProgrammeImportBatch.objects,
            "filter",
            side_effect=_fail_filter_inside_database,
        ),
    ):
        result = dependencies.programme_department_retirement_dependency_state(
            **scope,
        )

    assert result is ProgrammeDepartmentDependencyState.UNAVAILABLE
    call_probe.assert_called_once_with(**scope)
    _assert_connection_is_usable()
