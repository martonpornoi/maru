"""Minimal browser, operational, and build endpoints."""

import logging
from typing import Any
from uuid import UUID

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.utils import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from maru.activity.queries import record_activity
from maru.authorization.services import AuthorizationDenied
from maru.core.forms import StrictInputForm
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY, selected_admin_edition
from maru.events.forms import EventEditionCreationForm, EventEditionUpdateForm
from maru.events.models import EventEdition
from maru.events.services import (
    EDITION_PROFILE_EDITABLE_LIFECYCLES,
    create_event_edition,
    update_event_edition,
)
from maru.identity.models import Account
from maru.organizations.forms import (
    ConventionSeriesCreationForm,
    ConventionSeriesUpdateForm,
    OrganizationCreationForm,
    OrganizationDeletionForm,
)
from maru.organizations.models import ConventionSeries, Organization
from maru.organizations.queries import platform_organization_inventory
from maru.organizations.services import (
    create_convention_series,
    create_draft_organization,
    delete_empty_draft_organization,
    update_convention_series,
    update_organization_profile,
)

logger = logging.getLogger(__name__)


def _require_platform_administrator(request: HttpRequest) -> Account:
    if (
        not isinstance(request.user, Account)
        or not request.user.is_active
        or not request.user.is_platform_administrator
    ):
        raise PermissionDenied
    return request.user


def baseline_root(request: HttpRequest) -> HttpResponse:
    """Send the deliberately empty browser experience to its only home."""

    del request
    return redirect("baseline-admin-home")


@login_required(login_url="staff-login")
def baseline_administration_home(request: HttpRequest) -> HttpResponse:
    """Render the platform-wide organization inventory for its administrators."""

    _require_platform_administrator(request)

    load_failed = False
    status = 200
    try:
        organizations = list(platform_organization_inventory())
    except DatabaseError:
        logger.exception("Unable to load the platform organization inventory")
        organizations = []
        load_failed = True
        status = 503

    return TemplateResponse(
        request,
        "core/baseline_admin_home.html",
        {
            "organizations": organizations,
            "organization_inventory_load_failed": load_failed,
        },
        status=status,
    )


@login_required(login_url="staff-login")
def baseline_create_organization(request: HttpRequest) -> HttpResponse:
    """Create the minimum draft organization record for later completion."""

    actor = _require_platform_administrator(request)
    form = OrganizationCreationForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            organization = create_draft_organization(
                actor=actor,
                details=form.creation_details(),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="web",
            )
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                for field_name, field_errors in error.message_dict.items():
                    target = field_name if field_name in form.fields else None
                    for field_error in field_errors:
                        form.add_error(target, field_error)
            else:
                form.add_error(None, error)
        except DatabaseError:
            logger.exception("Unable to create a draft organization")
            form.add_error(
                None,
                "The organization could not be created. Try again after the "
                "database is available.",
            )
            status = 503
        else:
            messages.success(
                request,
                f"{organization.name} was created as a draft.",
            )
            return redirect("baseline-admin-home")

    return TemplateResponse(
        request,
        "core/baseline_create_organization.html",
        {"form": form},
        status=status,
    )


def _organization_for_record(slug: str) -> Organization:
    try:
        return Organization.objects.get(slug__iexact=slug)
    except Organization.DoesNotExist as error:
        raise Http404 from error


def _add_validation_errors(
    form: forms.BaseForm,
    error: ValidationError,
) -> None:
    if hasattr(error, "message_dict"):
        for field_name, field_errors in error.message_dict.items():
            target = field_name if field_name in form.fields else None
            if target is not None and isinstance(
                form.fields[target].widget,
                forms.HiddenInput,
            ):
                target = None
            for field_error in field_errors:
                form.add_error(target, field_error)
    else:
        form.add_error(None, error)


def _series_for_organization(
    organization: Organization,
) -> list[ConventionSeries]:
    return list(
        ConventionSeries.objects.filter(organization=organization).order_by(
            "name", "id"
        )
    )


def _series_for_record(
    organization: Organization,
    slug: str,
) -> ConventionSeries:
    try:
        return ConventionSeries.objects.get(
            organization=organization,
            slug__iexact=slug,
        )
    except ConventionSeries.DoesNotExist as error:
        raise Http404 from error


def _editions_for_series(series: ConventionSeries) -> list[EventEdition]:
    return list(
        EventEdition.objects.filter(
            organization=series.organization,
            series=series,
        ).order_by("-starts_on", "name", "id")
    )


def _edition_for_record(
    *,
    organization: Organization,
    series: ConventionSeries,
    slug: str,
) -> EventEdition:
    try:
        return EventEdition.objects.get(
            organization=organization,
            series=series,
            slug__iexact=slug,
        )
    except EventEdition.DoesNotExist as error:
        raise Http404 from error


@login_required(login_url="staff-login")
def baseline_organization_record(
    request: HttpRequest,
    organization_slug: str,
) -> HttpResponse:
    """Render and update one organization profile without changing its identity."""

    actor = _require_platform_administrator(request)
    try:
        organization = _organization_for_record(organization_slug)
        series = _series_for_organization(organization)
    except DatabaseError:
        logger.exception("Unable to load the organization record")
        return TemplateResponse(
            request,
            "core/baseline_organization_record.html",
            {"organization_record_load_failed": True},
            status=503,
        )

    form = OrganizationCreationForm.for_organization(
        organization,
        data=request.POST if request.method == "POST" else None,
    )
    deletion_form = OrganizationDeletionForm(organization=organization)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            result = update_organization_profile(
                actor=actor,
                organization_id=organization.id,
                details=form.creation_details(),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="web",
            )
        except ValidationError as error:
            _add_validation_errors(form, error)
        except (Organization.DoesNotExist, DatabaseError):
            logger.exception("Unable to update the organization profile")
            form.add_error(
                None,
                "The organization could not be updated. Try again after the "
                "database is available.",
            )
            status = 503
        else:
            if result.changed_fields:
                messages.success(
                    request,
                    f"{result.organization.name} was updated.",
                )
            else:
                messages.info(request, "No organization details changed.")
            return redirect(
                "baseline-organization-record",
                organization_slug=result.organization.slug,
            )

    return TemplateResponse(
        request,
        "core/baseline_organization_record.html",
        {
            "organization": organization,
            "series": series,
            "form": form,
            "deletion_form": deletion_form,
            "organization_record_load_failed": False,
        },
        status=status,
    )


@login_required(login_url="staff-login")
@require_POST
def baseline_delete_organization(
    request: HttpRequest,
    organization_slug: str,
) -> HttpResponse:
    """Delete one confirmed, empty Draft organization."""

    actor = _require_platform_administrator(request)
    try:
        organization = _organization_for_record(organization_slug)
        series = _series_for_organization(organization)
    except DatabaseError:
        logger.exception("Unable to load the organization for deletion")
        return TemplateResponse(
            request,
            "core/baseline_organization_record.html",
            {"organization_record_load_failed": True},
            status=503,
        )

    form = OrganizationCreationForm.for_organization(organization)
    deletion_form = OrganizationDeletionForm(
        request.POST,
        organization=organization,
    )
    status = 200
    if deletion_form.is_valid():
        try:
            deleted = delete_empty_draft_organization(
                actor=actor,
                organization_id=organization.id,
                confirmation_name=str(deletion_form.cleaned_data["confirmation_name"]),
                acknowledged=bool(deletion_form.cleaned_data["acknowledge"]),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="web",
            )
        except ValidationError as error:
            _add_validation_errors(deletion_form, error)
        except (Organization.DoesNotExist, DatabaseError):
            logger.exception("Unable to delete the draft organization")
            deletion_form.add_error(
                None,
                "The organization could not be deleted. Try again after the "
                "database is available.",
            )
            status = 503
        else:
            messages.success(request, f"{deleted.name} was deleted.")
            return redirect("baseline-admin-home")

    return TemplateResponse(
        request,
        "core/baseline_organization_record.html",
        {
            "organization": organization,
            "series": series,
            "form": form,
            "deletion_form": deletion_form,
            "organization_record_load_failed": False,
        },
        status=status,
    )


@login_required(login_url="staff-login")
def baseline_create_convention_series(
    request: HttpRequest,
    organization_slug: str,
) -> HttpResponse:
    """Create one recurring convention identity beneath an organization."""

    actor = _require_platform_administrator(request)
    try:
        organization = _organization_for_record(organization_slug)
    except DatabaseError:
        logger.exception("Unable to load the organization for series creation")
        return TemplateResponse(
            request,
            "core/baseline_create_convention_series.html",
            {"series_creation_load_failed": True},
            status=503,
        )

    if organization.lifecycle == Organization.Lifecycle.CLOSED:
        return TemplateResponse(
            request,
            "core/baseline_create_convention_series.html",
            {
                "organization": organization,
                "series_creation_blocked": True,
                "series_creation_load_failed": False,
            },
            status=409,
        )

    form = ConventionSeriesCreationForm(request.POST or None)
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            series = create_convention_series(
                actor=actor,
                organization_id=organization.id,
                details=form.creation_details(),
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="web",
            )
        except ValidationError as error:
            _add_validation_errors(form, error)
        except (Organization.DoesNotExist, DatabaseError, RuntimeError):
            logger.exception("Unable to create the convention series")
            form.add_error(
                None,
                "The convention series could not be created. Try again after "
                "the database is available.",
            )
            status = 503
        else:
            messages.success(
                request,
                f"{series.name} was created as a convention series.",
            )
            return redirect(
                "baseline-organization-record",
                organization_slug=organization.slug,
            )

    return TemplateResponse(
        request,
        "core/baseline_create_convention_series.html",
        {
            "organization": organization,
            "form": form,
            "series_creation_blocked": False,
            "series_creation_load_failed": False,
        },
        status=status,
    )


@login_required(login_url="staff-login")
def baseline_convention_series_record(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
) -> HttpResponse:
    """Render and update one scoped recurring convention brand."""

    actor = _require_platform_administrator(request)
    try:
        organization = _organization_for_record(organization_slug)
        series = _series_for_record(organization, series_slug)
        editions = _editions_for_series(series)
        activity = record_activity(
            organization_id=organization.id,
            aggregate_type="organizations.convention_series",
            aggregate_id=series.id,
            time_zone=organization.default_time_zone,
        )
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to load the convention-series record")
        return TemplateResponse(
            request,
            "core/baseline_convention_series_record.html",
            {"series_record_load_failed": True},
            status=503,
        )

    editable = organization.lifecycle != Organization.Lifecycle.CLOSED
    form = (
        ConventionSeriesUpdateForm.for_series(
            series,
            data=request.POST if request.method == "POST" else None,
        )
        if editable
        else None
    )
    status = 200
    if request.method == "POST":
        if form is None:
            status = 409
        elif form.is_valid():
            try:
                result = update_convention_series(
                    actor=actor,
                    organization_id=organization.id,
                    series_id=series.id,
                    expected_profile_version=int(
                        form.cleaned_data["expected_profile_version"]
                    ),
                    details=form.creation_details(),
                    correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                    source_channel="web",
                )
            except ValidationError as error:
                _add_validation_errors(form, error)
                if _validation_error_is_conflict(error):
                    status = 409
            except (
                Organization.DoesNotExist,
                ConventionSeries.DoesNotExist,
            ) as error:
                raise Http404 from error
            except (DatabaseError, RuntimeError):
                logger.exception("Unable to update the convention-series record")
                form.add_error(
                    None,
                    "The convention series could not be updated. Try again "
                    "after the database is available.",
                )
                status = 503
            else:
                if result.changed_fields:
                    messages.success(request, f"{result.series.name} was updated.")
                else:
                    messages.info(request, "No convention-series details changed.")
                return redirect(
                    "baseline-convention-series-record",
                    organization_slug=organization.slug,
                    series_slug=result.series.slug,
                )

    return TemplateResponse(
        request,
        "core/baseline_convention_series_record.html",
        {
            "organization": organization,
            "convention_series": series,
            "editions": editions,
            "activity": activity,
            "activity_time_zone": organization.default_time_zone,
            "form": form,
            "series_editable": editable,
            "series_record_load_failed": False,
        },
        status=status,
    )


@login_required(login_url="staff-login")
def baseline_create_event_edition(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
) -> HttpResponse:
    """Create one Draft edition beneath an exact organization-owned series."""

    actor = _require_platform_administrator(request)
    try:
        organization = _organization_for_record(organization_slug)
        series = _series_for_record(organization, series_slug)
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to load the parent series for edition creation")
        return TemplateResponse(
            request,
            "core/baseline_create_event_edition.html",
            {"edition_creation_load_failed": True},
            status=503,
        )

    blocked = (
        organization.lifecycle == Organization.Lifecycle.CLOSED or not series.is_active
    )
    if blocked:
        return TemplateResponse(
            request,
            "core/baseline_create_event_edition.html",
            {
                "organization": organization,
                "convention_series": series,
                "edition_creation_blocked": True,
                "edition_creation_load_failed": False,
            },
            status=409,
        )

    form = EventEditionCreationForm.for_series(
        organization=organization,
        series=series,
        data=request.POST if request.method == "POST" else None,
    )
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            result = create_event_edition(
                actor=actor,
                organization_id=organization.id,
                series_id=series.id,
                details=form.edition_details(),
                idempotency_key=form.cleaned_data["idempotency_key"],
                correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                source_channel="web",
            )
        except ValidationError as error:
            _add_validation_errors(form, error)
            if _validation_error_is_conflict(error):
                status = 409
        except AuthorizationDenied as error:
            raise PermissionDenied from error
        except (
            Organization.DoesNotExist,
            ConventionSeries.DoesNotExist,
        ) as error:
            raise Http404 from error
        except (DatabaseError, RuntimeError):
            logger.exception("Unable to create the event edition")
            form.add_error(
                None,
                "The event edition could not be created. Try again after the "
                "database is available.",
            )
            status = 503
        else:
            if result.replayed:
                messages.info(
                    request,
                    f"{result.edition.name} was already created; Maru reused it.",
                )
            else:
                messages.success(
                    request,
                    f"{result.edition.name} was created as a Draft edition.",
                )
            return redirect(
                "baseline-event-edition-record",
                organization_slug=organization.slug,
                series_slug=series.slug,
                edition_slug=result.edition.slug,
            )

    return TemplateResponse(
        request,
        "core/baseline_create_event_edition.html",
        {
            "organization": organization,
            "convention_series": series,
            "form": form,
            "edition_creation_blocked": False,
            "edition_creation_load_failed": False,
        },
        status=status,
    )


@login_required(login_url="staff-login")
def baseline_event_edition_record(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Render and update one exact edition record and its human activity."""

    actor = _require_platform_administrator(request)
    try:
        organization = _organization_for_record(organization_slug)
        series = _series_for_record(organization, series_slug)
        edition = _edition_for_record(
            organization=organization,
            series=series,
            slug=edition_slug,
        )
        activity = record_activity(
            organization_id=organization.id,
            aggregate_type="events.event_edition",
            aggregate_id=edition.id,
            time_zone=edition.time_zone,
        )
        selected = selected_admin_edition(request)
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to load the event-edition record")
        return TemplateResponse(
            request,
            "core/baseline_event_edition_record.html",
            {"edition_record_load_failed": True},
            status=503,
        )

    editable = (
        organization.lifecycle != Organization.Lifecycle.CLOSED
        and edition.lifecycle in EDITION_PROFILE_EDITABLE_LIFECYCLES
    )
    form = (
        EventEditionUpdateForm.for_edition(
            edition,
            data=request.POST if request.method == "POST" else None,
        )
        if editable
        else None
    )
    status = 200
    if request.method == "POST":
        if form is None:
            status = 409
        elif form.is_valid():
            try:
                result = update_event_edition(
                    actor=actor,
                    organization_id=organization.id,
                    series_id=series.id,
                    edition_id=edition.id,
                    expected_aggregate_version=int(
                        form.cleaned_data["expected_aggregate_version"]
                    ),
                    details=form.edition_details(),
                    correlation_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                    request_id=UUID(request.correlation_id),  # type: ignore[attr-defined]
                    source_channel="web",
                )
            except ValidationError as error:
                _add_validation_errors(form, error)
                status = 409 if _validation_error_is_conflict(error) else status
            except AuthorizationDenied as error:
                raise PermissionDenied from error
            except (
                Organization.DoesNotExist,
                ConventionSeries.DoesNotExist,
                EventEdition.DoesNotExist,
            ) as error:
                raise Http404 from error
            except (DatabaseError, RuntimeError):
                logger.exception("Unable to update the event-edition record")
                form.add_error(
                    None,
                    "The event edition could not be updated. Try again after "
                    "the database is available.",
                )
                status = 503
            else:
                if result.changed_fields:
                    messages.success(request, f"{result.edition.name} was updated.")
                else:
                    messages.info(request, "No edition details changed.")
                return redirect(
                    "baseline-event-edition-record",
                    organization_slug=organization.slug,
                    series_slug=series.slug,
                    edition_slug=result.edition.slug,
                )

    return TemplateResponse(
        request,
        "core/baseline_event_edition_record.html",
        {
            "organization": organization,
            "convention_series": series,
            "edition": edition,
            "activity": activity,
            "activity_time_zone": edition.time_zone,
            "form": form,
            "edition_editable": editable,
            "edition_is_selected": selected is not None and selected.id == edition.id,
            "edition_record_load_failed": False,
        },
        status=status,
    )


def _validation_error_is_conflict(error: ValidationError) -> bool:
    conflict_codes = {
        "edition_creation_idempotency_conflict",
        "edition_parent_closed",
        "edition_profile_read_only",
        "edition_series_inactive",
        "series_parent_closed",
        "stale_series_profile",
        "stale_edition_version",
    }
    if hasattr(error, "error_dict"):
        return any(
            item.code in conflict_codes
            for field_errors in error.error_dict.values()
            for item in field_errors
        )
    return any(item.code in conflict_codes for item in error.error_list)


def _context_action_input_error_response(
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse | None:
    """Reject undeclared context-action input without changing the session."""

    form = StrictInputForm(request.POST)
    if form.is_valid():
        return None
    messages.error(request, str(form.non_field_errors()[0]))
    return redirect(
        "baseline-event-edition-record",
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )


@login_required(login_url="staff-login")
@require_POST
def baseline_select_event_edition(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Persist one already authorized exact route chain as display context."""

    _require_platform_administrator(request)
    input_error = _context_action_input_error_response(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    if input_error is not None:
        return input_error
    try:
        organization = _organization_for_record(organization_slug)
        series = _series_for_record(organization, series_slug)
        edition = _edition_for_record(
            organization=organization,
            series=series,
            slug=edition_slug,
        )
        request.session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
        messages.success(request, f"Working edition changed to {edition.name}.")
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to select the working event edition")
        return TemplateResponse(
            request,
            "core/baseline_event_edition_record.html",
            {"edition_record_load_failed": True},
            status=503,
        )
    return redirect(
        "baseline-event-edition-record",
        organization_slug=organization.slug,
        series_slug=series.slug,
        edition_slug=edition.slug,
    )


@login_required(login_url="staff-login")
@require_POST
def baseline_clear_event_edition(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Clear display context without changing edition records or authority."""

    _require_platform_administrator(request)
    input_error = _context_action_input_error_response(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    if input_error is not None:
        return input_error
    try:
        organization = _organization_for_record(organization_slug)
        series = _series_for_record(organization, series_slug)
        edition = _edition_for_record(
            organization=organization,
            series=series,
            slug=edition_slug,
        )
        request.session.pop(ADMIN_EDITION_SESSION_KEY, None)
        messages.success(request, "Working edition cleared.")
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to clear the working event edition")
        return TemplateResponse(
            request,
            "core/baseline_event_edition_record.html",
            {"edition_record_load_failed": True},
            status=503,
        )
    return redirect(
        "baseline-event-edition-record",
        organization_slug=organization.slug,
        series_slug=series.slug,
        edition_slug=edition.slug,
    )


def platform_home(request: HttpRequest) -> TemplateResponse:
    return TemplateResponse(
        request,
        "core/home.html",
        {
            "build_version": settings.BUILD_VERSION,
        },
    )


@login_required(login_url="staff-login")
@ensure_csrf_cookie
def administration_index(request: HttpRequest) -> HttpResponse:
    """Serve Django's original administration index to active accounts."""

    return admin.site.index(request)


@login_required(login_url="staff-login")
@ensure_csrf_cookie
def administration_workspace(request: HttpRequest) -> HttpResponse:
    """Serve API-backed workflows inside the Django administration shell."""

    selected_edition = selected_admin_edition(request)
    return TemplateResponse(
        request,
        "core/admin_workspace.html",
        {
            **admin.site.each_context(request),
            "title": "Convention work",
            "selected_admin_edition_id": (
                str(selected_edition.id) if selected_edition is not None else ""
            ),
        },
    )


def removed_administration_route(request: HttpRequest) -> HttpResponse:
    """Keep retired administration entry points from becoming login redirects."""

    del request
    raise Http404


@extend_schema(
    operation_id="platform_liveness",
    auth=[],
    responses={200: OpenApiResponse(description="The process can serve requests.")},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def liveness(request: Request) -> Response:
    del request
    return Response({"status": "ok"})


@extend_schema(
    operation_id="platform_readiness",
    auth=[],
    responses={
        200: OpenApiResponse(description="Required dependencies are ready."),
        503: OpenApiResponse(description="A required dependency is unavailable."),
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def readiness(request: Request) -> Response:
    del request
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return Response(
            {"status": "unavailable", "dependencies": {"database": "unavailable"}},
            status=503,
        )
    return Response({"status": "ok", "dependencies": {"database": "ok"}})


def build_info(request: HttpRequest) -> JsonResponse:
    del request
    payload: dict[str, Any] = {
        "service": "maru",
        "version": settings.BUILD_VERSION,
        "commit": settings.BUILD_COMMIT,
    }
    return JsonResponse(payload)
