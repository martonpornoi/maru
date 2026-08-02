"""Reference volunteer opportunity and private document views."""

from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.utils.timezone import now as timezone_now
from django.views.decorators.http import require_GET

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
from maru.organizations.queries import executive_board_governance_anchor
from maru.workforce.forms import (
    OnboardingDocumentUploadForm,
    VolunteerApplicationForm,
)
from maru.workforce.models import (
    OnboardingDocumentRequest,
    VolunteerApplication,
    VolunteerOpportunity,
)
from maru.workforce.queries import (
    WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
    project_edition_structure,
)
from maru.workforce.services import (
    submit_volunteer_application,
    upload_onboarding_document,
)
from maru.workforce.structure_audit import append_structure_read_audit

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
            "baseline_hide_admin_scoped_navigation": True,
            "structure_load_failed": True,
        }
    )
    return TemplateResponse(
        request,
        "workforce/organization_structure.html",
        context,
        status=503,
    )


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
    evaluated_at = timezone_now()
    try:
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
        require_complete_projection(
            required_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
            permitted_fields=view_decision.fields,
        )
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
        governance = executive_board_governance_anchor(
            organization_id=organization.id,
        )
        structure = project_edition_structure(
            organization_id=organization.id,
            edition_id=edition.id,
            at=evaluated_at,
        )
        # Keep the hierarchy internally coherent at ``evaluated_at`` while a
        # fresh final decision prevents mid-request expiry or revocation from
        # releasing the completed name-bearing response.
        response_authorized_at = timezone_now()
        view_decision = decide(
            principal=actor,
            capability_code="workforce.view_structure",
            resource=edition_target,
            requested_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
            at=response_authorized_at,
        )
        if not view_decision.allowed:
            raise PermissionDenied
        require_complete_projection(
            required_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
            permitted_fields=view_decision.fields,
        )
        append_structure_read_audit(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
            decision=view_decision,
            correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
            route_name="organization-structure",
            source_channel="web",
            occurred_at=response_authorized_at,
        )
    except (
        DatabaseError,
        RuntimeError,
        ValidationError,
        FieldProjectionDeniedError,
    ):
        logger.exception("Unable to load the edition organization structure")
        return _organization_structure_dependency_failure(request)

    context = admin.site.each_context(request)
    context.update(
        {
            "title": f"Organization structure — {edition.name}",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "organization-structure",
            "baseline_page_class": "",
            "baseline_can_view_organization": can_view_organization,
            "baseline_can_manage_representation": can_manage_representation,
            "baseline_can_create_series": can_create_series,
            "baseline_can_create_edition": can_create_edition,
            "baseline_can_view_edition": can_view_edition,
            "baseline_can_view_structure": True,
            "baseline_can_manage_structure": manage_decision.allowed,
            "organization": organization,
            "convention_series": series,
            "edition": edition,
            "governance": governance,
            "structure": structure,
            "structure_load_failed": False,
            "structure_access_label": _structure_access_label(view_decision),
            "can_manage_structure": manage_decision.allowed,
        }
    )
    return TemplateResponse(
        request,
        "workforce/organization_structure.html",
        context,
    )


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
        .order_by("position__department__position", "position__title", "id")
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
