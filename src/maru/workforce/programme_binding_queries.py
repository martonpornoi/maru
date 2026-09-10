"""Bounded exact-source binding views and separately authorized retained history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.staffing_inputs import (
    MAX_STAFFING_REQUIREMENTS_PER_ITEM,
    ProgrammeStaffingSource,
)
from maru.programme.staffing_queries import (
    ProgrammeStaffingReadRequest,
    load_programme_staffing_requirements,
)

from .models import ProgrammeShiftBinding, ProgrammeShiftBindingRevision
from .programme_references import lock_programme_staffing_scope
from .programme_staffing_inputs import MAX_PROGRAMME_BINDING_REVISIONS
from .programme_staffing_queries import (
    ProgrammeStaffingUnavailableError,
    authorize_programme_staffing_adapter,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

BINDING_HISTORY_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class ProgrammeBindingView:
    """Exact retained source and work identity, without rationale or personnel.

    Attributes
    ----------
    binding_id
        Stable Workforce-owned requirement lineage.
    version
        Exact binding revision, not the current demand version.
    revision_id
        Immutable evidence for this binding action.
    source
        Explicit requirement, occurrence and alternative placement identities.
    demand_id
        Work selected by this revision, possibly a retained predecessor today.
    demand_version
        Demand version when bound; lifecycle movement alone is not source drift.
    work_terms_digest
        Fingerprint of the explicit bound work expectation.
    source_digest
        Fingerprint of the complete authorized source selection.
    operation
        Closed create, link, reconcile or successor action.
    predecessor_id
        Preserved prior demand for a successor, without its private reasons.
    """

    binding_id: UUID
    version: int
    revision_id: UUID
    source: ProgrammeStaffingSource
    demand_id: UUID
    demand_version: int
    work_terms_digest: str
    source_digest: str
    operation: str
    predecessor_id: UUID | None


@dataclass(frozen=True, slots=True)
class ProgrammeBindingHistoryEntry:
    """One restricted historical binding decision, never a planning coverage row.

    Attributes
    ----------
    binding
        Exact immutable source and work lineage at this action.
    actor_id
        Opaque original actor reference, not a person directory or display label.
    reason
        Explicit retained Workforce-visible binding rationale.
    occurred_at
        Server timestamp of the retained revision.
    """

    binding: ProgrammeBindingView
    actor_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ProgrammeBindingHistoryPage:
    """Fixed-ceiling history with a bounded exclusive continuation cursor.

    Attributes
    ----------
    through_version
        Inclusive selected ceiling, never silently advanced by subsequent writes.
    entries
        At most fifty consecutive immutable decisions in ascending order.
    next_after_version
        Exclusive cursor for another page, or None at the selected ceiling.
    """

    through_version: int
    entries: tuple[ProgrammeBindingHistoryEntry, ...]
    next_after_version: int | None


def _view(
    row: ProgrammeShiftBindingRevision, binding: ProgrammeShiftBinding
) -> ProgrammeBindingView:
    return ProgrammeBindingView(
        binding.id,
        row.sequence,
        row.id,
        ProgrammeStaffingSource(
            binding.requirement_id,
            row.requirement_revision_id,
            row.requirement_version,
            binding.occurrence_id,
            row.occurrence_version,
            row.candidate_id,
            row.candidate_revision_id,
            row.placement_id,
        ).validated(),
        row.demand_id,
        row.demand_version,
        row.work_terms_digest,
        row.source_digest,
        row.operation,
        row.predecessor_id,
    )


def _admit(
    request: ProgrammeStaffingReadRequest,
    *,
    history: bool,
    authorizer: ProgrammeAuthorizer,
) -> None:
    authorize_programme_staffing_adapter(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        purpose="read",
    )
    authorize_programme_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=PROGRAMME_VIEW_STAFFING,
        requested_fields=frozenset(
            {"staffing_history" if history else "staffing_requirements"}
        ),
        authorizer=authorizer,
    )


def _read[ResultT](
    request: ProgrammeStaffingReadRequest,
    *,
    history: bool,
    loader: Callable[[], ResultT],
    authorizer: ProgrammeAuthorizer,
) -> ResultT:
    _admit(request, history=history, authorizer=authorizer)
    if not isinstance(request.item_id, UUID) or not isinstance(
        request.correlation_id, UUID
    ):
        raise ProgrammeStaffingUnavailableError
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _admit(request, history=history, authorizer=authorizer)
        result = loader()
        _admit(request, history=history, authorizer=authorizer)
        decision = authorize_programme_staffing_adapter(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            purpose="read",
        )
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=request.actor_id,
                principal_context_id=None,
                organization_id=request.organization_id,
                event_edition_id=request.edition_id,
                capability_code="workforce.view_shifts",
                operation="workforce.programme_binding.history"
                if history
                else "workforce.programme_binding.read",
                target_type="programme.item",
                target_id=request.item_id,
                outcome="allow",
                reason_code=decision.reason_code,
                correlation_id=request.correlation_id,
                request_id=request.correlation_id,
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


def load_programme_bindings(
    request: ProgrammeStaffingReadRequest,
    *,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeBindingView, ...]:
    """Read every current binding for one independently authorized Programme item.

    Parameters
    ----------
    request : ProgrammeStaffingReadRequest
        Exact actor, tenant, edition, item and sensitive-read attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme staffing-requirements field policy.

    Returns
    -------
    tuple[ProgrammeBindingView, ...]
        Complete requirement-ordered bindings without actor, rationale or work copy.

    Notes
    -----
    Authorized absence means no binding, not zero volunteers. Foreign or absent
    items and incomplete revisions fail instead of returning an empty result.
    The reader does not assert source freshness or release authority. Retired
    requirements remain inspectable and retain their original work lineage.
    """

    def load() -> tuple[ProgrammeBindingView, ...]:
        overview = load_programme_staffing_requirements(request, authorizer=authorizer)
        requirements = {row.requirement_id: row for row in overview.requirements}
        bindings = tuple(
            ProgrammeShiftBinding.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                item_id=request.item_id,
            )
            .only("id", "requirement_id", "occurrence_id", "version", "demand_id")
            .order_by("requirement_id")[: MAX_STAFFING_REQUIREMENTS_PER_ITEM + 1]
        )
        if len(bindings) > MAX_STAFFING_REQUIREMENTS_PER_ITEM or any(
            binding.requirement_id not in requirements
            or requirements[binding.requirement_id].occurrence_id
            != binding.occurrence_id
            for binding in bindings
        ):
            raise ProgrammeStaffingUnavailableError
        rows = ProgrammeShiftBindingRevision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            binding_id__in=[binding.id for binding in bindings],
            sequence=F("binding__version"),
        ).only(
            "id",
            "binding_id",
            "sequence",
            "requirement_revision_id",
            "requirement_version",
            "occurrence_version",
            "candidate_id",
            "candidate_revision_id",
            "placement_id",
            "demand_id",
            "demand_version",
            "work_terms_digest",
            "source_digest",
            "operation",
            "predecessor_id",
        )
        by_binding = {row.binding_id: row for row in rows}
        if len(by_binding) != len(bindings) or any(
            by_binding[binding.id].demand_id != binding.demand_id
            for binding in bindings
        ):
            raise ProgrammeStaffingUnavailableError
        return tuple(_view(by_binding[binding.id], binding) for binding in bindings)

    return _read(request, history=False, loader=load, authorizer=authorizer)


def load_programme_binding_history(
    request: ProgrammeStaffingReadRequest,
    *,
    binding_id: UUID,
    through_version: int,
    after_version: int = 0,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeBindingHistoryPage:
    """Read restricted binding decisions under both owners' independent authority.

    Parameters
    ----------
    request : ProgrammeStaffingReadRequest
        Exact actor and owning Programme item, with trusted audit correlation.
    binding_id : UUID
        Explicit Workforce lineage in that item, not a discovery filter.
    through_version : int
        Inclusive fixed ceiling from an authorized binding view.
    after_version : int, default=0
        Exclusive cursor; zero starts retained history.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Programme staffing-history authority, separate from current terms.

    Returns
    -------
    ProgrammeBindingHistoryPage
        Complete consecutive page, or an exception before any rationale is released.

    Notes
    -----
    Workforce work-field authority remains mandatory. This purpose does not
    include volunteer identities, private commitment reasons or availability.
    Current terms alone never grant history, and mutation authority grants neither.
    """

    def load() -> ProgrammeBindingHistoryPage:
        if (
            not isinstance(binding_id, UUID)
            or type(through_version) is not int
            or type(after_version) is not int
            or not 0
            <= after_version
            < through_version
            <= MAX_PROGRAMME_BINDING_REVISIONS
        ):
            raise ProgrammeStaffingUnavailableError
        binding = (
            ProgrammeShiftBinding.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                item_id=request.item_id,
                id=binding_id,
            )
            .only("id", "requirement_id", "occurrence_id", "version")
            .first()
        )
        if binding is None or through_version > binding.version:
            raise ProgrammeStaffingUnavailableError
        rows = tuple(
            ProgrammeShiftBindingRevision.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                binding_id=binding.id,
                sequence__gt=after_version,
                sequence__lte=through_version,
            ).order_by("sequence")[: BINDING_HISTORY_PAGE_SIZE + 1]
        )
        expected = min(through_version - after_version, BINDING_HISTORY_PAGE_SIZE + 1)
        if len(rows) != expected or any(
            row.sequence != after_version + index + 1 for index, row in enumerate(rows)
        ):
            raise ProgrammeStaffingUnavailableError
        page = rows[:BINDING_HISTORY_PAGE_SIZE]
        return ProgrammeBindingHistoryPage(
            through_version,
            tuple(
                ProgrammeBindingHistoryEntry(
                    _view(row, binding), row.actor_id, row.reason, row.created_at
                )
                for row in page
            ),
            page[-1].sequence if len(rows) > BINDING_HISTORY_PAGE_SIZE else None,
        )

    return _read(request, history=True, loader=load, authorizer=authorizer)
