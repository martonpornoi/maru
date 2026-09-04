"""Opaque Programme dependency checks for Workforce Department retirement."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction

from maru.applications.models import (
    ApplicationDefinitionStatus,
    ProgrammeCall,
    ProgrammeImportBatch,
    ProgrammeImportBatchState,
    ProgrammeImportItemState,
)

if TYPE_CHECKING:
    from uuid import UUID


class ProgrammeDepartmentDependencyState(StrEnum):
    """Describe the closed result of a Department retirement dependency check."""

    CLEAR = "clear"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


def _programme_call_dependency_state(
    *,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
) -> ProgrammeDepartmentDependencyState:
    """Check current Programme-call ownership without disclosing call details.

    Parameters
    ----------
    organization_id : UUID
        The exact organizer scope being changed.
    edition_id : UUID
        The exact event-edition scope being changed.
    department_id : UUID
        The exact owner Department proposed for retirement.

    Returns
    -------
    ProgrammeDepartmentDependencyState
        ``blocked`` when a draft or active call retains the Department,
        ``clear`` when none does, or ``unavailable`` when the database probe
        cannot complete.
    """
    try:
        with transaction.atomic():
            blocked = ProgrammeCall.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                owner_department_id=department_id,
                definition__status__in=(
                    ApplicationDefinitionStatus.DRAFT,
                    ApplicationDefinitionStatus.ACTIVE,
                ),
            ).exists()
    except DatabaseError:
        return ProgrammeDepartmentDependencyState.UNAVAILABLE
    return (
        ProgrammeDepartmentDependencyState.BLOCKED
        if blocked
        else ProgrammeDepartmentDependencyState.CLEAR
    )


def _programme_import_dependency_state(
    *,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
) -> ProgrammeDepartmentDependencyState:
    """Check unresolved Programme imports without disclosing batch details.

    Parameters
    ----------
    organization_id : UUID
        The exact organizer scope being changed.
    edition_id : UUID
        The exact event-edition scope being changed.
    department_id : UUID
        The exact owner Department proposed for retirement.

    Returns
    -------
    ProgrammeDepartmentDependencyState
        ``blocked`` when at least one staged batch retains a staged item,
        ``clear`` when none does, or ``unavailable`` when the database probe
        cannot complete. Import expiry is deliberately irrelevant because it
        never disposes retained private staging data.
    """
    try:
        with transaction.atomic():
            blocked = ProgrammeImportBatch.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                owner_department_id=department_id,
                state=ProgrammeImportBatchState.STAGED,
                items__state=ProgrammeImportItemState.STAGED,
            ).exists()
    except DatabaseError:
        return ProgrammeDepartmentDependencyState.UNAVAILABLE
    return (
        ProgrammeDepartmentDependencyState.BLOCKED
        if blocked
        else ProgrammeDepartmentDependencyState.CLEAR
    )


def programme_department_retirement_dependency_state(
    *,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
) -> ProgrammeDepartmentDependencyState:
    """Return one non-disclosing result for all Programme retirement probes.

    Both independent probes always execute. A known blocker takes precedence
    over an unavailable probe so callers can return a stable conflict without
    revealing which Applications aggregate retained the Department.

    Parameters
    ----------
    organization_id : UUID
        The exact organizer scope being changed.
    edition_id : UUID
        The exact event-edition scope being changed.
    department_id : UUID
        The exact owner Department proposed for retirement.

    Returns
    -------
    ProgrammeDepartmentDependencyState
        The closed aggregate state: ``blocked`` wins, then ``unavailable``,
        otherwise ``clear``.
    """
    probe_arguments = {
        "organization_id": organization_id,
        "edition_id": edition_id,
        "department_id": department_id,
    }
    states = (
        _programme_call_dependency_state(**probe_arguments),
        _programme_import_dependency_state(**probe_arguments),
    )
    if ProgrammeDepartmentDependencyState.BLOCKED in states:
        return ProgrammeDepartmentDependencyState.BLOCKED
    if ProgrammeDepartmentDependencyState.UNAVAILABLE in states:
        return ProgrammeDepartmentDependencyState.UNAVAILABLE
    return ProgrammeDepartmentDependencyState.CLEAR


__all__ = [
    "ProgrammeDepartmentDependencyState",
    "programme_department_retirement_dependency_state",
]
