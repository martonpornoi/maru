"""Typed, bounded Scheduling intent without caller-controlled authority facts."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError

from .catalogs import (
    MAX_OCCURRENCES,
    MAX_REASON_LENGTH,
    MAX_SOURCE_CHANNEL_LENGTH,
    MAX_TITLE_LENGTH,
)
from .time_rules import (
    SchedulingEnvelope,
    SchedulingHostPresence,
    SchedulingWindow,
    normalize_host_presences,
    normalize_scheduling_envelope,
    normalize_scheduling_window,
    require_scheduling_precision,
)


def require_identifier(value: UUID) -> UUID:
    """Require a parsed exact identifier, without inferring tenant scope.

    Parameters
    ----------
    value : UUID
        Untrusted identifier.

    Returns
    -------
    UUID
        The unchanged typed identifier.

    Raises
    ------
    ValidationError
        If the identifier is not a UUID.
    """
    if not isinstance(value, UUID):
        raise ValidationError("Supply an exact typed Scheduling identifier.")
    return value


def require_version(value: int, *, initial: bool = False) -> int:
    """Validate an advanceable version without accepting booleans or coercion.

    Parameters
    ----------
    value : int
        Caller-observed optimistic version.
    initial : bool, default=False
        Whether a not-yet-created edition control may be version zero.

    Returns
    -------
    int
        The unchanged bounded integer.

    Raises
    ------
    ValidationError
        If the version is malformed, negative, zero when disallowed or exhausted.
    """
    if type(value) is not int or not (0 if initial else 1) <= value < 2**63 - 1:
        raise ValidationError("Supply an exact advanceable Scheduling version.")
    return value


def normalized_text(value: str, *, maximum: int) -> str:
    """Normalize bounded single-line human text without inventing a rationale.

    Parameters
    ----------
    value : str
        Explicit label or explanation.
    maximum : int
        Code-owned character bound.

    Returns
    -------
    str
        Nonempty NFC text with ordinary surrounding whitespace removed.

    Raises
    ------
    ValidationError
        If text is empty, over-bound or contains control characters.
    """
    if not isinstance(value, str):
        raise ValidationError("Supply Scheduling text.")
    normalized = unicodedata.normalize("NFC", value).strip()
    if (
        not normalized
        or len(normalized) > maximum
        or any(
            unicodedata.category(character).startswith("C") for character in normalized
        )
    ):
        raise ValidationError("Use bounded nonempty text without control characters.")
    return normalized


def scheduling_digest(payload: dict[str, object]) -> str:
    """Hash a code-owned canonical payload; never use the digest as authority.

    Parameters
    ----------
    payload : dict[str, object]
        Already normalized JSON-compatible intent or minimized dependency evidence.

    Returns
    -------
    str
        Lower-case SHA-256 digest of sorted compact UTF-8 JSON.
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SchedulingCommandRequest:
    """Trusted adapter attribution with one actor/edition retry namespace.

    Attributes
    ----------
    actor_id
        Authenticated current person, independently resolved by policy.
    organization_id
        Expected owner; not accepted as proof of ownership.
    edition_id
        Exact intended edition.
    idempotency_key
        Stable key for retries of the same normalized intent.
    correlation_id
        Trusted trace identifier, not part of retry equivalence.
    reason
        Inspectable action reason or explicit human rationale as the command requires.
    source_channel
        Trusted bounded adapter code.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    idempotency_key: UUID
    correlation_id: UUID
    reason: str
    source_channel: str = "scheduling"

    def normalized(self) -> SchedulingCommandRequest:
        """Validate identifiers and rationale without resolving private domain state.

        Returns
        -------
        SchedulingCommandRequest
            Complete normalized attribution.

        Raises
        ------
        ValidationError
            If the source channel is not a bounded lower-case adapter code.
        """
        for value in (
            self.actor_id,
            self.organization_id,
            self.edition_id,
            self.idempotency_key,
            self.correlation_id,
        ):
            require_identifier(value)
        if (
            not isinstance(self.source_channel, str)
            or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,31}", self.source_channel)
            or len(self.source_channel) > MAX_SOURCE_CHANNEL_LENGTH
        ):
            raise ValidationError("Use a registered lower-case source channel.")
        return SchedulingCommandRequest(
            self.actor_id,
            self.organization_id,
            self.edition_id,
            self.idempotency_key,
            self.correlation_id,
            normalized_text(self.reason, maximum=MAX_REASON_LENGTH),
            self.source_channel,
        )


@dataclass(frozen=True, slots=True)
class SchedulingServiceDayInput:
    """Explicit day intent; overnight windows are not split at browser midnight.

    Attributes
    ----------
    label
        Human-readable private service-day name.
    window
        Positive absolute half-open interval within the current edition.
    precision_minutes
        Whole-minute grid step anchored to the supplied start.
    """

    label: str
    window: SchedulingWindow
    precision_minutes: int

    def normalized(self) -> SchedulingServiceDayInput:
        """Normalize exact instants, bounded label and supported grid precision.

        Returns
        -------
        SchedulingServiceDayInput
            Frozen normalized day intent; owner bounds are checked separately.
        """
        return SchedulingServiceDayInput(
            normalized_text(self.label, maximum=MAX_TITLE_LENGTH),
            normalize_scheduling_window(self.window),
            require_scheduling_precision(self.precision_minutes),
        )


@dataclass(frozen=True, slots=True)
class SchedulingOccurrenceInput:
    """Bind explicit occurrence identity without copying Programme content.

    Attributes
    ----------
    item_id
        Exact Programme-owned source item.
    group_key
        Optional edition-scoped explicit group identity, not an inferred recurrence.
    group_sequence
        Positive sequence within the group, required exactly when a group is supplied.
    """

    item_id: UUID
    group_key: UUID | None = None
    group_sequence: int | None = None

    def normalized(self) -> SchedulingOccurrenceInput:
        """Require one source identifier and a coherent optional group pair.

        Returns
        -------
        SchedulingOccurrenceInput
            Validated occurrence intent.

        Raises
        ------
        ValidationError
            If grouping fields are inconsistent or the sequence exceeds its bound.
        """
        require_identifier(self.item_id)
        if self.group_key is None:
            if self.group_sequence is not None:
                raise ValidationError("A group sequence requires an explicit group.")
        else:
            require_identifier(self.group_key)
            if (
                type(self.group_sequence) is not int
                or not 1 <= self.group_sequence <= MAX_OCCURRENCES
            ):
                raise ValidationError("Supply a positive bounded group sequence.")
        return self


@dataclass(frozen=True, slots=True)
class SchedulingPlacementInput:
    """Complete occurrence placement intent, independent of room or host approval.

    Attributes
    ----------
    occurrence_id
        Stable Scheduling occurrence.
    occurrence_version
        Exact current occurrence metadata version.
    day_id
        Explicit Scheduling service day.
    day_version
        Exact current service-day version.
    space_selection_id
        Exact Venue-owned selection resolved independently.
    envelope
        Preparation, effective delivery and teardown occupancy.
    capacity_mode
        Seated, standing or table capacity to evaluate.
    expected_attendance
        Explicit positive bounded planning estimate, not Registration evidence.
    host_presences
        Complete selected host purposes and required presence intervals.
    """

    occurrence_id: UUID
    occurrence_version: int
    day_id: UUID
    day_version: int
    space_selection_id: UUID
    envelope: SchedulingEnvelope
    capacity_mode: str
    expected_attendance: int
    host_presences: tuple[SchedulingHostPresence, ...] = ()

    def normalized(self) -> SchedulingPlacementInput:
        """Validate structural intent while leaving dependency conflicts explainable.

        Returns
        -------
        SchedulingPlacementInput
            Frozen normalized placement with canonical host ordering.

        Raises
        ------
        ValidationError
            If the capacity mode or attendance estimate is outside its closed bound.
        """
        for value in (self.occurrence_id, self.day_id, self.space_selection_id):
            require_identifier(value)
        require_version(self.occurrence_version)
        require_version(self.day_version)
        envelope = normalize_scheduling_envelope(self.envelope)
        if type(self.capacity_mode) is not str or self.capacity_mode not in {
            "seated",
            "standing",
            "table",
        }:
            raise ValidationError("Use a closed Scheduling capacity mode.")
        if (
            type(self.expected_attendance) is not int
            or not 1 <= self.expected_attendance <= 2**31 - 1
        ):
            raise ValidationError("Supply a positive bounded attendance estimate.")
        return SchedulingPlacementInput(
            self.occurrence_id,
            self.occurrence_version,
            self.day_id,
            self.day_version,
            self.space_selection_id,
            envelope,
            self.capacity_mode,
            self.expected_attendance,
            normalize_host_presences(self.host_presences, envelope=envelope),
        )
