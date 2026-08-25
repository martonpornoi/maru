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
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from maru.activity.queries import record_activity
from maru.applications.readiness import applications_database_integrity_is_ready
from maru.authorization.database_role_safety import (
    RuntimeDatabaseRoleProbeError,
    probe_runtime_database_role_safety,
)
from maru.authorization.models import (
    AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
    AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
    AUTHORITY_PROVENANCE_INACTIVE_GENERATION,
)
from maru.authorization.policy import (
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.provenance_readiness import (
    authority_provenance_runtime_contract_is_ready,
)
from maru.authorization.services import AuthorizationDenied
from maru.catalog.readiness import catalog_database_integrity_is_ready
from maru.charities.readiness import charities_database_integrity_is_ready
from maru.core.forms import StrictInputForm
from maru.core.navigation import destination_code_is_supported
from maru.events.admin_context import (
    ADMIN_EDITION_SESSION_KEY,
    admin_shell_access,
    authorized_admin_edition_for_route,
    authorized_admin_organization_ids,
    has_active_admin_scope,
    selected_admin_edition,
)
from maru.events.forms import EventEditionCreationForm, EventEditionUpdateForm
from maru.events.models import EventEdition
from maru.events.services import (
    EDITION_PROFILE_EDITABLE_LIFECYCLES,
    create_event_edition,
    update_event_edition,
)
from maru.identity.invitation_readiness import (
    platform_invitation_runtime_contract_is_ready,
)
from maru.identity.models import Account
from maru.identity.navigation_preferences import (
    pin_navigation_destination,
    unpin_navigation_destination,
)
from maru.logistics.readiness import logistics_current_session_is_ready
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
from maru.venues.readiness import venues_database_integrity_is_ready

logger = logging.getLogger(__name__)

_EXACT_AUTHORITY_PROVENANCE_POSTGRESQL_MAJOR = 17
_AUTHORITY_PROVENANCE_TABLE_HEALTH_QUERY = """
SELECT
    pg_catalog.to_regclass(
        'public.authorization_authorityprovenanceactivation'
    ) IS NOT NULL,
    pg_catalog.to_regclass(
        'public.authorization_provenanceactivationlatch'
    ) IS NOT NULL
"""
_DORMANT_AUTHORITY_PROVENANCE_HEALTH_QUERY = """
SELECT
    NOT EXISTS (
        SELECT 1
        FROM public.authorization_authorityprovenanceactivation
    ),
    (
        SELECT COUNT(*) = 1
           AND COUNT(*) FILTER (
               WHERE latch.singleton IS TRUE
                 AND latch.generation = %s
           ) = 1
        FROM public.authorization_provenanceactivationlatch AS latch
    )
"""
_EXACT_AUTHORITY_PROVENANCE_HEALTH_QUERY = """
SELECT
    pg_catalog.current_setting('server_version_num')::integer / 10000,
    pg_catalog.has_database_privilege(
        CURRENT_USER,
        pg_catalog.current_database(),
        'TEMPORARY'
    ),
    (pg_catalog.current_schemas(TRUE))[1:2]
        = ARRAY['pg_catalog', 'public']::name[],
    EXISTS (
        SELECT 1
        FROM public.authorization_provenanceactivationlatch AS latch
        WHERE latch.singleton IS TRUE
          AND latch.generation = %s
    ),
    EXISTS (
        SELECT 1
        FROM public.authorization_authorityprovenanceactivation AS activation
        WHERE activation.singleton IS TRUE
          AND activation.contract_version = %s
          AND activation.policy_version = %s
    )
"""

_BASELINE_PAGE_PRESENTATION = {
    "core/baseline_admin_home.html": ("platform-administration-home", ""),
    "core/baseline_create_organization.html": (
        "create-organization",
        "baseline-page--form",
    ),
    "core/baseline_organization_record.html": (
        "organization-record",
        "baseline-page--form",
    ),
    "core/baseline_create_convention_series.html": (
        "create-convention-series",
        "baseline-page--form",
    ),
    "core/baseline_convention_series_record.html": (
        "convention-series-record",
        "baseline-page--form",
    ),
    "core/baseline_create_event_edition.html": (
        "create-event-edition",
        "baseline-page--form",
    ),
    "core/baseline_event_edition_record.html": (
        "event-edition-record",
        "baseline-page--form",
    ),
}


def _require_platform_administrator(request: HttpRequest) -> Account:
    if (
        not isinstance(request.user, Account)
        or not request.user.is_active
        or not request.user.is_platform_administrator
    ):
        raise PermissionDenied
    return request.user


def _active_account(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise PermissionDenied
    return request.user


def _require_possible_organization_authority(
    request: HttpRequest,
    actor: Account,
) -> None:
    """Fail before tenant lookup when an account has no active scoped authority.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    if actor.is_platform_administrator:
        return
    if has_active_admin_scope(request):
        return
    raise PermissionDenied


def _can(
    *,
    actor: Account,
    organization_id: UUID,
    capability_code: str,
    edition_id: UUID | None = None,
) -> bool:
    return decide(
        principal=actor,
        capability_code=capability_code,
        resource=(
            resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            if edition_id is not None
            else resolve_organization_target(organization_id=organization_id)
        ),
    ).allowed


def _require_capability(
    *,
    actor: Account,
    organization_id: UUID,
    capability_code: str,
    edition_id: UUID | None = None,
) -> None:
    if not _can(
        actor=actor,
        organization_id=organization_id,
        capability_code=capability_code,
        edition_id=edition_id,
    ):
        raise PermissionDenied


def _baseline_page_response(
    request: HttpRequest,
    template_name: str,
    context: dict[str, Any] | None = None,
    *,
    status: int = 200,
) -> TemplateResponse:
    """Render a workflow in the canonical admin shell or isolated test shell.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    template_name : str
        The human-readable template name shown to authorized readers.
    context : dict[str, Any] | None, default=None
        The request context supplied by the calling framework.
    status : int, default=200
        The closed status value to evaluate or expose.

    Returns
    -------
    TemplateResponse
        The HTTP response for the requested operation.
    """
    use_admin_shell = request.path_info.startswith("/admin/platform/")
    page_id, page_class = _BASELINE_PAGE_PRESENTATION[template_name]
    template_context = admin.site.each_context(request) if use_admin_shell else {}
    template_context.update(context or {})
    if use_admin_shell:
        template_context["has_permission"] = True
    organization = template_context.get("organization")
    edition = template_context.get("edition")
    actor = request.user
    if isinstance(organization, Organization) and isinstance(actor, Account):
        template_context.setdefault(
            "baseline_can_view_organization",
            _can(
                actor=actor,
                organization_id=organization.id,
                capability_code="organizations.view_basic",
            ),
        )
        template_context.setdefault(
            "baseline_can_manage_representation",
            _can(
                actor=actor,
                organization_id=organization.id,
                capability_code="organizations.manage_representation",
            ),
        )
        template_context.setdefault(
            "baseline_can_create_series",
            _can(
                actor=actor,
                organization_id=organization.id,
                capability_code="organizations.create_series",
            ),
        )
        template_context.setdefault(
            "baseline_can_create_edition",
            _can(
                actor=actor,
                organization_id=organization.id,
                capability_code="events.create",
            ),
        )
        if isinstance(edition, EventEdition):
            template_context.setdefault(
                "baseline_can_view_edition",
                _can(
                    actor=actor,
                    organization_id=organization.id,
                    capability_code="events.view_basic",
                    edition_id=edition.id,
                ),
            )
            template_context.setdefault(
                "baseline_can_view_structure",
                _can(
                    actor=actor,
                    organization_id=organization.id,
                    capability_code="workforce.view_structure",
                    edition_id=edition.id,
                ),
            )
            template_context.setdefault(
                "baseline_can_manage_structure",
                _can(
                    actor=actor,
                    organization_id=organization.id,
                    capability_code="workforce.manage_structure",
                    edition_id=edition.id,
                ),
            )
            template_context.setdefault(
                "baseline_can_manage_registration",
                _can(
                    actor=actor,
                    organization_id=organization.id,
                    capability_code="registration.manage_configuration",
                    edition_id=edition.id,
                ),
            )
    template_context.update(
        {
            "baseline_admin_parent_template": (
                "admin/base_site.html"
                if use_admin_shell
                else "core/baseline_admin_standalone.html"
            ),
            "baseline_page_class": page_class,
            "baseline_page_id": page_id,
            "baseline_use_admin_shell": use_admin_shell,
        }
    )
    return TemplateResponse(
        request,
        template_name,
        template_context,
        status=status,
    )


def baseline_root(request: HttpRequest) -> HttpResponse:
    """Send the deliberately empty browser experience to its only home.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    del request
    return redirect("baseline-admin-home")


@login_required(login_url="staff-login")
def baseline_administration_home(request: HttpRequest) -> HttpResponse:
    """Render the platform-wide organization inventory for its administrators.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
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

    return _baseline_page_response(
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
    """Create the minimum draft organization record for later completion.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
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

    return _baseline_page_response(
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


def _organization_for_authorized_route(
    *,
    request: HttpRequest,
    actor: Account,
    slug: str,
    capability_code: str,
) -> Organization:
    """Resolve non-platform routes only inside the actor's possible scope.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    actor : Account
        The authenticated account authorizing the operation.
    slug : str
        The stable URL slug identifying the slug.
    capability_code : str
        The stable capability code required by the operation.

    Returns
    -------
    Organization
        The resolved Organization for organization for authorized route.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    if actor.is_platform_administrator:
        return _organization_for_record(slug)
    candidate_ids = authorized_admin_organization_ids(
        request,
        capability_codes=frozenset({capability_code}),
    )
    organization = (
        Organization.objects.filter(
            id__in=candidate_ids,
            slug__iexact=slug,
        )
        .order_by("id")
        .first()
    )
    if organization is None:
        raise PermissionDenied
    return organization


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
    """Render and update one organization profile without changing its identity.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_account(request)
    _require_possible_organization_authority(request, actor)
    try:
        organization = _organization_for_authorized_route(
            request=request,
            actor=actor,
            slug=organization_slug,
            capability_code="organizations.view_basic",
        )
        _require_capability(
            actor=actor,
            organization_id=organization.id,
            capability_code="organizations.view_basic",
        )
        series = _series_for_organization(organization)
    except DatabaseError:
        logger.exception("Unable to load the organization record")
        return _baseline_page_response(
            request,
            "core/baseline_organization_record.html",
            {"organization_record_load_failed": True},
            status=503,
        )

    editable = _can(
        actor=actor,
        organization_id=organization.id,
        capability_code="organizations.change_profile",
    )
    can_create_series = _can(
        actor=actor,
        organization_id=organization.id,
        capability_code="organizations.create_series",
    )
    if request.method == "POST" and not editable:
        raise PermissionDenied
    form = (
        OrganizationCreationForm.for_organization(
            organization,
            data=request.POST if request.method == "POST" else None,
        )
        if editable
        else None
    )
    deletion_form = (
        OrganizationDeletionForm(organization=organization)
        if actor.is_platform_administrator
        else None
    )
    status = 200
    if request.method == "POST" and form is not None and form.is_valid():
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

    return _baseline_page_response(
        request,
        "core/baseline_organization_record.html",
        {
            "organization": organization,
            "series": series,
            "form": form,
            "deletion_form": deletion_form,
            "organization_editable": editable,
            "can_create_series": can_create_series,
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
    """Delete one confirmed, empty Draft organization.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    actor = _require_platform_administrator(request)
    try:
        organization = _organization_for_record(organization_slug)
        series = _series_for_organization(organization)
    except DatabaseError:
        logger.exception("Unable to load the organization for deletion")
        return _baseline_page_response(
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

    return _baseline_page_response(
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
    """Create one recurring convention identity beneath an organization.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    actor = _active_account(request)
    _require_possible_organization_authority(request, actor)
    try:
        organization = _organization_for_authorized_route(
            request=request,
            actor=actor,
            slug=organization_slug,
            capability_code="organizations.create_series",
        )
        _require_capability(
            actor=actor,
            organization_id=organization.id,
            capability_code="organizations.create_series",
        )
    except DatabaseError:
        logger.exception("Unable to load the organization for series creation")
        return _baseline_page_response(
            request,
            "core/baseline_create_convention_series.html",
            {"series_creation_load_failed": True},
            status=503,
        )

    if organization.lifecycle == Organization.Lifecycle.CLOSED:
        return _baseline_page_response(
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

    return _baseline_page_response(
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
    """Render and update one scoped recurring convention brand.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_account(request)
    _require_possible_organization_authority(request, actor)
    try:
        organization = _organization_for_authorized_route(
            request=request,
            actor=actor,
            slug=organization_slug,
            capability_code="organizations.view_basic",
        )
        _require_capability(
            actor=actor,
            organization_id=organization.id,
            capability_code="organizations.view_basic",
        )
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
        return _baseline_page_response(
            request,
            "core/baseline_convention_series_record.html",
            {"series_record_load_failed": True},
            status=503,
        )

    can_change_series = _can(
        actor=actor,
        organization_id=organization.id,
        capability_code="organizations.change_series",
    )
    editable = (
        organization.lifecycle != Organization.Lifecycle.CLOSED and can_change_series
    )
    can_create_edition = _can(
        actor=actor,
        organization_id=organization.id,
        capability_code="events.create",
    )
    if request.method == "POST" and not can_change_series:
        raise PermissionDenied
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

    return _baseline_page_response(
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
            "can_create_edition": can_create_edition,
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
    """Create one Draft edition beneath an exact organization-owned series.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_account(request)
    _require_possible_organization_authority(request, actor)
    try:
        organization = _organization_for_authorized_route(
            request=request,
            actor=actor,
            slug=organization_slug,
            capability_code="events.create",
        )
        _require_capability(
            actor=actor,
            organization_id=organization.id,
            capability_code="events.create",
        )
        series = _series_for_record(organization, series_slug)
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to load the parent series for edition creation")
        return _baseline_page_response(
            request,
            "core/baseline_create_event_edition.html",
            {"edition_creation_load_failed": True},
            status=503,
        )

    blocked = (
        organization.lifecycle == Organization.Lifecycle.CLOSED or not series.is_active
    )
    if blocked:
        return _baseline_page_response(
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

    return _baseline_page_response(
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
    """Render and update one exact edition record and its human activity.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_account(request)
    _require_possible_organization_authority(request, actor)
    try:
        organization, series, edition = authorized_admin_edition_for_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            capability_code="events.view_basic",
        )
        _require_capability(
            actor=actor,
            organization_id=organization.id,
            capability_code="events.view_basic",
            edition_id=edition.id,
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
        return _baseline_page_response(
            request,
            "core/baseline_event_edition_record.html",
            {"edition_record_load_failed": True},
            status=503,
        )

    can_change_edition = _can(
        actor=actor,
        organization_id=organization.id,
        capability_code="events.change_profile",
        edition_id=edition.id,
    )
    editable = (
        organization.lifecycle != Organization.Lifecycle.CLOSED
        and edition.lifecycle in EDITION_PROFILE_EDITABLE_LIFECYCLES
        and can_change_edition
    )
    if request.method == "POST" and not can_change_edition:
        raise PermissionDenied
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

    return _baseline_page_response(
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
    """Reject undeclared context-action input without changing the session.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.

    Returns
    -------
    HttpResponse | None
        The HTTP response for the requested operation.
    """
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
    """Persist one already authorized exact route chain as display context.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    actor = _active_account(request)
    _require_possible_organization_authority(request, actor)
    input_error = _context_action_input_error_response(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    if input_error is not None:
        return input_error
    try:
        organization, series, edition = authorized_admin_edition_for_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            capability_code="events.view_basic",
        )
        _require_capability(
            actor=actor,
            organization_id=organization.id,
            capability_code="events.view_basic",
            edition_id=edition.id,
        )
        request.session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
        messages.success(request, f"Working edition changed to {edition.name}.")
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to select the working event edition")
        return _baseline_page_response(
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
    """Clear display context without changing edition records or authority.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    organization_slug : str
        The stable URL slug identifying the organization.
    series_slug : str
        The stable URL slug identifying the series.
    edition_slug : str
        The stable URL slug identifying the edition.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    actor = _active_account(request)
    _require_possible_organization_authority(request, actor)
    input_error = _context_action_input_error_response(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    if input_error is not None:
        return input_error
    try:
        organization, series, edition = authorized_admin_edition_for_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            capability_code="events.view_basic",
        )
        _require_capability(
            actor=actor,
            organization_id=organization.id,
            capability_code="events.view_basic",
            edition_id=edition.id,
        )
        request.session.pop(ADMIN_EDITION_SESSION_KEY, None)
        messages.success(request, "Working edition cleared.")
    except (DatabaseError, RuntimeError):
        logger.exception("Unable to clear the working event edition")
        return _baseline_page_response(
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
    """Render platform home.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    TemplateResponse
        The HTTP response for this request.
    """
    return TemplateResponse(
        request,
        "core/home.html",
        {
            "build_version": settings.BUILD_VERSION,
        },
    )


@login_required(login_url="staff-login")
@ensure_csrf_cookie
def my_maru_home(request: HttpRequest) -> TemplateResponse:
    """Serve the focused personal surface inside Maru's shared visual shell.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    TemplateResponse
        The HTTP response for the requested operation.
    """
    actor = _active_account(request)
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "My Maru",
            "has_permission": True,
            "maru_personal_surface": True,
            "maru_shell_access": admin_shell_access(request),
            "has_management_access": bool(
                has_active_admin_scope(request) or actor.is_staff
            ),
        }
    )
    return TemplateResponse(request, "core/my_maru.html", context)


def _safe_navigation_return_path(request: HttpRequest) -> str:
    candidate = request.POST.get("next", "")
    if candidate.startswith(("/admin/", "/my/")) and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("my-maru-home")


@login_required(login_url="staff-login")
@require_POST
def update_navigation_pin(request: HttpRequest) -> HttpResponse:
    """Change only the caller's preference; destinations remain policy-owned.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
    actor = _active_account(request)
    if set(request.POST) - {
        "csrfmiddlewaretoken",
        "destination_code",
        "action",
        "next",
    }:
        raise Http404
    destination_code = request.POST.get("destination_code", "").strip()
    action = request.POST.get("action", "").strip()
    if not destination_code_is_supported(destination_code) or action not in {
        "pin",
        "unpin",
    }:
        raise Http404
    try:
        if action == "pin":
            pin_navigation_destination(
                account=actor,
                destination_code=destination_code,
            )
            messages.success(request, "Navigation shortcut pinned.")
        else:
            unpin_navigation_destination(
                account=actor,
                destination_code=destination_code,
            )
            messages.success(request, "Navigation shortcut unpinned.")
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect(_safe_navigation_return_path(request))


@login_required(login_url="staff-login")
@ensure_csrf_cookie
def administration_index(request: HttpRequest) -> HttpResponse:
    """Serve a policy-filtered home without granting Django staff status.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.
    """
    actor = _active_account(request)
    extra_context: dict[str, Any] = {
        "has_permission": True,
        "maru_shell_access": admin_shell_access(request),
    }
    if not actor.is_staff:
        extra_context.update({"app_list": (), "available_apps": ()})
    return admin.site.index(
        request,
        extra_context=extra_context,
    )


@login_required(login_url="staff-login")
@ensure_csrf_cookie
def administration_workspace(request: HttpRequest) -> HttpResponse:
    """Serve API-backed workflows inside the Django administration shell.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    _active_account(request)
    if not has_active_admin_scope(request):
        raise PermissionDenied
    selected_edition = selected_admin_edition(request)
    context = admin.site.each_context(request)
    context["has_permission"] = True
    return TemplateResponse(
        request,
        "core/admin_workspace.html",
        {
            **context,
            "title": "Convention work",
            "maru_shell_access": admin_shell_access(request),
            "maru_shell_access_rendered_by_page": True,
            "selected_admin_edition_id": (
                str(selected_edition.id) if selected_edition is not None else ""
            ),
        },
    )


def removed_administration_route(request: HttpRequest) -> HttpResponse:
    """Keep retired administration entry points from becoming login redirects.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    HttpResponse
        The HTTP response for the requested operation.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    """
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
    """Render liveness.

    Parameters
    ----------
    request : Request
        The incoming HTTP request.

    Returns
    -------
    Response
        The HTTP response for this request.
    """
    del request
    return Response({"status": "ok"})


def _append_invitation_runtime_readiness(dependencies: dict[str, str]) -> bool:
    """Append one value-safe account-onboarding dependency when required.

    Parameters
    ----------
    dependencies : dict[str, str]
        The dependencies mapping to validate or transform.

    Returns
    -------
    bool
        `True` when one account-onboarding dependency was appended when
        requires it; otherwise `False`.
    """
    if not bool(getattr(settings, "IDENTITY_INVITATION_ENCRYPTION_REQUIRED", False)):
        return True
    try:
        ready = platform_invitation_runtime_contract_is_ready()
    except (DatabaseError, TypeError, ValueError):
        ready = False
    dependencies["identity_invitations"] = "ok" if ready else "unavailable"
    return ready


def _append_logistics_runtime_readiness(dependencies: dict[str, str]) -> bool:
    """Append the fail-closed Logistics catalog and current-session gate.

    Parameters
    ----------
    dependencies : dict[str, str]
        The dependencies mapping to validate or transform.

    Returns
    -------
    bool
        `True` when Append the fail-closed Logistics catalog and current-session
        gate; otherwise `False`.
    """
    try:
        ready = logistics_current_session_is_ready()
    except (
        DatabaseError,
        RuntimeDatabaseRoleProbeError,
        LookupError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        ready = False
    dependencies["logistics"] = "ok" if ready else "unavailable"
    return ready


def _append_bounded_domain_integrity_readiness(
    dependencies: dict[str, str],
) -> bool:
    """Append value-safe integrity gates for the four mounted bounded contexts.

    Parameters
    ----------
    dependencies : dict[str, str]
        The dependencies mapping to validate or transform.

    Returns
    -------
    bool
        `True` when Append value-safe integrity gates for the four mounted
        bounded contexts; otherwise `False`.
    """
    probes = (
        ("applications_integrity", applications_database_integrity_is_ready),
        ("charities_integrity", charities_database_integrity_is_ready),
        ("catalog_integrity", catalog_database_integrity_is_ready),
        ("venues_integrity", venues_database_integrity_is_ready),
    )
    results: list[bool] = []
    for status_key, probe in probes:
        try:
            ready = probe()
        except (
            DatabaseError,
            LookupError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            ready = False
        dependencies[status_key] = "ok" if ready else "unavailable"
        results.append(ready)
    return all(results)


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
    """Render readiness.

    Parameters
    ----------
    request : Request
        The incoming HTTP request.

    Returns
    -------
    Response
        The HTTP response for this request.
    """
    del request
    require_exact_provenance = settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE
    try:
        with connection.cursor() as cursor:
            cursor.execute(_AUTHORITY_PROVENANCE_TABLE_HEALTH_QUERY)
            provenance_tables = cursor.fetchone()
    except DatabaseError:
        return Response(
            {"status": "unavailable", "dependencies": {"database": "unavailable"}},
            status=503,
        )
    dependencies = {"database": "ok"}
    authority_provenance_ready = False
    if not require_exact_provenance:
        if provenance_tables == (False, False):
            authority_provenance_ready = True
        elif provenance_tables == (True, True):
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        _DORMANT_AUTHORITY_PROVENANCE_HEALTH_QUERY,
                        (AUTHORITY_PROVENANCE_INACTIVE_GENERATION,),
                    )
                    dormant_contract = cursor.fetchone()
            except DatabaseError:
                dormant_contract = None
            authority_provenance_ready = dormant_contract == (True, True)
    elif provenance_tables == (True, True):
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    _EXACT_AUTHORITY_PROVENANCE_HEALTH_QUERY,
                    (
                        AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
                        AUTHORITY_PROVENANCE_CONTRACT_VERSION,
                        AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
                    ),
                )
                exact_contract_row = cursor.fetchone()
        except DatabaseError:
            exact_contract_row = None
        exact_contract_ready = exact_contract_row == (
            _EXACT_AUTHORITY_PROVENANCE_POSTGRESQL_MAJOR,
            False,
            True,
            True,
            True,
        )
        runtime_role_safe = False
        runtime_contract_ready = False
        if exact_contract_ready:
            runtime_contract_ready = authority_provenance_runtime_contract_is_ready()
        if exact_contract_ready and runtime_contract_ready:
            try:
                runtime_role_safe = probe_runtime_database_role_safety(
                    role_name=settings.RUNTIME_DATABASE_ROLE
                ).current_session_is_safe
            except (DatabaseError, RuntimeDatabaseRoleProbeError):
                runtime_role_safe = False
        authority_provenance_ready = (
            exact_contract_ready and runtime_contract_ready and runtime_role_safe
        )
    if not authority_provenance_ready:
        dependencies["authority_provenance"] = "unavailable"
        return Response(
            {"status": "unavailable", "dependencies": dependencies},
            status=503,
        )
    if require_exact_provenance:
        dependencies["authority_provenance"] = "ok"

    invitation_ready = _append_invitation_runtime_readiness(dependencies)
    bounded_domains_ready = _append_bounded_domain_integrity_readiness(dependencies)
    logistics_ready = _append_logistics_runtime_readiness(dependencies)
    all_dependencies_ready = (
        invitation_ready and bounded_domains_ready and logistics_ready
    )
    return Response(
        {
            "status": "ok" if all_dependencies_ready else "unavailable",
            "dependencies": dependencies,
        },
        status=200 if all_dependencies_ready else 503,
    )


def build_info(request: HttpRequest) -> JsonResponse:
    """Build info.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.

    Returns
    -------
    JsonResponse
        The HTTP response for this request.
    """
    del request
    payload: dict[str, Any] = {
        "service": "maru",
        "version": settings.BUILD_VERSION,
        "commit": settings.BUILD_COMMIT,
    }
    return JsonResponse(payload)
