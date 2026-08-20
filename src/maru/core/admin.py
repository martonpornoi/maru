"""Shared conventions for the bootstrap Django administration interface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from django.contrib import admin
from django.contrib.auth.models import Group
from django.db import models

from maru.core.forms import HttpsURLField

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.http import HttpRequest

admin.site.site_header = "Maru Administration"
admin.site.site_title = "Maru Administration"
admin.site.index_title = "Administration"
admin.site.empty_value_display = "—"

# Maru authorization is capability- and scope-based. Django groups would be a
# misleading second role system in this bootstrap interface.
if admin.site.is_registered(Group):
    admin.site.unregister(Group)


class ReadOnlyAdminMixin:
    """Expose immutable or command-owned records for inspection only."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Return whether add permission.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.

        Returns
        -------
        bool
            `True` when add permission; otherwise `False`.
        """
        _ = request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
    ) -> bool:
        """Return whether change permission.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        obj : models.Model | None, default=None
            The model instance being validated or presented.

        Returns
        -------
        bool
            `True` when change permission; otherwise `False`.
        """
        _ = request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
    ) -> bool:
        """Return whether delete permission.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        obj : models.Model | None, default=None
            The model instance being validated or presented.

        Returns
        -------
        bool
            `True` when delete permission; otherwise `False`.
        """
        _ = request, obj
        return False


class NoDeleteAdminMixin:
    """Hide destructive actions where records have a lifecycle instead."""

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
    ) -> bool:
        """Return whether delete permission.

        Parameters
        ----------
        request : HttpRequest
            The incoming HTTP request and authenticated principal context.
        obj : models.Model | None, default=None
            The model instance being validated or presented.

        Returns
        -------
        bool
            `True` when delete permission; otherwise `False`.
        """
        _ = request, obj
        return False


class HttpsURLAdminMixin:
    """Keep model-generated URL form fields warning-free and HTTPS-first."""

    formfield_overrides: ClassVar[
        Mapping[type[models.Field[Any, Any]], Mapping[str, Any]]
    ] = {
        models.URLField: {"form_class": HttpsURLField},
    }
