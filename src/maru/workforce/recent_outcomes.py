"""Bounded current-receipt facts for the separately admitted Home component."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

from django.db import models
from django.utils import timezone

from maru.workforce.models import ShiftDemand, ShiftDemandCommandReceipt
from maru.workforce.shift_queries import MAX_SHIFT_DEMANDS

if TYPE_CHECKING:
    from uuid import UUID

MAX_RECENT_OUTCOME_CANDIDATES = 128
MAX_RECENT_OUTCOMES = 5
RECENT_OUTCOME_HORIZON = timedelta(days=7)
RECENT_OUTCOME_RELEASE_SECONDS = 5.0
RECENT_OUTCOME_STATEMENT_MILLISECONDS = 1_000
_OUTCOMES = frozenset({"locked", "completed", "cancelled"})
Outcome = Literal["locked", "completed", "cancelled"]


class RecentOutcomesUnavailableError(RuntimeError):
    """Complete current evidence cannot be released within the fixed bounds."""


@dataclass(frozen=True, slots=True)
class RecentShiftOutcome:
    """One current authorized label and retained closed outcome.

    Attributes
    ----------
    demand_id, label
        Exact ordinary destination identity and current readable Shift title.
    outcome, recorded_at
        Closed command outcome and its immutable aware receipt time.
    """

    demand_id: UUID
    label: str
    outcome: Outcome
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class RecentShiftOutcomes:
    """An optional request-local component, independent of next-step priority.

    Attributes
    ----------
    state
        Present, empty or generic unavailable; denial omits this object entirely.
    items
        At most five minimized distinct Shift outcomes, with no people or reasons.
    checked_at, time_zone
        Final source check instant and authorized edition display zone.
    """

    state: Literal["present", "empty", "unavailable"]
    items: tuple[RecentShiftOutcome, ...] = ()
    checked_at: datetime | None = None
    time_zone: str = "UTC"


@dataclass(frozen=True, slots=True)
class OutcomeCandidate:
    """Minimal exact-version metadata, never itself a shell projection.

    Attributes
    ----------
    demand_id, version, status
        Current scoped parent identity, positive command version and state.
    receipt_id, organization_id, edition_id
        Matching unique-version receipt identity and its exact recorded scope.
    action, resulting_status, recorded_at
        Closed receipt result and immutable aware recording instant.
    """

    demand_id: UUID
    version: int
    status: str
    receipt_id: UUID | None
    organization_id: UUID | None
    edition_id: UUID | None
    action: str | None
    resulting_status: str | None
    recorded_at: datetime | None


@dataclass(frozen=True, slots=True)
class RecentOutcomeFacts:
    """Complete bounded signature material and its inclusive-window expiry.

    Attributes
    ----------
    items
        Only selected current labels, never lazy models or raw receipts.
    signature
        Complete parent/cohort/selected-label facts for repeated owner fencing.
    valid_until
        Earliest candidate's inclusive seven-day boundary, if any.
    """

    items: tuple[RecentShiftOutcome, ...]
    signature: object
    valid_until: datetime | None


def select_outcome_candidates(
    rows: tuple[OutcomeCandidate, ...],
    *,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime,
) -> tuple[OutcomeCandidate, ...]:
    """Validate the whole candidate cohort before deterministic five-row selection.

    Parameters
    ----------
    rows : tuple[OutcomeCandidate, ...]
        Complete horizon or inconsistent-evidence cohort, including overflow row.
    organization_id : UUID
        Independently admitted organization.
    edition_id : UUID
        Independently admitted exact owner scope.
    at : datetime
        Trusted aware UTC-comparable check instant.

    Returns
    -------
    tuple[OutcomeCandidate, ...]
        Valid distinct candidates in descending time, receipt and demand order.

    Raises
    ------
    RecentOutcomesUnavailableError
        On overflow, duplicate, missing, incoherent or future evidence.
    """
    if timezone.is_naive(at) or len(rows) > MAX_RECENT_OUTCOME_CANDIDATES:
        raise RecentOutcomesUnavailableError
    at = at.astimezone(UTC)
    seen: set[UUID] = set()
    for row in rows:
        if (
            row.demand_id in seen
            or row.version < 1
            or row.status not in _OUTCOMES
            or row.receipt_id is None
            or row.organization_id != organization_id
            or row.edition_id != edition_id
            or row.action != row.status
            or row.resulting_status != row.status
            or row.recorded_at is None
            or timezone.is_naive(row.recorded_at)
            or not at - RECENT_OUTCOME_HORIZON <= row.recorded_at.astimezone(UTC) <= at
        ):
            raise RecentOutcomesUnavailableError
        seen.add(row.demand_id)
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                cast("datetime", row.recorded_at).astimezone(UTC),
                row.receipt_id,
                row.demand_id,
            ),
            reverse=True,
        )
    )


def read_recent_outcome_facts(
    *, organization_id: UUID, edition_id: UUID, at: datetime
) -> RecentOutcomeFacts:
    """Read bounded parents, exact-index receipts and only five current labels.

    Parameters
    ----------
    organization_id : UUID
        Independently admitted organization.
    edition_id : UUID
        Exact scope already admitted by the owner inside its coherent snapshot.
    at : datetime
        Trusted aware instant defining the inclusive seven-day UTC horizon.

    Returns
    -------
    RecentOutcomeFacts
        Complete bounded signature, minimized rows and next window boundary.

    Raises
    ------
    RecentOutcomesUnavailableError
        If complete coherent metadata or selected labels cannot be established.
    """
    if timezone.is_naive(at):
        raise RecentOutcomesUnavailableError
    at = at.astimezone(UTC)
    demands = ShiftDemand.objects.filter(
        organization_id=organization_id, edition_id=edition_id
    )
    parents = tuple(
        demands.order_by("id").values_list("id", "command_version", "status")[
            : MAX_SHIFT_DEMANDS + 1
        ]
    )
    if len(parents) > MAX_SHIFT_DEMANDS or any(
        version < 1 or status not in ShiftDemand.Status.values
        for _identity, version, status in parents
    ):
        raise RecentOutcomesUnavailableError
    # The existing (demand, resulting_version) unique index makes these point
    # probes, not scans of retained history. Do not scope the subquery away:
    # mismatched receipt scope must be detected rather than silently discarded.
    receipt = ShiftDemandCommandReceipt.objects.filter(
        demand_id=models.OuterRef("id"),
        resulting_version=models.OuterRef("command_version"),
    ).order_by()
    fields = {
        "receipt_id": "id",
        "receipt_organization": "organization_id",
        "receipt_edition": "edition_id",
        "receipt_action": "action",
        "receipt_status": "resulting_status",
        "receipt_time": "created_at",
    }
    current = demands.filter(
        id__in=[identity for identity, _version, _status in parents],
        status__in=_OUTCOMES,
    ).annotate(
        **{
            name: models.Subquery(receipt.values(field)[:1])
            for name, field in fields.items()
        }
    )
    candidates = tuple(
        OutcomeCandidate(*row)
        for row in current.filter(
            models.Q(receipt_time__gte=at - RECENT_OUTCOME_HORIZON)
            | models.Q(receipt_time__isnull=True)
            | ~models.Q(receipt_organization=organization_id)
            | ~models.Q(receipt_edition=edition_id)
            | ~models.Q(receipt_action=models.F("status"))
            | ~models.Q(receipt_status=models.F("status"))
        )
        .order_by("id")
        .values_list("id", "command_version", "status", *fields)[
            : MAX_RECENT_OUTCOME_CANDIDATES + 1
        ]
    )
    ordered = select_outcome_candidates(
        candidates, organization_id=organization_id, edition_id=edition_id, at=at
    )
    selected = ordered[:MAX_RECENT_OUTCOMES]
    labels = tuple(
        demands.filter(id__in=[row.demand_id for row in selected])
        .order_by("id")
        .values_list("id", "command_version", "status", "title")[:MAX_RECENT_OUTCOMES]
    )
    by_id = {
        identity: (version, status, title)
        for identity, version, status, title in labels
    }
    if len(by_id) != len(selected) or any(
        by_id.get(row.demand_id, ())[:2] != (row.version, row.status)
        for row in selected
    ):
        raise RecentOutcomesUnavailableError
    items = tuple(
        RecentShiftOutcome(
            row.demand_id,
            by_id[row.demand_id][2],
            cast("Outcome", row.status),
            cast("datetime", row.recorded_at),
        )
        for row in selected
    )
    return RecentOutcomeFacts(
        items,
        (parents, candidates, labels),
        min(
            (
                row.recorded_at + RECENT_OUTCOME_HORIZON
                for row in ordered
                if row.recorded_at is not None
            ),
            default=None,
        ),
    )
