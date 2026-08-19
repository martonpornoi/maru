"""Shared, unmounted Page 9a.1 Department structure commands.

The HTML and API adapters deliberately do not exist yet.  This module is the
single transaction boundary they will call once Page 9a.1 is mounted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError, RestrictedError
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision, decide, resolve_edition_target
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
)
from maru.workforce.queries import MAX_STRUCTURE_DEPARTMENTS, MAX_STRUCTURE_DEPTH
from maru.workforce.structure_inputs import (
    MAX_DEPARTMENT_DISPLAY_ORDER,
    canonical_request_digest,
    generate_department_code,
    normalize_department_description,
    normalize_department_name,
    normalize_structure_reason,
    validate_department_display_order,
    validate_exact_confirmation,
)
from maru.workforce.structure_templates import (
    UnknownBuiltinStructureTemplateError,
    get_builtin_structure_template,
)
from maru.workforce.writer_boundary import lock_edition_structure_mutex

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
    """Keep a unique current rank or append safely after the locked siblings."""

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
        raise StructureLimitConflictError()

    appended_order = max(sibling_orders, default=-1) + 1
    if appended_order <= MAX_DEPARTMENT_DISPLAY_ORDER:
        return appended_order

    # The edition-wide Department ceiling makes exhaustion impossible in the
    # current contract, but use a bounded gap fallback so the helper remains
    # correct if a historical/API-supplied sibling already uses the maximum.
    for candidate in range(MAX_DEPARTMENT_DISPLAY_ORDER + 1):
        if candidate not in sibling_orders:
            return candidate
    raise StructureLimitConflictError()


class StructureCommandError(RuntimeError):
    """Base for stable, adapter-safe Page 9 command failures."""

    reason_code = "structure_command_failed"

    def __init__(self, message: str = "The structure command could not complete."):
        super().__init__(message)


class StructureAuthorizationDeniedError(StructureCommandError):
    reason_code = "structure_authorization_denied"


class StructureDepartmentUnavailableError(StructureCommandError):
    reason_code = "structure_department_unavailable"


class StructureVersionConflictError(StructureCommandError):
    reason_code = "structure_version_conflict"


class StructureRetryConflictError(StructureCommandError):
    reason_code = "structure_retry_conflict"


class StructureLifecycleConflictError(StructureCommandError):
    reason_code = "structure_lifecycle_conflict"


class StructureStateConflictError(StructureCommandError):
    reason_code = "structure_state_conflict"


class StructureDependencyConflictError(StructureCommandError):
    reason_code = "structure_department_has_dependencies"


class StructureLimitConflictError(StructureCommandError):
    reason_code = "structure_limit_exceeded"


@dataclass(frozen=True, slots=True)
class BuiltinStructureTemplateResult:
    structure_id: UUID
    receipt_id: UUID
    resulting_version: int
    department_ids: tuple[UUID, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class DepartmentStructureResult:
    structure_id: UUID
    receipt_id: UUID | None
    department_id: UUID
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
        raise StructureAuthorizationDeniedError()
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if target is None:
        raise StructureAuthorizationDeniedError()
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
        raise StructureAuthorizationDeniedError()
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
        raise StructureAuthorizationDeniedError()
    return manage


def _lock_scope(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> _LockedScope:
    """Apply ADR 0045's complete cross-module lock order."""

    lock_retired_department_authority_boundaries()
    organization = (
        Organization.objects.select_for_update().filter(id=organization_id).first()
    )
    if organization is None:
        raise StructureAuthorizationDeniedError()
    series = (
        ConventionSeries.objects.select_for_update()
        .filter(id=series_id, organization_id=organization.id)
        .first()
    )
    if series is None:
        raise StructureAuthorizationDeniedError()
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
        raise StructureAuthorizationDeniedError()
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
        raise StructureLimitConflictError()
    persisted_actor = Account.objects.select_for_update().filter(pk=actor.pk).first()
    if persisted_actor is None:
        raise StructureAuthorizationDeniedError()
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
        manage_decision=manage_decision,
        evaluated_at=evaluated_at,
    )


def _require_editable_lifecycle(scope: _LockedScope) -> None:
    if (
        scope.organization.lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
        or scope.edition.lifecycle not in _EDITABLE_EDITION_LIFECYCLES
    ):
        raise StructureLifecycleConflictError()


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
    if Position.objects.filter(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
    ).exists():
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
        raise StructureVersionConflictError()
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
        raise StructureRetryConflictError()


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
        raise StructureDepartmentUnavailableError()
    return department


def _validate_resulting_hierarchy(
    departments: tuple[Department, ...],
    *,
    changed_department_id: UUID | None = None,
    changed_parent_id: UUID | None = None,
) -> None:
    if len(departments) > MAX_STRUCTURE_DEPARTMENTS:
        raise StructureLimitConflictError()
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
                raise StructureLimitConflictError()
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
    """Copy one immutable built-in Department template into an empty edition."""

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
            raise StructureLimitConflictError()

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
    """Create one edition-owned Department with deterministic code generation."""

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
            raise StructureLimitConflictError()
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
    """Completely replace one current Department's editable properties."""

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
    """Retire one dependency-free current Department without deleting history."""

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
                raise StructureDependencyConflictError()
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
            raise StructureDependencyConflictError() from error
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
    """

    try:
        with transaction.atomic():
            deleted_count, _detail = department.delete()
    except (ProtectedError, RestrictedError) as error:
        raise StructureDependencyConflictError() from error
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
            raise StructureDependencyConflictError() from error
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
    """Hard-delete one provably unused, command-created current leaf."""

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
            raise StructureDependencyConflictError()
        resulting_version = current_version + 1
        deleted_name = department.name
        if scope.control is None:
            raise StructureStateConflictError()
        control = _new_or_advanced_control(
            scope=scope,
            origin=EditionStructureControl.Origin.MANUAL,
            resulting_version=resulting_version,
        )
        deleted_count = _delete_department_without_cascade(department)
        if deleted_count != 1:
            raise StructureDependencyConflictError()
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
