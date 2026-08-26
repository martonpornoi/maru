"""Bounded organizer and person-owned projections for Workforce Shifts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.identity.queries import account_display_labels
from maru.workforce.availability_inputs import MAX_AVAILABILITY_WINDOWS
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PersonAvailabilityWindow,
    PositionAssignment,
    ShiftCommitment,
    ShiftDemand,
)

if TYPE_CHECKING:
    from uuid import UUID

MAX_SHIFT_DEMANDS = 1_024
MAX_SHIFT_COMMITMENTS = 4_096
SHIFT_ORGANIZER_REQUIRED_FIELDS = frozenset(
    {
        "shift_demands",
        "coverage_states",
        "holder_display_labels",
        "suitability_consequences",
    }
)


class ShiftReadLimitExceededError(RuntimeError):
    """Signal that a complete Shift projection exceeded a safe bound."""


class ShiftProjectionIntegrityError(RuntimeError):
    """Signal inconsistent demand, commitment, or snapshot evidence."""


@dataclass(frozen=True, slots=True)
class OrganizerShiftCommitmentItem:
    """One minimized commitment row in an authorized coverage projection.

    Attributes
    ----------
    commitment : ShiftCommitment
        Retained governed commitment.
    account_label : str
        Operational display label released after authorization.
    availability_current : bool
        Whether current submitted Availability still covers the snapshot.
    qualification_current : bool
        Whether the exact Position assignment still spans the work.
    """

    commitment: ShiftCommitment
    account_label: str
    availability_current: bool
    qualification_current: bool

    @property
    def needs_confirmation_review(self) -> bool:
        """Return whether an open planner should confirm or refresh this row."""
        return bool(
            self.commitment.status == ShiftCommitment.Status.CLAIMED
            or (
                self.commitment.status == ShiftCommitment.Status.CONFIRMED
                and (not self.availability_current or not self.qualification_current)
            )
        )


@dataclass(frozen=True, slots=True)
class OrganizerShiftDemandItem:
    """One Shift demand with complete bounded coverage counts and people.

    Attributes
    ----------
    demand : ShiftDemand
        Governed demand aggregate.
    department_name : str
        Current operational Department label.
    position_title : str
        Current operational Position label.
    claimed_count : int
        Active claims awaiting organizer confirmation.
    confirmed_count : int
        Active independently confirmed commitments.
    active_count : int
        Combined active claims and confirmations consuming capacity.
    remaining_count : int
        Non-negative capacity still available.
    commitments : tuple[OrganizerShiftCommitmentItem, ...]
        Complete bounded retained coverage rows for the demand.
    """

    demand: ShiftDemand
    department_name: str
    position_title: str
    claimed_count: int
    confirmed_count: int
    active_count: int
    remaining_count: int
    commitments: tuple[OrganizerShiftCommitmentItem, ...]


@dataclass(frozen=True, slots=True)
class OrganizerShiftOverview:
    """Complete exact-edition Shift-planning projection.

    Attributes
    ----------
    demands : tuple[OrganizerShiftDemandItem, ...]
        Stable complete demand collection.
    open_count : int
        Number of demands accepting claims.
    locked_count : int
        Number of demands with frozen coverage.
    attention_count : int
        Open demands with claims, stale evidence, or remaining capacity.
    """

    demands: tuple[OrganizerShiftDemandItem, ...]
    open_count: int
    locked_count: int
    attention_count: int


@dataclass(frozen=True, slots=True)
class SuitableShiftItem:
    """One open Shift the current person may claim now.

    Attributes
    ----------
    demand : ShiftDemand
        Open demand that passed current suitability checks.
    department_name : str
        Operational Department label.
    position_title : str
        Exact assigned Position label.
    preference : str
        Covering Availability preference code used only for ordering.
    preference_label : str
        Human-readable Availability consequence.
    remaining_count : int
        Capacity available when the projection was evaluated.
    """

    demand: ShiftDemand
    department_name: str
    position_title: str
    preference: str
    preference_label: str
    remaining_count: int


@dataclass(frozen=True, slots=True)
class MyShiftCommitmentItem:
    """One current or retained commitment visible only to its owner.

    Attributes
    ----------
    commitment : ShiftCommitment
        Person-owned retained commitment aggregate.
    demand : ShiftDemand
        Operational Shift instructions retained by the commitment.
    department_name : str
        Operational Department label.
    position_title : str
        Position label attached to the work.
    availability_current : bool
        Whether current submitted Availability still covers the work.
    qualification_current : bool
        Whether the exact Position assignment still spans the work.
    can_withdraw : bool
        Whether planning is open and self-withdrawal is currently permitted.
    """

    commitment: ShiftCommitment
    demand: ShiftDemand
    department_name: str
    position_title: str
    availability_current: bool
    qualification_current: bool
    can_withdraw: bool


@dataclass(frozen=True, slots=True)
class MyShiftOverview:
    """One person's suitable open work and retained commitments.

    Attributes
    ----------
    suitable : tuple[SuitableShiftItem, ...]
        Open work the person may claim at projection time.
    commitments : tuple[MyShiftCommitmentItem, ...]
        Current and historical commitments visible to their owner.
    """

    suitable: tuple[SuitableShiftItem, ...]
    commitments: tuple[MyShiftCommitmentItem, ...]


@dataclass(frozen=True, slots=True)
class MyShiftScopeItem:
    """One personal Shifts continuation shown on the My Workforce home.

    Attributes
    ----------
    organization_slug : str
        Organization route locator.
    series_slug : str
        Convention-series route locator.
    edition_slug : str
        Exact event-edition route locator.
    organization_name : str
        Human-readable related organization.
    edition_name : str
        Human-readable related edition.
    open_suitable_count : int
        Number of currently claimable Shifts.
    active_commitment_count : int
        Number of current Claims and Confirmations.
    """

    organization_slug: str
    series_slug: str
    edition_slug: str
    organization_name: str
    edition_name: str
    open_suitable_count: int
    active_commitment_count: int


def person_has_shift_relationship(
    *, account: Account, organization_id: UUID, edition_id: UUID
) -> bool:
    """Return whether a person has Workforce eligibility or Shift history.

    Parameters
    ----------
    account : Account
        Candidate person account.
    organization_id : UUID
        Exact organization scope.
    edition_id : UUID
        Exact edition scope.

    Returns
    -------
    bool
        Whether the person has an Assignment or retained Shift commitment.
    """
    if account.pk is None or account.account_kind != Account.Kind.PERSON:
        return False
    return (
        PositionAssignment.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=account.id,
        ).exists()
        or ShiftCommitment.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=account.id,
        ).exists()
    )


def _availability_is_current(commitment: ShiftCommitment) -> bool:
    plan = commitment.availability_plan
    return bool(
        plan.status == PersonAvailabilityPlan.Status.SUBMITTED
        and plan.command_version == commitment.availability_version
        and getattr(commitment, "availability_covers_snapshot", False)
    )


def _with_availability_coverage(
    queryset: models.QuerySet[ShiftCommitment],
) -> models.QuerySet[ShiftCommitment]:
    """Annotate one bounded commitment query with current covering evidence.

    Parameters
    ----------
    queryset : models.QuerySet[ShiftCommitment]
        Commitment query to annotate without evaluating it.

    Returns
    -------
    models.QuerySet[ShiftCommitment]
        Query annotated with ``availability_covers_snapshot``.
    """
    covering_window = PersonAvailabilityWindow.objects.filter(
        plan_id=models.OuterRef("availability_plan_id"),
        created_by_version=models.OuterRef("availability_version"),
        starts_at__lte=models.OuterRef("starts_at"),
        ends_at__gte=models.OuterRef("ends_at"),
    )
    return queryset.annotate(
        availability_covers_snapshot=models.Exists(covering_window)
    )


def _qualification_is_current(commitment: ShiftCommitment) -> bool:
    assignment = commitment.position_assignment
    return bool(
        assignment.status == PositionAssignment.Status.ACTIVE
        and assignment.position_id == commitment.demand.position_id
        and assignment.effective_from <= commitment.starts_at
        and (
            assignment.expires_at is None or assignment.expires_at >= commitment.ends_at
        )
    )


def load_organizer_shift_overview(*, edition: EventEdition) -> OrganizerShiftOverview:
    """Return all Shift demand and coverage for one authorized exact edition.

    Parameters
    ----------
    edition : EventEdition
        Already scoped and authorized exact edition.

    Returns
    -------
    OrganizerShiftOverview
        Complete bounded demand, coverage, and attention projection.

    Raises
    ------
    ShiftReadLimitExceededError
        If demand or commitment volume exceeds a complete-projection ceiling.
    ShiftProjectionIntegrityError
        If retained commitment snapshots do not match their demand.
    """
    demands = tuple(
        ShiftDemand.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        .select_related("position", "position__department")
        .order_by("starts_at", "title", "id")[: MAX_SHIFT_DEMANDS + 1]
    )
    if len(demands) > MAX_SHIFT_DEMANDS:
        raise ShiftReadLimitExceededError
    demand_ids = tuple(item.id for item in demands)
    commitments = tuple(
        _with_availability_coverage(
            ShiftCommitment.objects.filter(demand_id__in=demand_ids)
        )
        .select_related(
            "demand",
            "demand__position",
            "position_assignment",
            "availability_plan",
        )
        .order_by("demand_id", "claimed_at", "id")[: MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(commitments) > MAX_SHIFT_COMMITMENTS:
        raise ShiftReadLimitExceededError
    if any(
        item.starts_at != item.demand.starts_at
        or item.ends_at != item.demand.ends_at
        or item.organization_id != edition.organization_id
        or item.edition_id != edition.id
        for item in commitments
    ):
        raise ShiftProjectionIntegrityError
    labels = account_display_labels(tuple({item.account_id for item in commitments}))
    grouped: dict[UUID, list[ShiftCommitment]] = {item.id: [] for item in demands}
    for commitment in commitments:
        grouped[commitment.demand_id].append(commitment)
    items: list[OrganizerShiftDemandItem] = []
    attention_count = 0
    for demand in demands:
        rows = grouped[demand.id]
        active = tuple(
            item
            for item in rows
            if item.status
            in (ShiftCommitment.Status.CLAIMED, ShiftCommitment.Status.CONFIRMED)
        )
        claimed_count = sum(
            item.status == ShiftCommitment.Status.CLAIMED for item in active
        )
        confirmed_count = sum(
            item.status == ShiftCommitment.Status.CONFIRMED for item in active
        )
        projected_rows = tuple(
            OrganizerShiftCommitmentItem(
                commitment=item,
                account_label=labels[item.account_id],
                availability_current=(
                    _availability_is_current(item)
                    if item.status
                    in (
                        ShiftCommitment.Status.CLAIMED,
                        ShiftCommitment.Status.CONFIRMED,
                    )
                    else False
                ),
                qualification_current=(
                    _qualification_is_current(item)
                    if item.status
                    in (
                        ShiftCommitment.Status.CLAIMED,
                        ShiftCommitment.Status.CONFIRMED,
                    )
                    else False
                ),
            )
            for item in rows
        )
        if demand.status == ShiftDemand.Status.OPEN and (
            len(active) < demand.required_headcount
            or claimed_count > 0
            or any(
                not row.availability_current or not row.qualification_current
                for row in projected_rows
                if row.commitment.status
                in (
                    ShiftCommitment.Status.CLAIMED,
                    ShiftCommitment.Status.CONFIRMED,
                )
            )
        ):
            attention_count += 1
        items.append(
            OrganizerShiftDemandItem(
                demand=demand,
                department_name=demand.position.department.name,
                position_title=demand.position.title,
                claimed_count=claimed_count,
                confirmed_count=confirmed_count,
                active_count=len(active),
                remaining_count=max(0, demand.required_headcount - len(active)),
                commitments=projected_rows,
            )
        )
    return OrganizerShiftOverview(
        demands=tuple(items),
        open_count=sum(item.status == ShiftDemand.Status.OPEN for item in demands),
        locked_count=sum(item.status == ShiftDemand.Status.LOCKED for item in demands),
        attention_count=attention_count,
    )


def _covering_preference(
    *, windows: tuple[PersonAvailabilityWindow, ...], demand: ShiftDemand
) -> str | None:
    for window in windows:
        if window.starts_at <= demand.starts_at and window.ends_at >= demand.ends_at:
            return window.preference
    return None


def load_my_shift_overview(
    *, account: Account, edition: EventEdition
) -> MyShiftOverview:
    """Return suitable open work and retained commitments for one person.

    Parameters
    ----------
    account : Account
        Authenticated person whose work is projected.
    edition : EventEdition
        Exact related edition.

    Returns
    -------
    MyShiftOverview
        Suitable open demand and the person's retained commitment history.

    Raises
    ------
    ShiftReadLimitExceededError
        If a complete personal projection exceeds a code-owned ceiling.
    """
    evaluated_at = timezone.now()
    assignments = tuple(
        PositionAssignment.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            account=account,
            status=PositionAssignment.Status.ACTIVE,
        )
        .select_related("position")
        .order_by("position_id", "id")[: MAX_SHIFT_DEMANDS + 1]
    )
    if len(assignments) > MAX_SHIFT_DEMANDS:
        raise ShiftReadLimitExceededError
    assignment_by_position = {item.position_id: item for item in assignments}
    demands = tuple(
        ShiftDemand.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            position_id__in=tuple(assignment_by_position),
            status=ShiftDemand.Status.OPEN,
            ends_at__gt=evaluated_at,
        )
        .select_related("position", "position__department")
        .order_by("starts_at", "title", "id")[: MAX_SHIFT_DEMANDS + 1]
    )
    if len(demands) > MAX_SHIFT_DEMANDS:
        raise ShiftReadLimitExceededError
    commitments = tuple(
        _with_availability_coverage(
            ShiftCommitment.objects.filter(
                organization_id=edition.organization_id,
                edition_id=edition.id,
                account=account,
            )
        )
        .select_related(
            "demand",
            "demand__position",
            "demand__position__department",
            "position_assignment",
            "availability_plan",
        )
        .order_by("starts_at", "id")[: MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(commitments) > MAX_SHIFT_COMMITMENTS:
        raise ShiftReadLimitExceededError
    active_commitments = tuple(
        item
        for item in commitments
        if item.status
        in (ShiftCommitment.Status.CLAIMED, ShiftCommitment.Status.CONFIRMED)
    )
    active_demand_ids = {item.demand_id for item in active_commitments}
    plan = (
        PersonAvailabilityPlan.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            account=account,
        )
        .order_by()
        .first()
    )
    availability_windows: tuple[PersonAvailabilityWindow, ...] = ()
    if plan is not None and plan.status == PersonAvailabilityPlan.Status.SUBMITTED:
        availability_windows = tuple(
            PersonAvailabilityWindow.objects.filter(
                plan=plan,
                created_by_version=plan.command_version,
            ).order_by("preference", "starts_at", "id")[: MAX_AVAILABILITY_WINDOWS + 1]
        )
        if len(availability_windows) > MAX_AVAILABILITY_WINDOWS:
            raise ShiftReadLimitExceededError
    capacity_counts = {
        row["demand_id"]: row["count"]
        for row in ShiftCommitment.objects.filter(
            demand_id__in=tuple(item.id for item in demands),
            status__in=(
                ShiftCommitment.Status.CLAIMED,
                ShiftCommitment.Status.CONFIRMED,
            ),
        )
        .values("demand_id")
        .annotate(count=models.Count("id"))
    }
    suitable: list[SuitableShiftItem] = []
    for demand in demands:
        if demand.id in active_demand_ids:
            continue
        assignment = assignment_by_position.get(demand.position_id)
        if (
            assignment is None
            or assignment.effective_from > demand.starts_at
            or (
                assignment.expires_at is not None
                and assignment.expires_at < demand.ends_at
            )
        ):
            continue
        active_count = int(capacity_counts.get(demand.id, 0))
        if active_count >= demand.required_headcount:
            continue
        preference = _covering_preference(
            windows=availability_windows,
            demand=demand,
        )
        if preference is None:
            continue
        rest_end = demand.ends_at + timedelta(minutes=demand.minimum_rest_minutes)
        conflicts = any(
            item.starts_at < rest_end and item.rest_ends_at > demand.starts_at
            for item in active_commitments
        )
        if conflicts:
            continue
        suitable.append(
            SuitableShiftItem(
                demand=demand,
                department_name=demand.position.department.name,
                position_title=demand.position.title,
                preference=preference,
                preference_label=(
                    "Preferred time" if preference == "preferred" else "Available time"
                ),
                remaining_count=demand.required_headcount - active_count,
            )
        )
    suitable.sort(
        key=lambda item: (
            0 if item.preference == "preferred" else 1,
            item.demand.starts_at,
            item.demand.title.casefold(),
            str(item.demand.id),
        )
    )
    personal_commitments = tuple(
        MyShiftCommitmentItem(
            commitment=item,
            demand=item.demand,
            department_name=item.demand.position.department.name,
            position_title=item.demand.position.title,
            availability_current=(
                _availability_is_current(item)
                if item.status
                in (ShiftCommitment.Status.CLAIMED, ShiftCommitment.Status.CONFIRMED)
                else False
            ),
            qualification_current=(
                _qualification_is_current(item)
                if item.status
                in (ShiftCommitment.Status.CLAIMED, ShiftCommitment.Status.CONFIRMED)
                else False
            ),
            can_withdraw=(
                item.status
                in (ShiftCommitment.Status.CLAIMED, ShiftCommitment.Status.CONFIRMED)
                and item.demand.status == ShiftDemand.Status.OPEN
            ),
        )
        for item in commitments
    )
    return MyShiftOverview(
        suitable=tuple(suitable),
        commitments=personal_commitments,
    )


def my_shift_scope_items(
    *,
    account: Account,
    permitted_scopes: frozenset[tuple[UUID, UUID]],
) -> tuple[MyShiftScopeItem, ...]:
    """Return personal Shifts continuations for permitted related editions.

    Parameters
    ----------
    account : Account
        Authenticated person whose continuations are requested.
    permitted_scopes : frozenset[tuple[UUID, UUID]]
        Exact organization and edition pairs already permitted for My Workforce.

    Returns
    -------
    tuple[MyShiftScopeItem, ...]
        Stable purpose-oriented Shift continuations with current counts.
    """
    items: list[MyShiftScopeItem] = []
    for organization_id, edition_id in sorted(
        permitted_scopes,
        key=lambda scope: (str(scope[0]), str(scope[1])),
    ):
        edition = (
            EventEdition.objects.select_related("organization", "series")
            .filter(
                id=edition_id,
                organization_id=organization_id,
            )
            .order_by()
            .first()
        )
        if edition is None or not person_has_shift_relationship(
            account=account,
            organization_id=organization_id,
            edition_id=edition_id,
        ):
            continue
        overview = load_my_shift_overview(account=account, edition=edition)
        items.append(
            MyShiftScopeItem(
                organization_slug=edition.organization.slug,
                series_slug=edition.series.slug,
                edition_slug=edition.slug,
                organization_name=edition.organization.name,
                edition_name=edition.name,
                open_suitable_count=len(overview.suitable),
                active_commitment_count=sum(
                    item.commitment.status
                    in (
                        ShiftCommitment.Status.CLAIMED,
                        ShiftCommitment.Status.CONFIRMED,
                    )
                    for item in overview.commitments
                ),
            )
        )
    return tuple(
        sorted(
            items,
            key=lambda item: (item.edition_name.casefold(), item.organization_name),
            reverse=True,
        )
    )
