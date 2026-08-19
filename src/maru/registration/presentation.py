"""Purpose-bound attendee presentation derived from authoritative records."""

from dataclasses import asdict, dataclass

from maru.participation.models import ParticipationCapacity
from maru.registration.models import Entitlement, Registration


@dataclass(frozen=True, slots=True)
class AttendanceLabel:
    """One accessible attendee-directory label and its semantic color token.

    Attributes
    ----------
    code
        The stable domain code to resolve or validate.
    label
        The human-readable label shown to authorized readers.
    tone
        The tone retained in this immutable projection.
    """

    code: str
    label: str
    tone: str

    def as_dict(self) -> dict[str, str]:
        """Serialize this specification as a dictionary.

        Returns
        -------
        dict[str, str]
            A mapping containing the resolved as dict data.
        """
        return asdict(self)


def _contains_any(value: str, candidates: tuple[str, ...]) -> bool:
    normalized = value.casefold()
    return any(candidate in normalized for candidate in candidates)


def attendance_labels(registration: Registration) -> tuple[AttendanceLabel, ...]:
    """Derive public-safe labels without exposing product, price, or payment.

    Parameters
    ----------
    registration : Registration
        The attendee registration governed by the operation.

    Returns
    -------
    tuple[AttendanceLabel, ...]
        The matching attendance labels records in deterministic order.
    """
    active_entitlements = [
        entitlement
        for entitlement in registration.entitlements.all()
        if entitlement.status == Entitlement.Status.ACTIVE
    ]
    entitlement_text = " ".join(
        f"{entitlement.code} {entitlement.label_snapshot}"
        for entitlement in active_entitlements
    )
    admission_text = (
        f"{registration.product.code} {registration.product_name_snapshot} "
        f"{entitlement_text}"
    )

    if _contains_any(admission_text, ("guest", "guest-of-honour")):
        primary = AttendanceLabel("guest", "Guest", "guest")
    elif _contains_any(
        admission_text,
        ("infinity", "super-sponsor", "super sponsor", "supersponsor"),
    ):
        primary = AttendanceLabel(
            "super_sponsor",
            "Super sponsor",
            "super-sponsor",
        )
    elif _contains_any(admission_text, ("sponsor", "supporter", "patron")):
        primary = AttendanceLabel("sponsor", "Sponsor", "sponsor")
    else:
        primary = AttendanceLabel("attendee", "Attendee", "attendee")

    capacities = registration.participation.capacities.all()
    volunteer = any(
        capacity.status
        in (
            ParticipationCapacity.Status.PROPOSED,
            ParticipationCapacity.Status.ACTIVE,
        )
        and capacity.code == "volunteer"
        for capacity in capacities
    )
    if volunteer:
        return (
            primary,
            AttendanceLabel("volunteer", "Volunteer", "volunteer"),
        )
    return (primary,)
