"""Minimal operational and build endpoints."""

from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from maru.identity.models import Account
from maru.participation.queries import has_convention_workspace


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
def staff_console(request: HttpRequest) -> HttpResponse:
    """Serve the independently built, API-backed Staff Console host."""

    account = request.user
    if (
        isinstance(account, Account)
        and account.is_staff
        and not has_convention_workspace(account)
    ):
        return redirect("admin:index")
    return TemplateResponse(request, "core/staff_console.html")


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
