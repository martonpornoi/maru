"""Dormant exact-authority Department navigation and explicit Draft transfer."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from . import programme_call_departments as departments
from . import programme_commands as commands
from . import programme_queries as queries
from .programme_authorization import ApplicationsProgrammeAuthorizationDeniedError
from .programme_call_forms import ProgrammeCallConfirmationForm, _apply_errors
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

if TYPE_CHECKING:
    from maru.workforce.queries import CurrentDepartmentChoiceReference


class ProgrammeCallTransferForm(ProgrammeCallConfirmationForm):
    """Choose an independently admitted destination and confirm the consequence."""

    destination_department_id = forms.ChoiceField(label="Destination Department")

    def __init__(
        self,
        *args: Any,
        choices: tuple[CurrentDepartmentChoiceReference, ...],
        **kwargs: Any,
    ) -> None:
        """Populate labels only from the complete protected owner projection.

        Parameters
        ----------
        *args : Any
            Framework arguments, including optional retained bound input.
        choices : tuple[CurrentDepartmentChoiceReference, ...]
            Admitted destinations excluding the current owner.
        **kwargs : Any
            Framework keywords including original version and retry identity.
        """
        super().__init__(*args, **kwargs)
        cast("forms.ChoiceField", self.fields["destination_department_id"]).choices = [
            ("", "Choose the destination Department"),
            *(
                (str(item.department_id), f"{item.label} ({item.code})")
                for item in choices
            ),
        ]
        self.fields["confirm"].label = (
            "I confirm the selected Department will own this call; its configuration "
            "and retained history will not be rewritten."
        )


def _scope(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None,
) -> _Scope:
    if not isinstance(request.user.pk, UUID):
        raise ApplicationsProgrammeAuthorizationDeniedError
    if request.GET or request.FILES:
        raise ValueError
    if request.method == "POST":
        if call_id is None:
            raise ValueError
        allowed = {*ProgrammeCallTransferForm.base_fields, "csrfmiddlewaretoken"}
        if set(request.POST) - allowed or any(
            len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
            for _, values in request.POST.lists()
        ):
            raise ValueError
    return _Scope(request.user.pk, organization_id, edition_id, department_id, uuid4())


def _post(
    scope: _Scope,
    source: queries.ProgrammeCallConfigurationProjection,
    form: ProgrammeCallTransferForm,
) -> tuple[HttpResponse | None, int]:
    if not form.is_valid():
        return None, 400
    if form.cleaned_data["expected_version"] != source.summary.aggregate_version:
        form.add_error(
            None,
            "The call changed. Your original input is retained. Review its current "
            "ownership and configuration before a fresh attempt; an earlier attempt "
            "may already have succeeded.",
        )
        return None, 409
    destination = UUID(form.cleaned_data["destination_department_id"])
    try:
        result = commands.reassign_programme_call(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            call_id=source.summary.call_id,
            source_department_id=scope.department_id,
            destination_department_id=destination,
            expected_version=form.cleaned_data["expected_version"],
            reason=form.cleaned_data["reason"],
            retry_key=form.cleaned_data["retry_key"],
            correlation_id=scope.correlation_id,
            source_channel=_SOURCE,
        )
    except _CONFLICTS:
        form.add_error(
            None,
            "Call ownership, lifecycle or retry state changed. Your original input "
            "is retained. Check the current authorized Department inventories before "
            "a fresh attempt; an earlier transfer may already have succeeded.",
        )
        return None, 409
    except ValidationError as error:
        _apply_errors(form, error)
        return None, 400
    destination_root = _root(replace(scope, department_id=destination))
    return _secure(
        HttpResponseRedirect(f"{destination_root}{result.target_id}/overview/")
    ), 302


def _serve(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None,
) -> HttpResponse:
    scope = _scope(request, organization_id, edition_id, department_id, call_id)
    planning = _authorize(scope)
    values = _scope_values(scope)
    department = queries.get_managed_programme_call_department(**values)
    context: dict[str, Any] = {
        "department": department,
        "task": "reassign" if call_id else "departments",
        "task_label": "Transfer call to another Department"
        if call_id
        else "Choose Department",
        "pending": request.method == "POST",
    }
    status = 200
    if call_id is not None:
        source = queries.get_managed_programme_call_configuration(
            **values, call_id=call_id
        )
        context.update(source=source, call_url=f"{_root(scope)}{call_id}/")
        if not planning or source.summary.status != "draft":
            if request.method == "POST":
                raise ApplicationsProgrammeAuthorizationDeniedError
            context["read_only"] = True
            return _render(
                request,
                scope,
                context,
                template="applications/programme_call_departments.html",
            )
    choices = departments.list_managed_programme_call_departments(**values)
    current = next(
        (item for item in choices if item.department_id == department_id), None
    )
    if current is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    context["source_department_code"] = current.code
    context["department_choices"] = tuple(
        {
            "label": item.label,
            "code": item.code,
            "current": item.department_id == department_id,
            "url": _root(replace(scope, department_id=item.department_id)),
        }
        for item in choices
    )
    if call_id is not None:
        destinations = tuple(
            item for item in choices if item.department_id != department_id
        )
        if destinations or request.method == "POST":
            form = ProgrammeCallTransferForm(
                request.POST if request.method == "POST" else None,
                choices=destinations,
                initial={
                    "expected_version": source.summary.aggregate_version,
                    "retry_key": uuid4(),
                },
            )
            context["form"] = form
            if request.method == "POST":
                response, status = _post(scope, source, form)
                if response is not None:
                    return response
        else:
            context["no_destination"] = True
    return _render(
        request,
        scope,
        context,
        status,
        template="applications/programme_call_departments.html",
    )


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_call_departments(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID | None = None,
) -> HttpResponse:
    """Show the complete admitted chooser or one explicit Draft transfer task.

    Parameters
    ----------
    request : HttpRequest
        Authenticated strict transport with no caller-selected authority.
    organization_id : UUID
        Exact expected organization owner.
    edition_id : UUID
        Exact expected edition owner.
    department_id : UUID
        Independently admitted current anchor or source Department.
    call_id : UUID | None, default=None
        Exact source Draft call, or ``None`` for read-only Department navigation.

    Returns
    -------
    HttpResponse
        Protected HTML, destination redirect or nondisclosing refusal.
    """
    try:
        return _serve(request, organization_id, edition_id, department_id, call_id)
    except ApplicationsProgrammeAuthorizationDeniedError:
        return _secure(
            HttpResponse(
                "Call workspace unavailable. Use the current authorized Department "
                "inventories to locate calls. An earlier transfer may already "
                "have succeeded.",
                status=404,
            )
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "Call workspace temporarily unavailable. No partial choices are "
                "shown. Review current ownership before a new attempt.",
                status=503,
            )
        )
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("The call workspace cannot accept this request.", status=400)
        )
