"""Versioned, code-owned capability declarations."""

from dataclasses import dataclass
from enum import StrEnum


class ScopeLevel(StrEnum):
    ORGANIZATION = "organization"
    EDITION = "edition"
    DEPARTMENT = "department"
    RESOURCE = "resource"


class Sensitivity(StrEnum):
    PUBLIC = "C0"
    INTERNAL = "C1"
    PERSONAL = "C2"
    RESTRICTED = "C3"
    SECURITY_CRITICAL = "C4"


@dataclass(frozen=True, slots=True)
class Capability:
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
        code="workforce.view_structure",
        description=(
            "View edition departments, positions, reporting lines, minimized "
            "holder labels, and application status."
        ),
        maximum_scope=ScopeLevel.EDITION,
        delegable=True,
        field_ceiling=frozenset(
            {
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
        code="workforce.view_self",
        description="View one's own applications, requested documents, and positions.",
        maximum_scope=ScopeLevel.RESOURCE,
        persistable=False,
        allow_self=True,
        sensitivity_ceiling=Sensitivity.RESTRICTED,
        field_ceiling=frozenset({"applications", "document_requests", "assignments"}),
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

POLICY_VERSION = "2026-08-01.3"


def capability(code: str) -> Capability | None:
    return CAPABILITIES.get(code)


def require_capability(code: str) -> Capability:
    definition = capability(code)
    if definition is None:
        raise ValueError(f"Unknown capability: {code}")
    return definition
