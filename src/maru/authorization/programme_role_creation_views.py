"""Dormant preview-and-confirm request creation over the existing approval owner."""

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

from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_commands import request_programme_role
from maru.authorization.programme_role_creation import (
    ProgrammeRoleCreation,
    load_programme_role_creation,
    prepare_programme_role_creation,
)
from maru.authorization.programme_role_creation_forms import ProgrammeRoleCreationForm
from maru.authorization.programme_role_inputs import ProgrammeRoleScope
from maru.authorization.programme_role_selection import (
    ProgrammeRoleRequestDraft,
    verify_programme_role_selection,
)
from maru.authorization.programme_role_views import _actor, _root, _secure

if TYPE_CHECKING:
    from maru.identity.models import Account

_MAX_INPUT_LENGTH = 4096

_UNAVAILABLE = (
    "Programme access preparation is temporarily unavailable. No private content "
    "is shown. Keep the original input and retry identity after uncertainty."
)


def _input(request: HttpRequest) -> None:
    if (
        request.GET
        or request.FILES
        or (
            request.method == "POST"
            and (
                set(request.POST)
                - {*ProgrammeRoleCreationForm.base_fields, "csrfmiddlewaretoken"}
                or any(
                    len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
                    for _, values in request.POST.lists()
                )
            )
        )
    ):
        raise ValueError


def _render(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeRoleScope,
    workspace: ProgrammeRoleCreation,
    form: ProgrammeRoleCreationForm,
    original: tuple[ProgrammeRoleRequestDraft, str] | None,
    status: int,
) -> HttpResponse:
    nonce = token_urlsafe(32)
    selected_recipe = next(
        (
            recipe
            for recipe in workspace.recipes
            if workspace.selection is not None
            and (recipe.code, recipe.version)
            == (
                workspace.selection.details.recipe_code,
                workspace.selection.details.recipe_version,
            )
        ),
        None,
    )
    context: dict[str, Any] = dict(admin.site.each_context(request))
    context.update(
        title="Request Programme access",
        has_permission=True,
        maru_csp_nonce=nonce,
        workspace=workspace,
        form=form,
        selected_recipe=selected_recipe,
        scope_level=scope.level.value,
        root_url=_root(request, scope),
        confirming=form["action"].value() == "confirm",
    )
    content = render_to_string(
        "authorization/programme_role_creation.html", context, request=request
    )
    current = load_programme_role_creation(
        actor=actor,
        scope=scope,
        correlation_id=uuid4(),
        source_channel="html",
        original=original,
    )
    if current != workspace:
        return _secure(
            HttpResponse(
                "The selected people, scope or your access changed while this page was "
                "prepared. No private content is shown. Keep the original intent after "
                "uncertainty; reload its receipt before starting another request.",
                status=409,
            ),
            nonce,
        )
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        return _secure(HttpResponse(_UNAVAILABLE, status=503), nonce)
    return _secure(HttpResponse(content, status=status), nonce)


def _submit(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeRoleScope,
    workspace: ProgrammeRoleCreation,
    form: ProgrammeRoleCreationForm,
    draft: ProgrammeRoleRequestDraft,
) -> HttpResponse:
    proof = form.cleaned_data["selection_proof"]
    try:
        selection = verify_programme_role_selection(
            actor_id=actor.id,
            scope=scope,
            draft=draft,
            proof=proof,
        )
    except ValidationError as error:
        form.add_error(None, " ".join(error.messages))
        return _render(request, actor, scope, workspace, form, None, 400)
    original = (draft, proof)
    try:
        result = request_programme_role(
            actor=actor,
            scope=scope,
            details=selection.details,
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
            "Submission could not be confirmed. Retry the exact original input "
            "and key; do not start a replacement request.",
        )
        status = 503
    else:
        return _secure(
            HttpResponseRedirect(f"{_root(request, scope)}{result.request_id}/")
        )
    workspace = load_programme_role_creation(
        actor=actor,
        scope=scope,
        correlation_id=uuid4(),
        source_channel="html",
        original=original,
    )
    return _render(request, actor, scope, workspace, form, original, status)


def _post(
    request: HttpRequest,
    actor: Account,
    scope: ProgrammeRoleScope,
    workspace: ProgrammeRoleCreation,
    form: ProgrammeRoleCreationForm,
) -> HttpResponse:
    status = 400
    original = None
    if form.is_valid() and form.draft is not None:
        draft = form.draft
        if form.cleaned_data["action"] == "preview":
            try:
                workspace = prepare_programme_role_creation(
                    actor=actor,
                    scope=scope,
                    draft=draft,
                    correlation_id=uuid4(),
                    source_channel="html",
                )
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
            except DatabaseError:
                form.add_error(
                    None, "The preview is unavailable. No request was submitted."
                )
                status = 503
            else:
                if workspace.selection is None:
                    form.add_error(
                        None,
                        "The two exact people cannot be prepared. Check the known "
                        "addresses; no request was submitted.",
                    )
                else:
                    proof = workspace.selection.proof
                    original = (draft, proof)
                    initial = request.POST.dict()
                    initial.update(
                        action="confirm", selection_proof=proof, confirmed=""
                    )
                    form = ProgrammeRoleCreationForm(
                        recipes=workspace.recipes,
                        confirming=True,
                        initial=initial,
                    )
                    status = 200
        else:
            return _submit(request, actor, scope, workspace, form, draft)
    elif form.data.get("action") == "confirm" and form.data.get("selection_proof"):
        # Missing confirmation may still show the verified original terms. Rebuild
        # only pure terms; never select addresses or call the command to render.
        preview_data = request.POST.copy()
        preview_data["confirmed"] = "on"
        preview_form = ProgrammeRoleCreationForm(
            preview_data,
            recipes=workspace.recipes,
            confirming=True,
        )
        if preview_form.is_valid() and preview_form.draft is not None:
            try:
                verify_programme_role_selection(
                    actor_id=actor.id,
                    scope=scope,
                    draft=preview_form.draft,
                    proof=preview_form.cleaned_data["selection_proof"],
                )
            except ValidationError:
                pass
            else:
                original = (
                    preview_form.draft,
                    preview_form.cleaned_data["selection_proof"],
                )
                workspace = load_programme_role_creation(
                    actor=actor,
                    scope=scope,
                    correlation_id=uuid4(),
                    source_channel="html",
                    original=original,
                )
    return _render(request, actor, scope, workspace, form, original, status)


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_role_creation(
    request: HttpRequest,
    organization_id: UUID,
    edition_id: UUID,
    *,
    level: str,
    department_id: UUID | None = None,
    resource_binding_id: UUID | None = None,
) -> HttpResponse:
    """Prepare exact people and deliberately retain one request, never a grant.

    Parameters
    ----------
    request : HttpRequest
        Real authenticated CSRF-protected request with closed bounded fields.
    organization_id : UUID
        Exact independently admitted organization locator.
    edition_id : UUID
        Exact independently admitted Programme context locator.
    level : str
        Code-owned target level, never a submitted form choice.
    department_id : UUID | None, default=None
        Exact narrower Department for Department and room routes.
    resource_binding_id : UUID | None, default=None
        Existing canonical room binding required by the resource route.

    Returns
    -------
    HttpResponse
        Protected current preview, original receipt redirect or non-disclosing
        validation/denial/recovery; no production route or profile is activated.
    """
    try:
        _input(request)
        actor = _actor(request)
        scope = ProgrammeRoleScope(
            organization_id,
            edition_id,
            ScopeLevel(level),
            department_id,
            resource_binding_id,
            "venue.edition_space" if resource_binding_id else "",
        )
        workspace = load_programme_role_creation(
            actor=actor,
            scope=scope,
            correlation_id=uuid4(),
            source_channel="html",
        )
        form = ProgrammeRoleCreationForm(
            request.POST if request.method == "POST" else None,
            recipes=workspace.recipes,
            confirming=request.method == "POST"
            and request.POST.get("action") == "confirm",
            initial={"action": "preview", "idempotency_key": uuid4()},
        )
        if request.method == "POST":
            return _post(request, actor, scope, workspace, form)
        return _render(request, actor, scope, workspace, form, None, 200)
    except PermissionDenied:
        return _secure(
            HttpResponse("Programme access preparation is unavailable.", status=404)
        )
    except ValueError:
        return _secure(HttpResponse("Unsupported Programme access input.", status=400))
    except (ValidationError, DatabaseError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
