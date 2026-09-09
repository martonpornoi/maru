"""Programme-owned staffing requirements; no implicit Workforce demand writes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.events.queries import resolve_edition_time_envelope_reference
from maru.scheduling.staffing_references import resolve_staffing_occurrence_reference
from maru.workforce.programme_references import (
    lock_programme_staffing_scope,
    resolve_staffing_position_reference,
)

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_STAFFING,
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from .catalogs import ProgrammeCommandOperation, ProgrammeItemLifecycle
from .commands import (
    ProgrammeCommandResult,
    ProgrammeLifecycleConflictError,
    ProgrammeLimitConflictError,
    ProgrammeUnavailableError,
    _advance_item,
    _append_denial_audit,
    _audit_command_errors,
    _ensure_editable,
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
from .models import ProgrammeStaffingRequirement, ProgrammeStaffingRevision
from .staffing_inputs import (
    MAX_STAFFING_REQUIREMENT_REVISIONS,
    MAX_STAFFING_REQUIREMENTS_PER_ITEM,
    ProgrammeStaffingChange,
    ProgrammeStaffingExpectation,
)
from .writer_boundary import programme_writer

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingCommandResult:
    """Minimized retained result; replay does not release current work terms.

    Attributes
    ----------
    receipt_id
        Immutable Programme command evidence.
    item_id
        Exact item affected by the historical command.
    requirement_id
        Stable staffing requirement identifier.
    revision_id
        Immutable terms or retirement revision.
    resulting_item_version
        Historical Programme item version, not necessarily current.
    resulting_requirement_version
        Historical requirement version represented by this receipt.
    replayed
        Whether retained identifiers were returned without new writes.
    """

    receipt_id: UUID
    item_id: UUID
    requirement_id: UUID
    revision_id: UUID
    resulting_item_version: int
    resulting_requirement_version: int
    replayed: bool


def _result(result: ProgrammeCommandResult) -> ProgrammeStaffingCommandResult:
    row = (
        ProgrammeStaffingRevision.objects.filter(
            id=result.result_object_id,
            item_id=result.item_id,
        )
        .values_list("requirement_id", "sequence")
        .first()
    )
    if row is None:
        raise ProgrammeUnavailableError
    return ProgrammeStaffingCommandResult(
        result.receipt_id,
        result.item_id,
        row[0],
        result.result_object_id,
        result.resulting_item_version,
        row[1],
        result.replayed,
    )


def _retained_terms(
    requirement: ProgrammeStaffingRequirement,
) -> ProgrammeStaffingExpectation:
    revision = ProgrammeStaffingRevision.objects.filter(
        requirement=requirement,
        sequence=requirement.version,
        organization_id=requirement.organization_id,
        edition_id=requirement.edition_id,
        item_id=requirement.item_id,
    ).first()
    if revision is None:
        raise ProgrammeUnavailableError
    return ProgrammeStaffingExpectation(
        **{
            field: getattr(revision, field)
            for field in ProgrammeStaffingExpectation.__dataclass_fields__
        }
    )


def _source_terms(
    scope: AuthorizedProgrammeScope,
    change: ProgrammeStaffingChange,
    requirement: ProgrammeStaffingRequirement | None,
) -> ProgrammeStaffingExpectation:
    occurrence = resolve_staffing_occurrence_reference(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        item_id=change.item_id,
        occurrence_id=change.occurrence_id,
    )
    envelope = resolve_edition_time_envelope_reference(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
    )
    if occurrence is None or envelope is None:
        raise ProgrammeUnavailableError
    _require_version(
        actual=occurrence.version, expected=change.expected_occurrence_version
    )
    _require_version(actual=envelope.version, expected=change.expected_edition_version)
    if change.retire:
        if requirement is None:
            raise ProgrammeUnavailableError
        return _retained_terms(requirement)
    terms = change.expectation
    if terms is None:
        raise ProgrammeUnavailableError
    position = resolve_staffing_position_reference(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        position_id=terms.position_id,
    )
    if position is None:
        raise ProgrammeUnavailableError
    if not occurrence.active or not position.accepts_staffing:
        raise ProgrammeLifecycleConflictError
    if not envelope.starts_at <= terms.starts_at < terms.ends_at <= envelope.ends_at:
        raise ValidationError(
            "Work must fit the current edition date envelope.",
            code="programme_staffing_envelope_invalid",
        )
    return terms


def _locked_requirement(
    scope: AuthorizedProgrammeScope,
    change: ProgrammeStaffingChange,
) -> ProgrammeStaffingRequirement | None:
    requirements = ProgrammeStaffingRequirement.objects.filter(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        item_id=change.item_id,
    )
    if change.requirement_id is None:
        if requirements.count() >= MAX_STAFFING_REQUIREMENTS_PER_ITEM:
            raise ProgrammeLimitConflictError
        return None
    requirement = (
        requirements.select_for_update()
        .filter(
            id=change.requirement_id,
            occurrence_id=change.occurrence_id,
        )
        .first()
    )
    if requirement is None:
        raise ProgrammeUnavailableError
    _require_version(
        actual=requirement.version, expected=change.expected_requirement_version
    )
    if requirement.lifecycle != ProgrammeItemLifecycle.ACTIVE.value:
        raise ProgrammeLifecycleConflictError
    ceiling = MAX_STAFFING_REQUIREMENT_REVISIONS + (1 if change.retire else 0)
    if requirement.version >= ceiling:
        raise ProgrammeLimitConflictError
    return requirement


@_audit_command_errors(
    capability_code=PROGRAMME_MANAGE_STAFFING, operation="staffing_change"
)
def change_programme_staffing_requirement(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    change: ProgrammeStaffingChange,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "programme-staffing",
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeStaffingCommandResult:
    """Create, revise or retire one need without changing any volunteer expectation.

    Parameters
    ----------
    actor_id : UUID
        Current authenticated organizer, reauthorized under the edition lock.
    organization_id : UUID
        Expected tenant, independently resolved before private input.
    edition_id : UUID
        Exact edition; current executable profiles deny this dormant capability.
    change : ProgrammeStaffingChange
        Closed complete work intent and optimistic source preconditions.
    reason : str
        Required retained organizer rationale, never copied into a public event.
    idempotency_key : UUID
        Exact actor/edition retry identity for the normalized intent.
    correlation_id : UUID
        Trusted trace attribution, not an authorization credential.
    source_channel : str, default="programme-staffing"
        Closed channel identifier for receipt and audit provenance.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy by default; replacement requires the existing isolated-test guard.

    Returns
    -------
    ProgrammeStaffingCommandResult
        Retained identifiers and historical versions, never a Workforce commitment.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If the actor, scope, profile or capability is unavailable.
    ValidationError
        If input, explicit terms or the current edition envelope is invalid.

    Notes
    -----
    Owner validation propagates ``ProgrammeUnavailableError`` when an exact
    reference or required history is absent, ``ProgrammeLifecycleConflictError``
    when the edition or selected owner no longer accepts the change, and
    ``ProgrammeLimitConflictError`` when bounded requirement or revision history
    has no remaining room.
    """
    for field, value in (
        ("actor_id", actor_id),
        ("organization_id", organization_id),
        ("edition_id", edition_id),
        ("idempotency_key", idempotency_key),
        ("correlation_id", correlation_id),
    ):
        require_uuid(value, field=field)
    source_channel = normalized_source_channel(source_channel)

    def authorize(*, lock: bool = False) -> AuthorizedProgrammeScope:
        return authorize_programme_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=PROGRAMME_MANAGE_STAFFING,
            authorizer=authorizer,
            lock=lock,
        )

    operation = "staffing_change"
    try:
        authorize()
        if not isinstance(change, ProgrammeStaffingChange):
            raise ValidationError(
                "Use a typed staffing change.", code="programme_staffing_intent_invalid"
            )
        change = change.normalized()
        reason = normalized_reason(reason)
        command_operation = (
            ProgrammeCommandOperation.STAFFING_RETIRE
            if change.retire
            else ProgrammeCommandOperation.STAFFING_CREATE
            if change.requirement_id is None
            else ProgrammeCommandOperation.STAFFING_REVISE
        )
        operation = command_operation.value
        digest = canonical_digest(
            {
                "operation": operation,
                "change": asdict(change),
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
            _ensure_editable(scope)
            control = _locked_control(
                organization_id=organization_id, edition_id=edition_id, required=True
            )
            item = _locked_item(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id=change.item_id,
            )
            _require_version(
                actual=item.aggregate_version, expected=change.expected_item_version
            )
            requirement = _locked_requirement(scope, change)
            terms = _source_terms(scope, change, requirement)
            expected_version = item.aggregate_version
            item_version = _advance_item(item, actor_id=actor_id)
            if requirement is None:
                requirement = ProgrammeStaffingRequirement(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    item=item,
                    occurrence_id=change.occurrence_id,
                    version=1,
                )
            else:
                requirement.version += 1
            requirement.lifecycle = (
                ProgrammeItemLifecycle.RETIRED.value
                if change.retire
                else ProgrammeItemLifecycle.ACTIVE.value
            )
            requirement.item_version = item_version
            requirement.last_modified_by_id = actor_id
            requirement.save()
            occurred_at = timezone.now()
            revision = ProgrammeStaffingRevision.objects.create(
                organization_id=organization_id,
                edition_id=edition_id,
                item=item,
                requirement=requirement,
                sequence=requirement.version,
                item_version=item_version,
                occurrence_version=change.expected_occurrence_version,
                operation=operation,
                lifecycle=requirement.lifecycle,
                actor_id=actor_id,
                reason=reason,
                occurred_at=occurred_at,
                **asdict(terms),
            )
            return _result(
                _record_success(
                    scope=scope,
                    control=control,
                    item=item,
                    operation=command_operation,
                    event_action={
                        "staffing_create": "create_staffing",
                        "staffing_revise": "revise_staffing",
                        "staffing_retire": "retire_staffing",
                    }[operation],
                    capability_code=PROGRAMME_MANAGE_STAFFING,
                    reason=reason,
                    idempotency_key=idempotency_key,
                    request_digest=digest,
                    correlation_id=correlation_id,
                    source_channel=source_channel,
                    result_object_id=revision.id,
                    expected_version=expected_version,
                    resulting_item_version=item_version,
                    resulting_control_version=None,
                    changed_fields=("staffing_requirement",),
                    occurred_at=occurred_at,
                )
            )
    except ProgrammeAuthorizationDeniedError:
        _append_denial_audit(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=PROGRAMME_MANAGE_STAFFING,
            operation=operation,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        raise
