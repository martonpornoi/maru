"""Current ordinary controller admission for minimized Programme stop purposes."""

from uuid import UUID

from django.db import connection

from maru.authorization.catalog import ScopeLevel
from maru.authorization.policy import decide, decide_verified_principal_exact_edition
from maru.authorization.programme_role_boundary import (
    _lock_people,
    _lock_scope,
    _require_current_controller,
    _require_integrity,
    _require_profile,
    _resolve_scope,
)
from maru.authorization.programme_role_inputs import ProgrammeRoleScope
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied
from maru.identity.queries import resolve_active_verified_person_references


def require_programme_stop_preflight(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> None:
    """Admit minimized lock preparation without granting the final stop operation.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated person, never an alternate privileged principal.
    organization_id, edition_id : UUID
        Exact expected tenant and Programme version-one adoption.

    Raises
    ------
    AuthorizationDenied
        If identity, profile, scope or either ordinary capability is unavailable.

    Notes
    -----
    This nonlocking observation permits only preparation of canonical parent and
    affected-person locks. It is not controller provenance, a stable authorization
    proof, source-content access or mutation authority. Callers must subsequently
    invoke ``require_programme_stop_controller`` in their retained transaction.
    """
    if any(
        type(value) is not UUID or value.int == 0
        for value in (actor_id, organization_id, edition_id)
    ):
        raise AuthorizationDenied(
            "Programme stop is unavailable.", reason_code="programme_stop_unavailable"
        )
    _require_profile()
    people = resolve_active_verified_person_references(account_ids={actor_id})
    if people is None or tuple(person.account_id for person in people) != (actor_id,):
        raise AuthorizationDenied(
            "Programme stop is unavailable.", reason_code="programme_stop_unavailable"
        )
    _resolve_scope(ProgrammeRoleScope(organization_id, edition_id, ScopeLevel.EDITION))
    for capability in ("authorization.manage_roles", "events.transition"):
        if not decide_verified_principal_exact_edition(
            principal_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability,
        ).allowed:
            raise AuthorizationDenied(
                "Programme stop is unavailable.",
                reason_code="programme_stop_unavailable",
            )


def require_programme_stop_controller(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> None:
    """Require actual controller provenance and independent edition-stop authority.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated person, reloaded and locked; never an alternate actor.
    organization_id, edition_id : UUID
        Exact expected tenant and Programme adoption, not discovered private scope.

    Raises
    ------
    AuthorizationDenied
        If scope, active accountability, ordinary controller provenance or current
        Events transition authority is unavailable. Platform status is insufficient.
    RuntimeError
        If the caller has not opened the transaction that retains all scope locks.

    Notes
    -----
    This admits only the explicit minimized stop-impact purpose. It does not grant
    source-content/export permission, release withdrawal, authority revocation or
    mutation rights. Each owning consequence must independently authorize again.
    Retained terminal scope is admitted for original authorized receipt replay;
    lifecycle and native command readiness remain Events' independent obligation.
    A composer must acquire the complete affected-person closure in stable order
    before this selector locks controller provenance or appends disclosure audit.
    """
    if any(
        type(value) is not UUID or value.int == 0
        for value in (actor_id, organization_id, edition_id)
    ):
        raise AuthorizationDenied(
            "Programme stop is unavailable.", reason_code="programme_stop_unavailable"
        )
    if not connection.in_atomic_block:
        raise RuntimeError("Programme stop admission requires an open transaction.")
    require_programme_stop_preflight(
        actor_id=actor_id, organization_id=organization_id, edition_id=edition_id
    )
    lock_retired_department_authority_boundaries()
    _require_profile()
    scope = ProgrammeRoleScope(organization_id, edition_id, ScopeLevel.EDITION)
    target = _lock_scope(scope, historical=True)
    actor = _lock_people({actor_id})[actor_id]
    _require_current_controller(actor, target)
    decision = decide(
        principal=actor, capability_code="events.transition", resource=target
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "Programme stop is unavailable.", reason_code="programme_stop_unavailable"
        )
    _require_integrity()
