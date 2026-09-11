"""Accountable exact-source placement assessments with independent evidence streams."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizer,
)
from maru.scheduling.planning_queries import (
    SchedulingReadRequest,
    load_scheduling_historical_manifest,
)
from maru.workforce.programme_references import lock_programme_staffing_scope

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_DELIVERY,
    PROGRAMME_MANAGE_STAFFING,
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from .catalogs import ProgrammeCommandOperation as Operation
from .commands import (
    ProgrammeCommandResult,
    ProgrammeLifecycleConflictError,
    ProgrammeUnavailableError,
    ProgrammeVersionConflictError,
    _append_denial_audit,
    _append_error_audit_best_effort,
    _locked_control,
    _locked_item,
    _record_success,
    _replay,
    _require_version,
)
from .inputs import (
    canonical_digest,
    normalized_reason,
    normalized_source_channel,
    require_uuid,
)
from .models import ProgrammePlacementDecision
from .placement_queries import (
    ProgrammePlacementReadRequest,
    _admit,
    preview_programme_placement_decision,
)
from .release_inputs import (
    ProgrammePlacementDecisionIntent,
    ProgrammePlacementSelection,
)
from .release_inputs import ProgrammePlacementDecisionKind as Kind
from .release_inputs import ProgrammePlacementDecisionState as State
from .writer_boundary import programme_writer

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProgrammePlacementCommandResult:
    """Historical exact command identifiers; no current source or private rationale.

    Attributes
    ----------
    receipt_id
        Retained Programme idempotency evidence.
    decision_id
        Immutable owner assessment or withdrawal.
    item_id
        Exact Programme owner, whose item version was not advanced.
    item_version
        Item version at this historical command.
    decision_sequence
        Independent placement/purpose sequence.
    replayed
        Whether this is a retained retry with no new decision or effects.
    """

    receipt_id: UUID
    decision_id: UUID
    item_id: UUID
    item_version: int
    decision_sequence: int
    replayed: bool


def _result(result: ProgrammeCommandResult) -> ProgrammePlacementCommandResult:
    row = (
        ProgrammePlacementDecision.objects.filter(
            id=result.result_object_id, item_id=result.item_id
        )
        .values_list("sequence", flat=True)
        .first()
    )
    if row is None:
        raise ProgrammeUnavailableError
    return ProgrammePlacementCommandResult(
        result.receipt_id,
        result.result_object_id,
        result.item_id,
        result.resulting_item_version,
        row,
        result.replayed,
    )


def _withdrawal(
    request: ProgrammePlacementReadRequest,
    intent: ProgrammePlacementDecisionIntent,
    prior: ProgrammePlacementDecision | None,
    scheduling_authorizer: SchedulingAuthorizer,
) -> tuple[UUID | None, int | None]:
    if prior is None or (
        prior.source_digest != intent.source_digest
        or prior.candidate_revision_id != intent.candidate_revision_id
    ):
        raise ProgrammeVersionConflictError
    history = load_scheduling_historical_manifest(
        SchedulingReadRequest(
            request.actor_id,
            request.organization_id,
            request.edition_id,
            request.correlation_id,
        ),
        revision_id=intent.candidate_revision_id,
        authorizer=scheduling_authorizer,
    )
    if (
        history.candidate_id != intent.candidate_id
        or history.entry.version != intent.expected_candidate_version
    ):
        raise ProgrammeVersionConflictError
    if not any(
        row.id == intent.placement_id and row.occurrence_id == intent.occurrence_id
        for row in history.placements
    ):
        raise ProgrammeUnavailableError
    return prior.delivery_revision_id, prior.space_selection_version


def _require_operational(
    request: ProgrammePlacementReadRequest, lifecycle: str
) -> None:
    edition = resolve_scheduling_edition_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if (
        edition is None
        or not edition.accepts_scheduling_writes
        or lifecycle != "active"
    ):
        raise ProgrammeLifecycleConflictError


def _assessment_source(
    request: ProgrammePlacementReadRequest,
    intent: ProgrammePlacementDecisionIntent,
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> tuple[UUID | None, int | None]:
    preview = preview_programme_placement_decision(
        request,
        selection=ProgrammePlacementSelection(
            intent.item_id,
            intent.occurrence_id,
            intent.candidate_id,
            intent.candidate_revision_id,
            intent.placement_id,
            intent.expected_item_version,
            intent.expected_candidate_version,
            intent.kind,
        ),
        programme_authorizer=programme_authorizer,
        scheduling_authorizer=scheduling_authorizer,
    )
    if preview.source_digest != intent.source_digest:
        raise ProgrammeVersionConflictError
    if (
        intent.kind is Kind.STAFFING_NOT_REQUIRED
        and intent.state is State.SATISFIED
        and not preview.staffing_absence_available
    ):
        raise ValidationError(
            "Current staffing needs or retained work prevent no-staffing approval.",
            code="programme_staffing_absence_unavailable",
        )
    return (
        preview.delivery_revision_id,
        preview.physical_source.selection_version if preview.physical_source else None,
    )


def record_programme_placement_decision(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    intent: ProgrammePlacementDecisionIntent,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "programme-placement",
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammePlacementCommandResult:
    """Record an explicit assessment against freshly recomputed exact owner sources.

    Parameters
    ----------
    actor_id : UUID
        Trusted current organizer, reauthorized inside the canonical transaction.
    organization_id : UUID
        Exact expected tenant.
    edition_id : UUID
        Exact edition admitting operational scheduling decisions.
    intent : ProgrammePlacementDecisionIntent
        Closed assessment, exact preview digest and optimistic source/history versions.
    reason : str
        Required retained rationale, never copied to broad events or preflight.
    idempotency_key : UUID
        Exact actor/edition retry identifier.
    correlation_id : UUID
        Trusted mandatory audit and event correlation.
    source_channel : str, default="programme-placement"
        Closed originating adapter identifier.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent owner management and read field policy.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent current candidate or exact retained history policy.

    Returns
    -------
    ProgrammePlacementCommandResult
        Historical decision and receipt identity, never release approval.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If exact owner authority or adapter admission is unavailable.
    Exception
        Re-raises source, validation, lifecycle, version or effect failure after
        transactional rollback and a best-effort minimized failure audit.

    Notes
    -----
    Draft, Preparing, Ready and Live admit these operational decisions without
    advancing the private item version. Current profiles still omit the adapter.
    Withdrawal uses the exact retained candidate provenance, not a fresh placement;
    its expected candidate version is the retained manifest sequence. No stale
    success is reused. Receipt, audit, own-stream event and outbox commit atomically.
    A changed current source or history sequence raises a version conflict.
    """
    if (
        type(intent) is not ProgrammePlacementDecisionIntent
        or type(intent.kind) is not Kind
    ):
        raise ProgrammeAuthorizationDeniedError
    fit = intent.kind is Kind.ACCESSIBILITY_FIT
    capability = PROGRAMME_MANAGE_DELIVERY if fit else PROGRAMME_MANAGE_STAFFING
    operation = (
        Operation.ACCESSIBILITY_FIT_RECORD if fit else Operation.STAFFING_ABSENCE_RECORD
    )
    request = ProgrammePlacementReadRequest(
        actor_id, organization_id, edition_id, correlation_id, source_channel
    )

    def authorize(*, lock: bool = False) -> AuthorizedProgrammeScope:
        scope = authorize_programme_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability,
            authorizer=programme_authorizer,
            lock=lock,
        )
        _admit(request, intent.kind, programme_authorizer)
        return scope

    try:
        for field, value in (
            ("actor_id", actor_id),
            ("organization_id", organization_id),
            ("edition_id", edition_id),
            ("correlation_id", correlation_id),
            ("idempotency_key", idempotency_key),
        ):
            require_uuid(value, field=field)
        authorize()
        intent.validated()
        reason = normalized_reason(reason)
        source_channel = normalized_source_channel(source_channel)
        digest = canonical_digest(
            {
                "operation": operation,
                "intent": asdict(intent),
                "reason": reason,
                "source_channel": source_channel,
            }
        )
        with transaction.atomic(), programme_writer():
            lock_programme_staffing_scope(
                organization_id=organization_id, edition_id=edition_id
            )
            scope = authorize(lock=True)
            replay = _replay(
                actor_id=actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return _result(replay)
            control = _locked_control(
                organization_id=organization_id, edition_id=edition_id, required=True
            )
            item = _locked_item(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id=intent.item_id,
            )
            _require_version(
                actual=item.aggregate_version, expected=intent.expected_item_version
            )
            _require_operational(request, item.lifecycle)
            prior = (
                ProgrammePlacementDecision.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    item_id=item.id,
                    occurrence_id=intent.occurrence_id,
                    placement_id=intent.placement_id,
                    kind=intent.kind,
                )
                .order_by("-sequence")
                .first()
            )
            _require_version(
                actual=prior.sequence if prior else 0,
                expected=intent.expected_decision_sequence,
            )
            if intent.state is State.WITHDRAWN:
                delivery_id, space_version = _withdrawal(
                    request, intent, prior, scheduling_authorizer
                )
            else:
                delivery_id, space_version = _assessment_source(
                    request, intent, programme_authorizer, scheduling_authorizer
                )
            scope = authorize()
            now = timezone.now()
            decision = ProgrammePlacementDecision.objects.create(
                organization_id=organization_id,
                edition_id=edition_id,
                item=item,
                occurrence_id=intent.occurrence_id,
                candidate_revision_id=intent.candidate_revision_id,
                placement_id=intent.placement_id,
                kind=intent.kind.value,
                state=intent.state.value,
                sequence=intent.expected_decision_sequence + 1,
                item_version=item.aggregate_version,
                source_digest=intent.source_digest,
                delivery_revision_id=delivery_id,
                space_selection_version=space_version,
                actor_id=actor_id,
                reason=reason,
                occurred_at=now,
            )
            return _result(
                _record_success(
                    scope=scope,
                    control=control,
                    item=item,
                    operation=operation,
                    event_action="record_accessibility_fit"
                    if fit
                    else "record_staffing_absence",
                    capability_code=capability,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    request_digest=digest,
                    correlation_id=correlation_id,
                    source_channel=source_channel,
                    result_object_id=decision.id,
                    expected_version=item.aggregate_version,
                    resulting_item_version=item.aggregate_version,
                    resulting_control_version=None,
                    changed_fields=("placement_decisions",),
                    occurred_at=now,
                    event_aggregate_type="programme.accessibility_fit"
                    if fit
                    else "programme.staffing_absence",
                    event_aggregate_id=intent.placement_id,
                    event_aggregate_version=decision.sequence,
                )
            )
    except ProgrammeAuthorizationDeniedError:
        _append_denial_audit(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability,
            operation=operation.value,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        raise
    except Exception as error:
        _append_error_audit_best_effort(
            error=error,
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability,
            operation=operation.value,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        raise
