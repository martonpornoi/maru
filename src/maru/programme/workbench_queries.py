"""Coherent, audited owner references for the dormant item workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_PRIVATE,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from .catalogs import MAX_PROGRAMME_ITEMS_PER_EDITION
from .models import ProgrammeEditionControl, ProgrammeItem, ProgrammeWorkingRevision
from .queries import (
    ProgrammePrivateItemProjection,
    ProgrammeQueryUnavailableError,
    ProgrammeTimetableInventoryLimitError,
    ProgrammeTimetableItemProjection,
    ProgrammeWorkingProjection,
    _authorized_query,
    _item_projection,
)

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProgrammeWorkbenchRequest:
    """Carry trusted request scope, never caller-declared permission.

    Attributes
    ----------
    actor_id
        Authenticated principal, reloaded by the owner authorizer.
    organization_id
        Expected exact organization.
    edition_id
        Exact edition, not the session's selected-context assertion.
    correlation_id
        Server-created trace for minimized read and command evidence.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class ProgrammeWorkbenchInventory:
    """Expose complete working labels and the exact creation cursor.

    Attributes
    ----------
    control_version
        Current creation version, zero only for an absent edition control.
    items
        Complete bounded title-only inventory; no summaries or adjacent layers.
    """

    control_version: int
    items: tuple[ProgrammeTimetableItemProjection, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeWorkbenchItem:
    """Bind the displayed private working copy to its exact source reference.

    Attributes
    ----------
    private
        Existing ceilinged item and working fields.
    working_revision_id
        Hidden source reference for approval of this exact displayed revision.
    """

    private: ProgrammePrivateItemProjection
    working_revision_id: UUID


def _lock(scope: ProgrammeWorkbenchRequest, authorizer: ProgrammeAuthorizer) -> None:
    authorize_programme_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=frozenset({"item_summaries", "working_information"}),
        authorizer=authorizer,
        lock=True,
    )


def load_programme_workbench_inventory(
    scope: ProgrammeWorkbenchRequest,
    *,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeWorkbenchInventory:
    """Read complete labels and the creation version under canonical scope locks.

    Parameters
    ----------
    scope : ProgrammeWorkbenchRequest
        Trusted authenticated scope and trace, reauthorized by Programme.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Existing exact policy or doubly guarded native-test authorizer.

    Returns
    -------
    ProgrammeWorkbenchInventory
        One coherent inventory with no private summary or other layer.

    Notes
    -----
    The guarded loader propagates ProgrammeTimetableInventoryLimitError rather
    than returning a truncated inventory, and ProgrammeQueryUnavailableError
    when retained item and working evidence are incomplete.
    """

    def load() -> ProgrammeWorkbenchInventory:
        _lock(scope, authorizer)
        control = ProgrammeEditionControl.objects.filter(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        ).first()
        items = tuple(
            ProgrammeItem.objects.filter(
                organization_id=scope.organization_id, edition_id=scope.edition_id
            ).order_by("created_at", "id")[: MAX_PROGRAMME_ITEMS_PER_EDITION + 1]
        )
        if len(items) > MAX_PROGRAMME_ITEMS_PER_EDITION:
            raise ProgrammeTimetableInventoryLimitError
        if items and control is None:
            raise ProgrammeQueryUnavailableError
        working = {
            revision.item_id: revision
            for revision in ProgrammeWorkingRevision.objects.filter(
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                item_id__in=tuple(item.id for item in items),
            )
            .order_by("item_id", "-sequence", "-id")
            .distinct("item_id")
            .only("id", "item_id", "internal_title", "item_version")
        }
        if any(item.id not in working for item in items):
            raise ProgrammeQueryUnavailableError
        return ProgrammeWorkbenchInventory(
            control.aggregate_version if control else 0,
            tuple(
                ProgrammeTimetableItemProjection(
                    _item_projection(item),
                    working[item.id].internal_title,
                    working[item.id].item_version,
                )
                for item in items
            ),
        )

    return _authorized_query(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=frozenset({"item_summaries", "working_information"}),
        operation="programme.query.workbench_inventory",
        loader=load,
        target_type="events.edition",
        target_id=scope.edition_id,
        target_count=lambda result: len(result.items),
        reason="Select private Programme items and prepare organizer core work",
        correlation_id=scope.correlation_id,
        source_channel="programme-workbench",
        authorizer=authorizer,
    )


def load_programme_workbench_item(
    scope: ProgrammeWorkbenchRequest,
    *,
    item_id: UUID,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeWorkbenchItem:
    """Read an item version and its displayed working source atomically.

    Parameters
    ----------
    scope : ProgrammeWorkbenchRequest
        Trusted authenticated scope and trace, reauthorized by Programme.
    item_id : UUID
        Exact selected item; foreign or missing scope is non-disclosing.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Existing exact policy or doubly guarded native-test authorizer.

    Returns
    -------
    ProgrammeWorkbenchItem
        Working fields and source identity from one protected scope.

    Notes
    -----
    The guarded loader propagates ProgrammeQueryUnavailableError when the item
    or its working source is unavailable in the exact scope.
    """

    def load() -> ProgrammeWorkbenchItem:
        _lock(scope, authorizer)
        item = ProgrammeItem.objects.filter(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            id=item_id,
        ).first()
        working = (
            ProgrammeWorkingRevision.objects.filter(
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                item_id=item_id,
            )
            .order_by("-sequence", "-id")
            .first()
        )
        if item is None or working is None:
            raise ProgrammeQueryUnavailableError
        return ProgrammeWorkbenchItem(
            ProgrammePrivateItemProjection(
                _item_projection(item),
                ProgrammeWorkingProjection(
                    working.internal_title,
                    working.working_summary,
                    working.item_version,
                ),
            ),
            working.id,
        )

    return _authorized_query(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=frozenset({"item_summaries", "working_information"}),
        operation="programme.query.workbench_item",
        loader=load,
        target_type="programme.item",
        target_id=item_id,
        target_count=lambda _result: 1,
        reason="Prepare the selected private Programme item",
        correlation_id=scope.correlation_id,
        source_channel="programme-workbench",
        authorizer=authorizer,
    )
