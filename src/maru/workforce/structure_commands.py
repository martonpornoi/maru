"""Shared edition workforce-structure commands for browser and API adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.bindings import ensure_workforce_position_binding
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.authorization.policy import PolicyDecision, decide, resolve_edition_target
from maru.authorization.provenance import role_bundle_provenance_is_historical
from maru.authorization.queries import (
    department_authority_dependencies,
    edition_resource_binding_count,
)
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.workforce.models import (
    Department,
    EditionStructureCommandReceipt,
    EditionStructureControl,
    Position,
    PositionAssignment,
    PositionTemplate,
    ShiftDemand,
    VolunteerOpportunity,
)
from maru.workforce.queries import (
    MAX_STRUCTURE_DEPARTMENTS,
    MAX_STRUCTURE_DEPTH,
    MAX_STRUCTURE_POSITIONS,
)
from maru.workforce.structure_inputs import (
    MAX_DEPARTMENT_DISPLAY_ORDER,
    canonical_request_digest,
    generate_department_code,
    generate_position_code,
    normalize_department_description,
    normalize_department_name,
    normalize_opportunity_description,
    normalize_opportunity_headline,
    normalize_position_description,
    normalize_position_title,
    normalize_structure_reason,
    validate_department_display_order,
    validate_exact_confirmation,
    validate_position_headcount,
)
from maru.workforce.structure_templates import (
    UnknownBuiltinStructureTemplateError,
    get_builtin_structure_template,
)
from maru.workforce.writer_boundary import lock_edition_structure_mutex

if TYPE_CHECKING:
    from datetime import datetime

_EDITABLE_ORGANIZATION_LIFECYCLES = frozenset(
    {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
)
_EDITABLE_EDITION_LIFECYCLES = frozenset(
    {EventEdition.Lifecycle.DRAFT, EventEdition.Lifecycle.PREPARING}
)
_SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_MAX_SOURCE_CHANNEL_LENGTH = 32


def _automatic_sibling_display_order(
    scope: _LockedScope,
    *,
    parent_department_id: UUID | None,
    current_department: Department | None = None,
) -> int:
    """Keep a unique current rank or append safely after the locked siblings.

    Parameters
    ----------
    scope : _LockedScope
        The exact tenant and resource scope of the operation.
    parent_department_id : UUID | None
        The parent department identifier within the requested scope.
    current_department : Department | None, default=None
        The current department applied within the audited domain transition.

    Returns
    -------
    int
        The resolved int for automatic sibling display order.

    Raises
    ------
    StructureLimitConflictError
        If the operation would exceed a configured hard limit.
    """
    sibling_orders = {
        department.display_order
        for department in scope.departments
        if department.parent_id == parent_department_id
        and (current_department is None or department.id != current_department.id)
    }
    if (
        current_department is not None
        and current_department.parent_id == parent_department_id
        and current_department.display_order not in sibling_orders
    ):
        return current_department.display_order

    if (
        current_department is not None
        and current_department.parent_id == parent_department_id
    ):
        # Heal an old duplicate into the nearest following gap. This avoids
        # moving it past unrelated siblings that already have a later rank.
        for candidate in range(
            current_department.display_order + 1,
            MAX_DEPARTMENT_DISPLAY_ORDER + 1,
        ):
            if candidate not in sibling_orders:
                return candidate
        for candidate in range(current_department.display_order):
            if candidate not in sibling_orders:
                return candidate
        raise StructureLimitConflictError

    appended_order = max(sibling_orders, default=-1) + 1
    if appended_order <= MAX_DEPARTMENT_DISPLAY_ORDER:
        return appended_order

    # The edition-wide Department ceiling makes exhaustion impossible in the
    # current contract, but use a bounded gap fallback so the helper remains
    # correct if a historical/API-supplied sibling already uses the maximum.
    for candidate in range(MAX_DEPARTMENT_DISPLAY_ORDER + 1):
        if candidate not in sibling_orders:
            return candidate
    raise StructureLimitConflictError


class StructureCommandError(RuntimeError):
    """Base for stable, adapter-safe Organization structure failures."""

    reason_code = "structure_command_failed"

    def __init__(
        self, message: str = "The structure command could not complete."
    ) -> None:
        """Initialize the StructureCommandError instance.

        Parameters
        ----------
        message : str, default='The structure command could not complete.'
            The disclosure-safe message associated with the outcome.
        """
        super().__init__(message)


class StructureAuthorizationDeniedError(StructureCommandError):
    """Signal structure authorization denied."""

    reason_code = "structure_authorization_denied"


class StructureDepartmentUnavailableError(StructureCommandError):
    """Signal structure department unavailable."""

    reason_code = "structure_department_unavailable"


class StructurePositionUnavailableError(StructureCommandError):
    """Signal that a Position target is unavailable in the authorized scope."""

    reason_code = "structure_position_unavailable"


class StructureVersionConflictError(StructureCommandError):
    """Signal structure version conflict."""

    reason_code = "structure_version_conflict"


class StructureRetryConflictError(StructureCommandError):
    """Signal structure retry conflict."""

    reason_code = "structure_retry_conflict"


class StructureLifecycleConflictError(StructureCommandError):
    """Signal structure lifecycle conflict."""

    reason_code = "structure_lifecycle_conflict"


class StructureStateConflictError(StructureCommandError):
    """Signal structure state conflict."""

    reason_code = "structure_state_conflict"


class StructureDependencyConflictError(StructureCommandError):
    """Signal structure dependency conflict."""

    reason_code = "structure_department_has_dependencies"


class StructureLimitConflictError(StructureCommandError):
    """Signal structure limit conflict."""

    reason_code = "structure_limit_exceeded"


@dataclass(frozen=True, slots=True)
class BuiltinStructureTemplateResult:
    """Describe builtin structure template result.

    Attributes
    ----------
    structure_id
        The structure identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    department_ids
        The selected department identifiers.
    replayed
        The replayed retained in this immutable projection.
    """

    structure_id: UUID
    receipt_id: UUID
    resulting_version: int
    department_ids: tuple[UUID, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class DepartmentStructureResult:
    """Describe department structure result.

    Attributes
    ----------
    structure_id
        The structure identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    department_id
        The department identifier within the requested scope.
    resulting_version
        The expected resulting version used to reject stale updates.
    changed_fields
        The canonical field names changed by the operation.
    action
        The stable action code describing the requested transition.
    replayed
        The replayed retained in this immutable projection.
    """

    structure_id: UUID
    receipt_id: UUID | None
    department_id: UUID
    resulting_version: int
    changed_fields: tuple[str, ...]
    action: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class PositionStructureResult:
    """Describe one minimized Position or opportunity command result.

    Attributes
    ----------
    structure_id
        The structure identifier within the requested scope.
    receipt_id
        The receipt identifier within the requested scope.
    position_id
        The Position identifier affected by the command.
    resulting_version
        The expected resulting version used to reject stale updates.
    changed_fields
        The canonical field names changed by the operation.
    action
        The stable action code describing the requested transition.
    replayed
        Whether this result came from an idempotent command replay.
    """

    structure_id: UUID
    receipt_id: UUID | None
    position_id: UUID
    resulting_version: int
    changed_fields: tuple[str, ...]
    action: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class _LockedScope:
    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    control: EditionStructureControl | None
    departments: tuple[Department, ...]
    positions: tuple[Position, ...]
    manage_decision: PolicyDecision
    evaluated_at: datetime


def _validate_expected_version(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(
            {
                "expected_version": ValidationError(
                    "Enter a whole structure version of zero or greater.",
                    code="structure_expected_version_invalid",
                )
            },
        )
    return value


def _validate_uuid(value: UUID, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValidationError(
            {
                field_name: ValidationError(
                    "Enter a valid UUID.",
                    code="structure_identifier_invalid",
                )
            },
        )
    return value


def _validate_source_channel(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_SOURCE_CHANNEL_LENGTH
        or _SOURCE_CHANNEL_PATTERN.fullmatch(value) is None
    ):
        raise ValidationError(
            {
                "source_channel": ValidationError(
                    "Use a registered source channel.",
                    code="structure_source_channel_invalid",
                )
            },
        )
    return value


def _route_target(
    *, organization_id: UUID, series_id: UUID, edition_id: UUID
) -> object:
    route_exists = EventEdition.objects.filter(
        id=edition_id,
        organization_id=organization_id,
        series_id=series_id,
        series__organization_id=organization_id,
    ).exists()
    if not route_exists:
        raise StructureAuthorizationDeniedError
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if target is None:
        raise StructureAuthorizationDeniedError
    return target


def _require_view_and_manage(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    at: datetime | None = None,
) -> PolicyDecision:
    if actor.pk is None:
        raise StructureAuthorizationDeniedError
    target = _route_target(
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    view = decide(
        principal=actor,
        capability_code="workforce.view_structure",
        resource=target,  # type: ignore[arg-type]
        at=at,
    )
    manage = decide(
        principal=actor,
        capability_code="workforce.manage_structure",
        resource=target,  # type: ignore[arg-type]
        at=at,
    )
    if not view.allowed or not manage.allowed:
        raise StructureAuthorizationDeniedError
    return manage


def _lock_scope(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> _LockedScope:
    """Apply ADR 0045's complete cross-module lock order.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    _LockedScope
        The resolved _LockedScope for lock scope.

    Raises
    ------
    StructureAuthorizationDeniedError
        If the actor lacks the required scoped capability.
    StructureLimitConflictError
        If the operation would exceed a configured hard limit.
    """
    lock_retired_department_authority_boundaries()
    organization = (
        Organization.objects.select_for_update().filter(id=organization_id).first()
    )
    if organization is None:
        raise StructureAuthorizationDeniedError
    series = (
        ConventionSeries.objects.select_for_update()
        .filter(id=series_id, organization_id=organization.id)
        .first()
    )
    if series is None:
        raise StructureAuthorizationDeniedError
    edition = (
        EventEdition.objects.select_for_update()
        .filter(
            id=edition_id,
            organization_id=organization.id,
            series_id=series.id,
        )
        .first()
    )
    if edition is None:
        raise StructureAuthorizationDeniedError
    lock_edition_structure_mutex(
        organization_id=organization.id,
        edition_id=edition.id,
    )
    control = (
        EditionStructureControl.objects.select_for_update()
        .filter(organization_id=organization.id, edition_id=edition.id)
        .first()
    )
    departments = tuple(
        Department.objects.select_for_update()
        .filter(organization_id=organization.id, edition_id=edition.id)
        .order_by("id")[: MAX_STRUCTURE_DEPARTMENTS + 1]
    )
    if len(departments) > MAX_STRUCTURE_DEPARTMENTS:
        raise StructureLimitConflictError
    positions = tuple(
        Position.objects.select_for_update(of=("self",))
        .select_related("template", "role_bundle", "department", "reports_to")
        .filter(organization_id=organization.id, edition_id=edition.id)
        .order_by("id")[: MAX_STRUCTURE_POSITIONS + 1]
    )
    if len(positions) > MAX_STRUCTURE_POSITIONS:
        raise StructureLimitConflictError
    persisted_actor = Account.objects.select_for_update().filter(pk=actor.pk).first()
    if persisted_actor is None:
        raise StructureAuthorizationDeniedError
    evaluated_at = timezone.now()
    manage_decision = _require_view_and_manage(
        actor=persisted_actor,
        organization_id=organization.id,
        series_id=series.id,
        edition_id=edition.id,
        at=evaluated_at,
    )
    return _LockedScope(
        organization=organization,
        series=series,
        edition=edition,
        control=control,
        departments=departments,
        positions=positions,
        manage_decision=manage_decision,
        evaluated_at=evaluated_at,
    )


def _require_editable_lifecycle(scope: _LockedScope) -> None:
    if (
        scope.organization.lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
        or scope.edition.lifecycle not in _EDITABLE_EDITION_LIFECYCLES
    ):
        raise StructureLifecycleConflictError


def _current_version(scope: _LockedScope) -> int:
    if scope.control is not None:
        return int(scope.control.aggregate_version)
    if _edition_has_structure_content(scope):
        raise StructureStateConflictError(
            "A populated edition has no structure control aggregate."
        )
    return 0


def _edition_has_structure_content(scope: _LockedScope) -> bool:
    if scope.departments:
        return True
    if scope.positions:
        return True
    if PositionAssignment.objects.filter(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
    ).exists():
        return True
    if EditionStructureCommandReceipt.objects.filter(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
    ).exists():
        return True
    return bool(
        edition_resource_binding_count(
            organization_id=scope.organization.id,
            edition_id=scope.edition.id,
        )
    )


def _require_expected_version(scope: _LockedScope, expected_version: int) -> int:
    current = _current_version(scope)
    if expected_version != current:
        raise StructureVersionConflictError
    return current


def _receipt_for_retry(
    *, scope: _LockedScope, actor_id: UUID, retry_key: UUID
) -> EditionStructureCommandReceipt | None:
    return (
        EditionStructureCommandReceipt.objects.filter(
            organization_id=scope.organization.id,
            edition_id=scope.edition.id,
            actor_id=actor_id,
            retry_key=retry_key,
        )
        .order_by("id")
        .first()
    )


def _validate_retry_receipt(
    *,
    receipt: EditionStructureCommandReceipt,
    action: str,
    request_digest: str,
) -> None:
    if receipt.action != action or receipt.request_digest != request_digest:
        raise StructureRetryConflictError


def _new_or_advanced_control(
    *, scope: _LockedScope, origin: str, resulting_version: int
) -> EditionStructureControl:
    if scope.control is None:
        return EditionStructureControl.objects.create(
            organization=scope.organization,
            edition=scope.edition,
            origin=origin,
            aggregate_version=resulting_version,
        )
    scope.control.aggregate_version = resulting_version
    scope.control.save(update_fields=("aggregate_version", "updated_at"))
    return scope.control


def _append_change_evidence(
    *,
    scope: _LockedScope,
    actor: Account,
    control: EditionStructureControl,
    action: str,
    resulting_version: int,
    changed_fields: tuple[str, ...],
    affected_department_ids: tuple[UUID, ...],
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    retry_key: UUID | None = None,
    request_digest: str = "",
    template_code: str = "",
    template_version: int | None = None,
    template_digest: str = "",
    deleted_name_snapshot: str = "",
    affected_position: Position | None = None,
) -> EditionStructureCommandReceipt:
    receipt = EditionStructureCommandReceipt.objects.create(
        structure=control,
        organization=scope.organization,
        edition=scope.edition,
        action=action,
        resulting_version=resulting_version,
        actor=actor,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        changed_fields=list(changed_fields),
        affected_department_ids=list(affected_department_ids),
        affected_position=affected_position,
        retry_key=retry_key,
        request_digest=request_digest,
        template_code=template_code,
        template_version=template_version,
        template_digest=template_digest,
        deleted_name_snapshot=deleted_name_snapshot,
    )
    safe_metadata: dict[str, object] = {
        "policy_version": POLICY_VERSION,
        "target_count": len(affected_department_ids),
    }
    audit_event = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            capability_code="workforce.manage_structure",
            operation="workforce.structure.change",
            target_type="workforce.edition_structure",
            target_id=scope.edition.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=scope.manage_decision.reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.manage_decision.obligations)),
            changed_fields=changed_fields,
            safe_metadata=safe_metadata,
            retention_class="workforce-restricted",
        ),
        occurred_at=scope.evaluated_at,
    )
    payload: dict[str, object] = {
        "action": action,
        "aggregate_version": str(resulting_version),
        "changed_fields": ",".join(changed_fields),
    }
    if template_code:
        payload.update(
            {
                "template_code": template_code,
                "template_version": str(template_version),
            }
        )
    publish_domain_event(
        DomainEventRecord(
            event_name="workforce.structure.changed.v1",
            schema_version=1,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            aggregate_type="workforce.edition_structure",
            aggregate_id=control.id,
            aggregate_version=resulting_version,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=audit_event.id,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="workforce-restricted",
        ),
        occurred_at=scope.evaluated_at,
    )
    return receipt


def _department_by_id(
    scope: _LockedScope, department_id: UUID, *, current: bool = True
) -> Department:
    department = next(
        (item for item in scope.departments if item.id == department_id),
        None,
    )
    if department is None or (current and department.retired_at is not None):
        raise StructureDepartmentUnavailableError
    return department


def _validate_resulting_hierarchy(
    departments: tuple[Department, ...],
    *,
    changed_department_id: UUID | None = None,
    changed_parent_id: UUID | None = None,
) -> None:
    if len(departments) > MAX_STRUCTURE_DEPARTMENTS:
        raise StructureLimitConflictError
    parent_by_id = {department.id: department.parent_id for department in departments}
    if changed_department_id is not None:
        parent_by_id[changed_department_id] = changed_parent_id
    known_ids = frozenset(parent_by_id)
    for department_id in sorted(parent_by_id, key=str):
        seen: set[UUID] = set()
        cursor: UUID | None = department_id
        depth = 0
        while cursor is not None:
            if cursor in seen:
                raise ValidationError(
                    {
                        "parent_department_id": ValidationError(
                            "The Department hierarchy cannot contain a cycle.",
                            code="structure_department_cycle",
                        )
                    },
                )
            if cursor not in known_ids:
                raise StructureStateConflictError(
                    "The Department hierarchy is incomplete."
                )
            seen.add(cursor)
            depth += 1
            if depth > MAX_STRUCTURE_DEPTH:
                raise StructureLimitConflictError
            cursor = parent_by_id[cursor]


def _validate_manual_name(name: str) -> str:
    normalized = normalize_department_name(name)
    if normalized.casefold() == "executive board":
        raise ValidationError(
            {
                "name": ValidationError(
                    "Executive Board is the separate governance anchor.",
                    code="structure_executive_board_reserved",
                )
            },
        )
    return normalized


def apply_builtin_structure_template(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    template_identifier: str,
    expected_version: int,
    confirmation_name: str,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> BuiltinStructureTemplateResult:
    """Copy one immutable built-in Department template into an empty edition.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    template_identifier : str
        The template identifier applied within the audited domain transition.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    confirmation_name : str
        The human-readable confirmation name shown to authorized readers.
    reason : str
        The operator-supplied rationale recorded with the change.
    retry_key : UUID
        The stable key that makes an exact command retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    BuiltinStructureTemplateResult
        The BuiltinStructureTemplateResult produced by apply builtin structure
        template.

    Raises
    ------
    StructureLimitConflictError
        If the operation would exceed a configured hard limit.
    StructureStateConflictError
        If the target lifecycle state does not permit the transition.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    normalized_reason = normalize_structure_reason(reason)
    preliminary_at = timezone.now()
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=preliminary_at,
    )
    try:
        template = get_builtin_structure_template(template_identifier)
    except UnknownBuiltinStructureTemplateError as error:
        raise ValidationError(
            {
                "template": ValidationError(
                    "Choose an available built-in structure template.",
                    code="structure_template_unknown",
                )
            }
        ) from error
    request_digest = canonical_request_digest(
        {
            "action": EditionStructureCommandReceipt.Action.TEMPLATE_APPLIED,
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "template": template.identifier,
            "expected_version": expected_version,
            "confirmation_name": confirmation_name,
            "reason": normalized_reason,
        }
    )

    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(
            scope=scope,
            actor_id=actor.id,
            retry_key=retry_key,
        )
        if replay is not None:
            _validate_retry_receipt(
                receipt=replay,
                action=EditionStructureCommandReceipt.Action.TEMPLATE_APPLIED,
                request_digest=request_digest,
            )
            return BuiltinStructureTemplateResult(
                structure_id=replay.structure_id,
                receipt_id=replay.id,
                resulting_version=replay.resulting_version,
                department_ids=tuple(replay.affected_department_ids),
                replayed=True,
            )
        _require_editable_lifecycle(scope)
        if _require_expected_version(scope, expected_version) != 0:
            raise StructureStateConflictError("A template requires an empty structure.")
        validate_exact_confirmation(confirmation_name, expected=scope.edition.name)
        if len(template.departments) > MAX_STRUCTURE_DEPARTMENTS:
            raise StructureLimitConflictError

        by_code: dict[str, Department] = {}
        departments: list[Department] = []
        for definition in template.departments:
            department = Department(
                organization=scope.organization,
                edition=scope.edition,
                parent=(
                    by_code[definition.parent_code]
                    if definition.parent_code is not None
                    else None
                ),
                code=definition.code,
                name=definition.name,
                description=definition.description,
                display_order=definition.display_order,
                created_in_structure_version=1,
                last_changed_in_structure_version=1,
            )
            department.full_clean(
                exclude=("parent",) if definition.parent_code is not None else ()
            )
            by_code[definition.code] = department
            departments.append(department)
        _validate_resulting_hierarchy(tuple(departments))
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.BUILTIN_TEMPLATE,
            resulting_version=1,
        )
        Department.objects.bulk_create(departments)
        department_ids = tuple(department.id for department in departments)
        receipt = _append_change_evidence(
            scope=scope,
            actor=actor,
            control=control,
            action=EditionStructureCommandReceipt.Action.TEMPLATE_APPLIED,
            resulting_version=1,
            changed_fields=("departments",),
            affected_department_ids=department_ids,
            reason=normalized_reason,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            retry_key=retry_key,
            request_digest=request_digest,
            template_code=template.code,
            template_version=template.version,
            template_digest=template.sha256_digest,
        )
        return BuiltinStructureTemplateResult(
            structure_id=control.id,
            receipt_id=receipt.id,
            resulting_version=1,
            department_ids=department_ids,
            replayed=False,
        )


def create_department(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    name: str,
    description: str,
    parent_department_id: UUID | None,
    display_order: int | None,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> DepartmentStructureResult:
    """Create one edition-owned Department with deterministic code generation.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    name : str
        The human-readable name to normalize or persist.
    description : str
        The human-readable description shown to authorized readers.
    parent_department_id : UUID | None
        The parent department identifier within the requested scope.
    display_order : int | None
        The deterministic display position within the owning collection.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    reason : str
        The operator-supplied rationale recorded with the change.
    retry_key : UUID
        The stable key that makes an exact command retry idempotent.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    DepartmentStructureResult
        The newly created DepartmentStructureResult.

    Raises
    ------
    StructureLimitConflictError
        If the operation would exceed a configured hard limit.
    """
    normalized_name = _validate_manual_name(name)
    normalized_description = normalize_department_description(description)
    requested_display_order = (
        validate_department_display_order(display_order)
        if display_order is not None
        else None
    )
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    if parent_department_id is not None:
        parent_department_id = _validate_uuid(
            parent_department_id, field_name="parent_department_id"
        )
    source_channel = _validate_source_channel(source_channel)
    normalized_reason = normalize_structure_reason(reason)
    preliminary_at = timezone.now()
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=preliminary_at,
    )
    request_digest = canonical_request_digest(
        {
            "action": EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "name": normalized_name,
            "description": normalized_description,
            "parent_department_id": (
                str(parent_department_id) if parent_department_id else None
            ),
            "display_order": (
                requested_display_order
                if requested_display_order is not None
                else "automatic"
            ),
            "expected_version": expected_version,
            "reason": normalized_reason,
        }
    )

    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        replay = _receipt_for_retry(
            scope=scope,
            actor_id=actor.id,
            retry_key=retry_key,
        )
        if replay is not None:
            _validate_retry_receipt(
                receipt=replay,
                action=EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
                request_digest=request_digest,
            )
            return DepartmentStructureResult(
                structure_id=replay.structure_id,
                receipt_id=replay.id,
                department_id=replay.affected_department_ids[0],
                resulting_version=replay.resulting_version,
                changed_fields=tuple(replay.changed_fields),
                action=replay.action,
                replayed=True,
            )
        _require_editable_lifecycle(scope)
        current_version = _require_expected_version(scope, expected_version)
        if len(scope.departments) >= MAX_STRUCTURE_DEPARTMENTS:
            raise StructureLimitConflictError
        parent = (
            _department_by_id(scope, parent_department_id)
            if parent_department_id is not None
            else None
        )
        effective_display_order = (
            requested_display_order
            if requested_display_order is not None
            else _automatic_sibling_display_order(
                scope,
                parent_department_id=parent.id if parent else None,
            )
        )
        resulting_version = current_version + 1
        department = Department(
            organization=scope.organization,
            edition=scope.edition,
            parent=parent,
            code=generate_department_code(
                normalized_name,
                existing_codes=(item.code for item in scope.departments),
            ),
            name=normalized_name,
            description=normalized_description,
            display_order=effective_display_order,
            created_in_structure_version=resulting_version,
            last_changed_in_structure_version=resulting_version,
        )
        _validate_resulting_hierarchy((*scope.departments, department))
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.MANUAL,
            resulting_version=resulting_version,
        )
        department.save(force_insert=True)
        receipt = _append_change_evidence(
            scope=scope,
            actor=actor,
            control=control,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
            resulting_version=resulting_version,
            changed_fields=("departments",),
            affected_department_ids=(department.id,),
            reason=normalized_reason,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            retry_key=retry_key,
            request_digest=request_digest,
        )
        return DepartmentStructureResult(
            structure_id=control.id,
            receipt_id=receipt.id,
            department_id=department.id,
            resulting_version=resulting_version,
            changed_fields=("departments",),
            action=receipt.action,
            replayed=False,
        )


def update_department(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    name: str,
    description: str,
    parent_department_id: UUID | None,
    display_order: int | None,
    expected_version: int,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> DepartmentStructureResult:
    """Completely replace one current Department's editable properties.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    department_id : UUID
        The department identifier within the requested scope.
    name : str
        The human-readable name to normalize or persist.
    description : str
        The human-readable description shown to authorized readers.
    parent_department_id : UUID | None
        The parent department identifier within the requested scope.
    display_order : int | None
        The deterministic display position within the owning collection.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    DepartmentStructureResult
        The updated DepartmentStructureResult after the transition is committed.
    """
    department_id = _validate_uuid(department_id, field_name="department_id")
    normalized_name = _validate_manual_name(name)
    normalized_description = normalize_department_description(description)
    requested_display_order = (
        validate_department_display_order(display_order)
        if display_order is not None
        else None
    )
    expected_version = _validate_expected_version(expected_version)
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    if parent_department_id is not None:
        parent_department_id = _validate_uuid(
            parent_department_id, field_name="parent_department_id"
        )
    source_channel = _validate_source_channel(source_channel)
    normalized_reason = normalize_structure_reason(reason)
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=timezone.now(),
    )

    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_editable_lifecycle(scope)
        current_version = _require_expected_version(scope, expected_version)
        department = _department_by_id(scope, department_id)
        parent = (
            _department_by_id(scope, parent_department_id)
            if parent_department_id is not None
            else None
        )
        effective_display_order = (
            requested_display_order
            if requested_display_order is not None
            else _automatic_sibling_display_order(
                scope,
                parent_department_id=parent.id if parent else None,
                current_department=department,
            )
        )
        replacement = {
            "name": normalized_name,
            "description": normalized_description,
            "parent_id": parent.id if parent else None,
            "display_order": effective_display_order,
        }
        changed_fields = tuple(
            sorted(
                field
                for field, changed in (
                    ("name", department.name != replacement["name"]),
                    (
                        "description",
                        department.description != replacement["description"],
                    ),
                    (
                        "parent_department",
                        department.parent_id != replacement["parent_id"],
                    ),
                    (
                        "display_order",
                        department.display_order != replacement["display_order"],
                    ),
                )
                if changed
            )
        )
        if not changed_fields:
            return DepartmentStructureResult(
                structure_id=scope.control.id,  # type: ignore[union-attr]
                receipt_id=None,
                department_id=department.id,
                resulting_version=current_version,
                changed_fields=(),
                action=EditionStructureCommandReceipt.Action.DEPARTMENT_UPDATED,
                replayed=False,
            )
        _validate_resulting_hierarchy(
            scope.departments,
            changed_department_id=department.id,
            changed_parent_id=parent.id if parent else None,
        )
        resulting_version = current_version + 1
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.MANUAL,
            resulting_version=resulting_version,
        )
        department.name = normalized_name
        department.description = normalized_description
        department.parent = parent
        department.display_order = effective_display_order
        department.last_changed_in_structure_version = resulting_version
        department.save(
            update_fields=(
                "name",
                "description",
                "parent",
                "display_order",
                "last_changed_in_structure_version",
                "updated_at",
            )
        )
        receipt = _append_change_evidence(
            scope=scope,
            actor=actor,
            control=control,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_UPDATED,
            resulting_version=resulting_version,
            changed_fields=changed_fields,
            affected_department_ids=(department.id,),
            reason=normalized_reason,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        return DepartmentStructureResult(
            structure_id=control.id,
            receipt_id=receipt.id,
            department_id=department.id,
            resulting_version=resulting_version,
            changed_fields=changed_fields,
            action=receipt.action,
            replayed=False,
        )


def _retirement_dependencies(scope: _LockedScope, department: Department) -> bool:
    if any(
        item.parent_id == department.id
        for item in scope.departments
        if item.retired_at is None
    ):
        return True
    if (
        Position.objects.filter(
            organization_id=scope.organization.id,
            edition_id=scope.edition.id,
            department_id=department.id,
        )
        .exclude(status=Position.Status.CLOSED)
        .exists()
    ):
        return True
    if (
        PositionAssignment.objects.filter(
            organization_id=scope.organization.id,
            edition_id=scope.edition.id,
            position__department_id=department.id,
            status=PositionAssignment.Status.ACTIVE,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=scope.evaluated_at))
        .exists()
    ):
        return True
    authority = department_authority_dependencies(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        department_id=department.id,
        at=scope.evaluated_at,
    )
    return bool(
        authority.has_current_or_future_capability_grant
        or authority.has_current_or_future_role_assignment
    )


def retire_department(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    expected_version: int,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> DepartmentStructureResult:
    """Retire one dependency-free current Department without deleting history.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    department_id : UUID
        The department identifier within the requested scope.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    DepartmentStructureResult
        The resolved DepartmentStructureResult for retire department.

    Raises
    ------
    IntegrityError
        If a concurrent write violates a durable database invariant.
    StructureDependencyConflictError
        If the operation encounters a structure dependency conflict condition.
    """
    department_id = _validate_uuid(department_id, field_name="department_id")
    expected_version = _validate_expected_version(expected_version)
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    normalized_reason = normalize_structure_reason(reason)
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=timezone.now(),
    )
    try:
        with transaction.atomic():
            scope = _lock_scope(
                actor=actor,
                organization_id=organization_id,
                series_id=series_id,
                edition_id=edition_id,
            )
            _require_editable_lifecycle(scope)
            current_version = _require_expected_version(scope, expected_version)
            department = _department_by_id(scope, department_id)
            if _retirement_dependencies(scope, department):
                raise StructureDependencyConflictError
            resulting_version = current_version + 1
            control = _new_or_advanced_control(
                scope=scope,
                origin=EditionStructureControl.Origin.MANUAL,
                resulting_version=resulting_version,
            )
            department.retired_at = scope.evaluated_at
            department.retired_by = actor
            department.retired_in_structure_version = resulting_version
            department.last_changed_in_structure_version = resulting_version
            department.save(
                update_fields=(
                    "retired_at",
                    "retired_by",
                    "retired_in_structure_version",
                    "last_changed_in_structure_version",
                    "updated_at",
                )
            )
            receipt = _append_change_evidence(
                scope=scope,
                actor=actor,
                control=control,
                action=EditionStructureCommandReceipt.Action.DEPARTMENT_RETIRED,
                resulting_version=resulting_version,
                changed_fields=("retirement",),
                affected_department_ids=(department.id,),
                reason=normalized_reason,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
            )
            return DepartmentStructureResult(
                structure_id=control.id,
                receipt_id=receipt.id,
                department_id=department.id,
                resulting_version=resulting_version,
                changed_fields=("retirement",),
                action=receipt.action,
                replayed=False,
            )
    except IntegrityError as error:
        if "current authority blocks Department retirement" in str(error):
            raise StructureDependencyConflictError from error
        raise


def _has_deletion_dependencies(  # noqa: PLR0911
    scope: _LockedScope, department: Department
) -> bool:
    if department.created_in_structure_version is None:
        return True
    if (
        department.last_changed_in_structure_version
        != department.created_in_structure_version
    ):
        return True
    if any(item.parent_id == department.id for item in scope.departments):
        return True
    if Position.objects.filter(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        department_id=department.id,
    ).exists():
        return True
    if PositionAssignment.objects.filter(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        position__department_id=department.id,
    ).exists():
        return True
    authority = department_authority_dependencies(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        department_id=department.id,
        at=scope.evaluated_at,
    )
    if (
        authority.has_resource_binding_history
        or authority.has_historical_authority_reference
    ):
        return True
    history = tuple(
        EditionStructureCommandReceipt.objects.filter(
            organization_id=scope.organization.id,
            edition_id=scope.edition.id,
            affected_department_ids__contains=[department.id],
        ).order_by("resulting_version", "id")
    )
    if len(history) != 1:
        return True
    creation = history[0]
    return not (
        creation.resulting_version == department.created_in_structure_version
        and creation.action
        in {
            EditionStructureCommandReceipt.Action.TEMPLATE_APPLIED,
            EditionStructureCommandReceipt.Action.DEPARTMENT_CREATED,
        }
    )


def _delete_department_without_cascade(department: Department) -> int:
    """Delete one row while translating an unknown retained FK safely.

    The savepoint is required because PostgreSQL marks the statement's
    transaction as failed before reporting a foreign-key dependency that is
    not represented in Django's model graph.

    Parameters
    ----------
    department : Department
        The department applied within the audited domain transition.

    Returns
    -------
    int
        The resolved int for delete department without cascade.

    Raises
    ------
    IntegrityError
        If a concurrent write violates a durable database invariant.
    StructureDependencyConflictError
        If the operation encounters a structure dependency conflict condition.
    """
    try:
        with transaction.atomic():
            deleted_count, _detail = department.delete()
    except (ProtectedError, RestrictedError) as error:
        raise StructureDependencyConflictError from error
    except IntegrityError as error:
        cause = error.__cause__
        database_message = str(error)
        if (
            getattr(cause, "sqlstate", None) == "23503"
            or "Department foreign-key contract changed; deletion denied"
            in database_message
            or "Department deletion is protected by retained dependencies"
            in database_message
        ):
            raise StructureDependencyConflictError from error
        raise
    return deleted_count


def delete_unused_department(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    expected_version: int,
    confirmation_name: str,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> DepartmentStructureResult:
    """Hard-delete one provably unused, command-created current leaf.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    series_id : UUID
        The convention-series identifier within the organization scope.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    department_id : UUID
        The department identifier within the requested scope.
    expected_version : int
        The aggregate version required for optimistic concurrency control.
    confirmation_name : str
        The human-readable confirmation name shown to authorized readers.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    DepartmentStructureResult
        The resolved DepartmentStructureResult for delete unused department.

    Raises
    ------
    StructureDependencyConflictError
        If the operation encounters a structure dependency conflict condition.
    StructureStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    department_id = _validate_uuid(department_id, field_name="department_id")
    expected_version = _validate_expected_version(expected_version)
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    normalized_reason = normalize_structure_reason(reason)
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=timezone.now(),
    )

    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_editable_lifecycle(scope)
        current_version = _require_expected_version(scope, expected_version)
        department = _department_by_id(scope, department_id)
        validate_exact_confirmation(confirmation_name, expected=department.name)
        if _has_deletion_dependencies(scope, department):
            raise StructureDependencyConflictError
        resulting_version = current_version + 1
        deleted_name = department.name
        if scope.control is None:
            raise StructureStateConflictError
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.MANUAL,
            resulting_version=resulting_version,
        )
        deleted_count = _delete_department_without_cascade(department)
        if deleted_count != 1:
            raise StructureDependencyConflictError
        receipt = _append_change_evidence(
            scope=scope,
            actor=actor,
            control=control,
            action=EditionStructureCommandReceipt.Action.DEPARTMENT_DELETED,
            resulting_version=resulting_version,
            changed_fields=("departments",),
            affected_department_ids=(department_id,),
            reason=normalized_reason,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            deleted_name_snapshot=deleted_name,
        )
        return DepartmentStructureResult(
            structure_id=control.id,
            receipt_id=receipt.id,
            department_id=department_id,
            resulting_version=resulting_version,
            changed_fields=("departments",),
            action=receipt.action,
            replayed=False,
        )


def _position_by_id(scope: _LockedScope, position_id: UUID) -> Position:
    position = next((item for item in scope.positions if item.id == position_id), None)
    if position is None:
        raise StructurePositionUnavailableError
    return position


def _published_position_template(
    scope: _LockedScope,
    *,
    template_id: UUID,
    actor: Account,
    initial_authority_bootstrap: bool,
) -> PositionTemplate:
    template = (
        PositionTemplate.objects.select_for_update()
        .select_related("role_bundle")
        .filter(
            id=template_id,
            organization_id=scope.organization.id,
            status=PositionTemplate.Status.PUBLISHED,
        )
        .order_by()
        .first()
    )
    provenance_is_historical = template is not None and (
        role_bundle_provenance_is_historical(
            bundle=template.role_bundle,
            evaluated_at=scope.evaluated_at,
            lock=True,
        )
    )
    initial_chair_template_is_safe = bool(
        initial_authority_bootstrap
        and template is not None
        and actor.is_platform_administrator
        and not scope.positions
        and scope.control is not None
        and scope.control.aggregate_version == 1
        and template.code == "convention-chair"
        and template.created_by_id == actor.id
        and template.role_bundle.created_by_id == actor.id
        and template.role_bundle.approved_by_id is not None
        and template.role_bundle.approved_by_id != actor.id
    )
    if template is None or not (
        provenance_is_historical or initial_chair_template_is_safe
    ):
        raise ValidationError(
            {
                "template_id": ValidationError(
                    "Choose an available published Position template.",
                    code="structure_position_template_unavailable",
                )
            }
        )
    return template


def _active_position_department(
    scope: _LockedScope,
    *,
    department_id: UUID,
) -> Department:
    return _department_by_id(scope, department_id)


def _reporting_position(
    scope: _LockedScope,
    *,
    reports_to_id: UUID | None,
    current_position_id: UUID | None = None,
) -> Position | None:
    if reports_to_id is None:
        return None
    if current_position_id is not None and reports_to_id == current_position_id:
        raise ValidationError(
            {
                "reports_to_id": ValidationError(
                    "A Position cannot report to itself.",
                    code="structure_position_reports_to_self",
                )
            }
        )
    manager = _position_by_id(scope, reports_to_id)
    if manager.status == Position.Status.CLOSED:
        raise ValidationError(
            {
                "reports_to_id": ValidationError(
                    "Choose a current Position in this edition.",
                    code="structure_position_manager_closed",
                )
            }
        )
    return manager


def _validate_position_reporting_graph(
    positions: tuple[Position, ...],
    *,
    changed_position_id: UUID | None = None,
    changed_reports_to_id: UUID | None = None,
    added_position: Position | None = None,
) -> None:
    parent_by_id = {position.id: position.reports_to_id for position in positions}
    if added_position is not None:
        parent_by_id[added_position.id] = added_position.reports_to_id
    if changed_position_id is not None:
        parent_by_id[changed_position_id] = changed_reports_to_id
    known_ids = frozenset(parent_by_id)
    for position_id in sorted(parent_by_id, key=str):
        seen: set[UUID] = set()
        cursor: UUID | None = position_id
        depth = 0
        while cursor is not None:
            if cursor in seen:
                raise ValidationError(
                    {
                        "reports_to_id": ValidationError(
                            "The Position reporting line cannot contain a cycle.",
                            code="structure_position_reporting_cycle",
                        )
                    }
                )
            if cursor not in known_ids:
                raise StructureStateConflictError(
                    "The Position reporting graph is incomplete."
                )
            seen.add(cursor)
            depth += 1
            if depth > MAX_STRUCTURE_DEPTH:
                raise StructureLimitConflictError
            cursor = parent_by_id[cursor]


def _position_authority_is_open(scope: _LockedScope, position: Position) -> bool:
    current_or_future = Q(expires_at__isnull=True) | Q(
        expires_at__gt=scope.evaluated_at
    )
    binding_scope = {
        "organization_id": scope.organization.id,
        "edition_id": scope.edition.id,
        "resource_binding__resource_kind": "workforce.position",
        "resource_binding__resource_id": position.id,
    }
    return bool(
        CapabilityGrant.objects.filter(
            **binding_scope,
            revoked_at__isnull=True,
        )
        .filter(current_or_future)
        .exists()
        or RoleAssignment.objects.filter(
            **binding_scope,
            revoked_at__isnull=True,
        )
        .filter(current_or_future)
        .exists()
    )


def create_position(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    template_id: UUID,
    department_id: UUID,
    reports_to_id: UUID | None,
    title: str,
    description: str,
    headcount: int,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
    initial_authority_bootstrap: bool = False,
) -> PositionStructureResult:
    """Create one Position, its draft opportunity, and exact resource binding.

    Parameters
    ----------
    actor : Account
        Authenticated account authorizing and explaining the change.
    organization_id : UUID
        Organization that owns the template and exact edition.
    series_id : UUID
        Convention series in the persisted route chain.
    edition_id : UUID
        Editable event edition that owns the Position.
    template_id : UUID
        Published organization Position template with historical provenance.
    department_id : UUID
        Active exact-edition Department that permanently scopes the Position.
    reports_to_id : UUID | None
        Optional current same-edition operational reporting Position.
    title : str
        Human-readable responsibility title.
    description : str
        Organizer- and applicant-facing purpose and responsibilities.
    headcount : int
        Maximum number of proposed and active holders.
    expected_version : int
        Exact structure version required for optimistic concurrency.
    reason : str
        Organizer rationale retained with the command receipt.
    retry_key : UUID
        Stable identifier that makes an exact creation retry idempotent.
    correlation_id : UUID
        Correlation identifier shared by audit and domain-event evidence.
    request_id : UUID | None, default=None
        Incoming request identifier, or the correlation identifier when absent.
    source_channel : str, default='service'
        Closed channel code identifying the command adapter.
    initial_authority_bootstrap : bool, default=False
        Permit only the one initial Convention Chair template before authority
        provenance activation; ordinary Position creation always rejects it.

    Returns
    -------
    PositionStructureResult
        Minimized Position identifier and committed aggregate evidence.

    Raises
    ------
    StructureLimitConflictError
        If the exact-edition Position ceiling has been reached.
    StructureStateConflictError
        If a retry receipt or aggregate lacks required Position evidence.
    ValidationError
        If Position input or the initial-authority bootstrap marker is invalid.
    """
    template_id = _validate_uuid(template_id, field_name="template_id")
    department_id = _validate_uuid(department_id, field_name="department_id")
    if reports_to_id is not None:
        reports_to_id = _validate_uuid(reports_to_id, field_name="reports_to_id")
    normalized_title = normalize_position_title(title)
    normalized_description = normalize_position_description(description)
    normalized_headcount = validate_position_headcount(headcount)
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    if type(initial_authority_bootstrap) is not bool:
        raise ValidationError(
            {
                "initial_authority_bootstrap": ValidationError(
                    "Choose whether this is the initial authority bootstrap.",
                    code="structure_initial_authority_bootstrap_invalid",
                )
            }
        )
    normalized_reason = normalize_structure_reason(reason)
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=timezone.now(),
    )

    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_editable_lifecycle(scope)
        template = _published_position_template(
            scope,
            template_id=template_id,
            actor=actor,
            initial_authority_bootstrap=initial_authority_bootstrap,
        )
        request_digest = canonical_request_digest(
            {
                "action": EditionStructureCommandReceipt.Action.POSITION_CREATED,
                "organization_id": str(organization_id),
                "series_id": str(series_id),
                "edition_id": str(edition_id),
                "template_id": str(template.id),
                "department_id": str(department_id),
                "reports_to_id": str(reports_to_id) if reports_to_id else None,
                "title": normalized_title,
                "description": normalized_description,
                "headcount": normalized_headcount,
                "expected_version": expected_version,
                "reason": normalized_reason,
                "initial_authority_bootstrap": initial_authority_bootstrap,
            }
        )
        replay = _receipt_for_retry(
            scope=scope,
            actor_id=actor.id,
            retry_key=retry_key,
        )
        if replay is not None:
            _validate_retry_receipt(
                receipt=replay,
                action=EditionStructureCommandReceipt.Action.POSITION_CREATED,
                request_digest=request_digest,
            )
            if replay.affected_position_id is None:
                raise StructureStateConflictError
            return PositionStructureResult(
                structure_id=replay.structure_id,
                receipt_id=replay.id,
                position_id=replay.affected_position_id,
                resulting_version=replay.resulting_version,
                changed_fields=tuple(replay.changed_fields),
                action=replay.action,
                replayed=True,
            )
        current_version = _require_expected_version(scope, expected_version)
        if scope.control is None or len(scope.positions) >= MAX_STRUCTURE_POSITIONS:
            raise StructureLimitConflictError
        department = _active_position_department(
            scope,
            department_id=department_id,
        )
        manager = _reporting_position(
            scope,
            reports_to_id=reports_to_id,
        )
        resulting_version = current_version + 1
        position = Position(
            organization=scope.organization,
            edition=scope.edition,
            template=template,
            department=department,
            reports_to=manager,
            role_bundle=template.role_bundle,
            code=generate_position_code(
                template.code,
                existing_codes=(item.code for item in scope.positions),
            ),
            title=normalized_title,
            description=normalized_description,
            headcount=normalized_headcount,
            capacity_codes=list(template.default_capacity_codes),
            status=Position.Status.PLANNED,
            created_by=actor,
            created_in_structure_version=resulting_version,
            last_changed_in_structure_version=resulting_version,
        )
        _validate_position_reporting_graph(scope.positions, added_position=position)
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.MANUAL,
            resulting_version=resulting_version,
        )
        position.save(force_insert=True)
        VolunteerOpportunity.objects.create(
            position=position,
            status=VolunteerOpportunity.Status.DRAFT,
            headline=normalized_title,
            description=normalized_description,
            visible_when_filled=True,
            created_in_structure_version=resulting_version,
            last_changed_in_structure_version=resulting_version,
        )
        ensure_workforce_position_binding(position=position)
        changed_fields = ("opportunity", "position", "resource_binding")
        receipt = _append_change_evidence(
            scope=scope,
            actor=actor,
            control=control,
            action=EditionStructureCommandReceipt.Action.POSITION_CREATED,
            resulting_version=resulting_version,
            changed_fields=changed_fields,
            affected_department_ids=(department.id,),
            affected_position=position,
            reason=normalized_reason,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            retry_key=retry_key,
            request_digest=request_digest,
        )
        return PositionStructureResult(
            structure_id=control.id,
            receipt_id=receipt.id,
            position_id=position.id,
            resulting_version=resulting_version,
            changed_fields=changed_fields,
            action=receipt.action,
            replayed=False,
        )


def update_position(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    position_id: UUID,
    reports_to_id: UUID | None,
    title: str,
    description: str,
    headcount: int,
    expected_version: int,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> PositionStructureResult:
    """Replace the editable operational details of one current Position.

    Parameters
    ----------
    actor : Account
        Authenticated account authorizing and explaining the change.
    organization_id : UUID
        Organization that owns the exact edition.
    series_id : UUID
        Convention series in the persisted route chain.
    edition_id : UUID
        Editable event edition that owns the Position.
    position_id : UUID
        Current Position whose operational details are replaced.
    reports_to_id : UUID | None
        Optional current same-edition reporting Position.
    title : str
        Complete replacement responsibility title.
    description : str
        Complete replacement purpose and responsibilities.
    headcount : int
        Replacement approved holder ceiling.
    expected_version : int
        Exact structure version required for optimistic concurrency.
    reason : str
        Organizer rationale retained for a real change.
    correlation_id : UUID
        Correlation identifier shared by audit and domain-event evidence.
    request_id : UUID | None, default=None
        Incoming request identifier, or the correlation identifier when absent.
    source_channel : str, default='service'
        Closed channel code identifying the command adapter.

    Returns
    -------
    PositionStructureResult
        Committed aggregate evidence, or an unchanged same-version result.

    Raises
    ------
    StructureStateConflictError
        If the Position is closed or required aggregate evidence is absent.
    ValidationError
        If headcount or the resulting reporting graph is invalid.
    """
    position_id = _validate_uuid(position_id, field_name="position_id")
    if reports_to_id is not None:
        reports_to_id = _validate_uuid(reports_to_id, field_name="reports_to_id")
    normalized_title = normalize_position_title(title)
    normalized_description = normalize_position_description(description)
    normalized_headcount = validate_position_headcount(headcount)
    expected_version = _validate_expected_version(expected_version)
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    normalized_reason = normalize_structure_reason(reason)
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=timezone.now(),
    )

    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_editable_lifecycle(scope)
        current_version = _require_expected_version(scope, expected_version)
        position = _position_by_id(scope, position_id)
        if position.status == Position.Status.CLOSED:
            raise StructureStateConflictError("A closed Position is immutable.")
        manager = _reporting_position(
            scope,
            reports_to_id=reports_to_id,
            current_position_id=position.id,
        )
        open_assignments = tuple(
            PositionAssignment.objects.select_for_update()
            .filter(
                position_id=position.id,
                organization_id=scope.organization.id,
                edition_id=scope.edition.id,
                status__in=(
                    PositionAssignment.Status.PROPOSED,
                    PositionAssignment.Status.ACTIVE,
                ),
            )
            .order_by("id")
        )
        if normalized_headcount < len(open_assignments):
            raise ValidationError(
                {
                    "headcount": ValidationError(
                        (
                            "Headcount cannot be lower than current and proposed "
                            "assignments."
                        ),
                        code="structure_position_headcount_below_assignments",
                    )
                }
            )
        changed_fields = tuple(
            sorted(
                field
                for field, changed in (
                    ("description", position.description != normalized_description),
                    ("headcount", position.headcount != normalized_headcount),
                    ("reports_to", position.reports_to_id != reports_to_id),
                    ("title", position.title != normalized_title),
                )
                if changed
            )
        )
        if not changed_fields:
            if scope.control is None:
                raise StructureStateConflictError
            return PositionStructureResult(
                structure_id=scope.control.id,
                receipt_id=None,
                position_id=position.id,
                resulting_version=current_version,
                changed_fields=(),
                action=EditionStructureCommandReceipt.Action.POSITION_UPDATED,
                replayed=False,
            )
        _validate_position_reporting_graph(
            scope.positions,
            changed_position_id=position.id,
            changed_reports_to_id=reports_to_id,
        )
        resulting_version = current_version + 1
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.MANUAL,
            resulting_version=resulting_version,
        )
        position.title = normalized_title
        position.description = normalized_description
        position.headcount = normalized_headcount
        position.reports_to = manager
        position.last_changed_in_structure_version = resulting_version
        position.save(
            update_fields=(
                "title",
                "description",
                "headcount",
                "reports_to",
                "last_changed_in_structure_version",
                "updated_at",
            )
        )
        receipt = _append_change_evidence(
            scope=scope,
            actor=actor,
            control=control,
            action=EditionStructureCommandReceipt.Action.POSITION_UPDATED,
            resulting_version=resulting_version,
            changed_fields=changed_fields,
            affected_department_ids=(position.department_id,),
            affected_position=position,
            reason=normalized_reason,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        return PositionStructureResult(
            structure_id=control.id,
            receipt_id=receipt.id,
            position_id=position.id,
            resulting_version=resulting_version,
            changed_fields=changed_fields,
            action=receipt.action,
            replayed=False,
        )


_OPPORTUNITY_TRANSITIONS: dict[str, frozenset[str]] = {
    VolunteerOpportunity.Status.DRAFT: frozenset(
        {
            VolunteerOpportunity.Status.DRAFT,
            VolunteerOpportunity.Status.PUBLISHED,
            VolunteerOpportunity.Status.WITHDRAWN,
        }
    ),
    VolunteerOpportunity.Status.PUBLISHED: frozenset(
        {
            VolunteerOpportunity.Status.PUBLISHED,
            VolunteerOpportunity.Status.CLOSED,
            VolunteerOpportunity.Status.WITHDRAWN,
        }
    ),
    VolunteerOpportunity.Status.CLOSED: frozenset(
        {
            VolunteerOpportunity.Status.CLOSED,
            VolunteerOpportunity.Status.PUBLISHED,
            VolunteerOpportunity.Status.WITHDRAWN,
        }
    ),
    VolunteerOpportunity.Status.WITHDRAWN: frozenset(
        {VolunteerOpportunity.Status.WITHDRAWN}
    ),
}


def update_position_opportunity(  # noqa: PLR0912, PLR0915
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    position_id: UUID,
    status: str,
    headline: str,
    description: str,
    applications_open_at: datetime | None,
    applications_close_at: datetime | None,
    visible_when_filled: bool,
    expected_version: int,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> PositionStructureResult:
    """Replace the applicant-facing opportunity paired to one Position.

    Parameters
    ----------
    actor : Account
        Authenticated account authorizing and explaining the change.
    organization_id : UUID
        Organization that owns the exact edition.
    series_id : UUID
        Convention series in the persisted route chain.
    edition_id : UUID
        Editable event edition that owns the Position.
    position_id : UUID
        Current Position paired with the opportunity.
    status : str
        Requested opportunity lifecycle state.
    headline : str
        Complete applicant-facing headline.
    description : str
        Complete applicant-facing opportunity description.
    applications_open_at : datetime | None
        Optional aware instant when applications begin.
    applications_close_at : datetime | None
        Optional aware instant after opening when applications stop.
    visible_when_filled : bool
        Whether a filled opportunity remains publicly discoverable.
    expected_version : int
        Exact structure version required for optimistic concurrency.
    reason : str
        Organizer rationale retained for a real change.
    correlation_id : UUID
        Correlation identifier shared by audit and domain-event evidence.
    request_id : UUID | None, default=None
        Incoming request identifier, or the correlation identifier when absent.
    source_channel : str, default='service'
        Closed channel code identifying the command adapter.

    Returns
    -------
    PositionStructureResult
        Committed aggregate evidence, or an unchanged same-version result.

    Raises
    ------
    StructureStateConflictError
        If the Position is closed or required aggregate evidence is absent.
    ValidationError
        If the lifecycle, boolean, date-time, or application window is invalid.
    """
    position_id = _validate_uuid(position_id, field_name="position_id")
    if status not in VolunteerOpportunity.Status.values:
        raise ValidationError(
            {
                "status": ValidationError(
                    "Choose a supported opportunity status.",
                    code="structure_opportunity_status_invalid",
                )
            }
        )
    normalized_headline = normalize_opportunity_headline(headline)
    normalized_description = normalize_opportunity_description(description)
    if type(visible_when_filled) is not bool:
        raise ValidationError(
            {
                "visible_when_filled": ValidationError(
                    "Choose whether the opportunity remains visible when filled.",
                    code="structure_opportunity_visibility_invalid",
                )
            }
        )
    for field_name, date_value in (
        ("applications_open_at", applications_open_at),
        ("applications_close_at", applications_close_at),
    ):
        if date_value is not None and not timezone.is_aware(date_value):
            raise ValidationError(
                {
                    field_name: ValidationError(
                        "Enter a date and time with an explicit timezone.",
                        code="structure_opportunity_datetime_invalid",
                    )
                }
            )
    if (
        applications_open_at is not None
        and applications_close_at is not None
        and applications_close_at <= applications_open_at
    ):
        raise ValidationError(
            {
                "applications_close_at": ValidationError(
                    "Closing must be after opening.",
                    code="structure_opportunity_window_invalid",
                )
            }
        )
    expected_version = _validate_expected_version(expected_version)
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    normalized_reason = normalize_structure_reason(reason)
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=timezone.now(),
    )

    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_editable_lifecycle(scope)
        current_version = _require_expected_version(scope, expected_version)
        position = _position_by_id(scope, position_id)
        if position.status == Position.Status.CLOSED:
            raise StructureStateConflictError("A closed Position is immutable.")
        opportunity = (
            VolunteerOpportunity.objects.select_for_update()
            .filter(position_id=position.id)
            .order_by()
            .first()
        )
        current_status = (
            opportunity.status
            if opportunity is not None
            else VolunteerOpportunity.Status.DRAFT
        )
        if status not in _OPPORTUNITY_TRANSITIONS[current_status]:
            raise ValidationError(
                {
                    "status": ValidationError(
                        "That opportunity lifecycle transition is not available.",
                        code="structure_opportunity_transition_invalid",
                    )
                }
            )
        values = {
            "status": status,
            "headline": normalized_headline,
            "description": normalized_description,
            "applications_open_at": applications_open_at,
            "applications_close_at": applications_close_at,
            "visible_when_filled": visible_when_filled,
        }
        if opportunity is None:
            changed_fields = tuple(sorted(f"opportunity.{key}" for key in values))
        else:
            changed_fields = tuple(
                sorted(
                    f"opportunity.{field}"
                    for field, value in values.items()
                    if getattr(opportunity, field) != value
                )
            )
        position_opens = (
            status == VolunteerOpportunity.Status.PUBLISHED
            and position.status == Position.Status.PLANNED
        )
        if position_opens:
            changed_fields = tuple(sorted((*changed_fields, "status")))
        if not changed_fields:
            if scope.control is None:
                raise StructureStateConflictError
            return PositionStructureResult(
                structure_id=scope.control.id,
                receipt_id=None,
                position_id=position.id,
                resulting_version=current_version,
                changed_fields=(),
                action=EditionStructureCommandReceipt.Action.OPPORTUNITY_UPDATED,
                replayed=False,
            )
        resulting_version = current_version + 1
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.MANUAL,
            resulting_version=resulting_version,
        )
        if opportunity is None:
            opportunity = VolunteerOpportunity(
                position=position,
                created_in_structure_version=resulting_version,
            )
        for field, field_value in values.items():
            setattr(opportunity, field, field_value)
        opportunity.last_changed_in_structure_version = resulting_version
        opportunity.save()
        if position_opens:
            position.status = Position.Status.OPEN
            position.last_changed_in_structure_version = resulting_version
            position.save(
                update_fields=(
                    "status",
                    "last_changed_in_structure_version",
                    "updated_at",
                )
            )
        receipt = _append_change_evidence(
            scope=scope,
            actor=actor,
            control=control,
            action=EditionStructureCommandReceipt.Action.OPPORTUNITY_UPDATED,
            resulting_version=resulting_version,
            changed_fields=changed_fields,
            affected_department_ids=(position.department_id,),
            affected_position=position,
            reason=normalized_reason,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        return PositionStructureResult(
            structure_id=control.id,
            receipt_id=receipt.id,
            position_id=position.id,
            resulting_version=resulting_version,
            changed_fields=changed_fields,
            action=receipt.action,
            replayed=False,
        )


def close_position(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    position_id: UUID,
    expected_version: int,
    confirmation_name: str,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> PositionStructureResult:
    """Close one dependency-free Position and stop its opportunity.

    Parameters
    ----------
    actor : Account
        Authenticated account authorizing and explaining the closure.
    organization_id : UUID
        Organization that owns the exact edition.
    series_id : UUID
        Convention series in the persisted route chain.
    edition_id : UUID
        Editable event edition that owns the Position.
    position_id : UUID
        Current Position to preserve as closed history.
    expected_version : int
        Exact structure version required for optimistic concurrency.
    confirmation_name : str
        Exact current Position title used as destructive-action confirmation.
    reason : str
        Organizer rationale retained with the closure receipt.
    correlation_id : UUID
        Correlation identifier shared by audit and domain-event evidence.
    request_id : UUID | None, default=None
        Incoming request identifier, or the correlation identifier when absent.
    source_channel : str, default='service'
        Closed channel code identifying the command adapter.

    Returns
    -------
    PositionStructureResult
        Minimized Position identifier and committed closure evidence.

    Raises
    ------
    StructureDependencyConflictError
        If assignments, direct reports, or scoped authority still depend on it.
    StructureStateConflictError
        If the Position is already closed.
    """
    position_id = _validate_uuid(position_id, field_name="position_id")
    expected_version = _validate_expected_version(expected_version)
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    normalized_reason = normalize_structure_reason(reason)
    _require_view_and_manage(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        at=timezone.now(),
    )

    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_editable_lifecycle(scope)
        current_version = _require_expected_version(scope, expected_version)
        position = _position_by_id(scope, position_id)
        if position.status == Position.Status.CLOSED:
            raise StructureStateConflictError("The Position is already closed.")
        validate_exact_confirmation(confirmation_name, expected=position.title)
        open_assignments = PositionAssignment.objects.select_for_update().filter(
            position_id=position.id,
            organization_id=scope.organization.id,
            edition_id=scope.edition.id,
            status__in=(
                PositionAssignment.Status.PROPOSED,
                PositionAssignment.Status.ACTIVE,
            ),
        )
        unfinished_shift_demands = ShiftDemand.objects.select_for_update().filter(
            position_id=position.id,
            organization_id=scope.organization.id,
            edition_id=scope.edition.id,
            status__in=(
                ShiftDemand.Status.DRAFT,
                ShiftDemand.Status.OPEN,
                ShiftDemand.Status.LOCKED,
            ),
        )
        if unfinished_shift_demands.exists():
            raise StructureDependencyConflictError(
                "Draft, open, or locked Shifts still depend on this Position. "
                "Complete or cancel them before closing it."
            )
        has_current_direct_report = any(
            item.reports_to_id == position.id and item.status != Position.Status.CLOSED
            for item in scope.positions
        )
        if (
            open_assignments.exists()
            or has_current_direct_report
            or _position_authority_is_open(scope, position)
        ):
            raise StructureDependencyConflictError(
                "Current assignments, reports, or authority protect this Position."
            )
        opportunity = (
            VolunteerOpportunity.objects.select_for_update()
            .filter(position_id=position.id)
            .order_by()
            .first()
        )
        resulting_version = current_version + 1
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.MANUAL,
            resulting_version=resulting_version,
        )
        position.status = Position.Status.CLOSED
        position.closed_at = scope.evaluated_at
        position.closed_by = actor
        position.last_changed_in_structure_version = resulting_version
        position.save(
            update_fields=(
                "status",
                "closed_at",
                "closed_by",
                "last_changed_in_structure_version",
                "updated_at",
            )
        )
        changed_fields = ["closure"]
        if opportunity is not None and opportunity.status not in {
            VolunteerOpportunity.Status.WITHDRAWN,
            VolunteerOpportunity.Status.CLOSED,
        }:
            opportunity.status = VolunteerOpportunity.Status.CLOSED
            opportunity.last_changed_in_structure_version = resulting_version
            opportunity.save(
                update_fields=(
                    "status",
                    "last_changed_in_structure_version",
                    "updated_at",
                )
            )
            changed_fields.append("opportunity.status")
        canonical_changed_fields = tuple(sorted(changed_fields))
        receipt = _append_change_evidence(
            scope=scope,
            actor=actor,
            control=control,
            action=EditionStructureCommandReceipt.Action.POSITION_CLOSED,
            resulting_version=resulting_version,
            changed_fields=canonical_changed_fields,
            affected_department_ids=(position.department_id,),
            affected_position=position,
            reason=normalized_reason,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        return PositionStructureResult(
            structure_id=control.id,
            receipt_id=receipt.id,
            position_id=position.id,
            resulting_version=resulting_version,
            changed_fields=canonical_changed_fields,
            action=receipt.action,
            replayed=False,
        )
