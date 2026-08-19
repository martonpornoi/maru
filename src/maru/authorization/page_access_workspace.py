"""Queries and disclosure records for the server-rendered access workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.access import MANAGE_ACCESS_CAPABILITY
from maru.authorization.api import ACCESS_GROUP_LABELS, NON_SHAREABLE_ROLE_CODES
from maru.authorization.catalog import POLICY_VERSION, ScopeLevel, capability
from maru.authorization.models import (
    RoleAssignment,
    RoleBundle,
    ScopedResourceBinding,
)
from maru.authorization.policy import ResolvedAuthorizationTarget, decide
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import Department


@dataclass(frozen=True, slots=True)
class PageAccessRole:
    id: UUID
    code: str
    name: str
    version: int
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PageAccessAssignment:
    id: UUID
    person_name: str
    person_email: str
    role_name: str
    role_version: int
    scope_label: str
    exact_scope: bool
    expires_at: object | None


@dataclass(frozen=True, slots=True)
class PageAccessWorkspace:
    scope_label: str
    scope_level: str
    roles: tuple[PageAccessRole, ...]
    assignments: tuple[PageAccessAssignment, ...]
    can_revoke: bool


_SCOPE_DEPTH = {
    ScopeLevel.ORGANIZATION: 0,
    ScopeLevel.EDITION: 1,
    ScopeLevel.DEPARTMENT: 2,
    ScopeLevel.RESOURCE: 3,
}


def require_page_access_authority(
    *,
    actor: Account,
    target: ResolvedAuthorizationTarget,
) -> None:
    decision = decide(
        principal=actor,
        capability_code=MANAGE_ACCESS_CAPABILITY,
        resource=target,
    )
    if not decision.allowed:
        raise PermissionDenied("Access management is unavailable.")


def audit_page_access_relationship_denial(
    *,
    actor: Account,
    target: ResolvedAuthorizationTarget,
    correlation_id: UUID,
) -> None:
    decision = decide(
        principal=actor,
        capability_code=MANAGE_ACCESS_CAPABILITY,
        resource=target,
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=target.organization_id,
            event_edition_id=target.edition_id,
            capability_code=MANAGE_ACCESS_CAPABILITY,
            operation="authorization.page_access.relationships.view",
            target_type="authorization.role_assignment",
            target_id=None,
            outcome=AuditEvent.Outcome.DENY,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="html",
            obligations=("audit_sensitive_read",),
            safe_metadata={
                "policy_version": POLICY_VERSION,
            },
            retention_class="security-extended",
        )
    )


def page_access_scope_label(target: ResolvedAuthorizationTarget) -> str:
    organization = Organization.objects.filter(pk=target.organization_id).first()
    if organization is None:
        raise PermissionDenied("Access management is unavailable.")
    if target.edition_id is None:
        return organization.name
    edition = EventEdition.objects.filter(
        pk=target.edition_id,
        organization_id=target.organization_id,
    ).first()
    if edition is None:
        raise PermissionDenied("Access management is unavailable.")
    if target.department_id is None:
        return f"{organization.name} / {edition.name}"
    department = Department.objects.filter(
        pk=target.department_id,
        organization_id=target.organization_id,
        edition_id=target.edition_id,
        retired_at__isnull=True,
    ).first()
    if department is None:
        raise PermissionDenied("Access management is unavailable.")
    if target.resource_binding_id is None:
        return f"{edition.name} / {department.name}"
    binding = ScopedResourceBinding.objects.filter(
        pk=target.resource_binding_id,
        organization_id=target.organization_id,
        edition_id=target.edition_id,
        department_id=target.department_id,
    ).first()
    if binding is None:
        raise PermissionDenied("Access management is unavailable.")
    return f"{edition.name} / {department.name} / {_resource_label(binding)}"


def _resource_label(binding: ScopedResourceBinding) -> str:
    if binding.resource_kind == ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION:
        from maru.workforce.models import Position  # noqa: PLC0415

        title = (
            Position.objects.filter(pk=binding.resource_id)
            .values_list("title", flat=True)
            .first()
        )
        return str(title or "Position")
    if binding.resource_kind == ScopedResourceBinding.ResourceKind.CHARITY_SELECTION:
        from maru.charities.models import CharitySelection  # noqa: PLC0415

        name = (
            CharitySelection.objects.filter(pk=binding.resource_id)
            .values_list("partner__public_name", flat=True)
            .first()
        )
        return f"Charity selection: {name or 'review'}"
    if binding.resource_kind == ScopedResourceBinding.ResourceKind.VENUE_EDITION_SPACE:
        from maru.venues.models import EditionSpaceSelection  # noqa: PLC0415

        name = (
            EditionSpaceSelection.objects.filter(pk=binding.resource_id)
            .values_list("source_space__name", flat=True)
            .first()
        )
        return f"Venue space: {name or 'schedule'}"
    return "Typed resource"


def _roles_for_target(
    target: ResolvedAuthorizationTarget,
) -> tuple[PageAccessRole, ...]:
    latest: dict[str, RoleBundle] = {}
    for role in (
        RoleBundle.objects.filter(organization_id=target.organization_id)
        .exclude(code__in=NON_SHAREABLE_ROLE_CODES)
        .order_by("code", "-version", "id")
    ):
        latest.setdefault(role.code, role)
    values: list[PageAccessRole] = []
    for role in latest.values():
        definitions = tuple(capability(code) for code in role.capability_codes)
        if any(
            definition is None
            or not definition.persistable
            or _SCOPE_DEPTH[target.scope_level] < _SCOPE_DEPTH[definition.maximum_scope]
            for definition in definitions
        ):
            continue
        values.append(
            PageAccessRole(
                id=role.id,
                code=role.code,
                name=ACCESS_GROUP_LABELS.get(role.code, role.name),
                version=role.version,
                capabilities=tuple(role.capability_codes),
            )
        )
    return tuple(sorted(values, key=lambda value: (value.name.casefold(), value.code)))


def _authority_scope_filter(target: ResolvedAuthorizationTarget) -> Q:
    organization_scope = Q(
        edition__isnull=True,
        department__isnull=True,
        resource_binding__isnull=True,
    )
    if target.edition_id is None:
        return organization_scope
    edition_scope = Q(
        edition_id=target.edition_id,
        department__isnull=True,
        resource_binding__isnull=True,
    )
    if target.department_id is None:
        return organization_scope | edition_scope
    department_scope = Q(
        edition_id=target.edition_id,
        department_id=target.department_id,
        resource_binding__isnull=True,
    )
    if target.resource_binding_id is None:
        return organization_scope | edition_scope | department_scope
    return (
        organization_scope
        | edition_scope
        | department_scope
        | Q(
            edition_id=target.edition_id,
            department_id=target.department_id,
            resource_binding_id=target.resource_binding_id,
        )
    )


def _exact_scope(
    assignment: RoleAssignment,
    target: ResolvedAuthorizationTarget,
) -> bool:
    return (
        assignment.organization_id == target.organization_id
        and assignment.edition_id == target.edition_id
        and assignment.department_id == target.department_id
        and assignment.resource_binding_id == target.resource_binding_id
    )


def _assignment_scope_label(assignment: RoleAssignment) -> str:
    if assignment.resource_binding_id is not None:
        return "Exact typed resource"
    if assignment.department_id is not None:
        department = cast(Department, assignment.department)
        return f"Department: {department.name}"
    if assignment.edition_id is not None:
        edition = cast(EventEdition, assignment.edition)
        return f"Edition: {edition.name}"
    return "All organizer editions"


def _assignments_for_target(
    target: ResolvedAuthorizationTarget,
) -> tuple[PageAccessAssignment, ...]:
    now = timezone.now()
    rows = (
        RoleAssignment.objects.filter(
            _authority_scope_filter(target),
            organization_id=target.organization_id,
            revoked_at__isnull=True,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .exclude(role_bundle__code__in=NON_SHAREABLE_ROLE_CODES)
        .select_related(
            "principal",
            "role_bundle",
            "edition",
            "department",
        )
        .order_by("role_bundle__name", "principal__display_name", "id")
    )
    return tuple(
        PageAccessAssignment(
            id=row.id,
            person_name=row.principal.display_name or row.principal.email,
            person_email=row.principal.email,
            role_name=ACCESS_GROUP_LABELS.get(
                row.role_bundle.code,
                row.role_bundle.name,
            ),
            role_version=row.role_bundle.version,
            scope_label=_assignment_scope_label(row),
            exact_scope=_exact_scope(row, target),
            expires_at=row.expires_at,
        )
        for row in rows
    )


def load_page_access_workspace(
    *,
    actor: Account,
    target: ResolvedAuthorizationTarget,
    correlation_id: UUID,
) -> PageAccessWorkspace:
    """Read relationship names only after authority and append an audit row."""

    require_page_access_authority(actor=actor, target=target)
    assignments = _assignments_for_target(target)
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=target.organization_id,
            event_edition_id=target.edition_id,
            capability_code=MANAGE_ACCESS_CAPABILITY,
            operation="authorization.page_access.relationships.view",
            target_type="authorization.role_assignment",
            target_id=None,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="computed_scoped_access",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="html",
            obligations=("audit_sensitive_read",),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "target_count": len(assignments),
            },
            retention_class="security-extended",
        )
    )
    return PageAccessWorkspace(
        scope_label=page_access_scope_label(target),
        scope_level=target.scope_level.value,
        roles=_roles_for_target(target),
        assignments=assignments,
        can_revoke=decide(
            principal=actor,
            capability_code="authorization.revoke",
            resource=target,
        ).allowed,
    )


def exact_active_person(email: str) -> Account:
    account = Account.objects.filter(
        email__iexact=email.strip(),
        is_active=True,
        account_kind=Account.Kind.PERSON,
    ).first()
    if account is None:
        raise ValidationError(
            {"person_email": "No active person matches that exact email address."}
        )
    return account


def exact_role_version(
    *,
    target: ResolvedAuthorizationTarget,
    role_version_id: UUID,
) -> RoleBundle:
    role = (
        RoleBundle.objects.filter(
            pk=role_version_id,
            organization_id=target.organization_id,
        )
        .exclude(code__in=NON_SHAREABLE_ROLE_CODES)
        .first()
    )
    if role is None:
        raise ValidationError(
            {"role_version_id": "Choose an available immutable group version."}
        )
    return role


def exact_active_approver(email: str) -> Account:
    account = Account.objects.filter(
        email__iexact=email.strip(),
        is_active=True,
    ).first()
    if account is None:
        raise ValidationError(
            {"approver_email": "No active account matches that exact email address."}
        )
    return account


def exact_assignment_for_target(
    *,
    target: ResolvedAuthorizationTarget,
    assignment_id: UUID,
) -> RoleAssignment:
    assignments = RoleAssignment.objects.filter(
        pk=assignment_id,
        organization_id=target.organization_id,
        edition_id=target.edition_id,
        resource_binding_id=target.resource_binding_id,
        revoked_at__isnull=True,
    )
    if target.department_id is None:
        assignments = assignments.filter(department__isnull=True)
    else:
        assignments = assignments.filter(department_id=target.department_id)
    assignment = assignments.exclude(
        role_bundle__code__in=NON_SHAREABLE_ROLE_CODES
    ).first()
    if assignment is None:
        raise PermissionDenied("The access assignment is unavailable.")
    return assignment


def audit_page_access_preview(
    *,
    actor: Account,
    target: ResolvedAuthorizationTarget,
    correlation_id: UUID,
    outcome: str,
    reason_code: str,
    mode: str,
    subject_id: UUID | None = None,
    target_count: int | None = None,
) -> None:
    metadata: dict[str, object] = {
        "policy_version": POLICY_VERSION,
        "contract_version": "access-preview.v1",
    }
    if target_count is not None:
        metadata["target_count"] = target_count
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=target.organization_id,
            event_edition_id=target.edition_id,
            capability_code=MANAGE_ACCESS_CAPABILITY,
            operation="authorization.access_preview.view",
            target_type=(
                "identity.account" if mode == "person" else "authorization.role_bundle"
            ),
            target_id=subject_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="html",
            obligations=("audit_sensitive_read",),
            safe_metadata=metadata,
            retention_class="security-extended",
        )
    )
