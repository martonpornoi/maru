"""Dormant shared-shell composition over existing independent Programme owners."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.urls import NoReverseMatch, Resolver404, resolve, reverse

from maru.authorization.programme_role_scope_choices import (
    can_enter_programme_role_scopes,
)
from maru.events.adoption import adoption_profile, profile_allows_shell_destination
from maru.events.programme_setup_queries import require_programme_setup_actor
from maru.identity.models import Account
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.workspace_navigation import programme_workspace_links

PROGRAMME_SHELL_KINDS = {
    "applications": "edition.programme-applications",
    "items": "edition.programme-items",
    "timetable": "edition.programme-timetable",
    "release": "edition.programme-release",
    "notices": "edition.programme-notices",
    "operators": "edition.programme-operators",
    "access": "edition.programme-access",
}
_HANDLERS = {
    "applications": (
        "programme-department-tasks",
        "maru.applications.programme_department_task_views",
        "programme_department_tasks",
    ),
    "items": ("programme-items", "maru.programme.workbench_views", "programme_items"),
    "timetable": (
        "programme-timetable-workspace",
        "maru.scheduling.planning_workspace_views",
        "programme_timetable_workspace",
    ),
    "release": (
        "programme-release-workspace",
        "maru.scheduling.release_workspace_views",
        "programme_release_workspace",
    ),
    "notices": (
        "programme-change-notices",
        "maru.scheduling.change_notice_views",
        "programme_change_notices",
    ),
    "operators": (
        "programme-operator-entry",
        "maru.scheduling.operator_entry_views",
        "operator_entry",
    ),
    "access": (
        "programme-access-scopes",
        "maru.authorization.programme_role_scope_views",
        "programme_role_scopes",
    ),
    "setup": (
        "programme-setup",
        "maru.events.programme_setup_views",
        "programme_setup_workspace",
    ),
}


@dataclass(frozen=True, slots=True)
class ProgrammeShellLink:
    """Retain one admitted code-owned navigation task without source content.

    Attributes
    ----------
    code, label, url
        Closed task identity, fixed human label and exact owning local destination.
    shell_kind
        Independently declared future profile destination; never a permission.
    """

    code: str
    label: str
    url: str
    shell_kind: str


def _mounted(code: str, url: str, values: dict[str, UUID], urlconf: Any) -> bool:
    name, module, handler = _HANDLERS[code]
    try:
        match = resolve(url, urlconf=urlconf)
    except Resolver404:
        return False
    # Resolve fixed owner handlers lazily: their templates consume this registry.
    return (
        match.view_name == name
        and match.kwargs == values
        and match.func is getattr(import_module(module), handler)
    )


def _access_url(actor: Account, values: dict[str, UUID], urlconf: Any) -> str:
    try:
        url = reverse("programme-access-scopes", kwargs=values, urlconf=urlconf)
        if not _mounted("access", url, values, urlconf):
            return ""
        if can_enter_programme_role_scopes(actor=actor, **values) is not True:
            return ""
    except (
        NoReverseMatch,
        PermissionDenied,
        ValidationError,
        DatabaseError,
        RuntimeError,
    ):
        return ""
    else:
        return url


def programme_shell_links(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    profile_code: str,
    profile_version: int,
    urlconf: Any = None,
) -> tuple[ProgrammeShellLink, ...]:
    """Compose independently admitted mounted tasks for an exact Programme edition.

    Parameters
    ----------
    actor : Account
        Actual authenticated account; each owner rechecks its own current purpose.
    organization_id : UUID
        Trusted candidate owner, never a label-discovery or sibling permission.
    edition_id : UUID
        Exact candidate context; owning policies resolve its persisted scope again.
    profile_code : str
        Profile code from the authorized edition or name-free owner reference.
    profile_version : int
        Exact persisted profile version; existing and unknown profiles add nothing.
    urlconf : Any, default=None
        Current URL configuration; unmounted or shadowed destinations are omitted.

    Returns
    -------
    tuple[ProgrammeShellLink, ...]
        At most seven fixed-label tasks with individually pinned shell kinds.
        No private source inventory, sensitive-read audit or command is invoked.
    """
    if (
        (profile_code, profile_version) != ("programme_operations", 1)
        or type(profile_version) is not int
        or adoption_profile(profile_code, profile_version) is None
        or not isinstance(actor, Account)
        or not actor.is_active
    ):
        return ()
    allowed = frozenset(
        code
        for code, kind in PROGRAMME_SHELL_KINDS.items()
        if profile_allows_shell_destination(profile_code, profile_version, kind)
    )
    values = {"organization_id": organization_id, "edition_id": edition_id}
    result = []
    try:
        owner_links = programme_workspace_links(
            SchedulingReadRequest(actor.id, organization_id, edition_id, uuid4()),
            current="navigation",
            urlconf=urlconf,
            allowed_codes=allowed - {"access"},
        )
    except (PermissionDenied, ValidationError, DatabaseError, RuntimeError):
        owner_links = ()
    for link in owner_links:
        if link.code not in allowed or link.code == "access":
            continue
        try:
            # Scheduling already resolved the canonical series for its two routes.
            expected = dict(values)
            target = resolve(link.url, urlconf=urlconf)
            if link.code in {"timetable", "release"}:
                series = target.kwargs.get("series_id")
                if not isinstance(series, UUID) or not series.int:
                    continue
                expected["series_id"] = series
            if not _mounted(link.code, link.url, expected, urlconf):
                continue
        except (Resolver404, RuntimeError):
            continue
        result.append(
            ProgrammeShellLink(
                link.code, link.label, link.url, PROGRAMME_SHELL_KINDS[link.code]
            )
        )
    if "access" in allowed and (url := _access_url(actor, values, urlconf)):
        result.append(
            ProgrammeShellLink(
                "access",
                "Programme access requests",
                url,
                PROGRAMME_SHELL_KINDS["access"],
            )
        )
    return tuple(result)


def programme_setup_navigation_url(*, actor: Account, urlconf: Any = None) -> str:
    """Offer optional platform setup only under its real exact-profile admission.

    Parameters
    ----------
    actor : Account
        Actual current platform principal, independently checked by Identity.
    urlconf : Any, default=None
        Current URL configuration; a name or admin catch-all is not a mounted task.

    Returns
    -------
    str
        Fixed setup URL, or empty for absent profile, route, authority or dependency.
        This does not create foundations, operational roles or a profile activation.
    """
    if adoption_profile("programme_operations", 1) is None:
        return ""
    try:
        url = reverse("programme-setup", urlconf=urlconf)
        if not _mounted("setup", url, {}, urlconf):
            return ""
        require_programme_setup_actor(actor)
    except (
        NoReverseMatch,
        PermissionDenied,
        ValidationError,
        DatabaseError,
        RuntimeError,
    ):
        return ""
    else:
        return url
