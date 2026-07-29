"""Persistent event-edition context for bootstrap administration."""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from maru.events.models import EventEdition
from maru.organizations.models import ConventionSeries, Organization

ADMIN_EDITION_SESSION_KEY = "maru.admin.edition_id"
ADMIN_PATH_PREFIX = "/admin/"
_REQUEST_CACHE_ATTRIBUTE = "_maru_admin_edition_context"
_NOT_CACHED = object()


def selected_admin_edition(request: HttpRequest) -> EventEdition | None:
    """Resolve and request-cache the selected bootstrap edition."""

    cached = getattr(request, _REQUEST_CACHE_ATTRIBUTE, _NOT_CACHED)
    if cached is not _NOT_CACHED:
        return cached if isinstance(cached, EventEdition) else None

    raw_edition_id = request.session.get(ADMIN_EDITION_SESSION_KEY)
    edition: EventEdition | None = None
    if isinstance(raw_edition_id, str):
        try:
            edition_id = UUID(raw_edition_id)
        except ValueError:
            request.session.pop(ADMIN_EDITION_SESSION_KEY, None)
        else:
            edition = (
                EventEdition.objects.select_related("organization", "series")
                .filter(id=edition_id)
                .first()
            )
            if edition is None:
                request.session.pop(ADMIN_EDITION_SESSION_KEY, None)

    setattr(request, _REQUEST_CACHE_ATTRIBUTE, edition)
    return edition


def admin_edition_options(request: HttpRequest) -> dict[str, object]:
    """Return selector state only for active bootstrap administrators."""

    user = request.user
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return {"available": False, "selected": None, "editions": ()}
    return {
        "available": True,
        "selected": selected_admin_edition(request),
        "editions": EventEdition.objects.select_related(
            "organization",
            "series",
        ).order_by("-starts_on", "organization__name", "name"),
    }


def _safe_admin_return_path(request: HttpRequest) -> str:
    candidate = request.POST.get("next", "")
    if candidate.startswith(ADMIN_PATH_PREFIX) and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("admin:index")


@staff_member_required
@require_POST
def change_admin_edition_context(request: HttpRequest) -> HttpResponse:
    """Select or clear the persistent bootstrap-administration edition."""

    raw_edition_id = request.POST.get("edition_id", "").strip()
    if not raw_edition_id:
        request.session.pop(ADMIN_EDITION_SESSION_KEY, None)
        messages.success(request, "Showing all foundation data.")
        return redirect(_safe_admin_return_path(request))

    try:
        edition_id = UUID(raw_edition_id)
    except ValueError as error:
        raise Http404 from error
    edition = EventEdition.objects.filter(id=edition_id).first()
    if edition is None:
        raise Http404

    request.session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    messages.success(request, f"Convention workspace changed to {edition.name}.")
    return redirect(_safe_admin_return_path(request))


class EditionContextAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Scope an admin model to the selected edition before object lookup."""

    edition_context_lookup = "edition_id"
    edition_context_value_attribute = "id"
    edition_context_foreign_key_lookups: ClassVar[dict[str, str]] = {}
    edition_context_redundant_filters: ClassVar[frozenset[str]] = frozenset(
        {
            "edition",
            "organization",
            "series",
            "participation__edition",
            "participation__organization",
            "registration__edition",
            "registration__organization",
        }
    )

    def edition_context_q(
        self,
        request: HttpRequest,
        edition: EventEdition,
    ) -> Q:
        del request
        value = getattr(edition, self.edition_context_value_attribute)
        return Q(**{self.edition_context_lookup: value})

    def scope_queryset_to_edition(
        self,
        request: HttpRequest,
        queryset: QuerySet[models.Model],
        edition: EventEdition,
    ) -> QuerySet[models.Model]:
        return queryset.filter(self.edition_context_q(request, edition))

    def get_queryset(self, request: HttpRequest) -> QuerySet[models.Model]:
        queryset = super().get_queryset(request)
        edition = selected_admin_edition(request)
        if edition is None:
            return queryset
        return self.scope_queryset_to_edition(request, queryset, edition)

    def get_list_filter(self, request: HttpRequest) -> Any:
        list_filter = super().get_list_filter(request)
        if selected_admin_edition(request) is None:
            return list_filter
        return tuple(
            item
            for item in list_filter
            if not (
                isinstance(item, str) and item in self.edition_context_redundant_filters
            )
        )

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        initial = super().get_changeform_initial_data(request)
        edition = selected_admin_edition(request)
        if edition is None:
            return initial
        edition_defaults = {
            "edition": edition.id,
            "organization": edition.organization_id,
            "series": edition.series_id,
        }
        for field_name, value in edition_defaults.items():
            try:
                self.model._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue
            initial.setdefault(field_name, str(value))
        return initial

    def formfield_for_foreignkey(
        self,
        db_field: models.ForeignKey[Any, Any],
        request: HttpRequest,
        **kwargs: Any,
    ) -> forms.ModelChoiceField[Any] | None:
        edition = selected_admin_edition(request)
        if edition is not None:
            if db_field.name == "edition":
                kwargs["queryset"] = EventEdition.objects.filter(id=edition.id)
            elif db_field.name == "organization":
                kwargs["queryset"] = Organization.objects.filter(
                    id=edition.organization_id
                )
            elif db_field.name == "series":
                kwargs["queryset"] = ConventionSeries.objects.filter(
                    id=edition.series_id
                )
            elif lookup := self.edition_context_foreign_key_lookups.get(db_field.name):
                kwargs["queryset"] = (
                    db_field.remote_field.model._default_manager.filter(
                        **{lookup: edition.id}
                    )
                )
        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs,
        )
