"""Persistent event-edition context for bootstrap administration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, cast
from uuid import UUID

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldDoesNotExist, PermissionDenied
from django.db import models
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.authorization.policy import grant_chain_is_active
from maru.core.admin import HttpsURLAdminMixin
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization

ADMIN_EDITION_SESSION_KEY = "maru.admin.edition_id"
ADMIN_PATH_PREFIX = "/admin/"
_REQUEST_CACHE_ATTRIBUTE = "_maru_admin_edition_context"
_AUTHORIZED_EDITIONS_CACHE_ATTRIBUTE = "_maru_authorized_admin_editions"
_ACTIVE_ADMIN_SCOPE_CACHE_ATTRIBUTE = "_maru_active_admin_scope"
_ADMIN_ORGANIZATION_NAVIGATION_CACHE_ATTRIBUTE = "_maru_admin_organization_navigation"
_NOT_CACHED = object()

_ORGANIZATION_NAVIGATION_CAPABILITIES = frozenset(
    {
        "organizations.view_basic",
        "organizations.manage_representation",
        "organizations.create_series",
    }
)


def _active_account(request: HttpRequest) -> Account | None:
    user = request.user
    if not isinstance(user, Account) or not user.is_authenticated or not user.is_active:
        return None
    return user


def _active_scope_filter(evaluated_at: datetime) -> Q:
    return (
        Q(effective_from__lte=evaluated_at)
        & (Q(expires_at__isnull=True) | Q(expires_at__gt=evaluated_at))
        & Q(revoked_at__isnull=True)
    )


def has_active_admin_scope(request: HttpRequest) -> bool:
    """Return whether the account may enter convention management.

    Django's ``is_staff`` flag remains the boundary for specialist model
    administration.  This separate predicate admits only an active platform
    administrator or an account with current, organization-scoped Maru
    authority.  Delegated grants are accepted only while their complete chain
    remains valid.
    """

    cached = getattr(request, _ACTIVE_ADMIN_SCOPE_CACHE_ATTRIBUTE, _NOT_CACHED)
    if cached is not _NOT_CACHED:
        return bool(cached)

    account = _active_account(request)
    if account is None:
        available = False
    elif account.is_platform_administrator:
        available = True
    else:
        evaluated_at = timezone.now()
        active_at = _active_scope_filter(evaluated_at)
        available = RoleAssignment.objects.filter(
            active_at,
            principal=account,
        ).exists() or bool(
            _active_grant_ids_with_valid_chains(
                account,
                evaluated_at=evaluated_at,
                active_at=active_at,
            )
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


def _grant_chain_is_loaded(
    grant: CapabilityGrant,
    grants_by_id: dict[UUID, CapabilityGrant],
) -> bool:
    """Fail closed if an ancestor disappeared while its chain was loaded."""

    seen: set[UUID] = set()
    current = grant
    while current.delegated_from_id is not None:
        if current.id in seen:
            # A fully loaded cycle is passed to the canonical validator, which
            # rejects it. Stopping here avoids looping during this completeness
            # check.
            return True
        seen.add(current.id)
        parent = grants_by_id.get(current.delegated_from_id)
        if parent is None:
            return False
        current = parent
    return True


def _active_grant_ids_with_valid_chains(
    account: Account,
    *,
    evaluated_at: datetime,
    active_at: Q,
) -> set[UUID]:
    """Load delegation ancestors in batches and reject invalid grant chains."""

    candidates = list(
        CapabilityGrant.objects.filter(
            active_at,
            principal=account,
        )
    )
    grants_by_id = {grant.id: grant for grant in candidates}
    pending_parent_ids = {
        grant.delegated_from_id
        for grant in candidates
        if grant.delegated_from_id is not None
        and grant.delegated_from_id not in grants_by_id
    }
    while pending_parent_ids:
        parents = list(CapabilityGrant.objects.filter(id__in=pending_parent_ids))
        grants_by_id.update((parent.id, parent) for parent in parents)
        pending_parent_ids = {
            parent.delegated_from_id
            for parent in parents
            if parent.delegated_from_id is not None
            and parent.delegated_from_id not in grants_by_id
        }

    # Populate Django's relation cache so the canonical chain validator never
    # issues one query per ancestor. Missing parents remain uncached and cause
    # the explicit completeness check below to deny the candidate.
    for grant in grants_by_id.values():
        if (
            grant.delegated_from_id is not None
            and grant.delegated_from_id in grants_by_id
        ):
            grant._state.fields_cache["delegated_from"] = grants_by_id[
                grant.delegated_from_id
            ]

    return {
        grant.id
        for grant in candidates
        if _grant_chain_is_loaded(grant, grants_by_id)
        and grant_chain_is_active(grant, evaluated_at)
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
        evaluated_at = timezone.now()
        active_at = _active_scope_filter(evaluated_at)
        capabilities_by_organization: dict[UUID, set[str]] = {}

        assignments = RoleAssignment.objects.filter(
            active_at,
            principal=account,
            edition__isnull=True,
        ).select_related("role_bundle")
        for assignment in assignments:
            capabilities = _ORGANIZATION_NAVIGATION_CAPABILITIES.intersection(
                assignment.role_bundle.capability_codes
            )
            if capabilities:
                capabilities_by_organization.setdefault(
                    assignment.organization_id,
                    set(),
                ).update(capabilities)

        valid_grant_ids = _active_grant_ids_with_valid_chains(
            account,
            evaluated_at=evaluated_at,
            active_at=active_at,
        )
        grants = CapabilityGrant.objects.filter(
            id__in=valid_grant_ids,
            edition__isnull=True,
            capability_code__in=_ORGANIZATION_NAVIGATION_CAPABILITIES,
        ).values_list("organization_id", "capability_code")
        for organization_id, capability_code in grants:
            capabilities_by_organization.setdefault(organization_id, set()).add(
                capability_code
            )

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
        evaluated_at = timezone.now()
        active_at = _active_scope_filter(evaluated_at)
        matching_scope = Q(edition__isnull=True) | Q(edition_id=OuterRef("pk"))
        active_assignments = RoleAssignment.objects.filter(
            active_at,
            matching_scope,
            principal=account,
            organization_id=OuterRef("organization_id"),
        )
        annotations: dict[str, Exists] = {
            "_maru_has_active_assignment": Exists(active_assignments),
        }
        authority_filter = Q(_maru_has_active_assignment=True)

        valid_grant_ids = _active_grant_ids_with_valid_chains(
            account,
            evaluated_at=evaluated_at,
            active_at=active_at,
        )
        if valid_grant_ids:
            active_grants = CapabilityGrant.objects.filter(
                matching_scope,
                id__in=valid_grant_ids,
                principal=account,
                organization_id=OuterRef("organization_id"),
            )
            annotations["_maru_has_active_grant"] = Exists(active_grants)
            authority_filter |= Q(_maru_has_active_grant=True)

        authorized_editions = editions.annotate(**annotations).filter(authority_filter)

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
    return {
        "available": True,
        "selected": selected_admin_edition(request),
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
