"""Dormant exact-source conversion with original receipt recovery before reads."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.programme import commands as programme_commands
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.creation_queries import (
    ProgrammeCreationState,
    load_programme_creation_state,
)
from maru.programme.queries import (
    ProgrammeQueryUnavailableError,
    load_programme_private_item,
)
from maru.programme.workbench_queries import ProgrammeWorkbenchRequest

from . import programme_conversion_queries as queries
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_call_forms import _apply_errors
from .programme_call_views import _secure
from .programme_commands import ApplicationsProgrammeIdempotencyConflictError
from .programme_conversion_authorization import authorize_programme_conversion_retry
from .programme_conversion_commands import (
    ProgrammeConversionResult,
    convert_accepted_programme_proposal,
)
from .programme_conversion_forms import ProgrammeConversionForm
from .programme_conversion_sources import (
    ProgrammeConversionConflictError,
    ProgrammeConversionUnavailableError,
)
from .programme_review_rules import ProgrammeReviewUnavailableError
from .programme_write_scope import ApplicationsProgrammeWriteScopeUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

_SOURCE = "programme-conversion"
_MAX_INPUT_BYTES = 12_000
_DENIED = (Denied, ProgrammeAuthorizationDeniedError)
_UNAVAILABLE = (
    DatabaseError,
    ProgrammeConversionUnavailableError,
    ProgrammeReviewUnavailableError,
    ApplicationsProgrammeWriteScopeUnavailableError,
    ProgrammeQueryUnavailableError,
    programme_commands.ProgrammeUnavailableError,
)
_CONFLICTS = (
    ProgrammeConversionConflictError,
    ApplicationsProgrammeIdempotencyConflictError,
    programme_commands.ProgrammeVersionConflictError,
    programme_commands.ProgrammeLifecycleConflictError,
    programme_commands.ProgrammeLimitConflictError,
    programme_commands.ProgrammeIdempotencyConflictError,
)


def _root(scope: queries.ProgrammeConversionReadRequest) -> str:
    return (
        f"/admin/applications/programme-review/{scope.organization_id}/"
        f"{scope.edition_id}/{scope.department_id}/conversion/"
    )


def _entry(scope: queries.ProgrammeConversionReadRequest) -> None:
    # Original receipt recovery deliberately precedes fresh Department, writer,
    # source and item-read authority, exactly as the canonical owner specifies.
    authorize_programme_conversion_retry(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
    )


def _transport(request: HttpRequest, *, queue: bool) -> dict[str, Any]:
    if request.FILES or (queue and request.method != "GET"):
        raise ValueError
    if request.method == "POST" and (
        request.GET or request.POST.get("action") != "convert"
    ):
        raise ValueError
    if set(request.GET) - ({"after"} if queue else set()):
        raise ValueError
    if any(
        len(values) != 1 or len(values[0].encode("utf-8")) > _MAX_INPUT_BYTES
        for data in (request.GET, request.POST)
        for _key, values in data.lists()
    ):
        raise ValueError
    if "after" not in request.GET:
        return {}
    value = request.GET.getlist("after")[0]
    identifier = UUID(value)
    if value != str(identifier):
        raise ValueError
    return {"after_id": identifier}


def _html(
    request: HttpRequest,
    scope: queries.ProgrammeConversionReadRequest,
    context: dict[str, Any],
    verify: Callable[[], None],
    status: int = 200,
) -> HttpResponse:
    verify()
    nonce = token_urlsafe(32)
    shell = dict(admin.site.each_context(request))
    shell.update(
        has_permission=True,
        title="Accepted Programme conversion",
        maru_csp_nonce=nonce,
        root_url=_root(scope),
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=scope.department_id,
    )
    shell.update(context)
    content = render_to_string("applications/programme_conversion.html", shell, request)
    if len(content.encode("utf-8")) > 8 * 1024 * 1024:
        raise ProgrammeConversionUnavailableError
    verify()
    return _secure(HttpResponse(content, status=status), nonce)


def _item_link(
    scope: queries.ProgrammeConversionReadRequest, item_id: UUID
) -> str | None:
    try:
        load_programme_private_item(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            item_id=item_id,
            reason="Offer independently authorized continuation after exact conversion",
            correlation_id=scope.correlation_id,
            source_channel=_SOURCE,
        )
    except (*_DENIED, *_UNAVAILABLE):
        return None
    return (
        f"/admin/programme/items/{scope.organization_id}/{scope.edition_id}/"
        f"{item_id}/working/"
    )


def _receipt(
    request: HttpRequest,
    scope: queries.ProgrammeConversionReadRequest,
    result: ProgrammeConversionResult,
) -> HttpResponse:
    link = _item_link(scope, result.programme_item_id)

    def verify() -> None:
        _entry(scope)
        if link is not None and _item_link(scope, result.programme_item_id) != link:
            raise Denied

    try:
        return _html(request, scope, {"result": result, "item_link": link}, verify)
    except Denied:
        # A disappearing optional item grant must not hide a still-admitted
        # original creation receipt. Render again without private continuation.
        return _html(request, scope, {"result": result}, lambda: _entry(scope))


def _run(
    scope: queries.ProgrammeConversionReadRequest,
    decision_id: UUID,
    form: ProgrammeConversionForm,
) -> tuple[ProgrammeConversionResult | None, int]:
    if not form.is_valid():
        return None, 400
    try:
        result = convert_accepted_programme_proposal(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            command=form.to_command(decision_id),
            retry_key=form.cleaned_data["retry_key"],
            reason=form.cleaned_data["reason"],
            correlation_id=scope.correlation_id,
            source_channel=_SOURCE,
        )
    except ValidationError as error:
        _apply_errors(form, error)
        return None, 400
    except _CONFLICTS:
        form.add_error(
            None,
            "Conversion was not confirmed. Keep the original decision, seal, "
            "both versions, retry and private input. Inspect current eligibility "
            "before a new intent; a new key cannot bypass an already converted source.",
        )
        return None, 409
    except _UNAVAILABLE:
        form.add_error(
            None,
            "Conversion is temporarily unavailable. Keep the exact original request "
            "to recover its receipt; do not replace either version or retry "
            "identity after an uncertain response.",
        )
        return None, 503
    return result, 200


def _detail(
    request: HttpRequest,
    scope: queries.ProgrammeConversionReadRequest,
    decision_id: UUID,
) -> HttpResponse:
    form = None
    status = 200
    if request.method == "POST":
        form = ProgrammeConversionForm(request.POST)
        result, status = _run(scope, decision_id, form)
        if result is not None:
            return _receipt(request, scope, result)

    def source() -> queries.ProgrammeConversionSource:
        return queries.get_programme_conversion_source(
            request=scope, decision_id=decision_id
        )

    def creation() -> ProgrammeCreationState:
        return load_programme_creation_state(
            ProgrammeWorkbenchRequest(
                scope.actor_id,
                scope.organization_id,
                scope.edition_id,
                scope.correlation_id,
            )
        )

    detail, cursor = source(), creation()
    available = (
        detail.eligible and not detail.consumed and detail.writable and cursor.writable
    )
    if request.method == "GET" and available:
        form = ProgrammeConversionForm(
            initial={
                "revision_id": detail.choice.revision_id,
                "expected_review_version": detail.choice.review_version,
                "expected_programme_version": cursor.control_version,
                "retry_key": uuid4(),
            }
        )

    def verify() -> None:
        if source() != detail or creation() != cursor:
            raise Denied

    return _html(
        request,
        scope,
        {"source": detail, "creation": cursor, "available": available, "form": form},
        verify,
        status,
    )


def _queue(
    request: HttpRequest,
    scope: queries.ProgrammeConversionReadRequest,
    cursors: dict[str, Any],
) -> HttpResponse:
    page = queries.list_programme_conversion_choices(request=scope, **cursors)

    def verify() -> None:
        if queries.list_programme_conversion_choices(request=scope, **cursors) != page:
            raise Denied

    return _html(request, scope, {"page": page}, verify)


@login_required
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_conversion(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    decision_id: UUID | None = None,
) -> HttpResponse:
    """Select exact acceptance and deliberately create one private Programme item.

    Parameters
    ----------
    request : HttpRequest
        Authenticated bounded request with real CSRF enforcement.
    organization_id : UUID
        Exact common Applications/Programme organization.
    edition_id : UUID
        Exact common source and target edition.
    department_id : UUID
        Original owning Department; fresh disclosure requires current authority.
    decision_id : UUID | None, default=None
        Exact selected acceptance, absent only on the discovery page.

    Returns
    -------
    HttpResponse
        Minimal source choice, confirmed receipt or non-disclosing failure.
    """
    if not isinstance(request.user.pk, UUID):
        return _secure(HttpResponse("This conversion task is unavailable.", status=404))
    scope = queries.ProgrammeConversionReadRequest(
        request.user.pk, organization_id, edition_id, department_id, uuid4()
    )
    try:
        _entry(scope)
        cursors = _transport(request, queue=decision_id is None)
        if decision_id is None:
            return _queue(request, scope, cursors)
        return _detail(request, scope, decision_id)
    except _DENIED:
        return _secure(HttpResponse("This conversion task is unavailable.", status=404))
    except (ValueError, ValidationError):
        return _secure(
            HttpResponse("Use the complete bounded conversion request.", status=400)
        )
    except _UNAVAILABLE:
        return _secure(
            HttpResponse(
                "The conversion service is temporarily unavailable.", status=503
            )
        )
