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
from .continuity_payload import ContinuityProjection, encode_continuity_payload
from .continuity_protocol import ContinuityScope, _scope_document
from .continuity_sources import (
    personal_continuity_projection,
    public_continuity_projection,
)
from .inputs import require_identifier
from .operator_output_queries import load_operator_run_sheet
from .operator_scope import OperatorReadRequest, OperatorScopeKind
from .output_observation import align_timetable_observation
from .output_queries import load_public_programme_timetable
from .personal_output_queries import load_personal_timetable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


def _admitted(scope: ContinuityScope) -> EditionAdoptionProfileReference:
    profile = edition_adoption_profile_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, SCHEDULING_CONTINUITY_ADAPTER
    ):
        raise SchedulingAuthorizationDeniedError
    return profile


def _source(
    scope: ContinuityScope, correlation_id: UUID, *, observed_at: datetime | None = None
) -> ContinuityProjection:
    ownership = {
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
    }
    if scope.audience == "public":
        public = load_public_programme_timetable(**ownership)
        return public_continuity_projection(
            align_timetable_observation(public, observed_at=observed_at)
            if observed_at is not None
            else public,
            **ownership,
        )
    if scope.actor_id is None:
        raise SchedulingAuthorizationDeniedError
    if scope.audience == "exact_person":
        personal = load_personal_timetable(
            actor_id=scope.actor_id, correlation_id=correlation_id, **ownership
        )
        return personal_continuity_projection(
            align_timetable_observation(personal, observed_at=observed_at)
            if observed_at is not None
            else personal,
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
    operator = load_operator_run_sheet(request, layers=frozenset(scope.layers))
    return operator_continuity_projection(
        align_timetable_observation(operator, observed_at=observed_at)
        if observed_at is not None
        else operator,
        scope=scope,
    )


def load_continuity_projection(
    scope: ContinuityScope,
    *,
    correlation_id: UUID,
    expected: ContinuityProjection | None = None,
) -> ContinuityProjection:
    """Read a complete on-site view without substituting continuity for owner authority.

    Parameters
    ----------
    scope : ContinuityScope
        Exact request purpose with an authenticated actor for private audiences.
    correlation_id : UUID
        Server-created attribution for the existing mandatory sensitive owner audits.
    expected : ContinuityProjection | None, default=None
        Original in-request projection for a final disclosure check, never authority.
        Its complete source digest must still match after aligning only check time.

    Returns
    -------
    ContinuityProjection
        Complete owner output; an expected comparison retains the original observation.

    Raises
    ------
    SchedulingUnavailableError
        If the scope, complete source or profile changes, or current evidence fails.

    Notes
    -----
    Invalid input and owner/adoption denial propagate without content. Parent and
    actor locks, final owner rechecks and sensitive audits remain in the existing
    reads. The outer transaction retains their locks through the final profile check;
    it adds no competing lock order. No profile, grant, cache or relay is activated.
    """
    _scope_document(scope)
    require_identifier(correlation_id)
    if expected is not None:
        if type(expected) is not ContinuityProjection or expected.scope != scope:
            raise SchedulingUnavailableError
        encode_continuity_payload(expected)
    try:
        with transaction.atomic():
            profile = _admitted(scope)
            result = _source(
                scope,
                correlation_id,
                observed_at=expected.observed_at if expected is not None else None,
            )
            if _admitted(scope) != profile or (
                expected is not None and result != expected
            ):
                raise SchedulingUnavailableError
            return result
    except DatabaseError as error:
        raise SchedulingUnavailableError from error
