"""Audited creation-cursor preparation without private Programme inventory reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_ITEMS,
    authorize_programme_scope,
)
from .models import ProgrammeEditionControl, ProgrammeItem
from .queries import ProgrammeQueryUnavailableError, _authorized_query

if TYPE_CHECKING:
    from .authorization import ProgrammeAuthorizer
    from .workbench_queries import ProgrammeWorkbenchRequest


@dataclass(frozen=True, slots=True)
class ProgrammeCreationState:
    """Expose only the original creation cursor and a planning-state hint.

    Attributes
    ----------
    control_version : int
        Exact edition creation cursor, zero only for absent unused control.
    writable : bool
        Whether planning is open, not proof of capacity or command admission.
    """

    control_version: int
    writable: bool


def load_programme_creation_state(
    scope: ProgrammeWorkbenchRequest,
    *,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeCreationState:
    """Prepare item creation under manage authority without reading private titles.

    Parameters
    ----------
    scope : ProgrammeWorkbenchRequest
        Trusted actor, organization, edition and server correlation identifiers.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real owner policy or the existing doubly guarded test seam.

    Returns
    -------
    ProgrammeCreationState
        Locked, audited cursor and planning hint with no private inventory.

    Notes
    -----
    An absent control with existing items is unavailable, never version zero.
    The unchanged creation command independently rechecks capacity and version.
    """

    def load() -> ProgrammeCreationState:
        admitted = authorize_programme_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            capability_code=PROGRAMME_MANAGE_ITEMS,
            requested_fields=frozenset(),
            authorizer=authorizer,
            lock=True,
        )
        identifiers = {
            "organization_id": scope.organization_id,
            "edition_id": scope.edition_id,
        }
        control = ProgrammeEditionControl.objects.filter(**identifiers).first()
        if control is None and ProgrammeItem.objects.filter(**identifiers).exists():
            raise ProgrammeQueryUnavailableError
        return ProgrammeCreationState(
            control.aggregate_version if control is not None else 0,
            admitted.accepts_private_planning_writes,
        )

    return _authorized_query(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        requested_fields=frozenset(),
        operation="programme.query.creation_state",
        loader=load,
        target_type="events.edition",
        target_id=scope.edition_id,
        target_count=lambda _result: 1,
        reason="Prepare an explicit private Programme item creation",
        correlation_id=scope.correlation_id,
        source_channel="programme-conversion",
        authorizer=authorizer,
    )
