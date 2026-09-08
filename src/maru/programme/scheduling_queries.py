"""Minimized, currently authorized Programme dependencies for Scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.events.adoption import profile_allows_conflict_source
from maru.events.queries import (
    EditionTimeEnvelopeReference,
    edition_adoption_profile_reference,
    resolve_edition_time_envelope_reference,
    resolve_private_planning_edition_reference,
)
from maru.identity.queries import (
    edition_person_conflict_key,
    resolve_active_verified_person_references,
)
from maru.programme.adoption import PROGRAMME_SCHEDULING_CONFLICT_SOURCE
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_SCHEDULING_DEPENDENCIES,
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
)
from maru.programme.host_catalogs import (
    HOST_TERMINAL_STATES,
    MAX_HOST_AVAILABILITY_PERIODS,
)
from maru.programme.host_inputs import ProgrammeHostAvailabilityPeriod
from maru.programme.models import (
    ProgrammeHostAvailabilityWindow,
    ProgrammeHostRelationship,
    ProgrammeItem,
    ProgrammeReadinessRequirement,
)
from maru.programme.queries import ProgrammeQueryUnavailableError, _authorized_query

MAX_SCHEDULING_SOURCE_ITEMS: Final = 2_000
# Leave room for the independently authenticated actor in Identity's batch bound.
MAX_SCHEDULING_SOURCE_HOSTS: Final = 1_999
MAX_SCHEDULING_SOURCE_PERIODS: Final = 16_384
SCHEDULING_DEPENDENCY_FIELDS: Final = frozenset(
    {
        "item_scheduling_facts",
        "host_conflict_keys",
        "current_shared_host_periods",
    }
)


@dataclass(frozen=True, slots=True)
class ProgrammeSchedulingItem:
    """Title-free current item facts, not a release-readiness decision.

    Attributes
    ----------
    item_id
        Exact retained Programme item.
    item_version
        Current optimistic item version.
    lifecycle
        Current active or retired item state.
    hosting_required
        False only for an explicitly configured not-applicable host concern.
    """

    item_id: UUID
    item_version: int
    lifecycle: str
    hosting_required: bool


@dataclass(frozen=True, slots=True)
class ProgrammeSchedulingHost:
    """One explicitly selected purpose, with no private or historical periods.

    Attributes
    ----------
    host_id
        Exact selected relationship, not an inferred proposal contributor.
    item_id
        Item to which this hosting purpose belongs.
    host_version
        Current relationship version.
    availability_version
        Current availability version, including withdrawal.
    person_key
        Edition-bounded pseudonymous conflict key for a current confirmed person.
    status
        Ended, inactive, unconfirmed, not_shared, outside_edition, unavailable
        or shared; missing information never means free.
    periods
        Only deliberately shared current periods inside the current edition.
    """

    host_id: UUID
    item_id: UUID
    host_version: int
    availability_version: int
    person_key: UUID | None
    status: str
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeSchedulingSnapshot:
    """Complete bounded dependency result for exact selected items and hosts.

    Attributes
    ----------
    contract
        Exact source descriptor that the edition's manifest must pin.
    edition_version
        Current Events envelope version, or no valid envelope.
    items
        Every requested item, in deterministic identifier order.
    hosts
        Every explicitly requested relationship, not the entire retained roster.
    """

    contract: str
    edition_version: int | None
    items: tuple[ProgrammeSchedulingItem, ...]
    hosts: tuple[ProgrammeSchedulingHost, ...]


def _identifiers(values: tuple[UUID, ...], maximum: int) -> tuple[UUID, ...]:
    if (
        not isinstance(values, tuple)
        or len(values) > maximum
        or any(not isinstance(value, UUID) for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValidationError("Supply complete bounded distinct source identifiers.")
    return tuple(sorted(values, key=str))


def _current_periods(
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...],
) -> tuple[ProgrammeHostAvailabilityPeriod, ...]:
    if len(periods) > MAX_HOST_AVAILABILITY_PERIODS:
        raise ProgrammeQueryUnavailableError
    try:
        normalized = tuple(period.normalized() for period in periods)
    except ValidationError as error:
        raise ProgrammeQueryUnavailableError from error
    if any(left.ends_at > right.starts_at for left, right in pairwise(normalized)):
        raise ProgrammeQueryUnavailableError
    return normalized


def _host_consequence(
    host: ProgrammeHostRelationship,
    *,
    current: set[UUID],
    envelope: EditionTimeEnvelopeReference | None,
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...],
) -> ProgrammeSchedulingHost:
    key = None
    disclosed: tuple[ProgrammeHostAvailabilityPeriod, ...] = ()
    if host.state in HOST_TERMINAL_STATES:
        status = "ended"
    elif host.account_id not in current:
        status = "inactive"
    elif host.state != "confirmed":
        status = "unconfirmed"
    else:
        key = edition_person_conflict_key(
            edition_id=host.edition_id, account_id=host.account_id
        )
        if host.availability_state != "shared":
            status = "not_shared"
        elif envelope is None:
            status = "outside_edition"
        else:
            normalized = _current_periods(periods)
            if any(
                p.starts_at < envelope.starts_at or p.ends_at > envelope.ends_at
                for p in normalized
            ):
                status = "outside_edition"
            else:
                disclosed = normalized
                status = "shared" if disclosed else "unavailable"
    return ProgrammeSchedulingHost(
        host.id,
        host.item_id,
        host.version,
        host.availability_version,
        key,
        status,
        disclosed,
    )


def load_programme_scheduling_dependencies(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_ids: tuple[UUID, ...],
    host_ids: tuple[UUID, ...],
    correlation_id: UUID,
    source_channel: str = "scheduling",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeSchedulingSnapshot:
    """Resolve current consent and availability through an exact pinned owner seam.

    The caller must not persist exact personal periods in candidate history.
    No existing adoption profile pins this dormant source. A trusted future
    adapter must select explicit host purposes; it cannot derive consent from
    accepted proposals or treat missing host selection as not applicable.

    Parameters
    ----------
    actor_id : UUID
        Current authenticated person requiring independent Programme authority.
    organization_id : UUID
        Expected organization owner.
    edition_id : UUID
        Exact edition and conflict-key namespace.
    item_ids : tuple[UUID, ...]
        Complete distinct item selection, bounded to 2000.
    host_ids : tuple[UUID, ...]
        Complete distinct explicit host selection, bounded to 1999.
    correlation_id : UUID
        Trusted attribution for the mandatory minimized audit.
    source_channel : str, default="scheduling"
        Bounded trusted adapter identifier.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or sealed isolated-test substitute.

    Returns
    -------
    ProgrammeSchedulingSnapshot
        Complete minimized current evidence after reauthorization and audit.
    """
    selected_items = _identifiers(item_ids, MAX_SCHEDULING_SOURCE_ITEMS)
    selected_hosts = _identifiers(host_ids, MAX_SCHEDULING_SOURCE_HOSTS)

    def load() -> ProgrammeSchedulingSnapshot:
        if (
            resolve_private_planning_edition_reference(
                organization_id=organization_id, edition_id=edition_id, lock=True
            )
            is None
        ):
            raise ProgrammeQueryUnavailableError
        profile = edition_adoption_profile_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        if profile is None or not profile_allows_conflict_source(
            profile.code, profile.version, PROGRAMME_SCHEDULING_CONFLICT_SOURCE
        ):
            raise ProgrammeQueryUnavailableError
        hosts = tuple(
            ProgrammeHostRelationship.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id__in=selected_items,
                id__in=selected_hosts,
            ).order_by("id")
        )
        if len(hosts) != len(selected_hosts):
            raise ProgrammeQueryUnavailableError
        people = resolve_active_verified_person_references(
            account_ids={actor_id, *(host.account_id for host in hosts)}, lock=True
        )
        current = (
            {person.account_id for person in people} if people is not None else set()
        )
        if actor_id not in current:
            raise ProgrammeAuthorizationDeniedError
        items = tuple(
            ProgrammeItem.objects.select_for_update(of=("self",))
            .filter(
                organization_id=organization_id,
                edition_id=edition_id,
                id__in=selected_items,
            )
            .order_by("id")
        )
        if len(items) != len(selected_items):
            raise ProgrammeQueryUnavailableError
        not_applicable = set(
            ProgrammeReadinessRequirement.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id__in=selected_items,
                concern="host_confirmation",
                disposition="not_applicable",
            ).values_list("item_id", flat=True)
        )
        envelope = resolve_edition_time_envelope_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        shared = {
            host.id
            for host in hosts
            if host.state == "confirmed"
            and host.account_id in current
            and host.availability_state == "shared"
            and envelope is not None
        }
        rows = tuple(
            ProgrammeHostAvailabilityWindow.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                host_id__in=shared,
            )
            .order_by("host_id", "starts_at", "id")
            .values_list("host_id", "starts_at", "ends_at", "kind")[
                : MAX_SCHEDULING_SOURCE_PERIODS + 1
            ]
        )
        if len(rows) > MAX_SCHEDULING_SOURCE_PERIODS:
            raise ProgrammeQueryUnavailableError
        periods_by_host: dict[UUID, list[ProgrammeHostAvailabilityPeriod]] = {}
        for host_id, start, end, kind in rows:
            periods_by_host.setdefault(host_id, []).append(
                ProgrammeHostAvailabilityPeriod(start, end, kind)
            )
        return ProgrammeSchedulingSnapshot(
            PROGRAMME_SCHEDULING_CONFLICT_SOURCE,
            envelope.version if envelope else None,
            tuple(
                ProgrammeSchedulingItem(
                    item.id,
                    item.aggregate_version,
                    item.lifecycle,
                    item.id not in not_applicable,
                )
                for item in items
            ),
            tuple(
                _host_consequence(
                    host,
                    current=current,
                    envelope=envelope,
                    periods=tuple(periods_by_host.get(host.id, ())),
                )
                for host in hosts
            ),
        )

    return _authorized_query(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_VIEW_SCHEDULING_DEPENDENCIES,
        requested_fields=SCHEDULING_DEPENDENCY_FIELDS,
        operation="programme.query.scheduling_dependencies",
        loader=load,
        target_type="programme.scope",
        target_id=edition_id,
        target_count=lambda result: len(result.items) + len(result.hosts),
        reason="Evaluate explicit Scheduling dependencies",
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )
