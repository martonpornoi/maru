"""Dormant exact-person timetable transport in the shared My Maru shell."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .authorization import SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError
from .output_rendering import MAX_TIMETABLE_OUTPUT_BYTES, TimetableOutputInvalidError
from .personal_output_queries import PersonalTimetable, load_personal_timetable
from .personal_output_rendering import (
    PersonalCalendarUnavailableError,
    render_personal_timetable_calendar,
    render_personal_timetable_json,
)
from .release_queries import ProgrammeReleaseState

if TYPE_CHECKING:
    from datetime import datetime

    from maru.programme.timetable_queries import PersonalHostPurpose

_WORK_LABELS = {
    "claimed": "Claim — not confirmed",
    "confirmed": "Confirmed work",
    "removed": "Removed work record",
    "completed": "Completed work record",
}


def _secure(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; manifest-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    response["Referrer-Policy"] = "same-origin"
    return response


def _html(
    request: HttpRequest, context: dict[str, object], *, status: int = 200
) -> HttpResponse:
    shell = admin.site.each_context(request)
    shell.update(
        has_permission=True,
        maru_personal_surface=True,
        title="My hosting and work timetable",
    )
    shell.update(context)
    content = render_to_string(
        "scheduling/personal_timetable.html", shell, request=request
    ).encode("utf-8")
    if len(content) > MAX_TIMETABLE_OUTPUT_BYTES:
        raise TimetableOutputInvalidError
    return _secure(HttpResponse(content, status=status))


def _context(snapshot: PersonalTimetable, *, print_view: bool) -> dict[str, object]:
    zone = ZoneInfo(snapshot.zone_name)

    def instant(value: datetime) -> str:
        return value.astimezone(zone).isoformat(sep=" ", timespec="minutes")

    rows: list[dict[str, object]] = []
    unscheduled: tuple[PersonalHostPurpose, ...] = ()
    calendar_available = True
    hosting_state = "Not adopted for this edition"
    if snapshot.hosting is not None:
        reference = snapshot.hosting.reference
        hosting_state = {
            None: "No confirmed hosting requires a release lookup",
            ProgrammeReleaseState.ABSENT: "No hosting timetable published yet",
            ProgrammeReleaseState.AVAILABLE: "Approved hosting release available",
            ProgrammeReleaseState.WITHDRAWN: (
                "Hosting release withdrawn — recheck with the organizer"
            ),
            ProgrammeReleaseState.INVALIDATED: (
                "Hosting release needs review — recheck with the organizer"
            ),
        }[reference.state]
        calendar_available = reference.state not in {
            ProgrammeReleaseState.WITHDRAWN,
            ProgrammeReleaseState.INVALIDATED,
        }
        purposes = {row.host_id: row for row in reference.purposes}
        rooms = {row.space_id: row for row in snapshot.hosting.rooms}
        placed = {row.host_id for row in reference.presences}
        unscheduled = tuple(
            row for row in reference.purposes if row.host_id not in placed
        )
        for presence in reference.presences:
            purpose = purposes[presence.host_id]
            rows.append(
                {
                    "kind": "hosting",
                    "sort": (presence.starts_at, "hosting", str(presence.placement_id)),
                    "title": purpose.title,
                    "state_label": "Approved required host presence",
                    "starts_label": instant(presence.starts_at),
                    "ends_label": instant(presence.ends_at),
                    "purpose": purpose,
                    "presence": presence,
                    "room": rooms[presence.space_id],
                    "preparation_label": instant(presence.envelope.setup_starts_at),
                    "delivery_label": instant(presence.envelope.effective_starts_at),
                    "delivery_end_label": instant(presence.envelope.effective_ends_at),
                    "teardown_label": instant(presence.envelope.teardown_ends_at),
                }
            )
    rows.extend(
        {
            "kind": "work",
            "sort": (shift.starts_at, "work", str(shift.commitment_id)),
            "title": shift.instructions.title,
            "state_label": _WORK_LABELS[shift.status],
            "starts_label": instant(shift.starts_at),
            "ends_label": instant(shift.ends_at),
            "rest_label": instant(shift.rest_ends_at),
            "shift": shift,
        }
        for shift in snapshot.shifts or ()
    )
    return {
        "snapshot": snapshot,
        "checked_label": instant(snapshot.checked_at),
        "print_view": print_view,
        "hosting_state": hosting_state,
        "calendar_available": calendar_available,
        "rows": sorted(
            rows, key=lambda row: cast("tuple[datetime, str, str]", row["sort"])
        ),
        "unscheduled": unscheduled,
    }


def _render(
    request: HttpRequest, snapshot: PersonalTimetable, output_format: str
) -> HttpResponse:
    # Validate the entire closed DTO before HTML traversal or any serialization.
    encoded = render_personal_timetable_json(snapshot)
    if output_format in {"json", "calendar"}:
        calendar = output_format == "calendar"
        response = HttpResponse(
            render_personal_timetable_calendar(snapshot) if calendar else encoded,
            content_type=(
                "text/calendar; charset=utf-8"
                if calendar
                else "application/json; charset=utf-8"
            ),
        )
        suffix = "ics" if calendar else "json"
        response["Content-Disposition"] = (
            f'attachment; filename="my-hosting-and-work.{suffix}"'
        )
        return _secure(response)
    return _html(request, _context(snapshot, print_view=output_format == "print"))


def _format(request: HttpRequest) -> str:
    if set(request.GET) - {"format"} or any(
        len(values) != 1 for _key, values in request.GET.lists()
    ):
        raise ValueError
    output_format = request.GET.get("format", "html")
    if output_format not in {"html", "print", "json", "calendar"}:
        raise ValueError
    return output_format


@never_cache
@require_safe
@login_required(login_url="staff-login")
def personal_timetable(
    request: HttpRequest, *, organization_id: UUID, edition_id: UUID
) -> HttpResponse:
    """Serve one freshly authorized own timetable without a subject selector.

    Parameters
    ----------
    request : HttpRequest
        Authenticated GET/HEAD with server-owned correlation and optional format.
    organization_id : UUID
        Exact requested tenant, not permission to disclose its existence.
    edition_id : UUID
        Exact edition independently checked by every adopted source owner.

    Returns
    -------
    HttpResponse
        Private no-store HTML/print, JSON/calendar download or safe error state.
        This component remains unmounted in production.
    """
    try:
        output_format = _format(request)
        snapshot = load_personal_timetable(
            actor_id=UUID(str(request.user.pk)),
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=UUID(str(request.correlation_id)),  # type: ignore[attr-defined]
        )
        return _render(request, snapshot, output_format)
    except (SchedulingAuthorizationDeniedError, ValidationError):
        status, title, message = (
            404,
            "Timetable not available",
            "Your timetable is not available at this address.",
        )
    except PersonalCalendarUnavailableError:
        status, title, message = (
            409,
            "Combined calendar not available",
            "Hosting was withdrawn or needs review. Reload your timetable to see "
            "its current state and your unchanged work. "
            "No partial calendar is provided.",
        )
    except (SchedulingUnavailableError, TimetableOutputInvalidError):
        status, title, message = (
            503,
            "Timetable temporarily unavailable",
            "Your complete adopted timetable could not be verified. "
            "No earlier or partial timetable is shown. Reload to try again.",
        )
    except ValueError:
        status, title, message = (
            400,
            "Check the timetable address",
            "Reload the timetable without extra options, then choose a copy format.",
        )
    return _html(
        request, {"state_title": title, "state_message": message}, status=status
    )
