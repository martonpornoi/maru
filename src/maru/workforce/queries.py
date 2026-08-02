"""Bounded, tenant-scoped workforce structure read projections."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from django.db.models import F, Q
from django.utils import timezone

from maru.authorization.policy import current_role_assignment_ids
from maru.identity.queries import active_person_account_display_labels
from maru.workforce.models import Department, Position, PositionAssignment

# These limits are deliberately code-owned. Every relation is fetched with a
# limit+1 probe so a response is either complete or contains no partial tree.
MAX_STRUCTURE_DEPARTMENTS = 256
MAX_STRUCTURE_POSITIONS = 1_024
MAX_STRUCTURE_EFFECTIVE_HOLDERS = 4_096
MAX_STRUCTURE_DEPTH = 32
MAX_STRUCTURE_OTHER_ROLE_LINKS = 16_384
WORKFORCE_STRUCTURE_REQUIRED_FIELDS = frozenset(
    {
        "departments",
        "positions",
        "assignment_counts",
        "holder_display_labels",
    }
)

StructureProjectionState = Literal["complete", "structure_limit_exceeded"]


class StructureProjectionIntegrityError(RuntimeError):
    """The stored edition hierarchy cannot be represented safely."""


class _StructureProjectionLimitExceededError(Exception):
    """Signal a valid projection that exceeds a code-owned output bound."""


@dataclass(frozen=True, slots=True)
class OtherRole:
    department_name: str
    position_title: str


@dataclass(frozen=True, slots=True)
class EffectiveHolder:
    display_name: str
    other_roles: tuple[OtherRole, ...]


@dataclass(frozen=True, slots=True)
class PositionNode:
    id: UUID
    reports_to_id: UUID | None
    reports_to_title: str | None
    code: str
    title: str
    description: str
    headcount: int
    status: str
    holders: tuple[EffectiveHolder, ...]


@dataclass(frozen=True, slots=True)
class DepartmentNode:
    id: UUID
    parent_id: UUID | None
    code: str
    name: str
    description: str
    display_order: int
    positions: tuple[PositionNode, ...]
    children: tuple[DepartmentNode, ...]


@dataclass(frozen=True, slots=True)
class EditionStructureProjection:
    state: StructureProjectionState
    departments: tuple[DepartmentNode, ...]


@dataclass(frozen=True, slots=True)
class _DepartmentRow:
    id: UUID
    parent_id: UUID | None
    code: str
    name: str
    description: str
    display_order: int


@dataclass(frozen=True, slots=True)
class _PositionRow:
    id: UUID
    department_id: UUID
    reports_to_id: UUID | None
    code: str
    title: str
    description: str
    headcount: int
    status: str


@dataclass(frozen=True, slots=True)
class _HolderRow:
    id: UUID
    position_id: UUID
    account_id: UUID
    role_assignment_id: UUID
    display_name: str


def _overflow() -> EditionStructureProjection:
    return EditionStructureProjection(
        state="structure_limit_exceeded",
        departments=(),
    )


def _department_sort_key(row: _DepartmentRow) -> tuple[int, str, str, str]:
    return (row.display_order, row.name.casefold(), row.name, str(row.id))


def _position_sort_key(row: _PositionRow) -> tuple[str, str, str]:
    return (row.title.casefold(), row.title, str(row.id))


def _validate_parent_graph[
    RowT: _DepartmentRow | _PositionRow,
](
    *,
    rows_by_id: dict[UUID, RowT],
    parent_id_for: Callable[[RowT], UUID | None],
) -> bool:
    """Reject invalid graphs and report whether valid depth stays bounded."""

    depths: dict[UUID, int] = {}
    for row_id in rows_by_id:
        if row_id in depths:
            continue
        path: list[UUID] = []
        path_ids: set[UUID] = set()
        current_id: UUID | None = row_id
        while current_id is not None and current_id not in depths:
            if current_id in path_ids:
                raise StructureProjectionIntegrityError(
                    "The workforce hierarchy contains a cycle."
                )
            path.append(current_id)
            path_ids.add(current_id)
            current = rows_by_id.get(current_id)
            if current is None:
                raise StructureProjectionIntegrityError(
                    "The workforce hierarchy has an unavailable parent."
                )
            current_id = parent_id_for(current)
        depth = depths.get(current_id, 0) if current_id is not None else 0
        for path_id in reversed(path):
            depth += 1
            if depth > MAX_STRUCTURE_DEPTH:
                return False
            depths[path_id] = depth
    return True


def _department_rows(
    *, organization_id: UUID, edition_id: UUID
) -> tuple[_DepartmentRow, ...] | None:
    raw_rows = list(
        Department.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .values("id", "parent_id", "code", "name", "description", "position")
        .order_by("position", "name", "id")[: MAX_STRUCTURE_DEPARTMENTS + 1]
    )
    if len(raw_rows) > MAX_STRUCTURE_DEPARTMENTS:
        return None
    return tuple(
        _DepartmentRow(
            id=row["id"],
            parent_id=cast(UUID | None, row["parent_id"]),
            code=row["code"],
            name=row["name"],
            description=row["description"],
            display_order=row["position"],
        )
        for row in raw_rows
    )


def _position_rows(
    *, organization_id: UUID, edition_id: UUID
) -> tuple[_PositionRow, ...] | None:
    raw_rows = list(
        Position.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .values(
            "id",
            "department_id",
            "reports_to_id",
            "code",
            "title",
            "description",
            "headcount",
            "status",
        )
        .order_by("department_id", "title", "id")[: MAX_STRUCTURE_POSITIONS + 1]
    )
    if len(raw_rows) > MAX_STRUCTURE_POSITIONS:
        return None
    return tuple(
        _PositionRow(
            id=row["id"],
            department_id=row["department_id"],
            reports_to_id=cast(UUID | None, row["reports_to_id"]),
            code=row["code"],
            title=row["title"],
            description=row["description"],
            headcount=row["headcount"],
            status=row["status"],
        )
        for row in raw_rows
    )


def _effective_holder_rows(
    *,
    organization_id: UUID,
    edition_id: UUID,
    position_ids: frozenset[UUID],
    at: datetime,
) -> tuple[_HolderRow, ...] | None:
    if not position_ids:
        return ()
    raw_rows = list(
        PositionAssignment.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            position_id__in=position_ids,
            status=PositionAssignment.Status.ACTIVE,
            effective_from__lte=at,
            ended_at__isnull=True,
            role_assignment__effective_from__lte=at,
            role_assignment__revoked_at__isnull=True,
            role_assignment__organization_id=F("organization_id"),
            role_assignment__edition_id=F("edition_id"),
            role_assignment__principal_id=F("account_id"),
            role_assignment__role_bundle_id=F("position__role_bundle_id"),
        )
        .filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=at),
            Q(role_assignment__expires_at__isnull=True)
            | Q(role_assignment__expires_at__gt=at),
        )
        .filter(
            Q(
                role_assignment__department_id__isnull=True,
                role_assignment__resource_binding_id__isnull=True,
            )
            | Q(
                role_assignment__department_id=F("position__department_id"),
                role_assignment__resource_binding_id__isnull=True,
            )
            | Q(
                role_assignment__department_id=F("position__department_id"),
                role_assignment__resource_binding__organization_id=F("organization_id"),
                role_assignment__resource_binding__edition_id=F("edition_id"),
                role_assignment__resource_binding__department_id=F(
                    "position__department_id"
                ),
                role_assignment__resource_binding__resource_kind=("workforce.position"),
                role_assignment__resource_binding__resource_id=F("position_id"),
            )
        )
        .values(
            "id",
            "position_id",
            "account_id",
            "role_assignment_id",
        )
        .order_by("position_id", "account_id", "id")[
            : MAX_STRUCTURE_EFFECTIVE_HOLDERS + 1
        ]
    )
    if len(raw_rows) > MAX_STRUCTURE_EFFECTIVE_HOLDERS:
        return None
    current_role_ids = current_role_assignment_ids(
        assignment_ids=tuple(row["role_assignment_id"] for row in raw_rows),
        at=at,
    )
    current_rows = tuple(
        row for row in raw_rows if row["role_assignment_id"] in current_role_ids
    )
    holder_role_counts = Counter(row["account_id"] for row in current_rows)
    expanded_other_role_links = sum(
        role_count * (role_count - 1) for role_count in holder_role_counts.values()
    )
    if expanded_other_role_links > MAX_STRUCTURE_OTHER_ROLE_LINKS:
        return None
    display_labels = (
        active_person_account_display_labels(
            frozenset(row["account_id"] for row in current_rows)
        )
        if current_rows
        else {}
    )
    return tuple(
        _HolderRow(
            id=row["id"],
            position_id=row["position_id"],
            account_id=row["account_id"],
            role_assignment_id=row["role_assignment_id"],
            display_name=display_labels[row["account_id"]],
        )
        for row in current_rows
        if row["account_id"] in display_labels
    )


def _project_complete_edition_structure(  # noqa: PLR0912
    *,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime | None = None,
) -> EditionStructureProjection:
    """Build one complete minimized tree or signal a code-owned limit."""

    evaluated_at = at or timezone.now()
    if not timezone.is_aware(evaluated_at):
        raise StructureProjectionIntegrityError(
            "The workforce projection instant must be timezone-aware."
        )
    departments = _department_rows(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if departments is None:
        raise _StructureProjectionLimitExceededError
    department_by_id = {row.id: row for row in departments}
    if not _validate_parent_graph(
        rows_by_id=department_by_id,
        parent_id_for=lambda row: row.parent_id,
    ):
        raise _StructureProjectionLimitExceededError

    positions = _position_rows(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if positions is None:
        raise _StructureProjectionLimitExceededError
    position_by_id = {row.id: row for row in positions}
    if any(row.department_id not in department_by_id for row in positions):
        raise StructureProjectionIntegrityError(
            "A workforce position has an unavailable department."
        )
    if not _validate_parent_graph(
        rows_by_id=position_by_id,
        parent_id_for=lambda row: row.reports_to_id,
    ):
        raise _StructureProjectionLimitExceededError

    holders = _effective_holder_rows(
        organization_id=organization_id,
        edition_id=edition_id,
        position_ids=frozenset(position_by_id),
        at=evaluated_at,
    )
    if holders is None:
        raise _StructureProjectionLimitExceededError
    if any(row.position_id not in position_by_id for row in holders):
        raise StructureProjectionIntegrityError(
            "A workforce holder has an unavailable position."
        )

    position_order = sorted(positions, key=_position_sort_key)
    role_by_position = {
        row.id: OtherRole(
            department_name=department_by_id[row.department_id].name,
            position_title=row.title,
        )
        for row in position_order
    }
    position_rank = {row.id: rank for rank, row in enumerate(position_order)}
    roles_by_account: dict[UUID, list[tuple[UUID, OtherRole]]] = {}
    for holder in holders:
        roles_by_account.setdefault(holder.account_id, []).append(
            (holder.position_id, role_by_position[holder.position_id])
        )
    for account_roles in roles_by_account.values():
        account_roles.sort(key=lambda item: position_rank[item[0]])

    holders_by_position: dict[UUID, list[_HolderRow]] = {}
    for holder in holders:
        holders_by_position.setdefault(holder.position_id, []).append(holder)
    projected_positions: dict[UUID, PositionNode] = {}
    for position in position_order:
        position_holders = sorted(
            holders_by_position.get(position.id, ()),
            key=lambda holder: (
                (holder.display_name or "Maru account").casefold(),
                holder.display_name or "Maru account",
                str(holder.account_id),
                str(holder.id),
            ),
        )
        projected_positions[position.id] = PositionNode(
            id=position.id,
            reports_to_id=position.reports_to_id,
            reports_to_title=(
                position_by_id[position.reports_to_id].title
                if position.reports_to_id is not None
                else None
            ),
            code=position.code,
            title=position.title,
            description=position.description,
            headcount=position.headcount,
            status=position.status,
            holders=tuple(
                EffectiveHolder(
                    display_name=holder.display_name or "Maru account",
                    other_roles=tuple(
                        role
                        for role_position_id, role in roles_by_account.get(
                            holder.account_id, ()
                        )
                        if role_position_id != position.id
                    ),
                )
                for holder in position_holders
            ),
        )

    positions_by_department: dict[UUID, list[PositionNode]] = {}
    for position in position_order:
        positions_by_department.setdefault(position.department_id, []).append(
            projected_positions[position.id]
        )
    children_by_parent: dict[UUID | None, list[_DepartmentRow]] = {}
    for department in sorted(departments, key=_department_sort_key):
        children_by_parent.setdefault(department.parent_id, []).append(department)

    def build_department(row: _DepartmentRow) -> DepartmentNode:
        return DepartmentNode(
            id=row.id,
            parent_id=row.parent_id,
            code=row.code,
            name=row.name,
            description=row.description,
            display_order=row.display_order,
            positions=tuple(positions_by_department.get(row.id, ())),
            children=tuple(
                build_department(child) for child in children_by_parent.get(row.id, ())
            ),
        )

    return EditionStructureProjection(
        state="complete",
        departments=tuple(
            build_department(row) for row in children_by_parent.get(None, ())
        ),
    )


def project_edition_structure(
    *,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime | None = None,
) -> EditionStructureProjection:
    """Return one complete minimized tree, or an explicit generic overflow."""

    try:
        return _project_complete_edition_structure(
            organization_id=organization_id,
            edition_id=edition_id,
            at=at,
        )
    except _StructureProjectionLimitExceededError:
        return _overflow()
