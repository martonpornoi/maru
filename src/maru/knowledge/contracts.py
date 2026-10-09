"""Immutable owner inputs and separately admitted Guidance projections."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GuidanceReadRequest:
    """Actual actor and independently authorized edition context.

    Attributes
    ----------
    actor_id
        Authenticated account; a selected person never substitutes for this actor.
    organization_id, edition_id
        Exact tenant and event boundaries admitted before any protected read.
    correlation_id
        Request reference joining authorized access to minimized audit evidence.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class GuidanceCommandRequest(GuidanceReadRequest):
    """Exact retry identity carried across one normalized command intent.

    Attributes
    ----------
    idempotency_key
        Actor-scoped retry reference; changed intent must use a different key.
    source_channel
        Bounded adapter attribution retained by the receipt and audit.
    """

    idempotency_key: UUID
    source_channel: str = "knowledge-html"


@dataclass(frozen=True, slots=True)
class GuidanceCommandResult:
    """Identifier-only accepted result, including exact receipt replays.

    Attributes
    ----------
    receipt_id, object_id
        Immutable command proof and operation-specific output reference.
    version
        Resulting item or settings version, never a copy revision number.
    item_id
        Owning Guidance item; absent for edition-wide settings and stop commands.
    replayed
        True when no new domain mutation occurred.
    """

    receipt_id: UUID
    object_id: UUID
    version: int
    item_id: UUID | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class GuidanceSettingsInput:
    """An organizer's confirmation of actual organizational record-keeping rules.

    Attributes
    ----------
    policy_name, record_owner
        Readable rule name and responsible records custodian.
    review_on
        Inclusive event-local deadline for reviewing the applicable rules.
    confirmed
        Actual confirmation covering copy, private review and exported evidence.
    policy_url, policy_description
        Safe reference or bounded explanation; at least one is required.
    """

    policy_name: str
    record_owner: str
    review_on: date
    confirmed: bool
    policy_url: str = ""
    policy_description: str = ""


@dataclass(frozen=True, slots=True)
class GuidanceDraftInput:
    """Plain text and reviewed metadata for one language and fixed internal purpose.

    Attributes
    ----------
    title, body
        Bounded plain text preserved as an immutable working version.
    language_code
        One configured language for this Guidance item.
    review_by
        Organizer-chosen review date; optional until requesting independent review.
    placements
        Closed contextual placement codes reviewed together with the copy.
    """

    title: str
    body: str
    language_code: str
    review_by: date | None = None
    placements: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuidanceActions:
    """Current explanatory action admission; commands independently reauthorize.

    Attributes
    ----------
    can_view_current, can_view_working
        Separate current-reader and private working-copy admission.
    can_compose, can_review, can_withdraw
        Content actions permitted by current authority and relevant item state.
    can_manage_settings, can_export_evidence
        Independent settings and private artifact permissions.
    """

    can_view_current: bool = False
    can_view_working: bool = False
    can_compose: bool = False
    can_review: bool = False
    can_withdraw: bool = False
    can_manage_settings: bool = False
    can_export_evidence: bool = False


@dataclass(frozen=True, slots=True)
class GuidanceOptions:
    """Writer-safe readiness and choices without private policy descriptions.

    Attributes
    ----------
    settings_version, control_version
        Settings cursor and every-command sequence for stale-form protection.
    configured, stopped, rules_current
        Whether recorded rules exist and currently admit new content work.
    language_codes, time_zone
        Current Events-owned locale configuration.
    placement_codes
        Closed placements admitted by the exact current adoption pair.
    owner_label, audience_label, purpose
        Fixed accepted Guidance team, internal readers and operational purpose.
    actions
        Independently resolved action admission for the current actor.
    blocking_reasons
        Closed safe reasons writing cannot proceed, without private rule or people data.
    """

    settings_version: int
    control_version: int
    configured: bool
    stopped: bool
    rules_current: bool
    language_codes: tuple[str, ...]
    time_zone: str
    placement_codes: tuple[str, ...]
    owner_label: str
    audience_label: str
    purpose: str
    actions: GuidanceActions
    blocking_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuidanceSettingsView:
    """Private record-keeping setup admitted only to settings managers.

    Attributes
    ----------
    options
        Current control cursor and safe scope/readiness information.
    revision_id
        Exact immutable rules confirmation, absent before setup.
    policy_name, record_owner
        Recorded rules name and responsible records custodian.
    review_on
        Inclusive rules deadline, absent before setup.
    policy_url, policy_description
        Recorded organizational reference and explanation, never legal certification.
    """

    options: GuidanceOptions
    revision_id: UUID | None
    policy_name: str = ""
    record_owner: str = ""
    review_on: date | None = None
    policy_url: str = ""
    policy_description: str = ""


@dataclass(frozen=True, slots=True)
class GuidanceCurrentSummary:
    """Current internal copy metadata without drafts or private review evidence.

    Attributes
    ----------
    id, revision_id
        Scoped item and exact current approved copy references.
    title, language_code
        Approved title and the item's single language.
    number, effective_at
        Human-readable copy version and actual independent publication time.
    review_by, review_due
        Approved review date and its current event-local currency indication.
    owner_label
        Accepted Guidance team responsible for this internal content.
    """

    id: UUID
    revision_id: UUID
    title: str
    language_code: str
    number: int
    effective_at: datetime
    review_by: date
    review_due: bool
    owner_label: str


@dataclass(frozen=True, slots=True)
class GuidanceCurrentView:
    """Exact current-reader rendition; no private source graph is loaded for it.

    Attributes
    ----------
    summary
        Approved metadata and review currency for this exact current copy.
    body
        Complete approved plain text.
    purpose, audience_label
        Fixed internal convention purpose and independently authorized readers.
    placements
        Approved contextual locations, never arbitrary route or permission tokens.
    """

    summary: GuidanceCurrentSummary
    body: str
    purpose: str
    audience_label: str
    placements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GuidanceCurrentPage:
    """Bounded current-only result page with a stable identifier continuation.

    Attributes
    ----------
    items
        Admitted current-copy summaries; search never includes working text.
    next_after
        Exclusive continuation identifier, absent when this result page is final.
    actions
        Current actor admission, without treating the menu as authority.
    """

    items: tuple[GuidanceCurrentSummary, ...]
    next_after: UUID | None
    actions: GuidanceActions


@dataclass(frozen=True, slots=True)
class GuidanceRevisionView:
    """Private immutable working or historical version, independent of availability.

    Attributes
    ----------
    id, number
        Exact retained version reference and human-readable sequence.
    title, body, language_code
        Complete authored plain text and the item's single language.
    review_by, placements
        Reviewed metadata, with a review date optional only in unfinished drafts.
    created_at
        When this immutable authored version was recorded.
    """

    id: UUID
    number: int
    title: str
    body: str
    language_code: str
    review_by: date | None
    placements: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GuidanceWorkingSummary:
    """Private work-list entry with separate working and reader availability states.

    Attributes
    ----------
    id, title, language_code
        Scoped item reference and latest working copy metadata.
    version, status
        Optimistic command cursor and current working state.
    current_number, withdrawn
        Available copy version, if any, and explicit withdrawal state.
    updated_at
        When the latest item command updated its aggregate.
    """

    id: UUID
    title: str
    language_code: str
    version: int
    status: str
    current_number: int | None
    withdrawn: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GuidanceWorkingPage:
    """Bounded private work page, separate from current-reader search.

    Attributes
    ----------
    items, next_after
        Private summaries and exclusive identifier continuation.
    options
        Safe current scope, rules readiness and actor admission.
    """

    items: tuple[GuidanceWorkingSummary, ...]
    next_after: UUID | None
    options: GuidanceOptions


@dataclass(frozen=True, slots=True)
class GuidanceHistoryEntry:
    """One admitted command fact; never included in current-reader artifacts.

    Attributes
    ----------
    action, actor_label
        Accepted operation and minimized operational attribution without email.
    occurred_at, reason
        Recorded command time and bounded organizer rationale.
    """

    action: str
    actor_label: str
    occurred_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class GuidanceWorkingDetail:
    """Private working copy, retained approvals and separately evaluated action rights.

    Attributes
    ----------
    id, version, status, withdrawn
        Scoped item identity, optimistic cursor, working and availability state.
    draft, last_approved
        Latest authored copy and historical approval, even after withdrawal.
    current
        Currently published copy, absent after withdrawal or while stopped.
    review_note, history
        Bounded private decision feedback and command evidence.
    options, actions
        Current scope configuration and item-specific action admission.
    """

    id: UUID
    version: int
    status: str
    withdrawn: bool
    draft: GuidanceRevisionView
    last_approved: GuidanceRevisionView | None
    current: GuidanceCurrentView | None
    review_note: str
    history: tuple[GuidanceHistoryEntry, ...]
    options: GuidanceOptions
    actions: GuidanceActions


@dataclass(frozen=True, slots=True)
class GuidanceResumePreview:
    """Exact retained current content requiring explicit confirmation before resuming.

    Attributes
    ----------
    control_version
        Every-command sequence; any intervening mutation invalidates this preview.
    preview_digest
        Owner-generated digest binding the exact retained current-copy set.
    items
        Complete bounded current-copy inventory, excluding withdrawn items.
    can_resume
        Current manager admission and refreshed rules permit a resume attempt.
    blocking_reasons
        Closed safe reasons the confirmed set cannot yet return to readers.
    """

    control_version: int
    preview_digest: str
    items: tuple[GuidanceCurrentSummary, ...]
    can_resume: bool
    blocking_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GuidanceDownload:
    """Complete bounded artifact with separately admitted reader or private content.

    Attributes
    ----------
    filename, content_type
        Owner-generated artifact name and matching serialized media type.
    content
        Complete bytes; overflow fails rather than silently truncating evidence.
    content_fingerprint
        Canonical content digest excluding generation time, for a final admitted
        current-copy comparison before releasing freshly generated artifact bytes.
    """

    filename: str
    content_type: str
    content: bytes
    content_fingerprint: str = ""
