"""Complete Programme Shift-link history without private workforce discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from django.db import transaction

from maru.audit.services import AuditRecord, append_audit
from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_STAFFING,
    authorize_programme_scope,
)
from maru.programme.inputs import require_uuid
from maru.programme.staffing_queries import ProgrammeStaffingReadRequest

from .models import ProgrammeShiftBinding
from .programme_binding_queries import (
    ProgrammeBindingHistoryEntry,
    ProgrammeBindingView,
    load_programme_binding_history,
    load_programme_bindings,
)
from .programme_references import lock_programme_staffing_scope
from .programme_staffing_queries import (
    ProgrammeStaffingUnavailableError,
    authorize_programme_staffing_adapter,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.authorization.policy import PolicyDecision
    from maru.programme.authorization import ProgrammeAuthorizer

MAX_EXIT_BINDINGS: Final = 10_000
MAX_EXIT_BINDING_REVISIONS: Final = 100_000


@dataclass(frozen=True, slots=True)
class ProgrammeExitBinding:
    """One exact item binding and its complete immutable source/work history.

    Attributes
    ----------
    item_id, current, history
        Explicit source identity and independently admitted current/history DTOs.
        No worker identities, private commitment reasons or calendars are selected.
    """

    item_id: UUID = field(repr=False)
    current: ProgrammeBindingView = field(repr=False)
    history: tuple[ProgrammeBindingHistoryEntry, ...] = field(repr=False)


def _inventory(
    organization_id: UUID, edition_id: UUID
) -> tuple[tuple[UUID, UUID, int], ...]:
    rows = tuple(
        ProgrammeShiftBinding.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .order_by("id")
        .values_list("id", "item_id", "version")[: MAX_EXIT_BINDINGS + 1]
    )
    if len(rows) > MAX_EXIT_BINDINGS:
        raise ProgrammeStaffingUnavailableError
    return rows


def _history(
    request: ProgrammeStaffingReadRequest,
    binding: ProgrammeBindingView,
    authorizer: ProgrammeAuthorizer,
) -> tuple[ProgrammeBindingHistoryEntry, ...]:
    if not 1 <= binding.version <= MAX_EXIT_BINDING_REVISIONS:
        raise ProgrammeStaffingUnavailableError
    entries: list[ProgrammeBindingHistoryEntry] = []
    while len(entries) < binding.version:
        page = load_programme_binding_history(
            request,
            binding_id=binding.binding_id,
            through_version=binding.version,
            after_version=len(entries),
            authorizer=authorizer,
        )
        if page.through_version != binding.version or not page.entries:
            raise ProgrammeStaffingUnavailableError
        for entry in page.entries:
            if (
                entry.binding.binding_id != binding.binding_id
                or entry.binding.version != len(entries) + 1
            ):
                raise ProgrammeStaffingUnavailableError
            entries.append(entry)
        expected_cursor = len(entries) if len(entries) < binding.version else None
        if len(entries) > binding.version or page.next_after_version != expected_cursor:
            raise ProgrammeStaffingUnavailableError
    if entries[-1].binding != binding:
        raise ProgrammeStaffingUnavailableError
    return tuple(entries)


@transaction.atomic
def load_programme_exit_bindings(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[ProgrammeExitBinding, ...]:
    """Collect all declared Programme Shift links through existing owner purposes.

    Parameters
    ----------
    actor_id : UUID
        Actual current requester, not a worker or administrator impersonation.
    organization_id : UUID
        Exact expected tenant.
    edition_id : UUID
        Exact selected edition, without a partial item selector.
    correlation_id : UUID
        Server-owned sensitive-read trace.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme source/export policy; Workforce uses its real policy.

    Returns
    -------
    tuple[ProgrammeExitBinding, ...]
        Complete bounded binding identity/history, not live coverage or personnel.

    Raises
    ------
    ProgrammeStaffingUnavailableError
        If complete inventory, paging, current-source comparisons or budgets fail.

    Notes
    -----
    Parent/edition locking precedes owned discovery. Full archive composition must
    prelock its larger Department/person closure before any child read audit.
    Current Programme terms and Workforce work fields never substitute for the
    separate historical rationale or additional archive-purpose admission.
    """
    for name, value in (
        ("actor_id", actor_id),
        ("organization_id", organization_id),
        ("edition_id", edition_id),
        ("correlation_id", correlation_id),
    ):
        require_uuid(value, field=name)

    def admit() -> PolicyDecision:
        authorize_programme_archive_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=authorizer,
        )
        authorize_programme_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=PROGRAMME_VIEW_STAFFING,
            requested_fields=frozenset({"staffing_requirements", "staffing_history"}),
            authorizer=authorizer,
        )
        return authorize_programme_staffing_adapter(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            purpose="read",
        )

    admit()
    lock_programme_staffing_scope(
        organization_id=organization_id, edition_id=edition_id
    )
    admit()
    inventory = _inventory(organization_id, edition_id)
    result = []
    entry_count = 0
    for item_id in sorted({row[1] for row in inventory}):
        request = ProgrammeStaffingReadRequest(
            actor_id,
            organization_id,
            edition_id,
            item_id,
            correlation_id,
            "programme-exit",
        )
        bindings = load_programme_bindings(request, authorizer=authorizer)
        expected = tuple(
            (identifier, version)
            for identifier, item, version in inventory
            if item == item_id
        )
        if tuple(sorted((row.binding_id, row.version) for row in bindings)) != expected:
            raise ProgrammeStaffingUnavailableError
        for binding in bindings:
            entry_count += binding.version
            if entry_count > MAX_EXIT_BINDING_REVISIONS:
                raise ProgrammeStaffingUnavailableError
            result.append(
                ProgrammeExitBinding(
                    item_id, binding, _history(request, binding, authorizer)
                )
            )
        if load_programme_bindings(request, authorizer=authorizer) != bindings:
            raise ProgrammeStaffingUnavailableError
    if _inventory(organization_id, edition_id) != inventory:
        raise ProgrammeStaffingUnavailableError
    decision = admit()
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="workforce.view_shifts",
            operation="workforce.programme_binding.exit_owner",
            target_type="events.edition",
            target_id=edition_id,
            outcome="allow",
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="programme-exit",
            obligations=tuple(
                sorted(set(decision.obligations) | {"audit_sensitive_read"})
            ),
            retention_class="workforce-restricted",
        )
    )
    return tuple(sorted(result, key=lambda row: row.current.binding_id))
