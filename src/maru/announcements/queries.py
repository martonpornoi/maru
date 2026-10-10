"""Bounded current-scope projections with independent public-copy and history gates."""

from collections.abc import Callable
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import DatabaseError, transaction
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.events.announcements_scope import resolve_announcements_edition_scope
from maru.identity.queries import (
    account_display_labels,
    lock_account_references_for_evidence,
)

from .authorization import (
    AuthorizedAnnouncementScope,
    authorize_announcements_scope,
    can_use,
)
from .catalog import (
    MAX_EXPORT_BYTES,
    MAX_HISTORY,
    MAX_REPORTS,
    MAX_REVISIONS,
    RETENTION_CLASS,
)
from .contracts import (
    AnnouncementDetail,
    AnnouncementDownload,
    AnnouncementHistoryEntry,
    AnnouncementPage,
    AnnouncementPublicationReportView,
    AnnouncementReadRequest,
    AnnouncementRevisionView,
    AnnouncementSettingsView,
    AnnouncementSummary,
    AnnouncementVariantView,
    ManualChannel,
)
from .errors import AnnouncementDeniedError, AnnouncementError, AnnouncementLimitError
from .inputs import canonical_json, digest, identifier
from .models import (
    Announcement,
    AnnouncementCommandReceipt,
    AnnouncementControl,
    AnnouncementPublicationReport,
    AnnouncementReview,
    AnnouncementRevision,
    AnnouncementSettingsRevision,
)
from .readiness import require_announcements_integrity

MAX_PAGE_SIZE = 100


def _current_revision(item: Announcement) -> AnnouncementRevision:
    row = item.current_revision
    if row is None:
        raise AnnouncementError
    return row


def _ownership(request: AnnouncementReadRequest) -> dict[str, UUID]:
    return {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }


def _read[T](
    request: AnnouncementReadRequest,
    *,
    capability: str,
    fields: frozenset[str],
    purpose: str,
    load: Callable[[AuthorizedAnnouncementScope], T],
) -> T:
    authorize_announcements_scope(request, capability=capability, fields=fields)
    require_announcements_integrity()
    try:
        with transaction.atomic():
            scope = resolve_announcements_edition_scope(
                **_ownership(request), for_update=True
            )
            if (
                scope is None
                or lock_account_references_for_evidence(account_ids=(request.actor_id,))
                is None
            ):
                raise AnnouncementDeniedError
            admitted = authorize_announcements_scope(
                request, capability=capability, fields=fields
            )
            result = load(admitted)
            admitted = authorize_announcements_scope(
                request, capability=capability, fields=fields
            )
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=request.actor_id,
                    principal_context_id=None,
                    organization_id=request.organization_id,
                    event_edition_id=request.edition_id,
                    capability_code=capability,
                    operation=f"announcements.query.{purpose}",
                    target_type="events.edition",
                    target_id=request.edition_id,
                    outcome="allow",
                    reason_code=admitted.decision.reason_code,
                    correlation_id=request.correlation_id,
                    request_id=request.correlation_id,
                    source_channel="announcements",
                    obligations=("audit_sensitive_read",),
                    safe_metadata={"access_purpose": purpose},
                    retention_class=RETENTION_CLASS,
                )
            )
            return result
    except DatabaseError as error:
        raise AnnouncementError from error


def _bounded[T](rows: list[T], maximum: int) -> tuple[T, ...]:
    if len(rows) > maximum:
        raise AnnouncementLimitError
    return tuple(rows)


def _control(request: AnnouncementReadRequest) -> AnnouncementControl | None:
    return (
        AnnouncementControl.objects.filter(**_ownership(request))
        .select_related("current_settings")
        .only(
            "id",
            "settings_version",
            "stopped",
            "current_settings_id",
            "current_settings__id",
            "current_settings__review_on",
            "current_settings__channels",
        )
        .first()
    )


def _settings_ready(
    control: AnnouncementControl | None, scope: AuthorizedAnnouncementScope
) -> bool:
    today = timezone.now().astimezone(ZoneInfo(scope.edition.time_zone)).date()
    return bool(
        control
        and control.current_settings
        and not control.stopped
        and scope.edition.accepts_writes
        and control.current_settings.review_on >= today
    )


def load_announcement_settings(
    request: AnnouncementReadRequest,
) -> AnnouncementSettingsView:
    """Return readable configured rules and permitted choices, never policy defaults.

    Parameters
    ----------
    request : AnnouncementReadRequest
        Actual authenticated actor and exact organization/edition context.

    Returns
    -------
    AnnouncementSettingsView
        The complete validated result; failures do not return partial evidence.
    """

    def load(scope: AuthorizedAnnouncementScope) -> AnnouncementSettingsView:
        control = _control(request)
        row = control.current_settings if control else None
        can_manage = can_use(request, "announcements.manage_settings")
        private = None
        if row and can_manage:
            authorize_announcements_scope(
                request, capability="announcements.manage_settings"
            )
            private = AnnouncementSettingsRevision.objects.only(
                "id",
                "policy_name",
                "record_owner",
                "review_on",
                "policy_url",
                "policy_description",
            ).get(**_ownership(request), id=row.id)
            authorize_announcements_scope(
                request, capability="announcements.manage_settings"
            )
        return AnnouncementSettingsView(
            version=control.settings_version if control else 0,
            revision_id=row.id if row else None,
            configured=row is not None,
            stopped=control.stopped if control else False,
            rules_current=_settings_ready(control, scope),
            policy_name=private.policy_name if private else "",
            record_owner=private.record_owner if private else "",
            review_on=private.review_on if private else None,
            policy_url=private.policy_url if private else "",
            policy_description=private.policy_description if private else "",
            channels=tuple(ManualChannel(**channel) for channel in row.channels)
            if row
            else (),
            language_codes=scope.edition.language_codes,
            time_zone=scope.edition.time_zone,
            can_manage=can_manage,
        )

    return _read(
        request,
        capability="announcements.view",
        fields=frozenset({"announcement"}),
        purpose="settings",
        load=load,
    )


def list_announcements(
    request: AnnouncementReadRequest, *, after: UUID | None = None, limit: int = 50
) -> AnnouncementPage:
    """List only admitted announcement summaries with a bounded stable continuation.

    Parameters
    ----------
    request : AnnouncementReadRequest
        Actual authenticated actor and exact organization/edition context.
    after : UUID | None, default=None
        Optional exclusive UUID continuation from the preceding page.
    limit : int, default=50
        Bounded maximum number of summary rows to return.

    Returns
    -------
    AnnouncementPage
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    AnnouncementLimitError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise AnnouncementLimitError
    if after is not None:
        identifier(after)

    def load(scope: AuthorizedAnnouncementScope) -> AnnouncementPage:
        query = Announcement.objects.filter(**_ownership(request)).select_related(
            "current_revision"
        )
        if after:
            query = query.filter(id__gt=after)
        rows = list(query.order_by("id")[: limit + 1])
        control = _control(request)
        return AnnouncementPage(
            items=tuple(
                AnnouncementSummary(
                    row.id,
                    _current_revision(row).headline,
                    row.status,
                    row.version,
                    row.updated_at,
                )
                for row in rows[:limit]
            ),
            next_after=rows[limit - 1].id if len(rows) > limit else None,
            can_compose=can_use(request, "announcements.compose"),
            can_manage_settings=can_use(request, "announcements.manage_settings"),
            settings_ready=_settings_ready(control, scope),
        )

    return _read(
        request,
        capability="announcements.view",
        fields=frozenset({"announcement"}),
        purpose="list",
        load=load,
    )


def _item(request: AnnouncementReadRequest, announcement_id: UUID) -> Announcement:
    identifier(announcement_id)
    row = (
        Announcement.objects.filter(id=announcement_id, **_ownership(request))
        .select_related("current_revision", "approved_revision")
        .first()
    )
    if row is None or row.current_revision is None:
        raise AnnouncementError
    return row


def _report_rows(
    request: AnnouncementReadRequest, item: Announcement
) -> tuple[AnnouncementPublicationReport, ...]:
    return _bounded(
        list(
            AnnouncementPublicationReport.objects.filter(
                **_ownership(request),
                variant__revision__announcement=item,
            )
            .select_related("variant__revision")
            .order_by("command_receipt__control_sequence")[: MAX_REPORTS + 1]
        ),
        MAX_REPORTS,
    )


def _approved_item(
    request: AnnouncementReadRequest, announcement_id: UUID
) -> Announcement:
    identifier(announcement_id)
    row = (
        Announcement.objects.filter(id=announcement_id, **_ownership(request))
        .select_related("approved_revision")
        .only(
            "id",
            "approved_revision_id",
            "approved_revision__id",
            "approved_revision__number",
            "approved_revision__headline",
            "approved_revision__body",
            "approved_revision__language_code",
            "approved_revision__occurred_at",
        )
        .first()
    )
    if row is None or row.approved_revision is None:
        raise AnnouncementError
    return row


def _revision_view(
    row: AnnouncementRevision,
    reports: tuple[AnnouncementPublicationReport, ...],
    labels: dict[UUID, str],
) -> AnnouncementRevisionView:
    latest = {}
    by_id = {report.id: report for report in reports}
    replacement = {
        report.supersedes_report_id: report
        for report in reports
        if report.supersedes_report_id
    }
    for recorded in reports:
        if recorded.supersedes_report_id in by_id:
            continue
        variant = recorded.variant
        # Correcting an older claim must not promote it above a later posting.
        current = recorded
        while current.id in replacement:
            current = replacement[current.id]
        latest[(variant.channel_code, variant.language_code, variant.channel_url)] = (
            current
        )
    variants = []
    for variant in row.variants.only(
        "id",
        "channel_code",
        "channel_label",
        "channel_url",
        "language_code",
        "headline",
        "body",
        "copy_digest",
    ).order_by("channel_code", "language_code"):
        report = latest.get(
            (variant.channel_code, variant.language_code, variant.channel_url)
        )
        status = "no_record"
        if report:
            status = (
                "report_withdrawn"
                if report.withdrawn
                else "reported"
                if report.variant.copy_digest == variant.copy_digest
                else "update_needed"
            )
        variants.append(
            AnnouncementVariantView(
                id=variant.id,
                channel_code=variant.channel_code,
                channel_label=variant.channel_label,
                channel_url=variant.channel_url,
                language_code=variant.language_code,
                headline=variant.headline,
                body=variant.body,
                publication_status=status,
                publication_report_id=report.id if report else None,
                publication_url=report.publication_url
                if report and not report.withdrawn
                else "",
                publication_recorded_at=report.occurred_at if report else None,
                publication_published_at=report.published_at
                if report and not report.withdrawn
                else None,
                publication_reporter_label=labels.get(
                    report.actor_id, "Former organizer"
                )
                if report
                else "",
                reported_headline=report.variant.headline
                if report and not report.withdrawn
                else "",
                reported_body=report.variant.body
                if report and not report.withdrawn
                else "",
            )
        )
    return AnnouncementRevisionView(
        row.id,
        row.number,
        row.headline,
        row.body,
        row.language_code,
        tuple(variants),
        row.occurred_at,
    )


def load_announcement(
    request: AnnouncementReadRequest, *, announcement_id: UUID
) -> AnnouncementDetail:
    """Read working copy and operational history only with all their field rights.

    Parameters
    ----------
    request : AnnouncementReadRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.

    Returns
    -------
    AnnouncementDetail
        The complete validated result; failures do not return partial evidence.
    """

    def load(scope: AuthorizedAnnouncementScope) -> AnnouncementDetail:
        item, control = _item(request, announcement_id), _control(request)
        reports = _report_rows(request, item)
        receipts = _bounded(
            list(
                AnnouncementCommandReceipt.objects.filter(
                    **_ownership(request), announcement=item
                ).order_by("control_sequence")[: MAX_HISTORY + 1]
            ),
            MAX_HISTORY,
        )
        labels = account_display_labels(
            {row.actor_id for row in reports} | {row.actor_id for row in receipts}
        )
        current_revision = _current_revision(item)
        latest_review = AnnouncementReview.objects.filter(
            revision=item.current_revision
        ).first()
        ready = _settings_ready(control, scope)
        can_review = (
            ready
            and item.status == "in_review"
            and can_use(request, "announcements.review")
            and not AnnouncementRevision.objects.filter(
                announcement=item,
                round_id=current_revision.round_id,
                actor_id=request.actor_id,
            ).exists()
        )
        can_record = (
            scope.edition.accepts_writes
            and item.approved_revision_id is not None
            and can_use(request, "announcements.record_publication")
        )
        superseded = {
            row.supersedes_report_id for row in reports if row.supersedes_report_id
        }
        return AnnouncementDetail(
            id=item.id,
            status=item.status,
            version=item.version,
            draft=_revision_view(current_revision, reports, labels),
            approved=_revision_view(item.approved_revision, reports, labels)
            if item.approved_revision
            else None,
            review_note=latest_review.note if latest_review else "",
            can_compose=ready
            and item.status != "cancelled"
            and can_use(request, "announcements.compose"),
            can_review=can_review,
            can_record_publication=can_record,
            can_export_evidence=can_use(request, "announcements.export_evidence"),
            stopped=control.stopped if control else False,
            history=tuple(
                AnnouncementHistoryEntry(
                    row.operation,
                    labels.get(row.actor_id, "Former organizer"),
                    row.occurred_at,
                    row.reason,
                )
                for row in receipts
            ),
            publication_history=tuple(
                AnnouncementPublicationReportView(
                    id=row.id,
                    variant_id=row.variant_id,
                    revision_id=row.variant.revision_id,
                    revision_number=row.variant.revision.number,
                    channel_code=row.variant.channel_code,
                    channel_label=row.variant.channel_label,
                    channel_url=row.variant.channel_url,
                    language_code=row.variant.language_code,
                    publication_url=row.publication_url,
                    publication_published_at=row.published_at,
                    publication_recorded_at=row.occurred_at,
                    publication_reporter_label=labels.get(
                        row.actor_id, "Former organizer"
                    ),
                    withdrawn=row.withdrawn,
                    supersedes_report_id=row.supersedes_report_id,
                    reason=row.reason,
                    can_correct=can_record and row.id not in superseded,
                )
                for row in reports
            ),
        )

    return _read(
        request,
        capability="announcements.view",
        fields=frozenset({"announcement", "approved_copy", "history"}),
        purpose="detail",
        load=load,
    )


def _copy(row: AnnouncementRevision) -> dict[str, object]:
    return {
        "revision_id": row.id,
        "revision_number": row.number,
        "headline": row.headline,
        "body": row.body,
        "language_code": row.language_code,
        "variants": list(
            row.variants.order_by("channel_code", "language_code").values(
                "id",
                "channel_code",
                "channel_label",
                "channel_url",
                "language_code",
                "headline",
                "body",
            )
        ),
    }


def _download(
    announcement_id: UUID, kind: str, payload: dict[str, object]
) -> AnnouncementDownload:
    body = canonical_json(
        {
            "format": "maru-announcements",
            "format_version": 1,
            "kind": kind,
            "payload": payload,
            "payload_sha256": digest(payload),
        }
    )
    if len(body) > MAX_EXPORT_BYTES:
        raise AnnouncementLimitError
    return AnnouncementDownload(
        f"announcement-{announcement_id}-{kind}.json",
        "application/json; charset=utf-8",
        body,
    )


def load_approved_announcement_copy(
    request: AnnouncementReadRequest, *, announcement_id: UUID
) -> AnnouncementDownload:
    """Download approved public-facing text without review notes or actor evidence.

    Parameters
    ----------
    request : AnnouncementReadRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.

    Returns
    -------
    AnnouncementDownload
        The complete validated result; failures do not return partial evidence.
    """

    def load(scope: AuthorizedAnnouncementScope) -> AnnouncementDownload:
        del scope
        item = _approved_item(request, announcement_id)
        approved_revision = item.approved_revision
        if approved_revision is None:
            raise AnnouncementError
        return _download(
            item.id,
            "approved-copy",
            {
                "announcement_id": item.id,
                "copy": _copy(approved_revision),
                "publication": "manual; download is not publication",
            },
        )

    return _read(
        request,
        capability="announcements.view",
        fields=frozenset({"approved_copy"}),
        purpose="approved_copy",
        load=load,
    )


def load_approved_announcement_preview(
    request: AnnouncementReadRequest, *, announcement_id: UUID
) -> AnnouncementRevisionView:
    """Read only approved public text with its own field-level admission.

    Parameters
    ----------
    request : AnnouncementReadRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.

    Returns
    -------
    AnnouncementRevisionView
        The complete validated result; failures do not return partial evidence.
    """

    def load(scope: AuthorizedAnnouncementScope) -> AnnouncementRevisionView:
        del scope
        item = _approved_item(request, announcement_id)
        approved_revision = item.approved_revision
        if approved_revision is None:
            raise AnnouncementError
        return _revision_view(approved_revision, (), {})

    return _read(
        request,
        capability="announcements.view",
        fields=frozenset({"approved_copy"}),
        purpose="approved_copy",
        load=load,
    )


def export_announcement_evidence(
    request: AnnouncementReadRequest, *, announcement_id: UUID
) -> AnnouncementDownload:
    """Export one complete bounded history under separate privileged authority.

    Parameters
    ----------
    request : AnnouncementReadRequest
        Actual authenticated actor and exact organization/edition context.
    announcement_id : UUID
        Announcement identifier resolved only inside the admitted scope.

    Returns
    -------
    AnnouncementDownload
        The complete validated result; failures do not return partial evidence.
    """

    def load(scope: AuthorizedAnnouncementScope) -> AnnouncementDownload:
        del scope
        item = _item(request, announcement_id)
        revisions = _bounded(
            list(
                AnnouncementRevision.objects.filter(
                    **_ownership(request), announcement=item
                ).order_by("number")[: MAX_REVISIONS + 1]
            ),
            MAX_REVISIONS,
        )
        reports = _report_rows(request, item)
        receipts = _bounded(
            list(
                AnnouncementCommandReceipt.objects.filter(
                    **_ownership(request), announcement=item
                ).order_by("control_sequence")[: MAX_HISTORY + 1]
            ),
            MAX_HISTORY,
        )
        reviews = list(
            AnnouncementReview.objects.filter(
                **_ownership(request), revision__announcement=item
            )
            .order_by("occurred_at")
            .values(
                "id",
                "revision_id",
                "actor_id",
                "occurred_at",
                "decision",
                "note",
                "command_receipt_id",
            )
        )
        settings_ids = {row.settings_revision_id for row in revisions}
        rules = list(
            AnnouncementSettingsRevision.objects.filter(
                **_ownership(request), id__in=settings_ids
            )
            .order_by("number")
            .values(
                "id",
                "number",
                "policy_name",
                "policy_url",
                "policy_description",
                "record_owner",
                "review_on",
                "channels",
                "actor_id",
                "occurred_at",
                "command_receipt_id",
            )
        )
        settings_receipts = list(
            AnnouncementCommandReceipt.objects.filter(
                **_ownership(request),
                id__in=[row["command_receipt_id"] for row in rules],
            ).order_by("control_sequence")
        )
        receipts = tuple(
            sorted(
                (*receipts, *settings_receipts), key=lambda row: row.control_sequence
            )
        )
        payload = {
            "organization_id": request.organization_id,
            "edition_id": request.edition_id,
            "announcement_id": item.id,
            "version": item.version,
            "status": item.status,
            "current_revision_id": item.current_revision_id,
            "approved_revision_id": item.approved_revision_id,
            "revisions": [
                {
                    **_copy(row),
                    "previous_revision_id": row.previous_revision_id,
                    "base_approved_revision_id": row.base_approved_revision_id,
                    "round_id": row.round_id,
                    "settings_revision_id": row.settings_revision_id,
                    "actor_id": row.actor_id,
                    "occurred_at": row.occurred_at,
                    "command_receipt_id": row.command_receipt_id,
                }
                for row in revisions
            ],
            "reviews": reviews,
            "record_keeping_confirmations": rules,
            "publication_reports": [
                {
                    "id": row.id,
                    "variant_id": row.variant_id,
                    "supersedes_report_id": row.supersedes_report_id,
                    "withdrawn": row.withdrawn,
                    "publication_url": row.publication_url,
                    "published_at": row.published_at,
                    "actor_id": row.actor_id,
                    "recorded_at": row.occurred_at,
                    "reason": row.reason,
                    "command_receipt_id": row.command_receipt_id,
                }
                for row in reports
            ],
            "commands": [
                {
                    "id": row.id,
                    "operation": row.operation,
                    "actor_id": row.actor_id,
                    "object_id": row.object_id,
                    "resulting_version": row.resulting_version,
                    "occurred_at": row.occurred_at,
                    "reason": row.reason,
                    "request_digest": row.request_digest,
                    "control_sequence": row.control_sequence,
                }
                for row in receipts
            ],
        }
        return _download(item.id, "private-evidence", payload)

    return _read(
        request,
        capability="announcements.export_evidence",
        fields=frozenset({"evidence"}),
        purpose="evidence_export",
        load=load,
    )
