"""Unified organizer Shift planning and person-owned My shifts views."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, models
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.timezone import now as timezone_now
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from maru.authorization.enforcement import (
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_edition_target,
    resolve_organization_target,
    resolve_self_target,
)
from maru.events.admin_context import authorized_admin_edition_for_route
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.models import (
    Position,
    ShiftDemand,
)
from maru.workforce.shift_audit import append_shift_read_audit
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftAvailabilityConflictError,
    ShiftCapacityConflictError,
    ShiftCommandError,
    ShiftLifecycleConflictError,
    ShiftOverlapConflictError,
    ShiftQualificationConflictError,
    ShiftRetryConflictError,
    ShiftStateConflictError,
    ShiftUnavailableError,
    ShiftVersionConflictError,
    authorize_shift_organizer_command,
    authorize_shift_self_command,
    cancel_shift_demand,
    claim_shift,
    complete_shift_demand,
    confirm_shift_commitment,
    create_shift_demand,
    lock_shift_demand,
    open_shift_demand,
    remove_shift_commitment,
    reopen_shift_demand,
    update_shift_demand,
    withdraw_shift_claim,
)
from maru.workforce.shift_forms import (
    ShiftClaimForm,
    ShiftCommitmentReasonForm,
    ShiftDemandForm,
    ShiftLockForm,
    ShiftReasonCommandForm,
    ShiftWithdrawForm,
)
from maru.workforce.shift_queries import (
    SHIFT_ORGANIZER_REQUIRED_FIELDS,
    MyShiftCommitmentItem,
    MyShiftOverview,
    OrganizerShiftDemandItem,
    OrganizerShiftOverview,
    ShiftProjectionIntegrityError,
    ShiftReadLimitExceededError,
    SuitableShiftItem,
    load_my_shift_overview,
    load_organizer_shift_overview,
    person_has_shift_relationship,
)
from maru.workforce.structure_snapshot import repeatable_read_only_snapshot

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from datetime import datetime

    from maru.organizations.models import ConventionSeries, Organization


@dataclass(frozen=True, slots=True)
class _OrganizerShiftPage:
    """One freshly authorized organizer Shift-planning projection."""

    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    decision: PolicyDecision
    overview: OrganizerShiftOverview
    can_manage: bool


@dataclass(frozen=True, slots=True)
class _CommitmentActionRow:
    """Organizer commitment projection with isolated command forms."""

    item: object
    confirm_form: ShiftCommitmentReasonForm
    remove_form: ShiftCommitmentReasonForm


@dataclass(frozen=True, slots=True)
class _PersonalSuitableRow:
    """Suitable Shift projection with its versioned claim form."""

    item: SuitableShiftItem
    claim_form: ShiftClaimForm


@dataclass(frozen=True, slots=True)
class _PersonalCommitmentRow:
    """Owned commitment projection with its confirmation-only withdrawal form."""

    item: MyShiftCommitmentItem
    withdraw_form: ShiftWithdrawForm


def _account(request: HttpRequest) -> Account | None:
    return request.user if isinstance(request.user, Account) else None


def _active_account(request: HttpRequest) -> Account:
    account = _account(request)
    if account is None or not account.is_active:
        raise PermissionDenied
    return account


def _access_label(decision: PolicyDecision) -> str:
    return {
        "platform_administration": "Platform oversight",
        "direct_grant": "Exact edition capability",
        "role_assignment": "Scoped edition role",
    }.get(decision.reason_code, "Current scoped authority")


def _authorize_shift_read(
    *, actor: Account, organization_id: UUID, edition_id: UUID, at: datetime
) -> PolicyDecision:
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    decision = decide(
        principal=actor,
        capability_code="workforce.view_shifts",
        resource=target,
        requested_fields=SHIFT_ORGANIZER_REQUIRED_FIELDS,
        at=at,
    )
    if not decision.allowed:
        raise PermissionDenied
    try:
        require_complete_projection(
            required_fields=SHIFT_ORGANIZER_REQUIRED_FIELDS,
            permitted_fields=decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied from error
    return decision


def _load_organizer_page(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> _OrganizerShiftPage:
    with repeatable_read_only_snapshot():
        organization, series, edition = authorized_admin_edition_for_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            capability_code="workforce.view_shifts",
        )
        _authorize_shift_read(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
            at=timezone_now(),
        )
        overview = load_organizer_shift_overview(edition=edition)
    evaluated_at = timezone_now()
    decision = _authorize_shift_read(
        actor=actor,
        organization_id=organization.id,
        edition_id=edition.id,
        at=evaluated_at,
    )
    target = resolve_edition_target(
        organization_id=organization.id,
        edition_id=edition.id,
    )
    can_manage = decide(
        principal=actor,
        capability_code="workforce.manage_shifts",
        resource=target,
        at=evaluated_at,
    ).allowed
    route_name = (
        request.resolver_match.url_name
        if request.resolver_match is not None and request.resolver_match.url_name
        else "organization-workforce-shifts"
    )
    append_shift_read_audit(
        actor=actor,
        organization_id=organization.id,
        edition_id=edition.id,
        decision=decision,
        correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
        route_name=route_name,
        http_method=cast("str", request.method),
        source_channel="web",
        occurred_at=evaluated_at,
    )
    return _OrganizerShiftPage(
        organization=organization,
        series=series,
        edition=edition,
        decision=decision,
        overview=overview,
        can_manage=can_manage,
    )


def _position_choices(page: _OrganizerShiftPage) -> tuple[tuple[str, str], ...]:
    rows = Position.objects.filter(
        organization=page.organization,
        edition=page.edition,
        department__retired_at__isnull=True,
    ).exclude(status=Position.Status.CLOSED)
    return tuple(
        (str(item.id), f"{item.department.name} — {item.title}")
        for item in rows.select_related("department").order_by(
            "department__display_order", "department__name", "title", "id"
        )
    )


def _demand_form(
    *,
    page: _OrganizerShiftPage,
    data: object | None = None,
    demand: ShiftDemand | None = None,
) -> ShiftDemandForm:
    initial: dict[str, object] = {}
    expected_version = 0
    choices = _position_choices(page)
    if demand is not None:
        expected_version = demand.command_version
        choices = ((str(demand.position_id), demand.position.title),)
        initial = {
            "position_id": demand.position_id,
            "title": demand.title,
            "location_label": demand.location_label,
            "starts_at": demand.starts_at,
            "ends_at": demand.ends_at,
            "required_headcount": demand.required_headcount,
            "break_minutes": demand.break_minutes,
            "minimum_rest_minutes": demand.minimum_rest_minutes,
            "briefing": demand.briefing,
            "supervision_note": demand.supervision_note,
        }
    return ShiftDemandForm(
        data,
        position_choices=choices,
        starts_on=page.edition.starts_on,
        ends_on=page.edition.ends_on,
        time_zone=page.edition.time_zone,
        expected_version=expected_version,
        initial=initial,
    )


def _baseline_context(
    request: HttpRequest,
    *,
    actor: Account,
    page: _OrganizerShiftPage,
) -> dict[str, object]:
    organization_target = resolve_organization_target(
        organization_id=page.organization.id
    )
    edition_target = resolve_edition_target(
        organization_id=page.organization.id,
        edition_id=page.edition.id,
    )
    context = admin.site.each_context(request)
    context.update(
        {
            "title": f"Shift planning — {page.edition.name}",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "organization-workforce-shifts",
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
            "shift_overview": page.overview,
            "can_manage_shifts": page.can_manage,
            "shift_access_label": _access_label(page.decision),
        }
    )
    return context


def _organizer_list_context(
    request: HttpRequest,
    *,
    actor: Account,
    page: _OrganizerShiftPage,
    form: ShiftDemandForm | None = None,
    action_error: str = "",
) -> dict[str, object]:
    context = _baseline_context(request, actor=actor, page=page)
    context.update(
        {
            "demand_form": form or _demand_form(page=page),
            "action_error": action_error,
        }
    )
    return context


def _demand_item(
    *, page: _OrganizerShiftPage, demand_id: UUID
) -> OrganizerShiftDemandItem:
    for item in page.overview.demands:
        if item.demand.id == demand_id:
            return item
    raise Http404


def _organizer_detail_context(
    request: HttpRequest,
    *,
    actor: Account,
    page: _OrganizerShiftPage,
    item: OrganizerShiftDemandItem,
    edit_form: ShiftDemandForm | None = None,
    action_error: str = "",
    active_action: str = "",
) -> dict[str, object]:
    demand = item.demand
    context = _baseline_context(request, actor=actor, page=page)
    rows = tuple(
        _CommitmentActionRow(
            item=row,
            confirm_form=ShiftCommitmentReasonForm(
                expected_version=row.commitment.command_version,
                action_code=f"confirm_{row.commitment.id}",
            ),
            remove_form=ShiftCommitmentReasonForm(
                expected_version=row.commitment.command_version,
                action_code=f"remove_{row.commitment.id}",
            ),
        )
        for row in item.commitments
    )
    context.update(
        {
            "shift_item": item,
            "demand": demand,
            "commitment_rows": rows,
            "edit_form": edit_form or _demand_form(page=page, demand=demand),
            "open_form": ShiftReasonCommandForm(
                expected_version=demand.command_version,
                action_code="open",
            ),
            "lock_form": ShiftLockForm(
                expected_version=demand.command_version,
                action_code="lock",
            ),
            "reopen_form": ShiftReasonCommandForm(
                expected_version=demand.command_version,
                action_code="reopen",
            ),
            "complete_form": ShiftReasonCommandForm(
                expected_version=demand.command_version,
                action_code="complete",
            ),
            "cancel_form": ShiftReasonCommandForm(
                expected_version=demand.command_version,
                action_code="cancel",
            ),
            "demand_history": demand.command_receipts.select_related("actor").order_by(
                "-resulting_version", "-id"
            ),
            "shift_has_ended": timezone_now() >= demand.ends_at,
            "action_error": action_error,
            "active_action": active_action,
        }
    )
    return context


def _organizer_failure(request: HttpRequest) -> TemplateResponse:
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Shift planning unavailable",
            "has_permission": True,
            "message": "Shift planning is temporarily unavailable. Try again shortly.",
        }
    )
    return TemplateResponse(
        request,
        "workforce/shift_state.html",
        context,
        status=503,
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_workforce_shifts(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render unified exact-edition Shift demand and coverage.

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
        Audited planning page or bounded safe failure response.

    Raises
    ------
    PermissionDenied
        If the authenticated account lacks exact Shift read authority.
    """
    actor = _active_account(request)
    if request.GET:
        return TemplateResponse(
            request,
            "workforce/shift_state.html",
            {"message": "This page does not accept URL parameters."},
            status=400,
        )
    try:
        page = _load_organizer_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        context = _organizer_list_context(request, actor=actor, page=page)
    except PermissionDenied:
        raise
    except (
        DatabaseError,
        RuntimeError,
        ValidationError,
        ShiftReadLimitExceededError,
        ShiftProjectionIntegrityError,
    ):
        logger.exception("Unable to load organizer Shift planning")
        return _organizer_failure(request)
    return TemplateResponse(request, "workforce/shift_management.html", context)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def organization_workforce_shift(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    demand_id: UUID,
) -> HttpResponse:
    """Render one Shift demand, coverage, actions, and reason history.

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
    demand_id : UUID
        Exact Shift demand identifier.

    Returns
    -------
    HttpResponse
        Audited detail page or bounded safe failure response.

    Raises
    ------
    Http404
        If the authorized complete projection does not contain the demand.
    PermissionDenied
        If the authenticated account lacks exact Shift read authority.
    """
    actor = _active_account(request)
    if request.GET:
        return TemplateResponse(
            request,
            "workforce/shift_state.html",
            {"message": "This page does not accept URL parameters."},
            status=400,
        )
    try:
        page = _load_organizer_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        item = _demand_item(page=page, demand_id=demand_id)
        context = _organizer_detail_context(
            request,
            actor=actor,
            page=page,
            item=item,
        )
    except PermissionDenied:
        raise
    except Http404:
        raise
    except (
        DatabaseError,
        RuntimeError,
        ValidationError,
        ShiftReadLimitExceededError,
        ShiftProjectionIntegrityError,
    ):
        logger.exception("Unable to load organizer Shift detail")
        return _organizer_failure(request)
    return TemplateResponse(request, "workforce/shift_detail.html", context)


def _organizer_route_page_before_parse(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> tuple[Organization, ConventionSeries, EventEdition]:
    organization, series, edition = authorized_admin_edition_for_route(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        capability_code="workforce.manage_shifts",
    )
    authorize_shift_organizer_command(
        actor=actor,
        organization_id=organization.id,
        edition_id=edition.id,
    )
    return organization, series, edition


@never_cache
@login_required(login_url="staff-login")
@require_POST
def create_organization_workforce_shift(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Create a draft Shift through the shared command boundary.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.

    Returns
    -------
    HttpResponse
        Validation state, safe failure, or redirect to the created Shift.

    Raises
    ------
    PermissionDenied
        If the authenticated account lacks exact Shift management authority.
    """
    actor = _active_account(request)
    try:
        organization, series, edition = _organizer_route_page_before_parse(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        page = _load_organizer_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (DatabaseError, RuntimeError, ValidationError):
        logger.exception("Unable to authorize Shift creation")
        return _organizer_failure(request)
    form = _demand_form(page=page, data=request.POST)
    if request.GET or not form.is_valid():
        return TemplateResponse(
            request,
            "workforce/shift_management.html",
            _organizer_list_context(
                request,
                actor=actor,
                page=page,
                form=form,
                action_error="Review the highlighted Shift. Nothing was created.",
            ),
            status=400,
        )
    try:
        result = create_shift_demand(
            actor=actor,
            organization_id=organization.id,
            series_id=series.id,
            edition_id=edition.id,
            position_id=cast("UUID", form.cleaned_data["position_id"]),
            title=str(form.cleaned_data["title"]),
            location_label=str(form.cleaned_data["location_label"]),
            briefing=str(form.cleaned_data["briefing"]),
            supervision_note=str(form.cleaned_data["supervision_note"]),
            starts_at=cast("datetime", form.cleaned_data["starts_at"]),
            ends_at=cast("datetime", form.cleaned_data["ends_at"]),
            required_headcount=int(form.cleaned_data["required_headcount"]),
            break_minutes=int(form.cleaned_data["break_minutes"]),
            minimum_rest_minutes=int(form.cleaned_data["minimum_rest_minutes"]),
            reason=str(form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (ValidationError, ShiftCommandError) as error:
        form.add_error(None, _shift_conflict_message(error))
        return TemplateResponse(
            request,
            "workforce/shift_management.html",
            _organizer_list_context(
                request,
                actor=actor,
                page=page,
                form=form,
                action_error="The Shift was not created.",
            ),
            status=409 if isinstance(error, ShiftCommandError) else 400,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to create Shift demand")
        return _organizer_failure(request)
    messages.success(request, "Draft Shift created. Review it before opening claims.")
    return redirect(
        "organization-workforce-shift",
        organization_slug=organization.slug,
        series_slug=series.slug,
        edition_slug=edition.slug,
        demand_id=result.demand_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_organization_workforce_shift(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    demand_id: UUID,
) -> HttpResponse:
    """Replace editable fields on one unpublished Shift draft.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    organization_slug : str
        Organization locator from the route.
    series_slug : str
        Convention-series locator from the route.
    edition_slug : str
        Exact event-edition locator from the route.
    demand_id : UUID
        Draft Shift demand identifier.

    Returns
    -------
    HttpResponse
        Validation state, safe failure, or redirect to the updated Shift.

    Raises
    ------
    PermissionDenied
        If the authenticated account lacks exact Shift management authority.
    """
    actor = _active_account(request)
    try:
        organization, series, edition = _organizer_route_page_before_parse(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        page = _load_organizer_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        item = _demand_item(page=page, demand_id=demand_id)
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    form = _demand_form(page=page, data=request.POST, demand=item.demand)
    if request.GET or not form.is_valid():
        return TemplateResponse(
            request,
            "workforce/shift_detail.html",
            _organizer_detail_context(
                request,
                actor=actor,
                page=page,
                item=item,
                edit_form=form,
                action_error="Review the highlighted values. Nothing changed.",
                active_action="edit",
            ),
            status=400,
        )
    try:
        update_shift_demand(
            actor=actor,
            organization_id=organization.id,
            series_id=series.id,
            edition_id=edition.id,
            demand_id=demand_id,
            expected_version=int(form.cleaned_data["expected_version"]),
            title=str(form.cleaned_data["title"]),
            location_label=str(form.cleaned_data["location_label"]),
            briefing=str(form.cleaned_data["briefing"]),
            supervision_note=str(form.cleaned_data["supervision_note"]),
            starts_at=cast("datetime", form.cleaned_data["starts_at"]),
            ends_at=cast("datetime", form.cleaned_data["ends_at"]),
            required_headcount=int(form.cleaned_data["required_headcount"]),
            break_minutes=int(form.cleaned_data["break_minutes"]),
            minimum_rest_minutes=int(form.cleaned_data["minimum_rest_minutes"]),
            reason=str(form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (ValidationError, ShiftCommandError) as error:
        form.add_error(None, _shift_conflict_message(error))
        return TemplateResponse(
            request,
            "workforce/shift_detail.html",
            _organizer_detail_context(
                request,
                actor=actor,
                page=page,
                item=item,
                edit_form=form,
                action_error="The draft was not changed.",
                active_action="edit",
            ),
            status=409 if isinstance(error, ShiftCommandError) else 400,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to update Shift demand")
        return _organizer_failure(request)
    messages.success(request, "Draft Shift updated.")
    return redirect(
        "organization-workforce-shift",
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        demand_id=demand_id,
    )


def _shift_conflict_message(error: Exception) -> str:  # noqa: PLR0911
    if isinstance(error, ShiftVersionConflictError):
        return "This Shift changed. Reload it before trying again."
    if isinstance(error, ShiftRetryConflictError):
        return "This retry key belongs to a different Shift action. Reload first."
    if isinstance(error, ShiftAvailabilityConflictError):
        return "Current shared Availability no longer covers the complete Shift."
    if isinstance(error, ShiftQualificationConflictError):
        return "The person no longer has an active matching Position assignment."
    if isinstance(error, ShiftCapacityConflictError):
        return str(error) or "The requested Shift coverage is unavailable."
    if isinstance(error, ShiftOverlapConflictError):
        return "This work would overlap another Shift or its required rest."
    if isinstance(error, ShiftLifecycleConflictError):
        return "This edition is read-only for that Shift action."
    if isinstance(error, (ShiftStateConflictError, ShiftUnavailableError)):
        return str(error) or "The Shift is no longer in a compatible state."
    return "Review the submitted Shift action."


_DemandCommand = Callable[..., object]


def _run_demand_action(
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    demand_id: UUID,
    action_name: str,
    command: _DemandCommand,
    lock_action: bool = False,
) -> HttpResponse:
    actor = _active_account(request)
    try:
        organization, series, edition = _organizer_route_page_before_parse(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    form: ShiftReasonCommandForm = (
        ShiftLockForm(
            request.POST,
            expected_version=1,
            action_code=action_name,
        )
        if lock_action
        else ShiftReasonCommandForm(
            request.POST,
            expected_version=1,
            action_code=action_name,
        )
    )
    if request.GET or not form.is_valid():
        messages.error(
            request,
            "The Shift action was incomplete. Reload and try again.",
        )
        return redirect(
            "organization-workforce-shift",
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            demand_id=demand_id,
        )
    kwargs: dict[str, object] = {
        "actor": actor,
        "organization_id": organization.id,
        "series_id": series.id,
        "edition_id": edition.id,
        "demand_id": demand_id,
        "expected_version": int(form.cleaned_data["expected_version"]),
        "reason": str(form.cleaned_data["reason"]),
        "retry_key": cast("UUID", form.cleaned_data["retry_key"]),
        "correlation_id": UUID(request.correlation_id),  # type: ignore[attr-defined]
        "request_id": UUID(request.correlation_id),  # type: ignore[attr-defined]
        "source_channel": "web",
    }
    if lock_action:
        kwargs["allow_understaffed"] = bool(
            form.cleaned_data.get("allow_understaffed", False)
        )
    try:
        command(**kwargs)
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (ValidationError, ShiftCommandError) as error:
        messages.error(request, _shift_conflict_message(error))
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to perform Shift demand action %s", action_name)
        messages.error(request, "The Shift was not changed. Try again shortly.")
    else:
        messages.success(request, f"Shift {action_name}.")
    return redirect(
        "organization-workforce-shift",
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        demand_id=demand_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def open_organization_workforce_shift(
    request: HttpRequest, **kwargs: object
) -> HttpResponse:
    """Publish a draft Shift from the organizer surface.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    **kwargs : object
        Exact route locators forwarded to the shared action adapter.

    Returns
    -------
    HttpResponse
        Redirect to the demand detail with an action-local message.
    """
    return _run_demand_action(
        request,
        action_name="opened for claims",
        command=open_shift_demand,
        **kwargs,  # type: ignore[arg-type]
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def lock_organization_workforce_shift(
    request: HttpRequest, **kwargs: object
) -> HttpResponse:
    """Lock confirmed Shift coverage from the organizer surface.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    **kwargs : object
        Exact route locators forwarded to the shared action adapter.

    Returns
    -------
    HttpResponse
        Redirect to the demand detail with an action-local message.
    """
    return _run_demand_action(
        request,
        action_name="coverage locked",
        command=lock_shift_demand,
        lock_action=True,
        **kwargs,  # type: ignore[arg-type]
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def reopen_organization_workforce_shift(
    request: HttpRequest, **kwargs: object
) -> HttpResponse:
    """Reopen locked Shift coverage from the organizer surface.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    **kwargs : object
        Exact route locators forwarded to the shared action adapter.

    Returns
    -------
    HttpResponse
        Redirect to the demand detail with an action-local message.
    """
    return _run_demand_action(
        request,
        action_name="reopened",
        command=reopen_shift_demand,
        **kwargs,  # type: ignore[arg-type]
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def complete_organization_workforce_shift(
    request: HttpRequest, **kwargs: object
) -> HttpResponse:
    """Complete ended Shift coverage from the organizer surface.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    **kwargs : object
        Exact route locators forwarded to the shared action adapter.

    Returns
    -------
    HttpResponse
        Redirect to the demand detail with an action-local message.
    """
    return _run_demand_action(
        request,
        action_name="completed",
        command=complete_shift_demand,
        **kwargs,  # type: ignore[arg-type]
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def cancel_organization_workforce_shift(
    request: HttpRequest, **kwargs: object
) -> HttpResponse:
    """Cancel unfinished Shift demand from the organizer surface.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    **kwargs : object
        Exact route locators forwarded to the shared action adapter.

    Returns
    -------
    HttpResponse
        Redirect to the demand detail with an action-local message.
    """
    return _run_demand_action(
        request,
        action_name="cancelled",
        command=cancel_shift_demand,
        **kwargs,  # type: ignore[arg-type]
    )


def _run_commitment_action(
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    demand_id: UUID,
    commitment_id: UUID,
    action_name: str,
    command: Callable[..., object],
) -> HttpResponse:
    actor = _active_account(request)
    try:
        organization, series, edition = _organizer_route_page_before_parse(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    form = ShiftCommitmentReasonForm(
        request.POST,
        expected_version=1,
        action_code=action_name,
    )
    if request.GET or not form.is_valid():
        messages.error(request, "The coverage action was incomplete. Reload and retry.")
    else:
        try:
            command(
                actor=actor,
                organization_id=organization.id,
                series_id=series.id,
                edition_id=edition.id,
                commitment_id=commitment_id,
                expected_version=int(form.cleaned_data["expected_version"]),
                reason=str(form.cleaned_data["reason"]),
                retry_key=cast("UUID", form.cleaned_data["retry_key"]),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="web",
            )
        except ShiftAuthorizationDeniedError as error:
            raise PermissionDenied from error
        except (ValidationError, ShiftCommandError) as error:
            messages.error(request, _shift_conflict_message(error))
        except (DatabaseError, RuntimeError):
            logger.exception("Unable to perform commitment action %s", action_name)
            messages.error(request, "Coverage was not changed. Try again shortly.")
        else:
            messages.success(request, f"Shift claim {action_name}.")
    return redirect(
        "organization-workforce-shift",
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        demand_id=demand_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def confirm_organization_workforce_shift_commitment(
    request: HttpRequest, **kwargs: object
) -> HttpResponse:
    """Confirm one claimed Shift from the organizer surface.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    **kwargs : object
        Exact demand and commitment route locators forwarded to the adapter.

    Returns
    -------
    HttpResponse
        Redirect to the demand detail with an action-local message.
    """
    return _run_commitment_action(
        request,
        action_name="confirmed",
        command=confirm_shift_commitment,
        **kwargs,  # type: ignore[arg-type]
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def remove_organization_workforce_shift_commitment(
    request: HttpRequest, **kwargs: object
) -> HttpResponse:
    """Remove one active Shift commitment from the organizer surface.

    Parameters
    ----------
    request : HttpRequest
        Incoming organizer form submission.
    **kwargs : object
        Exact demand and commitment route locators forwarded to the adapter.

    Returns
    -------
    HttpResponse
        Redirect to the demand detail with an action-local message.
    """
    return _run_commitment_action(
        request,
        action_name="removed",
        command=remove_shift_commitment,
        **kwargs,  # type: ignore[arg-type]
    )


def _personal_route(
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> tuple[Organization, ConventionSeries, EventEdition]:
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(
            slug=edition_slug,
            organization__slug=organization_slug,
            series__slug=series_slug,
            series__organization_id=models.F("organization_id"),
        )
        .order_by()
        .first()
    )
    if edition is None:
        raise PermissionDenied
    target = resolve_self_target(
        principal=actor,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    decision = decide(
        principal=actor,
        capability_code="workforce.view_self",
        resource=target,
        requested_fields=frozenset({"shifts"}),
    )
    if not decision.allowed or decision.fields != frozenset({"shifts"}):
        raise PermissionDenied
    if not person_has_shift_relationship(
        account=actor,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    ):
        raise PermissionDenied
    return edition.organization, edition.series, edition


def _personal_context(
    request: HttpRequest,
    *,
    organization: Organization,
    series: ConventionSeries,
    edition: EventEdition,
    overview: MyShiftOverview,
    action_error: str = "",
    bound_claim: tuple[UUID, ShiftClaimForm] | None = None,
    bound_withdraw: tuple[UUID, ShiftWithdrawForm] | None = None,
) -> dict[str, object]:
    suitable_rows = tuple(
        _PersonalSuitableRow(
            item=item,
            claim_form=(
                bound_claim[1]
                if bound_claim is not None and bound_claim[0] == item.demand.id
                else ShiftClaimForm(
                    expected_version=item.demand.command_version,
                    action_code=f"claim_{item.demand.id}",
                )
            ),
        )
        for item in overview.suitable
    )
    commitment_rows = tuple(
        _PersonalCommitmentRow(
            item=item,
            withdraw_form=(
                bound_withdraw[1]
                if bound_withdraw is not None
                and bound_withdraw[0] == item.commitment.id
                else ShiftWithdrawForm(
                    expected_version=item.commitment.command_version,
                    action_code=f"withdraw_{item.commitment.id}",
                )
            ),
        )
        for item in overview.commitments
    )
    context = admin.site.each_context(request)
    context.update(
        {
            "title": f"My shifts — {edition.name}",
            "has_permission": True,
            "maru_personal_surface": True,
            "organization": organization,
            "convention_series": series,
            "edition": edition,
            "suitable_rows": suitable_rows,
            "commitment_rows": commitment_rows,
            "action_error": action_error,
        }
    )
    return context


def _load_personal(
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> tuple[Organization, ConventionSeries, EventEdition, MyShiftOverview]:
    organization, series, edition = _personal_route(
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    return (
        organization,
        series,
        edition,
        load_my_shift_overview(account=actor, edition=edition),
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def my_workforce_shifts(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render suitable open work and retained commitments for one person.

    Parameters
    ----------
    request : HttpRequest
        Incoming authenticated personal request.
    organization_slug : str
        Related organization locator from the route.
    series_slug : str
        Related convention-series locator from the route.
    edition_slug : str
        Exact related event-edition locator from the route.

    Returns
    -------
    HttpResponse
        Private personal Shift page or bounded safe failure response.

    Raises
    ------
    PermissionDenied
        If the account lacks the exact person-owned Workforce relationship.
    """
    actor = _active_account(request)
    if request.GET:
        return TemplateResponse(
            request,
            "workforce/shift_state.html",
            {"message": "This page does not accept URL parameters."},
            status=400,
        )
    try:
        organization, series, edition, overview = _load_personal(
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except PermissionDenied:
        raise
    except (DatabaseError, RuntimeError, ShiftReadLimitExceededError):
        logger.exception("Unable to load My shifts")
        return TemplateResponse(
            request,
            "workforce/shift_state.html",
            {"message": "Your Shifts are temporarily unavailable."},
            status=503,
        )
    return TemplateResponse(
        request,
        "workforce/my_shifts.html",
        _personal_context(
            request,
            organization=organization,
            series=series,
            edition=edition,
            overview=overview,
        ),
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def claim_my_workforce_shift(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    demand_id: UUID,
) -> HttpResponse:
    """Claim one suitable Shift from the person-owned surface.

    Parameters
    ----------
    request : HttpRequest
        Incoming personal claim submission.
    organization_slug : str
        Related organization locator from the route.
    series_slug : str
        Related convention-series locator from the route.
    edition_slug : str
        Exact related event-edition locator from the route.
    demand_id : UUID
        Suitable open demand identifier.

    Returns
    -------
    HttpResponse
        Validation state or redirect to the refreshed personal Shift page.

    Raises
    ------
    PermissionDenied
        If the account lacks the exact person-owned Shift boundary.
    """
    actor = _active_account(request)
    try:
        organization, series, edition, overview = _load_personal(
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        authorize_shift_self_command(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    form = ShiftClaimForm(request.POST, expected_version=1)
    if request.GET or not form.is_valid():
        return TemplateResponse(
            request,
            "workforce/my_shifts.html",
            _personal_context(
                request,
                organization=organization,
                series=series,
                edition=edition,
                overview=overview,
                action_error="Reload this Shift before claiming it.",
                bound_claim=(demand_id, form),
            ),
            status=400,
        )
    try:
        claim_shift(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
            demand_id=demand_id,
            expected_version=int(form.cleaned_data["expected_version"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (ValidationError, ShiftCommandError) as error:
        form.add_error(None, _shift_conflict_message(error))
        return TemplateResponse(
            request,
            "workforce/my_shifts.html",
            _personal_context(
                request,
                organization=organization,
                series=series,
                edition=edition,
                overview=overview,
                action_error="This Shift was not claimed.",
                bound_claim=(demand_id, form),
            ),
            status=409 if isinstance(error, ShiftCommandError) else 400,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to claim Shift")
        messages.error(request, "The Shift was not claimed. Try again shortly.")
    else:
        messages.success(
            request,
            "Shift claimed. An organizer still needs to confirm the commitment.",
        )
    return redirect(
        "my-workforce-shifts",
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def withdraw_my_workforce_shift(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    commitment_id: UUID,
) -> HttpResponse:
    """Withdraw one owned open commitment after explicit confirmation.

    Parameters
    ----------
    request : HttpRequest
        Incoming personal withdrawal submission.
    organization_slug : str
        Related organization locator from the route.
    series_slug : str
        Related convention-series locator from the route.
    edition_slug : str
        Exact related event-edition locator from the route.
    commitment_id : UUID
        Person-owned active commitment identifier.

    Returns
    -------
    HttpResponse
        Validation state or redirect to the refreshed personal Shift page.

    Raises
    ------
    PermissionDenied
        If the account lacks the exact person-owned Shift boundary.
    """
    actor = _active_account(request)
    try:
        organization, series, edition, overview = _load_personal(
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        authorize_shift_self_command(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    form = ShiftWithdrawForm(
        request.POST,
        expected_version=1,
        action_code=f"withdraw_{commitment_id}",
    )
    if request.GET or not form.is_valid():
        return TemplateResponse(
            request,
            "workforce/my_shifts.html",
            _personal_context(
                request,
                organization=organization,
                series=series,
                edition=edition,
                overview=overview,
                action_error="Confirm the withdrawal. Nothing changed.",
                bound_withdraw=(commitment_id, form),
            ),
            status=400,
        )
    try:
        withdraw_shift_claim(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
            commitment_id=commitment_id,
            expected_version=int(form.cleaned_data["expected_version"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            source_channel="web",
        )
    except ShiftAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (ValidationError, ShiftCommandError) as error:
        form.add_error(None, _shift_conflict_message(error))
        return TemplateResponse(
            request,
            "workforce/my_shifts.html",
            _personal_context(
                request,
                organization=organization,
                series=series,
                edition=edition,
                overview=overview,
                action_error="The commitment was not withdrawn.",
                bound_withdraw=(commitment_id, form),
            ),
            status=409 if isinstance(error, ShiftCommandError) else 400,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to withdraw Shift")
        messages.error(request, "The commitment was not withdrawn. Try again shortly.")
    else:
        messages.success(request, "Your Shift commitment was withdrawn.")
    return redirect(
        "my-workforce-shifts",
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
