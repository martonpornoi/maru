"""Reference volunteer opportunity and private document views."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.timezone import now as timezone_now
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.enforcement import (
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import (
    PolicyDecision,
    ResolvedAuthorizationTarget,
    decide,
    resolve_edition_target,
    resolve_organization_target,
    resolve_owned_target,
)
from maru.events.admin_context import authorized_admin_edition_for_route
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.organizations.queries import (
    ExecutiveBoardAnchor,
    executive_board_governance_anchor,
)
from maru.workforce.forms import (
    DepartmentCreationForm,
    DepartmentDeletionForm,
    DepartmentParentChoices,
    DepartmentRetirementForm,
    DepartmentUpdateForm,
    OnboardingDocumentUploadForm,
    StructureTemplateApplicationForm,
    VolunteerApplicationForm,
)
from maru.workforce.models import (
    OnboardingDocumentRequest,
    VolunteerApplication,
    VolunteerOpportunity,
)
from maru.workforce.queries import (
    WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
    DepartmentNode,
    EditionStructureProjection,
    project_edition_structure,
)
from maru.workforce.services import (
    submit_volunteer_application,
    upload_onboarding_document,
)
from maru.workforce.structure_audit import append_structure_read_audit
from maru.workforce.structure_commands import (
    StructureAuthorizationDeniedError,
    StructureCommandError,
    StructureDepartmentUnavailableError,
    StructureDependencyConflictError,
    StructureLifecycleConflictError,
    StructureLimitConflictError,
    StructureRetryConflictError,
    StructureStateConflictError,
    StructureVersionConflictError,
    apply_builtin_structure_template,
    create_department,
    delete_unused_department,
    retire_department,
    update_department,
)
from maru.workforce.structure_snapshot import (
    StructureSnapshotRead,
    load_version_fenced_snapshot,
)

logger = logging.getLogger(__name__)


def _account(request: HttpRequest) -> Account | None:
    return request.user if isinstance(request.user, Account) else None


def _active_admin_account(request: HttpRequest) -> Account:
    account = _account(request)
    if account is None or not account.is_active:
        raise PermissionDenied
    return account


def _structure_access_label(decision: PolicyDecision) -> str:
    return {
        "platform_administration": "Platform oversight",
        "direct_grant": "Exact edition capability",
        "role_assignment": "Scoped edition role",
    }.get(decision.reason_code, "Current scoped authority")


def _required_organization_target(
    *,
    organization_id: UUID,
) -> ResolvedAuthorizationTarget:
    target = resolve_organization_target(organization_id=organization_id)
    if target is None:
        raise RuntimeError("The resolved edition lost its organization target.")
    return target


@dataclass(frozen=True, slots=True)
class _OrganizationStructureSnapshot:
    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    governance: ExecutiveBoardAnchor
    structure: EditionStructureProjection
    can_manage_structure: bool
    can_view_organization: bool
    can_manage_representation: bool
    can_create_series: bool
    can_create_edition: bool
    can_view_edition: bool
    can_manage_registration: bool


@dataclass(frozen=True, slots=True)
class _OrganizationStructurePageRead:
    snapshot: _OrganizationStructureSnapshot
    view_decision: PolicyDecision
    manage_decision: PolicyDecision

    @property
    def can_manage_structure(self) -> bool:
        return self.snapshot.can_manage_structure and self.manage_decision.allowed


class _StructurePostQueryParametersUnsupportedError(Exception):
    """Stop a POST after route policy but before any name-bearing projection."""


@dataclass(frozen=True, slots=True)
class _DepartmentTreeItem:
    id: UUID
    name: str
    description: str
    state: str
    positions: tuple[object, ...]
    children: tuple[_DepartmentTreeItem, ...]
    hierarchy_ordinal: str

    @property
    def index_label(self) -> str:
        return f"{self.name} — hierarchy item {self.hierarchy_ordinal}"

    @property
    def management_accessible_name(self) -> str:
        return f"Manage {self.name} Department, hierarchy item {self.hierarchy_ordinal}"


def _load_organization_structure_snapshot(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> StructureSnapshotRead[_OrganizationStructureSnapshot]:
    """Compose every Page 9 label and relationship in one MVCC snapshot."""

    evaluated_at = timezone_now()
    organization, series, edition = authorized_admin_edition_for_route(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        capability_code="workforce.view_structure",
    )
    edition_target = resolve_edition_target(
        organization_id=organization.id,
        edition_id=edition.id,
    )
    view_decision = decide(
        principal=actor,
        capability_code="workforce.view_structure",
        resource=edition_target,
        requested_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
        at=evaluated_at,
    )
    if not view_decision.allowed:
        raise PermissionDenied
    try:
        require_complete_projection(
            required_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
            permitted_fields=view_decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied from error
    manage_decision = decide(
        principal=actor,
        capability_code="workforce.manage_structure",
        resource=edition_target,
        at=evaluated_at,
    )
    organization_target = _required_organization_target(
        organization_id=organization.id,
    )
    can_view_organization = decide(
        principal=actor,
        capability_code="organizations.view_basic",
        resource=organization_target,
        at=evaluated_at,
    ).allowed
    can_manage_representation = decide(
        principal=actor,
        capability_code="organizations.manage_representation",
        resource=organization_target,
        at=evaluated_at,
    ).allowed
    can_create_series = decide(
        principal=actor,
        capability_code="organizations.create_series",
        resource=organization_target,
        at=evaluated_at,
    ).allowed
    can_create_edition = decide(
        principal=actor,
        capability_code="events.create",
        resource=organization_target,
        at=evaluated_at,
    ).allowed
    can_view_edition = decide(
        principal=actor,
        capability_code="events.view_basic",
        resource=edition_target,
        at=evaluated_at,
    ).allowed
    can_manage_registration = decide(
        principal=actor,
        capability_code="registration.manage_configuration",
        resource=edition_target,
        at=evaluated_at,
    ).allowed
    governance = executive_board_governance_anchor(
        organization_id=organization.id,
    )
    structure = project_edition_structure(
        organization_id=organization.id,
        edition_id=edition.id,
        at=evaluated_at,
    )
    transitional_uncontrolled_legacy = (
        structure.aggregate_version == 0 and structure.source.kind == "legacy_existing"
    )
    return StructureSnapshotRead(
        value=_OrganizationStructureSnapshot(
            organization=organization,
            series=series,
            edition=edition,
            governance=governance,
            structure=structure,
            can_manage_structure=(
                manage_decision.allowed and not transitional_uncontrolled_legacy
            ),
            can_view_organization=can_view_organization,
            can_manage_representation=can_manage_representation,
            can_create_series=can_create_series,
            can_create_edition=can_create_edition,
            can_view_edition=can_view_edition,
            can_manage_registration=can_manage_registration,
        ),
        organization_id=organization.id,
        edition_id=edition.id,
        aggregate_version=structure.aggregate_version,
    )


def _organization_structure_dependency_failure(
    request: HttpRequest,
) -> TemplateResponse:
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Organization structure unavailable",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "organization-structure",
            "baseline_page_class": "",
            "baseline_can_view_organization": False,
            "baseline_can_manage_representation": False,
            "baseline_can_create_series": False,
            "baseline_can_create_edition": False,
            "baseline_can_view_edition": False,
            "baseline_can_view_structure": False,
            "baseline_can_manage_structure": False,
            "baseline_can_manage_registration": False,
            "baseline_hide_admin_scoped_navigation": True,
            "structure_load_failed": True,
            "structure_request_invalid": False,
        }
    )
    return TemplateResponse(
        request,
        "workforce/organization_structure.html",
        context,
        status=503,
    )


def _organization_structure_bad_request(request: HttpRequest) -> TemplateResponse:
    """Return a name-free response for unsupported URL input."""

    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Invalid organization structure request",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "organization-structure",
            "baseline_page_class": "",
            "baseline_can_view_organization": False,
            "baseline_can_manage_representation": False,
            "baseline_can_create_series": False,
            "baseline_can_create_edition": False,
            "baseline_can_view_edition": False,
            "baseline_can_view_structure": False,
            "baseline_can_manage_structure": False,
            "baseline_can_manage_registration": False,
            "baseline_hide_admin_scoped_navigation": True,
            "structure_load_failed": False,
            "structure_request_invalid": True,
        }
    )
    return TemplateResponse(
        request,
        "workforce/organization_structure.html",
        context,
        status=400,
    )


def _authorize_structure_route(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    require_manage: bool,
) -> tuple[Organization, ConventionSeries, EventEdition]:
    """Authorize exact route scope before parsing an action's submitted body."""

    organization, series, edition = authorized_admin_edition_for_route(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        capability_code="workforce.view_structure",
    )
    evaluated_at = timezone_now()
    target = resolve_edition_target(
        organization_id=organization.id,
        edition_id=edition.id,
    )
    view_decision = decide(
        principal=actor,
        capability_code="workforce.view_structure",
        resource=target,
        requested_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
        at=evaluated_at,
    )
    if not view_decision.allowed:
        raise PermissionDenied
    try:
        require_complete_projection(
            required_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
            permitted_fields=view_decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied from error
    if require_manage:
        manage_decision = decide(
            principal=actor,
            capability_code="workforce.manage_structure",
            resource=target,
            at=evaluated_at,
        )
        if not manage_decision.allowed:
            raise PermissionDenied
    return organization, series, edition


def _load_structure_snapshot_without_disclosure(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> _OrganizationStructureSnapshot:
    """Load bounded choices after authorization but before parsing a POST."""

    return load_version_fenced_snapshot(
        load=lambda: _load_organization_structure_snapshot(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    )


def _load_audited_structure_page(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    route_name: str,
    require_manage: bool,
) -> _OrganizationStructurePageRead:
    """Repeat current policy and audit before releasing any structure labels."""

    snapshot = _load_structure_snapshot_without_disclosure(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    response_authorized_at = timezone_now()
    response_target = resolve_edition_target(
        organization_id=snapshot.organization.id,
        edition_id=snapshot.edition.id,
    )
    view_decision = decide(
        principal=actor,
        capability_code="workforce.view_structure",
        resource=response_target,
        requested_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
        at=response_authorized_at,
    )
    if not view_decision.allowed:
        raise PermissionDenied
    try:
        require_complete_projection(
            required_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
            permitted_fields=view_decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied from error
    manage_decision = decide(
        principal=actor,
        capability_code="workforce.manage_structure",
        resource=response_target,
        at=response_authorized_at,
    )
    if require_manage and not manage_decision.allowed:
        raise PermissionDenied
    resolved_route_name = (
        request.resolver_match.url_name
        if request.resolver_match is not None and request.resolver_match.url_name
        else route_name
    )
    http_method = request.method
    if http_method is None:
        raise RuntimeError("The structure request lost its HTTP method.")
    append_structure_read_audit(
        actor=actor,
        organization_id=snapshot.organization.id,
        edition_id=snapshot.edition.id,
        decision=view_decision,
        correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
        route_name=resolved_route_name,
        http_method=http_method,
        source_channel="web",
        occurred_at=response_authorized_at,
    )
    return _OrganizationStructurePageRead(
        snapshot=snapshot,
        view_decision=view_decision,
        manage_decision=manage_decision,
    )


def _structure_mutations_allowed(read: _OrganizationStructurePageRead) -> bool:
    snapshot = read.snapshot
    return bool(
        read.can_manage_structure
        and snapshot.structure.state == "complete"
        and snapshot.organization.lifecycle
        in {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
        and snapshot.edition.lifecycle
        in {EventEdition.Lifecycle.DRAFT, EventEdition.Lifecycle.PREPARING}
    )


def _structure_mutation_blocked_reason(
    read: _OrganizationStructurePageRead,
) -> str:
    snapshot = read.snapshot
    if not read.manage_decision.allowed:
        return (
            "You have view access, but not the separate "
            "structure-management capability."
        )
    if not snapshot.can_manage_structure:
        return (
            "This existing structure is awaiting its durable deployment control "
            "record and remains read-only."
        )
    if snapshot.structure.state != "complete":
        return "Maru cannot edit a hierarchy that is too large to show completely."
    if snapshot.organization.lifecycle not in {
        Organization.Lifecycle.DRAFT,
        Organization.Lifecycle.ACTIVE,
    }:
        return "The organization lifecycle keeps this edition's structure read-only."
    if snapshot.edition.lifecycle not in {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
    }:
        return (
            "Department changes are available only while the edition is Draft "
            "or Preparing."
        )
    return "Structure changes are not available in the current state."


def _structure_page_context(
    request: HttpRequest,
    *,
    read: _OrganizationStructurePageRead,
    page_id: str,
) -> dict[str, object]:
    snapshot = read.snapshot
    allowed = _structure_mutations_allowed(read)
    context = admin.site.each_context(request)
    context.update(
        {
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": page_id,
            "baseline_page_class": "",
            "baseline_can_view_organization": snapshot.can_view_organization,
            "baseline_can_manage_representation": snapshot.can_manage_representation,
            "baseline_can_create_series": snapshot.can_create_series,
            "baseline_can_create_edition": snapshot.can_create_edition,
            "baseline_can_view_edition": snapshot.can_view_edition,
            "baseline_can_view_structure": True,
            "baseline_can_manage_structure": read.can_manage_structure,
            "baseline_can_manage_registration": snapshot.can_manage_registration,
            "baseline_structure_navigation_current": True,
            "organization": snapshot.organization,
            "convention_series": snapshot.series,
            "edition": snapshot.edition,
            "governance": snapshot.governance,
            "structure": snapshot.structure,
            "structure_load_failed": False,
            "structure_request_invalid": False,
            "structure_access_label": _structure_access_label(read.view_decision),
            "can_manage_structure": read.can_manage_structure,
            "structure_mutations_allowed": allowed,
            "structure_mutation_blocked_reason": (
                "" if allowed else _structure_mutation_blocked_reason(read)
            ),
        }
    )
    return context


def _flatten_departments(
    departments: tuple[DepartmentNode, ...],
    *,
    depth: int = 0,
) -> tuple[tuple[DepartmentNode, int], ...]:
    flattened: list[tuple[DepartmentNode, int]] = []
    for department in departments:
        flattened.append((department, depth))
        flattened.extend(_flatten_departments(department.children, depth=depth + 1))
    return tuple(flattened)


def _department_tree_items(
    departments: tuple[DepartmentNode, ...],
    *,
    parent_ordinal: tuple[int, ...] = (),
) -> tuple[_DepartmentTreeItem, ...]:
    items: list[_DepartmentTreeItem] = []
    for index, department in enumerate(departments, start=1):
        ordinal = (*parent_ordinal, index)
        items.append(
            _DepartmentTreeItem(
                id=department.id,
                name=department.name,
                description=department.description,
                state=department.state,
                positions=tuple(department.positions),
                children=_department_tree_items(
                    department.children,
                    parent_ordinal=ordinal,
                ),
                hierarchy_ordinal=".".join(str(part) for part in ordinal),
            )
        )
    return tuple(items)


def _flatten_department_tree_items(
    departments: tuple[_DepartmentTreeItem, ...],
) -> tuple[_DepartmentTreeItem, ...]:
    flattened: list[_DepartmentTreeItem] = []
    for department in departments:
        flattened.append(department)
        flattened.extend(_flatten_department_tree_items(department.children))
    return tuple(flattened)


def _find_department(
    structure: EditionStructureProjection,
    department_id: UUID,
) -> DepartmentNode:
    department = next(
        (
            item
            for item, _depth in _flatten_departments(structure.departments)
            if item.id == department_id
        ),
        None,
    )
    if department is None or department.state != "active":
        raise Http404
    return department


def _descendant_ids(department: DepartmentNode) -> frozenset[UUID]:
    identifiers: set[UUID] = set()
    for child in department.children:
        identifiers.add(child.id)
        identifiers.update(_descendant_ids(child))
    return frozenset(identifiers)


def _parent_choices(
    structure: EditionStructureProjection,
    *,
    edited_department: DepartmentNode | None = None,
) -> DepartmentParentChoices:
    excluded = (
        frozenset({edited_department.id}) | _descendant_ids(edited_department)
        if edited_department is not None
        else frozenset()
    )
    flattened = _flatten_departments(structure.departments)
    names_by_id = {department.id: department.name for department, _depth in flattened}
    choices: list[tuple[str, str]] = []
    for option_index, (department, _depth) in enumerate(flattened, start=1):
        if department.state != "active" or department.id in excluded:
            continue
        if department.parent_id is None:
            placement = "top-level"
        else:
            parent_name = names_by_id.get(department.parent_id)
            if parent_name is None:
                raise RuntimeError("The bounded Department projection lost a parent.")
            placement = f"child of {parent_name}"
        label = f"{department.name} — {placement} — option {option_index}"
        choices.append((str(department.id), label))
    return tuple(choices)


def _add_structure_validation_errors(
    form: forms.Form,
    error: ValidationError,
) -> bool:
    safe_fields = frozenset(
        {
            "name",
            "description",
            "parent_department_id",
            "display_order",
            "expected_version",
            "confirmation_name",
            "reason",
            "retry_key",
            "template",
        }
    )
    if hasattr(error, "error_dict") and error.error_dict:
        if any(
            field_name not in safe_fields or field_name not in form.fields
            for field_name in error.error_dict
        ):
            return False
        for field_name, field_errors in error.error_dict.items():
            for field_error in field_errors:
                form.add_error(field_name, field_error)
        return True
    return False


def _log_internal_structure_validation_key(action: str) -> None:
    """Log an invariant breach without serializing the private exception detail."""

    logger.error("%s command returned an internal validation key", action)


def _structure_conflict_message(  # noqa: PLR0911
    error: StructureCommandError,
) -> str:
    if isinstance(error, StructureVersionConflictError):
        return (
            "The structure changed after this form was opened. Your entered "
            "values are still shown; reload the latest structure before trying again."
        )
    if isinstance(error, StructureRetryConflictError):
        return (
            "This browser retry identifier was already used with different "
            "values. Reload the latest form before trying again."
        )
    if isinstance(error, StructureLifecycleConflictError):
        return "The edition or organization is now read-only for structure changes."
    if isinstance(error, StructureStateConflictError):
        return "The stored structure state no longer permits this action."
    if isinstance(error, StructureDependencyConflictError):
        return (
            "This Department has retained dependencies, so Maru made no change. "
            "Resolve them through their owning workflows before trying again."
        )
    if isinstance(error, StructureLimitConflictError):
        return "The complete structure reached a safe size or depth limit."
    return "The structure action could not be completed safely."


def _command_scope(snapshot: _OrganizationStructureSnapshot) -> dict[str, UUID]:
    return {
        "organization_id": snapshot.organization.id,
        "series_id": snapshot.series.id,
        "edition_id": snapshot.edition.id,
    }


def _preflight_structure_post(
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> tuple[Account, _OrganizationStructureSnapshot]:
    actor = _active_admin_account(request)
    _authorize_structure_route(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        require_manage=True,
    )
    if request.GET:
        raise _StructurePostQueryParametersUnsupportedError
    snapshot = _load_structure_snapshot_without_disclosure(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    return actor, snapshot


def _structure_route_kwargs(
    snapshot: _OrganizationStructureSnapshot,
) -> dict[str, str]:
    return {
        "organization_slug": snapshot.organization.slug,
        "series_slug": snapshot.series.slug,
        "edition_slug": snapshot.edition.slug,
    }


def _structure_overview_location(
    snapshot: _OrganizationStructureSnapshot,
    *,
    department_id: UUID | None = None,
) -> str:
    location = reverse(
        "organization-structure",
        kwargs=_structure_route_kwargs(snapshot),
    )
    if department_id is not None:
        return f"{location}#department-{department_id}"
    return location


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_structure(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render one complete bounded edition structure in the shared shell."""

    actor = _active_admin_account(request)
    try:
        _authorize_structure_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            require_manage=False,
        )
        if request.GET:
            return _organization_structure_bad_request(request)
        read = _load_audited_structure_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            route_name="organization-structure",
            require_manage=False,
        )
    except (
        DatabaseError,
        RuntimeError,
        ValidationError,
    ):
        logger.exception("Unable to load the edition organization structure")
        return _organization_structure_dependency_failure(request)

    snapshot = read.snapshot
    organization = snapshot.organization
    series = snapshot.series
    edition = snapshot.edition
    governance = snapshot.governance
    structure = snapshot.structure
    structure_departments = _department_tree_items(structure.departments)
    view_decision = read.view_decision
    can_manage_structure = read.can_manage_structure
    context = _structure_page_context(
        request,
        read=read,
        page_id="organization-structure",
    )
    context.update(
        {
            "title": f"Organization structure — {edition.name}",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "organization-structure",
            "baseline_page_class": "",
            "baseline_can_view_organization": snapshot.can_view_organization,
            "baseline_can_manage_representation": (snapshot.can_manage_representation),
            "baseline_can_create_series": snapshot.can_create_series,
            "baseline_can_create_edition": snapshot.can_create_edition,
            "baseline_can_view_edition": snapshot.can_view_edition,
            "baseline_can_view_structure": True,
            "baseline_can_manage_structure": can_manage_structure,
            "baseline_can_manage_registration": snapshot.can_manage_registration,
            "organization": organization,
            "convention_series": series,
            "edition": edition,
            "governance": governance,
            "structure": structure,
            "structure_load_failed": False,
            "structure_access_label": _structure_access_label(view_decision),
            "can_manage_structure": can_manage_structure,
            "template_application_available": bool(
                _structure_mutations_allowed(read)
                and structure.aggregate_version == 0
                and not structure.departments
                and structure.source.kind == "empty"
            ),
            "structure_departments": structure_departments,
            "department_index": _flatten_department_tree_items(structure_departments),
        }
    )
    return TemplateResponse(
        request,
        "workforce/organization_structure.html",
        context,
    )


def _render_structure_template_application(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    form: StructureTemplateApplicationForm | None = None,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> TemplateResponse:
    read = _load_audited_structure_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        route_name="organization-structure-template-application",
        require_manage=True,
    )
    snapshot = read.snapshot
    eligible = bool(
        snapshot.structure.aggregate_version == 0
        and not snapshot.structure.departments
        and snapshot.structure.source.kind == "empty"
    )
    if form is None:
        form = StructureTemplateApplicationForm(
            edition_name=snapshot.edition.name,
            expected_version=snapshot.structure.aggregate_version,
        )
    context = _structure_page_context(
        request,
        read=read,
        page_id="organization-structure-template-application",
    )
    context.update(
        {
            "title": f"Use built-in reference — {snapshot.edition.name}",
            "form": form,
            "template_application_available": bool(
                _structure_mutations_allowed(read) and eligible
            ),
            "show_submitted_form": form.is_bound,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return TemplateResponse(
        request,
        "workforce/organization_structure_template_application.html",
        context,
        status=status,
    )


def _render_structure_department_create(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    form: DepartmentCreationForm | None = None,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> TemplateResponse:
    read = _load_audited_structure_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        route_name="organization-structure-department-create",
        require_manage=True,
    )
    snapshot = read.snapshot
    choices = _parent_choices(snapshot.structure)
    if form is None:
        form = DepartmentCreationForm(
            parent_choices=choices,
            expected_version=snapshot.structure.aggregate_version,
        )
    else:
        form.set_parent_choices(choices, retain_bound_unavailable=True)
    context = _structure_page_context(
        request,
        read=read,
        page_id="organization-structure-department-create",
    )
    context.update(
        {
            "title": f"Create Department — {snapshot.edition.name}",
            "form": form,
            "show_submitted_form": form.is_bound,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return TemplateResponse(
        request,
        "workforce/organization_structure_department_create.html",
        context,
        status=status,
    )


def _render_structure_department(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    department_id: UUID,
    update_form: DepartmentUpdateForm | None = None,
    retirement_form: DepartmentRetirementForm | None = None,
    deletion_form: DepartmentDeletionForm | None = None,
    active_action: str = "",
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> TemplateResponse:
    read = _load_audited_structure_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        route_name="organization-structure-department",
        require_manage=True,
    )
    snapshot = read.snapshot
    department = _find_department(snapshot.structure, department_id)
    index_labels_by_id = {
        item.id: item.index_label
        for item in _flatten_department_tree_items(
            _department_tree_items(snapshot.structure.departments)
        )
    }
    department_parent_label = ""
    if department.parent_id is not None:
        department_parent_label = index_labels_by_id.get(department.parent_id, "")
        if not department_parent_label:
            raise RuntimeError("The bounded Department projection lost a parent label.")
    choices = _parent_choices(
        snapshot.structure,
        edited_department=department,
    )
    if active_action == "update":
        if update_form is None:
            raise RuntimeError("An update rerender requires its bound form.")
        update_form.set_parent_choices(choices, retain_bound_unavailable=True)
    elif active_action == "retire":
        if retirement_form is None:
            raise RuntimeError("A retirement rerender requires its bound form.")
    elif active_action == "delete":
        if deletion_form is None:
            raise RuntimeError("A deletion rerender requires its bound form.")
    else:
        update_form = DepartmentUpdateForm(
            parent_choices=choices,
            expected_version=snapshot.structure.aggregate_version,
            initial={
                "name": department.name,
                "description": department.description,
                "parent_department_id": department.parent_id,
            },
        )
        retirement_form = DepartmentRetirementForm(
            expected_version=snapshot.structure.aggregate_version,
        )
        deletion_form = DepartmentDeletionForm(
            expected_version=snapshot.structure.aggregate_version,
            department_name=department.name,
        )
    context = _structure_page_context(
        request,
        read=read,
        page_id="organization-structure-department",
    )
    context.update(
        {
            "title": f"{department.name} — Organization structure",
            "department": department,
            "department_parent_label": department_parent_label,
            "update_form": update_form,
            "retirement_form": retirement_form,
            "deletion_form": deletion_form,
            "active_action": active_action,
            "action_error": action_error,
            "reload_required": reload_required,
            "show_submitted_form": bool(active_action),
        }
    )
    return TemplateResponse(
        request,
        "workforce/organization_structure_department.html",
        context,
        status=status,
    )


def _render_structure_action_failure(
    request: HttpRequest,
    *,
    renderer: str,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    status: int,
    action_error: str,
    reload_required: bool = False,
    department_id: UUID | None = None,
    form: forms.Form,
    active_action: str = "",
) -> HttpResponse:
    """Audit one name-bearing validation/conflict rerender or fail name-free."""

    try:
        if renderer == "template":
            if not isinstance(form, StructureTemplateApplicationForm):
                raise TypeError("The template failure form contract changed.")
            return _render_structure_template_application(
                request,
                actor=actor,
                organization_slug=organization_slug,
                series_slug=series_slug,
                edition_slug=edition_slug,
                form=form,
                status=status,
                action_error=action_error,
                reload_required=reload_required,
            )
        if renderer == "create":
            if not isinstance(form, DepartmentCreationForm):
                raise TypeError("The create failure form contract changed.")
            return _render_structure_department_create(
                request,
                actor=actor,
                organization_slug=organization_slug,
                series_slug=series_slug,
                edition_slug=edition_slug,
                form=form,
                status=status,
                action_error=action_error,
                reload_required=reload_required,
            )
        if department_id is None:
            raise TypeError("A Department failure rerender requires its identifier.")
        editor_forms: dict[str, object] = {
            "update_form": form if active_action == "update" else None,
            "retirement_form": form if active_action == "retire" else None,
            "deletion_form": form if active_action == "delete" else None,
        }
        return _render_structure_department(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department_id,
            active_action=active_action,
            status=status,
            action_error=action_error,
            reload_required=reload_required,
            **editor_forms,  # type: ignore[arg-type]
        )
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to render the audited structure action response")
        return _organization_structure_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_structure_template_application(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    actor = _active_admin_account(request)
    try:
        _authorize_structure_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            require_manage=True,
        )
        if request.GET:
            return _organization_structure_bad_request(request)
        return _render_structure_template_application(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to load the structure template application page")
        return _organization_structure_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_structure_department_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    actor = _active_admin_account(request)
    try:
        _authorize_structure_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            require_manage=True,
        )
        if request.GET:
            return _organization_structure_bad_request(request)
        return _render_structure_department_create(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to load the Department creation page")
        return _organization_structure_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_structure_department(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    department_id: UUID,
) -> HttpResponse:
    actor = _active_admin_account(request)
    try:
        _authorize_structure_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            require_manage=True,
        )
        if request.GET:
            return _organization_structure_bad_request(request)
        return _render_structure_department(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department_id,
        )
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to load the Department structure editor")
        return _organization_structure_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_POST
def apply_organization_structure_template(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    try:
        actor, snapshot = _preflight_structure_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to resolve the structure template command scope")
        return _organization_structure_dependency_failure(request)
    form = StructureTemplateApplicationForm(
        request.POST,
        edition_name=snapshot.edition.name,
        expected_version=snapshot.structure.aggregate_version,
    )
    if not form.is_valid():
        return _render_structure_action_failure(
            request,
            renderer="template",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=400,
            action_error="Review the highlighted values. No Departments were copied.",
        )
    try:
        result = apply_builtin_structure_template(
            actor=actor,
            organization_id=snapshot.organization.id,
            series_id=snapshot.series.id,
            edition_id=snapshot.edition.id,
            template_identifier=str(form.cleaned_data["template"]),
            expected_version=int(form.cleaned_data["expected_version"]),
            confirmation_name=str(form.cleaned_data["confirmation_name"]),
            reason=str(form.cleaned_data["reason"]),
            retry_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_structure_validation_errors(form, error):
            _log_internal_structure_validation_key("Structure template")
            return _organization_structure_dependency_failure(request)
        return _render_structure_action_failure(
            request,
            renderer="template",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=400,
            action_error="Review the highlighted values. No Departments were copied.",
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except StructureDepartmentUnavailableError as error:
        raise Http404 from error
    except (
        StructureVersionConflictError,
        StructureRetryConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _render_structure_action_failure(
            request,
            renderer="template",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=409,
            action_error=_structure_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to apply the built-in structure template")
        return _organization_structure_dependency_failure(request)
    messages.success(
        request,
        (
            "The built-in Department reference was already applied."
            if result.replayed
            else "The built-in Department reference was applied."
        ),
    )
    return redirect(_structure_overview_location(snapshot))


@never_cache
@login_required(login_url="staff-login")
@require_POST
def create_organization_structure_department(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    try:
        actor, snapshot = _preflight_structure_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to resolve the Department creation scope")
        return _organization_structure_dependency_failure(request)
    form = DepartmentCreationForm(
        request.POST,
        parent_choices=_parent_choices(snapshot.structure),
        expected_version=snapshot.structure.aggregate_version,
    )
    if not form.is_valid():
        return _render_structure_action_failure(
            request,
            renderer="create",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=400,
            action_error="Review the highlighted values. No Department was created.",
        )
    try:
        result = create_department(
            actor=actor,
            organization_id=snapshot.organization.id,
            series_id=snapshot.series.id,
            edition_id=snapshot.edition.id,
            name=str(form.cleaned_data["name"]),
            description=str(form.cleaned_data["description"]),
            parent_department_id=cast(
                UUID | None,
                form.cleaned_data["parent_department_id"],
            ),
            display_order=None,
            expected_version=int(form.cleaned_data["expected_version"]),
            reason=str(form.cleaned_data["reason"]),
            retry_key=cast(UUID, form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_structure_validation_errors(form, error):
            _log_internal_structure_validation_key("Department create")
            return _organization_structure_dependency_failure(request)
        return _render_structure_action_failure(
            request,
            renderer="create",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=400,
            action_error="Review the highlighted values. No Department was created.",
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except StructureDepartmentUnavailableError:
        return _render_structure_action_failure(
            request,
            renderer="create",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=409,
            action_error=(
                "The selected parent Department is no longer available. "
                "Reload the latest form before trying again."
            ),
            reload_required=True,
        )
    except (
        StructureVersionConflictError,
        StructureRetryConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _render_structure_action_failure(
            request,
            renderer="create",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=409,
            action_error=_structure_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to create the Department")
        return _organization_structure_dependency_failure(request)
    messages.success(
        request,
        "The Department already existed from this browser request."
        if result.replayed
        else "The Department was created.",
    )
    return redirect(
        _structure_overview_location(
            snapshot,
            department_id=result.department_id,
        )
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_organization_structure_department(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    department_id: UUID,
) -> HttpResponse:
    try:
        actor, snapshot = _preflight_structure_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        department = _find_department(snapshot.structure, department_id)
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to resolve the Department update scope")
        return _organization_structure_dependency_failure(request)
    form = DepartmentUpdateForm(
        request.POST,
        parent_choices=_parent_choices(
            snapshot.structure,
            edited_department=department,
        ),
        expected_version=snapshot.structure.aggregate_version,
    )
    if not form.is_valid():
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department_id,
            active_action="update",
            form=form,
            status=400,
            action_error="Review the highlighted values. No Department was changed.",
        )
    try:
        result = update_department(
            actor=actor,
            organization_id=snapshot.organization.id,
            series_id=snapshot.series.id,
            edition_id=snapshot.edition.id,
            department_id=department_id,
            name=str(form.cleaned_data["name"]),
            description=str(form.cleaned_data["description"]),
            parent_department_id=cast(
                UUID | None,
                form.cleaned_data["parent_department_id"],
            ),
            display_order=None,
            expected_version=int(form.cleaned_data["expected_version"]),
            reason=str(form.cleaned_data["reason"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_structure_validation_errors(form, error):
            _log_internal_structure_validation_key("Department update")
            return _organization_structure_dependency_failure(request)
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department_id,
            active_action="update",
            form=form,
            status=400,
            action_error="Review the highlighted values. No Department was changed.",
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except StructureDepartmentUnavailableError:
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department_id,
            active_action="update",
            form=form,
            status=409,
            action_error=(
                "The Department or selected parent is no longer available. "
                "Reload the latest record before trying again."
            ),
            reload_required=True,
        )
    except (
        StructureVersionConflictError,
        StructureRetryConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department_id,
            active_action="update",
            form=form,
            status=409,
            action_error=_structure_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to update the Department")
        return _organization_structure_dependency_failure(request)
    if result.changed_fields:
        messages.success(request, "The Department was updated.")
    else:
        messages.info(request, "No Department details changed.")
    return redirect(
        _structure_overview_location(
            snapshot,
            department_id=result.department_id,
        )
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def retire_organization_structure_department(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    department_id: UUID,
) -> HttpResponse:
    try:
        actor, snapshot = _preflight_structure_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        department = _find_department(snapshot.structure, department_id)
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to resolve the Department retirement scope")
        return _organization_structure_dependency_failure(request)
    form = DepartmentRetirementForm(
        request.POST,
        expected_version=snapshot.structure.aggregate_version,
    )
    if not form.is_valid():
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department.id,
            active_action="retire",
            form=form,
            status=400,
            action_error=(
                "Review the highlighted values. The Department remains active."
            ),
        )
    try:
        retire_department(
            actor=actor,
            organization_id=snapshot.organization.id,
            series_id=snapshot.series.id,
            edition_id=snapshot.edition.id,
            department_id=department.id,
            expected_version=int(form.cleaned_data["expected_version"]),
            reason=str(form.cleaned_data["reason"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_structure_validation_errors(form, error):
            _log_internal_structure_validation_key("Department retire")
            return _organization_structure_dependency_failure(request)
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department.id,
            active_action="retire",
            form=form,
            status=400,
            action_error=(
                "Review the highlighted values. The Department remains active."
            ),
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except StructureDepartmentUnavailableError as error:
        raise Http404 from error
    except (
        StructureVersionConflictError,
        StructureRetryConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department.id,
            active_action="retire",
            form=form,
            status=409,
            action_error=_structure_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to retire the Department")
        return _organization_structure_dependency_failure(request)
    messages.success(request, "The Department was retired and its history was kept.")
    return redirect(
        _structure_overview_location(
            snapshot,
            department_id=department.id,
        )
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def delete_organization_structure_department(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    department_id: UUID,
) -> HttpResponse:
    try:
        actor, snapshot = _preflight_structure_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        department = _find_department(snapshot.structure, department_id)
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to resolve the Department deletion scope")
        return _organization_structure_dependency_failure(request)
    form = DepartmentDeletionForm(
        request.POST,
        expected_version=snapshot.structure.aggregate_version,
        department_name=department.name,
    )
    if not form.is_valid():
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department.id,
            active_action="delete",
            form=form,
            status=400,
            action_error="Review the highlighted values. Nothing was deleted.",
        )
    try:
        delete_unused_department(
            actor=actor,
            organization_id=snapshot.organization.id,
            series_id=snapshot.series.id,
            edition_id=snapshot.edition.id,
            department_id=department.id,
            expected_version=int(form.cleaned_data["expected_version"]),
            confirmation_name=str(form.cleaned_data["confirmation_name"]),
            reason=str(form.cleaned_data["reason"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_structure_validation_errors(form, error):
            _log_internal_structure_validation_key("Department delete")
            return _organization_structure_dependency_failure(request)
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department.id,
            active_action="delete",
            form=form,
            status=400,
            action_error="Review the highlighted values. Nothing was deleted.",
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except StructureDepartmentUnavailableError as error:
        raise Http404 from error
    except (
        StructureVersionConflictError,
        StructureRetryConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _render_structure_action_failure(
            request,
            renderer="department",
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            department_id=department.id,
            active_action="delete",
            form=form,
            status=409,
            action_error=_structure_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to delete the Department")
        return _organization_structure_dependency_failure(request)
    messages.success(request, "The unused Department was deleted.")
    return redirect(_structure_overview_location(snapshot))


def volunteer_opportunities(
    request: HttpRequest,
    edition_id: UUID,
) -> TemplateResponse:
    edition = get_object_or_404(
        EventEdition.objects.exclude(lifecycle__in=("archived", "cancelled")),
        id=edition_id,
    )
    candidates = list(
        VolunteerOpportunity.objects.filter(
            position__edition=edition,
            status=VolunteerOpportunity.Status.PUBLISHED,
        )
        .select_related(
            "position",
            "position__department",
            "position__reports_to",
        )
        .prefetch_related("position__assignments")
        .order_by("position__department__display_order", "position__title", "id")
    )
    opportunities = [
        opportunity
        for opportunity in candidates
        if not opportunity.is_filled or opportunity.visible_when_filled
    ]
    account = _account(request)
    applied_ids = (
        set(
            VolunteerApplication.objects.filter(
                account=account,
                opportunity__in=opportunities,
            ).values_list("opportunity_id", flat=True)
        )
        if account is not None
        else set()
    )
    return TemplateResponse(
        request,
        "workforce/opportunities.html",
        {
            "edition": edition,
            "opportunities": opportunities,
            "account": account,
            "applied_ids": applied_ids,
        },
    )


@login_required(login_url="staff-login")
def apply_for_opportunity(
    request: HttpRequest,
    edition_id: UUID,
    opportunity_id: UUID,
) -> HttpResponse:
    account = _account(request)
    if account is None:
        raise Http404
    opportunity = get_object_or_404(
        VolunteerOpportunity.objects.select_related(
            "position",
            "position__edition",
            "position__department",
        ),
        id=opportunity_id,
        position__edition_id=edition_id,
        status=VolunteerOpportunity.Status.PUBLISHED,
    )
    form = VolunteerApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            submit_volunteer_application(
                actor=account,
                opportunity_id=opportunity.id,
                motivation=cast(str, form.cleaned_data["motivation"]),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except ValidationError as error:
            form.add_error(None, error.messages[0])
        else:
            return redirect("workforce-opportunities", edition_id=edition_id)
    return TemplateResponse(
        request,
        "workforce/application_form.html",
        {"opportunity": opportunity, "form": form},
    )


@login_required(login_url="staff-login")
def my_onboarding_documents(
    request: HttpRequest,
    edition_id: UUID,
) -> HttpResponse:
    account = _account(request)
    if account is None:
        raise Http404
    edition = get_object_or_404(EventEdition, id=edition_id)
    requests = list(
        OnboardingDocumentRequest.objects.filter(
            edition=edition,
            account=account,
        )
        .select_related("document_type")
        .order_by("status", "due_at", "id")
    )
    return TemplateResponse(
        request,
        "workforce/my_documents.html",
        {"edition": edition, "document_requests": requests},
    )


@login_required(login_url="staff-login")
def upload_onboarding_document_view(
    request: HttpRequest,
    edition_id: UUID,
    document_request_id: UUID,
) -> HttpResponse:
    account = _account(request)
    if account is None:
        raise Http404
    document_request = get_object_or_404(
        OnboardingDocumentRequest.objects.select_related(
            "document_type",
            "edition",
        ),
        id=document_request_id,
        edition_id=edition_id,
        account=account,
    )
    form = OnboardingDocumentUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            upload_onboarding_document(
                actor=account,
                request_id=document_request.id,
                upload=form.cleaned_data["document"],
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            )
        except ValidationError as error:
            form.add_error(None, error.messages[0])
        else:
            return redirect("workforce-my-documents", edition_id=edition_id)
    return TemplateResponse(
        request,
        "workforce/document_upload.html",
        {"document_request": document_request, "form": form},
    )


@login_required(login_url="staff-login")
def download_onboarding_document(
    request: HttpRequest,
    document_request_id: UUID,
) -> FileResponse:
    actor = _account(request)
    if actor is None:
        raise Http404
    document_request = (
        OnboardingDocumentRequest.objects.filter(id=document_request_id)
        .select_related("account", "document_type")
        .first()
    )
    if document_request is None or not document_request.document:
        raise Http404
    owner = actor.id == document_request.account_id
    capability_code = "workforce.view_self" if owner else "workforce.manage_documents"
    decision = decide(
        principal=actor,
        capability_code=capability_code,
        resource=resolve_owned_target(resource=document_request),
    )
    if not decision.allowed:
        raise Http404
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=document_request.organization_id,
            event_edition_id=document_request.edition_id,
            capability_code=capability_code,
            operation="workforce.document.download",
            target_type="workforce.onboarding_document_request",
            target_id=document_request.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code="self_relationship" if owner else decision.reason_code,
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
            obligations=tuple(sorted(decision.obligations)),
            changed_fields=(),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-restricted",
        )
    )
    response = FileResponse(
        document_request.document.open("rb"),
        content_type=document_request.content_type or "application/pdf",
        as_attachment=True,
        filename=document_request.original_filename or "signed-document.pdf",
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
