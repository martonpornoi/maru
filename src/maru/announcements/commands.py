"""Canonical announcement writes; every adapter shares these owner commands."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from .authorization import authorize_announcements_scope
from .catalog import (
    MAX_HISTORY,
    MAX_NOTE,
    MAX_REPORTS,
    MAX_REVISIONS,
    MAX_STORED_TEXT_BYTES,
)
from .command_support import CommandContext, execute
from .contracts import (
    AnnouncementCommandRequest,
    AnnouncementCommandResult,
    AnnouncementDraftInput,
    AnnouncementSettingsInput,
)
from .errors import (
    AnnouncementDeniedError,
    AnnouncementError,
    AnnouncementLimitError,
    AnnouncementSettingsRequiredError,
    AnnouncementStateConflictError,
    AnnouncementVersionConflictError,
)
from .inputs import (
    canonical_json,
    digest,
    draft_payload,
    identifier,
    normalize_draft,
    normalize_settings,
    safe_url,
    text,
    version,
)
from .models import (
    Announcement,
    AnnouncementPublicationReport,
    AnnouncementReview,
    AnnouncementRevision,
    AnnouncementSettingsRevision,
    AnnouncementVariant,
)


def _admit(request: AnnouncementCommandRequest, capability: str) -> None:
    authorize_announcements_scope(request, capability=f"announcements.{capability}")


def _writes_open(context: CommandContext, *, stopped_ok: bool = False) -> None:
    if not context.scope.edition.accepts_writes or (
        context.control.stopped and not stopped_ok
    ):
        raise AnnouncementStateConflictError


def _settings(context: CommandContext) -> AnnouncementSettingsRevision:
    _writes_open(context)
    row = context.control.current_settings
    today = context.occurred_at.astimezone(
        ZoneInfo(context.scope.edition.time_zone)
    ).date()
    if row is None or row.review_on < today:
        raise AnnouncementSettingsRequiredError
    return row


def _item(
    context: CommandContext, announcement_id: UUID, expected_version: int
) -> Announcement:
    row = (
        Announcement.objects.select_for_update()
        .filter(
            id=announcement_id,
            organization_id=context.request.organization_id,
            edition_id=context.request.edition_id,
        )
        .first()
    )
    if row is None:
        raise AnnouncementError
    if row.version != expected_version:
        raise AnnouncementVersionConflictError
    return row


def _advance(item: Announcement) -> None:
    if item.version >= MAX_HISTORY:
        raise AnnouncementLimitError
    item.version += 1
    item.save()


def _write_revision(
    context: CommandContext,
    item: Announcement,
    draft: AnnouncementDraftInput,
    settings: AnnouncementSettingsRevision,
) -> AnnouncementRevision:
    previous = item.current_revision
    number = previous.number + 1 if previous else 1
    text_bytes = len(canonical_json(draft_payload(draft)))
    retained = (
        AnnouncementRevision.objects.filter(announcement=item).aggregate(
            total=Sum("text_bytes")
        )["total"]
        or 0
    )
    if number > MAX_REVISIONS or retained + text_bytes > MAX_STORED_TEXT_BYTES:
        raise AnnouncementLimitError
    channels = {channel["code"]: channel for channel in settings.channels}
    languages = context.scope.edition.language_codes
    if draft.language_code not in languages or any(
        v.language_code not in languages or v.channel_code not in channels
        for v in draft.variants
    ):
        raise ValidationError(
            "Choose the current event languages and publishing channels.",
            code="unavailable_selection",
        )
    if previous is None or item.current_revision_id == item.approved_revision_id:
        base_approved = item.approved_revision
        round_id = uuid4()
    else:
        base_approved = previous.base_approved_revision
        round_id = previous.round_id
    revision = AnnouncementRevision.objects.create(
        **context.evidence(),
        announcement=item,
        number=number,
        previous_revision=previous,
        base_approved_revision=base_approved,
        round_id=round_id,
        settings_revision=settings,
        headline=draft.headline,
        body=draft.body,
        language_code=draft.language_code,
        text_bytes=text_bytes,
    )
    for copy in draft.variants:
        channel = channels[copy.channel_code]
        AnnouncementVariant.objects.create(
            **context.evidence(),
            revision=revision,
            channel_code=copy.channel_code,
            channel_label=channel["label"],
            channel_url=channel["url"],
            language_code=copy.language_code,
            headline=copy.headline,
            body=copy.body,
            copy_digest=digest({"headline": copy.headline, "body": copy.body}),
        )
    item.current_revision = revision
    item.status = "draft"
    return revision


def update_announcement_settings(
    request: AnnouncementCommandRequest,
    *,
    settings: AnnouncementSettingsInput,
    expected_version: int,
) -> AnnouncementCommandResult:
    """Record an organizer's explicit rules confirmation and channel choices.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    settings : AnnouncementSettingsInput
        Explicit rules confirmation and manual channel selections.
    expected_version : int
        Optimistic version observed by the caller.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.
    """
    _admit(request, "manage_settings")
    value = normalize_settings(settings)
    expected = version(expected_version, initial=True)

    def write(context: CommandContext) -> tuple[UUID, None, int]:
        _writes_open(context, stopped_ok=True)
        if context.control.settings_version != expected:
            raise AnnouncementVersionConflictError
        previous = AnnouncementSettingsRevision.objects.filter(
            organization_id=context.request.organization_id,
            edition_id=context.request.edition_id,
        ).values_list("channels", flat=True)
        for channels in previous.iterator(chunk_size=100):
            old_channels = {channel["code"]: channel for channel in channels}
            if any(
                channel.code in old_channels
                and not old_channels[channel.code]["url"]
                and old_channels[channel.code]["label"] != channel.label
                for channel in value.channels
            ):
                raise ValidationError(
                    "Add a new channel for a different destination without a link.",
                    code="channel_identity_changed",
                )
        if (
            value.review_on
            < context.occurred_at.astimezone(
                ZoneInfo(context.scope.edition.time_zone)
            ).date()
        ):
            raise ValidationError(
                "Choose a current or future rules review date.",
                code="rules_review_overdue",
            )
        row = AnnouncementSettingsRevision.objects.create(
            **context.evidence(),
            number=expected + 1,
            policy_name=value.policy_name,
            policy_description=value.policy_description,
            policy_url=value.policy_url,
            record_owner=value.record_owner,
            review_on=value.review_on,
            channels=[asdict(channel) for channel in value.channels],
        )
        context.control.settings_version += 1
        context.control.current_settings = row
        return row.id, None, context.control.settings_version

    return execute(
        request,
        operation="settings_update",
        intent={"settings": asdict(value), "expected_version": expected},
        write=write,
    )


def set_announcements_stopped(
    request: AnnouncementCommandRequest,
    *,
    stopped: bool,
    expected_version: int,
    reason: str,
) -> AnnouncementCommandResult:
    """Stop or resume new work without deleting retained records or external posts.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    stopped : bool
        Whether new announcement work should stop.
    expected_version : int
        Optimistic version observed by the caller.
    reason : str
        Bounded operational explanation retained with this command.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    _admit(request, "manage_settings")
    if type(stopped) is not bool:
        raise ValidationError("Choose stop or resume.", code="invalid_state")
    expected, note = version(expected_version), text(reason, maximum=MAX_NOTE)

    def write(context: CommandContext) -> tuple[UUID, None, int]:
        _writes_open(context, stopped_ok=True)
        if context.control.settings_version != expected:
            raise AnnouncementVersionConflictError
        if context.control.stopped == stopped:
            raise AnnouncementStateConflictError
        context.control.stopped = stopped
        if not stopped:
            _settings(context)
        context.control.settings_version += 1
        return context.control.id, None, context.control.settings_version

    return execute(
        request,
        operation="stop" if stopped else "resume",
        intent={"stopped": stopped, "expected_version": expected},
        write=write,
        reason=note,
    )


def create_announcement(
    request: AnnouncementCommandRequest,
    *,
    draft: AnnouncementDraftInput,
    expected_settings_version: int,
) -> AnnouncementCommandResult:
    """Create one draft from explicit text under current confirmed record rules.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    draft : AnnouncementDraftInput
        Complete proposed public text and destination copies.
    expected_settings_version : int
        Record-keeping settings version observed by the caller.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.
    """
    _admit(request, "compose")
    value, expected = normalize_draft(draft), version(expected_settings_version)

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        settings = _settings(context)
        if context.control.settings_version != expected:
            raise AnnouncementVersionConflictError
        item = Announcement.objects.create(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _write_revision(context, item, value, settings)
        item.save()
        return item.id, item.id, item.version

    return execute(
        request,
        operation="create",
        intent={"draft": draft_payload(value), "expected_settings_version": expected},
        write=write,
    )


def revise_announcement(
    request: AnnouncementCommandRequest,
    *,
    announcement_id: UUID,
    draft: AnnouncementDraftInput,
    expected_version: int,
    expected_settings_version: int,
    reason: str,
) -> AnnouncementCommandResult:
    """Append draft or correction text while preserving the last approved copy.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.
    draft : AnnouncementDraftInput
        Complete proposed public text and destination copies.
    expected_version : int
        Optimistic version observed by the caller.
    expected_settings_version : int
        Record-keeping settings and destinations observed by the caller.
    reason : str
        Bounded operational explanation retained with this command.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.
    """
    _admit(request, "compose")
    selected, expected = identifier(announcement_id), version(expected_version)
    expected_settings = version(expected_settings_version)
    value, note = normalize_draft(draft), text(reason, maximum=MAX_NOTE)

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        settings = _settings(context)
        if context.control.settings_version != expected_settings:
            raise AnnouncementVersionConflictError
        item = _item(context, selected, expected)
        if item.status == "cancelled":
            raise AnnouncementStateConflictError
        row = _write_revision(context, item, value, settings)
        _advance(item)
        return row.id, item.id, item.version

    return execute(
        request,
        operation="revise",
        intent={
            "announcement_id": selected,
            "draft": draft_payload(value),
            "expected_version": expected,
            "expected_settings_version": expected_settings,
        },
        write=write,
        reason=note,
    )


def request_announcement_review(
    request: AnnouncementCommandRequest, *, announcement_id: UUID, expected_version: int
) -> AnnouncementCommandResult:
    """Freeze the current draft for a separate person's exact-copy decision.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.
    expected_version : int
        Optimistic version observed by the caller.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.
    """
    _admit(request, "compose")
    selected, expected = identifier(announcement_id), version(expected_version)

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        _settings(context)
        item = _item(context, selected, expected)
        if (
            item.status != "draft"
            or item.current_revision_id is None
            or AnnouncementReview.objects.filter(
                revision_id=item.current_revision_id
            ).exists()
        ):
            raise AnnouncementStateConflictError
        item.status = "in_review"
        _advance(item)
        return item.current_revision_id, item.id, item.version

    return execute(
        request,
        operation="request_review",
        intent={"announcement_id": selected, "expected_version": expected},
        write=write,
    )


def review_announcement(
    request: AnnouncementCommandRequest,
    *,
    announcement_id: UUID,
    revision_id: UUID,
    expected_version: int,
    decision: str,
    note: str = "",
) -> AnnouncementCommandResult:
    """Independently decide an exact submitted revision, retaining every editor.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.
    revision_id : UUID
        Exact retained copy revision to decide.
    expected_version : int
        Optimistic version observed by the caller.
    decision : str
        Approve or request changes for the exact submitted revision.
    note : str, default=''
        Private reviewer explanation; required when requesting changes.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    _admit(request, "review")
    selected, revision, expected = (
        identifier(announcement_id),
        identifier(revision_id),
        version(expected_version),
    )
    if decision not in ("approve", "changes_requested"):
        raise ValidationError(
            "Approve the copy or ask for changes.", code="invalid_decision"
        )
    reason = text(note, maximum=MAX_NOTE, required=decision == "changes_requested")

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        _settings(context)
        item = _item(context, selected, expected)
        current = item.current_revision
        if item.status != "in_review" or current is None or current.id != revision:
            raise AnnouncementStateConflictError
        if AnnouncementRevision.objects.filter(
            announcement=item,
            round_id=current.round_id,
            actor_id=request.actor_id,
        ).exists():
            raise AnnouncementDeniedError
        row = AnnouncementReview.objects.create(
            **context.evidence(), revision_id=revision, decision=decision, note=reason
        )
        item.status = "approved" if decision == "approve" else "changes_requested"
        if decision == "approve":
            item.approved_revision_id = revision
        _advance(item)
        return row.id, item.id, item.version

    return execute(
        request,
        operation=decision,
        intent={
            "announcement_id": selected,
            "revision_id": revision,
            "expected_version": expected,
            "decision": decision,
            "note": reason,
        },
        write=write,
        reason=reason,
    )


def _publication_time(value: datetime | None) -> datetime | None:
    if value is not None and (
        type(value) is not datetime
        or timezone.is_naive(value)
        or value > timezone.now()
    ):
        raise ValidationError(
            "Enter an actual past publication time with a time zone.",
            code="invalid_publication_time",
        )
    return value


def _variant(
    context: CommandContext, item: Announcement, variant_id: UUID
) -> AnnouncementVariant:
    row = AnnouncementVariant.objects.filter(
        id=variant_id,
        organization_id=context.request.organization_id,
        edition_id=context.request.edition_id,
        revision__announcement=item,
        revision__review__decision="approve",
    ).first()
    if row is None:
        raise AnnouncementError
    return row


def _report_limit(item: Announcement) -> None:
    if (
        AnnouncementPublicationReport.objects.filter(
            variant__revision__announcement=item
        ).count()
        >= MAX_REPORTS
    ):
        raise AnnouncementLimitError


def record_announcement_publication(
    request: AnnouncementCommandRequest,
    *,
    announcement_id: UUID,
    variant_id: UUID,
    expected_version: int,
    publication_url: str = "",
    published_at: datetime | None = None,
) -> AnnouncementCommandResult:
    """Record a human publication claim; never assert provider verification.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.
    variant_id : UUID
        Exact independently approved destination copy.
    expected_version : int
        Optimistic version observed by the caller.
    publication_url : str, default=''
        Optional HTTPS reference for the reported external post.
    published_at : datetime | None, default=None
        Optional actual publication time claimed by the reporting actor.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.
    """
    _admit(request, "record_publication")
    selected, variant, expected = (
        identifier(announcement_id),
        identifier(variant_id),
        version(expected_version),
    )
    url, occurred = safe_url(publication_url), _publication_time(published_at)

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        # Retrospective facts remain recordable when rules expire or work stops.
        _writes_open(context, stopped_ok=True)
        item = _item(context, selected, expected)
        copy = _variant(context, item, variant)
        if AnnouncementPublicationReport.objects.filter(variant=copy).exists():
            raise AnnouncementStateConflictError
        _report_limit(item)
        row = AnnouncementPublicationReport.objects.create(
            **context.evidence(),
            variant=copy,
            publication_url=url,
            published_at=occurred,
        )
        _advance(item)
        return row.id, item.id, item.version

    return execute(
        request,
        operation="record_publication",
        intent={
            "announcement_id": selected,
            "variant_id": variant,
            "expected_version": expected,
            "publication_url": url,
            "published_at": occurred,
        },
        write=write,
    )


def correct_announcement_publication(
    request: AnnouncementCommandRequest,
    *,
    announcement_id: UUID,
    report_id: UUID,
    expected_version: int,
    withdrawn: bool,
    reason: str,
    publication_url: str = "",
    published_at: datetime | None = None,
) -> AnnouncementCommandResult:
    """Append corrected reporting evidence; withdrawal never claims post removal.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.
    report_id : UUID
        Latest retained report in the correction chain.
    expected_version : int
        Optimistic version observed by the caller.
    withdrawn : bool
        Whether the prior report is withdrawn without claiming external removal.
    reason : str
        Bounded operational explanation retained with this command.
    publication_url : str, default=''
        Optional HTTPS reference for the reported external post.
    published_at : datetime | None, default=None
        Optional actual publication time claimed by the reporting actor.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    _admit(request, "record_publication")
    selected, report, expected = (
        identifier(announcement_id),
        identifier(report_id),
        version(expected_version),
    )
    if type(withdrawn) is not bool:
        raise ValidationError(
            "Choose whether this report was mistaken.", code="invalid_report"
        )
    url, occurred, note = (
        safe_url(publication_url),
        _publication_time(published_at),
        text(reason, maximum=MAX_NOTE),
    )
    if withdrawn and (url or occurred):
        raise ValidationError(
            "A withdrawn report cannot claim a publication.", code="invalid_report"
        )

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        _writes_open(context, stopped_ok=True)
        item = _item(context, selected, expected)
        previous = AnnouncementPublicationReport.objects.filter(
            id=report,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            variant__revision__announcement=item,
            replacement__isnull=True,
        ).first()
        if previous is None:
            raise AnnouncementStateConflictError
        _report_limit(item)
        row = AnnouncementPublicationReport.objects.create(
            **context.evidence(),
            variant_id=previous.variant_id,
            supersedes_report=previous,
            withdrawn=withdrawn,
            publication_url=url,
            published_at=occurred,
            reason=note,
        )
        _advance(item)
        return row.id, item.id, item.version

    return execute(
        request,
        operation="withdraw_report" if withdrawn else "correct_publication",
        intent={
            "announcement_id": selected,
            "report_id": report,
            "expected_version": expected,
            "withdrawn": withdrawn,
            "publication_url": url,
            "published_at": occurred,
        },
        write=write,
        reason=note,
    )


def cancel_announcement(
    request: AnnouncementCommandRequest,
    *,
    announcement_id: UUID,
    expected_version: int,
    reason: str,
) -> AnnouncementCommandResult:
    """Stop pending publication tasks without rewriting approved or external history.

    Parameters
    ----------
    request : AnnouncementCommandRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.
    expected_version : int
        Optimistic version observed by the caller.
    reason : str
        Bounded operational explanation retained with this command.

    Returns
    -------
    AnnouncementCommandResult
        The complete validated result; failures do not return partial evidence.
    """
    _admit(request, "compose")
    selected, expected, note = (
        identifier(announcement_id),
        version(expected_version),
        text(reason, maximum=MAX_NOTE),
    )

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        _writes_open(context, stopped_ok=True)
        item = _item(context, selected, expected)
        if item.status == "cancelled":
            raise AnnouncementStateConflictError
        item.status = "cancelled"
        _advance(item)
        return item.id, item.id, item.version

    return execute(
        request,
        operation="cancel",
        intent={"announcement_id": selected, "expected_version": expected},
        write=write,
        reason=note,
    )
