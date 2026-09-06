"""Bounded, independently ceilinged host-purpose reads with audited disclosure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.events.queries import (
    resolve_edition_time_envelope_reference,
    resolve_private_planning_edition_reference,
)
from maru.identity.queries import resolve_active_verified_person_reference

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_HOST_SELF,
    PROGRAMME_VIEW_HOSTS,
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
)
from .host_authorization import authorize_host_retry_scope
from .host_catalogs import (
    HOST_SELF_FIELDS,
    MAX_HOST_AVAILABILITY_PERIODS,
    MAX_HOST_REVISIONS,
    MAX_HOSTS_PER_ITEM,
)
from .host_inputs import ProgrammeHostAvailabilityPeriod
from .inputs import require_uuid
from .models import (
    ProgrammeHostAvailabilityWindow,
    ProgrammeHostInvitation,
    ProgrammeHostRelationship,
    ProgrammeHostRevision,
    ProgrammeItem,
    ProgrammePublicRendition,
)
from .queries import (
    ProgrammePublicCopyProjection,
    ProgrammeQueryUnavailableError,
    _authorized_query,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProgrammeHostReadRequest:
    """Exact trusted routing and audit attribution, never portable authority.

    Attributes
    ----------
    actor_id
        Authenticated person whose current authority will be resolved.
    organization_id
        Expected tenant owner.
    edition_id
        Exact edition containing the item.
    item_id
        Exact hosting purpose to read.
    correlation_id
        Caller trace identifier for minimized audit.
    source_channel
        Bounded adapter name.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    item_id: UUID
    correlation_id: UUID
    source_channel: str = "programme-hosts"


@dataclass(frozen=True, slots=True)
class ProgrammeHostStateProjection:
    """One title-free retained relationship state, with no account directory data.

    Attributes
    ----------
    host_id
        Opaque relationship identifier.
    role
        Explicit host or co-host role.
    state
        Current invitation or hosting state.
    version
        Relationship optimistic version.
    invitation_sequence
        Exact invitation requiring a person response.
    """

    host_id: UUID
    role: str
    state: str
    version: int
    invitation_sequence: int


@dataclass(frozen=True, slots=True)
class ProgrammeHostInvitationProjection:
    """Only deliberate host-visible copy, not private organizer rationale.

    Attributes
    ----------
    sequence
        Retained invitation sequence.
    role
        Explicit role in this invitation.
    title
        Deliberately host-visible title.
    briefing
        Deliberately host-visible operational briefing.
    """

    sequence: int
    role: str
    title: str
    briefing: str


@dataclass(frozen=True, slots=True)
class ProgrammeHostSelfSnapshot:
    """Complete own-purpose snapshot without another person's or organizer's fields.

    Attributes
    ----------
    item_version
        Item version fencing subsequent commands.
    relationship
        Current retained personal hosting state.
    invitations
        Complete bounded history of this person's deliberate invitations.
    history
        Version, invitation sequence and state only, with no actor or rationale.
    availability_state
        Own exact sharing state, including the private draft distinction.
    availability_version
        Own current availability source version.
    periods
        Own current exact periods, including private drafts.
    public_copy
        Latest approved copy only for a currently confirmed relationship.
    """

    item_version: int
    relationship: ProgrammeHostStateProjection
    invitations: tuple[ProgrammeHostInvitationProjection, ...]
    history: tuple[ProgrammeHostStateProjection, ...]
    availability_state: str
    availability_version: int
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...]
    public_copy: ProgrammePublicCopyProjection | None


@dataclass(frozen=True, slots=True)
class ProgrammeHostRosterEntry:
    """Organizer roster evidence, separate from personal availability and history.

    Attributes
    ----------
    relationship
        Current title-free relationship state.
    account_id
        Exact already-related person, not a directory search result.
    person_current
        Whether Identity still proves an active verified person.
    """

    relationship: ProgrammeHostStateProjection
    account_id: UUID
    person_current: bool


@dataclass(frozen=True, slots=True)
class ProgrammeHostRosterSnapshot:
    """Complete bounded item roster with optimistic fencing.

    Attributes
    ----------
    item_version
        Current item version under the same edition lock.
    entries
        Every retained relationship, never a silently truncated partial roster.
    """

    item_version: int
    entries: tuple[ProgrammeHostRosterEntry, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeHostHistoryEntry:
    """Separately authorized organizer history without exact historical periods.

    Attributes
    ----------
    relationship
        Retained role and state at this revision.
    operation
        Closed operation that produced the revision.
    actor_id
        Accountable actor identifier.
    reason
        Retained rationale, not available through the self projection.
    occurred_at
        Authoritative history instant.
    item_version
        Exact item version of this revision.
    """

    relationship: ProgrammeHostStateProjection
    operation: str
    actor_id: UUID
    reason: str
    occurred_at: datetime
    item_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeHostAvailabilityProjection:
    """Current scheduling consequence without private draft or withheld periods.

    Attributes
    ----------
    host_id
        Exact related purpose identifier.
    host_version
        Current source relationship version.
    availability_version
        Current availability source version.
    status
        Ended, unconfirmed, inactive, not_shared, unavailable,
        outside_edition or shared.
    periods
        Only currently shared, in-envelope periods for a confirmed current person.
    """

    host_id: UUID
    host_version: int
    availability_version: int
    status: str
    periods: tuple[ProgrammeHostAvailabilityPeriod, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeHostDependencySnapshot:
    """Versioned minimized dependency for later Scheduling, not schedule approval.

    Attributes
    ----------
    item_id
        Exact Programme item source.
    item_version
        Current Programme aggregate source version.
    edition_version
        Current Events version defining the date envelope, or no valid envelope.
    contract
        Stable versioned query contract identifier.
    hosts
        Complete retained host consequences; no contact, rationale or draft.
    """

    item_id: UUID
    item_version: int
    edition_version: int | None
    contract: str
    hosts: tuple[ProgrammeHostAvailabilityProjection, ...]


def _state(host: ProgrammeHostRelationship) -> ProgrammeHostStateProjection:
    return ProgrammeHostStateProjection(
        host.id, host.role, host.state, host.version, host.invitation_sequence
    )


def _revision_state(revision: ProgrammeHostRevision) -> ProgrammeHostStateProjection:
    return ProgrammeHostStateProjection(
        revision.host_id,
        revision.role,
        revision.state,
        revision.sequence,
        revision.invitation_sequence,
    )


def _read_people(
    item: ProgrammeItem, *, actor_id: UUID, roster: bool
) -> dict[UUID, bool]:
    people = {actor_id}
    if roster:
        people.update(host.account_id for host in _hosts(item))
    current = {
        account_id: resolve_active_verified_person_reference(
            account_id=account_id, lock=True
        )
        is not None
        for account_id in sorted(people, key=str)
    }
    if not current[actor_id]:
        raise ProgrammeAuthorizationDeniedError
    return current


def _read[ResultT](
    request: ProgrammeHostReadRequest,
    *,
    capability: str,
    fields: frozenset[str],
    operation: str,
    loader: Callable[[ProgrammeItem, dict[UUID, bool]], ResultT],
    authorizer: ProgrammeAuthorizer,
    roster: bool = False,
) -> ResultT:
    for field in (
        "actor_id",
        "organization_id",
        "edition_id",
        "item_id",
        "correlation_id",
    ):
        require_uuid(getattr(request, field), field=field)

    def load() -> ResultT:
        # Fence the edition, then lock actor and subjects in one canonical order.
        if (
            resolve_private_planning_edition_reference(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                lock=True,
            )
            is None
        ):
            raise ProgrammeAuthorizationDeniedError
        authorize_host_retry_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=capability,
            authorizer=authorizer,
        )
        item = ProgrammeItem.objects.filter(
            id=request.item_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
        ).first()
        if item is None:
            if capability == PROGRAMME_VIEW_HOST_SELF:
                raise ProgrammeAuthorizationDeniedError
            raise ProgrammeQueryUnavailableError
        people = _read_people(item, actor_id=request.actor_id, roster=roster)
        return loader(item, people)

    return _authorized_query(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=capability,
        requested_fields=fields,
        operation=operation,
        loader=load,
        target_type="programme.item",
        target_id=request.item_id,
        target_count=lambda _: 1,
        reason="Explicit Programme host-purpose read",
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
        authorizer=authorizer,
    )


def _periods(
    host: ProgrammeHostRelationship,
) -> tuple[ProgrammeHostAvailabilityPeriod, ...]:
    rows = tuple(
        ProgrammeHostAvailabilityWindow.objects.filter(host=host)
        .order_by("starts_at", "id")
        .values_list("starts_at", "ends_at", "kind")[
            : MAX_HOST_AVAILABILITY_PERIODS + 1
        ]
    )
    if len(rows) > MAX_HOST_AVAILABILITY_PERIODS:
        raise ProgrammeQueryUnavailableError
    return tuple(ProgrammeHostAvailabilityPeriod(*row) for row in rows)


def _hosts(item: ProgrammeItem) -> tuple[ProgrammeHostRelationship, ...]:
    rows = tuple(
        ProgrammeHostRelationship.objects.filter(item=item).order_by("id")[
            : MAX_HOSTS_PER_ITEM + 1
        ]
    )
    if len(rows) > MAX_HOSTS_PER_ITEM:
        raise ProgrammeQueryUnavailableError
    return rows


def load_programme_host_self(
    request: ProgrammeHostReadRequest,
    *,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeHostSelfSnapshot:
    """Read only the authenticated person's retained invitations and current purpose.

    Parameters
    ----------
    request : ProgrammeHostReadRequest
        Exact trusted item scope and audit attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or sealed isolated-test substitute.

    Returns
    -------
    ProgrammeHostSelfSnapshot
        Complete own-purpose snapshot after current relationship proof and audit.
    """

    def load(
        item: ProgrammeItem, people: dict[UUID, bool]
    ) -> ProgrammeHostSelfSnapshot:
        del people
        host = ProgrammeHostRelationship.objects.filter(
            item=item, account_id=request.actor_id
        ).first()
        if host is None:
            raise ProgrammeAuthorizationDeniedError
        invitations = tuple(
            ProgrammeHostInvitation.objects.filter(host=host).order_by("sequence")[
                : MAX_HOST_REVISIONS + 3
            ]
        )
        history = tuple(
            ProgrammeHostRevision.objects.filter(host=host).order_by("sequence")[
                : MAX_HOST_REVISIONS + 3
            ]
        )
        if (
            len(invitations) > MAX_HOST_REVISIONS
            or len(history) > MAX_HOST_REVISIONS + 2
        ):
            raise ProgrammeQueryUnavailableError
        rendition = (
            ProgrammePublicRendition.objects.filter(item=item)
            .order_by("-rendition_number")
            .first()
            if host.state == "confirmed"
            else None
        )
        return ProgrammeHostSelfSnapshot(
            item.aggregate_version,
            _state(host),
            tuple(
                ProgrammeHostInvitationProjection(
                    i.sequence, i.role, i.title, i.briefing
                )
                for i in invitations
            ),
            tuple(_revision_state(r) for r in history),
            host.availability_state,
            host.availability_version,
            _periods(host),
            ProgrammePublicCopyProjection(
                rendition.rendition_number,
                rendition.public_title,
                rendition.public_summary,
                rendition.public_content_note,
            )
            if rendition is not None
            else None,
        )

    return _read(
        request,
        capability=PROGRAMME_VIEW_HOST_SELF,
        fields=HOST_SELF_FIELDS,
        operation="programme.query.host_self",
        loader=load,
        authorizer=authorizer,
    )


def load_programme_host_roster(
    request: ProgrammeHostReadRequest,
    *,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeHostRosterSnapshot:
    """Read a complete organizer roster without history or personal availability.

    Parameters
    ----------
    request : ProgrammeHostReadRequest
        Exact trusted item scope and audit attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or sealed isolated-test substitute.

    Returns
    -------
    ProgrammeHostRosterSnapshot
        Independently authorized roster, never another information layer.
    """

    def load(
        item: ProgrammeItem, people: dict[UUID, bool]
    ) -> ProgrammeHostRosterSnapshot:
        return ProgrammeHostRosterSnapshot(
            item.aggregate_version,
            tuple(
                ProgrammeHostRosterEntry(
                    _state(h),
                    h.account_id,
                    people[h.account_id],
                )
                for h in sorted(_hosts(item), key=lambda row: str(row.account_id))
            ),
        )

    return _read(
        request,
        capability=PROGRAMME_VIEW_HOSTS,
        fields=frozenset({"host_roster"}),
        operation="programme.query.host_roster",
        loader=load,
        authorizer=authorizer,
        roster=True,
    )


def load_programme_host_history(
    request: ProgrammeHostReadRequest,
    *,
    host_id: UUID,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeHostHistoryEntry, ...]:
    """Read separately ceilinged organizer history for one exact relationship.

    Parameters
    ----------
    request : ProgrammeHostReadRequest
        Exact trusted item scope and audit attribution.
    host_id : UUID
        Exact relationship in that scope.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or sealed isolated-test substitute.

    Returns
    -------
    tuple[ProgrammeHostHistoryEntry, ...]
        Complete bounded rationale history without exact historical periods.
    """
    require_uuid(host_id, field="host_id")

    def load(
        item: ProgrammeItem, people: dict[UUID, bool]
    ) -> tuple[ProgrammeHostHistoryEntry, ...]:
        del people
        if not ProgrammeHostRelationship.objects.filter(item=item, id=host_id).exists():
            raise ProgrammeQueryUnavailableError
        revisions = tuple(
            ProgrammeHostRevision.objects.filter(item=item, host_id=host_id).order_by(
                "sequence"
            )[: MAX_HOST_REVISIONS + 3]
        )
        if len(revisions) > MAX_HOST_REVISIONS + 2:
            raise ProgrammeQueryUnavailableError
        return tuple(
            ProgrammeHostHistoryEntry(
                _revision_state(r),
                r.operation,
                r.actor_id,
                r.reason,
                r.occurred_at,
                r.item_version,
            )
            for r in revisions
        )

    return _read(
        request,
        capability=PROGRAMME_VIEW_HOSTS,
        fields=frozenset({"host_history"}),
        operation="programme.query.host_history",
        loader=load,
        authorizer=authorizer,
    )


def load_programme_host_dependencies(
    request: ProgrammeHostReadRequest,
    *,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeHostDependencySnapshot:
    """Read minimized current scheduling consequences, never infer missing time as free.

    Parameters
    ----------
    request : ProgrammeHostReadRequest
        Exact trusted item scope and audit attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy or sealed isolated-test substitute.

    Returns
    -------
    ProgrammeHostDependencySnapshot
        Complete current-person and current-envelope evidence for later Scheduling.
    """

    def load(
        item: ProgrammeItem, people: dict[UUID, bool]
    ) -> ProgrammeHostDependencySnapshot:
        envelope = resolve_edition_time_envelope_reference(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            lock=True,
        )
        projections = []
        for host in sorted(_hosts(item), key=lambda row: str(row.account_id)):
            periods: tuple[ProgrammeHostAvailabilityPeriod, ...] = ()
            if host.state in {"declined", "withdrawn", "removed"}:
                status = "ended"
            elif not people[host.account_id]:
                status = "inactive"
            elif host.state != "confirmed":
                status = "unconfirmed"
            elif host.availability_state != "shared":
                status = "not_shared"
            else:
                periods = _periods(host)
                if envelope is None or any(
                    p.starts_at < envelope.starts_at or p.ends_at > envelope.ends_at
                    for p in periods
                ):
                    status, periods = "outside_edition", ()
                else:
                    status = "shared" if periods else "unavailable"
            projections.append(
                ProgrammeHostAvailabilityProjection(
                    host.id, host.version, host.availability_version, status, periods
                )
            )
        return ProgrammeHostDependencySnapshot(
            item.id,
            item.aggregate_version,
            envelope.version if envelope else None,
            "programme.host-dependencies@1",
            tuple(projections),
        )

    return _read(
        request,
        capability=PROGRAMME_VIEW_HOSTS,
        fields=frozenset({"shared_host_availability"}),
        operation="programme.query.host_dependencies",
        loader=load,
        authorizer=authorizer,
        roster=True,
    )
