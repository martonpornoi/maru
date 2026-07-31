"""Minimal browser, operational, and build endpoints."""

import logging
from typing import Any
from uuid import UUID

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
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from maru.events.admin_context import selected_admin_edition
from maru.identity.models import Account
from maru.organizations.forms import OrganizationCreationForm
from maru.organizations.queries import platform_organization_inventory
from maru.organizations.services import create_draft_organization

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
