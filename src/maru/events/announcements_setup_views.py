"""Native standalone Announcements setup, with explicit foundation reuse."""

from __future__ import annotations

from functools import partial
from secrets import token_urlsafe
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

from maru.authorization.page_access import fixed_page_access
from maru.events.announcements_adoption import set_up_announcements_adoption
from maru.events.announcements_setup_forms import AnnouncementsSetupForm
from maru.events.announcements_setup_inputs import AnnouncementsSetupMode
from maru.events.announcements_setup_queries import (
    load_announcements_setup_choices,
    require_announcements_setup_actor,
)
from maru.identity.models import Account

_UNAVAILABLE = (
    "Announcements setup is temporarily unavailable. Keep your original answers "
    "and retry this form; do not start a replacement while the outcome is uncertain."
)
_MAX_INPUT_LENGTH = 4096


def _actor(request: HttpRequest) -> Account:
    if not isinstance(request.user, Account):
        raise PermissionDenied
    require_announcements_setup_actor(request.user)
    return request.user


def _input(request: HttpRequest, *, selected: bool) -> None:
    if request.GET or request.FILES or (request.method == "POST" and not selected):
        raise ValueError
    if request.method == "POST" and any(
        (name != "language_codes" and len(values) != 1)
        or any(len(value) > _MAX_INPUT_LENGTH for value in values)
        for name, values in request.POST.lists()
    ):
        raise ValueError


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


@login_required(login_url="staff-login")
@never_cache
@csrf_protect
@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
def announcements_setup_workspace(
    request: HttpRequest,
    *,
    mode: str | None = None,
    organization_id: UUID | None = None,
    series_id: UUID | None = None,
) -> HttpResponse:
    """Select a foundation and submit one exact, independently governed setup.

    Parameters
    ----------
    request : HttpRequest
        Actual authenticated platform principal's request.
    mode : str | None, default=None
        Route-owned create/reuse mode, or the initial selector.
    organization_id : UUID | None, default=None
        Exact reused organization from the route.
    series_id : UUID | None, default=None
        Exact same-parent convention from the route.

    Returns
    -------
    HttpResponse
        Revalidated form, representation handoff, or safe non-disclosing error.
    """
    try:
        actor = _actor(request)
        _input(request, selected=mode is not None)
        load_choices = partial(
            load_announcements_setup_choices,
            actor=actor,
            correlation_id=uuid4(),
            mode=AnnouncementsSetupMode(mode) if mode else None,
            organization_id=organization_id,
            series_id=series_id,
        )
        choices = load_choices()
        form = None
        status = 200
        if mode:
            form = AnnouncementsSetupForm(
                request.POST if request.method == "POST" else None,
                mode=mode,
                organization_id=organization_id,
                series_id=series_id,
                initial={
                    "idempotency_key": uuid4(),
                    "time_zone": "UTC",
                    "foundation_fingerprint": choices.foundation.fingerprint
                    if choices.foundation
                    else "",
                },
            )
        if form is not None and request.method == "POST":
            if not form.is_valid():
                status = 400
            else:
                try:
                    result = set_up_announcements_adoption(
                        actor=actor,
                        details=form.setup_input(),
                        idempotency_key=form.cleaned_data["idempotency_key"],
                        correlation_id=uuid4(),
                        source_channel="html",
                    )
                except ValidationError as error:
                    form.add_error(None, " ".join(error.messages))
                    status = 409
                except DatabaseError:
                    form.add_error(None, _UNAVAILABLE)
                    status = 503
                else:
                    return _secure(
                        HttpResponseRedirect(
                            reverse(
                                "organization-representation",
                                kwargs={"organization_slug": result.organization_slug},
                            )
                        )
                    )
        root_url = reverse("announcements-setup")
        nonce = token_urlsafe(32)
        context = dict(admin.site.each_context(request))
        context.update(
            title="Set up Announcements",
            has_permission=True,
            maru_csp_nonce=nonce,
            maru_page_access_spec=fixed_page_access(
                policy="platform",
                scope_label="Platform administration",
                explanation=(
                    "Current platform administrators may create the "
                    "organizing foundation. Each operator must accept "
                    "their own invitation separately."
                ),
            ),
            form=form,
            choices=choices,
            mode=mode,
            root_url=root_url,
            new_url=reverse("announcements-setup-new"),
            organization_links=tuple(
                (
                    item,
                    reverse(
                        "announcements-setup-organization",
                        kwargs={"organization_id": item.id},
                    ),
                )
                for item in choices.organizations
            ),
            series_links=tuple(
                (
                    item,
                    reverse(
                        "announcements-setup-series",
                        kwargs={
                            "organization_id": organization_id,
                            "series_id": item.id,
                        },
                    ),
                )
                for item in choices.series
            ),
            submit_label="Create Announcements workspace",
            baseline_hide_admin_scoped_navigation=True,
        )
        content = render_to_string(
            "events/announcements_setup.html", context, request=request
        )
        require_announcements_setup_actor(actor)
        if load_choices() != choices:
            return _secure(
                HttpResponse(
                    "The foundation or your access changed. Reload before continuing.",
                    status=409,
                ),
                nonce,
            )
        return _secure(HttpResponse(content, status=status), nonce)
    except PermissionDenied:
        return _secure(HttpResponse("Announcements setup is unavailable.", status=404))
    except ValueError:
        return _secure(HttpResponse("Unsupported setup input.", status=400))
    except (ValidationError, DatabaseError):
        return _secure(HttpResponse(_UNAVAILABLE, status=503))
