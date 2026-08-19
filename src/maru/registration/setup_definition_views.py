"""Same-shell HTML adapters for governed Page 10 definition commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
    QueryDict,
)
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from maru.events.models import EventEdition
from maru.organizations.models import Organization
from maru.registration.models import ProfileExtensionStatus
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupCommandError,
    RegistrationSetupDependencyError,
)
from maru.registration.setup_definition_commands import (
    RegistrationSetupMinorPolicyUnavailableError,
    RegistrationSetupProductDependencyError,
    RegistrationSetupProductUnavailableError,
    RegistrationSetupProfileFieldImmutableError,
    RegistrationSetupProfileFieldUnavailableError,
    RegistrationSetupQuestionDependencyError,
    RegistrationSetupQuestionUnavailableError,
    create_admission_product,
    create_registration_profile_extension_field,
    create_registration_question,
    delete_admission_product,
    delete_registration_question,
    move_admission_product,
    move_registration_profile_extension_field,
    move_registration_question,
    remove_minor_registration_policy,
    retire_registration_profile_extension_field,
    set_minor_registration_policy,
    update_admission_product,
    update_registration_profile_extension_field,
    update_registration_question,
)
from maru.registration.setup_forms import (
    RegistrationDefinitionDeleteForm,
    RegistrationMinorPolicyForm,
    RegistrationProductCreateForm,
    RegistrationProductMoveForm,
    RegistrationProductUpdateForm,
    RegistrationProfileFieldCreateForm,
    RegistrationProfileFieldMoveForm,
    RegistrationProfileFieldUpdateForm,
    RegistrationQuestionCreateForm,
    RegistrationQuestionMoveForm,
    RegistrationQuestionUpdateForm,
)
from maru.registration.setup_views import (
    _active_account,
    _add_domain_validation_errors,
    _base_context,
    _command_conflict_message,
    _configuration_for_route,
    _configuration_location,
    _definition_choices,
    _definition_predecessor,
    _load_registration_page,
    _preflight_post,
    _private_no_store,
    _registration_bad_request,
    _registration_dependency_failure,
    _registration_response,
    _RegistrationPostQueryParametersUnsupportedError,
    _RegistrationSetupPageRead,
    _reload_required,
    _request_id,
    _route_kwargs,
)
from maru.workforce.models import Department

if TYPE_CHECKING:
    from uuid import UUID

    from django import forms

    from maru.identity.models import Account
    from maru.registration.setup_queries import (
        RegistrationSetupProductProjection,
        RegistrationSetupProfileFieldProjection,
        RegistrationSetupQuestionProjection,
    )

HTTP_CONFLICT = 409


@dataclass(frozen=True, slots=True)
class _ProfileFieldEditor:
    field: RegistrationSetupProfileFieldProjection
    ordinal: int
    update_form: RegistrationProfileFieldUpdateForm | None
    move_form: RegistrationProfileFieldMoveForm | None
    retire_form: RegistrationDefinitionDeleteForm | None


def _question_by_id(
    read: _RegistrationSetupPageRead,
    question_id: UUID,
) -> tuple[RegistrationSetupQuestionProjection, int]:
    for ordinal, question in enumerate(read.workspace.questions, start=1):
        if question.id == question_id:
            return question, ordinal
    raise Http404


def _product_by_id(
    read: _RegistrationSetupPageRead,
    product_id: UUID,
) -> tuple[RegistrationSetupProductProjection, int]:
    for ordinal, product in enumerate(read.workspace.products, start=1):
        if product.id == product_id:
            return product, ordinal
    raise Http404


def _profile_field_by_id(
    read: _RegistrationSetupPageRead,
    field_id: UUID,
) -> tuple[RegistrationSetupProfileFieldProjection, int]:
    for ordinal, field in enumerate(read.workspace.profile_fields, start=1):
        if field.id == field_id:
            return field, ordinal
    raise Http404


def _question_create_form(
    read: _RegistrationSetupPageRead,
    *,
    data: QueryDict | None = None,
) -> RegistrationQuestionCreateForm:
    return RegistrationQuestionCreateForm(
        data,
        section_choices=tuple(
            (str(section.id), section.title) for section in read.workspace.sections
        ),
        question_choices=_definition_choices(
            read.workspace.questions,
            label_attribute="label",
        ),
        condition_choices=tuple(
            (question.key, question.label) for question in read.workspace.questions
        ),
        expected_version=read.workspace.aggregate_version,
        initial={
            "field_type": "short_text",
            "classification": "C2",
            "required": "false",
            "visibility": "attendee_and_staff",
            "after_question_id": (
                str(read.workspace.questions[-1].id) if read.workspace.questions else ""
            ),
        },
    )


def _product_create_form(
    read: _RegistrationSetupPageRead,
    *,
    data: QueryDict | None = None,
) -> RegistrationProductCreateForm:
    return RegistrationProductCreateForm(
        data,
        placement_choices=_definition_choices(
            read.workspace.products,
            label_attribute="name",
        ),
        capacity_code_choices=tuple(
            (code, code) for code in read.workspace.active_capacity_codes
        ),
        edition_time_zone=read.edition.time_zone,
        expected_version=read.workspace.aggregate_version,
        initial={
            "waitlist_enabled": "true",
            "after_product_id": (
                str(read.workspace.products[-1].id) if read.workspace.products else ""
            ),
        },
    )


def _profile_department_choices(
    read: _RegistrationSetupPageRead,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(department.id), department.name)
        for department in Department.objects.filter(
            organization=read.organization,
            edition=read.edition,
            retired_at__isnull=True,
        ).order_by("display_order", "name", "id")
    )


def _profile_create_form(
    read: _RegistrationSetupPageRead,
    *,
    data: QueryDict | None = None,
) -> RegistrationProfileFieldCreateForm:
    prior_ids: set[UUID] = set()
    prior_choices: list[tuple[str, str]] = []
    for source in read.workspace.prior_configurations:
        if source.source_edition_id is None or source.source_edition_id in prior_ids:
            continue
        prior_ids.add(source.source_edition_id)
        prior_choices.append(
            (str(source.source_edition_id), source.source_edition_name)
        )
    draft_fields = tuple(
        field
        for field in read.workspace.profile_fields
        if field.status == ProfileExtensionStatus.DRAFT
    )
    return RegistrationProfileFieldCreateForm(
        data,
        template_choices=tuple(
            (str(source.source_id), f"{source.name} v{source.version}")
            for source in read.workspace.published_templates
        ),
        prior_edition_choices=tuple(prior_choices),
        placement_choices=_definition_choices(
            draft_fields,
            label_attribute="label",
        ),
        department_choices=_profile_department_choices(read),
        expected_version=read.workspace.aggregate_version,
        initial={
            "field_type": "short_text",
            "classification": "C2",
            "required": "false",
            "audience_policy": "self",
            "audience_department_id": "",
            "writer_policy": "attendee_and_staff",
            "after_field_id": str(draft_fields[-1].id) if draft_fields else "",
        },
    )


def _render_definition_form(
    request: HttpRequest,
    *,
    read: _RegistrationSetupPageRead,
    form: forms.Form,
    title: str,
    heading: str,
    intro: str,
    submit_label: str,
    back_location: str,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> HttpResponse:
    action_location = request.path
    configuration = read.workspace.current_configuration
    if not form.is_bound and isinstance(form, RegistrationQuestionCreateForm):
        if configuration is None:
            raise Http404
        action_location = reverse(
            "create-registration-setup-question",
            kwargs={
                **_route_kwargs(read),
                "configuration_id": configuration.id,
            },
        )
    elif not form.is_bound and isinstance(form, RegistrationProductCreateForm):
        if configuration is None:
            raise Http404
        action_location = reverse(
            "create-registration-setup-product",
            kwargs={
                **_route_kwargs(read),
                "configuration_id": configuration.id,
            },
        )
    elif not form.is_bound and isinstance(form, RegistrationProfileFieldCreateForm):
        action_location = reverse(
            "registration-setup-profile-fields",
            kwargs=_route_kwargs(read),
        )
    context = _base_context(request, read=read, page_id="registration-definition")
    if back_location == _profile_location(read):
        context.update(
            {
                "registration_mutations_allowed": _profile_mutations_allowed(read),
                "registration_mutation_blocked_reason": (
                    _profile_mutation_blocked_reason(read)
                ),
            }
        )
    context.update(
        {
            "title": title,
            "form": form,
            "definition_heading": heading,
            "definition_intro": intro,
            "definition_submit_label": submit_label,
            "definition_back_location": back_location,
            "definition_action_location": action_location,
            "show_submitted_form": form.is_bound,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_definition_form.html",
        context=context,
        status=status,
    )


def _load_get(
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> tuple[Account, _RegistrationSetupPageRead]:
    actor = _active_account(request)
    return actor, _load_registration_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )


def _profile_location(read: _RegistrationSetupPageRead) -> str:
    return reverse("registration-setup-profile-fields", kwargs=_route_kwargs(read))


def _profile_mutations_allowed(read: _RegistrationSetupPageRead) -> bool:
    return bool(
        read.workspace.aggregate_version > 0
        and read.organization.lifecycle
        in {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
        and read.edition.lifecycle
        in {EventEdition.Lifecycle.DRAFT, EventEdition.Lifecycle.PREPARING}
    )


def _profile_mutation_blocked_reason(read: _RegistrationSetupPageRead) -> str:
    if read.workspace.aggregate_version == 0:
        return "Start registration setup before defining profile extensions."
    if read.organization.lifecycle not in {
        Organization.Lifecycle.DRAFT,
        Organization.Lifecycle.ACTIVE,
    }:
        return "The organization lifecycle keeps profile extensions read-only."
    if read.edition.lifecycle not in {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
    }:
        return (
            "Profile extension changes are available while the edition is Draft "
            "or Preparing."
        )
    return "Profile extensions are read-only in the current state."


def _definition_error_message(error: RegistrationSetupCommandError) -> str:
    if isinstance(error, RegistrationSetupQuestionDependencyError):
        return "A conditional question still depends on this question."
    if isinstance(error, RegistrationSetupProductDependencyError):
        return "Protected registration or commercial evidence still uses this product."
    if isinstance(error, RegistrationSetupProfileFieldImmutableError):
        return "Active profile-field definitions are immutable; create a successor."
    return _command_conflict_message(error)


def _handle_command_error(
    request: HttpRequest,
    *,
    read: _RegistrationSetupPageRead,
    form: forms.Form,
    error: RegistrationSetupCommandError,
    title: str,
    heading: str,
    intro: str,
    submit_label: str,
    back_location: str,
) -> HttpResponse:
    return _render_definition_form(
        request,
        read=read,
        form=form,
        title=title,
        heading=heading,
        intro=intro,
        submit_label=submit_label,
        back_location=back_location,
        status=409,
        action_error=_definition_error_message(error),
        reload_required=_reload_required(error),
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_question_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
) -> HttpResponse:
    """Return registration setup question create.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    configuration_id : UUID
        The identifier of the configuration.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    if request.GET:
        return _registration_bad_request(request)
    try:
        _actor, read = _load_get(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        _configuration_for_route(read, configuration_id)
        form = _question_create_form(read)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    return _render_definition_form(
        request,
        read=read,
        form=form,
        title=f"Create registration question — {read.edition.name}",
        heading="Create registration question",
        intro=(
            "Define one typed, purpose-bound question. Conditional questions "
            "must follow their source and cannot depend on hidden staff data."
        ),
        submit_label="Create question",
        back_location=_configuration_location(read, configuration_id),
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_product_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
) -> HttpResponse:
    """Return registration setup product create.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    configuration_id : UUID
        The identifier of the configuration.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    if request.GET:
        return _registration_bad_request(request)
    try:
        _actor, read = _load_get(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        _configuration_for_route(read, configuration_id)
        form = _product_create_form(read)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    return _render_definition_form(
        request,
        read=read,
        form=form,
        title=f"Create admission product — {read.edition.name}",
        heading="Create admission product",
        intro=(
            "Prices use exact minor currency units. Capacity restrictions can "
            "select only active participation capacities from this edition."
        ),
        submit_label="Create product",
        back_location=_configuration_location(read, configuration_id),
    )


def _minor_form(
    read: _RegistrationSetupPageRead,
    *,
    data: QueryDict | None = None,
) -> RegistrationMinorPolicyForm:
    configuration = read.workspace.current_configuration
    if configuration is None:
        raise Http404
    policy = read.workspace.minor_policy
    initial: dict[str, object] = {
        "enabled": "false",
        "minor_age_threshold": min(configuration.minimum_age + 1, 120),
    }
    if policy is not None:
        initial.update(
            {
                "enabled": "true" if policy.enabled else "false",
                "minor_age_threshold": policy.minor_age_threshold,
                "guardian_notice_version": policy.guardian_notice_version,
                "jurisdiction_code": policy.jurisdiction_code,
                "review_reference": policy.review_reference,
            }
        )
    return RegistrationMinorPolicyForm(
        data,
        expected_version=read.workspace.aggregate_version,
        initial=initial,
    )


def _render_minor_policy(
    request: HttpRequest,
    *,
    read: _RegistrationSetupPageRead,
    configuration_id: UUID,
    form: RegistrationMinorPolicyForm,
    remove_form: RegistrationDefinitionDeleteForm | None = None,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> HttpResponse:
    context = _base_context(request, read=read, page_id="registration-minor-policy")
    context.update(
        {
            "title": f"Minor registration policy — {read.edition.name}",
            "configuration": read.workspace.current_configuration,
            "minor_policy": read.workspace.minor_policy,
            "form": form,
            "remove_form": remove_form
            or RegistrationDefinitionDeleteForm(
                expected_version=read.workspace.aggregate_version,
                ordinal=1,
                kind="minor_policy",
            ),
            "show_submitted_form": form.is_bound,
            "action_error": action_error,
            "reload_required": reload_required,
            "definition_back_location": _configuration_location(read, configuration_id),
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_minor_policy.html",
        context=context,
        status=status,
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_minor_policy(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
) -> HttpResponse:
    """Return registration setup minor policy.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    configuration_id : UUID
        The identifier of the configuration.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    if request.GET:
        return _registration_bad_request(request)
    try:
        _actor, read = _load_get(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        _configuration_for_route(read, configuration_id)
        form = _minor_form(read)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    return _render_minor_policy(
        request,
        read=read,
        configuration_id=configuration_id,
        form=form,
    )


def registration_setup_minor_policy_dispatch(
    request: HttpRequest,
    *args: Any,
    **kwargs: Any,
) -> HttpResponse:
    """Return registration setup minor policy dispatch.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    *args : Any
        Positional arguments forwarded to the framework implementation.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    if request.method == "GET":
        return registration_setup_minor_policy(request, *args, **kwargs)
    if request.method == "POST":
        return set_registration_setup_minor_policy(request, *args, **kwargs)
    return HttpResponseNotAllowed(("GET", "POST"))


def _profile_editors(
    read: _RegistrationSetupPageRead,
) -> tuple[_ProfileFieldEditor, ...]:
    drafts = tuple(
        field
        for field in read.workspace.profile_fields
        if field.status == ProfileExtensionStatus.DRAFT
    )
    editors: list[_ProfileFieldEditor] = []
    department_choices = _profile_department_choices(read)
    for ordinal, field in enumerate(read.workspace.profile_fields, start=1):
        if field.status != ProfileExtensionStatus.DRAFT:
            editors.append(
                _ProfileFieldEditor(
                    field=field,
                    ordinal=ordinal,
                    update_form=None,
                    move_form=None,
                    retire_form=(
                        None
                        if field.status == ProfileExtensionStatus.RETIRED
                        else RegistrationDefinitionDeleteForm(
                            expected_version=read.workspace.aggregate_version,
                            ordinal=ordinal,
                            kind="profile_field",
                        )
                    ),
                )
            )
            continue
        update_form = RegistrationProfileFieldUpdateForm(
            expected_version=read.workspace.aggregate_version,
            ordinal=ordinal,
            department_choices=department_choices,
            initial={
                "key": field.key,
                "label": field.label,
                "help_text": field.help_text,
                "field_type": field.field_type,
                "options": "\n".join(field.options),
                "purpose": field.purpose,
                "classification": field.classification,
                "required": "true" if field.required else "false",
                "audience_policy": field.audience_policy,
                "audience_department_id": (
                    str(field.audience_department_id)
                    if field.audience_department_id is not None
                    else ""
                ),
                "writer_policy": field.writer_policy,
            },
        )
        move_form = RegistrationProfileFieldMoveForm(
            placement_choices=_definition_choices(
                drafts,
                label_attribute="label",
                exclude_id=field.id,
            ),
            expected_version=read.workspace.aggregate_version,
            ordinal=ordinal,
            initial={"after_field_id": _definition_predecessor(drafts, field.id)},
        )
        editors.append(
            _ProfileFieldEditor(
                field=field,
                ordinal=ordinal,
                update_form=update_form,
                move_form=move_form,
                retire_form=RegistrationDefinitionDeleteForm(
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                    kind="profile_field",
                ),
            )
        )
    return tuple(editors)


def _render_profile_fields(
    request: HttpRequest,
    *,
    read: _RegistrationSetupPageRead,
    status: int = 200,
    action_error: str = "",
) -> HttpResponse:
    context = _base_context(request, read=read, page_id="registration-profile-fields")
    context.update(
        {
            "title": f"Registration profile extensions — {read.edition.name}",
            "profile_field_editors": _profile_editors(read),
            "action_error": action_error,
            "reload_required": status == HTTP_CONFLICT,
            "registration_mutations_allowed": _profile_mutations_allowed(read),
            "registration_mutation_blocked_reason": (
                _profile_mutation_blocked_reason(read)
            ),
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_profile_fields.html",
        context=context,
        status=status,
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_profile_fields(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Return registration setup profile fields.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    if request.GET:
        return _registration_bad_request(request)
    try:
        _actor, read = _load_get(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    return _render_profile_fields(request, read=read)


def registration_setup_profile_fields_dispatch(
    request: HttpRequest,
    *args: Any,
    **kwargs: Any,
) -> HttpResponse:
    """Return registration setup profile fields dispatch.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    *args : Any
        Positional arguments forwarded to the framework implementation.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    if request.method == "GET":
        return registration_setup_profile_fields(request, *args, **kwargs)
    if request.method == "POST":
        return create_registration_setup_profile_field(request, *args, **kwargs)
    return HttpResponseNotAllowed(("GET", "POST"))


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_profile_field_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Return registration setup profile field create.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    if request.GET:
        return _registration_bad_request(request)
    try:
        _actor, read = _load_get(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        form = _profile_create_form(read)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    return _render_definition_form(
        request,
        read=read,
        form=form,
        title=f"Create profile extension — {read.edition.name}",
        heading="Create profile extension",
        intro=(
            "Define current, purpose-bound data separately from immutable "
            "registration submissions. Reserved authoritative facts are rejected."
        ),
        submit_label="Create profile field",
        back_location=_profile_location(read),
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_profile_field_detail(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    field_id: UUID,
) -> HttpResponse:
    """Return registration setup profile field detail.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    field_id : UUID
        The identifier of the field.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    if request.GET:
        return _registration_bad_request(request)
    try:
        _actor, read = _load_get(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        field, _ordinal = _profile_field_by_id(read, field_id)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    context = _base_context(
        request,
        read=read,
        page_id="registration-profile-field-detail",
    )
    context.update(
        {
            "title": f"{field.label} — profile extension",
            "profile_field": field,
            "definition_back_location": _profile_location(read),
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_profile_field_detail.html",
        context=context,
    )


def _configuration_post_form(  # noqa: PLR0911
    *,
    request: HttpRequest,
    read: _RegistrationSetupPageRead,
    kind: str,
    action: str,
    target_id: UUID | None,
) -> tuple[forms.Form, str, str, str]:
    if kind == "question":
        if action == "create":
            return (
                _question_create_form(read, data=request.POST),
                "Create registration question",
                "Create question",
                "No question was created.",
            )
        if target_id is None:
            raise Http404
        question, ordinal = _question_by_id(read, target_id)
        if action == "update":
            return (
                RegistrationQuestionUpdateForm(
                    request.POST,
                    section_choices=tuple(
                        (str(section.id), section.title)
                        for section in read.workspace.sections
                    ),
                    condition_choices=tuple(
                        (item.key, item.label)
                        for item in read.workspace.questions
                        if item.id != question.id
                    ),
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                ),
                "Edit registration question",
                "Save question",
                "No question was changed.",
            )
        if action == "move":
            return (
                RegistrationQuestionMoveForm(
                    request.POST,
                    placement_choices=_definition_choices(
                        read.workspace.questions,
                        label_attribute="label",
                        exclude_id=question.id,
                    ),
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                ),
                "Move registration question",
                "Move question",
                "The question order was not changed.",
            )
        if action == "remove":
            return (
                RegistrationDefinitionDeleteForm(
                    request.POST,
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                    kind="question",
                ),
                "Remove registration question",
                "Remove unused question",
                "No question was removed.",
            )
    if kind == "product":
        if action == "create":
            return (
                _product_create_form(read, data=request.POST),
                "Create admission product",
                "Create product",
                "No product was created.",
            )
        if target_id is None:
            raise Http404
        product, ordinal = _product_by_id(read, target_id)
        if action == "update":
            return (
                RegistrationProductUpdateForm(
                    request.POST,
                    capacity_code_choices=tuple(
                        (code, code) for code in read.workspace.active_capacity_codes
                    ),
                    edition_time_zone=read.edition.time_zone,
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                ),
                "Edit admission product",
                "Save product",
                "No product was changed.",
            )
        if action == "move":
            return (
                RegistrationProductMoveForm(
                    request.POST,
                    placement_choices=_definition_choices(
                        read.workspace.products,
                        label_attribute="name",
                        exclude_id=product.id,
                    ),
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                ),
                "Move admission product",
                "Move product",
                "The product order was not changed.",
            )
        if action == "remove":
            return (
                RegistrationDefinitionDeleteForm(
                    request.POST,
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                    kind="product",
                ),
                "Remove admission product",
                "Remove unused product",
                "No product was removed.",
            )
    raise Http404


def _run_configuration_command(  # noqa: PLR0911
    *,
    actor: Account,
    read: _RegistrationSetupPageRead,
    configuration_id: UUID,
    kind: str,
    action: str,
    target_id: UUID | None,
    form: forms.Form,
    correlation_id: UUID,
) -> Any:
    common: dict[str, Any] = {
        "actor": actor,
        "organization_id": read.organization.id,
        "series_id": read.series.id,
        "edition_id": read.edition.id,
        "configuration_id": configuration_id,
        "expected_version": cast("int", form.cleaned_data["expected_version"]),
        "reason": cast("str", form.cleaned_data["reason"]),
        "retry_key": cast("UUID", form.cleaned_data["retry_key"]),
        "correlation_id": correlation_id,
        "request_id": correlation_id,
        "source_channel": "web",
    }
    if kind == "question":
        if action in {"create", "update"}:
            values: dict[str, Any] = {
                **common,
                "key": cast("str", form.cleaned_data["key"]),
                "label": cast("str", form.cleaned_data["label"]),
                "help_text": cast("str", form.cleaned_data["help_text"]),
                "field_type": cast("str", form.cleaned_data["field_type"]),
                "required": cast("bool", form.cleaned_data["required"]),
                "options": cast("list[str]", form.cleaned_data["options"]),
                "purpose": cast("str", form.cleaned_data["purpose"]),
                "visibility": cast("str", form.cleaned_data["visibility"]),
                "classification": cast("str", form.cleaned_data["classification"]),
                "condition_question_key": cast(
                    "str", form.cleaned_data["condition_question_key"]
                ),
                "condition_value": cast("str", form.cleaned_data["condition_value"]),
                "section_id": cast("UUID | None", form.cleaned_data["section_id"]),
            }
            if action == "create":
                return create_registration_question(
                    **values,
                    after_question_id=cast(
                        "UUID | None", form.cleaned_data["after_question_id"]
                    ),
                )
            return update_registration_question(
                **values,
                question_id=cast("UUID", target_id),
            )
        if action == "move":
            return move_registration_question(
                **common,
                question_id=cast("UUID", target_id),
                after_question_id=cast(
                    "UUID | None", form.cleaned_data["after_question_id"]
                ),
            )
        if action == "remove":
            return delete_registration_question(
                **common,
                question_id=cast("UUID", target_id),
            )
    if kind == "product":
        if action in {"create", "update"}:
            values = {
                **common,
                "code": cast("str", form.cleaned_data["code"]),
                "name": cast("str", form.cleaned_data["name"]),
                "description": cast("str", form.cleaned_data["description"]),
                "price_minor": cast("int", form.cleaned_data["price_minor"]),
                "capacity": cast("int", form.cleaned_data["capacity"]),
                "capacity_ceiling": cast(
                    "int | None",
                    form.cleaned_data["capacity_ceiling"],
                ),
                "entitlement_code": cast("str", form.cleaned_data["entitlement_code"]),
                "entitlement_name": cast("str", form.cleaned_data["entitlement_name"]),
                "sales_open_at": form.cleaned_data["sales_open_at"],
                "sales_close_at": form.cleaned_data["sales_close_at"],
                "required_capacity_codes": cast(
                    "list[str]", form.cleaned_data["required_capacity_codes"]
                ),
                "eligibility_explanation": cast(
                    "str", form.cleaned_data["eligibility_explanation"]
                ),
                "waitlist_enabled": cast("bool", form.cleaned_data["waitlist_enabled"]),
                "payment_window_minutes": cast(
                    "int | None", form.cleaned_data["payment_window_minutes"]
                ),
            }
            if action == "create":
                return create_admission_product(
                    **values,
                    after_product_id=cast(
                        "UUID | None", form.cleaned_data["after_product_id"]
                    ),
                )
            return update_admission_product(
                **values,
                product_id=cast("UUID", target_id),
            )
        if action == "move":
            return move_admission_product(
                **common,
                product_id=cast("UUID", target_id),
                after_product_id=cast(
                    "UUID | None", form.cleaned_data["after_product_id"]
                ),
            )
        if action == "remove":
            return delete_admission_product(
                **common,
                product_id=cast("UUID", target_id),
            )
    raise Http404


def _configuration_definition_post(  # noqa: PLR0911
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
    kind: str,
    action: str,
    target_id: UUID | None,
) -> HttpResponse:
    try:
        actor, read = _preflight_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        _configuration_for_route(read, configuration_id)
        if kind == "question" and target_id is not None:
            _question_by_id(read, target_id)
        if kind == "product" and target_id is not None:
            _product_by_id(read, target_id)
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    form, heading, submit_label, invalid_message = _configuration_post_form(
        request=request,
        read=read,
        kind=kind,
        action=action,
        target_id=target_id,
    )
    back_location = _configuration_location(read, configuration_id)
    title = f"{heading} — {read.edition.name}"
    intro = "This exact action uses the current setup version and never cascades."
    if not form.is_valid():
        return _render_definition_form(
            request,
            read=read,
            form=form,
            title=title,
            heading=heading,
            intro=intro,
            submit_label=submit_label,
            back_location=back_location,
            status=400,
            action_error=f"Review the highlighted values. {invalid_message}",
        )
    correlation_id = _request_id(request)
    try:
        result = _run_configuration_command(
            actor=actor,
            read=read,
            configuration_id=configuration_id,
            kind=kind,
            action=action,
            target_id=target_id,
            form=form,
            correlation_id=correlation_id,
        )
    except ValidationError as error:
        if not _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset(form.fields),
        ):
            return _registration_dependency_failure(request)
        return _render_definition_form(
            request,
            read=read,
            form=form,
            title=title,
            heading=heading,
            intro=intro,
            submit_label=submit_label,
            back_location=back_location,
            status=400,
            action_error=f"Review the highlighted values. {invalid_message}",
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        RegistrationSetupQuestionUnavailableError,
        RegistrationSetupProductUnavailableError,
    ) as error:
        raise Http404 from error
    except (DatabaseError, RegistrationSetupDependencyError):
        return _registration_dependency_failure(request)
    except RegistrationSetupCommandError as error:
        return _handle_command_error(
            request,
            read=read,
            form=form,
            error=error,
            title=title,
            heading=heading,
            intro=intro,
            submit_label=submit_label,
            back_location=back_location,
        )
    except RuntimeError:
        return _registration_dependency_failure(request)
    messages.success(
        request,
        f"The {kind} action was already recorded for this request."
        if result.replayed
        else f"Registration {kind} {action}d.",
    )
    return _private_no_store(redirect(back_location))


@never_cache
@login_required(login_url="staff-login")
@require_POST
def create_registration_setup_question(
    request: HttpRequest,
    **kwargs: Any,
) -> HttpResponse:
    """Create registration setup question.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.
    """
    return _configuration_definition_post(
        request,
        **kwargs,
        kind="question",
        action="create",
        target_id=None,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_registration_setup_question(
    request: HttpRequest,
    question_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Update registration setup question.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    question_id : UUID
        The identifier of the question.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.
    """
    return _configuration_definition_post(
        request,
        **kwargs,
        kind="question",
        action="update",
        target_id=question_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def move_registration_setup_question(
    request: HttpRequest,
    question_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Move registration setup question.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    question_id : UUID
        The identifier of the question.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    return _configuration_definition_post(
        request,
        **kwargs,
        kind="question",
        action="move",
        target_id=question_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def remove_registration_setup_question(
    request: HttpRequest,
    question_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Remove registration setup question.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    question_id : UUID
        The identifier of the question.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    return _configuration_definition_post(
        request,
        **kwargs,
        kind="question",
        action="remove",
        target_id=question_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def create_registration_setup_product(
    request: HttpRequest,
    **kwargs: Any,
) -> HttpResponse:
    """Create registration setup product.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.
    """
    return _configuration_definition_post(
        request,
        **kwargs,
        kind="product",
        action="create",
        target_id=None,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_registration_setup_product(
    request: HttpRequest,
    product_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Update registration setup product.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    product_id : UUID
        The identifier of the product.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.
    """
    return _configuration_definition_post(
        request,
        **kwargs,
        kind="product",
        action="update",
        target_id=product_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def move_registration_setup_product(
    request: HttpRequest,
    product_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Move registration setup product.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    product_id : UUID
        The identifier of the product.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    return _configuration_definition_post(
        request,
        **kwargs,
        kind="product",
        action="move",
        target_id=product_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def remove_registration_setup_product(
    request: HttpRequest,
    product_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Remove registration setup product.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    product_id : UUID
        The identifier of the product.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    return _configuration_definition_post(
        request,
        **kwargs,
        kind="product",
        action="remove",
        target_id=product_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def set_registration_setup_minor_policy(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
) -> HttpResponse:
    """Set registration setup minor policy.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    configuration_id : UUID
        The identifier of the configuration.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    try:
        actor, read = _preflight_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        _configuration_for_route(read, configuration_id)
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    form = _minor_form(read, data=request.POST)
    if not form.is_valid():
        return _render_minor_policy(
            request,
            read=read,
            configuration_id=configuration_id,
            form=form,
            status=400,
            action_error="Review the highlighted values. No policy was changed.",
        )
    correlation_id = _request_id(request)
    try:
        result = set_minor_registration_policy(
            actor=actor,
            organization_id=read.organization.id,
            series_id=read.series.id,
            edition_id=read.edition.id,
            configuration_id=configuration_id,
            enabled=cast("bool", form.cleaned_data["enabled"]),
            minor_age_threshold=cast("int", form.cleaned_data["minor_age_threshold"]),
            guardian_notice_version=cast(
                "str", form.cleaned_data["guardian_notice_version"]
            ),
            jurisdiction_code=cast("str", form.cleaned_data["jurisdiction_code"]),
            review_reference=cast("str", form.cleaned_data["review_reference"]),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_domain_validation_errors(
            form, error, allowed_fields=frozenset(form.fields)
        ):
            return _registration_dependency_failure(request)
        return _render_minor_policy(
            request,
            read=read,
            configuration_id=configuration_id,
            form=form,
            status=400,
            action_error="Review the highlighted values. No policy was changed.",
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (DatabaseError, RegistrationSetupDependencyError):
        return _registration_dependency_failure(request)
    except RegistrationSetupCommandError as error:
        return _render_minor_policy(
            request,
            read=read,
            configuration_id=configuration_id,
            form=form,
            status=409,
            action_error=_definition_error_message(error),
            reload_required=_reload_required(error),
        )
    except RuntimeError:
        return _registration_dependency_failure(request)
    messages.success(
        request,
        "The minor policy action was already recorded for this request."
        if result.replayed
        else "Minor registration policy saved.",
    )
    return _private_no_store(redirect(_configuration_location(read, configuration_id)))


@never_cache
@login_required(login_url="staff-login")
@require_POST
def remove_registration_setup_minor_policy(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
) -> HttpResponse:
    """Remove registration setup minor policy.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    organization_slug : str
        The URL slug identifying the organization.
    series_slug : str
        The URL slug identifying the convention series.
    edition_slug : str
        The URL slug identifying the event edition.
    configuration_id : UUID
        The identifier of the configuration.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    try:
        actor, read = _preflight_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        _configuration_for_route(read, configuration_id)
        if read.workspace.minor_policy is None:
            raise Http404
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    form = RegistrationDefinitionDeleteForm(
        request.POST,
        expected_version=read.workspace.aggregate_version,
        ordinal=1,
        kind="minor_policy",
    )
    if not form.is_valid():
        return _render_minor_policy(
            request,
            read=read,
            configuration_id=configuration_id,
            form=_minor_form(read),
            remove_form=form,
            status=400,
            action_error="Review the removal reason. No policy was removed.",
        )
    correlation_id = _request_id(request)
    try:
        result = remove_minor_registration_policy(
            actor=actor,
            organization_id=read.organization.id,
            series_id=read.series.id,
            edition_id=read.edition.id,
            configuration_id=configuration_id,
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except RegistrationSetupMinorPolicyUnavailableError as error:
        raise Http404 from error
    except (DatabaseError, RegistrationSetupDependencyError):
        return _registration_dependency_failure(request)
    except RegistrationSetupCommandError as error:
        return _render_minor_policy(
            request,
            read=read,
            configuration_id=configuration_id,
            form=_minor_form(read),
            remove_form=form,
            status=409,
            action_error=_definition_error_message(error),
            reload_required=_reload_required(error),
        )
    except RuntimeError:
        return _registration_dependency_failure(request)
    messages.success(
        request,
        "The policy removal was already recorded for this request."
        if result.replayed
        else "Minor registration policy removed.",
    )
    return _private_no_store(redirect(_configuration_location(read, configuration_id)))


def _profile_post_form(
    *,
    request: HttpRequest,
    read: _RegistrationSetupPageRead,
    action: str,
    field_id: UUID | None,
) -> tuple[forms.Form, str, str]:
    if action == "create":
        return (
            _profile_create_form(read, data=request.POST),
            "Create profile extension",
            "Create profile field",
        )
    if field_id is None:
        raise Http404
    field, ordinal = _profile_field_by_id(read, field_id)
    if action == "update":
        return (
            RegistrationProfileFieldUpdateForm(
                request.POST,
                expected_version=read.workspace.aggregate_version,
                ordinal=ordinal,
                department_choices=_profile_department_choices(read),
            ),
            "Edit profile extension",
            "Save profile field",
        )
    if action == "move":
        drafts = tuple(
            item
            for item in read.workspace.profile_fields
            if item.status == ProfileExtensionStatus.DRAFT
        )
        return (
            RegistrationProfileFieldMoveForm(
                request.POST,
                placement_choices=_definition_choices(
                    drafts,
                    label_attribute="label",
                    exclude_id=field.id,
                ),
                expected_version=read.workspace.aggregate_version,
                ordinal=ordinal,
            ),
            "Move profile extension",
            "Move profile field",
        )
    if action == "retire":
        return (
            RegistrationDefinitionDeleteForm(
                request.POST,
                expected_version=read.workspace.aggregate_version,
                ordinal=ordinal,
                kind="profile_field",
            ),
            "Retire profile extension",
            "Retire profile field",
        )
    raise Http404


def _run_profile_command(
    *,
    actor: Account,
    read: _RegistrationSetupPageRead,
    action: str,
    field_id: UUID | None,
    form: forms.Form,
    correlation_id: UUID,
) -> Any:
    common: dict[str, Any] = {
        "actor": actor,
        "organization_id": read.organization.id,
        "series_id": read.series.id,
        "edition_id": read.edition.id,
        "expected_version": cast("int", form.cleaned_data["expected_version"]),
        "reason": cast("str", form.cleaned_data["reason"]),
        "retry_key": cast("UUID", form.cleaned_data["retry_key"]),
        "correlation_id": correlation_id,
        "request_id": correlation_id,
        "source_channel": "web",
    }
    if action in {"create", "update"}:
        values: dict[str, Any] = {
            **common,
            "key": cast("str", form.cleaned_data["key"]),
            "label": cast("str", form.cleaned_data["label"]),
            "help_text": cast("str", form.cleaned_data["help_text"]),
            "field_type": cast("str", form.cleaned_data["field_type"]),
            "options": cast("list[str]", form.cleaned_data["options"]),
            "purpose": cast("str", form.cleaned_data["purpose"]),
            "classification": cast("str", form.cleaned_data["classification"]),
            "audience_policy": cast("str", form.cleaned_data["audience_policy"]),
            "audience_department_id": cast(
                "UUID | None",
                form.cleaned_data["audience_department_id"],
            ),
            "writer_policy": cast("str", form.cleaned_data["writer_policy"]),
            "required": cast("bool", form.cleaned_data["required"]),
        }
        if action == "create":
            return create_registration_profile_extension_field(
                **values,
                source_template_id=cast(
                    "UUID | None", form.cleaned_data["source_template_id"]
                ),
                source_prior_edition_id=cast(
                    "UUID | None", form.cleaned_data["source_prior_edition_id"]
                ),
                after_field_id=cast("UUID | None", form.cleaned_data["after_field_id"]),
            )
        return update_registration_profile_extension_field(
            **values,
            field_id=cast("UUID", field_id),
        )
    if action == "move":
        return move_registration_profile_extension_field(
            **common,
            field_id=cast("UUID", field_id),
            after_field_id=cast("UUID | None", form.cleaned_data["after_field_id"]),
        )
    if action == "retire":
        return retire_registration_profile_extension_field(
            **common,
            field_id=cast("UUID", field_id),
        )
    raise Http404


def _profile_definition_post(  # noqa: PLR0911
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    action: str,
    field_id: UUID | None,
) -> HttpResponse:
    try:
        actor, read = _preflight_post(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        if field_id is not None:
            _profile_field_by_id(read, field_id)
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    form, heading, submit_label = _profile_post_form(
        request=request,
        read=read,
        action=action,
        field_id=field_id,
    )
    back_location = _profile_location(read)
    title = f"{heading} — {read.edition.name}"
    intro = (
        "Profile definitions contain no attendee values. Active definitions are "
        "immutable and retirement preserves all value history."
    )
    if not form.is_valid():
        return _render_definition_form(
            request,
            read=read,
            form=form,
            title=title,
            heading=heading,
            intro=intro,
            submit_label=submit_label,
            back_location=back_location,
            status=400,
            action_error="Review the highlighted values. No profile field changed.",
        )
    correlation_id = _request_id(request)
    try:
        result = _run_profile_command(
            actor=actor,
            read=read,
            action=action,
            field_id=field_id,
            form=form,
            correlation_id=correlation_id,
        )
    except ValidationError as error:
        if not _add_domain_validation_errors(
            form, error, allowed_fields=frozenset(form.fields)
        ):
            return _registration_dependency_failure(request)
        return _render_definition_form(
            request,
            read=read,
            form=form,
            title=title,
            heading=heading,
            intro=intro,
            submit_label=submit_label,
            back_location=back_location,
            status=400,
            action_error="Review the highlighted values. No profile field changed.",
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except RegistrationSetupProfileFieldUnavailableError as error:
        raise Http404 from error
    except (DatabaseError, RegistrationSetupDependencyError):
        return _registration_dependency_failure(request)
    except RegistrationSetupCommandError as error:
        return _handle_command_error(
            request,
            read=read,
            form=form,
            error=error,
            title=title,
            heading=heading,
            intro=intro,
            submit_label=submit_label,
            back_location=back_location,
        )
    except RuntimeError:
        return _registration_dependency_failure(request)
    messages.success(
        request,
        "The profile-field action was already recorded for this request."
        if result.replayed
        else f"Profile field {action}d.",
    )
    return _private_no_store(redirect(back_location))


@never_cache
@login_required(login_url="staff-login")
@require_POST
def create_registration_setup_profile_field(
    request: HttpRequest,
    **kwargs: Any,
) -> HttpResponse:
    """Create registration setup profile field.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.
    """
    return _profile_definition_post(
        request,
        **kwargs,
        action="create",
        field_id=None,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_registration_setup_profile_field(
    request: HttpRequest,
    field_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Update registration setup profile field.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    field_id : UUID
        The identifier of the field.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.
    """
    return _profile_definition_post(
        request,
        **kwargs,
        action="update",
        field_id=field_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def move_registration_setup_profile_field(
    request: HttpRequest,
    field_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Move registration setup profile field.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    field_id : UUID
        The identifier of the field.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    return _profile_definition_post(
        request,
        **kwargs,
        action="move",
        field_id=field_id,
    )


@never_cache
@login_required(login_url="staff-login")
@require_POST
def retire_registration_setup_profile_field(
    request: HttpRequest,
    field_id: UUID,
    **kwargs: Any,
) -> HttpResponse:
    """Retire registration setup profile field.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    field_id : UUID
        The identifier of the field.
    **kwargs : Any
        Keyword arguments forwarded to the framework implementation.

    Returns
    -------
    HttpResponse
        The HTTP response for this request.
    """
    return _profile_definition_post(
        request,
        **kwargs,
        action="retire",
        field_id=field_id,
    )


__all__ = [
    "create_registration_setup_product",
    "create_registration_setup_profile_field",
    "create_registration_setup_question",
    "move_registration_setup_product",
    "move_registration_setup_profile_field",
    "move_registration_setup_question",
    "registration_setup_minor_policy",
    "registration_setup_minor_policy_dispatch",
    "registration_setup_product_create",
    "registration_setup_profile_field_create",
    "registration_setup_profile_field_detail",
    "registration_setup_profile_fields",
    "registration_setup_profile_fields_dispatch",
    "registration_setup_question_create",
    "remove_registration_setup_minor_policy",
    "remove_registration_setup_product",
    "remove_registration_setup_question",
    "retire_registration_setup_profile_field",
    "set_registration_setup_minor_policy",
    "update_registration_setup_product",
    "update_registration_setup_profile_field",
    "update_registration_setup_question",
]
