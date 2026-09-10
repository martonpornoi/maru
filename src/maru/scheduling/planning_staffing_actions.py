"""Thin native staffing dispatch through independently authorized owning commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_STAFFING,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.staffing_commands import (
    ProgrammeStaffingCommandResult,
    change_programme_staffing_requirement,
)
from maru.programme.staffing_queries import ProgrammeStaffingReadRequest
from maru.workforce.programme_binding import (
    ProgrammeStaffingBindingPreview,
    ProgrammeStaffingBindingResult,
    apply_programme_staffing_binding,
    preview_programme_staffing_binding,
)
from maru.workforce.programme_staffing_queries import (
    authorize_programme_staffing_adapter,
)

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_PLANNING,
    SchedulingAuthorizer,
    authorize_scheduling_scope,
)
from .planning_queries import PLANNING_FIELDS, SchedulingReadRequest

if TYPE_CHECKING:
    from uuid import UUID

    from maru.identity.models import Account

    from .planning_staffing_forms import (
        PlanningStaffingBindingForm,
        PlanningStaffingRequirementForm,
    )


def _admit(
    scope: SchedulingReadRequest,
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> None:
    authorize_scheduling_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=VIEW_PLANNING,
        requested_fields=PLANNING_FIELDS,
        authorizer=scheduling_authorizer,
    )
    authorize_programme_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_VIEW_STAFFING,
        requested_fields=frozenset({"staffing_requirements"}),
        authorizer=programme_authorizer,
    )


def submit_planning_staffing_requirement(
    scope: SchedulingReadRequest,
    form: PlanningStaffingRequirementForm,
    *,
    item_id: UUID,
    occurrence_id: UUID,
    requirement_id: UUID | None,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeStaffingCommandResult | None:
    """Dispatch only the exact selected requirement and original optimistic intent.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Trusted authenticated actor, exact edition and request correlation.
    form : PlanningStaffingRequirementForm
        Original strict native input, never implicitly rebound to newer versions.
    item_id : UUID
        Independently resolved selected item in the authorized inventory.
    occurrence_id : UUID
        Independently resolved selected occurrence in that item.
    requirement_id : UUID | None
        Selected retained requirement, or None for explicit creation.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme current-read and mutation authority.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent private-planning read authority before input parsing.

    Returns
    -------
    ProgrammeStaffingCommandResult | None
        Retained owner result, or None with action-local validation errors.

    Notes
    -----
    Admission precedes form validation. The owner command rechecks authority,
    exact source, lifecycle and versions under canonical locks. This adapter
    creates no Workforce demand, claims, unrelated records or published timing.
    """
    _admit(scope, programme_authorizer, scheduling_authorizer)
    authorize_programme_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_MANAGE_STAFFING,
        authorizer=programme_authorizer,
    )
    change = form.change(item_id=item_id, occurrence_id=occurrence_id)
    if change is None:
        return None
    if change.requirement_id != requirement_id:
        form.add_error(
            None, "The submitted requirement does not match the selected task."
        )
        return None
    return change_programme_staffing_requirement(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        change=change,
        reason=form.cleaned_data["reason"],
        idempotency_key=form.cleaned_data["retry_key"],
        correlation_id=scope.correlation_id,
        source_channel="scheduling-staffing",
        authorizer=programme_authorizer,
    )


def submit_planning_staffing_binding(
    actor: Account,
    scope: SchedulingReadRequest,
    form: PlanningStaffingBindingForm,
    *,
    item_id: UUID,
    occurrence_id: UUID,
    requirement_id: UUID,
    candidate_id: UUID,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeStaffingBindingPreview | ProgrammeStaffingBindingResult | None:
    """Keep native impact preview and explicit apply as distinct owner operations.

    Parameters
    ----------
    actor : Account
        Trusted authenticated account passed to the existing Shift lifecycle.
    scope : SchedulingReadRequest
        Server-resolved actor, tenant, edition and correlation, not form values.
    form : PlanningStaffingBindingForm
        Strict original source, work intent and retry evidence.
    item_id : UUID
        Independently resolved selected Programme item.
    occurrence_id : UUID
        Selected occurrence; hidden input cannot change the visible target.
    requirement_id : UUID
        Selected requirement within the item.
    candidate_id : UUID
        Deliberately selected alternative, not the newest candidate revision.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme source-read and, for apply, mutation policy.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent private alternative read policy.

    Returns
    -------
    ProgrammeStaffingBindingPreview | ProgrammeStaffingBindingResult | None
        Audited preview, retained command result or action-local invalid input.

    Notes
    -----
    Preview never calls apply. Apply resolves the exact preview afresh, requires
    affirmative impact confirmation, and preserves the original retry key.
    Neither operation substitutes fresh versions into the submitted intent.
    """
    _admit(scope, programme_authorizer, scheduling_authorizer)
    authorize_programme_staffing_adapter(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        purpose="read",
    )
    change = form.change()
    if change is None:
        return None
    if (
        change.source.requirement_id,
        change.source.occurrence_id,
        change.source.candidate_id,
    ) != (requirement_id, occurrence_id, candidate_id):
        form.add_error(None, "The submitted source does not match the selected task.")
        return None
    request = ProgrammeStaffingReadRequest(
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        item_id,
        scope.correlation_id,
        "scheduling-staffing",
    )
    if form.cleaned_data["action"] == "staffing_preview":
        return preview_programme_staffing_binding(
            request,
            change=change,
            programme_authorizer=programme_authorizer,
            scheduling_authorizer=scheduling_authorizer,
        )
    return apply_programme_staffing_binding(
        actor,
        request,
        change=change,
        preview_digest=form.cleaned_data["preview_digest"],
        reason=form.cleaned_data["reason"],
        retry_key=form.cleaned_data["retry_key"],
        programme_authorizer=programme_authorizer,
        scheduling_authorizer=scheduling_authorizer,
    )
