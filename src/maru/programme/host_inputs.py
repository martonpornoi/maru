"""Pure bounded host intent and offset-aware availability normalization."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from .host_catalogs import (
    MAX_HOST_AVAILABILITY_PERIODS,
    MAX_HOST_BRIEFING,
    MAX_HOST_INVITATION_TITLE,
    ProgrammeHostAvailabilityKind,
    ProgrammeHostAvailabilityState,
    ProgrammeHostResponse,
    ProgrammeHostRole,
)
from .inputs import (
    normalized_closed_code,
    normalized_text,
    require_expected_version,
    require_positive_version,
    require_uuid,
)

if TYPE_CHECKING:
    from uuid import UUID


def _host_version(value: int, *, field: str, initial: bool = False) -> int:
    version = (
        require_expected_version(value, field=field)
        if initial
        else require_positive_version(value, field=field)
    )
    if version >= 2**63 - 1:
        raise ValidationError(
            "The host version cannot advance.", code="programme_host_version_invalid"
        )
    return version


def _host_briefing(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(
            "Supply host briefing text.", code="programme_host_briefing_invalid"
        )
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n")).strip()
    if len(value) > MAX_HOST_BRIEFING or any(
        unicodedata.category(character) == "Cc" and character != "\n"
        for character in value
    ):
        raise ValidationError(
            "Use bounded host briefing text without control characters.",
            code="programme_host_briefing_invalid",
        )
    return value


def _utc_minute(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.second
        or value.microsecond
    ):
        raise ValidationError(
            "Use an offset-aware whole-minute instant.",
            code="programme_host_instant_invalid",
        )
    try:
        result = value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValidationError(
            "The instant cannot be represented in UTC.",
            code="programme_host_instant_invalid",
        ) from error
    if result.second or result.microsecond:
        raise ValidationError(
            "Use a whole-minute UTC instant.",
            code="programme_host_instant_invalid",
        )
    return result


@dataclass(frozen=True, slots=True)
class ProgrammeHostAvailabilityPeriod:
    """One half-open period that the person deliberately chose to supply.

    Attributes
    ----------
    starts_at
        Inclusive offset-aware start, normalized to a whole UTC minute.
    ends_at
        Exclusive offset-aware end, normalized to a whole UTC minute.
    kind
        Available or preferred, never inferred from absence.
    """

    starts_at: datetime
    ends_at: datetime
    kind: str = ProgrammeHostAvailabilityKind.AVAILABLE.value

    def normalized(self) -> ProgrammeHostAvailabilityPeriod:
        """Validate and freeze one positive UTC interval.

        Returns
        -------
        ProgrammeHostAvailabilityPeriod
            An equivalent interval with canonical UTC instants and kind.

        Raises
        ------
        ValidationError
            If the interval does not have a positive duration.
        """
        start, end = _utc_minute(self.starts_at), _utc_minute(self.ends_at)
        kind = normalized_closed_code(
            self.kind, enum_type=ProgrammeHostAvailabilityKind, field="kind"
        )
        if end <= start:
            raise ValidationError(
                "The end must be after the start.",
                code="programme_host_period_invalid",
            )
        return ProgrammeHostAvailabilityPeriod(start, end, kind.value)


def normalize_host_availability_periods(
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...],
    *,
    edition_starts_at: datetime,
    edition_ends_at: datetime,
) -> tuple[ProgrammeHostAvailabilityPeriod, ...]:
    """Bound and order non-overlapping periods inside the owner's edition envelope.

    Parameters
    ----------
    periods : tuple[ProgrammeHostAvailabilityPeriod, ...]
        Complete bounded replacement; an empty tuple is meaningful.
    edition_starts_at : datetime
        Trusted inclusive start resolved from Events, never client scope.
    edition_ends_at : datetime
        Trusted exclusive end resolved from Events, never client scope.

    Returns
    -------
    tuple[ProgrammeHostAvailabilityPeriod, ...]
        Ordered normalized periods with adjacency preserved.

    Raises
    ------
    ValidationError
        If the complete periods are unbounded, overlapping or outside the edition.
    """
    if (
        not isinstance(periods, tuple)
        or len(periods) > MAX_HOST_AVAILABILITY_PERIODS
        or any(
            not isinstance(period, ProgrammeHostAvailabilityPeriod)
            for period in periods
        )
    ):
        raise ValidationError(
            "Supply a bounded complete tuple of host availability periods.",
            code="programme_host_periods_invalid",
        )
    edition_start, edition_end = (
        _utc_minute(edition_starts_at),
        _utc_minute(edition_ends_at),
    )
    if edition_end <= edition_start:
        raise ValidationError(
            "The edition time envelope is unavailable.",
            code="programme_host_edition_envelope_invalid",
        )
    ordered = tuple(
        sorted((period.normalized() for period in periods), key=lambda p: p.starts_at)
    )
    previous_end = edition_start
    for period in ordered:
        if period.starts_at < previous_end or period.ends_at > edition_end:
            raise ValidationError(
                "Periods must not overlap and must stay inside the edition.",
                code="programme_host_periods_conflict",
            )
        previous_end = period.ends_at
    return ordered


@dataclass(frozen=True, slots=True)
class ProgrammeHostInvitationInput:
    """An explicit organizer invitation, independent of any proposal roster.

    Attributes
    ----------
    account_id
        Existing exact person whom Identity must independently revalidate.
    role
        Host or co-host; reinvitation requires fresh person confirmation.
    title
        Deliberately host-visible invitation title, not inferred working copy.
    briefing
        Deliberately shared bounded operational briefing.
    expected_item_version
        Exact current Programme item version.
    expected_host_version
        Zero only for the first invitation to this item/person.
    """

    account_id: UUID
    role: str
    title: str
    briefing: str
    expected_item_version: int
    expected_host_version: int = 0

    def normalized(self) -> ProgrammeHostInvitationInput:
        """Normalize the complete explicit invitation without deriving private values.

        Returns
        -------
        ProgrammeHostInvitationInput
            Frozen normalized intent suitable for exact retry comparison.
        """
        return ProgrammeHostInvitationInput(
            account_id=require_uuid(self.account_id, field="account_id"),
            role=normalized_closed_code(
                self.role, enum_type=ProgrammeHostRole, field="role"
            ).value,
            title=normalized_text(
                self.title,
                field="title",
                maximum=MAX_HOST_INVITATION_TITLE,
                required=True,
                collapse=True,
            ),
            briefing=_host_briefing(self.briefing),
            expected_item_version=_host_version(
                self.expected_item_version, field="expected_item_version"
            ),
            expected_host_version=_host_version(
                self.expected_host_version, field="expected_host_version", initial=True
            ),
        )


@dataclass(frozen=True, slots=True)
class ProgrammeHostResponseInput:
    """One person's response to a versioned invitation or confirmed relationship.

    Attributes
    ----------
    host_id
        Exact relationship that must belong to the authenticated actor.
    response
        Confirm, decline or withdraw; organizers cannot respond for the subject.
    expected_item_version
        Optimistic item version shared with other Programme commands.
    expected_host_version
        Exact current relationship version.
    invitation_sequence
        Exact invitation whose response is being recorded.
    """

    host_id: UUID
    response: str
    expected_item_version: int
    expected_host_version: int
    invitation_sequence: int

    def normalized(self) -> ProgrammeHostResponseInput:
        """Validate a response without accepting caller-owned person or audit fields.

        Returns
        -------
        ProgrammeHostResponseInput
            Frozen normalized response intent.
        """
        return ProgrammeHostResponseInput(
            host_id=require_uuid(self.host_id, field="host_id"),
            response=normalized_closed_code(
                self.response, enum_type=ProgrammeHostResponse, field="response"
            ).value,
            expected_item_version=_host_version(
                self.expected_item_version, field="expected_item_version"
            ),
            expected_host_version=_host_version(
                self.expected_host_version, field="expected_host_version"
            ),
            invitation_sequence=_host_version(
                self.invitation_sequence, field="invitation_sequence"
            ),
        )


def normalize_host_availability_state(value: str) -> ProgrammeHostAvailabilityState:
    """Admit only a person's explicit draft, share or withdrawal command.

    Parameters
    ----------
    value : str
        Untrusted requested availability state.

    Returns
    -------
    ProgrammeHostAvailabilityState
        A person-owned target state; unknown is not a write operation.

    Raises
    ------
    ValidationError
        If the caller attempts to write an unknown sharing state.
    """
    state = normalized_closed_code(
        value, enum_type=ProgrammeHostAvailabilityState, field="availability_state"
    )
    if state is ProgrammeHostAvailabilityState.UNKNOWN:
        raise ValidationError(
            "Choose draft, shared or withdrawn availability.",
            code="programme_host_availability_state_invalid",
        )
    return state


@dataclass(frozen=True, slots=True)
class ProgrammeHostAvailabilityInput:
    """Complete person-owned availability intent for one exact relationship.

    Attributes
    ----------
    host_id
        Exact relationship owned by the authenticated person.
    state
        Explicit draft, shared or withdrawn target state.
    periods
        Complete replacement; withdrawal must carry no periods.
    expected_item_version
        Current Programme item version.
    expected_host_version
        Current relationship version.
    """

    host_id: UUID
    state: str
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...]
    expected_item_version: int
    expected_host_version: int

    def normalized(self) -> ProgrammeHostAvailabilityInput:
        """Normalize bounded intent before the locked edition-envelope check.

        Returns
        -------
        ProgrammeHostAvailabilityInput
            Immutable intent; the command must still validate current edition bounds.

        Raises
        ------
        ValidationError
            If withdrawal would retain exact periods.
        """
        state = normalize_host_availability_state(self.state)
        periods = normalize_host_availability_periods(
            self.periods,
            edition_starts_at=datetime.min.replace(tzinfo=UTC),
            edition_ends_at=datetime.max.replace(second=0, microsecond=0, tzinfo=UTC),
        )
        if state is ProgrammeHostAvailabilityState.WITHDRAWN and periods:
            raise ValidationError(
                "Withdrawal must not retain availability periods.",
                code="programme_host_withdrawal_periods_forbidden",
            )
        return ProgrammeHostAvailabilityInput(
            require_uuid(self.host_id, field="host_id"),
            state.value,
            periods,
            _host_version(self.expected_item_version, field="expected_item_version"),
            _host_version(self.expected_host_version, field="expected_host_version"),
        )


def host_availability_periods_digest(
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...],
) -> str:
    """Fingerprint normalized periods without retaining their historical values.

    Parameters
    ----------
    periods : tuple[ProgrammeHostAvailabilityPeriod, ...]
        Already validated, ordered UTC whole-minute intervals.

    Returns
    -------
    str
        Lowercase SHA-256 of newline-separated epoch-second and closed-kind rows.
        PostgreSQL independently computes this exact representation.
    """
    encoded = "\n".join(
        f"{int(period.starts_at.timestamp())}:{int(period.ends_at.timestamp())}:{period.kind}"
        for period in periods
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
