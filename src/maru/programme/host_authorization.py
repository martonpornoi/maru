"""Identity/adoption admission for retained host retries, never fresh authority."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import connection

from maru.events.adoption import profile_allows_capability
from maru.events.queries import edition_adoption_profile_reference
from maru.identity.queries import resolve_active_verified_person_reference

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_HOST_SELF_CAPABILITIES,
    PROGRAMME_MANAGE_HOSTS,
    PROGRAMME_VIEW_HOSTS,
    ProgrammeAuthorizationDeniedError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import ProgrammeAuthorizer


def authorize_host_retry_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> None:
    """Prove current person and exact adoption before identifier-only retained replay.

    Parameters
    ----------
    actor_id : UUID
        Authenticated person whose own retained receipt may be read.
    organization_id : UUID
        Expected owner of the edition and receipt.
    edition_id : UUID
        Exact edition containing the caller-owned retry key.
    capability_code : str
        Code-owned operation capability that the exact profile must still pin.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real policy adapter or the existing two-factor isolated-test substitute.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If identity, scope, adoption or substitute containment is unavailable.

    Notes
    -----
    This proves no fresh host authority and grants no roster or content read.
    Fresh commands independently authorize their capability and relationship.
    """
    if capability_code not in {
        PROGRAMME_MANAGE_HOSTS,
        PROGRAMME_VIEW_HOSTS,
        *PROGRAMME_HOST_SELF_CAPABILITIES,
    }:
        raise ProgrammeAuthorizationDeniedError
    substitute = authorizer is not DEFAULT_PROGRAMME_AUTHORIZER
    if substitute:
        name = connection.settings_dict.get("NAME")
        if (
            not getattr(settings, "MARU_ALLOW_PROGRAMME_TEST_AUTHORIZER", False)
            or not isinstance(name, str)
            or not name.startswith("test_")
        ):
            raise ProgrammeAuthorizationDeniedError
    person = resolve_active_verified_person_reference(account_id=actor_id)
    profile = edition_adoption_profile_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if (
        person is None
        or profile is None
        or (
            not substitute
            and not profile_allows_capability(
                profile.code, profile.version, capability_code
            )
        )
    ):
        raise ProgrammeAuthorizationDeniedError
