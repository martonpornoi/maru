"""Require the extra archive purpose without granting any source-content access."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference

from .adoption import PROGRAMME_EXIT_ARCHIVE_ADAPTER
from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_EXPORT_ARCHIVE,
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDeniedError,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)

if TYPE_CHECKING:
    from uuid import UUID

PROGRAMME_ARCHIVE_FIELDS: Final = frozenset({"archive_requests", "source_lineage"})


def authorize_programme_archive_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    requested_fields: frozenset[str],
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    lock: bool = False,
) -> AuthorizedProgrammeScope:
    """Require current exact export fields and pinned archive-adapter admission.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated principal, reloaded through the owning policy seam.
    organization_id : UUID
        Exact expected tenant, never inferred from a task or source identifier.
    edition_id : UUID
        Exact edition whose export purpose is independently evaluated.
    requested_fields : frozenset[str]
        Nonempty closed archive-request or source-lineage fields; no wildcard.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Existing exact policy; replacement retains the sealed isolated-test guard.
    lock : bool, default=False
        Use the canonical parent/edition/actor lock seam inside a transaction.
        A whole-owner collector must establish complete person lock order first.

    Returns
    -------
    AuthorizedProgrammeScope
        Additional export-purpose admission only, not content or download authority.

    Raises
    ------
    ProgrammeAuthorizationDeniedError
        If fields, scope, current permission or the exact profile adapter is absent.

    Notes
    -----
    Each actual reader or worker must still check the current requester, every
    owning content/history/file ceiling, retention, source consistency and final
    disclosure admission, with required audit. Calling this helper performs no
    grant, task, artifact or audit write and does not activate a current profile.
    """
    if (
        type(requested_fields) is not frozenset
        or not requested_fields
        or not requested_fields <= PROGRAMME_ARCHIVE_FIELDS
    ):
        raise ProgrammeAuthorizationDeniedError
    scope = authorize_programme_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_EXPORT_ARCHIVE,
        requested_fields=requested_fields,
        authorizer=authorizer,
        lock=lock,
    )
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, PROGRAMME_EXIT_ARCHIVE_ADAPTER
    ):
        raise ProgrammeAuthorizationDeniedError
    return scope
