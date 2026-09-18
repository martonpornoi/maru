"""Audited fixed-template preview with original known-person selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.models import AuthorityControl
from maru.authorization.page_access_workspace import page_access_scope_label
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied
from maru.events.queries import resolve_private_planning_edition_reference
from maru.identity.queries import (
    active_verified_person_account_display_labels,
    resolve_active_verified_person_reference_by_email,
)
from maru.workforce.programme_starter_boundary import (
    _lock_people,
    _lock_scope,
    _require_actor,
    _require_controller,
    _require_integrity,
    _require_planning,
    _require_profile,
    _resolve_scope,
    _unavailable,
)
from maru.workforce.programme_starter_inputs import (
    PROGRAMME_STARTER_DEFINITION,
    ProgrammeStarterDefinition,
    ProgrammeStarterScope,
    _validate_context,
)
from maru.workforce.programme_starter_selection import (
    ProgrammeStarterDraft,
    ProgrammeStarterSelection,
    _selector,
    _sign_selection,
    verify_programme_starter_selection,
)

if TYPE_CHECKING:
    from maru.identity.models import Account


@dataclass(frozen=True, slots=True)
class ProgrammeStarterCreation:
    """Explain fixed shared meaning and optional exact original-person preview.

    Attributes
    ----------
    organization_label, edition_label
        Independently admitted definition owner and motivating Programme context.
    definition
        Single immutable minimal Volunteer template, never a custom-role editor.
    can_request
        Current planning phase; commands still authorize each new request/retry.
    selection
        Signed original intent, or None before a complete eligible fresh preview.
    approver_name
        Current eligible display label or neutral original-selection fallback.
    """

    organization_label: str
    edition_label: str
    definition: ProgrammeStarterDefinition
    can_request: bool
    selection: ProgrammeStarterSelection | None = None
    approver_name: str = ""


def _load(
    actor: Account,
    scope: ProgrammeStarterScope,
    correlation_id: UUID,
    source_channel: str,
    draft: ProgrammeStarterDraft | None,
    proof: str | None,
) -> ProgrammeStarterCreation:
    _require_profile()
    _validate_context(correlation_id, correlation_id, source_channel)
    _require_actor(actor, _resolve_scope(scope))
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        _lock_scope(scope)
        targets = _resolve_scope(scope)
        _require_profile()
        _require_integrity()
        selected_id = None
        selection = None
        identities = {actor.id}
        if draft is not None:
            _selector(draft)
            draft.intent(UUID(int=1))
            if proof is None:
                _require_planning(scope)
                person = resolve_active_verified_person_reference_by_email(
                    email=_selector(draft)
                )
                if person is not None and person.account_id != actor.id:
                    selected_id = person.account_id
                    identities.add(selected_id)
            else:
                selection = verify_programme_starter_selection(
                    actor_id=actor.id, scope=scope, draft=draft, proof=proof
                )
        people = _lock_people(identities)
        current = people[actor.id]
        _require_controller(current, targets)
        if selected_id is not None and draft is not None:
            try:
                _require_controller(
                    people[selected_id], targets, role=AuthorityControl.Role.APPROVER
                )
            except AuthorizationDenied:
                selected_id = None
            if selected_id is not None:
                selection = _sign_selection(current.id, scope, draft, selected_id)
        label = ""
        if selection is not None:
            selected_id = selection.details.approver_id
            labels = active_verified_person_account_display_labels({selected_id})
            if proof is None and selected_id not in labels:
                selection = None
            else:
                label = labels.get(selected_id, "Unavailable person")
        reference = resolve_private_planning_edition_reference(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        if reference is None:
            raise _unavailable()
        result = ProgrammeStarterCreation(
            page_access_scope_label(targets[0]),
            page_access_scope_label(targets[1]),
            PROGRAMME_STARTER_DEFINITION,
            reference.accepts_private_planning_writes,
            selection,
            label,
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
                operation="workforce.programme_starter.preview",
                target_type="workforce.programme_starter_request",
                target_id=None,
                outcome="allow",
                reason_code="own_request_preview",
                correlation_id=correlation_id,
                source_channel=source_channel,
                obligations=("audit_sensitive_read",),
                retention_class="security-extended",
            )
        )
        return result


def load_programme_starter_creation(
    *,
    actor: Account,
    scope: ProgrammeStarterScope,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ProgrammeStarterCreation:
    """Load the fixed shared meaning without a person lookup or retained request.

    Parameters
    ----------
    actor : Account
        Actual current ordinary controller; platform fallback is not accepted.
    scope : ProgrammeStarterScope
        Complete exact Programme context and shared-definition owner.
    correlation_id : UUID
        Nonempty trace for the audited purpose-specific read.
    source_channel : str, default='service'
        Bounded caller channel.

    Returns
    -------
    ProgrammeStarterCreation
        Current admitted labels, fixed meaning and phase with no selected person.
    """
    return _load(actor, scope, correlation_id, source_channel, None, None)


def prepare_programme_starter_creation(
    *,
    actor: Account,
    scope: ProgrammeStarterScope,
    draft: ProgrammeStarterDraft,
    correlation_id: UUID,
    proof: str | None = None,
    source_channel: str = "service",
) -> ProgrammeStarterCreation:
    """Preview a fresh known approver or recover exact signed original selection.

    Parameters
    ----------
    actor : Account
        Actual authenticated author, currently admitted before any name disclosure.
    scope : ProgrammeStarterScope
        Original complete organization/series/edition context.
    draft : ProgrammeStarterDraft
        Original known selector, bounded rationale and author-bound retry key.
    correlation_id : UUID
        Nonempty read trace; never part of the retry intent.
    proof : str | None, default=None
        Original signed selection; when provided, no mutable email is looked up.
    source_channel : str, default='service'
        Bounded caller channel retained with the sensitive-read audit.

    Returns
    -------
    ProgrammeStarterCreation
        Exact admitted meaning/selection or a non-disclosing unavailable selection.

    Notes
    -----
    This query creates no request, template, approval or message. Original proof
    is not refreshed after expiry or person/authority changes; the command decides
    whether new intent is permitted or an original retry can be recovered.
    """
    return _load(actor, scope, correlation_id, source_channel, draft, proof)
