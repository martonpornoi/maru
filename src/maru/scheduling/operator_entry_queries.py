"""Complete independently admitted on-site purpose choices, not an output cache."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import (
    EditionAdoptionProfileReference,
    edition_adoption_profile_reference,
)
from maru.events.scheduling_queries import (
    SchedulingEditionReference,
    resolve_scheduling_edition_reference,
)
from maru.identity.queries import (
    ActiveVerifiedPersonReference,
    resolve_active_verified_person_reference,
)
from maru.venues.operator_entry_references import (
    OperatorRoomCandidate,
    OperatorRoomChoiceReference,
    OperatorRoomSetReference,
    resolve_operator_room_choice_reference,
    resolve_operator_room_set_reference,
)
from maru.venues.scheduling_queries import MAX_SCHEDULING_SPACE_SELECTIONS
from maru.workforce.adoption import WORKFORCE_PROGRAMME_STAFFING_ADAPTER
from maru.workforce.queries import (
    MAX_STRUCTURE_DEPARTMENTS,
    CurrentDepartmentChoiceReference,
    CurrentDepartmentSetReference,
    resolve_current_department_choice_reference,
    resolve_current_department_set_reference,
)

from .adoption import SCHEDULING_OPERATOR_RELEASE_ADAPTER
from .authorization import SchedulingAuthorizationDeniedError as Denied
from .command_support import SchedulingUnavailableError as Unavailable
from .operator_scope import (
    OperatorReadRequest,
    OperatorScopeKind,
    resolve_operator_entry_decision,
)
from .planning_queries import SchedulingReadRequest

if TYPE_CHECKING:
    from maru.authorization.policy import PolicyDecision

_OWNERS = (
    ("scheduling.view_operator_output", frozenset({"released_geometry"})),
    ("programme.view_operator_copy", frozenset({"reviewed_copy"})),
    ("venues.view_operator_wayfinding", frozenset({"scope_links", "wayfinding"})),
)
_WORK = ("workforce.view_operator_staffing", frozenset({"scope_links"}))


@dataclass(frozen=True, slots=True)
class OperatorEntryChoice:
    """Describe one current admitted purpose without optional private output.

    Attributes
    ----------
    kind, target_id
        Exact persisted purpose, never a portable authorization token.
    label
        Minimal owner-supplied room/Department label or fixed whole-edition text.
    detail
        Authorized venue context, stable Department code or fixed scope explanation.
    """

    kind: OperatorScopeKind
    target_id: UUID
    label: str
    detail: str


@dataclass(frozen=True, slots=True)
class OperatorEntryCatalog:
    """Retain complete choices and server-only source-comparison evidence.

    Attributes
    ----------
    choices
        Complete independently admitted current purposes, never all tenant targets.
    source_fingerprint
        Server-only complete source observation, not a credential or client field.
    """

    choices: tuple[OperatorEntryChoice, ...]
    source_fingerprint: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Purpose:
    kind: OperatorScopeKind
    target_id: UUID
    decisions: tuple[PolicyDecision, ...]


@dataclass(frozen=True, slots=True)
class _Snapshot:
    actor: ActiveVerifiedPersonReference
    edition: SchedulingEditionReference
    profile: EditionAdoptionProfileReference
    staffing: bool
    rooms: OperatorRoomSetReference
    departments: CurrentDepartmentSetReference
    purposes: tuple[_Purpose, ...]
    choices: tuple[OperatorEntryChoice, ...]


def _require(*, condition: bool) -> None:
    if not condition:
        raise Unavailable


def _uuid(value: object) -> bool:
    return type(value) is UUID and bool(value.int)


def _text(value: object, limit: int) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= limit
        and value == value.strip()
        and value.isprintable()
    )


def _owners(
    kind: OperatorScopeKind, *, staffing: bool
) -> tuple[tuple[str, frozenset[str]], ...]:
    return (
        (*_OWNERS, _WORK)
        if kind is OperatorScopeKind.DEPARTMENT and staffing
        else _OWNERS
    )


def _admitted(purpose: _Purpose, *, staffing: bool) -> bool:
    return all(
        decision.allowed and decision.fields == fields
        for decision, (_capability, fields) in zip(
            purpose.decisions, _owners(purpose.kind, staffing=staffing), strict=True
        )
    )


def _room_choice(
    scope: SchedulingReadRequest, room: OperatorRoomCandidate
) -> OperatorEntryChoice:
    reference = resolve_operator_room_choice_reference(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        space_id=room.space_id,
    )
    if not isinstance(reference, OperatorRoomChoiceReference):
        raise Unavailable
    _require(
        condition=reference.source == room
        and _text(reference.label, 200)
        and _text(reference.venue_label, 200)
    )
    return OperatorEntryChoice(
        OperatorScopeKind.ROOM, room.space_id, reference.label, reference.venue_label
    )


def _department_choice(
    scope: SchedulingReadRequest, target_id: UUID
) -> OperatorEntryChoice:
    reference = resolve_current_department_choice_reference(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        department_id=target_id,
    )
    if not isinstance(reference, CurrentDepartmentChoiceReference):
        raise Unavailable
    _require(
        condition=reference.department_id == target_id
        and _text(reference.label, 200)
        and _text(reference.code, 100)
    )
    return OperatorEntryChoice(
        OperatorScopeKind.DEPARTMENT, target_id, reference.label, reference.code
    )


def _snapshot(scope: SchedulingReadRequest, *, labels: bool) -> _Snapshot:
    actor = resolve_active_verified_person_reference(account_id=scope.actor_id)
    edition = resolve_scheduling_edition_reference(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
    )
    profile = edition_adoption_profile_reference(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
    )
    if (
        not isinstance(actor, ActiveVerifiedPersonReference)
        or actor.account_id != scope.actor_id
        or not isinstance(edition, SchedulingEditionReference)
        or edition.organization_id != scope.organization_id
        or edition.edition_id != scope.edition_id
        or not isinstance(profile, EditionAdoptionProfileReference)
        or profile_allows_adapter(
            profile.code, profile.version, SCHEDULING_OPERATOR_RELEASE_ADAPTER
        )
        is not True
    ):
        raise Denied
    staffing = profile_allows_adapter(
        profile.code, profile.version, WORKFORCE_PROGRAMME_STAFFING_ADAPTER
    )
    _require(condition=type(staffing) is bool)
    rooms = resolve_operator_room_set_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    departments = resolve_current_department_set_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if not isinstance(rooms, OperatorRoomSetReference) or not isinstance(
        departments, CurrentDepartmentSetReference
    ):
        raise Unavailable
    _require(
        condition=rooms.organization_id
        == departments.organization_id
        == scope.organization_id
        and rooms.edition_id == departments.edition_id == scope.edition_id
        and type(rooms.rooms) is tuple
        and len(rooms.rooms) <= MAX_SCHEDULING_SPACE_SELECTIONS
        and type(departments.department_ids) is tuple
        and len(departments.department_ids) <= MAX_STRUCTURE_DEPARTMENTS
        and all(_uuid(value) for value in departments.department_ids)
        and len(set(departments.department_ids)) == len(departments.department_ids)
    )
    for room in rooms.rooms:
        _require(
            condition=isinstance(room, OperatorRoomCandidate)
            and _uuid(room.space_id)
            and _uuid(room.venue_id)
            and _uuid(room.department_id)
            and room.department_id in departments.department_ids
            and type(room.version) is int
            and room.version > 0
            and type(room.venue_version) is int
            and room.venue_version > 0
        )
    _require(condition=len({room.space_id for room in rooms.rooms}) == len(rooms.rooms))
    targets = (
        (OperatorScopeKind.EDITION, scope.edition_id),
        *(
            (OperatorScopeKind.DEPARTMENT, value)
            for value in sorted(departments.department_ids)
        ),
        *(
            (OperatorScopeKind.ROOM, room.space_id)
            for room in sorted(rooms.rooms, key=lambda row: row.space_id)
        ),
    )
    purposes = tuple(
        _Purpose(
            kind,
            target_id,
            tuple(
                resolve_operator_entry_decision(
                    OperatorReadRequest(
                        scope.actor_id,
                        scope.organization_id,
                        scope.edition_id,
                        scope.correlation_id,
                        kind,
                        target_id,
                    ),
                    capability=capability,
                    fields=fields,
                )
                for capability, fields in _owners(kind, staffing=staffing)
            ),
        )
        for kind, target_id in targets
    )
    # Complete policy observation precedes every label lookup.
    by_id = {room.space_id: room for room in rooms.rooms}
    choices = []
    for purpose in purposes:
        if not labels or not _admitted(purpose, staffing=staffing):
            continue
        if purpose.kind is OperatorScopeKind.ROOM:
            choices.append(_room_choice(scope, by_id[purpose.target_id]))
        elif purpose.kind is OperatorScopeKind.DEPARTMENT:
            choices.append(_department_choice(scope, purpose.target_id))
        else:
            choices.append(
                OperatorEntryChoice(
                    purpose.kind,
                    purpose.target_id,
                    "Whole edition",
                    "All approved Programme work in this edition",
                )
            )
    _require(
        condition=len(
            {(row.kind, row.label.casefold(), row.detail.casefold()) for row in choices}
        )
        == len(choices)
    )
    return _Snapshot(
        actor,
        edition,
        profile,
        staffing,
        rooms,
        departments,
        purposes,
        tuple(
            sorted(
                choices,
                key=lambda row: (
                    row.kind,
                    row.detail.casefold(),
                    row.label.casefold(),
                    row.target_id,
                ),
            )
        ),
    )


def _scope(scope: SchedulingReadRequest) -> None:
    if not isinstance(scope, SchedulingReadRequest) or not all(
        _uuid(value)
        for value in (
            scope.actor_id,
            scope.organization_id,
            scope.edition_id,
            scope.correlation_id,
        )
    ):
        raise Denied


def _audit(scope: SchedulingReadRequest, snapshot: _Snapshot) -> None:
    admitted = tuple(
        purpose
        for purpose in snapshot.purposes
        if _admitted(purpose, staffing=snapshot.staffing)
    )
    records = tuple(
        (purpose.kind, purpose.target_id, capability, decision)
        for purpose in admitted
        for (capability, _fields), decision in zip(
            _owners(purpose.kind, staffing=snapshot.staffing),
            purpose.decisions,
            strict=True,
        )
    )
    for kind, target_id, capability, decision in records or (
        (None, None, _OWNERS[0][0], None),
    ):
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=scope.actor_id,
                principal_context_id=None,
                organization_id=scope.organization_id,
                event_edition_id=scope.edition_id,
                capability_code=capability,
                operation="scheduling.operator_entry.read",
                target_type=f"scheduling.operator_{kind.value}"
                if kind
                else "scheduling.operator_entry",
                target_id=target_id,
                outcome="allow" if decision else "deny",
                reason_code=decision.reason_code if decision else "permission_absent",
                correlation_id=scope.correlation_id,
                request_id=scope.correlation_id,
                source_channel="programme-operator-entry",
                obligations=("audit_sensitive_read",),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="workforce-personal"
                if capability.startswith("workforce.")
                else "programme-restricted",
            )
        )


def _encode(value: object) -> str | list[str]:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, frozenset):
        return sorted(value)
    raise TypeError


def load_operator_entry(scope: SchedulingReadRequest) -> OperatorEntryCatalog:
    """Read complete ordinary operator purposes with required audit and rechecks.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Actual authenticated principal and exact selected organization/edition.

    Returns
    -------
    OperatorEntryCatalog
        Complete admitted labels and server-only source evidence, possibly empty.

    Raises
    ------
    Unavailable
        SchedulingUnavailableError when complete sources, labels, policy comparison
        or required audit fails.

    Notes
    -----
    Invalid attribution, current profile or exact-purpose policy propagates
    SchedulingAuthorizationDeniedError from the shared admission boundary.
    No release, Programme content or personnel inventory is read. All default
    output owners authorize independently; adopted Department work membership
    requires its own field even without detailed staffing. No optional layers are
    requested. Pages repeat the complete observation after rendering their bytes.
    """
    _scope(scope)
    try:
        with transaction.atomic():
            initial = _snapshot(scope, labels=True)
            _require(condition=initial == _snapshot(scope, labels=True))
            _audit(scope, initial)
            fingerprint = hashlib.sha256(
                json.dumps(
                    asdict(initial),
                    default=_encode,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            return OperatorEntryCatalog(initial.choices, fingerprint)
    except (DatabaseError, ValidationError) as exc:
        raise Unavailable from exc


def can_enter_operator_tasks(scope: SchedulingReadRequest) -> bool:
    """Check an optional fixed-label link without names, output or new read audit.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Actual viewer and selected edition, never a reused authorization result.

    Returns
    -------
    bool
        Whether coherent current metadata admits any default output purpose.

    Notes
    -----
    False includes unavailable evidence and makes no completeness claim. The
    real entry independently reads, audits and rechecks its complete catalog.
    """
    try:
        _scope(scope)
        with transaction.atomic():
            initial = _snapshot(scope, labels=False)
            return initial == _snapshot(scope, labels=False) and any(
                _admitted(purpose, staffing=initial.staffing)
                for purpose in initial.purposes
            )
    except (Denied, Unavailable, DatabaseError, ValidationError):
        return False
