"""Exact-self retained Programme work lineage without an operator permission seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.identity.queries import resolve_active_verified_person_reference
from maru.scheduling.command_support import SchedulingUnavailableError

from .adoption import WORKFORCE_PROGRAMME_STAFFING_ADAPTER
from .operator_links import _load_lineage
from .programme_references import lock_programme_staffing_scope
from .shift_commands import ShiftAuthorizationDeniedError, ShiftUnavailableError
from .shift_queries import MAX_SHIFT_COMMITMENTS
from .timetable_queries import _authorize, load_personal_shift_timetable

if TYPE_CHECKING:
    from .timetable_queries import PersonalShiftTimetableEntry


@dataclass(frozen=True, slots=True)
class PersonalProgrammeWorkLink:
    """One own retained work-to-occurrence link with independent current versions.

    Attributes
    ----------
    commitment_id
        Exact authenticated person's retained work identity, not another recipient.
    commitment_version
        Current work command version, not a change to accepted intervals.
    status
        Claimed, confirmed, removed or completed; ended history is not current work.
    demand_id
        Retained work's actual demand, never substituted with its successor.
    demand_version
        Current demand instruction/lifecycle version.
    occurrence_id
        Stable Programme occurrence proved by complete retained binding lineage.
    binding_id
        Exact Workforce-owned binding identity, not authority to read candidates.
    binding_version
        Current binding sequence verified against its complete immutable history.
    current
        Whether this demand is currently selected by the binding. False does not
        cancel retained work, and True does not confirm a person's claim.
    """

    commitment_id: UUID
    commitment_version: int
    status: str
    demand_id: UUID
    demand_version: int
    occurrence_id: UUID
    binding_id: UUID
    binding_version: int
    current: bool


def _adopted(organization_id: UUID, edition_id: UUID) -> bool:
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    return profile is not None and profile_allows_adapter(
        profile.code, profile.version, WORKFORCE_PROGRAMME_STAFFING_ADAPTER
    )


def _links(
    organization_id: UUID,
    edition_id: UUID,
    work: tuple[PersonalShiftTimetableEntry, ...],
) -> tuple[PersonalProgrammeWorkLink, ...]:
    if len(work) > MAX_SHIFT_COMMITMENTS or len(
        {row.commitment_id for row in work}
    ) != len(work):
        raise ShiftUnavailableError
    if not work:
        return ()
    lineage = _load_lineage(
        organization_id=organization_id,
        edition_id=edition_id,
        demand_ids={row.instructions.demand_id for row in work},
    )
    by_demand = {}
    own_demands = {row.instructions.demand_id for row in work}
    for source in lineage:
        if source.demand_id in by_demand or source.demand_id not in own_demands:
            # One demand cannot silently identify two different Programme purposes.
            raise ShiftUnavailableError
        by_demand[source.demand_id] = source
    result = []
    for row in sorted(work, key=lambda entry: entry.commitment_id):
        link = by_demand.get(row.instructions.demand_id)
        if link is None:
            continue  # A genuinely unlinked own Shift is not Programme work.
        if link.demand_version != row.instructions.version:
            raise ShiftUnavailableError
        result.append(
            PersonalProgrammeWorkLink(
                row.commitment_id,
                row.version,
                row.status,
                link.demand_id,
                link.demand_version,
                link.occurrence_id,
                link.binding_id,
                link.binding_version,
                link.current,
            )
        )
    return tuple(result)


def load_personal_programme_work_links(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> tuple[PersonalProgrammeWorkLink, ...] | None:
    """Prove only own retained Programme work through real Workforce self authority.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated exact person; there is no other-owner selector.
    organization_id : UUID
        Exact tenant owning commitments, demand and complete binding lineage.
    edition_id : UUID
        Exact edition whose Workforce self and optional staffing adoption are checked.
    correlation_id : UUID
        Trusted trace for required work and lineage sensitive-read evidence.

    Returns
    -------
    tuple[PersonalProgrammeWorkLink, ...] | None
        Complete current/retained own links, empty if genuinely unlinked. None
        means Programme staffing is unadopted, never denied or unavailable.

    Raises
    ------
    ValidationError
        If trusted attribution identifiers are not exact nonzero UUIDs.
    ShiftUnavailableError
        If retained work/lineage or adoption is incomplete, inconsistent or moving.
    ShiftAuthorizationDeniedError
        If real current verified person or independently required self authority fails.

    Notes
    -----
    Real self denial propagates ShiftAuthorizationDeniedError; planner/operator
    grants cannot substitute. Canonical shared scope precedes owner person locks.
    Complete work, lineage, adoption and final authority are rechecked before
    mandatory audit. Unadopted Programme performs no work/Programme/Scheduling
    lookup. The owner selects demands from own work, not caller-provided IDs.
    This reference grants no release/geometry/copy authority, exposes no other
    person, candidate, availability or instructions, and changes no commitment.
    """
    if any(
        type(value) is not UUID or value.int == 0
        for value in (actor_id, organization_id, edition_id, correlation_id)
    ):
        raise ValidationError("Exact typed personal work identifiers are required.")
    arguments = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "correlation_id": correlation_id,
    }
    try:
        with transaction.atomic():
            _authorize(actor_id, organization_id, edition_id)
            lock_programme_staffing_scope(
                organization_id=organization_id, edition_id=edition_id
            )
            if (
                resolve_active_verified_person_reference(account_id=actor_id, lock=True)
                is None
            ):
                raise ShiftAuthorizationDeniedError
            _authorize(actor_id, organization_id, edition_id)
            adopted = _adopted(organization_id, edition_id)
            work = load_personal_shift_timetable(**arguments) if adopted else ()
            result = _links(organization_id, edition_id, work) if adopted else None
            if (
                _adopted(organization_id, edition_id) != adopted
                or (adopted and load_personal_shift_timetable(**arguments) != work)
                or (adopted and _links(organization_id, edition_id, work) != result)
            ):
                raise ShiftUnavailableError
            decision = _authorize(actor_id, organization_id, edition_id)
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=actor_id,
                    principal_context_id=None,
                    organization_id=organization_id,
                    event_edition_id=edition_id,
                    capability_code="workforce.view_self",
                    operation="workforce.personal_programme_links.read",
                    target_type="events.event_edition",
                    target_id=edition_id,
                    outcome="allow",
                    reason_code=decision.reason_code,
                    correlation_id=correlation_id,
                    request_id=correlation_id,
                    source_channel="workforce-timetable",
                    obligations=tuple(
                        sorted(decision.obligations | {"audit_sensitive_read"})
                    ),
                    safe_metadata={
                        "policy_version": POLICY_VERSION,
                        "access_purpose": "own_retained_programme_work_links",
                    },
                    retention_class="workforce-personal",
                )
            )
            return result
    except (DatabaseError, SchedulingUnavailableError) as error:
        raise ShiftUnavailableError from error
