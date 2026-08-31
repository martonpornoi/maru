"""Exact-version event-edition adoption manifests and profile boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping


def _freeze_unique(
    values: tuple[str, ...],
    *,
    declaration: str,
) -> frozenset[str]:
    """Freeze one literal declaration without hiding duplicate members.

    Parameters
    ----------
    values : tuple[str, ...]
        Source-order literal members to validate and freeze.
    declaration : str
        Human-readable declaration name used in import-time failures.

    Returns
    -------
    frozenset[str]
        Immutable unique members.

    Raises
    ------
    RuntimeError
        If the source declaration repeats any member.
    """
    frozen = frozenset(values)
    if len(frozen) != len(values):
        raise RuntimeError(f"{declaration} contains duplicate declarations.")
    return frozen


def _build_unique_tuple(
    values: tuple[str, ...],
    *,
    declaration: str,
) -> tuple[str, ...]:
    """Keep an ordered literal declaration after rejecting duplicates.

    Parameters
    ----------
    values : tuple[str, ...]
        Source-order literal members to validate.
    declaration : str
        Human-readable declaration name used in import-time failures.

    Returns
    -------
    tuple[str, ...]
        The validated source tuple unchanged.

    Raises
    ------
    RuntimeError
        If the source declaration repeats any member.
    """
    if len(frozenset(values)) != len(values):
        raise RuntimeError(f"{declaration} contains duplicate declarations.")
    return values


def _build_unique_mapping[Key, Value](
    entries: tuple[tuple[Key, Value], ...],
    *,
    declaration: str,
) -> Mapping[Key, Value]:
    """Build a read-only registry without dictionary-key normalization.

    Parameters
    ----------
    entries : tuple[tuple[Key, Value], ...]
        Source-order key/value declarations.
    declaration : str
        Human-readable declaration name used in import-time failures.

    Returns
    -------
    Mapping[Key, Value]
        Read-only mapping retaining the declared insertion order.

    Raises
    ------
    RuntimeError
        If the source declaration repeats any key.
    """
    keys = tuple(key for key, _value in entries)
    if len(frozenset(keys)) != len(keys):
        raise RuntimeError(f"{declaration} contains duplicate declarations.")
    return MappingProxyType(dict(entries))


class AdoptionProfileCode(StrEnum):
    """Enumerate currently executable event-edition adoption profiles."""

    FULL_CONVENTION = "full_convention"
    WORKFORCE_ONLY = "workforce_only"


FULL_CONVENTION_PROFILE_VERSION = 1
WORKFORCE_ONLY_PROFILE_VERSION = 1
DEFAULT_ADOPTION_PROFILE_VERSION = FULL_CONVENTION_PROFILE_VERSION

_ADOPTION_MODULE_NAMESPACE_DECLARATIONS = (
    "audit",
    "authorization",
    "effects",
    "events",
    "identity",
    "organizations",
    "privacy",
    "accreditation",
    "applications",
    "catalog",
    "charities",
    "communications",
    "logistics",
    "participation",
    "programme",
    "registration",
    "venues",
    "workforce",
)

_FOUNDATION_MODULE_DECLARATIONS = (
    "audit",
    "authorization",
    "effects",
    "events",
    "identity",
    "organizations",
    "privacy",
)

_FULL_CONVENTION_MODULE_DECLARATIONS = (
    "audit",
    "authorization",
    "effects",
    "events",
    "identity",
    "organizations",
    "privacy",
    "accreditation",
    "applications",
    "catalog",
    "charities",
    "communications",
    "logistics",
    "participation",
    "registration",
    "venues",
    "workforce",
)

_WORKFORCE_ONLY_MODULE_DECLARATIONS = (
    "audit",
    "authorization",
    "effects",
    "events",
    "identity",
    "organizations",
    "privacy",
    "workforce",
)

ADOPTION_MODULE_NAMESPACE_CATALOG = _freeze_unique(
    _ADOPTION_MODULE_NAMESPACE_DECLARATIONS,
    declaration="Adoption module namespace catalog",
)

FOUNDATION_MODULES = _freeze_unique(
    _FOUNDATION_MODULE_DECLARATIONS,
    declaration="Foundation modules",
)

FULL_CONVENTION_MODULES = _freeze_unique(
    _FULL_CONVENTION_MODULE_DECLARATIONS,
    declaration="Full-convention modules",
)

WORKFORCE_ONLY_MODULES = _freeze_unique(
    _WORKFORCE_ONLY_MODULE_DECLARATIONS,
    declaration="Workforce-only modules",
)


@dataclass(frozen=True, slots=True, order=True)
class EffectRoute:
    """Pin one versioned domain event to one registered delivery destination.

    Attributes
    ----------
    event_name
        The versioned domain-event name from the Effects registry.
    destination
        The registered handler destination for this event.
    """

    event_name: str
    destination: str


@dataclass(frozen=True, slots=True)
class AdoptionProfile:
    """Describe one immutable, exact-version edition adoption manifest.

    Attributes
    ----------
    code
        The stable profile code stored on an event edition.
    version
        The immutable semantic version stored with the profile code.
    label
        The concise human-readable profile name.
    description
        The plain-language boundary shown during setup and review.
    modules
        The exact module namespaces adopted by this profile version.
    capability_codes
        The exact authorization capability codes admitted at edition scope.
    destination_codes
        The ordered Staff Console destination tokens exposed by context APIs.
    shell_destination_kinds
        Stable, identifier-free shell destination kinds admitted by the profile.
    effect_routes
        Exact versioned event and handler-destination pairs.
    catalog_entries
        Exact code-owned profile-governed catalog entries.
    adapter_codes
        Exact cross-module or purpose-discovery adapters admitted by the profile.
    conflict_source_codes
        Exact conflict sources consulted by profile-wide orchestration.
    root_role_codes
        Reserved accountable root-role codes applicable to this profile.
    primary_module
        The product module anchoring the next action after setup.
    """

    code: AdoptionProfileCode
    version: int
    label: str
    description: str
    modules: frozenset[str]
    capability_codes: frozenset[str]
    destination_codes: tuple[str, ...]
    shell_destination_kinds: frozenset[str]
    effect_routes: frozenset[EffectRoute]
    catalog_entries: frozenset[str]
    adapter_codes: frozenset[str]
    conflict_source_codes: frozenset[str]
    root_role_codes: frozenset[str]
    primary_module: str

    @property
    def key(self) -> tuple[str, int]:
        """Return the exact persisted manifest key.

        Returns
        -------
        tuple[str, int]
            The stable profile code and immutable version.
        """
        return (self.code.value, self.version)


_FULL_CONVENTION_CAPABILITY_CODES = _freeze_unique(
    (
        "accreditation.issue",
        "accreditation.manage_offline",
        "accreditation.revoke",
        "applications.apply_self",
        "applications.manage_definitions",
        "applications.review",
        "applications.review_sensitive",
        "applications.view_self",
        "audit.view_security",
        "authorization.delegate",
        "authorization.grant_direct",
        "authorization.manage_roles",
        "authorization.revoke",
        "catalog.manage",
        "catalog.manage_payments",
        "catalog.manage_stock",
        "catalog.order_self",
        "catalog.view_activity",
        "catalog.view_self",
        "charities.comment_selection",
        "charities.manage_partners",
        "charities.propose_selection",
        "charities.publish_selection",
        "charities.review_selection",
        "charities.view_partners",
        "charities.view_review_queue",
        "charities.view_selection",
        "effects.replay",
        "events.change_profile",
        "events.create",
        "events.transition",
        "events.view_basic",
        "identity.manage_restrictions",
        "logistics.manage_catalog",
        "logistics.manage_manifest",
        "logistics.manage_operations",
        "logistics.offer_self",
        "logistics.reconcile_offline",
        "logistics.review_offers",
        "logistics.view_manifest",
        "logistics.view_restricted_contacts",
        "logistics.view_workspace",
        "organizations.change_profile",
        "organizations.change_series",
        "organizations.create_series",
        "organizations.manage_representation",
        "organizations.view_basic",
        "participation.view_self",
        "participation.view_staff_summary",
        "privacy.manage_requests",
        "registration.check_in",
        "registration.manage_configuration",
        "registration.manage_exceptions",
        "registration.manage_finance",
        "registration.manage_self_profile",
        "registration.moderate_public_profile",
        "registration.register_on_behalf",
        "registration.register_self",
        "registration.update_profile_extensions",
        "registration.view_attendee_reporting",
        "registration.view_payment_summary",
        "registration.view_profile_extensions",
        "registration.view_self",
        "registration.view_self_profile",
        "registration.view_service_summary",
        "venues.manage_accommodation",
        "venues.manage_properties",
        "venues.manage_space_schedule",
        "venues.publish_space_schedule",
        "venues.select_for_edition",
        "venues.view_properties",
        "venues.view_space_schedule",
        "venues.view_workspace",
        "workforce.apply_self",
        "workforce.manage_applications",
        "workforce.manage_assignments",
        "workforce.manage_documents",
        "workforce.manage_self_availability",
        "workforce.manage_self_shifts",
        "workforce.manage_shifts",
        "workforce.manage_structure",
        "workforce.view_availability",
        "workforce.view_self",
        "workforce.view_shifts",
        "workforce.view_structure",
    ),
    declaration="Full-convention capabilities",
)

_WORKFORCE_ONLY_CAPABILITY_CODES = _freeze_unique(
    (
        "audit.view_security",
        "authorization.delegate",
        "authorization.grant_direct",
        "authorization.manage_roles",
        "authorization.revoke",
        "effects.replay",
        "events.change_profile",
        "events.create",
        "events.transition",
        "events.view_basic",
        "identity.manage_restrictions",
        "organizations.change_profile",
        "organizations.change_series",
        "organizations.create_series",
        "organizations.manage_representation",
        "organizations.view_basic",
        "privacy.manage_requests",
        "workforce.apply_self",
        "workforce.manage_applications",
        "workforce.manage_assignments",
        "workforce.manage_documents",
        "workforce.manage_self_availability",
        "workforce.manage_self_shifts",
        "workforce.manage_shifts",
        "workforce.manage_structure",
        "workforce.view_availability",
        "workforce.view_self",
        "workforce.view_shifts",
        "workforce.view_structure",
    ),
    declaration="Workforce-only capabilities",
)

STAFF_CONSOLE_DESTINATION_CATALOG = _freeze_unique(
    (
        "today",
        "my-registration",
        "people",
        "workforce",
        "commerce",
        "reports",
        "setup",
        "security",
    ),
    declaration="Staff Console destination catalog",
)

_FULL_CONVENTION_DESTINATIONS = _build_unique_tuple(
    (
        "today",
        "my-registration",
        "people",
        "workforce",
        "commerce",
        "reports",
        "setup",
        "security",
    ),
    declaration="Full-convention Staff Console destinations",
)

_WORKFORCE_ONLY_DESTINATIONS = _build_unique_tuple(
    ("today", "workforce", "setup", "security"),
    declaration="Workforce-only Staff Console destinations",
)

SHELL_DESTINATION_KIND_CATALOG = _freeze_unique(
    (
        "edition.application-review",
        "edition.application-studio",
        "edition.catalog",
        "edition.charities",
        "edition.logistics",
        "edition.overview",
        "edition.registration",
        "edition.registration-commerce",
        "edition.structure",
        "edition.venues",
        "my.applications",
        "my.catalog",
        "my.equipment-offers",
        "my.registrations",
        "my.schedule",
        "my.workforce",
        "work.attendee-service",
        "work.people",
        "work.reports",
        "work.security",
        "work.setup",
        "work.today",
        "work.workforce",
    ),
    declaration="Shell destination catalog",
)

_FULL_CONVENTION_SHELL_DESTINATION_KINDS = _freeze_unique(
    (
        "edition.application-review",
        "edition.application-studio",
        "edition.catalog",
        "edition.charities",
        "edition.logistics",
        "edition.overview",
        "edition.registration",
        "edition.registration-commerce",
        "edition.structure",
        "edition.venues",
        "my.applications",
        "my.catalog",
        "my.equipment-offers",
        "my.registrations",
        "my.schedule",
        "my.workforce",
        "work.attendee-service",
        "work.people",
        "work.reports",
        "work.security",
        "work.setup",
        "work.today",
        "work.workforce",
    ),
    declaration="Full-convention shell destinations",
)

_WORKFORCE_ONLY_SHELL_DESTINATION_KINDS = _freeze_unique(
    (
        "edition.overview",
        "edition.structure",
        "my.workforce",
        "work.security",
        "work.setup",
        "work.today",
        "work.workforce",
    ),
    declaration="Workforce-only shell destinations",
)

_FULL_INTERNAL_EFFECT_EVENT_NAMES = (
    "applications.definition.changed.v1",
    "applications.submission.changed.v1",
    "authorization.capability.delegated.v1",
    "authorization.capability.direct_granted.v1",
    "authorization.capability.revoked.v1",
    "authorization.role.assigned.v1",
    "authorization.role.revoked.v1",
    "authorization.role_bundle.version_created.v1",
    "catalog.definition.changed.v1",
    "catalog.order.changed.v1",
    "catalog.stock.adjusted.v1",
    "charities.media.changed.v1",
    "charities.partner.changed.v1",
    "charities.selection.changed.v1",
    "events.edition.created.v1",
    "events.edition.details_updated.v1",
    "events.edition.lifecycle_transitioned.v1",
    "identity.account_restriction.applied.v1",
    "logistics.record.changed.v1",
    "organizations.convention_series.created.v1",
    "organizations.convention_series.updated.v1",
    "organizations.representation.changed.v1",
    "registration.admission_tier_replacement.completed.v1",
    "registration.admission_tier_replacement.expired.v1",
    "registration.admission_tier_replacement.reserved.v1",
    "registration.cancelled.v1",
    "registration.capacity.adjusted.v1",
    "registration.checked_in.v1",
    "registration.configuration.activated.v1",
    "registration.configuration.draft_changed.v1",
    "registration.configuration.draft_created.v1",
    "registration.guardian.accepted.v1",
    "registration.payment.deadline_changed.v1",
    "registration.payment.expired.v1",
    "registration.payment.reconciled.v1",
    "registration.payment.waived.v1",
    "registration.profile.media_reviewed.v1",
    "registration.profile.updated.v1",
    "registration.profile_extension.value_appended.v1",
    "registration.submitted.v1",
    "registration.template.published.v1",
    "registration.waitlist.batch_offered.v1",
    "registration.waitlist.offered.v1",
    "system.effect.probe_requested.v1",
    "venues.record.changed.v1",
    "workforce.application.submitted.v1",
    "workforce.document.reviewed.v1",
    "workforce.person_availability.changed.v1",
    "workforce.position_assignment.activated.v1",
    "workforce.position_assignment.ended.v1",
    "workforce.position_assignment.proposed.v1",
    "workforce.position_assignment.rejected.v1",
    "workforce.shift_commitment.changed.v1",
    "workforce.shift_demand.changed.v1",
    "workforce.structure.changed.v1",
)

_FULL_NOTIFICATION_EFFECT_EVENT_NAMES = (
    "identity.account_restriction.applied.v1",
    "registration.cancelled.v1",
    "registration.checked_in.v1",
    "registration.guardian.accepted.v1",
    "registration.payment.deadline_changed.v1",
    "registration.payment.expired.v1",
    "registration.payment.reconciled.v1",
    "registration.payment.waived.v1",
    "registration.submitted.v1",
    "registration.waitlist.offered.v1",
)

_WORKFORCE_ONLY_INTERNAL_EFFECT_EVENT_NAMES = (
    "authorization.capability.delegated.v1",
    "authorization.capability.direct_granted.v1",
    "authorization.capability.revoked.v1",
    "authorization.role.assigned.v1",
    "authorization.role.revoked.v1",
    "authorization.role_bundle.version_created.v1",
    "events.edition.created.v1",
    "events.edition.details_updated.v1",
    "events.edition.lifecycle_transitioned.v1",
    "identity.account_restriction.applied.v1",
    "organizations.convention_series.created.v1",
    "organizations.convention_series.updated.v1",
    "organizations.representation.changed.v1",
    "system.effect.probe_requested.v1",
    "workforce.application.submitted.v1",
    "workforce.document.reviewed.v1",
    "workforce.person_availability.changed.v1",
    "workforce.position_assignment.activated.v1",
    "workforce.position_assignment.ended.v1",
    "workforce.position_assignment.proposed.v1",
    "workforce.position_assignment.rejected.v1",
    "workforce.shift_commitment.changed.v1",
    "workforce.shift_demand.changed.v1",
    "workforce.structure.changed.v1",
)


def _build_effect_routes(
    *,
    internal_event_names: tuple[str, ...],
    notification_event_names: tuple[str, ...] = (),
) -> frozenset[EffectRoute]:
    """Build routes without allowing duplicate literal declarations.

    Parameters
    ----------
    internal_event_names : tuple[str, ...]
        Exact events routed to the built-in internal handler.
    notification_event_names : tuple[str, ...], default=()
        Exact events routed to the notifications handler.

    Returns
    -------
    frozenset[EffectRoute]
        Immutable event/destination pins.

    Raises
    ------
    RuntimeError
        If the literal declarations contain the same route more than once.
    """
    routes = tuple(
        EffectRoute(event_name, destination)
        for destination, event_names in (
            ("internal", internal_event_names),
            ("notifications", notification_event_names),
        )
        for event_name in event_names
    )
    if len(set(routes)) != len(routes):
        raise RuntimeError("Adoption profile effect routes must be unique.")
    return frozenset(routes)


_FULL_CONVENTION_EFFECT_ROUTES = _build_effect_routes(
    internal_event_names=_FULL_INTERNAL_EFFECT_EVENT_NAMES,
    notification_event_names=_FULL_NOTIFICATION_EFFECT_EVENT_NAMES,
)

_WORKFORCE_ONLY_EFFECT_ROUTES = _build_effect_routes(
    internal_event_names=_WORKFORCE_ONLY_INTERNAL_EFFECT_EVENT_NAMES,
)

_FULL_CONVENTION_CATALOG_ENTRIES = _freeze_unique(
    (
        "applications.starter.adult-fursuit-striptease@1",
        "applications.starter.damage-report@1",
        "applications.starter.dj-application@1",
        "applications.starter.feedback@1",
        "applications.starter.fursuit-dance-competition@1",
        "applications.starter.helper-application@1",
        "applications.starter.idea-submission@1",
        "applications.starter.maid-cafe@1",
        "applications.starter.merch-submission@1",
        "applications.starter.registration@1",
        "applications.starter.volunteer-application@1",
        "registration.starter.convention-registration@1",
        "workforce.position-template.workforce-volunteer@1",
        "workforce.structure-template.marucon-reference@1",
    ),
    declaration="Full-convention catalog entries",
)

_WORKFORCE_ONLY_CATALOG_ENTRIES = _freeze_unique(
    (
        "workforce.position-template.workforce-volunteer@1",
        "workforce.structure-template.marucon-reference@1",
    ),
    declaration="Workforce-only catalog entries",
)

_FULL_CONVENTION_ADAPTER_CODES = _freeze_unique(
    (
        "accreditation.identity-restriction-consequence@1",
        "accreditation.offline-check-in-relay@1",
        "applications.eligibility.active_volunteer@1",
        "applications.eligibility.authenticated_person@1",
        "applications.eligibility.confirmed_attendee@1",
        "applications.eligibility.edition_participant@1",
        "applications.eligibility.registered_attendee@1",
        "applications.source.account.display_name@1",
        "applications.source.registration.telegram@1",
        "applications.self@1",
        "applications.target.adult_fursuit_striptease@1",
        "applications.target.damage_report@1",
        "applications.target.dj_set@1",
        "applications.target.feedback@1",
        "applications.target.fursuit_dance_competition@1",
        "applications.target.helper@1",
        "applications.target.idea@1",
        "applications.target.maid_cafe@1",
        "applications.target.merch_submission@1",
        "applications.target.volunteer@1",
        "participation.attendee@1",
        "registration.identity-restriction-consequence@1",
        "venues.attendee-schedule@1",
        "workforce.assignment.participation-required@1",
        "workforce.self@1",
    ),
    declaration="Full-convention adapters",
)

_WORKFORCE_ONLY_ADAPTER_CODES = _freeze_unique(
    (
        "workforce.assignment.participation-excluded@1",
        "workforce.self@1",
    ),
    declaration="Workforce-only adapters",
)

_FULL_CONVENTION_CONFLICT_SOURCE_CODES = _freeze_unique(
    (),
    declaration="Full-convention conflict sources",
)

_WORKFORCE_ONLY_CONFLICT_SOURCE_CODES = _freeze_unique(
    (),
    declaration="Workforce-only conflict sources",
)

_FULL_CONVENTION_ROOT_ROLE_CODES = _freeze_unique(
    ("executive-board",),
    declaration="Full-convention root roles",
)

_WORKFORCE_ONLY_ROOT_ROLE_CODES = _freeze_unique(
    ("executive-board", "maru-operators"),
    declaration="Workforce-only root roles",
)


ADOPTION_PROFILES = _build_unique_mapping(
    (
        (
            (
                AdoptionProfileCode.FULL_CONVENTION.value,
                FULL_CONVENTION_PROFILE_VERSION,
            ),
            AdoptionProfile(
                code=AdoptionProfileCode.FULL_CONVENTION,
                version=FULL_CONVENTION_PROFILE_VERSION,
                label="Full convention",
                description=(
                    "Use Maru as the convention-wide operating platform. This exact "
                    "version pins every currently adopted capability and destination."
                ),
                modules=FULL_CONVENTION_MODULES,
                capability_codes=_FULL_CONVENTION_CAPABILITY_CODES,
                destination_codes=_FULL_CONVENTION_DESTINATIONS,
                shell_destination_kinds=_FULL_CONVENTION_SHELL_DESTINATION_KINDS,
                effect_routes=_FULL_CONVENTION_EFFECT_ROUTES,
                catalog_entries=_FULL_CONVENTION_CATALOG_ENTRIES,
                adapter_codes=_FULL_CONVENTION_ADAPTER_CODES,
                conflict_source_codes=_FULL_CONVENTION_CONFLICT_SOURCE_CODES,
                root_role_codes=_FULL_CONVENTION_ROOT_ROLE_CODES,
                primary_module="events",
            ),
        ),
        (
            (
                AdoptionProfileCode.WORKFORCE_ONLY.value,
                WORKFORCE_ONLY_PROFILE_VERSION,
            ),
            AdoptionProfile(
                code=AdoptionProfileCode.WORKFORCE_ONLY,
                version=WORKFORCE_ONLY_PROFILE_VERSION,
                label="Workforce only",
                description=(
                    "Use Maru for volunteer structure, Positions, assignments, "
                    "Availability, and Shifts without adopting attendee registration, "
                    "payments, or unrelated convention modules."
                ),
                modules=WORKFORCE_ONLY_MODULES,
                capability_codes=_WORKFORCE_ONLY_CAPABILITY_CODES,
                destination_codes=_WORKFORCE_ONLY_DESTINATIONS,
                shell_destination_kinds=_WORKFORCE_ONLY_SHELL_DESTINATION_KINDS,
                effect_routes=_WORKFORCE_ONLY_EFFECT_ROUTES,
                catalog_entries=_WORKFORCE_ONLY_CATALOG_ENTRIES,
                adapter_codes=_WORKFORCE_ONLY_ADAPTER_CODES,
                conflict_source_codes=_WORKFORCE_ONLY_CONFLICT_SOURCE_CODES,
                root_role_codes=_WORKFORCE_ONLY_ROOT_ROLE_CODES,
                primary_module="workforce",
            ),
        ),
    ),
    declaration="Adoption profile registry keys",
)

SELECTABLE_ADOPTION_PROFILE_KEYS = _build_unique_mapping(
    (
        (
            AdoptionProfileCode.FULL_CONVENTION,
            (
                AdoptionProfileCode.FULL_CONVENTION.value,
                FULL_CONVENTION_PROFILE_VERSION,
            ),
        ),
        (
            AdoptionProfileCode.WORKFORCE_ONLY,
            (
                AdoptionProfileCode.WORKFORCE_ONLY.value,
                WORKFORCE_ONLY_PROFILE_VERSION,
            ),
        ),
    ),
    declaration="Selectable adoption profile keys",
)

PERSISTED_ADOPTION_PROFILE_CHOICES = tuple(
    {
        profile.code.value: profile.label for profile in ADOPTION_PROFILES.values()
    }.items()
)

SELECTABLE_ADOPTION_PROFILE_CHOICES = tuple(
    (code.value, ADOPTION_PROFILES[key].label)
    for code, key in SELECTABLE_ADOPTION_PROFILE_KEYS.items()
)


def _validate_manifest(profile: AdoptionProfile) -> None:
    """Reject an internally inconsistent code-owned adoption manifest.

    Parameters
    ----------
    profile : AdoptionProfile
        Exact immutable manifest to validate during module import.

    Raises
    ------
    RuntimeError
        If the manifest identity, modules, catalogs, or routes are inconsistent.
    """
    if (
        isinstance(profile.version, bool)
        or not isinstance(profile.version, int)
        or profile.version < 1
        or profile.primary_module not in profile.modules
    ):
        raise RuntimeError("Adoption profile identity and modules must be valid.")
    if not profile.capability_codes or not profile.destination_codes:
        raise RuntimeError("Adoption profiles require capabilities and destinations.")
    if len(set(profile.destination_codes)) != len(profile.destination_codes):
        raise RuntimeError("Adoption profile destinations must be unique.")
    if not frozenset(profile.destination_codes) <= STAFF_CONSOLE_DESTINATION_CATALOG:
        raise RuntimeError(
            "Adoption profile Staff Console destinations must resolve in the "
            "server-owned catalog."
        )
    if not profile.shell_destination_kinds <= SHELL_DESTINATION_KIND_CATALOG:
        raise RuntimeError(
            "Adoption profile shell destinations must resolve in the governed catalog."
        )
    if any(
        capability.partition(".")[0] not in profile.modules
        for capability in profile.capability_codes
    ):
        raise RuntimeError(
            "Adoption profile capabilities must belong to adopted modules."
        )
    if any(
        entry.partition(".")[0] not in profile.modules
        for entry in (
            *profile.catalog_entries,
            *profile.adapter_codes,
            *profile.conflict_source_codes,
        )
    ):
        raise RuntimeError("Adoption profile catalogs must belong to adopted modules.")
    if any(
        route.event_name.partition(".")[0] not in profile.modules | {"system"}
        or not route.destination
        for route in profile.effect_routes
    ):
        raise RuntimeError(
            "Adoption profile effect routes must be explicit and adopted."
        )


for _manifest_key, _manifest in ADOPTION_PROFILES.items():
    if _manifest_key != _manifest.key:
        raise RuntimeError("Adoption profile registry keys must match their manifests.")
    _validate_manifest(_manifest)


def adoption_profile(code: str, version: int) -> AdoptionProfile | None:
    """Return the manifest for one exact persisted profile pair.

    Parameters
    ----------
    code : str
        The persisted adoption-profile code.
    version : int
        The persisted immutable profile version.

    Returns
    -------
    AdoptionProfile | None
        The exact manifest, or ``None`` for an unsupported pair.
    """
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        return None
    try:
        normalized = AdoptionProfileCode(code)
    except ValueError:
        return None
    return ADOPTION_PROFILES.get((normalized.value, version))


def selectable_adoption_profile(code: str) -> AdoptionProfile | None:
    """Return the exact manifest attached to one supported setup choice.

    Parameters
    ----------
    code : str
        The submitted setup-choice code.

    Returns
    -------
    AdoptionProfile | None
        The explicitly selected exact manifest, or ``None`` for an unknown code.
    """
    try:
        normalized = AdoptionProfileCode(code)
    except ValueError:
        return None
    key = SELECTABLE_ADOPTION_PROFILE_KEYS.get(normalized)
    return ADOPTION_PROFILES.get(key) if key is not None else None


def profile_adopts_module(
    profile_code: str,
    profile_version: int,
    module_code: str,
) -> bool:
    """Return whether an exact manifest adopts one module namespace.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    module_code : str
        Stable Django module namespace to test.

    Returns
    -------
    bool
        ``True`` only when the exact known manifest pins the module.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile is not None and module_code in profile.modules


def profile_allows_capability(
    profile_code: str,
    profile_version: int,
    capability_code: str,
) -> bool:
    """Return whether an exact manifest pins one capability code.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    capability_code : str
        Exact code-owned authorization capability.

    Returns
    -------
    bool
        ``True`` only when the exact known manifest pins the capability.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile is not None and capability_code in profile.capability_codes


def profile_allows_capabilities(
    profile_code: str,
    profile_version: int,
    capability_codes: Collection[str],
) -> bool:
    """Return whether a non-empty capability set is wholly pinned.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    capability_codes : Collection[str]
        Complete capability set requested by an edition-scoped role.

    Returns
    -------
    bool
        ``True`` only when every requested capability is explicitly pinned.
    """
    profile = adoption_profile(profile_code, profile_version)
    return bool(
        profile is not None
        and capability_codes
        and set(capability_codes) <= profile.capability_codes
    )


def profile_destination_codes(
    profile_code: str,
    profile_version: int,
) -> tuple[str, ...]:
    """Return ordered Staff Console destinations for an exact manifest.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.

    Returns
    -------
    tuple[str, ...]
        Exact ordered destination codes, or an empty tuple when unsupported.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile.destination_codes if profile is not None else ()


def profile_allows_destination(
    profile_code: str,
    profile_version: int,
    destination_code: str,
) -> bool:
    """Return whether an exact manifest pins one Staff Console destination.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    destination_code : str
        Stable Staff Console destination token.

    Returns
    -------
    bool
        ``True`` only when the exact known manifest pins the destination.
    """
    return destination_code in profile_destination_codes(profile_code, profile_version)


def profile_allows_shell_destination(
    profile_code: str,
    profile_version: int,
    destination_kind: str,
) -> bool:
    """Return whether an exact manifest pins one shell destination kind.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    destination_kind : str
        Identifier-free shell destination kind.

    Returns
    -------
    bool
        ``True`` only when the exact known manifest pins the destination kind.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile is not None and destination_kind in profile.shell_destination_kinds


def profile_allows_effect(
    profile_code: str,
    profile_version: int,
    event_name: str,
    destination: str,
) -> bool:
    """Return whether an exact manifest pins one event delivery route.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    event_name : str
        Exact versioned domain-event name.
    destination : str
        Registered handler destination.

    Returns
    -------
    bool
        ``True`` only when the exact event/destination pair is pinned.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile is not None and EffectRoute(event_name, destination) in (
        profile.effect_routes
    )


def profile_allows_catalog_entry(
    profile_code: str,
    profile_version: int,
    entry_code: str,
) -> bool:
    """Return whether an exact manifest pins one code-owned catalog entry.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    entry_code : str
        Exact versioned catalog-entry code.

    Returns
    -------
    bool
        ``True`` only when the exact known manifest pins the entry.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile is not None and entry_code in profile.catalog_entries


def profile_allows_adapter(
    profile_code: str,
    profile_version: int,
    adapter_code: str,
) -> bool:
    """Return whether an exact manifest pins one cross-module adapter.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    adapter_code : str
        Exact versioned adapter code.

    Returns
    -------
    bool
        ``True`` only when the exact known manifest pins the adapter.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile is not None and adapter_code in profile.adapter_codes


def profile_allows_conflict_source(
    profile_code: str,
    profile_version: int,
    source_code: str,
) -> bool:
    """Return whether an exact manifest pins one conflict source.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    source_code : str
        Exact versioned conflict-source code.

    Returns
    -------
    bool
        ``True`` only when the exact known manifest pins the source.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile is not None and source_code in profile.conflict_source_codes


def profile_allows_role(
    profile_code: str,
    profile_version: int,
    role_code: str,
) -> bool:
    """Return whether an exact manifest admits one reserved root role.

    Parameters
    ----------
    profile_code : str
        Persisted adoption-profile code.
    profile_version : int
        Persisted adoption-profile version.
    role_code : str
        Stable reserved accountable root-role code.

    Returns
    -------
    bool
        ``True`` only when the exact known manifest pins the root role.
    """
    profile = adoption_profile(profile_code, profile_version)
    return profile is not None and role_code in profile.root_role_codes


def profile_keys_for_module(module_code: str) -> tuple[tuple[str, int], ...]:
    """Return exact manifest keys that deliberately adopt one module.

    Parameters
    ----------
    module_code : str
        Stable Django module namespace.

    Returns
    -------
    tuple[tuple[str, int], ...]
        Exact code/version pairs in registry order. An unknown module yields an
        empty tuple rather than a code-only or namespace-derived fallback.
    """
    return tuple(
        profile.key
        for profile in ADOPTION_PROFILES.values()
        if module_code in profile.modules
    )
