"""One permission-filtered navigation registry for Maru's authenticated shells."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from django.urls import reverse

from maru.authorization.policy import (
    decide,
    resolve_edition_target,
)
from maru.events.admin_context import (
    admin_edition_options,
    admin_organization_navigation,
    admin_shell_access,
    selected_admin_profile_allows_app,
)
from maru.events.adoption import profile_allows_shell_destination
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.identity.navigation_preferences import navigation_pin_codes
from maru.organizations.models import Organization

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from django.http import HttpRequest

_SUPPORTED_PIN_NAMESPACES = frozenset(
    {"my", "work", "platform", "organization", "series", "edition", "record"}
)
_DESTINATION_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,159}$")
_PROFILE_PAIR_LENGTH = 2
_SECTION_ORDER = (
    "Pinned",
    "Convention work",
    "Convention tools",
    "Organizations",
    "Platform",
    "Account",
    "Actions",
    "Specialist records",
    "Personal",
    "Work",
)


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """Describe one authorized destination in the shared navigation registry.

    Attributes
    ----------
    code
        The stable destination code used for pins and registry lookup.
    label
        The human-readable label shown to authorized readers.
    url
        The already-resolved local URL for the destination.
    section
        The presentation section used for deterministic grouping.
    context_label
        The optional organization or edition label disambiguating the item.
    description
        The human-readable description shown to authorized readers.
    keywords
        Additional task language accepted by navigation search.
    kind
        The closed destination kind, such as ``destination`` or ``action``.
    profile_destination_kind
        The optional manifest kind required when an edition scopes this item.
    current
        Whether this destination represents the current request path.
    pinnable
        Whether the destination may be stored as a navigation pin.
    pinned
        Whether the account has pinned this destination.
    """

    code: str
    label: str
    url: str
    section: str
    context_label: str = ""
    description: str = ""
    keywords: tuple[str, ...] = ()
    kind: str = "destination"
    profile_destination_kind: str = ""
    current: bool = False
    pinnable: bool = True
    pinned: bool = False

    @property
    def search_text(self) -> str:
        """Return normalized searchable text for this navigation item.

        Returns
        -------
        str
            The non-empty searchable fields joined in their relevance order.

        Examples
        --------
        >>> item = NavigationItem(
        ...     code="work.volunteers",
        ...     label="Volunteers",
        ...     url="/admin/workforce/",
        ...     section="Convention work",
        ...     keywords=("staff", "helpers"),
        ... )
        >>> item.search_text
        'Volunteers staff helpers Convention work'
        """
        return " ".join(
            part
            for part in (
                self.label,
                self.description,
                *self.keywords,
                self.context_label,
                self.section,
            )
            if part
        )


def destination_code_is_supported(destination_code: str) -> bool:
    """Validate preference syntax without resolving or disclosing a resource.

    Parameters
    ----------
    destination_code : str
        The stable destination code from the relevant closed catalog.

    Returns
    -------
    bool
        `True` when Validate preference syntax without resolving or disclosing a
        resource; otherwise `False`.
    """
    return bool(
        _DESTINATION_CODE_PATTERN.fullmatch(destination_code)
        and destination_code.partition(".")[0] in _SUPPORTED_PIN_NAMESPACES
    )


def _route_is(request: HttpRequest, *names: str) -> bool:
    match = request.resolver_match
    return bool(match and match.url_name in names)


def _scoped_route_is(request: HttpRequest, name: str, *args: object) -> bool:
    """Match both the route and its exact tenant-owned path parameters.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    name : str
        The human-readable name to normalize or persist.
    *args : object
        Positional arguments forwarded to the framework implementation.

    Returns
    -------
    bool
        `True` when Match both the route and its exact tenant-owned path
        parameters; otherwise `False`.
    """
    return _route_is(request, name) and request.path == reverse(name, args=args)


def _workspace_item(
    request: HttpRequest,
    *,
    code: str,
    label: str,
    view: str,
    description: str,
    keywords: tuple[str, ...],
    section: str = "Convention work",
) -> NavigationItem:
    url = reverse("management-console")
    if view != "today":
        url = f"{url}?view={view}"
    requested_view = request.GET.get("view", "today")
    return NavigationItem(
        code=code,
        label=label,
        url=url,
        section=section,
        description=description,
        keywords=keywords,
        profile_destination_kind=code,
        current=_route_is(request, "management-console") and requested_view == view,
    )


def _profile_filtered_items(
    *,
    items: Iterable[NavigationItem],
    edition: EventEdition,
) -> list[NavigationItem]:
    """Remove edition destinations absent from the exact profile manifest.

    Parameters
    ----------
    items : Iterable[NavigationItem]
        Already-authorized navigation candidates.
    edition : EventEdition
        Edition whose immutable profile code and version govern discovery.

    Returns
    -------
    list[NavigationItem]
        Non-edition items plus explicitly pinned edition destinations. Unknown
        exact profiles disclose no profile-scoped destination.
    """
    return [
        item
        for item in items
        if not item.profile_destination_kind
        or profile_allows_shell_destination(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
            item.profile_destination_kind,
        )
    ]


def _personal_profile_pairs(
    page_context: Mapping[str, Any],
) -> tuple[tuple[str, int], ...]:
    """Return exact profiles from editions already disclosed by a personal page.

    Parameters
    ----------
    page_context : Mapping[str, Any]
        Flattened trusted template context for the current personal surface.

    Returns
    -------
    tuple[tuple[str, int], ...]
        Distinct exact profile pairs. Invalid or unsupported context values do
        not create a permissive fallback.
    """
    pairs: set[tuple[str, int]] = set()

    def add_edition(value: object) -> None:
        if not isinstance(value, EventEdition):
            return
        pairs.add(
            (
                value.adoption_profile_code,
                value.adoption_profile_version,
            )
        )

    add_edition(page_context.get("edition"))
    personal_editions = page_context.get("maru_personal_editions", ())
    if isinstance(personal_editions, (list, tuple)):
        for edition in personal_editions:
            add_edition(edition)
    explicit_pairs = page_context.get("maru_personal_profile_pairs", ())
    if isinstance(explicit_pairs, (list, tuple)):
        for pair in explicit_pairs:
            if (
                isinstance(pair, (list, tuple))
                and len(pair) == _PROFILE_PAIR_LENGTH
                and isinstance(pair[0], str)
                and isinstance(pair[1], int)
            ):
                pairs.add((pair[0], pair[1]))
    return tuple(sorted(pairs))


def _personal_items(
    request: HttpRequest,
    *,
    profile_pairs: tuple[tuple[str, int], ...],
) -> list[NavigationItem]:
    items = [
        NavigationItem(
            code="my.home",
            label="My Maru",
            url=reverse("my-maru-home"),
            section="Personal",
            description="Your personal Maru home, profile, and convention activity.",
            keywords=("account", "profile", "dashboard"),
            current=_route_is(request, "my-maru-home"),
        ),
        NavigationItem(
            code="my.registrations",
            label="Registration & tickets",
            url=reverse("public-registration-index"),
            section="Personal",
            description="Register for a convention and manage admission tickets.",
            keywords=("attendee", "admission", "payment", "booking"),
            profile_destination_kind="my.registrations",
            current=_route_is(
                request,
                "public-registration-index",
                "public-registration-form",
                "public-registration-profile",
                "edit-attendee-profile",
                "public-registration-tier-replacement",
                "public-registration-hosted-payment",
            ),
        ),
        NavigationItem(
            code="my.catalog",
            label="Shop & orders",
            url=reverse("my-catalog-index"),
            section="Personal",
            description="Browse convention products and review your orders.",
            keywords=("store", "merchandise", "merch", "purchase"),
            profile_destination_kind="my.catalog",
            current=_route_is(
                request,
                "my-catalog-index",
                "my-catalog",
                "my-catalog-orders",
                "my-catalog-order",
                "my-catalog-checkout",
                "my-catalog-hosted-payment",
                "my-catalog-demo-payment",
            ),
        ),
        NavigationItem(
            code="my.applications",
            label="My applications",
            url=reverse("my-application-index"),
            section="Personal",
            description="Complete and review your submitted convention forms.",
            keywords=("volunteer", "staff", "helper", "programme", "forms"),
            profile_destination_kind="my.applications",
            current=_route_is(
                request,
                "my-application-index",
                "my-applications",
                "my-application-detail",
                "application-submission-start",
                "application-answer-append",
                "application-submit",
            ),
        ),
        NavigationItem(
            code="my.workforce",
            label="My Workforce",
            url=reverse("my-workforce-assignments"),
            section="Work",
            description="Review your Positions, Availability, and Shifts.",
            keywords=("staff", "volunteer", "assignments", "rota", "crew"),
            profile_destination_kind="my.workforce",
            current=_route_is(
                request,
                "my-workforce-assignments",
                "my-workforce-availability",
                "save-my-workforce-availability",
                "withdraw-my-workforce-availability",
                "my-workforce-shifts",
                "claim-my-workforce-shift",
                "withdraw-my-workforce-shift",
            ),
        ),
        NavigationItem(
            code="my.schedule",
            label="My schedule",
            url=reverse("my-maru-schedule-index"),
            section="Personal",
            description="See your published convention timetable and locations.",
            keywords=("programme", "calendar", "events", "agenda"),
            profile_destination_kind="my.schedule",
            current=_route_is(
                request,
                "my-maru-schedule-index",
                "my-maru-venue-schedule",
            ),
        ),
        NavigationItem(
            code="my.equipment_offers",
            label="Equipment offers",
            url=reverse("my-logistics-offer-index"),
            section="Personal",
            description="Offer equipment for convention logistics use.",
            keywords=("assets", "inventory", "loan", "gear"),
            profile_destination_kind="my.equipment-offers",
            current=_route_is(
                request,
                "my-logistics-offer-index",
                "my-logistics-offers",
            ),
        ),
        NavigationItem(
            code="my.governance-invitations",
            label="Governance invitations",
            url=reverse("my-representation-invitations"),
            section="Personal",
            description="Review invitations to represent an organization.",
            keywords=("board", "controller", "leadership", "authority"),
            current=_route_is(request, "my-representation-invitations"),
        ),
    ]
    items = [
        item
        for item in items
        if not item.profile_destination_kind
        or any(
            profile_allows_shell_destination(
                profile_code,
                profile_version,
                item.profile_destination_kind,
            )
            for profile_code, profile_version in profile_pairs
        )
    ]
    if _route_is(
        request,
        "my-workforce-assignments",
        "my-workforce-availability",
        "save-my-workforce-availability",
        "withdraw-my-workforce-availability",
        "my-workforce-shifts",
        "claim-my-workforce-shift",
        "withdraw-my-workforce-shift",
    ):
        focused_codes = {"my.home", "my.workforce"}
        return [item for item in items if item.code in focused_codes]
    return items


def _management_items(
    request: HttpRequest,
    *,
    page_context: Mapping[str, Any],
) -> list[NavigationItem]:
    shell_access = admin_shell_access(request)
    if not shell_access["workspace_available"]:
        return []
    items = [
        _workspace_item(
            request,
            code="work.today",
            label="Today",
            view="today",
            description="See current convention status, assigned work, and warnings.",
            keywords=("home", "dashboard", "tasks", "deadlines", "actions"),
        ),
        _workspace_item(
            request,
            code="work.people",
            label="People",
            view="people",
            description="Find attendees and the people working on the convention.",
            keywords=(
                "users",
                "accounts",
                "staff",
                "volunteers",
                "crew",
                "team",
            ),
        ),
        _workspace_item(
            request,
            code="work.workforce",
            label="Workforce",
            view="workforce",
            description=(
                "Review Departments, Positions, assignments, Availability, and Shifts."
            ),
            keywords=(
                "staff",
                "volunteers",
                "teams",
                "departments",
                "positions",
                "assignments",
                "availability",
                "shifts",
                "rota",
            ),
        ),
        _workspace_item(
            request,
            code="work.attendee-service",
            label="Registration desk",
            view="commerce",
            description="Find and help attendees from registration through arrival.",
            keywords=(
                "registration",
                "attendees",
                "tickets",
                "payments",
                "check in",
                "support",
            ),
        ),
        _workspace_item(
            request,
            code="work.reports",
            label="Reports & badges",
            view="reports",
            description="Review attendance and prepare minimized badge exports.",
            keywords=("analytics", "exports", "participants", "labels"),
        ),
        _workspace_item(
            request,
            code="work.setup",
            label="Setup guide",
            view="setup",
            description="Continue the safe, ordered setup of this convention.",
            keywords=(
                "onboarding",
                "checklist",
                "board",
                "governance",
                "departments",
            ),
        ),
        _workspace_item(
            request,
            code="work.security",
            label="Security history",
            view="security",
            description="Review important security events for your account.",
            keywords=("audit", "login", "sign in", "sessions"),
            section="Account",
        ),
    ]
    routed_edition = page_context.get("edition")
    selected = (
        routed_edition
        if isinstance(routed_edition, EventEdition)
        else admin_edition_options(request).get("selected")
    )
    if isinstance(selected, EventEdition):
        return _profile_filtered_items(items=items, edition=selected)
    return items


def _selected_edition_items(request: HttpRequest) -> list[NavigationItem]:
    options = admin_edition_options(request)
    selected = options.get("selected")
    if not isinstance(selected, EventEdition):
        return []
    edition = selected
    context_label = (
        f"{edition.organization.name} / {edition.series.name} / {edition.name}"
    )
    items: list[NavigationItem] = []
    if options.get("selected_can_view_structure"):
        items.append(
            NavigationItem(
                code=f"edition.{edition.id}.structure",
                label="Organization structure",
                url=reverse(
                    "organization-structure",
                    args=(
                        edition.organization.slug,
                        edition.series.slug,
                        edition.slug,
                    ),
                ),
                section="Convention",
                context_label=context_label,
                profile_destination_kind="edition.structure",
                current=_scoped_route_is(
                    request,
                    "organization-structure",
                    edition.organization.slug,
                    edition.series.slug,
                    edition.slug,
                ),
            )
        )
    if options.get("selected_can_manage_registration"):
        items.append(
            NavigationItem(
                code=f"edition.{edition.id}.registration",
                label="Registration",
                url=reverse(
                    "registration-setup",
                    args=(
                        edition.organization.slug,
                        edition.series.slug,
                        edition.slug,
                    ),
                ),
                section="Convention",
                context_label=context_label,
                profile_destination_kind="edition.registration",
                current=_scoped_route_is(
                    request,
                    "registration-setup",
                    edition.organization.slug,
                    edition.series.slug,
                    edition.slug,
                ),
            )
        )
    actor = request.user
    edition_target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    if isinstance(actor, Account) and edition_target is not None:
        if decide(
            principal=actor,
            capability_code="applications.manage_definitions",
            resource=edition_target,
        ).allowed:
            items.append(
                NavigationItem(
                    code=f"edition.{edition.id}.application-studio",
                    label="Application studio",
                    url=reverse(
                        "application-definition-workspace",
                        args=(edition.organization_id, edition.id),
                    ),
                    section="Convention",
                    context_label=context_label,
                    profile_destination_kind="edition.application-studio",
                    current=_scoped_route_is(
                        request,
                        "application-definition-workspace",
                        edition.organization_id,
                        edition.id,
                    ),
                )
            )
        if decide(
            principal=actor,
            capability_code="applications.review",
            resource=edition_target,
        ).allowed:
            items.append(
                NavigationItem(
                    code=f"edition.{edition.id}.application-review",
                    label="Application review",
                    url=reverse(
                        "application-review-workspace",
                        args=(edition.organization_id, edition.id),
                    ),
                    section="Convention",
                    context_label=context_label,
                    profile_destination_kind="edition.application-review",
                    current=_scoped_route_is(
                        request,
                        "application-review-workspace",
                        edition.organization_id,
                        edition.id,
                    ),
                )
            )
        if decide(
            principal=actor,
            capability_code="registration.manage_exceptions",
            resource=edition_target,
        ).allowed:
            items.append(
                NavigationItem(
                    code=f"edition.{edition.id}.registration-commerce",
                    label="Capacity & waitlist",
                    url=reverse(
                        "registration-commerce-workspace",
                        args=(
                            edition.organization.slug,
                            edition.series.slug,
                            edition.slug,
                        ),
                    ),
                    section="Convention",
                    context_label=context_label,
                    profile_destination_kind="edition.registration-commerce",
                    current=_route_is(
                        request,
                        "registration-commerce-workspace",
                        "registration-commerce-adjust-overall",
                        "registration-commerce-adjust-product",
                        "registration-commerce-offer-batch",
                    ),
                )
            )
        if decide(
            principal=actor,
            capability_code="catalog.view_activity",
            resource=edition_target,
        ).allowed:
            catalog_url = reverse(
                "catalog-staff-workspace",
                args=(
                    edition.organization.slug,
                    edition.series.slug,
                    edition.slug,
                ),
            )
            items.append(
                NavigationItem(
                    code=f"edition.{edition.id}.catalog",
                    label="Catalog commerce",
                    url=catalog_url,
                    section="Convention",
                    context_label=context_label,
                    profile_destination_kind="edition.catalog",
                    current=(
                        _scoped_route_is(
                            request,
                            "catalog-staff-workspace",
                            edition.organization.slug,
                            edition.series.slug,
                            edition.slug,
                        )
                        or (
                            _route_is(request, "catalog-stock-adjust-page")
                            and request.path.startswith(catalog_url)
                        )
                    ),
                )
            )
        if decide(
            principal=actor,
            capability_code="venues.view_workspace",
            resource=edition_target,
        ).allowed:
            items.append(
                NavigationItem(
                    code=f"edition.{edition.id}.venues",
                    label="Venues and spaces",
                    url=reverse(
                        "venue-workspace",
                        args=(
                            edition.organization.slug,
                            edition.series.slug,
                            edition.slug,
                        ),
                    ),
                    section="Convention",
                    context_label=context_label,
                    profile_destination_kind="edition.venues",
                    current=_route_is(
                        request,
                        "venue-workspace",
                        "venue-space-schedule-page",
                    ),
                )
            )
        if decide(
            principal=actor,
            capability_code="logistics.view_workspace",
            resource=edition_target,
        ).allowed:
            items.append(
                NavigationItem(
                    code=f"edition.{edition.id}.logistics",
                    label="Logistics",
                    url=reverse(
                        "logistics-workspace",
                        args=(
                            edition.organization.slug,
                            edition.series.slug,
                            edition.slug,
                        ),
                    ),
                    section="Convention",
                    context_label=context_label,
                    profile_destination_kind="edition.logistics",
                    current=_route_is(
                        request,
                        "logistics-workspace",
                        "logistics-manifest-detail-page",
                        "logistics-manifest-receipt",
                        "logistics-staff-object-command",
                        "logistics-staff-command",
                        "logistics-stage-receiving-page",
                        "logistics-restricted-contact-request",
                        "logistics-restricted-contact-result",
                    ),
                )
            )
    if (
        isinstance(actor, Account)
        and decide(
            principal=actor,
            capability_code="charities.view_review_queue",
            resource=resolve_edition_target(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            ),
        ).allowed
    ):
        items.append(
            NavigationItem(
                code=f"edition.{edition.id}.charities",
                label="Charity partners",
                url=reverse(
                    "charity-workspace",
                    args=(
                        edition.organization.slug,
                        edition.series.slug,
                        edition.slug,
                    ),
                ),
                section="Convention",
                context_label=context_label,
                profile_destination_kind="edition.charities",
                current=_route_is(
                    request,
                    "charity-workspace",
                    "charity-selection-review-page",
                ),
            )
        )
    return _profile_filtered_items(items=items, edition=edition)


def _scoped_organization_items(request: HttpRequest) -> list[NavigationItem]:
    items: list[NavigationItem] = []
    for projection in admin_organization_navigation(request):
        projected_organization = projection["organization"]
        if not isinstance(projected_organization, Organization):
            continue
        organization = projected_organization
        context_label = organization.name
        if projection["can_view_organization"]:
            items.extend(
                (
                    NavigationItem(
                        code=f"organization.{organization.id}.record",
                        label="Organization record",
                        url=reverse(
                            "baseline-organization-record",
                            args=(organization.slug,),
                        ),
                        section="Organizations",
                        context_label=context_label,
                        current=_scoped_route_is(
                            request,
                            "baseline-organization-record",
                            organization.slug,
                        ),
                    ),
                    NavigationItem(
                        code=f"organization.{organization.id}.series",
                        label="Convention series",
                        url=(
                            reverse(
                                "baseline-organization-record",
                                args=(organization.slug,),
                            )
                            + "#convention-series-title"
                        ),
                        section="Organizations",
                        context_label=context_label,
                    ),
                )
            )
        if (
            projection["can_view_organization"]
            or projection["can_manage_representation"]
        ):
            items.append(
                NavigationItem(
                    code=f"organization.{organization.id}.representation",
                    label="Representation & access",
                    url=reverse(
                        "organization-representation",
                        args=(organization.slug,),
                    ),
                    section="Organizations",
                    context_label=context_label,
                    current=_scoped_route_is(
                        request,
                        "organization-representation",
                        organization.slug,
                    ),
                )
            )
        if projection["can_create_series"] and organization.lifecycle != "closed":
            items.append(
                NavigationItem(
                    code=f"organization.{organization.id}.series-add",
                    label="Add convention series",
                    url=reverse(
                        "baseline-create-convention-series",
                        args=(organization.slug,),
                    ),
                    section="Organizations",
                    context_label=context_label,
                    current=_scoped_route_is(
                        request,
                        "baseline-create-convention-series",
                        organization.slug,
                    ),
                )
            )
    return items


def _page_context_items(
    request: HttpRequest,
    page_context: Mapping[str, Any],
) -> list[NavigationItem]:
    """Flatten already-authorized route context without re-querying tenant names.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    page_context : Mapping[str, Any]
        The page context mapping to validate or transform.

    Returns
    -------
    list[NavigationItem]
        The matching page context items records in deterministic order.
    """
    organization = page_context.get("organization")
    series = page_context.get("convention_series")
    edition = page_context.get("edition")
    if organization is None:
        return []
    organization_label = str(organization.name)
    items: list[NavigationItem] = []
    if page_context.get("baseline_can_view_organization"):
        items.extend(
            (
                NavigationItem(
                    code=f"organization.{organization.id}.record",
                    label="Organization record",
                    url=reverse(
                        "baseline-organization-record",
                        args=(organization.slug,),
                    ),
                    section="Organizations",
                    context_label=organization_label,
                    current=_scoped_route_is(
                        request,
                        "baseline-organization-record",
                        organization.slug,
                    ),
                ),
                NavigationItem(
                    code=f"organization.{organization.id}.series",
                    label="Convention series",
                    url=(
                        reverse(
                            "baseline-organization-record",
                            args=(organization.slug,),
                        )
                        + "#convention-series-title"
                    ),
                    section="Organizations",
                    context_label=organization_label,
                ),
            )
        )
    if page_context.get("baseline_can_view_organization") or page_context.get(
        "baseline_can_manage_representation"
    ):
        items.append(
            NavigationItem(
                code=f"organization.{organization.id}.representation",
                label="Representation & access",
                url=reverse("organization-representation", args=(organization.slug,)),
                section="Organizations",
                context_label=organization_label,
                current=_scoped_route_is(
                    request,
                    "organization-representation",
                    organization.slug,
                ),
            )
        )
    if (
        page_context.get("baseline_can_create_series")
        and organization.lifecycle != "closed"
    ):
        items.append(
            NavigationItem(
                code=f"organization.{organization.id}.series-add",
                label="Add convention series",
                url=reverse(
                    "baseline-create-convention-series",
                    args=(organization.slug,),
                ),
                section="Organizations",
                context_label=organization_label,
                current=_scoped_route_is(
                    request,
                    "baseline-create-convention-series",
                    organization.slug,
                ),
            )
        )
    if series is None:
        return items
    series_label = f"{organization.name} / {series.name}"
    if page_context.get("baseline_can_view_organization"):
        items.extend(
            (
                NavigationItem(
                    code=f"series.{series.id}.record",
                    label="Series record",
                    url=reverse(
                        "baseline-convention-series-record",
                        args=(organization.slug, series.slug),
                    ),
                    section="Organizations",
                    context_label=series_label,
                    current=_scoped_route_is(
                        request,
                        "baseline-convention-series-record",
                        organization.slug,
                        series.slug,
                    ),
                ),
                NavigationItem(
                    code=f"series.{series.id}.editions",
                    label="Convention editions",
                    url=(
                        reverse(
                            "baseline-convention-series-record",
                            args=(organization.slug, series.slug),
                        )
                        + "#event-editions-title"
                    ),
                    section="Organizations",
                    context_label=series_label,
                ),
            )
        )
    if (
        page_context.get("baseline_can_create_edition")
        and organization.lifecycle != "closed"
        and series.is_active
    ):
        items.append(
            NavigationItem(
                code=f"series.{series.id}.edition-add",
                label="Add convention edition",
                url=reverse(
                    "baseline-create-event-edition",
                    args=(organization.slug, series.slug),
                ),
                section="Organizations",
                context_label=series_label,
                current=_scoped_route_is(
                    request,
                    "baseline-create-event-edition",
                    organization.slug,
                    series.slug,
                ),
            )
        )
    if edition is None:
        return items
    edition_label = f"{organization.name} / {series.name} / {edition.name}"
    if page_context.get("baseline_can_view_edition"):
        items.append(
            NavigationItem(
                code=f"edition.{edition.id}.overview",
                label="Edition overview",
                url=reverse(
                    "baseline-event-edition-record",
                    args=(organization.slug, series.slug, edition.slug),
                ),
                section="Convention",
                context_label=edition_label,
                profile_destination_kind="edition.overview",
                current=_scoped_route_is(
                    request,
                    "baseline-event-edition-record",
                    organization.slug,
                    series.slug,
                    edition.slug,
                ),
            )
        )
    if page_context.get("baseline_can_view_structure"):
        items.append(
            NavigationItem(
                code=f"edition.{edition.id}.structure",
                label="Organization structure",
                url=reverse(
                    "organization-structure",
                    args=(organization.slug, series.slug, edition.slug),
                ),
                section="Convention",
                context_label=edition_label,
                profile_destination_kind="edition.structure",
                current=bool(
                    page_context.get("baseline_structure_navigation_current")
                    or _route_is(request, "organization-structure")
                ),
            )
        )
    if page_context.get("baseline_can_manage_registration"):
        items.append(
            NavigationItem(
                code=f"edition.{edition.id}.registration",
                label="Registration",
                url=reverse(
                    "registration-setup",
                    args=(organization.slug, series.slug, edition.slug),
                ),
                section="Convention",
                context_label=edition_label,
                profile_destination_kind="edition.registration",
                current=bool(
                    page_context.get("baseline_registration_navigation_current")
                    or _route_is(request, "registration-setup")
                ),
            )
        )
    if isinstance(edition, EventEdition):
        return _profile_filtered_items(items=items, edition=edition)
    return items


def _platform_items(request: HttpRequest) -> list[NavigationItem]:
    actor = request.user
    if not isinstance(actor, Account) or not actor.is_platform_administrator:
        return []
    return [
        NavigationItem(
            code="platform.organizations",
            label="Organizations",
            url=reverse("baseline-admin-home"),
            section="Platform",
            current=_route_is(request, "baseline-admin-home"),
        ),
        NavigationItem(
            code="platform.workforce-setup",
            label="Set up Workforce",
            url=reverse("workforce-adoption-setup"),
            section="Platform",
            description=(
                "Create or reuse the minimum foundation for volunteer operations."
            ),
            keywords=("volunteers", "staff", "progressive adoption", "onboarding"),
            current=_route_is(request, "workforce-adoption-setup"),
        ),
        NavigationItem(
            code="platform.organizations-add",
            label="Add organization",
            url=reverse("baseline-create-organization"),
            section="Platform",
            current=_route_is(request, "baseline-create-organization"),
        ),
        NavigationItem(
            code="platform.accounts",
            label="User accounts",
            url=reverse("platform-account-inventory"),
            section="Platform",
            current=_route_is(
                request,
                "platform-account-inventory",
                "platform-account-invitation-detail",
                "platform-account-invitation-reissue",
                "platform-account-invitation-revoke",
            ),
        ),
        NavigationItem(
            code="platform.accounts-invite",
            label="Invite account",
            url=reverse("platform-account-invite"),
            section="Platform",
            current=_route_is(request, "platform-account-invite"),
        ),
    ]


def _specialist_items(
    request: HttpRequest,
    available_apps: Iterable[Mapping[str, Any]],
) -> list[NavigationItem]:
    items: list[NavigationItem] = []
    for app in available_apps:
        app_label = str(app.get("app_label", ""))
        if not selected_admin_profile_allows_app(
            request,
            app_label=app_label,
        ):
            continue
        app_name = str(app.get("name", ""))
        for model in app.get("models", ()):
            url = model.get("admin_url")
            object_name = str(model.get("object_name", "")).lower()
            if not url or not app_label or not object_name:
                continue
            items.append(
                NavigationItem(
                    code=f"record.{app_label}.{object_name}",
                    label=str(model.get("name", object_name)),
                    url=str(url),
                    section="Specialist records",
                    context_label=app_name,
                    description=(
                        f"Inspect the technical {model.get('name', object_name)} "
                        "record list."
                    ),
                    keywords=(
                        "technical",
                        "advanced",
                        "database",
                        "records",
                        app_label,
                        object_name,
                    ),
                    kind="specialist",
                    current=str(url) in request.path,
                )
            )
    return items


def _decorate_navigation_item(item: NavigationItem) -> NavigationItem:
    """Attach task language without changing route or authorization behavior.

    Parameters
    ----------
    item : NavigationItem
        The domain object being validated, rendered, or persisted.

    Returns
    -------
    NavigationItem
        The resolved NavigationItem for decorate navigation item.
    """
    code = item.code
    if code == "platform.organizations":
        return replace(
            item,
            description="Find and continue setting up organizer organizations.",
            keywords=("organizers", "conventions", "tenants", "foundation"),
        )
    if code == "platform.accounts":
        return replace(
            item,
            description="Find login identities and review invitation state.",
            keywords=(
                "users",
                "people",
                "staff",
                "volunteers",
                "email",
                "login",
                "credentials",
            ),
        )

    action_metadata: tuple[str, tuple[str, ...]] | None = None
    if code == "platform.organizations-add":
        action_metadata = (
            "Create a new organizer organization.",
            ("new", "organizer", "convention", "tenant"),
        )
    elif code == "platform.accounts-invite":
        action_metadata = (
            "Invite a person to create a recipient-owned Maru account.",
            ("new", "user", "staff", "volunteer", "email", "onboarding"),
        )
    elif code.endswith(".series-add"):
        action_metadata = (
            "Create a convention series for this organization.",
            ("new", "convention", "event"),
        )
    elif code.endswith(".edition-add"):
        action_metadata = (
            "Create the next convention edition in this series.",
            ("new", "event", "year", "occurrence"),
        )
    if action_metadata is not None:
        description, keywords = action_metadata
        return replace(
            item,
            section="Actions",
            description=description,
            keywords=keywords,
            kind="action",
            pinnable=False,
        )

    metadata_by_suffix: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        (
            ".representation",
            "Review the Executive Board and delegated organization authority.",
            ("board", "controllers", "governance", "leadership", "roles"),
        ),
        (
            ".application-studio",
            "Build and publish application forms for this convention.",
            ("volunteers", "staff", "forms", "intake", "submissions"),
        ),
        (
            ".application-review",
            "Review submitted applications assigned to you.",
            ("volunteers", "staff", "forms", "decisions", "submissions"),
        ),
        (
            ".registration-commerce",
            "Manage admission capacity, offers, and registration exceptions.",
            ("tickets", "payments", "waitlist", "attendees", "sales"),
        ),
        (
            ".registration",
            "Configure the attendee registration form and admission products.",
            ("tickets", "attendees", "questions", "profile", "forms"),
        ),
        (
            ".catalog",
            "Manage convention products, stock, orders, and fulfilment activity.",
            ("shop", "merchandise", "sales", "inventory", "orders"),
        ),
        (
            ".venues",
            "Manage selected venues, spaces, and physical occupancy.",
            ("rooms", "buildings", "locations", "schedule"),
        ),
        (
            ".logistics",
            "Manage equipment, storage, custody, and movement.",
            ("inventory", "assets", "keys", "transport", "warehouse"),
        ),
        (
            ".charities",
            "Review and publish convention charity partners.",
            ("fundraising", "beneficiary", "donations", "review"),
        ),
        (
            ".structure",
            "Review departments, positions, and the convention team structure.",
            ("staff", "volunteers", "team", "departments", "org chart"),
        ),
        (
            ".overview",
            "Review this convention edition and its current setup state.",
            ("event", "year", "status", "workspace"),
        ),
        (
            ".editions",
            "Review the convention editions in this series.",
            ("events", "years", "occurrences"),
        ),
        (
            ".series",
            "Review the recurring convention series for this organization.",
            ("events", "editions", "convention"),
        ),
        (
            ".record",
            "Review this organizer or convention record.",
            ("details", "settings", "profile"),
        ),
    )
    for suffix, description, keywords in metadata_by_suffix:
        if code.endswith(suffix):
            section = (
                "Convention tools" if code.startswith("edition.") else item.section
            )
            return replace(
                item,
                section=section,
                description=description,
                keywords=keywords,
                kind="record" if suffix in {".record", ".overview"} else item.kind,
            )
    return item


def _deduplicate(items: Iterable[NavigationItem]) -> list[NavigationItem]:
    by_code: dict[str, NavigationItem] = {}
    for raw_item in items:
        item = _decorate_navigation_item(raw_item)
        existing = by_code.get(item.code)
        if existing is None or (item.current and not existing.current):
            by_code[item.code] = item
    return list(by_code.values())


def project_shell_navigation(
    request: HttpRequest,
    *,
    available_apps: Iterable[Mapping[str, Any]] = (),
    page_context: Mapping[str, Any],
    personal_surface: bool,
) -> dict[str, object]:
    """Build one live, permission-filtered menu and reauthorize every pin.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request and authenticated principal context.
    available_apps : Iterable[Mapping[str, Any]], default=()
        The available apps evaluated while project shell navigation.
    page_context : Mapping[str, Any]
        The page context mapping to validate or transform.
    personal_surface : bool
        The personal surface evaluated while project shell navigation.

    Returns
    -------
    dict[str, object]
        A mapping containing the resolved project shell navigation data.
    """
    actor = request.user
    if (
        not isinstance(actor, Account)
        or not actor.is_authenticated
        or not actor.is_active
    ):
        return {"groups": (), "count": 0}

    personal_items = _personal_items(
        request,
        profile_pairs=_personal_profile_pairs(page_context),
    )
    management_items = _management_items(request, page_context=page_context)
    items = _deduplicate(
        (
            *personal_items,
            *management_items,
            *_selected_edition_items(request),
            *_scoped_organization_items(request),
            *_page_context_items(request, page_context),
            *_platform_items(request),
            *_specialist_items(request, available_apps),
        )
    )
    personal_codes = {item.code for item in personal_items}
    surface_items = [
        item
        for item in items
        if (
            (personal_surface and item.code in personal_codes)
            or (not personal_surface and item.code not in personal_codes)
        )
    ]
    eligible_by_code = {item.code: item for item in surface_items}
    pin_codes = navigation_pin_codes(account=actor)
    pinned_items = [
        replace(eligible_by_code[code], section="Pinned", pinned=True)
        for code in pin_codes
        if code in eligible_by_code
    ]
    pinned_code_set = {item.code for item in pinned_items}

    if personal_surface:
        visible_items = [
            item for item in surface_items if item.code not in pinned_code_set
        ]
        if admin_shell_access(request)["workspace_available"] or actor.is_staff:
            administration_label = (
                "Administration" if actor.is_staff else "Convention workspace"
            )
            administration_description = (
                "Open organizer and platform administration tools."
                if actor.is_staff
                else "Open the convention workspaces this account may use."
            )
            visible_items.append(
                NavigationItem(
                    code="work.administration",
                    label=administration_label,
                    url=reverse("admin:index"),
                    section="Work",
                    description=administration_description,
                    keywords=("staff", "organizer", "management"),
                    pinnable=False,
                )
            )
    else:
        visible_items = [
            item for item in surface_items if item.code not in pinned_code_set
        ]

    grouped: dict[str, list[NavigationItem]] = {}
    if pinned_items:
        grouped["Pinned"] = pinned_items
    for item in visible_items:
        grouped.setdefault(item.section, []).append(item)
    ordered_labels = sorted(
        grouped,
        key=lambda label: (
            _SECTION_ORDER.index(label) if label in _SECTION_ORDER else 999,
            label.casefold(),
        ),
    )
    groups: tuple[dict[str, object], ...] = tuple(
        {
            "label": label,
            "items": tuple(grouped[label]),
            "collapsed": label
            in {
                "Account",
                "Actions",
                "Convention tools",
                "Organizations",
                "Platform",
                "Specialist records",
            },
            "search_only": label == "Actions",
            "current": any(item.current for item in grouped[label]),
        }
        for label in ordered_labels
        if grouped[label]
    )
    visible_count = sum(
        len(grouped[label]) for label in ordered_labels if grouped[label]
    )
    return {"groups": groups, "count": visible_count}
