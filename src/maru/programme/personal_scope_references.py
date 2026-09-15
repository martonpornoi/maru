"""Opaque own-host scope candidates and current proof, never an edition directory."""

from dataclasses import dataclass
from uuid import UUID

from django.db import DatabaseError, transaction

from maru.authorization.policy import PolicyDecision
from maru.events.queries import adoption_profile_filter_for_capabilities
from maru.events.write_references import lock_edition_ownership
from maru.identity.queries import resolve_active_verified_person_reference

from .authorization import (
    PROGRAMME_VIEW_HOST_SELF,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from .models import ProgrammeHostRelationship
from .queries import ProgrammeQueryUnavailableError

MAX_PERSONAL_HOST_EDITIONS = 256
_FIELDS = frozenset({"own_host_relationship", "own_host_invitation"})


@dataclass(frozen=True, slots=True)
class PersonalHostScopeSet:
    """Complete opaque own-host candidate scopes without labels or permission.

    Attributes
    ----------
    actor_id
        Current verified person whose retained relationships supply candidates.
    scopes
        Stable distinct organization/edition pairs, never a general directory.
    """

    actor_id: UUID
    scopes: tuple[tuple[UUID, UUID], ...]


@dataclass(frozen=True, slots=True)
class PersonalHostScopeProof:
    """Current minimal own-purpose evidence for separately authorized label reads.

    Attributes
    ----------
    actor_id, organization_id, edition_id
        Exact subject and independently admitted scope.
    present
        Whether at least one coherent retained own relationship exists.
    decision
        Complete current default self-policy decision, not a reusable permission.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    present: bool
    decision: PolicyDecision


def _person(actor_id: UUID) -> None:
    if type(actor_id) is not UUID or not actor_id.int:
        raise ProgrammeAuthorizationDeniedError
    person = resolve_active_verified_person_reference(account_id=actor_id)
    if person is None or person.account_id != actor_id:
        raise ProgrammeAuthorizationDeniedError


def personal_host_scope_candidates(*, actor_id: UUID) -> PersonalHostScopeSet:
    """Find only opaque retained own-host scopes in exact adopted profile pairs.

    Parameters
    ----------
    actor_id : UUID
        Genuine person, independently reloaded before and after candidate reads.

    Returns
    -------
    PersonalHostScopeSet
        Complete bounded candidates. No label or current scope authority is supplied.

    Raises
    ------
    ProgrammeQueryUnavailableError
        If candidates exceed the bound or the owner database is unavailable.

    Notes
    -----
    Invalid/inactive identity propagates ProgrammeAuthorizationDeniedError. This
    server-only reference reads just this person's opaque pairs, not invitation
    content or other people. Callers must separately admit and prove each scope
    before labels/audit/disclosure; candidates are not a permission token.
    """
    try:
        _person(actor_id)
        rows = tuple(
            ProgrammeHostRelationship.objects.filter(
                adoption_profile_filter_for_capabilities(
                    {PROGRAMME_VIEW_HOST_SELF}, field_prefix="edition"
                ),
                account_id=actor_id,
            )
            .order_by("organization_id", "edition_id")
            .values_list("organization_id", "edition_id")
            .distinct()[: MAX_PERSONAL_HOST_EDITIONS + 1]
        )
        if len(rows) > MAX_PERSONAL_HOST_EDITIONS:
            raise ProgrammeQueryUnavailableError
        _person(actor_id)
        return PersonalHostScopeSet(actor_id, rows)
    except DatabaseError as error:
        raise ProgrammeQueryUnavailableError from error


def personal_host_scope_proof(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> PersonalHostScopeProof:
    """Prove current coherent retained hosting without loading invitation content.

    Parameters
    ----------
    actor_id : UUID
        Actual person whose own relationship is required.
    organization_id : UUID
        Exact expected owner, never inferred from a narrower row.
    edition_id : UUID
        Independently admitted edition under canonical parent-before-person locks.

    Returns
    -------
    PersonalHostScopeProof
        Current default policy and retained-purpose presence, without names/counts.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If identifiers or returned owner attribution are incoherent.
    ProgrammeQueryUnavailableError
        If an owned relationship is corrupt, policy moves or database work fails.

    Notes
    -----
    The caller owns required label-disclosure audit and complete source comparison.
    A multi-edition compositor must acquire all admitted parents before its person
    lock; this seam never discovers another scope. No command or new audit is issued.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (actor_id, organization_id, edition_id)
    ):
        raise ProgrammeAuthorizationDeniedError
    try:
        with transaction.atomic():

            def authorize() -> PolicyDecision:
                scope = authorize_programme_scope(
                    actor_id=actor_id,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    capability_code=PROGRAMME_VIEW_HOST_SELF,
                    requested_fields=_FIELDS,
                )
                if (scope.actor_id, scope.organization_id, scope.edition_id) != (
                    actor_id,
                    organization_id,
                    edition_id,
                ):
                    raise ProgrammeAuthorizationDeniedError
                return scope.decision

            _person(actor_id)
            initial = authorize()
            if not lock_edition_ownership(
                organization_id=organization_id, edition_id=edition_id
            ):
                raise ProgrammeAuthorizationDeniedError
            person = resolve_active_verified_person_reference(
                account_id=actor_id, lock=True
            )
            if person is None or person.account_id != actor_id:
                raise ProgrammeAuthorizationDeniedError
            owned = ProgrammeHostRelationship.objects.filter(
                account_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            if owned.exclude(
                item__organization_id=organization_id, item__edition_id=edition_id
            ).exists():
                raise ProgrammeQueryUnavailableError
            present = owned.exists()
            if initial != authorize():
                raise ProgrammeQueryUnavailableError
            _person(actor_id)
            return PersonalHostScopeProof(
                actor_id, organization_id, edition_id, present, initial
            )
    except DatabaseError as error:
        raise ProgrammeQueryUnavailableError from error
