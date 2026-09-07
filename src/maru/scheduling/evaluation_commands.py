"""Immutable evaluation reports and exact-current reasoned warning acknowledgements."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .authorization import (
    ACKNOWLEDGE_WARNINGS,
    DEFAULT_SCHEDULING_AUTHORIZER,
    EVALUATE_CANDIDATES,
)
from .catalogs import SchedulingOperation
from .command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
    _CommandTransaction,
    _execute,
)
from .evaluation_sources import (
    _current_evaluation,
    _CurrentEvaluation,
    _finding_fingerprint,
)
from .inputs import SchedulingCommandRequest, require_identifier, require_version
from .models import (
    SchedulingConflict,
    SchedulingEvaluation,
    SchedulingWarningAcknowledgement,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult


def evaluate_scheduling_candidate(
    request: SchedulingCommandRequest,
    *,
    candidate_id: UUID,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Record a complete bounded report of declared current dependencies, not approval.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current authenticated attribution, action rationale and exact retry key.
    candidate_id : UUID
        Exact current draft to evaluate without changing its manifest.
    expected_version : int
        Exact current candidate revision.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent Scheduling policy; each source also reauthorizes its own facts.

    Returns
    -------
    SchedulingCommandResult
        Immutable report identity with version-only dependencies and closed findings.
    """

    def normalize() -> UUID:
        require_version(expected_version)
        return require_identifier(candidate_id)

    def write(
        context: _CommandTransaction, _identifier: UUID, current: _CurrentEvaluation
    ) -> tuple[UUID, int]:
        report = SchedulingEvaluation.objects.create(
            **context.evidence(),
            revision=current.revision,
            dependency_digest=current.digest,
            source_evidence=current.evidence,
            conflict_count=len(current.findings),
            is_complete=current.complete,
        )
        SchedulingConflict.objects.bulk_create(
            [
                SchedulingConflict(
                    **context.ownership(),
                    evaluation=report,
                    occurrence_id=finding.occurrence_id,
                    other_occurrence_id=finding.other_occurrence_id,
                    source_code=finding.source_code,
                    code=finding.code.value,
                    severity=finding.severity.value,
                    fingerprint=_finding_fingerprint(current.digest, finding),
                )
                for finding in current.findings
            ]
        )
        return report.id, 1

    return _execute(
        request,
        operation=SchedulingOperation.EVALUATION_RECORD,
        capability=EVALUATE_CANDIDATES,
        normalize=normalize,
        payload=lambda identifier: {
            "candidate_id": str(identifier),
            "expected_version": expected_version,
        },
        prepare=lambda identifier: _current_evaluation(
            request, candidate_id=identifier, expected_version=expected_version
        ),
        write=write,
        authorizer=authorizer,
    )


def acknowledge_scheduling_warning(
    request: SchedulingCommandRequest,
    *,
    conflict_id: UUID,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Acknowledge one warning only while its exact candidate and dependencies match.

    Acknowledgement cannot waive a blocker, an unavailable check, or a changed
    source. Later dependency changes make it stale without rewriting history.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current accountable actor, explicit reason and exact retry key.
    conflict_id : UUID
        Exact retained warning to re-evaluate before accepting the reason.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent Scheduling policy; dependency owners reauthorize fresh reads.

    Returns
    -------
    SchedulingCommandResult
        Immutable acknowledgement identity, never release or Venue approval.
    """

    def prepare(identifier: UUID) -> tuple[SchedulingConflict, _CurrentEvaluation]:
        warning = (
            SchedulingConflict.objects.filter(
                id=identifier,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                severity="warning",
            )
            .select_related("evaluation__revision")
            .first()
        )
        if warning is None:
            raise SchedulingUnavailableError
        revision = warning.evaluation.revision
        current = _current_evaluation(
            request,
            candidate_id=revision.candidate_id,
            expected_version=revision.sequence,
        )
        if (
            not current.complete
            or current.digest != warning.evaluation.dependency_digest
            or warning.fingerprint
            not in {
                _finding_fingerprint(current.digest, finding)
                for finding in current.findings
                if finding.severity == "warning"
            }
        ):
            raise SchedulingVersionConflictError
        return warning, current

    def write(
        context: _CommandTransaction,
        _identifier: UUID,
        prepared: tuple[SchedulingConflict, _CurrentEvaluation],
    ) -> tuple[UUID, int]:
        warning, _current = prepared
        if SchedulingWarningAcknowledgement.objects.filter(conflict=warning).exists():
            raise SchedulingVersionConflictError
        acknowledgement = SchedulingWarningAcknowledgement.objects.create(
            **context.evidence(), conflict=warning
        )
        return acknowledgement.id, 1

    return _execute(
        request,
        operation=SchedulingOperation.WARNING_ACKNOWLEDGE,
        capability=ACKNOWLEDGE_WARNINGS,
        normalize=lambda: require_identifier(conflict_id),
        payload=lambda identifier: {"conflict_id": str(identifier)},
        prepare=prepare,
        write=write,
        authorizer=authorizer,
    )
