"""Native, scope-bound manual publishing pages over the Announcements owner."""

from __future__ import annotations

from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Any, cast
from uuid import UUID, uuid4

from django.contrib import admin, messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
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
from maru.authorization.page_access import scoped_page_access
from maru.authorization.policy import resolve_edition_target
from maru.core.localization import language_labels
from maru.events.announcements_workspace_queries import (
    AnnouncementsWorkspaceReference,
    announcements_workspace_reference,
)

from . import services
from .authorization import authorize_announcements_scope
from .catalog import MAX_BODY, MAX_CHANNELS, MAX_EXPORT_BYTES, MAX_VARIANTS
from .contracts import (
    AnnouncementCommandRequest,
    AnnouncementCommandResult,
    AnnouncementDetail,
    AnnouncementPage,
    AnnouncementPublicationReportView,
    AnnouncementReadRequest,
    AnnouncementSettingsView,
)
from .errors import (
    AnnouncementDeniedError,
    AnnouncementError,
    AnnouncementIdempotencyConflictError,
    AnnouncementLimitError,
    AnnouncementSettingsRequiredError,
    AnnouncementStateConflictError,
    AnnouncementVersionConflictError,
)
from .forms import (
    CommandForm,
    CorrectReportForm,
    DraftForm,
    PublicationForm,
    ReasonForm,
    RequestReviewForm,
    ReviewForm,
    SettingsForm,
)
from .queries import (
    export_announcement_evidence,
    list_announcements,
    load_announcement,
    load_announcement_settings,
    load_approved_announcement_copy,
    load_approved_announcement_preview,
)

_CAPABILITIES = {
    "new": "announcements.compose",
    "edit": "announcements.compose",
    "request-review": "announcements.compose",
    "review": "announcements.review",
    "report": "announcements.record_publication",
    "correct-report": "announcements.record_publication",
    "cancel": "announcements.compose",
    "settings": "announcements.manage_settings",
    "stop": "announcements.manage_settings",
    "resume": "announcements.manage_settings",
    "evidence": "announcements.export_evidence",
}
_READ_ONLY = frozenset(
    {"inventory", "detail", "copy", "download", "text-download", "evidence"}
)
_STATUS = {
    "draft": "Draft",
    "in_review": "Waiting for review",
    "changes_requested": "Changes requested",
    "approved": "Ready to publish",
    "cancelled": "Cancelled",
}
_PUBLICATION_STATUS = {
    "no_record": "No publication recorded",
    "reported": "Publication reported",
    "update_needed": "Update needed",
    "report_withdrawn": "Report withdrawn",
}
_HISTORY = {
    "create": "Draft created",
    "revise": "Changes saved",
    "request_review": "Review requested",
    "approve": "Approved",
    "changes_requested": "Changes requested",
    "record_publication": "Publication reported",
    "correct_publication": "Publication report corrected",
    "withdraw_report": "Publication report withdrawn",
    "cancel": "Announcement cancelled",
}
_CONFIRMATIONS = {
    "new": "Draft saved.",
    "edit": "Changes saved. Ask for review when the text is ready.",
    "request-review": "Review requested. Another organizer can now check this version.",
    "review": "Review decision saved.",
    "report": "Publication report saved.",
    "correct-report": "Report correction saved. The original remains in history.",
    "cancel": "Announcement cancelled.",
    "settings": "Announcement settings saved.",
    "stop": "New announcement work is stopped.",
    "resume": "Announcement work can continue.",
}
_UNAVAILABLE = (
    "Announcements are temporarily unavailable. No partial content is shown. "
    "Keep your original answers and retry the same form if its outcome is uncertain."
)
_CONFLICT = (
    "This announcement or its settings changed. Your original answers are retained "
    "below. Open the current announcement in another tab and compare it before "
    "starting a new attempt; this form has not silently switched to the new version."
)
_MAX_FORM_FIELDS = 250
_PUBLIC_COPY_ACTIONS = frozenset({"copy", "download", "text-download"})


@dataclass(frozen=True, slots=True)
class _Page:
    settings: AnnouncementSettingsView
    reference: AnnouncementsWorkspaceReference
    detail: AnnouncementDetail | None = None
    inventory: AnnouncementPage | None = None


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
    scope: AnnouncementReadRequest,
    action: str = "inventory",
    announcement_id: UUID | None = None,
    report_id: UUID | None = None,
) -> str:
    kwargs = {"organization_id": scope.organization_id, "edition_id": scope.edition_id}
    if announcement_id is not None:
        kwargs["announcement_id"] = announcement_id
    if report_id is not None:
        kwargs["report_id"] = report_id
    return reverse(f"announcements-{action}", kwargs=kwargs)


def _load(
    scope: AnnouncementReadRequest,
    action: str,
    announcement_id: UUID | None,
    after: UUID | None,
) -> _Page:
    authorize_announcements_scope(scope, capability="announcements.view")
    if action in _CAPABILITIES:
        authorize_announcements_scope(scope, capability=_CAPABILITIES[action])
    reference = announcements_workspace_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if reference is None:
        raise AnnouncementDeniedError
    settings = load_announcement_settings(scope)
    detail = (
        load_announcement(scope, announcement_id=announcement_id)
        if announcement_id
        else None
    )
    inventory = (
        list_announcements(scope, after=after) if action == "inventory" else None
    )
    return _Page(settings, reference, detail, inventory)


def _admit(scope: AnnouncementReadRequest, action: str) -> None:
    if action in _PUBLIC_COPY_ACTIONS:
        authorize_announcements_scope(
            scope, capability="announcements.view", fields=frozenset({"approved_copy"})
        )
    elif action == "evidence":
        authorize_announcements_scope(scope, capability="announcements.export_evidence")
    else:
        authorize_announcements_scope(scope, capability="announcements.view")
        if action in _CAPABILITIES:
            authorize_announcements_scope(scope, capability=_CAPABILITIES[action])


def _transport(request: HttpRequest, action: str) -> UUID | None:
    if request.FILES or (request.method == "POST" and action in _READ_ONLY):
        raise ValueError
    if set(request.GET) - ({"after"} if action == "inventory" else set()):
        raise ValueError
    if any(len(values) != 1 for _, values in request.GET.lists()):
        raise ValueError
    if len(request.POST) > _MAX_FORM_FIELDS or any(
        len(values) != 1 or len(values[0]) > MAX_BODY + 1024
        for _, values in request.POST.lists()
    ):
        raise ValueError
    cursor = request.GET.get("after")
    if cursor is None:
        return None
    result = UUID(cursor)
    if str(result) != cursor or not result.int:
        raise ValueError
    return result


def _count(request: HttpRequest, field: str, default: int, maximum: int) -> int:
    if request.method != "POST":
        return max(1, min(default, maximum))
    raw = request.POST.get(field, "")
    if (
        not raw.isascii()
        or not raw.isdecimal()
        or str(int(raw)) != raw
        or not 1 <= int(raw) <= maximum
    ):
        raise ValueError
    return int(raw)


def _form(  # noqa: PLR0911, PLR0912 - closed route-owned form dispatch
    request: HttpRequest,
    action: str,
    page: _Page,
    selected_report: AnnouncementPublicationReportView | None = None,
) -> CommandForm | None:
    if action in _READ_ONLY:
        return None
    detail = page.detail
    initial: dict[str, Any] = {
        "idempotency_key": uuid4(),
        "expected_version": detail.version if detail else page.settings.version,
    }
    data = request.POST if request.method == "POST" else None
    if action in {"new", "edit"}:
        if request.method == "GET" and (
            not page.settings.rules_current or page.settings.stopped
        ):
            raise AnnouncementSettingsRequiredError
        revision = detail.draft if detail else None
        initial["expected_settings_version"] = page.settings.version
        if revision:
            initial.update(
                headline=revision.headline,
                body=revision.body,
                language_code=revision.language_code,
            )
            for index, variant in enumerate(revision.variants):
                use_main = (
                    variant.language_code == revision.language_code
                    and variant.headline == revision.headline
                    and variant.body == revision.body
                )
                initial.update(
                    {
                        f"copy_{index}_channel": variant.channel_code,
                        f"copy_{index}_language": variant.language_code,
                        f"copy_{index}_mode": "main" if use_main else "custom",
                        f"copy_{index}_headline": "" if use_main else variant.headline,
                        f"copy_{index}_body": "" if use_main else variant.body,
                    }
                )
        return DraftForm(
            data,
            settings=page.settings,
            copy_count=_count(
                request,
                "copy_count",
                len(revision.variants) if revision else 1,
                MAX_VARIANTS,
            ),
            editing=action == "edit",
            initial=initial,
        )
    if action == "settings":
        settings = page.settings
        initial.update(
            policy_name=settings.policy_name,
            record_owner=settings.record_owner,
            review_on=settings.review_on,
            policy_url=settings.policy_url,
            policy_description=settings.policy_description,
        )
        for index, channel in enumerate(settings.channels):
            initial.update(
                {
                    f"channel_{index}_code": channel.code,
                    f"channel_{index}_label": channel.label,
                    f"channel_{index}_url": channel.url,
                }
            )
        return SettingsForm(
            data,
            channel_count=_count(
                request, "channel_count", len(settings.channels) or 1, MAX_CHANNELS
            ),
            initial=initial,
        )
    if action == "request-review":
        return RequestReviewForm(data, initial=initial)
    if action == "review" and detail:
        if not detail.can_review and request.method == "GET":
            raise AnnouncementDeniedError
        initial["revision_id"] = detail.draft.id
        return ReviewForm(data, initial=initial)
    if action == "report" and detail:
        if detail.approved is None:
            raise AnnouncementStateConflictError
        result = PublicationForm(
            data,
            choices=(
                (
                    str(copy.id),
                    f"{copy.channel_label} · {_language(copy.language_code)}",
                )
                for copy in detail.approved.variants
            ),
            initial=initial,
        )
        result.fields[
            "published_at"
        ].help_text = f"Use the convention's local time: {page.settings.time_zone}."
        return result
    if action == "correct-report":
        if (
            request.method == "GET"
            and selected_report
            and not selected_report.can_correct
        ):
            raise AnnouncementStateConflictError
        if selected_report:
            initial.update(
                publication_url=selected_report.publication_url,
                published_at=selected_report.publication_published_at,
            )
        correction_form = CorrectReportForm(data, initial=initial)
        correction_form.fields[
            "published_at"
        ].help_text = f"Use the convention's local time: {page.settings.time_zone}."
        return correction_form
    return ReasonForm(data, initial=initial)


def _add_row(
    request: HttpRequest, action: str, form: CommandForm, page: _Page
) -> CommandForm | None:
    key = (
        "add_copy"
        if action in {"new", "edit"}
        else "add_channel"
        if action == "settings"
        else ""
    )
    if not key or key not in request.POST:
        return None
    if request.POST[key] != "1" or set(request.POST) - {
        *form.fields,
        "csrfmiddlewaretoken",
        key,
    }:
        raise ValueError
    count_name, maximum = (
        ("copy_count", MAX_VARIANTS)
        if key == "add_copy"
        else ("channel_count", MAX_CHANNELS)
    )
    count = int(request.POST[count_name])
    if count >= maximum:
        form.is_valid()
        form.add_error(
            None, "This form already has the maximum number of copies or channels."
        )
        return form
    initial: dict[str, Any] = {name: request.POST.get(name, "") for name in form.fields}
    initial[count_name] = count + 1
    if key == "add_copy":
        return DraftForm(
            settings=page.settings,
            copy_count=count + 1,
            editing=action == "edit",
            initial=initial,
        )
    return SettingsForm(channel_count=count + 1, initial=initial)


def _submit(  # noqa: PLR0911 - one public owner command for each route-owned action
    scope: AnnouncementReadRequest,
    action: str,
    form: CommandForm,
    announcement_id: UUID | None,
    report_id: UUID | None,
) -> AnnouncementCommandResult:
    data = form.cleaned_data
    request = AnnouncementCommandRequest(
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        scope.correlation_id,
        data["idempotency_key"],
    )
    version = data["expected_version"]
    if action == "settings" and isinstance(form, SettingsForm):
        return services.update_announcement_settings(
            request, settings=form.settings_input(), expected_version=version
        )
    if action == "new" and isinstance(form, DraftForm):
        return services.create_announcement(
            request,
            draft=form.draft_input(),
            expected_settings_version=data["expected_settings_version"],
        )
    if action in {"stop", "resume"}:
        return services.set_announcements_stopped(
            request,
            stopped=action == "stop",
            expected_version=version,
            reason=data["reason"],
        )
    if announcement_id is None:
        raise ValueError
    if action == "edit" and isinstance(form, DraftForm):
        return services.revise_announcement(
            request,
            announcement_id=announcement_id,
            draft=form.draft_input(),
            expected_version=version,
            expected_settings_version=data["expected_settings_version"],
            reason=data["reason"],
        )
    if action == "request-review":
        return services.request_announcement_review(
            request, announcement_id=announcement_id, expected_version=version
        )
    if action == "review":
        return services.review_announcement(
            request,
            announcement_id=announcement_id,
            revision_id=data["revision_id"],
            expected_version=version,
            decision=data["decision"],
            note=data["note"],
        )
    if action == "report":
        return services.record_announcement_publication(
            request,
            announcement_id=announcement_id,
            variant_id=data["variant_id"],
            expected_version=version,
            publication_url=data["publication_url"],
            published_at=data["published_at"],
        )
    if action == "correct-report" and report_id:
        return services.correct_announcement_publication(
            request,
            announcement_id=announcement_id,
            report_id=report_id,
            expected_version=version,
            withdrawn=data["withdrawn"] == "yes",
            reason=data["reason"],
            publication_url=data["publication_url"],
            published_at=data["published_at"],
        )
    return services.cancel_announcement(
        request,
        announcement_id=announcement_id,
        expected_version=version,
        reason=data["reason"],
    )


def _post(
    scope: AnnouncementReadRequest,
    action: str,
    form: CommandForm,
    announcement_id: UUID | None,
    report_id: UUID | None,
) -> tuple[AnnouncementCommandResult | None, int]:
    if not form.is_valid():
        return None, 400
    try:
        return _submit(scope, action, form, announcement_id, report_id), 200
    except ValidationError as error:
        form.add_error(None, " ".join(error.messages))
        return None, 400
    except (
        AnnouncementVersionConflictError,
        AnnouncementIdempotencyConflictError,
        AnnouncementStateConflictError,
    ):
        form.add_error(None, _CONFLICT)
        return None, 409
    except AnnouncementSettingsRequiredError:
        form.add_error(
            None,
            "Current record-keeping rules and channels must be confirmed "
            "in Announcements settings before continuing.",
        )
        return None, 409
    except AnnouncementDeniedError:
        raise
    except (AnnouncementError, DatabaseError):
        form.add_error(None, _UNAVAILABLE)
        return None, 503


def _links(
    scope: AnnouncementReadRequest, detail: AnnouncementDetail | None
) -> dict[str, str]:
    links = {
        action.replace("-", "_"): _url(scope, action)
        for action in ("inventory", "new", "settings", "stop", "resume")
    }
    if detail:
        links.update(
            {
                action.replace("-", "_"): _url(scope, action, detail.id)
                for action in (
                    "detail",
                    "edit",
                    "request-review",
                    "review",
                    "report",
                    "cancel",
                    "copy",
                    "download",
                    "text-download",
                    "evidence",
                )
            }
        )
    return links


def _copy_rows(
    scope: AnnouncementReadRequest, detail: AnnouncementDetail | None
) -> tuple[dict[str, Any], ...]:
    if detail is None or detail.approved is None:
        return ()
    return tuple(
        {
            "copy": copy,
            "status": _PUBLICATION_STATUS.get(copy.publication_status, "Unavailable"),
            "correct_url": _url(
                scope, "correct-report", detail.id, copy.publication_report_id
            )
            if copy.publication_report_id and detail.can_record_publication
            else "",
        }
        for copy in detail.approved.variants
    )


def _selected_report(
    detail: AnnouncementDetail | None, report_id: UUID | None
) -> AnnouncementPublicationReportView | None:
    if report_id is None:
        return None
    if detail is not None:
        for report in detail.publication_history:
            if report.id == report_id:
                return report
    raise AnnouncementDeniedError


def _language(code: str) -> str:
    return language_labels().get(code, code)


def _render(
    request: HttpRequest,
    scope: AnnouncementReadRequest,
    action: str,
    page: _Page,
    form: CommandForm | None,
    report_id: UUID | None,
) -> tuple[str, str]:
    title, submit = {
        "inventory": ("Announcements", ""),
        "detail": (page.detail.draft.headline if page.detail else "Announcement", ""),
        "new": ("Write an announcement", "Save draft"),
        "edit": ("Edit announcement", "Save changes"),
        "request-review": ("Ask for review", "Request review"),
        "review": ("Review announcement", "Save review decision"),
        "report": ("Record publication", "Record publication"),
        "correct-report": ("Correct a publication report", "Save report correction"),
        "cancel": ("Cancel announcement", "Cancel announcement"),
        "settings": ("Announcements settings", "Save settings"),
        "stop": ("Stop new announcement work", "Stop new work"),
        "resume": ("Resume announcement work", "Resume work"),
        "copy": ("Approved copy", ""),
    }[action]
    reference = page.reference
    label = (
        f"{reference.organization_name} / {reference.series_name} / "
        f"{reference.edition_name}"
    )
    nonce = token_urlsafe(32)
    context = dict(admin.site.each_context(request))
    context.update(
        title=title,
        has_permission=True,
        maru_csp_nonce=nonce,
        announcements_scope=reference,
        scope_label=label,
        maru_page_access_spec=scoped_page_access(
            target=resolve_edition_target(
                organization_id=scope.organization_id, edition_id=scope.edition_id
            ),
            scope_label=label,
            intents=tuple(
                AccessIntent(code, label)
                for code, label in (
                    ("announcements.view", "Read announcements"),
                    ("announcements.compose", "Write announcements"),
                    ("announcements.review", "Review announcements"),
                    ("announcements.record_publication", "Record publication"),
                    ("announcements.manage_settings", "Manage settings"),
                    (
                        "announcements.export_evidence",
                        "Download full history",
                    ),
                )
            ),
            explanation=(
                "Your current event permissions control what you can do. "
                "Everyone who helped write this version needs someone else "
                "to approve it."
            ),
        ),
        workspace_url=_url(scope),
        action=action,
        form=form,
        submit_label=submit,
        settings=page.settings,
        detail=page.detail,
        links=_links(scope, page.detail),
        status_label=_STATUS.get(page.detail.status, "Unavailable")
        if page.detail
        else "",
        inventory=page.inventory,
        inventory_rows=tuple(
            (
                item,
                _url(scope, "detail", item.id),
                _STATUS.get(item.status, "Unavailable"),
            )
            for item in page.inventory.items
        )
        if page.inventory
        else (),
        next_url=f"{_url(scope)}?after={page.inventory.next_after}"
        if page.inventory and page.inventory.next_after
        else "",
        copy_rows=_copy_rows(scope, page.detail),
        history=tuple(
            (entry, _HISTORY.get(entry.action, "Announcement changed"))
            for entry in page.detail.history
        )
        if page.detail
        else (),
        publication_history=tuple(
            (
                report,
                _url(scope, "correct-report", page.detail.id, report.id)
                if report.can_correct
                else "",
            )
            for report in page.detail.publication_history
        )
        if page.detail
        else (),
        selected_report=_selected_report(page.detail, report_id),
    )
    return render_to_string(
        "announcements/workspace.html", context, request=request
    ), nonce


def _download(
    scope: AnnouncementReadRequest, action: str, announcement_id: UUID
) -> HttpResponse:
    preview = None
    artifact = None
    if action == "text-download":
        preview = load_approved_announcement_preview(
            scope, announcement_id=announcement_id
        )
        content = "\n\n".join(
            f"{copy.channel_label} ({_language(copy.language_code)})\n"
            f"{copy.headline}\n\n{copy.body}"
            for copy in preview.variants
        ).encode("utf-8")
        filename = f"announcement-{announcement_id}.txt"
        content_type = "text/plain; charset=utf-8"
    else:
        query = (
            export_announcement_evidence
            if action == "evidence"
            else load_approved_announcement_copy
        )
        artifact = query(scope, announcement_id=announcement_id)
        content = artifact.content
        suffix = "-private-evidence" if action == "evidence" else ""
        filename = f"announcement-{announcement_id}{suffix}.json"
        content_type = "application/json; charset=utf-8"
    if len(content) > MAX_EXPORT_BYTES:
        raise AnnouncementLimitError
    if preview is not None:
        current = load_approved_announcement_preview(
            scope, announcement_id=announcement_id
        )
        if current != preview:
            raise AnnouncementVersionConflictError
    elif query(scope, announcement_id=announcement_id) != artifact:
        raise AnnouncementVersionConflictError
    response = _secure(HttpResponse(content, content_type=content_type))
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Referrer-Policy"] = "no-referrer"
    return response


def _copy_page(
    request: HttpRequest, scope: AnnouncementReadRequest, announcement_id: UUID
) -> HttpResponse:
    approved = load_approved_announcement_preview(
        scope, announcement_id=announcement_id
    )
    reference = announcements_workspace_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if reference is None:
        raise AnnouncementDeniedError
    scope_label = (
        f"{reference.organization_name} / {reference.series_name} / "
        f"{reference.edition_name}"
    )
    nonce = token_urlsafe(32)
    context = dict(admin.site.each_context(request))
    detail_allowed = _copy_continuation_allowed(
        scope, frozenset({"announcement", "approved_copy", "history"})
    )
    inventory_allowed = _copy_continuation_allowed(scope, frozenset({"announcement"}))
    context.update(
        title="Approved copy",
        has_permission=True,
        maru_csp_nonce=nonce,
        announcements_scope=reference,
        scope_label=scope_label,
        approved=approved,
        workspace_url=_url(scope) if inventory_allowed else "",
        breadcrumb_root="Announcements",
        detail_allowed=detail_allowed,
        links={
            action.replace("-", "_"): _url(scope, action, announcement_id)
            for action in ("detail", "download", "text-download")
        },
        maru_page_access_spec=scoped_page_access(
            target=resolve_edition_target(
                organization_id=scope.organization_id, edition_id=scope.edition_id
            ),
            scope_label=scope_label,
            intents=(
                AccessIntent(
                    "announcements.view",
                    "Read approved copy",
                    frozenset({"approved_copy"}),
                ),
            ),
            explanation=(
                "Current event access allows reading this approved copy. "
                "No private review notes or publication history are included."
            ),
        ),
    )
    content = render_to_string("announcements/copy.html", context, request=request)
    _bounded_html(content)
    if (
        load_approved_announcement_preview(scope, announcement_id=announcement_id)
        != approved
        or announcements_workspace_reference(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        != reference
    ):
        raise AnnouncementVersionConflictError
    return _secure(HttpResponse(content), nonce)


def _copy_continuation_allowed(
    scope: AnnouncementReadRequest, fields: frozenset[str]
) -> bool:
    try:
        authorize_announcements_scope(
            scope, capability="announcements.view", fields=fields
        )
    except AnnouncementDeniedError:
        return False
    return True


def _bounded_html(content: str) -> None:
    if len(content.encode("utf-8")) > MAX_EXPORT_BYTES:
        raise AnnouncementLimitError


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def announcements_workspace(  # noqa: PLR0911 - explicit safe HTTP outcomes around one route-owned task
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    *,
    action: str = "inventory",
    announcement_id: UUID | None = None,
    report_id: UUID | None = None,
) -> HttpResponse:
    """Run one route-owned native task without conflating review and publication.

    Parameters
    ----------
    request : HttpRequest
        Actual authenticated actor's request; no submitted actor is accepted.
    organization_id : UUID
        Exact organization from the route.
    edition_id : UUID
        Exact same-parent edition from the route.
    action : str, default="inventory"
        Code-owned page or command name selected by URL configuration.
    announcement_id : UUID | None, default=None
        Exact announcement locator within the admitted scope.
    report_id : UUID | None, default=None
        Exact publication report being corrected, when applicable.

    Returns
    -------
    HttpResponse
        Revalidated page/download, post-redirect-get continuation, or safe error.
    """
    scope = AnnouncementReadRequest(
        cast("UUID", request.user.pk), organization_id, edition_id, uuid4()
    )
    try:
        _admit(scope, action)
        after = _transport(request, action)
        if action in _PUBLIC_COPY_ACTIONS | {"evidence"}:
            if announcement_id is None:
                return _secure(
                    HttpResponse("Announcements are unavailable.", status=404)
                )
            return (
                _copy_page(request, scope, announcement_id)
                if action == "copy"
                else _download(scope, action, announcement_id)
            )
        page = _load(scope, action, announcement_id, after)
        selected_report = _selected_report(page.detail, report_id)
        with timezone.override(page.settings.time_zone):
            form = _form(request, action, page, selected_report)
            status = 200
            if request.method == "POST" and form is not None:
                expanded = _add_row(request, action, form, page)
                if expanded is not None:
                    form = expanded
                else:
                    result, status = _post(
                        scope, action, form, announcement_id, report_id
                    )
                    if result is not None:
                        messages.success(
                            request,
                            "This change was already saved."
                            if result.replayed
                            else _CONFIRMATIONS[action],
                        )
                        target = result.announcement_id or announcement_id
                        return _secure(
                            HttpResponseRedirect(
                                _url(scope, "detail", target) if target else _url(scope)
                            )
                        )
            content, nonce = _render(request, scope, action, page, form, report_id)
            _bounded_html(content)
            response = _secure(HttpResponse(content, status=status), nonce)
        if _load(scope, action, announcement_id, after) != page:
            return _secure(
                HttpResponse(
                    "The announcement or your access changed while the page was "
                    "prepared. Reload before continuing.",
                    status=409,
                )
            )
    except AnnouncementDeniedError:
        return _secure(HttpResponse("Announcements are unavailable.", status=404))
    except (ValueError, ValidationError):
        return _secure(HttpResponse("Unsupported Announcements input.", status=400))
    except (
        AnnouncementStateConflictError,
        AnnouncementVersionConflictError,
        AnnouncementSettingsRequiredError,
    ):
        return _secure(
            HttpResponse(
                "This action is no longer available. Open the announcement "
                "again to review its current state.",
                status=409,
            )
        )
    except (AnnouncementError, DatabaseError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
    else:
        return response
