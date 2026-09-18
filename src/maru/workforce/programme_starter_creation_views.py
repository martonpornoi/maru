"""Dormant preview/confirm adapter for actual own-person Volunteer starter intent."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.workforce.programme_starter_commands import request_programme_starter
from maru.workforce.programme_starter_creation import (
    ProgrammeStarterCreation,
    load_programme_starter_creation,
    prepare_programme_starter_creation,
)
from maru.workforce.programme_starter_forms import ProgrammeStarterCreationForm
from maru.workforce.programme_starter_inputs import ProgrammeStarterScope
from maru.workforce.programme_starter_selection import (
    ProgrammeStarterDraft,
    verify_programme_starter_selection,
)
from maru.workforce.programme_starter_views import (
    _MAX_RESPONSE_BYTES,
    _UNAVAILABLE,
    _actor,
    _input,
    _secure,
    _url,
)

if TYPE_CHECKING:
    from maru.identity.models import Account


def _render(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeStarterScope,
    workspace: ProgrammeStarterCreation,
    form: ProgrammeStarterCreationForm,
    original: tuple[ProgrammeStarterDraft, str] | None,
    status: int,
) -> HttpResponse:
    nonce = token_urlsafe(32)
    context: dict[str, Any] = dict(admin.site.each_context(request))
    context.update(
        title="Request the Volunteer starter",
        has_permission=True,
        maru_csp_nonce=nonce,
        workspace=workspace,
        form=form,
        root_url=_url(request, scope),
        new_url=_url(request, scope, "-new"),
        confirming=form["action"].value() == "confirm",
    )
    content = render_to_string(
        "workforce/programme_starter_creation.html", context, request=request
    )
    if original is None:
        current = load_programme_starter_creation(
            actor=actor, scope=scope, correlation_id=uuid4(), source_channel="html"
        )
    else:
        current = prepare_programme_starter_creation(
            actor=actor,
            scope=scope,
            draft=original[0],
            proof=original[1],
            correlation_id=uuid4(),
            source_channel="html",
        )
    if current != workspace:
        return _secure(
            HttpResponse(
                "The original person, scope or your access changed while this page was "
                "prepared. No private content is shown. Keep original input and retry "
                "identities; inspect the original request after uncertainty.",
                status=409,
            ),
            nonce,
        )
    if len(content.encode()) > _MAX_RESPONSE_BYTES:
        return _secure(HttpResponse(_UNAVAILABLE, status=503), nonce)
    return _secure(HttpResponse(content, status=status), nonce)


def _submit(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeStarterScope,
    workspace: ProgrammeStarterCreation,
    form: ProgrammeStarterCreationForm,
) -> HttpResponse:
    draft = form.draft()
    proof = form.cleaned_data["selection_proof"]
    try:
        selected = verify_programme_starter_selection(
            actor_id=actor.id, scope=scope, draft=draft, proof=proof
        )
    except ValidationError as error:
        form.add_error(None, " ".join(error.messages))
        return _render(request, actor, scope, workspace, form, None, 400)
    try:
        result = request_programme_starter(
            actor=actor,
            scope=scope,
            details=selected.details,
            idempotency_key=draft.idempotency_key,
            correlation_id=uuid4(),
            source_channel="html",
        )
    except ValidationError as error:
        form.add_error(None, " ".join(error.messages))
        status = 409
    except DatabaseError:
        form.add_error(
            None,
            "The request outcome could not be confirmed. Retry the exact original "
            "input and key; do not start a replacement.",
        )
        status = 503
    else:
        return _secure(
            HttpResponseRedirect(
                _url(request, scope, "-request", request_id=result.request_id)
            )
        )
    workspace = prepare_programme_starter_creation(
        actor=actor,
        scope=scope,
        draft=draft,
        proof=proof,
        correlation_id=uuid4(),
        source_channel="html",
    )
    return _render(request, actor, scope, workspace, form, (draft, proof), status)


def _post(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeStarterScope,
    workspace: ProgrammeStarterCreation,
    form: ProgrammeStarterCreationForm,
) -> HttpResponse:
    original = None
    status = 400
    if form.is_valid():
        if form.cleaned_data["action"] == "confirm":
            return _submit(request, actor, scope, workspace, form)
        draft = form.draft()
        try:
            preview = prepare_programme_starter_creation(
                actor=actor,
                scope=scope,
                draft=draft,
                correlation_id=uuid4(),
                source_channel="html",
            )
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
            status = 409
        else:
            if preview.selection is None:
                form.add_error(
                    None,
                    "A complete eligible independent approver preview is unavailable. "
                    "No request was submitted.",
                )
            else:
                workspace = preview
                proof = preview.selection.proof
                original = (draft, proof)
                values = request.POST.dict()
                values.update(action="confirm", selection_proof=proof, confirmed="")
                form = ProgrammeStarterCreationForm(initial=values)
                status = 200
    elif form.data.get("action") == "confirm" and all(
        name in form.cleaned_data
        for name in ("approver_email", "reason", "idempotency_key", "selection_proof")
    ):
        # Missing confirmation may redisplay verified terms, never select again.
        draft = form.draft()
        proof = form.cleaned_data["selection_proof"]
        try:
            preview = prepare_programme_starter_creation(
                actor=actor,
                scope=scope,
                draft=draft,
                proof=proof,
                correlation_id=uuid4(),
                source_channel="html",
            )
        except ValidationError:
            pass
        else:
            workspace = preview
            original = (draft, proof)
    return _render(request, actor, scope, workspace, form, original, status)


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_starter_creation(
    request: HttpRequest,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> HttpResponse:
    """Preview the exact shared meaning and submit only an original request.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected request with strict bounded input.
    organization_id : UUID
        Exact shared-definition owner from the route.
    series_id : UUID
        Original series resolved within the same organization.
    edition_id : UUID
        Exact admitted Programme context, never another edition's authority.

    Returns
    -------
    HttpResponse
        Revalidated fixed-meaning preview, original receipt redirect or safe
        invalid/denied/stale/unavailable state without automatic replacement.
    """
    try:
        _input(request, set(ProgrammeStarterCreationForm.base_fields))
        scope = ProgrammeStarterScope(organization_id, series_id, edition_id)
        actor = _actor(request)
        workspace = load_programme_starter_creation(
            actor=actor, scope=scope, correlation_id=uuid4(), source_channel="html"
        )
        form = ProgrammeStarterCreationForm(
            request.POST if request.method == "POST" else None,
            initial={"action": "preview", "idempotency_key": uuid4()},
        )
        if request.method == "POST":
            return _post(request, actor, scope, workspace, form)
        return _render(request, actor, scope, workspace, form, None, 200)
    except PermissionDenied:
        return _secure(
            HttpResponse("Volunteer starter request is unavailable.", status=404)
        )
    except ValueError:
        return _secure(HttpResponse("Unsupported Volunteer starter input.", status=400))
    except (ValidationError, DatabaseError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
