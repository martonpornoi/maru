"""Dormant, independently authorized personal Programme command tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from . import programme_commands as commands
from . import programme_personal_queries as personal
from . import programme_queries as queries
from .forms import answer_initial_value
from .programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
    APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
    ApplicationsProgrammeAuthorizationDeniedError,
    authorize_programme_proposal_scope,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_domain_targets import DOMAIN_REFERENCE_KINDS
from .programme_inputs import ProgrammeProposalRevisionResponseInput
from .programme_personal_forms import (
    _ADDRESS_FIELDS,
    _REFERENCE_TYPES,
    ProgrammePersonalAnswerForm,
    ProgrammePersonalInvitationForm,
    ProgrammePersonalProfileForm,
    ProgrammePersonalResponseForm,
    ProgrammePersonalSelectionForm,
    ProgrammePersonalSubmitForm,
    ProgrammePersonalTaskForm,
)
from .programme_proposal_views import (
    _CONFLICTS,
    _UNAVAILABLE,
    _html,
    _root,
    _Scope,
    _values,
    _verify_summary,
)

if TYPE_CHECKING:
    from datetime import datetime

_EDIT = APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF
_MANAGE = APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF
_INVITATION = APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF
_SUBMIT = APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF
_ACTIONS = {
    "selection": ("Change track, format or duration", _MANAGE),
    "profile": ("Revise my proposed public profile", _EDIT),
    "answer": ("Revise this shared answer", _EDIT),
    "invite": ("Invite a known collaborator", _MANAGE),
    "reinvite": ("Reinvite a previous collaborator", _MANAGE),
    "remove": ("Remove this collaborator", _MANAGE),
    "accept-invitation": ("Accept my invitation", _INVITATION),
    "decline-invitation": ("Decline my invitation", _INVITATION),
    "leave": ("Leave this collaboration", _EDIT),
    "seal": ("Seal this exact draft", _MANAGE),
    "reopen": ("Reopen for a new draft revision", _MANAGE),
    "acknowledge": ("Acknowledge my exact sealed contribution", _EDIT),
    "decline-revision": ("Decline my exact sealed contribution", _EDIT),
    "submit": ("Submit this acknowledged seal", _SUBMIT),
    "withdraw": ("Withdraw this proposal", _SUBMIT),
}
_SIMPLE_COMMANDS = {
    "accept-invitation": "accept_programme_proposal_invitation",
    "decline-invitation": "decline_programme_proposal_invitation",
    "leave": "leave_programme_proposal",
    "seal": "seal_programme_proposal",
    "reopen": "reopen_programme_proposal",
    "submit": "submit_programme_proposal",
    "withdraw": "withdraw_programme_proposal",
}
_RESPONSE_TASKS = frozenset({"acknowledge", "decline-revision"})
_BASE_FIELDS = frozenset({"proposal_summary"})
_WORKFLOW_FIELDS = _BASE_FIELDS | {"workflow_context"}
_MAX_VALUES = 100
_MAX_VALUE_LENGTH = 65536
_MESSAGES = {
    "seal": "Sealing freezes shared answers, selection and included profiles. "
    "Every included collaborator must respond for themselves. This does not submit.",
    "reopen": "Reopening retains prior seals and responses but removes current "
    "submission status. A new seal and new collaborator responses are required.",
    "submit": "Submission sends only the current acknowledged seal for later review. "
    "It does not accept, publish, schedule or create a Programme item or host.",
    "withdraw": "Withdrawal ends this proposal's current submission candidacy. "
    "Attributable proposal history remains; this is not deletion.",
    "leave": "Leaving ends your collaboration access. Your prior evidence remains.",
    "remove": "Removal ends collaboration access, retaining prior evidence.",
    "accept-invitation": "Accepting joins this private proposal. You separately "
    "choose your own proposed public profile. This does not make you a Programme host.",
    "decline-invitation": "Declining ends this invitation and its proposal access.",
}


def _eligible(context: personal.ProgrammePersonalWorkflow, now: datetime) -> set[str]:
    if not context.planning:
        return set()
    summary = context.summary
    role, state = summary.relationship, summary.state
    editing = (
        context.call_status == "active"
        and context.opens_at <= now <= context.edit_until
    )
    responding = (
        context.call_status == "active" and context.opens_at <= now < context.closes_at
    )
    tasks: set[str] = set()
    if role == "lead" and state in {"draft", "sealed", "submitted"}:
        tasks.add("withdraw")
    if editing and state == "draft":
        if role == "lead":
            tasks.update({"selection", "invite", "reinvite", "remove", "seal"})
        if role in {"lead", "collaborator"}:
            tasks.update({"profile", "answer"})
        if role == "collaborator":
            tasks.add("leave")
        if role == "invited":
            tasks.update({"accept-invitation", "decline-invitation"})
    if editing and role == "lead" and state in {"sealed", "submitted"}:
        tasks.add("reopen")
    if responding and state == "sealed":
        if role == "lead":
            tasks.add("submit")
        if role == "collaborator":
            tasks.update(_RESPONSE_TASKS)
    return tasks


def _write_authority(
    scope: _Scope, context: personal.ProgrammePersonalWorkflow, action: str
) -> None:
    summary = context.summary
    admitted = authorize_programme_proposal_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        proposal_id=summary.proposal_id,
        capability_code=_ACTIONS[action][1],
    )
    for name in (
        "proposal_id",
        "submission_id",
        "call_id",
        "aggregate_version",
        "state",
        "relationship",
    ):
        if getattr(admitted, name) != getattr(summary, name):
            raise ApplicationsProgrammeAuthorizationDeniedError
    if not admitted.accepts_private_planning_writes:
        raise ApplicationsProgrammeAuthorizationDeniedError


def _fields(action: str, role: str) -> frozenset[str]:
    if action in {"accept-invitation", "decline-invitation"} or role == "invited":
        return _BASE_FIELDS | {"selection", "own_invitation"}
    return _BASE_FIELDS | {
        "profile": {"contributor_profiles"},
        "selection": {"selection"},
        "answer": {"answers"},
        "remove": {"contributors"},
        "work": {"selection", "answers", "contributors", "revision_responses"},
        "seal": {"selection", "answers", "contributor_profiles", "contributors"},
        "submit": {"revision_responses"},
        "acknowledge": {"revision_responses"},
        "decline-revision": {"revision_responses"},
    }.get(action, set())


def _transport(request: HttpRequest, action: str, selected_id: UUID | None) -> None:
    if action not in {*_ACTIONS, "work", "frozen"} or (
        (selected_id is not None) != (action in {"answer", "remove"})
    ):
        raise ValueError
    if request.GET or request.FILES:
        raise ValueError
    if request.method != "POST":
        return
    allowed = {
        *ProgrammePersonalTaskForm.base_fields,
        "csrfmiddlewaretoken",
        "track",
        "format",
        "duration",
        "public_name",
        "biography",
        "pronouns",
        "website",
        "publication_choice",
        "consent_acknowledged",
        "email",
        "expires_at",
        "value",
        *_ADDRESS_FIELDS,
        "revision_id",
        "contributor_id",
        "profile_revision_id",
    }
    if action not in _ACTIONS or set(request.POST) - allowed:
        raise ValueError
    for name, values in request.POST.lists():
        if (
            not values
            or len(values) > _MAX_VALUES
            or any(len(value) > _MAX_VALUE_LENGTH for value in values)
        ):
            raise ValueError
        if len(values) != 1 and (name != "value" or action != "answer"):
            raise ValueError


def _form(
    request: HttpRequest,
    context: personal.ProgrammePersonalWorkflow,
    detail: queries.ProgrammeProposalDetailProjection,
    action: str,
    answer: queries.ProgrammeAnswerProjection | None,
    frozen: personal.ProgrammePersonalFrozenRevision | None,
) -> ProgrammePersonalTaskForm:
    initial: dict[str, Any] = {
        "retry_key": uuid4(),
        "expected_version": context.summary.aggregate_version,
        "expected_call_version": context.call_version,
        "expected_definition_version": context.definition_version,
    }
    arguments: dict[str, Any] = {
        "data": request.POST if request.method == "POST" else None,
        "initial": initial,
    }
    if action == "selection":
        if detail.selection is None:
            raise queries.ApplicationsProgrammeProjectionError
        initial.update(
            track=detail.selection.track_id,
            format=detail.selection.format_id,
            duration=detail.selection.requested_duration_minutes,
        )
        return ProgrammePersonalSelectionForm(context=context, **arguments)
    if action == "profile":
        if detail.own_profile is not None:
            initial.update(dict(detail.own_profile.values))
        return ProgrammePersonalProfileForm(detail=detail, **arguments)
    if action == "answer" and answer is not None:
        if answer.question.field_type == "address":
            if isinstance(answer.value, dict):
                initial.update(answer.value)
        else:
            initial["value"] = answer_initial_value(answer.value)
        return ProgrammePersonalAnswerForm(question=answer.question, **arguments)
    if action in {"invite", "reinvite"}:
        return ProgrammePersonalInvitationForm(**arguments)
    if action in {*_RESPONSE_TASKS, "submit"} and frozen is not None:
        initial["revision_id"] = frozen.revision.revision_id
        form_type = ProgrammePersonalSubmitForm
        if action in _RESPONSE_TASKS:
            initial.update(_response_proofs(frozen))
            form_type = ProgrammePersonalResponseForm
        return form_type(**arguments)
    return ProgrammePersonalTaskForm(**arguments)


def _response_proofs(
    frozen: personal.ProgrammePersonalFrozenRevision,
) -> dict[str, UUID]:
    return {
        "revision_id": frozen.revision.revision_id,
        "contributor_id": frozen.own_contributor_id,
        "profile_revision_id": frozen.own_profile.profile_revision_id,
    }


def _execute(
    scope: _Scope,
    proposal_id: UUID,
    action: str,
    form: ProgrammePersonalTaskForm,
    selected_id: UUID | None,
) -> None:
    values = {
        **_values(scope),
        "proposal_id": proposal_id,
        **{
            name: form.cleaned_data[name]
            for name in ("expected_version", "reason", "retry_key")
        },
    }
    if isinstance(form, ProgrammePersonalSelectionForm):
        if form.selection is None:
            raise ValueError
        commands.revise_programme_proposal_selection(**values, selection=form.selection)
    elif isinstance(form, ProgrammePersonalProfileForm):
        if form.profile is None:
            raise ValueError
        commands.revise_programme_contributor_profile(**values, profile=form.profile)
    elif isinstance(form, ProgrammePersonalAnswerForm):
        if selected_id is None:
            raise ValueError
        commands.append_programme_proposal_answer(
            **values, question_id=selected_id, value=form.answer
        )
    elif isinstance(form, ProgrammePersonalInvitationForm):
        command = (
            commands.invite_programme_proposal_collaborator
            if action == "invite"
            else commands.reinvite_programme_proposal_collaborator
        )
        command(**values, invitation=form.invitation())
    elif isinstance(form, ProgrammePersonalResponseForm):
        commands.respond_to_programme_proposal_revision(
            **values,
            response=ProgrammeProposalRevisionResponseInput(
                **{
                    name: form.cleaned_data[name]
                    for name in ("revision_id", "contributor_id", "profile_revision_id")
                },
                decision="acknowledged" if action == "acknowledge" else "declined",
            ),
        )
    elif isinstance(form, ProgrammePersonalSubmitForm):
        commands.submit_programme_proposal(
            **values, revision_id=form.cleaned_data["revision_id"]
        )
    elif action == "remove":
        if selected_id is None:
            raise ValueError
        commands.remove_programme_proposal_collaborator(
            **values, collaborator_id=selected_id
        )
    else:
        getattr(commands, _SIMPLE_COMMANDS[action])(**values)


def _selection(
    request: HttpRequest,
    detail: queries.ProgrammeProposalDetailProjection,
    action: str,
    selected_id: UUID | None,
) -> tuple[queries.ProgrammeAnswerProjection | None, str]:
    answer = None
    label = ""
    if action == "answer":
        answer = next(
            (
                row
                for row in detail.answers or ()
                if row.question.question_id == selected_id
            ),
            None,
        )
        if answer is None or answer.question.field_type in _REFERENCE_TYPES:
            raise ApplicationsProgrammeAuthorizationDeniedError
        if (
            len(request.POST.getlist("value")) > 1
            and answer.question.field_type != "multiple_choice"
        ):
            raise ValueError
        label = answer.question.label
    if action == "remove":
        contributor = next(
            (
                row
                for row in detail.contributors or ()
                if row.collaborator_id == selected_id
                and row.role == "collaborator"
                and row.state in {"invited", "accepted"}
            ),
            None,
        )
        if contributor is None:
            raise ApplicationsProgrammeAuthorizationDeniedError
        label = contributor.display_label
    return answer, label


def _save(
    request: HttpRequest,
    scope: _Scope,
    context: personal.ProgrammePersonalWorkflow,
    action: str,
    form: ProgrammePersonalTaskForm,
    selected_id: UUID | None,
    frozen: personal.ProgrammePersonalFrozenRevision | None,
) -> HttpResponse | int:
    if request.method != "POST":
        return 200 if action in _eligible(context, timezone.now()) else 409
    if not form.is_valid():
        return 400
    try:
        values = form.cleaned_data
        if any(
            values[name] != expected
            for name, expected in {
                "expected_version": context.summary.aggregate_version,
                "expected_call_version": context.call_version,
                "expected_definition_version": context.definition_version,
            }.items()
        ) or (
            frozen is not None
            and any(
                values[name] != expected
                for name, expected in _response_proofs(frozen).items()
                if action in _RESPONSE_TASKS or name == "revision_id"
            )
        ):
            raise commands.ApplicationsProgrammeVersionConflictError
        if action not in _eligible(context, timezone.now()):
            raise commands.ApplicationsProgrammeStateConflictError
        _verify(scope, context)
        _write_authority(scope, context, action)
        _execute(scope, context.summary.proposal_id, action, form, selected_id)
        destination = _root(scope)
        if action not in {"leave", "decline-invitation"}:
            destination += f"{context.summary.proposal_id}/work/"
        return _secure(HttpResponseRedirect(destination))
    except _CONFLICTS:
        form.add_error(
            None,
            "The original version or task window is no longer current. "
            "Your input and original proof are retained. Check proposal history "
            "before starting a fresh request; an earlier attempt may have committed.",
        )
        return 409
    except commands.ApplicationsProgrammeCompletenessError:
        form.add_error(
            None,
            "This proposal is not ready for that step. Check required "
            "shared answers, each contributor's own profile, unresolved invitations "
            "and exact collaborator responses. Nothing was advanced by this attempt.",
        )
        return 400
    except ValidationError as error:
        _apply_errors(form, error)
        return 400


def _verify(scope: _Scope, context: personal.ProgrammePersonalWorkflow) -> None:
    _verify_summary(scope, context.summary, _WORKFLOW_FIELDS)
    if (
        personal.get_self_programme_workflow(
            **_values(scope), proposal_id=context.summary.proposal_id
        )
        != context
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError


def _page(
    request: HttpRequest,
    scope: _Scope,
    proposal_id: UUID,
    action: str,
    selected_id: UUID | None,
) -> HttpResponse:
    context = personal.get_self_programme_workflow(
        **_values(scope), proposal_id=proposal_id
    )
    if context.summary.proposal_id != proposal_id:
        raise ApplicationsProgrammeAuthorizationDeniedError
    if action in _ACTIONS:
        _write_authority(scope, context, action)
    fields = _fields(action, context.summary.relationship)
    detail = queries.get_self_programme_proposal_detail(
        **_values(scope), proposal_id=proposal_id, requested_fields=fields
    )
    if detail.summary != context.summary or detail.requested_fields != fields:
        raise ApplicationsProgrammeAuthorizationDeniedError
    answer, label = _selection(request, detail, action, selected_id)
    frozen = None
    if action in {"frozen", "submit"} or action in _RESPONSE_TASKS:
        if context.summary.sealed_revision_id is None:
            raise ApplicationsProgrammeAuthorizationDeniedError
        frozen = personal.get_self_programme_frozen_revision(
            **_values(scope),
            proposal_id=proposal_id,
            revision_id=context.summary.sealed_revision_id,
        )
        if frozen.summary != context.summary:
            raise ApplicationsProgrammeAuthorizationDeniedError
    form = None
    status = 200
    if action in _ACTIONS:
        form = _form(request, context, detail, action, answer, frozen)
        result = _save(request, scope, context, action, form, selected_id, frozen)
        if isinstance(result, HttpResponse):
            return result
        status = result
    tasks = _eligible(context, timezone.now())
    if any(
        row.account_id == scope.actor_id
        and row.revision_id == context.summary.sealed_revision_id
        and row.response is not None
        for row in detail.responses or ()
    ):
        tasks.difference_update(_RESPONSE_TASKS)
    links = []
    for task, (title, _) in _ACTIONS.items():
        if task not in tasks:
            continue
        try:
            _write_authority(scope, context, task)
        except ApplicationsProgrammeAuthorizationDeniedError:
            continue
        links.append((task, title))
    available = {task for task, _ in links}

    def verify() -> None:
        _verify(scope, context)
        _verify_summary(scope, context.summary, fields)
        if frozen is not None:
            _verify_summary(scope, context.summary, _BASE_FIELDS | {"frozen_revision"})
        if action in _ACTIONS:
            _write_authority(scope, context, action)

    return _html(
        request,
        scope,
        {
            "task": "work",
            "action": action,
            "workflow": context,
            "detail": detail,
            "form": form,
            "frozen": frozen,
            "selection_label": label,
            "action_title": _ACTIONS.get(action, ("Work on this proposal", ""))[0],
            "consequence": _MESSAGES.get(
                action,
                "This changes only this private proposal. "
                "It creates no host, attendee, schedule or publication.",
            ),
            "work_url": f"{_root(scope)}{proposal_id}/work/",
            "links": [
                (task, title)
                for task, title in links
                if task not in {"answer", "remove"}
            ],
            "can_answer": "answer" in available,
            "can_remove": "remove" in available,
            "reference_types": _REFERENCE_TYPES,
            "domain_reference_kinds": DOMAIN_REFERENCE_KINDS,
            "action_available": action in available,
        },
        verify,
        status=status,
    )


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_personal_tasks(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    *,
    action: str = "work",
    selected_id: UUID | None = None,
) -> HttpResponse:
    """Serve one explicit self task without mounting Programme in production.

    Parameters
    ----------
    request : HttpRequest
        Authenticated, CSRF-protected request with closed transport.
    organization_id : UUID
        Exact expected organization, independently authorized by the owner.
    edition_id : UUID
        Exact edition; route context grants no authority.
    proposal_id : UUID
        Exact current relationship-owned proposal.
    action : str, default="work"
        Closed workflow, frozen view or independently authorized mutation task.
    selected_id : UUID | None, default=None
        Authorized labelled question or collaborator relationship for its task.

    Returns
    -------
    HttpResponse
        Protected personal page, owner-command redirect or non-disclosing refusal.
    """
    try:
        _transport(request, action, selected_id)
        scope = _Scope(UUID(str(request.user.pk)), organization_id, edition_id, uuid4())
        return _page(request, scope, proposal_id, action, selected_id)
    except ApplicationsProgrammeAuthorizationDeniedError:
        return _secure(
            HttpResponse(
                "This personal task is unavailable. Check My proposals "
                "for any earlier attempt; it may already have committed.",
                status=404,
            )
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "Personal proposal workspace unavailable. An earlier "
                "attempt may have committed; check My proposals.",
                status=503,
            )
        )
    except (ValueError, TypeError):
        return _secure(HttpResponse("Invalid personal task request.", status=400))


__all__ = ["programme_personal_tasks"]
