"""Purpose-bound links between dormant Programme owner workspaces, never grants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import DatabaseError
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.queries import resolve_edition_series_identity
from maru.programme.authorization import (
    PROGRAMME_VIEW_PRIVATE,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from maru.venues.timetable_queries import TIMETABLE_SPACE_FIELDS

from .authorization import (
    VIEW_CHANGE_NOTICES,
    VIEW_PLANNING,
    SchedulingAuthorizationDeniedError,
    authorize_scheduling_scope,
)
from .planning_queries import PLANNING_FIELDS, SchedulingReadRequest
from .release_workspace import TASK_LABELS, authorize_release_task

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProgrammeWorkspaceLink:
    """One resolved fixed-label task, without source content or authority.

    Attributes
    ----------
    code
        Closed owning task, not an arbitrary capability or redirect target.
    label
        Code-owned human task name, never a protected record label.
    url
        Reversed and resolved exact-scope destination in the current URL configuration.
    """

    code: str
    label: str
    url: str


_TASKS = {
    "items": ("Programme items", "programme-items"),
    "timetable": ("Timetable planning", "programme-timetable-workspace"),
    "release": ("Release timetable", "programme-release-workspace"),
    "notices": ("Programme change notices", "programme-change-notices"),
}
_ITEM_FIELDS = frozenset({"item_summaries", "working_information"})


def authorize_timetable_workspace(scope: SchedulingReadRequest) -> None:
    """Admit all base owner fields without loading any item or room labels.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Trusted authenticated person and exact tenant/edition attribution.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If Scheduling planning or the independent Venue field ceiling fails.

    Notes
    -----
    Actual owner queries repeat their own admission and required sensitive-read audit.
    This metadata-only check does not certify source availability or grant mutation.
    Programme's independent private item-label denial propagates from its owner.
    """
    authorize_scheduling_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=VIEW_PLANNING,
        requested_fields=PLANNING_FIELDS,
    )
    _authorize_items(scope)
    decision = decide_verified_principal_exact_edition(
        principal_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code="venues.view_workspace",
        requested_fields=TIMETABLE_SPACE_FIELDS,
    )
    if (
        not isinstance(decision, PolicyDecision)
        or not decision.allowed
        or not TIMETABLE_SPACE_FIELDS.issubset(decision.fields)
    ):
        raise SchedulingAuthorizationDeniedError


def _authorize_items(scope: SchedulingReadRequest) -> None:
    authorize_programme_scope(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        capability_code=PROGRAMME_VIEW_PRIVATE,
        requested_fields=_ITEM_FIELDS,
    )


def _authorize(scope: SchedulingReadRequest, code: str) -> None:
    if code == "items":
        _authorize_items(scope)
    elif code == "timetable":
        authorize_timetable_workspace(scope)
    elif code == "notices":
        authorize_scheduling_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            capability_code=VIEW_CHANGE_NOTICES,
            requested_fields=frozenset({"change_notices"}),
        )
    else:
        # The chooser needs at least one independently admitted release task,
        # not all release read/write roles and never a fresh private source load.
        for task in TASK_LABELS:
            try:
                authorize_release_task(scope, task)
            except SchedulingAuthorizationDeniedError:
                continue
            return
        raise SchedulingAuthorizationDeniedError


def programme_workspace_links(
    scope: SchedulingReadRequest,
    *,
    current: str,
    series_id: UUID | None = None,
    urlconf: Any = None,
) -> tuple[ProgrammeWorkspaceLink, ...]:
    """Offer independently admitted mounted destinations without reading their data.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Already admitted source-page actor, organization, edition and trace.
    current : str
        Closed current workspace, omitted from its own continuation list.
    series_id : UUID | None, default=None
        Expected canonical parent when the source route already supplies it.
    urlconf : Any, default=None
        Current request URL configuration, or Django's ordinary configured root.

    Returns
    -------
    tuple[ProgrammeWorkspaceLink, ...]
        At most three fixed-label links, or four from the external Shift workspace.
        Denied, unavailable, unmounted or shadowed
        destinations are omitted. Absence makes no source-completeness claim.

    Notes
    -----
    Navigation is optional, including after a completed command. No owner inventory,
    history, release content or directory is loaded, and no sensitive value is placed
    in a query string. Callers must repeat this observation after rendering and omit
    moved links before releasing bytes. Destinations independently authorize again.
    """
    if current not in {*_TASKS, "shifts"}:
        return ()
    links = []
    for code, (label, name) in _TASKS.items():
        if code == current:
            continue
        kwargs: dict[str, UUID] = {
            "organization_id": scope.organization_id,
            "edition_id": scope.edition_id,
        }
        try:
            # Check declaration before any optional authorization/database work.
            # For canonical paths a supplied parent is verified, never trusted.
            if code in {"timetable", "release"}:
                parent = series_id or scope.edition_id  # Shape-only reverse probe.
                reverse(name, kwargs=kwargs | {"series_id": parent}, urlconf=urlconf)
            else:
                reverse(name, kwargs=kwargs, urlconf=urlconf)
            _authorize(scope, code)
            if code in {"timetable", "release"}:
                actual = resolve_edition_series_identity(
                    organization_id=scope.organization_id, edition_id=scope.edition_id
                )
                if actual is None or (series_id is not None and actual != series_id):
                    continue
                kwargs["series_id"] = actual
            url = reverse(name, kwargs=kwargs, urlconf=urlconf)
            target = resolve(url, urlconf=urlconf)
            if target.view_name != name or target.kwargs != kwargs:
                continue
        except (
            NoReverseMatch,
            Resolver404,
            ProgrammeAuthorizationDeniedError,
            SchedulingAuthorizationDeniedError,
            DatabaseError,
            RuntimeError,
        ):
            continue
        links.append(ProgrammeWorkspaceLink(code, label, url))
    return tuple(links)
