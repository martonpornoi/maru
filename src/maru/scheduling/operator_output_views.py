"""Dormant exact-purpose operator run sheets in the shared Administration shell."""

from __future__ import annotations

from secrets import token_urlsafe
from typing import TYPE_CHECKING
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .authorization import SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError
from .continuity_protocol import ContinuityScope
from .operator_output_queries import (
    OPERATOR_OPTIONAL_LAYERS,
    OperatorRunSheet,
    load_operator_run_sheet,
)
from .operator_output_rendering import (
    SAVED_COPY_NOTICE,
    render_operator_run_sheet_calendar,
    render_operator_run_sheet_json,
)
from .operator_scope import (
    OperatorReadRequest,
    OperatorScopeKind,
    authorize_operator_scope,
)
from .output_navigation import ProgrammeOutputLink, programme_output_links
from .output_observation import verify_timetable_observation
from .output_rendering import (
    MAX_TIMETABLE_OUTPUT_BYTES,
    TimetableOutputInvalidError,
    TimetableOutputUnavailableError,
)
from .release_queries import ProgrammeReleaseState

if TYPE_CHECKING:
    from datetime import datetime

_LAYER_LABELS = {
    "technical": "Technical instructions",
    "accessibility": "Accessibility delivery instructions",
    "media": "Media instructions",
    "staffing": "Linked staffing and retained work",
}
_STATE_LABELS = {
    ProgrammeReleaseState.AVAILABLE: "Approved release available",
    ProgrammeReleaseState.ABSENT: "No Programme release published yet",
    ProgrammeReleaseState.WITHDRAWN: (
        "Programme release withdrawn — recheck with the organizer"
    ),
    ProgrammeReleaseState.INVALIDATED: (
        "Programme release needs review — recheck with the organizer"
    ),
}


def _secure(response: HttpResponse, *, script_nonce: str | None = None) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    script_policy = "'self'" + (f" 'nonce-{script_nonce}'" if script_nonce else "")
    response["Content-Security-Policy"] = (
        f"default-src 'none'; script-src {script_policy}; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    response["Referrer-Policy"] = "same-origin"
    return response


def _options(request: HttpRequest) -> tuple[str, frozenset[str]]:
    if set(request.GET) - {"format", *OPERATOR_OPTIONAL_LAYERS} or any(
        len(values) != 1 for _key, values in request.GET.lists()
    ):
        raise ValueError
    output_format = request.GET.get("format", "html")
    if output_format not in {"html", "print", "json", "calendar"}:
        raise ValueError
    layers = frozenset(key for key in request.GET if key in OPERATOR_OPTIONAL_LAYERS)
    if any(request.GET[key] != "1" for key in layers):
        raise ValueError
    return output_format, layers


def _context(snapshot: OperatorRunSheet, *, print_view: bool) -> dict[str, object]:
    zone = ZoneInfo(snapshot.reference.zone_name)

    def instant(value: datetime) -> str:
        return value.astimezone(zone).isoformat(sep=" ", timespec="minutes")

    rows = tuple(
        {
            "entry": row,
            "day_label": instant(row.placement.day_starts_at),
            "setup_label": instant(row.placement.envelope.setup_starts_at),
            "delivery_label": instant(row.placement.envelope.effective_starts_at),
            "delivery_end_label": instant(row.placement.envelope.effective_ends_at),
            "teardown_label": instant(row.placement.envelope.teardown_ends_at),
            "instructions": tuple(
                (label, getattr(row.delivery, field))
                for field, label in _LAYER_LABELS.items()
                if field != "staffing"
                and field in snapshot.layers
                and row.delivery is not None
            ),
        }
        for row in snapshot.entries
    )
    titles = {row.placement.occurrence_id: row.copy.title for row in snapshot.entries}
    work = (
        tuple(
            {
                "demand": demand,
                "start_label": instant(demand.starts_at),
                "end_label": instant(demand.ends_at),
                "links": tuple(
                    {"link": link, "title": titles[link.occurrence_id]}
                    for link in snapshot.staffing.links
                    if link.demand_id == demand.demand_id
                ),
                "retained": tuple(
                    {
                        "work": row,
                        "start_label": instant(row.starts_at),
                        "end_label": instant(row.ends_at),
                        "rest_label": instant(row.rest_ends_at),
                    }
                    for row in demand.retained_work
                ),
            }
            for demand in snapshot.staffing.demands
        )
        if snapshot.staffing is not None
        else ()
    )
    return {
        "snapshot": snapshot,
        "print_view": print_view,
        "notice": SAVED_COPY_NOTICE,
        "state_label": _STATE_LABELS[snapshot.reference.state],
        "checked_label": instant(snapshot.checked_at),
        "published_label": instant(snapshot.reference.published_at)
        if snapshot.reference.published_at
        else "Not applicable",
        "calendar_available": snapshot.reference.state
        is ProgrammeReleaseState.AVAILABLE,
        "layer_options": tuple(
            (key, label, key in snapshot.layers) for key, label in _LAYER_LABELS.items()
        ),
        "requested_layer_labels": tuple(
            label for key, label in _LAYER_LABELS.items() if key in snapshot.layers
        ),
        "rows": rows,
        "work_rows": work,
    }


def _html(
    request: HttpRequest, context: dict[str, object], *, status: int = 200
) -> HttpResponse:
    shell = admin.site.each_context(request)
    script_nonce = token_urlsafe(32)
    shell.update(
        title="Programme run sheet",
        baseline_admin_parent_template="admin/base_site.html",
        baseline_use_admin_shell=True,
        baseline_page_id="programme-operator-run-sheet",
        baseline_page_class="operator-run-sheet",
        maru_csp_nonce=script_nonce,
    )
    shell.update(context)
    content = render_to_string(
        "scheduling/operator_run_sheet.html", shell, request=request
    ).encode("utf-8")
    if len(content) > MAX_TIMETABLE_OUTPUT_BYTES:
        raise TimetableOutputInvalidError
    return _secure(HttpResponse(content, status=status), script_nonce=script_nonce)


def _render(
    request: HttpRequest,
    snapshot: OperatorRunSheet,
    output_format: str,
    *,
    links: tuple[ProgrammeOutputLink, ...] = (),
) -> HttpResponse:
    # The same closed graph and byte bound govern visible pages and all exports.
    encoded = render_operator_run_sheet_json(snapshot)
    if output_format in {"json", "calendar"}:
        calendar = output_format == "calendar"
        response = HttpResponse(
            render_operator_run_sheet_calendar(snapshot) if calendar else encoded,
            content_type="text/calendar; charset=utf-8"
            if calendar
            else "application/json; charset=utf-8",
        )
        extension = "ics" if calendar else "json"
        response["Content-Disposition"] = (
            f'attachment; filename="programme-operator-run-sheet.{extension}"'
        )
        return _secure(response)
    return _html(
        request,
        _context(snapshot, print_view=output_format == "print")
        | {"output_links": links},
    )


@never_cache
@require_safe
@login_required(login_url="staff-login")
def operator_run_sheet(
    request: HttpRequest,
    *,
    organization_id: UUID,
    edition_id: UUID,
    scope_kind: str,
    target_id: UUID,
) -> HttpResponse:
    """Serve one fresh complete exact-purpose run sheet, without activating a route.

    Parameters
    ----------
    request : HttpRequest
        Authenticated GET/HEAD with optional closed format and layer requests.
    organization_id : UUID
        Exact expected tenant, not a discovery grant.
    edition_id : UUID
        Exact edition independently checked by every owning module.
    scope_kind : str
        Closed room, Department or edition purpose, not a user access flag.
    target_id : UUID
        Exact persisted purpose target, never a release, candidate or person.

    Returns
    -------
    HttpResponse
        Private no-store shared-shell HTML/print or complete JSON/calendar; safe
        non-disclosing 404, admitted malformed 400, unavailable 503 or calendar 409.

    Notes
    -----
    No production route includes this view. Base authority precedes option parsing;
    each requested layer then authorizes independently, including for empty scope.
    Failure never returns prior content, partial exports or a foreign selector list.
    """
    try:
        kind = OperatorScopeKind(scope_kind)
    except ValueError:
        return _secure(
            HttpResponse("Run sheet unavailable at this address.", status=404)
        )
    actor_id = request.user.pk
    if not isinstance(actor_id, UUID):
        return _secure(
            HttpResponse("Run sheet unavailable at this address.", status=404)
        )
    scope = OperatorReadRequest(
        actor_id, organization_id, edition_id, uuid4(), kind, target_id
    )
    try:
        authorize_operator_scope(
            scope,
            capability="scheduling.view_operator_output",
            fields=frozenset({"released_geometry"}),
        )
        output_format, layers = _options(request)
        snapshot = load_operator_run_sheet(scope, layers=layers)
        navigation = ContinuityScope(
            organization_id,
            edition_id,
            "private_operator",
            actor_id,
            kind.value,
            target_id,
            tuple(sorted(layers)),
        )
        urlconf = getattr(request, "urlconf", None)
        links = (
            programme_output_links(navigation, current="timetable", urlconf=urlconf)
            if output_format == "html"
            else ()
        )
        response = _render(request, snapshot, output_format, links=links)
        if links and links != programme_output_links(
            navigation, current="timetable", urlconf=urlconf
        ):
            response = _render(request, snapshot, output_format)
        fresh = load_operator_run_sheet(scope, layers=layers)
        verify_timetable_observation(snapshot, fresh)
    except SchedulingAuthorizationDeniedError:
        status, message = (
            404,
            "This run sheet or its requested layers are unavailable at this address. "
            "No partial output is provided.",
        )
    except TimetableOutputUnavailableError:
        status, message = (
            409,
            "No currently available release can be downloaded. Recheck the Programme "
            "run sheet; no earlier calendar is supplied.",
        )
    except (
        SchedulingUnavailableError,
        TimetableOutputInvalidError,
        DatabaseError,
        ValidationError,
        RuntimeError,
    ):
        status, message = (
            503,
            "The complete run sheet could not be verified. No earlier or partial "
            "output is shown. Reload to try again.",
        )
    except ValueError:
        status, message = (
            400,
            "Use the run-sheet format and layer controls without extra options.",
        )
    else:
        return response
    return _html(request, {"state_message": message}, status=status)
