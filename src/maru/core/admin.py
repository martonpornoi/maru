"""Shared conventions for the bootstrap Django administration interface."""

from django.contrib import admin
from django.contrib.auth.models import Group
from django.db import models
from django.http import HttpRequest

admin.site.site_header = "Maru administration"
admin.site.site_title = "Maru administration"
admin.site.index_title = "Bootstrap administration"
admin.site.empty_value_display = "—"

# Maru authorization is capability- and scope-based. Django groups would be a
# misleading second role system in this bootstrap interface.
if admin.site.is_registered(Group):
    admin.site.unregister(Group)


class ReadOnlyAdminMixin:
    """Expose immutable or command-owned records for inspection only."""

    def has_add_permission(self, request: HttpRequest) -> bool:
        _ = request
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
    ) -> bool:
        _ = request, obj
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
    ) -> bool:
        _ = request, obj
        return False


class NoDeleteAdminMixin:
    """Hide destructive actions where records have a lifecycle instead."""

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
    ) -> bool:
        _ = request, obj
        return False
