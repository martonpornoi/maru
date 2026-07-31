"""Reference volunteer opportunity and private document views."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import ResourceScope, decide
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.forms import (
    OnboardingDocumentUploadForm,
    VolunteerApplicationForm,
)
from maru.workforce.models import (
    OnboardingDocumentRequest,
    VolunteerApplication,
    VolunteerOpportunity,
)
from maru.workforce.services import (
    submit_volunteer_application,
    upload_onboarding_document,
)


def _account(request: HttpRequest) -> Account | None:
    return request.user if isinstance(request.user, Account) else None


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
        resource=ResourceScope(
            organization_id=document_request.organization_id,
            edition_id=document_request.edition_id,
            owner_account_id=document_request.account_id,
        ),
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
