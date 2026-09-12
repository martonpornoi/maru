"""Minimized exact-person retained work for independently composed timetables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_self,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.events.write_references import lock_edition_ownership
from maru.identity.queries import resolve_active_verified_person_reference

from .adoption import WORKFORCE_SELF_ADAPTER
from .models import ShiftCommitment
from .shift_commands import ShiftAuthorizationDeniedError, ShiftUnavailableError
from .shift_queries import MAX_SHIFT_COMMITMENTS, ShiftReadLimitExceededError

if TYPE_CHECKING:
    from datetime import datetime

_SELF_TIMETABLE_FIELDS: Final = frozenset({"shifts"})


@dataclass(frozen=True, slots=True)
class PersonalShiftInstructions:
    """Current owner instructions, separately versioned from retained work times.

    Attributes
    ----------
    demand_id
        Exact Workforce demand identity; no private Programme candidate is exposed.
    version
        Current demand command version owning these instructions.
    status
        Current demand lifecycle, not the person's confirmation or attendance.
    title
        Current operational work title.
    location
        Current work location label, never a silent replacement of accepted times.
    briefing
        Current instructions already visible to the holder of this work.
    supervision_note
        Current operational supervision instructions.
    department_id
        Exact owning Department identity for a separately authorized grouping.
    department_name
        Current owner Department label, not a historical snapshot.
    position_title
        Current owner Position label, not another person's assignment.
    """

    demand_id: UUID
    version: int
    status: str
    title: str
    location: str
    briefing: str
    supervision_note: str
    department_id: UUID
    department_name: str
    position_title: str


@dataclass(frozen=True, slots=True)
class PersonalShiftTimetableEntry:
    """Retained exact-person work, without planners, private reasons or availability.

    Attributes
    ----------
    commitment_id
        Stable retained claim/confirmation identity belonging to the current person.
    version
        Current commitment command version.
    status
        Claimed, confirmed, removed or completed; a claim is not confirmation.
    starts_at
        Retained accepted/claimed start from the commitment, not current demand.
    ends_at
        Retained end from the commitment, not a new timetable placement.
    rest_ends_at
        Retained minimum-rest boundary of this work snapshot.
    instructions
        Separately versioned current demand instructions, never attendance evidence.
    """

    commitment_id: UUID
    version: int
    status: str
    starts_at: datetime
    ends_at: datetime
    rest_ends_at: datetime
    instructions: PersonalShiftInstructions


def _authorize(
    actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> PolicyDecision:
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, WORKFORCE_SELF_ADAPTER
    ):
        raise ShiftAuthorizationDeniedError
    decision = decide_verified_principal_exact_self(
        principal_id=actor_id,
        owner_account_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="workforce.view_self",
        requested_fields=_SELF_TIMETABLE_FIELDS,
    )
    if not decision.allowed or not _SELF_TIMETABLE_FIELDS.issubset(decision.fields):
        raise ShiftAuthorizationDeniedError
    return decision


def _entries(
    actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> tuple[PersonalShiftTimetableEntry, ...]:
    owned = ShiftCommitment.objects.filter(
        organization_id=organization_id, edition_id=edition_id, account_id=actor_id
    )
    identifiers = tuple(
        owned.order_by("id").values_list("id", flat=True)[: MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(identifiers) > MAX_SHIFT_COMMITMENTS:
        raise ShiftReadLimitExceededError
    rows = tuple(
        owned.filter(
            id__in=identifiers,
            demand__organization_id=organization_id,
            demand__edition_id=edition_id,
            demand__position__organization_id=organization_id,
            demand__position__edition_id=edition_id,
            demand__position__department__organization_id=organization_id,
            demand__position__department__edition_id=edition_id,
        )
        .order_by("starts_at", "id")
        .values_list(
            "id",
            "command_version",
            "status",
            "starts_at",
            "ends_at",
            "rest_ends_at",
            "demand_id",
            "demand__command_version",
            "demand__status",
            "demand__title",
            "demand__location_label",
            "demand__briefing",
            "demand__supervision_note",
            "demand__position__department_id",
            "demand__position__department__name",
            "demand__position__title",
        )[: MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(rows) != len(identifiers):
        raise ShiftUnavailableError
    return tuple(
        PersonalShiftTimetableEntry(*row[:6], PersonalShiftInstructions(*row[6:]))
        for row in rows
    )


def load_personal_shift_timetable(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> tuple[PersonalShiftTimetableEntry, ...]:
    """Read only the authenticated person's complete retained Workforce work.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated person; there is no separately selectable owner.
    organization_id : UUID
        Exact expected owner of work, Position and Department.
    edition_id : UUID
        Exact edition whose current profile admits Workforce self-service.
    correlation_id : UUID
        Trusted trace for the purpose-bounded required sensitive-read evidence.

    Returns
    -------
    tuple[PersonalShiftTimetableEntry, ...]
        Complete own retained work in time/identity order. Empty means no owned
        commitment, not that unclaimed work or another person's work was loaded.

    Raises
    ------
    ShiftAuthorizationDeniedError
        If exact person, profile, scope or independently required field fails.
    ShiftUnavailableError
        If required owner evidence is incomplete or its database is unavailable.
    ValidationError
        If trusted identifiers are malformed.

    Notes
    -----
    Complete row collection propagates ShiftReadLimitExceededError when retained
    work exceeds the owner ceiling; it never returns a truncated timetable.
    Canonical parents precede the exact Identity person lock. Source reads and
    final authorization precede the mandatory audit; failed evidence releases
    nothing. No Programme/Scheduling/Participation lookup, unclaimed demand,
    other-person identity, availability calendar or confirmation/removal reason
    is fetched. Ended assignments do not erase the person's retained work.
    Consumers must distinguish claimed, confirmed and ended history, and must
    never change work or infer attendance from this read.
    """
    if any(
        type(value) is not UUID or value.int == 0
        for value in (actor_id, organization_id, edition_id, correlation_id)
    ):
        raise ValidationError(
            "Exact typed personal timetable identifiers are required."
        )
    try:
        with transaction.atomic():
            _authorize(actor_id, organization_id, edition_id)
            if not lock_edition_ownership(
                organization_id=organization_id, edition_id=edition_id
            ):
                raise ShiftAuthorizationDeniedError
            if (
                resolve_active_verified_person_reference(account_id=actor_id, lock=True)
                is None
            ):
                raise ShiftAuthorizationDeniedError
            _authorize(actor_id, organization_id, edition_id)
            result = _entries(actor_id, organization_id, edition_id)
            decision = _authorize(actor_id, organization_id, edition_id)
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=actor_id,
                    principal_context_id=None,
                    organization_id=organization_id,
                    event_edition_id=edition_id,
                    capability_code="workforce.view_self",
                    operation="workforce.personal_timetable.read",
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
                        "access_purpose": "own_retained_shift_timetable",
                    },
                    retention_class="workforce-personal",
                )
            )
            return result
    except DatabaseError as error:
        raise ShiftUnavailableError from error
