"""Bounded opaque Programme work lineage for exact Department operator purposes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Count, F, Max, Min, Q

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_scope import (
    OperatorReadRequest,
    OperatorScopeKind,
    operator_read,
)

from .adoption import WORKFORCE_PROGRAMME_STAFFING_ADAPTER
from .models import ProgrammeShiftBinding, ProgrammeShiftBindingRevision, ShiftDemand
from .shift_queries import MAX_SHIFT_DEMANDS

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class OperatorWorkLink:
    """Opaque complete current/retained lineage, not a work or personnel read.

    Attributes
    ----------
    occurrence_id
        Explicitly bound Programme occurrence, never inferred proposal ownership.
    binding_id
        Exact retained binding identity.
    binding_version
        Current binding version validated against complete immutable history.
    demand_id
        Exact current or retained predecessor work identity.
    demand_version
        Current Workforce instruction/lifecycle version.
    current
        Whether the binding currently selects this demand, not work cancellation.
    """

    occurrence_id: UUID
    binding_id: UUID
    binding_version: int
    demand_id: UUID
    demand_version: int
    current: bool


def operator_staffing_adopted(request: OperatorReadRequest) -> bool:
    """Check the exact optional staffing adapter without discovering work records.

    Parameters
    ----------
    request : OperatorReadRequest
        Already admitted operator scope, not a grant for this owner's fields.

    Returns
    -------
    bool
        Whether deliberate Programme staffing adoption is currently declared.

    Notes
    -----
    False is an unadopted layer, never an authorized empty staffing collection.
    Owner content queries must additionally require their own field authority.
    """
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    return profile is not None and profile_allows_adapter(
        profile.code, profile.version, WORKFORCE_PROGRAMME_STAFFING_ADAPTER
    )


def _load_links(
    request: OperatorReadRequest, *, occurrence_ids: set[UUID] | None = None
) -> tuple[OperatorWorkLink, ...]:
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    bindings_query = ProgrammeShiftBinding.objects.filter(**ownership)
    if occurrence_ids is not None:
        bindings_query = bindings_query.filter(occurrence_id__in=occurrence_ids)
    if request.kind is OperatorScopeKind.DEPARTMENT:
        bindings_query = bindings_query.filter(
            Q(demand__position__department_id=request.target_id)
            | Q(revisions__demand__position__department_id=request.target_id)
            | Q(revisions__predecessor__position__department_id=request.target_id)
        )
    bindings = tuple(
        bindings_query.order_by("id")
        .values_list("id", "version", "occurrence_id", "demand_id")
        .distinct()[: MAX_SHIFT_DEMANDS + 1]
    )
    if len(bindings) > MAX_SHIFT_DEMANDS:
        raise SchedulingUnavailableError
    revisions = ProgrammeShiftBindingRevision.objects.filter(
        **ownership, binding_id__in=[row[0] for row in bindings]
    ).order_by()
    histories = {
        row["binding_id"]: row
        for row in revisions.values("binding_id").annotate(
            count=Count("id"), first=Min("sequence"), last=Max("sequence")
        )
    }
    heads = dict(
        revisions.filter(sequence=F("binding__version")).values_list(
            "binding_id", "demand_id"
        )
    )
    for identifier, version, _occurrence, demand in bindings:
        history = histories.get(identifier)
        if (
            history is None
            or history["first"] != 1
            or history["last"] != version
            or history["count"] != version
            or heads.get(identifier) != demand
        ):
            raise SchedulingUnavailableError
    pairs = tuple(
        revisions.values_list("binding_id", "demand_id")
        .union(
            revisions.exclude(predecessor_id=None).values_list(
                "binding_id", "predecessor_id"
            )
        )
        .order_by("binding_id", "demand_id")[: MAX_SHIFT_DEMANDS + 1]
    )
    if len(pairs) > MAX_SHIFT_DEMANDS:
        raise SchedulingUnavailableError
    demands = {
        row[0]: row[1:]
        for row in ShiftDemand.objects.filter(
            **ownership,
            id__in={row[1] for row in pairs},
            position__organization_id=request.organization_id,
            position__edition_id=request.edition_id,
            position__department__organization_id=request.organization_id,
            position__department__edition_id=request.edition_id,
        ).values_list("id", "command_version", "position__department_id")
    }
    if set(demands) != {row[1] for row in pairs}:
        raise SchedulingUnavailableError
    indexed = {row[0]: row for row in bindings}
    return tuple(
        OperatorWorkLink(
            indexed[binding][2],
            binding,
            indexed[binding][1],
            demand,
            demands[demand][0],
            demand == indexed[binding][3],
        )
        for binding, demand in pairs
        if request.kind is not OperatorScopeKind.DEPARTMENT
        or demands[demand][1] == request.target_id
    )


def load_operator_department_work_links(
    request: OperatorReadRequest,
) -> tuple[OperatorWorkLink, ...]:
    """Resolve complete Department-linked current and retained work membership.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact Department purpose, independently authorized by Workforce.

    Returns
    -------
    tuple[OperatorWorkLink, ...]
        Opaque links with current versions, including retained predecessor work.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If the purpose is not Department or deliberate staffing adoption is absent.
    SchedulingUnavailableError
        If bounded immutable lineage is incomplete, inconsistent or changing.

    Notes
    -----
    No Scheduling release lookup occurs here. Names, accepted intervals, private
    reasons, proposals, assignments and account records are never selected.
    Even empty Department membership requires independent scope_links authority.
    """
    with operator_read(
        request,
        capability="workforce.view_operator_staffing",
        fields=frozenset({"scope_links"}),
    ):
        if (
            request.kind is not OperatorScopeKind.DEPARTMENT
            or not operator_staffing_adopted(request)
        ):
            raise SchedulingAuthorizationDeniedError
        result = _load_links(request)
        if not operator_staffing_adopted(request) or _load_links(request) != result:
            raise SchedulingUnavailableError
        return result
