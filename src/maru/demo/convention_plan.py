"""Pure, bounded content and date choices for the interactive convention demo."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

DEMO_ZONE = "Europe/Budapest"
DEMO_NAMESPACE = UUID("9b53ade1-391a-43ab-938f-879685d6dd38")
SCENARIOS = ("ongoing", "future")
CONTENT_ROLES = ("author", "reviewer", "reader")
ACCOUNT_KEYS = (
    "platform",
    "operator-a",
    "operator-b",
    *(f"{edition}-{role}" for edition in SCENARIOS for role in CONTENT_ROLES),
)
PREPARATION_REASON = (
    "Prepare fictional MaruCon practice data through real commands; "
    "synthetic decisions are not independent human acceptance."
)


@dataclass(frozen=True, slots=True)
class DemoEdition:
    """Fixed creation-time dates, kept unchanged throughout a preview.

    Attributes
    ----------
    key, name
        Stable scenario key and plain-language fictional event label.
    starts_on, ends_on
        Inclusive event dates in the explicit demonstration timezone.
    review_on
        Future deadline keeping the initial practice items usable.
    """

    key: str
    name: str
    starts_on: date
    ends_on: date
    review_on: date


def edition_plan(anchor: date) -> tuple[DemoEdition, DemoEdition]:
    """Make an underway and a future timeline without changing the clock.

    Parameters
    ----------
    anchor : date
        Event-local date captured once when creating a new preview.

    Returns
    -------
    tuple[DemoEdition, DemoEdition]
        The two immutable timelines; no dates are recomputed on page reads.

    Raises
    ------
    ValueError
        If the input is not a date or cannot hold both bounded timelines.
    """
    if type(anchor) is not date:
        raise ValueError("Use a calendar date for the demo anchor.")
    try:
        return (
            DemoEdition(
                "ongoing",
                "MaruCon - happening now",
                anchor - timedelta(days=1),
                anchor + timedelta(days=2),
                anchor + timedelta(days=30),
            ),
            DemoEdition(
                "future",
                "MaruCon - next gathering",
                anchor + timedelta(days=90),
                anchor + timedelta(days=93),
                anchor + timedelta(days=120),
            ),
        )
    except OverflowError as error:
        raise ValueError("The demo timeline exceeds the supported calendar.") from error


def current_anchor(now: datetime) -> date:
    """Resolve the explicit event-local anchor from an aware instant.

    Parameters
    ----------
    now : datetime
        Aware creation instant, independent of the host's local timezone.

    Returns
    -------
    date
        Creation date in Europe/Budapest.

    Raises
    ------
    ValueError
        If the instant is naive.
    """
    if now.utcoffset() is None:
        raise ValueError("The demo creation instant must include its timezone.")
    return now.astimezone(ZoneInfo(DEMO_ZONE)).date()


def account_identity(key: str) -> tuple[UUID, str]:
    """Resolve one reserved synthetic account without accepting arbitrary identities.

    Parameters
    ----------
    key : str
        One of the closed preview account keys.

    Returns
    -------
    tuple[UUID, str]
        Deterministic identity and reserved fictional email address.

    Raises
    ------
    ValueError
        If the requested account is outside this fixture.
    """
    if key not in ACCOUNT_KEYS:
        raise ValueError("Unknown convention demo account.")
    return uuid5(DEMO_NAMESPACE, key), f"demo.{key}@maru.invalid"


# All examples are fictional. There are no real emergency instructions or sends.
ANNOUNCEMENT_EXAMPLES = (
    (
        "draft",
        "Fursuit photo gathering",
        (
            "Practice draft: meet by the paper moon backdrop. Add a time "
            "before asking for review."
        ),
    ),
    (
        "in_review",
        "Sketch meetup has moved",
        (
            "Practice notice: the sketch meetup is now in the Birch room."
            " This fictional notice has not been posted anywhere."
        ),
    ),
    (
        "approved",
        "Welcome to MaruCon",
        (
            "Fictional welcome notice: the welcome desk is beside the "
            "blue paw sign. Ask there for a printed map."
        ),
    ),
)
GUIDE_EXAMPLES = (
    (
        "draft",
        "Preparing the welcome desk",
        (
            "Practice draft: put out the maps and the blue paw sign. Add "
            "the desk opening steps before asking for review."
        ),
    ),
    (
        "in_review",
        "Finding the quiet room",
        (
            "Fictional team guide: the quiet room is beside the Birch "
            "room. Replace these practice directions with reviewed local "
            "information before any real event."
        ),
    ),
    (
        "approved",
        "Helping someone find a room",
        (
            "Fictional team guide: use the printed map at the welcome "
            "desk. Point out the room name and route. These are practice "
            "directions for MaruCon, not a real venue."
        ),
    ),
)
