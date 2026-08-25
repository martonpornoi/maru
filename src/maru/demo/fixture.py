"""Deterministic, synthetic data for local exploration and demonstrations."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid5

from django.contrib.auth.hashers import make_password
from django.db import transaction

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.demo.operational_examples import (
    seed_operational_examples,
    seed_workforce_examples,
)
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EditionLifecycleTransition, EventEdition
from maru.events.services import transition_edition
from maru.identity.models import Account
from maru.organizations.models import (
    ConventionSeries,
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    MINIMUM_EXECUTIVE_BOARD_CONTROLLERS,
    activate_executive_board,
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from maru.participation.models import Participation, ParticipationCapacity
from maru.registration.models import (
    AdmissionProduct,
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    CheckInRecord,
    ConfigurationStatus,
    Entitlement,
    MinorRegistrationPolicy,
    PaymentAttempt,
    ProfileExtensionReviewStatus,
    ProfileExtensionStatus,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    QuestionVisibility,
    Registration,
    RegistrationConfiguration,
    RegistrationProfileExtensionField,
    RegistrationProfileExtensionValueRevision,
    RegistrationProvenanceStatus,
    RegistrationQuestion,
    RegistrationSection,
    RegistrationSetupControl,
    RegistrationSetupOrigin,
    RegistrationSubmission,
    RegistrationTemplate,
    RegistrationTemplateProduct,
    RegistrationTemplateQuestion,
    RegistrationTemplateSection,
    RegistrationTimelineEntry,
    TemplateStatus,
)
from maru.registration.profile_extension_values import (
    append_profile_extension_value,
)
from maru.registration.profile_policy import (
    COLLECTION_NOTICE_VERSION,
    DIRECTORY_CONSENT_VERSION,
)
from maru.registration.services import activate_configuration
from maru.workforce.bootstrap import STARTER_POSITIONS

DEMO_NAMESPACE = UUID("6c4b5775-8251-4f11-98e1-b29e09d8fbe6")
CURRENT_DEMO_CONFIGURATION_VERSION = 2
DEMO_ADMIN_EMAIL = "demo.admin@maru.invalid"
Authority = Literal["board", "director", "staff", "volunteer"]


class DemoDataConflictError(RuntimeError):
    """Existing data collides with an identity reserved by the demo fixture."""


@dataclass(frozen=True, slots=True)
class CapacitySpec:
    """Describe capacity spec.

    Attributes
    ----------
    code
        The stable domain code to resolve or validate.
    label
        The human-readable label shown to authorized readers.
    contribution
        The contribution retained in this immutable projection.
    public
        The public retained in this immutable projection.
    """

    code: str
    label: str
    contribution: str
    public: bool = False


@dataclass(frozen=True, slots=True)
class PersonaSpec:
    """Describe persona spec.

    Attributes
    ----------
    key
        The lookup, signing, or idempotency key selected by the contract.
    title
        The human-readable title shown to authorized readers.
    capacities
        The capacities retained in this immutable projection.
    relationship_label
        The human-readable relationship label shown to authorized readers.
    membership_state
        The closed membership state discriminator defined by the domain catalog.
    authority
        The authority retained in this immutable projection.
    past
        The past retained in this immutable projection.
    current
        Whether this destination represents the current request path.
    future
        The future retained in this immutable projection.
    current_status
        The closed current status discriminator defined by the domain catalog.
    current_capacity_status
        The closed current capacity status discriminator defined by the domain catalog.
    shared_account_key
        The stable shared account key used to authenticate or deduplicate the
        operation.
    """

    key: str
    title: str
    capacities: tuple[CapacitySpec, ...]
    relationship_label: str | None = None
    membership_state: str | None = None
    authority: Authority | None = None
    past: bool = False
    current: bool = True
    future: bool = False
    current_status: str = Participation.Status.CONFIRMED
    current_capacity_status: str = ParticipationCapacity.Status.ACTIVE
    shared_account_key: str | None = None


@dataclass(frozen=True, slots=True)
class EditionSpec:
    """Describe edition spec.

    Attributes
    ----------
    key
        The lookup, signing, or idempotency key selected by the contract.
    slug
        The stable URL slug identifying the slug.
    name
        The human-readable name to normalize or persist.
    starts_on
        The calendar date for starts.
    ends_on
        The calendar date for ends.
    lifecycle
        The lifecycle retained in this immutable projection.
    """

    key: str
    slug: str
    name: str
    starts_on: date
    ends_on: date
    lifecycle: str


@dataclass(frozen=True, slots=True)
class ConventionSpec:
    """Describe convention spec.

    Attributes
    ----------
    key
        The lookup, signing, or idempotency key selected by the contract.
    organization_slug
        The stable URL slug identifying the organization.
    organization_name
        The human-readable organization name shown to authorized readers.
    series_slug
        The stable URL slug identifying the series.
    series_name
        The human-readable series name shown to authorized readers.
    short_name
        The human-readable short name shown to authorized readers.
    country_code
        The stable country code from the relevant closed catalog.
    language
        The language retained in this immutable projection.
    time_zone
        The IANA time-zone name used for localized presentation.
    language_codes
        The language codes retained in this immutable projection.
    currency_codes
        The currency codes retained in this immutable projection.
    editions
        The editions retained in this immutable projection.
    """

    key: str
    organization_slug: str
    organization_name: str
    series_slug: str
    series_name: str
    short_name: str
    country_code: str
    language: str
    time_zone: str
    language_codes: tuple[str, ...]
    currency_codes: tuple[str, ...]
    editions: tuple[EditionSpec, ...]


@dataclass(frozen=True, slots=True)
class DemoSeedSummary:
    """Describe demo seed summary.

    Attributes
    ----------
    created
        The created mapping to validate or transform.
    totals
        The totals mapping to validate or transform.
    featured_logins
        The featured logins retained in this immutable projection.
    passwords_reset
        The passwords reset retained in this immutable projection.
    """

    created: dict[str, int]
    totals: dict[str, int]
    featured_logins: tuple[str, ...]
    passwords_reset: int

    def as_dict(self) -> dict[str, object]:
        """Serialize this specification as a dictionary.

        Returns
        -------
        dict[str, object]
            A mapping containing the resolved as dict data.
        """
        return {
            "dataset": "maru-fictional-two-convention-v6",
            "synthetic_only": True,
            "admin_login": DEMO_ADMIN_EMAIL,
            "featured_logins": list(self.featured_logins),
            "all_accounts_use_supplied_password": True,
            "created": self.created,
            "totals": self.totals,
            "passwords_reset": self.passwords_reset,
        }


ATTENDEE = CapacitySpec(
    "attendee",
    "Attendee",
    "Participates in the convention as an attendee.",
)
STAFF = CapacitySpec(
    "staff",
    "Staff",
    "Carries an accountable convention staff responsibility.",
)
VOLUNTEER = CapacitySpec(
    "volunteer",
    "Volunteer",
    "Contributes time to convention operations.",
)
BOARD_MEMBER = CapacitySpec(
    "board-member",
    "Board Member",
    "Provides organizer governance and continuity.",
)


def _capacity(
    code: str,
    label: str,
    contribution: str,
    *,
    public: bool = False,
) -> CapacitySpec:
    return CapacitySpec(code, label, contribution, public)


def _person(
    key: str,
    title: str,
    *roles: CapacitySpec,
    relationship_label: str | None = None,
    membership_state: str | None = None,
    authority: Authority | None = None,
    past: bool = False,
    current: bool = True,
    future: bool = False,
    current_status: str = Participation.Status.CONFIRMED,
    current_capacity_status: str = ParticipationCapacity.Status.ACTIVE,
    shared_account_key: str | None = None,
) -> PersonaSpec:
    return PersonaSpec(
        key=key,
        title=title,
        capacities=(ATTENDEE, *roles),
        relationship_label=relationship_label,
        membership_state=membership_state,
        authority=authority,
        past=past,
        current=current,
        future=future,
        current_status=current_status,
        current_capacity_status=current_capacity_status,
        shared_account_key=shared_account_key,
    )


def _active_staff(
    key: str,
    title: str,
    *roles: CapacitySpec,
    authority: Authority = "staff",
    future: bool = True,
) -> PersonaSpec:
    return _person(
        key,
        title,
        STAFF,
        VOLUNTEER,
        *roles,
        relationship_label=title,
        membership_state=OrganizationMembership.State.ACTIVE,
        authority=authority,
        past=True,
        future=future,
    )


def _personas() -> tuple[PersonaSpec, ...]:
    return (
        _person(
            "board-chair",
            "Board Chair",
            STAFF,
            BOARD_MEMBER,
            _capacity(
                "board-chair",
                "Board Chair",
                "Chairs the organizer board and its governance work.",
            ),
            relationship_label="Board Chair",
            membership_state=OrganizationMembership.State.ACTIVE,
            authority="board",
            past=True,
            future=True,
        ),
        _person(
            "board-vice-chair",
            "Board Vice Chair",
            STAFF,
            BOARD_MEMBER,
            _capacity(
                "board-vice-chair",
                "Board Vice Chair",
                "Supports governance and acts for the chair when delegated.",
            ),
            relationship_label="Board Vice Chair",
            membership_state=OrganizationMembership.State.ACTIVE,
            authority="board",
            past=True,
            future=True,
        ),
        _person(
            "treasurer",
            "Treasurer",
            STAFF,
            BOARD_MEMBER,
            _capacity(
                "treasurer",
                "Treasurer",
                "Oversees budgets, controls, and organizer financial reporting.",
            ),
            relationship_label="Treasurer",
            membership_state=OrganizationMembership.State.ACTIVE,
            authority="board",
            past=True,
            future=True,
        ),
        _person(
            "secretary",
            "Secretary",
            STAFF,
            BOARD_MEMBER,
            _capacity(
                "secretary",
                "Secretary",
                "Maintains governance records, decisions, and formal notices.",
            ),
            relationship_label="Secretary",
            membership_state=OrganizationMembership.State.ACTIVE,
            authority="board",
            past=True,
            future=True,
        ),
        _active_staff(
            "convention-chair",
            "Convention Chair",
            _capacity(
                "convention-chair",
                "Convention Chair",
                "Leads the edition and is accountable for cross-team delivery.",
            ),
            authority="director",
        ),
        _active_staff(
            "deputy-convention-chair",
            "Deputy Convention Chair",
            _capacity(
                "deputy-convention-chair",
                "Deputy Convention Chair",
                "Coordinates delivery and covers convention leadership.",
            ),
            authority="director",
        ),
        _active_staff(
            "operations-lead",
            "Operations Lead",
            _capacity(
                "operations",
                "Operations",
                "Coordinates onsite operations, dependencies, and escalation.",
            ),
        ),
        _active_staff(
            "registration-lead",
            "Registration Lead",
            _capacity(
                "registration",
                "Registration",
                "Leads attendee registration, check-in, and front-desk service.",
            ),
        ),
        _active_staff(
            "volunteer-coordinator",
            "Volunteer Coordinator",
            _capacity(
                "volunteer-coordination",
                "Volunteer Coordination",
                "Recruits, supports, schedules, and recognizes volunteers.",
            ),
        ),
        _active_staff(
            "programme-lead",
            "Programme Lead",
            _capacity(
                "programme",
                "Programme Team",
                "Curates and coordinates the convention programme.",
            ),
            _capacity(
                "programme-host",
                "Programme Host",
                "Hosts programme items and supports presenting participants.",
                public=True,
            ),
        ),
        _active_staff(
            "guest-liaison",
            "Guest Liaison",
            _capacity(
                "guest-relations",
                "Guest Relations",
                "Coordinates guest commitments, travel, and hospitality.",
            ),
        ),
        _active_staff(
            "dealer-liaison",
            "Dealer Liaison",
            _capacity(
                "dealer-relations",
                "Dealer Relations",
                "Coordinates dealer applications, tables, and onsite support.",
            ),
        ),
        _active_staff(
            "it-lead",
            "IT Lead",
            _capacity(
                "it",
                "IT",
                "Operates convention systems, networks, and technical support.",
            ),
        ),
        _active_staff(
            "stage-av-lead",
            "Stage and AV Lead",
            _capacity(
                "stage-av",
                "Stage and AV",
                "Plans stage operations, sound, lighting, and technical delivery.",
            ),
        ),
        _active_staff(
            "safety-lead",
            "Safety and Security Lead",
            _capacity(
                "safety",
                "Safety",
                "Coordinates safety planning and incident readiness.",
            ),
            _capacity(
                "security",
                "Security",
                "Leads access, response, and venue security coordination.",
            ),
        ),
        _active_staff(
            "first-aid-lead",
            "First Aid Lead",
            _capacity(
                "first-aid",
                "First Aid",
                "Coordinates qualified first-aid coverage and escalation.",
            ),
        ),
        _active_staff(
            "accessibility-lead",
            "Accessibility Lead",
            _capacity(
                "accessibility",
                "Accessibility",
                "Coordinates accessible services and removes participation barriers.",
            ),
        ),
        _active_staff(
            "hotel-liaison",
            "Hotel Liaison",
            _capacity(
                "hotel-liaison",
                "Hotel Liaison",
                "Coordinates venue and accommodation operations.",
            ),
        ),
        _active_staff(
            "communications-lead",
            "Communications Lead",
            _capacity(
                "communications",
                "Communications",
                "Coordinates announcements, press, community, and social channels.",
            ),
        ),
        _active_staff(
            "art-show-lead",
            "Art Show Lead",
            _capacity(
                "art-show",
                "Art Show",
                "Coordinates art intake, display, sales, and artist support.",
            ),
        ),
        _active_staff(
            "charity-lead",
            "Charity Lead",
            _capacity(
                "charity",
                "Charity",
                "Coordinates charity partners, fundraising, and fulfilment.",
            ),
        ),
        _active_staff(
            "fursuit-operations-lead",
            "Fursuit Operations Lead",
            _capacity(
                "fursuit-operations",
                "Fursuit Operations",
                "Coordinates lounge, parade, photo, and performer support.",
            ),
        ),
        _active_staff(
            "logistics-lead",
            "Logistics Lead",
            _capacity(
                "logistics",
                "Logistics",
                "Coordinates inventory, transport, loading, and storage.",
            ),
        ),
        _person(
            "front-desk-volunteer",
            "Front Desk Volunteer",
            VOLUNTEER,
            _capacity(
                "front-desk",
                "Front Desk",
                "Provides attendee help and routes operational requests.",
            ),
            relationship_label="Front Desk Volunteer",
            membership_state=OrganizationMembership.State.ACTIVE,
            authority="volunteer",
            past=True,
            future=True,
        ),
        _person(
            "registration-volunteer",
            "Registration Volunteer",
            VOLUNTEER,
            _capacity(
                "registration",
                "Registration",
                "Supports registration, check-in, and credential handover.",
            ),
            relationship_label="Registration Volunteer",
            membership_state=OrganizationMembership.State.ACTIVE,
            authority="volunteer",
            past=True,
            future=True,
        ),
        _person(
            "general-volunteer",
            "General Volunteer",
            VOLUNTEER,
            relationship_label="General Volunteer",
            membership_state=OrganizationMembership.State.ACTIVE,
            authority="volunteer",
            past=True,
            future=True,
        ),
        _person(
            "panel-host",
            "Panel Host",
            _capacity(
                "programme-host",
                "Programme Host",
                "Hosts a community panel in the convention programme.",
                public=True,
            ),
            past=True,
            future=True,
        ),
        _person(
            "dealer",
            "Dealer",
            _capacity(
                "dealer",
                "Dealer",
                "Operates a synthetic dealers-den table.",
                public=True,
            ),
            past=True,
            future=True,
        ),
        _person(
            "dealer-assistant",
            "Dealer Assistant",
            _capacity(
                "dealer-assistant",
                "Dealer Assistant",
                "Assists a synthetic dealer during public opening hours.",
                public=True,
            ),
            future=True,
        ),
        _person(
            "guest-of-honour",
            "Guest of Honour",
            _capacity(
                "guest-of-honour",
                "Guest of Honour",
                "Appears as a synthetic featured community guest.",
                public=True,
            ),
        ),
        _person(
            "performer-dj",
            "Performer and DJ",
            _capacity(
                "performer",
                "Performer",
                "Performs a synthetic stage or dance programme item.",
                public=True,
            ),
            future=True,
        ),
        _person(
            "photographer",
            "Convention Photographer",
            _capacity(
                "photographer",
                "Photographer",
                "Produces approved synthetic convention photography.",
                public=True,
            ),
            past=True,
        ),
        _person(
            "sponsor-attendee",
            "Sponsor Attendee",
            _capacity(
                "sponsor",
                "Sponsor Attendee",
                "Participates at the synthetic sponsor attendance level.",
                public=True,
            ),
            past=True,
            future=True,
        ),
        _person(
            "standard-attendee",
            "Standard Attendee",
            past=True,
            future=True,
        ),
        _person(
            "first-time-attendee",
            "First-time Attendee",
            _capacity(
                "first-time-attendee",
                "First-time Attendee",
                "Attends this convention series for the first time.",
            ),
        ),
        _person(
            "volunteer-applicant",
            "Prospective Volunteer",
            VOLUNTEER,
            relationship_label="Prospective Volunteer",
            membership_state=OrganizationMembership.State.INVITED,
            current_status=Participation.Status.PENDING,
            current_capacity_status=ParticipationCapacity.Status.PROPOSED,
        ),
        _person(
            "cancelled-attendee",
            "Cancelled Attendee",
            current_status=Participation.Status.CANCELLED,
            current_capacity_status=ParticipationCapacity.Status.WITHDRAWN,
        ),
        _person(
            "former-board-member",
            "Former Board Member",
            STAFF,
            BOARD_MEMBER,
            relationship_label="Former Board Member",
            membership_state=OrganizationMembership.State.ENDED,
            past=True,
            current=False,
        ),
        _person(
            "circuit-host",
            "Circuit Programme Host",
            _capacity(
                "programme-host",
                "Programme Host",
                "Hosts programme items at multiple independent conventions.",
                public=True,
            ),
            past=True,
            future=True,
            shared_account_key="shared.circuit-host",
        ),
        _person(
            "roaming-dealer",
            "Roaming Dealer",
            _capacity(
                "dealer",
                "Dealer",
                "Operates a synthetic table at multiple conventions.",
                public=True,
            ),
            past=True,
            future=True,
            shared_account_key="shared.roaming-dealer",
        ),
        _person(
            "crossover-volunteer",
            "Crossover Volunteer",
            VOLUNTEER,
            relationship_label="Crossover Volunteer",
            membership_state=OrganizationMembership.State.ACTIVE,
            authority="volunteer",
            past=True,
            future=True,
            shared_account_key="shared.crossover-volunteer",
        ),
    )


CONVENTIONS = (
    ConventionSpec(
        key="marucon",
        organization_slug="maru-community-events-demo",
        organization_name="Maru Community Events (Demo)",
        series_slug="marucon",
        series_name="MaruCon",
        short_name="MaruCon",
        country_code="HU",
        language="hu",
        time_zone="Europe/Budapest",
        language_codes=("en", "hu", "de"),
        currency_codes=("EUR", "HUF"),
        editions=(
            EditionSpec(
                key="past",
                slug="marucon-2025",
                name="MaruCon 2025",
                starts_on=date(2025, 8, 14),
                ends_on=date(2025, 8, 17),
                lifecycle=EventEdition.Lifecycle.ARCHIVED,
            ),
            EditionSpec(
                key="current",
                slug="marucon-2026",
                name="MaruCon 2026",
                starts_on=date(2026, 8, 13),
                ends_on=date(2026, 8, 16),
                lifecycle=EventEdition.Lifecycle.PREPARING,
            ),
            EditionSpec(
                key="future",
                slug="marucon-2027",
                name="MaruCon 2027",
                starts_on=date(2027, 8, 12),
                ends_on=date(2027, 8, 15),
                lifecycle=EventEdition.Lifecycle.DRAFT,
            ),
        ),
    ),
    ConventionSpec(
        key="marudance",
        organization_slug="maru-arts-collective-demo",
        organization_name="Maru Arts Collective (Demo)",
        series_slug="marudance",
        series_name="MaruDance",
        short_name="MaruDance",
        country_code="FI",
        language="fi",
        time_zone="Europe/Helsinki",
        language_codes=("en", "fi", "sv"),
        currency_codes=("EUR",),
        editions=(
            EditionSpec(
                key="past",
                slug="marudance-2025",
                name="MaruDance 2025",
                starts_on=date(2025, 10, 2),
                ends_on=date(2025, 10, 5),
                lifecycle=EventEdition.Lifecycle.ARCHIVED,
            ),
            EditionSpec(
                key="current",
                slug="marudance-2026",
                name="MaruDance 2026",
                starts_on=date(2026, 10, 1),
                ends_on=date(2026, 10, 4),
                lifecycle=EventEdition.Lifecycle.PREPARING,
            ),
            EditionSpec(
                key="future",
                slug="marudance-2027",
                name="MaruDance 2027",
                starts_on=date(2027, 9, 30),
                ends_on=date(2027, 10, 3),
                lifecycle=EventEdition.Lifecycle.DRAFT,
            ),
        ),
    ),
)


ROLE_DEFINITIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "board": (
        "Board oversight",
        (
            "events.view_basic",
            "authorization.delegate",
            "audit.view_security",
        ),
    ),
    "director": (
        "Edition director",
        (
            "events.view_basic",
            "events.transition",
            "participation.view_staff_summary",
        ),
    ),
    "staff": (
        "Operations staff",
        (
            "events.view_basic",
            "participation.view_staff_summary",
        ),
    ),
    "volunteer": (
        "Edition volunteer",
        ("events.view_basic",),
    ),
}

LIFECYCLE_PATH = (
    EventEdition.Lifecycle.DRAFT,
    EventEdition.Lifecycle.PREPARING,
    EventEdition.Lifecycle.READY,
    EventEdition.Lifecycle.LIVE,
    EventEdition.Lifecycle.CLOSING,
    EventEdition.Lifecycle.ARCHIVED,
)


def _stable_id(kind: str, key: str) -> UUID:
    return uuid5(DEMO_NAMESPACE, f"{kind}:{key}")


class _DemoSeeder:
    def __init__(self, *, password: str, reset_passwords: bool) -> None:
        """Initialize the _DemoSeeder instance.

        Parameters
        ----------
        password : str
            The password assigned to generated demo accounts.
        reset_passwords : bool
            Whether to replace passwords on existing demo accounts.
        """
        self.password_hash = make_password(password)
        self.reset_passwords = reset_passwords
        self.created: Counter[str] = Counter()
        self.passwords_reset = 0
        self.owned: defaultdict[str, set[UUID]] = defaultdict(set)
        self.featured_logins: list[str] = []

    def _own(self, kind: str, object_id: UUID, *, created: bool) -> None:
        self.owned[kind].add(object_id)
        if created:
            self.created[kind] += 1

    def _account(
        self,
        *,
        key: str,
        email: str,
        display_name: str,
        language: str,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> Account:
        object_id = _stable_id("account", key)
        email_collision = Account.objects.filter(email__iexact=email).first()
        if email_collision is not None and email_collision.id != object_id:
            raise DemoDataConflictError(
                f"Email {email!r} already belongs to a non-demo account."
            )

        account = Account.objects.filter(pk=object_id).first()
        created = account is None
        if account is None:
            account = Account(
                id=object_id,
                email=email,
                display_name=display_name,
                preferred_language=language,
                is_active=True,
                is_staff=is_staff,
                is_superuser=is_superuser,
                account_kind=(
                    Account.Kind.PLATFORM_ADMINISTRATOR
                    if is_superuser
                    else Account.Kind.PERSON
                ),
                email_verified_at=datetime(2024, 1, 1, 12, tzinfo=UTC),
                password=self.password_hash,
                date_joined=datetime(2024, 1, 1, 12, tzinfo=UTC),
            )
            account.full_clean()
            account.save(force_insert=True)
        elif account.email != email:
            raise DemoDataConflictError(
                f"Stable demo account ID {object_id} is already used by "
                f"{account.email!r}."
            )
        else:
            changed_fields: list[str] = []
            if account.email_verified_at is None:
                # Older local fixtures predate verified-email enforcement. The
                # deterministic demo address is synthetic and fixture-owned, so
                # reconciling it does not assert anything about a real person.
                account.email_verified_at = datetime(2024, 1, 1, 12, tzinfo=UTC)
                changed_fields.append("email_verified_at")
            if self.reset_passwords and account.id not in self.owned["accounts"]:
                account.password = self.password_hash
                changed_fields.append("password")
                self.passwords_reset += 1
            if changed_fields:
                account.save(update_fields=tuple(changed_fields))

        self._own("accounts", account.id, created=created)
        return account

    def _organization(self, spec: ConventionSpec) -> Organization:
        object_id = _stable_id("organization", spec.key)
        slug_collision = Organization.objects.filter(
            slug__iexact=spec.organization_slug
        ).first()
        if slug_collision is not None and slug_collision.id != object_id:
            raise DemoDataConflictError(
                f"Organization slug {spec.organization_slug!r} is already in use."
            )
        organization = Organization.objects.filter(pk=object_id).first()
        created = organization is None
        has_active_representation = OrganizationRepresentation.objects.filter(
            organization_id=object_id,
            state=OrganizationRepresentation.State.ACTIVE,
        ).exists()
        organization_values = {
            "lifecycle": (
                Organization.Lifecycle.ACTIVE
                if has_active_representation
                else Organization.Lifecycle.DRAFT
            ),
            "legal_name": spec.organization_name.removesuffix(" (Demo)"),
            "description": (
                f"Synthetic accountable organizer for the {spec.series_name} "
                "demonstration dataset."
            ),
            "website_url": f"https://{spec.organization_slug}.example.invalid/",
            "contact_email": (f"office@{spec.organization_slug}.demo.maru.invalid"),
            "country_code": spec.country_code,
            "default_language_codes": list(spec.language_codes),
            "default_time_zone": spec.time_zone,
        }
        if organization is None:
            organization = Organization(
                id=object_id,
                slug=spec.organization_slug,
                name=spec.organization_name,
                **organization_values,
            )
            organization.save(force_insert=True)
        elif organization.slug != spec.organization_slug:
            raise DemoDataConflictError(
                f"Stable demo organization ID {object_id} has unexpected data."
            )
        else:
            changed_fields = []
            for field_name, value in organization_values.items():
                if getattr(organization, field_name) != value:
                    setattr(organization, field_name, value)
                    changed_fields.append(field_name)
            if changed_fields:
                organization.save(update_fields=(*changed_fields, "updated_at"))
        self._own("organizations", organization.id, created=created)
        return organization

    def _executive_board_representation(
        self,
        *,
        convention: ConventionSpec,
        organization: Organization,
        administrator: Account,
        accounts: dict[str, Account],
    ) -> None:
        """Exercise the real two-controller handoff in the synthetic fixture.

        Parameters
        ----------
        convention : ConventionSpec
            The convention evaluated while executive board representation.
        organization : Organization
            The organization that owns the requested resource.
        administrator : Account
            The platform administrator authorizing the privileged action.
        accounts : dict[str, Account]
            The accounts mapping to validate or transform.

        Raises
        ------
        DemoDataConflictError
            If the operation encounters a demo data conflict condition.
        """
        representation = (
            OrganizationRepresentation.objects.filter(organization=organization)
            .select_related("organization")
            .first()
        )
        created = representation is None
        if representation is None:
            correlation_id = _stable_id(
                "representation-correlation",
                convention.key,
            )
            before_audit = AuditEvent.objects.filter(
                organization_id=organization.id
            ).count()
            before_events = DomainEvent.objects.filter(
                organization_id=organization.id
            ).count()
            before_outbox = OutboxMessage.objects.filter(
                organization_id=organization.id
            ).count()
            representation = provision_executive_board(
                actor=administrator,
                organization_id=organization.id,
                reason="Synthetic fixture Executive Board establishment.",
                correlation_id=correlation_id,
                source_channel="demo_seed",
            )
            for persona_key in ("board-chair", "board-vice-chair"):
                account = accounts[persona_key]
                appointment = invite_representation_controller(
                    actor=administrator,
                    representation_id=representation.id,
                    account_id=account.id,
                    reason="Synthetic fixture accountable controller invitation.",
                    correlation_id=correlation_id,
                    source_channel="demo_seed",
                )
                respond_to_representation_invitation(
                    actor=account,
                    appointment_id=appointment.id,
                    expected_version=appointment.invitation_version,
                    accept=True,
                    correlation_id=correlation_id,
                    source_channel="demo_seed",
                )
            representation.refresh_from_db(fields=("aggregate_version",))
            activate_executive_board(
                actor=administrator,
                representation_id=representation.id,
                expected_version=representation.aggregate_version,
                reason="Synthetic fixture independent controller activation.",
                correlation_id=correlation_id,
                source_channel="demo_seed",
            )
            self.created["audit_events"] += (
                AuditEvent.objects.filter(organization_id=organization.id).count()
                - before_audit
            )
            self.created["domain_events"] += (
                DomainEvent.objects.filter(organization_id=organization.id).count()
                - before_events
            )
            self.created["outbox_messages"] += (
                OutboxMessage.objects.filter(organization_id=organization.id).count()
                - before_outbox
            )

        representation.refresh_from_db()
        appointments = tuple(
            representation.appointments.select_related(
                "role_assignment",
                "role_assignment__role_bundle",
            ).all()
        )
        if (
            representation.state != OrganizationRepresentation.State.ACTIVE
            or len(
                [
                    appointment
                    for appointment in appointments
                    if appointment.state == RepresentationAppointment.State.ACTIVE
                ]
            )
            < MINIMUM_EXECUTIVE_BOARD_CONTROLLERS
        ):
            raise DemoDataConflictError(
                f"Synthetic organization {organization.slug!r} has an incomplete "
                "Executive Board handoff."
            )
        self._own(
            "organization_representations",
            representation.id,
            created=created,
        )
        for appointment in appointments:
            self._own(
                "representation_appointments",
                appointment.id,
                created=created,
            )
            if appointment.role_assignment is None:
                raise DemoDataConflictError(
                    f"Synthetic Executive Board appointment {appointment.id} "
                    "has no authority assignment."
                )
            self._own(
                "role_assignments",
                appointment.role_assignment.id,
                created=created,
            )
            self._own(
                "role_bundles",
                appointment.role_assignment.role_bundle_id,
                created=(
                    created
                    and appointment.role_assignment.role_bundle_id
                    not in self.owned["role_bundles"]
                ),
            )
        organization.refresh_from_db(fields=("lifecycle", "updated_at"))

    def _series(
        self,
        *,
        spec: ConventionSpec,
        organization: Organization,
    ) -> ConventionSeries:
        object_id = _stable_id("series", spec.key)
        slug_collision = ConventionSeries.objects.filter(
            organization=organization,
            slug__iexact=spec.series_slug,
        ).first()
        if slug_collision is not None and slug_collision.id != object_id:
            raise DemoDataConflictError(
                f"Convention slug {spec.series_slug!r} is already in use."
            )
        series = ConventionSeries.objects.filter(pk=object_id).first()
        created = series is None
        series_values = {
            "description": (
                f"Synthetic recurring public brand for {spec.short_name} "
                "convention editions."
            ),
            "website_url": f"https://{spec.series_slug}.example.invalid/",
            "contact_email": f"hello@{spec.series_slug}.demo.maru.invalid",
        }
        if series is None:
            series = ConventionSeries(
                id=object_id,
                organization=organization,
                slug=spec.series_slug,
                name=spec.series_name,
                **series_values,
            )
            series.save(force_insert=True)
        elif (
            series.organization_id != organization.id or series.slug != spec.series_slug
        ):
            raise DemoDataConflictError(
                f"Stable demo convention ID {object_id} has unexpected scope."
            )
        else:
            changed_fields = []
            for field_name, value in series_values.items():
                if getattr(series, field_name) != value:
                    setattr(series, field_name, value)
                    changed_fields.append(field_name)
            if changed_fields:
                series.profile_version += 1
                series.save(
                    update_fields=(
                        *changed_fields,
                        "profile_version",
                        "updated_at",
                    )
                )
        self._own("convention_series", series.id, created=created)
        return series

    def _edition(
        self,
        *,
        convention: ConventionSpec,
        spec: EditionSpec,
        organization: Organization,
        series: ConventionSeries,
    ) -> EventEdition:
        object_id = _stable_id("edition", f"{convention.key}.{spec.key}")
        slug_collision = EventEdition.objects.filter(
            series=series,
            slug__iexact=spec.slug,
        ).first()
        if slug_collision is not None and slug_collision.id != object_id:
            raise DemoDataConflictError(
                f"Edition slug {spec.slug!r} is already in use."
            )
        edition = EventEdition.objects.filter(pk=object_id).first()
        created = edition is None
        if edition is None:
            edition = EventEdition(
                id=object_id,
                organization=organization,
                series=series,
                slug=spec.slug,
                name=spec.name,
                time_zone=convention.time_zone,
                language_codes=list(convention.language_codes),
                currency_codes=list(convention.currency_codes),
                starts_on=spec.starts_on,
                ends_on=spec.ends_on,
            )
            edition.save(force_insert=True)
        elif (
            edition.organization_id != organization.id
            or edition.series_id != series.id
            or edition.slug != spec.slug
        ):
            raise DemoDataConflictError(
                f"Stable demo edition ID {object_id} has unexpected scope."
            )
        self._own("event_editions", edition.id, created=created)
        return edition

    def _membership(
        self,
        *,
        convention: ConventionSpec,
        persona: PersonaSpec,
        organization: Organization,
        account: Account,
    ) -> None:
        if persona.membership_state is None or persona.relationship_label is None:
            return
        object_id = _stable_id(
            "membership",
            f"{convention.key}.{persona.key}",
        )
        collision = OrganizationMembership.objects.filter(
            organization=organization,
            account=account,
        ).first()
        if collision is not None and collision.id != object_id:
            raise DemoDataConflictError(
                f"{account.email!r} already has a non-demo membership in "
                f"{organization.name!r}."
            )
        membership = OrganizationMembership.objects.filter(pk=object_id).first()
        created = membership is None
        if membership is None:
            ended_at = None
            if persona.membership_state == OrganizationMembership.State.ENDED:
                ended_at = datetime(2025, 12, 1, 12, tzinfo=UTC)
            membership = OrganizationMembership.objects.create(
                id=object_id,
                organization=organization,
                account=account,
                state=persona.membership_state,
                relationship_label=persona.relationship_label,
                started_at=datetime(2024, 1, 1, 12, tzinfo=UTC),
                ended_at=ended_at,
            )
        self._own("memberships", membership.id, created=created)

    def _role_bundle(
        self,
        *,
        convention: ConventionSpec,
        organization: Organization,
        authority: str,
    ) -> RoleBundle:
        name, capabilities = ROLE_DEFINITIONS[authority]
        role_code = f"demo-{authority}"
        object_id = _stable_id(
            "role-bundle",
            f"{convention.key}.{authority}.v1",
        )
        collision = RoleBundle.objects.filter(
            organization=organization,
            code=role_code,
            version=1,
        ).first()
        if collision is not None and collision.id != object_id:
            raise DemoDataConflictError(
                f"Role {role_code!r} version 1 already exists outside the fixture."
            )
        role = RoleBundle.objects.filter(pk=object_id).first()
        created = role is None
        if role is None:
            role = RoleBundle.objects.create(
                id=object_id,
                organization=organization,
                code=role_code,
                name=f"{name} (Demo)",
                version=1,
                capability_codes=list(capabilities),
            )
        elif tuple(role.capability_codes) != capabilities:
            raise DemoDataConflictError(
                f"Immutable demo role {role_code!r} has unexpected capabilities."
            )
        self._own("role_bundles", role.id, created=created)
        return role

    def _role_assignment(
        self,
        *,
        convention: ConventionSpec,
        persona: PersonaSpec,
        organization: Organization,
        edition: EventEdition | None,
        account: Account,
        role: RoleBundle,
        granted_by: Account,
    ) -> None:
        scope_key = str(edition.id) if edition is not None else "organization"
        object_id = _stable_id(
            "role-assignment",
            f"{convention.key}.{persona.key}.{role.code}.{scope_key}",
        )
        assignment = RoleAssignment.objects.filter(pk=object_id).first()
        created = assignment is None
        if assignment is None:
            assignment = RoleAssignment.objects.create(
                id=object_id,
                organization=organization,
                edition=edition,
                principal=account,
                role_bundle=role,
                effective_from=datetime(2024, 1, 1, 12, tzinfo=UTC),
                granted_by=granted_by,
                reason=f"Synthetic demo authority for {persona.title}.",
            )
        elif (
            assignment.organization_id != organization.id
            or assignment.edition_id != (edition.id if edition else None)
            or assignment.principal_id != account.id
            or assignment.role_bundle_id != role.id
        ):
            raise DemoDataConflictError(
                f"Stable demo role assignment ID {object_id} has unexpected scope."
            )
        self._own("role_assignments", assignment.id, created=created)

    def _starter_role_bundle(
        self,
        *,
        convention: ConventionSpec,
        organization: Organization,
        code: str,
        name: str,
        capability_codes: tuple[str, ...],
    ) -> RoleBundle:
        object_id = _stable_id(
            "starter-role-bundle",
            f"{convention.key}.{code}.v1",
        )
        collision = RoleBundle.objects.filter(
            organization=organization,
            code=code,
            version=1,
        ).first()
        if collision is not None and collision.id != object_id:
            raise DemoDataConflictError(
                f"Starter role {code!r} version 1 already exists outside the fixture."
            )
        role = RoleBundle.objects.filter(pk=object_id).first()
        created = role is None
        if role is None:
            role = RoleBundle.objects.create(
                id=object_id,
                organization=organization,
                code=code,
                name=name,
                version=1,
                capability_codes=list(capability_codes),
            )
        elif tuple(role.capability_codes) != capability_codes:
            raise DemoDataConflictError(
                f"Immutable starter role {code!r} has unexpected capabilities."
            )
        self._own("role_bundles", role.id, created=created)
        return role

    def _capability_grant(
        self,
        *,
        convention: ConventionSpec,
        organization: Organization,
        edition: EventEdition | None,
        account: Account,
        capability_code: str,
        granted_by: Account,
    ) -> None:
        object_id = _stable_id(
            "capability-grant",
            (
                f"{convention.key}."
                f"{edition.id if edition is not None else 'organization'}."
                f"{account.id}.{capability_code}"
            ),
        )
        grant = CapabilityGrant.objects.filter(pk=object_id).first()
        created = grant is None
        if grant is None:
            grant = CapabilityGrant.objects.create(
                id=object_id,
                organization=organization,
                edition=edition,
                principal=account,
                capability_code=capability_code,
                effective_from=datetime(2024, 1, 1, 12, tzinfo=UTC),
                granted_by=granted_by,
                approved_by=granted_by,
                reason="Synthetic registration workflow authority.",
            )
        elif (
            grant.organization_id != organization.id
            or grant.edition_id != (edition.id if edition is not None else None)
            or grant.principal_id != account.id
            or grant.capability_code != capability_code
        ):
            raise DemoDataConflictError(
                f"Stable demo capability grant ID {object_id} has unexpected scope."
            )
        self._own("capability_grants", grant.id, created=created)

    def _participation(
        self,
        *,
        convention: ConventionSpec,
        persona: PersonaSpec,
        edition_spec: EditionSpec,
        organization: Organization,
        edition: EventEdition,
        account: Account,
    ) -> Participation:
        object_id = _stable_id(
            "participation",
            f"{convention.key}.{edition_spec.key}.{persona.key}",
        )
        collision = Participation.objects.filter(
            account=account,
            edition=edition,
        ).first()
        if collision is not None and collision.id != object_id:
            raise DemoDataConflictError(
                f"{account.email!r} already has a non-demo participation in "
                f"{edition.name!r}."
            )

        status: str = Participation.Status.INTERESTED
        if edition_spec.key == "past":
            status = Participation.Status.COMPLETED
        elif edition_spec.key == "current":
            status = persona.current_status

        participation = Participation.objects.filter(pk=object_id).first()
        created = participation is None
        if participation is None:
            participation = Participation.objects.create(
                id=object_id,
                account=account,
                organization=organization,
                edition=edition,
                status=status,
                edition_name_snapshot=edition.name,
                series_name_snapshot=edition.series.name,
                public_history_visible=any(
                    capacity.public for capacity in persona.capacities
                ),
            )
        elif (
            participation.account_id != account.id
            or participation.organization_id != organization.id
            or participation.edition_id != edition.id
        ):
            raise DemoDataConflictError(
                f"Stable demo participation ID {object_id} has unexpected scope."
            )
        self._own("participations", participation.id, created=created)
        return participation

    def _participation_capacity(
        self,
        *,
        convention: ConventionSpec,
        persona: PersonaSpec,
        edition_spec: EditionSpec,
        participation: Participation,
        capacity: CapacitySpec,
    ) -> None:
        object_id = _stable_id(
            "participation-capacity",
            (f"{convention.key}.{edition_spec.key}.{persona.key}.{capacity.code}"),
        )
        collision = ParticipationCapacity.objects.filter(
            participation=participation,
            code=capacity.code,
        ).first()
        if collision is not None and collision.id != object_id:
            raise DemoDataConflictError(
                f"Capacity {capacity.code!r} already exists outside the fixture "
                f"for {participation.id}."
            )

        status: str = ParticipationCapacity.Status.PROPOSED
        started_at: datetime | None = None
        ended_at: datetime | None = None
        if edition_spec.key == "past":
            status = ParticipationCapacity.Status.COMPLETED
            started_at = datetime.combine(edition_spec.starts_on, datetime.min.time())
            started_at = started_at.replace(tzinfo=UTC)
            ended_at = datetime.combine(edition_spec.ends_on, datetime.min.time())
            ended_at = ended_at.replace(tzinfo=UTC)
        elif edition_spec.key == "current":
            status = persona.current_capacity_status
            if status == ParticipationCapacity.Status.ACTIVE:
                started_at = datetime(2026, 1, 15, 12, tzinfo=UTC)
            elif status == ParticipationCapacity.Status.WITHDRAWN:
                ended_at = datetime(2026, 6, 15, 12, tzinfo=UTC)

        record = ParticipationCapacity.objects.filter(pk=object_id).first()
        created = record is None
        if record is None:
            record = ParticipationCapacity.objects.create(
                id=object_id,
                participation=participation,
                code=capacity.code,
                label_snapshot=capacity.label,
                status=status,
                contribution_summary=capacity.contribution,
                public_history_visible=capacity.public,
                started_at=started_at,
                ended_at=ended_at,
            )
        elif (
            record.participation_id != participation.id or record.code != capacity.code
        ):
            raise DemoDataConflictError(
                f"Stable demo capacity ID {object_id} has unexpected ownership."
            )
        self._own("participation_capacities", record.id, created=created)

    @staticmethod
    def _registration_section_specs(
        convention: ConventionSpec,
    ) -> tuple[dict[str, object], ...]:
        custom = (
            {
                "key": "fursuit-profile",
                "title": "Fursuit profile",
                "description": (
                    "Optional character details for fursuit-related convention "
                    "services."
                ),
                "position": 20,
            }
            if convention.key == "marucon"
            else {
                "key": "visit-planning",
                "title": "Visit planning",
                "description": "Optional planning questions for this convention.",
                "position": 20,
            }
        )
        return (
            {
                "key": "attendee-details",
                "title": "Attendee details",
                "description": "Badge and service preferences for this edition.",
                "position": 10,
            },
            custom,
            {
                "key": "agreements",
                "title": "Agreements",
                "description": "Required edition policy acknowledgements.",
                "position": 90,
            },
        )

    @staticmethod
    def _registration_question_specs(
        convention: ConventionSpec,
    ) -> tuple[dict[str, object], ...]:
        common: tuple[dict[str, object], ...] = (
            {
                "section_key": "attendee-details",
                "key": "badge-name",
                "label": "Name on your badge",
                "help_text": (
                    "This may be a fandom name or another chosen display name."
                ),
                "field_type": QuestionFieldType.SHORT_TEXT,
                "required": True,
                "position": 10,
                "options": [],
                "purpose": "Print the attendee-facing name on the event badge.",
                "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
                "classification": QuestionClassification.PERSONAL,
                "condition_question_key": "",
                "condition_value": "",
            },
            {
                "section_key": "attendee-details",
                "key": "preferred-language",
                "label": "Preferred event language",
                "help_text": "Registration staff use this for attendee service.",
                "field_type": QuestionFieldType.SINGLE_CHOICE,
                "required": True,
                "position": 20,
                "options": list(convention.language_codes),
                "purpose": "Provide registration service in a suitable language.",
                "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
                "classification": QuestionClassification.PERSONAL,
                "condition_question_key": "",
                "condition_value": "",
            },
        )
        if convention.key == "marucon":
            custom = (
                {
                    "section_key": "fursuit-profile",
                    "key": "bringing-fursuit",
                    "label": "Will you bring a fursuit?",
                    "help_text": "This helps the convention plan lounge capacity.",
                    "field_type": QuestionFieldType.BOOLEAN,
                    "required": True,
                    "position": 30,
                    "options": [],
                    "purpose": "Plan fursuit lounge service capacity.",
                    "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
                    "classification": QuestionClassification.PERSONAL,
                    "condition_question_key": "",
                    "condition_value": "",
                },
                {
                    "section_key": "fursuit-profile",
                    "key": "fursuit-species",
                    "label": "Fursuit character species",
                    "help_text": "Optional operational label for the fursuit badge.",
                    "field_type": QuestionFieldType.SHORT_TEXT,
                    "required": False,
                    "position": 40,
                    "options": [],
                    "purpose": "Prepare an optional fursuit badge label.",
                    "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
                    "classification": QuestionClassification.PERSONAL,
                    "condition_question_key": "bringing-fursuit",
                    "condition_value": "true",
                },
            )
        else:
            custom = (
                {
                    "section_key": "visit-planning",
                    "key": "sauna-interest",
                    "label": "Interested in the scheduled sauna session?",
                    "help_text": "This is an interest signal, not a reservation.",
                    "field_type": QuestionFieldType.BOOLEAN,
                    "required": False,
                    "position": 30,
                    "options": [],
                    "purpose": "Estimate interest for an organizer-run activity.",
                    "visibility": QuestionVisibility.REGISTRATION_STAFF,
                    "classification": QuestionClassification.PERSONAL,
                    "condition_question_key": "",
                    "condition_value": "",
                },
                {
                    "section_key": "visit-planning",
                    "key": "arrival-mode",
                    "label": "Expected arrival mode",
                    "help_text": "Used only for aggregate arrival planning.",
                    "field_type": QuestionFieldType.SINGLE_CHOICE,
                    "required": False,
                    "position": 40,
                    "options": ["Train", "Coach", "Car", "Local transit", "Other"],
                    "purpose": "Estimate aggregate arrival patterns.",
                    "visibility": QuestionVisibility.REGISTRATION_STAFF,
                    "classification": QuestionClassification.PERSONAL,
                    "condition_question_key": "",
                    "condition_value": "",
                },
            )
        agreement = (
            {
                "section_key": "agreements",
                "key": "code-of-conduct",
                "label": "I agree to follow the convention code of conduct",
                "help_text": (
                    "The exact policy version remains part of this form version."
                ),
                "field_type": QuestionFieldType.BOOLEAN,
                "required": True,
                "position": 90,
                "options": [],
                "purpose": "Record the required event conduct agreement.",
                "visibility": QuestionVisibility.ATTENDEE_AND_STAFF,
                "classification": QuestionClassification.PERSONAL,
                "condition_question_key": "",
                "condition_value": "",
            },
        )
        return (*common, *custom, *agreement)

    @staticmethod
    def _registration_product_specs(
        convention: ConventionSpec,
    ) -> tuple[dict[str, object], ...]:
        if convention.key == "marucon":
            return (
                {
                    "code": "weekend",
                    "name": "Weekend admission",
                    "description": "Admission for all four convention days.",
                    "price_minor": 12_000,
                    "capacity": 900,
                    "position": 10,
                    "entitlement_code": "event-admission",
                    "entitlement_name": "MaruCon 2026 weekend admission",
                },
                {
                    "code": "sponsor",
                    "name": "Sponsor admission",
                    "description": "Weekend admission with a supporter package.",
                    "price_minor": 22_000,
                    "capacity": 180,
                    "position": 20,
                    "entitlement_code": "sponsor-admission",
                    "entitlement_name": "MaruCon 2026 sponsor admission",
                },
            )
        return (
            {
                "code": "weekend",
                "name": "MaruDance weekend admission",
                "description": "Admission for the complete convention.",
                "price_minor": 13_500,
                "capacity": 650,
                "position": 10,
                "entitlement_code": "event-admission",
                "entitlement_name": "MaruDance weekend admission",
            },
            {
                "code": "youth",
                "name": "Youth admission",
                "description": (
                    "Synthetic age-policy example; eligibility is future work."
                ),
                "price_minor": 7_500,
                "capacity": 90,
                "position": 20,
                "entitlement_code": "youth-admission",
                "entitlement_name": "MaruDance youth admission",
            },
        )

    def _registration_template(
        self,
        *,
        convention: ConventionSpec,
        organization: Organization,
        series: ConventionSeries,
        actor: Account,
    ) -> RegistrationTemplate:
        template_id = _stable_id("registration-template", f"{convention.key}.v1")
        template = RegistrationTemplate.objects.filter(id=template_id).first()
        created = template is None
        if template is None:
            template = RegistrationTemplate.objects.create(
                id=template_id,
                organization=organization,
                series=series,
                code=f"{convention.key}-attendee-registration",
                name=f"{convention.series_name} attendee registration",
                description=(
                    "Reviewed synthetic starting point for annual attendee "
                    "registration."
                ),
                version=1,
                created_by_id=actor.id,
            )
            sections: dict[str, RegistrationTemplateSection] = {}
            for spec in self._registration_section_specs(convention):
                section = RegistrationTemplateSection.objects.create(
                    id=_stable_id(
                        "registration-template-section",
                        f"{convention.key}.{spec['key']}",
                    ),
                    template=template,
                    **spec,
                )
                sections[str(spec["key"])] = section
                self._own(
                    "registration_template_sections",
                    section.id,
                    created=True,
                )
            for spec in self._registration_question_specs(convention):
                question_values = dict(spec)
                section_key = str(question_values.pop("section_key"))
                question = RegistrationTemplateQuestion.objects.create(
                    id=_stable_id(
                        "registration-template-question",
                        f"{convention.key}.{spec['key']}",
                    ),
                    template=template,
                    section=sections[section_key],
                    **question_values,
                )
                self._own(
                    "registration_template_questions",
                    question.id,
                    created=True,
                )
            for spec in self._registration_product_specs(convention):
                product = RegistrationTemplateProduct.objects.create(
                    id=_stable_id(
                        "registration-template-product",
                        f"{convention.key}.{spec['code']}",
                    ),
                    template=template,
                    **spec,
                )
                self._own(
                    "registration_template_products",
                    product.id,
                    created=True,
                )
            template.status = TemplateStatus.PUBLISHED
            template.published_at = datetime(2026, 1, 15, 12, tzinfo=UTC)
            template.save(update_fields=("status", "published_at", "updated_at"))
        elif (
            template.organization_id != organization.id
            or template.series_id != series.id
            or template.status != TemplateStatus.PUBLISHED
        ):
            raise DemoDataConflictError(
                f"Stable registration template {template_id} has unexpected scope."
            )
        self._own("registration_templates", template.id, created=created)
        return template

    def _registration_configuration(
        self,
        *,
        convention: ConventionSpec,
        edition_spec: EditionSpec,
        edition: EventEdition,
        organization: Organization,
        template: RegistrationTemplate,
        actor: Account,
        source_edition: EventEdition | None,
    ) -> RegistrationConfiguration:
        configuration_id = _stable_id(
            "registration-configuration",
            f"{convention.key}.{edition_spec.key}.v1",
        )
        configuration = RegistrationConfiguration.objects.filter(
            id=configuration_id
        ).first()
        created = configuration is None
        if configuration is None:
            opens_at = datetime.combine(
                edition_spec.starts_on - timedelta(days=120),
                datetime.min.time(),
                tzinfo=UTC,
            )
            closes_at = datetime.combine(
                edition_spec.starts_on,
                datetime.min.time(),
                tzinfo=UTC,
            )
            status = (
                ConfigurationStatus.DRAFT
                if edition_spec.key == "future"
                else ConfigurationStatus.ACTIVE
            )
            configuration = RegistrationConfiguration.objects.create(
                id=configuration_id,
                organization=organization,
                edition=edition,
                name=f"{edition.name} attendee registration",
                version=1,
                source_template=template if source_edition is None else None,
                source_edition=source_edition,
                review_required=status == ConfigurationStatus.DRAFT,
                review_note=(
                    "Inherited configuration requires annual review."
                    if status == ConfigurationStatus.DRAFT
                    else "Reviewed for the synthetic convention walkthrough."
                ),
                opens_at=opens_at,
                closes_at=closes_at,
                capacity=1_100 if convention.key == "marucon" else 740,
                currency="EUR",
                created_by_id=actor.id,
            )
            sections: dict[str, RegistrationSection] = {}
            for spec in self._registration_section_specs(convention):
                section = RegistrationSection.objects.create(
                    id=_stable_id(
                        "registration-section",
                        f"{convention.key}.{edition_spec.key}.{spec['key']}",
                    ),
                    configuration=configuration,
                    **spec,
                )
                sections[str(spec["key"])] = section
                self._own("registration_sections", section.id, created=True)
            for spec in self._registration_question_specs(convention):
                question_values = dict(spec)
                section_key = str(question_values.pop("section_key"))
                question = RegistrationQuestion.objects.create(
                    id=_stable_id(
                        "registration-question",
                        f"{convention.key}.{edition_spec.key}.{spec['key']}",
                    ),
                    configuration=configuration,
                    section=sections[section_key],
                    **question_values,
                )
                self._own("registration_questions", question.id, created=True)
            for spec in self._registration_product_specs(convention):
                product = AdmissionProduct.objects.create(
                    id=_stable_id(
                        "registration-product",
                        f"{convention.key}.{edition_spec.key}.{spec['code']}",
                    ),
                    configuration=configuration,
                    **spec,
                )
                self._own("admission_products", product.id, created=True)
            if status == ConfigurationStatus.ACTIVE:
                configuration.status = ConfigurationStatus.ACTIVE
                configuration.review_required = False
                configuration.activated_at = datetime(
                    2026,
                    1,
                    20,
                    12,
                    tzinfo=UTC,
                )
                configuration.save(
                    update_fields=(
                        "status",
                        "review_required",
                        "activated_at",
                        "updated_at",
                    )
                )
        elif (
            configuration.organization_id != organization.id
            or configuration.edition_id != edition.id
        ):
            raise DemoDataConflictError(
                f"Stable registration configuration {configuration_id} "
                "has unexpected scope."
            )
        if (
            configuration.status == ConfigurationStatus.DRAFT
            and not configuration.sections.exists()
        ):
            sections = {}
            for spec in self._registration_section_specs(convention):
                section = RegistrationSection.objects.create(
                    id=_stable_id(
                        "registration-section",
                        f"{convention.key}.{edition_spec.key}.{spec['key']}",
                    ),
                    configuration=configuration,
                    **spec,
                )
                sections[str(spec["key"])] = section
                self._own("registration_sections", section.id, created=True)
            for question in configuration.questions.all():
                spec = next(
                    value
                    for value in self._registration_question_specs(convention)
                    if value["key"] == question.key
                )
                question.section = sections[str(spec["section_key"])]
                question.save(update_fields=("section", "updated_at"))
        self._own("registration_configurations", configuration.id, created=created)
        return configuration

    def _registration_setup_control(
        self,
        *,
        convention: ConventionSpec,
        edition: EventEdition,
        organization: Organization,
    ) -> RegistrationSetupControl:
        """Expose directly seeded registration setup through the canonical reader.

        The demonstration configuration still uses the documented compatibility
        writer while Registration setup writer cutover remains incomplete. Mirror the
        migration backfill boundary honestly: the aggregate is readable, but it
        retains legacy origin and unknown provenance rather than inventing a
        source digest, actor, or command receipt.

        Parameters
        ----------
        convention : ConventionSpec
            The fictional convention namespace that owns the stable identifier.
        edition : EventEdition
            The exact edition whose seeded configuration is exposed.
        organization : Organization
            The organizer that owns the exact edition.

        Returns
        -------
        RegistrationSetupControl
            The existing or newly created honest legacy setup control.

        Raises
        ------
        DemoDataConflictError
            If a reserved identifier or edition scope contains incompatible
            registration setup provenance.
        """
        control_id = _stable_id(
            "registration-setup-control",
            f"{convention.key}.{edition.slug}",
        )
        control = RegistrationSetupControl.objects.filter(edition=edition).first()
        created = control is None
        if control is None:
            collision = RegistrationSetupControl.objects.filter(id=control_id).first()
            if collision is not None:
                raise DemoDataConflictError(
                    f"Stable registration setup control {control_id} has "
                    "unexpected scope."
                )
            control = RegistrationSetupControl.objects.create(
                id=control_id,
                organization=organization,
                edition=edition,
                origin=RegistrationSetupOrigin.LEGACY_EXISTING,
                provenance_status=RegistrationProvenanceStatus.LEGACY_UNKNOWN,
                aggregate_version=1,
            )
        elif (
            control.organization_id != organization.id
            or control.origin != RegistrationSetupOrigin.LEGACY_EXISTING
            or control.provenance_status != RegistrationProvenanceStatus.LEGACY_UNKNOWN
            or control.aggregate_version < 1
        ):
            raise DemoDataConflictError(
                f"Registration setup control for {edition.slug!r} has "
                "unexpected provenance."
            )
        self._own("registration_setup_controls", control.id, created=created)
        return control

    def _current_demo_configuration(
        self,
        *,
        convention: ConventionSpec,
        edition: EventEdition,
        organization: Organization,
        template: RegistrationTemplate,
        actor: Account,
        base_configuration: RegistrationConfiguration,
    ) -> RegistrationConfiguration:
        """Create the complete current-edition demo form without rewriting v1.

        Parameters
        ----------
        convention : ConventionSpec
            The convention evaluated while current demo configuration.
        edition : EventEdition
            The event edition that scopes the operation.
        organization : Organization
            The organization that owns the requested resource.
        template : RegistrationTemplate
            The immutable starter or template used as the copy source.
        actor : Account
            The authenticated account authorizing the operation.
        base_configuration : RegistrationConfiguration
            The base configuration evaluated while current demo configuration.

        Returns
        -------
        RegistrationConfiguration
            The resolved RegistrationConfiguration for current demo configuration.

        Raises
        ------
        DemoDataConflictError
            If the operation encounters a demo data conflict condition.
        """
        configuration_id = _stable_id(
            "registration-configuration",
            f"{convention.key}.current.full-demo.v2",
        )
        configuration = RegistrationConfiguration.objects.filter(
            id=configuration_id
        ).first()
        created = configuration is None
        if configuration is None:
            collision = RegistrationConfiguration.objects.filter(
                edition=edition,
                version=2,
            ).first()
            if collision is not None:
                raise DemoDataConflictError(
                    f"{edition.name!r} already has a non-demo registration "
                    "configuration version 2."
                )
            configuration = RegistrationConfiguration.objects.create(
                id=configuration_id,
                organization=organization,
                edition=edition,
                name=f"{edition.name} complete demonstration registration",
                version=2,
                source_template=template,
                review_required=True,
                review_note=(
                    "Synthetic annual review covering phased pricing, minors, "
                    "waiting, payment, profiles, and staff operations."
                ),
                opens_at=base_configuration.opens_at,
                closes_at=base_configuration.closes_at,
                capacity=base_configuration.capacity,
                currency=base_configuration.currency,
                minimum_age=13,
                default_payment_window_minutes=48 * 60,
                waitlist_enabled=True,
                automatic_waitlist_promotion=True,
                created_by_id=actor.id,
            )
            sections: dict[str, RegistrationSection] = {}
            for spec in self._registration_section_specs(convention):
                section = RegistrationSection.objects.create(
                    id=_stable_id(
                        "registration-section",
                        f"{convention.key}.current.full-demo.{spec['key']}",
                    ),
                    configuration=configuration,
                    **spec,
                )
                sections[str(spec["key"])] = section
                self._own("registration_sections", section.id, created=True)
            for spec in self._registration_question_specs(convention):
                values = dict(spec)
                section_key = str(values.pop("section_key"))
                question = RegistrationQuestion.objects.create(
                    id=_stable_id(
                        "registration-question",
                        f"{convention.key}.current.full-demo.{spec['key']}",
                    ),
                    configuration=configuration,
                    section=sections[section_key],
                    **values,
                )
                self._own("registration_questions", question.id, created=True)

            opens_at = configuration.opens_at
            closes_at = configuration.closes_at
            volunteer_close = min(opens_at + timedelta(days=21), closes_at)
            early_close = min(opens_at + timedelta(days=60), closes_at)
            product_specs: tuple[dict[str, object], ...] = (
                {
                    "code": "volunteer",
                    "name": "Volunteer pre-registration",
                    "description": (
                        "Reduced admission for accepted active volunteers."
                    ),
                    "price_minor": 8_000,
                    "capacity": 220,
                    "position": 10,
                    "entitlement_code": "event-admission",
                    "entitlement_name": f"{edition.name} volunteer admission",
                    "sales_open_at": opens_at,
                    "sales_close_at": volunteer_close,
                    "required_capacity_codes": ["volunteer"],
                    "eligibility_explanation": (
                        "Available after the volunteer team records an active "
                        "volunteer role."
                    ),
                    "waitlist_enabled": True,
                    "payment_window_minutes": 72 * 60,
                },
                {
                    "code": "early-bird",
                    "name": "Early-bird admission",
                    "description": "Lower public price during the early window.",
                    "price_minor": 10_000,
                    "capacity": 500,
                    "position": 20,
                    "entitlement_code": "event-admission",
                    "entitlement_name": f"{edition.name} early-bird admission",
                    "sales_open_at": volunteer_close,
                    "sales_close_at": early_close,
                    "required_capacity_codes": [],
                    "eligibility_explanation": "",
                    "waitlist_enabled": True,
                    "payment_window_minutes": 48 * 60,
                },
                {
                    "code": "weekend",
                    "name": "Normal weekend admission",
                    "description": "Standard admission after early bird closes.",
                    "price_minor": (12_000 if convention.key == "marucon" else 13_500),
                    "capacity": (900 if convention.key == "marucon" else 650),
                    "position": 30,
                    "entitlement_code": "event-admission",
                    "entitlement_name": f"{edition.name} weekend admission",
                    "sales_open_at": early_close,
                    "sales_close_at": closes_at,
                    "required_capacity_codes": [],
                    "eligibility_explanation": "",
                    "waitlist_enabled": True,
                    "payment_window_minutes": 48 * 60,
                },
                {
                    "code": "sponsor",
                    "name": "Infinity supporter admission",
                    "description": (
                        "Weekend admission with the synthetic Infinity supporter "
                        "package."
                    ),
                    "price_minor": (22_000 if convention.key == "marucon" else 24_000),
                    "capacity": 180,
                    "position": 40,
                    "entitlement_code": "infinity-ticket",
                    "entitlement_name": "Infinity Ticket Holder",
                    "sales_open_at": volunteer_close,
                    "sales_close_at": closes_at,
                    "required_capacity_codes": [],
                    "eligibility_explanation": "",
                    "waitlist_enabled": True,
                    "payment_window_minutes": 48 * 60,
                },
                {
                    "code": "guest",
                    "name": "Invited guest admission",
                    "description": (
                        "Complimentary admission derived from guest authority."
                    ),
                    "price_minor": 0,
                    "capacity": 30,
                    "position": 50,
                    "entitlement_code": "guest-admission",
                    "entitlement_name": f"{edition.name} invited guest admission",
                    "sales_open_at": opens_at,
                    "sales_close_at": closes_at,
                    "required_capacity_codes": ["guest-of-honour"],
                    "eligibility_explanation": (
                        "Available only to an invited guest recorded by staff."
                    ),
                    "waitlist_enabled": False,
                    "payment_window_minutes": None,
                },
            )
            for spec in product_specs:
                product = AdmissionProduct.objects.create(
                    id=_stable_id(
                        "registration-product",
                        f"{convention.key}.current.full-demo.{spec['code']}",
                    ),
                    configuration=configuration,
                    **spec,
                )
                self._own("admission_products", product.id, created=True)

            policy = MinorRegistrationPolicy.objects.create(
                id=_stable_id(
                    "minor-registration-policy",
                    f"{convention.key}.current.full-demo",
                ),
                configuration=configuration,
                enabled=True,
                minor_age_threshold=18,
                guardian_notice_version="demo-guardian-v1",
                jurisdiction_code="DEMO-EU",
                review_reference="DEMO-SAFEGUARDING-2026",
                reviewed_by=actor,
                reviewed_at=datetime(2026, 1, 18, 12, tzinfo=UTC),
            )
            self._own("minor_registration_policies", policy.id, created=True)
        elif (
            configuration.organization_id != organization.id
            or configuration.edition_id != edition.id
            or configuration.version != CURRENT_DEMO_CONFIGURATION_VERSION
        ):
            raise DemoDataConflictError(
                f"Stable full demo configuration {configuration_id} has "
                "unexpected scope."
            )

        if configuration.status == ConfigurationStatus.DRAFT:
            configuration = activate_configuration(
                organization_id=organization.id,
                edition_id=edition.id,
                configuration_id=configuration.id,
                actor=actor,
                reason=(
                    "Activate the reviewed synthetic full registration demonstration."
                ),
                correlation_id=_stable_id(
                    "registration-correlation",
                    f"{configuration.id}.activate",
                ),
                source_channel="demo_seed",
            )
            self.created["audit_events"] += 1
            self.created["domain_events"] += 1
            self.created["outbox_messages"] += 1
        self._own("registration_configurations", configuration.id, created=created)
        return configuration

    def _demo_registration(  # noqa: PLR0912, PLR0915
        self,
        *,
        convention: ConventionSpec,
        edition: EventEdition,
        configuration: RegistrationConfiguration,
        account: Account,
        state: str,
        product_code: str,
    ) -> Registration:
        registration_id = _stable_id(
            "registration",
            f"{convention.key}.{edition.id}.{account.id}",
        )
        registration = Registration.objects.filter(id=registration_id).first()
        created = registration is None
        if registration is None:
            participation = Participation.objects.get(
                edition=edition,
                account=account,
            )
            product = configuration.products.get(code=product_code)
            submitted_at = datetime(2026, 6, 12, 10, tzinfo=UTC)
            waitlisted_at = (
                submitted_at if state == Registration.State.WAITLISTED else None
            )
            expired_at = (
                submitted_at + timedelta(days=2)
                if state == Registration.State.EXPIRED
                else None
            )
            cancelled_at = (
                submitted_at + timedelta(days=1)
                if state == Registration.State.CANCELLED
                else None
            )
            initial_state = (
                Registration.State.PAYMENT_PENDING
                if state
                in {
                    Registration.State.CONFIRMED,
                    Registration.State.CHECKED_IN,
                }
                else state
            )
            confirmed_at = (
                datetime(2026, 6, 12, 10, 5, tzinfo=UTC)
                if state
                in {
                    Registration.State.CONFIRMED,
                    Registration.State.CHECKED_IN,
                }
                else None
            )
            registration = Registration.objects.create(
                id=registration_id,
                organization=edition.organization,
                edition=edition,
                participation=participation,
                account=account,
                configuration=configuration,
                product=product,
                reference=f"REG-{registration_id.hex[:10].upper()}",
                state=initial_state,
                aggregate_version=1,
                product_name_snapshot=product.name,
                price_minor_snapshot=product.price_minor,
                currency_snapshot=configuration.currency,
                submitted_at=submitted_at,
                waitlisted_at=waitlisted_at,
                payment_due_at=(
                    submitted_at
                    + timedelta(minutes=configuration.default_payment_window_minutes)
                    if initial_state
                    in {
                        Registration.State.PAYMENT_PENDING,
                        Registration.State.EXPIRED,
                    }
                    else None
                ),
                confirmed_at=None,
                checked_in_at=None,
                expired_at=expired_at,
                cancelled_at=cancelled_at,
            )
            answers = {
                "badge-name": account.display_name.replace(" (Demo)", ""),
                "preferred-language": convention.language_codes[0],
                "code-of-conduct": True,
            }
            if convention.key == "marucon":
                answers["bringing-fursuit"] = account.email.endswith(
                    "first-time-attendee@demo.maru.invalid"
                )
                if answers["bringing-fursuit"]:
                    answers["fursuit-species"] = "River otter"
            else:
                answers["sauna-interest"] = True
                answers["arrival-mode"] = "Train"
            schema = [
                {
                    "key": question.key,
                    "label": question.label,
                    "field_type": question.field_type,
                    "required": question.required,
                    "options": question.options,
                    "purpose": question.purpose,
                    "visibility": question.visibility,
                    "classification": question.classification,
                    "condition_question_key": question.condition_question_key,
                    "condition_value": question.condition_value,
                    "section": (
                        {
                            "key": question.section.key,
                            "title": question.section.title,
                            "description": question.section.description,
                            "position": question.section.position,
                        }
                        if question.section_id is not None
                        and question.section is not None
                        else None
                    ),
                }
                for question in configuration.questions.all()
            ]
            submission = RegistrationSubmission.objects.create(
                id=_stable_id("registration-submission", str(registration.id)),
                registration=registration,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                configuration_version=configuration.version,
                schema_snapshot=schema,
                answers=answers,
                submitted_at=submitted_at,
            )
            self._own("registration_submissions", submission.id, created=True)
            submitted_timeline = RegistrationTimelineEntry.objects.create(
                id=_stable_id(
                    "registration-timeline",
                    f"{registration.id}.submitted",
                ),
                registration=registration,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                sequence=1,
                kind="registration_submitted",
                title="Registration submitted",
                summary=f"{product.name} selected.",
                audience=RegistrationTimelineEntry.Audience.ATTENDEE_AND_STAFF,
                occurred_at=submitted_at,
                actor_kind="account",
                actor_id=account.id,
                correlation_id=_stable_id(
                    "registration-correlation",
                    f"{registration.id}.submitted",
                ),
            )
            self._own(
                "registration_timeline_entries",
                submitted_timeline.id,
                created=True,
            )
            if confirmed_at is not None:
                if product.price_minor:
                    payment = PaymentAttempt.objects.create(
                        id=_stable_id("registration-payment", str(registration.id)),
                        registration=registration,
                        organization_id=edition.organization_id,
                        edition_id=edition.id,
                        provider="demo",
                        provider_reference=f"seed-{registration.id}",
                        idempotency_key=_stable_id(
                            "registration-payment-idempotency",
                            str(registration.id),
                        ),
                        amount_minor=product.price_minor,
                        currency=configuration.currency,
                        status=PaymentAttempt.Status.SUCCEEDED,
                        occurred_at=confirmed_at,
                        safe_result_code="demo_payment_succeeded",
                    )
                    self._own("payment_attempts", payment.id, created=True)
                registration.state = Registration.State.CONFIRMED
                registration.aggregate_version = 2
                registration.confirmed_at = confirmed_at
                registration.confirmation_basis = (
                    Registration.ConfirmationBasis.PROVIDER
                    if product.price_minor
                    else Registration.ConfirmationBasis.FREE
                )
                registration.save(
                    update_fields=(
                        "state",
                        "aggregate_version",
                        "confirmed_at",
                        "confirmation_basis",
                        "updated_at",
                    )
                )
                entitlement = Entitlement.objects.create(
                    id=_stable_id("registration-entitlement", str(registration.id)),
                    registration=registration,
                    organization_id=edition.organization_id,
                    edition_id=edition.id,
                    code=product.entitlement_code,
                    label_snapshot=product.entitlement_name,
                    granted_at=confirmed_at,
                )
                self._own("entitlements", entitlement.id, created=True)
                confirmed_timeline = RegistrationTimelineEntry.objects.create(
                    id=_stable_id(
                        "registration-timeline",
                        f"{registration.id}.confirmed",
                    ),
                    registration=registration,
                    organization_id=edition.organization_id,
                    edition_id=edition.id,
                    sequence=2,
                    kind="payment_confirmed",
                    title="Payment confirmed",
                    summary="The demo provider result was reconciled.",
                    audience=RegistrationTimelineEntry.Audience.ATTENDEE_AND_STAFF,
                    occurred_at=confirmed_at,
                    actor_kind="provider",
                    actor_id=None,
                    correlation_id=_stable_id(
                        "registration-correlation",
                        f"{registration.id}.confirmed",
                    ),
                )
                self._own(
                    "registration_timeline_entries",
                    confirmed_timeline.id,
                    created=True,
                )
                if state == Registration.State.CHECKED_IN:
                    checked_in_at = confirmed_at + timedelta(days=1)
                    registration.state = Registration.State.CHECKED_IN
                    registration.aggregate_version = 3
                    registration.checked_in_at = checked_in_at
                    registration.save(
                        update_fields=(
                            "state",
                            "aggregate_version",
                            "checked_in_at",
                            "updated_at",
                        )
                    )
                    check_in = CheckInRecord.objects.create(
                        id=_stable_id(
                            "registration-check-in",
                            str(registration.id),
                        ),
                        registration=registration,
                        organization_id=edition.organization_id,
                        edition_id=edition.id,
                        actor_id=account.id,
                        checked_in_at=checked_in_at,
                        method="demo_front_desk",
                        reason="Synthetic arrival example.",
                    )
                    self._own("check_in_records", check_in.id, created=True)
                    checked_timeline = RegistrationTimelineEntry.objects.create(
                        id=_stable_id(
                            "registration-timeline",
                            f"{registration.id}.checked-in",
                        ),
                        registration=registration,
                        organization_id=edition.organization_id,
                        edition_id=edition.id,
                        sequence=3,
                        kind="checked_in",
                        title="Checked in",
                        summary="Front Desk completed the synthetic arrival.",
                        audience=(
                            RegistrationTimelineEntry.Audience.ATTENDEE_AND_STAFF
                        ),
                        occurred_at=checked_in_at,
                        actor_kind="account",
                        actor_id=account.id,
                        correlation_id=_stable_id(
                            "registration-correlation",
                            f"{registration.id}.checked-in",
                        ),
                    )
                    self._own(
                        "registration_timeline_entries",
                        checked_timeline.id,
                        created=True,
                    )
            elif state != Registration.State.PAYMENT_PENDING:
                state_labels: dict[str, tuple[str, str]] = {
                    Registration.State.GUARDIAN_PENDING: (
                        "Guardian consent requested",
                        "Payment remains unavailable until consent is accepted.",
                    ),
                    Registration.State.WAITLISTED: (
                        "Added to waiting list",
                        "No capacity is held and no payment is requested.",
                    ),
                    Registration.State.EXPIRED: (
                        "Payment window expired",
                        "The synthetic reservation expired and released capacity.",
                    ),
                    Registration.State.CANCELLED: (
                        "Registration cancelled",
                        "The synthetic attendee cancelled this registration.",
                    ),
                }
                title, summary = state_labels[state]
                state_timeline = RegistrationTimelineEntry.objects.create(
                    id=_stable_id(
                        "registration-timeline",
                        f"{registration.id}.{state}",
                    ),
                    registration=registration,
                    organization_id=edition.organization_id,
                    edition_id=edition.id,
                    sequence=2,
                    kind=state,
                    title=title,
                    summary=summary,
                    audience=RegistrationTimelineEntry.Audience.ATTENDEE_AND_STAFF,
                    occurred_at=(
                        waitlisted_at or expired_at or cancelled_at or submitted_at
                    ),
                    actor_kind="system",
                    actor_id=None,
                    correlation_id=_stable_id(
                        "registration-correlation",
                        f"{registration.id}.{state}",
                    ),
                )
                self._own(
                    "registration_timeline_entries",
                    state_timeline.id,
                    created=True,
                )
        elif (
            registration.organization_id != edition.organization_id
            or registration.edition_id != edition.id
            or registration.account_id != account.id
        ):
            raise DemoDataConflictError(
                f"Stable demo registration {registration_id} has unexpected scope."
            )
        profile_id = _stable_id("attendee-registration-profile", str(registration.id))
        profile = AttendeeRegistrationProfile.objects.filter(id=profile_id).first()
        profile_created = profile is None
        is_fursuiter = "first-time-attendee" in account.email
        demo_country_codes = ("HU", "AT", "DE", "SK", "CZ", "PL", "HR", "FI")
        demo_country_code = demo_country_codes[
            int(account.id.hex[:8], 16) % len(demo_country_codes)
        ]
        if profile is None:
            directory_visible = registration.state in {
                Registration.State.CONFIRMED,
                Registration.State.CHECKED_IN,
            }
            profile = AttendeeRegistrationProfile.objects.create(
                id=profile_id,
                registration=registration,
                organization=edition.organization,
                edition=edition,
                account=account,
                real_name=account.display_name.replace(" (Demo)", ""),
                date_of_birth=(
                    date(2010, 5, 20)
                    if state == Registration.State.GUARDIAN_PENDING
                    else date(1995, 5, 20)
                ),
                address_line_1="12 Synthetic Convention Street",
                address_line_2="",
                locality="Budapest",
                postal_code="1051",
                region="Budapest",
                country_code=demo_country_code,
                emergency_contact_name="Synthetic Emergency Contact",
                emergency_contact_phone="+36 20 555 0199",
                phone_number="+36 30 555 0123",
                telegram_handle=f"{convention.key}_{account.id.hex[:8]}",
                pronoun_code="they_them",
                other_pronouns="",
                pronouns="they/them",
                bio=(
                    "Friendly first-time attendee who enjoys meeting new people."
                    if is_fursuiter
                    else ""
                ),
                spoken_language_codes=["en", "hu"],
                brings_fursuits=is_fursuiter,
                directory_visible=directory_visible,
                directory_country_code=(demo_country_code if directory_visible else ""),
                directory_consent_version=(
                    DIRECTORY_CONSENT_VERSION if directory_visible else ""
                ),
                directory_consent_at=(
                    registration.confirmed_at if directory_visible else None
                ),
                collection_notice_version=COLLECTION_NOTICE_VERSION,
            )
        elif (
            profile.registration_id != registration.id
            or profile.edition_id != edition.id
            or profile.account_id != account.id
        ):
            raise DemoDataConflictError(
                f"Stable demo attendee profile {profile_id} has unexpected scope."
            )
        elif profile.address_line_1 == "12 Synthetic Convention Street" and (
            profile.spoken_language_codes or profile.directory_visible
        ):
            directory_visible = profile.directory_visible
            changed_fields: list[str] = []
            if directory_visible and not profile.spoken_language_codes:
                profile.spoken_language_codes = ["en", "hu"]
                changed_fields.append("spoken_language_codes")
            if (
                profile.country_code == "HU"
                and profile.country_code != demo_country_code
            ):
                profile.country_code = demo_country_code
                changed_fields.append("country_code")
            expected_directory_country = demo_country_code if directory_visible else ""
            expected_consent_version = (
                DIRECTORY_CONSENT_VERSION if directory_visible else ""
            )
            if (
                profile.directory_consent_version != expected_consent_version
                and not profile.directory_country_code
            ):
                profile.directory_country_code = expected_directory_country
                profile.directory_consent_version = expected_consent_version
                changed_fields.extend(
                    ("directory_country_code", "directory_consent_version")
                )
            if profile.collection_notice_version != COLLECTION_NOTICE_VERSION:
                profile.collection_notice_version = COLLECTION_NOTICE_VERSION
                changed_fields.append("collection_notice_version")
            if changed_fields:
                profile.aggregate_version += 1
                profile.save(
                    update_fields=(
                        *changed_fields,
                        "aggregate_version",
                        "updated_at",
                    )
                )
        if is_fursuiter:
            fursuit_id = _stable_id("attendee-fursuit", str(profile.id))
            fursuit = AttendeeFursuit.objects.filter(id=fursuit_id).first()
            migrated_fursuit = (
                AttendeeFursuit.objects.filter(
                    profile=profile,
                    position=0,
                    is_active=True,
                )
                .order_by("id")
                .first()
            )
            if (
                fursuit is not None
                and migrated_fursuit is not None
                and fursuit.id != migrated_fursuit.id
            ):
                raise DemoDataConflictError(
                    f"Demo attendee profile {profile.id} has two position-zero "
                    "fursuits."
                )
            fursuit = fursuit or migrated_fursuit
            fursuit_created = False
            if fursuit is None:
                fursuit = AttendeeFursuit.objects.create(
                    id=fursuit_id,
                    profile=profile,
                    registration=registration,
                    organization=edition.organization,
                    edition=edition,
                    account=account,
                    position=0,
                    name="Riverlight",
                    species="River otter",
                )
                fursuit_created = True
            elif (
                fursuit.profile_id != profile.id
                or fursuit.registration_id != registration.id
                or fursuit.organization_id != edition.organization_id
                or fursuit.edition_id != edition.id
                or fursuit.account_id != account.id
            ):
                raise DemoDataConflictError(
                    f"Demo attendee fursuit {fursuit.id} has unexpected scope."
                )
            self._own(
                "attendee_fursuits",
                fursuit.id,
                created=fursuit_created,
            )
            second_fursuit_id = _stable_id(
                "attendee-fursuit",
                f"{profile.id}.second",
            )
            second_fursuit = AttendeeFursuit.objects.filter(
                id=second_fursuit_id
            ).first()
            migrated_second_fursuit = (
                AttendeeFursuit.objects.filter(
                    profile=profile,
                    position=1,
                    is_active=True,
                )
                .order_by("id")
                .first()
            )
            if (
                second_fursuit is not None
                and migrated_second_fursuit is not None
                and second_fursuit.id != migrated_second_fursuit.id
            ):
                raise DemoDataConflictError(
                    f"Demo attendee profile {profile.id} has two position-one fursuits."
                )
            second_fursuit = second_fursuit or migrated_second_fursuit
            second_created = False
            if second_fursuit is None:
                second_fursuit = AttendeeFursuit.objects.create(
                    id=second_fursuit_id,
                    profile=profile,
                    registration=registration,
                    organization=edition.organization,
                    edition=edition,
                    account=account,
                    position=1,
                    name="Starlight",
                    species="Clouded leopard",
                )
                second_created = True
            if (
                second_fursuit.profile_id != profile.id
                or second_fursuit.registration_id != registration.id
                or second_fursuit.account_id != account.id
            ):
                raise DemoDataConflictError(
                    f"Demo attendee fursuit {second_fursuit.id} has unexpected scope."
                )
            self._own(
                "attendee_fursuits",
                second_fursuit.id,
                created=second_created,
            )
        self._own("registrations", registration.id, created=created)
        self._own(
            "attendee_registration_profiles",
            profile.id,
            created=profile_created,
        )
        return registration

    def _profile_extension_example(
        self,
        *,
        convention: ConventionSpec,
        edition: EventEdition,
        administrator: Account,
        registration: Registration,
    ) -> None:
        """Populate the versioned extension catalog and one current value.

        Parameters
        ----------
        convention : ConventionSpec
            The convention evaluated while profile extension example.
        edition : EventEdition
            The event edition that scopes the operation.
        administrator : Account
            The platform administrator authorizing the privileged action.
        registration : Registration
            The attendee registration governed by the operation.

        Raises
        ------
        DemoDataConflictError
            If the operation encounters a demo data conflict condition.
        """
        field_id = _stable_id(
            "registration-profile-extension-field",
            f"{convention.key}.{edition.id}.arrival-detail.v1",
        )
        field = RegistrationProfileExtensionField.objects.filter(id=field_id).first()
        field_created = field is None
        if field is None:
            field = RegistrationProfileExtensionField.objects.create(
                id=field_id,
                organization=edition.organization,
                edition=edition,
                key="arrival-detail",
                version=1,
                label="Additional arrival detail",
                help_text="Synthetic attendee/staff completion example.",
                field_type=QuestionFieldType.SHORT_TEXT,
                purpose="Complete a missing current arrival detail.",
                classification=QuestionClassification.PERSONAL,
                attendee_visible=True,
                writer_policy=ProfileExtensionWriter.ATTENDEE_AND_STAFF,
                required=False,
                position=10,
                review_status=ProfileExtensionReviewStatus.APPROVED,
                status=ProfileExtensionStatus.ACTIVE,
                created_by=administrator,
                approved_by=administrator,
                approved_at=datetime(2026, 6, 13, 9, tzinfo=UTC),
            )
        elif (
            field.organization_id != edition.organization_id
            or field.edition_id != edition.id
            or field.key != "arrival-detail"
        ):
            raise DemoDataConflictError(
                f"Stable profile extension field {field_id} has unexpected scope."
            )
        self._own(
            "registration_profile_extension_fields",
            field.id,
            created=field_created,
        )

        revision = (
            RegistrationProfileExtensionValueRevision.objects.filter(
                registration=registration,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                field_key=field.key,
            )
            .order_by("-sequence", "-id")
            .first()
        )
        revision_created = revision is None
        if revision is None:
            correlation_id = _stable_id(
                "registration-profile-extension-value-correlation",
                f"{registration.id}.{field.key}.1",
            )
            result = append_profile_extension_value(
                actor=registration.account,
                organization_id=edition.organization_id,
                edition_id=edition.id,
                registration_id=registration.id,
                field_id=field.id,
                value="Synthetic arrival detail",
                expected_sequence=0,
                retry_key=_stable_id(
                    "registration-profile-extension-value-retry",
                    f"{registration.id}.{field.key}.1",
                ),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="demo_seed",
            )
            revision = RegistrationProfileExtensionValueRevision.objects.get(
                pk=result.revision_id
            )
        elif (
            revision.registration_id != registration.id
            or revision.field_id != field.id
            or revision.sequence != 1
            or revision.value != "Synthetic arrival detail"
        ):
            raise DemoDataConflictError(
                "The demo profile-extension value has unexpected history."
            )
        self._own(
            "registration_profile_extension_value_revisions",
            revision.id,
            created=revision_created,
        )

    def _advance_lifecycle(
        self,
        *,
        edition: EventEdition,
        target: str,
        actor: Account,
    ) -> None:
        edition.refresh_from_db()
        if edition.lifecycle == EventEdition.Lifecycle.CANCELLED:
            return
        try:
            current_index = LIFECYCLE_PATH.index(edition.lifecycle)
            target_index = LIFECYCLE_PATH.index(target)
        except ValueError as error:
            raise DemoDataConflictError(
                f"Edition {edition.name!r} has an unsupported lifecycle state."
            ) from error
        if current_index >= target_index:
            return

        for next_state in LIFECYCLE_PATH[current_index + 1 : target_index + 1]:
            edition = transition_edition(
                organization_id=edition.organization_id,
                edition_id=edition.id,
                to_state=next_state,
                actor=actor,
                reason=(
                    f"Synthetic demo fixture lifecycle progression to {next_state}."
                ),
                correlation_id=_stable_id(
                    "lifecycle-correlation",
                    f"{edition.id}.{next_state}",
                ),
                source_channel="demo_seed",
            )
            self.created["lifecycle_transitions"] += 1
            self.created["audit_events"] += 1
            self.created["domain_events"] += 1
            self.created["outbox_messages"] += 1

    @staticmethod
    def _participates(persona: PersonaSpec, edition_key: str) -> bool:
        if edition_key == "past":
            return persona.past
        if edition_key == "current":
            return persona.current
        if edition_key == "future":
            return persona.future
        return False

    def run(self) -> DemoSeedSummary:  # noqa: PLR0912, PLR0915
        administrator = self._account(
            key="administrator",
            email=DEMO_ADMIN_EMAIL,
            display_name="Maru Demo Administrator",
            language="en",
            is_staff=True,
            is_superuser=True,
        )
        personas = _personas()
        personas_by_key = {persona.key: persona for persona in personas}
        demo_organization_ids: set[UUID] = set()
        demo_edition_ids: set[UUID] = set()

        for convention in CONVENTIONS:
            organization = self._organization(convention)
            demo_organization_ids.add(organization.id)
            series = self._series(spec=convention, organization=organization)
            editions = {
                spec.key: self._edition(
                    convention=convention,
                    spec=spec,
                    organization=organization,
                    series=series,
                )
                for spec in convention.editions
            }
            demo_edition_ids.update(edition.id for edition in editions.values())
            roles = {
                authority: self._role_bundle(
                    convention=convention,
                    organization=organization,
                    authority=authority,
                )
                for authority in ROLE_DEFINITIONS
            }
            starter_roles = {
                position.code: self._starter_role_bundle(
                    convention=convention,
                    organization=organization,
                    code=position.code,
                    name=position.name,
                    capability_codes=position.capability_codes,
                )
                for position in STARTER_POSITIONS
            }
            accounts: dict[str, Account] = {}

            for persona in personas:
                account_key = (
                    persona.shared_account_key or f"{convention.key}.{persona.key}"
                )
                shared = persona.shared_account_key is not None
                email = (
                    f"{account_key}@demo.maru.invalid"
                    if shared
                    else f"{convention.key}.{persona.key}@demo.maru.invalid"
                )
                display_name = (
                    f"{persona.title} (Shared Demo)"
                    if shared
                    else f"{convention.short_name} {persona.title} (Demo)"
                )
                account = self._account(
                    key=account_key,
                    email=email,
                    display_name=display_name,
                    language="en" if shared else convention.language,
                )
                accounts[persona.key] = account
                if persona.key == "convention-chair":
                    self.featured_logins.append(account.email)
                if convention.key == "marucon" and persona.key == "standard-attendee":
                    self.featured_logins.append(account.email)
                self._membership(
                    convention=convention,
                    persona=persona,
                    organization=organization,
                    account=account,
                )

                if persona.authority == "board":
                    self._role_assignment(
                        convention=convention,
                        persona=persona,
                        organization=organization,
                        edition=None,
                        account=account,
                        role=roles["board"],
                        granted_by=administrator,
                    )

                for edition_spec in convention.editions:
                    if not self._participates(persona, edition_spec.key):
                        continue
                    edition = editions[edition_spec.key]
                    participation = self._participation(
                        convention=convention,
                        persona=persona,
                        edition_spec=edition_spec,
                        organization=organization,
                        edition=edition,
                        account=account,
                    )
                    for capacity in persona.capacities:
                        self._participation_capacity(
                            convention=convention,
                            persona=persona,
                            edition_spec=edition_spec,
                            participation=participation,
                            capacity=capacity,
                        )
                    if persona.authority is not None and persona.authority != "board":
                        self._role_assignment(
                            convention=convention,
                            persona=persona,
                            organization=organization,
                            edition=edition,
                            account=account,
                            role=roles[persona.authority],
                            granted_by=administrator,
                        )
                        if (
                            edition_spec.key == "current"
                            and persona.key == "registration-lead"
                        ):
                            self._role_assignment(
                                convention=convention,
                                persona=persona,
                                organization=organization,
                                edition=edition,
                                account=account,
                                role=roles["volunteer"],
                                granted_by=administrator,
                            )

            self._executive_board_representation(
                convention=convention,
                organization=organization,
                administrator=administrator,
                accounts=accounts,
            )
            lifecycle_actor = accounts["convention-chair"]
            for persona_key, role_code in (
                ("convention-chair", "convention-chair"),
                ("board-chair", "board-member"),
                ("registration-lead", "registration-lead"),
                ("front-desk-volunteer", "front-desk"),
                ("treasurer", "treasurer"),
            ):
                self._role_assignment(
                    convention=convention,
                    persona=personas_by_key[persona_key],
                    organization=organization,
                    edition=editions["current"],
                    account=accounts[persona_key],
                    role=starter_roles[role_code],
                    granted_by=administrator,
                )
            for capability_code in (
                "authorization.manage_roles",
                "authorization.revoke",
            ):
                self._capability_grant(
                    convention=convention,
                    organization=organization,
                    edition=None,
                    account=lifecycle_actor,
                    capability_code=capability_code,
                    granted_by=administrator,
                )
            self._capability_grant(
                convention=convention,
                organization=organization,
                edition=None,
                account=accounts["board-chair"],
                capability_code="authorization.manage_roles",
                granted_by=administrator,
            )
            for capability_code in (
                "registration.manage_configuration",
                "registration.view_service_summary",
                "registration.view_profile_extensions",
                "registration.update_profile_extensions",
                "registration.view_attendee_reporting",
                "registration.moderate_public_profile",
                "registration.check_in",
                "registration.view_payment_summary",
                "registration.manage_exceptions",
                "registration.manage_finance",
                "identity.manage_restrictions",
                "privacy.manage_requests",
                "accreditation.issue",
                "accreditation.revoke",
                "accreditation.manage_offline",
            ):
                self._capability_grant(
                    convention=convention,
                    organization=organization,
                    edition=editions["current"],
                    account=accounts["convention-chair"],
                    capability_code=capability_code,
                    granted_by=administrator,
                )
            for capability_code in (
                "registration.view_service_summary",
                "registration.view_profile_extensions",
                "registration.update_profile_extensions",
                "registration.view_attendee_reporting",
                "registration.moderate_public_profile",
                "registration.check_in",
                "registration.view_payment_summary",
                "registration.manage_exceptions",
                "registration.manage_finance",
                "identity.manage_restrictions",
                "privacy.manage_requests",
                "accreditation.issue",
                "accreditation.revoke",
                "accreditation.manage_offline",
            ):
                self._capability_grant(
                    convention=convention,
                    organization=organization,
                    edition=editions["current"],
                    account=accounts["registration-lead"],
                    capability_code=capability_code,
                    granted_by=administrator,
                )
            self._capability_grant(
                convention=convention,
                organization=organization,
                edition=editions["future"],
                account=accounts["convention-chair"],
                capability_code="registration.manage_configuration",
                granted_by=administrator,
            )
            seed_workforce_examples(
                convention_key=convention.key,
                organization=organization,
                edition=editions["current"],
                accounts=accounts,
                own=self._own,
                happened_at=datetime(2026, 6, 12, 10, 5, tzinfo=UTC),
            )
            template = self._registration_template(
                convention=convention,
                organization=organization,
                series=series,
                actor=accounts["convention-chair"],
            )
            configurations: dict[str, RegistrationConfiguration] = {}
            for edition_spec in convention.editions:
                configuration_id = _stable_id(
                    "registration-configuration",
                    f"{convention.key}.{edition_spec.key}.v1",
                )
                if (
                    editions[edition_spec.key].lifecycle
                    == EventEdition.Lifecycle.ARCHIVED
                    and not RegistrationConfiguration.objects.filter(
                        id=configuration_id
                    ).exists()
                ):
                    continue
                source_edition: EventEdition | None = None
                if edition_spec.key == "current":
                    source_edition = editions["past"]
                elif edition_spec.key == "future" and convention.key == "marucon":
                    source_edition = editions["current"]
                configurations[edition_spec.key] = self._registration_configuration(
                    convention=convention,
                    edition_spec=edition_spec,
                    edition=editions[edition_spec.key],
                    organization=organization,
                    template=template,
                    actor=accounts["convention-chair"],
                    source_edition=source_edition,
                )
            configurations["current"] = self._current_demo_configuration(
                convention=convention,
                edition=editions["current"],
                organization=organization,
                template=template,
                actor=accounts["convention-chair"],
                base_configuration=configurations["current"],
            )
            for edition_key in configurations:
                self._registration_setup_control(
                    convention=convention,
                    edition=editions[edition_key],
                    organization=organization,
                )
            registrations: dict[str, Registration] = {}
            registration_specs = (
                (
                    "sponsor-attendee",
                    Registration.State.CONFIRMED,
                    "sponsor",
                ),
                (
                    "first-time-attendee",
                    (
                        Registration.State.PAYMENT_PENDING
                        if convention.key == "marucon"
                        else Registration.State.GUARDIAN_PENDING
                    ),
                    "weekend" if convention.key == "marucon" else "early-bird",
                ),
                (
                    "guest-of-honour",
                    Registration.State.CHECKED_IN,
                    "guest",
                ),
                (
                    "standard-attendee",
                    Registration.State.WAITLISTED,
                    "early-bird",
                ),
                (
                    "dealer-assistant",
                    Registration.State.EXPIRED,
                    "weekend",
                ),
                (
                    "cancelled-attendee",
                    Registration.State.CANCELLED,
                    "weekend",
                ),
                (
                    "registration-volunteer",
                    Registration.State.CONFIRMED,
                    "volunteer",
                ),
                (
                    "volunteer-applicant",
                    Registration.State.GUARDIAN_PENDING,
                    "early-bird",
                ),
            )
            for persona_key, state, product_code in registration_specs:
                registrations[persona_key] = self._demo_registration(
                    convention=convention,
                    edition=editions["current"],
                    configuration=configurations["current"],
                    account=accounts[persona_key],
                    state=state,
                    product_code=product_code,
                )
            self._profile_extension_example(
                convention=convention,
                edition=editions["current"],
                administrator=administrator,
                registration=registrations["sponsor-attendee"],
            )
            for edition_spec in convention.editions:
                self._advance_lifecycle(
                    edition=editions[edition_spec.key],
                    target=edition_spec.lifecycle,
                    actor=lifecycle_actor,
                )
            seed_operational_examples(
                convention_key=convention.key,
                organization=organization,
                editions=editions,
                configurations=configurations,
                accounts=accounts,
                registrations=registrations,
                administrator=administrator,
                own=self._own,
            )

        totals = {
            kind: len(object_ids) for kind, object_ids in sorted(self.owned.items())
        }
        totals.update(
            {
                "lifecycle_transitions": EditionLifecycleTransition.objects.filter(
                    edition_id__in=demo_edition_ids
                ).count(),
                "audit_events": AuditEvent.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "domain_events": DomainEvent.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "outbox_messages": OutboxMessage.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "registration_templates": RegistrationTemplate.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "registration_template_questions": (
                    RegistrationTemplateQuestion.objects.filter(
                        template__organization_id__in=demo_organization_ids
                    ).count()
                ),
                "registration_template_sections": (
                    RegistrationTemplateSection.objects.filter(
                        template__organization_id__in=demo_organization_ids
                    ).count()
                ),
                "registration_template_products": (
                    RegistrationTemplateProduct.objects.filter(
                        template__organization_id__in=demo_organization_ids
                    ).count()
                ),
                "registration_configurations": (
                    RegistrationConfiguration.objects.filter(
                        organization_id__in=demo_organization_ids
                    ).count()
                ),
                "registration_questions": RegistrationQuestion.objects.filter(
                    configuration__organization_id__in=demo_organization_ids
                ).count(),
                "registration_sections": RegistrationSection.objects.filter(
                    configuration__organization_id__in=demo_organization_ids
                ).count(),
                "admission_products": AdmissionProduct.objects.filter(
                    configuration__organization_id__in=demo_organization_ids
                ).count(),
                "registrations": Registration.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "attendee_registration_profiles": (
                    AttendeeRegistrationProfile.objects.filter(
                        organization_id__in=demo_organization_ids
                    ).count()
                ),
                "attendee_fursuits": AttendeeFursuit.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "minor_registration_policies": (
                    MinorRegistrationPolicy.objects.filter(
                        configuration__organization_id__in=demo_organization_ids
                    ).count()
                ),
                "registration_submissions": (
                    RegistrationSubmission.objects.filter(
                        organization_id__in=demo_organization_ids
                    ).count()
                ),
                "registration_profile_extension_fields": (
                    RegistrationProfileExtensionField.objects.filter(
                        organization_id__in=demo_organization_ids
                    ).count()
                ),
                "registration_profile_extension_value_revisions": (
                    RegistrationProfileExtensionValueRevision.objects.filter(
                        organization_id__in=demo_organization_ids
                    ).count()
                ),
                "payment_attempts": PaymentAttempt.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "entitlements": Entitlement.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "check_in_records": CheckInRecord.objects.filter(
                    organization_id__in=demo_organization_ids
                ).count(),
                "registration_timeline_entries": (
                    RegistrationTimelineEntry.objects.filter(
                        organization_id__in=demo_organization_ids
                    ).count()
                ),
            }
        )
        return DemoSeedSummary(
            created=dict(sorted(self.created.items())),
            totals=dict(sorted(totals.items())),
            featured_logins=tuple(self.featured_logins),
            passwords_reset=self.passwords_reset,
        )


@transaction.atomic
def seed_demo_data(
    *,
    password: str,
    reset_passwords: bool = False,
) -> DemoSeedSummary:
    """Create or verify the local-only synthetic fixture atomically.

    Parameters
    ----------
    password : str
        The plaintext secret to verify without logging or retaining it.
    reset_passwords : bool, default=False
        The reset passwords evaluated while seed demo data.

    Returns
    -------
    DemoSeedSummary
        The resolved DemoSeedSummary for seed demo data.
    """
    return _DemoSeeder(
        password=password,
        reset_passwords=reset_passwords,
    ).run()
