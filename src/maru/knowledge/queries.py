"""Separately admitted current-reader, working-history and complete evidence queries."""

from collections.abc import Callable
from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.guidance_authority_queries import guidance_team_reference
from maru.events.knowledge_scope import resolve_knowledge_edition_scope
from maru.identity.queries import (
    account_display_labels,
    lock_account_references_for_evidence,
)

from .authorization import AuthorizedGuidanceScope, authorize_guidance_scope, can_use
from .catalog import (
    AUDIENCE_LABEL,
    CAPABILITY_FIELDS,
    MAX_CONTROL_HISTORY,
    MAX_EXPORT_BYTES,
    MAX_HISTORY,
    MAX_PAGE_SIZE,
    MAX_QUERY,
    MAX_REVISIONS,
    OWNER_LABEL,
    PLACEMENTS,
    PURPOSE,
    RETENTION_CLASS,
)
from .contracts import (
    GuidanceActions,
    GuidanceCurrentPage,
    GuidanceCurrentSummary,
    GuidanceCurrentView,
    GuidanceDownload,
    GuidanceHistoryEntry,
    GuidanceOptions,
    GuidanceReadRequest,
    GuidanceResumePreview,
    GuidanceRevisionView,
    GuidanceSettingsView,
    GuidanceWorkingDetail,
    GuidanceWorkingPage,
    GuidanceWorkingSummary,
)
from .errors import (
    GuidanceDeniedError,
    GuidanceError,
    GuidanceLimitError,
    GuidanceNotAvailableError,
)
from .evidence_bound import require_complete_export_bound
from .inputs import canonical_json, digest, identifier, text
from .models import (
    GuidanceCommandReceipt,
    GuidanceControl,
    GuidanceItem,
    GuidanceReview,
    GuidanceRevision,
    GuidanceSettingsRevision,
)
from .readiness import require_knowledge_integrity
from .resume import current_copy_rows, retained_current_snapshot


def _ownership(request: GuidanceReadRequest) -> dict[str, UUID]:
    return {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }


def _read[T](
    request: GuidanceReadRequest,
    *,
    capability: str,
    fields: frozenset[str],
    purpose: str,
    load: Callable[[AuthorizedGuidanceScope], T],
) -> T:
    authorize_guidance_scope(request, capability=capability, fields=fields)
    require_knowledge_integrity()
    try:
        with transaction.atomic():
            scope = resolve_knowledge_edition_scope(
                **_ownership(request), for_update=True
            )
            if (
                scope is None
                or lock_account_references_for_evidence(account_ids=(request.actor_id,))
                is None
            ):
                raise GuidanceDeniedError
            admitted = authorize_guidance_scope(
                request, capability=capability, fields=fields
            )
            result = load(admitted)
            admitted = authorize_guidance_scope(
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
                    operation=f"knowledge.query.{purpose}",
                    target_type="events.edition",
                    target_id=request.edition_id,
                    outcome="allow",
                    reason_code=admitted.decision.reason_code,
                    correlation_id=request.correlation_id,
                    request_id=request.correlation_id,
                    source_channel="knowledge",
                    obligations=("audit_sensitive_read",),
                    safe_metadata={"access_purpose": purpose},
                    retention_class=RETENTION_CLASS,
                )
            )
            return result
    except DatabaseError as error:
        raise GuidanceError from error


def _bounded[T](rows: list[T], maximum: int) -> tuple[T, ...]:
    if len(rows) > maximum:
        raise GuidanceLimitError
    return tuple(rows)


def _control(request: GuidanceReadRequest) -> GuidanceControl | None:
    return (
        GuidanceControl.objects.filter(**_ownership(request))
        .select_related("current_settings")
        .only(
            "id",
            "sequence",
            "settings_version",
            "stopped",
            "current_settings_id",
            "current_settings__id",
            "current_settings__review_on",
        )
        .first()
    )


def _actions(request: GuidanceReadRequest) -> GuidanceActions:
    return GuidanceActions(
        can_view_current=can_use(request, "knowledge.view_current"),
        can_view_working=can_use(request, "knowledge.view_working"),
        can_compose=can_use(request, "knowledge.compose"),
        can_review=can_use(request, "knowledge.review"),
        can_withdraw=can_use(request, "knowledge.withdraw"),
        can_manage_settings=can_use(request, "knowledge.manage_settings"),
        can_export_evidence=can_use(request, "knowledge.export_evidence"),
    )


def _options(
    request: GuidanceReadRequest, scope: AuthorizedGuidanceScope
) -> GuidanceOptions:
    control = _control(request)
    rules = control.current_settings if control else None
    team = guidance_team_reference(**_ownership(request))
    today = timezone.now().astimezone(ZoneInfo(scope.edition.time_zone)).date()
    placements = (
        PLACEMENTS
        if scope.edition.adoption_profile_code == "announcements_guidance"
        else ("knowledge.compose",)
    )
    blockers = []
    if rules is None:
        blockers.append("rules_missing")
    elif rules.review_on < today:
        blockers.append("rules_overdue")
    if control and control.stopped:
        blockers.append("work_stopped")
    if not scope.edition.accepts_writes:
        blockers.append("event_closed")
    if team is None or not team.ready:
        blockers.append("team_unavailable")
    return GuidanceOptions(
        settings_version=control.settings_version if control else 0,
        control_version=control.sequence if control else 0,
        configured=rules is not None,
        stopped=control.stopped if control else False,
        rules_current=not blockers,
        language_codes=scope.edition.language_codes,
        time_zone=scope.edition.time_zone,
        placement_codes=placements,
        owner_label=OWNER_LABEL,
        audience_label=AUDIENCE_LABEL,
        purpose=PURPOSE,
        actions=_actions(request),
        blocking_reasons=tuple(blockers),
    )


def load_guidance_options(
    request: GuidanceReadRequest,
    *,
    capability: str = "knowledge.view_working",
) -> GuidanceOptions:
    """Return safe writer choices and current cursors without reading private rules.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual actor and independently authorized scope.
    capability : str, default='knowledge.view_working'
        Owning page's declared capability; each listed capability admits safe metadata.

    Returns
    -------
    GuidanceOptions
        Fixed purpose, available choices, current readiness and action admission.
    """
    return _read(
        request,
        capability=capability,
        fields=CAPABILITY_FIELDS.get(capability, frozenset()),
        purpose="options",
        load=lambda scope: _options(request, scope),
    )


def load_guidance_settings(request: GuidanceReadRequest) -> GuidanceSettingsView:
    """Read actual private rules only after independent settings-management admission.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual settings reader and exact event scope.

    Returns
    -------
    GuidanceSettingsView
        Readable recorded rules or an explicitly unconfigured state.
    """

    def load(scope: AuthorizedGuidanceScope) -> GuidanceSettingsView:
        options = _options(request, scope)
        control = _control(request)
        row = (
            GuidanceSettingsRevision.objects.filter(
                **_ownership(request), id=control.current_settings_id
            ).first()
            if control and control.current_settings_id
            else None
        )
        return GuidanceSettingsView(
            options=options,
            revision_id=row.id if row else None,
            policy_name=row.policy_name if row else "",
            record_owner=row.record_owner if row else "",
            review_on=row.review_on if row else None,
            policy_url=row.policy_url if row else "",
            policy_description=row.policy_description if row else "",
        )

    return _read(
        request,
        capability="knowledge.manage_settings",
        fields=frozenset({"settings"}),
        purpose="settings",
        load=load,
    )


def _today(scope: AuthorizedGuidanceScope) -> date:
    return timezone.now().astimezone(ZoneInfo(scope.edition.time_zone)).date()


def _summary(
    row: GuidanceItem, scope: AuthorizedGuidanceScope
) -> GuidanceCurrentSummary:
    source = row.published_revision
    if source is None or source.review_by is None:
        raise GuidanceNotAvailableError
    return GuidanceCurrentSummary(
        id=row.id,
        revision_id=source.id,
        title=source.title,
        language_code=source.language_code,
        number=source.number,
        effective_at=source.review.occurred_at,
        review_by=source.review_by,
        review_due=source.review_by < _today(scope),
        owner_label=OWNER_LABEL,
    )


def _current_view(
    row: GuidanceItem, scope: AuthorizedGuidanceScope
) -> GuidanceCurrentView:
    source = row.published_revision
    if source is None:
        raise GuidanceNotAvailableError
    return GuidanceCurrentView(
        _summary(row, scope),
        source.body,
        PURPOSE,
        AUDIENCE_LABEL,
        tuple(source.placements),
    )


def _reader_open(request: GuidanceReadRequest) -> bool:
    control = (
        GuidanceControl.objects.filter(**_ownership(request)).only("stopped").first()
    )
    return bool(control and not control.stopped)


def _page_inputs(after: UUID | None, limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise GuidanceLimitError
    if after is not None:
        identifier(after)


def _current_page(
    request: GuidanceReadRequest,
    scope: AuthorizedGuidanceScope,
    *,
    query: str,
    language_code: str | None,
    after: UUID | None,
    limit: int,
    context: str | None = None,
    search_body: bool = False,
) -> GuidanceCurrentPage:
    _page_inputs(after, limit)
    term = text(query, maximum=MAX_QUERY, required=False)
    language = text(language_code, maximum=35) if language_code is not None else None
    if not _reader_open(request):
        return GuidanceCurrentPage((), None, _actions(request))
    rows = current_copy_rows(request).defer("published_revision__body")
    if term:
        match = Q(published_revision__title__icontains=term)
        if search_body:
            match |= Q(published_revision__body__icontains=term)
        rows = rows.filter(match)
    if language:
        rows = rows.filter(published_revision__language_code=language)
    if context:
        rows = rows.filter(published_revision__placements__contains=[context])
    if after:
        rows = rows.filter(id__gt=after)
    values = list(rows.order_by("id")[: limit + 1])
    return GuidanceCurrentPage(
        tuple(_summary(row, scope) for row in values[:limit]),
        values[limit - 1].id if len(values) > limit else None,
        _actions(request),
    )


def list_current_guidance(
    request: GuidanceReadRequest,
    *,
    query: str = "",
    language_code: str | None = None,
    after: UUID | None = None,
    limit: int = 50,
) -> GuidanceCurrentPage:
    """Search only currently available approved copy within the admitted edition.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual current-content reader and exact scope.
    query : str, default=''
        Bounded title search, also matching text when current-copy access is admitted;
        search terms are never copied into audit metadata.
    language_code : str | None, default=None
        Optional exact language filter; no translation or silent fallback occurs.
    after : UUID | None, default=None
        Exclusive stable identifier continuation.
    limit : int, default=50
        Page bound, at most the declared current-query maximum.

    Returns
    -------
    GuidanceCurrentPage
        Current-only metadata without private notes, drafts or actor labels.
    """
    fields = frozenset({"current_summary"})
    authorize_guidance_scope(
        request, capability="knowledge.view_current", fields=fields
    )
    search_body = bool(query) and can_use(
        request,
        "knowledge.view_current",
        fields=frozenset({"current_copy"}),
    )
    if search_body:
        fields |= {"current_copy"}
    return _read(
        request,
        capability="knowledge.view_current",
        fields=fields,
        purpose="current_list",
        load=lambda scope: _current_page(
            request,
            scope,
            query=query,
            language_code=language_code,
            after=after,
            limit=limit,
            search_body=search_body,
        ),
    )


def load_current_guidance(
    request: GuidanceReadRequest, *, item_id: UUID
) -> GuidanceCurrentView:
    """Return current approved text with one unavailable result for all hidden states.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual reader and exact independent scope.
    item_id : UUID
        Scoped current item reference; possession conveys no access.

    Returns
    -------
    GuidanceCurrentView
        Exact currently available internal copy and approved metadata.
    """

    def load(scope: AuthorizedGuidanceScope) -> GuidanceCurrentView:
        selected = identifier(item_id)
        if not _reader_open(request):
            raise GuidanceNotAvailableError
        row = current_copy_rows(request).filter(id=selected).first()
        if row is None:
            raise GuidanceNotAvailableError
        return _current_view(row, scope)

    return _read(
        request,
        capability="knowledge.view_current",
        fields=frozenset({"current_copy"}),
        purpose="current_copy",
        load=load,
    )


def load_context_guidance(
    request: GuidanceReadRequest,
    *,
    context: str,
    language_code: str | None = None,
    after: UUID | None = None,
    limit: int = 3,
) -> GuidanceCurrentPage:
    """Supply independently admitted current titles beside one allowlisted owning task.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual reader; the receiving workflow's permission is not reused.
    context : str
        Closed knowledge.compose or announcements.compose placement.
    language_code : str | None, default=None
        Optional exact language filter.
    after : UUID | None, default=None
        Exclusive continuation for additional matching current guidance.
    limit : int, default=3
        Bounded contextual summary count.

    Returns
    -------
    GuidanceCurrentPage
        Only current metadata, or no entries for an unadopted contextual task.
    """

    def load(scope: AuthorizedGuidanceScope) -> GuidanceCurrentPage:
        if context not in PLACEMENTS:
            raise GuidanceNotAvailableError
        if (
            context == "announcements.compose"
            and scope.edition.adoption_profile_code != "announcements_guidance"
        ):
            return GuidanceCurrentPage((), None, _actions(request))
        return _current_page(
            request,
            scope,
            query="",
            language_code=language_code,
            after=after,
            limit=limit,
            context=context,
        )

    return _read(
        request,
        capability="knowledge.view_current",
        fields=frozenset({"current_summary"}),
        purpose="context",
        load=load,
    )


def _revision_view(row: GuidanceRevision) -> GuidanceRevisionView:
    return GuidanceRevisionView(
        row.id,
        row.number,
        row.title,
        row.body,
        row.language_code,
        row.review_by,
        tuple(row.placements),
        row.occurred_at,
    )


def list_working_guidance(
    request: GuidanceReadRequest,
    *,
    after: UUID | None = None,
    limit: int = 50,
) -> GuidanceWorkingPage:
    """List private work independently of ordinary current-reader search.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual working-copy reader and exact scope.
    after : UUID | None, default=None
        Exclusive stable identifier continuation.
    limit : int, default=50
        Bounded private summary count.

    Returns
    -------
    GuidanceWorkingPage
        Draft/current availability metadata and safe editor options.
    """

    def load(scope: AuthorizedGuidanceScope) -> GuidanceWorkingPage:
        _page_inputs(after, limit)
        options = _options(request, scope)
        rows = GuidanceItem.objects.filter(**_ownership(request)).select_related(
            "current_revision", "published_revision"
        )
        if after:
            rows = rows.filter(id__gt=after)
        values = list(rows.order_by("id")[: limit + 1])
        summaries = []
        for row in values[:limit]:
            if row.current_revision is None:
                raise GuidanceError
            summaries.append(
                GuidanceWorkingSummary(
                    row.id,
                    row.current_revision.title,
                    row.language_code,
                    row.version,
                    row.status,
                    row.published_revision.number
                    if row.published_revision and not options.stopped
                    else None,
                    row.withdrawn,
                    row.updated_at,
                )
            )
        return GuidanceWorkingPage(
            tuple(summaries),
            values[limit - 1].id if len(values) > limit else None,
            options,
        )

    return _read(
        request,
        capability="knowledge.view_working",
        fields=frozenset({"draft", "history"}),
        purpose="working_list",
        load=load,
    )


def load_working_guidance(
    request: GuidanceReadRequest, *, item_id: UUID
) -> GuidanceWorkingDetail:
    """Read exact working copy and bounded private evidence after full field admission.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual private working-history reader and exact scope.
    item_id : UUID
        Exact guide resolved only inside the admitted tenant boundary.

    Returns
    -------
    GuidanceWorkingDetail
        Separate working, retained approval and current availability projections.
    """

    def load(scope: AuthorizedGuidanceScope) -> GuidanceWorkingDetail:
        selected = identifier(item_id)
        row = (
            GuidanceItem.objects.filter(**_ownership(request), id=selected)
            .select_related(
                "current_revision", "approved_revision", "published_revision__review"
            )
            .first()
        )
        if row is None or row.current_revision is None:
            raise GuidanceNotAvailableError
        receipts = _bounded(
            list(
                GuidanceCommandReceipt.objects.filter(
                    **_ownership(request), item=row
                ).order_by("resulting_version")[: MAX_HISTORY + 1]
            ),
            MAX_HISTORY,
        )
        labels = account_display_labels({r.actor_id for r in receipts})
        options = _options(request, scope)
        source = row.current_revision
        latest_review = (
            GuidanceReview.objects.filter(**_ownership(request), revision__item=row)
            .order_by("command_receipt__control_sequence")
            .last()
        )
        base = options.actions
        independent = not GuidanceRevision.objects.filter(
            item=row, round_id=source.round_id, actor_id=request.actor_id
        ).exists()
        language_available = source.language_code in options.language_codes
        actions = GuidanceActions(
            can_view_current=base.can_view_current,
            can_view_working=base.can_view_working,
            can_compose=base.can_compose
            and options.rules_current
            and language_available,
            can_review=base.can_review
            and options.rules_current
            and language_available
            and row.status == "in_review"
            and independent,
            can_withdraw=base.can_withdraw
            and scope.edition.accepts_writes
            and row.status != "withdrawn",
            can_manage_settings=base.can_manage_settings,
            can_export_evidence=base.can_export_evidence,
        )
        return GuidanceWorkingDetail(
            id=row.id,
            version=row.version,
            status=row.status,
            withdrawn=row.withdrawn,
            draft=_revision_view(source),
            last_approved=_revision_view(row.approved_revision)
            if row.approved_revision
            else None,
            current=_current_view(row, scope)
            if row.published_revision and not options.stopped
            else None,
            review_note=latest_review.note if latest_review else "",
            history=tuple(
                GuidanceHistoryEntry(
                    r.operation,
                    labels.get(r.actor_id, "Former Guidance operator"),
                    r.occurred_at,
                    r.reason,
                )
                for r in receipts
            ),
            options=options,
            actions=actions,
        )

    return _read(
        request,
        capability="knowledge.view_working",
        fields=frozenset({"draft", "review_notes", "history"}),
        purpose="working_detail",
        load=load,
    )


def load_guidance_resume_preview(request: GuidanceReadRequest) -> GuidanceResumePreview:
    """Preview the exact retained current set before an explicit manager confirmation.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual manager with independent settings admission.

    Returns
    -------
    GuidanceResumePreview
        Complete bounded current-copy metadata, sequence and deterministic digest.
    """

    def load(scope: AuthorizedGuidanceScope) -> GuidanceResumePreview:
        control = _control(request)
        if control is None:
            raise GuidanceNotAvailableError
        rows, fingerprint = retained_current_snapshot(request, control)
        options = _options(request, scope)
        blockers = tuple(
            code for code in options.blocking_reasons if code != "work_stopped"
        )
        if not control.stopped:
            blockers += ("work_already_running",)
        return GuidanceResumePreview(
            control.sequence,
            fingerprint,
            tuple(_summary(row, scope) for row in rows),
            not blockers,
            blockers,
        )

    return _read(
        request,
        capability="knowledge.manage_settings",
        fields=frozenset({"settings"}),
        purpose="resume_preview",
        load=load,
    )


def _download(item_id: UUID, kind: str, payload: object) -> GuidanceDownload:
    section = canonical_json(payload)
    fingerprint = digest(payload)
    envelope = {
        "format": f"knowledge.{kind}@1",
        "sha256": fingerprint,
        "content": payload,
    }
    if kind == "current-copy":
        envelope["generated_at"] = timezone.now()
    artifact = canonical_json(envelope)
    if len(section) > MAX_EXPORT_BYTES or len(artifact) > MAX_EXPORT_BYTES:
        raise GuidanceLimitError
    return GuidanceDownload(
        f"guidance-{item_id}-{kind}.json",
        "application/json; charset=utf-8",
        artifact,
        fingerprint,
    )


def download_current_guidance(
    request: GuidanceReadRequest, *, item_id: UUID
) -> GuidanceDownload:
    """Download only currently available internal copy under reader field admission.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual current-content reader and exact scope.
    item_id : UUID
        Scoped guide whose current copy is requested.

    Returns
    -------
    GuidanceDownload
        Complete approved text and metadata without private evidence.
    """
    view = load_current_guidance(request, item_id=item_id)
    return _download(
        item_id,
        "current-copy",
        {
            "organization_id": request.organization_id,
            "edition_id": request.edition_id,
            "item_id": item_id,
            "revision_id": view.summary.revision_id,
            "number": view.summary.number,
            "title": view.summary.title,
            "body": view.body,
            "language_code": view.summary.language_code,
            "review_by": view.summary.review_by,
            "effective_at": view.summary.effective_at,
            "owner": view.summary.owner_label,
            "purpose": view.purpose,
            "audience": view.audience_label,
            "placements": view.placements,
            "saved_copy_notice": "Saved copies may be out of date.",
        },
    )


def export_guidance_evidence(
    request: GuidanceReadRequest, *, item_id: UUID
) -> GuidanceDownload:
    """Export complete bounded owner history under separate evidence permission.

    Parameters
    ----------
    request : GuidanceReadRequest
        Actual independently admitted private-evidence exporter.
    item_id : UUID
        Exact item resolved inside the admitted event and tenant.

    Returns
    -------
    GuidanceDownload
        Complete guide history and edition rules/control evidence with explicit
        scope metadata; other guides and their commands are excluded.
    """

    def load(_scope: AuthorizedGuidanceScope) -> GuidanceDownload:
        selected = identifier(item_id)
        item = GuidanceItem.objects.filter(**_ownership(request), id=selected).first()
        if item is None:
            raise GuidanceNotAvailableError
        require_complete_export_bound(**_ownership(request), item_id=selected)
        control = GuidanceControl.objects.filter(**_ownership(request)).first()
        if control is None:
            raise GuidanceNotAvailableError
        revisions = _bounded(
            list(
                GuidanceRevision.objects.filter(**_ownership(request), item=item)
                .order_by("number")
                .values()[: MAX_REVISIONS + 1]
            ),
            MAX_REVISIONS,
        )
        ids = [row["id"] for row in revisions]
        rules = _bounded(
            list(
                GuidanceSettingsRevision.objects.filter(**_ownership(request))
                .order_by("number")
                .values()[: MAX_CONTROL_HISTORY + 1]
            ),
            MAX_CONTROL_HISTORY,
        )
        receipts = _bounded(
            list(
                GuidanceCommandReceipt.objects.filter(**_ownership(request))
                .filter(Q(item=item) | Q(item__isnull=True))
                .order_by("control_sequence")
                .values()[: MAX_HISTORY + MAX_CONTROL_HISTORY + 1]
            ),
            MAX_HISTORY + MAX_CONTROL_HISTORY,
        )
        reviews = _bounded(
            list(
                GuidanceReview.objects.filter(
                    **_ownership(request), revision_id__in=ids
                )
                .order_by("command_receipt__control_sequence")
                .values()[: MAX_REVISIONS + 1]
            ),
            MAX_REVISIONS,
        )
        return _download(
            selected,
            "evidence",
            {
                "organization_id": request.organization_id,
                "edition_id": request.edition_id,
                "export_scope": {
                    "kind": "one-guide-and-edition-controls",
                    "guide_history": (
                        "All revisions, reviews and commands for this guide."
                    ),
                    "edition_controls": (
                        "All record-keeping settings, stop and resume evidence."
                    ),
                    "excluded": "Other guides and their item-command receipts.",
                    "sequence_notice": (
                        "Edition command sequence gaps may belong to other guides; "
                        "this is not a complete edition command journal."
                    ),
                },
                "edition_control": {
                    "id": control.id,
                    "sequence": control.sequence,
                    "settings_version": control.settings_version,
                    "current_settings_id": control.current_settings_id,
                    "stopped": control.stopped,
                },
                "item": {
                    "id": item.id,
                    "version": item.version,
                    "status": item.status,
                    "withdrawn": item.withdrawn,
                    "current_revision_id": item.current_revision_id,
                    "published_revision_id": item.published_revision_id,
                    "approved_revision_id": item.approved_revision_id,
                },
                "revisions": revisions,
                "reviews": reviews,
                "settings": rules,
                "receipts": receipts,
                "custody_notice": (
                    "Private evidence remains governed by the recorded "
                    "organizational rules."
                ),
            },
        )

    return _read(
        request,
        capability="knowledge.export_evidence",
        fields=frozenset({"evidence"}),
        purpose="evidence_export",
        load=load,
    )
