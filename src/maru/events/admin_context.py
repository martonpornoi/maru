"""Persistent event-edition context for bootstrap administration."""

from __future__ import annotations

from typing import Any, ClassVar, cast
from uuid import UUID

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db import models
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from maru.authorization.policy import (
    AuthorizedScopeProjection,
    project_active_authority_scopes,
)
from maru.core.admin import HttpsURLAdminMixin
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization

ADMIN_EDITION_SESSION_KEY = "maru.admin.edition_id"
ADMIN_PATH_PREFIX = "/admin/"
_REQUEST_CACHE_ATTRIBUTE = "_maru_admin_edition_context"
_AUTHORIZED_EDITIONS_CACHE_ATTRIBUTE = "_maru_authorized_admin_editions"
_ACTIVE_ADMIN_SCOPE_CACHE_ATTRIBUTE = "_maru_active_admin_scope"
_AUTHORIZED_ADMIN_SCOPES_CACHE_ATTRIBUTE = "_maru_authorized_admin_scopes"
_ADMIN_ORGANIZATION_NAVIGATION_CACHE_ATTRIBUTE = "_maru_admin_organization_navigation"
_NOT_CACHED = object()

_ORGANIZATION_NAVIGATION_CAPABILITIES = frozenset(
    {
        "organizations.view_basic",
        "organizations.manage_representation",
        "organizations.create_series",
    }
)

_EDITION_WORKSPACE_NAVIGATION_CAPABILITIES = frozenset(
    {
        "applications.manage_definitions",
        "applications.review",
        "catalog.view_activity",
        "charities.view_review_queue",
        "events.view_basic",
        "logistics.view_workspace",
        "registration.manage_configuration",
        "registration.manage_exceptions",
        "venues.view_workspace",
        "workforce.view_structure",
    }
)


def _active_account(request: HttpRequest) -> Account | None:
    user = request.user
    if not isinstance(user, Account) or not user.is_authenticated or not user.is_active:
        return None
    return user


def _authorized_admin_scopes(
    request: HttpRequest,
) -> tuple[AuthorizedScopeProjection, ...]:
    """Return request-local, name-free scopes whose lineage is current.

    The authorization policy owns compatibility versus exact-lineage
    selection. In the exact contract it validates every candidate row's pinned
    issuance recursively; a missing or malformed required contract returns no
    scope before any organization or edition name is queried.
    """

    cached = getattr(
        request,
        _AUTHORIZED_ADMIN_SCOPES_CACHE_ATTRIBUTE,
        _NOT_CACHED,
    )
    if cached is not _NOT_CACHED:
        return cast("tuple[AuthorizedScopeProjection, ...]", cached)

    account = _active_account(request)
    if account is None or account.is_platform_administrator:
        authorized: tuple[AuthorizedScopeProjection, ...] = ()
    else:
        authorized = project_active_authority_scopes(
            principal=account,
            at=timezone.now(),
        )

    setattr(request, _AUTHORIZED_ADMIN_SCOPES_CACHE_ATTRIBUTE, authorized)
    return authorized


def authorized_admin_organization_ids(
    request: HttpRequest,
    *,
    capability_codes: frozenset[str],
) -> frozenset[UUID]:
    """Return exact organization-target IDs without projecting tenant names.

    Platform callers retain their explicit oversight branch and should not use
    this organizer-scope query as a substitute for it. Narrower authority does
    not flow upward into organization-record routes.
    """

    return frozenset(
        scope.organization_id
        for scope in _authorized_admin_scopes(request)
        if scope.edition_id is None
        and scope.department_id is None
        and scope.resource_binding_id is None
        and scope.capability_codes.intersection(capability_codes)
    )


def _authorized_admin_edition_scope_ids(
    request: HttpRequest,
    *,
    capability_codes: frozenset[str],
) -> tuple[frozenset[UUID], frozenset[UUID]]:
    """Return organization-wide and exact-edition authority separately."""

    organization_ids: set[UUID] = set()
    edition_ids: set[UUID] = set()
    for scope in _authorized_admin_scopes(request):
        if (
            not scope.capability_codes.intersection(capability_codes)
            or scope.department_id is not None
            or scope.resource_binding_id is not None
        ):
            continue
        if scope.edition_id is None:
            organization_ids.add(scope.organization_id)
        else:
            edition_ids.add(scope.edition_id)
    return frozenset(organization_ids), frozenset(edition_ids)


def authorized_admin_edition_ids(
    request: HttpRequest,
    *,
    capability_codes: frozenset[str],
) -> frozenset[UUID]:
    """Resolve name-free edition IDs for org-wide or exact-edition authority."""

    organization_ids, edition_ids = _authorized_admin_edition_scope_ids(
        request,
        capability_codes=capability_codes,
    )
    if not organization_ids and not edition_ids:
        return frozenset()
    return frozenset(
        EventEdition.objects.filter(
            Q(organization_id__in=organization_ids) | Q(id__in=edition_ids)
        ).values_list("id", flat=True)
    )


def authorized_admin_edition_for_route(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    capability_code: str,
) -> tuple[Organization, ConventionSeries, EventEdition]:
    """Resolve one complete route chain inside a name-free authority set.

    Platform oversight has its own explicit branch. Ordinary accounts first
    project exact current authority to edition identifiers, so a foreign
    organization, series, or edition name cannot enter the response before
    authorization. Every destination must still repeat its sealed-target
    policy decision after this candidate-resolution gate.
    """

    editions = EventEdition.objects.select_related("organization", "series").filter(
        organization__slug__iexact=organization_slug,
        series__slug__iexact=series_slug,
        slug__iexact=edition_slug,
    )
    if not actor.is_platform_administrator:
        candidate_ids = authorized_admin_edition_ids(
            request,
            capability_codes=frozenset({capability_code}),
        )
        editions = editions.filter(id__in=candidate_ids)
    edition = editions.order_by("id").first()
    if edition is None:
        if actor.is_platform_administrator:
            raise Http404
        raise PermissionDenied
    return edition.organization, edition.series, edition


def has_active_admin_scope(request: HttpRequest) -> bool:
    """Return whether the account may enter convention management.

    Django's ``is_staff`` flag remains the boundary for specialist model
    administration.  Ordinary access requires at least one current capability
    whose complete compatibility or exact-lineage policy decision succeeds.
    """

    cached = getattr(request, _ACTIVE_ADMIN_SCOPE_CACHE_ATTRIBUTE, _NOT_CACHED)
    if cached is not _NOT_CACHED:
        return bool(cached)

    account = _active_account(request)
    available = bool(
        account
        and (account.is_platform_administrator or _authorized_admin_scopes(request))
    )
    setattr(request, _ACTIVE_ADMIN_SCOPE_CACHE_ATTRIBUTE, available)
    return available


def admin_shell_access(request: HttpRequest) -> dict[str, bool]:
    """Expose the management-shell boundary without granting Django staff."""

    account = _active_account(request)
    return {
        "active": account is not None,
        "workspace_available": has_active_admin_scope(request),
        "specialist_records_available": bool(account and account.is_staff),
    }


def admin_organization_navigation(
    request: HttpRequest,
) -> tuple[dict[str, object], ...]:
    """Project exact organization links from current scoped authority.

    This is navigation only.  Every destination repeats its own capability
    decision.  Invalid delegated grants are excluded before an organization
    name can enter the projection.
    """

    cached = getattr(
        request,
        _ADMIN_ORGANIZATION_NAVIGATION_CACHE_ATTRIBUTE,
        _NOT_CACHED,
    )
    if cached is not _NOT_CACHED:
        return cast("tuple[dict[str, object], ...]", cached)

    account = _active_account(request)
    if account is None or account.is_platform_administrator:
        navigation: tuple[dict[str, object], ...] = ()
    else:
        capabilities_by_organization: dict[UUID, set[str]] = {}
        for scope in _authorized_admin_scopes(request):
            if scope.edition_id is not None:
                continue
            capabilities = _ORGANIZATION_NAVIGATION_CAPABILITIES.intersection(
                scope.capability_codes
            )
            if capabilities:
                capabilities_by_organization.setdefault(
                    scope.organization_id,
                    set(),
                ).update(capabilities)

        organizations = Organization.objects.filter(
            id__in=capabilities_by_organization
        ).order_by("name", "id")
        navigation = tuple(
            {
                "organization": organization,
                "can_view_organization": "organizations.view_basic"
                in capabilities_by_organization[organization.id],
                "can_manage_representation": (
                    "organizations.manage_representation"
                    in capabilities_by_organization[organization.id]
                ),
                "can_create_series": "organizations.create_series"
                in capabilities_by_organization[organization.id],
            }
            for organization in organizations
        )

    setattr(
        request,
        _ADMIN_ORGANIZATION_NAVIGATION_CACHE_ATTRIBUTE,
        navigation,
    )
    return navigation


def _authorized_admin_editions(request: HttpRequest) -> QuerySet[EventEdition]:
    """Scope selector candidates before any edition row is evaluated."""

    cached = getattr(request, _AUTHORIZED_EDITIONS_CACHE_ATTRIBUTE, _NOT_CACHED)
    if cached is not _NOT_CACHED:
        return cast("QuerySet[EventEdition]", cached)

    editions = EventEdition.objects.select_related("organization", "series")
    account = _active_account(request)
    if account is None:
        authorized_editions = editions.none()
    elif account.is_platform_administrator:
        authorized_editions = editions
    else:
        organization_ids, edition_ids = _authorized_admin_edition_scope_ids(
            request,
            capability_codes=_EDITION_WORKSPACE_NAVIGATION_CAPABILITIES,
        )
        if organization_ids or edition_ids:
            authorized_editions = editions.filter(
                Q(organization_id__in=organization_ids) | Q(id__in=edition_ids)
            )
        else:
            authorized_editions = editions.none()

    setattr(request, _AUTHORIZED_EDITIONS_CACHE_ATTRIBUTE, authorized_editions)
    return authorized_editions


def selected_admin_edition(request: HttpRequest) -> EventEdition | None:
    """Resolve and request-cache the selected bootstrap edition."""

    cached = getattr(request, _REQUEST_CACHE_ATTRIBUTE, _NOT_CACHED)
    if cached is not _NOT_CACHED:
        return cached if isinstance(cached, EventEdition) else None

    raw_edition_id = request.session.get(ADMIN_EDITION_SESSION_KEY)
    edition: EventEdition | None = None
    if raw_edition_id is not None and not isinstance(raw_edition_id, str):
        request.session.pop(ADMIN_EDITION_SESSION_KEY, None)
    elif isinstance(raw_edition_id, str):
        try:
            edition_id = UUID(raw_edition_id)
        except ValueError:
            request.session.pop(ADMIN_EDITION_SESSION_KEY, None)
        else:
            edition = _authorized_admin_editions(request).filter(id=edition_id).first()
            if edition is None:
                request.session.pop(ADMIN_EDITION_SESSION_KEY, None)

    setattr(request, _REQUEST_CACHE_ATTRIBUTE, edition)
    return edition


def admin_edition_options(request: HttpRequest) -> dict[str, object]:
    """Return selector state only for accounts with active scoped authority."""

    if not has_active_admin_scope(request):
        selected_admin_edition(request)
        return {"available": False, "selected": None, "editions": ()}
    selected = selected_admin_edition(request)
    account = _active_account(request)
    selected_can_view_structure = bool(
        selected
        and account
        and (
            account.is_platform_administrator
            or selected.id
            in authorized_admin_edition_ids(
                request,
                capability_codes=frozenset({"workforce.view_structure"}),
            )
        )
    )
    selected_can_manage_registration = bool(
        selected
        and account
        and (
            account.is_platform_administrator
            or selected.id
            in authorized_admin_edition_ids(
                request,
                capability_codes=frozenset({"registration.manage_configuration"}),
            )
        )
    )
    return {
        "available": True,
        "selected": selected,
        "selected_can_view_structure": selected_can_view_structure,
        "selected_can_manage_registration": selected_can_manage_registration,
        "editions": _authorized_admin_editions(request).order_by(
            "-starts_on",
            "organization__name",
            "name",
        ),
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


@login_required(login_url="staff-login")
@require_POST
def change_admin_edition_context(request: HttpRequest) -> HttpResponse:
    """Select or clear an edition within the account's active authority."""

    if not has_active_admin_scope(request):
        raise PermissionDenied

    raw_edition_id = request.POST.get("edition_id", "").strip()
    if not raw_edition_id:
        request.session.pop(ADMIN_EDITION_SESSION_KEY, None)
        messages.success(request, "Showing all foundation data.")
        return redirect(_safe_admin_return_path(request))

    try:
        edition_id = UUID(raw_edition_id)
    except ValueError as error:
        raise Http404 from error
    edition = _authorized_admin_editions(request).filter(id=edition_id).first()
    if edition is None:
        raise Http404

    request.session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    messages.success(request, f"Convention workspace changed to {edition.name}.")
    return redirect(_safe_admin_return_path(request))


class EditionContextAdmin(
    HttpsURLAdminMixin,
    admin.ModelAdmin,  # type: ignore[type-arg]
):
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
