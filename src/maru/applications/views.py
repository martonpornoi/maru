"""Same-shell organizer, applicant, and reviewer application journeys."""

from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import Form
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from maru.applications.commands import (
    ApplicationAuthorizationDenied,
    ApplicationCommandError,
    ApplicationEligibilityDenied,
    ApplicationUnavailable,
    activate_definition,
    add_question,
    add_section,
    append_answer_revision,
    configure_definition,
    create_definition_from_starter,
    create_successor_definition,
    record_review_decision,
    retire_definition,
    start_submission,
    submit_application,
)
from maru.applications.forms import (
    ApplicantAnswerForm,
    DefinitionConfigureForm,
    DefinitionLifecycleForm,
    DefinitionSuccessorForm,
    QuestionAddForm,
    ReviewDecisionForm,
    SectionAddForm,
    StarterCopyForm,
    StartSubmissionForm,
    SubmitApplicationForm,
    answer_initial_value,
)
from maru.applications.models import (
    ApplicationDefinition,
    ApplicationQuestion,
    ApplicationState,
    ApplicationSubmission,
    ReviewDecisionKind,
)
from maru.applications.queries import (
    available_applications,
    definition_detail,
    definition_workspace,
    my_application_editions,
    my_submission_detail,
    my_submissions,
    review_queue,
    review_submission_detail,
)
from maru.applications.serializers import decision_history, latest_answers
from maru.applications.source_adapters import source_bound_value
from maru.applications.starters import application_starter, starter_catalog
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.models import RoleBundle
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.workforce.models import Department


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account) or not request.user.is_active:
        raise PermissionDenied
    return request.user


def _correlation_id(request: HttpRequest) -> UUID:
    return UUID(str(request.correlation_id))  # type: ignore[attr-defined]


def _edition(organization_id: UUID, edition_id: UUID) -> EventEdition:
    edition = (
        EventEdition.objects.select_related("organization", "series")
        .filter(id=edition_id, organization_id=organization_id)
        .first()
    )
    if edition is None:
        raise Http404
    return edition


def _context(
    request: HttpRequest,
    *,
    edition: EventEdition | None = None,
    personal: bool,
    **values: object,
) -> dict[str, object]:
    context = admin.site.each_context(request)
    context.update(values)
    context["has_permission"] = True
    context["maru_personal_surface"] = personal
    if edition is not None:
        context.update(
            edition=edition,
            organization=edition.organization,
            convention_series=edition.series,
        )
    return context


def _response(
    request: HttpRequest,
    template_name: str,
    context: dict[str, object],
    *,
    status: int = 200,
) -> HttpResponse:
    response = TemplateResponse(request, template_name, context, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _strict_get(request: HttpRequest) -> HttpResponse | None:
    if request.GET:
        return HttpResponseBadRequest("This applications page has no query options.")
    return None


def _audit_read(
    *,
    request: HttpRequest,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    operation: str,
    target_count: int,
    target_id: UUID | None = None,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            target_type="applications.edition_workspace",
            target_id=target_id or edition_id,
            outcome="allow",
            reason_code="applications_workspace_read",
            correlation_id=_correlation_id(request),
            source_channel="html",
            obligations=("audit_sensitive_read",),
            safe_metadata={"target_count": target_count},
        )
    )


def _add_command_error(form: Form, error: Exception) -> int:
    if isinstance(error, ApplicationAuthorizationDenied):
        raise PermissionDenied from error
    if isinstance(error, ApplicationUnavailable):
        raise Http404 from error
    if isinstance(error, ApplicationEligibilityDenied):
        raise PermissionDenied from error
    if isinstance(error, ValidationError):
        if hasattr(error, "message_dict"):
            for field_name, field_errors in error.message_dict.items():
                target = field_name if field_name in form.fields else None
                for field_error in field_errors:
                    form.add_error(target, field_error)
        else:
            for message in error.messages:
                form.add_error(None, message)
        return 400
    if isinstance(error, ApplicationCommandError):
        form.add_error(
            None,
            "The application workflow changed. Reload before trying again.",
        )
        return 409
    raise error


def _departments(definition: ApplicationDefinition) -> tuple[Department, ...]:
    return tuple(
        Department.objects.filter(
            organization_id=definition.organization_id,
            edition_id=definition.edition_id,
            retired_at__isnull=True,
        ).order_by("name", "id")
    )


def _reviewer_roles(definition: ApplicationDefinition) -> tuple[RoleBundle, ...]:
    required = {"applications.review"}
    if definition.is_sensitive:
        required.add("applications.review_sensitive")
    return tuple(
        role
        for role in RoleBundle.objects.filter(
            organization_id=definition.organization_id
        ).order_by("name", "-version", "id")
        if required <= set(role.capability_codes)
    )


def _configuration_initial(definition: ApplicationDefinition) -> dict[str, object]:
    return {
        "retry_key": str(uuid4()),
        "expected_version": definition.aggregate_version,
        "name": definition.name,
        "description": definition.description,
        "purpose": definition.purpose,
        "classification": definition.classification,
        "eligibility_kind": definition.eligibility_kind,
        "maximum_submissions": definition.max_submissions_per_person,
        "opens_at": definition.opens_at,
        "closes_at": definition.closes_at,
        "applicant_edit_until": definition.applicant_edit_until,
        "minimum_age": definition.minimum_age,
        "audience_policy_code": definition.audience_policy_code,
        "retention_policy_code": definition.retention_policy_code,
        "age_policy_code": definition.age_policy_code,
        "owner_department_ids": [
            str(value)
            for value in definition.owner_department_links.values_list(
                "department_id", flat=True
            )
        ],
        "reviewer_role_bundle_ids": [
            str(value)
            for value in definition.reviewer_roles.values_list(
                "role_bundle_id", flat=True
            )
        ],
        "reviewer_emails": "\n".join(
            definition.reviewer_people.values_list("account__email", flat=True)
        ),
    }


def _definition_forms(
    definition: ApplicationDefinition,
    *,
    active_name: str = "",
    active_form: Form | None = None,
) -> dict[str, Form]:
    departments = _departments(definition)
    roles = _reviewer_roles(definition)
    values: dict[str, Form] = {
        "configuration_form": DefinitionConfigureForm(
            initial=_configuration_initial(definition),
            departments=departments,
            roles=roles,
            edition_time_zone=definition.edition.time_zone,
        ),
        "section_form": SectionAddForm(
            initial={
                "retry_key": str(uuid4()),
                "expected_version": definition.aggregate_version,
            }
        ),
        "question_form": QuestionAddForm(
            initial={
                "retry_key": str(uuid4()),
                "expected_version": definition.aggregate_version,
                "classification": definition.classification,
                "applicant_visible": True,
                "applicant_writable": True,
                "staff_visible": True,
                "reviewer_visible": True,
                "api_projection": True,
            },
            definition=definition,
        ),
        "lifecycle_form": DefinitionLifecycleForm(
            initial={
                "retry_key": str(uuid4()),
                "expected_version": definition.aggregate_version,
            }
        ),
        "successor_form": DefinitionSuccessorForm(initial={"retry_key": str(uuid4())}),
    }
    if active_name and active_form is not None:
        values[active_name] = active_form
    return values


def _definition_response(
    request: HttpRequest,
    *,
    edition: EventEdition,
    definition: ApplicationDefinition,
    active_name: str = "",
    active_form: Form | None = None,
    status: int = 200,
) -> HttpResponse:
    context = _context(
        request,
        edition=edition,
        personal=False,
        title=f"{definition.name} configuration",
        definition=definition,
        **_definition_forms(
            definition,
            active_name=active_name,
            active_form=active_form,
        ),
    )
    return _response(
        request,
        "applications/definition_detail.html",
        context,
        status=status,
    )


@login_required(login_url="staff-login")
@require_GET
def application_definition_workspace(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    try:
        definitions = definition_workspace(
            actor=_actor(request),
            organization_id=organization_id,
            edition_id=edition_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    edition = _edition(organization_id, edition_id)
    return _response(
        request,
        "applications/definition_workspace.html",
        _context(
            request,
            edition=edition,
            personal=False,
            title="Applications",
            definitions=definitions,
            starters=starter_catalog(),
        ),
    )


@login_required(login_url="staff-login")
@require_GET
def application_starter_copy_page(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    starter_code: str,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    definition_workspace(
        actor=_actor(request),
        organization_id=organization_id,
        edition_id=edition_id,
    )
    starter = application_starter(starter_code)
    if starter is None or starter.is_external:
        raise Http404
    now = timezone.now()
    edition = _edition(organization_id, edition_id)
    form = StarterCopyForm(
        initial={
            "retry_key": str(uuid4()),
            "opens_at": now,
            "closes_at": now + timedelta(days=30),
            "applicant_edit_until": now + timedelta(days=29),
        },
        edition_time_zone=edition.time_zone,
    )
    return _response(
        request,
        "applications/starter_copy.html",
        _context(
            request,
            edition=edition,
            personal=False,
            title=f"Copy {starter.name}",
            starter=starter,
            form=form,
        ),
    )


@login_required(login_url="staff-login")
@require_POST
def application_starter_copy(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    starter_code: str,
) -> HttpResponse:
    actor = _actor(request)
    definition_workspace(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    starter = application_starter(starter_code)
    if starter is None or starter.is_external:
        raise Http404
    edition = _edition(organization_id, edition_id)
    form = StarterCopyForm(request.POST, edition_time_zone=edition.time_zone)
    status = 400
    if form.is_valid():
        try:
            result = create_definition_from_starter(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                starter_code=starter.code,
                opens_at=form.cleaned_data["opens_at"],
                closes_at=form.cleaned_data["closes_at"],
                applicant_edit_until=form.cleaned_data["applicant_edit_until"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, "An independent edition draft was created.")
            return redirect(
                "application-definition-detail",
                organization_id,
                edition_id,
                result.definition_id,
            )
    return _response(
        request,
        "applications/starter_copy.html",
        _context(
            request,
            edition=edition,
            personal=False,
            title=f"Copy {starter.name}",
            starter=starter,
            form=form,
        ),
        status=status,
    )


@login_required(login_url="staff-login")
@require_GET
def application_definition_detail(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    try:
        definition = definition_detail(
            actor=_actor(request),
            organization_id=organization_id,
            edition_id=edition_id,
            definition_id=definition_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    return _definition_response(
        request,
        edition=_edition(organization_id, edition_id),
        definition=definition,
    )


def _definition_for_post(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> tuple[Account, EventEdition, ApplicationDefinition]:
    actor = _actor(request)
    try:
        definition = definition_detail(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            definition_id=definition_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    return actor, _edition(organization_id, edition_id), definition


@login_required(login_url="staff-login")
@require_POST
def application_definition_configure(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> HttpResponse:
    actor, edition, definition = _definition_for_post(
        request, organization_id, edition_id, definition_id
    )
    form = DefinitionConfigureForm(
        request.POST,
        departments=_departments(definition),
        roles=_reviewer_roles(definition),
        edition_time_zone=edition.time_zone,
    )
    status = 400
    if form.is_valid():
        try:
            configure_definition(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                definition_id=definition_id,
                expected_version=form.cleaned_data["expected_version"],
                name=form.cleaned_data["name"],
                description=form.cleaned_data["description"],
                purpose=form.cleaned_data["purpose"],
                classification=form.cleaned_data["classification"],
                eligibility_kind=form.cleaned_data["eligibility_kind"],
                maximum_submissions=form.cleaned_data["maximum_submissions"],
                opens_at=form.cleaned_data["opens_at"],
                closes_at=form.cleaned_data["closes_at"],
                applicant_edit_until=form.cleaned_data["applicant_edit_until"],
                minimum_age=form.cleaned_data["minimum_age"],
                audience_policy_code=form.cleaned_data["audience_policy_code"],
                retention_policy_code=form.cleaned_data["retention_policy_code"],
                age_policy_code=form.cleaned_data["age_policy_code"],
                owner_department_ids=form.cleaned_data["owner_department_ids"],
                reviewer_role_bundle_ids=form.cleaned_data["reviewer_role_bundle_ids"],
                reviewer_account_ids=form.reviewer_account_ids,
                reason=form.cleaned_data["reason"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, "The application draft was configured.")
            return redirect(
                "application-definition-detail",
                organization_id,
                edition_id,
                definition_id,
            )
    return _definition_response(
        request,
        edition=edition,
        definition=definition,
        active_name="configuration_form",
        active_form=form,
        status=status,
    )


@login_required(login_url="staff-login")
@require_POST
def application_section_add(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> HttpResponse:
    actor, edition, definition = _definition_for_post(
        request, organization_id, edition_id, definition_id
    )
    form = SectionAddForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            add_section(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                definition_id=definition_id,
                expected_version=form.cleaned_data["expected_version"],
                key=form.cleaned_data["key"],
                title=form.cleaned_data["title"],
                help_text=form.cleaned_data["help_text"],
                reason=form.cleaned_data["reason"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, "A draft section was added.")
            return redirect(
                "application-definition-detail",
                organization_id,
                edition_id,
                definition_id,
            )
    return _definition_response(
        request,
        edition=edition,
        definition=definition,
        active_name="section_form",
        active_form=form,
        status=status,
    )


@login_required(login_url="staff-login")
@require_POST
def application_question_add(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> HttpResponse:
    actor, edition, definition = _definition_for_post(
        request, organization_id, edition_id, definition_id
    )
    form = QuestionAddForm(request.POST, definition=definition)
    status = 400
    if form.is_valid():
        try:
            add_question(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                definition_id=definition_id,
                section_id=form.cleaned_data["section_id"],
                expected_version=form.cleaned_data["expected_version"],
                key=form.cleaned_data["key"],
                field_type=form.cleaned_data["field_type"],
                label=form.cleaned_data["label"],
                help_text=form.cleaned_data["help_text"],
                required=form.cleaned_data["required"],
                options=form.cleaned_data["options_text"],
                minimum_length=form.cleaned_data.get("minimum_length"),
                maximum_length=form.cleaned_data.get("maximum_length"),
                minimum_value=form.cleaned_data.get("minimum_value"),
                maximum_value=form.cleaned_data.get("maximum_value"),
                maximum_choices=form.cleaned_data.get("maximum_choices"),
                reference_kind=form.cleaned_data["reference_kind"],
                condition=form.condition,
                purpose=form.cleaned_data["purpose"],
                classification=form.cleaned_data["classification"],
                applicant_visible=form.cleaned_data["applicant_visible"],
                applicant_writable=form.cleaned_data["applicant_writable"],
                staff_visible=form.cleaned_data["staff_visible"],
                staff_writable=form.cleaned_data["staff_writable"],
                reviewer_visible=form.cleaned_data["reviewer_visible"],
                public_after_approval=form.cleaned_data["public_after_approval"],
                api_projection=form.cleaned_data["api_projection"],
                retention_policy_code=form.cleaned_data["retention_policy_code"],
                reason=form.cleaned_data["reason"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, "A typed draft question was added.")
            return redirect(
                "application-definition-detail",
                organization_id,
                edition_id,
                definition_id,
            )
    return _definition_response(
        request,
        edition=edition,
        definition=definition,
        active_name="question_form",
        active_form=form,
        status=status,
    )


def _lifecycle_command(
    request: HttpRequest,
    *,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
    operation: str,
) -> HttpResponse:
    actor, edition, definition = _definition_for_post(
        request, organization_id, edition_id, definition_id
    )
    form = DefinitionLifecycleForm(request.POST)
    status = 400
    if form.is_valid():
        command = activate_definition if operation == "activate" else retire_definition
        try:
            command(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                definition_id=definition_id,
                expected_version=form.cleaned_data["expected_version"],
                reason=form.cleaned_data["reason"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, f"The application definition was {operation}d.")
            return redirect(
                "application-definition-detail",
                organization_id,
                edition_id,
                definition_id,
            )
    return _definition_response(
        request,
        edition=edition,
        definition=definition,
        active_name="lifecycle_form",
        active_form=form,
        status=status,
    )


@login_required(login_url="staff-login")
@require_POST
def application_definition_activate(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> HttpResponse:
    return _lifecycle_command(
        request,
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
        operation="activate",
    )


@login_required(login_url="staff-login")
@require_POST
def application_definition_retire(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> HttpResponse:
    return _lifecycle_command(
        request,
        organization_id=organization_id,
        edition_id=edition_id,
        definition_id=definition_id,
        operation="retire",
    )


@login_required(login_url="staff-login")
@require_POST
def application_definition_successor(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> HttpResponse:
    actor, edition, definition = _definition_for_post(
        request, organization_id, edition_id, definition_id
    )
    form = DefinitionSuccessorForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            result = create_successor_definition(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                definition_id=definition_id,
                reason=form.cleaned_data["reason"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, "An independent successor draft was created.")
            return redirect(
                "application-definition-detail",
                organization_id,
                edition_id,
                result.definition_id,
            )
    return _definition_response(
        request,
        edition=edition,
        definition=definition,
        active_name="successor_form",
        active_form=form,
        status=status,
    )


def _start_form() -> StartSubmissionForm:
    return StartSubmissionForm(initial={"retry_key": str(uuid4())})


@login_required(login_url="staff-login")
@require_GET
def my_application_index(request: HttpRequest) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    actor = _actor(request)
    try:
        editions = my_application_editions(actor=actor)
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    rows: list[dict[str, object]] = []
    for edition in editions:
        available = available_applications(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        submissions = my_submissions(
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        _audit_read(
            request=request,
            actor=actor,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            capability_code="applications.view_self",
            operation="applications.self_index.read",
            target_count=len(available) + len(submissions),
        )
        rows.append(
            {
                "edition": edition,
                "available_count": len(available),
                "submission_count": len(submissions),
            }
        )
    return _response(
        request,
        "applications/my_application_index.html",
        _context(
            request,
            personal=True,
            title="My applications",
            edition_rows=rows,
        ),
    )


@login_required(login_url="staff-login")
@require_GET
def my_application_workspace(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    actor = _actor(request)
    try:
        available = available_applications(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        submissions = my_submissions(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    _audit_read(
        request=request,
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.view_self",
        operation="applications.self_workspace.read",
        target_count=len(available) + len(submissions),
    )
    edition = _edition(organization_id, edition_id)
    return _response(
        request,
        "applications/my_applications.html",
        _context(
            request,
            edition=edition,
            personal=True,
            title="My applications",
            available_rows=tuple(
                {"definition": item, "form": _start_form()} for item in available
            ),
            submissions=submissions,
        ),
    )


@login_required(login_url="staff-login")
@require_POST
def application_submission_start(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    definition_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    form = StartSubmissionForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("The application start request is invalid.")
    try:
        result = start_submission(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            definition_id=definition_id,
            retry_key=form.cleaned_data["retry_key"],
            correlation_id=_correlation_id(request),
            source_channel="html",
        )
    except Exception as error:  # noqa: BLE001
        status = _add_command_error(form, error)
        return HttpResponse(
            "The application could not be started.",
            status=status,
        )
    messages.success(request, "Your application draft was created.")
    return redirect(
        "my-application-detail",
        organization_id,
        edition_id,
        result.submission_id,
    )


def _submission_answer_rows(
    *,
    actor: Account,
    submission: ApplicationSubmission,
) -> tuple[dict[str, object], ...]:
    current = {
        str(item["question_id"]): item["value"]
        for item in latest_answers(submission, audience="applicant")
    }
    rows: list[dict[str, object]] = []
    for question in submission.definition.questions.filter(
        applicant_visible=True
    ).order_by("section__position", "position", "id"):
        value = current.get(str(question.id))
        sourced_value: object | None = None
        if question.source_binding:
            sourced_value = source_bound_value(question=question, account=actor)
        form: ApplicantAnswerForm | None = None
        if question.applicant_writable:
            form = ApplicantAnswerForm(
                question=question,
                initial={
                    "retry_key": str(uuid4()),
                    "question_id": str(question.id),
                    "expected_version": submission.aggregate_version,
                    "value": answer_initial_value(value),
                },
            )
        rows.append(
            {
                "question": question,
                "current_value": value,
                "sourced_value": sourced_value,
                "form": form,
            }
        )
    return tuple(rows)


def _submission_response(
    request: HttpRequest,
    *,
    actor: Account,
    edition: EventEdition,
    submission: ApplicationSubmission,
    active_question_id: UUID | None = None,
    active_form: ApplicantAnswerForm | SubmitApplicationForm | None = None,
    status: int = 200,
) -> HttpResponse:
    rows = list(_submission_answer_rows(actor=actor, submission=submission))
    if active_question_id is not None and isinstance(active_form, ApplicantAnswerForm):
        for row in rows:
            question = cast(ApplicationQuestion, row["question"])
            if question.id == active_question_id:
                row["form"] = active_form
                break
    submit_form: SubmitApplicationForm = SubmitApplicationForm(
        initial={
            "retry_key": str(uuid4()),
            "expected_version": submission.aggregate_version,
        }
    )
    if isinstance(active_form, SubmitApplicationForm):
        submit_form = active_form
    editable = (
        submission.state
        in {
            ApplicationState.DRAFT,
            ApplicationState.CHANGES_REQUESTED,
        }
        and timezone.now() <= submission.definition.applicant_edit_until
    )
    return _response(
        request,
        "applications/my_application_detail.html",
        _context(
            request,
            edition=edition,
            personal=True,
            title=submission.definition.name,
            submission=submission,
            answer_rows=rows,
            submit_form=submit_form,
            editable=editable,
            decision_history=decision_history(submission),
        ),
        status=status,
    )


@login_required(login_url="staff-login")
@require_GET
def my_application_detail(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    actor = _actor(request)
    try:
        submission = my_submission_detail(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    answers = latest_answers(submission, audience="applicant")
    _audit_read(
        request=request,
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.view_self",
        operation="applications.self_submission.read",
        target_count=len(answers),
        target_id=submission.id,
    )
    return _submission_response(
        request,
        actor=actor,
        edition=_edition(organization_id, edition_id),
        submission=submission,
    )


def _owned_submission_for_post(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> ApplicationSubmission:
    try:
        return my_submission_detail(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error


@login_required(login_url="staff-login")
@require_POST
def application_answer_append(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    submission = _owned_submission_for_post(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        submission_id=submission_id,
    )
    raw_question_id = request.POST.get("question_id", "")
    question = next(
        (
            item
            for item in submission.definition.questions.all()
            if str(item.id) == raw_question_id
            and item.applicant_visible
            and item.applicant_writable
        ),
        None,
    )
    if question is None:
        raise Http404
    form = ApplicantAnswerForm(request.POST, question=question)
    status = 400
    if form.is_valid():
        try:
            append_answer_revision(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                submission_id=submission_id,
                question_id=question.id,
                expected_version=form.cleaned_data["expected_version"],
                value=form.cleaned_data["value"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, "Your answer revision was saved.")
            return redirect(
                "my-application-detail",
                organization_id,
                edition_id,
                submission_id,
            )
    return _submission_response(
        request,
        actor=actor,
        edition=_edition(organization_id, edition_id),
        submission=submission,
        active_question_id=question.id,
        active_form=form,
        status=status,
    )


@login_required(login_url="staff-login")
@require_POST
def application_submit(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    submission = _owned_submission_for_post(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        submission_id=submission_id,
    )
    form = SubmitApplicationForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            submit_application(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                submission_id=submission_id,
                expected_version=form.cleaned_data["expected_version"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, "Your application was submitted.")
            return redirect(
                "my-application-detail",
                organization_id,
                edition_id,
                submission_id,
            )
    return _submission_response(
        request,
        actor=actor,
        edition=_edition(organization_id, edition_id),
        submission=submission,
        active_form=form,
        status=status,
    )


@login_required(login_url="staff-login")
@require_GET
def application_review_workspace(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    actor = _actor(request)
    try:
        submissions = review_queue(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    _audit_read(
        request=request,
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.review",
        operation="applications.review_queue.read",
        target_count=len(submissions),
    )
    edition = _edition(organization_id, edition_id)
    return _response(
        request,
        "applications/review_workspace.html",
        _context(
            request,
            edition=edition,
            personal=False,
            title="Application review",
            submissions=submissions,
        ),
    )


def _review_forms(submission: ApplicationSubmission) -> tuple[ReviewDecisionForm, ...]:
    allowed: tuple[str, ...]
    if submission.state == ApplicationState.SUBMITTED:
        allowed = (
            ReviewDecisionKind.START_REVIEW,
            ReviewDecisionKind.REQUEST_CHANGES,
            ReviewDecisionKind.ACCEPT,
            ReviewDecisionKind.REJECT,
        )
    elif submission.state == ApplicationState.UNDER_REVIEW:
        allowed = (
            ReviewDecisionKind.REQUEST_CHANGES,
            ReviewDecisionKind.ACCEPT,
            ReviewDecisionKind.REJECT,
        )
    elif submission.state == ApplicationState.CHANGES_REQUESTED:
        allowed = (ReviewDecisionKind.ACCEPT, ReviewDecisionKind.REJECT)
    else:
        allowed = ()
    return tuple(
        ReviewDecisionForm(
            initial={
                "retry_key": str(uuid4()),
                "expected_version": submission.aggregate_version,
                "decision": decision,
            }
        )
        for decision in allowed
    )


def _review_response(
    request: HttpRequest,
    *,
    edition: EventEdition,
    submission: ApplicationSubmission,
    active_form: ReviewDecisionForm | None = None,
    status: int = 200,
) -> HttpResponse:
    answers = latest_answers(submission, audience="reviewer")
    forms = list(_review_forms(submission))
    if active_form is not None:
        forms = [active_form]
    return _response(
        request,
        "applications/review_detail.html",
        _context(
            request,
            edition=edition,
            personal=False,
            title=f"Review {submission.definition.name}",
            submission=submission,
            answers=answers,
            decisions=submission.review_decisions.all(),
            review_forms=forms,
        ),
        status=status,
    )


@login_required(login_url="staff-login")
@require_GET
def application_review_detail(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> HttpResponse:
    invalid = _strict_get(request)
    if invalid is not None:
        return invalid
    actor = _actor(request)
    try:
        submission = review_submission_detail(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    answers = latest_answers(submission, audience="reviewer")
    _audit_read(
        request=request,
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="applications.review",
        operation="applications.review_submission.read",
        target_count=len(answers),
        target_id=submission.id,
    )
    return _review_response(
        request,
        edition=_edition(organization_id, edition_id),
        submission=submission,
    )


@login_required(login_url="staff-login")
@require_POST
def application_review_decision(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    submission_id: UUID,
) -> HttpResponse:
    actor = _actor(request)
    try:
        submission = review_submission_detail(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
            submission_id=submission_id,
        )
    except ApplicationAuthorizationDenied as error:
        raise PermissionDenied from error
    form = ReviewDecisionForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            record_review_decision(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                submission_id=submission_id,
                expected_version=form.cleaned_data["expected_version"],
                decision=form.cleaned_data["decision"],
                reason=form.cleaned_data["reason"],
                retry_key=form.cleaned_data["retry_key"],
                correlation_id=_correlation_id(request),
                source_channel="html",
            )
        except Exception as error:  # noqa: BLE001
            status = _add_command_error(form, error)
        else:
            messages.success(request, "The accountable review decision was recorded.")
            return redirect(
                "application-review-detail",
                organization_id,
                edition_id,
                submission_id,
            )
    return _review_response(
        request,
        edition=_edition(organization_id, edition_id),
        submission=submission,
        active_form=form,
        status=status,
    )
