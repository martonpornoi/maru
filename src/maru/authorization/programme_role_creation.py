"""Audited exact-scope role choices and original known-person request previews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import ScopeLevel
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
from maru.authorization.programme_role_recipes import (
    PROGRAMME_ROLE_RECIPES,
    ProgrammeRoleRecipe,
)
from maru.authorization.programme_role_selection import (
    ProgrammeRoleRequestDraft,
    ProgrammeRoleSelection,
    _selectors,
    _sign_selection,
    verify_programme_role_selection,
)
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.events.adoption import (
    profile_allows_capabilities,
    profile_allows_catalog_entry,
)
from maru.identity.queries import (
    active_verified_person_account_display_labels,
    resolve_active_verified_person_reference_by_email,
)

if TYPE_CHECKING:
    from maru.authorization.programme_role_inputs import ProgrammeRoleScope
    from maru.identity.models import Account


@dataclass(frozen=True, slots=True)
class ProgrammeRoleCreation:
    """Expose admitted scope and choices with an optional exact-person preview.

    Attributes
    ----------
    scope_label, context_label
        Current independently admitted actual target and Programme context labels.
    recipes
        Complete code-owned definitions admitted at this exact target and profile.
    selection
        Original signed terms, or None for ordinary input or no eligible match.
    recipient_name, approver_name
        Current minimized person labels, never a contact or controller directory.
        Missing people on original retry receive a neutral label, not new selection.
    """

    scope_label: str
    context_label: str
    recipes: tuple[ProgrammeRoleRecipe, ...]
    selection: ProgrammeRoleSelection | None = None
    recipient_name: str = ""
    approver_name: str = ""


def _recipes(scope: ProgrammeRoleScope) -> tuple[ProgrammeRoleRecipe, ...]:
    return tuple(
        recipe
        for recipe in PROGRAMME_ROLE_RECIPES.values()
        if scope.level in recipe.target_scopes
        and (
            scope.level is not ScopeLevel.RESOURCE
            or recipe.resource_kind == scope.resource_kind
        )
        and profile_allows_catalog_entry(
            "programme_operations", 1, recipe.catalog_entry
        )
        and profile_allows_capabilities(
            "programme_operations", 1, recipe.capability_codes
        )
    )


def _load(
    actor: Account,
    scope: ProgrammeRoleScope,
    correlation_id: UUID,
    source_channel: str,
    draft: ProgrammeRoleRequestDraft | None,
    proof: str | None,
) -> ProgrammeRoleCreation:
    _require_profile()
    _validate_context(correlation_id, correlation_id, source_channel)
    _require_actor(actor, _resolve_scope(scope))
    with transaction.atomic():
        lock_retired_department_authority_boundaries()
        target = _lock_scope(scope)
        current = _lock_people({actor.id})[actor.id]
        _require_profile()
        _require_integrity()
        _require_current_controller(current, target)
        recipes = _recipes(scope)
        selection = None
        labels: dict[UUID, str] = {}
        if draft is not None:
            if not any(
                (recipe.code, recipe.version)
                == (draft.recipe_code, draft.recipe_version)
                for recipe in recipes
            ):
                raise _unavailable()
            if proof is None:
                recipient_email, approver_email = _selectors(draft)
                # Validate all pure terms before the purpose-limited person lookups.
                draft.intent(UUID(int=1), UUID(int=2))
                recipient = resolve_active_verified_person_reference_by_email(
                    email=recipient_email
                )
                approver = resolve_active_verified_person_reference_by_email(
                    email=approver_email
                )
                if recipient is not None and approver is not None:
                    selection = _sign_selection(
                        current.id,
                        scope,
                        draft,
                        recipient.account_id,
                        approver.account_id,
                    )
            else:
                selection = verify_programme_role_selection(
                    actor_id=current.id, scope=scope, draft=draft, proof=proof
                )
            if selection is not None:
                identities = {
                    selection.details.recipient_id,
                    selection.details.approver_id,
                }
                labels = active_verified_person_account_display_labels(identities)
                if proof is None and set(labels) != identities:
                    # Fresh preparation must not offer a partly vanished selection.
                    selection = None
                    labels = {}
        context = resolve_edition_target(
            organization_id=scope.organization_id, edition_id=scope.programme_edition_id
        )
        if context is None:
            raise _unavailable()
        result = ProgrammeRoleCreation(
            page_access_scope_label(target),
            page_access_scope_label(context),
            recipes,
            selection,
            labels.get(selection.details.recipient_id, "Unavailable person")
            if selection
            else "",
            labels.get(selection.details.approver_id, "Unavailable person")
            if selection
            else "",
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
                operation="authorization.programme_role.prepare",
                target_type="authorization.programme_role_request",
                target_id=None,
                outcome="allow",
                reason_code="exact_request_preparation",
                correlation_id=correlation_id,
                source_channel=source_channel,
                obligations=("audit_sensitive_read",),
                safe_metadata={"target_count": 2 if selection else 0},
                retention_class="security-extended",
            )
        )
        return result


def load_programme_role_creation(
    *,
    actor: Account,
    scope: ProgrammeRoleScope,
    correlation_id: UUID,
    source_channel: str = "service",
    original: tuple[ProgrammeRoleRequestDraft, str] | None = None,
) -> ProgrammeRoleCreation:
    """Read exact current choices and optionally refresh an original signed preview.

    Parameters
    ----------
    actor : Account
        Actual authenticated person, reloaded under current controller locks.
    scope : ProgrammeRoleScope
        Complete route-owned organization, Programme context and target chain.
    correlation_id : UUID
        Nonempty server trace for the sensitive read, including empty choices.
    source_channel : str, default='service'
        Bounded lowercase audit channel.
    original : tuple[ProgrammeRoleRequestDraft, str] | None, default=None
        Original input and proof to verify without resolving any mutable address.

    Returns
    -------
    ProgrammeRoleCreation
        Audited current labels and exact choices, never a request or permission.

    Notes
    -----
    Current profiles deny before database access. Ordinary current controller,
    exact owner scope and native integrity are rechecked under canonical locks.
    An unavailable selected person is not replaced; only the existing command
    decides whether an original retry or new request remains permitted.
    """
    return _load(
        actor,
        scope,
        correlation_id,
        source_channel,
        original[0] if original else None,
        original[1] if original else None,
    )


def prepare_programme_role_creation(
    *,
    actor: Account,
    scope: ProgrammeRoleScope,
    draft: ProgrammeRoleRequestDraft,
    correlation_id: UUID,
    source_channel: str = "service",
) -> ProgrammeRoleCreation:
    """Select two known people once under audited exact-purpose controller admission.

    Parameters
    ----------
    actor : Account
        Actual authenticated original author, never a platform fallback.
    scope : ProgrammeRoleScope
        Exact independently resolved Programme context and actual target.
    draft : ProgrammeRoleRequestDraft
        Closed original selectors, role, interval, rationale and retry identity.
    correlation_id : UUID
        Server trace for the sensitive preparation, including an empty match.
    source_channel : str, default='service'
        Bounded lowercase audit channel.

    Returns
    -------
    ProgrammeRoleCreation
        Signed original selection or the same neutral empty match for unavailable
        people. No request, invitation, role, assignment or message is created.
    """
    return _load(actor, scope, correlation_id, source_channel, draft, None)
