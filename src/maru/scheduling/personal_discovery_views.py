"""Dormant shared-shell personal edition choice, with final complete revalidation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .authorization import SchedulingAuthorizationDeniedError as Denied
from .command_support import SchedulingUnavailableError as Unavailable
from .output_rendering import MAX_TIMETABLE_OUTPUT_BYTES
from .personal_discovery_queries import (
    PersonalEditionCatalog,
    PersonalEditionChoice,
    load_personal_timetable_editions,
)
from .personal_output_views import _secure


@dataclass(frozen=True, slots=True)
class _Row:
    choice: PersonalEditionChoice
    url: str


def _require(*, condition: bool) -> None:
    if not condition:
        raise Unavailable


def _rows(request: HttpRequest, catalog: PersonalEditionCatalog) -> tuple[_Row, ...]:
    result = []
    urlconf = getattr(request, "urlconf", None)
    for choice in catalog.choices:
        kwargs = {
            "organization_id": choice.edition.organization_id,
            "edition_id": choice.edition.edition_id,
        }
        name = "my-hosting-work-timetable"
        try:
            url = reverse(name, kwargs=kwargs, urlconf=urlconf)
            target = resolve(url, urlconf=urlconf)
            if target.view_name != name or target.kwargs != kwargs:
                raise Unavailable
        except (NoReverseMatch, Resolver404) as error:
            raise Unavailable from error
        result.append(_Row(choice, url))
    return tuple(result)


@never_cache
@require_safe
@login_required(login_url="staff-login")
def personal_timetable_editions(request: HttpRequest) -> HttpResponse:
    """Choose an own-purpose edition without a directory or selectable other person.

    Parameters
    ----------
    request : HttpRequest
        Safe authenticated request, without filters, files or other controls.

    Returns
    -------
    HttpResponse
        Complete revalidated own-edition links or a non-disclosing safe failure.
    """
    actor_id = request.user.pk
    if type(actor_id) is not UUID or not actor_id.int:
        return _secure(
            HttpResponse("Your timetable editions are unavailable.", status=404)
        )
    if request.GET or request.FILES:
        return _secure(
            HttpResponse(
                "Open your timetable editions without extra controls.", status=400
            )
        )
    correlation_id = uuid4()
    try:
        catalog = load_personal_timetable_editions(
            actor_id=actor_id, correlation_id=correlation_id
        )
        _require(condition=catalog.actor_id == actor_id)
        rows = _rows(request, catalog)
        context = dict(admin.site.each_context(request))
        context.update(
            has_permission=True,
            maru_personal_surface=True,
            title="My Programme timetable editions",
            rows=rows,
        )
        content = render_to_string(
            "scheduling/personal_editions.html", context, request
        ).encode("utf-8")
        _require(
            condition=(
                len(content) <= MAX_TIMETABLE_OUTPUT_BYTES
                and _rows(request, catalog) == rows
                and load_personal_timetable_editions(
                    actor_id=actor_id, correlation_id=correlation_id
                )
                == catalog
            )
        )
        return _secure(HttpResponse(content))
    except Denied:
        return _secure(
            HttpResponse("Your timetable editions are unavailable.", status=404)
        )
    except (Unavailable, DatabaseError, ValidationError, ValueError, RuntimeError):
        return _secure(
            HttpResponse(
                "Your complete timetable edition list could not be verified. "
                "No earlier or partial list is shown. Reload to try again.",
                status=503,
            )
        )
