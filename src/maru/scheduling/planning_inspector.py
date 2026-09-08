"""Explicit single-layer Programme composition for the dormant timetable inspector."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.programme import host_queries, queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.host_queries import ProgrammeHostReadRequest

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_PLANNING,
    SchedulingAuthorizationDeniedError,
)
from .command_support import SchedulingUnavailableError
from .inputs import require_identifier
from .planning_queries import PLANNING_FIELDS, _read

if TYPE_CHECKING:
    from typing import TypedDict
    from uuid import UUID

    from maru.programme.host_queries import (
        ProgrammeHostDependencySnapshot,
        ProgrammeHostRosterSnapshot,
    )
    from maru.programme.queries import (
        ProgrammeDeliveryProjection,
        ProgrammePrivateItemProjection,
        ProgrammePublicCopyProjection,
        ProgrammeReadinessConcernProjection,
    )

    from .authorization import AuthorizedSchedulingScope, SchedulingAuthorizer
    from .planning_queries import SchedulingReadRequest

    class _ProgrammeReadScope(TypedDict):
        actor_id: UUID
        organization_id: UUID
        edition_id: UUID
        item_id: UUID
        correlation_id: UUID

    type InspectorData = (
        ProgrammePrivateItemProjection
        | ProgrammeDeliveryProjection
        | ProgrammePublicCopyProjection
        | tuple[ProgrammeReadinessConcernProjection, ...]
        | ProgrammeHostRosterSnapshot
        | ProgrammeHostDependencySnapshot
        | None
    )


class PlanningItemLayer(StrEnum):
    """Closed selectable layers; private Applications review is not included."""

    WORKING = "working"
    PUBLIC_COPY = "public_copy"
    DELIVERY = "delivery"
    READINESS = "readiness"
    HOSTS = "hosts"
    SHARED_AVAILABILITY = "shared_availability"


@dataclass(frozen=True, slots=True)
class PlanningItemInspector:
    """Exactly one current, independently authorized Programme information layer.

    Attributes
    ----------
    item_id
        Explicit selected item, scoped again by its owning query.
    layer
        Exact requested layer; unrelated layers were not loaded.
    data
        That owner's minimized projection, including an honest absent value.
        No historical release, review approval or readiness claim is inferred.
    """

    item_id: UUID
    layer: PlanningItemLayer
    data: InspectorData


def _owner_layer(
    request: SchedulingReadRequest, item_id: UUID, layer: PlanningItemLayer
) -> InspectorData:
    common: _ProgrammeReadScope = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "item_id": item_id,
        "correlation_id": request.correlation_id,
    }
    channel = "scheduling-planning"
    purpose = "Inspect the explicitly selected timetable item layer"
    match layer:
        case PlanningItemLayer.WORKING:
            return queries.load_programme_private_item(
                **common, reason=purpose, source_channel=channel
            )
        case PlanningItemLayer.PUBLIC_COPY:
            return queries.load_programme_public_copy(**common, source_channel=channel)
        case PlanningItemLayer.DELIVERY:
            return queries.load_programme_delivery(
                **common, reason=purpose, source_channel=channel
            )
        case PlanningItemLayer.READINESS:
            return queries.load_programme_readiness(
                **common, reason=purpose, source_channel=channel
            )
        case PlanningItemLayer.HOSTS:
            return host_queries.load_programme_host_roster(
                ProgrammeHostReadRequest(**common, source_channel=channel)
            )
        case PlanningItemLayer.SHARED_AVAILABILITY:
            return host_queries.load_programme_host_dependencies(
                ProgrammeHostReadRequest(**common, source_channel=channel)
            )


def load_scheduling_item_inspector(
    request: SchedulingReadRequest,
    *,
    item_id: UUID,
    layer: PlanningItemLayer,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> PlanningItemInspector:
    """Read only an explicitly selected layer after both owners authorize it.

    This works for items before an occurrence exists. Scheduling grants no
    Programme permission; Programme scopes and audits the selected item/layer.
    Unavailable or denied layers do not fall back to a less protected query.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted exact-edition actor and minimized read-audit attribution.
    item_id : UUID
        Explicit item selected from an independently authorized inventory.
    layer : PlanningItemLayer
        Closed selected information purpose, not arbitrary field names.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary Scheduling policy or its sealed isolated-test substitute.

    Returns
    -------
    PlanningItemInspector
        One owner-backed projection; adjacent private layers were not queried.

    Raises
    ------
    ValidationError
        If the requested layer is not a closed typed selection.
    """
    require_identifier(item_id)
    if not isinstance(layer, PlanningItemLayer):
        raise ValidationError("Select one supported Programme inspector layer.")

    def load(_scope: AuthorizedSchedulingScope) -> PlanningItemInspector:
        try:
            data = _owner_layer(request, item_id, layer)
        except ProgrammeAuthorizationDeniedError as error:
            raise SchedulingAuthorizationDeniedError from error
        except queries.ProgrammeQueryError as error:
            raise SchedulingUnavailableError from error
        return PlanningItemInspector(item_id, layer, data)

    return _read(
        request,
        capability=VIEW_PLANNING,
        fields=PLANNING_FIELDS,
        purpose=f"item_layer_{layer.value}",
        authorizer=authorizer,
        loader=load,
    )
