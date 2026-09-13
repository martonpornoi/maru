"""Closed operator-purpose targets shared by independently authorizing owners.

A request is an attribution and selection, never a permission token. Each owner
uses its own fixed capability and fields through this boundary before reading
content and again before its mandatory audit. No planner or public permission
is substituted and no profile is activated here.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import CAPABILITIES, POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_department,
    decide_verified_principal_exact_edition,
    decide_verified_principal_exact_resource,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.identity.queries import resolve_active_verified_person_reference
from maru.venues.authorization import resolve_edition_space_target
from maru.workforce.programme_references import lock_programme_staffing_scope

from .adoption import SCHEDULING_OPERATOR_RELEASE_ADAPTER
from .authorization import SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError

if TYPE_CHECKING:
    from collections.abc import Iterator

OPERATOR_CAPABILITIES = frozenset(
    {
        "scheduling.view_operator_output",
        "programme.view_operator_copy",
        "programme.view_operator_delivery",
        "venues.view_operator_wayfinding",
        "workforce.view_operator_staffing",
    }
)


class OperatorScopeKind(StrEnum):
    """Select one persisted purpose target, never an inferred ownership tree."""

    ROOM = "room"
    DEPARTMENT = "department"
    EDITION = "edition"


@dataclass(frozen=True, slots=True)
class OperatorReadRequest:
    """Untrusted exact selection with trusted authenticated attribution.

    Attributes
    ----------
    actor_id
        Authenticated current account, independently verified by ordinary policy.
    organization_id
        Expected exact organization owner.
    edition_id
        Expected exact edition, never an arbitrary release selector.
    correlation_id
        Server-created trace for mandatory per-owner sensitive-read evidence.
    kind
        Closed room, Department or edition purpose.
    target_id
        Exact persisted room/Department/edition identity, not a portable grant.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID
    kind: OperatorScopeKind
    target_id: UUID


def authorize_operator_scope(
    request: OperatorReadRequest, *, capability: str, fields: frozenset[str]
) -> PolicyDecision:
    """Independently authorize one owner's fields against the exact purpose.

    Parameters
    ----------
    request : OperatorReadRequest
        Untrusted selection with authenticated attribution.
    capability : str
        One of the five code-owned operator capabilities.
    fields : frozenset[str]
        Nonempty owner-selected fields, not a user-supplied disclosure ceiling.

    Returns
    -------
    PolicyDecision
        Complete current decision, not reusable by another owner or request.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        Uniformly for malformed, foreign, inactive, unadopted or denied targets.
    """
    if (
        not isinstance(request, OperatorReadRequest)
        or not isinstance(request.kind, OperatorScopeKind)
        or any(
            not isinstance(value, UUID)
            for value in (
                request.actor_id,
                request.organization_id,
                request.edition_id,
                request.correlation_id,
                request.target_id,
            )
        )
        or type(capability) is not str
        or capability not in OPERATOR_CAPABILITIES
        or not isinstance(fields, frozenset)
        or not fields
        or not fields <= CAPABILITIES[capability].field_ceiling
    ):
        raise SchedulingAuthorizationDeniedError
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, SCHEDULING_OPERATOR_RELEASE_ADAPTER
    ):
        raise SchedulingAuthorizationDeniedError
    if request.kind is OperatorScopeKind.ROOM:
        target = resolve_edition_space_target(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            space_selection_id=request.target_id,
        )
        if (
            target is None
            or target.department_id is None
            or target.resource_binding_id is None
        ):
            raise SchedulingAuthorizationDeniedError
        decision = decide_verified_principal_exact_resource(
            principal_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=capability,
            requested_fields=fields,
            department_id=target.department_id,
            resource_binding_id=target.resource_binding_id,
        )
    elif request.kind is OperatorScopeKind.DEPARTMENT:
        decision = decide_verified_principal_exact_department(
            principal_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=capability,
            requested_fields=fields,
            department_id=request.target_id,
        )
    else:
        if request.target_id != request.edition_id:
            raise SchedulingAuthorizationDeniedError
        decision = decide_verified_principal_exact_edition(
            principal_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=capability,
            requested_fields=fields,
        )
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or not fields <= decision.fields
    ):
        raise SchedulingAuthorizationDeniedError
    return decision


def _audit(
    request: OperatorReadRequest, capability: str, decision: PolicyDecision | None
) -> None:
    owner = capability.split(".", 1)[0]
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code=capability,
            operation=f"{owner}.operator_output.read",
            target_type=f"scheduling.operator_{request.kind.value}",
            target_id=request.target_id if decision else None,
            outcome="allow" if decision else "deny",
            reason_code=decision.reason_code if decision else "operator_read_denied",
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel="programme-operator",
            obligations=tuple(
                sorted(
                    (decision.obligations if decision else frozenset())
                    | {"audit_sensitive_read"}
                )
            ),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-personal"
            if owner == "workforce"
            else "programme-restricted",
        )
    )


def _lock_actor(request: OperatorReadRequest) -> None:
    if (
        resolve_active_verified_person_reference(account_id=request.actor_id, lock=True)
        is None
    ):
        raise SchedulingAuthorizationDeniedError


@contextmanager
def operator_read(
    request: OperatorReadRequest, *, capability: str, fields: frozenset[str]
) -> Iterator[None]:
    """Guard an owner read with canonical locks, fresh authority and required audit.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact purpose and attribution, never caller authorization proof.
    capability : str
        Owner's fixed operator capability.
    fields : frozenset[str]
        Independently required owner's fields, including for an empty result.

    Yields
    ------
    None
        A transaction scope; it returns no transferable authorization object.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If any initial or final authority, ownership or actor check fails.
    SchedulingUnavailableError
        If database evidence or mandatory successful-read audit is unavailable.

    Notes
    -----
    Owners must bound and recheck their own content and membership. Shared
    parents and the structure mutex precede actor locks, matching Programme and
    Scheduling writers. The mutex is profile-neutral with respect to the optional
    Programme staffing adapter; Workforce's foundational Department scope is
    still required. Failed output never commits a successful-read audit.
    """
    authorize_operator_scope(request, capability=capability, fields=fields)
    try:
        with transaction.atomic():
            lock_programme_staffing_scope(
                organization_id=request.organization_id, edition_id=request.edition_id
            )
            authorize_operator_scope(request, capability=capability, fields=fields)
            yield
            _lock_actor(request)
            decision = authorize_operator_scope(
                request, capability=capability, fields=fields
            )
            _audit(request, capability, decision)
    except SchedulingAuthorizationDeniedError:
        try:
            with transaction.atomic():
                _audit(request, capability, None)
        except (DatabaseError, RuntimeError, ValidationError):
            pass
        raise
    except (DatabaseError, ValidationError) as error:
        raise SchedulingUnavailableError from error
