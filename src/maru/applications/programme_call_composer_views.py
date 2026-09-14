"""Dormant call creation and structured graph editing through existing owners."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import ChoiceField
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, QueryDict
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.core.forms import StrictBase10IntegerField
from maru.events.scheduling_queries import resolve_scheduling_edition_reference

from . import programme_call_composer_forms as controls
from . import programme_commands as commands
from . import programme_queries as queries
from .programme_authorization import ApplicationsProgrammeAuthorizationDeniedError
from .programme_write_scope import lock_programme_edition_write_scope

if TYPE_CHECKING:
    from django import forms

    from maru.events.scheduling_queries import SchedulingEditionReference
from .programme_call_editor import (
    ProgrammeCallEditorConflictError,
    ProgrammeCallEditorInputs,
    edit_programme_call_question,
    edit_programme_call_section,
    move_programme_call_question,
    programme_call_editor_inputs,
)
from .programme_call_forms import ProgrammeCallConfirmationForm, ProgrammeCallTaskForm
from .programme_call_views import (
    _CONFLICTS,
    _MAX_INPUT_LENGTH,
    _SOURCE,
    _UNAVAILABLE,
    _authorize,
    _render,
    _root,
    _Scope,
    _scope_values,
    _secure,
)
from .programme_inputs import (
    ProgrammeCallQuestionInput,
    ProgrammeCallQuestionOptionInput,
    ProgrammeCallSectionInput,
)

_TASKS = {"create", "section", "question", "remove-section", "remove-question"}
_OPTION_KEY = re.compile(r"options-(0|[1-9][0-9]?)-(code|label|DELETE)\Z")
_MANAGEMENT = {
    f"options-{name}"
    for name in ("TOTAL_FORMS", "INITIAL_FORMS", "MIN_NUM_FORMS", "MAX_NUM_FORMS")
}


@dataclass
class _Bundle:
    evidence: ProgrammeCallTaskForm
    section: controls.ProgrammeSectionForm | None = None
    question: controls.ProgrammeQuestionForm | None = None
    options: forms.BaseFormSet[controls.ProgrammeQuestionOptionForm] | None = None

    def displayed_forms(self) -> list[dict[str, Any]]:
        """Return labelled task forms followed by their original command evidence.

        Returns
        -------
        list[dict[str, Any]]
            Ordered form groups for the shared accessible task template.
        """
        values: list[dict[str, Any]] = []
        if isinstance(self.evidence, controls.ProgrammeCallCreationForm):
            groups = {
                "Call identity and collection": (
                    "code",
                    "name",
                    "description",
                    "purpose",
                    "classification",
                    "maximum_submissions_per_person",
                    "maximum_collaborators",
                ),
                "Explicit policy references": (
                    "audience_policy_code",
                    "retention_policy_code",
                    "content_policy_code",
                    "contributor_consent_policy_code",
                    "collaboration_retention_policy_code",
                ),
                "Edition-local deadlines": (
                    "opens_at",
                    "applicant_edit_until",
                    "closes_at",
                ),
                "Initial track and format": (
                    "track_code",
                    "track_label",
                    "format_code",
                    "format_label",
                    "minimum_duration_minutes",
                    "default_duration_minutes",
                    "maximum_duration_minutes",
                ),
            }
            values.extend(
                {"legend": legend, "fields": [self.evidence[name] for name in names]}
                for legend, names in groups.items()
            )
            values.append(
                {
                    "legend": "Confirm this starting draft",
                    "form": self.evidence,
                    "fields": [
                        self.evidence[name]
                        for name in (
                            "expected_version",
                            "expected_edition_version",
                            "retry_key",
                            "reason",
                            "confirm",
                        )
                    ],
                }
            )
            return values
        if self.section is not None:
            values.append(
                {"legend": "Section", "form": self.section, "fields": self.section}
            )
        if self.question is not None:
            values.append(
                {"legend": "Question", "form": self.question, "fields": self.question}
            )
        values.append(
            {
                "legend": "Confirm this task",
                "form": self.evidence,
                "fields": self.evidence,
            }
        )
        return values


def _has_question(task: str, section: int | None) -> bool:
    return task == "question" or (task == "section" and section is None)


def _request_shape(
    request: HttpRequest, task: str, section: int | None, row: int | None
) -> str:
    if any(
        value is not None and (type(value) is not int or value < 0)
        for value in (section, row)
    ):
        raise ValueError
    if request.GET or request.FILES or task not in _TASKS:
        raise ValueError
    if task == "create" and (section is not None or row is not None):
        raise ValueError
    if (row is not None and "question" not in task) or (
        "question" in task and section is None
    ):
        raise ValueError
    if task.startswith("remove-") and (
        section is None or (task == "remove-question" and row is None)
    ):
        raise ValueError
    if request.method != "POST":
        return "save"
    evidence_type = (
        controls.ProgrammeCallCreationForm
        if task == "create"
        else ProgrammeCallTaskForm
    )
    if task.startswith("remove-"):
        evidence_type = ProgrammeCallConfirmationForm
    allowed = {*evidence_type.base_fields, "csrfmiddlewaretoken", "intent"}
    if task == "section":
        allowed.update(
            f"section-{name}" for name in controls.ProgrammeSectionForm.base_fields
        )
    if _has_question(task, section):
        allowed.update(
            f"question-{name}" for name in controls.ProgrammeQuestionForm.base_fields
        )
        allowed.update(_option_transport(request.POST))
    if set(request.POST) - allowed or any(
        len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
        for _, values in request.POST.lists()
    ):
        raise ValueError
    intent = request.POST.get("intent", "save")
    if intent not in {"save", "add-option"} or (
        intent == "add-option" and not _has_question(task, section)
    ):
        raise ValueError
    return intent


def _option_transport(data: QueryDict) -> set[str]:
    allowed = set(_MANAGEMENT)
    count = StrictBase10IntegerField(min_value=0, max_value=100).clean(
        data.get("options-TOTAL_FORMS")
    )
    initial = StrictBase10IntegerField(min_value=0, max_value=100).clean(
        data.get("options-INITIAL_FORMS")
    )
    if initial > count:
        raise ValueError
    for name in data:
        match = _OPTION_KEY.fullmatch(name)
        if match is not None and int(match[1]) < count:
            allowed.add(name)
    return allowed


def _data(request: HttpRequest, names: set[str]) -> QueryDict | None:
    if request.method != "POST":
        return None
    result = QueryDict(mutable=True)
    for name in names:
        if name in request.POST:
            result.setlist(name, request.POST.getlist(name))
    return result


def _question_initial(question: ProgrammeCallQuestionInput | None) -> dict[str, Any]:
    if question is None:
        return {}
    result = {field.name: getattr(question, field.name) for field in fields(question)}
    condition = question.condition
    if condition is not None:
        value = condition.value
        result.update(
            condition_question=condition.question_key,
            condition_operator=condition.operator,
            condition_value=str(value).lower() if type(value) is bool else str(value),
        )
    return result


def _bundle(
    request: HttpRequest,
    graph: ProgrammeCallEditorInputs,
    task: str,
    section: int | None,
    row: int | None,
    version: int,
) -> _Bundle:
    sections = graph.definition.sections
    if (
        section is not None
        and not 0 <= section < len(sections)
        and request.method != "POST"
    ):
        raise ValueError
    selected = (
        sections[section]
        if section is not None and 0 <= section < len(sections)
        else None
    )
    if (
        row is not None
        and (selected is None or not 0 <= row < len(selected.questions))
        and request.method != "POST"
    ):
        raise ValueError
    evidence_type = (
        ProgrammeCallConfirmationForm
        if task.startswith("remove-")
        else ProgrammeCallTaskForm
    )
    evidence = evidence_type(
        _data(request, set(evidence_type.base_fields)),
        initial={"expected_version": version, "retry_key": uuid4()},
    )
    bundle = _Bundle(evidence)
    if task == "section":
        initial: dict[str, Any] = {"position": len(sections) + 1}
        if selected is not None:
            initial = {
                name: getattr(selected, name)
                for name in controls.ProgrammeSectionForm.base_fields
            }
        bundle.section = controls.ProgrammeSectionForm(
            request.POST if request.method == "POST" else None,
            prefix="section",
            initial=initial,
        )
    if not _has_question(task, section):
        return bundle
    question = (
        selected.questions[row]
        if selected is not None
        and row is not None
        and 0 <= row < len(selected.questions)
        else None
    )
    earlier = tuple(
        question
        for index, item in enumerate(sections)
        for offset, question in enumerate(item.questions)
        if section is None
        or index < section
        or (index == section and (row is None or offset < row))
    )
    initial = {
        "position": len(selected.questions) + 1 if selected else 1,
        "classification": graph.definition.classification,
        **_question_initial(question),
    }
    bundle.question = controls.ProgrammeQuestionForm(
        request.POST if request.method == "POST" else None,
        prefix="question",
        initial=initial,
        earlier_questions=earlier,
    )
    if task == "question" and row is not None:
        destination = bundle.question.fields["destination_section"]
        if isinstance(destination, ChoiceField):
            destination.choices = [("", "Keep this section")] + [
                (item.key, item.title)
                for offset, item in enumerate(sections)
                if offset != section
            ]
    option_initial = (
        [{"code": value.code, "label": value.label} for value in question.options]
        if question
        else []
    )
    bundle.options = controls.ProgrammeQuestionOptions(
        request.POST if request.method == "POST" else None,
        prefix="options",
        initial=option_initial,
    )
    return bundle


def _question_input(bundle: _Bundle) -> ProgrammeCallQuestionInput:
    if bundle.question is None or bundle.options is None:
        raise ValueError
    values = tuple(
        ProgrammeCallQuestionOptionInput(
            form.cleaned_data["code"], form.cleaned_data["label"]
        )
        for form in bundle.options.forms
        if form.cleaned_data and not form.cleaned_data.get("DELETE")
    )
    return bundle.question.question_input(values)


def _compose(
    bundle: _Bundle,
    graph: ProgrammeCallEditorInputs,
    task: str,
    section: int | None,
    row: int | None,
) -> ProgrammeCallEditorInputs:
    if task == "remove-section":
        return edit_programme_call_section(graph, index=section, value=None)
    if task == "section":
        if bundle.section is None:
            raise ValueError
        questions = (
            (_question_input(bundle),)
            if section is None
            else graph.definition.sections[section].questions
        )
        value = ProgrammeCallSectionInput(
            **bundle.section.cleaned_data, questions=questions
        )
        return edit_programme_call_section(graph, index=section, value=value)
    if section is None:
        raise ValueError
    if (
        bundle.question is not None
        and bundle.question.cleaned_data["destination_section"]
    ):
        if row is None:
            raise ValidationError("Add a question from its intended section.")
        destination_index = next(
            index
            for index, item in enumerate(graph.definition.sections)
            if item.key == bundle.question.cleaned_data["destination_section"]
        )
        return move_programme_call_question(
            graph,
            section_index=section,
            index=row,
            destination_index=destination_index,
            value=_question_input(bundle),
        )
    return edit_programme_call_question(
        graph,
        section_index=section,
        index=row,
        value=None if task == "remove-question" else _question_input(bundle),
    )


def _valid(bundle: _Bundle) -> bool:
    results = [bundle.evidence.is_valid()]
    results.extend(
        form.is_valid()
        for form in (bundle.section, bundle.question, bundle.options)
        if form is not None
    )
    if bundle.options is not None and results[-1]:
        initial = StrictBase10IntegerField(min_value=0, max_value=100).clean(
            bundle.options.data.get("options-INITIAL_FORMS")
        )
        if initial != len(bundle.options.initial or []):
            raise ValidationError(
                "The original option count changed. Reload before a fresh attempt."
            )
    return all(results)


def _error(bundle: _Bundle, error: ValidationError | None = None) -> None:
    if error is None:
        bundle.evidence.add_error(
            None,
            "The call, edition or retry state changed. Original input and versions "
            "are retained. An earlier attempt may already have succeeded; review "
            "the current call before a fresh attempt.",
        )
    else:
        bundle.evidence.add_error(None, error.messages)


def _save(
    scope: _Scope,
    source: queries.ProgrammeCallConfigurationProjection,
    graph: ProgrammeCallEditorInputs,
    bundle: _Bundle,
    task: str,
    section: int | None,
    row: int | None,
) -> HttpResponse | None:
    if not _valid(bundle):
        return None
    updated = _compose(bundle, graph, task, section, row)
    result = commands.configure_programme_call(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        owner_department_id=scope.department_id,
        call_id=source.summary.call_id,
        definition_input=updated.definition,
        configuration=updated.configuration,
        correlation_id=scope.correlation_id,
        source_channel=_SOURCE,
        **{
            name: bundle.evidence.cleaned_data[name]
            for name in ("expected_version", "retry_key", "reason")
        },
    )
    return _secure(HttpResponseRedirect(f"{_root(scope)}{result.target_id}/overview/"))


def _selected_coordinates(
    graph: ProgrammeCallEditorInputs, section: int | None, row: int | None
) -> None:
    if section is not None and section >= len(graph.definition.sections):
        raise ValidationError("The selected section is no longer available.")
    if (
        row is not None
        and section is not None
        and row >= len(graph.definition.sections[section].questions)
    ):
        raise ValidationError("The selected question is no longer available.")


def _add_option(bundle: _Bundle, request: HttpRequest) -> None:
    if bundle.options is None:
        raise ValueError
    count = StrictBase10IntegerField(min_value=0, max_value=100).clean(
        request.POST.get("options-TOTAL_FORMS")
    )
    maximum_rows = 100
    if count >= maximum_rows:
        raise ValidationError(
            "A question may have at most 100 option rows. "
            "Use or replace an existing row."
        )
    data = request.POST.copy()
    data["options-TOTAL_FORMS"] = str(count + 1)
    bundle.options = controls.ProgrammeQuestionOptions(
        data, prefix="options", initial=bundle.options.initial
    )
    bundle.options.forms[-1].fields["code"].widget.attrs["autofocus"] = True


def _edit_post(
    request: HttpRequest,
    scope: _Scope,
    source: queries.ProgrammeCallConfigurationProjection,
    graph: ProgrammeCallEditorInputs,
    bundle: _Bundle,
    task: str,
    section: int | None,
    row: int | None,
    intent: str,
) -> tuple[HttpResponse | None, int]:
    try:
        original = StrictBase10IntegerField().clean(
            request.POST.get("expected_version")
        )
        if original != source.summary.aggregate_version:
            raise ProgrammeCallEditorConflictError
        _selected_coordinates(graph, section, row)
        if intent == "add-option":
            _add_option(bundle, request)
            return None, 200
        response = _save(scope, source, graph, bundle, task, section, row)
    except _CONFLICTS:
        _error(bundle)
        return None, 409
    except ValidationError as error:
        _error(bundle, error)
        return None, 400
    else:
        return response, 302 if response is not None else 400


def _create(
    request: HttpRequest,
    scope: _Scope,
    context: dict[str, Any],
    edition: SchedulingEditionReference,
) -> HttpResponse:
    form = controls.ProgrammeCallCreationForm(
        _data(request, set(controls.ProgrammeCallCreationForm.base_fields)),
        initial={
            "expected_version": 0,
            "expected_edition_version": edition.version,
            "retry_key": uuid4(),
        },
        edition_time_zone=edition.zone_name,
    )
    bundle = _Bundle(form)
    status = 200
    if request.method == "POST":
        try:
            original = StrictBase10IntegerField(min_value=1).clean(
                request.POST.get("expected_edition_version")
            )
            if original != edition.version:
                raise ProgrammeCallEditorConflictError
            status = 400
            if form.is_valid():
                graph = form.call_inputs(owner_department_id=scope.department_id)
                with transaction.atomic():
                    lock_programme_edition_write_scope(
                        actor_id=scope.actor_id,
                        organization_id=scope.organization_id,
                        edition_id=scope.edition_id,
                        department_ids=(scope.department_id,),
                    )
                    _authorize(scope)
                    current = resolve_scheduling_edition_reference(
                        organization_id=scope.organization_id,
                        edition_id=scope.edition_id,
                    )
                    if current is None or current.version != original:
                        raise ProgrammeCallEditorConflictError
                    result = commands.create_programme_call(
                        actor_id=scope.actor_id,
                        organization_id=scope.organization_id,
                        edition_id=scope.edition_id,
                        definition_input=graph.definition,
                        configuration=graph.configuration,
                        correlation_id=scope.correlation_id,
                        source_channel=_SOURCE,
                        **{
                            name: form.cleaned_data[name]
                            for name in ("expected_version", "retry_key", "reason")
                        },
                    )
                return _secure(
                    HttpResponseRedirect(f"{_root(scope)}{result.target_id}/overview/")
                )
        except _CONFLICTS:
            _error(bundle)
            status = 409
        except ValidationError as error:
            _error(bundle, error)
    context.update(composer_forms=bundle.displayed_forms(), creating=True)
    return _render(
        request,
        scope,
        context,
        status,
        template="applications/programme_call_composer.html",
    )


def _serve(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None,
    task: str,
    section: int | None,
    row: int | None,
) -> HttpResponse:
    intent = _request_shape(request, task, section, row)
    if not isinstance(request.user.pk, UUID) or (task == "create") != (call_id is None):
        raise ApplicationsProgrammeAuthorizationDeniedError
    scope = _Scope(request.user.pk, organization_id, edition_id, department_id, uuid4())
    planning = _authorize(scope)
    department = queries.get_managed_programme_call_department(**_scope_values(scope))
    edition = resolve_scheduling_edition_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if edition is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    context: dict[str, Any] = {
        "department": department,
        "task": task,
        "pending": request.method == "POST",
        "zone_name": edition.zone_name,
        "task_label": {
            "create": "Create a call draft",
            "section": "Compose section",
            "question": "Compose question",
            "remove-section": "Remove section and its questions",
            "remove-question": "Remove question",
        }[task],
    }
    if call_id is None:
        if not planning:
            raise ApplicationsProgrammeAuthorizationDeniedError
        return _create(request, scope, context, edition)
    source = queries.get_managed_programme_call_configuration(
        **_scope_values(scope), call_id=call_id
    )
    context.update(source=source, call_url=f"{_root(scope)}{call_id}/")
    if not planning or source.summary.status != "draft":
        if request.method == "POST":
            raise ApplicationsProgrammeAuthorizationDeniedError
        return _render(
            request,
            scope,
            context,
            template="applications/programme_call_composer.html",
        )
    graph = programme_call_editor_inputs(
        source, expected_version=source.summary.aggregate_version
    )
    bundle = _bundle(
        request, graph, task, section, row, source.summary.aggregate_version
    )
    status = 200
    if request.method == "POST":
        response, status = _edit_post(
            request, scope, source, graph, bundle, task, section, row, intent
        )
        if response is not None:
            return response
    selected = (
        graph.definition.sections[section]
        if section is not None and section < len(graph.definition.sections)
        else None
    )
    if selected is not None:
        context["selected_label"] = (
            selected.questions[row].label
            if row is not None and row < len(selected.questions)
            else selected.title
        )
    context.update(
        composer_forms=bundle.displayed_forms(),
        options=bundle.options,
        removing=task.startswith("remove-"),
        option_added=intent == "add-option" and status == HTTPStatus.OK,
    )
    return _render(
        request,
        scope,
        context,
        status,
        template="applications/programme_call_composer.html",
    )


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_call_composer(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None = None,
    task: str = "create",
    section: int | None = None,
    row: int | None = None,
) -> HttpResponse:
    """Serve an explicit new call or one exact structured graph task.

    Parameters
    ----------
    request : HttpRequest
        Authenticated, CSRF-checked request with closed bounded fields.
    organization_id : UUID
        Independently authorized organization scope.
    edition_id : UUID
        Exact edition owning the Department and call.
    department_id : UUID
        Current exact Department, not inferred through hierarchy.
    call_id : UUID | None, default=None
        Exact call or no call for deliberate creation.
    task : str, default='create'
        Closed creation, section, question or confirmed-removal operation.
    section : int | None, default=None
        Original section offset or no offset for insertion.
    row : int | None, default=None
        Original question offset or no offset for insertion.

    Returns
    -------
    HttpResponse
        Protected form, confirmed owner-command redirect or safe refusal.
    """
    try:
        return _serve(
            request,
            organization_id,
            edition_id,
            department_id,
            call_id,
            task,
            section,
            row,
        )
    except ApplicationsProgrammeAuthorizationDeniedError:
        return _secure(HttpResponse("Call workspace unavailable.", status=404))
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "Call workspace temporarily unavailable. Review the current "
                "call before a fresh attempt.",
                status=503,
            )
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("The call workspace cannot accept this request.", status=400)
        )
