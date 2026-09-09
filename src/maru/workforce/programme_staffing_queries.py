"""Authorized exact-demand work terms for deliberate staffing impact previews."""

from __future__ import annotations

from dataclasses import fields
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.programme.staffing_inputs import ProgrammeStaffingExpectation

from .adoption import WORKFORCE_PROGRAMME_STAFFING_ADAPTER
from .models import ShiftCommitment, ShiftDemand
from .programme_impact import ProgrammeStaffingDemandState, _validated_demand
from .programme_references import lock_programme_staffing_scope

PROGRAMME_STAFFING_DEMAND_FIELDS = frozenset({"shift_demands", "coverage_states"})


class ProgrammeStaffingDeniedError(RuntimeError):
    """Withhold existence when independent staffing adapter authority is absent."""


class ProgrammeStaffingUnavailableError(RuntimeError):
    """Report one absent, foreign or inconsistent exact staffing source uniformly."""


def authorize_programme_staffing_adapter(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    purpose: Literal["read", "write"],
) -> PolicyDecision:
    """Require independent owner authority and the exact, currently dormant adapter.

    Parameters
    ----------
    actor_id : UUID
        Trusted current principal, resolved by the ordinary identity policy.
    organization_id : UUID
        Exact expected owner.
    edition_id : UUID
        Exact edition target; wider discovery authority is not substituted.
    purpose : Literal['read', 'write']
        Closed caller-owned purpose. Write authority does not grant a work read.

    Returns
    -------
    PolicyDecision
        Current owner decision, not portable authority for a later action.

    Raises
    ------
    ProgrammeStaffingDeniedError
        If the scope, purpose, field authority or exact adapter is unavailable.
    """
    if purpose not in ("read", "write") or any(
        not isinstance(value, UUID) for value in (actor_id, organization_id, edition_id)
    ):
        raise ProgrammeStaffingDeniedError
    requested_fields = PROGRAMME_STAFFING_DEMAND_FIELDS if purpose == "read" else None
    decision = decide_verified_principal_exact_edition(
        principal_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="workforce.view_shifts"
        if purpose == "read"
        else "workforce.manage_shifts",
        requested_fields=requested_fields,
    )
    if not decision.allowed or (
        requested_fields is not None and not decision.fields >= requested_fields
    ):
        raise ProgrammeStaffingDeniedError
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, WORKFORCE_PROGRAMME_STAFFING_ADAPTER
    ):
        raise ProgrammeStaffingDeniedError
    return decision


def _load_demand(
    *, organization_id: UUID, edition_id: UUID, demand_id: UUID
) -> ProgrammeStaffingDemandState:
    work_fields = tuple(field.name for field in fields(ProgrammeStaffingExpectation))
    row = (
        ShiftDemand.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            id=demand_id,
        )
        .values("id", "command_version", "status", *work_fields)
        .first()
    )
    if row is None:
        raise ProgrammeStaffingUnavailableError
    counts = ShiftCommitment.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
        demand_id=demand_id,
    ).aggregate(
        retained=Count("id"),
        claimed=Count("id", filter=Q(status="claimed")),
        confirmed=Count("id", filter=Q(status="confirmed")),
    )
    result = ProgrammeStaffingDemandState(
        demand_id=row["id"],
        version=row["command_version"],
        status=row["status"],
        expectation=ProgrammeStaffingExpectation(
            **{field: row[field] for field in work_fields}
        ),
        retained_commitments=counts["retained"],
        claimed=counts["claimed"],
        confirmed=counts["confirmed"],
    )
    _validated_demand(result)
    return result


def load_programme_staffing_demand(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    demand_id: UUID,
    correlation_id: UUID,
) -> ProgrammeStaffingDemandState:
    """Read one current work expectation and aggregate impact without personnel.

    Parameters
    ----------
    actor_id : UUID
        Authenticated principal with independent Workforce work-field authority.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact owning edition, locked in canonical cross-owner order.
    demand_id : UUID
        Explicit selected demand; parsed only after admission.
    correlation_id : UUID
        Trusted correlation identifier for mandatory sensitive-read evidence.

    Returns
    -------
    ProgrammeStaffingDemandState
        One complete work expectation and retained/active counts, without names.

    Raises
    ------
    ProgrammeStaffingUnavailableError
        If selection or correlation is malformed, or the exact source is absent.

    Notes
    -----
    This separate adapter may disclose work briefings under shift_demands; the
    minimized planning coverage adapter still cannot. It selects no personnel,
    private cancellation/confirmation rationale or availability. The canonical
    scope serializes governed lifecycle/commitment writes. A composing writer
    acquires that scope before other owners, then resolves again before commit.
    """
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    authorize_programme_staffing_adapter(**scope, purpose="read")
    if not isinstance(demand_id, UUID) or not isinstance(correlation_id, UUID):
        raise ProgrammeStaffingUnavailableError
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        authorize_programme_staffing_adapter(**scope, purpose="read")
        result = _load_demand(
            organization_id=organization_id, edition_id=edition_id, demand_id=demand_id
        )
        decision = authorize_programme_staffing_adapter(**scope, purpose="read")
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="workforce.view_shifts",
                operation="workforce.programme_staffing_demand.read",
                target_type="workforce.shift_demand",
                target_id=demand_id,
                outcome="allow",
                reason_code=decision.reason_code,
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="service",
                obligations=tuple(
                    sorted(set(decision.obligations) | {"audit_sensitive_read"})
                ),
                changed_fields=(),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="workforce-personal",
            ),
            occurred_at=timezone.now(),
        )
        return result
