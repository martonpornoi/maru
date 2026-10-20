"""Compose the first owner-provided administration-home continuation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.urls import reverse

from maru.identity.models import Account
from maru.workforce.home_guidance import load_workforce_setup_guidance

if TYPE_CHECKING:
    from datetime import datetime

    from django.http import HttpRequest

    from maru.events.adoption import AdoptionProfile
    from maru.events.models import EventEdition

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
    """

    state: str
    title: str
    explanation: str
    action_label: str = ""
    action_url: str = ""
    checked_at: datetime | None = None


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


def _unavailable() -> HomeGuidance:
    return HomeGuidance(
        "Unavailable",
        "Team setup guidance could not be checked",
        (
            "Refresh this page to try again. "
            "You can still open your permitted tools below."
        ),
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
        result = load_workforce_setup_guidance(
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
    if result.step == "unavailable":
        return _unavailable()
    state, title, explanation, label, route = _COPY[result.step]
    args: list[object] = [edition.organization.slug, edition.series.slug, edition.slug]
    if result.step == "opportunities":
        args.append(result.position_id)
    if (
        result.step in {"departments", "positions", "opportunities"}
        and not result.can_manage
    ):
        state = "Waiting"
        title = "Waiting for a team organizer"
        explanation = (
            "An organizer with structure-management access can continue this setup. "
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
    )
