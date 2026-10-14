"""Exact independent review, current availability and accountable Guidance controls."""

from dataclasses import asdict
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError

from maru.authorization.guidance_authority_queries import (
    GuidanceTeamReference,
    guidance_team_reference,
)

from .authorization import authorize_guidance_scope
from .catalog import DIGEST_HEX_LENGTH, MAX_HISTORY, MAX_ITEMS, MAX_NOTE, MAX_REVISIONS
from .command_support import CommandContext, execute
from .contracts import (
    GuidanceCommandRequest,
    GuidanceCommandResult,
    GuidanceDraftInput,
    GuidanceSettingsInput,
)
from .errors import (
    GuidanceLimitError,
    GuidanceSettingsRequiredError,
    GuidanceStateConflictError,
    GuidanceVersionConflictError,
)
from .inputs import (
    canonical_json,
    draft_payload,
    identifier,
    normalize_draft,
    normalize_settings,
    text,
    version,
)
from .models import (
    GuidanceItem,
    GuidanceReview,
    GuidanceRevision,
    GuidanceSettingsRevision,
)
from .resume import retained_current_snapshot


def _admit(request: GuidanceCommandRequest, action: str) -> None:
    authorize_guidance_scope(request, capability=f"knowledge.{action}")


def _writes_open(context: CommandContext, *, stopped_ok: bool = False) -> None:
    if not context.scope.edition.accepts_writes:
        raise GuidanceStateConflictError
    if context.control.stopped and not stopped_ok:
        raise GuidanceStateConflictError


def _settings(context: CommandContext) -> GuidanceSettingsRevision:
    _writes_open(context)
    settings_id = context.control.current_settings_id
    if settings_id is None:
        raise GuidanceSettingsRequiredError
    rules = (
        GuidanceSettingsRevision.objects.filter(
            organization_id=context.request.organization_id,
            edition_id=context.request.edition_id,
            id=settings_id,
        )
        .only("id", "review_on")
        .first()
    )
    today = context.occurred_at.astimezone(
        ZoneInfo(context.scope.edition.time_zone)
    ).date()
    if rules is None or rules.review_on < today:
        raise GuidanceSettingsRequiredError
    return rules


def _item(context: CommandContext, item_id: UUID, expected: int) -> GuidanceItem:
    row = (
        GuidanceItem.objects.select_for_update()
        .filter(
            organization_id=context.request.organization_id,
            edition_id=context.request.edition_id,
            id=item_id,
        )
        .first()
    )
    if row is None:
        raise GuidanceStateConflictError
    if row.version != expected:
        raise GuidanceVersionConflictError
    return row


def _revision(item: GuidanceItem) -> GuidanceRevision:
    row = item.current_revision
    if row is None:
        raise GuidanceStateConflictError
    return row


def _advance(item: GuidanceItem) -> None:
    if item.version >= MAX_HISTORY:
        raise GuidanceLimitError
    item.version += 1
    item.save()


def _require_team(context: CommandContext) -> GuidanceTeamReference:
    team = guidance_team_reference(
        organization_id=context.request.organization_id,
        edition_id=context.request.edition_id,
    )
    if team is None or not team.ready:
        raise GuidanceSettingsRequiredError
    return team


def _require_current_language(
    context: CommandContext, revision: GuidanceRevision
) -> None:
    if revision.language_code not in context.scope.edition.language_codes:
        raise ValidationError(
            "Restore this guide's event language before asking for "
            "or recording review.",
            code="unavailable_language",
        )


def _write_revision(
    context: CommandContext,
    item: GuidanceItem,
    draft: GuidanceDraftInput,
    rules: GuidanceSettingsRevision,
) -> GuidanceRevision:
    team = _require_team(context)
    if draft.language_code != item.language_code:
        raise ValidationError(
            "Create a separate guide for another language.", code="language_changed"
        )
    if draft.language_code not in context.scope.edition.language_codes:
        raise ValidationError(
            "This guide's language is no longer configured for the event.",
            code="unavailable_language",
        )
    if (
        "announcements.compose" in draft.placements
        and context.scope.edition.adoption_profile_code != "announcements_guidance"
    ):
        raise ValidationError(
            "This event has not adopted Announcements with Guidance.",
            code="unavailable_placement",
        )
    previous = item.current_revision
    number = previous.number + 1 if previous else 1
    if number > MAX_REVISIONS:
        raise GuidanceLimitError
    if previous is None or item.current_revision_id == item.approved_revision_id:
        base = item.approved_revision
        round_id = uuid4()
    else:
        base = previous.base_approved_revision
        round_id = previous.round_id
    row = GuidanceRevision.objects.create(
        **context.evidence(),
        item=item,
        number=number,
        previous_revision=previous,
        base_approved_revision=base,
        round_id=round_id,
        settings_revision=rules,
        team_id=team.team_id,
        team_activation_receipt_id=team.activation_receipt_id,
        team_label=team.team_label,
        title=draft.title,
        body=draft.body,
        language_code=draft.language_code,
        review_by=draft.review_by,
        placements=list(draft.placements),
        text_bytes=len(canonical_json(draft_payload(draft))),
    )
    item.current_revision = row
    item.status = "draft"
    return row


def update_guidance_settings(
    request: GuidanceCommandRequest,
    *,
    settings: GuidanceSettingsInput,
    expected_version: int,
) -> GuidanceCommandResult:
    """Record actual organizational rules without inventing or executing disposal.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual actor, exact scope and retained retry identity.
    settings : GuidanceSettingsInput
        Explicit readable organizational rules and actual confirmation.
    expected_version : int
        Settings cursor observed by the organizer, zero for first setup.

    Returns
    -------
    GuidanceCommandResult
        Exact accepted rules revision and resulting settings cursor.
    """
    _admit(request, "manage_settings")
    value, expected = (
        normalize_settings(settings),
        version(expected_version, initial=True),
    )

    def write(context: CommandContext) -> tuple[UUID, None, int]:
        _writes_open(context, stopped_ok=True)
        _require_team(context)
        if context.control.settings_version != expected:
            raise GuidanceVersionConflictError
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
        row = GuidanceSettingsRevision.objects.create(
            **context.evidence(),
            number=expected + 1,
            policy_name=value.policy_name,
            policy_description=value.policy_description,
            policy_url=value.policy_url,
            record_owner=value.record_owner,
            review_on=value.review_on,
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


def create_guidance(
    request: GuidanceCommandRequest,
    *,
    draft: GuidanceDraftInput,
    expected_settings_version: int,
) -> GuidanceCommandResult:
    """Create one internal guide under exact current rules and accepted team ownership.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual actor, exact scope and retained retry identity.
    draft : GuidanceDraftInput
        Complete proposed plain text and reviewed metadata.
    expected_settings_version : int
        Rules cursor displayed to the author before entering content.

    Returns
    -------
    GuidanceCommandResult
        Stable new item identity and its first command version.
    """
    _admit(request, "compose")
    value, expected = normalize_draft(draft), version(expected_settings_version)

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        rules = _settings(context)
        if context.control.settings_version != expected:
            raise GuidanceVersionConflictError
        if (
            GuidanceItem.objects.filter(edition_id=request.edition_id).count()
            >= MAX_ITEMS
        ):
            raise GuidanceLimitError
        item = GuidanceItem.objects.create(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            language_code=value.language_code,
        )
        _write_revision(context, item, value, rules)
        item.save()
        return item.id, item.id, item.version

    return execute(
        request,
        operation="create",
        intent={"draft": draft_payload(value), "expected_settings_version": expected},
        write=write,
    )


def revise_guidance(
    request: GuidanceCommandRequest,
    *,
    item_id: UUID,
    draft: GuidanceDraftInput,
    expected_version: int,
    expected_settings_version: int,
    reason: str,
) -> GuidanceCommandResult:
    """Append a working version while retaining any current approved reader copy.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual actor, exact scope and retained retry identity.
    item_id : UUID
        Exact item resolved only inside the admitted scope.
    draft : GuidanceDraftInput
        Complete replacement text and metadata in the same item language.
    expected_version : int
        Item cursor observed before editing.
    expected_settings_version : int
        Rules cursor observed before editing, retained in the retry digest.
    reason : str
        Bounded explanation retained for this new version.

    Returns
    -------
    GuidanceCommandResult
        Exact new revision and advanced item version.
    """
    _admit(request, "compose")
    selected, expected = identifier(item_id), version(expected_version)
    expected_settings, value = (
        version(expected_settings_version),
        normalize_draft(draft),
    )
    note = text(reason, maximum=MAX_NOTE)

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        rules = _settings(context)
        if context.control.settings_version != expected_settings:
            raise GuidanceVersionConflictError
        item = _item(context, selected, expected)
        row = _write_revision(context, item, value, rules)
        _advance(item)
        return row.id, item.id, item.version

    return execute(
        request,
        operation="revise",
        intent={
            "item_id": selected,
            "draft": draft_payload(value),
            "expected_version": expected,
            "expected_settings_version": expected_settings,
        },
        write=write,
        reason=note,
    )


def request_guidance_review(
    request: GuidanceCommandRequest,
    *,
    item_id: UUID,
    expected_version: int,
) -> GuidanceCommandResult:
    """Submit one exact draft with an explicit review date for independent approval.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual actor, exact scope and retained retry identity.
    item_id : UUID
        Exact scoped guide whose current revision will be submitted.
    expected_version : int
        Observed item cursor; withdrawal or another edit invalidates it.

    Returns
    -------
    GuidanceCommandResult
        Submitted revision identity and advanced item version.
    """
    _admit(request, "compose")
    selected, expected = identifier(item_id), version(expected_version)

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        _settings(context)
        _require_team(context)
        item = _item(context, selected, expected)
        row = _revision(item)
        _require_current_language(context, row)
        if (
            item.status != "draft"
            or GuidanceReview.objects.filter(revision=row).exists()
        ):
            raise GuidanceStateConflictError
        if row.review_by is None:
            raise ValidationError(
                "Save a review date before asking for review.",
                code="review_date_required",
            )
        item.status = "in_review"
        _advance(item)
        return row.id, item.id, item.version

    return execute(
        request,
        operation="request_review",
        intent={"item_id": selected, "expected_version": expected},
        write=write,
    )


def review_guidance(
    request: GuidanceCommandRequest,
    *,
    item_id: UUID,
    revision_id: UUID,
    expected_version: int,
    decision: str,
    note: str = "",
) -> GuidanceCommandResult:
    """Independently decide exact text and metadata; approval makes it current now.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual reviewer, exact scope and retained retry identity.
    item_id : UUID
        Exact scoped item whose pending review is being decided.
    revision_id : UUID
        Immutable text and metadata version shown to the reviewer.
    expected_version : int
        Observed item cursor, including any intervening withdrawal.
    decision : str
        Closed approve or changes_requested decision.
    note : str, default=''
        Private feedback, mandatory when asking for changes.

    Returns
    -------
    GuidanceCommandResult
        Retained independent decision and advanced item cursor.

    Raises
    ------
    ValidationError
        If the decision or required feedback is malformed.
    """
    _admit(request, "review")
    selected, revision, expected = (
        identifier(item_id),
        identifier(revision_id),
        version(expected_version),
    )
    if decision not in ("approve", "changes_requested"):
        raise ValidationError(
            "Choose approve or ask for changes.", code="invalid_decision"
        )
    feedback = text(note, maximum=MAX_NOTE, required=decision == "changes_requested")

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        _settings(context)
        _require_team(context)
        item = _item(context, selected, expected)
        source = _revision(item)
        _require_current_language(context, source)
        if (
            item.status != "in_review"
            or source.id != revision
            or source.review_by is None
        ):
            raise GuidanceStateConflictError
        if GuidanceRevision.objects.filter(
            item=item, round_id=source.round_id, actor_id=request.actor_id
        ).exists():
            raise GuidanceStateConflictError
        row = GuidanceReview.objects.create(
            **context.evidence(), revision=source, decision=decision, note=feedback
        )
        item.status = "approved" if decision == "approve" else "changes_requested"
        if decision == "approve":
            item.approved_revision = source
            item.published_revision = source
            item.withdrawn = False
        _advance(item)
        return row.id, item.id, item.version

    return execute(
        request,
        operation=decision,
        intent={
            "item_id": selected,
            "revision_id": revision,
            "expected_version": expected,
            "decision": decision,
            "note": feedback,
        },
        write=write,
    )


def withdraw_guidance(
    request: GuidanceCommandRequest,
    *,
    item_id: UUID,
    expected_version: int,
    reason: str,
) -> GuidanceCommandResult:
    """Remove reader availability and invalidate pending review without erasing history.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual authorized actor, scope and retained retry identity.
    item_id : UUID
        Exact scoped guide to withdraw from current reader surfaces.
    expected_version : int
        Item cursor shown when explaining the withdrawal consequence.
    reason : str
        Bounded accountable explanation retained in command evidence.

    Returns
    -------
    GuidanceCommandResult
        Retained withdrawal outcome and advanced item cursor.
    """
    _admit(request, "withdraw")
    selected, expected, note = (
        identifier(item_id),
        version(expected_version),
        text(reason, maximum=MAX_NOTE),
    )

    def write(context: CommandContext) -> tuple[UUID, UUID, int]:
        _writes_open(context, stopped_ok=True)
        item = _item(context, selected, expected)
        if item.status == "withdrawn":
            raise GuidanceStateConflictError
        item.withdrawn = True
        item.published_revision = None
        item.status = "withdrawn"
        _advance(item)
        return item.id, item.id, item.version

    return execute(
        request,
        operation="withdraw",
        intent={"item_id": selected, "expected_version": expected},
        write=write,
        reason=note,
    )


def stop_guidance(
    request: GuidanceCommandRequest,
    *,
    expected_control_version: int,
    reason: str,
) -> GuidanceCommandResult:
    """Hide reader content and pause writing while retaining history and withdrawal.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual settings manager, scope and retained retry identity.
    expected_control_version : int
        Edition sequence observed before the explicit stop decision.
    reason : str
        Bounded reason for stopping this purpose without stopping other workflows.

    Returns
    -------
    GuidanceCommandResult
        Retained stop evidence and resulting settings cursor.
    """
    _admit(request, "manage_settings")
    expected, note = version(expected_control_version), text(reason, maximum=MAX_NOTE)

    def write(context: CommandContext) -> tuple[UUID, None, int]:
        _writes_open(context, stopped_ok=True)
        if context.control.sequence != expected:
            raise GuidanceVersionConflictError
        if context.control.stopped:
            raise GuidanceStateConflictError
        context.control.stopped = True
        context.control.settings_version += 1
        return context.control.id, None, context.control.settings_version

    return execute(
        request,
        operation="stop",
        intent={"expected_control_version": expected},
        write=write,
        reason=note,
    )


def resume_guidance(
    request: GuidanceCommandRequest,
    *,
    expected_control_version: int,
    preview_digest: str,
    confirmed: bool,
    reason: str,
) -> GuidanceCommandResult:
    """Restore the confirmed current copies while keeping withdrawn guides hidden.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual settings manager, scope and retained retry identity.
    expected_control_version : int
        Exact complete command sequence retained by the preview.
    preview_digest : str
        Owner-generated digest of the retained current-copy inventory.
    confirmed : bool
        Explicit confirmation that those exact versions may become available again.
    reason : str
        Bounded accountable explanation for resuming Guidance.

    Returns
    -------
    GuidanceCommandResult
        Retained resume evidence and resulting settings cursor.

    Raises
    ------
    ValidationError
        If explicit confirmation is absent or the supplied digest is malformed.
    """
    _admit(request, "manage_settings")
    expected, note = version(expected_control_version), text(reason, maximum=MAX_NOTE)
    fingerprint = text(preview_digest, maximum=DIGEST_HEX_LENGTH)
    if (
        confirmed is not True
        or len(fingerprint) != DIGEST_HEX_LENGTH
        or any(c not in "0123456789abcdef" for c in fingerprint)
    ):
        raise ValidationError(
            "Confirm the exact guidance that will return.", code="resume_unconfirmed"
        )

    def write(context: CommandContext) -> tuple[UUID, None, int]:
        _writes_open(context, stopped_ok=True)
        if context.control.sequence != expected:
            raise GuidanceVersionConflictError
        if not context.control.stopped:
            raise GuidanceStateConflictError
        _rows, current_digest = retained_current_snapshot(
            context.request, context.control
        )
        if current_digest != fingerprint:
            raise GuidanceVersionConflictError
        context.control.stopped = False
        _settings(context)
        _require_team(context)
        context.control.settings_version += 1
        return context.control.id, None, context.control.settings_version

    return execute(
        request,
        operation="resume",
        intent={
            "expected_control_version": expected,
            "preview_digest": fingerprint,
            "confirmed": True,
        },
        write=write,
        reason=note,
    )
