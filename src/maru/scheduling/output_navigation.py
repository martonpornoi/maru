"""Closed same-viewer Programme output continuations, never permission or discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.workforce.operator_links import operator_staffing_adopted

from .adoption import SCHEDULING_CONTINUITY_ADAPTER, SCHEDULING_PUBLIC_RELEASE_ADAPTER
from .authorization import (
    VIEW_CHANGE_NOTICES,
    VIEW_CHANGE_SELF,
    SchedulingAuthorizationDeniedError,
    authorize_scheduling_scope,
)
from .command_support import SchedulingUnavailableError
from .continuity_protocol import ContinuityScope, _scope_document
from .operator_entry_queries import can_enter_operator_tasks
from .operator_scope import (
    OperatorReadRequest,
    OperatorScopeKind,
    authorize_operator_scope,
)
from .personal_navigation import personal_programme_task_links
from .personal_output_queries import authorize_personal_timetable_scope
from .planning_queries import SchedulingReadRequest

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProgrammeOutputLink:
    """Fixed-label same-audience continuation with current independent admission.

    Attributes
    ----------
    code, label
        Closed destination and code-owned human label, without protected source text.
    url
        Resolved current-configuration route with only fixed explicit layer parameters.
    """

    code: str
    label: str
    url: str


_DESTINATIONS = {
    "public": {
        "timetable": (
            "Complete public Programme timetable",
            "programme-public-timetable",
        ),
        "now": ("Complete public Programme now and next", "programme-public-now"),
    },
    "exact_person": {
        "timetable": (
            "My current hosting and work timetable",
            "my-hosting-work-timetable",
        ),
        "now": ("My Programme now and next", "my-programme-now"),
        "notices": ("My reviewed Programme change notices", "my-programme-changes"),
    },
    "private_operator": {
        "entry": ("Choose another operator scope", "programme-operator-entry"),
        "timetable": ("Current operator run sheet", "programme-operator-run-sheet"),
        "now": ("Operator now and next", "programme-operator-now"),
        "notices": ("Programme change notices", "programme-change-notices"),
    },
}


def _adapter(scope: ContinuityScope, adapter: str) -> None:
    profile = edition_adoption_profile_reference(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, adapter
    ):
        raise SchedulingAuthorizationDeniedError


def _operator(scope: ContinuityScope) -> None:
    if scope.actor_id is None or scope.target_id is None:
        raise SchedulingAuthorizationDeniedError
    request = OperatorReadRequest(
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        uuid4(),
        OperatorScopeKind(scope.kind),
        scope.target_id,
    )
    fields = {
        "scheduling.view_operator_output": frozenset({"released_geometry"}),
        "programme.view_operator_copy": frozenset({"reviewed_copy"}),
        "venues.view_operator_wayfinding": frozenset({"scope_links", "wayfinding"}),
    }
    delivery = frozenset(scope.layers) - {"staffing"}
    if delivery:
        fields["programme.view_operator_delivery"] = delivery
    if "staffing" in scope.layers:
        fields["workforce.view_operator_staffing"] = frozenset(
            {"scope_links", "work_instructions", "coverage"}
        )
    elif request.kind is OperatorScopeKind.DEPARTMENT and operator_staffing_adopted(
        request
    ):
        fields["workforce.view_operator_staffing"] = frozenset({"scope_links"})
    for capability, required in fields.items():
        authorize_operator_scope(request, capability=capability, fields=required)


def _admit(scope: ContinuityScope, destination: str) -> None:
    if destination == "entry":
        if (
            scope.actor_id is None
            or can_enter_operator_tasks(
                SchedulingReadRequest(
                    scope.actor_id, scope.organization_id, scope.edition_id, uuid4()
                )
            )
            is not True
        ):
            raise SchedulingAuthorizationDeniedError
        return
    if destination == "notices":
        if scope.actor_id is None:
            raise SchedulingAuthorizationDeniedError
        personal = scope.audience == "exact_person"
        authorize_scheduling_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            capability_code=VIEW_CHANGE_SELF if personal else VIEW_CHANGE_NOTICES,
            requested_fields=frozenset(
                {"own_change_notices" if personal else "change_notices"}
            ),
        )
        return
    if destination == "now":
        _adapter(scope, SCHEDULING_CONTINUITY_ADAPTER)
    if scope.audience == "public":
        _adapter(scope, SCHEDULING_PUBLIC_RELEASE_ADAPTER)
    elif scope.audience == "exact_person":
        if scope.actor_id is None:
            raise SchedulingAuthorizationDeniedError
        authorize_personal_timetable_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
        )
    else:
        _operator(scope)


def programme_output_links(
    scope: ContinuityScope, *, current: str, urlconf: Any = None
) -> tuple[ProgrammeOutputLink, ...]:
    """Offer only mounted independently admitted tasks for the actual source viewer.

    Parameters
    ----------
    scope : ContinuityScope
        Trusted same-person or same-operator purpose, never a selected other account.
    current : str
        Closed source task: timetable, now, notices or entry; omit its own link.
    urlconf : Any, default=None
        Current request URL configuration or the ordinary configured root.

    Returns
    -------
    tuple[ProgrammeOutputLink, ...]
        At most four fixed-label links; public scopes have at most two and
        operator scopes at most three. Personal output may additionally connect
        to independently admitted proposal and hosting tasks.
        Denied, unavailable, unmounted or shadowed
        destinations are omitted without a partial-output completeness claim.

    Notes
    -----
    No owner inventory, body, history or recipient output is read. Output-to-output
    links retain explicit layers and exact scope; notices are a separate workflow.
    Public now/next is explicitly complete, not a silently retained day/room filter.
    Repeat after rendering and omit changed optional links without redispatching
    writers or signers. Every destination independently authorizes its actual data.
    """
    if current not in {"timetable", "now", "notices", "entry"}:
        return ()
    try:
        _scope_document(scope)
    except ValueError:
        return ()
    links = []
    for code, (label, name) in _DESTINATIONS[scope.audience].items():
        if code == current or (current == "entry" and code == "notices"):
            continue
        kwargs: dict[str, UUID | str] = {
            "organization_id": scope.organization_id,
            "edition_id": scope.edition_id,
        }
        parameters = {}
        if scope.audience == "private_operator" and code not in {"notices", "entry"}:
            if scope.target_id is None:
                return ()
            kwargs.update(scope_kind=scope.kind, target_id=scope.target_id)
            parameters = dict.fromkeys(scope.layers, "1")
        try:
            url = reverse(name, kwargs=kwargs, urlconf=urlconf)
            target = resolve(url, urlconf=urlconf)
            if target.view_name != name or target.kwargs != kwargs:
                continue
            _admit(scope, code)
        except (
            NoReverseMatch,
            Resolver404,
            SchedulingAuthorizationDeniedError,
            SchedulingUnavailableError,
            DatabaseError,
            ValidationError,
            RuntimeError,
        ):
            continue
        links.append(
            ProgrammeOutputLink(
                code, label, url + ("?" + urlencode(parameters) if parameters else "")
            )
        )
    if scope.audience == "exact_person" and scope.actor_id is not None:
        links.extend(
            ProgrammeOutputLink(link.code, link.label, link.url)
            for link in personal_programme_task_links(
                actor_id=scope.actor_id,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                current="timetable",
                urlconf=urlconf,
            )
        )
    return tuple(links)
