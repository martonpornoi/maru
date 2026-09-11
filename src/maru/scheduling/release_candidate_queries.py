"""Complete minimized candidate source for independently owned release checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.workforce.programme_references import lock_programme_staffing_scope

from .adoption import SCHEDULING_RELEASE_SOURCE_ADAPTER
from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_PLANNING,
    AuthorizedSchedulingScope,
    SchedulingAuthorizationDeniedError,
    SchedulingAuthorizer,
    authorize_scheduling_scope,
)
from .command_support import SchedulingUnavailableError
from .evaluation_sources import _placement_facts
from .inputs import require_identifier, require_version
from .models import SchedulingCandidateRevision
from .planning_queries import PLANNING_FIELDS, SchedulingReadRequest, _audit

if TYPE_CHECKING:
    from uuid import UUID

    from .conflicts import SchedulingPlacementFacts


@dataclass(frozen=True, slots=True)
class SchedulingReleaseCandidateSource:
    """Exact complete candidate identity and placement facts without private copy.

    Attributes
    ----------
    candidate_id
        Current explicit private alternative.
    revision_id
        Exact immutable selected manifest.
    candidate_version
        Current alternative command version.
    edition_version
        Current Events envelope/lifecycle version.
    manifest_digest
        Digest verified against complete retained membership by Scheduling.
    placements
        Every selected placement, including exact item/occurrence/day references
        and selected presence intervals; no private host availability is included.
    """

    candidate_id: UUID
    revision_id: UUID
    candidate_version: int
    edition_version: int
    manifest_digest: str
    placements: tuple[SchedulingPlacementFacts, ...]


def _authorize(
    request: SchedulingReadRequest, authorizer: SchedulingAuthorizer
) -> AuthorizedSchedulingScope:
    scope = authorize_scheduling_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=VIEW_PLANNING,
        requested_fields=PLANNING_FIELDS,
        authorizer=authorizer,
    )
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, SCHEDULING_RELEASE_SOURCE_ADAPTER
    ):
        raise SchedulingAuthorizationDeniedError
    return scope


def load_release_candidate_source(
    request: SchedulingReadRequest,
    *,
    candidate_id: UUID,
    candidate_revision_id: UUID,
    expected_candidate_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingReleaseCandidateSource:
    """Read one current complete candidate under shared parent locks and audit.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actor, exact tenant/edition and trace attribution.
    candidate_id : UUID
        Selected alternative, validated only after independent admission.
    candidate_revision_id : UUID
        Exact selected immutable manifest, not a latest-row discovery hint.
    expected_candidate_version : int
        Current optimistic candidate version required by the caller's preview.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Real policy or its existing doubly guarded isolated-test substitute.

    Returns
    -------
    SchedulingReleaseCandidateSource
        Complete minimized facts, not a reusable authorization or approval token.

    Raises
    ------
    SchedulingUnavailableError
        If lifecycle, exact selection or complete source membership is unavailable.

    Notes
    -----
    Current profiles omit the new exact adapter. Authority is rechecked before
    audit and disclosure. Shared parent locks remain held in a surrounding
    transaction; this reader deliberately takes no actor-only person lock before
    a composing collector has resolved its complete canonical person set.
    A later publication must repeat collection and its own authority checks.
    """
    for value in (
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    ):
        require_identifier(value)
    _authorize(request, authorizer)
    require_identifier(candidate_id)
    require_identifier(candidate_revision_id)
    require_version(expected_candidate_version)
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        scope = _authorize(request, authorizer)
        if not scope.accepts_writes:
            raise SchedulingUnavailableError
        revision = (
            SchedulingCandidateRevision.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                id=candidate_revision_id,
                candidate_id=candidate_id,
                candidate__organization_id=request.organization_id,
                candidate__edition_id=request.edition_id,
                candidate__lifecycle="draft",
                candidate__aggregate_version=expected_candidate_version,
                sequence=expected_candidate_version,
            )
            .only(
                "id",
                "organization_id",
                "edition_id",
                "candidate_id",
                "sequence",
                "placement_count",
                "manifest_digest",
            )
            .first()
        )
        if revision is None or revision.placement_count == 0:
            raise SchedulingUnavailableError
        placements = _placement_facts(revision)
        if len(placements) != revision.placement_count:
            raise SchedulingUnavailableError
        result = SchedulingReleaseCandidateSource(
            candidate_id,
            revision.id,
            revision.sequence,
            scope.edition_version,
            revision.manifest_digest,
            placements,
        )
        scope = _authorize(request, authorizer)
        _audit(request, VIEW_PLANNING, "release_candidate_source", scope=scope)
        return result
