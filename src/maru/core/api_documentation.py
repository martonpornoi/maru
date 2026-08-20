"""Private, read-only views over Maru's canonical OpenAPI contract."""

from collections.abc import Sequence
from typing import Any

from django.db.utils import DatabaseError
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from maru.identity.models import Account


class IsCurrentPlatformAdministrator(BasePermission):
    """Admit only a freshly resolved active platform administrator."""

    message = "An active platform administrator is required."

    def has_permission(self, request: Request, view: Any) -> bool:
        """Return whether the request may access the resource.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        view : Any
            The view evaluated while has permission.

        Returns
        -------
        bool
            `True` when the request may access the resource; otherwise `False`.
        """
        del view
        actor = request.user
        if not isinstance(actor, Account) or not actor.is_authenticated:
            return False
        try:
            persisted = Account.objects.only(
                "account_kind",
                "is_active",
                "is_staff",
                "is_superuser",
            ).get(pk=actor.pk)
        except (Account.DoesNotExist, DatabaseError, TypeError, ValueError):
            return False
        return bool(
            persisted.is_active
            and persisted.is_staff
            and persisted.is_superuser
            and persisted.is_platform_administrator
        )


def _harden_documentation_response(response: Response) -> Response:
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response["Cross-Origin-Opener-Policy"] = "same-origin"
    return response


class PlatformApiSchemaView(SpectacularAPIView):
    """Serve the canonical machine-readable schema to platform operators."""

    authentication_classes: Sequence[type[BaseAuthentication]] = (
        SessionAuthentication,
    )
    permission_classes: Sequence[type[BasePermission]] = (
        IsCurrentPlatformAdministrator,
    )

    def finalize_response(
        self,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Apply the private documentation response headers.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        response : Response
            The HTTP response before policy headers or content are finalized.
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        return _harden_documentation_response(
            super().finalize_response(request, response, *args, **kwargs)
        )


class PlatformApiSwaggerView(SpectacularSwaggerView):
    """Render a searchable, read-only Swagger view of the canonical schema."""

    authentication_classes: Sequence[type[BaseAuthentication]] = (
        SessionAuthentication,
    )
    permission_classes: Sequence[type[BasePermission]] = (
        IsCurrentPlatformAdministrator,
    )

    def finalize_response(
        self,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Apply the private documentation response headers.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        response : Response
            The HTTP response before policy headers or content are finalized.
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        return _harden_documentation_response(
            super().finalize_response(request, response, *args, **kwargs)
        )


class PlatformApiRedocView(SpectacularRedocView):
    """Render a reading-focused ReDoc view of the canonical schema."""

    authentication_classes: Sequence[type[BaseAuthentication]] = (
        SessionAuthentication,
    )
    permission_classes: Sequence[type[BasePermission]] = (
        IsCurrentPlatformAdministrator,
    )

    def finalize_response(
        self,
        request: Request,
        response: Response,
        *args: Any,
        **kwargs: Any,
    ) -> Response:
        """Apply the private documentation response headers.

        Parameters
        ----------
        request : Request
            The incoming HTTP request and authenticated principal context.
        response : Response
            The HTTP response before policy headers or content are finalized.
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.

        Returns
        -------
        Response
            The HTTP response for the requested operation.
        """
        return _harden_documentation_response(
            super().finalize_response(request, response, *args, **kwargs)
        )
