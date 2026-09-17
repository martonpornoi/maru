"""Audited, exact-scope own-request projections for Programme approval review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.models import ProgrammeRoleDecisionRecord, ProgrammeRoleRequest
from maru.authorization.page_access_workspace import page_access_scope_label
from maru.authorization.policy import resolve_edition_target
from maru.authorization.programme_role_boundary import (
    _lock_people,
    _lock_scope,
    _require_actor,
    _require_current_controller,
    _require_integrity,
    _require_profile,
    _resolve_scope,
    _unavailable,
    _validate_context,
)
from maru.authorization.programme_role_commands import _retained_intent, _scope_filter
from maru.authorization.programme_role_inputs import (
    ProgrammeRoleScope,
    programme_role_intent_digest,
)
from maru.authorization.programme_role_recipes import (
    ProgrammeRoleRecipe,
    programme_role_recipe,
)
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied
from maru.identity.queries import active_verified_person_account_display_labels

if TYPE_CHECKING:
    from datetime import datetime

    from maru.identity.models import Account

MAX_PENDING_PROGRAMME_ROLE_REQUESTS = 100


@dataclass(frozen=True, slots=True)
class ProgrammeRoleReview:
    """Expose one authorized immutable intent and historical decision, not access.

    Attributes
    ----------
    request_id, author_id, approver_id, recipient_id
        Exact authorized locators, never a directory or caller-supplied authority.
    author_name, approver_name, recipient_name
        Current active verified display labels, otherwise a neutral fallback.
    recipe
        Exact admitted immutable task and capability consequences.
    requested_at, approval_deadline, not_before, expires_at
        Original UTC-aware request, approval deadline and desired access interval.
    reason
        Original minimized access rationale, separate from a decision's reason.
    state, decision_reason, decided_at, role_assignment_id
        Pending/expired or retained terminal outcome; no claim of effective access.
    can_approve, can_decline, can_cancel
        Own-person controls for this observed state, not command authorization.
    """

    request_id: UUID
    author_id: UUID
    approver_id: UUID
    recipient_id: UUID
    author_name: str
    approver_name: str
    recipient_name: str
    recipe: ProgrammeRoleRecipe
    requested_at: datetime
    approval_deadline: datetime
    not_before: datetime | None
    expires_at: datetime | None
    reason: str
    state: str
    decision_reason: str
    decided_at: datetime | None
    role_assignment_id: UUID | None
    can_approve: bool
    can_decline: bool
    can_cancel: bool

    @property
    def state_label(self) -> str:
        """Return lifecycle wording without claiming a historical grant is active."""
        return {
            "pending": "Pending",
            "expired": "Expired",
            "approve": "Approved",
            "decline": "Declined",
            "cancel": "Cancelled",
        }[self.state]


@dataclass(frozen=True, slots=True)
class ProgrammeRoleWorkspace:
    """Bind the complete bounded own-request projection to exact current labels.

    Attributes
    ----------
    scope_label, context_label
        Independently admitted actual grant target and Programme edition context.
    requests
        Complete open inventory or the single exact requested historical record.
    """

    scope_label: str
    context_label: str
    requests: tuple[ProgrammeRoleReview, ...]


def _recipe_for(
    row: ProgrammeRoleRequest, scope: ProgrammeRoleScope
) -> ProgrammeRoleRecipe:
    recipe = programme_role_recipe(row.recipe_code, row.recipe_version)
    if (
        recipe is None
        or recipe.digest != row.recipe_digest
        or programme_role_intent_digest(scope=scope, details=_retained_intent(row))
        != row.request_digest
    ):
        raise _unavailable()
    _require_profile(recipe)
    return recipe


def _project(
    row: ProgrammeRoleRequest,
    decision: ProgrammeRoleDecisionRecord | None,
    recipe: ProgrammeRoleRecipe,
    labels: dict[UUID, str],
    actor_id: UUID,
    now: datetime,
) -> ProgrammeRoleReview:
    expired = now >= row.approval_deadline or (
        row.expires_at is not None and now >= row.expires_at
    )
    state = decision.action if decision else "expired" if expired else "pending"
    identities = (row.author_id, row.approver_id, row.recipient_id)
    return ProgrammeRoleReview(
        row.id,
        *identities,
        labels.get(row.author_id, "Unavailable person"),
        labels.get(row.approver_id, "Unavailable person"),
        labels.get(row.recipient_id, "Unavailable person"),
        recipe,
        row.requested_at,
        row.approval_deadline,
        row.not_before,
        row.expires_at,
        row.reason,
        state,
        decision.reason if decision else "",
        decision.decided_at if decision else None,
        decision.role_assignment_id if decision else None,
        decision is None
        and not expired
        and actor_id == row.approver_id
        and all(identity in labels for identity in identities),
        decision is None and actor_id == row.approver_id,
        decision is None and actor_id == row.author_id,
    )


def load_programme_role_workspace(
    *,
    actor: Account,
    scope: ProgrammeRoleScope,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> ProgrammeRoleWorkspace:
    """Read only this current controller's authored or assigned requests.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; persistent authority is reloaded under locks.
    scope : ProgrammeRoleScope
        Full exact organization, Programme context and actual target chain.
    correlation_id : UUID
        Nonempty server trace for the sensitive read, including empty inventories.
    request_id : UUID | None, default=None
        Exact retained intent, or the complete bounded unexpired open inventory.
    source_channel : str, default='service'
        Bounded lowercase channel for minimized security evidence.

    Returns
    -------
    ProgrammeRoleWorkspace
        Immutable current labels and ceilinged requests after final admission/audit.

    Raises
    ------
    AuthorizationDenied
        For unsupported profile, unavailable scope, foreign intent or lost authority.
    ValidationError
        For malformed trace, incomplete integrity or overflow without partial output.

    Notes
    -----
    Recipient status and platform fallback alone never authorize this read. The
    inventory is not a history export. Exact terminal detail does not regrant or
    assert current effective authority. Adapters must recheck the projection after
    rendering and suppress output when its source or current admission changes.
    """
    _require_profile()
    _validate_context(correlation_id, correlation_id, source_channel)
    if request_id is not None and (
        not isinstance(request_id, UUID) or request_id.int == 0
    ):
        raise AuthorizationDenied(
            "Programme access is unavailable.", reason_code="programme_role_unavailable"
        )
    _require_actor(actor, _resolve_scope(scope))
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        target = _lock_scope(scope)
        current = _lock_people({actor.id})[actor.id]
        _require_profile()
        _require_integrity()
        _require_current_controller(current, target)
        now = timezone.now()
        query = ProgrammeRoleRequest.objects.filter(
            _scope_filter(scope), Q(author_id=current.id) | Q(approver_id=current.id)
        )
        if request_id is None:
            query = query.filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=now),
                approval_deadline__gt=now,
                decision__isnull=True,
            )
        else:
            query = query.filter(id=request_id)
        rows = tuple(
            query.order_by("requested_at", "id")[
                : MAX_PENDING_PROGRAMME_ROLE_REQUESTS + 1
            ]
        )
        if len(rows) > MAX_PENDING_PROGRAMME_ROLE_REQUESTS:
            raise ValidationError(
                "Too many open requests. Review known request links before retrying.",
                code="programme_role_inventory_overflow",
            )
        if request_id is not None and not rows:
            raise AuthorizationDenied(
                "Programme access is unavailable.",
                reason_code="programme_role_unavailable",
            )
        recipes = {row.id: _recipe_for(row, scope) for row in rows}
        decisions = {
            decision.request_id: decision
            for decision in ProgrammeRoleDecisionRecord.objects.filter(
                _scope_filter(scope, prefix="request__"),
                request_id__in=tuple(row.id for row in rows),
            )
        }
        identities = {
            identity
            for row in rows
            for identity in (row.author_id, row.approver_id, row.recipient_id)
        }
        labels = (
            active_verified_person_account_display_labels(identities)
            if identities
            else {}
        )
        context = resolve_edition_target(
            organization_id=scope.organization_id, edition_id=scope.programme_edition_id
        )
        if context is None:
            raise AuthorizationDenied(
                "Programme access is unavailable.",
                reason_code="programme_role_unavailable",
            )
        result = ProgrammeRoleWorkspace(
            page_access_scope_label(target),
            page_access_scope_label(context),
            tuple(
                _project(
                    row, decisions.get(row.id), recipes[row.id], labels, current.id, now
                )
                for row in rows
            ),
        )
        _require_profile()
        _require_current_controller(current, target)
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=current.id,
                principal_context_id=None,
                organization_id=scope.organization_id,
                event_edition_id=scope.programme_edition_id,
                capability_code="authorization.manage_roles",
                operation="authorization.programme_role.review",
                target_type="authorization.programme_role_request",
                target_id=request_id,
                outcome="allow",
                reason_code="own_request_review",
                correlation_id=correlation_id,
                source_channel=source_channel,
                obligations=("audit_sensitive_read",),
                safe_metadata={"target_count": len(rows)},
                retention_class="security-extended",
            )
        )
        return result
