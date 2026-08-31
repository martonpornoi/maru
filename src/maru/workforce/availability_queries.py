"""Bounded personal and organizer projections for Workforce availability."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.db import models

from maru.events.queries import adoption_profile_filter_for_adapter
from maru.identity.models import Account
from maru.identity.queries import account_display_labels
from maru.workforce.adoption import WORKFORCE_SELF_ADAPTER
from maru.workforce.availability_inputs import MAX_AVAILABILITY_WINDOWS
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PersonAvailabilityWindow,
    PositionAssignment,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.events.models import EventEdition

MAX_AVAILABILITY_PEOPLE = 1_024
MAX_AVAILABILITY_ASSIGNMENTS = 4_096
MAX_AVAILABILITY_TOTAL_WINDOWS = MAX_AVAILABILITY_PEOPLE * MAX_AVAILABILITY_WINDOWS
AVAILABILITY_ORGANIZER_REQUIRED_FIELDS = frozenset(
    {
        "availability_consequences",
        "availability_windows",
        "holder_display_labels",
    }
)


class AvailabilityReadLimitExceededError(RuntimeError):
    """Signal that a complete availability projection exceeded a safe bound."""


class AvailabilityProjectionIntegrityError(RuntimeError):
    """Signal inconsistent plan metadata or current-period evidence."""


@dataclass(frozen=True, slots=True)
class AvailabilityWindowProjection:
    """One exact current interval rendered in the edition's time zone.

    Attributes
    ----------
    starts_at
        Inclusive aware start localized for presentation.
    ends_at
        Exclusive aware end localized for presentation.
    preference
        Stable ``available`` or ``preferred`` code.
    preference_label
        Human-readable planning signal.
    """

    starts_at: datetime
    ends_at: datetime
    preference: str
    preference_label: str


@dataclass(frozen=True, slots=True)
class PersonAvailabilityProjection:
    """One owner's current plan without command fingerprints or history.

    Attributes
    ----------
    plan
        Current plan row, or ``None`` when the person has never saved one.
    state
        Person-facing stable state code.
    state_label
        Plain-language current consequence.
    windows
        Current periods; draft periods are returned only to their owner.
    """

    plan: PersonAvailabilityPlan | None
    state: str
    state_label: str
    windows: tuple[AvailabilityWindowProjection, ...]

    @property
    def version(self) -> int:
        """Return zero for an absent plan or its optimistic current version."""
        return self.plan.command_version if self.plan is not None else 0


@dataclass(frozen=True, slots=True)
class MyAvailabilityScopeItem:
    """One exact-edition continuation shown on My Workforce.

    Attributes
    ----------
    organization_slug
        Human URL locator for the owning organization.
    series_slug
        Human URL locator for the convention series.
    edition_slug
        Human URL locator for the exact edition.
    organization_name
        Owning organization label.
    edition_name
        Exact edition label.
    time_zone
        Edition IANA time zone.
    position_titles
        Current proposed or active responsibilities in the edition.
    state_label
        Person-facing plan consequence.
    can_edit
        Whether a current open assignment permits a replacement.
    """

    organization_slug: str
    series_slug: str
    edition_slug: str
    organization_name: str
    edition_name: str
    time_zone: str
    position_titles: tuple[str, ...]
    state_label: str
    can_edit: bool


@dataclass(frozen=True, slots=True)
class OrganizerAvailabilityPosition:
    """One minimized open responsibility attached to an organizer row.

    Attributes
    ----------
    department_name
        Operational Department containing the Position.
    position_title
        Current human Position title.
    assignment_status
        Current proposed or active relationship state.
    """

    department_name: str
    position_title: str
    assignment_status: str


@dataclass(frozen=True, slots=True)
class OrganizerAvailabilityItem:
    """One open-assignment person and their shared planning consequence.

    Attributes
    ----------
    account_id
        Stable person identifier used only inside the authorized projection.
    account_label
        Minimized current display label.
    positions
        Complete current open responsibilities in the edition.
    state
        Machine-readable organizer consequence.
    state_label
        Human-readable organizer consequence.
    shared_at
        Current submission time when a statement is shared.
    windows
        Current submitted periods; never private draft periods.
    """

    account_id: UUID
    account_label: str
    positions: tuple[OrganizerAvailabilityPosition, ...]
    state: str
    state_label: str
    shared_at: datetime | None
    windows: tuple[AvailabilityWindowProjection, ...]


@dataclass(frozen=True, slots=True)
class OrganizerAvailabilityOverview:
    """Complete bounded exact-edition organizer availability projection.

    Attributes
    ----------
    people
        Stable person rows for every open assignment owner.
    shared_count
        People who shared one or more current periods.
    unavailable_count
        People who submitted an explicit empty complete set.
    not_shared_count
        People with either no plan or a private draft.
    withdrawn_count
        People whose latest statement is withdrawn.
    """

    people: tuple[OrganizerAvailabilityItem, ...]
    shared_count: int
    unavailable_count: int
    not_shared_count: int
    withdrawn_count: int


def person_has_availability_relationship(
    *, account: Account, organization_id: UUID, edition_id: UUID
) -> bool:
    """Return whether a person has Workforce history or a plan in this scope.

    Parameters
    ----------
    account : Account
        Authenticated person whose relationship is checked.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact event edition.

    Returns
    -------
    bool
        ``True`` for retained assignment history or an owned plan.
    """
    if account.pk is None or account.account_kind != Account.Kind.PERSON:
        return False
    return (
        PositionAssignment.objects.filter(
            adoption_profile_filter_for_adapter(
                WORKFORCE_SELF_ADAPTER,
                field_prefix="edition",
            ),
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=account.id,
        ).exists()
        or PersonAvailabilityPlan.objects.filter(
            adoption_profile_filter_for_adapter(
                WORKFORCE_SELF_ADAPTER,
                field_prefix="edition",
            ),
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=account.id,
        ).exists()
    )


def person_can_edit_availability(
    *, account: Account, organization_id: UUID, edition_id: UUID
) -> bool:
    """Return whether a proposed or active assignment permits a new statement.

    Parameters
    ----------
    account : Account
        Authenticated person whose open relationship is checked.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact event edition.

    Returns
    -------
    bool
        ``True`` when at least one exact-edition assignment remains open.
    """
    return PositionAssignment.objects.filter(
        adoption_profile_filter_for_adapter(
            WORKFORCE_SELF_ADAPTER,
            field_prefix="edition",
        ),
        organization_id=organization_id,
        edition_id=edition_id,
        account_id=account.id,
        status__in=(
            PositionAssignment.Status.PROPOSED,
            PositionAssignment.Status.ACTIVE,
        ),
    ).exists()


def _window_projection(
    *, window: PersonAvailabilityWindow, zone: ZoneInfo
) -> AvailabilityWindowProjection:
    return AvailabilityWindowProjection(
        starts_at=window.starts_at.astimezone(zone),
        ends_at=window.ends_at.astimezone(zone),
        preference=window.preference,
        preference_label=window.get_preference_display(),
    )


def _validated_plan_windows(
    *, plan: PersonAvailabilityPlan, expose_draft: bool
) -> tuple[AvailabilityWindowProjection, ...]:
    rows = tuple(
        PersonAvailabilityWindow.objects.filter(plan=plan).order_by(
            "starts_at", "ends_at", "id"
        )[: MAX_AVAILABILITY_WINDOWS + 1]
    )
    if len(rows) > MAX_AVAILABILITY_WINDOWS:
        raise AvailabilityReadLimitExceededError
    if len(rows) != plan.window_count or any(
        row.created_by_version != plan.command_version for row in rows
    ):
        raise AvailabilityProjectionIntegrityError
    if plan.status == PersonAvailabilityPlan.Status.WITHDRAWN and rows:
        raise AvailabilityProjectionIntegrityError
    if plan.status == PersonAvailabilityPlan.Status.DRAFT and not expose_draft:
        return ()
    zone = ZoneInfo(plan.time_zone)
    return tuple(_window_projection(window=row, zone=zone) for row in rows)


def load_person_availability(
    *,
    account: Account,
    organization_id: UUID,
    edition_id: UUID,
) -> PersonAvailabilityProjection:
    """Load one owner's current plan and exact current periods.

    Parameters
    ----------
    account : Account
        Authenticated plan owner.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact event edition.

    Returns
    -------
    PersonAvailabilityProjection
        Current owner-visible plan, including private draft periods.
    """
    plan = (
        PersonAvailabilityPlan.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            account_id=account.id,
        )
        .order_by()
        .first()
    )
    if plan is None:
        return PersonAvailabilityProjection(
            plan=None,
            state="not_started",
            state_label="Not started",
            windows=(),
        )
    windows = _validated_plan_windows(plan=plan, expose_draft=True)
    if plan.status == PersonAvailabilityPlan.Status.SUBMITTED:
        state = "shared" if windows else "unavailable"
        state_label = (
            "Shared with organizers" if windows else "Not available for this edition"
        )
    elif plan.status == PersonAvailabilityPlan.Status.DRAFT:
        state = "draft"
        state_label = "Private draft"
    else:
        state = "withdrawn"
        state_label = "Withdrawn"
    return PersonAvailabilityProjection(
        plan=plan,
        state=state,
        state_label=state_label,
        windows=windows,
    )


def _scope_filter(
    permitted_scopes: frozenset[tuple[UUID, UUID]],
) -> models.Q | None:
    condition: models.Q | None = None
    for organization_id, edition_id in permitted_scopes:
        item = models.Q(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        condition = item if condition is None else condition | item
    return condition


def my_availability_scope_items(
    *,
    account: Account,
    permitted_scopes: frozenset[tuple[UUID, UUID]],
) -> tuple[MyAvailabilityScopeItem, ...]:
    """Return one personal Availability continuation per related edition.

    Parameters
    ----------
    account : Account
        Signed-in person.
    permitted_scopes : frozenset[tuple[UUID, UUID]]
        Exact scopes already permitted through ``workforce.view_self``.

    Returns
    -------
    tuple[MyAvailabilityScopeItem, ...]
        Stable newest-edition-first personal continuations.

    Raises
    ------
    AvailabilityReadLimitExceededError
        If the bounded assignment projection cannot be returned completely.
    """
    condition = _scope_filter(permitted_scopes)
    if condition is None:
        return ()
    assignments = tuple(
        PositionAssignment.objects.filter(
            adoption_profile_filter_for_adapter(
                WORKFORCE_SELF_ADAPTER,
                field_prefix="edition",
            ),
            condition,
            account=account,
        )
        .select_related(
            "organization",
            "edition",
            "edition__series",
            "position",
        )
        .order_by("-edition__starts_on", "position__title", "id")[
            : MAX_AVAILABILITY_ASSIGNMENTS + 1
        ]
    )
    if len(assignments) > MAX_AVAILABILITY_ASSIGNMENTS:
        raise AvailabilityReadLimitExceededError
    plans = {
        plan.edition_id: plan
        for plan in PersonAvailabilityPlan.objects.filter(
            adoption_profile_filter_for_adapter(
                WORKFORCE_SELF_ADAPTER,
                field_prefix="edition",
            ),
            condition,
            account=account,
        ).order_by("edition_id")
    }
    grouped: dict[UUID, list[PositionAssignment]] = defaultdict(list)
    for assignment in assignments:
        grouped[assignment.edition_id].append(assignment)
    items: list[MyAvailabilityScopeItem] = []
    for edition_id, rows in grouped.items():
        first = rows[0]
        open_rows = tuple(
            row
            for row in rows
            if row.status
            in (PositionAssignment.Status.PROPOSED, PositionAssignment.Status.ACTIVE)
        )
        plan = plans.get(edition_id)
        if plan is None:
            state_label = "Not started"
        elif plan.status == PersonAvailabilityPlan.Status.DRAFT:
            state_label = "Private draft"
        elif plan.status == PersonAvailabilityPlan.Status.WITHDRAWN:
            state_label = "Withdrawn"
        elif plan.window_count == 0:
            state_label = "Not available for this edition"
        else:
            state_label = "Shared with organizers"
        items.append(
            MyAvailabilityScopeItem(
                organization_slug=first.organization.slug,
                series_slug=first.edition.series.slug,
                edition_slug=first.edition.slug,
                organization_name=first.organization.name,
                edition_name=first.edition.name,
                time_zone=first.edition.time_zone,
                position_titles=tuple(
                    sorted({row.position.title for row in open_rows})
                ),
                state_label=state_label,
                can_edit=bool(open_rows),
            )
        )
    return tuple(
        sorted(
            items,
            key=lambda item: (item.edition_name.casefold(), item.organization_name),
            reverse=True,
        )
    )


def load_organizer_availability_overview(  # noqa: DOC503 - delegated row checks
    *, edition: EventEdition
) -> OrganizerAvailabilityOverview:
    """Return the complete minimized projection for open assignment people.

    Parameters
    ----------
    edition : EventEdition
        Already scoped and authorized exact edition.

    Returns
    -------
    OrganizerAvailabilityOverview
        Bounded people, open Positions, and deliberately shared consequences.

    Raises
    ------
    AvailabilityReadLimitExceededError
        If a complete projection exceeds a code-owned ceiling.
    AvailabilityProjectionIntegrityError
        If current plan metadata and current rows disagree.
    """
    assignments = tuple(
        PositionAssignment.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            status__in=(
                PositionAssignment.Status.PROPOSED,
                PositionAssignment.Status.ACTIVE,
            ),
        )
        .select_related("position", "position__department")
        .order_by("account_id", "position__department__name", "position__title", "id")[
            : MAX_AVAILABILITY_ASSIGNMENTS + 1
        ]
    )
    if len(assignments) > MAX_AVAILABILITY_ASSIGNMENTS:
        raise AvailabilityReadLimitExceededError
    account_ids = tuple(sorted({row.account_id for row in assignments}))
    if len(account_ids) > MAX_AVAILABILITY_PEOPLE:
        raise AvailabilityReadLimitExceededError
    labels = account_display_labels(account_ids)
    plans = {
        plan.account_id: plan
        for plan in PersonAvailabilityPlan.objects.filter(
            organization_id=edition.organization_id,
            edition_id=edition.id,
            account_id__in=account_ids,
        ).order_by("account_id")
    }
    grouped: dict[UUID, list[PositionAssignment]] = defaultdict(list)
    for assignment in assignments:
        grouped[assignment.account_id].append(assignment)
    people: list[OrganizerAvailabilityItem] = []
    total_windows = 0
    for account_id, rows in grouped.items():
        plan = plans.get(account_id)
        windows: tuple[AvailabilityWindowProjection, ...] = ()
        shared_at = None
        if plan is None or plan.status == PersonAvailabilityPlan.Status.DRAFT:
            state = "not_shared"
            state_label = "Not shared"
        elif plan.status == PersonAvailabilityPlan.Status.WITHDRAWN:
            _validated_plan_windows(plan=plan, expose_draft=False)
            state = "withdrawn"
            state_label = "Withdrawn"
        else:
            windows = _validated_plan_windows(plan=plan, expose_draft=False)
            shared_at = plan.submitted_at
            if windows:
                state = "shared"
                state_label = "Shared"
            else:
                state = "unavailable"
                state_label = "Not available"
        total_windows += len(windows)
        if total_windows > MAX_AVAILABILITY_TOTAL_WINDOWS:
            raise AvailabilityReadLimitExceededError
        people.append(
            OrganizerAvailabilityItem(
                account_id=account_id,
                account_label=labels.get(account_id, "Maru account"),
                positions=tuple(
                    OrganizerAvailabilityPosition(
                        department_name=row.position.department.name,
                        position_title=row.position.title,
                        assignment_status=row.get_status_display(),
                    )
                    for row in rows
                ),
                state=state,
                state_label=state_label,
                shared_at=shared_at,
                windows=windows,
            )
        )
    ordered = tuple(
        sorted(
            people,
            key=lambda item: (item.account_label.casefold(), str(item.account_id)),
        )
    )
    return OrganizerAvailabilityOverview(
        people=ordered,
        shared_count=sum(item.state == "shared" for item in ordered),
        unavailable_count=sum(item.state == "unavailable" for item in ordered),
        not_shared_count=sum(item.state == "not_shared" for item in ordered),
        withdrawn_count=sum(item.state == "withdrawn" for item in ordered),
    )
