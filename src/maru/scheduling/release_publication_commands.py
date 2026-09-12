"""Dormant exact approval publication and explicit whole-release withdrawal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db.models import F

from maru.identity.queries import lock_account_references_for_evidence
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER

from .authorization import (
    APPROVE_RELEASE,
    DEFAULT_SCHEDULING_AUTHORIZER,
    PUBLISH_RELEASE,
    WITHDRAW_RELEASE,
    SchedulingAuthorizationDeniedError,
    authorize_scheduling_scope,
)
from .catalogs import MAX_OCCURRENCES, MAX_RELEASE_DEPENDENCY_USES, SchedulingOperation
from .command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
    _CommandTransaction,
    _execute,
)
from .models import (
    SchedulingRelease,
    SchedulingReleaseApproval,
    SchedulingReleaseArtifact,
    SchedulingReleasePointer,
    SchedulingReleaseWithdrawal,
)
from .release_artifacts import (
    CanonicalReleaseArtifact,
    ReleaseArtifactSelection,
    prepare_canonical_release_artifact,
    verify_canonical_release_artifact,
)
from .release_authorship import _load_release_authorship
from .release_capture import _capture_release_generations, _load_release_sources
from .release_eligibility import RELEASE_ELIGIBILITY_POLICY
from .release_inputs import (
    ReleaseCandidateSelection,
    ReleasePublicationIntent,
    ReleaseWithdrawalIntent,
)
from .release_review_commands import _read_request, _require_eligible_approval

if TYPE_CHECKING:
    from maru.programme.authorization import ProgrammeAuthorizer

    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult
    from .inputs import SchedulingCommandRequest
    from .release_capture import _ReleaseSources


@dataclass(frozen=True, slots=True)
class _Publication:
    approval: SchedulingReleaseApproval
    pointer: SchedulingReleasePointer | None
    release_id: UUID
    artifact: CanonicalReleaseArtifact
    added: int
    changed: int
    removed: int


def _pointer(
    request: SchedulingCommandRequest,
    *,
    expected_version: int,
    expected_active: UUID | None,
) -> SchedulingReleasePointer | None:
    pointer = (
        SchedulingReleasePointer.objects.select_for_update()
        .filter(organization_id=request.organization_id, edition_id=request.edition_id)
        .first()
    )
    actual = (pointer.version, pointer.active_release_id) if pointer else (0, None)
    if actual != (expected_version, expected_active):
        raise SchedulingVersionConflictError
    return pointer


def _placements(
    approval: SchedulingReleaseApproval,
) -> tuple[ReleaseArtifactSelection, ...]:
    rows = tuple(
        approval.placements.filter(
            organization_id=approval.organization_id, edition_id=approval.edition_id
        )
        .order_by("occurrence_id")
        .values_list("occurrence_id", "placement_id", "public_rendition_id")[
            : MAX_OCCURRENCES + 1
        ]
    )
    if not 1 <= len(rows) == approval.placement_count <= MAX_OCCURRENCES:
        raise SchedulingUnavailableError
    return tuple(ReleaseArtifactSelection(*row) for row in rows)


def _assert_captures(
    approval: SchedulingReleaseApproval, sources: _ReleaseSources
) -> None:
    current = _capture_release_generations(sources, create_missing=False)
    rows = tuple(
        approval.dependencies.filter(
            organization_id=approval.organization_id, edition_id=approval.edition_id
        ).values_list(
            "dependency_id",
            "captured_generation",
            "approval_placement__placement_id",
            "horizon",
            "operational_ends_at",
        )[: MAX_RELEASE_DEPENDENCY_USES + 1]
    )
    if not 1 <= len(rows) == approval.dependency_count <= MAX_RELEASE_DEPENDENCY_USES:
        raise SchedulingUnavailableError
    if set(rows) != {
        (
            row.dependency_id,
            row.generation,
            row.reference.placement_id,
            row.reference.horizon.value,
            row.reference.operational_ends_at,
        )
        for row in current
    }:
        raise SchedulingVersionConflictError


def _prepare_publication(
    request: SchedulingCommandRequest,
    intent: ReleasePublicationIntent,
    *,
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> _Publication:
    approval = (
        SchedulingReleaseApproval.objects.filter(
            id=intent.approval_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            command_receipt__operation=SchedulingOperation.RELEASE_APPROVE,
            command_receipt__result_object_id=F("id"),
            command_receipt__actor_id=F("actor_id"),
            command_receipt__organization_id=request.organization_id,
            command_receipt__edition_id=request.edition_id,
            command_receipt__reason=F("reason"),
            command_receipt__occurred_at=F("occurred_at"),
            command_receipt__resulting_version=1,
        )
        .select_related("candidate_revision")
        .first()
    )
    if approval is None:
        raise SchedulingUnavailableError
    if approval.actor_id == request.actor_id:
        raise SchedulingAuthorizationDeniedError
    if (
        approval.source_snapshot_digest != intent.source_snapshot_digest
        or approval.eligibility_policy != RELEASE_ELIGIBILITY_POLICY
        or SchedulingRelease.objects.filter(approval=approval).exists()
    ):
        raise SchedulingVersionConflictError
    candidate = approval.candidate_revision
    retained_people: tuple[UUID, ...] = ()
    if intent.expected_active_release_id is not None:
        # Owning parents already serialize this edition. Read the retained person
        # union before any narrower source locks; do not lock a pointer first.
        prior_release = SchedulingRelease.objects.filter(
            id=intent.expected_active_release_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
        ).first()
        if prior_release is None:
            raise SchedulingVersionConflictError
        retained_people = tuple(
            prior_release.approval.dependencies.filter(
                dependency__kind="identity_account"
            ).values_list("dependency__source_id", flat=True)[
                : MAX_RELEASE_DEPENDENCY_USES + 1
            ]
        )
        if len(retained_people) > MAX_RELEASE_DEPENDENCY_USES:
            raise SchedulingUnavailableError
    sources = _load_release_sources(
        _read_request(request),
        ReleaseCandidateSelection(
            candidate.candidate_id,
            candidate.id,
            candidate.sequence,
            intent.source_snapshot_digest,
        ),
        approval_actor_id=approval.actor_id,
        programme_authorizer=programme_authorizer,
        scheduling_authorizer=scheduling_authorizer,
        retained_person_ids=retained_people,
    )
    # Publication authority does not keep the earlier reviewer's grant alive.
    # The collector already locked this actor in the complete person union.
    reviewer_scope = authorize_scheduling_scope(
        actor_id=approval.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=APPROVE_RELEASE,
        authorizer=scheduling_authorizer,
    )
    if not reviewer_scope.accepts_writes:
        raise SchedulingAuthorizationDeniedError
    authors = _load_release_authorship(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        candidate_revision_id=candidate.id,
    )
    if approval.actor_id in authors.author_ids:
        raise SchedulingUnavailableError
    _require_eligible_approval(request, sources, tuple(approval.warning_ids))
    placements = _placements(approval)
    if approval.manifest_digest != sources.candidate.manifest_digest or set(
        placements
    ) != set(sources.placements):
        raise SchedulingVersionConflictError
    _assert_captures(approval, sources)
    pointer = _pointer(
        request,
        expected_version=intent.expected_release_version,
        expected_active=intent.expected_active_release_id,
    )
    previous: tuple[ReleaseArtifactSelection, ...] = ()
    if pointer and pointer.active_release_id:
        release = (
            SchedulingRelease.objects.filter(
                id=pointer.active_release_id,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
            )
            .select_related("approval")
            .first()
        )
        if release is None:
            raise SchedulingUnavailableError
        previous = _placements(release.approval)
    before = {row.occurrence_id: row for row in previous}
    after = {row.occurrence_id: row for row in placements}
    release_id = uuid4()
    artifact = prepare_canonical_release_artifact(
        release_id=release_id,
        approval_id=approval.id,
        candidate_revision_id=candidate.id,
        source_snapshot_digest=approval.source_snapshot_digest,
        selections=placements,
    )
    verify_canonical_release_artifact(
        artifact,
        release_id=release_id,
        approval_id=approval.id,
        candidate_revision_id=candidate.id,
        source_snapshot_digest=approval.source_snapshot_digest,
        selections=placements,
    )
    return _Publication(
        approval,
        pointer,
        release_id,
        artifact,
        len(after.keys() - before.keys()),
        sum(before[key] != after[key] for key in before.keys() & after.keys()),
        len(before.keys() - after.keys()),
    )


def publish_programme_release(
    request: SchedulingCommandRequest,
    *,
    intent: ReleasePublicationIntent,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Publish one exact independent approval with mandatory verified canonical bytes.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current exact publisher, scope, rationale and reauthorized retry identity.
    intent : ReleasePublicationIntent
        Retained approval, exact source digest and observed prior pointer state.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent owner-source policy; isolated dormant-profile test seam only.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Separate publication and protected-source capabilities.

    Returns
    -------
    SchedulingCommandResult
        Exact immutable release receipt and monotonic edition pointer version.

    Notes
    -----
    Every source is recollected under canonical locks. Any intervening captured
    generation change rejects the approval even if its visible source was restored.
    Artifact construction and semantic verification precede the active pointer;
    all release, artifact, pointer, audit and effects writes share one transaction.
    This dormant command does not activate profiles, outputs or runtime writers.
    """

    def normalize() -> ReleasePublicationIntent:
        if type(intent) is not ReleasePublicationIntent:
            raise ValidationError("Supply one exact Programme release selection.")
        return intent.validated()

    def prepare(change: ReleasePublicationIntent) -> _Publication:
        return _prepare_publication(
            request,
            change,
            programme_authorizer=programme_authorizer,
            scheduling_authorizer=scheduling_authorizer,
        )

    def write(
        context: _CommandTransaction,
        change: ReleasePublicationIntent,
        prepared: _Publication,
    ) -> tuple[UUID, int]:
        version = change.expected_release_version + 1
        release = SchedulingRelease.objects.create(
            id=prepared.release_id,
            **context.evidence(),
            command_receipt_id=context.receipt_id,
            approval=prepared.approval,
            previous_release_id=change.expected_active_release_id,
            pointer_version=version,
            added_count=prepared.added,
            changed_count=prepared.changed,
            removed_count=prepared.removed,
        )
        artifact = prepared.artifact
        SchedulingReleaseArtifact.objects.create(
            **context.ownership(),
            release=release,
            contract=artifact.contract,
            sha256=artifact.sha256,
            byte_length=artifact.byte_length,
            payload=artifact.payload,
        )
        _advance_pointer(context, prepared.pointer, release.id, version)
        return release.id, version

    return _execute(
        request,
        operation=SchedulingOperation.RELEASE_PUBLISH,
        capability=PUBLISH_RELEASE,
        normalize=normalize,
        payload=lambda change: {
            "approval_id": str(change.approval_id),
            "expected_active_release_id": str(change.expected_active_release_id)
            if change.expected_active_release_id
            else None,
            "expected_release_version": change.expected_release_version,
            "source_snapshot_digest": change.source_snapshot_digest,
        },
        prepare=prepare,
        write=write,
        authorizer=scheduling_authorizer,
    )


def _advance_pointer(
    context: _CommandTransaction,
    pointer: SchedulingReleasePointer | None,
    release_id: UUID | None,
    version: int,
) -> None:
    if pointer is None:
        SchedulingReleasePointer.objects.create(
            **context.ownership(),
            active_release_id=release_id,
            command_receipt_id=context.receipt_id,
            version=version,
        )
    else:
        pointer.active_release_id = release_id
        pointer.command_receipt_id = context.receipt_id
        pointer.version = version
        pointer.save(
            update_fields=("active_release", "command_receipt", "version", "updated_at")
        )


def withdraw_programme_release(
    request: SchedulingCommandRequest,
    *,
    intent: ReleaseWithdrawalIntent,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Deliberately withdraw the active release without requiring safe source recovery.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current scoped actor with separate withdrawal authority and a human reason.
    intent : ReleaseWithdrawalIntent
        Exact active release and observed monotonic pointer version.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Current independently scoped policy; dormant test seam only.

    Returns
    -------
    SchedulingCommandResult
        Immutable withdrawal receipt; retained releases and artifacts are not deleted.

    Notes
    -----
    Captured person references are locked before the pointer so withdrawing
    operative commitments can serialize with new native person work. Inactive
    source people do not prevent cleanup; the actor remains independently authorized.
    A withdrawn version never resets to the initial never-published state.
    """

    def normalize() -> ReleaseWithdrawalIntent:
        if type(intent) is not ReleaseWithdrawalIntent:
            raise ValidationError("Supply one exact release withdrawal selection.")
        return intent.validated()

    def prepare(change: ReleaseWithdrawalIntent) -> SchedulingReleasePointer:
        release = (
            SchedulingRelease.objects.filter(
                id=change.active_release_id,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
            )
            .select_related("approval")
            .first()
        )
        if release is None:
            raise SchedulingUnavailableError
        people = tuple(
            sorted(
                {
                    request.actor_id,
                    *release.approval.dependencies.filter(
                        dependency__kind="identity_account"
                    ).values_list("dependency__source_id", flat=True)[
                        : MAX_RELEASE_DEPENDENCY_USES + 1
                    ],
                }
            )
        )
        if lock_account_references_for_evidence(account_ids=people) != people:
            raise SchedulingUnavailableError
        pointer = _pointer(
            request,
            expected_version=change.expected_release_version,
            expected_active=change.active_release_id,
        )
        if pointer is None:
            raise SchedulingVersionConflictError
        return pointer

    def write(
        context: _CommandTransaction,
        change: ReleaseWithdrawalIntent,
        pointer: SchedulingReleasePointer,
    ) -> tuple[UUID, int]:
        version = change.expected_release_version + 1
        withdrawal = SchedulingReleaseWithdrawal.objects.create(
            **context.evidence(),
            command_receipt_id=context.receipt_id,
            release_id=change.active_release_id,
            pointer_version=version,
        )
        _advance_pointer(context, pointer, None, version)
        return withdrawal.id, version

    return _execute(
        request,
        operation=SchedulingOperation.RELEASE_WITHDRAW,
        capability=WITHDRAW_RELEASE,
        normalize=normalize,
        payload=lambda change: {
            "active_release_id": str(change.active_release_id),
            "expected_release_version": change.expected_release_version,
        },
        prepare=prepare,
        write=write,
        authorizer=scheduling_authorizer,
    )
