"""Export profile-admitted recipe definitions without personnel or authority history."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import transaction

from maru.audit.services import AuditRecord, append_audit
from maru.events.adoption import adoption_profile
from maru.events.queries import edition_adoption_profile_reference
from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER
from maru.programme.exit_archive_protocol import ProgrammeArchiveSection
from maru.workforce.programme_references import lock_programme_staffing_scope

from .catalog import POLICY_VERSION
from .policy import PolicyDecision, decide_verified_principal_exact_edition
from .programme_role_recipes import PROGRAMME_ROLE_RECIPES, ProgrammeRoleRecipe

if TYPE_CHECKING:
    from maru.programme.authorization import ProgrammeAuthorizer

MAX_EXIT_RECIPES: Final = 100
MAX_EXIT_JSON_BYTES: Final = 2_097_152
FIELDS: Final = frozenset({"adoption_profile_code", "adoption_profile_version"})
EXCLUSIONS: Final = (
    "actual-grants-and-assignments",
    "named-person-approval-requests",
    "private-approval-rationale",
    "identity-directories",
    "unadmitted-recipes",
)


class ProgrammeExitAuthorizationUnavailableError(RuntimeError):
    """Withhold unavailable profile configuration without private data."""

    def __init__(self) -> None:
        super().__init__("programme_exit_authorization_unavailable")


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _section(code: str, version: int) -> ProgrammeArchiveSection:
    profile = adoption_profile(code, version)
    if profile is None or profile.key != (code, version):
        raise ProgrammeExitAuthorizationUnavailableError
    expected = {
        entry
        for entry in profile.catalog_entries
        if entry.startswith("authorization.programme_role.")
    }
    recipes = tuple(
        sorted(
            (
                recipe
                for recipe in PROGRAMME_ROLE_RECIPES.values()
                if recipe.catalog_entry in expected
            ),
            key=lambda recipe: (recipe.code, recipe.version),
        )
    )
    if (
        len(recipes) > MAX_EXIT_RECIPES
        or {recipe.catalog_entry for recipe in recipes} != expected
    ):
        raise ProgrammeExitAuthorizationUnavailableError
    if any(type(recipe) is not ProgrammeRoleRecipe for recipe in recipes):
        raise ProgrammeExitAuthorizationUnavailableError
    records = [
        {
            "code": recipe.code,
            "version": recipe.version,
            "name": recipe.name,
            "purpose": recipe.purpose,
            "capability_codes": recipe.capability_codes,
            "target_scopes": tuple(scope.value for scope in recipe.target_scopes),
            "resource_kind": recipe.resource_kind,
            "digest": recipe.digest,
        }
        for recipe in recipes
    ]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(
            {
                "scope": {"const": "profile-recipe-definitions@1"},
                "purpose_exclusions": {"const": list(EXCLUSIONS)},
                "profile_code": {"type": "string"},
                "profile_version": {"type": "integer", "minimum": 1},
                "policy_version": {"type": "string"},
                "recipes": {
                    "type": "array",
                    "maxItems": MAX_EXIT_RECIPES,
                    "items": _object(
                        {
                            **{
                                name: {"type": "string"}
                                for name in ("code", "name", "purpose", "resource_kind")
                            },
                            "version": {"type": "integer", "minimum": 1},
                            "capability_codes": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "target_scopes": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                        }
                    ),
                },
            }
        ),
    }
    try:
        data = json.dumps(
            {
                "scope": "profile-recipe-definitions@1",
                "purpose_exclusions": EXCLUSIONS,
                "profile_code": code,
                "profile_version": version,
                "policy_version": POLICY_VERSION,
                "recipes": records,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        schema_bytes = json.dumps(
            schema, sort_keys=True, separators=(",", ":")
        ).encode()
    except (ValueError, TypeError, UnicodeError):
        raise ProgrammeExitAuthorizationUnavailableError from None
    if max(len(data), len(schema_bytes)) > MAX_EXIT_JSON_BYTES:
        raise ProgrammeExitAuthorizationUnavailableError
    return ProgrammeArchiveSection(
        "authorization", "authorization.programme-exit@1", data, schema_bytes
    )


def load_programme_exit_authorization(  # noqa: DOC503 -- nested admission raises denial.
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeArchiveSection:
    """Collect exact admitted recipe definitions, not effective or retained grants.

    Parameters
    ----------
    actor_id : UUID
        Actual currently authenticated requester.
    organization_id : UUID
        Exact expected tenant.
    edition_id : UUID
        Exact edition owning the independently readable profile pair.
    correlation_id : UUID
        Server-selected generation trace for mandatory owner audit.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Extra bulk purpose only, not the independent Events source policy.

    Returns
    -------
    ProgrammeArchiveSection
        Bounded immutable recipe definitions and explicit private-layer exclusions.

    Raises
    ------
    ProgrammeExitAuthorizationUnavailableError
        If scope, exact profile, recipe definitions or bounded encoding fails.
    PermissionDenied
        If independently evaluated Events basic profile fields are denied.

    Notes
    -----
    Full multi-owner composition must acquire its complete person/Department
    closure before this child reader's mandatory audit.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (
            actor_id,
            organization_id,
            edition_id,
            correlation_id,
        )
    ):
        raise ProgrammeExitAuthorizationUnavailableError

    def admit() -> None:
        authorize_programme_archive_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )
        decision = decide_verified_principal_exact_edition(
            principal_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="events.view_basic",
            requested_fields=FIELDS,
        )
        if (
            not isinstance(decision, PolicyDecision)
            or not decision.allowed
            or not decision.fields >= FIELDS
        ):
            raise PermissionDenied("Programme exit configuration unavailable.")

    admit()
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        admit()
        profile = edition_adoption_profile_reference(
            organization_id=organization_id, edition_id=edition_id
        )
        if profile is None:
            raise ProgrammeExitAuthorizationUnavailableError
        result = _section(profile.code, profile.version)
        if (
            edition_adoption_profile_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            != profile
        ):
            raise ProgrammeExitAuthorizationUnavailableError
        admit()
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="events.view_basic",
                operation="authorization.programme_exit.read",
                target_type="events.event_edition",
                target_id=edition_id,
                outcome="allow",
                reason_code="programme_exit_source",
                correlation_id=correlation_id,
                source_channel="programme-exit",
                obligations=("audit_sensitive_read",),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="programme-restricted",
            )
        )
        return result
