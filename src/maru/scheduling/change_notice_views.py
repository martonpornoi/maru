"""Dormant shared-shell notice workflow using only governed owner entrypoints."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from django import forms
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.queries import (
    ProgrammeQueryUnavailableError,
    ProgrammeTimetableInventoryLimitError,
)
from maru.workforce.notice_recipient_choices import ProgrammeWorkNoticeLimitError
from maru.workforce.programme_staffing_queries import ProgrammeStaffingDeniedError

from .authorization import (
    ACKNOWLEDGE_CHANGE_SELF,
    HANDOFF_CHANGE_NOTICES,
    PREPARE_CHANGE_NOTICES,
    REVIEW_CHANGE_NOTICES,
    VIEW_CHANGE_NOTICES,
    VIEW_CHANGE_SELF,
    SchedulingAuthorizationDeniedError,
    authorize_scheduling_scope,
)
from .change_catalogs import (
    ChangeNoticeAction,
    ChangeNoticeReview,
    ChangeRecipientPurpose,
)
from .change_inputs import (
    ChangeNoticeDecisionIntent,
    ChangeRecipientSelection,
    PrepareChangeNoticeIntent,
)
from .change_notice_commands import (
    acknowledge_programme_change_notice,
    handoff_programme_change_notice,
    prepare_programme_change_notice,
    review_programme_change_notice,
)
from .change_notice_forms import (
    NoticeAcknowledgeForm,
    NoticeDecisionForm,
    NoticePrepareForm,
    NoticePreviewForm,
    NoticeSelectionForm,
)
from .change_notice_inventory import (
    NoticeDetail,
    load_programme_change_notice_inventory,
)
from .change_notice_queries import (
    PersonalProgrammeChangeNotice,
    ProgrammeChangeNotice,
    load_personal_programme_change_notice,
    load_programme_change_notice,
    preview_programme_change_notice,
)
from .change_notice_selection import (
    NoticeHostSelection,
    NoticeSourceSelectionLimitError,
    NoticeWorkSelection,
    load_notice_host_selection,
    load_notice_work_selection,
)
from .change_notice_sources import ProgrammeChangeNoticePreview
from .command_support import (
    SchedulingCommandError,
    SchedulingIdempotencyConflictError,
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingVersionConflictError,
)
from .inputs import SchedulingCommandRequest
from .output_rendering import MAX_TIMETABLE_OUTPUT_BYTES
from .planning_queries import SchedulingReadRequest
from .workspace_navigation import ProgrammeWorkspaceLink, programme_workspace_links

if TYPE_CHECKING:
    from django.http import QueryDict

_CAPABILITIES = {
    "prepare": PREPARE_CHANGE_NOTICES,
    "approve": REVIEW_CHANGE_NOTICES,
    "reject": REVIEW_CHANGE_NOTICES,
    "handoff": HANDOFF_CHANGE_NOTICES,
    "acknowledge": ACKNOWLEDGE_CHANGE_SELF,
}
_MAX_NOTICE_INPUT_LENGTH = 4096


def _secure(response: HttpResponse, nonce: str) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _html(
    request: HttpRequest,
    context: dict[str, object],
    *,
    personal: bool,
    status: int = 200,
) -> HttpResponse:
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        title="My Programme changes" if personal else "Programme change notices",
        has_permission=True,
        maru_personal_surface=personal,
        maru_csp_nonce=nonce,
        personal=personal,
    )
    shell.update(context)
    scope = context.get("notice_scope")
    links: tuple[ProgrammeWorkspaceLink, ...] = ()
    if isinstance(scope, SchedulingReadRequest) and not personal:
        links = programme_workspace_links(
            scope,
            current="notices",
            urlconf=getattr(request, "urlconf", None),
        )
        shell["workspace_links"] = links
    detail = context.get("detail")
    if (
        isinstance(detail, ProgrammeChangeNotice)
        and detail.state.review is ChangeNoticeReview.APPROVED
    ):
        shell["recipient_url"] = request.build_absolute_uri(
            f"/my/{context['organization_id']}/{context['edition_id']}/"
            f"programme-changes/?notice={detail.notice_id}"
        )
    preview = context.get("preview")
    if isinstance(preview, ProgrammeChangeNoticePreview):
        shell["source_label"] = preview.source_state.value.replace(
            "_", " "
        ).capitalize()
        labels = {
            "effective_starts_at": "Delivery starts",
            "effective_ends_at": "Delivery ends",
            "setup_starts_at": "Preparation starts",
            "teardown_ends_at": "Teardown ends",
            "space_id": "Room",
            "public_rendition_id": "Reviewed copy reference",
            "placement_id": "Released placement reference",
        }
        shell["changed_labels"] = (
            tuple(
                labels.get(field, field.replace("_", " ").capitalize())
                for field in preview.change.changed_fields
            )
            if preview.change
            else ()
        )
    content = render_to_string("scheduling/change_notices.html", shell, request=request)
    if isinstance(scope, SchedulingReadRequest):
        _verify_rendered_context(scope, context, personal=personal)
        if not personal and links != programme_workspace_links(
            scope,
            current="notices",
            urlconf=getattr(request, "urlconf", None),
        ):
            shell["workspace_links"] = ()
            content = render_to_string(
                "scheduling/change_notices.html", shell, request=request
            )
            _verify_rendered_context(scope, context, personal=personal)
    if len(content.encode("utf-8")) > MAX_TIMETABLE_OUTPUT_BYTES:
        return _secure(
            HttpResponse(
                "Notice output is too large. Narrow the release filter.", status=503
            ),
            nonce,
        )
    return _secure(HttpResponse(content, status=status), nonce)


def _verify_rendered_context(
    scope: SchedulingReadRequest,
    context: dict[str, object],
    *,
    personal: bool,
) -> None:
    _authorize(
        scope, VIEW_CHANGE_SELF if personal else VIEW_CHANGE_NOTICES, personal=personal
    )
    guided = context.get("guided_selection")
    if (
        isinstance(guided, NoticeHostSelection)
        and load_notice_host_selection(
            scope,
            occurrence_id=cast("UUID | None", context.get("selected_occurrence")),
        )
        != guided
    ):
        raise SchedulingVersionConflictError
    if (
        isinstance(guided, NoticeWorkSelection)
        and load_notice_work_selection(
            scope,
            occurrence_id=cast("UUID | None", context.get("selected_occurrence")),
        )
        != guided
    ):
        raise SchedulingVersionConflictError
    detail = context.get("detail")
    if isinstance(detail, (ProgrammeChangeNotice, PersonalProgrammeChangeNotice)):
        fresh = (
            load_personal_programme_change_notice(scope, notice_id=detail.notice_id)
            if personal
            else load_programme_change_notice(scope, notice_id=detail.notice_id)
        )
        if fresh != detail:
            raise SchedulingVersionConflictError
    elif isinstance(context.get("preview"), ProgrammeChangeNoticePreview):
        preview = cast("ProgrammeChangeNoticePreview", context["preview"])
        if (
            preview_programme_change_notice(
                scope,
                release_id=preview.release_id,
                occurrence_id=preview.occurrence_id,
                recipient=preview.recipient,
            )
            != preview
        ):
            raise SchedulingVersionConflictError
    if "inventory" in context:
        selection = cast("NoticeSelectionForm", context["selection_form"])
        if (
            load_programme_change_notice_inventory(
                scope,
                personal=personal,
                release_id=selection.cleaned_data["release"],
            )
            != context["inventory"]
        ):
            raise SchedulingVersionConflictError
    for action, _form in cast(
        "tuple[tuple[str, forms.Form], ...]", context.get("actions", ())
    ):
        _authorize(scope, _CAPABILITIES[action])
    if context.get("prepare_form") is not None:
        _authorize(scope, PREPARE_CHANGE_NOTICES)


def _recipient_selection(
    scope: SchedulingReadRequest,
    occurrence_id: UUID | None,
    *,
    work: bool,
) -> dict[str, object]:
    observation = (
        load_notice_work_selection(scope, occurrence_id=occurrence_id)
        if work
        else load_notice_host_selection(scope, occurrence_id=occurrence_id)
    )
    if isinstance(observation, NoticeWorkSelection):
        recipients = tuple(
            (
                str(row.recipient.work.commitment_id),
                f"{row.title} · {row.recipient.display_label} · "
                f"{row.recipient.work.status} · "
                f"{'current' if row.recipient.work.current else 'retained'} work · "
                f"{row.starts_at.isoformat(sep=' ', timespec='minutes')} — "
                f"{row.ends_at.isoformat(sep=' ', timespec='minutes')}",
            )
            for row in observation.commitments
        )
    else:
        recipients = tuple((str(row.host_id), row.label) for row in observation.hosts)
    form = forms.Form(
        initial={"task": "work" if work else "hosts", "occurrence": occurrence_id}
    )
    form.fields["task"] = forms.CharField(widget=forms.HiddenInput)
    form.fields["occurrence"] = forms.ChoiceField(
        label="Current Programme occurrence",
        choices=[
            ("", "Choose an occurrence"),
            *((str(row.occurrence.id), row.label) for row in observation.occurrences),
        ],
    )
    preview_form = None
    if occurrence_id is not None and observation.release_id is not None and recipients:
        preview_form = NoticePreviewForm(
            initial={
                "action": "preview",
                "release_id": observation.release_id,
                "occurrence_id": occurrence_id,
                "purpose": "work" if work else "host",
            }
        )
        for field in preview_form.fields.values():
            field.widget = forms.HiddenInput()
        preview_form.fields["target_id"] = forms.ChoiceField(
            label="Accepted work and current holder" if work else "Confirmed host",
            choices=[
                ("", "Choose accepted work" if work else "Choose a confirmed host"),
                *recipients,
            ],
        )
    return {
        "guided_selection": observation,
        "work_selection": work,
        "has_recipients": bool(recipients),
        "selected_occurrence": occurrence_id,
        "guided_source_form": form,
        "guided_preview_form": preview_form,
    }


def _authorize(
    scope: SchedulingReadRequest, capability: str, *, personal: bool = False
) -> None:
    fields = (
        frozenset({"own_change_notices" if personal else "change_notices"})
        if capability in {VIEW_CHANGE_NOTICES, VIEW_CHANGE_SELF}
        else None
    )
    admitted = authorize_scheduling_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=capability,
        requested_fields=fields,
    )
    if capability in _CAPABILITIES.values() and not admitted.accepts_writes:
        raise SchedulingAuthorizationDeniedError


def _allowed(scope: SchedulingReadRequest, action: str) -> bool:
    try:
        _authorize(scope, _CAPABILITIES[action])
    except SchedulingAuthorizationDeniedError:
        return False
    return True


def _form_input(data: QueryDict, form_type: type[forms.Form]) -> None:
    if set(data) - {*form_type.base_fields, "csrfmiddlewaretoken"} or any(
        len(values) != 1 or len(values[0]) > _MAX_NOTICE_INPUT_LENGTH
        for _key, values in data.lists()
    ):
        raise ValueError


def _preview(
    scope: SchedulingReadRequest, form: NoticePreviewForm
) -> ProgrammeChangeNoticePreview:
    data = form.cleaned_data
    return preview_programme_change_notice(
        scope,
        release_id=data["release_id"],
        occurrence_id=data["occurrence_id"],
        recipient=ChangeRecipientSelection(
            ChangeRecipientPurpose(data["purpose"]),
            data["target_id"],
            data["operator_account_id"],
        ),
    )


def _prepare_form(preview: ProgrammeChangeNoticePreview) -> NoticePrepareForm:
    form = NoticePrepareForm(
        initial={
            "action": "prepare",
            "release_id": preview.release_id,
            "occurrence_id": preview.occurrence_id,
            "purpose": preview.recipient.purpose.value,
            "target_id": preview.recipient.target_id,
            "operator_account_id": preview.recipient.operator_account_id,
            "expected_pointer_version": preview.pointer_version,
            "snapshot_digest": preview.snapshot_digest,
            "retry_key": uuid4(),
        }
    )
    for name, field in form.fields.items():
        if name != "reason":
            field.widget = forms.HiddenInput()
    return form


def _actions(
    scope: SchedulingReadRequest, detail: NoticeDetail
) -> tuple[tuple[str, forms.Form], ...]:
    if isinstance(detail, PersonalProgrammeChangeNotice):
        actions = [] if detail.acknowledged else ["acknowledge"]
        version = detail.version
    else:
        state = detail.state
        version = state.version
        actions = []
        if state.review is None and state.preparer_id != scope.actor_id:
            actions = ["approve", "reject"]
        elif (
            state.review is ChangeNoticeReview.APPROVED
            and state.handed_off_by_id is None
        ):
            actions = ["handoff"]
    return tuple(
        (
            action,
            (NoticeAcknowledgeForm if action == "acknowledge" else NoticeDecisionForm)(
                initial={
                    "action": action,
                    "notice_id": detail.notice_id,
                    "expected_version": version,
                    "snapshot_digest": detail.preview.snapshot_digest,
                    "retry_key": uuid4(),
                },
                auto_id=f"id_{action}_%s",
            ),
        )
        for action in actions
        if _allowed(scope, action)
    )


def _submit(scope: SchedulingReadRequest, form: forms.Form) -> UUID:
    data = form.cleaned_data
    action = data["action"]
    if action == "acknowledge":
        acknowledge_programme_change_notice(
            scope,
            ChangeNoticeDecisionIntent(
                data["notice_id"], data["expected_version"], data["snapshot_digest"]
            ),
            idempotency_key=data["retry_key"],
        )
        return cast("UUID", data["notice_id"])
    command = SchedulingCommandRequest(
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        data["retry_key"],
        scope.correlation_id,
        data["reason"],
        "programme-change-web",
    )
    if action == "prepare":
        result = prepare_programme_change_notice(
            command,
            PrepareChangeNoticeIntent(
                data["release_id"],
                data["occurrence_id"],
                data["expected_pointer_version"],
                ChangeRecipientSelection(
                    ChangeRecipientPurpose(data["purpose"]),
                    data["target_id"],
                    data["operator_account_id"],
                ),
                data["snapshot_digest"],
            ),
        )
        return result.object_id
    intent = ChangeNoticeDecisionIntent(
        data["notice_id"], data["expected_version"], data["snapshot_digest"]
    )
    if action == "handoff":
        handoff_programme_change_notice(command, intent)
    else:
        review_programme_change_notice(
            command, intent, action=ChangeNoticeAction(action)
        )
    return intent.notice_id


def _post(
    scope: SchedulingReadRequest, request: HttpRequest, *, personal: bool
) -> tuple[dict[str, object], int] | UUID:
    action = request.POST.get("action")
    form_types: dict[str, type[forms.Form]] = (
        {"acknowledge": NoticeAcknowledgeForm}
        if personal
        else {
            "preview": NoticePreviewForm,
            "prepare": NoticePrepareForm,
            "approve": NoticeDecisionForm,
            "reject": NoticeDecisionForm,
            "handoff": NoticeDecisionForm,
        }
    )
    if action not in form_types:
        raise ValueError
    if action != "preview":
        _authorize(scope, _CAPABILITIES[action])
    form_type = form_types[action]
    _form_input(request.POST, form_type)
    form = form_type(request.POST)
    if not form.is_valid():
        return {
            "invalid_form": form,
            "message": "Check the labelled fields. No action was recorded.",
        }, 400
    if action == "preview":
        preview = _preview(scope, cast("NoticePreviewForm", form))
        return {
            "preview": preview,
            "prepare_form": _prepare_form(preview)
            if _allowed(scope, "prepare")
            else None,
        }, 200
    return _submit(scope, form)


def _get(
    scope: SchedulingReadRequest, request: HttpRequest, *, personal: bool
) -> dict[str, object]:
    _form_input(request.GET, NoticeSelectionForm)
    selection = NoticeSelectionForm(request.GET)
    if not selection.is_valid():
        raise ValueError
    if selection.cleaned_data["task"]:
        if (
            personal
            or selection.cleaned_data["notice"]
            or selection.cleaned_data["release"]
        ):
            raise ValueError
        return _recipient_selection(
            scope,
            selection.cleaned_data["occurrence"],
            work=selection.cleaned_data["task"] == "work",
        )
    if selection.cleaned_data["occurrence"] is not None:
        raise ValueError
    # Guided source selection is separate from specialist exact-reference search.
    selection.fields.pop("task")
    selection.fields.pop("occurrence")
    notice_id = selection.cleaned_data["notice"]
    if notice_id is not None:
        detail: NoticeDetail = (
            load_personal_programme_change_notice(scope, notice_id=notice_id)
            if personal
            else load_programme_change_notice(scope, notice_id=notice_id)
        )
        return {
            "detail": detail,
            "preview": detail.preview,
            "actions": _actions(scope, detail),
        }
    inventory = load_programme_change_notice_inventory(
        scope, personal=personal, release_id=selection.cleaned_data["release"]
    )
    return {
        "inventory": inventory,
        "selection_form": selection,
        "preview_form": NoticePreviewForm(initial={"action": "preview"})
        if not personal
        else None,
    }


def _request_scope(
    request: HttpRequest, organization_id: UUID, edition_id: UUID, *, personal: bool
) -> SchedulingReadRequest:
    if not isinstance(request.user.pk, UUID):
        raise SchedulingAuthorizationDeniedError
    scope = SchedulingReadRequest(request.user.pk, organization_id, edition_id, uuid4())
    _authorize(
        scope, VIEW_CHANGE_SELF if personal else VIEW_CHANGE_NOTICES, personal=personal
    )
    if request.FILES or (request.method == "POST" and request.GET):
        raise ValueError
    return scope


def _page(
    request: HttpRequest, organization_id: UUID, edition_id: UUID, *, personal: bool
) -> HttpResponse:
    try:
        scope = _request_scope(request, organization_id, edition_id, personal=personal)
        result = (
            _post(scope, request, personal=personal)
            if request.method == "POST"
            else (_get(scope, request, personal=personal), 200)
        )
        if isinstance(result, UUID):
            return _secure(
                HttpResponseRedirect(f"{request.path}?notice={result}"),
                token_urlsafe(32),
            )
        context, status = result
        context.update(
            organization_id=organization_id, edition_id=edition_id, notice_scope=scope
        )
        return _html(request, context, personal=personal, status=status)
    except (
        SchedulingAuthorizationDeniedError,
        ProgrammeAuthorizationDeniedError,
        ProgrammeStaffingDeniedError,
    ):
        status, message = 404, "Programme changes are not available at this address."
    except (
        SchedulingVersionConflictError,
        SchedulingLifecycleConflictError,
        SchedulingIdempotencyConflictError,
    ):
        status, message = (
            409,
            "This exact package or decision is no longer current. "
            "Refresh and review before trying again. No old content is shown.",
        )
    except NoticeSourceSelectionLimitError:
        status, message = (
            503,
            "The complete current Programme source choices are too large. "
            "Ask the organizer to review the occurrence inventory. "
            "No partial list is shown.",
        )
    except ProgrammeWorkNoticeLimitError:
        status, message = (
            503,
            "The complete accepted-work choices for this occurrence are too large. "
            "Ask the organizer to review its work bindings. No partial list is shown.",
        )
    except (SchedulingLimitError, ProgrammeTimetableInventoryLimitError):
        status, message = (
            503,
            "The complete notice inventory is too large. Select an exact release "
            "or open a known notice reference. No partial list is shown.",
        )
    except (
        SchedulingCommandError,
        ProgrammeQueryUnavailableError,
        DatabaseError,
        RuntimeError,
    ):
        status, message = (
            503,
            "Programme changes could not be fully verified. No cached or partial "
            "content is shown. Retry the original action with its original key "
            "if its outcome is uncertain.",
        )
    except (ValueError, ValidationError):
        status, message = (
            400,
            "Use the Programme change controls without extra or repeated options.",
        )
    return _html(
        request,
        {"message": message, "unavailable": True},
        personal=personal,
        status=status,
    )


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@login_required(login_url="staff-login")
@sensitive_post_parameters()
@csrf_protect
def programme_change_notices(
    request: HttpRequest, *, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Serve dormant organizer preparation, independent review and manual handoff.

    Parameters
    ----------
    request : HttpRequest
        Authenticated, CSRF-protected request; actor and correlation are server-owned.
    organization_id : UUID
        Exact expected tenant, independently authorized before private input.
    edition_id : UUID
        Exact edition, never authority implied by a route or selected context.

    Returns
    -------
    HttpResponse
        Private shared-shell content, safe failure or post/redirect/get continuation.
        No production route, profile or delivery provider is activated.
    """
    return _page(request, organization_id, edition_id, personal=False)


@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@login_required(login_url="staff-login")
@sensitive_post_parameters()
@csrf_protect
def personal_programme_changes(
    request: HttpRequest, *, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Serve only genuine-person approved notices and exact acknowledgement.

    Parameters
    ----------
    request : HttpRequest
        Authenticated person; accepts neither another recipient nor a private reason.
    organization_id : UUID
        Exact expected tenant, independently checked before notice discovery.
    edition_id : UUID
        Exact adopted scope, not a grant or attendance relationship.

    Returns
    -------
    HttpResponse
        No-store My Maru content without organizer rationale or other actor fields.
        The component remains unmounted in production.
    """
    return _page(request, organization_id, edition_id, personal=True)
