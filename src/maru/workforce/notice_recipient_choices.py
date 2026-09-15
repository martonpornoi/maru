"""Bounded exact-occurrence work choices, separate from broad personnel overviews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.identity.queries import (
    active_verified_person_account_display_labels,
    lock_account_references_for_evidence,
    resolve_active_verified_person_reference,
)
from maru.scheduling.command_support import SchedulingUnavailableError

from .adoption import WORKFORCE_PROGRAMME_STAFFING_ADAPTER
from .change_recipient_queries import ProgrammeWorkChangeRecipient
from .models import ShiftCommitment
from .operator_links import _load_lineage
from .personal_programme_links import PersonalProgrammeWorkLink
from .programme_references import lock_programme_staffing_scope
from .programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)

if TYPE_CHECKING:
    from datetime import datetime

    from .operator_links import OperatorWorkLink

MAX_NOTICE_WORK_CHOICES = 1_024
NOTICE_WORK_CHOICE_FIELDS = frozenset(
    {"shift_demands", "coverage_states", "holder_display_labels"}
)


class ProgrammeWorkNoticeLimitError(ProgrammeStaffingUnavailableError):
    """The complete operative work selection exceeds its declared bound."""


@dataclass(frozen=True, slots=True)
class ProgrammeWorkNoticeRequest:
    """Trusted sender and one deliberate occurrence, never a recipient directory.

    Attributes
    ----------
    actor_id
        Actual authenticated sender, independently admitted as a current person.
    organization_id
        Exact expected tenant for every binding, work and parent reference.
    edition_id
        Exact adopted Programme staffing edition.
    correlation_id
        Server-owned trace for the mandatory sender-attributed audit.
    occurrence_id
        Deliberate owning occurrence; labels require separate Scheduling admission.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID
    occurrence_id: UUID


@dataclass(frozen=True, slots=True)
class ProgrammeWorkNoticeChoice:
    """One readable operative commitment, not acceptance of replacement work.

    Attributes
    ----------
    recipient
        Exact current person and current/retained work lineage with source versions.
    title
        Current Shift title, independently requiring the Shift-demand field.
    starts_at
        Inclusive accepted work start, not the audience timetable boundary.
    ends_at
        Exclusive accepted work end, coherent with the retained demand.
    """

    recipient: ProgrammeWorkChangeRecipient
    title: str
    starts_at: datetime
    ends_at: datetime


class _WorkRow(NamedTuple):
    """Minimized exact work columns and same-demand interval coherence evidence."""

    id: UUID
    account_id: UUID
    version: int
    status: str
    demand_id: UUID
    demand_version: int
    title: str
    starts_at: datetime
    ends_at: datetime
    demand_starts_at: datetime
    demand_ends_at: datetime


class _Scope(TypedDict):
    organization_id: UUID
    edition_id: UUID


def _scope(request: ProgrammeWorkNoticeRequest) -> _Scope:
    return {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }


def _admit(request: ProgrammeWorkNoticeRequest) -> PolicyDecision:
    decision = decide_verified_principal_exact_edition(
        principal_id=request.actor_id,
        **_scope(request),
        capability_code="workforce.view_shifts",
        requested_fields=NOTICE_WORK_CHOICE_FIELDS,
    )
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or not decision.fields >= NOTICE_WORK_CHOICE_FIELDS
    ):
        raise ProgrammeStaffingDeniedError
    profile = edition_adoption_profile_reference(**_scope(request))
    if profile is None or not profile_allows_adapter(
        profile.code,
        profile.version,
        WORKFORCE_PROGRAMME_STAFFING_ADAPTER,
    ):
        raise ProgrammeStaffingDeniedError
    return decision


def _lineage(request: ProgrammeWorkNoticeRequest) -> tuple[OperatorWorkLink, ...]:
    links = _load_lineage(**_scope(request), occurrence_ids={request.occurrence_id})
    demands = {row.demand_id for row in links}
    if len(demands) != len(links) or any(
        row.occurrence_id != request.occurrence_id for row in links
    ):
        raise ProgrammeStaffingUnavailableError
    if demands and _load_lineage(**_scope(request), demand_ids=demands) != links:
        # A retained demand cannot silently belong to a second occurrence elsewhere.
        raise ProgrammeStaffingUnavailableError
    return links


def _rows(
    request: ProgrammeWorkNoticeRequest, links: tuple[OperatorWorkLink, ...]
) -> tuple[_WorkRow, ...]:
    demands = {row.demand_id: row for row in links}
    records = tuple(
        _WorkRow(*row)
        for row in ShiftCommitment.objects.filter(
            **_scope(request),
            demand_id__in=demands,
            status__in=("claimed", "confirmed"),
            demand__organization_id=request.organization_id,
            demand__edition_id=request.edition_id,
            demand__position__organization_id=request.organization_id,
            demand__position__edition_id=request.edition_id,
            demand__position__department__organization_id=request.organization_id,
            demand__position__department__edition_id=request.edition_id,
        )
        .order_by("demand_id", "account_id", "id")
        .values_list(
            "id",
            "account_id",
            "command_version",
            "status",
            "demand_id",
            "demand__command_version",
            "demand__title",
            "starts_at",
            "ends_at",
            "demand__starts_at",
            "demand__ends_at",
        )[: MAX_NOTICE_WORK_CHOICES + 1]
    )
    if len(records) > MAX_NOTICE_WORK_CHOICES:
        raise ProgrammeWorkNoticeLimitError
    if ShiftCommitment.objects.filter(
        **_scope(request), demand_id__in=demands, status__in=("claimed", "confirmed")
    ).count() != len(records) or any(
        row.demand_id not in demands
        or row.demand_version != demands[row.demand_id].demand_version
        or row.starts_at.utcoffset() is None
        or row.ends_at.utcoffset() is None
        or row.starts_at != row.demand_starts_at
        or row.ends_at != row.demand_ends_at
        or row.starts_at >= row.ends_at
        for row in records
    ):
        raise ProgrammeStaffingUnavailableError
    return records


def _audit(request: ProgrammeWorkNoticeRequest, decision: PolicyDecision) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code="workforce.view_shifts",
            operation="workforce.programme_change_recipient_choices.read",
            target_type="events.event_edition",
            target_id=request.edition_id,
            outcome="allow",
            reason_code=decision.reason_code,
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel="programme-change",
            obligations=tuple(sorted(decision.obligations | {"audit_sensitive_read"})),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": "programme_work_recipient_choices",
            },
            retention_class="workforce-personal",
        )
    )


def list_programme_work_notice_choices(
    request: ProgrammeWorkNoticeRequest,
) -> tuple[ProgrammeWorkNoticeChoice, ...]:
    """Read complete eligible work choices for one occurrence under sender authority.

    Parameters
    ----------
    request : ProgrammeWorkNoticeRequest
        Actual sender and exact scope; never another person's personal read context.

    Returns
    -------
    tuple[ProgrammeWorkNoticeChoice, ...]
        At most 1,024 operative current/retained commitments for current people.
        Empty eligible choices do not claim that everyone has been notified.

    Raises
    ------
    ProgrammeStaffingDeniedError
        If trusted scope, sender, adapter or any independent choice field is denied.
    ProgrammeStaffingUnavailableError
        If complete work/lineage, identity locks, source coherence or audit fails.

    Notes
    -----
    Scope precedes the complete sorted person lock set. Missing accounts fail closed;
    inactive/unverified/non-person recipients are omitted without hidden counts.
    No availability, qualification, briefing, personal output or unrelated work is
    loaded. Every preview still uses the existing exact work-recipient owner query.
    Callers compare a fresh observation before final rendered disclosure.
    """
    if type(request) is not ProgrammeWorkNoticeRequest or any(
        type(value) is not UUID or not value.int
        for value in (
            request.actor_id,
            request.organization_id,
            request.edition_id,
            request.correlation_id,
            request.occurrence_id,
        )
    ):
        raise ProgrammeStaffingDeniedError
    try:
        _admit(request)
        with transaction.atomic():
            lock_programme_staffing_scope(**_scope(request))
            _admit(request)
            links = _lineage(request)
            rows = _rows(request, links)
            accounts = tuple(
                sorted({request.actor_id, *(row.account_id for row in rows)})
            )
            if lock_account_references_for_evidence(account_ids=accounts) != accounts:
                raise ProgrammeStaffingUnavailableError
            if (
                resolve_active_verified_person_reference(account_id=request.actor_id)
                is None
            ):
                raise ProgrammeStaffingDeniedError
            labels = active_verified_person_account_display_labels(accounts)
            if request.actor_id not in labels:
                raise ProgrammeStaffingDeniedError
            if (
                _lineage(request) != links
                or _rows(request, links) != rows
                or active_verified_person_account_display_labels(accounts) != labels
            ):
                raise ProgrammeStaffingUnavailableError
            by_demand = {row.demand_id: row for row in links}
            result = tuple(
                ProgrammeWorkNoticeChoice(
                    ProgrammeWorkChangeRecipient(
                        row.account_id,
                        labels[row.account_id],
                        PersonalProgrammeWorkLink(
                            row.id,
                            row.version,
                            row.status,
                            row.demand_id,
                            row.demand_version,
                            request.occurrence_id,
                            by_demand[row.demand_id].binding_id,
                            by_demand[row.demand_id].binding_version,
                            by_demand[row.demand_id].current,
                        ),
                    ),
                    row.title,
                    row.starts_at,
                    row.ends_at,
                )
                for row in rows
                if row.account_id in labels
            )
            decision = _admit(request)
            _audit(request, decision)
            return result
    except ValidationError as error:
        raise ProgrammeStaffingDeniedError from error
    except (DatabaseError, SchedulingUnavailableError) as error:
        raise ProgrammeStaffingUnavailableError from error
