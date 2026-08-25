"""Reference volunteer opportunity and private document views."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode
from uuid import UUID

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, models
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
    resolve_self_target,
)
from maru.authorization.provenance import role_bundle_provenance_is_historical
from maru.events.admin_context import authorized_admin_edition_for_route
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.identity.queries import account_display_labels
from maru.identity.services import require_recent_step_up
from maru.organizations.models import ConventionSeries, Organization
from maru.organizations.queries import (
    ExecutiveBoardAnchor,
    executive_board_governance_anchor,
)
from maru.workforce.assignment_commands import (
    AssignmentAuthorizationDeniedError,
    AssignmentCandidateUnavailableError,
    AssignmentCommandError,
    AssignmentHeadcountConflictError,
    AssignmentLifecycleConflictError,
    AssignmentReadinessConflictError,
    AssignmentRetryConflictError,
    AssignmentUnavailableError,
    AssignmentVersionConflictError,
    approve_position_assignment,
    end_position_assignment,
    propose_position_assignment,
    reject_position_assignment,
)
from maru.workforce.assignment_queries import (
    AssignmentReadLimitExceededError,
    assignment_history_items,
    assignment_overview_items,
    assignment_readiness,
    known_assignment_candidates,
    my_assignment_items,
)
from maru.workforce.availability_audit import append_availability_read_audit
from maru.workforce.availability_commands import (
    AvailabilityAuthorizationDeniedError,
    AvailabilityCommandError,
    AvailabilityLifecycleConflictError,
    AvailabilityRelationshipRequiredError,
    AvailabilityRetryConflictError,
    AvailabilityStateConflictError,
    AvailabilityVersionConflictError,
    authorize_person_availability_command,
    save_person_availability,
    withdraw_person_availability,
)
from maru.workforce.availability_queries import (
    AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
    AvailabilityProjectionIntegrityError,
    AvailabilityReadLimitExceededError,
    OrganizerAvailabilityOverview,
    PersonAvailabilityProjection,
    load_organizer_availability_overview,
    load_person_availability,
    my_availability_scope_items,
    person_can_edit_availability,
    person_has_availability_relationship,
)
from maru.workforce.forms import (
    AssignmentDecisionForm,
    AvailabilityCommandForm,
    AvailabilityWindowFormSet,
    AvailabilityWithdrawForm,
    BaseAvailabilityWindowFormSet,
    DepartmentCreationForm,
    DepartmentDeletionForm,
    DepartmentParentChoices,
    DepartmentRetirementForm,
    DepartmentUpdateForm,
    OnboardingDocumentUploadForm,
    PositionAssignmentProposalForm,
    PositionClosureForm,
    PositionCreationForm,
    PositionOpportunityForm,
    PositionUpdateForm,
    StructureTemplateApplicationForm,
    VolunteerApplicationForm,
)
from maru.workforce.models import (
    EditionStructureCommandReceipt,
    OnboardingDocumentRequest,
    PersonAvailabilityPlan,
    Position,
    PositionAssignment,
    PositionTemplate,
    ShiftCommitment,
    VolunteerApplication,
    VolunteerOpportunity,
)
from maru.workforce.queries import (
    WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
    DepartmentNode,
    EditionStructureProjection,
    PositionNode,
    project_edition_structure,
)
from maru.workforce.services import (
    submit_volunteer_application,
    upload_onboarding_document,
)
from maru.workforce.shift_queries import (
    ShiftReadLimitExceededError,
    my_shift_scope_items,
)
from maru.workforce.structure_audit import append_structure_read_audit
from maru.workforce.structure_commands import (
    StructureAuthorizationDeniedError,
    StructureCommandError,
    StructureDepartmentUnavailableError,
    StructureDependencyConflictError,
    StructureLifecycleConflictError,
    StructureLimitConflictError,
    StructurePositionUnavailableError,
    StructureRetryConflictError,
    StructureStateConflictError,
    StructureVersionConflictError,
    apply_builtin_structure_template,
    close_position,
    create_department,
    create_position,
    delete_unused_department,
    retire_department,
    update_department,
    update_position,
    update_position_opportunity,
)
from maru.workforce.structure_snapshot import (
    StructureSnapshotRead,
    load_version_fenced_snapshot,
    repeatable_read_only_snapshot,
)

if TYPE_CHECKING:
    from datetime import datetime

    from django import forms

logger = logging.getLogger(__name__)

MAX_POSITION_TEMPLATE_CHOICES = 128
MAX_PERSONAL_ASSIGNMENT_SCOPES = 1_024
_AVAILABILITY_WINDOW_FIELD = re.compile(
    r"windows-(?:0|[1-9][0-9]*)-(?:starts_at|ends_at|preference|DELETE)\Z"
)
_AVAILABILITY_MANAGEMENT_FIELDS = frozenset(
    {
        "windows-TOTAL_FORMS",
        "windows-INITIAL_FORMS",
        "windows-MIN_NUM_FORMS",
        "windows-MAX_NUM_FORMS",
    }
)


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
    """Compose every Organization structure label in one MVCC snapshot.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.

    Returns
    -------
    StructureSnapshotRead[_OrganizationStructureSnapshot]
        The StructureSnapshotRead[_OrganizationStructureSnapshot] produced by
        load organization structure snapshot.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
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
    """Return a name-free response for unsupported URL input.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    TemplateResponse
        The HTTP response for the requested operation.
    """
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
    """Authorize exact route scope before parsing an action's submitted body.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.
    require_manage : bool
        Whether to require manage.

    Returns
    -------
    tuple[Organization, ConventionSeries, EventEdition]
        The matching authorize structure route records in deterministic order.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
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
    """Load bounded choices after authorization but before parsing a POST.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.

    Returns
    -------
    _OrganizationStructureSnapshot
        The _OrganizationStructureSnapshot produced by load structure snapshot
        without disclosure.
    """
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
    """Repeat current policy and audit before releasing any structure labels.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.
    route_name : str
        The human-readable route name shown to authorized readers.
    require_manage : bool
        Whether to require manage.

    Returns
    -------
    _OrganizationStructurePageRead
        The _OrganizationStructurePageRead produced by load audited structure
        page.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    """
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


@dataclass(frozen=True, slots=True)
class _PositionOverviewItem:
    position: PositionNode
    department_name: str
    opportunity_status: str
    accepts_applications: bool


@dataclass(frozen=True, slots=True)
class _StructureHistoryItem:
    action_label: str
    target_label: str
    reason: str
    actor_label: str
    occurred_at: object
    resulting_version: int


def _flatten_positions(
    structure: EditionStructureProjection,
) -> tuple[tuple[PositionNode, DepartmentNode], ...]:
    return tuple(
        (position, department)
        for department, _depth in _flatten_departments(structure.departments)
        for position in department.positions
    )


def _find_position(
    structure: EditionStructureProjection,
    position_id: UUID,
) -> tuple[PositionNode, DepartmentNode]:
    match = next(
        (
            (position, department)
            for position, department in _flatten_positions(structure)
            if position.id == position_id
        ),
        None,
    )
    if match is None:
        raise Http404
    return match


def _position_reporting_choices(
    structure: EditionStructureProjection,
    *,
    edited_position_id: UUID | None = None,
) -> tuple[tuple[str, str], ...]:
    flattened = _flatten_positions(structure)
    parent_by_id = {position.id: position.reports_to_id for position, _ in flattened}
    excluded: set[UUID] = set()
    if edited_position_id is not None:
        excluded.add(edited_position_id)
        for candidate_id, reporting_parent_id in parent_by_id.items():
            cursor = reporting_parent_id
            seen: set[UUID] = set()
            while cursor is not None and cursor not in seen:
                if cursor == edited_position_id:
                    excluded.add(candidate_id)
                    break
                seen.add(cursor)
                cursor = parent_by_id.get(cursor)
    choices = []
    for position, department in flattened:
        if position.id in excluded or position.status == Position.Status.CLOSED:
            continue
        choices.append(
            (
                str(position.id),
                f"{position.title} — {department.name}",
            )
        )
    return tuple(choices)


def _position_department_choices(
    structure: EditionStructureProjection,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(department.id), department.name)
        for department, _depth in _flatten_departments(structure.departments)
        if department.state == "active"
    )


def _position_template_choices(
    *,
    organization_id: UUID,
) -> tuple[tuple[str, str], ...]:
    templates = tuple(
        PositionTemplate.objects.select_related("role_bundle")
        .filter(
            organization_id=organization_id,
            status=PositionTemplate.Status.PUBLISHED,
            role_bundle__authority_issuance__isnull=False,
        )
        .order_by("name", "version", "id")[: MAX_POSITION_TEMPLATE_CHOICES + 1]
    )
    if len(templates) > MAX_POSITION_TEMPLATE_CHOICES:
        raise RuntimeError("The Position template selector exceeded its safe bound.")
    evaluated_at = timezone_now()
    return tuple(
        (
            str(template.id),
            (
                f"{template.name} v{template.version} — "
                f"{template.role_bundle.name}; default headcount "
                f"{template.default_headcount}"
            ),
        )
        for template in templates
        if role_bundle_provenance_is_historical(
            bundle=template.role_bundle,
            evaluated_at=evaluated_at,
        )
    )


def _position_record(
    *,
    organization_id: UUID,
    edition_id: UUID,
    position_id: UUID,
) -> Position:
    position = (
        Position.objects.select_related(
            "template",
            "role_bundle",
            "department",
            "reports_to",
            "closed_by",
        )
        .filter(
            id=position_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .order_by()
        .first()
    )
    if position is None:
        raise Http404
    return position


def _position_opportunity(position: Position) -> VolunteerOpportunity | None:
    return (
        VolunteerOpportunity.objects.filter(position_id=position.id).order_by().first()
    )


def _structure_history_items(
    *,
    organization_id: UUID,
    edition_id: UUID,
    position_id: UUID | None = None,
    limit: int = 24,
) -> tuple[_StructureHistoryItem, ...]:
    query = EditionStructureCommandReceipt.objects.select_related(
        "actor",
        "affected_position",
    ).filter(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if position_id is not None:
        query = query.filter(affected_position_id=position_id)
    receipts = tuple(query.order_by("-resulting_version", "-id")[:limit])
    items = []
    for receipt in receipts:
        if receipt.affected_position is not None:
            target_label = receipt.affected_position.title
        elif receipt.deleted_name_snapshot:
            target_label = receipt.deleted_name_snapshot
        elif len(receipt.affected_department_ids) == 1:
            target_label = "Department structure"
        else:
            target_label = "Edition structure"
        items.append(
            _StructureHistoryItem(
                action_label=receipt.get_action_display(),
                target_label=target_label,
                reason=receipt.reason,
                actor_label=receipt.actor.display_name or "Maru account",
                occurred_at=receipt.created_at,
                resulting_version=receipt.resulting_version,
            )
        )
    return tuple(items)


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
    """Log an invariant breach without serializing the private exception detail.

    Parameters
    ----------
    action : str
        The stable action code describing the requested transition.
    """
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
    """Render one complete bounded edition structure in the shared shell.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
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
            "structure_history": (
                _structure_history_items(
                    organization_id=organization.id,
                    edition_id=edition.id,
                )
                if can_manage_structure
                else ()
            ),
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
    """Audit one name-bearing validation/conflict rerender or fail name-free.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    renderer : str
        The renderer resolved from the authorized request.
    actor : Account
        The authenticated account authorizing the operation.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.
    status : int
        The closed status value to evaluate or expose.
    action_error : str
        The action error resolved from the authorized request.
    reload_required : bool, default=False
        The reload required resolved from the authorized request.
    department_id : UUID | None, default=None
        The department identifier within the requested scope.
    form : forms.Form
        The form resolved from the authorized request.
    active_action : str, default=''
        The active action resolved from the authorized request.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    TypeError
        If the caller supplies an object of an unsupported type.
    """
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
    """Render organization structure template application.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
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
    """Render organization structure department create.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
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
    """Render organization structure department.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    department_id : UUID
        The identifier of the department.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
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
    """Apply organization structure template.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
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
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
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
    """Create organization structure department.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
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
                "UUID | None",
                form.cleaned_data["parent_department_id"],
            ),
            display_order=None,
            expected_version=int(form.cleaned_data["expected_version"]),
            reason=str(form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
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
    """Update organization structure department.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    department_id : UUID
        The identifier of the department.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
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
                "UUID | None",
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
    """Retire organization structure department.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    department_id : UUID
        The identifier of the department.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
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
    """Delete organization structure department.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    department_id : UUID
        The identifier of the department.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
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


def _position_management_location(
    snapshot: _OrganizationStructureSnapshot,
    *,
    position_id: UUID | None = None,
) -> str:
    route_name = (
        "organization-structure-position"
        if position_id is not None
        else "organization-structure-positions"
    )
    kwargs: dict[str, object] = dict(_structure_route_kwargs(snapshot))
    if position_id is not None:
        kwargs["position_id"] = position_id
    return reverse(route_name, kwargs=kwargs)


def _position_context(
    request: HttpRequest,
    *,
    read: _OrganizationStructurePageRead,
    page_id: str,
) -> dict[str, object]:
    context = _structure_page_context(request, read=read, page_id=page_id)
    actor = _account(request)
    target = resolve_edition_target(
        organization_id=read.snapshot.organization.id,
        edition_id=read.snapshot.edition.id,
    )
    can_manage_assignments = bool(
        actor is not None
        and decide(
            principal=actor,
            capability_code="workforce.manage_assignments",
            resource=target,
        ).allowed
    )
    can_issue_assignment_authority = bool(
        can_manage_assignments
        and actor is not None
        and decide(
            principal=actor,
            capability_code="authorization.manage_roles",
            resource=target,
        ).allowed
    )
    availability_decision = (
        decide(
            principal=actor,
            capability_code="workforce.view_availability",
            resource=target,
            requested_fields=AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
        )
        if actor is not None
        else None
    )
    can_view_availability = bool(
        availability_decision is not None
        and availability_decision.allowed
        and availability_decision.fields == AVAILABILITY_ORGANIZER_REQUIRED_FIELDS
    )
    can_view_shifts = bool(
        actor is not None
        and decide(
            principal=actor,
            capability_code="workforce.view_shifts",
            resource=target,
        ).allowed
    )
    context.update(
        {
            "baseline_structure_navigation_current": True,
            "position_mutations_allowed": _structure_mutations_allowed(read),
            "can_manage_assignments": can_manage_assignments,
            "can_issue_assignment_authority": can_issue_assignment_authority,
            "can_view_availability": can_view_availability,
            "can_view_shifts": can_view_shifts,
        }
    )
    return context


def _position_overview_items(
    read: _OrganizationStructurePageRead,
) -> tuple[_PositionOverviewItem, ...]:
    flattened = _flatten_positions(read.snapshot.structure)
    position_ids = tuple(position.id for position, _department in flattened)
    opportunities = {
        opportunity.position_id: opportunity
        for opportunity in VolunteerOpportunity.objects.filter(
            position_id__in=position_ids,
            position__organization_id=read.snapshot.organization.id,
            position__edition_id=read.snapshot.edition.id,
        ).order_by("position_id")
    }
    evaluated_at = timezone_now()
    items = []
    for position, department in flattened:
        opportunity = opportunities.get(position.id)
        accepts_applications = bool(
            opportunity is not None
            and opportunity.status == VolunteerOpportunity.Status.PUBLISHED
            and len(position.holders) < position.headcount
            and (
                opportunity.applications_open_at is None
                or opportunity.applications_open_at <= evaluated_at
            )
            and (
                opportunity.applications_close_at is None
                or opportunity.applications_close_at > evaluated_at
            )
        )
        items.append(
            _PositionOverviewItem(
                position=position,
                department_name=department.name,
                opportunity_status=(
                    opportunity.get_status_display()
                    if opportunity is not None
                    else "Draft setup required"
                ),
                accepts_applications=accepts_applications,
            )
        )
    return tuple(items)


def _render_position_management(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> TemplateResponse:
    read = _load_audited_structure_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        route_name="organization-structure-positions",
        require_manage=True,
    )
    snapshot = read.snapshot
    template_choices = _position_template_choices(
        organization_id=snapshot.organization.id,
    )
    department_choices = _position_department_choices(snapshot.structure)
    context = _position_context(
        request,
        read=read,
        page_id="organization-structure-positions",
    )
    context.update(
        {
            "title": f"Position management — {snapshot.edition.name}",
            "positions": _position_overview_items(read),
            "position_creation_available": bool(
                _structure_mutations_allowed(read)
                and template_choices
                and department_choices
            ),
            "has_position_templates": bool(template_choices),
            "has_position_departments": bool(department_choices),
            "position_history": _structure_history_items(
                organization_id=snapshot.organization.id,
                edition_id=snapshot.edition.id,
            ),
        }
    )
    return TemplateResponse(
        request,
        "workforce/position_management.html",
        context,
    )


def _render_position_create(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    form: PositionCreationForm | None = None,
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
        route_name="organization-structure-position-create",
        require_manage=True,
    )
    snapshot = read.snapshot
    template_choices = _position_template_choices(
        organization_id=snapshot.organization.id,
    )
    department_choices = _position_department_choices(snapshot.structure)
    reporting_choices = _position_reporting_choices(snapshot.structure)
    if form is None:
        form = PositionCreationForm(
            template_choices=template_choices,
            department_choices=department_choices,
            reporting_choices=reporting_choices,
            expected_version=snapshot.structure.aggregate_version,
        )
    context = _position_context(
        request,
        read=read,
        page_id="organization-structure-position-create",
    )
    context.update(
        {
            "title": f"Create Position — {snapshot.edition.name}",
            "form": form,
            "action_error": action_error,
            "reload_required": reload_required,
            "show_submitted_form": form.is_bound,
            "position_creation_available": bool(
                _structure_mutations_allowed(read)
                and template_choices
                and department_choices
            ),
            "has_position_templates": bool(template_choices),
            "has_position_departments": bool(department_choices),
        }
    )
    return TemplateResponse(
        request,
        "workforce/position_create.html",
        context,
        status=status,
    )


def _render_position_detail(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
    update_form: PositionUpdateForm | None = None,
    opportunity_form: PositionOpportunityForm | None = None,
    closure_form: PositionClosureForm | None = None,
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
        route_name="organization-structure-position",
        require_manage=True,
    )
    snapshot = read.snapshot
    projected_position, projected_department = _find_position(
        snapshot.structure,
        position_id,
    )
    position = _position_record(
        organization_id=snapshot.organization.id,
        edition_id=snapshot.edition.id,
        position_id=position_id,
    )
    opportunity = _position_opportunity(position)
    reporting_choices = _position_reporting_choices(
        snapshot.structure,
        edited_position_id=position.id,
    )
    if position.status != Position.Status.CLOSED:
        if update_form is None:
            update_form = PositionUpdateForm(
                reporting_choices=reporting_choices,
                expected_version=snapshot.structure.aggregate_version,
                initial={
                    "title": position.title,
                    "description": position.description,
                    "headcount": position.headcount,
                    "reports_to_id": position.reports_to_id,
                },
            )
        if opportunity_form is None:
            opportunity_form = PositionOpportunityForm(
                edition_time_zone=snapshot.edition.time_zone,
                expected_version=snapshot.structure.aggregate_version,
                initial={
                    "status": (
                        opportunity.status
                        if opportunity is not None
                        else VolunteerOpportunity.Status.DRAFT
                    ),
                    "headline": (
                        opportunity.headline
                        if opportunity is not None
                        else position.title
                    ),
                    "description": (
                        opportunity.description
                        if opportunity is not None
                        else position.description
                    ),
                    "applications_open_at": (
                        opportunity.applications_open_at
                        if opportunity is not None
                        else None
                    ),
                    "applications_close_at": (
                        opportunity.applications_close_at
                        if opportunity is not None
                        else None
                    ),
                    "visible_when_filled": (
                        opportunity.visible_when_filled
                        if opportunity is not None
                        else True
                    ),
                },
            )
        if closure_form is None:
            closure_form = PositionClosureForm(
                expected_version=snapshot.structure.aggregate_version,
                position_title=position.title,
            )
    context = _position_context(
        request,
        read=read,
        page_id="organization-structure-position",
    )
    context.update(
        {
            "title": f"{position.title} — Position management",
            "position": position,
            "projected_position": projected_position,
            "position_department": projected_department,
            "opportunity": opportunity,
            "update_form": update_form,
            "opportunity_form": opportunity_form,
            "closure_form": closure_form,
            "active_action": active_action,
            "action_error": action_error,
            "reload_required": reload_required,
            "show_submitted_form": bool(active_action),
            "open_assignment_count": PositionAssignment.objects.filter(
                position_id=position.id,
                organization_id=snapshot.organization.id,
                edition_id=snapshot.edition.id,
                status__in=(
                    PositionAssignment.Status.PROPOSED,
                    PositionAssignment.Status.ACTIVE,
                ),
            ).count(),
            "application_count": (
                opportunity.applications.count() if opportunity is not None else 0
            ),
            "position_history": _structure_history_items(
                organization_id=snapshot.organization.id,
                edition_id=snapshot.edition.id,
                position_id=position.id,
            ),
        }
    )
    return TemplateResponse(
        request,
        "workforce/position_detail.html",
        context,
        status=status,
    )


def _add_position_validation_errors(
    form: forms.Form,
    error: ValidationError,
) -> bool:
    safe_fields = frozenset(
        {
            "template_id",
            "department_id",
            "reports_to_id",
            "position_id",
            "title",
            "description",
            "headcount",
            "status",
            "headline",
            "applications_open_at",
            "applications_close_at",
            "visible_when_filled",
            "expected_version",
            "confirmation_name",
            "reason",
            "retry_key",
        }
    )
    if not hasattr(error, "error_dict") or not error.error_dict:
        return False
    if any(
        field_name not in safe_fields or field_name not in form.fields
        for field_name in error.error_dict
    ):
        return False
    for field_name, field_errors in error.error_dict.items():
        for field_error in field_errors:
            form.add_error(field_name, field_error)
    return True


def _position_conflict_message(error: StructureCommandError) -> str:
    if isinstance(error, StructureVersionConflictError):
        return (
            "The Workforce structure changed after this form was opened. "
            "Reload the latest Position before trying again."
        )
    if isinstance(error, StructureRetryConflictError):
        return (
            "This browser retry identifier was already used with different "
            "Position details. Reload before creating another Position."
        )
    if isinstance(error, StructureLifecycleConflictError):
        return "The edition or organization is now read-only for Position changes."
    if isinstance(error, StructureDependencyConflictError):
        return (
            "Current assignments, direct reports, or scoped authority still "
            "depend on this Position. Resolve them in their owning workflows first."
        )
    if isinstance(error, StructureLimitConflictError):
        return "The complete Workforce structure reached a safe size or depth limit."
    return "The Position action no longer matches the current Workforce state."


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_structure_positions(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render the purpose-built Position management overview.

    Parameters
    ----------
    request : HttpRequest
        Authenticated browser request with no query parameters.
    organization_slug : str
        Untrusted organization route locator.
    series_slug : str
        Untrusted convention-series route locator.
    edition_slug : str
        Untrusted event-edition route locator.

    Returns
    -------
    HttpResponse
        Private authorized overview or a minimized safe failure response.
    """
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
        return _render_position_management(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to load Position management")
        return _organization_structure_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_structure_position_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render one governed Position creation form.

    Parameters
    ----------
    request : HttpRequest
        Authenticated browser request with no query parameters.
    organization_slug : str
        Untrusted organization route locator.
    series_slug : str
        Untrusted convention-series route locator.
    edition_slug : str
        Untrusted event-edition route locator.

    Returns
    -------
    HttpResponse
        Private authorized creation form or a minimized safe failure response.
    """
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
        return _render_position_create(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to load Position creation")
        return _organization_structure_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_structure_position(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
) -> HttpResponse:
    """Render one governed Position, its opportunity, and retained history.

    Parameters
    ----------
    request : HttpRequest
        Authenticated browser request with no query parameters.
    organization_slug : str
        Untrusted organization route locator.
    series_slug : str
        Untrusted convention-series route locator.
    edition_slug : str
        Untrusted event-edition route locator.
    position_id : UUID
        Position identifier resolved only inside the authorized exact edition.

    Returns
    -------
    HttpResponse
        Private authorized detail page or a minimized safe failure response.
    """
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
        return _render_position_detail(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
        )
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to load Position detail")
        return _organization_structure_dependency_failure(request)


def _position_post_snapshot(
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> tuple[Account, _OrganizationStructureSnapshot]:
    return _preflight_structure_post(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def create_organization_structure_position(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Create a Position through the shared structure command.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected creation request.
    organization_slug : str
        Untrusted organization route locator.
    series_slug : str
        Untrusted convention-series route locator.
    edition_slug : str
        Untrusted event-edition route locator.

    Returns
    -------
    HttpResponse
        Redirect on success or private validation, conflict, or dependency state.

    Raises
    ------
    PermissionDenied
        If fresh command authorization no longer permits the mutation.
    """
    try:
        actor, snapshot = _position_post_snapshot(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to prepare Position creation")
        return _organization_structure_dependency_failure(request)
    form = PositionCreationForm(
        request.POST,
        template_choices=_position_template_choices(
            organization_id=snapshot.organization.id
        ),
        department_choices=_position_department_choices(snapshot.structure),
        reporting_choices=_position_reporting_choices(snapshot.structure),
        expected_version=snapshot.structure.aggregate_version,
    )
    if not form.is_valid():
        return _render_position_create(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=400,
            action_error="Review the highlighted values. Nothing was created.",
        )
    try:
        result = create_position(
            actor=actor,
            organization_id=snapshot.organization.id,
            series_id=snapshot.series.id,
            edition_id=snapshot.edition.id,
            template_id=cast("UUID", form.cleaned_data["template_id"]),
            department_id=cast("UUID", form.cleaned_data["department_id"]),
            reports_to_id=cast("UUID | None", form.cleaned_data["reports_to_id"]),
            title=cast("str", form.cleaned_data["title"]),
            description=cast("str", form.cleaned_data["description"]),
            headcount=cast("int", form.cleaned_data["headcount"]),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_position_validation_errors(form, error):
            logger.exception("Position creation returned an internal validation key")
            return _organization_structure_dependency_failure(request)
        return _render_position_create(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=400,
            action_error="Review the highlighted values. Nothing was created.",
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        StructureVersionConflictError,
        StructureRetryConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _render_position_create(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            form=form,
            status=409,
            action_error=_position_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to create Position")
        return _organization_structure_dependency_failure(request)
    messages.success(
        request,
        "Position created with a private draft volunteer opportunity.",
    )
    return redirect(
        _position_management_location(snapshot, position_id=result.position_id)
    )


def _bound_position_detail_failure(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
    form: PositionUpdateForm | PositionOpportunityForm | PositionClosureForm,
    active_action: str,
    status: int,
    action_error: str,
    reload_required: bool = False,
) -> TemplateResponse:
    kwargs: dict[str, object] = {
        "update_form": None,
        "opportunity_form": None,
        "closure_form": None,
    }
    kwargs[f"{active_action}_form"] = form
    return _render_position_detail(
        request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        position_id=position_id,
        active_action=active_action,
        status=status,
        action_error=action_error,
        reload_required=reload_required,
        **kwargs,  # type: ignore[arg-type]
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_organization_structure_position(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
) -> HttpResponse:
    """Update one Position through the shared structure command.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected complete replacement request.
    organization_slug : str
        Untrusted organization route locator.
    series_slug : str
        Untrusted convention-series route locator.
    edition_slug : str
        Untrusted event-edition route locator.
    position_id : UUID
        Position identifier resolved only inside the authorized exact edition.

    Returns
    -------
    HttpResponse
        Redirect on success or private validation, conflict, or dependency state.

    Raises
    ------
    Http404
        If the authorized exact edition has no matching Position.
    PermissionDenied
        If fresh command authorization no longer permits the mutation.
    """
    try:
        actor, snapshot = _position_post_snapshot(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to prepare Position update")
        return _organization_structure_dependency_failure(request)
    form = PositionUpdateForm(
        request.POST,
        reporting_choices=_position_reporting_choices(
            snapshot.structure,
            edited_position_id=position_id,
        ),
        expected_version=snapshot.structure.aggregate_version,
    )
    if not form.is_valid():
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="update",
            status=400,
            action_error="Review the highlighted values. Nothing was changed.",
        )
    try:
        update_position(
            actor=actor,
            **_command_scope(snapshot),
            position_id=position_id,
            reports_to_id=cast("UUID | None", form.cleaned_data["reports_to_id"]),
            title=cast("str", form.cleaned_data["title"]),
            description=cast("str", form.cleaned_data["description"]),
            headcount=cast("int", form.cleaned_data["headcount"]),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except StructurePositionUnavailableError as error:
        raise Http404 from error
    except ValidationError as error:
        if not _add_position_validation_errors(form, error):
            return _organization_structure_dependency_failure(request)
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="update",
            status=400,
            action_error="Review the highlighted values. Nothing was changed.",
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        StructureVersionConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="update",
            status=409,
            action_error=_position_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to update Position")
        return _organization_structure_dependency_failure(request)
    messages.success(request, "Position details saved.")
    return redirect(_position_management_location(snapshot, position_id=position_id))


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_organization_structure_position_opportunity(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
) -> HttpResponse:
    """Update the volunteer opportunity paired with one Position.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected complete replacement request.
    organization_slug : str
        Untrusted organization route locator.
    series_slug : str
        Untrusted convention-series route locator.
    edition_slug : str
        Untrusted event-edition route locator.
    position_id : UUID
        Position identifier resolved only inside the authorized exact edition.

    Returns
    -------
    HttpResponse
        Redirect on success or private validation, conflict, or dependency state.

    Raises
    ------
    Http404
        If the authorized exact edition has no matching Position.
    PermissionDenied
        If fresh command authorization no longer permits the mutation.
    """
    try:
        actor, snapshot = _position_post_snapshot(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to prepare opportunity update")
        return _organization_structure_dependency_failure(request)
    form = PositionOpportunityForm(
        request.POST,
        edition_time_zone=snapshot.edition.time_zone,
        expected_version=snapshot.structure.aggregate_version,
    )
    if not form.is_valid():
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="opportunity",
            status=400,
            action_error="Review the highlighted values. Publication was not changed.",
        )
    try:
        update_position_opportunity(
            actor=actor,
            **_command_scope(snapshot),
            position_id=position_id,
            status=cast("str", form.cleaned_data["status"]),
            headline=cast("str", form.cleaned_data["headline"]),
            description=cast("str", form.cleaned_data["description"]),
            applications_open_at=form.cleaned_data["applications_open_at"],
            applications_close_at=form.cleaned_data["applications_close_at"],
            visible_when_filled=cast("bool", form.cleaned_data["visible_when_filled"]),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except StructurePositionUnavailableError as error:
        raise Http404 from error
    except ValidationError as error:
        if not _add_position_validation_errors(form, error):
            return _organization_structure_dependency_failure(request)
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="opportunity",
            status=400,
            action_error="Review the highlighted values. Publication was not changed.",
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        StructureVersionConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="opportunity",
            status=409,
            action_error=_position_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to update Position opportunity")
        return _organization_structure_dependency_failure(request)
    messages.success(request, "Volunteer opportunity settings saved.")
    return redirect(_position_management_location(snapshot, position_id=position_id))


@never_cache
@login_required(login_url="staff-login")
@require_POST
def close_organization_structure_position(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
) -> HttpResponse:
    """Close one Position through the dependency-safe shared command.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected closure request.
    organization_slug : str
        Untrusted organization route locator.
    series_slug : str
        Untrusted convention-series route locator.
    edition_slug : str
        Untrusted event-edition route locator.
    position_id : UUID
        Position identifier resolved only inside the authorized exact edition.

    Returns
    -------
    HttpResponse
        Redirect on success or private validation, conflict, or dependency state.

    Raises
    ------
    Http404
        If the authorized exact edition has no matching Position.
    PermissionDenied
        If fresh command authorization no longer permits the mutation.
    """
    try:
        actor, snapshot = _position_post_snapshot(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        position, _department = _find_position(snapshot.structure, position_id)
    except _StructurePostQueryParametersUnsupportedError:
        return _organization_structure_bad_request(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to prepare Position closure")
        return _organization_structure_dependency_failure(request)
    form = PositionClosureForm(
        request.POST,
        expected_version=snapshot.structure.aggregate_version,
        position_title=position.title,
    )
    if not form.is_valid():
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="closure",
            status=400,
            action_error="Review the highlighted values. The Position remains open.",
        )
    try:
        close_position(
            actor=actor,
            **_command_scope(snapshot),
            position_id=position_id,
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            confirmation_name=cast("str", form.cleaned_data["confirmation_name"]),
            reason=cast("str", form.cleaned_data["reason"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except StructurePositionUnavailableError as error:
        raise Http404 from error
    except ValidationError as error:
        if not _add_position_validation_errors(form, error):
            return _organization_structure_dependency_failure(request)
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="closure",
            status=400,
            action_error="Review the highlighted values. The Position remains open.",
        )
    except StructureAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        StructureVersionConflictError,
        StructureLifecycleConflictError,
        StructureStateConflictError,
        StructureDependencyConflictError,
        StructureLimitConflictError,
    ) as error:
        return _bound_position_detail_failure(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            active_action="closure",
            status=409,
            action_error=_position_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to close Position")
        return _organization_structure_dependency_failure(request)
    messages.success(request, "Position closed with its history retained.")
    return redirect(_position_management_location(snapshot, position_id=position_id))


@dataclass(frozen=True, slots=True)
class _AssignmentPageRead:
    """Authorized structure context plus assignment-control decisions."""

    structure_read: _OrganizationStructurePageRead
    manage_decision: PolicyDecision
    role_decision: PolicyDecision
    revoke_decision: PolicyDecision

    @property
    def snapshot(self) -> _OrganizationStructureSnapshot:
        """Return the shared exact-edition snapshot."""
        return self.structure_read.snapshot

    @property
    def can_issue_authority(self) -> bool:
        """Return whether the actor can propose or decide authority issuance."""
        return self.role_decision.allowed

    @property
    def can_end_authority(self) -> bool:
        """Return whether the actor can revoke an active assignment's authority."""
        return self.revoke_decision.allowed


def _load_assignment_page(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    route_name: str,
    require_role_control: bool = False,
    require_revoke: bool = False,
) -> _AssignmentPageRead:
    """Authorize and audit assignment access before protected labels.

    Parameters
    ----------
    request : HttpRequest
        Incoming browser request carrying correlation and route evidence.
    actor : Account
        Active account requesting Assignment management.
    organization_slug : str
        Untrusted organization route locator.
    series_slug : str
        Untrusted convention-series route locator.
    edition_slug : str
        Untrusted event-edition route locator.
    route_name : str
        Stable fallback route name for read-audit evidence.
    require_role_control : bool, default=False
        Whether current role-management authority is mandatory.
    require_revoke : bool, default=False
        Whether current authority-revocation capability is mandatory.

    Returns
    -------
    _AssignmentPageRead
        Authorized exact-edition snapshot and current action decisions.

    Raises
    ------
    PermissionDenied
        If required assignment, role-management, or revocation authority is
        unavailable.
    """
    structure_read = _load_audited_structure_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        route_name=route_name,
        require_manage=False,
    )
    snapshot = structure_read.snapshot
    target = resolve_edition_target(
        organization_id=snapshot.organization.id,
        edition_id=snapshot.edition.id,
    )
    evaluated_at = timezone_now()
    manage_decision = decide(
        principal=actor,
        capability_code="workforce.manage_assignments",
        resource=target,
        at=evaluated_at,
    )
    role_decision = decide(
        principal=actor,
        capability_code="authorization.manage_roles",
        resource=target,
        at=evaluated_at,
    )
    revoke_decision = decide(
        principal=actor,
        capability_code="authorization.revoke",
        resource=target,
        at=evaluated_at,
    )
    if (
        not manage_decision.allowed
        or (require_role_control and not role_decision.allowed)
        or (require_revoke and not revoke_decision.allowed)
    ):
        raise PermissionDenied
    route = (
        request.resolver_match.url_name
        if request.resolver_match is not None and request.resolver_match.url_name
        else route_name
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=snapshot.organization.id,
            event_edition_id=snapshot.edition.id,
            capability_code="workforce.manage_assignments",
            operation="workforce.position_assignment.view",
            target_type="events.event_edition",
            target_id=snapshot.edition.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=manage_decision.reason_code,
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
            obligations=tuple(sorted(manage_decision.obligations)),
            changed_fields=(),
            safe_metadata={"policy_version": POLICY_VERSION, "route_name": route},
            retention_class="workforce-restricted",
        ),
        occurred_at=evaluated_at,
    )
    return _AssignmentPageRead(
        structure_read=structure_read,
        manage_decision=manage_decision,
        role_decision=role_decision,
        revoke_decision=revoke_decision,
    )


def _assignment_page_context(
    request: HttpRequest,
    *,
    read: _AssignmentPageRead,
    page_id: str,
) -> dict[str, object]:
    context = _position_context(
        request,
        read=read.structure_read,
        page_id=page_id,
    )
    context.update(
        {
            "can_manage_assignments": True,
            "can_issue_assignment_authority": read.can_issue_authority,
            "can_end_assignment_authority": read.can_end_authority,
            "assignment_access_label": _structure_access_label(read.manage_decision),
        }
    )
    return context


def _assignment_route_kwargs(
    snapshot: _OrganizationStructureSnapshot,
) -> dict[str, object]:
    return {
        "organization_slug": snapshot.organization.slug,
        "series_slug": snapshot.series.slug,
        "edition_slug": snapshot.edition.slug,
    }


def _assignment_location(
    snapshot: _OrganizationStructureSnapshot,
    *,
    assignment_id: UUID | None = None,
) -> str:
    kwargs = _assignment_route_kwargs(snapshot)
    if assignment_id is None:
        return reverse("organization-workforce-assignments", kwargs=kwargs)
    kwargs["assignment_id"] = assignment_id
    return reverse("organization-workforce-assignment", kwargs=kwargs)


def _assignment_lifecycle_allows(
    read: _AssignmentPageRead,
    *,
    cleanup: bool = False,
) -> bool:
    permitted = {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
    }
    if cleanup:
        permitted.add(EventEdition.Lifecycle.CLOSING)
    return bool(
        read.snapshot.organization.lifecycle
        in {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
        and read.snapshot.edition.lifecycle in permitted
    )


def _default_assignment_effective_from() -> datetime:
    """Return the next whole minute so authority never starts in the past.

    Returns
    -------
    datetime
        Aware next whole-minute proposal default.
    """
    return (timezone_now() + timedelta(minutes=1)).replace(second=0, microsecond=0)


def _assignment_record(
    *,
    read: _AssignmentPageRead,
    assignment_id: UUID,
) -> PositionAssignment:
    assignment = (
        PositionAssignment.objects.select_related(
            "account",
            "position",
            "position__department",
            "position__template",
            "position__role_bundle",
            "proposed_by",
            "approved_by",
            "decision_by",
            "ended_by",
            "role_assignment",
        )
        .filter(
            id=assignment_id,
            organization_id=read.snapshot.organization.id,
            edition_id=read.snapshot.edition.id,
        )
        .order_by()
        .first()
    )
    if assignment is None:
        raise Http404
    return assignment


def _render_assignment_overview(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> TemplateResponse:
    read = _load_assignment_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        route_name="organization-workforce-assignments",
    )
    context = _assignment_page_context(
        request,
        read=read,
        page_id="organization-workforce-assignments",
    )
    context.update(
        {
            "title": f"Assignments — {read.snapshot.edition.name}",
            "assignments": assignment_overview_items(
                organization_id=read.snapshot.organization.id,
                edition_id=read.snapshot.edition.id,
                actor=actor,
            ),
            "assignment_actions_allowed": _assignment_lifecycle_allows(read),
            "assignment_cleanup_allowed": _assignment_lifecycle_allows(
                read,
                cleanup=True,
            ),
            "positions": _position_overview_items(read.structure_read),
        }
    )
    return TemplateResponse(
        request,
        "workforce/assignment_management.html",
        context,
    )


def _render_assignment_proposal(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
    form: PositionAssignmentProposalForm | None = None,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> TemplateResponse:
    read = _load_assignment_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        route_name="organization-workforce-assignment-proposal",
        require_role_control=True,
    )
    projected_position, _department = _find_position(
        read.snapshot.structure,
        position_id,
    )
    position = _position_record(
        organization_id=read.snapshot.organization.id,
        edition_id=read.snapshot.edition.id,
        position_id=position_id,
    )
    candidates = known_assignment_candidates(position=position)
    choices = tuple(
        (str(candidate.account_id), candidate.choice_label) for candidate in candidates
    )
    if form is None:
        form = PositionAssignmentProposalForm(
            candidate_choices=choices,
            zone_name=read.snapshot.edition.time_zone,
            default_effective_from=_default_assignment_effective_from(),
        )
    open_assignment_count = PositionAssignment.objects.filter(
        position=position,
        status__in=(
            PositionAssignment.Status.PROPOSED,
            PositionAssignment.Status.ACTIVE,
        ),
    ).count()
    proposal_available = bool(
        _assignment_lifecycle_allows(read)
        and position.status != Position.Status.CLOSED
        and open_assignment_count < position.headcount
        and candidates
    )
    context = _assignment_page_context(
        request,
        read=read,
        page_id="organization-workforce-assignment-proposal",
    )
    context.update(
        {
            "title": f"Propose assignment — {position.title}",
            "position": position,
            "projected_position": projected_position,
            "candidates": candidates,
            "form": form,
            "proposal_available": proposal_available,
            "open_assignment_count": open_assignment_count,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return TemplateResponse(
        request,
        "workforce/assignment_proposal.html",
        context,
        status=status,
    )


def _render_assignment_detail(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    assignment_id: UUID,
    approve_form: AssignmentDecisionForm | None = None,
    reject_form: AssignmentDecisionForm | None = None,
    end_form: AssignmentDecisionForm | None = None,
    active_action: str = "",
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> TemplateResponse:
    read = _load_assignment_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        route_name="organization-workforce-assignment",
    )
    assignment = _assignment_record(read=read, assignment_id=assignment_id)
    version = assignment.command_version or 1
    if approve_form is None:
        approve_form = AssignmentDecisionForm(
            expected_version=version,
            action_code="approve",
        )
    if reject_form is None:
        reject_form = AssignmentDecisionForm(
            expected_version=version,
            action_code="reject",
        )
    if end_form is None:
        end_form = AssignmentDecisionForm(
            expected_version=version,
            action_code="end",
        )
    labels = account_display_labels(
        {
            assignment.account_id,
            assignment.proposed_by_id,
            *(
                (assignment.decision_by_id,)
                if assignment.decision_by_id is not None
                else ()
            ),
            *((assignment.ended_by_id,) if assignment.ended_by_id is not None else ()),
        }
    )
    readiness = assignment_readiness(
        position=assignment.position,
        account_id=assignment.account_id,
    )
    proposal_open = assignment.status == PositionAssignment.Status.PROPOSED
    can_decide = bool(
        proposal_open
        and read.can_issue_authority
        and assignment.proposed_by_id != actor.id
        and _assignment_lifecycle_allows(read, cleanup=True)
    )
    can_approve = bool(can_decide and _assignment_lifecycle_allows(read))
    can_end = bool(
        assignment.status == PositionAssignment.Status.ACTIVE
        and read.can_end_authority
        and _assignment_lifecycle_allows(read, cleanup=True)
    )
    context = _assignment_page_context(
        request,
        read=read,
        page_id="organization-workforce-assignment",
    )
    context.update(
        {
            "title": f"{assignment.position.title} assignment",
            "assignment": assignment,
            "account_label": labels.get(assignment.account_id, "Maru account"),
            "proposer_label": labels.get(
                assignment.proposed_by_id,
                "Maru account",
            ),
            "decider_label": (
                labels.get(assignment.decision_by_id)
                if assignment.decision_by_id is not None
                else None
            ),
            "ender_label": (
                labels.get(assignment.ended_by_id)
                if assignment.ended_by_id is not None
                else None
            ),
            "readiness": readiness,
            "history": assignment_history_items(assignment=assignment),
            "approve_form": approve_form,
            "reject_form": reject_form,
            "end_form": end_form,
            "can_decide_assignment": can_decide,
            "can_approve_assignment": can_approve and readiness.ready,
            "can_end_assignment": can_end,
            "is_proposer": assignment.proposed_by_id == actor.id,
            "active_action": active_action,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return TemplateResponse(
        request,
        "workforce/assignment_detail.html",
        context,
        status=status,
    )


def _assignment_conflict_message(  # noqa: PLR0911
    error: AssignmentCommandError,
) -> str:
    if isinstance(error, AssignmentVersionConflictError):
        return (
            "This assignment changed after the page was opened. Reload its "
            "latest state before trying again."
        )
    if isinstance(error, AssignmentRetryConflictError):
        return (
            "This retry identifier was already used for a different assignment "
            "action. Reload before trying again."
        )
    if isinstance(error, AssignmentLifecycleConflictError):
        return "The edition or organization is now read-only for this action."
    if isinstance(error, AssignmentHeadcountConflictError):
        return "This Position has reached its approved headcount."
    if isinstance(error, AssignmentReadinessConflictError):
        return (
            "Required onboarding items are not all approved yet. Review readiness "
            "before approving."
        )
    if isinstance(error, AssignmentCandidateUnavailableError):
        return (
            "That person is no longer an active, known candidate in this scope. "
            "Reload the candidate list."
        )
    return "The action no longer matches the assignment's current state."


def _add_assignment_validation_errors(
    form: forms.BaseForm,
    error: ValidationError,
) -> bool:
    if not hasattr(error, "error_dict"):
        form.add_error(None, "Review the submitted assignment details.")
        return True
    known_fields = {"account_id", "effective_from", "expires_at", "reason"}
    known_fields.update({"expected_version", "retry_key"})
    if set(error.error_dict) - known_fields:
        return False
    for field_name, field_errors in error.error_dict.items():
        for field_error in field_errors:
            form.add_error(field_name, field_error)
    return True


def _assignment_step_up_redirect(
    *,
    return_to: str,
) -> HttpResponse:
    response = redirect(
        f"{reverse('account-step-up')}?{urlencode({'next': return_to})}"
    )
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _require_assignment_step_up(
    request: HttpRequest,
    *,
    actor: Account,
    return_to: str,
) -> HttpResponse | None:
    """Require recent authentication for assignment decisions or ending.

    Parameters
    ----------
    request : HttpRequest
        Incoming decision request whose body remains unread.
    actor : Account
        Current authorized assignment controller.
    return_to : str
        Local assignment URL restored after successful step-up.

    Returns
    -------
    HttpResponse | None
        A private redirect to step-up when required, otherwise ``None``.
    """
    try:
        require_recent_step_up(account=actor, request=request)
    except ValidationError:
        return _assignment_step_up_redirect(return_to=return_to)
    return None


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_workforce_assignments(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render the purpose-built assignment queue for one exact edition.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated browser request.
    organization_slug : str
        Organization locator from the persisted route chain.
    series_slug : str
        Convention-series locator from the persisted route chain.
    edition_slug : str
        Event-edition locator from the persisted route chain.

    Returns
    -------
    HttpResponse
        Private assignment queue or a bounded failure response.
    """
    actor = _active_admin_account(request)
    try:
        if request.GET:
            return _organization_structure_bad_request(request)
        return _render_assignment_overview(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except (AssignmentReadLimitExceededError, DatabaseError, RuntimeError):
        logger.exception("Unable to load Workforce assignments")
        return _organization_structure_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_workforce_assignment_proposal(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
) -> HttpResponse:
    """Render a closed-candidate assignment proposal form.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated browser request.
    organization_slug : str
        Organization locator from the persisted route chain.
    series_slug : str
        Convention-series locator from the persisted route chain.
    edition_slug : str
        Event-edition locator from the persisted route chain.
    position_id : UUID
        Exact Position receiving a proposed person.

    Returns
    -------
    HttpResponse
        Private proposal form or a bounded failure response.
    """
    actor = _active_admin_account(request)
    try:
        if request.GET:
            return _organization_structure_bad_request(request)
        return _render_assignment_proposal(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
        )
    except (AssignmentReadLimitExceededError, DatabaseError, RuntimeError):
        logger.exception("Unable to load assignment proposal")
        return _organization_structure_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_POST
def propose_organization_workforce_assignment(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    position_id: UUID,
) -> HttpResponse:
    """Create a non-authoritative assignment proposal.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated browser request with closed proposal input.
    organization_slug : str
        Organization locator from the persisted route chain.
    series_slug : str
        Convention-series locator from the persisted route chain.
    edition_slug : str
        Event-edition locator from the persisted route chain.
    position_id : UUID
        Exact Position receiving the proposal.

    Returns
    -------
    HttpResponse
        Redirect after success or a private validation, conflict, or failure
        response.

    Raises
    ------
    Http404
        If an authorized request names an unavailable Position.
    PermissionDenied
        If current assignment or role-management authority is unavailable.
    """
    actor = _active_admin_account(request)
    try:
        read = _load_assignment_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            route_name="propose-organization-workforce-assignment",
            require_role_control=True,
        )
        if request.GET:
            return _organization_structure_bad_request(request)
        position = _position_record(
            organization_id=read.snapshot.organization.id,
            edition_id=read.snapshot.edition.id,
            position_id=position_id,
        )
        candidates = known_assignment_candidates(position=position)
    except Http404:
        raise
    except (AssignmentReadLimitExceededError, DatabaseError, RuntimeError):
        logger.exception("Unable to prepare assignment proposal")
        return _organization_structure_dependency_failure(request)
    form = PositionAssignmentProposalForm(
        request.POST,
        candidate_choices=tuple(
            (str(candidate.account_id), candidate.choice_label)
            for candidate in candidates
        ),
        zone_name=read.snapshot.edition.time_zone,
        default_effective_from=_default_assignment_effective_from(),
    )
    if not form.is_valid():
        return _render_assignment_proposal(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            status=400,
            action_error="Review the highlighted values. Nothing was proposed.",
        )
    try:
        result = propose_position_assignment(
            actor=actor,
            organization_id=read.snapshot.organization.id,
            series_id=read.snapshot.series.id,
            edition_id=read.snapshot.edition.id,
            position_id=position_id,
            account_id=cast("UUID", form.cleaned_data["account_id"]),
            effective_from=cast("datetime", form.cleaned_data["effective_from"]),
            expires_at=cast("datetime | None", form.cleaned_data["expires_at"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_assignment_validation_errors(form, error):
            logger.exception("Assignment proposal returned an internal field key")
            return _organization_structure_dependency_failure(request)
        return _render_assignment_proposal(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            status=400,
            action_error="Review the highlighted values. Nothing was proposed.",
        )
    except AssignmentAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except AssignmentUnavailableError as error:
        raise Http404 from error
    except AssignmentCommandError as error:
        return _render_assignment_proposal(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            position_id=position_id,
            form=form,
            status=409,
            action_error=_assignment_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to propose Workforce assignment")
        return _organization_structure_dependency_failure(request)
    messages.success(
        request,
        "Assignment proposed. A different authorized controller must decide it.",
    )
    return redirect(
        _assignment_location(
            read.snapshot,
            assignment_id=result.assignment_id,
        )
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_workforce_assignment(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    assignment_id: UUID,
) -> HttpResponse:
    """Render one assignment's state, readiness, and retained history.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated browser request.
    organization_slug : str
        Organization locator from the persisted route chain.
    series_slug : str
        Convention-series locator from the persisted route chain.
    edition_slug : str
        Event-edition locator from the persisted route chain.
    assignment_id : UUID
        Exact assignment to inspect.

    Returns
    -------
    HttpResponse
        Private assignment detail or a bounded failure response.
    """
    actor = _active_admin_account(request)
    try:
        if request.GET:
            return _organization_structure_bad_request(request)
        return _render_assignment_detail(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            assignment_id=assignment_id,
        )
    except (AssignmentReadLimitExceededError, DatabaseError, RuntimeError):
        logger.exception("Unable to load Workforce assignment")
        return _organization_structure_dependency_failure(request)


def _assignment_decision_post(  # noqa: PLR0911
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    assignment_id: UUID,
    action: str,
) -> HttpResponse:
    actor = _active_admin_account(request)
    require_revoke = action == "end"
    try:
        read = _load_assignment_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            route_name=f"{action}-organization-workforce-assignment",
            require_role_control=not require_revoke,
            require_revoke=require_revoke,
        )
        if request.GET:
            return _organization_structure_bad_request(request)
        assignment = _assignment_record(read=read, assignment_id=assignment_id)
    except Http404:
        raise
    except (AssignmentReadLimitExceededError, DatabaseError, RuntimeError):
        logger.exception("Unable to prepare assignment %s", action)
        return _organization_structure_dependency_failure(request)
    return_to = _assignment_location(
        read.snapshot,
        assignment_id=assignment.id,
    )
    step_up_response = _require_assignment_step_up(
        request,
        actor=actor,
        return_to=return_to,
    )
    if step_up_response is not None:
        return step_up_response
    form = AssignmentDecisionForm(
        request.POST,
        expected_version=assignment.command_version or 1,
        action_code=action,
    )
    if not form.is_valid():
        return _render_assignment_detail(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            assignment_id=assignment.id,
            approve_form=form if action == "approve" else None,
            reject_form=form if action == "reject" else None,
            end_form=form if action == "end" else None,
            active_action=action,
            status=400,
            action_error="Review the highlighted values. Nothing was changed.",
        )
    commands = {
        "approve": approve_position_assignment,
        "reject": reject_position_assignment,
        "end": end_position_assignment,
    }
    command = commands[action]
    try:
        result = command(
            actor=actor,
            organization_id=read.snapshot.organization.id,
            series_id=read.snapshot.series.id,
            edition_id=read.snapshot.edition.id,
            assignment_id=assignment.id,
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_assignment_validation_errors(form, error):
            logger.exception("Assignment %s returned an internal field key", action)
            return _organization_structure_dependency_failure(request)
        return _render_assignment_detail(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            assignment_id=assignment.id,
            approve_form=form if action == "approve" else None,
            reject_form=form if action == "reject" else None,
            end_form=form if action == "end" else None,
            active_action=action,
            status=400,
            action_error="Review the highlighted values. Nothing was changed.",
        )
    except AssignmentAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except AssignmentUnavailableError as error:
        raise Http404 from error
    except AssignmentCommandError as error:
        return _render_assignment_detail(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            assignment_id=assignment.id,
            approve_form=form if action == "approve" else None,
            reject_form=form if action == "reject" else None,
            end_form=form if action == "end" else None,
            active_action=action,
            status=409,
            action_error=_assignment_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to %s Workforce assignment", action)
        return _organization_structure_dependency_failure(request)
    messages.success(
        request,
        {
            "approve": "Assignment approved and its scoped authority is active.",
            "reject": "Assignment proposal rejected with its history retained.",
            "end": "Assignment and its scoped authority ended.",
        }[action],
    )
    return redirect(
        _assignment_location(
            read.snapshot,
            assignment_id=result.assignment_id,
        )
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def approve_organization_workforce_assignment(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    assignment_id: UUID,
) -> HttpResponse:
    """Approve one proposal after current authorization and fresh step-up.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated browser decision request.
    organization_slug : str
        Organization locator from the persisted route chain.
    series_slug : str
        Convention-series locator from the persisted route chain.
    edition_slug : str
        Event-edition locator from the persisted route chain.
    assignment_id : UUID
        Proposed assignment to approve.

    Returns
    -------
    HttpResponse
        Step-up redirect, action result redirect, or private failure response.
    """
    return _assignment_decision_post(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        assignment_id=assignment_id,
        action="approve",
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def reject_organization_workforce_assignment(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    assignment_id: UUID,
) -> HttpResponse:
    """Reject one proposal after current authorization and fresh step-up.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated browser decision request.
    organization_slug : str
        Organization locator from the persisted route chain.
    series_slug : str
        Convention-series locator from the persisted route chain.
    edition_slug : str
        Event-edition locator from the persisted route chain.
    assignment_id : UUID
        Proposed assignment to reject.

    Returns
    -------
    HttpResponse
        Step-up redirect, action result redirect, or private failure response.
    """
    return _assignment_decision_post(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        assignment_id=assignment_id,
        action="reject",
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def end_organization_workforce_assignment(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    assignment_id: UUID,
) -> HttpResponse:
    """End one active assignment after authorization and fresh step-up.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated browser ending request.
    organization_slug : str
        Organization locator from the persisted route chain.
    series_slug : str
        Convention-series locator from the persisted route chain.
    edition_slug : str
        Event-edition locator from the persisted route chain.
    assignment_id : UUID
        Active assignment to end.

    Returns
    -------
    HttpResponse
        Step-up redirect, action result redirect, or private failure response.
    """
    return _assignment_decision_post(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        assignment_id=assignment_id,
        action="end",
    )


@dataclass(frozen=True, slots=True)
class _PersonalAvailabilityPage:
    """One authorized owner-facing exact-edition Availability projection."""

    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    projection: PersonAvailabilityProjection
    can_edit: bool


def _personal_availability_state_response(
    request: HttpRequest,
    *,
    status: int,
    message: str,
) -> TemplateResponse:
    """Render a private, name-free Availability failure state.

    Parameters
    ----------
    request : HttpRequest
        Incoming personal-surface request.
    status : int
        HTTP status for the bounded state.
    message : str
        Safe explanation shown without edition or Position labels.

    Returns
    -------
    TemplateResponse
        Private personal Availability state response.
    """
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "My availability",
            "has_permission": True,
            "maru_personal_surface": True,
            "availability_state_message": message,
        }
    )
    return TemplateResponse(
        request,
        "workforce/my_availability.html",
        context,
        status=status,
    )


def _personal_availability_page(
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    require_edit: bool,
) -> _PersonalAvailabilityPage:
    """Resolve relationship and policy before loading scoped display labels.

    Parameters
    ----------
    actor : Account
        Authenticated person who owns any returned plan.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.
    require_edit : bool
        Whether an open assignment must permit replacement.

    Returns
    -------
    _PersonalAvailabilityPage
        Authorized exact-edition context and owner-visible projection.

    Raises
    ------
    Http404
        If the persisted route chain does not exist.
    PermissionDenied
        If the person has no retained exact-edition relationship.
    AvailabilityRelationshipRequiredError
        If replacement was requested without an open assignment.
    """
    scope = (
        EventEdition.objects.filter(
            organization__slug__iexact=organization_slug,
            series__slug__iexact=series_slug,
            series__organization_id=models.F("organization_id"),
            slug__iexact=edition_slug,
        )
        .order_by("id")
        .values("id", "organization_id", "series_id")
        .first()
    )
    if scope is None:
        raise Http404
    organization_id = scope["organization_id"]
    edition_id = scope["id"]
    authorize_person_availability_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if not person_has_availability_relationship(
        account=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    ):
        raise PermissionDenied
    can_edit = person_can_edit_availability(
        account=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if require_edit and not can_edit:
        raise AvailabilityRelationshipRequiredError
    with repeatable_read_only_snapshot():
        edition = EventEdition.objects.select_related("organization", "series").get(
            id=edition_id,
            organization_id=organization_id,
            series_id=scope["series_id"],
        )
        projection = load_person_availability(
            account=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    authorize_person_availability_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    return _PersonalAvailabilityPage(
        organization=edition.organization,
        series=edition.series,
        edition=edition,
        projection=projection,
        can_edit=can_edit,
    )


def _availability_period_initial(
    projection: PersonAvailabilityProjection,
) -> tuple[dict[str, str], ...]:
    """Convert local aware periods to minute-precision browser controls.

    Parameters
    ----------
    projection : PersonAvailabilityProjection
        Current owner-visible plan projection.

    Returns
    -------
    tuple[dict[str, str], ...]
        Local form initial values in canonical period order.
    """
    return tuple(
        {
            "starts_at": window.starts_at.strftime("%Y-%m-%dT%H:%M"),
            "ends_at": window.ends_at.strftime("%Y-%m-%dT%H:%M"),
            "preference": window.preference,
        }
        for window in projection.windows
    )


def _personal_availability_context(
    request: HttpRequest,
    *,
    page: _PersonalAvailabilityPage,
    command_form: AvailabilityCommandForm | None = None,
    window_formset: BaseAvailabilityWindowFormSet | None = None,
    withdraw_form: AvailabilityWithdrawForm | None = None,
    action_error: str = "",
    reload_required: bool = False,
) -> dict[str, object]:
    """Compose a single owner-facing Availability workspace context.

    Parameters
    ----------
    request : HttpRequest
        Incoming personal-surface request.
    page : _PersonalAvailabilityPage
        Authorized owner context and current projection.
    command_form : AvailabilityCommandForm | None, default=None
        Optional bound replacement command form.
    window_formset : BaseAvailabilityWindowFormSet | None, default=None
        Optional bound repeatable-period formset.
    withdraw_form : AvailabilityWithdrawForm | None, default=None
        Optional bound withdrawal form.
    action_error : str, default=""
        Safe action-local failure guidance.
    reload_required : bool, default=False
        Whether stale state requires a fresh page load.

    Returns
    -------
    dict[str, object]
        Private template context for the unified personal page.
    """
    version = page.projection.version
    if command_form is None:
        command_form = AvailabilityCommandForm(expected_version=version)
    if window_formset is None:
        window_formset = AvailabilityWindowFormSet(
            prefix="windows",
            initial=_availability_period_initial(page.projection),
            starts_on=page.edition.starts_on,
            ends_on=page.edition.ends_on,
            time_zone=page.edition.time_zone,
        )
    if withdraw_form is None and page.projection.plan is not None:
        withdraw_form = AvailabilityWithdrawForm(expected_version=version)
    can_withdraw = bool(
        page.projection.plan is not None
        and page.projection.plan.status != PersonAvailabilityPlan.Status.WITHDRAWN
        and page.organization.lifecycle
        in {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
        and page.edition.lifecycle
        in {
            EventEdition.Lifecycle.DRAFT,
            EventEdition.Lifecycle.PREPARING,
            EventEdition.Lifecycle.READY,
            EventEdition.Lifecycle.LIVE,
            EventEdition.Lifecycle.CLOSING,
        }
    )
    context = admin.site.each_context(request)
    context.update(
        {
            "title": f"My availability — {page.edition.name}",
            "has_permission": True,
            "maru_personal_surface": True,
            "organization": page.organization,
            "convention_series": page.series,
            "edition": page.edition,
            "availability": page.projection,
            "command_form": command_form,
            "window_formset": window_formset,
            "withdraw_form": withdraw_form,
            "can_edit_availability": page.can_edit,
            "can_withdraw_availability": can_withdraw,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return context


def _render_personal_availability(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    command_form: AvailabilityCommandForm | None = None,
    window_formset: BaseAvailabilityWindowFormSet | None = None,
    withdraw_form: AvailabilityWithdrawForm | None = None,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> TemplateResponse:
    """Render one authorized personal Availability workspace.

    Parameters
    ----------
    request : HttpRequest
        Incoming personal-surface request.
    actor : Account
        Authenticated person who owns the projection.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.
    command_form : AvailabilityCommandForm | None, default=None
        Optional bound replacement command form.
    window_formset : BaseAvailabilityWindowFormSet | None, default=None
        Optional bound repeatable-period formset.
    withdraw_form : AvailabilityWithdrawForm | None, default=None
        Optional bound withdrawal form.
    status : int, default=200
        HTTP status for the rendered response.
    action_error : str, default=""
        Safe action-local failure guidance.
    reload_required : bool, default=False
        Whether stale state requires a fresh page load.

    Returns
    -------
    TemplateResponse
        Private owner workspace response.
    """
    page = _personal_availability_page(
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        require_edit=False,
    )
    return TemplateResponse(
        request,
        "workforce/my_availability.html",
        _personal_availability_context(
            request,
            page=page,
            command_form=command_form,
            window_formset=window_formset,
            withdraw_form=withdraw_form,
            action_error=action_error,
            reload_required=reload_required,
        ),
        status=status,
    )


def _availability_post_keys_are_supported(request: HttpRequest) -> bool:
    """Return whether the complete formset POST uses only closed fields.

    Parameters
    ----------
    request : HttpRequest
        Incoming replacement request.

    Returns
    -------
    bool
        ``True`` only when every key and multiplicity is supported.
    """
    command_fields = frozenset(
        {"csrfmiddlewaretoken", "expected_version", "retry_key", "status"}
    )
    for field_name in request.POST:
        if (
            field_name not in command_fields
            and field_name not in _AVAILABILITY_MANAGEMENT_FIELDS
            and _AVAILABILITY_WINDOW_FIELD.fullmatch(field_name) is None
        ):
            return False
        if len(request.POST.getlist(field_name)) != 1:
            return False
    return True


def _bound_availability_forms(
    request: HttpRequest,
    *,
    page: _PersonalAvailabilityPage,
) -> tuple[AvailabilityCommandForm, BaseAvailabilityWindowFormSet]:
    """Bind strict command fields separately from repeatable period fields.

    Parameters
    ----------
    request : HttpRequest
        Incoming replacement request.
    page : _PersonalAvailabilityPage
        Authorized edition context used for horizon and version binding.

    Returns
    -------
    tuple[AvailabilityCommandForm, BaseAvailabilityWindowFormSet]
        Bound command and complete-period forms.
    """
    command_form = AvailabilityCommandForm(
        {
            "expected_version": request.POST.get("expected_version", ""),
            "retry_key": request.POST.get("retry_key", ""),
            "status": request.POST.get("status", ""),
        },
        expected_version=page.projection.version,
    )
    window_formset = AvailabilityWindowFormSet(
        request.POST,
        prefix="windows",
        starts_on=page.edition.starts_on,
        ends_on=page.edition.ends_on,
        time_zone=page.edition.time_zone,
    )
    return command_form, window_formset


def _availability_conflict_message(error: AvailabilityCommandError) -> str:
    """Map current-state conflicts to owner-facing recovery guidance.

    Parameters
    ----------
    error : AvailabilityCommandError
        Current-state conflict from the canonical command boundary.

    Returns
    -------
    str
        Safe concise recovery guidance.
    """
    if isinstance(error, AvailabilityVersionConflictError):
        return "Your availability changed after this page opened. Reload and try again."
    if isinstance(error, AvailabilityRetryConflictError):
        return (
            "This retry key was already used for different availability. "
            "Reload and try again."
        )
    if isinstance(error, AvailabilityLifecycleConflictError):
        return "Availability is read-only in the current organization or edition state."
    if isinstance(error, AvailabilityRelationshipRequiredError):
        return "An open proposed or active Position is required to change availability."
    return "This action no longer matches your current availability state."


@never_cache
@login_required(login_url="staff-login")
@require_GET
def my_workforce_availability(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render one person's private exact-edition Availability workspace.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated personal-surface request.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.

    Returns
    -------
    HttpResponse
        Private workspace or bounded safe failure response.

    Raises
    ------
    PermissionDenied
        If no active person or exact self authority is available.
    """
    actor = _account(request)
    if actor is None or not actor.is_active:
        raise PermissionDenied
    if request.GET:
        return _personal_availability_state_response(
            request,
            status=400,
            message="This page does not accept filters or other URL parameters.",
        )
    try:
        return _render_personal_availability(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except AvailabilityAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to load personal Workforce availability")
        return _personal_availability_state_response(
            request,
            status=503,
            message="Your availability is temporarily unavailable. Please try again.",
        )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def save_my_workforce_availability(  # noqa: PLR0911, PLR0912
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Replace the signed-in person's complete current Availability plan.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated replacement request.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.

    Returns
    -------
    HttpResponse
        Redirect after success or private validation, conflict, or failure state.

    Raises
    ------
    PermissionDenied
        If person, scope, relationship, or self authority is unavailable.
    """
    actor = _account(request)
    if actor is None or not actor.is_active:
        raise PermissionDenied
    try:
        page = _personal_availability_page(
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            require_edit=True,
        )
    except AvailabilityAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except AvailabilityRelationshipRequiredError as error:
        raise PermissionDenied from error
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to authorize personal availability replacement")
        return _personal_availability_state_response(
            request,
            status=503,
            message="Your availability is temporarily unavailable. Please try again.",
        )
    if request.GET:
        return _personal_availability_state_response(
            request,
            status=400,
            message="This action does not accept URL parameters.",
        )
    command_form, window_formset = _bound_availability_forms(request, page=page)
    supported = _availability_post_keys_are_supported(request)
    if not supported:
        command_form.add_error(None, "Remove unsupported or repeated form fields.")
    if not command_form.is_valid() or not window_formset.is_valid() or not supported:
        return TemplateResponse(
            request,
            "workforce/my_availability.html",
            _personal_availability_context(
                request,
                page=page,
                command_form=command_form,
                window_formset=window_formset,
                action_error="Review the highlighted periods. Nothing was changed.",
            ),
            status=400,
        )
    try:
        result = save_person_availability(
            actor=actor,
            organization_id=page.organization.id,
            edition_id=page.edition.id,
            expected_version=int(command_form.cleaned_data["expected_version"]),
            status=str(command_form.cleaned_data["status"]),
            windows=window_formset.windows,
            retry_key=cast("UUID", command_form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ValidationError as error:
        if hasattr(error, "error_dict"):
            for field_name, field_errors in error.error_dict.items():
                target = field_name if field_name in command_form.fields else None
                for field_error in field_errors:
                    command_form.add_error(target, field_error)
        else:
            command_form.add_error(None, "Review the submitted availability.")
        return TemplateResponse(
            request,
            "workforce/my_availability.html",
            _personal_availability_context(
                request,
                page=page,
                command_form=command_form,
                window_formset=window_formset,
                action_error="Review the highlighted periods. Nothing was changed.",
            ),
            status=400,
        )
    except AvailabilityAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        AvailabilityVersionConflictError,
        AvailabilityRetryConflictError,
        AvailabilityLifecycleConflictError,
        AvailabilityRelationshipRequiredError,
        AvailabilityStateConflictError,
    ) as error:
        return _render_personal_availability(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            command_form=command_form,
            window_formset=window_formset,
            status=409,
            action_error=_availability_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, AvailabilityCommandError, RuntimeError):
        logger.exception("Unable to save personal Workforce availability")
        return _personal_availability_state_response(
            request,
            status=503,
            message="Your availability was not changed. Please try again.",
        )
    messages.success(
        request,
        (
            "Your private availability draft was saved."
            if result.status == PersonAvailabilityPlan.Status.DRAFT
            else "Your current availability was shared with organizers."
        ),
    )
    return redirect(
        reverse(
            "my-workforce-availability",
            kwargs={
                "organization_slug": page.organization.slug,
                "series_slug": page.series.slug,
                "edition_slug": page.edition.slug,
            },
        )
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def withdraw_my_workforce_availability(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Withdraw a plan and immediately delete its current exact periods.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated withdrawal request.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.

    Returns
    -------
    HttpResponse
        Redirect after success or private validation, conflict, or failure state.

    Raises
    ------
    PermissionDenied
        If person, scope, relationship, or self authority is unavailable.
    """
    actor = _account(request)
    if actor is None or not actor.is_active:
        raise PermissionDenied
    try:
        page = _personal_availability_page(
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            require_edit=False,
        )
    except AvailabilityAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to authorize personal availability withdrawal")
        return _personal_availability_state_response(
            request,
            status=503,
            message="Your availability is temporarily unavailable. Please try again.",
        )
    form = AvailabilityWithdrawForm(
        request.POST,
        expected_version=max(1, page.projection.version),
    )
    if request.GET or not form.is_valid():
        return TemplateResponse(
            request,
            "workforce/my_availability.html",
            _personal_availability_context(
                request,
                page=page,
                withdraw_form=form,
                action_error="Confirm the withdrawal. Nothing was changed.",
            ),
            status=400,
        )
    try:
        withdraw_person_availability(
            actor=actor,
            organization_id=page.organization.id,
            edition_id=page.edition.id,
            expected_version=int(form.cleaned_data["expected_version"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except AvailabilityAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        AvailabilityVersionConflictError,
        AvailabilityRetryConflictError,
        AvailabilityLifecycleConflictError,
        AvailabilityStateConflictError,
    ) as error:
        return _render_personal_availability(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            withdraw_form=form,
            status=409,
            action_error=_availability_conflict_message(error),
            reload_required=True,
        )
    except (DatabaseError, AvailabilityCommandError, RuntimeError, ValidationError):
        logger.exception("Unable to withdraw personal Workforce availability")
        return _personal_availability_state_response(
            request,
            status=503,
            message="Your availability was not withdrawn. Please try again.",
        )
    messages.success(request, "Your exact availability periods were removed.")
    return redirect(
        reverse(
            "my-workforce-availability",
            kwargs={
                "organization_slug": page.organization.slug,
                "series_slug": page.series.slug,
                "edition_slug": page.edition.slug,
            },
        )
    )


@dataclass(frozen=True, slots=True)
class _OrganizerAvailabilityPage:
    """One authorized organizer Availability projection and policy decision."""

    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    decision: PolicyDecision
    overview: OrganizerAvailabilityOverview


def _authorize_organizer_availability(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime,
) -> PolicyDecision:
    """Require the complete organizer Availability field projection.

    Parameters
    ----------
    actor : Account
        Authenticated organizer.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact event edition.
    at : datetime
        Policy evaluation instant.

    Returns
    -------
    PolicyDecision
        Allowed decision with the complete field ceiling.

    Raises
    ------
    PermissionDenied
        If capability or any required projection field is absent.
    """
    decision = decide(
        principal=actor,
        capability_code="workforce.view_availability",
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        requested_fields=AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
        at=at,
    )
    if not decision.allowed:
        raise PermissionDenied
    try:
        require_complete_projection(
            required_fields=AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
            permitted_fields=decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied from error
    return decision


def _load_organizer_availability_page(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> _OrganizerAvailabilityPage:
    """Load one coherent minimized projection, reauthorize, then audit it.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer request carrying route and correlation context.
    actor : Account
        Authenticated organizer.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.

    Returns
    -------
    _OrganizerAvailabilityPage
        Audited exact-edition organizer projection and decision.
    """
    with repeatable_read_only_snapshot():
        organization, series, edition = authorized_admin_edition_for_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            capability_code="workforce.view_availability",
        )
        _authorize_organizer_availability(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
            at=timezone_now(),
        )
        overview = load_organizer_availability_overview(edition=edition)
    response_authorized_at = timezone_now()
    decision = _authorize_organizer_availability(
        actor=actor,
        organization_id=organization.id,
        edition_id=edition.id,
        at=response_authorized_at,
    )
    route_name = (
        request.resolver_match.url_name
        if request.resolver_match is not None and request.resolver_match.url_name
        else "organization-workforce-availability"
    )
    append_availability_read_audit(
        actor=actor,
        organization_id=organization.id,
        edition_id=edition.id,
        decision=decision,
        correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
        route_name=route_name,
        http_method=cast("str", request.method),
        source_channel="web",
        occurred_at=response_authorized_at,
    )
    return _OrganizerAvailabilityPage(
        organization=organization,
        series=series,
        edition=edition,
        decision=decision,
        overview=overview,
    )


def _organizer_availability_context(
    request: HttpRequest,
    *,
    actor: Account,
    page: _OrganizerAvailabilityPage,
) -> dict[str, object]:
    """Compose the shared management shell without broadening disclosure.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer request.
    actor : Account
        Authenticated organizer.
    page : _OrganizerAvailabilityPage
        Audited exact-edition projection.

    Returns
    -------
    dict[str, object]
        Unified administration-shell template context.
    """
    edition_target = resolve_edition_target(
        organization_id=page.organization.id,
        edition_id=page.edition.id,
    )
    organization_target = _required_organization_target(
        organization_id=page.organization.id
    )
    context = admin.site.each_context(request)
    context.update(
        {
            "title": f"Availability — {page.edition.name}",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "organization-workforce-availability",
            "baseline_page_class": "",
            "baseline_can_view_organization": decide(
                principal=actor,
                capability_code="organizations.view_basic",
                resource=organization_target,
            ).allowed,
            "baseline_can_manage_representation": False,
            "baseline_can_create_series": False,
            "baseline_can_create_edition": False,
            "baseline_can_view_edition": decide(
                principal=actor,
                capability_code="events.view_basic",
                resource=edition_target,
            ).allowed,
            "baseline_can_view_structure": decide(
                principal=actor,
                capability_code="workforce.view_structure",
                resource=edition_target,
            ).allowed,
            "baseline_can_manage_structure": False,
            "baseline_can_manage_registration": False,
            "baseline_structure_navigation_current": True,
            "organization": page.organization,
            "convention_series": page.series,
            "edition": page.edition,
            "availability_overview": page.overview,
            "availability_access_label": _structure_access_label(page.decision),
            "can_view_shifts": decide(
                principal=actor,
                capability_code="workforce.view_shifts",
                resource=edition_target,
            ).allowed,
        }
    )
    return context


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_workforce_availability(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render shared current availability for open-assignment people.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated organizer request.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.

    Returns
    -------
    HttpResponse
        Audited organizer projection or bounded safe failure response.
    """
    actor = _active_admin_account(request)
    if request.GET:
        return _organization_structure_bad_request(request)
    try:
        page = _load_organizer_availability_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        context = _organizer_availability_context(request, actor=actor, page=page)
    except (AvailabilityReadLimitExceededError, AvailabilityProjectionIntegrityError):
        logger.exception("Unable to produce a complete organizer Availability view")
        return _organization_structure_dependency_failure(request)
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to load organizer Workforce availability")
        return _organization_structure_dependency_failure(request)
    return TemplateResponse(
        request,
        "workforce/availability_management.html",
        context,
    )


def _my_workforce_state_response(
    request: HttpRequest,
    *,
    status: int,
    message: str,
) -> TemplateResponse:
    """Render a personal, name-free unavailable or invalid-request state.

    Parameters
    ----------
    request : HttpRequest
        Incoming personal-surface request.
    status : int
        HTTP status for the bounded state.
    message : str
        Safe explanation shown without assignment labels.

    Returns
    -------
    TemplateResponse
        Private personal Workforce state response.
    """
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "My Workforce",
            "has_permission": True,
            "maru_personal_surface": True,
            "assignments": (),
            "availability_scopes": (),
            "shift_scopes": (),
            "workforce_state_message": message,
        }
    )
    return TemplateResponse(
        request,
        "workforce/my_assignments.html",
        context,
        status=status,
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def my_workforce_assignments(request: HttpRequest) -> HttpResponse:
    """Render the signed-in person's reason-minimized assignment history.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated personal-surface request.

    Returns
    -------
    HttpResponse
        Private personal assignments or a bounded invalid/unavailable state.

    Raises
    ------
    PermissionDenied
        If no active account backs the authenticated session.
    """
    actor = _account(request)
    if actor is None or not actor.is_active:
        raise PermissionDenied
    if request.GET:
        return _my_workforce_state_response(
            request,
            status=400,
            message="This page does not accept filters or other URL parameters.",
        )
    try:
        assignment_scope_rows = tuple(
            PositionAssignment.objects.filter(account=actor)
            .order_by("organization_id", "edition_id")
            .values_list("organization_id", "edition_id")
            .distinct()[: MAX_PERSONAL_ASSIGNMENT_SCOPES + 1]
        )
        plan_scope_rows = tuple(
            PersonAvailabilityPlan.objects.filter(account=actor)
            .order_by("organization_id", "edition_id")
            .values_list("organization_id", "edition_id")
            .distinct()[: MAX_PERSONAL_ASSIGNMENT_SCOPES + 1]
        )
        commitment_scope_rows = tuple(
            ShiftCommitment.objects.filter(account=actor)
            .order_by("organization_id", "edition_id")
            .values_list("organization_id", "edition_id")
            .distinct()[: MAX_PERSONAL_ASSIGNMENT_SCOPES + 1]
        )
        if (
            len(assignment_scope_rows) > MAX_PERSONAL_ASSIGNMENT_SCOPES
            or len(plan_scope_rows) > MAX_PERSONAL_ASSIGNMENT_SCOPES
            or len(commitment_scope_rows) > MAX_PERSONAL_ASSIGNMENT_SCOPES
        ):
            return _my_workforce_state_response(
                request,
                status=503,
                message=(
                    "Your Workforce information is temporarily unavailable. "
                    "Please try again shortly."
                ),
            )
        scope_rows = tuple(
            sorted(
                set(assignment_scope_rows)
                | set(plan_scope_rows)
                | set(commitment_scope_rows)
            )
        )
        if len(scope_rows) > MAX_PERSONAL_ASSIGNMENT_SCOPES:
            return _my_workforce_state_response(
                request,
                status=503,
                message=(
                    "Your Workforce information is temporarily unavailable. "
                    "Please try again shortly."
                ),
            )
        permitted_scopes = set()
        for organization_id, edition_id in scope_rows:
            target = resolve_self_target(
                principal=actor,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            decision = decide(
                principal=actor,
                capability_code="workforce.view_self",
                resource=target,
                requested_fields=frozenset({"assignments", "availability", "shifts"}),
            )
            if decision.allowed and decision.fields == frozenset(
                {"assignments", "availability", "shifts"}
            ):
                permitted_scopes.add((organization_id, edition_id))
        assignments = my_assignment_items(
            account=actor,
            permitted_scopes=frozenset(permitted_scopes),
        )
        availability_scopes = my_availability_scope_items(
            account=actor,
            permitted_scopes=frozenset(permitted_scopes),
        )
        shift_scopes = my_shift_scope_items(
            account=actor,
            permitted_scopes=frozenset(permitted_scopes),
        )
    except (
        AssignmentReadLimitExceededError,
        AvailabilityReadLimitExceededError,
        ShiftReadLimitExceededError,
        DatabaseError,
        RuntimeError,
    ):
        logger.exception("Unable to load personal Workforce assignments")
        return _my_workforce_state_response(
            request,
            status=503,
            message=(
                "Your Workforce information is temporarily unavailable. "
                "Please try again shortly."
            ),
        )
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "My Workforce",
            "has_permission": True,
            "maru_personal_surface": True,
            "assignments": assignments,
            "availability_scopes": availability_scopes,
            "shift_scopes": shift_scopes,
        }
    )
    return TemplateResponse(request, "workforce/my_assignments.html", context)


def volunteer_opportunities(
    request: HttpRequest,
    edition_id: UUID,
) -> TemplateResponse:
    """Render volunteer opportunities.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    TemplateResponse
        The HTTP response for this request.
    """
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
    """Apply for opportunity.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    opportunity_id : UUID
        The identifier of the opportunity.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
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
                motivation=cast("str", form.cleaned_data["motivation"]),
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
    """Render my onboarding documents.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
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
    """Render upload onboarding document view.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    document_request_id : UUID
        The identifier of the document request.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
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
    """Download onboarding document.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    document_request_id : UUID
        The identifier of the document request.

    Returns
    -------
    FileResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
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
