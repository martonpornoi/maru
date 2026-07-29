"""Short, consistent purpose guidance for every bootstrap admin page."""

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
}


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
            "Use this bootstrap area to inspect and maintain Maru's foundation "
            "data. For example: open Registration configurations to edit a "
            "draft or Participations to find a person."
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
