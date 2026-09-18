"""Private exact-scope and genuine-controller admission for starter approval."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from maru.authorization.models import AuthorityControl
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    decide,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.provenance import (
    ControlHorizonMode,
    select_authorized_control_source,
)
from maru.authorization.services import AuthorizationDenied
from maru.events.adoption import (
    adoption_profile,
    profile_allows_capabilities,
    profile_allows_catalog_entry,
)
from maru.events.queries import (
    resolve_edition_series_identity,
    resolve_private_planning_edition_reference,
)
from maru.identity.models import Account
from maru.identity.queries import resolve_active_verified_person_references
from maru.organizations.programme_setup_references import (
    lock_programme_setup_foundation,
    resolve_programme_setup_foundation,
)
from maru.workforce.edition_write_scope import lock_workforce_edition_write_scope
from maru.workforce.programme_starter_inputs import (
    PROGRAMME_STARTER_DEFINITION,
    ProgrammeStarterScope,
    _scope,
)
from maru.workforce.programme_starter_readiness import (
    programme_starter_database_integrity_is_ready,
)

if TYPE_CHECKING:
    from uuid import UUID

    from maru.organizations.programme_setup_references import (
        ProgrammeSetupFoundationReference,
    )

_PROFILE = ("programme_operations", 1)
_DEFINITION_SHA256 = "13823da0315a8f4c1bbaf1b465662e0896a894508e8bef8e1a45d36d6da63b6a"


def _unavailable() -> AuthorizationDenied:
    return AuthorizationDenied(
        "Programme Volunteer starter is unavailable.",
        reason_code="programme_starter_unavailable",
    )


def _conflict(message: str, code: str) -> ValidationError:
    return ValidationError(message, code=f"programme_starter_{code}")


def _require_profile() -> None:
    definition = PROGRAMME_STARTER_DEFINITION
    if (
        adoption_profile(*_PROFILE) is None
        or definition.digest != _DEFINITION_SHA256
        or not profile_allows_catalog_entry(*_PROFILE, definition.catalog_entry)
        or not profile_allows_capabilities(*_PROFILE, definition.capability_codes)
    ):
        raise _unavailable()


def _resolve_scope(
    scope: ProgrammeStarterScope,
) -> tuple[ResolvedAuthorizationTarget, ResolvedAuthorizationTarget]:
    _scope(scope)
    organization = resolve_organization_target(organization_id=scope.organization_id)
    edition = resolve_edition_target(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if (
        organization is None
        or edition is None
        or (edition.adoption_profile_code, edition.adoption_profile_version) != _PROFILE
        or resolve_edition_series_identity(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        != scope.series_id
    ):
        raise _unavailable()
    return organization, edition


def _require_actor(
    actor: Account,
    targets: tuple[ResolvedAuthorizationTarget, ResolvedAuthorizationTarget],
) -> None:
    if (
        not isinstance(actor, Account)
        or not actor.is_active
        or actor.account_kind != Account.Kind.PERSON
        or actor.email_verified_at is None
        or not decide(
            principal=actor,
            capability_code="authorization.manage_roles",
            resource=targets[0],
        ).allowed
        or not decide(
            principal=actor,
            capability_code="workforce.manage_structure",
            resource=targets[1],
        ).allowed
    ):
        raise _unavailable()


def _require_controller(
    actor: Account,
    targets: tuple[ResolvedAuthorizationTarget, ResolvedAuthorizationTarget],
    *,
    role: str = AuthorityControl.Role.ACTOR,
) -> None:
    _require_actor(actor, targets)
    now = timezone.now()
    if (
        select_authorized_control_source(
            principal=actor,
            role=role,
            capability_code="authorization.manage_roles",
            target=targets[0],
            requested_effective_from=now,
            requested_expires_at=None,
            evaluated_at=now,
            horizon_mode=ControlHorizonMode.POINT_IN_TIME,
        )
        is None
    ):
        raise _unavailable()


def _lock_key(actor_id: UUID, key: UUID, purpose: str) -> None:
    digest = hashlib.sha256(purpose.encode() + actor_id.bytes + key.bytes)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [int.from_bytes(digest.digest()[:8], "big", signed=True)],
        )


def _lock_scope(scope: ProgrammeStarterScope) -> ProgrammeSetupFoundationReference:
    foundation = resolve_programme_setup_foundation(
        organization_id=scope.organization_id, series_id=scope.series_id
    )
    if foundation is None:
        raise _unavailable()
    locked = lock_programme_setup_foundation(
        organization_id=scope.organization_id,
        series_id=scope.series_id,
        expected_fingerprint=foundation.fingerprint,
    )
    if (
        locked is None
        or locked.organization_lifecycle != "active"
        or locked.representation_state != "active"
    ):
        raise _unavailable()
    lock_workforce_edition_write_scope(
        organization_id=scope.organization_id,
        series_id=scope.series_id,
        edition_id=scope.edition_id,
    )
    _resolve_scope(scope)
    return locked


def _require_planning(scope: ProgrammeStarterScope) -> None:
    reference = resolve_private_planning_edition_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if reference is None or not reference.accepts_private_planning_writes:
        raise _conflict("The private planning phase has ended.", "planning_closed")


def _lock_people(identities: set[UUID]) -> dict[UUID, Account]:
    references = resolve_active_verified_person_references(
        account_ids=identities, lock=True
    )
    if (
        references is None
        or {reference.account_id for reference in references} != identities
    ):
        raise _unavailable()
    return {
        person.id: person
        for person in Account.objects.filter(id__in=identities).only(
            "id", "account_kind", "is_active", "email_verified_at"
        )
    }


def _require_integrity() -> None:
    if not programme_starter_database_integrity_is_ready():
        raise _conflict(
            "Programme starter integrity is unavailable.", "integrity_unavailable"
        )
