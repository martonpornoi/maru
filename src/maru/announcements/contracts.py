"""Immutable public inputs and projections for the Announcements owner."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnnouncementReadRequest:
    """Actual authenticated actor and exact, independently authorized scope.

    Attributes
    ----------
    actor_id : UUID
        Actual authenticated account, never a represented organizer identity.
    organization_id : UUID
        Tenant boundary to verify before loading protected records.
    edition_id : UUID
        Exact event edition requiring its own adoption and capability admission.
    correlation_id : UUID
        Request reference joining authorized access with its audit evidence.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class AnnouncementCommandRequest(AnnouncementReadRequest):
    """A retry belongs to the actual actor, scope and complete normalized intent.

    Attributes
    ----------
    idempotency_key : UUID
        Actor-scoped retry identity retained across resubmission of one intent.
    source_channel : str
        Bounded caller attribution retained consistently in audit and receipt.
    """

    idempotency_key: UUID
    source_channel: str = "announcements-html"


@dataclass(frozen=True, slots=True)
class AnnouncementCommandResult:
    """Identifier-only result; an exact retry returns the same evidence.

    Attributes
    ----------
    receipt_id : UUID
        Immutable proof of the accepted command, shared by an exact retry.
    object_id : UUID
        Operation-specific result, such as a copy, review or publication report.
    version : int
        Resulting announcement or settings cursor for subsequent commands.
    announcement_id : UUID | None
        Owning announcement, absent for edition-wide settings and stop commands.
    replayed : bool
        True when the existing receipt was returned without another mutation.
    """

    receipt_id: UUID
    object_id: UUID
    version: int
    announcement_id: UUID | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ManualChannel:
    """An organizer-named destination, without credentials or recipients.

    Attributes
    ----------
    code : str
        Internal channel key matched together with its retained destination URL.
    label : str
        Organizer-readable name of the exact external destination.
    url : str
        Optional public HTTPS destination reference; empty for offline channels.
    """

    code: str
    label: str
    url: str = ""


@dataclass(frozen=True, slots=True)
class AnnouncementSettingsInput:
    """An organizer's recorded rules confirmation, not legal certification.

    Attributes
    ----------
    policy_name : str
        Readable name of the organization's applicable record-keeping rules.
    record_owner : str
        Responsible team or person named by the confirming organizer.
    review_on : date
        Last event-local date on which these rules admit new writing and review.
    confirmed : bool
        Explicit confirmation that existing rules cover the retained evidence.
    channels : tuple[ManualChannel, ...]
        Bounded destinations available for new manually published copy.
    policy_url : str
        Optional public HTTPS reference to the applicable organizational rules.
    policy_description : str
        Bounded rule description, required when no reference URL is supplied.
    """

    policy_name: str
    record_owner: str
    review_on: date
    confirmed: bool
    channels: tuple[ManualChannel, ...]
    policy_url: str = ""
    policy_description: str = ""


@dataclass(frozen=True, slots=True)
class AnnouncementVariantInput:
    """Exact text to review for one channel and language.

    Attributes
    ----------
    channel_code : str
        Configured destination selected for this copy; never a permission token.
    language_code : str
        Event-supported language of this exact rendition.
    headline : str
        Plain-text title to retain and independently review.
    body : str
        Complete bounded plain text intended for manual publication.
    """

    channel_code: str
    language_code: str
    headline: str
    body: str


@dataclass(frozen=True, slots=True)
class AnnouncementDraftInput:
    """Canonical public-facing text and explicitly selected manual variants.

    Attributes
    ----------
    headline : str
        Canonical plain-text title used to identify the announcement.
    body : str
        Canonical complete message retained with this draft version.
    language_code : str
        Event-supported language of the canonical message.
    variants : tuple[AnnouncementVariantInput, ...]
        Explicit destination and language renditions reviewed with the draft.
    """

    headline: str
    body: str
    language_code: str
    variants: tuple[AnnouncementVariantInput, ...]


@dataclass(frozen=True, slots=True)
class AnnouncementSettingsView:
    """Readable rules and channel choices, with hidden command cursors.

    Attributes
    ----------
    version : int
        Settings cursor required to detect stale forms and bind exact retries.
    revision_id : UUID | None
        Retained rules revision, absent before the first organizer confirmation.
    configured : bool
        Whether an organizer has recorded a rules revision for this edition.
    stopped : bool
        Whether new writing and review have been explicitly stopped.
    rules_current : bool
        Whether rules, stop state and edition lifecycle admit new content work.
    policy_name : str
        Readable rule name, empty without settings-management admission.
    record_owner : str
        Named records custodian, empty without settings-management admission.
    review_on : date | None
        Rules review deadline, withheld without settings-management admission.
    policy_url : str
        Public rules reference, empty without settings-management admission.
    policy_description : str
        Recorded rules explanation, empty without settings-management admission.
    channels : tuple[ManualChannel, ...]
        Current destination choices available to admitted content writers.
    language_codes : tuple[str, ...]
        Current edition languages available for new copy.
    time_zone : str
        IANA event zone used to interpret dates and manual publication times.
    can_manage : bool
        Current settings-management admission; mutations still reauthorize.
    """

    version: int
    revision_id: UUID | None
    configured: bool
    stopped: bool
    rules_current: bool
    policy_name: str
    record_owner: str
    review_on: date | None
    policy_url: str
    policy_description: str
    channels: tuple[ManualChannel, ...]
    language_codes: tuple[str, ...]
    time_zone: str
    can_manage: bool


@dataclass(frozen=True, slots=True)
class AnnouncementVariantView:
    """Exact copy and destination; publication remains separately reported.

    Attributes
    ----------
    id : UUID
        Immutable rendition reference used to bind an exact publication report.
    channel_code : str
        Retained internal destination identity from the copy's rules revision.
    channel_label : str
        Destination name as it was configured when this copy was written.
    channel_url : str
        Retained public destination reference, empty for offline channels.
    language_code : str
        Language of this exact rendition.
    headline : str
        Plain-text title retained in the selected copy version.
    body : str
        Complete text retained in the selected copy version.
    publication_status : str
        Report comparison: no_record, reported, update_needed or report_withdrawn.
    publication_report_id : UUID | None
        Current retained claim for this destination, absent in public-only views.
    publication_url : str
        Reported external post reference, withheld from public-only views.
    publication_recorded_at : datetime | None
        When the selected claim was recorded in Maru, if report access is admitted.
    publication_published_at : datetime | None
        Actual posting time claimed by the reporter, when supplied and admitted.
    publication_reporter_label : str
        Admitted operational actor label; never an account email address.
    reported_headline : str
        Earlier reported title for comparison with the selected copy version.
    reported_body : str
        Earlier reported text for comparison with the selected copy version.
    """

    id: UUID
    channel_code: str
    channel_label: str
    channel_url: str
    language_code: str
    headline: str
    body: str
    publication_status: str
    publication_report_id: UUID | None = None
    publication_url: str = ""
    publication_recorded_at: datetime | None = None
    publication_published_at: datetime | None = None
    publication_reporter_label: str = ""
    reported_headline: str = ""
    reported_body: str = ""


@dataclass(frozen=True, slots=True)
class AnnouncementHistoryEntry:
    """An admitted operational fact; never included in approved public copy.

    Attributes
    ----------
    action : str
        Accepted command operation represented by the retained receipt.
    actor_label : str
        Admitted operational attribution, without account contact details.
    occurred_at : datetime
        Timestamp shared by the accepted command's evidence graph.
    reason : str
        Bounded organizer explanation retained for that operation.
    """

    action: str
    actor_label: str
    occurred_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class AnnouncementPublicationReportView:
    """One retained manual claim with exact copy lineage and current action rights.

    Attributes
    ----------
    id : UUID
        Immutable report reference, including superseded historical claims.
    variant_id : UUID
        Exact approved destination and language rendition covered by this claim.
    revision_id : UUID
        Retained copy version containing the reported rendition.
    revision_number : int
        Human-readable copy version for comparing earlier publication reports.
    channel_code : str
        Retained internal destination identity of the reported copy.
    channel_label : str
        Destination name retained with the reported copy.
    channel_url : str
        Original public destination reference, empty for offline channels.
    language_code : str
        Language of the exact reported copy.
    publication_url : str
        Optional public HTTPS link claimed for the external post.
    publication_published_at : datetime | None
        Actual posting time claimed by the organizer, if known.
    publication_recorded_at : datetime
        When Maru retained this claim or correction.
    publication_reporter_label : str
        Admitted operational attribution for this specific report.
    withdrawn : bool
        Whether this evidence withdraws a claim without claiming external removal.
    supersedes_report_id : UUID | None
        Earlier claim corrected by this report; absent for an original report.
    reason : str
        Retained explanation for the report or correction.
    can_correct : bool
        The claim has no replacement and the actor may currently correct reports.
    """

    id: UUID
    variant_id: UUID
    revision_id: UUID
    revision_number: int
    channel_code: str
    channel_label: str
    channel_url: str
    language_code: str
    publication_url: str
    publication_published_at: datetime | None
    publication_recorded_at: datetime
    publication_reporter_label: str
    withdrawn: bool
    supersedes_report_id: UUID | None
    reason: str
    can_correct: bool


@dataclass(frozen=True, slots=True)
class AnnouncementRevisionView:
    """An immutable text snapshot; technical identity never grants access.

    Attributes
    ----------
    id : UUID
        Exact retained copy reference required by review and publication commands.
    number : int
        Monotonically increasing human-readable copy version.
    headline : str
        Canonical title retained in this version.
    body : str
        Canonical complete message retained in this version.
    language_code : str
        Language of the canonical message.
    variants : tuple[AnnouncementVariantView, ...]
        Bounded destination renditions belonging to this same immutable version.
    created_at : datetime
        When this exact copy version was recorded.
    """

    id: UUID
    number: int
    headline: str
    body: str
    language_code: str
    variants: tuple[AnnouncementVariantView, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AnnouncementSummary:
    """One authorized list item without private review or actor evidence.

    Attributes
    ----------
    id : UUID
        Scoped announcement reference for an independently authorized detail read.
    headline : str
        Canonical title from the current working copy.
    status : str
        Current draft, review, approval or cancellation state.
    version : int
        Announcement command cursor, distinct from the copy revision number.
    updated_at : datetime
        When the latest accepted announcement mutation updated its aggregate.
    """

    id: UUID
    headline: str
    status: str
    version: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AnnouncementPage:
    """Bounded list page with a continuation and current action admission.

    Attributes
    ----------
    items : tuple[AnnouncementSummary, ...]
        Authorized summaries in stable identifier order, limited to one page.
    next_after : UUID | None
        Exclusive identifier cursor for the next page, absent at the end.
    can_compose : bool
        Current writing capability admission, separate from settings readiness.
    can_manage_settings : bool
        Current admission to record rules or stop and resume new work.
    settings_ready : bool
        Whether the edition, recorded rules and stop state admit new content work.
    """

    items: tuple[AnnouncementSummary, ...]
    next_after: UUID | None
    can_compose: bool
    can_manage_settings: bool
    settings_ready: bool


@dataclass(frozen=True, slots=True)
class AnnouncementDetail:
    """Working and approved copy stay distinct through correction review.

    Attributes
    ----------
    id : UUID
        Exact announcement reference inside the admitted organization and edition.
    status : str
        Current draft, review, approval or cancellation state.
    version : int
        Command cursor required for optimistic mutation guards.
    draft : AnnouncementRevisionView
        Latest working copy, which may still need independent review.
    approved : AnnouncementRevisionView | None
        Latest independently approved copy, retained during a pending correction.
    review_note : str
        Latest retained reviewer feedback, admitted only with private history.
    can_compose : bool
        Current writing admission combined with rules readiness and cancellation.
    can_review : bool
        Current independent-review admission for this exact submitted draft.
    can_record_publication : bool
        Current authority to record external facts, including after stop or cancel.
    can_export_evidence : bool
        Separate current admission to download retained private evidence.
    stopped : bool
        Edition-wide stop state for new writing and review.
    history : tuple[AnnouncementHistoryEntry, ...]
        Bounded admitted command history, excluded from approved-copy downloads.
    publication_history : tuple[AnnouncementPublicationReportView, ...]
        Bounded retained claims and corrections, including earlier copy versions.
    """

    id: UUID
    status: str
    version: int
    draft: AnnouncementRevisionView
    approved: AnnouncementRevisionView | None
    review_note: str
    can_compose: bool
    can_review: bool
    can_record_publication: bool
    can_export_evidence: bool
    stopped: bool
    history: tuple[AnnouncementHistoryEntry, ...] = ()
    publication_history: tuple[AnnouncementPublicationReportView, ...] = ()


@dataclass(frozen=True, slots=True)
class AnnouncementDownload:
    """Bounded complete artifact, never a publication or permission token.

    Attributes
    ----------
    filename : str
        Owner-generated download name for the admitted artifact.
    content_type : str
        Media type matching the serialized artifact bytes.
    content : bytes
        Complete size-bounded approved copy or separately admitted private evidence.
    """

    filename: str
    content_type: str
    content: bytes
