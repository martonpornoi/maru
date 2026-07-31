"""Short, consistent purpose guidance for every bootstrap admin page."""

from dataclasses import dataclass

from django import template

register = template.Library()
ADMIN_APP_PATH_PARTS = 2

MODEL_PAGE_HELP: dict[tuple[str, str], str] = {
    (
        "identity",
        "account",
    ): (
        "Use this page to find bootstrap platform accounts. With a convention "
        "workspace selected, only accounts already linked to that edition by a "
        "participation are listed. A newly created account is still saved but "
        "remains hidden here until it joins the edition; choose All foundation "
        "data to find it. For example: clear the workspace before checking a "
        "new Chair account."
    ),
    (
        "identity",
        "accountsecurityevent",
    ): (
        "Use this platform-wide page to inspect append-only account security "
        "history; it is not edition-owned. For example: confirm when an "
        "account signed in or signed out."
    ),
    (
        "organizations",
        "organization",
    ): (
        "Use this page to define organizer tenant boundaries. "
        "For example: open an organizer to review its name, slug, and status."
    ),
    (
        "organizations",
        "conventionseries",
    ): (
        "Use this page to group annual editions of the same convention. "
        "For example: find every Danube edition under one stable series."
    ),
    (
        "organizations",
        "organizationmembership",
    ): (
        "Use this page to review a person's relationship with an organizer. "
        "For example: find active board members or ended memberships."
    ),
    (
        "events",
        "eventedition",
    ): (
        "Use this page to manage one annual convention project. "
        "For example: review dates, locale, lifecycle, and related records."
    ),
    (
        "events",
        "editionlifecycletransition",
    ): (
        "Use this page to inspect how an edition changed lifecycle state. "
        "For example: confirm who moved an edition into preparation and why."
    ),
    (
        "events",
        "archiveamendment",
    ): (
        "Use this page to inspect explicit corrections to archived editions. "
        "For example: review a corrected historical label and its reason."
    ),
    (
        "participation",
        "participation",
    ): (
        "Use this page to see who belongs to an edition. "
        "For example: search a person and review their participation status."
    ),
    (
        "participation",
        "participationcapacity",
    ): (
        "Use this page to see how each participant is involved. "
        "For example: find attendees, volunteers, hosts, or board members."
    ),
    (
        "authorization",
        "capabilitygrant",
    ): (
        "Use this page to inspect direct scoped authority. "
        "For example: confirm who can manage registration for one edition."
    ),
    (
        "authorization",
        "rolebundle",
    ): (
        "Use this page to inspect immutable role definitions. "
        "For example: compare which capabilities belong to each role version."
    ),
    (
        "authorization",
        "roleassignment",
    ): (
        "Use this page to inspect who received a scoped role. "
        "For example: find the registration lead assigned to an edition."
    ),
    (
        "registration",
        "registrationtemplate",
    ): (
        "Use this page to define reusable registration starting points. "
        "For example: edit a draft template's questions and products before "
        "publishing it."
    ),
    (
        "registration",
        "registrationconfiguration",
    ): (
        "Use this page to define registration for one edition. "
        "For example: edit a draft's dates, questions, products, and capacity."
    ),
    (
        "registration",
        "registration",
    ): (
        "Use this page to inspect an attendee's registration state. "
        "For example: find a reference and review payment, entitlement, and "
        "check-in status."
    ),
    (
        "registration",
        "registrationsubmission",
    ): (
        "Use this page to inspect the exact form version an attendee submitted. "
        "For example: verify which schema and answers belong to a registration."
    ),
    (
        "registration",
        "attendeeregistrationprofile",
    ): (
        "Use this restricted bootstrap page to inspect edition-owned attendee "
        "profile data. For example: resolve an address or emergency-contact "
        "correction without exposing it to Front Desk or the attendee directory."
    ),
    (
        "registration",
        "registrationprofileextensionfield",
    ): (
        "Use this page to add a reviewed current-profile field without changing "
        "an attendee's submitted registration. For example: request a missing "
        "address detail from attendees or define a staff-only verification."
    ),
    (
        "registration",
        "registrationprofileextensionvaluerevision",
    ): (
        "Use this page to inspect append-only current-profile field history. "
        "For example: confirm when an attendee supplied a missing detail or when "
        "registration staff recorded a reasoned correction."
    ),
    (
        "registration",
        "paymentattempt",
    ): (
        "Use this page to inspect append-only payment reconciliation evidence. "
        "For example: check provider state, amount, and safe result code."
    ),
    (
        "registration",
        "registrationadjustment",
    ): (
        "Use this page to inspect controlled registration exceptions and "
        "automation evidence. For example: verify why a payment deadline changed "
        "or a payment was waived."
    ),
    (
        "registration",
        "entitlement",
    ): (
        "Use this page to inspect admission or other granted rights. "
        "For example: confirm that a paid attendee has an active admission."
    ),
    (
        "registration",
        "checkinrecord",
    ): (
        "Use this page to inspect append-only arrival evidence. "
        "For example: confirm when Front Desk checked in an attendee and why."
    ),
    (
        "registration",
        "registrationtimelineentry",
    ): (
        "Use this page to inspect attendee-facing operational history. "
        "For example: follow submission, payment confirmation, and check-in."
    ),
    (
        "identity",
        "identitychallenge",
    ): (
        "Use this page to inspect verification and account-recovery challenges. "
        "For example: troubleshoot an email verification or password-reset link."
    ),
    (
        "identity",
        "accountsession",
    ): (
        "Use this page to inspect active and expired sign-in sessions. "
        "For example: confirm that a suspicious session was revoked."
    ),
    (
        "identity",
        "identityabusebucket",
    ): (
        "Use this page to inspect identity rate-limit and abuse evidence. "
        "For example: investigate repeated failed recovery attempts."
    ),
    (
        "identity",
        "accountrestriction",
    ): (
        "Use this page to inspect bans, suspensions, and scoped restrictions. "
        "For example: confirm why an account cannot register for an edition."
    ),
    (
        "events",
        "editionreadinessgate",
    ): (
        "Use this read-only page to inspect explicit checks recorded by the "
        "Convention work readiness review. For example: verify the evidence "
        "used for finance readiness before closure."
    ),
    (
        "events",
        "editionclosuremanifest",
    ): (
        "Use this page to inspect the evidence captured when an edition closes. "
        "For example: verify the final registration and finance state before "
        "archival."
    ),
    (
        "communications",
        "notificationmessage",
    ): (
        "Use this page to inspect the canonical content of attendee and staff "
        "notifications. For example: review the payment-confirmation message "
        "created for a registration."
    ),
    (
        "communications",
        "notificationdelivery",
    ): (
        "Use this page to inspect notification delivery attempts and outcomes. "
        "For example: find why a wait-list invitation email was not delivered."
    ),
    (
        "communications",
        "notificationpreference",
    ): (
        "Use this page to maintain a person's allowed notification channels and "
        "preferences. For example: respect an attendee's optional email opt-out."
    ),
    (
        "registration",
        "attendeefursuit",
    ): (
        "Use this restricted page to inspect edition-owned fursuit details and "
        "review state. For example: approve one of several reusable fursuit "
        "photos for the attendee directory."
    ),
    (
        "registration",
        "paymentprovideraccount",
    ): (
        "Use this page to configure an edition's payment-provider connection. "
        "For example: select the provider account that receives ticket payments."
    ),
    (
        "registration",
        "minorregistrationpolicy",
    ): (
        "Use this page to define age thresholds and guardian requirements. "
        "For example: require guardian consent for attendees below the configured "
        "adult age."
    ),
    (
        "registration",
        "guardianconsent",
    ): (
        "Use this page to inspect guardian consent evidence for a minor. "
        "For example: confirm that the required guardian approval was received."
    ),
    (
        "registration",
        "paymentintent",
    ): (
        "Use this page to inspect what a registration owes and its payment "
        "deadline. For example: verify the amount reserved for an early-bird "
        "ticket."
    ),
    (
        "registration",
        "paymentwebhookreceipt",
    ): (
        "Use this page to inspect deduplicated payment-provider callbacks. "
        "For example: prove that the same provider event was processed only once."
    ),
    (
        "registration",
        "paymentexception",
    ): (
        "Use this page to resolve payment mismatches and manual review cases. "
        "For example: investigate a provider payment with an unexpected amount."
    ),
    (
        "registration",
        "financialoperation",
    ): (
        "Use this page to inspect idempotent money-changing operations. "
        "For example: confirm that a refund command was not executed twice."
    ),
    (
        "registration",
        "financialledgerentry",
    ): (
        "Use this page to inspect immutable accounting movements. "
        "For example: reconcile a charge, refund, or adjustment against a "
        "registration."
    ),
    (
        "registration",
        "receiptrecord",
    ): (
        "Use this page to inspect receipt issuance and its immutable reference. "
        "For example: find the receipt attached to a confirmed ticket payment."
    ),
    (
        "registration",
        "settlementbatch",
    ): (
        "Use this page to inspect provider payout or settlement batches. "
        "For example: reconcile one bank payout with the payments it contains."
    ),
    (
        "registration",
        "settlementallocation",
    ): (
        "Use this page to inspect how settlement money was allocated to payment "
        "attempts. For example: explain which attendee payments belong to a "
        "provider payout."
    ),
    (
        "registration",
        "mediasafetyreceipt",
    ): (
        "Use this page to inspect media scanning and moderation evidence. "
        "For example: verify that an uploaded profile or fursuit image passed "
        "the safety pipeline."
    ),
    (
        "registration",
        "registrationlifecyclerun",
    ): (
        "Use this page to inspect automated registration lifecycle runs. "
        "For example: confirm when expired payment windows and wait-list "
        "promotions were processed."
    ),
    (
        "workforce",
        "department",
    ): (
        "Use this page to build the convention's team structure. "
        "For example: create Registration, Security, or Fursuit Support."
    ),
    (
        "workforce",
        "positiontemplate",
    ): (
        "Use this page to maintain reusable furry-convention job patterns. "
        "For example: start a new edition with a standard Department Lead role."
    ),
    (
        "workforce",
        "position",
    ): (
        "Use this page to define edition-specific jobs and reporting lines. "
        "For example: create a Registration Lead position under Operations."
    ),
    (
        "workforce",
        "onboardingdocumenttype",
    ): (
        "Use this page to define documents required for particular work. "
        "For example: describe the NDA required for a trusted staff position."
    ),
    (
        "workforce",
        "onboardingdocumentrequest",
    ): (
        "Use this page to request, review, and approve a person's onboarding "
        "document. For example: approve a signed NDA before assigning access."
    ),
    (
        "workforce",
        "positionassignment",
    ): (
        "Use this page to place one or more people into convention positions. "
        "For example: assign two volunteers to a role that allows multiple "
        "holders."
    ),
    (
        "workforce",
        "volunteeropportunity",
    ): (
        "Use this page to publish or retain a volunteer opening tied to a "
        "position. For example: keep the role description visible after the "
        "current vacancy is filled."
    ),
    (
        "workforce",
        "volunteerapplication",
    ): (
        "Use this page to review a person's application and decision history. "
        "For example: accept an applicant into the Registration team."
    ),
    (
        "accreditation",
        "credential",
    ): (
        "Use this page to inspect a badge or other issued access credential. "
        "For example: confirm which access profile belongs to an attendee."
    ),
    (
        "accreditation",
        "credentialevent",
    ): (
        "Use this page to inspect append-only credential issuance, activation, "
        "and revocation history. For example: explain why a badge no longer "
        "opens a controlled area."
    ),
    (
        "accreditation",
        "relaydevice",
    ): (
        "Use this page to authorize devices used for offline accreditation. "
        "For example: register a Front Desk laptop before the venue loses "
        "internet access."
    ),
    (
        "accreditation",
        "offlinecredentialmanifest",
    ): (
        "Use this page to inspect signed credential snapshots prepared for "
        "offline use. For example: verify which badges were available to an "
        "offline check-in station."
    ),
    (
        "accreditation",
        "offlinecheckinoperation",
    ): (
        "Use this page to inspect offline check-in operations synchronized back "
        "to Maru. For example: reconcile an arrival recorded while the venue "
        "network was unavailable."
    ),
    (
        "privacyops",
        "subjectrightsrequest",
    ): (
        "Use this page to manage privacy access, correction, export, or erasure "
        "requests. For example: track an attendee's request for a copy of their "
        "data."
    ),
    (
        "privacyops",
        "posteditioncorrection",
    ): (
        "Use this page to record controlled corrections after an edition. "
        "For example: fix historical personal data without silently rewriting "
        "closed records."
    ),
    (
        "privacyops",
        "retentionpolicy",
    ): (
        "Use this page to inspect approved retention rules. "
        "For example: confirm how long payment evidence must be kept."
    ),
    (
        "privacyops",
        "disposalreceipt",
    ): (
        "Use this page to inspect proof that expired data was disposed of. "
        "For example: verify deletion across Maru and a downstream provider."
    ),
}

APP_PAGE_HELP: dict[str, str] = {
    "identity": (
        "Use this area for platform accounts and their security history. "
        "For example: open Accounts to find a person."
    ),
    "organizations": (
        "Use this area for organizers, convention series, and memberships. "
        "For example: open Convention series to find annual editions."
    ),
    "events": (
        "Use this area for edition setup and lifecycle evidence. "
        "For example: open Event editions to review dates and state."
    ),
    "participation": (
        "Use this area for edition relationships and involvement. "
        "For example: open Participations to find a volunteer."
    ),
    "authorization": (
        "Use this area to inspect scoped roles and authority. "
        "For example: open Role assignments to see who holds a role."
    ),
    "registration": (
        "Use this area for registration setup and attendee lifecycle records. "
        "For example: open Registration configurations to edit a draft."
    ),
    "communications": (
        "Use this area for notification content, preferences, and delivery "
        "evidence. For example: investigate a missing payment confirmation."
    ),
    "workforce": (
        "Use this area for departments, positions, volunteer recruitment, and "
        "onboarding. For example: assign an approved volunteer to a position."
    ),
    "accreditation": (
        "Use this area for credentials and online or offline check-in evidence. "
        "For example: inspect a badge that was revoked at the venue."
    ),
    "privacyops": (
        "Use this area for privacy requests, retention, corrections, and "
        "disposal evidence. For example: track an attendee data-export request."
    ),
}


@dataclass(frozen=True, slots=True)
class AdminFunctionGroup:
    """Accessible label and palette key for related admin applications."""

    key: str
    label: str
    purpose: str


ADMIN_FUNCTION_GROUPS: tuple[AdminFunctionGroup, ...] = (
    AdminFunctionGroup(
        key="foundation",
        label="Foundation",
        purpose="Organizer, convention brand, and dated editions.",
    ),
    AdminFunctionGroup(
        key="people-access",
        label="People & access",
        purpose="Accounts, participation, teams, and scoped authority.",
    ),
    AdminFunctionGroup(
        key="registration-finance",
        label="Registration & finance",
        purpose="Forms, tickets, payments, attendee records, and automation.",
    ),
    AdminFunctionGroup(
        key="attendee-operations",
        label="Attendee operations",
        purpose="Notifications, credentials, and check-in.",
    ),
    AdminFunctionGroup(
        key="governance",
        label="Governance & privacy",
        purpose="Privacy rights, retention, correction, and disposal evidence.",
    ),
)

FUNCTION_GROUP_BY_APP: dict[str, AdminFunctionGroup] = {
    "organizations": ADMIN_FUNCTION_GROUPS[0],
    "events": ADMIN_FUNCTION_GROUPS[0],
    "identity": ADMIN_FUNCTION_GROUPS[1],
    "participation": ADMIN_FUNCTION_GROUPS[1],
    "authorization": ADMIN_FUNCTION_GROUPS[1],
    "workforce": ADMIN_FUNCTION_GROUPS[1],
    "registration": ADMIN_FUNCTION_GROUPS[2],
    "communications": ADMIN_FUNCTION_GROUPS[3],
    "accreditation": ADMIN_FUNCTION_GROUPS[3],
    "privacyops": ADMIN_FUNCTION_GROUPS[4],
}

DEFAULT_FUNCTION_GROUP = AdminFunctionGroup(
    key="platform",
    label="Platform",
    purpose="Cross-cutting platform administration.",
)


@register.simple_tag
def admin_function_groups() -> tuple[AdminFunctionGroup, ...]:
    """Return the ordered, text-labelled color legend for the admin directory."""

    return ADMIN_FUNCTION_GROUPS


@register.simple_tag
def admin_app_group(app_label: object = "") -> AdminFunctionGroup:
    """Return a functional group for an admin application."""

    return FUNCTION_GROUP_BY_APP.get(str(app_label or ""), DEFAULT_FUNCTION_GROUP)


@register.simple_tag
def admin_app_help(app_label: object = "") -> str:
    """Return the concise purpose and example for an admin application."""

    return APP_PAGE_HELP.get(
        str(app_label or ""),
        "Use this area for related platform records. "
        "For example: open a menu item to inspect its purpose.",
    )


@register.simple_tag
def admin_model_help(app_label: object = "", object_name: object = "") -> str:
    """Return purpose and use-case guidance for an admin directory item."""

    key = (str(app_label or ""), str(object_name or "").lower())
    return MODEL_PAGE_HELP.get(
        key,
        "Use this page to inspect or maintain this record type. "
        "For example: open a record to review its current state.",
    )


@register.simple_tag
def admin_page_help(
    path: object = "",
    app_label: object = "",
    model_name: object = "",
) -> str:
    """Return concise help for model, app, index, and account utility pages."""

    normalized_app = str(app_label or "")
    normalized_model = str(model_name or "")
    normalized_path = str(path or "")
    path_parts = normalized_path.strip("/").split("/")
    path_app = (
        path_parts[1]
        if len(path_parts) == ADMIN_APP_PATH_PARTS and path_parts[0] == "admin"
        else ""
    )
    help_text = MODEL_PAGE_HELP.get((normalized_app, normalized_model))
    help_text = help_text or APP_PAGE_HELP.get(normalized_app)
    help_text = help_text or APP_PAGE_HELP.get(path_app)

    if not help_text and normalized_path.rstrip("/") == "/admin":
        help_text = (
            "Use this administration home for convention work and specialist "
            "records. For example: open Registration for attendee service or "
            "Registration configurations to edit a draft."
        )
    elif not help_text and normalized_path.rstrip("/") == "/admin/workspace":
        help_text = (
            "Use this page for capability-checked convention work inside the "
            "administration shell. For example: serve an attendee, review a "
            "report, or continue guided setup."
        )
    elif not help_text and "password_change" in normalized_path:
        help_text = (
            "Use this page to replace your bootstrap administration password. "
            "For example: choose a unique local credential and save it."
        )
    elif not help_text and normalized_path.endswith("/login/"):
        help_text = (
            "Use this page to enter bootstrap administration. "
            "For example: sign in with the local demo administrator account."
        )
    return help_text or (
        "Use this bootstrap page to inspect or maintain the records shown here. "
        "For example: use search and filters to find the relevant record."
    )
