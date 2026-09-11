"""Audited point-in-time release manifests, never public content or access tokens."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from django.db.models import Count, Max, Min, OuterRef, Subquery

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_HISTORY, VIEW_PLANNING
from .catalogs import MAX_RELEASE_DEPENDENCY_USES
from .command_support import SchedulingUnavailableError
from .inputs import require_identifier
from .models import (
    SchedulingRelease,
    SchedulingReleaseDependencyChange,
    SchedulingReleasePointer,
    SchedulingReleaseWithdrawal,
)
from .planning_queries import _read
from .release_artifacts import (
    CanonicalReleaseArtifact,
    ReleaseArtifactInvalidError,
    ReleaseArtifactSelection,
    verify_canonical_release_artifact,
)
from .release_catalogs import (
    EDITION_RELEASE_DEPENDENCIES,
    GLOBAL_RELEASE_DEPENDENCIES,
    ORGANIZATION_RELEASE_DEPENDENCIES,
    ReleaseDependencyKind,
)
from .release_dependency_rules import (
    ReleaseDependencyChangeWindow,
    ReleaseDependencyConsequence,
    ReleaseDependencyEvidenceInvalidError,
    ReleaseDependencyHorizon,
    ReleaseDependencyUse,
    evaluate_release_dependency,
)
from .release_publication_commands import _placements

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import SchedulingAuthorizer
    from .planning_queries import SchedulingReadRequest

RELEASE_MANIFEST_FIELDS: Final = frozenset({"release_manifest"})


class ProgrammeReleaseState(StrEnum):
    """Non-content result of an authorized exact-scope release check."""

    ABSENT = "absent"
    WITHDRAWN = "withdrawn"
    INVALIDATED = "invalidated"
    AVAILABLE = "available"


@dataclass(frozen=True, slots=True)
class ProgrammeReleaseManifest:
    """Minimized checked references; no artifact bytes, people or private reasons.

    Attributes
    ----------
    state
        Current consequence; unavailable evidence raises instead of guessing.
    pointer_version
        Current edition pointer sequence, zero before any publication.
    release_id
        Selected retained release, if one exists in this authorized scope.
    is_active
        Whether the selected release is the current pointer target.
    selections
        Complete exact immutable references only while available. Consumers
        must independently authorize and recheck owner disclosure when rendering;
        this point-in-time projection grants no enduring serving authority.
    """

    state: ProgrammeReleaseState
    pointer_version: int
    release_id: UUID | None
    is_active: bool
    selections: tuple[ReleaseArtifactSelection, ...]


def _dependency_state(release: SchedulingRelease) -> ProgrammeReleaseState:
    approval = release.approval
    # All current generations and complete range aggregates share ONE database
    # statement snapshot. No loop of separately timed freshness observations, no
    # unbounded journal download, and no key locks followed by owner/person locks.
    changes = (
        SchedulingReleaseDependencyChange.objects.filter(
            dependency_id=OuterRef("dependency_id"),
            generation__gt=OuterRef("captured_generation"),
            generation__lte=OuterRef("dependency__generation"),
        )
        .order_by()
        .values("dependency_id")
        .annotate(
            count=Count("id"),
            first=Min("generation"),
            last=Max("generation"),
            earliest=Min("recorded_at"),
        )
    )
    rows = tuple(
        approval.dependencies.filter(
            organization_id=release.organization_id, edition_id=release.edition_id
        )
        .annotate(
            change_count=Subquery(changes.values("count")),
            first_generation=Subquery(changes.values("first")),
            last_generation=Subquery(changes.values("last")),
            earliest_change=Subquery(changes.values("earliest")),
        )
        .values(
            "captured_generation",
            "horizon",
            "operational_ends_at",
            "dependency__generation",
            "dependency__kind",
            "dependency__organization_id",
            "dependency__edition_id",
            "change_count",
            "first_generation",
            "last_generation",
            "earliest_change",
        )[: MAX_RELEASE_DEPENDENCY_USES + 1]
    )
    if not 1 <= len(rows) == approval.dependency_count <= MAX_RELEASE_DEPENDENCY_USES:
        raise SchedulingUnavailableError
    invalidated = False
    for row in rows:
        try:
            kind = ReleaseDependencyKind(row["dependency__kind"])
            expected_scope = (
                (None, None)
                if kind in GLOBAL_RELEASE_DEPENDENCIES
                else (release.organization_id, None)
                if kind in ORGANIZATION_RELEASE_DEPENDENCIES
                else (release.organization_id, release.edition_id)
                if kind in EDITION_RELEASE_DEPENDENCIES
                else ()
            )
            if (
                row["dependency__organization_id"],
                row["dependency__edition_id"],
            ) != expected_scope:
                raise SchedulingUnavailableError
            consequence = evaluate_release_dependency(
                captured_generation=row["captured_generation"],
                current_generation=row["dependency__generation"],
                horizon=ReleaseDependencyHorizon(row["horizon"]),
                use=ReleaseDependencyUse.SERVING,
                operational_ends_at=row["operational_ends_at"],
                changes=ReleaseDependencyChangeWindow(
                    row["change_count"] or 0,
                    row["first_generation"],
                    row["last_generation"],
                    row["earliest_change"],
                ),
            )
        except (ValueError, ReleaseDependencyEvidenceInvalidError) as error:
            raise SchedulingUnavailableError from error
        if consequence is ReleaseDependencyConsequence.UNAVAILABLE:
            raise SchedulingUnavailableError
        invalidated |= consequence is ReleaseDependencyConsequence.INVALIDATED
    return (
        ProgrammeReleaseState.INVALIDATED
        if invalidated
        else ProgrammeReleaseState.AVAILABLE
    )


def _manifest(
    request: SchedulingReadRequest, release_id: UUID | None
) -> ProgrammeReleaseManifest:
    ownership = {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    pointer = SchedulingReleasePointer.objects.filter(**ownership).first()
    version = pointer.version if pointer else 0
    selected = release_id or (pointer.active_release_id if pointer else None)
    if selected is None:
        return ProgrammeReleaseManifest(
            ProgrammeReleaseState.WITHDRAWN
            if pointer
            else ProgrammeReleaseState.ABSENT,
            pointer_version=version,
            release_id=None,
            is_active=False,
            selections=(),
        )
    release = (
        SchedulingRelease.objects.filter(id=selected, **ownership)
        .select_related("approval")
        .first()
    )
    if release is None:
        raise SchedulingUnavailableError
    active = bool(pointer and pointer.active_release_id == selected)
    if SchedulingReleaseWithdrawal.objects.filter(
        release=release, **ownership
    ).exists():
        return ProgrammeReleaseManifest(
            ProgrammeReleaseState.WITHDRAWN, version, selected, active, ()
        )
    selections = _placements(release.approval)
    artifacts = tuple(release.artifacts.filter(**ownership)[:2])
    if len(artifacts) != 1:
        raise SchedulingUnavailableError
    artifact = artifacts[0]
    try:
        verify_canonical_release_artifact(
            CanonicalReleaseArtifact(
                artifact.contract,
                bytes(artifact.payload),
                artifact.sha256,
                artifact.byte_length,
            ),
            release_id=release.id,
            approval_id=release.approval_id,
            candidate_revision_id=release.approval.candidate_revision_id,
            source_snapshot_digest=release.approval.source_snapshot_digest,
            selections=selections,
        )
    except ReleaseArtifactInvalidError as error:
        raise SchedulingUnavailableError from error
    state = _dependency_state(release)
    return ProgrammeReleaseManifest(
        state,
        version,
        selected,
        active,
        selections if state is ProgrammeReleaseState.AVAILABLE else (),
    )


def load_programme_release_manifest(  # noqa: DOC502 - The guarded read and loader propagate these errors.
    request: SchedulingReadRequest,
    *,
    release_id: UUID | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeReleaseManifest:
    """Read checked current or explicitly selected historical release references.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted attribution, not caller-supplied permission or source evidence.
    release_id : UUID | None, default=None
        Omit for the current pointer. Explicit history requires VIEW_HISTORY
        independently; neither path returns withdrawn/invalidated selections.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary policy or doubly gated synthetic-test substitute.

    Returns
    -------
    ProgrammeReleaseManifest
        One bounded audited point-in-time result, without disclosure authority.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If current exact scope, capability, principal or field authority fails.
    SchedulingUnavailableError
        If retained evidence, complete journal range or required database fails.
    ValidationError
        If trusted identifiers are malformed.
    """

    def loader(_scope: object) -> ProgrammeReleaseManifest:
        if release_id is not None:
            require_identifier(release_id)
        return _manifest(request, release_id)

    return _read(
        request,
        capability=VIEW_HISTORY if release_id is not None else VIEW_PLANNING,
        fields=RELEASE_MANIFEST_FIELDS,
        purpose="release_manifest",
        authorizer=authorizer,
        loader=loader,
    )
