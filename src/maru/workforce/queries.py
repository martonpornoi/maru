"""Bounded, tenant-scoped workforce structure read projections."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeVar, cast

from django.db.models import F, Q
from django.utils import timezone

from maru.authorization.policy import current_role_assignment_ids
from maru.identity.queries import active_person_account_display_labels
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
    Position,
    PositionAssignment,
)
from maru.workforce.structure_templates import (
    UnknownBuiltinStructureTemplateError,
    get_builtin_structure_template,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from uuid import UUID

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
        "structure_control",
    }
)

StructureProjectionState = Literal["complete", "structure_limit_exceeded"]
DepartmentState = Literal["active", "retired"]


class StructureProjectionIntegrityError(RuntimeError):
    """The stored edition hierarchy cannot be represented safely."""


class _StructureProjectionLimitExceededError(Exception):
    """Signal a valid projection that exceeds a code-owned output bound."""


@dataclass(frozen=True, slots=True)
class OtherRole:
    """Describe other role.

    Attributes
    ----------
    department_name
        The human-readable department name shown to authorized readers.
    position_title
        The human-readable position title shown to authorized readers.
    """

    department_name: str
    position_title: str


@dataclass(frozen=True, slots=True)
class EffectiveHolder:
    """Describe effective holder.

    Attributes
    ----------
    display_name
        The human-readable display name shown to authorized readers.
    other_roles
        The other roles retained in this immutable projection.
    """

    display_name: str
    other_roles: tuple[OtherRole, ...]


@dataclass(frozen=True, slots=True)
class PositionNode:
    """Describe position node.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    reports_to_id
        The reports to identifier within the requested scope.
    reports_to_title
        The human-readable reports to title shown to authorized readers.
    code
        The stable domain code to resolve or validate.
    title
        The human-readable title shown to authorized readers.
    description
        The human-readable description shown to authorized readers.
    headcount
        The headcount retained in this immutable projection.
    status
        The closed status value to evaluate or expose.
    holders
        The holders retained in this immutable projection.
    """

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
class StructureSource:
    """Describe structure source.

    Attributes
    ----------
    kind
        The closed discriminator selecting the requested behavior.
    """

    kind: Literal["empty", "manual", "legacy_existing"]


@dataclass(frozen=True, slots=True)
class BuiltinTemplateStructureSource:
    """Describe builtin template structure source.

    Attributes
    ----------
    kind
        The closed discriminator selecting the requested behavior.
    template_code
        The stable template code from the relevant closed catalog.
    template_version
        The expected template version used to reject stale updates.
    """

    kind: Literal["builtin_template"]
    template_code: str
    template_version: int


StructureSourceProjection = StructureSource | BuiltinTemplateStructureSource


@dataclass(frozen=True, slots=True)
class DepartmentNode:
    """Describe department node.

    Attributes
    ----------
    id
        The identifier of the target record within its authorized scope.
    parent_id
        The parent identifier within the requested scope.
    code
        The stable domain code to resolve or validate.
    name
        The human-readable name to normalize or persist.
    description
        The human-readable description shown to authorized readers.
    display_order
        The deterministic display position within the owning collection.
    state
        The lifecycle state to evaluate or expose.
    positions
        The positions retained in this immutable projection.
    children
        The children retained in this immutable projection.
    """

    id: UUID
    parent_id: UUID | None
    code: str
    name: str
    description: str
    display_order: int
    state: DepartmentState
    positions: tuple[PositionNode, ...]
    children: tuple[DepartmentNode, ...]


@dataclass(frozen=True, slots=True)
class EditionStructureProjection:
    """Describe edition structure projection.

    Attributes
    ----------
    state
        The lifecycle state to evaluate or expose.
    aggregate_version
        The expected aggregate version used to reject stale updates.
    source
        The immutable source record or definition from which data is derived.
    departments
        The departments retained in this immutable projection.
    """

    state: StructureProjectionState
    aggregate_version: int
    source: StructureSourceProjection
    departments: tuple[DepartmentNode, ...]


@dataclass(frozen=True, slots=True)
class _DepartmentRow:
    id: UUID
    parent_id: UUID | None
    code: str
    name: str
    description: str
    display_order: int
    state: DepartmentState


@dataclass(frozen=True, slots=True)
class _StructureControlProjection:
    aggregate_version: int
    source: StructureSourceProjection


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


_ParentGraphRowT = TypeVar("_ParentGraphRowT", bound=_DepartmentRow | _PositionRow)


@dataclass(frozen=True, slots=True)
class _HolderRow:
    id: UUID
    position_id: UUID
    account_id: UUID
    role_assignment_id: UUID
    display_name: str


def _overflow(
    control: _StructureControlProjection,
) -> EditionStructureProjection:
    return EditionStructureProjection(
        state="structure_limit_exceeded",
        aggregate_version=control.aggregate_version,
        source=control.source,
        departments=(),
    )


def _transitional_legacy_control() -> _StructureControlProjection:
    """Describe an expand-before-backfill tree without inventing provenance.

    Returns
    -------
    _StructureControlProjection
        The resolved _StructureControlProjection for transitional legacy control.
    """
    return _StructureControlProjection(
        aggregate_version=0,
        source=StructureSource(kind="legacy_existing"),
    )


def _structure_control_projection(
    *, organization_id: UUID, edition_id: UUID
) -> _StructureControlProjection:
    control = (
        EditionStructureControl.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .values("id", "origin", "aggregate_version")
        .first()
    )
    if control is None:
        return _StructureControlProjection(
            aggregate_version=0,
            source=StructureSource(kind="empty"),
        )

    aggregate_version = int(control["aggregate_version"])
    if aggregate_version < 1:
        raise StructureProjectionIntegrityError(
            "The workforce structure has an invalid aggregate version."
        )
    origin = control["origin"]
    template_receipts = list(
        EditionStructureCommandReceipt.objects.filter(
            structure_id=control["id"],
            organization_id=organization_id,
            edition_id=edition_id,
            action=EditionStructureCommandReceipt.Action.TEMPLATE_APPLIED,
        )
        .values(
            "resulting_version",
            "template_code",
            "template_version",
            "template_digest",
        )
        .order_by("resulting_version", "id")[:2]
    )
    if origin == EditionStructureControl.Origin.BUILTIN_TEMPLATE:
        if len(template_receipts) != 1:
            raise StructureProjectionIntegrityError(
                "The built-in structure source has incomplete provenance."
            )
        receipt = template_receipts[0]
        template_code = receipt["template_code"]
        template_version = receipt["template_version"]
        template_digest = receipt["template_digest"]
        resulting_version = int(receipt["resulting_version"])
        if (
            not template_code
            or template_version is None
            or int(template_version) < 1
            or resulting_version != 1
            or resulting_version > aggregate_version
        ):
            raise StructureProjectionIntegrityError(
                "The built-in structure source has invalid provenance."
            )
        try:
            template = get_builtin_structure_template(
                f"{template_code}@{int(template_version)}"
            )
        except UnknownBuiltinStructureTemplateError as error:
            raise StructureProjectionIntegrityError(
                "The built-in structure source is not available in this release."
            ) from error
        if template_digest != template.sha256_digest:
            raise StructureProjectionIntegrityError(
                "The built-in structure source digest does not match its catalog."
            )
        return _StructureControlProjection(
            aggregate_version=aggregate_version,
            source=BuiltinTemplateStructureSource(
                kind="builtin_template",
                template_code=str(template_code),
                template_version=int(template_version),
            ),
        )
    if template_receipts:
        raise StructureProjectionIntegrityError(
            "A non-template structure has conflicting template provenance."
        )
    if origin == EditionStructureControl.Origin.MANUAL:
        source_kind: Literal["manual", "legacy_existing"] = "manual"
    elif origin == EditionStructureControl.Origin.LEGACY_EXISTING:
        source_kind = "legacy_existing"
    else:
        raise StructureProjectionIntegrityError(
            "The workforce structure has an unsupported source."
        )
    return _StructureControlProjection(
        aggregate_version=aggregate_version,
        source=StructureSource(kind=source_kind),
    )


def _department_sort_key(row: _DepartmentRow) -> tuple[int, str, str, str]:
    return (row.display_order, row.name.casefold(), row.name, str(row.id))


def _position_sort_key(row: _PositionRow) -> tuple[str, str, str]:
    return (row.title.casefold(), row.title, str(row.id))


# GitHub-managed CodeQL omitted this file when the equivalent PEP 695 bounded
# header was used. Retain the legacy TypeVar form until a hosted analysis proves
# that the active extractor accepts this declaration.
def _validate_parent_graph(  # noqa: UP047
    *,
    rows_by_id: dict[UUID, _ParentGraphRowT],
    parent_id_for: Callable[[_ParentGraphRowT], UUID | None],
) -> bool:
    """Validate parent links and enforce the projection depth bound.

    Parameters
    ----------
    rows_by_id : dict[UUID, _ParentGraphRowT]
        Rows keyed by identifier within the already-authorized edition scope.
    parent_id_for : Callable[[_ParentGraphRowT], UUID | None]
        Callback returning the parent identifier for a row.

    Returns
    -------
    bool
        ``True`` when every valid path is within ``MAX_STRUCTURE_DEPTH``;
        ``False`` when an otherwise valid path exceeds that output bound.

    Raises
    ------
    StructureProjectionIntegrityError
        If a parent is unavailable within the scoped row set or the graph
        contains a cycle.
    """
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
        .values(
            "id",
            "parent_id",
            "code",
            "name",
            "description",
            "display_order",
            "retired_at",
        )
        .order_by("display_order", "name", "id")[: MAX_STRUCTURE_DEPARTMENTS + 1]
    )
    if len(raw_rows) > MAX_STRUCTURE_DEPARTMENTS:
        return None
    return tuple(
        _DepartmentRow(
            id=row["id"],
            parent_id=cast("UUID | None", row["parent_id"]),
            code=row["code"],
            name=row["name"],
            description=row["description"],
            display_order=row["display_order"],
            state="active" if row["retired_at"] is None else "retired",
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
            reports_to_id=cast("UUID | None", row["reports_to_id"]),
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
    control: _StructureControlProjection,
    at: datetime | None = None,
) -> EditionStructureProjection:
    """Build one complete minimized tree or signal a code-owned limit.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    control : _StructureControlProjection
        The control used to constrain the tenant-scoped query.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    EditionStructureProjection
        The EditionStructureProjection produced by project complete edition
        structure.

    Raises
    ------
    StructureProjectionIntegrityError
        If the operation encounters a structure projection integrity condition.
    _StructureProjectionLimitExceededError
        If the operation encounters a structure projection limit exceeded
        condition.
    """
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
    if control.aggregate_version == 0 and departments:
        # During the additive 0006 -> stopped-writer/backfill 0007 deployment
        # window, pre-existing trees have no control yet. This is a read-only,
        # version-zero compatibility projection, not durable source evidence;
        # adapters suppress management until the explicit legacy control lands.
        control = _transitional_legacy_control()
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
            state=row.state,
            positions=tuple(positions_by_department.get(row.id, ())),
            children=tuple(
                build_department(child) for child in children_by_parent.get(row.id, ())
            ),
        )

    return EditionStructureProjection(
        state="complete",
        aggregate_version=control.aggregate_version,
        source=control.source,
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
    """Return one complete minimized tree, or an explicit generic overflow.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    EditionStructureProjection
        The resolved EditionStructureProjection for project edition structure.
    """
    control = _structure_control_projection(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    try:
        return _project_complete_edition_structure(
            organization_id=organization_id,
            edition_id=edition_id,
            control=control,
            at=at,
        )
    except _StructureProjectionLimitExceededError:
        if control.aggregate_version == 0:
            control = _transitional_legacy_control()
        return _overflow(control)
