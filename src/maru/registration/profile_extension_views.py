"""Same-shell browser adapters for profile-extension value revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from maru.authorization.services import AuthorizationDenied
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.registration.models import Registration
from maru.registration.profile_extension_forms import (
    ProfileExtensionValueForm,
    StaffProfileExtensionValueForm,
)
from maru.registration.profile_extension_values import (
    ProfileExtensionValueError,
    ProfileExtensionValueEvidenceConflictError,
    ProfileExtensionValueFieldProjection,
    ProfileExtensionValueLimitExceededError,
    ProfileExtensionValueRetryConflictError,
    ProfileExtensionValueSequenceConflictError,
    ProfileExtensionValueUnavailableError,
    ProfileExtensionValueWorkspace,
    append_profile_extension_value,
    authorize_profile_extension_value_write_scope,
    read_profile_extension_values,
)


@dataclass(frozen=True, slots=True)
class ProfileExtensionValueEditor:
    field: ProfileExtensionValueFieldProjection
    form: ProfileExtensionValueForm | StaffProfileExtensionValueForm | None


def _request_id(request: HttpRequest) -> UUID:
    candidate = getattr(request, "correlation_id", None)
    if isinstance(candidate, str):
        try:
            return UUID(candidate)
        except ValueError:
            pass
    return uuid4()


def _active_person(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_authenticated:
        raise Http404
    actor = Account.objects.filter(
        id=request.user.id,
        is_active=True,
        account_kind=Account.Kind.PERSON,
    ).first()
    if actor is None:
        raise Http404
    return actor


def _private_no_store(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _plain_error(message: str, *, status: int) -> HttpResponse:
    return _private_no_store(HttpResponse(message, status=status))


def _owned_registration(*, actor: Account, edition_id: UUID) -> Registration:
    registration = (
        Registration.objects.select_related(
            "account",
            "organization",
            "edition",
            "edition__series",
        )
        .filter(account=actor, edition_id=edition_id)
        .first()
    )
    if registration is None:
        raise Http404
    return registration


def _staff_registration(
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    registration_id: UUID,
) -> Registration:
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(
            organization__slug=organization_slug,
            series__slug=series_slug,
            series__organization__slug=organization_slug,
            slug=edition_slug,
        )
        .first()
    )
    if edition is None:
        raise Http404
    registration = (
        Registration.objects.select_related("account", "organization", "edition")
        .filter(
            id=registration_id,
            organization_id=edition.organization_id,
            edition=edition,
        )
        .first()
    )
    if registration is None:
        raise Http404
    return registration


def _read_workspace(
    *,
    actor: Account,
    registration: Registration,
    correlation_id: UUID,
) -> ProfileExtensionValueWorkspace:
    return read_profile_extension_values(
        actor=actor,
        organization_id=registration.organization_id,
        edition_id=registration.edition_id,
        registration_id=registration.id,
        correlation_id=correlation_id,
        source_channel="web",
    )


def _projection_for_write(
    workspace: ProfileExtensionValueWorkspace,
    *,
    field_id: UUID,
) -> ProfileExtensionValueFieldProjection:
    projection = next(
        (field for field in workspace.fields if field.field_id == field_id),
        None,
    )
    if projection is None or not projection.can_write:
        raise Http404
    return projection


def _editors(
    workspace: ProfileExtensionValueWorkspace,
    *,
    staff: bool,
    bound_field_id: UUID | None = None,
    bound_form: (
        ProfileExtensionValueForm | StaffProfileExtensionValueForm | None
    ) = None,
) -> tuple[ProfileExtensionValueEditor, ...]:
    form_type = StaffProfileExtensionValueForm if staff else ProfileExtensionValueForm
    return tuple(
        ProfileExtensionValueEditor(
            field=field,
            form=(
                bound_form
                if field.field_id == bound_field_id
                else form_type(profile_field=field)
            )
            if field.can_write
            else None,
        )
        for field in workspace.fields
    )


def _self_response(
    request: HttpRequest,
    *,
    registration: Registration,
    workspace: ProfileExtensionValueWorkspace,
    status: int = 200,
    bound_field_id: UUID | None = None,
    bound_form: ProfileExtensionValueForm | None = None,
) -> HttpResponse:
    return _private_no_store(
        TemplateResponse(
            request,
            "registration/profile_extension_values_self.html",
            {
                "registration": registration,
                "profile_extension_workspace": workspace,
                "profile_extension_editors": _editors(
                    workspace,
                    staff=False,
                    bound_field_id=bound_field_id,
                    bound_form=bound_form,
                ),
            },
            status=status,
        )
    )


def _staff_response(
    request: HttpRequest,
    *,
    registration: Registration,
    workspace: ProfileExtensionValueWorkspace,
    status: int = 200,
    bound_field_id: UUID | None = None,
    bound_form: StaffProfileExtensionValueForm | None = None,
) -> HttpResponse:
    edition = registration.edition
    context = admin.site.each_context(request)
    context.update(
        {
            "has_permission": True,
            "maru_personal_surface": False,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "registration-profile-extension-values",
            "baseline_registration_navigation_current": True,
            "organization": registration.organization,
            "convention_series": edition.series,
            "edition": edition,
            "registration": registration,
            "profile_extension_workspace": workspace,
            "profile_extension_editors": _editors(
                workspace,
                staff=True,
                bound_field_id=bound_field_id,
                bound_form=bound_form,
            ),
        }
    )
    return _private_no_store(
        TemplateResponse(
            request,
            "registration/profile_extension_values_staff.html",
            context,
            status=status,
        )
    )


def _raise_unavailable(error: Exception) -> Never:
    raise Http404 from error


def _add_command_errors(
    form: ProfileExtensionValueForm | StaffProfileExtensionValueForm,
    error: ValidationError,
) -> None:
    if hasattr(error, "message_dict"):
        for field_name, messages in error.message_dict.items():
            target = field_name if field_name in form.fields else None
            for message in messages:
                form.add_error(target, message)
        return
    for message in error.messages:
        form.add_error(None, message)


def _append_or_render_error(
    *,
    request: HttpRequest,
    actor: Account,
    registration: Registration,
    workspace: ProfileExtensionValueWorkspace,
    projection: ProfileExtensionValueFieldProjection,
    form: ProfileExtensionValueForm | StaffProfileExtensionValueForm,
    staff: bool,
    correlation_id: UUID,
) -> HttpResponse | None:
    if not form.is_valid():
        responder = _staff_response if staff else _self_response
        return responder(
            request,
            registration=registration,
            workspace=workspace,
            status=400,
            bound_field_id=projection.field_id,
            bound_form=form,  # type: ignore[arg-type]
        )
    try:
        append_profile_extension_value(
            actor=actor,
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
            registration_id=registration.id,
            field_id=projection.field_id,
            value=form.cleaned_data["value"],
            expected_sequence=form.cleaned_data["expected_sequence"],
            retry_key=form.cleaned_data["retry_key"],
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
            reason=(str(form.cleaned_data["reason"]) if staff else ""),
        )
    except ValidationError as error:
        _add_command_errors(form, error)
        responder = _staff_response if staff else _self_response
        return responder(
            request,
            registration=registration,
            workspace=workspace,
            status=400,
            bound_field_id=projection.field_id,
            bound_form=form,  # type: ignore[arg-type]
        )
    except (
        ProfileExtensionValueSequenceConflictError,
        ProfileExtensionValueRetryConflictError,
        ProfileExtensionValueLimitExceededError,
    ):
        form.add_error(
            None,
            "This profile value changed or this retry key was already used. "
            "Reload before trying again.",
        )
        responder = _staff_response if staff else _self_response
        return responder(
            request,
            registration=registration,
            workspace=workspace,
            status=409,
            bound_field_id=projection.field_id,
            bound_form=form,  # type: ignore[arg-type]
        )
    except (AuthorizationDenied, ProfileExtensionValueUnavailableError) as error:
        _raise_unavailable(error)
    except (DatabaseError, ProfileExtensionValueEvidenceConflictError):
        return _plain_error(
            "Profile extensions are temporarily unavailable.",
            status=503,
        )
    return None


@never_cache
@login_required(login_url="staff-login")
@require_GET
def my_profile_extension_values(
    request: HttpRequest,
    edition_id: UUID,
) -> HttpResponse:
    if request.GET:
        return _plain_error("Unsupported query parameters.", status=400)
    actor = _active_person(request)
    registration = _owned_registration(actor=actor, edition_id=edition_id)
    try:
        workspace = _read_workspace(
            actor=actor,
            registration=registration,
            correlation_id=_request_id(request),
        )
    except (AuthorizationDenied, ProfileExtensionValueUnavailableError) as error:
        _raise_unavailable(error)
    except ProfileExtensionValueLimitExceededError:
        return _plain_error("Too many profile fields are available.", status=409)
    except (DatabaseError, ProfileExtensionValueError):
        return _plain_error(
            "Profile extensions are temporarily unavailable.",
            status=503,
        )
    return _self_response(
        request,
        registration=registration,
        workspace=workspace,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_my_profile_extension_value(
    request: HttpRequest,
    edition_id: UUID,
    field_id: UUID,
) -> HttpResponse:
    actor = _active_person(request)
    registration = _owned_registration(actor=actor, edition_id=edition_id)
    correlation_id = _request_id(request)
    try:
        authorize_profile_extension_value_write_scope(
            actor=actor,
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
            registration_id=registration.id,
            correlation_id=correlation_id,
            source_channel="web",
        )
        workspace = _read_workspace(
            actor=actor,
            registration=registration,
            correlation_id=correlation_id,
        )
        projection = _projection_for_write(workspace, field_id=field_id)
    except (AuthorizationDenied, ProfileExtensionValueUnavailableError) as error:
        _raise_unavailable(error)
    except (DatabaseError, ProfileExtensionValueError):
        return _plain_error(
            "Profile extensions are temporarily unavailable.",
            status=503,
        )
    form = ProfileExtensionValueForm(request.POST, profile_field=projection)
    response = _append_or_render_error(
        request=request,
        actor=actor,
        registration=registration,
        workspace=workspace,
        projection=projection,
        form=form,
        staff=False,
        correlation_id=correlation_id,
    )
    if response is not None:
        return response
    return _private_no_store(
        redirect(reverse("my-profile-extension-values", args=(edition_id,)))
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def staff_profile_extension_values(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    registration_id: UUID,
) -> HttpResponse:
    if request.GET:
        return _plain_error("Unsupported query parameters.", status=400)
    actor = _active_person(request)
    registration = _staff_registration(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        registration_id=registration_id,
    )
    try:
        workspace = _read_workspace(
            actor=actor,
            registration=registration,
            correlation_id=_request_id(request),
        )
    except (AuthorizationDenied, ProfileExtensionValueUnavailableError) as error:
        _raise_unavailable(error)
    except ProfileExtensionValueLimitExceededError:
        return _plain_error("Too many profile fields are available.", status=409)
    except (DatabaseError, ProfileExtensionValueError):
        return _plain_error(
            "Profile extensions are temporarily unavailable.",
            status=503,
        )
    return _staff_response(
        request,
        registration=registration,
        workspace=workspace,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_staff_profile_extension_value(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    registration_id: UUID,
    field_id: UUID,
) -> HttpResponse:
    actor = _active_person(request)
    registration = _staff_registration(
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        registration_id=registration_id,
    )
    correlation_id = _request_id(request)
    try:
        authorize_profile_extension_value_write_scope(
            actor=actor,
            organization_id=registration.organization_id,
            edition_id=registration.edition_id,
            registration_id=registration.id,
            correlation_id=correlation_id,
            source_channel="web",
        )
        workspace = _read_workspace(
            actor=actor,
            registration=registration,
            correlation_id=correlation_id,
        )
        projection = _projection_for_write(workspace, field_id=field_id)
    except (AuthorizationDenied, ProfileExtensionValueUnavailableError) as error:
        _raise_unavailable(error)
    except (DatabaseError, ProfileExtensionValueError):
        return _plain_error(
            "Profile extensions are temporarily unavailable.",
            status=503,
        )
    form = StaffProfileExtensionValueForm(request.POST, profile_field=projection)
    response = _append_or_render_error(
        request=request,
        actor=actor,
        registration=registration,
        workspace=workspace,
        projection=projection,
        form=form,
        staff=True,
        correlation_id=correlation_id,
    )
    if response is not None:
        return response
    return _private_no_store(
        redirect(
            reverse(
                "staff-profile-extension-values",
                kwargs={
                    "organization_slug": organization_slug,
                    "series_slug": series_slug,
                    "edition_slug": edition_slug,
                    "registration_id": registration_id,
                },
            )
        )
    )


__all__ = [
    "my_profile_extension_values",
    "staff_profile_extension_values",
    "update_my_profile_extension_value",
    "update_staff_profile_extension_value",
]
