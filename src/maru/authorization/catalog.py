"""Versioned, code-owned capability declarations."""

from dataclasses import dataclass
from enum import StrEnum


class ScopeLevel(StrEnum):
    """Enumerate supported scope level values."""

    ORGANIZATION = "organization"
    EDITION = "edition"
    DEPARTMENT = "department"
    RESOURCE = "resource"


class Sensitivity(StrEnum):
    """Enumerate supported sensitivity values."""

    PUBLIC = "C0"
    INTERNAL = "C1"
    PERSONAL = "C2"
    RESTRICTED = "C3"
    SECURITY_CRITICAL = "C4"


@dataclass(frozen=True, slots=True)
class Capability:
    """Describe capability.

    Attributes
    ----------
    code
        The stable domain code to resolve or validate.
    description
        The human-readable description shown to authorized readers.
    maximum_scope
        The maximum scope retained in this immutable projection.
    persistable
        The persistable retained in this immutable projection.
    field_ceiling
        The field ceiling retained in this immutable projection.
    sensitivity_ceiling
        The non-negative hard limit or requested amount for sensitivity ceiling.
    delegable
        The delegable retained in this immutable projection.
    allow_self
        Whether to allow self.
    requires_break_glass
        The requires break glass retained in this immutable projection.
    obligations
        The obligations retained in this immutable projection.
    """

    code: str
    description: str
    maximum_scope: ScopeLevel
    persistable: bool = True
    field_ceiling: frozenset[str] = frozenset()
    sensitivity_ceiling: Sensitivity = Sensitivity.INTERNAL
    delegable: bool = False
    allow_self: bool = False
    requires_break_glass: bool = False
    obligations: frozenset[str] = frozenset()


EDITION_BASIC_FIELD_CEILING = frozenset(
    {
        "id",
        "organization_id",
        "series_id",
        "slug",
        "name",
        "lifecycle",
        "aggregate_version",
        "time_zone",
        "language_codes",
        "currency_codes",
        "starts_on",
        "ends_on",
    }
)


CAPABILITY_DEFINITIONS = (
    Capability(
        code="organizations.view_basic",
        description="View the organizer profile and its recurring convention brands.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=True,
        field_ceiling=frozenset(
            {
                "id",
                "slug",
                "name",
                "lifecycle",
                "description",
                "legal_name",
                "legal_address",
                "legal_representative",
                "registration_authority",
                "registration_identifier",
                "tax_identifier",
                "imprint_text",
                "website_url",
                "contact_email",
                "contact_phone",
                "country_code",
                "default_language_codes",
                "default_time_zone",
            }
        ),
    ),
    Capability(
        code="organizations.change_profile",
        description="Change the bounded legal and operational organizer profile.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="organizations.create_series",
        description="Create a recurring convention brand for an organizer.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="organizations.change_series",
        description="Change a recurring convention brand owned by an organizer.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="organizations.manage_representation",
        description=(
            "Invite, activate, replace, or end accountable Executive Board terms."
        ),
        maximum_scope=ScopeLevel.ORGANIZATION,
        sensitivity_ceiling=Sensitivity.SECURITY_CRITICAL,
        delegable=False,
        obligations=frozenset({"reason", "audit", "approval"}),
    ),
    Capability(
        code="events.view_basic",
        description="View non-public basic metadata for an authorized event edition.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=True,
        field_ceiling=EDITION_BASIC_FIELD_CEILING,
    ),
    Capability(
        code="events.create",
        description="Create a Draft event edition beneath an authorized series.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        field_ceiling=EDITION_BASIC_FIELD_CEILING,
        delegable=False,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="events.change_profile",
        description=(
            "Change bounded Draft or Preparing edition identity, dates, and locale."
        ),
        maximum_scope=ScopeLevel.EDITION,
        field_ceiling=EDITION_BASIC_FIELD_CEILING,
        delegable=False,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="events.transition",
        description="Move an edition through an authorized lifecycle transition.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="participation.view_self",
        description="View one's own edition participation and safe history.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "edition",
                "status",
                "capacities",
                "public_history_visible",
            }
        ),
    ),
    Capability(
        code="participation.view_staff_summary",
        description="View a minimized participant summary for assigned staff work.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "account_id",
                "display_name",
                "participation_status",
                "capacity_labels",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="authorization.delegate",
        description="Delegate capabilities already held within a narrower scope.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="authorization.grant_direct",
        description=(
            "Create root capability grants under an independent approver's control."
        ),
        maximum_scope=ScopeLevel.ORGANIZATION,
        sensitivity_ceiling=Sensitivity.SECURITY_CRITICAL,
        delegable=False,
        obligations=frozenset({"reason", "audit", "approval"}),
    ),
    Capability(
        code="authorization.revoke",
        description=(
            "Immediately revoke capability grants and role assignments in scope."
        ),
        maximum_scope=ScopeLevel.ORGANIZATION,
        sensitivity_ceiling=Sensitivity.SECURITY_CRITICAL,
        delegable=False,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="authorization.manage_roles",
        description=(
            "Version role bundles and assign them under independent approval."
        ),
        maximum_scope=ScopeLevel.ORGANIZATION,
        sensitivity_ceiling=Sensitivity.SECURITY_CRITICAL,
        delegable=False,
        obligations=frozenset({"reason", "audit", "approval"}),
    ),
    Capability(
        code="effects.replay",
        description="Replay quarantined asynchronous work for one organization.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        sensitivity_ceiling=Sensitivity.SECURITY_CRITICAL,
        delegable=False,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="identity.manage_restrictions",
        description=(
            "Issue, revoke, and review organizer- or edition-scoped account "
            "restrictions without exposing sensitive case detail."
        ),
        maximum_scope=ScopeLevel.EDITION,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        delegable=False,
        obligations=frozenset({"reason", "audit", "approval"}),
    ),
    Capability(
        code="privacy.manage_requests",
        description=(
            "Verify and route subject-rights, post-edition corrections, exports, "
            "and retention decisions."
        ),
        maximum_scope=ScopeLevel.ORGANIZATION,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        delegable=False,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="audit.view_security",
        description="View minimized security audit metadata.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset(
            {
                "id",
                "occurred_at",
                "principal_kind",
                "principal_id",
                "event_edition_id",
                "capability_code",
                "operation",
                "target_type",
                "target_id",
                "outcome",
                "reason_code",
                "correlation_id",
                "source_channel",
                "delegated",
                "elevated",
                "break_glass",
            }
        ),
        obligations=frozenset({"reason", "audit_sensitive_read"}),
    ),
    Capability(
        code="registration.manage_configuration",
        description=(
            "Create, inherit, review, activate, and template edition registration "
            "configuration."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        field_ceiling=frozenset(
            {
                "id",
                "name",
                "version",
                "status",
                "source_summary",
                "review_required",
                "review_note",
                "opens_at",
                "closes_at",
                "capacity",
                "currency",
                "minimum_age",
                "default_payment_window_minutes",
                "waitlist_enabled",
                "automatic_waitlist_promotion",
                "questions",
                "products",
            }
        ),
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="registration.view_profile_extensions",
        description=(
            "View purpose-limited post-submission profile-extension values for "
            "registrations in one event edition."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "registration_id",
                "field_id",
                "field_key",
                "field_version",
                "label",
                "help_text",
                "field_type",
                "options",
                "purpose",
                "classification",
                "required",
                "writer_policy",
                "current_value",
                "current_sequence",
                "updated_at",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="registration.update_profile_extensions",
        description=(
            "Append reasoned staff-permitted profile-extension value revisions "
            "for registrations in one event edition."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="registration.view_service_summary",
        description=(
            "View the purpose-limited registration service queue and operational "
            "timeline."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "id",
                "reference",
                "account_id",
                "display_name",
                "state",
                "product_name",
                "amount_minor",
                "currency",
                "submitted_at",
                "waitlisted_at",
                "offered_at",
                "payment_due_at",
                "confirmed_at",
                "checked_in_at",
                "expired_at",
                "cancelled_at",
                "confirmation_basis",
                "submission_source",
                "submitted_by_id",
                "staff_submission_reason",
                "entitlements",
                "timeline",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="registration.view_attendee_reporting",
        description=(
            "View minimized edition attendance metrics and prepare a badge-data "
            "export without exposing payment or address detail."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "generated_at",
                "status_scope",
                "summary",
                "count",
                "page",
                "page_size",
                "has_next",
                "has_previous",
                "results",
                "badge_export",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="registration.view_payment_summary",
        description=(
            "View edition registration payment state, confirmation basis, and "
            "reconciliation totals."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "reference",
                "account_id",
                "display_name",
                "state",
                "product_name",
                "amount_minor",
                "currency",
                "payment_due_at",
                "confirmed_at",
                "confirmation_basis",
                "reconciliation",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="registration.manage_exceptions",
        description=(
            "Apply reasoned payment-deadline and payment-waiver exceptions to "
            "edition registrations."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="registration.register_on_behalf",
        description=(
            "Create a reasoned registration for a known account outside public "
            "sale windows without bypassing policy, capacity, or payment."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit", "audit_sensitive_read"}),
    ),
    Capability(
        code="registration.manage_finance",
        description=(
            "Propose, independently approve, reconcile, and resolve registration "
            "financial operations and provider exceptions."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit", "approval"}),
    ),
    Capability(
        code="registration.check_in",
        description="Check in a confirmed attendee and issue arrival evidence.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="accreditation.issue",
        description="Issue and reprint edition credentials from active entitlements.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="accreditation.revoke",
        description="Revoke an issued credential and propagate revocation.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="accreditation.manage_offline",
        description="Generate signed manifests and reconcile offline operations.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.SECURITY_CRITICAL,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="registration.view_self",
        description="View one's own registration, entitlements, and timeline.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "id",
                "reference",
                "state",
                "product_name",
                "amount_minor",
                "currency",
                "submitted_at",
                "waitlisted_at",
                "offered_at",
                "payment_due_at",
                "confirmed_at",
                "checked_in_at",
                "expired_at",
                "cancelled_at",
                "confirmation_basis",
                "entitlements",
                "timeline",
            }
        ),
    ),
    Capability(
        code="registration.register_self",
        description="Start and pay one's own registration in an open edition.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="registration.manage_self_profile",
        description=(
            "View and update one's mutable current-edition attendee profile "
            "without changing the immutable registration submission."
        ),
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="registration.view_self_profile",
        description=(
            "View one's own edition profile or a prior profile offered as an "
            "explicit registration suggestion."
        ),
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset(
            {
                "source_profile_id",
                "source_edition_id",
                "source_edition_name",
                "notice",
                "registration_identity",
                "address",
                "emergency_contact",
                "contact",
                "pronouns",
                "bio",
                "spoken_languages",
                "profile_media",
                "fursuits",
                "directory_visible",
                "directory_country",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="registration.moderate_public_profile",
        description=(
            "Review profile and fursuit images before they may appear in a "
            "public attendee rendition."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "id",
                "account_id",
                "display_name",
                "media_kind",
                "image",
                "review_status",
                "submitted_at",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="charities.view_partners",
        description=(
            "View organizer-owned charity partner profiles and governed media."
        ),
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset(
            {
                "id",
                "slug",
                "legal_name",
                "imprint_name",
                "public_name",
                "short_description",
                "description",
                "location_name",
                "postal_address",
                "country_code",
                "website_url",
                "contact_email",
                "contact_phone",
                "lifecycle",
                "aggregate_version",
                "media_references",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="charities.manage_partners",
        description=("Create, change, retire, and govern media for charity partners."),
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="charities.view_review_queue",
        description="View minimized charity selection state for one edition.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        requires_break_glass=True,
        field_ceiling=frozenset(
            {
                "id",
                "partner_id",
                "partner_name",
                "responsible_department_id",
                "responsible_department_name",
                "status",
                "publication_state",
                "aggregate_version",
            }
        ),
    ),
    Capability(
        code="charities.propose_selection",
        description="Propose and submit organizer charity partners for one edition.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        requires_break_glass=True,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="charities.view_selection",
        description=("View one purpose-scoped charity selection review timeline."),
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset(
            {
                "summary",
                "timeline",
                "reason",
                "private_comment",
                "actor_id",
                "occurred_at",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="charities.review_selection",
        description="Confirm or reject one submitted edition charity selection.",
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="charities.comment_selection",
        description="Append a private purpose-scoped comment to one selection.",
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="charities.publish_selection",
        description=(
            "Independently publish or withdraw one confirmed charity selection."
        ),
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=False,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit", "approval"}),
    ),
    Capability(
        code="venues.view_properties",
        description="View organizer-owned venue, layout, and provider records.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset(
            {
                "property",
                "sites",
                "buildings",
                "spaces",
                "configurations",
                "combinations",
                "layouts",
                "media",
                "provider_contact",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="venues.manage_properties",
        description="Create and govern reusable venue facts, media, and layouts.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="venues.manage_accommodation",
        description="Manage bounded room-type and nightly hotel inventory catalogs.",
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="venues.view_workspace",
        description=(
            "View selected venues, spaces, availability, and booking summaries."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        requires_break_glass=True,
        field_ceiling=frozenset(
            {
                "venue_selections",
                "space_selections",
                "availability",
                "booking_summaries",
            }
        ),
    ),
    Capability(
        code="venues.select_for_edition",
        description="Select reusable venues and spaces with edition-owned overrides.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        requires_break_glass=True,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="venues.view_space_schedule",
        description="View one exact edition space's operational booking layers.",
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset(
            {
                "space",
                "availability",
                "bookings",
                "setup_interval",
                "effective_interval",
                "teardown_interval",
                "internal_layout",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="venues.manage_space_schedule",
        description="Create, move, and cancel bookings in one exact edition space.",
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="venues.publish_space_schedule",
        description="Approve, publish, or withdraw one exact space schedule item.",
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=False,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit", "approval"}),
    ),
    Capability(
        code="catalog.manage",
        description=(
            "Configure and activate an edition merchandise and donation catalog."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="catalog.manage_stock",
        description="Append reasoned stock changes within configured hard ceilings.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="catalog.manage_payments",
        description="Reconcile hosted catalog payment outcomes for one edition.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="catalog.view_activity",
        description=(
            "View purpose-scoped catalog configuration, stock, and order activity."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {"action", "actor_label", "occurred_at", "target_count"}
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="catalog.order_self",
        description="Place and pay one's own edition catalog orders.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="catalog.view_self",
        description="View one's own catalog order history and fulfilment state.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {"reference", "status", "total", "lines", "payment", "fulfilment"}
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="logistics.offer_self",
        description="Offer and withdraw one's own equipment for an eligible edition.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="logistics.manage_catalog",
        description=(
            "Register reusable Logistics parties, locations, assets, stock, keys, "
            "agreements, kits, and labels."
        ),
        maximum_scope=ScopeLevel.ORGANIZATION,
        delegable=False,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="logistics.view_restricted_contacts",
        description=(
            "Read one purpose- and retention-limited Logistics pickup, storage, "
            "provider, or return contact."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit_sensitive_read"}),
    ),
    Capability(
        code="logistics.view_workspace",
        description=(
            "View an edition's minimized Logistics inventory, custody, manifest, "
            "return, and Stage Tech receiving workspace."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="logistics.manage_operations",
        description=(
            "Append receive, pack, move, custody, count, condition, damage, and "
            "return operations in one edition."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="logistics.review_offers",
        description="Accept or reject authenticated equipment offers for one edition.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"reason", "audit", "audit_sensitive_read"}),
    ),
    Capability(
        code="logistics.reconcile_offline",
        description="Review and reconcile bounded offline Logistics scan batches.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="logistics.view_manifest",
        description="View one exact edition Logistics manifest and receiving status.",
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="logistics.manage_manifest",
        description="Add lines to and transition one exact Logistics manifest.",
        maximum_scope=ScopeLevel.RESOURCE,
        delegable=True,
        requires_break_glass=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="applications.manage_definitions",
        description=(
            "Create, version, configure, activate, and retire edition-owned "
            "typed application definitions."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="applications.review",
        description="Review assigned C1/C2 typed applications in one edition.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"reason", "audit", "audit_sensitive_read"}),
    ),
    Capability(
        code="applications.review_sensitive",
        description=(
            "Review assigned C3/C4, adult, or case application material in one "
            "edition under an explicit audience policy."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.SECURITY_CRITICAL,
        obligations=frozenset({"reason", "audit", "audit_sensitive_read"}),
    ),
    Capability(
        code="applications.view_self",
        description="View one's own typed application drafts, answers, and decisions.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset(
            {"available", "submissions", "answers", "decisions", "typed_target"}
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="applications.apply_self",
        description="Create and submit one's own eligible typed applications.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="workforce.view_structure",
        description=(
            "View edition departments, positions, reporting lines, minimized "
            "holder labels, and application status."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        field_ceiling=frozenset(
            {
                "structure_control",
                "departments",
                "positions",
                "opportunities",
                "assignment_counts",
                "holder_display_labels",
            }
        ),
    ),
    Capability(
        code="workforce.manage_structure",
        description=(
            "Create edition departments, positions, requirements, and application "
            "publication settings."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        obligations=frozenset({"reason", "audit"}),
    ),
    Capability(
        code="workforce.manage_applications",
        description="Review volunteer applications within one edition.",
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"reason", "audit", "audit_sensitive_read"}),
    ),
    Capability(
        code="workforce.manage_documents",
        description=(
            "Request and review private onboarding agreement evidence for one edition."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit", "audit_sensitive_read"}),
    ),
    Capability(
        code="workforce.manage_assignments",
        description=(
            "Activate or end edition positions after prerequisites and independent "
            "approval."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=False,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        obligations=frozenset({"reason", "audit", "approval"}),
    ),
    Capability(
        code="workforce.view_availability",
        description=(
            "View deliberately shared current availability for people with open "
            "assignments in one edition."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset(
            {
                "availability_consequences",
                "availability_windows",
                "holder_display_labels",
            }
        ),
        obligations=frozenset({"audit_sensitive_read"}),
    ),
    Capability(
        code="workforce.view_self",
        description=(
            "View one's own applications, requested documents, positions, and "
            "availability."
        ),
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset(
            {"applications", "document_requests", "assignments", "availability"}
        ),
    ),
    Capability(
        code="workforce.manage_self_availability",
        description=(
            "Save, share, replace, or withdraw one's own edition availability."
        ),
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        field_ceiling=frozenset({"availability"}),
        obligations=frozenset({"audit"}),
    ),
    Capability(
        code="workforce.apply_self",
        description="Apply to a published edition volunteer opportunity.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.PERSONAL,
        obligations=frozenset({"audit"}),
    ),
)

CAPABILITIES = {definition.code: definition for definition in CAPABILITY_DEFINITIONS}
if len(CAPABILITIES) != len(CAPABILITY_DEFINITIONS):
    raise RuntimeError("Capability codes must be unique")

POLICY_VERSION = "2026-08-25.1"


def capability(code: str) -> Capability | None:
    """Return capability.

    Parameters
    ----------
    code : str
        The stable machine-readable code.

    Returns
    -------
    Capability | None
        The matching Capability, or `None` when no authorized record exists.
    """
    return CAPABILITIES.get(code)


def require_capability(code: str) -> Capability:
    """Require capability.

    Parameters
    ----------
    code : str
        The stable machine-readable code.

    Returns
    -------
    Capability
        The Capability established after require capability completes.

    Raises
    ------
    ValueError
        If the supplied value cannot satisfy the documented contract.
    """
    definition = capability(code)
    if definition is None:
        raise ValueError(f"Unknown capability: {code}")
    return definition
