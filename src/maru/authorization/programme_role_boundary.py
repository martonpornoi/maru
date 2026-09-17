"""Internal exact scope, person and source checks for Programme access commands."""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from maru.authorization import commands as authority
from maru.authorization.catalog import ScopeLevel
from maru.authorization.commands import _lock_target
from maru.authorization.models import AuthorityControl, RoleBundle
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    decide,
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_resource_target,
)
from maru.authorization.programme_role_inputs import ProgrammeRoleScope
from maru.authorization.programme_role_readiness import (
    programme_role_database_integrity_is_ready,
)
from maru.authorization.provenance import (
    ControlHorizonMode,
    role_bundle_provenance_is_historical,
    select_authorized_control_source,
)
from maru.authorization.services import AuthorizationDenied
from maru.events.adoption import (
    adoption_profile,
    profile_allows_capabilities,
    profile_allows_catalog_entry,
)
from maru.events.write_references import lock_edition_ownership
from maru.identity.models import Account
from maru.identity.queries import resolve_active_verified_person_references
from maru.organizations.programme_setup_references import (
    lock_programme_setup_foundation,
    resolve_programme_setup_foundation,
)

if TYPE_CHECKING:
    from datetime import datetime

    from maru.authorization.programme_role_recipes import ProgrammeRoleRecipe

_PROFILE = ("programme_operations", 1)
_CAPABILITY = "authorization.manage_roles"


def _unavailable() -> AuthorizationDenied:
    return AuthorizationDenied(
        "Programme access is unavailable.", reason_code="programme_role_unavailable"
    )


def _conflict(message: str, code: str) -> ValidationError:
    return ValidationError(message, code=f"programme_role_{code}")


def _require_profile(recipe: ProgrammeRoleRecipe | None = None) -> None:
    if adoption_profile(*_PROFILE) is None or (
        recipe is not None
        and (
            not profile_allows_catalog_entry(*_PROFILE, recipe.catalog_entry)
            or not profile_allows_capabilities(*_PROFILE, recipe.capability_codes)
        )
    ):
        raise _unavailable()


def _validate_context(key: UUID, correlation_id: UUID, source_channel: str) -> None:
    if any(
        not isinstance(value, UUID) or value.int == 0 for value in (key, correlation_id)
    ):
        raise _conflict(
            "Use exact non-empty command identifiers.", "identifier_invalid"
        )
    if (
        not isinstance(source_channel, str)
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", source_channel) is None
    ):
        raise _conflict("Use a bounded source channel.", "channel_invalid")


def _validate_scope(scope: ProgrammeRoleScope) -> None:
    if not isinstance(scope, ProgrammeRoleScope) or not isinstance(
        scope.level, ScopeLevel
    ):
        raise _unavailable()
    identities: list[UUID | None] = [scope.organization_id, scope.programme_edition_id]
    if scope.level in {ScopeLevel.DEPARTMENT, ScopeLevel.RESOURCE}:
        identities.append(scope.department_id)
    elif scope.department_id is not None:
        raise _unavailable()
    if scope.level is ScopeLevel.RESOURCE:
        identities.append(scope.resource_binding_id)
        if scope.resource_kind != "venue.edition_space":
            raise _unavailable()
    elif scope.resource_binding_id is not None or scope.resource_kind:
        raise _unavailable()
    if any(not isinstance(value, UUID) or value.int == 0 for value in identities):
        raise _unavailable()


def _resolve_scope(scope: ProgrammeRoleScope) -> ResolvedAuthorizationTarget:
    _validate_scope(scope)
    context = resolve_edition_target(
        organization_id=scope.organization_id, edition_id=scope.programme_edition_id
    )
    if (
        context is None
        or (context.adoption_profile_code, context.adoption_profile_version) != _PROFILE
    ):
        raise _unavailable()
    target: ResolvedAuthorizationTarget | None = context
    if scope.level is ScopeLevel.ORGANIZATION:
        target = resolve_organization_target(organization_id=scope.organization_id)
    elif scope.level is ScopeLevel.DEPARTMENT and scope.department_id is not None:
        target = resolve_department_target(
            organization_id=scope.organization_id,
            edition_id=scope.programme_edition_id,
            department_id=scope.department_id,
        )
    elif scope.level is ScopeLevel.RESOURCE and (
        scope.department_id is not None and scope.resource_binding_id is not None
    ):
        target = resolve_resource_target(
            organization_id=scope.organization_id,
            edition_id=scope.programme_edition_id,
            department_id=scope.department_id,
            resource_binding_id=scope.resource_binding_id,
        )
    if target is None:
        raise _unavailable()
    return target


def _require_actor(actor: Account, target: ResolvedAuthorizationTarget) -> None:
    if (
        not actor.is_active
        or actor.account_kind != Account.Kind.PERSON
        or actor.email_verified_at is None
        or not decide(
            principal=actor, capability_code=_CAPABILITY, resource=target
        ).allowed
    ):
        raise _unavailable()


def _lock_key(actor_id: UUID, key: UUID, purpose: str) -> None:
    digest = hashlib.sha256(purpose.encode() + actor_id.bytes + key.bytes)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [int.from_bytes(digest.digest()[:8], "big", signed=True)],
        )


def _lock_scope(scope: ProgrammeRoleScope) -> ResolvedAuthorizationTarget:
    foundation = resolve_programme_setup_foundation(
        organization_id=scope.organization_id
    )
    if foundation is None:
        raise _unavailable()
    locked = lock_programme_setup_foundation(
        organization_id=scope.organization_id,
        expected_fingerprint=foundation.fingerprint,
    )
    if (
        locked is None
        or locked.organization_lifecycle != "active"
        or (locked.representation_state != "active")
    ):
        raise _unavailable()
    if not lock_edition_ownership(
        organization_id=scope.organization_id, edition_id=scope.programme_edition_id
    ):
        raise _unavailable()
    context = resolve_edition_target(
        organization_id=scope.organization_id, edition_id=scope.programme_edition_id
    )
    if context is None:
        raise _unavailable()
    locked_context = _lock_target(context)
    if locked_context.edition is None or locked_context.edition.lifecycle in {
        "archived",
        "cancelled",
    }:
        raise _unavailable()
    locked_target = _lock_target(_resolve_scope(scope))
    if scope.level is ScopeLevel.RESOURCE and (
        locked_target.resource_binding is None
        or locked_target.resource_binding.resource_kind != scope.resource_kind
    ):
        raise _unavailable()
    return locked_target.target


def _lock_people(identities: set[UUID]) -> dict[UUID, Account]:
    references = resolve_active_verified_person_references(
        account_ids=identities, lock=True
    )
    if references is None or {value.account_id for value in references} != identities:
        raise _unavailable()
    return {
        person.id: person
        for person in Account.objects.filter(id__in=identities).only(
            "id", "account_kind", "is_active", "email_verified_at"
        )
    }


def _require_current_controller(
    actor: Account, target: ResolvedAuthorizationTarget
) -> None:
    _require_actor(actor, target)
    now = timezone.now()
    if (
        select_authorized_control_source(
            principal=actor,
            role=AuthorityControl.Role.ACTOR,
            capability_code=_CAPABILITY,
            target=target,
            requested_effective_from=now,
            requested_expires_at=None,
            evaluated_at=now,
            horizon_mode=ControlHorizonMode.POINT_IN_TIME,
        )
        is None
    ):
        raise _unavailable()


def _require_horizons(
    author: Account,
    approver: Account,
    target: ResolvedAuthorizationTarget,
    start: datetime,
    end: datetime | None,
) -> None:
    for principal in (author, approver):
        _require_actor(principal, target)
        authority.require_authorized_control_horizon(
            principal=principal,
            capability_code=_CAPABILITY,
            target=target,
            requested_effective_from=start,
            requested_expires_at=end,
        )


def _require_integrity() -> None:
    if not programme_role_database_integrity_is_ready():
        raise _conflict(
            "Programme approval integrity is unavailable.", "integrity_unavailable"
        )


def _exact_bundle(
    *,
    scope: ProgrammeRoleScope,
    recipe: ProgrammeRoleRecipe,
    author: Account,
    approver: Account,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
) -> RoleBundle:
    bundle = RoleBundle.objects.filter(
        organization_id=scope.organization_id,
        code=recipe.role_code,
        version=recipe.version,
    ).first()
    if bundle is None:
        if RoleBundle.objects.filter(
            organization_id=scope.organization_id, code=recipe.role_code
        ).exists():
            raise _conflict(
                "The reviewed role version is unavailable.", "recipe_conflict"
            )
        organization = resolve_organization_target(
            organization_id=scope.organization_id
        )
        if organization is None:
            raise _unavailable()
        bundle = authority.create_role_bundle_version(
            actor=author,
            approver=approver,
            target=organization,
            code=recipe.role_code,
            name=recipe.name,
            capability_codes=recipe.capability_codes,
            reason=reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
    if (
        bundle.version != recipe.version
        or bundle.name != recipe.name
        or tuple(bundle.capability_codes) != recipe.capability_codes
        or not role_bundle_provenance_is_historical(
            bundle=bundle, evaluated_at=timezone.now(), lock=True
        )
    ):
        raise _conflict("The reviewed role version is unavailable.", "recipe_conflict")
    return bundle
