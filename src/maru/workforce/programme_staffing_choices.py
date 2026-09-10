"""Purpose-bounded native staffing choices without holder or commitment disclosure."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, OuterRef
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
from .models import (
    Position,
    ProgrammeShiftBindingRevision,
    ShiftCommitment,
    ShiftDemand,
)
from .programme_references import lock_programme_staffing_scope
from .programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
    authorize_programme_staffing_adapter,
)
from .queries import MAX_STRUCTURE_POSITIONS
from .shift_queries import MAX_SHIFT_DEMANDS

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

POSITION_CHOICE_FIELDS = frozenset({"positions", "departments"})


@dataclass(frozen=True, slots=True)
class StaffingPositionChoice:
    """One current Position label, without assignments, vacancy counts or people.

    Attributes
    ----------
    id
        Exact selectable Position; not authority to bind it.
    title
        Authorized Position title.
    department_label
        Authorized current owning Department name.
    """

    id: UUID
    title: str
    department_label: str


@dataclass(frozen=True, slots=True)
class StaffingDemandChoice:
    """One identical uncommitted and unbound draft, without work or decision text.

    Attributes
    ----------
    id
        Exact existing draft demand, not a promise it remains linkable.
    version
        Observed demand version; preview and apply resolve again.
    title
        Independently authorized work title for deliberate native selection.
    starts_at
        Inclusive work start matching the selected expectation.
    ends_at
        Exclusive work end matching the selected expectation.
    """

    id: UUID
    version: int
    title: str
    starts_at: datetime
    ends_at: datetime


def _authorize(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    purpose: Literal["positions", "demands"],
) -> PolicyDecision:
    if purpose == "demands":
        return authorize_programme_staffing_adapter(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            purpose="read",
        )
    decision = decide_verified_principal_exact_edition(
        principal_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="workforce.view_structure",
        requested_fields=POSITION_CHOICE_FIELDS,
    )
    if not decision.allowed or not decision.fields >= POSITION_CHOICE_FIELDS:
        raise ProgrammeStaffingDeniedError
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, WORKFORCE_PROGRAMME_STAFFING_ADAPTER
    ):
        raise ProgrammeStaffingDeniedError
    return decision


def _read[ResultT](
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    purpose: Literal["positions", "demands"],
    loader: Callable[[], ResultT],
) -> ResultT:
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    if any(not isinstance(value, UUID) for value in scope.values()):
        raise ProgrammeStaffingDeniedError
    _authorize(**scope, purpose=purpose)
    if not isinstance(correlation_id, UUID):
        raise ProgrammeStaffingUnavailableError
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        _authorize(**scope, purpose=purpose)
        result = loader()
        decision = _authorize(**scope, purpose=purpose)
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="workforce.view_structure"
                if purpose == "positions"
                else "workforce.view_shifts",
                operation=f"workforce.programme_staffing.{purpose}",
                target_type="events.event_edition",
                target_id=edition_id,
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
                retention_class="workforce-restricted",
            ),
            occurred_at=timezone.now(),
        )
        return result


def list_programme_staffing_positions(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> tuple[StaffingPositionChoice, ...]:
    """Read a complete label-only Position catalog for an explicit staffing form.

    Parameters
    ----------
    actor_id : UUID
        Trusted person independently authorized for Position and Department fields.
    organization_id : UUID
        Exact owning tenant.
    edition_id : UUID
        Exact edition whose unpinned staffing adapter must be independently admitted.
    correlation_id : UUID
        Trusted sensitive-read trace identifier.

    Returns
    -------
    tuple[StaffingPositionChoice, ...]
        At most 1,024 current choices, or an exception rather than a partial list.

    Notes
    -----
    Closed Positions and retired Departments are not new staffing choices.
    The projection selects no holder, assignment, capacity or personnel data.
    Its label authority is separate from Programme management and Shift management.
    """

    def load() -> tuple[StaffingPositionChoice, ...]:
        rows = tuple(
            Position.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                department__organization_id=organization_id,
                department__edition_id=edition_id,
                department__retired_at__isnull=True,
            )
            .exclude(status=Position.Status.CLOSED)
            .order_by("department__name", "title", "id")
            .values("id", "title", "department__name")[: MAX_STRUCTURE_POSITIONS + 1]
        )
        if len(rows) > MAX_STRUCTURE_POSITIONS:
            raise ProgrammeStaffingUnavailableError
        return tuple(
            StaffingPositionChoice(row["id"], row["title"], row["department__name"])
            for row in rows
        )

    return _read(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=correlation_id,
        purpose="positions",
        loader=load,
    )


def list_programme_linkable_demands(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    expectation: ProgrammeStaffingExpectation,
) -> tuple[StaffingDemandChoice, ...]:
    """List only identical drafts without retained commitments or binding history.

    Parameters
    ----------
    actor_id : UUID
        Trusted current principal with independent Workforce work-field authority.
    organization_id : UUID
        Exact owning tenant.
    edition_id : UUID
        Exact edition owning every candidate draft.
    correlation_id : UUID
        Trusted mandatory read-audit correlation.
    expectation : ProgrammeStaffingExpectation
        Explicit selected requirement terms, parsed only after owner admission.

    Returns
    -------
    tuple[StaffingDemandChoice, ...]
        Complete bounded matching draft choices; preview/apply still resolve afresh.

    Notes
    -----
    This query neither creates a binding nor implies accepted work. Any retained
    commitment, including removed history, or prior binding lineage excludes the
    draft. No private rationale, holder label or full work briefing is released.
    """

    def load() -> tuple[StaffingDemandChoice, ...]:
        if not isinstance(expectation, ProgrammeStaffingExpectation):
            raise ProgrammeStaffingUnavailableError
        terms = expectation.normalized()
        commitments = ShiftCommitment.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            demand_id=OuterRef("pk"),
        )
        bindings = ProgrammeShiftBindingRevision.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            demand_id=OuterRef("pk"),
        )
        rows = tuple(
            ShiftDemand.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                status=ShiftDemand.Status.DRAFT,
                **asdict(terms),
            )
            .filter(~Exists(commitments), ~Exists(bindings))
            .order_by("title", "id")
            .values("id", "command_version", "title", "starts_at", "ends_at")[
                : MAX_SHIFT_DEMANDS + 1
            ]
        )
        if len(rows) > MAX_SHIFT_DEMANDS:
            raise ProgrammeStaffingUnavailableError
        return tuple(
            StaffingDemandChoice(
                row["id"],
                row["command_version"],
                row["title"],
                row["starts_at"],
                row["ends_at"],
            )
            for row in rows
        )

    return _read(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=correlation_id,
        purpose="demands",
        loader=load,
    )
