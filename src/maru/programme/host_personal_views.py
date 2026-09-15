"""Dormant genuine-person hosting decisions without organizer-layer disclosure."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.core.forms import StrictBase10IntegerField
from maru.events.queries import resolve_edition_time_envelope_reference
from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.scheduling.personal_navigation import (
    PersonalProgrammeTaskLink,
    personal_programme_task_links,
)

from . import commands, host_commands, host_queries, queries
from .authorization import ProgrammeAuthorizationDeniedError
from .host_catalogs import MAX_HOST_AVAILABILITY_PERIODS
from .host_forms import (
    ProgrammeHostAvailabilityForm,
    ProgrammeHostAvailabilityFormSet,
    ProgrammeHostAvailabilityWithdrawalForm,
    ProgrammeHostPersonalForm,
    ProgrammeHostResponseForm,
)
from .host_inputs import (
    ProgrammeHostAvailabilityInput,
    ProgrammeHostAvailabilityPeriod,
    ProgrammeHostResponseInput,
)
from .host_views import (
    _allowed,
    _authorize,
    _conflict,
    _errors,
    _host_request,
    _html,
    _input,
    _scope,
)
from .timetable_queries import load_personal_host_purposes
from .workbench_views import _CONFLICTS, _secure

if TYPE_CHECKING:
    from .workbench_queries import ProgrammeWorkbenchRequest

_FORMS: dict[str, type[ProgrammeHostPersonalForm]] = {
    "invitation": ProgrammeHostResponseForm,
    "availability": ProgrammeHostAvailabilityForm,
    "withdraw-availability": ProgrammeHostAvailabilityWithdrawalForm,
}
_TASKS = frozenset(
    {"inventory", "invitation", "availability", "withdraw-availability", "history"}
)
_SELF_RESPONSE = "programme.respond_host_self"
_SELF_AVAILABILITY = "programme.manage_host_availability_self"


def _root(scope: ProgrammeWorkbenchRequest) -> str:
    return f"/my/programme/hosting/{scope.organization_id}/{scope.edition_id}/"


def _selection(request: HttpRequest, task: str, item_id: UUID | None) -> None:
    if request.GET or request.FILES or task not in _TASKS:
        raise ValueError
    if (item_id is None) != (task == "inventory"):
        raise ValueError
    if request.method == "POST" and task not in _FORMS:
        raise ValueError


def _edition(scope: ProgrammeWorkbenchRequest) -> dict[str, Any]:
    edition = resolve_scheduling_edition_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    envelope = resolve_edition_time_envelope_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if edition is None or envelope is None or edition.version != envelope.version:
        raise queries.ProgrammeQueryUnavailableError
    try:
        zone = ZoneInfo(edition.zone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise queries.ProgrammeQueryUnavailableError from error
    return {
        "edition_version": edition.version,
        "zone_name": edition.zone_name,
        "edition_starts": envelope.starts_at.astimezone(zone),
        "edition_ends": envelope.ends_at.astimezone(zone),
    }


def _context(
    scope: ProgrammeWorkbenchRequest, item_id: UUID | None, task: str
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "personal": True,
        "page_title": "My hosting",
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
        "root_url": _root(scope),
        "task": task,
        "item_id": item_id,
    }
    if item_id is None:
        context["purposes"] = load_personal_host_purposes(
            **asdict(scope), purpose="hosting"
        )
        return context
    snapshot = host_queries.load_programme_host_self(_host_request(scope, item_id))
    invitation = next(
        (
            copy
            for copy in snapshot.invitations
            if copy.sequence == snapshot.relationship.invitation_sequence
        ),
        None,
    )
    if invitation is None:
        raise queries.ProgrammeQueryUnavailableError
    can_respond = _allowed(scope, _SELF_RESPONSE)
    can_confirm = can_respond and _allowed(scope, _SELF_RESPONSE, planning=True)
    state = snapshot.relationship.state
    responses = []
    if state == "invited" and can_respond:
        if can_confirm:
            responses.append(("confirm", "Confirm my hosting"))
        responses.append(("decline", "Decline this invitation"))
    elif state == "confirmed" and can_respond:
        responses.append(("withdraw", "Withdraw my confirmed hosting"))
    context.update(
        snapshot=snapshot,
        invitation=invitation,
        page_title=f"My hosting — {invitation.title}",
        responses=tuple(responses),
        can_availability=state == "confirmed"
        and _allowed(scope, _SELF_AVAILABILITY, planning=True),
        can_withdraw_availability=state == "confirmed"
        and snapshot.availability_state != "withdrawn"
        and _allowed(scope, _SELF_AVAILABILITY),
    )
    if task == "availability":
        context.update(_edition(scope))
    return context


def _initial(context: dict[str, Any]) -> dict[str, Any]:
    snapshot = context["snapshot"]
    return {
        "expected_item_version": snapshot.item_version,
        "expected_host_version": snapshot.relationship.version,
        "idempotency_key": uuid4(),
    }


def _personal_html(
    request: HttpRequest,
    scope: ProgrammeWorkbenchRequest,
    context: dict[str, Any],
    status: int = 200,
) -> HttpResponse:
    def links() -> tuple[PersonalProgrammeTaskLink, ...]:
        return personal_programme_task_links(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            current="hosting",
            urlconf=getattr(request, "urlconf", None),
        )

    navigation = links()
    response = _html(request, context | {"personal_task_links": navigation}, status)
    if navigation and navigation != links():
        response = _html(request, context | {"personal_task_links": ()}, status)
    # Re-read after the final render, including after optional-link recovery.
    # Bound forms are deliberately not rebuilt from the fresh source versions.
    fresh = _context(scope, context["item_id"], context["task"])
    if any(context.get(key) != value for key, value in fresh.items()):
        raise queries.ProgrammeQueryUnavailableError
    return response


def _forms(context: dict[str, Any], task: str, data: Any = None) -> dict[str, Any]:
    initial = _initial(context) if data is None else {}
    snapshot = context["snapshot"]
    if task == "invitation":
        if data is None:
            initial["invitation_sequence"] = snapshot.relationship.invitation_sequence
        form = ProgrammeHostResponseForm(data=data, initial=initial)
        if data is None:
            form.fields["response"] = forms.ChoiceField(
                choices=(("", "Choose your response"), *context["responses"]),
            )
        return {"form": form}
    if task == "withdraw-availability":
        return {
            "form": ProgrammeHostAvailabilityWithdrawalForm(data=data, initial=initial)
        }
    if data is None:
        initial.update(
            expected_edition_version=context["edition_version"],
            state=snapshot.availability_state
            if snapshot.availability_state in {"draft", "shared"}
            else "",
        )
    # The request-wide closed-field/duplicate check runs before binding. Keep
    # formset transport out of the independently strict decision form.
    decision_data = (
        {name: data.get(name, "") for name in ProgrammeHostAvailabilityForm.base_fields}
        if data is not None
        else None
    )
    return {
        "form": ProgrammeHostAvailabilityForm(data=decision_data, initial=initial),
        "period_formset": ProgrammeHostAvailabilityFormSet(
            data=data,
            prefix="periods",
            initial=[asdict(period) for period in snapshot.periods],
            form_kwargs={"zone_name": context["zone_name"]},
        ),
    }


def _can_edit(context: dict[str, Any], task: str) -> bool:
    return bool(
        {
            "invitation": context["responses"],
            "availability": context["can_availability"],
            "withdraw-availability": context["can_withdraw_availability"],
        }.get(task, False)
    )


def _permitted(request: HttpRequest, task: str) -> set[str]:
    permitted = set(_FORMS[task].base_fields)
    if task == "availability":
        count_field = StrictBase10IntegerField(
            min_value=0, max_value=MAX_HOST_AVAILABILITY_PERIODS
        )
        try:
            total = count_field.clean(request.POST.get("periods-TOTAL_FORMS"))
            initial = count_field.clean(request.POST.get("periods-INITIAL_FORMS"))
        except ValidationError as error:
            raise ValueError from error
        if total is None or initial is None or initial > total:
            raise ValueError
        permitted.update(
            f"periods-{name}"
            for name in (
                "TOTAL_FORMS",
                "INITIAL_FORMS",
                "MIN_NUM_FORMS",
                "MAX_NUM_FORMS",
            )
        )
        permitted.update(
            f"periods-{index}-{name}"
            for index in range(total)
            for name in ("starts_at", "ends_at", "kind", "DELETE")
        )
    return permitted


def _write(
    scope: ProgrammeWorkbenchRequest, capability: str, *, planning: bool
) -> None:
    admitted = _authorize(scope, capability)
    if planning and not admitted.accepts_private_planning_writes:
        raise ProgrammeAuthorizationDeniedError


def _submit(
    scope: ProgrammeWorkbenchRequest,
    item_id: UUID,
    task: str,
    context: dict[str, Any],
    forms: dict[str, Any],
) -> None:
    values = forms["form"].cleaned_data
    snapshot = context["snapshot"]
    common = {
        **asdict(scope),
        "item_id": item_id,
        "idempotency_key": values["idempotency_key"],
        "source_channel": "programme-hosts",
    }
    if task == "invitation":
        _write(scope, _SELF_RESPONSE, planning=values["response"] == "confirm")
        host_commands.respond_to_programme_host_invitation(
            **common,
            response=ProgrammeHostResponseInput(
                snapshot.relationship.host_id,
                values["response"],
                values["expected_item_version"],
                values["expected_host_version"],
                values["invitation_sequence"],
            ),
        )
        return
    withdrawal = task == "withdraw-availability"
    _write(scope, _SELF_AVAILABILITY, planning=not withdrawal)
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...] = ()
    if not withdrawal:
        if values["expected_edition_version"] != context["edition_version"]:
            raise commands.ProgrammeVersionConflictError
        periods = tuple(
            ProgrammeHostAvailabilityPeriod(
                row["starts_at"], row["ends_at"], row["kind"]
            )
            for row in forms["period_formset"].cleaned_data
            if row and not row.get("DELETE")
        )
    host_commands.replace_programme_host_availability(
        **common,
        availability=ProgrammeHostAvailabilityInput(
            snapshot.relationship.host_id,
            "withdrawn" if withdrawal else values["state"],
            periods,
            values["expected_item_version"],
            values["expected_host_version"],
        ),
    )


def _post(
    scope: ProgrammeWorkbenchRequest,
    request: HttpRequest,
    item_id: UUID,
    task: str,
    context: dict[str, Any],
) -> HttpResponse:
    capability = _SELF_RESPONSE if task == "invitation" else _SELF_AVAILABILITY
    _authorize(scope, capability)
    _input(request, _permitted(request, task))
    bound = _forms(context, task, request.POST)
    valid = bound["form"].is_valid()
    if "period_formset" in bound:
        valid = bound["period_formset"].is_valid() and valid
    status = 400
    if valid:
        try:
            _submit(scope, item_id, task, context, bound)
        except ValidationError as error:
            _errors(bound["form"], error)
        except _CONFLICTS:
            _conflict(bound["form"])
            status = 409
        else:
            messages.success(
                request,
                "Your hosting decision was recorded for this item only.",
                fail_silently=True,
            )
            return _secure(HttpResponseRedirect(f"{_root(scope)}{item_id}/invitation/"))
    context = _context(scope, item_id, task)
    _authorize(scope, capability)
    context.update(
        bound,
        message=(
            "Your decision was not saved. Original input and versions are retained."
        ),
        pending=True,
    )
    return _personal_html(request, scope, context, status)


@never_cache
@login_required
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def personal_programme_hosts(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID | None = None,
    task: str = "inventory",
) -> HttpResponse:
    """Discover and act only on the genuine person's own retained hosting purposes.

    Parameters
    ----------
    request : HttpRequest
        Authenticated personal request; no independently selectable subject exists.
    organization_id : UUID
        Exact expected organizer scope.
    edition_id : UUID
        Exact edition with independently proved hosting adoption and relationship.
    item_id : UUID | None, default=None
        Selected own purpose, or no item for the bounded personal inventory.
    task : str, default='inventory'
        Closed inventory, invitation, availability, withdrawal or own-history task.

    Returns
    -------
    HttpResponse
        Private personal page, fresh-read redirect or non-disclosing safe failure.
    """
    try:
        scope = _scope(request, organization_id, edition_id)
        _selection(request, task, item_id)
        context = _context(scope, item_id, task)
        if request.method == "POST" and item_id is not None:
            return _post(scope, request, item_id, task, context)
        if item_id is not None and task in _FORMS and _can_edit(context, task):
            context.update(_forms(context, task))
        return _personal_html(request, scope, context)
    except ProgrammeAuthorizationDeniedError:
        return _secure(HttpResponse("Hosting page not found.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported hosting request.", status=400))
    except (DatabaseError, queries.ProgrammeQueryError, commands.ProgrammeCommandError):
        return _secure(
            HttpResponse(
                "Hosting is unavailable. No partial content is shown.", status=503
            )
        )
