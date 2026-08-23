"""Current-schema workforce setup helpers for integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.db import transaction

from maru.workforce.edition_write_scope import (
    lock_active_department_write_target,
    lock_workforce_edition_write_scope,
)
from maru.workforce.models import (
    Department,
    EditionStructureControl,
    Position,
    PositionAssignment,
)
from maru.workforce.structure_commands import (
    BuiltinStructureTemplateResult,
    apply_builtin_structure_template,
    create_department,
    retire_department,
)
from maru.workforce.structure_templates import MARUCON_REFERENCE_V1
from tests.factories import AccountFactory

if TYPE_CHECKING:
    from maru.events.models import EventEdition
    from maru.identity.models import Account


def create_department_for_test(
    *,
    edition: EventEdition,
    name: str,
    expected_code: str,
    parent: Department | None = None,
    display_order: int = 0,
    actor: Account | None = None,
) -> Department:
    """Create one Department through the governed structure command."""

    platform_actor = actor or AccountFactory(is_staff=True, is_superuser=True)
    current_version = (
        EditionStructureControl.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        .values_list("aggregate_version", flat=True)
        .first()
        or 0
    )
    result = create_department(
        actor=platform_actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        name=name,
        description="Synthetic current-schema fixture.",
        parent_department_id=parent.id if parent is not None else None,
        display_order=display_order,
        expected_version=current_version,
        reason="Create a synthetic current-schema Department fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    department = Department.objects.get(id=result.department_id)
    assert department.code == expected_code
    return department


def apply_builtin_structure_template_for_test(
    *,
    edition: EventEdition,
    actor: Account | None = None,
) -> BuiltinStructureTemplateResult:
    """Apply the immutable reference template through the structure command."""

    platform_actor = actor or AccountFactory(is_staff=True, is_superuser=True)
    current_version = (
        EditionStructureControl.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        .values_list("aggregate_version", flat=True)
        .first()
        or 0
    )
    return apply_builtin_structure_template(
        actor=platform_actor,
        organization_id=edition.organization_id,
        series_id=edition.series_id,
        edition_id=edition.id,
        template_identifier=MARUCON_REFERENCE_V1.identifier,
        expected_version=current_version,
        confirmation_name=edition.name,
        reason="Apply the synthetic current-schema structure fixture.",
        retry_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def retire_department_for_test(
    *,
    department: Department,
    actor: Account | None = None,
) -> Department:
    """Retire one dependency-free Department through the structure command."""

    platform_actor = actor or AccountFactory(is_staff=True, is_superuser=True)
    current_version = EditionStructureControl.objects.values_list(
        "aggregate_version", flat=True
    ).get(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
    )
    retire_department(
        actor=platform_actor,
        organization_id=department.organization_id,
        series_id=department.edition.series_id,
        edition_id=department.edition_id,
        department_id=department.id,
        expected_version=current_version,
        reason="Retire a synthetic current-schema Department fixture.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    department.refresh_from_db()
    return department


def save_position_for_test(*, position: Position) -> Position:
    """Insert a Position while holding its current operational write scope."""

    with transaction.atomic():
        scope = lock_workforce_edition_write_scope(
            organization_id=position.organization_id,
            series_id=position.edition.series_id,
            edition_id=position.edition_id,
        )
        lock_active_department_write_target(
            scope=scope,
            department_id=position.department_id,
        )
        position.save(force_insert=True)
    return position


def update_position_for_test(
    *,
    position: Position,
    update_fields: tuple[str, ...],
) -> Position:
    """Update a Position while holding its current operational write scope."""

    with transaction.atomic():
        scope = lock_workforce_edition_write_scope(
            organization_id=position.organization_id,
            series_id=position.edition.series_id,
            edition_id=position.edition_id,
        )
        lock_active_department_write_target(
            scope=scope,
            department_id=position.department_id,
        )
        locked_position = Position.objects.select_for_update().get(pk=position.pk)
        for field_name in update_fields:
            setattr(locked_position, field_name, getattr(position, field_name))
        locked_position.save(update_fields=update_fields)
    position.refresh_from_db()
    return position


def save_position_assignment_for_test(
    *,
    assignment: PositionAssignment,
) -> PositionAssignment:
    """Insert a proposal after the edition, Department, and Position locks."""

    reference = (
        Position.objects.filter(id=assignment.position_id)
        .order_by()
        .values_list(
            "organization_id",
            "edition__series_id",
            "edition_id",
            "department_id",
        )
        .first()
    )
    if reference is None:
        raise AssertionError("The Position fixture must exist before its assignment.")
    organization_id, series_id, edition_id, department_id = reference
    with transaction.atomic():
        scope = lock_workforce_edition_write_scope(
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        lock_active_department_write_target(
            scope=scope,
            department_id=department_id,
        )
        locked_position_id: UUID | None = (
            Position.objects.select_for_update()
            .filter(
                id=assignment.position_id,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                department_id=department_id,
            )
            .order_by()
            .values_list("id", flat=True)
            .first()
        )
        if locked_position_id is None:
            raise AssertionError("The Position fixture changed scope before insertion.")
        assignment.save(force_insert=True)
    return assignment
