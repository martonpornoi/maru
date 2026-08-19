"""Minimal same-shell charity management and private review pages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from functools import partial
from typing import Any, cast
from uuid import UUID

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.db.models import F, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.models import Department

from .authorization import resolve_charity_selection_target
from .forms import (
    CharityMediaAddForm,
    CharityMediaReviewForm,
    CharityPartnerCreateForm,
    CharityPartnerUpdateForm,
    CharitySelectionCommentForm,
    CharitySelectionDecisionForm,
    CharitySelectionProposeForm,
    CharitySelectionPublishForm,
)
from .models import CharityPartner, CharityPartnerMedia, CharitySelection
from .queries import (
    list_charity_partners,
    list_charity_selection_queue,
    load_charity_selection_review,
)
from .services import (
    PARTNER_MANAGE_CAPABILITY,
    SELECTION_COMMENT_CAPABILITY,
    SELECTION_PROPOSE_CAPABILITY,
    SELECTION_PUBLISH_CAPABILITY,
    SELECTION_REVIEW_CAPABILITY,
    CharityAuthorizationDeniedError,
    CharityCommandError,
    CharityIndependentApprovalError,
    CharityPartnerProfile,
    CharityResourceUnavailableError,
    CharityRetryConflictError,
    CharityStateConflictError,
    CharityVersionConflictError,
    add_charity_partner_media,
    add_charity_selection_private_comment,
    approve_charity_partner_media,
    confirm_charity_selection,
    create_charity_partner,
    propose_charity_selection,
    publish_charity_selection,
    reject_charity_selection,
    submit_charity_selection,
    update_charity_partner,
    withdraw_charity_partner_media,
    withdraw_charity_selection_publication,
)


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise PermissionDenied("The charity workspace is unavailable.")
    return request.user


def _edition_route(
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> EventEdition:
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(
            organization__slug=organization_slug,
            series__slug=series_slug,
            slug=edition_slug,
            series__organization_id=F("organization_id"),
        )
        .first()
    )
    if edition is None:
        raise Http404
    return edition


_PARTNER_PROFILE_FIELDS = (
    "legal_name",
    "imprint_name",
    "public_name",
    "short_description",
    "description",
    "location_name",
    "postal_address",
    "country_code",
    "website_url",
    "contact_email",
    "contact_phone",
)


def _page_context(request: HttpRequest, edition: EventEdition) -> dict[str, object]:
    context = admin.site.each_context(request)
    context.update(
        {
            "organization": edition.organization,
            "convention_series": edition.series,
            "edition": edition,
            "maru_personal_surface": False,
        }
    )
    return context


def _correlation_id(request: HttpRequest) -> UUID:
    return UUID(str(request.correlation_id))  # type: ignore[attr-defined]


def _allowed(
    *,
    actor: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget | None,
) -> bool:
    return decide(
        principal=actor,
        capability_code=capability_code,
        resource=target,
    ).allowed


def _require_capability(
    *,
    actor: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget | None,
) -> None:
    if not _allowed(actor=actor, capability_code=capability_code, target=target):
        raise PermissionDenied("The charity operation is unavailable.")


def _workspace_location(edition: EventEdition) -> tuple[str, tuple[Any, ...]]:
    return "charity-workspace", (
        edition.organization.slug,
        edition.series.slug,
        edition.slug,
    )


def _review_location(
    edition: EventEdition, selection_id: UUID
) -> tuple[str, tuple[Any, ...]]:
    return "charity-selection-review-page", (
        edition.organization.slug,
        edition.series.slug,
        edition.slug,
        selection_id,
    )


def _redirect_location(location: tuple[str, tuple[Any, ...]]) -> HttpResponse:
    name, args = location
    return redirect(name, *args)


def _execute_command(
    request: HttpRequest,
    *,
    command: Callable[[], object],
    success_message: str,
    location: tuple[str, tuple[Any, ...]],
) -> HttpResponse:
    try:
        command()
    except CharityAuthorizationDeniedError as error:
        raise PermissionDenied("The charity operation is unavailable.") from error
    except CharityResourceUnavailableError as error:
        raise Http404 from error
    except CharityVersionConflictError:
        messages.error(request, "This record changed. Reload before trying again.")
    except CharityRetryConflictError:
        messages.error(request, "That retry key was already used for another command.")
    except CharityIndependentApprovalError:
        messages.error(
            request,
            "A different authorized person must perform this approval.",
        )
    except CharityStateConflictError:
        messages.error(request, "That action is not available in the current state.")
    except (ValidationError, CharityCommandError):
        messages.error(request, "Review the submitted fields; nothing was changed.")
    except DatabaseError:
        return HttpResponse("Charity records are temporarily unavailable.", status=503)
    else:
        messages.success(request, success_message)
    return _redirect_location(location)


def _invalid_form(
    request: HttpRequest, location: tuple[str, tuple[Any, ...]]
) -> HttpResponse:
    messages.error(request, "Review the submitted fields; nothing was changed.")
    return _redirect_location(location)


def _partner_queryset(edition: EventEdition) -> QuerySet[CharityPartner]:
    return CharityPartner.objects.filter(
        organization_id=edition.organization_id,
        lifecycle__in=(CharityPartner.Lifecycle.DRAFT, CharityPartner.Lifecycle.ACTIVE),
    ).order_by("public_name", "id")


def _department_queryset(edition: EventEdition) -> QuerySet[Department]:
    return Department.objects.filter(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        retired_at__isnull=True,
    ).order_by("display_order", "name", "id")


def _publishable_media_queryset(
    *,
    edition: EventEdition,
    partner_id: UUID,
) -> QuerySet[CharityPartnerMedia]:
    return (
        CharityPartnerMedia.objects.filter(
            organization_id=edition.organization_id,
            partner_id=partner_id,
            review_status=CharityPartnerMedia.ReviewStatus.APPROVED,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .exclude(public_reference="")
        .order_by("kind", "id")
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def charity_workspace(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    if request.GET:
        return HttpResponse("Unsupported query parameters.", status=400)
    try:
        actor = _actor(request)
        edition = _edition_route(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        partners = list_charity_partners(
            actor=actor,
            organization_id=edition.organization_id,
            reason="charity_partner_workspace",
            source_channel="browser",
        )
        selections = list_charity_selection_queue(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    except CharityAuthorizationDeniedError as error:
        raise PermissionDenied("The charity workspace is unavailable.") from error
    except DatabaseError:
        return HttpResponse("Charity records are temporarily unavailable.", status=503)
    organization_target = resolve_organization_target(
        organization_id=edition.organization_id
    )
    edition_target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    can_manage_partners = _allowed(
        actor=actor,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        target=organization_target,
    )
    can_propose = _allowed(
        actor=actor,
        capability_code=SELECTION_PROPOSE_CAPABILITY,
        target=edition_target,
    )
    partner_rows: list[dict[str, object]] = []
    for partner in partners:
        partner_values = asdict(partner)
        media_values = cast(tuple[dict[str, object], ...], partner_values.pop("media"))
        initial = {
            field_name: partner_values[field_name]
            for field_name in ("slug", *_PARTNER_PROFILE_FIELDS, "lifecycle")
        }
        initial["expected_version"] = partner.aggregate_version
        media_rows = tuple(
            {
                "media": media,
                "review_form": CharityMediaReviewForm(
                    initial={
                        "expected_version": media["aggregate_version"],
                        "public_reference": media["public_reference"],
                    },
                    auto_id=f"charity_media_{media['id']}_%s",
                ),
            }
            for media in media_values
        )
        partner_rows.append(
            {
                "partner": partner_values,
                "update_form": CharityPartnerUpdateForm(
                    initial=initial,
                    auto_id=f"charity_partner_{partner.id}_%s",
                ),
                "media_form": CharityMediaAddForm(
                    edition_time_zone=edition.time_zone,
                    auto_id=f"charity_media_add_{partner.id}_%s",
                ),
                "media_rows": media_rows,
            }
        )
    context = _page_context(request, edition)
    context.update(
        {
            "title": "Charity partners",
            "partner_rows": tuple(partner_rows),
            "selections": tuple(asdict(selection) for selection in selections),
            "can_manage_partners": can_manage_partners,
            "can_propose": can_propose,
            "partner_create_form": CharityPartnerCreateForm(
                auto_id="charity_partner_create_%s"
            ),
            "selection_propose_form": CharitySelectionProposeForm(
                partners=_partner_queryset(edition),
                departments=_department_queryset(edition),
                auto_id="charity_selection_propose_%s",
            ),
        }
    )
    return TemplateResponse(request, "charities/workspace.html", context)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def charity_selection_review_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    selection_id: UUID,
) -> HttpResponse:
    if request.GET:
        return HttpResponse("Unsupported query parameters.", status=400)
    try:
        actor = _actor(request)
        edition = _edition_route(
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        review = load_charity_selection_review(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            selection_id=selection_id,
            reason="charity_selection_review_page",
            source_channel="browser",
        )
    except CharityAuthorizationDeniedError as error:
        raise PermissionDenied("The charity review is unavailable.") from error
    except CharityResourceUnavailableError as error:
        raise Http404 from error
    except DatabaseError:
        return HttpResponse("Charity review is temporarily unavailable.", status=503)
    selection_target = resolve_charity_selection_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        selection_id=selection_id,
    )
    edition_target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    initial = {"expected_version": review.summary.aggregate_version}
    context = _page_context(request, edition)
    context.update(
        {
            "title": f"{review.summary.partner_name} — Charity review",
            "review": review,
            "can_submit": _allowed(
                actor=actor,
                capability_code=SELECTION_PROPOSE_CAPABILITY,
                target=edition_target,
            ),
            "can_review": _allowed(
                actor=actor,
                capability_code=SELECTION_REVIEW_CAPABILITY,
                target=selection_target,
            ),
            "can_comment": _allowed(
                actor=actor,
                capability_code=SELECTION_COMMENT_CAPABILITY,
                target=selection_target,
            ),
            "can_publish": _allowed(
                actor=actor,
                capability_code=SELECTION_PUBLISH_CAPABILITY,
                target=selection_target,
            ),
            "decision_form": CharitySelectionDecisionForm(
                initial=initial,
                auto_id="charity_selection_decision_%s",
            ),
            "comment_form": CharitySelectionCommentForm(
                initial=initial,
                auto_id="charity_selection_comment_%s",
            ),
            "publish_form": CharitySelectionPublishForm(
                initial=initial,
                media=_publishable_media_queryset(
                    edition=edition,
                    partner_id=review.summary.partner_id,
                ),
                auto_id="charity_selection_publish_%s",
            ),
        }
    )
    return TemplateResponse(request, "charities/selection_review.html", context)


def _command_edition(
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> EventEdition:
    return _edition_route(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def create_charity_partner_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    actor = _actor(request)
    edition = _command_edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    location = _workspace_location(edition)
    _require_capability(
        actor=actor,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        target=resolve_organization_target(organization_id=edition.organization_id),
    )
    form = CharityPartnerCreateForm(request.POST)
    if request.GET or not form.is_valid():
        return _invalid_form(request, location)
    profile = CharityPartnerProfile(
        **{
            field_name: str(form.cleaned_data[field_name])
            for field_name in _PARTNER_PROFILE_FIELDS
        }
    )
    return _execute_command(
        request,
        command=lambda: create_charity_partner(
            actor=actor,
            organization_id=edition.organization_id,
            slug=str(form.cleaned_data["slug"]),
            profile=profile,
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The charity partner was created as a draft.",
        location=location,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_charity_partner_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    partner_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _command_edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    location = _workspace_location(edition)
    _require_capability(
        actor=actor,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        target=resolve_organization_target(organization_id=edition.organization_id),
    )
    form = CharityPartnerUpdateForm(request.POST)
    if request.GET or not form.is_valid():
        return _invalid_form(request, location)
    changes = {
        field_name: str(form.cleaned_data[field_name])
        for field_name in ("slug", *_PARTNER_PROFILE_FIELDS, "lifecycle")
    }
    return _execute_command(
        request,
        command=lambda: update_charity_partner(
            actor=actor,
            organization_id=edition.organization_id,
            partner_id=partner_id,
            expected_version=cast(int, form.cleaned_data["expected_version"]),
            changes=changes,
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The charity partner profile was updated.",
        location=location,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def add_charity_media_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    partner_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    edition = _command_edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    location = _workspace_location(edition)
    _require_capability(
        actor=actor,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        target=resolve_organization_target(organization_id=edition.organization_id),
    )
    form = CharityMediaAddForm(
        request.POST,
        edition_time_zone=edition.time_zone,
    )
    if request.GET or not form.is_valid():
        return _invalid_form(request, location)
    return _execute_command(
        request,
        command=lambda: add_charity_partner_media(
            actor=actor,
            organization_id=edition.organization_id,
            partner_id=partner_id,
            kind=str(form.cleaned_data["kind"]),
            source_reference=str(form.cleaned_data["source_reference"]),
            owner_name=str(form.cleaned_data["owner_name"]),
            license_basis=str(form.cleaned_data["license_basis"]),
            usage_scope=str(form.cleaned_data["usage_scope"]),
            attribution=str(form.cleaned_data["attribution"]),
            expires_at=cast(datetime | None, form.cleaned_data["expires_at"]),
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The media reference was added for independent review.",
        location=location,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def review_charity_media_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    partner_id: UUID,
    media_id: UUID,
    action: str,
) -> HttpResponse:
    if action not in {"approve", "withdraw"}:
        raise Http404
    actor = _actor(request)
    edition = _command_edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    location = _workspace_location(edition)
    _require_capability(
        actor=actor,
        capability_code=PARTNER_MANAGE_CAPABILITY,
        target=resolve_organization_target(organization_id=edition.organization_id),
    )
    form = CharityMediaReviewForm(request.POST)
    if request.GET or not form.is_valid():
        return _invalid_form(request, location)
    expected_version = cast(int, form.cleaned_data["expected_version"])
    reason = str(form.cleaned_data["reason"])
    idempotency_key = cast(UUID, form.cleaned_data["idempotency_key"])
    correlation_id = _correlation_id(request)
    if action == "approve":
        command = partial(
            approve_charity_partner_media,
            actor=actor,
            organization_id=edition.organization_id,
            partner_id=partner_id,
            media_id=media_id,
            expected_version=expected_version,
            public_reference=str(form.cleaned_data["public_reference"]),
            reason=reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_channel="browser",
        )
        success_message = "The media reference was independently approved."
    else:
        command = partial(
            withdraw_charity_partner_media,
            actor=actor,
            organization_id=edition.organization_id,
            partner_id=partner_id,
            media_id=media_id,
            expected_version=expected_version,
            reason=reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_channel="browser",
        )
        success_message = "The media reference was withdrawn."
    return _execute_command(
        request,
        command=command,
        success_message=success_message,
        location=location,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def propose_charity_selection_page(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    actor = _actor(request)
    edition = _command_edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    location = _workspace_location(edition)
    _require_capability(
        actor=actor,
        capability_code=SELECTION_PROPOSE_CAPABILITY,
        target=resolve_edition_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    )
    form = CharitySelectionProposeForm(
        request.POST,
        partners=_partner_queryset(edition),
        departments=_department_queryset(edition),
    )
    if request.GET or not form.is_valid():
        return _invalid_form(request, location)
    partner = cast(CharityPartner, form.cleaned_data["partner_id"])
    department = cast(Department, form.cleaned_data["responsible_department_id"])
    return _execute_command(
        request,
        command=lambda: propose_charity_selection(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            partner_id=partner.id,
            responsible_department_id=department.id,
            reason=str(form.cleaned_data["reason"]),
            idempotency_key=cast(UUID, form.cleaned_data["idempotency_key"]),
            correlation_id=_correlation_id(request),
            source_channel="browser",
        ),
        success_message="The charity partner was proposed for this edition.",
        location=location,
    )


_SELECTION_COMMAND_CAPABILITIES = {
    "submit": SELECTION_PROPOSE_CAPABILITY,
    "confirm": SELECTION_REVIEW_CAPABILITY,
    "reject": SELECTION_REVIEW_CAPABILITY,
    "comment": SELECTION_COMMENT_CAPABILITY,
    "publish": SELECTION_PUBLISH_CAPABILITY,
    "withdraw": SELECTION_PUBLISH_CAPABILITY,
}


@never_cache
@login_required(login_url="staff-login")
@require_POST
def charity_selection_command_page(  # noqa: PLR0912
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    selection_id: UUID,
    action: str,
) -> HttpResponse:
    capability_code = _SELECTION_COMMAND_CAPABILITIES.get(action)
    if capability_code is None:
        raise Http404
    actor = _actor(request)
    edition = _command_edition(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    location = _review_location(edition, selection_id)
    if action == "submit":
        target = resolve_edition_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
    else:
        target = resolve_charity_selection_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            selection_id=selection_id,
        )
    _require_capability(
        actor=actor,
        capability_code=capability_code,
        target=target,
    )
    if action == "comment":
        comment_form = CharitySelectionCommentForm(request.POST)
        if request.GET or not comment_form.is_valid():
            return _invalid_form(request, location)
        return _execute_command(
            request,
            command=lambda: add_charity_selection_private_comment(
                actor=actor,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                selection_id=selection_id,
                expected_version=cast(
                    int, comment_form.cleaned_data["expected_version"]
                ),
                private_comment=str(comment_form.cleaned_data["private_comment"]),
                idempotency_key=cast(
                    UUID, comment_form.cleaned_data["idempotency_key"]
                ),
                correlation_id=_correlation_id(request),
                source_channel="browser",
            ),
            success_message="The private review comment was appended.",
            location=location,
        )
    if action == "publish":
        selection = CharitySelection.objects.filter(
            id=selection_id,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ).first()
        if selection is None:
            raise Http404
        publish_form = CharitySelectionPublishForm(
            request.POST,
            media=_publishable_media_queryset(
                edition=edition,
                partner_id=selection.partner_id,
            ),
        )
        if request.GET or not publish_form.is_valid():
            return _invalid_form(request, location)
        media = cast(
            QuerySet[CharityPartnerMedia],
            publish_form.cleaned_data["media_ids"],
        )
        return _execute_command(
            request,
            command=lambda: publish_charity_selection(
                actor=actor,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                selection_id=selection_id,
                expected_version=cast(
                    int, publish_form.cleaned_data["expected_version"]
                ),
                media_ids=tuple(item.id for item in media),
                reason=str(publish_form.cleaned_data["reason"]),
                idempotency_key=cast(
                    UUID, publish_form.cleaned_data["idempotency_key"]
                ),
                correlation_id=_correlation_id(request),
                source_channel="browser",
            ),
            success_message=(
                "The minimized charity profile was independently published."
            ),
            location=location,
        )
    decision_form = CharitySelectionDecisionForm(request.POST)
    if request.GET or not decision_form.is_valid():
        return _invalid_form(request, location)
    expected_version = cast(int, decision_form.cleaned_data["expected_version"])
    reason = str(decision_form.cleaned_data["reason"])
    idempotency_key = cast(UUID, decision_form.cleaned_data["idempotency_key"])
    correlation_id = _correlation_id(request)
    if action == "submit":
        command = partial(
            submit_charity_selection,
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            selection_id=selection_id,
            expected_version=expected_version,
            reason=reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_channel="browser",
        )
        success_message = "The charity selection was submitted for review."
    elif action == "confirm":
        command = partial(
            confirm_charity_selection,
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            selection_id=selection_id,
            expected_version=expected_version,
            reason=reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_channel="browser",
        )
        success_message = "The charity selection was independently confirmed."
    elif action == "reject":
        command = partial(
            reject_charity_selection,
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            selection_id=selection_id,
            expected_version=expected_version,
            reason=reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_channel="browser",
        )
        success_message = "The charity selection was rejected with a restricted reason."
    else:
        command = partial(
            withdraw_charity_selection_publication,
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            selection_id=selection_id,
            expected_version=expected_version,
            reason=reason,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_channel="browser",
        )
        success_message = "The public charity profile was withdrawn."
    return _execute_command(
        request,
        command=command,
        success_message=success_message,
        location=location,
    )
