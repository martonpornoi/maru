"""Collect bounded retained placement decisions without asserting current fitness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from maru.workforce.programme_references import lock_programme_staffing_scope

from . import placement_queries as placements
from .authorization import DEFAULT_PROGRAMME_AUTHORIZER, PROGRAMME_VIEW_DELIVERY
from .commands import ProgrammeUnavailableError
from .inputs import require_uuid
from .placement_queries import (
    ProgrammePlacementReadRequest,
    _admit,
    _history_fields,
)
from .queries import _authorized_query
from .release_inputs import MAX_PLACEMENT_DECISIONS
from .release_inputs import ProgrammePlacementDecisionKind as Kind

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import ProgrammeAuthorizer

MAX_EXIT_PLACEMENT_STREAMS: Final = 2_000
MAX_EXIT_PLACEMENT_RECORDS: Final = 20_000


@dataclass(frozen=True, slots=True)
class ProgrammeExitPlacementStream:
    """One retained independent decision stream, not current source approval.

    Attributes
    ----------
    kind, head
        Closed assessment purpose, opaque placement and fixed inclusive sequence.
    entries
        Complete retained decision history, including withdrawal and rationale.
        Current Scheduling, Venue and Workforce facts are not dereferenced.
    """

    kind: Kind = field(repr=False)
    head: placements.ProgrammePlacementHistoryHead = field(repr=False)
    entries: tuple[placements.ProgrammePlacementHistoryEntry, ...] = field(repr=False)


def _history(
    request: ProgrammePlacementReadRequest,
    *,
    item_id: UUID,
    kind: Kind,
    head: placements.ProgrammePlacementHistoryHead,
    authorizer: ProgrammeAuthorizer,
) -> ProgrammeExitPlacementStream:
    entries: list[placements.ProgrammePlacementHistoryEntry] = []
    after = 0
    while after < head.through_sequence:
        page = placements.load_programme_placement_decision_history(
            request,
            item_id=item_id,
            placement_id=head.placement_id,
            kind=kind,
            through_sequence=head.through_sequence,
            after_sequence=after,
            authorizer=authorizer,
        )
        expected = min(
            head.through_sequence - after, placements.PLACEMENT_HISTORY_PAGE_SIZE
        )
        if (
            page.through_sequence != head.through_sequence
            or len(page.entries) != expected
            or any(
                row.sequence != after + index + 1
                for index, row in enumerate(page.entries)
            )
        ):
            raise ProgrammeUnavailableError
        entries.extend(page.entries)
        after += len(page.entries)
        if page.next_after_sequence != (
            after if after < head.through_sequence else None
        ):
            raise ProgrammeUnavailableError
    return ProgrammeExitPlacementStream(kind, head, tuple(entries))


def load_programme_exit_placement_histories(
    request: ProgrammePlacementReadRequest,
    *,
    item_id: UUID,
    reason: str,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeExitPlacementStream, ...]:
    """Collect both independently authorized placement histories for an exact item.

    Parameters
    ----------
    request : ProgrammePlacementReadRequest
        Trusted actor, tenant, edition and retained sensitive-read attribution.
    item_id : UUID
        Exact retained Programme item, never a discovery filter.
    reason : str
        Required bounded purpose for the composed sensitive read.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Existing owner field policy and unchanged placement-adapter admission.

    Returns
    -------
    tuple[ProgrammeExitPlacementStream, ...]
        Complete bounded accessibility-fit and no-staffing histories, or refusal.

    Notes
    -----
    Canonical parent/edition locks remain in the outer audited transaction across
    head and history pages. Final admission checks both separate history ceilings.
    Placement sequences, not the unchanged Programme item version, establish each
    stream's completeness. The 2,000-stream and 20,000-record limits bound this
    collector, not writers or real-convention archive capacity; larger scopes need
    a later volume-aware path. No source approval, schema, route, file, current
    profile, cross-owner snapshot or future-download authority is introduced.
    """
    require_uuid(item_id, field="item_id")
    for name in ("actor_id", "organization_id", "edition_id", "correlation_id"):
        require_uuid(getattr(request, name), field=name)

    def authorize() -> None:
        for kind in Kind:
            _admit(request, kind, authorizer, history=True)

    def load() -> tuple[ProgrammeExitPlacementStream, ...]:
        authorize()
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        streams: list[ProgrammeExitPlacementStream] = []
        records = 0
        for kind in Kind:
            after = None
            while True:
                page = placements.list_programme_placement_history_heads(
                    request,
                    item_id=item_id,
                    kind=kind,
                    after_placement_id=after,
                    authorizer=authorizer,
                )
                if len(page.entries) > placements.PLACEMENT_HISTORY_PAGE_SIZE:
                    raise ProgrammeUnavailableError
                for head in page.entries:
                    if (
                        (after is not None and head.placement_id <= after)
                        or type(head.through_sequence) is not int
                        or not 1 <= head.through_sequence <= MAX_PLACEMENT_DECISIONS + 1
                        or len(streams) >= MAX_EXIT_PLACEMENT_STREAMS
                        or records + head.through_sequence > MAX_EXIT_PLACEMENT_RECORDS
                    ):
                        raise ProgrammeUnavailableError
                    streams.append(
                        _history(
                            request,
                            item_id=item_id,
                            kind=kind,
                            head=head,
                            authorizer=authorizer,
                        )
                    )
                    records += head.through_sequence
                    after = head.placement_id
                if page.next_after_placement_id is None:
                    break
                if not page.entries or page.next_after_placement_id != after:
                    raise ProgrammeUnavailableError
        authorize()
        return tuple(streams)

    return _authorized_query(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=PROGRAMME_VIEW_DELIVERY,
        requested_fields=_history_fields(Kind.ACCESSIBILITY_FIT),
        operation="programme.query.exit_placement_histories",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=len,
        reason=reason,
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
        authorizer=authorizer,
    )
