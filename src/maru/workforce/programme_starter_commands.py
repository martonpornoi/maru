"""Actual-person requests and atomic independent fixed-template decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Never

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.models import AuthorityControl
from maru.authorization.provenance import role_bundle_provenance_is_historical
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied
from maru.workforce.models import ProgrammeStarterDecision, ProgrammeStarterRequest
from maru.workforce.programme_starter_boundary import (
    _conflict,
    _lock_key,
    _lock_people,
    _lock_scope,
    _require_actor,
    _require_controller,
    _require_integrity,
    _require_planning,
    _require_profile,
    _resolve_scope,
)
from maru.workforce.programme_starter_inputs import (
    PROGRAMME_STARTER_APPROVAL_DAYS,
    PROGRAMME_STARTER_DEFINITION,
    ProgrammeStarterAction,
    ProgrammeStarterIntent,
    ProgrammeStarterScope,
    _reason,
    _validate_context,
    normalize_programme_starter_intent,
    programme_starter_decision_digest,
    programme_starter_intent_digest,
)
from maru.workforce.programme_starter_writer import _programme_starter_writer
from maru.workforce.starter_templates import (
    _create_starter_definition,
    _existing_starter,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.identity.models import Account


@dataclass(frozen=True, slots=True)
class ProgrammeStarterRequestResult:
    """Recover exact retained intent without creating a template or granting access.

    Attributes
    ----------
    request_id, approval_deadline
        Original identity and last permitted approval instant.
    replayed
        Whether the authorized author recovered the same immutable request.
    """

    request_id: UUID
    approval_deadline: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class ProgrammeStarterDecisionResult:
    """Identify the original terminal decision and its exact shared output.

    Attributes
    ----------
    request_id, decision_id, action
        Original intent, immutable decision identity and actual terminal action.
    template_id, role_bundle_id, created_output
        Exact approved meaning or absent for decline/cancel; never a role grant.
    replayed
        Whether this same actor recovered their original identical decision.
    """

    request_id: UUID
    decision_id: UUID
    action: ProgrammeStarterAction
    template_id: UUID | None
    role_bundle_id: UUID | None
    created_output: bool
    replayed: bool


def _scope_filter(scope: ProgrammeStarterScope, *, prefix: str = "") -> Q:
    return Q(
        **{
            f"{prefix}organization_id": scope.organization_id,
            f"{prefix}series_id": scope.series_id,
            f"{prefix}edition_id": scope.edition_id,
        }
    )


def _audit(
    *,
    actor: Account,
    scope: ProgrammeStarterScope,
    operation: str,
    target_id: UUID,
    target_type: str,
    correlation_id: UUID,
    source_channel: str,
) -> UUID:
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code="workforce.manage_structure",
            operation=operation,
            target_id=target_id,
            target_type=target_type,
            outcome="allow",
            reason_code="own_person_action",
            correlation_id=correlation_id,
            source_channel=source_channel,
            retention_class="security-extended",
        )
    ).id


def _append(record: ProgrammeStarterRequest | ProgrammeStarterDecision) -> None:
    with _programme_starter_writer():
        record.save(force_insert=True)


def _retry_failure(error: IntegrityError) -> Never:
    constraint = getattr(
        getattr(error.__cause__, "diag", None), "constraint_name", None
    )
    if constraint in {
        "wrk_starter_request_author_key",
        "wrk_starter_decision_actor_key",
    }:
        raise _conflict(
            "This key belongs to different intent.", "retry_conflict"
        ) from error
    raise error


def _decision_result(
    decision: ProgrammeStarterDecision, *, replayed: bool
) -> ProgrammeStarterDecisionResult:
    return ProgrammeStarterDecisionResult(
        decision.request_id,
        decision.id,
        ProgrammeStarterAction(decision.action),
        decision.template_id,
        decision.role_bundle_id,
        decision.created_output,
        replayed,
    )


def _validate_retained(
    original: ProgrammeStarterRequest, scope: ProgrammeStarterScope
) -> None:
    definition = PROGRAMME_STARTER_DEFINITION
    if (
        original.definition_code,
        original.definition_version,
        original.definition_digest,
    ) != (
        definition.code,
        definition.version,
        definition.digest,
    ) or original.request_digest != programme_starter_intent_digest(
        scope=scope,
        details=ProgrammeStarterIntent(original.approver_id, original.reason),
    ):
        raise _conflict("The retained starter intent is unavailable.", "intent_changed")


def request_programme_starter(
    *,
    actor: Account,
    scope: ProgrammeStarterScope,
    details: ProgrammeStarterIntent,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ProgrammeStarterRequestResult:
    """Retain exact fixed-template intent for a named person's own later decision.

    Parameters
    ----------
    actor : Account
        Actual ordinary verified author with current accountable source authority.
    scope : ProgrammeStarterScope
        Exact Programme organization, series and edition chain.
    details : ProgrammeStarterIntent
        Named different approver and original rationale; not approval evidence.
    idempotency_key : UUID
        Original author-bound key; changed intent conflicts without disclosure.
    correlation_id : UUID
        Audit trace, not part of the immutable retry identity.
    source_channel : str, default='service'
        Bounded caller channel retained with the request audit.

    Returns
    -------
    ProgrammeStarterRequestResult
        Exact pending intent or authorized replay; no template, grant or message.

    Raises
    ------
    AuthorizationDenied
        For unavailable exact scope, people or current accountable authority.
    ValidationError
        For malformed intent, changed retry, closed planning or unsafe integrity.

    Notes
    -----
    Unsupported profiles fail before database work. Canonical owner and person
    locks, genuine current authority and native readiness precede any insertion.
    """
    _require_profile()
    normalized = normalize_programme_starter_intent(details)
    digest = programme_starter_intent_digest(scope=scope, details=normalized)
    _validate_context(idempotency_key, correlation_id, source_channel)
    _require_actor(actor, _resolve_scope(scope))
    if actor.id == normalized.approver_id:
        raise AuthorizationDenied(
            "Programme Volunteer starter is unavailable.",
            reason_code="programme_starter_unavailable",
        )
    try:
        with transaction.atomic():
            lock_retired_department_authority_boundaries()
            _lock_key(actor.id, idempotency_key, "programme-starter-request@1")
            _lock_scope(scope)
            targets = _resolve_scope(scope)
            _require_profile()
            _require_integrity()
            original = (
                ProgrammeStarterRequest.objects.select_for_update()
                .filter(
                    _scope_filter(scope),
                    author_id=actor.id,
                    idempotency_key=idempotency_key,
                )
                .first()
            )
            if original is not None:
                current = _lock_people({actor.id})[actor.id]
                _require_controller(current, targets)
                _validate_retained(original, scope)
                if original.request_digest != digest:
                    raise ValidationError(
                        "This key belongs to different intent.",
                        code="programme_starter_retry_conflict",
                    )
                return ProgrammeStarterRequestResult(
                    original.id, original.approval_deadline, replayed=True
                )
            _require_planning(scope)
            people = _lock_people({actor.id, normalized.approver_id})
            _require_controller(people[actor.id], targets)
            _require_controller(
                people[normalized.approver_id],
                targets,
                role=AuthorityControl.Role.APPROVER,
            )
            now = timezone.now()
            definition = PROGRAMME_STARTER_DEFINITION
            original = ProgrammeStarterRequest(
                organization_id=scope.organization_id,
                series_id=scope.series_id,
                edition_id=scope.edition_id,
                author_id=actor.id,
                approver_id=normalized.approver_id,
                definition_code=definition.code,
                definition_version=definition.version,
                definition_digest=definition.digest,
                requested_at=now,
                approval_deadline=now + timedelta(days=PROGRAMME_STARTER_APPROVAL_DAYS),
                reason=normalized.reason,
                idempotency_key=idempotency_key,
                request_digest=digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
            )
            original.source_audit_id = _audit(
                actor=people[actor.id],
                scope=scope,
                operation="workforce.programme_starter.request",
                target_id=original.id,
                target_type="workforce.programme_starter_request",
                correlation_id=correlation_id,
                source_channel=source_channel,
            )
            _append(original)
            return ProgrammeStarterRequestResult(
                original.id, original.approval_deadline, replayed=False
            )
    except IntegrityError as error:
        _retry_failure(error)


def decide_programme_starter(
    *,
    actor: Account,
    scope: ProgrammeStarterScope,
    request_id: UUID,
    action: ProgrammeStarterAction,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ProgrammeStarterDecisionResult:
    """Personally approve, decline or cancel retained fixed-template intent once.

    Parameters
    ----------
    actor : Account
        Actual named approver, or original author for cancellation only.
    scope : ProgrammeStarterScope
        Exact independently resolved original context.
    request_id : UUID
        Original request; foreign and unknown values are non-disclosing.
    action : ProgrammeStarterAction
        Exact own-person terminal action.
    reason : str
        This actor's rationale, separate from the author's original reason.
    idempotency_key : UUID
        Actor-bound original decision retry key.
    correlation_id : UUID
        Audit trace; does not change the retained retry identity.
    source_channel : str, default='service'
        Bounded source channel retained with canonical audit evidence.

    Returns
    -------
    ProgrammeStarterDecisionResult
        Original terminal outcome; approval publishes/reuses only fixed shared
        template meaning, never a Position, assignment or authority grant.

    Raises
    ------
    AuthorizationDenied
        For unavailable scope/authority or a person not permitted this own action.
    ValidationError
        For malformed intent, expiry, retry conflict or incompatible shared meaning.

    Notes
    -----
    Current admission, source locks and exact retry precede new decisions.
    Publication, public RoleBundle issuance/effects and terminal audit/evidence
    share one transaction. Any failure preserves pending intent without outputs.
    """
    _require_profile()
    normalized_reason = _reason(reason)
    digest = programme_starter_decision_digest(
        scope=scope, request_id=request_id, action=action, reason=normalized_reason
    )
    _validate_context(idempotency_key, correlation_id, source_channel)
    _require_actor(actor, _resolve_scope(scope))
    try:
        with transaction.atomic():
            lock_retired_department_authority_boundaries()
            _lock_key(actor.id, idempotency_key, "programme-starter-decision@1")
            _lock_scope(scope)
            targets = _resolve_scope(scope)
            _require_profile()
            _require_integrity()
            original = (
                ProgrammeStarterRequest.objects.select_for_update()
                .filter(
                    _scope_filter(scope),
                    Q(author_id=actor.id) | Q(approver_id=actor.id),
                    id=request_id,
                )
                .first()
            )
            if original is None or actor.id != (
                original.author_id
                if action is ProgrammeStarterAction.CANCEL
                else original.approver_id
            ):
                raise AuthorizationDenied(
                    "Programme Volunteer starter is unavailable.",
                    reason_code="programme_starter_unavailable",
                )
            _validate_retained(original, scope)
            terminal = ProgrammeStarterDecision.objects.filter(
                request_id=original.id
            ).first()
            identities = {actor.id}
            if terminal is None and action is ProgrammeStarterAction.APPROVE:
                identities.update((original.author_id, original.approver_id))
            people = _lock_people(identities)
            _require_controller(people[actor.id], targets)
            if terminal is not None:
                if (
                    terminal.actor_id != actor.id
                    or terminal.idempotency_key != idempotency_key
                    or terminal.request_digest != digest
                    or terminal.action != action.value
                ):
                    raise ValidationError(
                        "This request already has a terminal decision.",
                        code="programme_starter_retry_conflict",
                    )
                return _decision_result(terminal, replayed=True)
            if ProgrammeStarterDecision.objects.filter(
                _scope_filter(scope, prefix="request__"),
                actor_id=actor.id,
                idempotency_key=idempotency_key,
            ).exists():
                raise ValidationError(
                    "This key belongs to different intent.",
                    code="programme_starter_retry_conflict",
                )
            now = timezone.now()
            terminal = ProgrammeStarterDecision(
                request_id=original.id,
                actor_id=actor.id,
                action=action.value,
                decided_at=now,
                reason=normalized_reason,
                idempotency_key=idempotency_key,
                request_digest=digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
            )
            if action is ProgrammeStarterAction.APPROVE:
                if now >= original.approval_deadline:
                    raise ValidationError(
                        "This approval request has expired.",
                        code="programme_starter_approval_expired",
                    )
                _require_planning(scope)
                _require_controller(people[original.author_id], targets)
                _require_controller(
                    people[original.approver_id],
                    targets,
                    role=AuthorityControl.Role.APPROVER,
                )
                output = _existing_starter(organization_id=scope.organization_id)
                if output is None:
                    output = _create_starter_definition(
                        actor=people[original.author_id],
                        approver=people[original.approver_id],
                        organization_id=scope.organization_id,
                        organization_target=targets[0],
                        reason=original.reason,
                        correlation_id=correlation_id,
                        request_id=idempotency_key,
                        source_channel=source_channel,
                    )
                if not role_bundle_provenance_is_historical(
                    bundle=output.role_bundle, lock=True
                ):
                    raise ValidationError(
                        "The starter's immutable authority meaning is unavailable.",
                        code="programme_starter_provenance_unavailable",
                    )
                terminal.template_id, terminal.role_bundle_id = (
                    output.template.id,
                    output.role_bundle.id,
                )
                terminal.created_output = not output.replayed
            terminal.source_audit_id = _audit(
                actor=people[actor.id],
                scope=scope,
                operation=f"workforce.programme_starter.{action.value}",
                target_id=terminal.id,
                target_type="workforce.programme_starter_decision",
                correlation_id=correlation_id,
                source_channel=source_channel,
            )
            _append(terminal)
            return _decision_result(terminal, replayed=False)
    except IntegrityError as error:
        _retry_failure(error)
