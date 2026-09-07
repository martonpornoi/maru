"""Purpose-bounded physical facts, without private booking or foreign edition copy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_resource,
)
from maru.events.adoption import profile_allows_conflict_source
from maru.events.queries import (
    edition_adoption_profile_reference,
    resolve_edition_time_envelope_reference,
)
from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.identity.queries import resolve_active_verified_person_reference

from .adoption import VENUES_SCHEDULING_CONFLICT_SOURCE
from .bindings import edition_space_binding_id
from .inputs import normalized_source_channel
from .models import (
    EditionSpaceAvailabilityWindow,
    EditionSpaceMember,
    EditionSpaceSelection,
    VenueBookingOccupancy,
    VenueSchedulingBinding,
)

if TYPE_CHECKING:
    from datetime import datetime

VENUES_VIEW_SCHEDULING_DEPENDENCIES: Final = "venues.view_scheduling_dependencies"
PHYSICAL_DEPENDENCY_FIELDS: Final = frozenset({"physical_dependencies"})
MAX_SCHEDULING_SPACE_SELECTIONS: Final = 256
MAX_SCHEDULING_PHYSICAL_MEMBERS: Final = 4_096
MAX_SCHEDULING_PHYSICAL_WINDOWS: Final = 16_384
MAX_SCHEDULING_BUSY_PERIODS: Final = 40_000
MAX_SCHEDULING_RESERVATIONS: Final = 2_000


def _physical_source_key(edition_id: UUID, booking_id: UUID) -> UUID:
    # An opaque 128-bit key, not a generated UUID identity or an authority token.
    # Native SHA-256 also lets the DB freshness fence compare complete live busy
    # source sets without installing an extension or retaining foreign booking IDs.
    payload = f"venue-physical-conflict@1:{edition_id}:{booking_id}".encode("ascii")
    return UUID(hex=hashlib.sha256(payload).hexdigest()[:32])


class VenueSchedulingSourceUnavailableError(RuntimeError):
    """No partial physical proof is released for an unavailable exact dependency."""

    reason_code = "venues_scheduling_source_unavailable"


class VenueSchedulingSourceDeniedError(RuntimeError):
    """Hide which exact selected resource, person or field caused denial."""

    reason_code = "venues_scheduling_source_denied"


@dataclass(frozen=True, slots=True)
class VenueSchedulingWindow:
    """One positive current hard-availability or busy interval.

    Attributes
    ----------
    starts_at
        Inclusive absolute start.
    ends_at
        Exclusive absolute end.
    """

    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class VenueSchedulingSpace:
    """Current selected physical facts without labels, contacts or layout content.

    Attributes
    ----------
    selection_id
        Exact authorized edition selection.
    version
        Current selected-space aggregate version.
    availability_version
        Current hard-availability revision, zero when not configured.
    active
        Whether selected space, property and physical members remain active.
    member_ids
        Complete physical member identifiers, including combination members.
    seated_capacity
        Explicit selected seated configuration ceiling.
    standing_capacity
        Explicit selected standing configuration ceiling.
    table_capacity
        Explicit selected table configuration ceiling.
    fire_capacity
        Independent physical fire ceiling.
    windows
        Complete current hard-availability windows, not historical restrictions.
    """

    selection_id: UUID
    version: int
    availability_version: int
    active: bool
    member_ids: tuple[UUID, ...]
    seated_capacity: int
    standing_capacity: int
    table_capacity: int
    fire_capacity: int
    windows: tuple[VenueSchedulingWindow, ...]


@dataclass(frozen=True, slots=True)
class VenueSchedulingBusyPeriod:
    """A physical conflict consequence, not an administrative booking projection.

    Attributes
    ----------
    source_key
        Requested-edition-bounded pseudonymous source identity.
    source_version
        Current booking/occupancy version, not historical approval proof.
    booking_id
        Exact booking identifier only inside the requested edition; otherwise absent.
    member_id
        Shared physical member on which the busy range applies.
    conflict_group
        ADR 0053 setup_effective or effective_teardown clique.
    window
        Busy interval clipped to the requested edition's current time envelope.
    """

    source_key: UUID
    source_version: int
    booking_id: UUID | None
    member_id: UUID
    conflict_group: str
    window: VenueSchedulingWindow


@dataclass(frozen=True, slots=True)
class VenueSchedulingReservation:
    """Current exact physical binding, without approval actor or private copy.

    Attributes
    ----------
    placement_id
        Explicitly requested immutable Scheduling placement.
    occurrence_id
        Stable occurrence owning the active physical hold.
    booking_id
        Exact same-edition booking, not a foreign-edition identifier.
    booking_version
        Current version including independent approval or later state changes.
    review_state
        Current physical review only; never Programme approval or publication.
    """

    placement_id: UUID
    occurrence_id: UUID
    booking_id: UUID
    booking_version: int
    review_state: str


@dataclass(frozen=True, slots=True)
class VenueSchedulingSnapshot:
    """Complete current selected-space and physical-member consequence snapshot.

    Attributes
    ----------
    contract
        Exact versioned source descriptor pinned by the requested edition.
    edition_version
        Current Events version owning the disclosed time envelope.
    spaces
        Complete exact selection set in stable identifier order.
    busy_periods
        Current same-organization physical consequences, never foreign edition IDs.
    reservations
        Current active bindings for explicitly requested same-edition placements.
    """

    contract: str
    edition_version: int
    spaces: tuple[VenueSchedulingSpace, ...]
    busy_periods: tuple[VenueSchedulingBusyPeriod, ...]
    reservations: tuple[VenueSchedulingReservation, ...] = ()


def _authorize_space(actor_id: UUID, space: EditionSpaceSelection) -> PolicyDecision:
    decision = decide_verified_principal_exact_resource(
        principal_id=actor_id,
        organization_id=space.organization_id,
        edition_id=space.edition_id,
        department_id=space.responsible_department_id,
        resource_binding_id=edition_space_binding_id(space.id),
        capability_code=VENUES_VIEW_SCHEDULING_DEPENDENCIES,
        requested_fields=PHYSICAL_DEPENDENCY_FIELDS,
    )
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or not decision.fields.issuperset(PHYSICAL_DEPENDENCY_FIELDS)
    ):
        raise VenueSchedulingSourceDeniedError
    return decision


def _audit_source(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    outcome: str,
    count: int = 0,
    obligations: tuple[str, ...] = ("audit_sensitive_read",),
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=VENUES_VIEW_SCHEDULING_DEPENDENCIES,
            operation="venues.query.scheduling_dependencies",
            target_type="venues.edition_spaces",
            target_id=edition_id if outcome == "allow" else None,
            outcome=outcome,
            reason_code="physical_dependencies_authorized"
            if outcome == "allow"
            else VenueSchedulingSourceDeniedError.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=obligations,
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "target_count": count,
                "access_purpose": "evaluate_physical_scheduling_dependencies",
            },
            retention_class="venue-operational",
        )
    )


def _load_spaces(
    organization_id: UUID, edition_id: UUID, selection_ids: tuple[UUID, ...]
) -> tuple[EditionSpaceSelection, ...]:
    spaces = tuple(
        EditionSpaceSelection.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            id__in=selection_ids,
        )
        .select_related("venue_selection__property")
        .only(
            "id",
            "organization_id",
            "edition_id",
            "responsible_department_id",
            "lifecycle",
            "aggregate_version",
            "current_availability_version",
            "seated_capacity",
            "standing_capacity",
            "table_capacity",
            "fire_capacity",
            "venue_selection__lifecycle",
            "venue_selection__property__lifecycle",
        )
        .order_by("id")
    )
    if len(spaces) != len(selection_ids):
        raise VenueSchedulingSourceDeniedError
    return spaces


def _space_facts(
    spaces: tuple[EditionSpaceSelection, ...],
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> tuple[VenueSchedulingSpace, ...]:
    selected_ids = tuple(space.id for space in spaces)
    member_rows = tuple(
        EditionSpaceMember.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id__in=selected_ids,
        )
        .order_by("space_selection_id", "source_space_id")
        .values_list(
            "space_selection_id", "source_space_id", "source_space__is_active"
        )[: MAX_SCHEDULING_PHYSICAL_MEMBERS + 1]
    )
    windows = tuple(
        EditionSpaceAvailabilityWindow.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id__in=selected_ids,
            availability_version=F("space_selection__current_availability_version"),
        )
        .order_by("space_selection_id", "starts_at", "id")
        .values_list("space_selection_id", "starts_at", "ends_at")[
            : MAX_SCHEDULING_PHYSICAL_WINDOWS + 1
        ]
    )
    if (
        len(member_rows) > MAX_SCHEDULING_PHYSICAL_MEMBERS
        or len(windows) > MAX_SCHEDULING_PHYSICAL_WINDOWS
    ):
        raise VenueSchedulingSourceUnavailableError
    members: dict[UUID, list[tuple[UUID, bool]]] = {}
    available: dict[UUID, list[VenueSchedulingWindow]] = {}
    for selection_id, member_id, active in member_rows:
        members.setdefault(selection_id, []).append((member_id, active))
    for selection_id, start, end in windows:
        available.setdefault(selection_id, []).append(VenueSchedulingWindow(start, end))
    results = []
    for space in spaces:
        selected_members = members.get(space.id, [])
        if not selected_members:
            raise VenueSchedulingSourceUnavailableError
        results.append(
            VenueSchedulingSpace(
                space.id,
                space.aggregate_version,
                space.current_availability_version,
                space.lifecycle == "active"
                and space.venue_selection.lifecycle == "active"
                and space.venue_selection.property.lifecycle == "active"
                and all(active for _, active in selected_members),
                tuple(member_id for member_id, _ in selected_members),
                space.seated_capacity,
                space.standing_capacity,
                space.table_capacity,
                space.fire_capacity,
                tuple(available.get(space.id, [])),
            )
        )
    return tuple(results)


def _busy_periods(
    *,
    organization_id: UUID,
    edition_id: UUID,
    member_ids: frozenset[UUID],
    window: VenueSchedulingWindow,
) -> tuple[VenueSchedulingBusyPeriod, ...]:
    rows = tuple(
        VenueBookingOccupancy.objects.filter(
            organization_id=organization_id,
            source_space_id__in=member_ids,
            active=True,
            booking__lifecycle="active",
            occupied_range__overlap=(window.starts_at, window.ends_at),
        )
        .order_by("booking_id", "source_space_id", "conflict_group")
        .values_list(
            "booking_id",
            "booking__aggregate_version",
            "booking__edition_id",
            "source_space_id",
            "conflict_group",
            "occupied_range",
        )[: MAX_SCHEDULING_BUSY_PERIODS + 1]
    )
    if len(rows) > MAX_SCHEDULING_BUSY_PERIODS:
        raise VenueSchedulingSourceUnavailableError
    results = []
    for booking_id, version, owner_edition, member_id, group, period in rows:
        if (
            group not in {"setup_effective", "effective_teardown"}
            or period.isempty
            or period.lower is None
            or period.upper is None
        ):
            raise VenueSchedulingSourceUnavailableError
        start, end = (
            max(period.lower, window.starts_at),
            min(period.upper, window.ends_at),
        )
        if start < end:
            results.append(
                VenueSchedulingBusyPeriod(
                    _physical_source_key(edition_id, booking_id),
                    version,
                    booking_id if owner_edition == edition_id else None,
                    member_id,
                    group,
                    VenueSchedulingWindow(start, end),
                )
            )
    return tuple(results)


def load_venue_scheduling_dependencies(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    selection_ids: tuple[UUID, ...],
    correlation_id: UUID,
    source_channel: str = "scheduling",
    placement_ids: tuple[UUID, ...] = (),
) -> VenueSchedulingSnapshot:
    """Read complete current physical consequences through independent Venue policy.

    A shared physical room can be occupied by another edition of this organization.
    Only its busy consequence within the requested edition envelope is disclosed:
    never that edition's identity, booking identity, copy, contacts or review actor.
    This read is a point-in-time dependency check, not a reservation or approval.

    Parameters
    ----------
    actor_id : UUID
        Current authenticated verified person.
    organization_id : UUID
        Exact common organization owner.
    edition_id : UUID
        Exact requesting edition and disclosure time envelope.
    selection_ids : tuple[UUID, ...]
        Complete distinct selected-space set, bounded to 256.
    correlation_id : UUID
        Trusted trace identifier for mandatory minimized audit.
    source_channel : str, default="scheduling"
        Trusted bounded adapter code.
    placement_ids : tuple[UUID, ...], default=()
        Optional complete distinct placement set whose active bindings are requested.

    Returns
    -------
    VenueSchedulingSnapshot
        Complete minimized current physical facts after fresh exact-resource policy.

    Raises
    ------
    ValidationError
        If identifiers or selection bounds are malformed.
    VenueSchedulingSourceDeniedError
        If current person, exact resource or field authority is unavailable.
    """
    if (
        any(
            not isinstance(value, UUID)
            for value in (actor_id, organization_id, edition_id, correlation_id)
        )
        or not isinstance(selection_ids, tuple)
        or len(selection_ids) > MAX_SCHEDULING_SPACE_SELECTIONS
        or any(not isinstance(value, UUID) for value in selection_ids)
        or len(set(selection_ids)) != len(selection_ids)
        or not isinstance(placement_ids, tuple)
        or len(placement_ids) > MAX_SCHEDULING_RESERVATIONS
        or any(not isinstance(value, UUID) for value in placement_ids)
        or len(set(placement_ids)) != len(placement_ids)
    ):
        raise ValidationError(
            "Supply complete bounded exact physical selection identifiers."
        )
    source_channel = normalized_source_channel(source_channel)

    def load() -> VenueSchedulingSnapshot:
        with transaction.atomic():
            if (
                resolve_scheduling_edition_reference(
                    organization_id=organization_id, edition_id=edition_id, lock=True
                )
                is None
            ):
                raise VenueSchedulingSourceDeniedError
            if (
                resolve_active_verified_person_reference(account_id=actor_id, lock=True)
                is None
            ):
                raise VenueSchedulingSourceDeniedError
            profile = edition_adoption_profile_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            if profile is None or not profile_allows_conflict_source(
                profile.code, profile.version, VENUES_SCHEDULING_CONFLICT_SOURCE
            ):
                raise VenueSchedulingSourceUnavailableError
            spaces = _load_spaces(organization_id, edition_id, selection_ids)
            for space in spaces:
                _authorize_space(actor_id, space)
            envelope = resolve_edition_time_envelope_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            if envelope is None:
                raise VenueSchedulingSourceUnavailableError
            facts = _space_facts(
                spaces, organization_id=organization_id, edition_id=edition_id
            )
            busy = _busy_periods(
                organization_id=organization_id,
                edition_id=edition_id,
                member_ids=frozenset(
                    member for fact in facts for member in fact.member_ids
                ),
                window=VenueSchedulingWindow(envelope.starts_at, envelope.ends_at),
            )
            reservations = tuple(
                VenueSchedulingReservation(*row)
                for row in VenueSchedulingBinding.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    placement_id__in=placement_ids,
                    booking__organization_id=organization_id,
                    booking__edition_id=edition_id,
                    booking__space_selection_id__in=selection_ids,
                    booking__lifecycle="active",
                )
                .order_by("placement_id")
                .values_list(
                    "placement_id",
                    "occurrence_id",
                    "booking_id",
                    "booking__aggregate_version",
                    "booking__review_state",
                )[: MAX_SCHEDULING_RESERVATIONS + 1]
            )
            if len(reservations) > MAX_SCHEDULING_RESERVATIONS or len(
                {binding.occurrence_id for binding in reservations}
            ) != len(reservations):
                raise VenueSchedulingSourceUnavailableError
            obligations = {"audit_sensitive_read"}
            for space in spaces:
                obligations.update(_authorize_space(actor_id, space).obligations)
            _audit_source(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                source_channel=source_channel,
                outcome="allow",
                count=len(spaces),
                obligations=tuple(sorted(obligations)),
            )
            return VenueSchedulingSnapshot(
                VENUES_SCHEDULING_CONFLICT_SOURCE,
                envelope.version,
                facts,
                busy,
                reservations,
            )

    try:
        return load()
    except VenueSchedulingSourceDeniedError:
        _audit_source(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            outcome="deny",
        )
        raise
