"""Closed fictional identities and fixed timelines for Workforce-only practice."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from maru.demo.convention_plan import DEMO_ZONE, SCENARIOS, DemoEdition
from maru.demo.convention_plan import edition_plan as convention_edition_plan

ROLES = ("manager", "reviewer", "volunteer")
ACCOUNT_KEYS = (
    "platform",
    "operator-a",
    "operator-b",
    *(f"{edition}-{role}" for edition in SCENARIOS for role in ROLES),
)
_NAMESPACE = UUID("239ca9bb-6141-4da1-a7b7-ac67637eeaae")


def account_identity(key: str) -> tuple[UUID, str]:
    """Resolve only one of the reserved, distinct Workforce practice identities.

    Parameters
    ----------
    key : str
        One of the fixed platform, operator or edition-role account keys.

    Returns
    -------
    tuple[UUID, str]
        Reserved synthetic identifier and fictional email, never a real recipient.

    Raises
    ------
    ValueError
        If the requested key is outside this fixture.
    """
    if key not in ACCOUNT_KEYS:
        raise ValueError("Unknown Workforce practice account.")
    return uuid5(_NAMESPACE, key), f"workforce.{key}@maru.invalid"


def edition_plan(anchor: date) -> tuple[DemoEdition, DemoEdition]:
    """Reuse the creation-time calendar with explicit Workforce event names.

    Parameters
    ----------
    anchor : date
        Captured event-local creation date; reads never move the timeline.

    Returns
    -------
    tuple[DemoEdition, DemoEdition]
        One ongoing and one future fictional Workforce-only edition.
    """
    ongoing, future = convention_edition_plan(anchor)
    return (
        replace(ongoing, name="MaruCon team - happening now"),
        replace(future, name="MaruCon team - next gathering"),
    )


def shift_period(plan: DemoEdition, prepared_at: datetime) -> tuple[datetime, datetime]:
    """Prepare short ongoing work or a future morning without backdating authority.

    Parameters
    ----------
    plan : DemoEdition
        One fixed creation-time edition timeline.
    prepared_at : datetime
        Aware current instant after the fixture's controlling grants were issued.

    Returns
    -------
    tuple[datetime, datetime]
        A real upcoming interval. Ongoing work ends after five actual minutes;
        the future interval stays at ten to eleven in the named edition zone.

    Raises
    ------
    ValueError
        If the instant is naive or the scenario key is unsupported.
    """
    if prepared_at.utcoffset() is None or plan.key not in SCENARIOS:
        raise ValueError("Use an aware instant and a supported practice edition.")
    if plan.key == "ongoing":
        return prepared_at + timedelta(minutes=3), prepared_at + timedelta(minutes=5)
    start = datetime.combine(plan.starts_on, time(10), ZoneInfo(DEMO_ZONE))
    return start, start + timedelta(hours=1)
