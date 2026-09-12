"""Dormant exact-warning and independent release-review application commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db.models import F

from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER

from .authorization import (
    ACKNOWLEDGE_RELEASE_WARNINGS,
    APPROVE_RELEASE,
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizationDeniedError,
)
from .catalogs import SchedulingConflictSeverity, SchedulingOperation
from .command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
    _CommandTransaction,
    _execute,
)
from .models import (
    SchedulingReleaseApproval,
    SchedulingReleaseApprovalDependency,
    SchedulingReleaseApprovalPlacement,
    SchedulingReleaseWarningAcknowledgement,
)
from .planning_queries import SchedulingReadRequest
from .release_authorship import _load_release_authorship
from .release_capture import _capture_release_generations, _load_release_sources
from .release_eligibility import (
    RELEASE_ELIGIBILITY_POLICY,
    ReleaseFinding,
    ReleaseWarningAcknowledgement,
    evaluate_release_eligibility,
)
from .release_inputs import (
    ReleaseApprovalIntent,
    ReleaseCandidateSelection,
    ReleaseWarningIntent,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.authorization import ProgrammeAuthorizer

    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult
    from .inputs import SchedulingCommandRequest
    from .release_capture import _ReleaseSources
    from .release_preflight import ReleasePreflightFinding


def _read_request(request: SchedulingCommandRequest) -> SchedulingReadRequest:
    return SchedulingReadRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        request.correlation_id,
    )


def _selection_payload(selection: ReleaseCandidateSelection) -> dict[str, object]:
    return {
        "candidate_id": str(selection.candidate_id),
        "candidate_revision_id": str(selection.candidate_revision_id),
        "expected_candidate_version": selection.expected_candidate_version,
        "source_snapshot_digest": selection.source_snapshot_digest,
    }


def _warning(sources: _ReleaseSources, fingerprint: str) -> ReleasePreflightFinding:
    matches = tuple(
        row
        for row in sources.preflight.findings
        if row.fingerprint == fingerprint
        and row.severity is SchedulingConflictSeverity.WARNING
    )
    if len(matches) != 1:
        raise SchedulingVersionConflictError
    return matches[0]


def _require_eligible_approval(
    request: SchedulingCommandRequest,
    sources: _ReleaseSources,
    acknowledgement_ids: tuple[UUID, ...],
) -> None:
    rows = tuple(
        SchedulingReleaseWarningAcknowledgement.objects.filter(
            id__in=acknowledgement_ids,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            candidate_revision_id=sources.candidate.revision_id,
            source_snapshot_digest=sources.preflight.snapshot_digest,
            command_receipt__organization_id=request.organization_id,
            command_receipt__edition_id=request.edition_id,
            command_receipt__operation=SchedulingOperation.RELEASE_WARNING_ACKNOWLEDGE,
            command_receipt__result_object_id=F("id"),
            command_receipt__resulting_version=1,
            command_receipt__actor_id=F("actor_id"),
            command_receipt__reason=F("reason"),
            command_receipt__occurred_at=F("occurred_at"),
        ).order_by("id")
    )
    if len(rows) != len(acknowledgement_ids) or len(
        {row.finding_fingerprint for row in rows}
    ) != len(rows):
        raise SchedulingVersionConflictError
    for row in rows:
        finding = _warning(sources, row.finding_fingerprint)
        if (
            row.check_code,
            row.finding_code,
            row.occurrence_id,
            row.other_occurrence_id,
        ) != (
            finding.check.value,
            finding.code,
            finding.occurrence_id,
            finding.other_occurrence_id,
        ):
            raise SchedulingUnavailableError
    preflight = sources.preflight
    eligibility = evaluate_release_eligibility(
        snapshot_digest=preflight.snapshot_digest,
        checks=preflight.checks,
        findings=tuple(
            ReleaseFinding(
                preflight.snapshot_digest, row.check, row.fingerprint, row.severity
            )
            for row in preflight.findings
        ),
        acknowledgements=tuple(
            ReleaseWarningAcknowledgement(
                row.source_snapshot_digest, row.finding_fingerprint
            )
            for row in rows
        ),
    )
    if not eligibility.eligible_for_review:
        raise SchedulingVersionConflictError


def acknowledge_programme_release_warning(
    request: SchedulingCommandRequest,
    *,
    intent: ReleaseWarningIntent,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Retain accountable acknowledgement of one exact current release warning.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current actor, exact scope, mandatory rationale and reauthorized retry identity.
    intent : ReleaseWarningIntent
        Exact candidate/source/finding selection; no caller-supplied eligibility.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independently checked owner source policy; isolated-test substitute only.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Separate release-warning capability and source-read field authority.

    Returns
    -------
    SchedulingCommandResult
        Immutable exact warning receipt; not independent approval or publication.

    Notes
    -----
    Complete owner/person/physical locks and mandatory audits precede the warning.
    Blockers, unavailable sources and planning acknowledgements cannot be waived.
    Current profiles deny this workflow; its full database graph remains required.
    """

    def normalize() -> ReleaseWarningIntent:
        if type(intent) is not ReleaseWarningIntent:
            raise ValidationError("Supply one exact release warning selection.")
        return intent.validated()

    def prepare(change: ReleaseWarningIntent) -> _ReleaseSources:
        sources = _load_release_sources(
            _read_request(request),
            change.selection,
            approval_actor_id=request.actor_id,
            programme_authorizer=programme_authorizer,
            scheduling_authorizer=scheduling_authorizer,
        )
        _warning(sources, change.finding_fingerprint)
        return sources

    def write(
        context: _CommandTransaction,
        change: ReleaseWarningIntent,
        sources: _ReleaseSources,
    ) -> tuple[UUID, int]:
        finding = _warning(sources, change.finding_fingerprint)
        if SchedulingReleaseWarningAcknowledgement.objects.filter(
            **context.ownership(),
            actor_id=request.actor_id,
            candidate_revision_id=sources.candidate.revision_id,
            source_snapshot_digest=sources.preflight.snapshot_digest,
            finding_fingerprint=finding.fingerprint,
        ).exists():
            raise SchedulingVersionConflictError
        warning = SchedulingReleaseWarningAcknowledgement.objects.create(
            **context.evidence(),
            command_receipt_id=context.receipt_id,
            candidate_revision_id=sources.candidate.revision_id,
            source_snapshot_digest=sources.preflight.snapshot_digest,
            finding_fingerprint=finding.fingerprint,
            check_code=finding.check.value,
            finding_code=finding.code,
            occurrence_id=finding.occurrence_id,
            other_occurrence_id=finding.other_occurrence_id,
        )
        return warning.id, 1

    return _execute(
        request,
        operation=SchedulingOperation.RELEASE_WARNING_ACKNOWLEDGE,
        capability=ACKNOWLEDGE_RELEASE_WARNINGS,
        normalize=normalize,
        payload=lambda change: {
            "selection": _selection_payload(change.selection),
            "finding_fingerprint": change.finding_fingerprint,
        },
        prepare=prepare,
        write=write,
        authorizer=scheduling_authorizer,
    )


def approve_programme_release(
    request: SchedulingCommandRequest,
    *,
    intent: ReleaseApprovalIntent,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Independently approve exact current sources and retain their native generations.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current exact actor/scope, reason and retry attribution.
    intent : ReleaseApprovalIntent
        Exact candidate snapshot and complete retained warning acknowledgement IDs.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent current Programme source authority; guarded test seam only.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Separate approval capability and independently ceilinged source-read authority.

    Returns
    -------
    SchedulingCommandResult
        Immutable approval identifier, not a published release or active pointer.

    Notes
    -----
    Former authors and exact copied/restored ancestry remain disqualifying.
    Every current category and warning is checked; unknown or partial evidence fails.
    Approval, placement/copy choices, native generations, receipt and effects share
    the command transaction. No source owner is mutated or volunteer reconfirmed.
    The full SQL graph and protected acceptance remain mandatory before delivery.
    """

    def normalize() -> ReleaseApprovalIntent:
        if type(intent) is not ReleaseApprovalIntent:
            raise ValidationError("Supply one exact release approval selection.")
        return intent.validated()

    def prepare(change: ReleaseApprovalIntent) -> _ReleaseSources:
        sources = _load_release_sources(
            _read_request(request),
            change.selection,
            approval_actor_id=request.actor_id,
            programme_authorizer=programme_authorizer,
            scheduling_authorizer=scheduling_authorizer,
        )
        authors = _load_release_authorship(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            candidate_revision_id=sources.candidate.revision_id,
        )
        if request.actor_id in authors.author_ids:
            raise SchedulingAuthorizationDeniedError
        _require_eligible_approval(request, sources, change.acknowledgement_ids)
        return sources

    def write(
        context: _CommandTransaction,
        change: ReleaseApprovalIntent,
        sources: _ReleaseSources,
    ) -> tuple[UUID, int]:
        generations = _capture_release_generations(sources)
        approval = SchedulingReleaseApproval.objects.create(
            **context.evidence(),
            command_receipt_id=context.receipt_id,
            candidate_revision_id=sources.candidate.revision_id,
            source_snapshot_digest=sources.preflight.snapshot_digest,
            manifest_digest=sources.candidate.manifest_digest,
            eligibility_policy=RELEASE_ELIGIBILITY_POLICY,
            warning_ids=list(change.acknowledgement_ids),
            placement_count=len(sources.placements),
            dependency_count=len(generations),
        )
        placements = {
            row.placement_id: SchedulingReleaseApprovalPlacement(
                **context.ownership(),
                approval=approval,
                occurrence_id=row.occurrence_id,
                placement_id=row.placement_id,
                public_rendition_id=row.public_rendition_id,
            )
            for row in sources.placements
        }
        SchedulingReleaseApprovalPlacement.objects.bulk_create(
            list(placements.values())
        )
        SchedulingReleaseApprovalDependency.objects.bulk_create(
            [
                SchedulingReleaseApprovalDependency(
                    **context.ownership(),
                    approval=approval,
                    dependency_id=row.dependency_id,
                    approval_placement=placements.get(row.reference.placement_id)
                    if row.reference.placement_id is not None
                    else None,
                    captured_generation=row.generation,
                    horizon=row.reference.horizon.value,
                    operational_ends_at=row.reference.operational_ends_at,
                )
                for row in generations
            ]
        )
        return approval.id, 1

    return _execute(
        request,
        operation=SchedulingOperation.RELEASE_APPROVE,
        capability=APPROVE_RELEASE,
        normalize=normalize,
        payload=lambda change: {
            "selection": _selection_payload(change.selection),
            "acknowledgement_ids": [str(value) for value in change.acknowledgement_ids],
        },
        prepare=prepare,
        write=write,
        authorizer=scheduling_authorizer,
    )
