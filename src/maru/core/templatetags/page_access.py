"""One stable template API for computed page access explanations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, cast
from uuid import UUID

from django import template
from django.db import DatabaseError
from django.http import HttpRequest

from maru.authorization.access import AccessIntent
from maru.authorization.models import ScopedResourceBinding
from maru.authorization.page_access import (
    PageAccessSpec,
    PageAccessSummary,
    build_page_access_summary,
    fixed_page_access,
    scoped_page_access,
    unavailable_page_access,
)
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_resource_target,
)
from maru.events.admin_context import selected_admin_edition
from maru.events.models import EventEdition
from maru.organizations.models import ConventionSeries, Organization

register = template.Library()

_PLATFORM_ROUTES = frozenset(
    {
        "baseline-admin-home",
        "baseline-create-organization",
        "platform-account-inventory",
        "platform-account-invite",
        "platform-account-invitation-detail",
    }
)
_REPRESENTATION_ROUTES = frozenset(
    {
        "organization-representation",
        "my-representation-invitations",
    }
)
_SAFEGUARDING_ROUTES = frozenset(
    {
        "application-review-workspace",
        "guardian-consent",
    }
)
_SECURITY_APPS = frozenset({"audit", "identity", "privacyops"})


class _DepartmentContextObject(Protocol):
    organization_id: UUID
    edition_id: UUID
    id: UUID


class _PositionContextObject(_DepartmentContextObject, Protocol):
    department_id: UUID


class _ResponsibleDepartmentContextObject(_DepartmentContextObject, Protocol):
    responsible_department_id: UUID


def _route_name(request: HttpRequest) -> str:
    match = request.resolver_match
    return str(match.url_name or "") if match is not None else ""


def _fixed_spec(  # noqa: PLR0911
    *,
    request: HttpRequest,
    context: template.Context,
    route_name: str,
) -> PageAccessSpec | None:
    if route_name in _PLATFORM_ROUTES:
        return fixed_page_access(
            policy="platform",
            scope_label="Maru platform administration",
            explanation=(
                "This platform-wide record is governed by active platform "
                "administrator authority. Convention roles and attendee status "
                "never grant access here."
            ),
            audience_labels=("Active platform administrators",),
        )
    if route_name in _REPRESENTATION_ROUTES:
        return fixed_page_access(
            policy="representation",
            scope_label="Executive Board representation",
            explanation=(
                "Controller access is created only by the accepted, term-bound "
                "representation appointment workflow. Generic role sharing is "
                "intentionally unavailable here."
            ),
            audience_labels=("Exact accepted controllers", "Platform oversight"),
        )
    if route_name in _SAFEGUARDING_ROUTES:
        return fixed_page_access(
            policy="safeguarding",
            scope_label="Restricted review relationship",
            explanation=(
                "This page is limited by its exact reviewer, adult-content, or "
                "safeguarding policy. Access must be configured in that governed "
                "workflow, not through a page sharing list."
            ),
            audience_labels=("Exact named reviewers", "Exact immutable reviewer role"),
        )
    personal = bool(context.get("maru_personal_surface"))
    if personal or route_name.startswith("my-") or request.path.startswith("/my/"):
        return fixed_page_access(
            policy="self",
            scope_label="Your own Maru records",
            explanation=(
                "This page is available through your signed-in own-record "
                "relationship. It cannot be shared with a staff role or another "
                "person from this page."
            ),
            audience_labels=("You",),
        )
    if not request.path.startswith("/admin/"):
        if route_name == "paid-attendee-directory":
            return fixed_page_access(
                policy="attendee_audience",
                scope_label="Edition attendee directory",
                explanation=(
                    "Directory visibility is an audience policy: only minimized, "
                    "approved fields from confirmed attendees who currently "
                    "consent are published. Withdrawal removes publication "
                    "immediately."
                ),
                audience_labels=("Confirmed attendees", "Consented public fields"),
            )
        return fixed_page_access(
            policy="public",
            scope_label="Public or participant workflow",
            explanation=(
                "Access follows this workflow's published, signed-in, or "
                "own-record policy. Staff role assignments are not an audience "
                "control for this page."
            ),
            audience_labels=("Published audience", "Eligible signed-in participant"),
        )
    opts = context.get("opts")
    app_label = str(getattr(opts, "app_label", ""))
    if app_label in _SECURITY_APPS:
        return fixed_page_access(
            policy="security",
            scope_label="Protected specialist records",
            explanation=(
                "This page follows a fixed security, privacy, or case-work "
                "capability with audited reads. Access cannot be widened through "
                "a contextual sharing action."
            ),
            audience_labels=("Authorized security or case workers",),
        )
    return None


def _intents(route_name: str, app_label: str) -> tuple[AccessIntent, ...]:
    candidates: Iterable[tuple[str, str]]
    if "structure" in route_name or app_label == "workforce":
        candidates = (
            ("workforce.view_structure", "View this organization structure"),
            ("workforce.manage_structure", "Change this organization structure"),
        )
    elif "registration" in route_name or app_label == "registration":
        candidates = (
            ("registration.manage_configuration", "Manage registration setup"),
            ("registration.view_service_summary", "View attendee service records"),
        )
    elif "application" in route_name or app_label == "applications":
        candidates = (
            ("applications.manage_definitions", "Manage application definitions"),
            ("applications.review", "Review assigned applications"),
        )
    elif "charity" in route_name or app_label == "charities":
        candidates = (
            ("charities.view_review_queue", "View charity review work"),
            ("charities.review_selection", "Review this charity selection"),
        )
    elif "venue" in route_name or app_label == "venues":
        candidates = (
            ("venues.view_workspace", "View venue planning"),
            ("venues.manage_space_schedule", "Manage this space schedule"),
        )
    elif "catalog" in route_name or app_label == "catalog":
        candidates = (
            ("catalog.view_activity", "View catalog activity"),
            ("catalog.manage", "Manage the edition catalog"),
        )
    elif "edition" in route_name or app_label == "events":
        candidates = (
            ("events.view_basic", "View this edition"),
            ("events.change_profile", "Change this edition"),
        )
    elif "series" in route_name:
        candidates = (
            ("organizations.view_basic", "View this convention series"),
            ("organizations.change_series", "Change this convention series"),
        )
    elif app_label == "authorization":
        candidates = (
            ("authorization.manage_roles", "Manage scoped role assignments"),
            ("authorization.revoke", "Remove scoped authority"),
        )
    else:
        candidates = (
            ("organizations.view_basic", "View this organizer record"),
            ("organizations.change_profile", "Change this organizer record"),
        )
    return tuple(
        AccessIntent(capability_code=code, label=label) for code, label in candidates
    )


def _context_object(context: template.Context) -> object | None:
    for key in (
        "original",
        "department",
        "configuration",
        "registration",
        "catalog",
        "organization",
        "convention_series",
        "edition",
    ):
        value: object | None = context.get(key)
        if value is not None:
            return value
    return None


def _object_scope_values(  # noqa: PLR0911, PLR0912
    value: object | None,
) -> tuple[UUID | None, ...]:
    if value is None:
        return None, None, None, None
    if isinstance(value, Organization):
        return value.id, None, None, None
    if isinstance(value, ConventionSeries):
        return value.organization_id, None, None, None
    if isinstance(value, EventEdition):
        return value.organization_id, value.id, None, None
    if isinstance(value, ScopedResourceBinding):
        return (
            value.organization_id,
            value.edition_id,
            value.department_id,
            value.id,
        )
    model_label = str(getattr(getattr(value, "_meta", None), "label_lower", ""))
    if model_label == "workforce.department":
        department = cast(_DepartmentContextObject, value)
        return department.organization_id, department.edition_id, department.id, None
    if model_label == "workforce.position":
        from maru.authorization.bindings import (  # noqa: PLC0415
            workforce_position_binding_id,
        )

        position = cast(_PositionContextObject, value)
        return (
            position.organization_id,
            position.edition_id,
            position.department_id,
            workforce_position_binding_id(position.id),
        )
    if model_label == "charities.charityselection":
        from maru.charities.bindings import (  # noqa: PLC0415
            charity_selection_binding_id,
        )

        selection = cast(_ResponsibleDepartmentContextObject, value)
        return (
            selection.organization_id,
            selection.edition_id,
            selection.responsible_department_id,
            charity_selection_binding_id(selection.id),
        )
    if model_label == "venues.editionspaceselection":
        from maru.venues.bindings import edition_space_binding_id  # noqa: PLC0415

        selection = cast(_ResponsibleDepartmentContextObject, value)
        return (
            selection.organization_id,
            selection.edition_id,
            selection.responsible_department_id,
            edition_space_binding_id(selection.id),
        )
    organization_id = _uuid_attribute(value, "organization_id")
    edition_id = _uuid_attribute(value, "edition_id")
    department_id = _uuid_attribute(value, "department_id")
    resource_binding_id = _uuid_attribute(value, "resource_binding_id")
    if organization_id is not None:
        return organization_id, edition_id, department_id, resource_binding_id
    for parent_name in ("configuration", "registration", "position", "opportunity"):
        parent: object | None = getattr(value, parent_name, None)
        if parent is not None and parent is not value:
            values = _object_scope_values(parent)
            if values[0] is not None:
                return values
    return None, None, None, None


def _uuid_attribute(value: object, name: str) -> UUID | None:
    attribute: object = getattr(value, name, None)
    return attribute if isinstance(attribute, UUID) else None


def _display_name(value: object | None, fallback: str) -> str:
    name: object = getattr(value, "name", fallback)
    return name if isinstance(name, str) else fallback


def _typed_target(
    *,
    request: HttpRequest,
    context: template.Context,
    organization_id: UUID,
    edition_id: UUID,
) -> ResolvedAuthorizationTarget | None:
    route_name = _route_name(request)
    kwargs = request.resolver_match.kwargs if request.resolver_match else {}
    if route_name == "charity-selection-review-page":
        from maru.charities.bindings import (  # noqa: PLC0415
            charity_selection_binding_id,
        )
        from maru.charities.models import CharitySelection  # noqa: PLC0415

        charity_selection_id = cast(UUID | str, kwargs.get("selection_id"))
        charity_selection = (
            CharitySelection.objects.filter(
                pk=charity_selection_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .only("responsible_department_id")
            .first()
        )
        if charity_selection is None:
            return None
        return resolve_resource_target(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=charity_selection.responsible_department_id,
            resource_binding_id=charity_selection_binding_id(charity_selection.id),
        )
    if route_name == "venue-space-schedule-page":
        from maru.venues.bindings import edition_space_binding_id  # noqa: PLC0415
        from maru.venues.models import EditionSpaceSelection  # noqa: PLC0415

        space_selection_id = cast(UUID | str, kwargs.get("space_selection_id"))
        space_selection = (
            EditionSpaceSelection.objects.filter(
                pk=space_selection_id,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .only("responsible_department_id")
            .first()
        )
        if space_selection is None:
            return None
        return resolve_resource_target(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=space_selection.responsible_department_id,
            resource_binding_id=edition_space_binding_id(space_selection.id),
        )
    department: object | None = context.get("department")
    department_id = (
        _uuid_attribute(department, "id") if department is not None else None
    )
    if department_id is None and "department_id" in kwargs:
        route_department_id: object = kwargs["department_id"]
        if isinstance(route_department_id, UUID):
            department_id = route_department_id
    if isinstance(department_id, UUID):
        return resolve_department_target(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
        )
    return None


def _target_and_label(
    request: HttpRequest,
    context: template.Context,
) -> tuple[ResolvedAuthorizationTarget | None, str]:
    organization: object | None = context.get("organization")
    edition: object | None = context.get("edition")
    object_value = _context_object(context)
    organization_id, edition_id, department_id, resource_binding_id = (
        _object_scope_values(object_value)
    )
    if isinstance(organization, Organization):
        organization_id = organization.id
    if isinstance(edition, EventEdition):
        organization_id = edition.organization_id
        edition_id = edition.id
    if organization_id is None and request.resolver_match is not None:
        kwargs = request.resolver_match.kwargs
        organization_id = kwargs.get("organization_id")
        edition_id = kwargs.get("edition_id", edition_id)
    if organization_id is None:
        selected = selected_admin_edition(request)
        if selected is not None:
            organization_id, edition_id, edition = (
                selected.organization_id,
                selected.id,
                selected,
            )
    if not isinstance(organization_id, UUID):
        return None, "Record-specific authority"
    if isinstance(edition_id, UUID):
        typed = _typed_target(
            request=request,
            context=context,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        if typed is not None:
            if typed.resource_binding_id is not None:
                return typed, f"{_display_name(edition, 'Edition')} / typed resource"
            return typed, (
                f"{_display_name(edition, 'Edition')} / "
                f"{_display_name(context.get('department'), 'Department')}"
            )
        if isinstance(resource_binding_id, UUID) and isinstance(department_id, UUID):
            target = resolve_resource_target(
                organization_id=organization_id,
                edition_id=edition_id,
                department_id=department_id,
                resource_binding_id=resource_binding_id,
            )
        elif isinstance(department_id, UUID):
            target = resolve_department_target(
                organization_id=organization_id,
                edition_id=edition_id,
                department_id=department_id,
            )
        else:
            target = resolve_edition_target(
                organization_id=organization_id,
                edition_id=edition_id,
            )
        return target, _display_name(edition, "Selected edition")
    target = resolve_organization_target(organization_id=organization_id)
    return target, _display_name(organization, "Organizer")


def _inferred_spec(
    request: HttpRequest,
    context: template.Context,
) -> PageAccessSpec:
    route_name = _route_name(request)
    fixed = _fixed_spec(request=request, context=context, route_name=route_name)
    if fixed is not None:
        return fixed
    target, scope_label = _target_and_label(request, context)
    if target is None:
        return fixed_page_access(
            policy="fixed",
            scope_label=scope_label,
            explanation=(
                "This record type is governed by its code-owned specialist "
                "policy. Choose an exact organizer record before changing "
                "underlying scoped assignments."
            ),
        )
    opts = context.get("opts")
    return scoped_page_access(
        target=target,
        scope_label=scope_label,
        intents=_intents(route_name, str(getattr(opts, "app_label", ""))),
    )


@register.simple_tag(takes_context=True)
def maru_page_access(context: template.Context) -> PageAccessSummary:
    """Resolve the shared component from an explicit spec or page context."""

    if context.get("maru_suppress_page_access_component"):
        return unavailable_page_access()
    request = context.get("request")
    if not isinstance(request, HttpRequest):
        return unavailable_page_access()
    explicit = context.get("maru_page_access_spec")
    try:
        spec = (
            explicit
            if isinstance(explicit, PageAccessSpec)
            else _inferred_spec(
                request,
                context,
            )
        )
        return build_page_access_summary(principal=request.user, spec=spec)
    except (AttributeError, DatabaseError, TypeError, ValueError):
        return build_page_access_summary(
            principal=request.user,
            spec=fixed_page_access(
                policy="fixed",
                scope_label="Access explanation unavailable",
                explanation=(
                    "Maru could not safely resolve the exact persisted scope for "
                    "this explanation. No access-management action is shown."
                ),
            ),
        )
