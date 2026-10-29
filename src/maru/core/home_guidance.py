"""Compose the first owner-provided administration-home continuation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.urls import reverse

from maru.identity.models import Account
from maru.workforce.operating_home import load_workforce_home_guidance

if TYPE_CHECKING:
    from datetime import datetime

    from django.http import HttpRequest

    from maru.events.adoption import AdoptionProfile
    from maru.events.models import EventEdition
    from maru.workforce.home_guidance import WorkforceSetupGuidance
    from maru.workforce.home_states import OperatingHomeItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HomeGuidance:
    """Present one minimized module-owned continuation.

    Attributes
    ----------
    state
        Human-readable state, also present as text rather than colour alone.
    title
        Short task or current outcome.
    explanation
        Why the continuation matters, without hidden labels or counts.
    action_label
        Name of a currently authorized navigation action, if available.
    action_url
        Exact existing destination; it independently authorizes every request.
    checked_at
        Last disclosure authorization time; absent for unavailable guidance.
    area, due_at, due_label, time_zone
        Checked area and an optional authorized edition-local decision boundary.
    attention
        At most three other independently admitted owner continuations.
    """

    state: str
    title: str
    explanation: str
    action_label: str = ""
    action_url: str = ""
    checked_at: datetime | None = None
    area: str = "Team setup"
    due_at: datetime | None = None
    due_label: str = ""
    time_zone: str = "UTC"
    attention: tuple[HomeGuidance, ...] = ()


_COPY = {
    "departments": (
        "Ready",
        "Set up your Departments",
        "Define the teams before adding their Positions.",
        "Open team structure",
        "organization-structure",
    ),
    "positions": (
        "Ready",
        "Prepare the team's Positions",
        "Check templates and define each Position before recruiting volunteers.",
        "Open Positions",
        "organization-structure-positions",
    ),
    "opportunities": (
        "Ready",
        "Prepare a volunteer opportunity",
        "Review the Position's draft opportunity and decide when people may apply.",
        "Review this Position",
        "organization-structure-position",
    ),
    "published": (
        "Published",
        "Your current volunteer opportunities are published",
        "Review their application windows before sharing them with volunteers.",
        "Review Positions",
        "organization-structure-positions",
    ),
    "review": (
        "Review",
        "Review your existing Positions",
        (
            "Closed or withdrawn opportunities need an organizer's decision "
            "before new recruitment."
        ),
        "Review Positions",
        "organization-structure-positions",
    ),
    "read_only": (
        "Read only",
        "Review the retained team structure",
        "The current event or organization stage keeps this setup read-only.",
        "Review team structure",
        "organization-structure",
    ),
}


_OPERATING_COPY = {
    "assignment_wait_authority": (
        "Waiting",
        "An Assignment needs an authority manager",
        "An independent organizer with authority-management access can review "
        "the decision. You can review the retained proposal.",
        "Review Assignments",
        "organization-workforce-assignments",
    ),
    "shift_wait_manager": (
        "Waiting",
        "Shift claims need an organizer's review",
        "Confirmation requires Shift-management access and independence from "
        "the claimant. You can review the current work record.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "assignment_end": (
        "Review",
        "Review an expired Assignment",
        "Its authority interval has ended. Review the retained record and "
        "the required ending decision.",
        "Review this Assignment",
        "organization-workforce-assignment",
    ),
    "assignment_wait_end": (
        "Waiting",
        "An expired Assignment needs an authorized decision",
        "An organizer with authority-revocation access can finish the ending "
        "process. You can review its record.",
        "Review this Assignment",
        "organization-workforce-assignment",
    ),
    "assignment_review": (
        "Review",
        "Review a proposed Assignment",
        "Check its requirements and retained proposal before making an "
        "independent decision.",
        "Review this proposal",
        "organization-workforce-assignment",
    ),
    "assignment_wait_review": (
        "Waiting",
        "Waiting for an independent Assignment decision",
        "Another authorized organizer must decide a proposal you made. The "
        "decision also requires authority-management access.",
        "Review Assignments",
        "organization-workforce-assignments",
    ),
    "assignment_plan": (
        "Plan",
        "Prepare your team's Assignments",
        "Review the existing Positions, candidate eligibility and "
        "independent approval steps before assigning responsibility.",
        "Open Assignments",
        "organization-workforce-assignments",
    ),
    "assignment_active": (
        "Review",
        "Review your retained Assignments",
        "Responsibilities have their own terms. Shared Availability and "
        "scheduled work are checked separately.",
        "Review Assignments",
        "organization-workforce-assignments",
    ),
    "assignment_closing": (
        "Closing",
        "Review retained responsibilities",
        "Review pending proposals and authority endings while closing the "
        "event. Each decision keeps its existing approval rules.",
        "Review Assignments",
        "organization-workforce-assignments",
    ),
    "assignment_history": (
        "Retained",
        "Review Assignment history",
        "Retained responsibility records remain available through their "
        "authorized pages.",
        "Review Assignments",
        "organization-workforce-assignments",
    ),
    "availability_wait": (
        "Waiting",
        "Waiting for volunteers to share Availability",
        "A volunteer controls their own plan. Private drafts and unshared "
        "plans stay private; organizers can review shared consequences.",
        "Review Availability",
        "organization-workforce-availability",
    ),
    "availability_withdrawn": (
        "Review",
        "Review withdrawn Availability",
        "A volunteer withdrew a previously shared plan. Review the effect on "
        "planning and keep their sharing decision under their control.",
        "Review Availability",
        "organization-workforce-availability",
    ),
    "availability_empty": (
        "Review",
        "A shared plan records no available periods",
        "This is a deliberate shared outcome. Review the effect on work "
        "coverage without asking the home to change a person's plan.",
        "Review Availability",
        "organization-workforce-availability",
    ),
    "availability_shared": (
        "Shared",
        "Review shared Availability when planning work",
        "Shared plans are planning inputs. Each Shift decision checks its "
        "current evidence and existing constraints again.",
        "Review Availability",
        "organization-workforce-availability",
    ),
    "availability_retained": (
        "Read only",
        "Review retained Availability consequences",
        "The current event or organizer stage keeps this guidance read-only. "
        "Person-owned and retained records keep their existing access rules.",
        "Review Availability",
        "organization-workforce-availability",
    ),
    "shift_complete": (
        "Review",
        "Review an ended, locked Shift",
        "The scheduled end has passed. Review its record before using the "
        "existing completion decision.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_wait_complete": (
        "Waiting",
        "An ended Shift awaits organizer completion",
        "An organizer with Shift-management access can review the retained "
        "planned-work completion decision.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_ended": (
        "Review",
        "Review unfinished work whose scheduled end has passed",
        "This demand is still draft or open. Review its retained state and "
        "choose an allowed cleanup action on its page.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_changed": (
        "Review",
        "Review changed Shift eligibility",
        "An active commitment no longer matches current Position or shared "
        "Availability evidence. Its retained record needs review.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_claims": (
        "Review",
        "Review pending Shift claims",
        "A claim awaits independent organizer confirmation. The decision "
        "rechecks current eligibility, capacity and rest rules.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_wait_claims": (
        "Waiting",
        "Waiting for independent Shift confirmation",
        "Confirmation needs another authorized organizer for your own claim, "
        "and separate Shift-management access.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_coverage": (
        "Review",
        "Review Shift coverage",
        "Confirmed coverage is below the requested headcount. Review the "
        "demand and its current commitments before deciding what to do.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_lock": (
        "Review",
        "Review confirmed coverage before locking",
        "The current commitment states permit a coverage review. The lock "
        "decision rechecks evidence and any explicit risk acceptance.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_wait_lock": (
        "Waiting",
        "Coverage awaits an organizer's review",
        "An organizer with Shift-management access can review whether to "
        "lock coverage. You can review the current record.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_draft": (
        "Review",
        "Review a draft Shift",
        "Check the work terms, Position and time before deciding whether to "
        "open this demand for claims.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_wait_draft": (
        "Waiting",
        "A draft Shift needs an organizer's decision",
        "An organizer with Shift-management access can review and publish "
        "the work. You can review its current terms.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_closing": (
        "Closing",
        "Review retained Shift cleanup",
        "This event is closing. Review the demand's allowed cleanup "
        "decisions and retained evidence.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_scheduled": (
        "Scheduled",
        "Review upcoming locked work",
        "Coverage is locked and the scheduled start is still ahead. Current "
        "operating instructions remain on the Shift page.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_running": (
        "Scheduled time",
        "A locked Shift is within its scheduled interval",
        "Review the retained plan and its scheduled end. Attendance and "
        "actual work time have their own separate acceptance boundary.",
        "Review this Shift",
        "organization-workforce-shift",
    ),
    "shift_plan": (
        "Plan",
        "Review your Shift planning",
        "No timed demand is recorded in this checked area. Review Positions, "
        "Assignments and shared Availability before planning work.",
        "Open Shift planning",
        "organization-workforce-shifts",
    ),
    "shift_history": (
        "Retained",
        "Review retained Shift records",
        "Review completed or cancelled planned work through its existing "
        "history. Other team responsibilities may still need attention.",
        "Review Shifts",
        "organization-workforce-shifts",
    ),
}


def _unavailable() -> HomeGuidance:
    return HomeGuidance(
        "Unavailable",
        "Team setup guidance could not be checked",
        (
            "Refresh this page to try again. "
            "You can still open your permitted tools below."
        ),
    )


def _setup_item(result: WorkforceSetupGuidance, edition: EventEdition) -> HomeGuidance:
    if result.step == "unavailable":
        return _unavailable()
    try:
        ZoneInfo(edition.time_zone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return _unavailable()
    state, title, explanation, label, route = _COPY[result.step]
    args: list[object] = [edition.organization.slug, edition.series.slug, edition.slug]
    if result.step == "opportunities":
        args.append(result.position_id)
    if not result.can_manage:
        if result.step in {"departments", "positions", "opportunities"}:
            state = "Waiting"
            title = "Waiting for a team organizer"
            explanation = (
                "An organizer with structure-management access can continue this "
                "setup. "
                "You can review the current team structure."
            )
        label, route = "Review team structure", "organization-structure"
        args = args[:3]
    return HomeGuidance(
        state,
        title,
        explanation,
        label,
        reverse(route, args=args),
        result.checked_at,
        time_zone=edition.time_zone,
    )


def _operating_item(item: OperatingHomeItem, edition: EventEdition) -> HomeGuidance:
    area = (
        "Assignments"
        if item.code.startswith("assignment")
        else "Availability"
        if item.code.startswith("availability")
        else "Shifts"
    )
    copy = _OPERATING_COPY.get(item.code)
    if copy is None:
        return HomeGuidance(
            "Unavailable",
            area + " guidance could not be checked",
            "Refresh this page to try again. Your other permitted work stays "
            "available.",
            area=area,
        )
    state, title, explanation, label, route = copy
    args: list[object] = [edition.organization.slug, edition.series.slug, edition.slug]
    if item.object_id is not None:
        args.append(item.object_id)
    due_label = "Assignment expiry" if area == "Assignments" else "Shift starts"
    if item.code in {
        "shift_ended",
        "shift_complete",
        "shift_wait_complete",
        "shift_closing",
        "shift_running",
    }:
        due_label = "Shift ends"
    return HomeGuidance(
        state,
        title,
        explanation,
        label,
        reverse(route, args=args),
        item.checked_at,
        area=area,
        due_at=item.due_at if area != "Availability" else None,
        due_label=due_label,
        time_zone=item.time_zone,
    )


def project_home_guidance(
    request: HttpRequest,
    edition: EventEdition | None,
    profile: AdoptionProfile | None,
) -> HomeGuidance | None:
    """Filter the adopted purpose before asking its owner for current guidance.

    Parameters
    ----------
    request : HttpRequest
        Current authenticated request, with middleware-owned correlation.
    edition : EventEdition | None
        Already authorized selected event; never authority in its own right.
    profile : AdoptionProfile | None
        Exact immutable profile from the current selected-event context.

    Returns
    -------
    HomeGuidance | None
        One bounded contribution, or none outside this Workforce-only slice.
    """
    if (
        edition is None
        or profile is None
        or profile.code.value != "workforce_only"
        or profile.version != 1
        or not isinstance(request.user, Account)
        or not request.user.is_active
    ):
        return None
    try:
        result = load_workforce_home_guidance(
            actor=request.user,
            organization_id=edition.organization_id,
            edition_id=edition.id,
            correlation_id=UUID(str(getattr(request, "correlation_id", ""))),
            http_method=request.method or "GET",
        )
    except PermissionDenied:
        return None
    except (DatabaseError, RuntimeError, ValueError):
        logger.warning("Workforce home guidance unavailable.")
        return _unavailable()
    if result is None:
        return None
    candidates = [
        (item.priority, _operating_item(item, edition)) for item in result.operating
    ]
    if result.setup is not None:
        priority = {"published": 100, "read_only": 95, "unavailable": 60}.get(
            result.setup.step, 45
        )
        candidates.append((priority, _setup_item(result.setup, edition)))
    if not candidates:
        return None
    ordered = tuple(
        item
        for _priority, item in sorted(
            candidates, key=lambda pair: (pair[0], pair[1].area)
        )
    )
    return replace(ordered[0], attention=ordered[1:4])
