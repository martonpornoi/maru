"""Independently admitted, minimized Workforce operating-home projections."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, models
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.enforcement import (
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import decide_verified_principal_exact_edition
from maru.events.queries import (
    edition_adoption_profile_reference,
    resolve_edition_work_phase_reference,
    resolve_private_planning_edition_reference,
)
from maru.organizations.queries import organization_accepts_planning_changes
from maru.workforce.assignment_queries import MAX_ASSIGNMENT_RECORDS
from maru.workforce.availability_audit import append_availability_read_audit
from maru.workforce.availability_inputs import MAX_AVAILABILITY_WINDOWS
from maru.workforce.availability_queries import (
    AVAILABILITY_ORGANIZER_REQUIRED_FIELDS,
    MAX_AVAILABILITY_ASSIGNMENTS,
    MAX_AVAILABILITY_PEOPLE,
)
from maru.workforce.home_guidance import (
    WorkforceSetupGuidance,
    load_workforce_setup_guidance,
)
from maru.workforce.home_states import (
    AssignmentHomeFact,
    OperatingHomeItem,
    ShiftHomeFact,
    assignment_home_item,
    availability_home_item,
    shift_home_item,
)
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PersonAvailabilityWindow,
    PositionAssignment,
    ShiftCommitment,
    ShiftDemand,
)
from maru.workforce.queries import WORKFORCE_STRUCTURE_REQUIRED_FIELDS
from maru.workforce.shift_audit import append_shift_read_audit
from maru.workforce.shift_queries import (
    MAX_SHIFT_COMMITMENTS,
    MAX_SHIFT_DEMANDS,
    SHIFT_ORGANIZER_REQUIRED_FIELDS,
    _availability_is_current,
    _qualification_is_current,
    _with_availability_coverage,
)
from maru.workforce.structure_snapshot import repeatable_read_only_snapshot

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.authorization.policy import PolicyDecision
    from maru.events.queries import EditionWorkPhaseReference
    from maru.identity.models import Account

logger = logging.getLogger(__name__)
Area = Literal["assignments", "availability", "shifts"]
_AREAS: tuple[Area, ...] = ("assignments", "availability", "shifts")
_EDITION_FIELDS = frozenset({"lifecycle", "aggregate_version", "time_zone"})
_READS = {
    "assignments": (
        ("workforce.view_structure", WORKFORCE_STRUCTURE_REQUIRED_FIELDS),
        ("workforce.manage_assignments", frozenset()),
    ),
    "availability": (
        ("workforce.view_availability", AVAILABILITY_ORGANIZER_REQUIRED_FIELDS),
    ),
    "shifts": (("workforce.view_shifts", SHIFT_ORGANIZER_REQUIRED_FIELDS),),
}


class OperatingHomeUnavailableError(RuntimeError):
    """A complete coherent component cannot be safely released."""


@dataclass(frozen=True, slots=True)
class WorkforceHomeGuidance:
    """Bound the home contribution without turning it into authority or tasks.

    Attributes
    ----------
    setup
        Separately admitted existing setup continuation, if available.
    operating
        At most three independently admitted operating-area continuations.
    """

    setup: WorkforceSetupGuidance | None
    operating: tuple[OperatingHomeItem, ...] = ()


@dataclass(frozen=True, slots=True)
class _Context:
    actor: Account
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID
    http_method: str


@dataclass(frozen=True, slots=True)
class _Snapshot:
    item: OperatingHomeItem | None
    signature: str
    reference: EditionWorkPhaseReference
    flags: tuple[bool, ...]
    valid_until: datetime | None = None


def _decision(
    context: _Context, capability: str, fields: frozenset[str]
) -> PolicyDecision:
    return decide_verified_principal_exact_edition(
        principal_id=context.actor.id,
        organization_id=context.organization_id,
        edition_id=context.edition_id,
        capability_code=capability,
        requested_fields=fields,
        at=timezone.now(),
    )


def _require(
    context: _Context, capability: str, fields: frozenset[str]
) -> PolicyDecision:
    decision = _decision(context, capability, fields)
    if not decision.allowed:
        raise PermissionDenied
    try:
        require_complete_projection(
            required_fields=fields, permitted_fields=decision.fields
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied from error
    return decision


def _authorize(context: _Context, area: Area) -> PolicyDecision:
    _require(context, "events.view_basic", _EDITION_FIELDS)
    decision = None
    for capability, fields in _READS[area]:
        decision = _require(context, capability, fields)
    if decision is None:
        raise PermissionDenied
    return decision


def _adopted(context: _Context) -> bool:
    profile = edition_adoption_profile_reference(
        organization_id=context.organization_id, edition_id=context.edition_id
    )
    return bool(profile and (profile.code, profile.version) == ("workforce_only", 1))


def _reference(context: _Context) -> EditionWorkPhaseReference:
    reference = resolve_edition_work_phase_reference(
        organization_id=context.organization_id, edition_id=context.edition_id
    )
    if reference is None:
        raise OperatingHomeUnavailableError
    if not organization_accepts_planning_changes(
        organization_id=context.organization_id
    ):
        reference = replace(reference, phase="retained")
    return reference


def _flags(context: _Context, area: Area) -> tuple[bool, ...]:
    capabilities = {
        "assignments": ("authorization.manage_roles", "authorization.revoke"),
        "availability": (),
        "shifts": ("workforce.manage_shifts",),
    }[area]
    return tuple(_decision(context, code, frozenset()).allowed for code in capabilities)


def _assignments(
    context: _Context,
    reference: EditionWorkPhaseReference,
    flags: tuple[bool, ...],
    at: datetime,
) -> tuple[OperatingHomeItem, object, datetime | None]:
    rows = tuple(
        PositionAssignment.objects.filter(
            organization_id=context.organization_id, edition_id=context.edition_id
        )
        .order_by("id")
        .values_list(
            "id",
            "status",
            "proposed_by_id",
            "effective_from",
            "expires_at",
            "command_version",
        )[: MAX_ASSIGNMENT_RECORDS + 1]
    )
    if len(rows) > MAX_ASSIGNMENT_RECORDS or any(
        status not in PositionAssignment.Status.values or version is None or version < 1
        for _id, status, _proposer, _start, _end, version in rows
    ):
        raise OperatingHomeUnavailableError
    facts = tuple(
        AssignmentHomeFact(identity, status, proposer, start, end)
        for identity, status, proposer, start, end, _version in rows
    )
    boundary = min(
        (
            row.expires_at
            for row in facts
            if row.status == "active"
            and row.expires_at is not None
            and row.expires_at > at
        ),
        default=None,
    )
    return (
        assignment_home_item(
            facts,
            phase=reference.phase,
            now=at,
            actor_id=context.actor.id,
            can_issue=flags[0],
            can_end=flags[1],
        ),
        rows,
        boundary,
    )


def _availability(
    context: _Context, reference: EditionWorkPhaseReference
) -> tuple[OperatingHomeItem | None, object]:
    assignments = tuple(
        PositionAssignment.objects.filter(
            organization_id=context.organization_id,
            edition_id=context.edition_id,
            status__in=(
                PositionAssignment.Status.PROPOSED,
                PositionAssignment.Status.ACTIVE,
            ),
        )
        .order_by("id")
        .values_list("id", "account_id", "status", "command_version")[
            : MAX_AVAILABILITY_ASSIGNMENTS + 1
        ]
    )
    people = tuple(sorted({row[1] for row in assignments}))
    if (
        len(assignments) > MAX_AVAILABILITY_ASSIGNMENTS
        or len(people) > MAX_AVAILABILITY_PEOPLE
    ):
        raise OperatingHomeUnavailableError
    windows = PersonAvailabilityWindow.objects.filter(plan_id=models.OuterRef("id"))
    mismatched = windows.exclude(
        created_by_version=models.OuterRef("command_version"),
    )
    plans = tuple(
        PersonAvailabilityPlan.objects.filter(
            organization_id=context.organization_id,
            edition_id=context.edition_id,
            account_id__in=people,
        )
        .annotate(
            actual_windows=models.Count("windows"),
            mismatched_windows=models.Exists(mismatched),
        )
        .order_by("account_id")
        .values_list(
            "account_id",
            "status",
            "command_version",
            "window_count",
            "actual_windows",
            "mismatched_windows",
            "submitted_at",
            "withdrawn_at",
        )
    )
    states = dict.fromkeys(people, "not_shared")
    signature: list[object] = []
    for account, status, version, declared, actual, bad, submitted, withdrawn in plans:
        if status not in PersonAvailabilityPlan.Status.values:
            raise OperatingHomeUnavailableError
        if status == PersonAvailabilityPlan.Status.DRAFT:
            # Private edits and missing plans intentionally share consequences
            # and signatures, including when only a private draft changes.
            continue
        if (
            version < 1
            or actual != declared
            or actual > MAX_AVAILABILITY_WINDOWS
            or bad
        ):
            raise OperatingHomeUnavailableError
        if status == PersonAvailabilityPlan.Status.WITHDRAWN:
            if actual or submitted is not None or withdrawn is None:
                raise OperatingHomeUnavailableError
            states[account] = "withdrawn"
        else:
            if submitted is None or withdrawn is not None:
                raise OperatingHomeUnavailableError
            states[account] = "shared" if actual else "unavailable"
        signature.append((account, status, version, actual, submitted, withdrawn))
    return availability_home_item(tuple(states.values()), phase=reference.phase), (
        assignments,
        tuple(signature),
        tuple(states.items()),
    )


def _shifts(
    context: _Context,
    reference: EditionWorkPhaseReference,
    flags: tuple[bool, ...],
    at: datetime,
) -> tuple[OperatingHomeItem, object, datetime | None]:
    demands = tuple(
        ShiftDemand.objects.filter(
            organization_id=context.organization_id, edition_id=context.edition_id
        )
        .order_by("starts_at", "id")
        .values_list(
            "id",
            "status",
            "starts_at",
            "ends_at",
            "required_headcount",
            "command_version",
        )[: MAX_SHIFT_DEMANDS + 1]
    )
    if len(demands) > MAX_SHIFT_DEMANDS or any(
        status not in ShiftDemand.Status.values or version < 1
        for _id, status, _start, _end, _required, version in demands
    ):
        raise OperatingHomeUnavailableError
    ids = tuple(row[0] for row in demands)
    commitments = tuple(
        _with_availability_coverage(ShiftCommitment.objects.filter(demand_id__in=ids))
        .select_related("demand", "position_assignment", "availability_plan")
        .only(
            "id",
            "demand_id",
            "organization_id",
            "edition_id",
            "account_id",
            "status",
            "starts_at",
            "ends_at",
            "command_version",
            "availability_version",
            "position_assignment_id",
            "availability_plan_id",
            "demand__id",
            "demand__position_id",
            "position_assignment__id",
            "position_assignment__command_version",
            "position_assignment__status",
            "position_assignment__position_id",
            "position_assignment__effective_from",
            "position_assignment__expires_at",
            "availability_plan__id",
            "availability_plan__status",
            "availability_plan__command_version",
        )
        .order_by("demand_id", "id")[: MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(commitments) > MAX_SHIFT_COMMITMENTS:
        raise OperatingHomeUnavailableError
    grouped: dict[UUID, list[tuple[str, bool, bool]]] = {
        identity: [] for identity in ids
    }
    intervals = {row[0]: (row[2], row[3]) for row in demands}
    signature = []
    for row in commitments:
        if (
            row.organization_id != context.organization_id
            or row.edition_id != context.edition_id
            or row.status not in ShiftCommitment.Status.values
            or row.command_version < 1
            or (row.starts_at, row.ends_at) != intervals[row.demand_id]
        ):
            raise OperatingHomeUnavailableError
        active = row.status in (
            ShiftCommitment.Status.CLAIMED,
            ShiftCommitment.Status.CONFIRMED,
        )
        current = not active or (
            _availability_is_current(row) and _qualification_is_current(row)
        )
        independent = row.account_id != context.actor.id
        grouped[row.demand_id].append((row.status, current, independent))
        signature.append(
            (
                row.id,
                row.command_version,
                row.status,
                current,
                independent,
                row.position_assignment.command_version,
                row.availability_plan.command_version,
            )
        )
    facts = []
    for identity, status, start, end, required, _version in demands:
        rows = grouped[identity]
        confirmed = sum(state == "confirmed" for state, _current, _independent in rows)
        facts.append(
            ShiftHomeFact(
                identity,
                status,
                start,
                end,
                underfilled=confirmed < required,
                has_claims=any(
                    state == "claimed" for state, _current, _independent in rows
                ),
                has_independent_claim=any(
                    state == "claimed" and independent
                    for state, _current, independent in rows
                ),
                changed_evidence=any(
                    not current for _state, current, _independent in rows
                ),
            )
        )
    boundary = min(
        (
            instant
            for row in facts
            if row.status not in {"completed", "cancelled"}
            for instant in (row.starts_at, row.ends_at)
            if instant > at
        ),
        default=None,
    )
    return (
        shift_home_item(
            tuple(facts), phase=reference.phase, now=at, can_manage=flags[0]
        ),
        (demands, tuple(signature)),
        boundary,
    )


def _read(context: _Context, area: Area) -> _Snapshot:
    with repeatable_read_only_snapshot():
        _authorize(context, area)
        if not _adopted(context):
            raise PermissionDenied
        reference = _reference(context)
        flags = _flags(context, area)
        at = timezone.now()
        boundary = None
        item: OperatingHomeItem | None
        if area == "assignments":
            item, facts, boundary = _assignments(context, reference, flags, at)
        elif area == "availability":
            item, facts = _availability(context, reference)
        else:
            item, facts, boundary = _shifts(context, reference, flags, at)
        signature = hashlib.sha256(repr((reference, flags, facts)).encode()).hexdigest()
        return _Snapshot(item, signature, reference, flags, boundary)


def _audit(
    context: _Context, area: Area, decision: PolicyDecision, at: datetime
) -> None:
    if area != "assignments":
        audit_read = (
            append_availability_read_audit
            if area == "availability"
            else append_shift_read_audit
        )
        audit_read(
            actor=context.actor,
            organization_id=context.organization_id,
            edition_id=context.edition_id,
            decision=decision,
            correlation_id=context.correlation_id,
            route_name="admin:index",
            http_method=context.http_method,
            source_channel="web",
            occurred_at=at,
        )
    else:
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=context.actor.id,
                principal_context_id=None,
                organization_id=context.organization_id,
                event_edition_id=context.edition_id,
                capability_code="workforce.manage_assignments",
                operation="workforce.position_assignment.view",
                target_type="events.event_edition",
                target_id=context.edition_id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
                correlation_id=context.correlation_id,
                request_id=context.correlation_id,
                source_channel="web",
                obligations=tuple(sorted(decision.obligations)),
                changed_fields=(),
                safe_metadata={
                    "policy_version": POLICY_VERSION,
                    "route_name": "admin:index",
                    "http_method": context.http_method,
                },
                retention_class="workforce-restricted",
            ),
            occurred_at=at,
        )


def _stable(context: _Context, area: Area) -> _Snapshot:
    for _attempt in range(2):
        first = _read(context, area)
        last = _read(context, area)
        if first.signature != last.signature:
            continue
        # Both source snapshots admit full policy. Current policy/owner/action
        # checks are repeated at the later audit and final aggregate release.
        return last
    raise OperatingHomeUnavailableError


def _load_setup(context: _Context) -> WorkforceSetupGuidance | None:
    try:
        _require(
            context, "workforce.view_structure", WORKFORCE_STRUCTURE_REQUIRED_FIELDS
        )
        return load_workforce_setup_guidance(
            actor=context.actor,
            organization_id=context.organization_id,
            edition_id=context.edition_id,
            correlation_id=context.correlation_id,
            http_method=context.http_method,
        )
    except PermissionDenied:
        return None
    except (DatabaseError, RuntimeError, ValueError):
        return WorkforceSetupGuidance("unavailable", timezone.now())


def _prepare_area(
    context: _Context, area: Area
) -> tuple[Area, OperatingHomeItem, _Snapshot | None] | None:
    try:
        snapshot = _stable(context, area)
    except PermissionDenied:
        return None
    except (DatabaseError, RuntimeError, ValueError):
        logger.warning("Workforce home area unavailable: %s", area)
        return area, OperatingHomeItem(area + "_unavailable", 60), None
    return (area, snapshot.item, snapshot) if snapshot.item is not None else None


def _release_area(
    context: _Context, prepared: tuple[Area, OperatingHomeItem, _Snapshot | None]
) -> OperatingHomeItem | None:
    area, item, snapshot = prepared
    try:
        decision = _authorize(context, area)
        if snapshot is None:
            return item
        _check_snapshot(context, area, snapshot)
        checked_at = timezone.now()
        _audit(context, area, decision, checked_at)
        _authorize(context, area)
        _check_snapshot(context, area, snapshot)
        return replace(
            item, checked_at=timezone.now(), time_zone=snapshot.reference.time_zone
        )
    except PermissionDenied:
        return None
    except (DatabaseError, RuntimeError, ValueError):
        return OperatingHomeItem(area + "_unavailable", 60)


def _check_snapshot(context: _Context, area: Area, snapshot: _Snapshot) -> None:
    if snapshot.reference != _reference(context) or snapshot.flags != _flags(
        context, area
    ):
        raise OperatingHomeUnavailableError
    current = _read(context, area)
    if snapshot.signature != current.signature or (
        snapshot.valid_until is not None and timezone.now() >= snapshot.valid_until
    ):
        raise OperatingHomeUnavailableError


def _finalize_area(
    context: _Context,
    prepared: tuple[Area, OperatingHomeItem, _Snapshot | None],
    item: OperatingHomeItem,
) -> OperatingHomeItem | None:
    area, _original, snapshot = prepared
    try:
        _authorize(context, area)
        if snapshot is not None and item.checked_at is not None:
            _check_snapshot(context, area, snapshot)
    except PermissionDenied:
        return None
    except (DatabaseError, RuntimeError, ValueError):
        return OperatingHomeItem(area + "_unavailable", 60)
    else:
        return item


def _recheck_setup(
    context: _Context, setup: WorkforceSetupGuidance | None
) -> WorkforceSetupGuidance | None:
    if setup is None:
        return None
    try:
        _require(
            context, "workforce.view_structure", WORKFORCE_STRUCTURE_REQUIRED_FIELDS
        )
        can_manage = _decision(
            context, "workforce.manage_structure", frozenset()
        ).allowed
        reference = resolve_private_planning_edition_reference(
            organization_id=context.organization_id, edition_id=context.edition_id
        )
        if (
            reference is None
            or not reference.accepts_private_planning_writes
            or not organization_accepts_planning_changes(
                organization_id=context.organization_id
            )
        ):
            return replace(
                setup,
                step="unavailable" if setup.step == "unavailable" else "read_only",
                can_manage=False,
                position_id=None,
            )
    except PermissionDenied:
        return None
    except (DatabaseError, RuntimeError, ValueError):
        return WorkforceSetupGuidance("unavailable", timezone.now())
    return replace(setup, can_manage=setup.can_manage and can_manage)


def load_workforce_home_guidance(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    http_method: str,
) -> WorkforceHomeGuidance | None:
    """Compose separately admitted setup and operating guidance for one request.

    Parameters
    ----------
    actor : Account
        Current authenticated principal, reloaded by exact-Edition policy.
    organization_id : UUID
        Exact coherent organization, never authority inferred from context.
    edition_id : UUID
        Exact edition within that authorized organization.
    correlation_id : UUID
        Existing request identity for required minimized read evidence.
    http_method : str
        Read method, GET or HEAD.

    Returns
    -------
    WorkforceHomeGuidance | None
        Up to four minimized area items, or no contribution outside exact adoption.
        Missing authority omits one area; unavailable areas do not suppress others.
    """
    context = _Context(actor, organization_id, edition_id, correlation_id, http_method)
    if http_method not in {"GET", "HEAD"} or not _adopted(context):
        return None
    setup = _load_setup(context)
    prepared = tuple(
        candidate
        for area in _AREAS
        if (candidate := _prepare_area(context, area)) is not None
    )
    if not _adopted(context):
        return None
    released_items = tuple(
        (candidate, released)
        for candidate in prepared
        if (released := _release_area(context, candidate)) is not None
    )
    if not _adopted(context):
        return None
    items = tuple(
        final
        for candidate, item in released_items
        if (final := _finalize_area(context, candidate, item)) is not None
    )
    if items:
        try:
            _require(context, "events.view_basic", _EDITION_FIELDS)
        except PermissionDenied:
            items = ()
    setup = _recheck_setup(context, setup)
    if not _adopted(context):
        return None
    return WorkforceHomeGuidance(setup, items) if setup is not None or items else None
