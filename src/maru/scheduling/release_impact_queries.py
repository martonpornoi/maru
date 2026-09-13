"""Audited exact published-transition geometry without recipient or copy disclosure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_HISTORY
from .catalogs import MAX_OCCURRENCES
from .command_support import SchedulingUnavailableError
from .inputs import require_identifier
from .models import SchedulingPlacementRevision, SchedulingRelease
from .planning_queries import HISTORY_FIELDS, _read
from .release_impact import (
    ReleaseSelectionChange,
    compare_release_selections,
)
from .release_queries import (
    RELEASE_MANIFEST_FIELDS,
    ProgrammeReleaseManifest,
    ProgrammeReleaseState,
    _manifest,
)
from .time_rules import SchedulingEnvelope

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import SchedulingAuthorizer
    from .planning_queries import SchedulingReadRequest


@dataclass(frozen=True, slots=True)
class ReleasedChangeGeometry:
    """Immutable Scheduling geometry with opaque room/day references only.

    Attributes
    ----------
    placement_id
        Exact immutable placement selected by the checked canonical artifact.
    day_id
        Stable service-day identity, not its private display label.
    space_id
        Exact Venue selection; dereferencing names needs independent authority.
    envelope
        Selected preparation, delivery and teardown intervals, never Shift work.
    """

    placement_id: UUID
    day_id: UUID
    space_id: UUID
    envelope: SchedulingEnvelope


@dataclass(frozen=True, slots=True)
class ReleasedOccurrenceChange:
    """Exact membership/reference change with independently compared visible geometry.

    Attributes
    ----------
    selection
        Stable occurrence, membership kind and exact placement/copy references.
    before
        Earlier released geometry, absent only for an actual addition.
    after
        Later released geometry, absent only for an actual removal.
    geometry_fields
        Closed changed day/room/phase fields for retained occurrences. An empty
        tuple does not turn an otherwise changed reference into unchanged work.
    """

    selection: ReleaseSelectionChange
    before: ReleasedChangeGeometry | None
    after: ReleasedChangeGeometry | None
    geometry_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeReleaseImpact:
    """One checked retained publication transition, not a communication receipt.

    Attributes
    ----------
    release_id
        Exact requested published release, not a private candidate.
    previous_release_id
        Its retained publication predecessor, absent after an empty active pointer.
    release_version
        Immutable pointer version at publication, not the current pointer version.
    observed_pointer_version
        Current pointer version checked around the composition.
    is_active
        Whether the target remains the current pointer target at this observation.
    before_state
        Current disclosure/safety state of the predecessor, or absent.
    after_state
        Current disclosure/safety state of the target.
    changes
        Complete comparison, or None when governing state suppresses either side.
        None is not an empty comparison or a claim that all events were removed.
    """

    release_id: UUID
    previous_release_id: UUID | None
    release_version: int
    observed_pointer_version: int
    is_active: bool
    before_state: ProgrammeReleaseState
    after_state: ProgrammeReleaseState
    changes: tuple[ReleasedOccurrenceChange, ...] | None


def _geometry(
    request: SchedulingReadRequest, manifest: ProgrammeReleaseManifest
) -> dict[UUID, ReleasedChangeGeometry]:
    selected = {row.placement_id: row for row in manifest.selections}
    rows = tuple(
        SchedulingPlacementRevision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            id__in=selected,
            occurrence_revision__organization_id=request.organization_id,
            occurrence_revision__edition_id=request.edition_id,
            occurrence_revision__occurrence__organization_id=request.organization_id,
            occurrence_revision__occurrence__edition_id=request.edition_id,
            day_revision__organization_id=request.organization_id,
            day_revision__edition_id=request.edition_id,
        )
        .order_by("id")
        .values_list(
            "id",
            "occurrence_revision__occurrence_id",
            "day_revision__day_id",
            "space_selection_id",
            "day_revision__starts_at",
            "day_revision__ends_at",
            "setup_starts_at",
            "effective_starts_at",
            "effective_ends_at",
            "teardown_ends_at",
        )[: MAX_OCCURRENCES + 1]
    )
    if not 1 <= len(rows) == len(selected) <= MAX_OCCURRENCES:
        raise SchedulingUnavailableError
    result = {}
    for (
        placement,
        occurrence,
        day,
        space,
        day_start,
        day_end,
        setup,
        start,
        end,
        teardown,
    ) in rows:
        if (
            placement not in selected
            or selected[placement].occurrence_id != occurrence
            or occurrence in result
            or not day_start <= setup <= start < end <= teardown <= day_end
        ):
            raise SchedulingUnavailableError
        result[occurrence] = ReleasedChangeGeometry(
            placement, day, space, SchedulingEnvelope(setup, start, end, teardown)
        )
    return result


def _changed_geometry(
    before: ReleasedChangeGeometry | None, after: ReleasedChangeGeometry | None
) -> tuple[str, ...]:
    if before is None or after is None:
        return ()
    return tuple(
        name
        for name in ("day_id", "space_id")
        if getattr(before, name) != getattr(after, name)
    ) + tuple(
        name
        for name in (
            "setup_starts_at",
            "effective_starts_at",
            "effective_ends_at",
            "teardown_ends_at",
        )
        if getattr(before.envelope, name) != getattr(after.envelope, name)
    )


def _load(request: SchedulingReadRequest, release_id: UUID) -> ProgrammeReleaseImpact:
    require_identifier(release_id)
    release = (
        SchedulingRelease.objects.filter(
            id=release_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
        )
        .only("id", "previous_release_id", "pointer_version")
        .first()
    )
    if release is None:
        raise SchedulingUnavailableError

    def manifests() -> tuple[ProgrammeReleaseManifest | None, ProgrammeReleaseManifest]:
        ownership = {
            "organization_id": request.organization_id,
            "edition_id": request.edition_id,
        }
        before = (
            _manifest(**ownership, release_id=release.previous_release_id)
            if release.previous_release_id is not None
            else None
        )
        return before, _manifest(**ownership, release_id=release.id)

    before, after = manifests()
    if before is not None and before.pointer_version != after.pointer_version:
        raise SchedulingUnavailableError
    changes = None
    if after.state is ProgrammeReleaseState.AVAILABLE and (
        before is None or before.state is ProgrammeReleaseState.AVAILABLE
    ):
        prior = _geometry(request, before) if before is not None else {}
        current = _geometry(request, after)
        impact = compare_release_selections(
            before=before.selections if before is not None else (),
            after=after.selections,
        )
        changes = tuple(
            ReleasedOccurrenceChange(
                selection,
                prior.get(selection.occurrence_id),
                current.get(selection.occurrence_id),
                _changed_geometry(
                    prior.get(selection.occurrence_id),
                    current.get(selection.occurrence_id),
                ),
            )
            for selection in impact.changes
        )
    if manifests() != (before, after):
        raise SchedulingUnavailableError
    return ProgrammeReleaseImpact(
        release.id,
        release.previous_release_id,
        release.pointer_version,
        after.pointer_version,
        after.is_active,
        before.state if before is not None else ProgrammeReleaseState.ABSENT,
        after.state,
        changes,
    )


def load_programme_release_impact(
    request: SchedulingReadRequest,
    *,
    release_id: UUID,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeReleaseImpact:
    """Compare one exact publication and its retained predecessor under history policy.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actor, tenant, edition and trace attribution; not permission.
    release_id : UUID
        Exact retained publication. The caller cannot substitute its predecessor.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary exact-profile policy or the existing gated synthetic-test seam.

    Returns
    -------
    ProgrammeReleaseImpact
        Audited complete geometry and opaque copy references, or explicit suppressed
        comparison when either retained side is withdrawn or invalidated.

    Notes
    -----
    Both history field ceilings are required before any release lookup and again
    before mandatory audit/disclosure. Canonical parent locks and repeated native
    manifest checks reject moving evidence. Foreign or missing IDs remain generic
    unavailable; malformed IDs are validated only after scope admission. This
    query reads no Programme prose, person, recipient, contact or Workforce work,
    and grants no serving, notification, acknowledgement or mutation authority.
    """
    return _read(
        request,
        capability=VIEW_HISTORY,
        fields=HISTORY_FIELDS | RELEASE_MANIFEST_FIELDS,
        purpose="release_impact",
        authorizer=authorizer,
        loader=lambda _scope: _load(request, release_id),
    )
