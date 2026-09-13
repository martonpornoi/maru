"""Sender-authorized exact Programme work recipient, not a personal-query bypass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import decide_verified_principal_exact_edition
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.identity.queries import (
    active_verified_person_account_display_labels,
    resolve_active_verified_person_reference,
)
from maru.scheduling.command_support import SchedulingUnavailableError

from .adoption import WORKFORCE_PROGRAMME_STAFFING_ADAPTER
from .models import ShiftCommitment
from .operator_links import _load_lineage
from .personal_programme_links import PersonalProgrammeWorkLink
from .programme_references import lock_programme_staffing_scope
from .programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)

if TYPE_CHECKING:
    from maru.authorization.policy import PolicyDecision

_FIELDS = frozenset({"coverage_states", "holder_display_labels"})


@dataclass(frozen=True, slots=True)
class ProgrammeWorkRecipientRequest:
    """Trusted sender and exact work purpose, never a destination address.

    Attributes
    ----------
    actor_id
        Authenticated sender whose organizer work-field authority is checked.
    organization_id
        Exact expected owner of work, demand and retained binding lineage.
    edition_id
        Exact edition whose explicit Programme staffing adoption is required.
    correlation_id
        Trusted trace for mandatory sensitive-read evidence attributed to sender.
    occurrence_id
        Exact occurrence the communication concerns, not a caller-supplied proof.
    commitment_id
        Exact retained work from which the owner resolves the recipient account.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID
    occurrence_id: UUID
    commitment_id: UUID


@dataclass(frozen=True, slots=True)
class ProgrammeWorkChangeRecipient:
    """One exact current operative work recipient, without personal instructions.

    Attributes
    ----------
    account_id
        Current verified owner of the selected retained claim/confirmation.
    display_label
        Current operational label, not an address or historical person snapshot.
    work
        Exact current/retained linkage and versions; no successor work substitution.
    """

    account_id: UUID
    display_label: str
    work: PersonalProgrammeWorkLink


def _admit(request: ProgrammeWorkRecipientRequest) -> PolicyDecision:
    decision = decide_verified_principal_exact_edition(
        principal_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code="workforce.view_shifts",
        requested_fields=_FIELDS,
    )
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
    )
    if (
        not decision.allowed
        or not decision.fields >= _FIELDS
        or profile is None
        or not profile_allows_adapter(
            profile.code, profile.version, WORKFORCE_PROGRAMME_STAFFING_ADAPTER
        )
    ):
        raise ProgrammeStaffingDeniedError
    return decision


def _work(
    request: ProgrammeWorkRecipientRequest,
) -> tuple[UUID, UUID, int, str, UUID, int]:
    row = (
        ShiftCommitment.objects.filter(
            id=request.commitment_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            demand__organization_id=request.organization_id,
            demand__edition_id=request.edition_id,
            demand__position__organization_id=request.organization_id,
            demand__position__edition_id=request.edition_id,
            demand__position__department__organization_id=request.organization_id,
            demand__position__department__edition_id=request.edition_id,
        )
        .values_list(
            "id",
            "account_id",
            "command_version",
            "status",
            "demand_id",
            "demand__command_version",
        )
        .first()
    )
    if row is None or row[3] not in {"claimed", "confirmed"}:
        raise ProgrammeStaffingUnavailableError
    return row


def load_work_change_recipient(
    request: ProgrammeWorkRecipientRequest,
) -> ProgrammeWorkChangeRecipient:
    """Resolve an exact operative work recipient under the real sender's authority.

    Parameters
    ----------
    request : ProgrammeWorkRecipientRequest
        Trusted sender/scope/trace plus exact occurrence and retained commitment.

    Returns
    -------
    ProgrammeWorkChangeRecipient
        Current minimized recipient proof, not delivery or timetable authority.

    Raises
    ------
    ProgrammeStaffingDeniedError
        If trusted routing, current sender fields/adoption or verified identity fails.
    ProgrammeStaffingUnavailableError
        If exact work, recipient identity or complete lineage is absent or moving.

    Notes
    -----
    Organizer coverage and holder-label fields are independent from personal,
    operator or planner access. Canonical scope precedes sorted sender/recipient
    person locks; current work and lineage are repeated before final authority
    and mandatory sender-attributed audit. No personal read is impersonated.
    Missing/foreign/nonoperative selections share an unavailable result; no
    arbitrary recipient account, address, private instructions or Shift write is
    accepted. A composing command rechecks this proof in its canonical transaction.
    """
    if not isinstance(request, ProgrammeWorkRecipientRequest) or any(
        type(value) is not UUID or value.int == 0
        for value in (
            request.actor_id,
            request.organization_id,
            request.edition_id,
            request.correlation_id,
            request.occurrence_id,
            request.commitment_id,
        )
    ):
        raise ProgrammeStaffingDeniedError
    try:
        with transaction.atomic():
            _admit(request)
            lock_programme_staffing_scope(
                organization_id=request.organization_id, edition_id=request.edition_id
            )
            _admit(request)
            work = _work(request)
            for account_id in sorted({request.actor_id, work[1]}, key=str):
                if (
                    resolve_active_verified_person_reference(
                        account_id=account_id, lock=True
                    )
                    is None
                ):
                    if account_id == request.actor_id:
                        raise ProgrammeStaffingDeniedError
                    raise ProgrammeStaffingUnavailableError
            lineage = _load_lineage(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                demand_ids={work[4]},
            )
            if (
                len(lineage) != 1
                or lineage[0].occurrence_id != request.occurrence_id
                or lineage[0].demand_id != work[4]
                or lineage[0].demand_version != work[5]
            ):
                raise ProgrammeStaffingUnavailableError
            labels = active_verified_person_account_display_labels({work[1]})
            if (
                set(labels) != {work[1]}
                or _work(request) != work
                or _load_lineage(
                    organization_id=request.organization_id,
                    edition_id=request.edition_id,
                    demand_ids={work[4]},
                )
                != lineage
            ):
                raise ProgrammeStaffingUnavailableError
            decision = _admit(request)
            source = lineage[0]
            result = ProgrammeWorkChangeRecipient(
                work[1],
                labels[work[1]],
                PersonalProgrammeWorkLink(
                    work[0],
                    work[2],
                    work[3],
                    work[4],
                    work[5],
                    source.occurrence_id,
                    source.binding_id,
                    source.binding_version,
                    source.current,
                ),
            )
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=request.actor_id,
                    principal_context_id=None,
                    organization_id=request.organization_id,
                    event_edition_id=request.edition_id,
                    capability_code="workforce.view_shifts",
                    operation="workforce.programme_change_recipient.read",
                    target_type="workforce.shift_commitment",
                    target_id=request.commitment_id,
                    outcome="allow",
                    reason_code=decision.reason_code,
                    correlation_id=request.correlation_id,
                    request_id=request.correlation_id,
                    source_channel="programme-change",
                    obligations=tuple(
                        sorted(decision.obligations | {"audit_sensitive_read"})
                    ),
                    safe_metadata={
                        "policy_version": POLICY_VERSION,
                        "access_purpose": "programme_change_recipient",
                    },
                    retention_class="workforce-personal",
                )
            )
            return result
    except (DatabaseError, SchedulingUnavailableError) as error:
        raise ProgrammeStaffingUnavailableError from error
