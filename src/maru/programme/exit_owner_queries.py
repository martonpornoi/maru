"""Compose complete bounded Programme-owned exit evidence under one locked read."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from maru.identity.queries import (
    MAX_PERSON_REFERENCE_BATCH,
    lock_account_references_for_evidence,
)
from maru.workforce.programme_references import lock_programme_staffing_scope

from .authorization import DEFAULT_PROGRAMME_AUTHORIZER, PROGRAMME_EXPORT_ARCHIVE
from .catalogs import MAX_PROGRAMME_ITEMS_PER_EDITION
from .exit_item_queries import ProgrammeExitItem, load_programme_exit_item
from .exit_lineage_queries import (
    ProgrammeExitLineage,
    _admit_lineage,
    load_programme_exit_lineage,
)
from .exit_placement_queries import (
    ProgrammeExitPlacementStream,
    load_programme_exit_placement_histories,
)
from .models import ProgrammeHostRelationship, ProgrammeItem
from .placement_queries import ProgrammePlacementReadRequest
from .queries import ProgrammeQueryUnavailableError, _authorized_query

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import ProgrammeAuthorizer
    from .exit_core_queries import _Scope

MAX_OWNER_LINEAGE_ROWS: Final = 150_000


@dataclass(frozen=True, slots=True)
class ProgrammeExitOwnerItem:
    """Joined independently protected content, retained decisions and lineage.

    Attributes
    ----------
    content, lineage, placements
        Exact-item evidence under the original owner permissions. Private contents
        stay out of repr; placement conclusions remain historical, not current fit.
    """

    content: ProgrammeExitItem = field(repr=False)
    lineage: ProgrammeExitLineage = field(repr=False)
    placements: tuple[ProgrammeExitPlacementStream, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProgrammeExitOwner:
    """One complete bounded owner's evidence, not the complete multi-owner package.

    Attributes
    ----------
    organization_id, edition_id
        Exact independently admitted scope.
    items
        Every retained item in UUID order, including retired items; empty is valid
        only after current source/export admission and successful audit.
    """

    organization_id: UUID = field(repr=False)
    edition_id: UUID = field(repr=False)
    items: tuple[ProgrammeExitOwnerItem, ...] = field(repr=False)


def load_programme_exit_owner(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    reason: str,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitOwner:
    """Collect this owner's complete edition without per-item person-lock inversion.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated requester with export and independent source rights.
    organization_id : UUID
        Exact expected tenant, never inferred from a selected source record.
    edition_id : UUID
        Exact edition whose complete retained Programme inventory is requested.
    correlation_id : UUID
        Server-owned trace joining required minimized owner read audits.
    reason : str
        Required bounded sensitive-read purpose.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Ordinary current policy with the existing sealed substitute guard.

    Returns
    -------
    ProgrammeExitOwner
        Complete bounded owned evidence, never a partial success or download grant.

    Notes
    -----
    The parent/edition fence precedes inventory and the complete requester/host
    person lock set. No actor-only lock occurs before that set. Cross-owner
    composition must prelock its larger complete closure in canonical order;
    this owner cannot discover private people or sources in another module.
    Refusal, revocation or failed mandatory audit returns no partial owner data.
    """
    scope: _Scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "authorizer": authorizer,
    }
    request = ProgrammePlacementReadRequest(
        actor_id, organization_id, edition_id, correlation_id, "programme-exit"
    )

    def collect() -> ProgrammeExitOwner:
        _admit_lineage(scope, request)
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        _admit_lineage(scope, request)
        item_ids = tuple(
            ProgrammeItem.objects.filter(
                organization_id=organization_id, edition_id=edition_id
            )
            .order_by("id")
            .values_list("id", flat=True)[: MAX_PROGRAMME_ITEMS_PER_EDITION + 1]
        )
        if len(item_ids) > MAX_PROGRAMME_ITEMS_PER_EDITION:
            raise ProgrammeQueryUnavailableError
        # Do this before *any* audited child read: an audit FK can implicitly
        # acquire an actor key-share lock and invert the complete person order.
        people = tuple(
            sorted(
                {
                    actor_id,
                    *ProgrammeHostRelationship.objects.filter(
                        organization_id=organization_id,
                        edition_id=edition_id,
                        item_id__in=item_ids,
                    )
                    .order_by("account_id")
                    .values_list("account_id", flat=True)
                    .distinct()[: MAX_PERSON_REFERENCE_BATCH + 1],
                }
            )
        )
        if (
            len(people) > MAX_PERSON_REFERENCE_BATCH
            or lock_account_references_for_evidence(account_ids=people) != people
        ):
            raise ProgrammeQueryUnavailableError
        row_count = 0
        result = []
        for item_id in item_ids:
            lineage = load_programme_exit_lineage(
                **scope, item_id=item_id, correlation_id=correlation_id, reason=reason
            )
            row_count += sum(len(group.rows) for group in lineage.collections)
            if row_count > MAX_OWNER_LINEAGE_ROWS:
                raise ProgrammeQueryUnavailableError
            content = load_programme_exit_item(
                **scope, item_id=item_id, correlation_id=correlation_id, reason=reason
            )
            item = content.core.private.item
            if (
                item.id != item_id
                or lineage.item_id != item_id
                or item.aggregate_version != lineage.item_version
            ):
                raise ProgrammeQueryUnavailableError
            placements = load_programme_exit_placement_histories(
                request, item_id=item_id, reason=reason, authorizer=authorizer
            )
            result.append(ProgrammeExitOwnerItem(content, lineage, placements))
        _admit_lineage(scope, request)
        return ProgrammeExitOwner(organization_id, edition_id, tuple(result))

    return _authorized_query(
        **scope,
        capability_code=PROGRAMME_EXPORT_ARCHIVE,
        requested_fields=frozenset({"source_lineage"}),
        operation="programme.query.exit_owner",
        loader=collect,
        target_type="events.event_edition",
        target_id=edition_id,
        target_count=lambda result: len(result.items),
        reason=reason,
        correlation_id=correlation_id,
        source_channel="programme-exit",
    )
