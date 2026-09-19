"""Compose protected Programme core, host and staffing evidence for one item."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from . import exit_core_queries as core
from . import host_queries as hosts
from . import staffing_queries as staffing
from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_HOSTS,
    PROGRAMME_VIEW_PRIVATE,
    PROGRAMME_VIEW_STAFFING,
    authorize_programme_scope,
)
from .host_catalogs import MAX_HOST_REVISIONS, MAX_HOSTS_PER_ITEM
from .inputs import require_uuid
from .queries import ProgrammeQueryUnavailableError, _authorized_query
from .staffing_inputs import (
    MAX_STAFFING_REQUIREMENT_REVISIONS,
    MAX_STAFFING_REQUIREMENTS_PER_ITEM,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import ProgrammeAuthorizer
    from .staffing_queries import ProgrammeStaffingHistoryEntry

_FIELDS: Final = (
    *core.PROGRAMME_EXIT_CORE_FIELDS,
    (
        PROGRAMME_VIEW_HOSTS,
        frozenset({"host_roster", "host_history", "shared_host_availability"}),
    ),
    (PROGRAMME_VIEW_STAFFING, frozenset({"staffing_requirements", "staffing_history"})),
)


@dataclass(frozen=True, slots=True)
class ProgrammeExitItem:
    """One bounded owner component, not a complete profile archive or access grant.

    Attributes
    ----------
    core
        Private, working, delivery, discussion, readiness and copy-review evidence.
    roster, host_histories, host_dependencies
        Current roster, complete ordered histories in the same roster order, and
        currently authorized shared availability. Historical private periods and
        invitation copy are deliberately outside these existing reader ceilings.
    staffing, staffing_histories
        Current retained requirements and complete histories in requirement order,
        including retirement evidence. No Workforce assignments or Shift decisions.
    """

    core: core.ProgrammeExitCore = field(repr=False)
    roster: hosts.ProgrammeHostRosterSnapshot = field(repr=False)
    host_histories: tuple[tuple[hosts.ProgrammeHostHistoryEntry, ...], ...] = field(
        repr=False
    )
    host_dependencies: hosts.ProgrammeHostDependencySnapshot = field(repr=False)
    staffing: staffing.ProgrammeStaffingOverview = field(repr=False)
    staffing_histories: tuple[tuple[ProgrammeStaffingHistoryEntry, ...], ...] = field(
        repr=False
    )


def _host_history(
    request: hosts.ProgrammeHostReadRequest,
    current: hosts.ProgrammeHostStateProjection,
    *,
    authorizer: ProgrammeAuthorizer,
) -> tuple[hosts.ProgrammeHostHistoryEntry, ...]:
    history = hosts.load_programme_host_history(
        request, host_id=current.host_id, authorizer=authorizer
    )
    if (
        type(current.version) is not int
        or not 1 <= current.version <= MAX_HOST_REVISIONS + 2
        or len(history) != current.version
        or any(
            row.relationship.host_id != current.host_id
            or row.relationship.version != index + 1
            for index, row in enumerate(history)
        )
        or history[-1].relationship != current
    ):
        raise ProgrammeQueryUnavailableError
    return history


def _staffing_history(
    request: staffing.ProgrammeStaffingReadRequest,
    current: staffing.ProgrammeStaffingRequirementView,
    *,
    authorizer: ProgrammeAuthorizer,
) -> tuple[staffing.ProgrammeStaffingHistoryEntry, ...]:
    if (
        type(current.version) is not int
        or not 1 <= current.version <= MAX_STAFFING_REQUIREMENT_REVISIONS + 1
    ):
        raise ProgrammeQueryUnavailableError
    result: list[staffing.ProgrammeStaffingHistoryEntry] = []
    after = 0
    while after < current.version:
        page = staffing.load_programme_staffing_history(
            request,
            requirement_id=current.requirement_id,
            through_version=current.version,
            after_version=after,
            authorizer=authorizer,
        )
        expected = min(current.version - after, staffing.STAFFING_HISTORY_PAGE_SIZE)
        if (
            page.through_version != current.version
            or len(page.entries) != expected
            or any(
                row.requirement.requirement_id != current.requirement_id
                or row.requirement.occurrence_id != current.occurrence_id
                or row.requirement.version != after + index + 1
                for index, row in enumerate(page.entries)
            )
        ):
            raise ProgrammeQueryUnavailableError
        result.extend(page.entries)
        after += len(page.entries)
        if page.next_after_version != (after if after < current.version else None):
            raise ProgrammeQueryUnavailableError
    if result[-1].requirement != current:
        raise ProgrammeQueryUnavailableError
    return tuple(result)


def load_programme_exit_item(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    correlation_id: UUID,
    reason: str,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitItem:
    """Collect one item's bounded evidence without expanding any owner's ceiling.

    Parameters
    ----------
    actor_id : UUID
        Authenticated principal subject to all current independent field checks.
    organization_id : UUID
        Exact expected tenant, never an archive-discovery filter.
    edition_id : UUID
        Exact edition admitted by the existing Programme policy.
    item_id : UUID
        Known Programme item within that scope.
    correlation_id : UUID
        Server-owned trace joining minimized sensitive-read audits.
    reason : str
        Required bounded sensitive-read rationale for the composed collection.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Existing owner policy, not a new export grant or root bypass.

    Returns
    -------
    ProgrammeExitItem
        Complete within these bounded layers or refusal, never a partial archive.

    Notes
    -----
    Every field set is checked before collection and before return. The actual
    host roster reader first fences parent/edition scope and locks the actor and
    related people in canonical identifier order. Only then may the core reader
    acquire its actor lock. Those locks remain in the outer audited transaction.
    Current source versions must agree; histories must end at their exact current
    projections. Existing host readers withhold private or obsolete availability.
    Source bindings, placement decisions, other owners, serializers, files, large
    volume handling and retrieval authorization remain separate unfinished work.
    """
    item_id = require_uuid(item_id, field="item_id")
    scope: core._Scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "authorizer": authorizer,
    }
    host_request = hosts.ProgrammeHostReadRequest(
        actor_id, organization_id, edition_id, item_id, correlation_id, "programme-exit"
    )
    staffing_request = staffing.ProgrammeStaffingReadRequest(
        actor_id, organization_id, edition_id, item_id, correlation_id, "programme-exit"
    )

    def authorize() -> None:
        for capability, fields in _FIELDS:
            authorize_programme_scope(
                **scope, capability_code=capability, requested_fields=fields
            )

    def load() -> ProgrammeExitItem:
        authorize()
        # This owner locks the complete person set before any actor-only reader.
        roster = hosts.load_programme_host_roster(host_request, authorizer=authorizer)
        item_core = core.load_programme_exit_core(
            **scope, item_id=item_id, correlation_id=correlation_id, reason=reason
        )
        dependencies = hosts.load_programme_host_dependencies(
            host_request, authorizer=authorizer
        )
        overview = staffing.load_programme_staffing_requirements(
            staffing_request, authorizer=authorizer
        )
        current = item_core.private.item
        host_ids = {row.relationship.host_id for row in roster.entries}
        dependency_ids = {row.host_id for row in dependencies.hosts}
        requirement_ids = {row.requirement_id for row in overview.requirements}
        if (
            current.id != item_id
            or dependencies.item_id != item_id
            or overview.item_id != item_id
            or not (
                current.aggregate_version
                == roster.item_version
                == dependencies.item_version
                == overview.item_version
            )
            or current.lifecycle != overview.item_lifecycle
            or len(roster.entries) > MAX_HOSTS_PER_ITEM
            or len(host_ids) != len(roster.entries)
            or host_ids != dependency_ids
            or len(dependencies.hosts) != len(host_ids)
            or len(overview.requirements) > MAX_STAFFING_REQUIREMENTS_PER_ITEM
            or len(requirement_ids) != len(overview.requirements)
        ):
            raise ProgrammeQueryUnavailableError
        versions = {
            row.relationship.host_id: row.relationship.version for row in roster.entries
        }
        if any(row.host_version != versions[row.host_id] for row in dependencies.hosts):
            raise ProgrammeQueryUnavailableError
        result = ProgrammeExitItem(
            item_core,
            roster,
            tuple(
                _host_history(host_request, row.relationship, authorizer=authorizer)
                for row in roster.entries
            ),
            dependencies,
            overview,
            tuple(
                _staffing_history(staffing_request, row, authorizer=authorizer)
                for row in overview.requirements
            ),
        )
        authorize()
        return result

    return _authorized_query(
        **scope,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=core.PROGRAMME_EXIT_CORE_FIELDS[0][1],
        operation="programme.query.exit_item",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda _result: 1,
        reason=reason,
        correlation_id=correlation_id,
        source_channel="programme-exit",
    )
