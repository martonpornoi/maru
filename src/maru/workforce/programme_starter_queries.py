"""Audited exact-scope own-person review of retained Volunteer starter intent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.page_access_workspace import page_access_scope_label
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied
from maru.events.queries import resolve_private_planning_edition_reference
from maru.identity.queries import active_verified_person_account_display_labels
from maru.workforce.models import ProgrammeStarterDecision, ProgrammeStarterRequest
from maru.workforce.programme_starter_boundary import (
    _lock_people,
    _lock_scope,
    _require_actor,
    _require_controller,
    _require_integrity,
    _require_profile,
    _resolve_scope,
    _unavailable,
)
from maru.workforce.programme_starter_commands import _scope_filter, _validate_retained
from maru.workforce.programme_starter_inputs import (
    PROGRAMME_STARTER_DEFINITION,
    ProgrammeStarterAction,
    ProgrammeStarterDefinition,
    ProgrammeStarterScope,
    _validate_context,
    programme_starter_decision_digest,
)

if TYPE_CHECKING:
    from datetime import datetime

    from maru.identity.models import Account

MAX_PENDING_PROGRAMME_STARTER_REQUESTS = 100


@dataclass(frozen=True, slots=True)
class ProgrammeStarterReview:
    """Expose one own intent and historical output, never an authority grant.

    Attributes
    ----------
    request_id, author_id, approver_id
        Original independently authorized scope-bound locators.
    author_name, approver_name
        Current eligible display names or a neutral unavailable-person fallback.
    requested_at, approval_deadline, reason
        Original request terms; no mutable selector or contact directory.
    state, decision_reason, decided_at
        Pending/expired or actual retained terminal outcome and separate rationale.
    template_id, role_bundle_id, created_output
        Historical exact shared meaning; not current access or a Position.
    can_approve, can_decline, can_cancel
        Observed own-person controls; every command independently reauthorizes.
    """

    request_id: UUID
    author_id: UUID
    approver_id: UUID
    author_name: str
    approver_name: str
    requested_at: datetime
    approval_deadline: datetime
    reason: str
    state: str
    decision_reason: str
    decided_at: datetime | None
    template_id: UUID | None
    role_bundle_id: UUID | None
    created_output: bool
    can_approve: bool
    can_decline: bool
    can_cancel: bool

    @property
    def state_label(self) -> str:
        """Describe retained outcome without implying an effective grant."""
        return {
            "pending": "Pending",
            "expired": "Expired",
            "approve": "Approved",
            "decline": "Declined",
            "cancel": "Cancelled",
        }[self.state]


@dataclass(frozen=True, slots=True)
class ProgrammeStarterWorkspace:
    """Bind the complete own-request inventory to shared and originating scope.

    Attributes
    ----------
    organization_label, edition_label
        Authorized shared-definition owner and motivating Programme context.
    definition
        Single fixed template meaning, not a configurable catalog.
    can_request
        Current private-planning phase; commands still reauthorize actual creation.
    requests
        Complete bounded open inventory or one exact historical request.
    """

    organization_label: str
    edition_label: str
    definition: ProgrammeStarterDefinition
    can_request: bool
    requests: tuple[ProgrammeStarterReview, ...]


def _validate_decision(
    row: ProgrammeStarterRequest,
    decision: ProgrammeStarterDecision,
    scope: ProgrammeStarterScope,
) -> None:
    try:
        action = ProgrammeStarterAction(decision.action)
        digest = programme_starter_decision_digest(
            scope=scope, request_id=row.id, action=action, reason=decision.reason
        )
    except (ValueError, ValidationError):
        raise _unavailable() from None
    actor_id = (
        row.author_id if action is ProgrammeStarterAction.CANCEL else row.approver_id
    )
    if (
        decision.request_id != row.id
        or decision.actor_id != actor_id
        or decision.request_digest != digest
    ):
        raise _unavailable()


def _project(
    row: ProgrammeStarterRequest,
    decision: ProgrammeStarterDecision | None,
    labels: dict[UUID, str],
    actor_id: UUID,
    now: datetime,
    *,
    planning: bool,
) -> ProgrammeStarterReview:
    expired = now >= row.approval_deadline
    return ProgrammeStarterReview(
        row.id,
        row.author_id,
        row.approver_id,
        labels.get(row.author_id, "Unavailable person"),
        labels.get(row.approver_id, "Unavailable person"),
        row.requested_at,
        row.approval_deadline,
        row.reason,
        decision.action if decision else "expired" if expired else "pending",
        decision.reason if decision else "",
        decision.decided_at if decision else None,
        decision.template_id if decision else None,
        decision.role_bundle_id if decision else None,
        decision.created_output if decision else False,
        decision is None
        and not expired
        and planning
        and actor_id == row.approver_id
        and all(identity in labels for identity in (row.author_id, row.approver_id)),
        decision is None and actor_id == row.approver_id,
        decision is None and actor_id == row.author_id,
    )


def load_programme_starter_workspace(
    *,
    actor: Account,
    scope: ProgrammeStarterScope,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> ProgrammeStarterWorkspace:
    """Read only the actual current controller's authored or assigned intent.

    Parameters
    ----------
    actor : Account
        Actual authenticated ordinary person, reloaded and authorized under locks.
    scope : ProgrammeStarterScope
        Full organization/series/Programme-edition route chain.
    correlation_id : UUID
        Nonempty trace for the sensitive read, including empty inventories.
    request_id : UUID | None, default=None
        Exact known historical intent, or complete bounded open inventory.
    source_channel : str, default='service'
        Bounded caller channel; never a principal or permission override.

    Returns
    -------
    ProgrammeStarterWorkspace
        Scope/meaning and own-request projections only after final admission/audit.

    Raises
    ------
    AuthorizationDenied
        For unavailable profile/scope/authority or unknown/foreign original intent.
    ValidationError
        For malformed trace, incomplete integrity or overflow without partial data.

    Notes
    -----
    Adapters repeat this owning query after rendering and suppress changed output.
    A terminal template identity is history, not an effective authority claim.
    """
    _require_profile()
    _validate_context(correlation_id, correlation_id, source_channel)
    if request_id is not None and (
        not isinstance(request_id, UUID) or not request_id.int
    ):
        raise AuthorizationDenied(
            "Programme starter review is unavailable.",
            reason_code="programme_starter_unavailable",
        )
    _require_actor(actor, _resolve_scope(scope))
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        _lock_scope(scope)
        targets = _resolve_scope(scope)
        current = _lock_people({actor.id})[actor.id]
        _require_profile()
        _require_integrity()
        _require_controller(current, targets)
        now = timezone.now()
        query = ProgrammeStarterRequest.objects.filter(
            _scope_filter(scope), Q(author_id=current.id) | Q(approver_id=current.id)
        )
        query = (
            query.filter(approval_deadline__gt=now, decision__isnull=True)
            if request_id is None
            else query.filter(id=request_id)
        )
        rows = tuple(
            query.order_by("requested_at", "id")[
                : MAX_PENDING_PROGRAMME_STARTER_REQUESTS + 1
            ]
        )
        if len(rows) > MAX_PENDING_PROGRAMME_STARTER_REQUESTS:
            raise ValidationError(
                "Too many open requests. Review known original request links.",
                code="programme_starter_inventory_overflow",
            )
        if request_id is not None and not rows:
            raise AuthorizationDenied(
                "Programme starter review is unavailable.",
                reason_code="programme_starter_unavailable",
            )
        for row in rows:
            _validate_retained(row, scope)
        decisions = {
            item.request_id: item
            for item in ProgrammeStarterDecision.objects.filter(
                _scope_filter(scope, prefix="request__"),
                request_id__in=tuple(row.id for row in rows),
            )
        }
        for row in rows:
            if row.id in decisions:
                _validate_decision(row, decisions[row.id], scope)
        identities = {
            identity for row in rows for identity in (row.author_id, row.approver_id)
        }
        labels = (
            active_verified_person_account_display_labels(identities)
            if identities
            else {}
        )
        reference = resolve_private_planning_edition_reference(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        if reference is None:
            raise AuthorizationDenied(
                "Programme starter review is unavailable.",
                reason_code="programme_starter_unavailable",
            )
        planning = reference.accepts_private_planning_writes
        result = ProgrammeStarterWorkspace(
            page_access_scope_label(targets[0]),
            page_access_scope_label(targets[1]),
            PROGRAMME_STARTER_DEFINITION,
            planning,
            tuple(
                _project(
                    row,
                    decisions.get(row.id),
                    labels,
                    current.id,
                    now,
                    planning=planning,
                )
                for row in rows
            ),
        )
        _require_profile()
        _require_controller(current, _resolve_scope(scope))
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=current.id,
                principal_context_id=None,
                organization_id=scope.organization_id,
                event_edition_id=scope.edition_id,
                capability_code="workforce.manage_structure",
                operation="workforce.programme_starter.review",
                target_type="workforce.programme_starter_request",
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
