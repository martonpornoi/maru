"""Code-owned inventory for edition registration-profile fields."""

from dataclasses import dataclass

COLLECTION_NOTICE_VERSION = "registration-profile-v2"
DIRECTORY_CONSENT_VERSION = "public-attendee-list-v3"
MAX_FURSUIT_PHOTO_BYTES = 5 * 1024 * 1024
ALLOWED_FURSUIT_PHOTO_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)


@dataclass(frozen=True)
class ProfileFieldPolicy:
    """Authorize profile field policy operations.

    Attributes
    ----------
    purpose
        The documented purpose constraining collection and processing.
    classification
        The closed sensitivity classification governing disclosure.
    visibility
        The closed disclosure audience applied to the projection.
    retention
        The retention retained in this immutable projection.
    """

    purpose: str
    classification: str
    visibility: str
    retention: str


PROFILE_FIELD_POLICY = {
    "real_name": ProfileFieldPolicy(
        purpose="Match the registration to the person for controlled service.",
        classification="C3",
        visibility="Restricted registration identity staff only.",
        retention="Remove after edition support and identity-dispute closure.",
    ),
    "date_of_birth": ProfileFieldPolicy(
        purpose="Evaluate the edition's age boundary at its start date.",
        classification="C3",
        visibility="Restricted registration policy processing only.",
        retention="Minimize to an age result after policy and dispute closure.",
    ),
    "address": ProfileFieldPolicy(
        purpose="Support registration fulfilment and required billing contact.",
        classification="C2",
        visibility="Registration and fulfilment staff only.",
        retention="Remove after fulfilment, support, and applicable finance closure.",
    ),
    "emergency_contact": ProfileFieldPolicy(
        purpose="Contact a nominated person during an attendee emergency.",
        classification="C3",
        visibility="Assigned emergency response staff only.",
        retention="Remove after the edition and defined incident follow-up.",
    ),
    "phone_number": ProfileFieldPolicy(
        purpose="Resolve time-sensitive registration or arrival service.",
        classification="C2",
        visibility="Registration service staff only.",
        retention="Remove after edition support closure.",
    ),
    "telegram_handle": ProfileFieldPolicy(
        purpose="Provide an optional attendee-selected contact route.",
        classification="C2",
        visibility="Registration service staff only.",
        retention="Remove after edition support closure.",
    ),
    "pronouns": ProfileFieldPolicy(
        purpose="Address the attendee respectfully during convention service.",
        classification="C2",
        visibility="Attendee and registration staff.",
        retention="Keep only with the edition registration profile.",
    ),
    "bio": ProfileFieldPolicy(
        purpose="Let the attendee provide an optional short public introduction.",
        classification="C2",
        visibility="Attendee and registration staff; public only by edition consent.",
        retention="Keep only with the edition registration profile.",
    ),
    "spoken_languages": ProfileFieldPolicy(
        purpose="Support attendee communication and structured badge metadata.",
        classification="C2",
        visibility="Attendee and registration staff; public only by edition consent.",
        retention="Keep only with the edition registration profile.",
    ),
    "profile_media": ProfileFieldPolicy(
        purpose="Support an optional moderated attendee profile image.",
        classification="C2",
        visibility="Private until approved; public only by edition consent.",
        retention=(
            "Remove media after edition support unless approved reuse remains valid."
        ),
    ),
    "fursuit_identity": ProfileFieldPolicy(
        purpose="Support optional character identification and convention services.",
        classification="C2",
        visibility=(
            "Attendee and registration staff; public only after media approval "
            "and edition consent."
        ),
        retention=(
            "Remove media after edition support unless approved reuse remains valid."
        ),
    ),
    "directory_visible": ProfileFieldPolicy(
        purpose="Publish a minimized attendee-selected public attendance rendition.",
        classification="C2",
        visibility="Public after payment confirmation.",
        retention=(
            "Withdraw from the public list immediately when consent is withdrawn."
        ),
    ),
    "directory_country_code": ProfileFieldPolicy(
        purpose=(
            "Let the attendee optionally name one country for their public "
            "directory card without publishing their address."
        ),
        classification="C2",
        visibility=(
            "Public only when entered specifically for the current edition's "
            "attendee directory."
        ),
        retention=(
            "Withdraw from the public list immediately when consent is withdrawn."
        ),
    ),
}
