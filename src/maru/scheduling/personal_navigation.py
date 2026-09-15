"""Same-person Programme task connections without purpose or edition discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from maru.applications.programme_authorization import (
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    ApplicationsProgrammeAuthorizationDeniedError,
    AuthorizedProgrammeSelfEntryScope,
    authorize_programme_self_entry_scope,
)
from maru.identity.queries import resolve_active_verified_person_reference
from maru.programme.authorization import (
    PROGRAMME_VIEW_HOST_SELF,
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)

from .authorization import SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError
from .personal_output_queries import authorize_personal_timetable_scope


@dataclass(frozen=True, slots=True)
class PersonalProgrammeTaskLink:
    """Fixed-label continuation for the actual source viewer, never a grant.

    Attributes
    ----------
    code, label
        Closed task identity and code-owned text without private source labels.
    url
        Current exact-edition task or own-edition chooser, without a person selector.
    """

    code: str
    label: str
    url: str


_TASKS = {
    "editions": ("Choose my timetable edition", "my-programme-timetable-editions"),
    "proposals": ("My Programme proposals", "my-programme-proposals"),
    "hosting": ("My hosting invitations and availability", "my-programme-hosts"),
    "timetable": ("My current hosting and work timetable", "my-hosting-work-timetable"),
}


def _admit(actor_id: UUID, organization_id: UUID, edition_id: UUID, code: str) -> None:
    if code == "editions":
        person = resolve_active_verified_person_reference(account_id=actor_id)
        if person is None or person.account_id != actor_id:
            raise SchedulingAuthorizationDeniedError
        return
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    if code == "timetable":
        authorize_personal_timetable_scope(**scope)
        return
    admitted: AuthorizedProgrammeSelfEntryScope | AuthorizedProgrammeScope
    if code == "proposals":
        fields = frozenset({"proposal_summary", "selection", "own_invitation"})
        admitted = authorize_programme_self_entry_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=fields,
        )
    else:
        fields = frozenset({"own_host_relationship", "own_host_invitation"})
        admitted = authorize_programme_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=PROGRAMME_VIEW_HOST_SELF,
            requested_fields=fields,
        )
    if (
        not isinstance(
            admitted, (AuthorizedProgrammeSelfEntryScope, AuthorizedProgrammeScope)
        )
        or any(getattr(admitted, key) != value for key, value in scope.items())
        or admitted.decision.allowed is not True
        or not fields <= admitted.decision.fields
    ):
        raise SchedulingAuthorizationDeniedError


def personal_programme_task_links(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    current: str,
    urlconf: Any = None,
) -> tuple[PersonalProgrammeTaskLink, ...]:
    """Offer independently admitted same-person tasks without reading their data.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated source viewer, never a selected notice recipient.
    organization_id : UUID
        Already selected tenant owner; no organization discovery is performed.
    edition_id : UUID
        Already selected exact edition; no cross-edition discovery is performed.
    current : str
        Closed editions, proposals, hosting or timetable task to omit from its links.
    urlconf : Any, default=None
        Current request routes, or the ordinary configured root.

    Returns
    -------
    tuple[PersonalProgrammeTaskLink, ...]
        At most three mounted fixed-label links. Denied, unavailable or shadowed
        optional tasks are omitted without asserting an empty owner inventory.

    Notes
    -----
    Default public owner authorization remains sealed. Metadata admission reads
    no answers, identities, relationships, work or release contents and adds no
    sensitive-read audit. A link establishes no hosting, work or attendance purpose.
    The global chooser link requires current verified identity only; its destination
    independently discovers actual own purposes and authorizes every edition.
    Destinations independently authorize and audit their actual complete reads.
    Recheck after rendering and omit moved optional links without repeating a
    command or replacing original bound input. Current production routes remain closed.
    """
    if current not in _TASKS or any(
        type(value) is not UUID or not value.int
        for value in (actor_id, organization_id, edition_id)
    ):
        return ()
    links = []
    for code, (label, name) in _TASKS.items():
        if code == current:
            continue
        kwargs = (
            {}
            if code == "editions"
            else {"organization_id": organization_id, "edition_id": edition_id}
        )
        try:
            url = reverse(name, kwargs=kwargs, urlconf=urlconf)
            target = resolve(url, urlconf=urlconf)
            if target.view_name != name or target.kwargs != kwargs:
                continue
            _admit(actor_id, organization_id, edition_id, code)
        except (
            NoReverseMatch,
            Resolver404,
            ApplicationsProgrammeAuthorizationDeniedError,
            ProgrammeAuthorizationDeniedError,
            SchedulingAuthorizationDeniedError,
            SchedulingUnavailableError,
            DatabaseError,
            ValidationError,
            RuntimeError,
        ):
            continue
        links.append(PersonalProgrammeTaskLink(code, label, url))
    return tuple(links)
