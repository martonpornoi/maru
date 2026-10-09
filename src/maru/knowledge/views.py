"""Native Guidance pages with separate current-reader and private working queries."""

from __future__ import annotations

from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Any, Never, cast
from urllib.parse import urlencode
from uuid import UUID, uuid4

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.authorization.access import AccessIntent
from maru.authorization.guidance_access_queries import require_guidance_access_actor
from maru.authorization.page_access import scoped_page_access
from maru.authorization.policy import resolve_edition_target
from maru.core.localization import language_labels
from maru.events.knowledge_workspace_queries import (
    KnowledgeWorkspaceReference,
    knowledge_workspace_reference,
)
from maru.identity.request_actor import authenticated_request_actor

from . import services
from .authorization import authorize_guidance_scope
from .catalog import MAX_BODY, MAX_EXPORT_BYTES, MAX_QUERY
from .contracts import (
    GuidanceActions,
    GuidanceCommandRequest,
    GuidanceCommandResult,
    GuidanceCurrentPage,
    GuidanceCurrentView,
    GuidanceOptions,
    GuidanceReadRequest,
    GuidanceResumePreview,
    GuidanceSettingsView,
    GuidanceWorkingDetail,
    GuidanceWorkingPage,
)
from .errors import (
    GuidanceDeniedError,
    GuidanceError,
    GuidanceIdempotencyConflictError,
    GuidanceLimitError,
    GuidanceNotAvailableError,
    GuidanceSettingsRequiredError,
    GuidanceStateConflictError,
    GuidanceVersionConflictError,
)
from .forms import (
    PLACEMENT_LABELS,
    ControlForm,
    DraftForm,
    RequestForm,
    RequestReviewForm,
    ResumeForm,
    ReviewForm,
    SettingsForm,
    WithdrawForm,
)
from .queries import (
    download_current_guidance,
    export_guidance_evidence,
    list_current_guidance,
    list_working_guidance,
    load_context_guidance,
    load_current_guidance,
    load_guidance_options,
    load_guidance_resume_preview,
    load_guidance_settings,
    load_working_guidance,
)

_MAX_FORM_FIELDS = 30
_MAX_REPEATED_VALUES = 2
_MAX_LANGUAGE_LENGTH = 35
_CAPABILITIES = {
    "new": "knowledge.compose",
    "edit": "knowledge.compose",
    "request-review": "knowledge.compose",
    "review": "knowledge.review",
    "withdraw": "knowledge.withdraw",
    "settings": "knowledge.manage_settings",
    "stop": "knowledge.manage_settings",
    "resume": "knowledge.manage_settings",
    "evidence": "knowledge.export_evidence",
}
_READ_ONLY = frozenset(
    {
        "inventory",
        "library",
        "current",
        "work",
        "detail",
        "download",
        "text-download",
        "evidence",
    }
)
_WORKING = frozenset(
    {"work", "detail", "new", "edit", "request-review", "review", "withdraw"}
)
_DOWNLOADS = frozenset({"download", "text-download", "evidence"})
_STATUS = {
    "draft": "Draft",
    "in_review": "Waiting for review",
    "changes_requested": "Changes requested",
    "approved": "Approved",
    "withdrawn": "Withdrawn",
}
_HISTORY = {
    "settings_update": "Record-keeping rules saved",
    "stop": "Guides stopped",
    "resume": "Guides resumed",
    "create": "Draft saved",
    "revise": "Changes saved",
    "request_review": "Review requested",
    "approve": "Approved and made available",
    "changes_requested": "Changes requested",
    "withdraw": "Guide withdrawn",
}
_CONFIRMATIONS = {
    "new": "Draft saved.",
    "edit": "Changes saved. Ask for review when the guide is ready.",
    "request-review": "Review requested. Another editor can now check this version.",
    "review": "Review decision saved.",
    "withdraw": "Guide withdrawn. Its history is kept.",
    "settings": "Guides settings saved.",
    "stop": "Guides are hidden from readers. Writing and review are paused.",
    "resume": (
        "The confirmed versions are available again. Writing and review can continue."
    ),
}
_UNAVAILABLE = (
    "Guides are temporarily unavailable. Keep your original answers "
    "and retry the same form if its outcome is uncertain."
)
_CONFLICT = (
    "This guide or its settings changed. Your original answers are "
    "retained below. Open the current page in another tab and "
    "compare it before starting a new attempt; this form still "
    "refers to the original version."
)
_BLOCKERS = {
    "rules_missing": (
        "The current record-keeping rules need to be confirmed in Guides settings."
    ),
    "rules_overdue": (
        "The record-keeping rules are overdue for review. Check them in "
        "Guides settings."
    ),
    "work_stopped": (
        "Guides are stopped. Writing and review are paused and guides "
        "are hidden from readers."
    ),
    "event_closed": (
        "This event is not open for changes. Ask the people responsible "
        "for the event to check its state."
    ),
    "team_unavailable": (
        "Guides needs its accepted responsible people. Ask a platform "
        "administrator to arrange an approved replacement for any "
        "missing responsibilities."
    ),
    "work_already_running": "Guides are already running.",
}


@dataclass(frozen=True, slots=True)
class _Selection:
    after: UUID | None = None
    query: str = ""
    language_code: str | None = None


@dataclass(frozen=True, slots=True)
class _Page:
    reference: KnowledgeWorkspaceReference
    actions: GuidanceActions
    options: GuidanceOptions | None = None
    settings: GuidanceSettingsView | None = None
    library: GuidanceCurrentPage | None = None
    current: GuidanceCurrentView | None = None
    work: GuidanceWorkingPage | None = None
    detail: GuidanceWorkingDetail | None = None
    resume: GuidanceResumePreview | None = None
    contextual: GuidanceCurrentPage | None = None


def _deny() -> Never:
    raise GuidanceDeniedError


def _changed() -> Never:
    raise GuidanceVersionConflictError


def _too_large() -> Never:
    raise GuidanceLimitError


def _secure(response: HttpResponse, nonce: str = "") -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "same-origin"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _url(
    scope: GuidanceReadRequest, action: str = "inventory", item_id: UUID | None = None
) -> str:
    kwargs = {"organization_id": scope.organization_id, "edition_id": scope.edition_id}
    if item_id is not None:
        kwargs["item_id"] = item_id
    return reverse(f"guidance-{action}", kwargs=kwargs)


def _allowed(
    scope: GuidanceReadRequest, capability: str, fields: frozenset[str] = frozenset()
) -> bool:
    try:
        authorize_guidance_scope(scope, capability=capability, fields=fields)
    except GuidanceDeniedError:
        return False
    return True


def _access_url(request: HttpRequest, scope: GuidanceReadRequest) -> str:
    try:
        require_guidance_access_actor(
            actor=authenticated_request_actor(request),
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
        )
    except PermissionDenied:
        return ""
    return reverse(
        "guidance-access-workspace",
        kwargs={
            "organization_id": scope.organization_id,
            "edition_id": scope.edition_id,
        },
    )


def _admit(scope: GuidanceReadRequest, action: str) -> None:
    if action == "inventory":
        if not _allowed(
            scope, "knowledge.view_current", frozenset({"current_summary"})
        ):
            authorize_guidance_scope(scope, capability="knowledge.view_working")
    elif action == "library":
        authorize_guidance_scope(
            scope,
            capability="knowledge.view_current",
            fields=frozenset({"current_summary"}),
        )
    elif action in {"current", "download", "text-download"}:
        authorize_guidance_scope(
            scope,
            capability="knowledge.view_current",
            fields=frozenset({"current_copy"}),
        )
    elif action in _WORKING:
        authorize_guidance_scope(scope, capability="knowledge.view_working")
    elif action not in _CAPABILITIES:
        raise ValueError
    if action in _CAPABILITIES:
        authorize_guidance_scope(scope, capability=_CAPABILITIES[action])


def _transport(request: HttpRequest, action: str) -> _Selection:
    if request.FILES or (request.method == "POST" and action in _READ_ONLY):
        raise ValueError
    allowed = (
        {"q", "language", "after"}
        if action == "library"
        else ({"after"} if action == "work" else set())
    )
    if set(request.GET) - allowed or any(
        len(values) != 1 for _, values in request.GET.lists()
    ):
        raise ValueError
    if len(request.POST) > _MAX_FORM_FIELDS or any(
        (len(values) != 1 and key != "placements")
        or len(values) > _MAX_REPEATED_VALUES
        or any(len(value) > MAX_BODY + 1024 for value in values)
        for key, values in request.POST.lists()
    ):
        raise ValueError
    raw = request.GET.get("after")
    after = UUID(raw) if raw is not None else None
    if after is not None and (str(after) != raw or not after.int):
        raise ValueError
    query = request.GET.get("q", "")
    language = request.GET.get("language") or None
    if len(query) > MAX_QUERY or (
        language is not None and len(language) > _MAX_LANGUAGE_LENGTH
    ):
        raise ValueError
    return _Selection(after, query, language)


def _load(  # noqa: PLR0912 - explicit closed route-owned dispatch
    scope: GuidanceReadRequest, action: str, item_id: UUID | None, selection: _Selection
) -> _Page:
    _admit(scope, action)
    library = current = work = detail = settings = resume = options = contextual = None
    if action == "library":
        library = list_current_guidance(
            scope,
            query=selection.query,
            language_code=selection.language_code,
            after=selection.after,
        )
        actions = library.actions
    elif action == "current" and item_id is not None:
        current = load_current_guidance(scope, item_id=item_id)
        actions = GuidanceActions(
            can_view_current=True,
            can_view_working=_allowed(scope, "knowledge.view_working"),
        )
    elif action == "work":
        work = list_working_guidance(scope, after=selection.after)
        options = work.options
        actions = options.actions
    elif action in _WORKING:
        if item_id is not None:
            detail = load_working_guidance(scope, item_id=item_id)
            options, actions = detail.options, detail.actions
        elif action == "new":
            options = load_guidance_options(scope)
            actions = options.actions
        else:
            _deny()
        if action in {"new", "edit"} and _allowed(
            scope, "knowledge.view_current", frozenset({"current_summary"})
        ):
            contextual = load_context_guidance(
                scope, context="knowledge.compose", limit=3
            )
    elif action == "settings":
        settings = load_guidance_settings(scope)
        options = settings.options
        actions = options.actions
    elif action in {"stop", "resume"}:
        options = load_guidance_options(scope, capability="knowledge.manage_settings")
        actions = options.actions
        if action == "resume":
            resume = load_guidance_resume_preview(scope)
    else:
        _deny()
    reference = knowledge_workspace_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if reference is None:
        _deny()
    return _Page(
        reference,
        actions,
        options,
        settings,
        library,
        current,
        work,
        detail,
        resume,
        contextual,
    )


def _form(  # noqa: PLR0911, PLR0912 - explicit closed route-owned dispatch
    request: HttpRequest, action: str, page: _Page
) -> RequestForm | None:
    if action in _READ_ONLY:
        return None
    options, detail = page.options, page.detail
    if options is None:
        _deny()
    if (
        request.method == "GET"
        and action in {"edit", "request-review", "review"}
        and detail is not None
        and detail.draft.language_code not in options.language_codes
    ):
        return None
    initial: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "expected_version": detail.version if detail else options.settings_version,
    }
    data = request.POST if request.method == "POST" else None
    if action in {"new", "edit"}:
        if request.method == "GET" and (not options.rules_current or options.stopped):
            return None
        initial["expected_settings_version"] = options.settings_version
        if detail:
            initial.update(
                title=detail.draft.title,
                body=detail.draft.body,
                language_code=detail.draft.language_code,
                review_by=detail.draft.review_by,
                placements=detail.draft.placements,
            )
        return DraftForm(
            data, options=options, editing=detail is not None, initial=initial
        )
    if action == "settings" and page.settings is not None:
        for name in (
            "policy_name",
            "record_owner",
            "review_on",
            "policy_url",
            "policy_description",
        ):
            initial[name] = getattr(page.settings, name)
        return SettingsForm(data, initial=initial)
    if action == "request-review":
        return RequestReviewForm(data, initial=initial)
    if action == "review" and detail is not None:
        if request.method == "GET" and not detail.actions.can_review:
            _deny()
        initial["revision_id"] = detail.draft.id
        form = ReviewForm(data, initial=initial)
        if detail.withdrawn:
            cast("Any", form.fields["decision"]).choices = [
                ("approve", "Approve and restore this guide"),
                ("changes_requested", "Request changes"),
            ]
        return form
    if action == "withdraw":
        return WithdrawForm(data, initial=initial)
    if action in {"stop", "resume"}:
        if action == "stop" and request.method == "GET" and not options.configured:
            return None
        initial.pop("expected_version")
        initial["expected_control_version"] = options.control_version
        if page.resume is not None:
            initial.update(
                expected_control_version=page.resume.control_version,
                preview_digest=page.resume.preview_digest,
            )
            return ResumeForm(data, initial=initial)
        return ControlForm(data, initial=initial)
    _deny()


def _post(  # noqa: PLR0911, PLR0912 - explicit closed route-owned dispatch
    scope: GuidanceReadRequest, action: str, form: RequestForm, item_id: UUID | None
) -> tuple[GuidanceCommandResult | None, int]:
    if not form.is_valid():
        return None, 400
    data = form.cleaned_data
    command = GuidanceCommandRequest(
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        scope.correlation_id,
        data["idempotency_key"],
    )
    try:
        if action == "settings" and isinstance(form, SettingsForm):
            return services.update_guidance_settings(
                command,
                settings=form.settings_input(),
                expected_version=data["expected_version"],
            ), 200
        if action == "new" and isinstance(form, DraftForm):
            return services.create_guidance(
                command,
                draft=form.draft_input(),
                expected_settings_version=data["expected_settings_version"],
            ), 200
        if action == "stop":
            return services.stop_guidance(
                command,
                expected_control_version=data["expected_control_version"],
                reason=data["reason"],
            ), 200
        if action == "resume":
            return services.resume_guidance(
                command,
                expected_control_version=data["expected_control_version"],
                preview_digest=data["preview_digest"],
                confirmed=data["confirmed"],
                reason=data["reason"],
            ), 200
        if item_id is None:
            _deny()
        common = {"item_id": item_id, "expected_version": data["expected_version"]}
        if action == "edit" and isinstance(form, DraftForm):
            return services.revise_guidance(
                command,
                **common,
                draft=form.draft_input(),
                expected_settings_version=data["expected_settings_version"],
                reason=data["reason"],
            ), 200
        if action == "request-review":
            return services.request_guidance_review(command, **common), 200
        if action == "review":
            return services.review_guidance(
                command,
                **common,
                revision_id=data["revision_id"],
                decision=data["decision"],
                note=data["note"],
            ), 200
        if action == "withdraw":
            return services.withdraw_guidance(
                command, **common, reason=data["reason"]
            ), 200
        _deny()
    except ValidationError as error:
        if hasattr(error, "message_dict"):
            for field, values in error.message_dict.items():
                for value in values:
                    form.add_error(field if field in form.fields else None, value)
        else:
            form.add_error(None, error)
        return None, 400
    except (
        GuidanceVersionConflictError,
        GuidanceStateConflictError,
        GuidanceIdempotencyConflictError,
        GuidanceSettingsRequiredError,
    ):
        form.add_error(None, _CONFLICT)
        return None, 409
    except (GuidanceDeniedError, GuidanceNotAvailableError):
        raise
    except (GuidanceError, DatabaseError):
        form.add_error(None, _UNAVAILABLE)
        return None, 503


def _links(scope: GuidanceReadRequest, item_id: UUID | None) -> dict[str, str]:
    result = {
        name: _url(scope, name)
        for name in (
            "inventory",
            "library",
            "work",
            "new",
            "settings",
            "stop",
            "resume",
        )
    }
    if item_id is not None:
        result.update(
            {
                name.replace("-", "_"): _url(scope, name, item_id)
                for name in (
                    "current",
                    "detail",
                    "edit",
                    "request-review",
                    "review",
                    "withdraw",
                    "download",
                    "text-download",
                    "evidence",
                )
            }
        )
    return result


def _next_url(
    scope: GuidanceReadRequest, action: str, selection: _Selection, after: UUID | None
) -> str:
    if after is None:
        return ""
    values = {"after": str(after)}
    if selection.query:
        values["q"] = selection.query
    if selection.language_code:
        values["language"] = selection.language_code
    return _url(scope, action) + "?" + urlencode(values)


def _render(
    request: HttpRequest,
    scope: GuidanceReadRequest,
    action: str,
    selection: _Selection,
    page: _Page,
    form: RequestForm | None,
) -> tuple[str, str, str]:
    title, submit = {
        "library": ("Guides", ""),
        "current": (page.current.summary.title if page.current else "Guides", ""),
        "work": ("Drafts & reviews", ""),
        "detail": (page.detail.draft.title if page.detail else "Guides", ""),
        "new": ("Write a guide", "Save draft"),
        "edit": ("Edit guide", "Save changes"),
        "request-review": ("Ask for review", "Request review"),
        "review": ("Review guide", "Save review decision"),
        "withdraw": ("Withdraw guide", "Withdraw guide"),
        "settings": ("Guides settings", "Save settings"),
        "stop": ("Stop using Guides", "Stop using Guides"),
        "resume": ("Resume Guides", "Resume Guides"),
    }[action]
    reference = page.reference
    label = (
        f"{reference.organization_name} / {reference.series_name} / "
        f"{reference.edition_name}"
    )
    item_id = (
        page.detail.id
        if page.detail
        else (page.current.summary.id if page.current else None)
    )
    nonce = token_urlsafe(32)
    intents = (
        (("knowledge.view_current", "Read guides"),)
        if action in {"library", "current"}
        else (
            ("knowledge.view_working", "Read drafts and private history"),
            ("knowledge.compose", "Write a guide"),
            ("knowledge.review", "Review guide"),
            ("knowledge.withdraw", "Withdraw guide"),
            ("knowledge.manage_settings", "Manage Guides settings"),
            ("knowledge.export_evidence", "Download full history"),
        )
    )
    context = dict(admin.site.each_context(request))
    access_url = _access_url(request, scope)
    context.update(
        title=title,
        submit_label=submit,
        action=action,
        form=form,
        has_permission=True,
        maru_csp_nonce=nonce,
        guidance_scope=reference,
        scope_label=label,
        workspace_url=_url(scope),
        links=_links(scope, item_id),
        actions=page.actions,
        manage_access_url=access_url,
        blocking_reasons=tuple(
            _BLOCKERS[code]
            for code in (
                page.resume.blocking_reasons
                if page.resume
                else (page.options.blocking_reasons if page.options else ())
            )
        ),
        maru_page_access_spec=scoped_page_access(
            target=resolve_edition_target(
                organization_id=scope.organization_id, edition_id=scope.edition_id
            ),
            scope_label=label,
            intents=tuple(
                AccessIntent(
                    code,
                    text,
                    frozenset(
                        {"current_summary" if action == "library" else "current_copy"}
                    )
                    if code == "knowledge.view_current"
                    else frozenset(),
                )
                for code, text in intents
            ),
            explanation=(
                "Your current event access controls what you can read or change. "
                "Reading guidance does not record an acknowledgement."
            ),
        ),
        options=page.options,
        settings=page.settings,
        current=page.current,
        detail=page.detail,
        draft_language_unavailable=page.detail is not None
        and page.detail.draft.language_code not in page.detail.options.language_codes,
        resume=page.resume,
        query=selection.query,
        generated_at=timezone.now(),
        language_filter=selection.language_code or "",
        max_query=MAX_QUERY,
        library_rows=tuple(
            (item, _url(scope, "current", item.id)) for item in page.library.items
        )
        if page.library
        else (),
        work_rows=tuple(
            (
                item,
                _url(scope, "detail", item.id),
                _STATUS.get(item.status, "Unavailable"),
            )
            for item in page.work.items
        )
        if page.work
        else (),
        next_url=_next_url(
            scope,
            action,
            selection,
            page.library.next_after
            if page.library
            else (page.work.next_after if page.work else None),
        ),
        guidance_links=tuple(
            (item, _url(scope, "current", item.id)) for item in page.contextual.items
        )
        if page.contextual
        else (),
        status_label=_STATUS.get(page.detail.status, "Unavailable")
        if page.detail
        else "",
        history=tuple(
            (entry, _HISTORY.get(entry.action, "Guide changed"))
            for entry in page.detail.history
        )
        if page.detail
        else (),
        draft_placements=tuple(
            PLACEMENT_LABELS[code] for code in page.detail.draft.placements
        )
        if page.detail
        else (),
        resume_preview_current=page.resume is not None
        and (
            request.method != "POST"
            or (
                request.POST.get("preview_digest") == page.resume.preview_digest
                and request.POST.get("expected_control_version")
                == str(page.resume.control_version)
            )
        ),
        fixed_language=language_labels().get(str(form["language_code"].value()), "")
        if isinstance(form, DraftForm) and form.fields["language_code"].widget.is_hidden
        else "",
    )
    return (
        render_to_string("knowledge/workspace.html", context, request=request),
        nonce,
        access_url,
    )


def _download(scope: GuidanceReadRequest, action: str, item_id: UUID) -> HttpResponse:
    if action == "text-download":
        current = load_current_guidance(scope, item_id=item_id)
        reference = knowledge_workspace_reference(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        if reference is None:
            _deny()
        summary = current.summary
        language = language_labels().get(summary.language_code, summary.language_code)
        content = (
            f"{summary.title}\nEvent: {reference.edition_name}\n\n{current.body}\n\n"
            f"{language}; approved version {summary.number}.\n"
            f"Responsible team: {summary.owner_label}\n"
            f"Review by: {summary.review_by.isoformat()}\n"
            f"Approved at: {summary.effective_at.isoformat()}\n"
            f"Generated at: {timezone.now().isoformat()}\n"
            + (
                (
                    "Review overdue. Check with the responsible team before relying "
                    "on this guidance.\n"
                )
                if summary.review_due
                else ""
            )
            + "Internal guidance. Saved copies may become out of date.\n"
        ).encode("utf-8")
        if (
            load_current_guidance(scope, item_id=item_id) != current
            or knowledge_workspace_reference(
                organization_id=scope.organization_id, edition_id=scope.edition_id
            )
            != reference
        ):
            _changed()
        suffix, content_type = ".txt", "text/plain; charset=utf-8"
    else:
        query = (
            export_guidance_evidence
            if action == "evidence"
            else download_current_guidance
        )
        artifact = query(scope, item_id=item_id)
        final_artifact = query(scope, item_id=item_id)
        if action == "evidence":
            if final_artifact != artifact:
                _changed()
        elif not artifact.content_fingerprint or (
            final_artifact.filename,
            final_artifact.content_type,
            final_artifact.content_fingerprint,
        ) != (
            artifact.filename,
            artifact.content_type,
            artifact.content_fingerprint,
        ):
            _changed()
        content = final_artifact.content
        suffix = "-private-history.json" if action == "evidence" else ".json"
        content_type = "application/json; charset=utf-8"
    if len(content) > MAX_EXPORT_BYTES:
        _too_large()
    response = _secure(HttpResponse(content, content_type=content_type))
    response["Content-Disposition"] = (
        f'attachment; filename="guidance-{item_id}{suffix}"'
    )
    response["Referrer-Policy"] = "no-referrer"
    return response


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def guidance_workspace(  # noqa: PLR0911 - explicit closed route-owned dispatch
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    *,
    action: str = "inventory",
    item_id: UUID | None = None,
) -> HttpResponse:
    """Serve one reauthorized native reader or working task at exact event scope.

    Parameters
    ----------
    request : HttpRequest
        Actual authenticated actor and original form input.
    organization_id : UUID
        Exact tenant from the route, independent of ambient selection.
    edition_id : UUID
        Same-parent event from the route, independently admitted for this task.
    action : str, default="inventory"
        Closed route-owned action, never selected by submitted input.
    item_id : UUID | None, default=None
        Optional item locator within this independently admitted scope.

    Returns
    -------
    HttpResponse
        Complete rechecked HTML, safe artifact, redirect or non-disclosing failure.
    """
    try:
        actor = authenticated_request_actor(request)
        scope = GuidanceReadRequest(actor.pk, organization_id, edition_id, uuid4())
        _admit(scope, action)
        selection = _transport(request, action)
        if action == "inventory":
            destination = (
                "work" if _allowed(scope, "knowledge.view_working") else "library"
            )
            _admit(scope, destination)
            return _secure(HttpResponseRedirect(_url(scope, destination)))
        if action in _DOWNLOADS:
            if item_id is None:
                _deny()
            return _download(scope, action, item_id)
        page = _load(scope, action, item_id, selection)
        with timezone.override(page.reference.time_zone):
            form = _form(request, action, page)
            status = 200
            if request.method == "POST" and form is not None:
                result, status = _post(scope, action, form, item_id)
                if result is not None:
                    messages.success(
                        request,
                        "This change was already saved."
                        if result.replayed
                        else _CONFIRMATIONS[action],
                    )
                    target = result.item_id or item_id
                    destination = (
                        _url(scope, "detail", target)
                        if target
                        else _url(scope, "settings")
                    )
                    return _secure(HttpResponseRedirect(destination))
            content, nonce, access_url = _render(
                request, scope, action, selection, page, form
            )
            if len(content.encode("utf-8")) > MAX_EXPORT_BYTES:
                _too_large()
        if (
            _load(scope, action, item_id, selection) != page
            or _access_url(request, scope) != access_url
        ):
            _changed()
        return _secure(HttpResponse(content, status=status), nonce)
    except (PermissionDenied, GuidanceDeniedError, GuidanceNotAvailableError):
        return _secure(HttpResponse("Guides are unavailable.", status=404))
    except (ValueError, ValidationError):
        return _secure(HttpResponse("Unsupported Guides input.", status=400))
    except (
        GuidanceStateConflictError,
        GuidanceVersionConflictError,
        GuidanceSettingsRequiredError,
    ):
        return _secure(
            HttpResponse(
                (
                    "This page or your access changed. Reload the current Guides "
                    "page before continuing."
                ),
                status=409,
            )
        )
    except (GuidanceError, DatabaseError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
