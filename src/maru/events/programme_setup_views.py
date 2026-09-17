"""Dormant guided foundation setup and independently admitted original receipts."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import Any
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.events.programme_setup import ProgrammeSetupResult, setup_programme_foundation
from maru.events.programme_setup_forms import ProgrammeSetupForm
from maru.events.programme_setup_inputs import ProgrammeSetupMode
from maru.events.programme_setup_queries import (
    ProgrammeSetupChoices,
    ProgrammeSetupReceiptView,
    load_programme_setup_choices,
    load_programme_setup_receipt,
    require_programme_setup_actor,
)
from maru.identity.models import Account

_UNAVAILABLE = (
    "Programme setup information is temporarily unavailable. No private content or "
    "partial choices are shown. Keep the original input and retry identity; "
    "do not start a replacement setup while its outcome is uncertain."
)
_MAX_INPUT_LENGTH = 4096


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


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account):
        raise PermissionDenied
    require_programme_setup_actor(request.user)
    return request.user


def _input(request: HttpRequest, *, selected: bool) -> None:
    if request.GET or request.FILES:
        raise ValueError
    if request.method == "POST" and (
        not selected
        or set(request.POST) - {*ProgrammeSetupForm.base_fields, "csrfmiddlewaretoken"}
        or any(
            len(values) != 1 or len(values[0]) > _MAX_INPUT_LENGTH
            for _, values in request.POST.lists()
        )
    ):
        raise ValueError


def _post(
    form: ProgrammeSetupForm, actor: Account
) -> tuple[ProgrammeSetupResult | None, int]:
    if not form.is_valid():
        return None, 400
    try:
        result = setup_programme_foundation(
            actor=actor,
            details=form.setup_input(),
            idempotency_key=form.cleaned_data["idempotency_key"],
            correlation_id=uuid4(),
            source_channel="html",
        )
    except ValidationError as error:
        form.add_error(None, " ".join(error.messages))
        return None, 409
    except DatabaseError:
        form.add_error(
            None,
            "The setup outcome could not be confirmed. Retain and retry this exact "
            "original input and key; do not create another attempt.",
        )
        return None, 503
    return result, 200


def _url(request: HttpRequest, name: str, **kwargs: UUID) -> str:
    return reverse(
        name, kwargs=kwargs or None, urlconf=getattr(request, "urlconf", None)
    )


def _content(request: HttpRequest, **values: Any) -> tuple[str, str]:
    nonce = token_urlsafe(32)
    context: dict[str, Any] = dict(admin.site.each_context(request))
    context.update(
        title="Set up Programme foundations",
        has_permission=True,
        maru_csp_nonce=nonce,
        **values,
    )
    return render_to_string(
        "events/programme_setup.html", context, request=request
    ), nonce


def _checked(
    content: str, nonce: str, current: object, original: object, status: int
) -> HttpResponse:
    if current != original:
        return _secure(
            HttpResponse(
                "The foundation or your access changed while this page was prepared. "
                "No private content is shown. "
                "Reload the original task before continuing.",
                status=409,
            ),
            nonce,
        )
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        return _secure(HttpResponse(_UNAVAILABLE, status=503), nonce)
    return _secure(HttpResponse(content, status=status), nonce)


def _render_setup(
    request: HttpRequest,
    actor: Account,
    mode: ProgrammeSetupMode | None,
    organization_id: UUID | None,
    series_id: UUID | None,
    choices: ProgrammeSetupChoices,
    form: ProgrammeSetupForm | None,
    status: int,
) -> HttpResponse:
    root = _url(request, "programme-setup")
    organization_links = tuple(
        (item, _url(request, "programme-setup-organization", organization_id=item.id))
        for item in choices.organizations
    )
    series_links = (
        tuple(
            (
                item,
                _url(
                    request,
                    "programme-setup-series",
                    organization_id=organization_id,
                    series_id=item.id,
                ),
            )
            for item in choices.series
        )
        if organization_id
        else ()
    )
    content, nonce = _content(
        request,
        choices=choices,
        form=form,
        mode=mode,
        root_url=root,
        new_url=_url(request, "programme-setup-new"),
        organization_links=organization_links,
        series_links=series_links,
        pending=request.method == "POST",
        source_changed=bool(
            form is not None
            and form.is_bound
            and choices.foundation is not None
            and form.data.get("foundation_fingerprint")
            != choices.foundation.fingerprint
        ),
        receipt=None,
    )
    current = load_programme_setup_choices(
        actor=actor,
        correlation_id=uuid4(),
        mode=mode,
        organization_id=organization_id,
        series_id=series_id,
    )
    return _checked(content, nonce, current, choices, status)


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def programme_setup_workspace(
    request: HttpRequest,
    *,
    mode: str | None = None,
    organization_id: UUID | None = None,
    series_id: UUID | None = None,
) -> HttpResponse:
    """Choose labelled foundations and deliberately submit one exact owning command.

    Parameters
    ----------
    request : HttpRequest
        Authenticated CSRF-protected request; no alternate actor is accepted.
    mode : str | None, default=None
        Code-owned route mode, or the initial selector without a mutation form.
    organization_id : UUID | None, default=None
        Exact reused parent from the route, never a cross-tenant lookup hint.
    series_id : UUID | None, default=None
        Exact reused convention series within that parent.

    Returns
    -------
    HttpResponse
        Final-revalidated shared-shell form, original receipt redirect or safe error.
    """
    try:
        _input(request, selected=mode is not None)
        actor = _actor(request)
        selected_mode = ProgrammeSetupMode(mode) if mode is not None else None
        form = None
        status = 200
        if request.method == "POST" and selected_mode is not None:
            form = ProgrammeSetupForm(
                request.POST,
                mode=selected_mode,
                organization_id=organization_id,
                series_id=series_id,
            )
            result, status = _post(form, actor)
            if result is not None:
                return _secure(
                    HttpResponseRedirect(
                        _url(
                            request,
                            "programme-setup-receipt",
                            organization_id=result.organization_id,
                            series_id=result.series_id,
                            edition_id=result.edition_id,
                            receipt_id=result.receipt_id,
                        )
                    )
                )
        choices = load_programme_setup_choices(
            actor=actor,
            correlation_id=uuid4(),
            mode=selected_mode,
            organization_id=organization_id,
            series_id=series_id,
        )
        if selected_mode is not None and form is None:
            form = ProgrammeSetupForm(
                mode=selected_mode,
                organization_id=organization_id,
                series_id=series_id,
                initial={
                    "foundation_fingerprint": choices.foundation.fingerprint
                    if choices.foundation
                    else "",
                    "idempotency_key": uuid4(),
                    "time_zone": choices.foundation.default_time_zone
                    if choices.foundation
                    else "UTC",
                    "department_name": "Programme",
                },
            )
        return _render_setup(
            request,
            actor,
            selected_mode,
            organization_id,
            series_id,
            choices,
            form,
            status,
        )
    except PermissionDenied:
        return _secure(HttpResponse("Programme setup is unavailable.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported Programme setup input.", status=400))
    except (ValidationError, DatabaseError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))


def _render_receipt(
    request: HttpRequest, receipt: ProgrammeSetupReceiptView
) -> tuple[str, str]:
    representation_url = reverse(
        "organization-representation",
        kwargs={"organization_slug": receipt.route.organization_slug},
    )
    return _content(
        request,
        receipt=receipt,
        representation_url=representation_url,
    )


@login_required(login_url="staff-login")
@never_cache
@require_http_methods(["GET"])
def programme_setup_receipt(
    request: HttpRequest,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    receipt_id: UUID,
) -> HttpResponse:
    """Explain one original setup without recreating it or inferring later approvals.

    Parameters
    ----------
    request : HttpRequest
        Actual authenticated original platform actor's read-only request.
    organization_id : UUID
        Exact original organization locator, never a grant token.
    series_id : UUID
        Exact same-parent original convention locator.
    edition_id : UUID
        Exact original Programme edition locator.
    receipt_id : UUID
        Exact original actor-bound receipt, never a directory token.

    Returns
    -------
    HttpResponse
        Current revalidated receipt and separately authorizing representation handoff.
    """
    try:
        _input(request, selected=False)
        actor = _actor(request)
        scope = {
            "organization_id": organization_id,
            "series_id": series_id,
            "edition_id": edition_id,
            "receipt_id": receipt_id,
        }
        receipt = load_programme_setup_receipt(
            actor=actor, correlation_id=uuid4(), **scope
        )
        content, nonce = _render_receipt(request, receipt)
        current = load_programme_setup_receipt(
            actor=actor, correlation_id=uuid4(), **scope
        )
        return _checked(content, nonce, current, receipt, 200)
    except PermissionDenied:
        return _secure(HttpResponse("Programme setup is unavailable.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported Programme setup input.", status=400))
    except (ValidationError, DatabaseError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
