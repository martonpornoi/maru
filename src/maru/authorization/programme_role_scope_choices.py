"""Complete bounded access-scope discovery without a Workforce personnel directory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import ScopeLevel
from maru.authorization.models import ScopedResourceBinding
from maru.authorization.page_access_workspace import page_access_scope_label
from maru.authorization.programme_role_boundary import (
    _lock_people,
    _lock_scope,
    _require_current_controller,
    _require_integrity,
    _require_profile,
    _resolve_scope,
    _unavailable,
    _validate_context,
    _validate_scope,
)
from maru.authorization.programme_role_inputs import ProgrammeRoleScope
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account
from maru.workforce.queries import (
    MAX_STRUCTURE_DEPARTMENTS,
    CurrentDepartmentSetReference,
    resolve_current_department_set_reference,
)

if TYPE_CHECKING:
    from maru.authorization.policy import ResolvedAuthorizationTarget

MAX_PROGRAMME_ACCESS_ROOMS = 256
_INCOMPLETE = (
    "Programme access scope choices cannot be shown completely. "
    "No partial list is shown."
)


@dataclass(frozen=True, slots=True)
class ProgrammeRoleScopeChoice:
    """Name an independently admitted actual access-management target.

    Attributes
    ----------
    scope
        Full exact owner/context/target chain, never inherited sibling permission.
    label
        Authorized current owner label, empty only inside metadata-only discovery.
    """

    scope: ProgrammeRoleScope
    label: str

    @property
    def purpose(self) -> str:
        """Return code-owned scope wording rather than a generic resource label."""
        return {
            ScopeLevel.ORGANIZATION: "Shared Organization Venue access",
            ScopeLevel.EDITION: "Edition access",
            ScopeLevel.DEPARTMENT: "Department access",
            ScopeLevel.RESOURCE: "Selected room access",
        }[self.scope.level]


@dataclass(frozen=True, slots=True)
class ProgrammeRoleScopeCatalog:
    """Retain the complete currently admitted scope list and context label.

    Attributes
    ----------
    context_label
        Independently admitted Programme context, never a tenant discovery result.
    choices
        Complete bounded authorized targets, with no denied target names/counts.
    """

    context_label: str
    choices: tuple[ProgrammeRoleScopeChoice, ...]


def _candidate_scopes(context: ProgrammeRoleScope) -> tuple[ProgrammeRoleScope, ...]:
    members = resolve_current_department_set_reference(
        organization_id=context.organization_id,
        edition_id=context.programme_edition_id,
    )
    if (
        not isinstance(members, CurrentDepartmentSetReference)
        or members.organization_id != context.organization_id
        or members.edition_id != context.programme_edition_id
        or not isinstance(members.department_ids, tuple)
        or len(members.department_ids) > MAX_STRUCTURE_DEPARTMENTS
        or any(
            not isinstance(value, UUID) or not value.int
            for value in members.department_ids
        )
        or len(set(members.department_ids)) != len(members.department_ids)
    ):
        raise ValidationError(
            _INCOMPLETE, code="programme_role_scope_inventory_unavailable"
        )
    departments = tuple(sorted(members.department_ids))
    rooms = tuple(
        ScopedResourceBinding.objects.filter(
            organization_id=context.organization_id,
            edition_id=context.programme_edition_id,
            department_id__in=departments,
            resource_kind="venue.edition_space",
        )
        .order_by("department_id", "id")
        .values_list("department_id", "id")[: MAX_PROGRAMME_ACCESS_ROOMS + 1]
    )
    if (
        len(rooms) > MAX_PROGRAMME_ACCESS_ROOMS
        or any(
            department_id not in departments
            or not isinstance(binding_id, UUID)
            or not binding_id.int
            for department_id, binding_id in rooms
        )
        or len({binding_id for _, binding_id in rooms}) != len(rooms)
    ):
        raise ValidationError(
            _INCOMPLETE, code="programme_role_scope_inventory_unavailable"
        )
    common = (context.organization_id, context.programme_edition_id)
    return (
        ProgrammeRoleScope(*common, ScopeLevel.ORGANIZATION),
        context,
        *(
            ProgrammeRoleScope(*common, ScopeLevel.DEPARTMENT, identifier)
            for identifier in departments
        ),
        *(
            ProgrammeRoleScope(
                *common,
                ScopeLevel.RESOURCE,
                department_id,
                binding_id,
                "venue.edition_space",
            )
            for department_id, binding_id in rooms
        ),
    )


def _admitted(
    actor: Account,
    context: ProgrammeRoleScope,
) -> tuple[tuple[ProgrammeRoleScope, ResolvedAuthorizationTarget], ...]:
    result = []
    for scope in _candidate_scopes(context):
        try:
            target = _resolve_scope(scope)
            _require_current_controller(actor, target)
        except AuthorizationDenied:
            continue
        result.append((scope, target))
    return tuple(result)


def _snapshot(
    actor: Account,
    context: ProgrammeRoleScope,
    *,
    labels: bool,
) -> ProgrammeRoleScopeCatalog:
    admitted = _admitted(actor, context)
    if not admitted:
        raise _unavailable()
    choices = tuple(
        ProgrammeRoleScopeChoice(
            scope, page_access_scope_label(target) if labels else ""
        )
        for scope, target in admitted
    )
    return ProgrammeRoleScopeCatalog(
        page_access_scope_label(_resolve_scope(context)) if labels else "",
        choices,
    )


def _query(
    actor: Account,
    context: ProgrammeRoleScope,
    correlation_id: UUID | None,
    source_channel: str,
) -> ProgrammeRoleScopeCatalog:
    _require_profile()
    _validate_scope(context)
    if (
        context.level is not ScopeLevel.EDITION
        or not isinstance(actor, Account)
        or not isinstance(actor.id, UUID)
        or not actor.id.int
        or not actor.is_active
        or actor.account_kind != Account.Kind.PERSON
        or actor.email_verified_at is None
    ):
        raise _unavailable()
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        _lock_scope(context)
        current = _lock_people({actor.id})[actor.id]
        _require_profile()
        _require_integrity()
        initial = _snapshot(current, context, labels=correlation_id is not None)
        _require_profile()
        if _snapshot(current, context, labels=correlation_id is not None) != initial:
            raise ValidationError(
                _INCOMPLETE, code="programme_role_scope_source_changed"
            )
        if correlation_id is not None:
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=current.id,
                    principal_context_id=None,
                    organization_id=context.organization_id,
                    event_edition_id=context.programme_edition_id,
                    capability_code="authorization.manage_roles",
                    operation="authorization.programme_role.scopes.read",
                    target_type="authorization.programme_role_scope",
                    target_id=context.programme_edition_id,
                    outcome="allow",
                    reason_code="current_controller_scope_discovery",
                    correlation_id=correlation_id,
                    source_channel=source_channel,
                    obligations=("audit_sensitive_read",),
                    safe_metadata={"target_count": len(initial.choices)},
                    retention_class="security-extended",
                )
            )
        return initial


def load_programme_role_scope_choices(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ProgrammeRoleScopeCatalog:
    """Read complete independently authorized labels for choosing actual access scope.

    Parameters
    ----------
    actor : Account
        Actual authenticated ordinary verified person, reloaded under owner locks.
    organization_id : UUID
        Exact expected tenant, not permission to enumerate another organization.
    edition_id : UUID
        Exact Programme context shared by all candidate scope levels.
    correlation_id : UUID
        Nonempty server trace for mandatory sensitive-read evidence.
    source_channel : str, default='service'
        Bounded lowercase audit channel.

    Returns
    -------
    ProgrammeRoleScopeCatalog
        Audited bounded current labels, not a grant or authority to sibling targets.

    Notes
    -----
    No admitted scope means non-disclosing denial. Incomplete/overflow/moved sources
    are unavailable without a partial list. Current profiles deny before database
    access. Every destination reauthorizes; adapters recheck after rendering.
    """
    _validate_context(correlation_id, correlation_id, source_channel)
    return _query(
        actor,
        ProgrammeRoleScope(organization_id, edition_id, ScopeLevel.EDITION),
        correlation_id,
        source_channel,
    )


def can_enter_programme_role_scopes(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
) -> bool:
    """Admit a fixed-label entry without names or activity audit.

    Parameters
    ----------
    actor : Account
        Actual current ordinary person, never a platform-administration fallback.
    organization_id : UUID
        Exact expected owner of the chosen Programme context.
    edition_id : UUID
        Exact Programme edition; no other tenant or edition is discovered.

    Returns
    -------
    bool
        Whether at least one current persistent controller target is admitted.
        False also covers unavailable sources and makes no completeness claim.
    """
    try:
        return bool(
            _query(
                actor,
                ProgrammeRoleScope(organization_id, edition_id, ScopeLevel.EDITION),
                None,
                "navigation",
            ).choices
        )
    except (AuthorizationDenied, ValidationError, DatabaseError):
        return False
