"""Metadata-only admission for exact already-disclosed bound Shift destinations."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import DatabaseError
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.queries import resolve_edition_route_identity

from .shift_queries import MAX_SHIFT_DEMANDS, SHIFT_ORGANIZER_REQUIRED_FIELDS

if TYPE_CHECKING:
    from collections.abc import Collection


def programme_shift_links(
    *,
    actor_id: UUID,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    demand_ids: Collection[UUID],
    urlconf: Any = None,
) -> dict[UUID, str]:
    """Resolve optional exact-demand links without reading personnel or work facts.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated source actor.
    organization_id : UUID
        Already admitted exact source organization.
    series_id : UUID
        Independently verified source parent.
    edition_id : UUID
        Already admitted exact source edition.
    demand_ids : Collection[UUID]
        Current owner-verified binding demands already disclosed by the source.
    urlconf : Any, default=None
        Current request URL configuration.

    Returns
    -------
    dict[UUID, str]
        Fixed-purpose resolved destinations, or empty when denied or unavailable.

    Notes
    -----
    The source must retain its audited binding query and final lineage check.
    This helper cannot prove demand existence, lifecycle or current coverage and
    never follows a successor. The destination repeats its full native admission.
    No new sensitive read occurs: only admitted route metadata is resolved.
    Callers repeat after rendering and omit moved links before releasing bytes.
    """
    if (
        not demand_ids
        or len(demand_ids) > MAX_SHIFT_DEMANDS
        or any(
            not isinstance(value, UUID)
            for value in (actor_id, organization_id, series_id, edition_id, *demand_ids)
        )
    ):
        return {}
    name = "organization-workforce-shift"

    def admitted() -> bool:
        decision = decide_verified_principal_exact_edition(
            principal_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="workforce.view_shifts",
            requested_fields=SHIFT_ORGANIZER_REQUIRED_FIELDS,
        )
        return (
            isinstance(decision, PolicyDecision)
            and decision.allowed
            and (decision.fields >= SHIFT_ORGANIZER_REQUIRED_FIELDS)
        )

    try:
        reverse(
            name,
            kwargs={
                "organization_slug": "probe",
                "series_slug": "probe",
                "edition_slug": "probe",
                "demand_id": next(iter(demand_ids)),
            },
            urlconf=urlconf,
        )
        if not admitted():
            return {}
        identity = resolve_edition_route_identity(
            organization_id=organization_id, series_id=series_id, edition_id=edition_id
        )
        if identity is None:
            return {}
        links = {}
        for demand_id in demand_ids:
            kwargs = asdict(identity) | {"demand_id": demand_id}
            url = reverse(name, kwargs=kwargs, urlconf=urlconf)
            target = resolve(url, urlconf=urlconf)
            if target.view_name == name and target.kwargs == kwargs:
                links[demand_id] = url
        return links if admitted() else {}
    except (DatabaseError, RuntimeError, NoReverseMatch, Resolver404):
        return {}
