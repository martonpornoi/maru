"""Actual-person Programme access requests and atomic independent decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization import commands as authority
from maru.authorization.catalog import ScopeLevel
from maru.authorization.models import ProgrammeRoleDecisionRecord, ProgrammeRoleRequest
from maru.authorization.programme_role_boundary import (
    _conflict,
    _exact_bundle,
    _lock_key,
    _lock_people,
    _lock_scope,
    _require_actor,
    _require_current_controller,
    _require_horizons,
    _require_integrity,
    _require_profile,
    _resolve_scope,
    _validate_context,
)
from maru.authorization.programme_role_inputs import (
    PROGRAMME_ROLE_APPROVAL_DAYS,
    ProgrammeRoleDecision,
    ProgrammeRoleIntent,
    ProgrammeRoleScope,
    _reason,
    normalize_programme_role_intent,
    programme_role_decision_digest,
    programme_role_intent_digest,
)
from maru.authorization.programme_role_recipes import programme_role_recipe
from maru.authorization.programme_role_writer import _programme_role_writer
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied

if TYPE_CHECKING:
    from uuid import UUID

    from maru.identity.models import Account


@dataclass(frozen=True, slots=True)
class ProgrammeRoleRequestResult:
    """Identify retained intent without returning person labels or granting access.

    Attributes
    ----------
    request_id, approval_deadline
        Original request identity and last permitted approval instant.
    replayed
        Whether this is an authorized exact retry, not a new pending request.
    """

    request_id: UUID
    approval_deadline: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class ProgrammeRoleDecisionResult:
    """Identify one retained terminal action, not current effective authority.

    Attributes
    ----------
    request_id, decision_id, action
        Original intent, immutable terminal result and actual action.
    role_assignment_id
        Original approved output, or None for decline/cancel. Replay never regrants.
    replayed
        Whether the actual principal recovered an existing identical decision.
    """

    request_id: UUID
    decision_id: UUID
    action: ProgrammeRoleDecision
    role_assignment_id: UUID | None
    replayed: bool


def _audit(
    *,
    actor: Account,
    scope: ProgrammeRoleScope,
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
            event_edition_id=scope.programme_edition_id,
            capability_code="authorization.manage_roles",
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome="allow",
            reason_code="own_person_action",
            correlation_id=correlation_id,
            source_channel=source_channel,
            retention_class="security-extended",
        )
    ).id


def _request_result(
    original: ProgrammeRoleRequest, *, replayed: bool
) -> ProgrammeRoleRequestResult:
    return ProgrammeRoleRequestResult(original.id, original.approval_deadline, replayed)


def _decision_result(
    original: ProgrammeRoleDecisionRecord, *, replayed: bool
) -> ProgrammeRoleDecisionResult:
    return ProgrammeRoleDecisionResult(
        original.request_id,
        original.id,
        ProgrammeRoleDecision(original.action),
        original.role_assignment_id,
        replayed,
    )


def _retained_intent(original: ProgrammeRoleRequest) -> ProgrammeRoleIntent:
    return ProgrammeRoleIntent(
        recipe_code=original.recipe_code,
        recipe_version=original.recipe_version,
        recipient_id=original.recipient_id,
        approver_id=original.approver_id,
        not_before=original.not_before,
        expires_at=original.expires_at,
        reason=original.reason,
    )


def _effective_start(details: ProgrammeRoleIntent, now: datetime) -> datetime:
    start = max(details.not_before or now, now)
    if details.expires_at is not None and details.expires_at <= start:
        raise _conflict("The requested access interval has ended.", "interval_expired")
    return start


def request_programme_role(
    *,
    actor: Account,
    scope: ProgrammeRoleScope,
    details: ProgrammeRoleIntent,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ProgrammeRoleRequestResult:
    """Retain one independently authorized proposal without granting any access.

    Parameters
    ----------
    actor : Account
        Authenticated author; must be a current verified person controller.
    scope : ProgrammeRoleScope
        Exact Programme context and requested target, independently resolved again.
    details : ProgrammeRoleIntent
        Immutable recipe, named independent approver, recipient, interval and reason.
    idempotency_key : UUID
        Author-bound original intent key; changed input conflicts.
    correlation_id : UUID
        Audit correlation, not evidence of approval or part of retry identity.
    source_channel : str, default='service'
        Bounded lowercase caller channel retained with the original audit.

    Returns
    -------
    ProgrammeRoleRequestResult
        Original minimized request identity and deadline, never authority.

    Raises
    ------
    AuthorizationDenied
        If profile, scope, people or current persistent sources are unavailable.
    ValidationError
        For invalid input, insufficient horizons, retry conflict or unsafe integrity.

    Notes
    -----
    Current profiles reject before database work. In an admitted candidate, shared
    authority fences precede canonical owner, person and source locks. Requests,
    audits and later terminal outcomes are retained; no invitation or message is sent.
    """
    _require_profile()
    normalized = normalize_programme_role_intent(details)
    digest = programme_role_intent_digest(scope=scope, details=normalized)
    recipe = programme_role_recipe(normalized.recipe_code, normalized.recipe_version)
    if recipe is None:
        raise AuthorizationDenied(
            "Programme access is unavailable.", reason_code="programme_role_unavailable"
        )
    _require_profile(recipe)
    _validate_context(idempotency_key, correlation_id, source_channel)
    if actor.id == normalized.approver_id:
        raise AuthorizationDenied(
            "Programme access is unavailable.", reason_code="programme_role_unavailable"
        )
    _require_actor(actor, _resolve_scope(scope))
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        _lock_key(actor.id, idempotency_key, "programme-role-request@1")
        target = _lock_scope(scope)
        _require_profile(recipe)
        _require_integrity()
        original = (
            ProgrammeRoleRequest.objects.select_for_update()
            .filter(author_id=actor.id, idempotency_key=idempotency_key)
            .first()
        )
        if original is not None:
            people = _lock_people({actor.id})
            _require_current_controller(people[actor.id], target)
            if original.request_digest != digest:
                raise ValidationError(
                    "This key belongs to different access intent.",
                    code="programme_role_retry_conflict",
                )
            return _request_result(original, replayed=True)
        people = _lock_people(
            {actor.id, normalized.approver_id, normalized.recipient_id}
        )
        now = timezone.now()
        start = _effective_start(normalized, now)
        _require_horizons(
            people[actor.id],
            people[normalized.approver_id],
            target,
            start,
            normalized.expires_at,
        )
        original = ProgrammeRoleRequest(
            organization_id=scope.organization_id,
            programme_edition_id=scope.programme_edition_id,
            edition_id=None
            if scope.level is ScopeLevel.ORGANIZATION
            else scope.programme_edition_id,
            department_id=scope.department_id,
            resource_binding_id=scope.resource_binding_id,
            scope_level=scope.level.value,
            author_id=actor.id,
            approver_id=normalized.approver_id,
            recipient_id=normalized.recipient_id,
            recipe_code=recipe.code,
            recipe_version=recipe.version,
            recipe_digest=recipe.digest,
            requested_at=now,
            approval_deadline=now + timedelta(days=PROGRAMME_ROLE_APPROVAL_DAYS),
            not_before=normalized.not_before,
            expires_at=normalized.expires_at,
            reason=normalized.reason,
            idempotency_key=idempotency_key,
            request_digest=digest,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        original.source_audit_id = _audit(
            actor=people[actor.id],
            scope=scope,
            operation="authorization.programme_role.request",
            target_id=original.id,
            target_type="authorization.programme_role_request",
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        with _programme_role_writer():
            original.save(force_insert=True)
        return _request_result(original, replayed=False)


def decide_programme_role(
    *,
    actor: Account,
    scope: ProgrammeRoleScope,
    request_id: UUID,
    action: ProgrammeRoleDecision,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ProgrammeRoleDecisionResult:
    """Commit an actual person's terminal decision and any exact grant atomically.

    Parameters
    ----------
    actor : Account
        Authenticated named approver for approve/decline, or original author for cancel.
    scope : ProgrammeRoleScope
        Exact authorized owner chain; foreign requests remain unavailable.
    request_id : UUID
        Original immutable request, not a replacement recipient or permission list.
    action : ProgrammeRoleDecision
        One deliberate approve, decline or cancel action.
    reason : str
        Required bounded decision rationale, separate from original grant intent.
    idempotency_key : UUID
        Actual-person retry identity; changed intent or a second outcome conflicts.
    correlation_id : UUID
        Shared trace for decision, assignment, provenance and canonical owner audits.
    source_channel : str, default='service'
        Bounded lowercase caller channel; no automatic notification is produced.

    Returns
    -------
    ProgrammeRoleDecisionResult
        Original terminal identifiers, not evidence of still-active approved access.

    Raises
    ------
    AuthorizationDenied
        For unavailable profile/scope, unrelated principal or revoked current authority.
    ValidationError
        For invalid input, expiry, conflict, stale recipe or unavailable integrity.

    Notes
    -----
    The approving principal must personally call this command. Both current
    controllers and exact immutable role provenance are checked under shared locks.
    Role creation/assignment, decision and all success evidence roll back together.
    Decline/cancel grants nothing. Terminal replay reauthorizes only its actual actor.
    """
    _require_profile()
    digest = programme_role_decision_digest(
        request_id=request_id, decision=action, reason=reason
    )
    normalized_reason = _reason(reason)
    _validate_context(idempotency_key, correlation_id, source_channel)
    _require_actor(actor, _resolve_scope(scope))
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        _lock_key(actor.id, idempotency_key, "programme-role-decision@1")
        target = _lock_scope(scope)
        _require_profile()
        _require_integrity()
        requests = ProgrammeRoleRequest.objects.select_for_update().filter(
            id=request_id,
            organization_id=scope.organization_id,
            programme_edition_id=scope.programme_edition_id,
            scope_level=scope.level.value,
            resource_binding_id=scope.resource_binding_id,
        )
        requests = (
            requests.filter(department__isnull=True)
            if scope.department_id is None
            else requests.filter(department_id=scope.department_id)
        )
        original = requests.first()
        if original is None or actor.id != (
            original.author_id
            if action is ProgrammeRoleDecision.CANCEL
            else original.approver_id
        ):
            raise AuthorizationDenied(
                "Programme access is unavailable.",
                reason_code="programme_role_unavailable",
            )
        details = _retained_intent(original)
        recipe = programme_role_recipe(details.recipe_code, details.recipe_version)
        if (
            recipe is None
            or recipe.digest != original.recipe_digest
            or (
                programme_role_intent_digest(scope=scope, details=details)
                != original.request_digest
            )
        ):
            raise AuthorizationDenied(
                "Programme access is unavailable.",
                reason_code="programme_role_unavailable",
            )
        _require_profile(recipe)
        terminal = ProgrammeRoleDecisionRecord.objects.filter(
            request_id=original.id
        ).first()
        if terminal is not None:
            people = _lock_people({actor.id})
            _require_current_controller(people[actor.id], target)
            if (
                terminal.actor_id,
                terminal.idempotency_key,
                terminal.request_digest,
            ) != (actor.id, idempotency_key, digest):
                raise ValidationError(
                    "This request already has a terminal decision.",
                    code="programme_role_decision_conflict",
                )
            return _decision_result(terminal, replayed=True)
        identities = {actor.id}
        if action is ProgrammeRoleDecision.APPROVE:
            identities.update(
                (original.author_id, original.approver_id, original.recipient_id)
            )
        people = _lock_people(identities)
        _require_current_controller(people[actor.id], target)
        if ProgrammeRoleDecisionRecord.objects.filter(
            actor_id=actor.id, idempotency_key=idempotency_key
        ).exists():
            raise ValidationError(
                "This key belongs to another decision.",
                code="programme_role_retry_conflict",
            )
        now = timezone.now()
        terminal = ProgrammeRoleDecisionRecord(
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
        if action is ProgrammeRoleDecision.APPROVE:
            if now >= original.approval_deadline:
                raise ValidationError(
                    "This approval request has expired.",
                    code="programme_role_approval_expired",
                )
            start = _effective_start(details, now)
            _require_horizons(
                people[original.author_id],
                people[original.approver_id],
                target,
                start,
                details.expires_at,
            )
            bundle = _exact_bundle(
                scope=scope,
                recipe=recipe,
                author=people[original.author_id],
                approver=people[original.approver_id],
                reason=original.reason,
                correlation_id=correlation_id,
                source_channel=source_channel,
            )
            assignment = authority.assign_role(
                actor=people[original.author_id],
                approver=people[original.approver_id],
                recipient=people[original.recipient_id],
                target=target,
                role_bundle_id=bundle.id,
                effective_from=start,
                expires_at=details.expires_at,
                reason=original.reason,
                correlation_id=correlation_id,
                source_channel=source_channel,
            )
            terminal.role_bundle_id, terminal.role_assignment_id = (
                bundle.id,
                assignment.id,
            )
        terminal.source_audit_id = _audit(
            actor=people[actor.id],
            scope=scope,
            operation=f"authorization.programme_role.{action.value}",
            target_id=terminal.id,
            target_type="authorization.programme_role_decision",
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        with _programme_role_writer():
            terminal.save(force_insert=True)
        return _decision_result(terminal, replayed=False)
