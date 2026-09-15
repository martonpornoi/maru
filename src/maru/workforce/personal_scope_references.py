"""Opaque own retained-work candidates, without suitability or an edition directory."""

from dataclasses import dataclass
from uuid import UUID

from django.db import DatabaseError, transaction

from maru.authorization.policy import PolicyDecision
from maru.events.queries import adoption_profile_filter_for_adapter
from maru.events.write_references import lock_edition_ownership
from maru.identity.queries import resolve_active_verified_person_reference

from .adoption import WORKFORCE_SELF_ADAPTER
from .models import ShiftCommitment
from .shift_commands import ShiftAuthorizationDeniedError, ShiftUnavailableError
from .timetable_queries import _authorize

MAX_PERSONAL_SHIFT_EDITIONS = 256


@dataclass(frozen=True, slots=True)
class PersonalShiftScopeSet:
    """Complete opaque candidates, never current disclosure authority.

    Attributes
    ----------
    actor_id
        Actual verified person whose retained work supplies candidates.
    scopes
        Distinct stable organization/edition pairs without labels or work contents.
    """

    actor_id: UUID
    scopes: tuple[tuple[UUID, UUID], ...]


@dataclass(frozen=True, slots=True)
class PersonalShiftScopeProof:
    """Current own-work presence and policy, without work titles or counts.

    Attributes
    ----------
    actor_id, organization_id, edition_id
        Exact independently authorized current person and owner scope.
    present
        Whether coherent retained own Shift records exist, including ended work.
    decision
        Current complete default owner policy, not reusable permission.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    present: bool
    decision: PolicyDecision


def _person(actor_id: UUID, *, lock: bool = False) -> None:
    if type(actor_id) is not UUID or not actor_id.int:
        raise ShiftAuthorizationDeniedError
    person = resolve_active_verified_person_reference(account_id=actor_id, lock=lock)
    if person is None or person.account_id != actor_id:
        raise ShiftAuthorizationDeniedError


def personal_shift_scope_candidates(*, actor_id: UUID) -> PersonalShiftScopeSet:
    """Find only opaque retained own-work scopes under exact profile filters.

    Parameters
    ----------
    actor_id : UUID
        Genuine current verified person, never a selected other account.

    Returns
    -------
    PersonalShiftScopeSet
        Complete bounded candidates; Assignment alone is never sufficient.

    Raises
    ------
    ShiftUnavailableError
        If complete candidates exceed the ceiling or the database is unavailable.

    Notes
    -----
    Identity denial propagates ShiftAuthorizationDeniedError. The consumer must
    separately admit and prove each scope before labels or disclosure. No general
    edition list, unclaimed work, suitability or other-person records are loaded.
    """
    try:
        _person(actor_id)
        rows = tuple(
            ShiftCommitment.objects.filter(
                adoption_profile_filter_for_adapter(
                    WORKFORCE_SELF_ADAPTER, field_prefix="edition"
                ),
                account_id=actor_id,
            )
            .order_by("organization_id", "edition_id")
            .values_list("organization_id", "edition_id")
            .distinct()[: MAX_PERSONAL_SHIFT_EDITIONS + 1]
        )
        if len(rows) > MAX_PERSONAL_SHIFT_EDITIONS:
            raise ShiftUnavailableError
        _person(actor_id)
        return PersonalShiftScopeSet(actor_id, rows)
    except DatabaseError as error:
        raise ShiftUnavailableError from error


def personal_shift_scope_proof(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> PersonalShiftScopeProof:
    """Prove coherent current own retained work with independent default authority.

    Parameters
    ----------
    actor_id : UUID
        Actual person whose retained Shift purpose must exist.
    organization_id : UUID
        Exact expected owner, never inferred from a narrower row.
    edition_id : UUID
        Independently admitted edition under canonical parent-before-person locks.

    Returns
    -------
    PersonalShiftScopeProof
        Presence and complete current policy, not work contents or counts.

    Raises
    ------
    ShiftAuthorizationDeniedError
        If identifiers, current person, parent ownership or owner authority fail.
    ShiftUnavailableError
        If ownership is corrupt, policy moves or the database is unavailable.

    Notes
    -----
    A multi-edition compositor must acquire all admitted parents before its person
    lock. The consumer owns mandatory label-disclosure audit and source comparison.
    This seam discovers no new scope and performs no mutation or extra audit.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (actor_id, organization_id, edition_id)
    ):
        raise ShiftAuthorizationDeniedError
    try:
        with transaction.atomic():
            _person(actor_id)
            initial = _authorize(actor_id, organization_id, edition_id)
            if not lock_edition_ownership(
                organization_id=organization_id, edition_id=edition_id
            ):
                raise ShiftAuthorizationDeniedError
            _person(actor_id, lock=True)
            owned = ShiftCommitment.objects.filter(
                account_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            if owned.exclude(
                demand__organization_id=organization_id,
                demand__edition_id=edition_id,
                demand__position__organization_id=organization_id,
                demand__position__edition_id=edition_id,
                demand__position__department__organization_id=organization_id,
                demand__position__department__edition_id=edition_id,
            ).exists():
                raise ShiftUnavailableError
            present = owned.exists()
            if initial != _authorize(actor_id, organization_id, edition_id):
                raise ShiftUnavailableError
            _person(actor_id)
            return PersonalShiftScopeProof(
                actor_id, organization_id, edition_id, present, initial
            )
    except DatabaseError as error:
        raise ShiftUnavailableError from error
