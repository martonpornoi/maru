"""Independently authorized room labels for the private timetable inventory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.identity.queries import resolve_active_verified_person_reference

from .models import EditionSpaceSelection
from .services import WORKSPACE_VIEW_CAPABILITY

TIMETABLE_SPACE_FIELDS: Final = frozenset({"venue_selections", "space_selections"})
MAX_TIMETABLE_SPACES: Final = 256


class VenueTimetableQueryDeniedError(RuntimeError):
    """Conceal which scope, person, profile or field prevented a label read."""

    reason_code = "venues_timetable_query_denied"


class VenueTimetableQueryUnavailableError(RuntimeError):
    """Withhold incomplete or unauditable room inventory."""

    reason_code = "venues_timetable_query_unavailable"


class VenueTimetableInventoryLimitError(VenueTimetableQueryUnavailableError):
    """Report explicit room-inventory overflow without releasing a partial list."""

    reason_code = "venues_timetable_inventory_limit"


@dataclass(frozen=True, slots=True)
class VenueTimetableSpace:
    """Current room labels, not permission or proof of physical availability.

    Attributes
    ----------
    id
        Exact edition space selection, including retained retired selections.
    version
        Current room selection version.
    label
        Private local room or combination label.
    configuration_label
        Selected configuration label, without copied layout or access notes.
    lifecycle
        Current active or retired selection state.
    venue_id
        Same-edition Venue selection identifier.
    venue_version
        Current Venue selection version.
    venue_label
        Private local Venue label, never a foreign edition label.
    venue_lifecycle
        Current active or retired Venue selection state.
    """

    id: UUID
    version: int
    label: str
    configuration_label: str
    lifecycle: str
    venue_id: UUID
    venue_version: int
    venue_label: str
    venue_lifecycle: str


def _authorize(
    actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> PolicyDecision:
    if resolve_active_verified_person_reference(account_id=actor_id) is None:
        raise VenueTimetableQueryDeniedError
    decision = decide_verified_principal_exact_edition(
        principal_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=WORKSPACE_VIEW_CAPABILITY,
        requested_fields=TIMETABLE_SPACE_FIELDS,
    )
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or not TIMETABLE_SPACE_FIELDS.issubset(decision.fields)
    ):
        raise VenueTimetableQueryDeniedError
    return decision


def _audit(
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    decision: PolicyDecision | None,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=WORKSPACE_VIEW_CAPABILITY,
            operation="venues.query.timetable_spaces",
            target_type="events.edition",
            target_id=edition_id if decision else None,
            outcome="allow" if decision else "deny",
            reason_code=decision.reason_code if decision else "venues_timetable_denied",
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="scheduling-planning",
            obligations=tuple(
                sorted(
                    (decision.obligations if decision else frozenset())
                    | {"audit_sensitive_read"}
                )
            ),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "access_purpose": "timetable_spaces",
            },
            retention_class="programme-restricted",
        )
    )


def _inventory(
    organization_id: UUID, edition_id: UUID
) -> tuple[VenueTimetableSpace, ...]:
    rows = tuple(
        EditionSpaceSelection.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            venue_selection__organization_id=organization_id,
            venue_selection__edition_id=edition_id,
        )
        .order_by("venue_selection__local_name", "local_name", "id")
        .values_list(
            "id",
            "aggregate_version",
            "local_name",
            "configuration_name",
            "lifecycle",
            "venue_selection_id",
            "venue_selection__aggregate_version",
            "venue_selection__local_name",
            "venue_selection__lifecycle",
        )[: MAX_TIMETABLE_SPACES + 1]
    )
    if len(rows) > MAX_TIMETABLE_SPACES:
        raise VenueTimetableInventoryLimitError
    if EditionSpaceSelection.objects.filter(
        organization_id=organization_id, edition_id=edition_id
    ).count() != len(rows):
        raise VenueTimetableQueryUnavailableError
    return tuple(VenueTimetableSpace(*row) for row in rows)


def list_venue_timetable_spaces(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID, correlation_id: UUID
) -> tuple[VenueTimetableSpace, ...]:
    """Read complete bounded room labels separately from physical conflict evidence.

    The inventory includes retained selections so historical placements remain
    explainable. Active labels do not establish current capacity, availability,
    booking authority or accessibility fit. Those require separate owner reads.

    Parameters
    ----------
    actor_id : UUID
        Current verified person, independently authorized for workspace labels.
    organization_id : UUID
        Expected exact owner, never inferred from a room identifier.
    edition_id : UUID
        Exact edition containing every returned room and Venue selection.
    correlation_id : UUID
        Server-owned attribution for the required minimized read audit.

    Returns
    -------
    tuple[VenueTimetableSpace, ...]
        Complete inventory of at most 256 current or retained selections.

    Raises
    ------
    ValidationError
        If scope identifiers are not exact UUID values.
    VenueTimetableQueryDeniedError
        If current identity, edition, profile or field authority is insufficient.
    VenueTimetableQueryUnavailableError
        If complete bounded inventory or mandatory audit cannot be supplied.
    """
    for value in (actor_id, organization_id, edition_id, correlation_id):
        if not isinstance(value, UUID):
            raise ValidationError("Use exact UUID timetable scope identifiers.")

    def load() -> tuple[VenueTimetableSpace, ...]:
        # This label-only read locks no other person. Call separately from a
        # multi-person preview; its owner must acquire its complete person set.
        if (
            resolve_scheduling_edition_reference(
                organization_id=organization_id, edition_id=edition_id, lock=True
            )
            is None
            or resolve_active_verified_person_reference(account_id=actor_id, lock=True)
            is None
        ):
            raise VenueTimetableQueryDeniedError
        _authorize(actor_id, organization_id, edition_id)
        result = _inventory(organization_id, edition_id)
        decision = _authorize(actor_id, organization_id, edition_id)
        _audit(actor_id, organization_id, edition_id, correlation_id, decision)
        return result

    try:
        with transaction.atomic():
            return load()
    except VenueTimetableQueryDeniedError:
        try:
            with transaction.atomic():
                _audit(actor_id, organization_id, edition_id, correlation_id, None)
        except (DatabaseError, RuntimeError):
            pass
        raise
    except DatabaseError as error:
        raise VenueTimetableQueryUnavailableError from error
