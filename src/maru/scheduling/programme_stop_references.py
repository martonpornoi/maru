"""Identifier-only retained release closure for canonical Programme stop locking."""

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import connection

from maru.authorization.programme_stop_authorization import (
    require_programme_stop_preflight,
)
from maru.identity.queries import MAX_PERSON_REFERENCE_BATCH

from .catalogs import MAX_RELEASE_DEPENDENCY_USES
from .models import SchedulingRelease, SchedulingReleasePointer
from .readiness import scheduling_database_integrity_is_ready


def resolve_programme_stop_release_people(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> tuple[UUID, ...]:
    """Collect exact retained people before any actor, authority or pointer lock.

    Parameters
    ----------
    actor_id : UUID
        Actual stop requester, independently admitted by nonlocking preflight.
    organization_id : UUID
        Exact explicitly selected tenant, never discovered through private records.
    edition_id : UUID
        Exact Programme ownership already locked by the surrounding composer.

    Returns
    -------
    tuple[UUID, ...]
        Complete sorted bounded union of requester and active-release source people.
        These internal IDs must never be disclosed as a controller's person directory.

    Raises
    ------
    ValidationError
        If the transaction, native integrity, retained source or bound is unavailable.

    Notes
    -----
    The caller retains canonical parent locks, then locks this complete union and
    reauthorizes actual controller provenance. This grants no withdrawal authority;
    the public withdrawal command checks that separately. Inactive retained people
    remain in the lock closure so security changes and cleanup serialize correctly.
    """
    require_programme_stop_preflight(
        actor_id=actor_id, organization_id=organization_id, edition_id=edition_id
    )
    if not connection.in_atomic_block or not scheduling_database_integrity_is_ready():
        raise ValidationError("Stop source unavailable.", code="programme_stop_source")
    active = (
        SchedulingReleasePointer.objects.filter(
            organization_id=organization_id, edition_id=edition_id
        )
        .values_list("active_release_id", flat=True)
        .first()
    )
    if active is None:
        return (actor_id,)
    release = (
        SchedulingRelease.objects.filter(
            id=active,
            organization_id=organization_id,
            edition_id=edition_id,
            approval__organization_id=organization_id,
            approval__edition_id=edition_id,
        )
        .select_related("approval")
        .first()
    )
    if release is None:
        raise ValidationError("Stop source unavailable.", code="programme_stop_source")
    sources = tuple(
        release.approval.dependencies.filter(dependency__kind="identity_account")
        .order_by("id")
        .values_list("dependency__source_id", flat=True)[
            : MAX_RELEASE_DEPENDENCY_USES + 1
        ]
    )
    people = tuple(sorted({actor_id, *sources}))
    if (
        len(sources) > MAX_RELEASE_DEPENDENCY_USES
        or len(people) > MAX_PERSON_REFERENCE_BATCH
    ):
        raise ValidationError("Stop source unavailable.", code="programme_stop_source")
    return people
