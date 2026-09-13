"""Dormant continuity admission around existing independent owner read boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import (
    EditionAdoptionProfileReference,
    edition_adoption_profile_reference,
)

from .adoption import SCHEDULING_CONTINUITY_ADAPTER
from .authorization import SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError
from .continuity_operator_source import operator_continuity_projection
from .continuity_protocol import ContinuityScope, _scope_document
from .continuity_sources import (
    personal_continuity_projection,
    public_continuity_projection,
)
from .inputs import require_identifier
from .operator_output_queries import load_operator_run_sheet
from .operator_scope import OperatorReadRequest, OperatorScopeKind
from .output_queries import load_public_programme_timetable
from .personal_output_queries import load_personal_timetable

if TYPE_CHECKING:
    from uuid import UUID

    from .continuity_payload import ContinuityProjection


def _admitted(scope: ContinuityScope) -> EditionAdoptionProfileReference:
    profile = edition_adoption_profile_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, SCHEDULING_CONTINUITY_ADAPTER
    ):
        raise SchedulingAuthorizationDeniedError
    return profile


def _source(scope: ContinuityScope, correlation_id: UUID) -> ContinuityProjection:
    ownership = {
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
    }
    if scope.audience == "public":
        return public_continuity_projection(
            load_public_programme_timetable(**ownership), **ownership
        )
    if scope.actor_id is None:
        raise SchedulingAuthorizationDeniedError
    if scope.audience == "exact_person":
        return personal_continuity_projection(
            load_personal_timetable(
                actor_id=scope.actor_id, correlation_id=correlation_id, **ownership
            ),
            actor_id=scope.actor_id,
            **ownership,
        )
    if scope.target_id is None:
        raise SchedulingAuthorizationDeniedError
    request = OperatorReadRequest(
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        correlation_id,
        OperatorScopeKind(scope.kind),
        scope.target_id,
    )
    return operator_continuity_projection(
        load_operator_run_sheet(request, layers=frozenset(scope.layers)), scope=scope
    )


def load_continuity_projection(
    scope: ContinuityScope, *, correlation_id: UUID
) -> ContinuityProjection:
    """Read a complete on-site view without substituting continuity for owner authority.

    Parameters
    ----------
    scope : ContinuityScope
        Exact request purpose with an authenticated actor for private audiences.
    correlation_id : UUID
        Server-created attribution for the existing mandatory sensitive owner audits.

    Returns
    -------
    ContinuityProjection
        Complete fresh owner output with release, instruction and work state preserved.

    Raises
    ------
    SchedulingUnavailableError
        If the pinned profile changes or database evidence fails during composition.

    Notes
    -----
    Invalid input and owner/adoption denial propagate without content. Parent and
    actor locks, final owner rechecks and sensitive audits remain in the existing
    reads. The outer transaction retains their locks through the final profile check;
    it adds no competing lock order. No profile, grant, cache or relay is activated.
    """
    _scope_document(scope)
    require_identifier(correlation_id)
    try:
        with transaction.atomic():
            profile = _admitted(scope)
            result = _source(scope, correlation_id)
            if _admitted(scope) != profile:
                raise SchedulingUnavailableError
            return result
    except DatabaseError as error:
        raise SchedulingUnavailableError from error
