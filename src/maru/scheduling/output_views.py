"""Dormant public timetable page and freshly checked complete download adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .authorization import SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError
from .output_queries import PublicProgrammeTimetable, load_public_programme_timetable
from .output_rendering import (
    MAX_TIMETABLE_OUTPUT_BYTES,
    TimetableOutputInvalidError,
    TimetableOutputUnavailableError,
    render_public_timetable_calendar,
    render_public_timetable_json,
)

if TYPE_CHECKING:
    from datetime import datetime

_UUID_TEXT_LENGTH = 36


@dataclass(frozen=True, slots=True)
class _Options:
    format: str
    day_id: UUID | None
    space_id: UUID | None


def _options(request: HttpRequest) -> _Options:
    if set(request.GET) - {"format", "day", "room"} or any(
        len(values) != 1 for _key, values in request.GET.lists()
    ):
        raise ValueError
    output_format = request.GET.get("format", "html")
    if output_format not in {"html", "json", "calendar", "print"}:
        raise ValueError
    selected = []
    for key in ("day", "room"):
        value = request.GET.get(key, "")
        if value and (len(value) != _UUID_TEXT_LENGTH or str(UUID(value)) != value):
            raise ValueError
        selected.append(UUID(value) if value else None)
    if output_format != "html" and any(selected):
        raise ValueError
    return _Options(output_format, *selected)


def _secure(response: HttpResponse) -> HttpResponse:
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    response["Referrer-Policy"] = "same-origin"
    return response


def _state(
    request: HttpRequest, *, status: int, title: str, message: str
) -> HttpResponse:
    return _secure(
        HttpResponse(
            render_to_string(
                "scheduling/public_timetable.html",
                {"state_title": title, "state_message": message},
                request=request,
            ),
            status=status,
        )
    )


def _page_context(
    snapshot: PublicProgrammeTimetable, options: _Options
) -> dict[str, object]:
    zone = ZoneInfo(snapshot.zone_name)

    def instant(value: datetime) -> str:
        return value.astimezone(zone).isoformat(sep=" ", timespec="minutes")

    days = {row.day_id: instant(row.day_starts_at) for row in snapshot.entries}
    rooms = {
        row.room.space_id: f"{row.room.venue_name} / {row.room.room_name}"
        for row in snapshot.entries
    }
    if (options.day_id is not None and options.day_id not in days) or (
        options.space_id is not None and options.space_id not in rooms
    ):
        raise ValueError
    selected = tuple(
        row
        for row in snapshot.entries
        if (
            (options.day_id is None or row.day_id == options.day_id)
            and (options.space_id is None or row.room.space_id == options.space_id)
        )
    )
    return {
        "snapshot": snapshot,
        "published_label": instant(snapshot.published_at)
        if snapshot.published_at
        else "",
        "checked_label": instant(snapshot.checked_at),
        "days": tuple(sorted(days.items(), key=lambda row: (row[1], str(row[0])))),
        "rooms": tuple(
            sorted(rooms.items(), key=lambda row: (row[1].casefold(), str(row[0])))
        ),
        "options": options,
        "print_view": options.format == "print",
        "total_count": len(snapshot.entries),
        "rows": tuple(
            {
                "entry": row,
                "starts_label": instant(row.starts_at),
                "ends_label": instant(row.ends_at),
                "starts_iso": row.starts_at.isoformat(),
                "ends_iso": row.ends_at.isoformat(),
                "day_label": days[row.day_id],
            }
            for row in selected
        ),
    }


def _render_snapshot(
    request: HttpRequest, snapshot: PublicProgrammeTimetable, options: _Options
) -> HttpResponse:
    # The same closed DTO and byte bounds govern HTML as well as JSON.
    encoded_json = render_public_timetable_json(snapshot)
    if options.format == "json":
        response = HttpResponse(
            encoded_json, content_type="application/json; charset=utf-8"
        )
        response["Content-Disposition"] = (
            'attachment; filename="programme-timetable.json"'
        )
        return _secure(response)
    if options.format == "calendar":
        response = HttpResponse(
            render_public_timetable_calendar(snapshot),
            content_type="text/calendar; charset=utf-8",
        )
        response["Content-Disposition"] = (
            'attachment; filename="programme-timetable.ics"'
        )
        return _secure(response)
    context = _page_context(snapshot, options)
    content = render_to_string(
        "scheduling/public_timetable.html", context, request=request
    ).encode("utf-8")
    if len(content) > MAX_TIMETABLE_OUTPUT_BYTES:
        raise TimetableOutputInvalidError
    return _secure(HttpResponse(content, content_type="text/html; charset=utf-8"))


@never_cache
@require_safe
def public_programme_timetable(
    request: HttpRequest, *, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Render public reviewed Programme or one complete newly checked download.

    Parameters
    ----------
    request : HttpRequest
        GET/HEAD with only bounded format, service-day and room selectors.
    organization_id : UUID
        Typed route scope, never proof that the organization may be disclosed.
    edition_id : UUID
        Typed exact edition; current public adapter admission is mandatory.

    Returns
    -------
    HttpResponse
        No-store public HTML/JSON/calendar, or a content-free safe error state.
        This view is not mounted in the production URL configuration.
    """
    try:
        options = _options(request)
        snapshot = load_public_programme_timetable(
            organization_id=organization_id, edition_id=edition_id
        )
        return _render_snapshot(request, snapshot, options)
    except (SchedulingAuthorizationDeniedError, ValidationError):
        return _state(
            request,
            status=404,
            title="Timetable not available",
            message="There is no public timetable available at this address.",
        )
    except TimetableOutputUnavailableError:
        return _state(
            request,
            status=409,
            title="Download not available",
            message=(
                "A calendar can be downloaded only while a complete Programme "
                "release is available. Reload to check its current state."
            ),
        )
    except (SchedulingUnavailableError, TimetableOutputInvalidError):
        return _state(
            request,
            status=503,
            title="Timetable temporarily unavailable",
            message=(
                "The complete release could not be verified. No earlier or partial "
                "timetable is being shown. Reload to try again."
            ),
        )
    except ValueError:
        return _state(
            request,
            status=400,
            title="Check the timetable filters",
            message=(
                "Choose a day and room from the current release, "
                "or reload the complete timetable."
            ),
        )
