"""Same-shell browser adapters for governed Page 10 registration setup."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import Http404, HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.timezone import now as timezone_now
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.events.admin_context import authorized_admin_edition_for_route
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.registration.models import ConfigurationStatus, RegistrationSetupOrigin
from maru.registration.setup_commands import (
    RegistrationSetupAuthorizationDeniedError,
    RegistrationSetupCommandError,
    RegistrationSetupDependencyError,
    RegistrationSetupLifecycleConflictError,
    RegistrationSetupLimitExceededError,
    RegistrationSetupRetryConflictError,
    RegistrationSetupSourceUnavailableError,
    RegistrationSetupStateConflictError,
    RegistrationSetupVersionConflictError,
)
from maru.registration.setup_commands import (
    start_registration_setup as start_registration_setup_command,
)
from maru.registration.setup_forms import (
    RegistrationDefinitionDeleteForm,
    RegistrationMinorPolicyForm,
    RegistrationProductMoveForm,
    RegistrationProductUpdateForm,
    RegistrationQuestionMoveForm,
    RegistrationQuestionUpdateForm,
    RegistrationSectionCreateForm,
    RegistrationSectionDeleteForm,
    RegistrationSectionMoveForm,
    RegistrationSectionUpdateForm,
    RegistrationSetupStartForm,
    SectionPlacementChoices,
    SetupSourceChoices,
)
from maru.registration.setup_queries import (
    RegistrationSetupProductProjection,
    RegistrationSetupQuestionProjection,
    RegistrationSetupSectionProjection,
    RegistrationSetupWorkspace,
    get_registration_setup_workspace,
)
from maru.registration.setup_section_commands import (
    RegistrationSetupConfigurationUnavailableError,
    RegistrationSetupSectionDependencyError,
    RegistrationSetupSectionUnavailableError,
    create_registration_section,
    delete_registration_section,
    move_registration_section,
    update_registration_section,
)

logger = logging.getLogger(__name__)


class _RegistrationPostQueryParametersUnsupportedError(Exception):
    """Stop a POST after route policy but before parsing its body."""


@dataclass(frozen=True, slots=True)
class _RegistrationSetupPageRead:
    organization: Organization
    series: ConventionSeries
    edition: EventEdition
    workspace: RegistrationSetupWorkspace
    decision: PolicyDecision
    can_view_organization: bool
    can_manage_representation: bool
    can_create_series: bool
    can_create_edition: bool
    can_view_edition: bool
    can_view_structure: bool


@dataclass(frozen=True, slots=True)
class _RegistrationSectionEditor:
    section: RegistrationSetupSectionProjection
    ordinal: int
    accessible_name: str
    update_form: RegistrationSectionUpdateForm
    move_form: RegistrationSectionMoveForm
    delete_form: RegistrationSectionDeleteForm


@dataclass(frozen=True, slots=True)
class _RegistrationQuestionEditor:
    question: RegistrationSetupQuestionProjection
    ordinal: int
    update_form: RegistrationQuestionUpdateForm
    move_form: RegistrationQuestionMoveForm
    delete_form: RegistrationDefinitionDeleteForm


@dataclass(frozen=True, slots=True)
class _RegistrationProductEditor:
    product: RegistrationSetupProductProjection
    ordinal: int
    update_form: RegistrationProductUpdateForm
    move_form: RegistrationProductMoveForm
    delete_form: RegistrationDefinitionDeleteForm


def _request_id(request: HttpRequest) -> UUID:
    candidate = getattr(request, "correlation_id", None)
    if isinstance(candidate, str):
        try:
            return UUID(candidate)
        except ValueError:
            pass
    return uuid4()


def _private_no_store(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _safe_dependency_log(request: HttpRequest, *, operation: str) -> None:
    logger.error(
        "Registration setup browser dependency failed",
        extra={
            "correlation_id": str(_request_id(request)),
            "operation": operation,
        },
    )


def _active_account(request: HttpRequest) -> Account:
    """Reload an active actor before resolving scope or parsing a protected body.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.

    Returns
    -------
    Account
        The resolved Account for active account.

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    if not isinstance(request.user, Account) or not request.user.is_authenticated:
        raise PermissionDenied
    actor = Account.objects.filter(pk=request.user.pk, is_active=True).first()
    if actor is None:
        raise PermissionDenied
    return actor


def _authorize_registration_route(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> tuple[Organization, ConventionSeries, EventEdition, PolicyDecision]:
    organization, series, edition = authorized_admin_edition_for_route(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
        capability_code="registration.manage_configuration",
    )
    target = resolve_edition_target(
        organization_id=organization.id,
        edition_id=edition.id,
    )
    if target is None:
        raise PermissionDenied
    decision = decide(
        principal=actor,
        capability_code="registration.manage_configuration",
        resource=target,
        at=timezone_now(),
    )
    if not decision.allowed:
        raise PermissionDenied
    return organization, series, edition, decision


def _can_organization(
    *,
    actor: Account,
    organization_id: UUID,
    capability_code: str,
) -> bool:
    return decide(
        principal=actor,
        capability_code=capability_code,
        resource=resolve_organization_target(organization_id=organization_id),
        at=timezone_now(),
    ).allowed


def _can_edition(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
) -> bool:
    return decide(
        principal=actor,
        capability_code=capability_code,
        resource=resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
        at=timezone_now(),
    ).allowed


def _registration_access_label(decision: PolicyDecision) -> str:
    return {
        "platform_administration": "Platform oversight",
        "direct_grant": "Exact edition capability",
        "role_assignment": "Scoped edition role",
    }.get(decision.reason_code, "Current scoped authority")


def _load_registration_page(
    *,
    request: HttpRequest,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> _RegistrationSetupPageRead:
    organization, series, edition, _decision = _authorize_registration_route(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    request_id = _request_id(request)
    try:
        workspace = get_registration_setup_workspace(
            actor=actor,
            organization_id=organization.id,
            series_id=series.id,
            edition_id=edition.id,
            correlation_id=request_id,
            request_id=request_id,
            source_channel="web",
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error

    target = resolve_edition_target(
        organization_id=organization.id,
        edition_id=edition.id,
    )
    if target is None:
        raise PermissionDenied
    decision = decide(
        principal=actor,
        capability_code="registration.manage_configuration",
        resource=target,
        at=timezone_now(),
    )
    if not decision.allowed:
        raise PermissionDenied
    return _RegistrationSetupPageRead(
        organization=organization,
        series=series,
        edition=edition,
        workspace=workspace,
        decision=decision,
        can_view_organization=_can_organization(
            actor=actor,
            organization_id=organization.id,
            capability_code="organizations.view_basic",
        ),
        can_manage_representation=_can_organization(
            actor=actor,
            organization_id=organization.id,
            capability_code="organizations.manage_representation",
        ),
        can_create_series=_can_organization(
            actor=actor,
            organization_id=organization.id,
            capability_code="organizations.create_series",
        ),
        can_create_edition=_can_organization(
            actor=actor,
            organization_id=organization.id,
            capability_code="events.create",
        ),
        can_view_edition=_can_edition(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
            capability_code="events.view_basic",
        ),
        can_view_structure=_can_edition(
            actor=actor,
            organization_id=organization.id,
            edition_id=edition.id,
            capability_code="workforce.view_structure",
        ),
    )


def _mutations_allowed(read: _RegistrationSetupPageRead) -> bool:
    configuration = read.workspace.current_configuration
    return bool(
        configuration is not None
        and configuration.status == ConfigurationStatus.DRAFT
        and read.organization.lifecycle
        in {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
        and read.edition.lifecycle
        in {EventEdition.Lifecycle.DRAFT, EventEdition.Lifecycle.PREPARING}
    )


def _mutation_blocked_reason(read: _RegistrationSetupPageRead) -> str:
    configuration = read.workspace.current_configuration
    if configuration is None:
        return "Start registration setup before editing its form sections."
    if configuration.status != ConfigurationStatus.DRAFT:
        return "An active or retired registration version is immutable."
    if read.organization.lifecycle not in {
        Organization.Lifecycle.DRAFT,
        Organization.Lifecycle.ACTIVE,
    }:
        return "The organization lifecycle keeps registration setup read-only."
    if read.edition.lifecycle not in {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
    }:
        return (
            "Registration setup changes are currently available only while the "
            "edition is Draft or Preparing."
        )
    return "Registration setup is read-only in the current state."


def _base_context(
    request: HttpRequest,
    *,
    read: _RegistrationSetupPageRead,
    page_id: str,
) -> dict[str, object]:
    context = admin.site.each_context(request)
    context.update(
        {
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": page_id,
            "baseline_page_class": "",
            "baseline_can_view_organization": read.can_view_organization,
            "baseline_can_manage_representation": read.can_manage_representation,
            "baseline_can_create_series": read.can_create_series,
            "baseline_can_create_edition": read.can_create_edition,
            "baseline_can_view_edition": read.can_view_edition,
            "baseline_can_view_structure": read.can_view_structure,
            "baseline_can_manage_registration": True,
            "baseline_registration_navigation_current": True,
            "organization": read.organization,
            "convention_series": read.series,
            "edition": read.edition,
            "registration_workspace": read.workspace,
            "registration_access_label": _registration_access_label(read.decision),
            "registration_mutations_allowed": _mutations_allowed(read),
            "registration_mutation_blocked_reason": _mutation_blocked_reason(read),
            "registration_load_failed": False,
            "registration_request_invalid": False,
        }
    )
    return context


def _registration_response(
    request: HttpRequest,
    *,
    template_name: str,
    context: dict[str, object],
    status: int = 200,
) -> HttpResponse:
    return _private_no_store(
        TemplateResponse(request, template_name, context, status=status)
    )


def _registration_dependency_failure(request: HttpRequest) -> HttpResponse:
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Registration setup unavailable",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "registration-setup",
            "baseline_page_class": "",
            "baseline_hide_admin_scoped_navigation": True,
            "registration_load_failed": True,
            "registration_request_invalid": False,
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_workspace.html",
        context=context,
        status=503,
    )


def _registration_bad_request(request: HttpRequest) -> HttpResponse:
    context = admin.site.each_context(request)
    context.update(
        {
            "title": "Invalid registration setup request",
            "has_permission": True,
            "baseline_admin_parent_template": "admin/base_site.html",
            "baseline_use_admin_shell": True,
            "baseline_page_id": "registration-setup",
            "baseline_page_class": "",
            "baseline_hide_admin_scoped_navigation": True,
            "registration_load_failed": False,
            "registration_request_invalid": True,
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_workspace.html",
        context=context,
        status=400,
    )


def _route_kwargs(read: _RegistrationSetupPageRead) -> dict[str, str]:
    return {
        "organization_slug": read.organization.slug,
        "series_slug": read.series.slug,
        "edition_slug": read.edition.slug,
    }


def _workspace_location(read: _RegistrationSetupPageRead) -> str:
    return reverse("registration-setup", kwargs=_route_kwargs(read))


def _configuration_location(
    read: _RegistrationSetupPageRead,
    configuration_id: UUID,
) -> str:
    return reverse(
        "registration-setup-configuration",
        kwargs={**_route_kwargs(read), "configuration_id": configuration_id},
    )


def _source_choices(
    workspace: RegistrationSetupWorkspace,
) -> tuple[SetupSourceChoices, dict[UUID, str]]:
    choices: list[tuple[str, str]] = []
    kinds: dict[UUID, str] = {}
    for option_index, option in enumerate(workspace.platform_starters, start=1):
        choices.append(
            (
                str(option.source_id),
                f"Platform starter - {option.name} - version {option.version} "
                f"- catalog option {option_index}",
            )
        )
        kinds[option.source_id] = RegistrationSetupOrigin.PLATFORM_STARTER
    for option_index, option in enumerate(workspace.published_templates, start=1):
        choices.append(
            (
                str(option.source_id),
                f"Published template — {option.name} — version {option.version} "
                f"— option {option_index}",
            )
        )
        kinds[option.source_id] = RegistrationSetupOrigin.PUBLISHED_TEMPLATE
    prior_offset = len(choices)
    for option_index, option in enumerate(workspace.prior_configurations, start=1):
        choices.append(
            (
                str(option.source_id),
                f"Prior edition — {option.source_edition_name} — {option.name} "
                f"version {option.version} — option {prior_offset + option_index}",
            )
        )
        kinds[option.source_id] = RegistrationSetupOrigin.PRIOR_EDITION
    return tuple(choices), kinds


def _start_initial(read: _RegistrationSetupPageRead) -> dict[str, object]:
    zone = ZoneInfo(read.edition.time_zone)
    opens_at = datetime.combine(
        read.edition.starts_on - timedelta(days=180),
        time(hour=9),
        tzinfo=zone,
    )
    closes_at = datetime.combine(
        read.edition.starts_on - timedelta(days=1),
        time(hour=23, minute=59),
        tzinfo=zone,
    )
    return {
        "name": "Attendee registration",
        "opens_at": opens_at,
        "closes_at": closes_at,
        "capacity": 1_000,
        "capacity_ceiling": 1_000,
        "currency": read.edition.currency_codes[0],
        "minimum_age": 18,
        "default_payment_window_minutes": 1_440,
        "waitlist_enabled": "true",
        "automatic_waitlist_promotion": "true",
    }


def _new_start_form(
    read: _RegistrationSetupPageRead,
    *,
    data: QueryDict | None = None,
) -> RegistrationSetupStartForm:
    choices, kinds = _source_choices(read.workspace)
    return RegistrationSetupStartForm(
        data,
        source_choices=choices,
        source_kinds_by_id=kinds,
        currency_codes=read.edition.currency_codes,
        edition_time_zone=read.edition.time_zone,
        expected_version=0,
        initial=_start_initial(read),
    )


def _placement_choices(
    workspace: RegistrationSetupWorkspace,
    *,
    exclude_section_id: UUID | None = None,
) -> SectionPlacementChoices:
    return tuple(
        (
            str(section.id),
            f"After {section.title} — current section {ordinal}",
        )
        for ordinal, section in enumerate(workspace.sections, start=1)
        if section.id != exclude_section_id
    )


def _find_section(
    workspace: RegistrationSetupWorkspace,
    section_id: UUID,
) -> RegistrationSetupSectionProjection:
    section = next(
        (candidate for candidate in workspace.sections if candidate.id == section_id),
        None,
    )
    if section is None:
        raise Http404
    return section


def _section_ordinal(
    workspace: RegistrationSetupWorkspace,
    section_id: UUID,
) -> int:
    for ordinal, section in enumerate(workspace.sections, start=1):
        if section.id == section_id:
            return ordinal
    raise Http404


def _section_predecessor(
    workspace: RegistrationSetupWorkspace,
    section_id: UUID,
) -> str:
    previous = ""
    for section in workspace.sections:
        if section.id == section_id:
            return previous
        previous = str(section.id)
    raise Http404


def _section_editors(
    read: _RegistrationSetupPageRead,
    *,
    active_action: str = "",
    active_section_id: UUID | None = None,
    active_form: forms.Form | None = None,
) -> tuple[_RegistrationSectionEditor, ...]:
    editors: list[_RegistrationSectionEditor] = []
    for ordinal, section in enumerate(read.workspace.sections, start=1):
        update_form: RegistrationSectionUpdateForm
        move_form: RegistrationSectionMoveForm
        delete_form: RegistrationSectionDeleteForm
        if (
            section.id == active_section_id
            and active_action == "update"
            and isinstance(active_form, RegistrationSectionUpdateForm)
        ):
            update_form = active_form
        else:
            update_form = RegistrationSectionUpdateForm(
                expected_version=read.workspace.aggregate_version,
                ordinal=ordinal,
                initial={
                    "key": section.key,
                    "title": section.title,
                    "description": section.description,
                },
            )
        placement_choices = _placement_choices(
            read.workspace,
            exclude_section_id=section.id,
        )
        if (
            section.id == active_section_id
            and active_action == "move"
            and isinstance(active_form, RegistrationSectionMoveForm)
        ):
            active_form.set_placement_choices(placement_choices)
            move_form = active_form
        else:
            move_form = RegistrationSectionMoveForm(
                placement_choices=placement_choices,
                expected_version=read.workspace.aggregate_version,
                ordinal=ordinal,
                initial={
                    "after_section_id": _section_predecessor(
                        read.workspace,
                        section.id,
                    )
                },
            )
        if (
            section.id == active_section_id
            and active_action == "delete"
            and isinstance(active_form, RegistrationSectionDeleteForm)
        ):
            delete_form = active_form
        else:
            delete_form = RegistrationSectionDeleteForm(
                expected_version=read.workspace.aggregate_version,
                ordinal=ordinal,
            )
        editors.append(
            _RegistrationSectionEditor(
                section=section,
                ordinal=ordinal,
                accessible_name=f"{section.title} — section {ordinal}",
                update_form=update_form,
                move_form=move_form,
                delete_form=delete_form,
            )
        )
    return tuple(editors)


def _definition_choices(
    records: tuple[Any, ...],
    *,
    label_attribute: str,
    exclude_id: UUID | None = None,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            str(record.id),
            f"After {getattr(record, label_attribute)} — current item {ordinal}",
        )
        for ordinal, record in enumerate(records, start=1)
        if record.id != exclude_id
    )


def _definition_predecessor(records: tuple[Any, ...], target_id: UUID) -> str:
    previous = ""
    for record in records:
        if record.id == target_id:
            return previous
        previous = str(record.id)
    raise Http404


def _question_editors(
    read: _RegistrationSetupPageRead,
) -> tuple[_RegistrationQuestionEditor, ...]:
    sections = tuple(
        (str(section.id), section.title) for section in read.workspace.sections
    )
    condition_choices = tuple(
        (question.key, question.label) for question in read.workspace.questions
    )
    editors: list[_RegistrationQuestionEditor] = []
    for ordinal, question in enumerate(read.workspace.questions, start=1):
        update_form = RegistrationQuestionUpdateForm(
            section_choices=sections,
            condition_choices=(
                choice for choice in condition_choices if choice[0] != question.key
            ),
            expected_version=read.workspace.aggregate_version,
            ordinal=ordinal,
            initial={
                "key": question.key,
                "label": question.label,
                "help_text": question.help_text,
                "field_type": question.field_type,
                "options": "\n".join(question.options),
                "purpose": question.purpose,
                "classification": question.classification,
                "required": "true" if question.required else "false",
                "visibility": question.visibility,
                "section_id": str(question.section_id) if question.section_id else "",
                "condition_question_key": question.condition_question_key,
                "condition_value": question.condition_value,
            },
        )
        move_form = RegistrationQuestionMoveForm(
            placement_choices=_definition_choices(
                read.workspace.questions,
                label_attribute="label",
                exclude_id=question.id,
            ),
            expected_version=read.workspace.aggregate_version,
            ordinal=ordinal,
            initial={
                "after_question_id": _definition_predecessor(
                    read.workspace.questions,
                    question.id,
                )
            },
        )
        editors.append(
            _RegistrationQuestionEditor(
                question=question,
                ordinal=ordinal,
                update_form=update_form,
                move_form=move_form,
                delete_form=RegistrationDefinitionDeleteForm(
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                    kind="question",
                ),
            )
        )
    return tuple(editors)


def _product_editors(
    read: _RegistrationSetupPageRead,
) -> tuple[_RegistrationProductEditor, ...]:
    capacity_choices = tuple(
        (code, code) for code in read.workspace.active_capacity_codes
    )
    editors: list[_RegistrationProductEditor] = []
    for ordinal, product in enumerate(read.workspace.products, start=1):
        update_form = RegistrationProductUpdateForm(
            capacity_code_choices=capacity_choices,
            edition_time_zone=read.edition.time_zone,
            expected_version=read.workspace.aggregate_version,
            ordinal=ordinal,
            initial={
                "code": product.code,
                "name": product.name,
                "description": product.description,
                "price_minor": product.price_minor,
                "capacity": product.capacity,
                "capacity_ceiling": product.capacity_ceiling or product.capacity,
                "entitlement_code": product.entitlement_code,
                "entitlement_name": product.entitlement_name,
                "sales_open_at": product.sales_open_at,
                "sales_close_at": product.sales_close_at,
                "required_capacity_codes": product.required_capacity_codes,
                "eligibility_explanation": product.eligibility_explanation,
                "waitlist_enabled": ("true" if product.waitlist_enabled else "false"),
                "payment_window_minutes": product.payment_window_minutes,
            },
        )
        move_form = RegistrationProductMoveForm(
            placement_choices=_definition_choices(
                read.workspace.products,
                label_attribute="name",
                exclude_id=product.id,
            ),
            expected_version=read.workspace.aggregate_version,
            ordinal=ordinal,
            initial={
                "after_product_id": _definition_predecessor(
                    read.workspace.products,
                    product.id,
                )
            },
        )
        editors.append(
            _RegistrationProductEditor(
                product=product,
                ordinal=ordinal,
                update_form=update_form,
                move_form=move_form,
                delete_form=RegistrationDefinitionDeleteForm(
                    expected_version=read.workspace.aggregate_version,
                    ordinal=ordinal,
                    kind="product",
                ),
            )
        )
    return tuple(editors)


def _minor_policy_form(read: _RegistrationSetupPageRead) -> RegistrationMinorPolicyForm:
    policy = read.workspace.minor_policy
    configuration = read.workspace.current_configuration
    if configuration is None:
        raise Http404
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
        expected_version=read.workspace.aggregate_version,
        initial=initial,
    )


def _configuration_for_route(
    read: _RegistrationSetupPageRead,
    configuration_id: UUID,
) -> None:
    configuration = read.workspace.current_configuration
    if configuration is None or configuration.id != configuration_id:
        raise Http404


def _render_workspace(
    request: HttpRequest,
    *,
    read: _RegistrationSetupPageRead,
) -> HttpResponse:
    context = _base_context(request, read=read, page_id="registration-setup")
    context.update({"title": f"Registration — {read.edition.name}"})
    return _registration_response(
        request,
        template_name="registration/setup_workspace.html",
        context=context,
    )


def _render_start(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    form: RegistrationSetupStartForm | None = None,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> HttpResponse:
    read = _load_registration_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    if form is None:
        form = _new_start_form(read)
    else:
        choices, kinds = _source_choices(read.workspace)
        form.source_kinds_by_id = kinds
        source_field = cast("Any", form.fields["source_id"])
        source_field.set_choices((("", "No source record — start blank"), *choices))
    context = _base_context(
        request,
        read=read,
        page_id="registration-setup-start",
    )
    context.update(
        {
            "title": f"Start registration — {read.edition.name}",
            "form": form,
            "setup_start_available": read.workspace.current_configuration is None,
            "show_submitted_form": form.is_bound,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_start.html",
        context=context,
        status=status,
    )


def _render_configuration(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
    active_action: str = "",
    active_section_id: UUID | None = None,
    active_form: forms.Form | None = None,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> HttpResponse:
    read = _load_registration_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    _configuration_for_route(read, configuration_id)
    context = _base_context(
        request,
        read=read,
        page_id="registration-setup-configuration",
    )
    context.update(
        {
            "title": f"Registration builder — {read.edition.name}",
            "configuration": read.workspace.current_configuration,
            "section_editors": _section_editors(
                read,
                active_action=active_action,
                active_section_id=active_section_id,
                active_form=active_form,
            ),
            "question_editors": _question_editors(read),
            "product_editors": _product_editors(read),
            "minor_policy_form": _minor_policy_form(read),
            "minor_policy": read.workspace.minor_policy,
            "active_action": active_action,
            "active_section_id": active_section_id,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_configuration.html",
        context=context,
        status=status,
    )


def _render_section_create(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
    form: RegistrationSectionCreateForm | None = None,
    status: int = 200,
    action_error: str = "",
    reload_required: bool = False,
) -> HttpResponse:
    read = _load_registration_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    _configuration_for_route(read, configuration_id)
    choices = _placement_choices(read.workspace)
    if form is None:
        form = RegistrationSectionCreateForm(
            placement_choices=choices,
            expected_version=read.workspace.aggregate_version,
            initial={
                "after_section_id": (
                    str(read.workspace.sections[-1].id)
                    if read.workspace.sections
                    else ""
                )
            },
        )
    else:
        form.set_placement_choices(choices)
    context = _base_context(
        request,
        read=read,
        page_id="registration-setup-section-create",
    )
    context.update(
        {
            "title": f"Create registration section — {read.edition.name}",
            "configuration": read.workspace.current_configuration,
            "form": form,
            "show_submitted_form": form.is_bound,
            "action_error": action_error,
            "reload_required": reload_required,
        }
    )
    return _registration_response(
        request,
        template_name="registration/setup_section_create.html",
        context=context,
        status=status,
    )


def _preflight_post(
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> tuple[Account, _RegistrationSetupPageRead]:
    actor = _active_account(request)
    _authorize_registration_route(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    if request.GET:
        raise _RegistrationPostQueryParametersUnsupportedError
    return actor, _load_registration_page(
        request=request,
        actor=actor,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )


def _add_domain_validation_errors(
    form: forms.Form,
    error: ValidationError,
    *,
    allowed_fields: frozenset[str],
) -> bool:
    if not hasattr(error, "error_dict") or not error.error_dict:
        return False
    if any(
        field_name not in allowed_fields or field_name not in form.fields
        for field_name in error.error_dict
    ):
        return False
    for field_name, field_errors in error.error_dict.items():
        target: str | None = field_name
        if isinstance(form.fields[field_name].widget, forms.HiddenInput):
            target = None
        for field_error in field_errors:
            form.add_error(target, field_error)
    return True


def _command_conflict_message(  # noqa: PLR0911
    error: RegistrationSetupCommandError,
) -> str:
    if isinstance(error, RegistrationSetupVersionConflictError):
        return (
            "Registration setup changed after this form was opened. Your safe "
            "values remain shown; reload the latest builder before trying again."
        )
    if isinstance(error, RegistrationSetupRetryConflictError):
        return (
            "This browser retry identifier was already used with different "
            "values. Reload the latest form before trying again."
        )
    if isinstance(error, RegistrationSetupLifecycleConflictError):
        return "The edition or organization is now read-only for registration setup."
    if isinstance(error, RegistrationSetupSectionDependencyError):
        return (
            "This section is still referenced by a registration question, so "
            "Maru made no change. Remove that dependency through its future "
            "question workflow before deleting the section."
        )
    if isinstance(error, RegistrationSetupLimitExceededError):
        return "The complete registration setup reached a code-owned safety limit."
    if isinstance(error, RegistrationSetupSourceUnavailableError):
        return (
            "The selected source is no longer eligible or readable. Reload the "
            "source choices and select a current version."
        )
    if isinstance(error, RegistrationSetupStateConflictError):
        return "The stored registration setup no longer permits this exact action."
    return "The registration setup action could not be completed safely."


def _reload_required(error: RegistrationSetupCommandError) -> bool:
    return isinstance(
        error,
        (
            RegistrationSetupVersionConflictError,
            RegistrationSetupRetryConflictError,
            RegistrationSetupLifecycleConflictError,
            RegistrationSetupStateConflictError,
            RegistrationSetupSourceUnavailableError,
            RegistrationSetupLimitExceededError,
        ),
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_workspace(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Return registration setup workspace.

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

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_account(request)
    try:
        _authorize_registration_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        if request.GET:
            return _registration_bad_request(request)
        read = _load_registration_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        return _render_workspace(request, read=read)
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        _safe_dependency_log(request, operation="registration_setup_read")
        return _registration_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_start(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Return registration setup start.

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

    Raises
    ------
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    actor = _active_account(request)
    try:
        _authorize_registration_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        if request.GET:
            return _registration_bad_request(request)
        read = _load_registration_page(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        if read.workspace.current_configuration is not None:
            return _private_no_store(
                redirect(
                    _configuration_location(
                        read,
                        read.workspace.current_configuration.id,
                    )
                )
            )
        return _render_start(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        _safe_dependency_log(request, operation="registration_setup_start_read")
        return _registration_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_POST
def start_registration_setup_view(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
) -> HttpResponse:
    """Start registration setup view.

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
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        _safe_dependency_log(request, operation="registration_setup_start_preflight")
        return _registration_dependency_failure(request)
    form = _new_start_form(read, data=request.POST)
    if not form.is_valid():
        try:
            return _render_start(
                request,
                actor=actor,
                organization_slug=organization_slug,
                series_slug=series_slug,
                edition_slug=edition_slug,
                form=form,
                status=400,
                action_error="Review the highlighted values. Nothing was created.",
            )
        except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
            _safe_dependency_log(request, operation="registration_setup_start_invalid")
            return _registration_dependency_failure(request)

    correlation_id = _request_id(request)
    try:
        result = start_registration_setup_command(
            actor=actor,
            organization_id=read.organization.id,
            series_id=read.series.id,
            edition_id=read.edition.id,
            source_kind=cast("str", form.cleaned_data["source_kind"]),
            source_id=cast("UUID | None", form.cleaned_data["source_id"]),
            name=cast("str", form.cleaned_data["name"]),
            opens_at=cast("datetime | None", form.cleaned_data["opens_at"]),
            closes_at=cast("datetime | None", form.cleaned_data["closes_at"]),
            capacity=cast("int | None", form.cleaned_data["capacity"]),
            capacity_ceiling=cast(
                "int | None",
                form.cleaned_data["capacity_ceiling"],
            ),
            currency=cast("str | None", form.cleaned_data["currency"]),
            minimum_age=cast("int | None", form.cleaned_data["minimum_age"]),
            default_payment_window_minutes=cast(
                "int | None",
                form.cleaned_data["default_payment_window_minutes"],
            ),
            waitlist_enabled=cast("bool | None", form.cleaned_data["waitlist_enabled"]),
            automatic_waitlist_promotion=cast(
                "bool | None",
                form.cleaned_data["automatic_waitlist_promotion"],
            ),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset(form.fields),
        ):
            _safe_dependency_log(
                request,
                operation="registration_setup_start_validation",
            )
            return _registration_dependency_failure(request)
        try:
            return _render_start(
                request,
                actor=actor,
                organization_slug=organization_slug,
                series_slug=series_slug,
                edition_slug=edition_slug,
                form=form,
                status=400,
                action_error="Review the highlighted values. Nothing was created.",
            )
        except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
            return _registration_dependency_failure(request)
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        RegistrationSetupVersionConflictError,
        RegistrationSetupRetryConflictError,
        RegistrationSetupLifecycleConflictError,
        RegistrationSetupStateConflictError,
        RegistrationSetupSourceUnavailableError,
        RegistrationSetupLimitExceededError,
    ) as error:
        try:
            return _render_start(
                request,
                actor=actor,
                organization_slug=organization_slug,
                series_slug=series_slug,
                edition_slug=edition_slug,
                form=form,
                status=409,
                action_error=_command_conflict_message(error),
                reload_required=_reload_required(error),
            )
        except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
            return _registration_dependency_failure(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        _safe_dependency_log(request, operation="registration_setup_start_command")
        return _registration_dependency_failure(request)
    messages.success(
        request,
        (
            "Registration setup was already started by this exact browser request."
            if result.replayed
            else "Registration setup was started."
        ),
    )
    return _private_no_store(
        redirect(_configuration_location(read, result.configuration_id))
    )


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_configuration(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
) -> HttpResponse:
    """Return registration setup configuration.

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
    actor = _active_account(request)
    try:
        _authorize_registration_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        if request.GET:
            return _registration_bad_request(request)
        return _render_configuration(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        _safe_dependency_log(request, operation="registration_configuration_read")
        return _registration_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_GET
def registration_setup_section_create(
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
) -> HttpResponse:
    """Return registration setup section create.

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
    actor = _active_account(request)
    try:
        _authorize_registration_route(
            request=request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
        )
        if request.GET:
            return _registration_bad_request(request)
        return _render_section_create(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        _safe_dependency_log(request, operation="registration_section_create_read")
        return _registration_dependency_failure(request)


def _section_failure_response(
    request: HttpRequest,
    *,
    actor: Account,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
    section_id: UUID | None,
    action: str,
    form: forms.Form,
    status: int,
    action_error: str,
    reload_required: bool,
) -> HttpResponse:
    if action == "create" and not isinstance(form, RegistrationSectionCreateForm):
        _safe_dependency_log(
            request,
            operation="registration_section_create_render_contract",
        )
        return _registration_dependency_failure(request)
    if action != "create" and section_id is None:
        _safe_dependency_log(
            request,
            operation=f"registration_section_{action}_render_contract",
        )
        return _registration_dependency_failure(request)
    try:
        if action == "create":
            return _render_section_create(
                request,
                actor=actor,
                organization_slug=organization_slug,
                series_slug=series_slug,
                edition_slug=edition_slug,
                configuration_id=configuration_id,
                form=cast("RegistrationSectionCreateForm", form),
                status=status,
                action_error=action_error,
                reload_required=reload_required,
            )
        return _render_configuration(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            active_action=action,
            active_section_id=cast("UUID", section_id),
            active_form=form,
            status=status,
            action_error=action_error,
            reload_required=reload_required,
        )
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        _safe_dependency_log(request, operation=f"registration_section_{action}_render")
        return _registration_dependency_failure(request)


@never_cache
@login_required(login_url="staff-login")
@require_POST
def create_registration_setup_section(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
) -> HttpResponse:
    """Create registration setup section.

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
        The persisted record after validation and transaction commit.

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
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    choices = _placement_choices(read.workspace)
    form = RegistrationSectionCreateForm(
        request.POST,
        placement_choices=choices,
        expected_version=read.workspace.aggregate_version,
    )
    if not form.is_valid():
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=None,
            action="create",
            form=form,
            status=400,
            action_error="Review the highlighted values. No section was created.",
            reload_required=False,
        )
    correlation_id = _request_id(request)
    try:
        result = create_registration_section(
            actor=actor,
            organization_id=read.organization.id,
            series_id=read.series.id,
            edition_id=read.edition.id,
            configuration_id=configuration_id,
            key=cast("str", form.cleaned_data["key"]),
            title=cast("str", form.cleaned_data["title"]),
            description=cast("str", form.cleaned_data["description"]),
            after_section_id=cast("UUID | None", form.cleaned_data["after_section_id"]),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset(form.fields),
        ):
            return _registration_dependency_failure(request)
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=None,
            action="create",
            form=form,
            status=400,
            action_error="Review the highlighted values. No section was created.",
            reload_required=False,
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except RegistrationSetupConfigurationUnavailableError as error:
        raise Http404 from error
    except (
        RegistrationSetupVersionConflictError,
        RegistrationSetupRetryConflictError,
        RegistrationSetupLifecycleConflictError,
        RegistrationSetupStateConflictError,
        RegistrationSetupLimitExceededError,
    ) as error:
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=None,
            action="create",
            form=form,
            status=409,
            action_error=_command_conflict_message(error),
            reload_required=_reload_required(error),
        )
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    messages.success(
        request,
        "The section already exists for this browser request."
        if result.replayed
        else "Registration section created.",
    )
    return _private_no_store(redirect(_configuration_location(read, configuration_id)))


def _section_action_preflight(
    request: HttpRequest,
    *,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
    section_id: UUID,
) -> tuple[Account, _RegistrationSetupPageRead, int]:
    actor, read = _preflight_post(
        request,
        organization_slug=organization_slug,
        series_slug=series_slug,
        edition_slug=edition_slug,
    )
    _configuration_for_route(read, configuration_id)
    _find_section(read.workspace, section_id)
    return actor, read, _section_ordinal(read.workspace, section_id)


@never_cache
@login_required(login_url="staff-login")
@require_POST
def update_registration_setup_section(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
    section_id: UUID,
) -> HttpResponse:
    """Update registration setup section.

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
    section_id : UUID
        The identifier of the section.

    Returns
    -------
    HttpResponse
        The persisted record after validation and transaction commit.

    Raises
    ------
    Http404
        If the scoped resource is unavailable to the caller.
    PermissionDenied
        If the caller lacks permission for the requested scope.
    """
    try:
        actor, read, ordinal = _section_action_preflight(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
        )
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    form = RegistrationSectionUpdateForm(
        request.POST,
        expected_version=read.workspace.aggregate_version,
        ordinal=ordinal,
    )
    if not form.is_valid():
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="update",
            form=form,
            status=400,
            action_error="Review the highlighted values. The section was unchanged.",
            reload_required=False,
        )
    correlation_id = _request_id(request)
    try:
        result = update_registration_section(
            actor=actor,
            organization_id=read.organization.id,
            series_id=read.series.id,
            edition_id=read.edition.id,
            configuration_id=configuration_id,
            section_id=section_id,
            key=cast("str", form.cleaned_data["key"]),
            title=cast("str", form.cleaned_data["title"]),
            description=cast("str", form.cleaned_data["description"]),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset(form.fields),
        ):
            return _registration_dependency_failure(request)
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="update",
            form=form,
            status=400,
            action_error="Review the highlighted values. The section was unchanged.",
            reload_required=False,
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        RegistrationSetupConfigurationUnavailableError,
        RegistrationSetupSectionUnavailableError,
    ) as error:
        raise Http404 from error
    except (
        RegistrationSetupVersionConflictError,
        RegistrationSetupRetryConflictError,
        RegistrationSetupLifecycleConflictError,
        RegistrationSetupStateConflictError,
        RegistrationSetupLimitExceededError,
    ) as error:
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="update",
            form=form,
            status=409,
            action_error=_command_conflict_message(error),
            reload_required=_reload_required(error),
        )
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    messages.success(
        request,
        "The section already has this exact browser change."
        if result.replayed
        else "Registration section updated.",
    )
    return _private_no_store(redirect(_configuration_location(read, configuration_id)))


@never_cache
@login_required(login_url="staff-login")
@require_POST
def move_registration_setup_section(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
    section_id: UUID,
) -> HttpResponse:
    """Move registration setup section.

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
    section_id : UUID
        The identifier of the section.

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
        actor, read, ordinal = _section_action_preflight(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
        )
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    form = RegistrationSectionMoveForm(
        request.POST,
        placement_choices=_placement_choices(
            read.workspace,
            exclude_section_id=section_id,
        ),
        expected_version=read.workspace.aggregate_version,
        ordinal=ordinal,
    )
    if not form.is_valid():
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="move",
            form=form,
            status=400,
            action_error="Review the highlighted values. The order was unchanged.",
            reload_required=False,
        )
    correlation_id = _request_id(request)
    try:
        result = move_registration_section(
            actor=actor,
            organization_id=read.organization.id,
            series_id=read.series.id,
            edition_id=read.edition.id,
            configuration_id=configuration_id,
            section_id=section_id,
            after_section_id=cast("UUID | None", form.cleaned_data["after_section_id"]),
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset(form.fields),
        ):
            return _registration_dependency_failure(request)
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="move",
            form=form,
            status=400,
            action_error="Review the highlighted values. The order was unchanged.",
            reload_required=False,
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        RegistrationSetupConfigurationUnavailableError,
        RegistrationSetupSectionUnavailableError,
    ) as error:
        raise Http404 from error
    except (
        RegistrationSetupVersionConflictError,
        RegistrationSetupRetryConflictError,
        RegistrationSetupLifecycleConflictError,
        RegistrationSetupStateConflictError,
        RegistrationSetupLimitExceededError,
    ) as error:
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="move",
            form=form,
            status=409,
            action_error=_command_conflict_message(error),
            reload_required=_reload_required(error),
        )
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    messages.success(
        request,
        "The section already has this exact browser placement."
        if result.replayed
        else "Registration section moved.",
    )
    return _private_no_store(redirect(_configuration_location(read, configuration_id)))


@never_cache
@login_required(login_url="staff-login")
@require_POST
def remove_registration_setup_section(  # noqa: PLR0911
    request: HttpRequest,
    organization_slug: str,
    series_slug: str,
    edition_slug: str,
    configuration_id: UUID,
    section_id: UUID,
) -> HttpResponse:
    """Remove registration setup section.

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
    section_id : UUID
        The identifier of the section.

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
        actor, read, ordinal = _section_action_preflight(
            request,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
        )
    except _RegistrationPostQueryParametersUnsupportedError:
        return _registration_bad_request(request)
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    form = RegistrationSectionDeleteForm(
        request.POST,
        expected_version=read.workspace.aggregate_version,
        ordinal=ordinal,
    )
    if not form.is_valid():
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="delete",
            form=form,
            status=400,
            action_error="Review the highlighted values. The section was not removed.",
            reload_required=False,
        )
    correlation_id = _request_id(request)
    try:
        result = delete_registration_section(
            actor=actor,
            organization_id=read.organization.id,
            series_id=read.series.id,
            edition_id=read.edition.id,
            configuration_id=configuration_id,
            section_id=section_id,
            expected_version=cast("int", form.cleaned_data["expected_version"]),
            reason=cast("str", form.cleaned_data["reason"]),
            retry_key=cast("UUID", form.cleaned_data["retry_key"]),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="web",
        )
    except ValidationError as error:
        if not _add_domain_validation_errors(
            form,
            error,
            allowed_fields=frozenset(form.fields),
        ):
            return _registration_dependency_failure(request)
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="delete",
            form=form,
            status=400,
            action_error="Review the highlighted values. The section was not removed.",
            reload_required=False,
        )
    except RegistrationSetupAuthorizationDeniedError as error:
        raise PermissionDenied from error
    except (
        RegistrationSetupConfigurationUnavailableError,
        RegistrationSetupSectionUnavailableError,
    ) as error:
        raise Http404 from error
    except (
        RegistrationSetupVersionConflictError,
        RegistrationSetupRetryConflictError,
        RegistrationSetupLifecycleConflictError,
        RegistrationSetupStateConflictError,
        RegistrationSetupSectionDependencyError,
        RegistrationSetupLimitExceededError,
    ) as error:
        return _section_failure_response(
            request,
            actor=actor,
            organization_slug=organization_slug,
            series_slug=series_slug,
            edition_slug=edition_slug,
            configuration_id=configuration_id,
            section_id=section_id,
            action="delete",
            form=form,
            status=409,
            action_error=_command_conflict_message(error),
            reload_required=_reload_required(error),
        )
    except (DatabaseError, RegistrationSetupDependencyError, RuntimeError):
        return _registration_dependency_failure(request)
    messages.success(
        request,
        "The section was already removed by this exact browser request."
        if result.replayed
        else "Registration section removed.",
    )
    return _private_no_store(redirect(_configuration_location(read, configuration_id)))


__all__ = [
    "create_registration_setup_section",
    "move_registration_setup_section",
    "registration_setup_configuration",
    "registration_setup_section_create",
    "registration_setup_start",
    "registration_setup_workspace",
    "remove_registration_setup_section",
    "start_registration_setup_view",
    "update_registration_setup_section",
]
