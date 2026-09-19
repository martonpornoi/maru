"""Collect one authorized Programme core, never a complete profile exit archive."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, TypedDict

from . import queries
from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_DELIVERY,
    PROGRAMME_VIEW_DISCUSSION,
    PROGRAMME_VIEW_PRIVATE,
    PROGRAMME_VIEW_READINESS,
    authorize_programme_scope,
)
from .catalogs import (
    MAX_PROGRAMME_DISCUSSION_ENTRIES,
    MAX_PROGRAMME_LAYER_REVISIONS,
    MAX_PROGRAMME_PUBLIC_RENDITIONS,
)
from .inputs import require_uuid
from .queries import _authorized_query

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from .authorization import ProgrammeAuthorizer

MAX_CORE_READINESS_ENTRIES: Final = 21_000
PROGRAMME_EXIT_CORE_FIELDS: Final = (
    (
        PROGRAMME_VIEW_PRIVATE,
        frozenset(
            {
                "item_summaries",
                "working_information",
                "working_history",
                "public_copy_review_history",
            }
        ),
    ),
    (PROGRAMME_VIEW_DELIVERY, frozenset({"delivery_history"})),
    (PROGRAMME_VIEW_DISCUSSION, frozenset({"discussion_entries"})),
    (PROGRAMME_VIEW_READINESS, frozenset({"readiness_history"})),
)


class _Scope(TypedDict):
    """Typed arguments shared by the existing owner authorization boundary."""

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    authorizer: ProgrammeAuthorizer


class _Query(_Scope):
    """Exact item read and retained purpose shared by the existing readers."""

    item_id: UUID
    reason: str
    correlation_id: UUID
    source_channel: str


@dataclass(frozen=True, slots=True)
class ProgrammeExitCore:
    """Complete bounded core histories under their existing independent ceilings.

    Attributes
    ----------
    private
        Current item identity, lifecycle/version and private working projection.
    working, delivery, discussion, readiness, copy_reviews
        Retained histories, not automatically public or authorized for later
        download. Hosts, staffing, source bindings and other owners are absent;
        this is explicitly a core component, not a complete Programme archive.
    """

    private: queries.ProgrammePrivateItemProjection = field(repr=False)
    working: tuple[queries.ProgrammeWorkingHistoryEntryProjection, ...] = field(
        repr=False
    )
    delivery: tuple[queries.ProgrammeDeliveryHistoryEntryProjection, ...] = field(
        repr=False
    )
    discussion: tuple[queries.ProgrammeDiscussionEntryProjection, ...] = field(
        repr=False
    )
    readiness: tuple[queries.ProgrammeReadinessHistoryEntryProjection, ...] = field(
        repr=False
    )
    copy_reviews: tuple[
        queries.ProgrammePublicCopyReviewHistoryEntryProjection, ...
    ] = field(repr=False)


def _sequence_history[EntryT](
    read: Callable[[int | None], tuple[EntryT, ...]],
    sequence: Callable[[EntryT], int],
    maximum: int,
) -> tuple[EntryT, ...]:
    result: list[EntryT] = []
    before = None
    while True:
        page = read(before)
        if (
            len(page) > queries.MAX_PROGRAMME_QUERY_ITEMS
            or len(result) + len(page) > maximum
        ):
            raise queries.ProgrammeQueryUnavailableError
        for entry in page:
            position = sequence(entry)
            if type(position) is not int or not 1 <= position <= maximum:
                raise queries.ProgrammeQueryUnavailableError
            if before is not None and position != before - 1:
                raise queries.ProgrammeQueryUnavailableError
            before = position
            result.append(entry)
        if len(page) < queries.MAX_PROGRAMME_QUERY_ITEMS:
            if before not in (None, 1):
                raise queries.ProgrammeQueryUnavailableError
            return tuple(result)


def _readiness_history(
    read: Callable[
        [queries.ProgrammeReadinessHistoryCursor | None],
        tuple[queries.ProgrammeReadinessHistoryEntryProjection, ...],
    ],
) -> tuple[queries.ProgrammeReadinessHistoryEntryProjection, ...]:
    result: list[queries.ProgrammeReadinessHistoryEntryProjection] = []
    before = None
    groups: dict[tuple[str, str], int] = {}
    while True:
        page = read(before)
        if (
            len(page) > queries.MAX_PROGRAMME_QUERY_ITEMS
            or len(result) + len(page) > MAX_CORE_READINESS_ENTRIES
        ):
            raise queries.ProgrammeQueryUnavailableError
        for entry in page:
            key = (entry.concern, entry.kind)
            if (
                type(entry.sequence) is not int
                or not 1 <= entry.sequence <= MAX_CORE_READINESS_ENTRIES
            ):
                raise queries.ProgrammeQueryUnavailableError
            if key in groups and entry.sequence != groups[key] - 1:
                raise queries.ProgrammeQueryUnavailableError
            groups[key] = entry.sequence
            result.append(entry)
        if len(page) < queries.MAX_PROGRAMME_QUERY_ITEMS:
            if any(last != 1 for last in groups.values()):
                raise queries.ProgrammeQueryUnavailableError
            return tuple(result)
        last = page[-1]
        before = queries.ProgrammeReadinessHistoryCursor(
            last.item_version, last.concern, last.kind, last.sequence
        )


def load_programme_exit_core(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    correlation_id: UUID,
    reason: str,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitCore:
    """Collect one private core through owner readers under canonical scope locks.

    Parameters
    ----------
    actor_id : UUID
        Current authenticated principal, reloaded by the owner authorizer.
    organization_id : UUID
        Exact expected tenant, never a discovery filter.
    edition_id : UUID
        Exact edition with the existing Programme read admission.
    item_id : UUID
        Known selected item within that tenant and edition.
    correlation_id : UUID
        Server-created trace shared by the minimized read audits.
    reason : str
        Required bounded sensitive-read purpose retained by each owner audit.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Existing real policy; only the established guarded native seam may replace it.

    Returns
    -------
    ProgrammeExitCore
        Bounded complete core histories, or refusal rather than truncated records.

    Notes
    -----
    Existing independent field permissions are checked before collection and
    again before return. Canonical parent/edition locks stay in the outer read
    transaction, serializing Programme writers including independent withdrawals.
    Helpers propagate non-disclosing owner errors and required audit failures.
    The 21,000 readiness-entry bound is a collection limit, not a new writer
    ceiling. Larger histories require a later volume-aware export path; nothing
    is silently omitted. This adds no file access, schema, route, export grant,
    portable source attestation, cross-owner snapshot or download authorization.
    """
    item_id = require_uuid(item_id, field="item_id")
    scope: _Scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "authorizer": authorizer,
    }
    common: _Query = {
        **scope,
        "item_id": item_id,
        "reason": reason,
        "correlation_id": correlation_id,
        "source_channel": "programme-exit",
    }

    def authorize(*, lock: bool = False) -> None:
        for capability, fields in PROGRAMME_EXIT_CORE_FIELDS:
            authorize_programme_scope(
                **scope, capability_code=capability, requested_fields=fields, lock=lock
            )

    def load() -> ProgrammeExitCore:
        authorize(lock=True)
        private = queries.load_programme_private_item(**common)
        working = _sequence_history(
            lambda cursor: queries.list_programme_working_history(
                **common, limit=200, before_sequence=cursor
            ),
            lambda entry: entry.sequence,
            MAX_PROGRAMME_LAYER_REVISIONS,
        )
        if (
            not working
            or private.working is None
            or (
                private.working.internal_title,
                private.working.working_summary,
                private.working.item_version,
            )
            != (
                working[0].internal_title,
                working[0].working_summary,
                working[0].item_version,
            )
        ):
            raise queries.ProgrammeQueryUnavailableError
        result = ProgrammeExitCore(
            private,
            working,
            _sequence_history(
                lambda cursor: queries.list_programme_delivery_history(
                    **common, limit=200, before_sequence=cursor
                ),
                lambda entry: entry.sequence,
                MAX_PROGRAMME_LAYER_REVISIONS,
            ),
            _sequence_history(
                lambda cursor: queries.list_programme_discussion(
                    **common, limit=200, before_sequence=cursor
                ),
                lambda entry: entry.sequence,
                MAX_PROGRAMME_DISCUSSION_ENTRIES,
            ),
            _readiness_history(
                lambda cursor: queries.list_programme_readiness_history(
                    **common, limit=200, before=cursor
                )
            ),
            _sequence_history(
                lambda cursor: queries.list_programme_public_copy_review_history(
                    **common, limit=200, before_rendition_number=cursor
                ),
                lambda entry: entry.rendition_number,
                MAX_PROGRAMME_PUBLIC_RENDITIONS,
            ),
        )
        authorize()
        return result

    return _authorized_query(
        **scope,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=PROGRAMME_EXIT_CORE_FIELDS[0][1],
        operation="programme.query.exit_core",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda _result: 1,
        reason=reason,
        correlation_id=correlation_id,
        source_channel="programme-exit",
    )
