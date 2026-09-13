"""Actual-actor, freshly recomposed change notices without sending authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.programme.authorization import ProgrammeAuthorizationDenied
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftUnavailableError,
)

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_CHANGE_NOTICES,
    VIEW_CHANGE_SELF,
    SchedulingAuthorizationDeniedError,
)
from .change_catalogs import ChangeNoticeReview
from .change_inputs import ChangeRecipientSelection, _identifier
from .change_notice_records import _record, _selection
from .change_notice_sources import (
    ProgrammeChangeNoticePreview,
    _self_sources,
    _sender_sources,
)
from .command_support import SchedulingUnavailableError, SchedulingVersionConflictError
from .planning_queries import SchedulingReadRequest, _read

if TYPE_CHECKING:
    from .change_lifecycle import ChangeNoticeState


def _fresh_preview(
    request: SchedulingReadRequest,
    *,
    release_id: UUID,
    occurrence_id: UUID,
    recipient: ChangeRecipientSelection,
    personal: bool = False,
) -> ProgrammeChangeNoticePreview:
    # The composing read/command must authorize its own field first. Complete
    # owner-person locks inside the source query precede _read's actor-only lock.
    _identifier(release_id)
    _identifier(occurrence_id)
    if type(recipient) is not ChangeRecipientSelection:
        raise ValidationError("Select one exact Programme change recipient.")
    recipient.validated()
    collect = _self_sources if personal else _sender_sources
    try:
        first = collect(
            request,
            release_id=release_id,
            occurrence_id=occurrence_id,
            recipient=recipient,
        )
        current = collect(
            request,
            release_id=release_id,
            occurrence_id=occurrence_id,
            recipient=recipient,
        )
    except (ProgrammeAuthorizationDenied, ProgrammeStaffingDeniedError) as error:
        raise SchedulingAuthorizationDeniedError from error
    except (
        ProgrammeQueryUnavailableError,
        ProgrammeStaffingUnavailableError,
        ShiftAuthorizationDeniedError,
        ShiftUnavailableError,
    ) as error:
        raise SchedulingUnavailableError from error
    if first != current:
        raise SchedulingUnavailableError
    return current


def preview_programme_change_notice(
    request: SchedulingReadRequest,
    *,
    release_id: UUID,
    occurrence_id: UUID,
    recipient: ChangeRecipientSelection,
) -> ProgrammeChangeNoticePreview:
    """Preview one exact affected purpose under independent real-sender authority.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actual actor, exact tenant/edition and audit correlation.
    release_id : UUID
        Current publication or latest explicit withdrawal, not arbitrary history.
    occurrence_id : UUID
        Selected occurrence whose affected membership must independently exist.
    recipient : ChangeRecipientSelection
        Exact owner relationship or deliberately selected operator person/purpose.

    Returns
    -------
    ProgrammeChangeNoticePreview
        One minimized fresh comparison or explicit suppression without old content.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If trusted routing or independent sender notice/owner authority is denied.

    Notes
    -----
    Shared validation, unavailable-dependency and stale-publication errors
    propagate. Notice-field admission precedes private selector inspection.
    Owner sources are collected twice under canonical scope and person locks;
    moving sources fail closed. Final notice authority and mandatory actual-actor
    audit precede disclosure. No personal query is invoked as the recipient.
    The digest grants no lasting permission, delivery or acknowledgement: each
    subsequent action must recompose its own exact current source and purpose.
    No authorizer override, directory, contact address or free-text body is exposed.
    """
    if type(request) is not SchedulingReadRequest or any(
        type(value) is not UUID or value.int == 0
        for value in (
            request.actor_id,
            request.organization_id,
            request.edition_id,
            request.correlation_id,
        )
    ):
        raise SchedulingAuthorizationDeniedError
    return _read(
        request,
        capability=VIEW_CHANGE_NOTICES,
        fields=frozenset({"change_notices"}),
        purpose="programme_change_notice_preview",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=lambda _scope: _fresh_preview(
            request,
            release_id=release_id,
            occurrence_id=occurrence_id,
            recipient=recipient,
        ),
    )


@dataclass(frozen=True, slots=True)
class ProgrammeChangeNotice:
    """Restricted sender detail for one still-current immutable package.

    Attributes
    ----------
    notice_id
        Exact retained package selected within the admitted edition.
    preview
        Reconstituted current owner-authorized change, never cached private content.
    state
        Current independent facts and restricted actor references.
    reason
        Retained preparation rationale, never disclosed to a personal reader.
    """

    notice_id: UUID
    preview: ProgrammeChangeNoticePreview
    state: ChangeNoticeState
    reason: str


@dataclass(frozen=True, slots=True)
class PersonalProgrammeChangeNotice:
    """Own approved exact change without organizer rationale or other actors.

    Attributes
    ----------
    notice_id
        Exact notice owned by the authenticated recipient's current purpose.
    preview
        Fresh genuine-self comparison, matched to the prepared package fingerprint.
    version
        Observed evidence sequence for an optimistic acknowledgement.
    handed_off
        Whether a manual handoff was recorded, not delivery-provider evidence.
    acknowledged
        Whether this exact recipient already acknowledged this exact package.
    """

    notice_id: UUID
    preview: ProgrammeChangeNoticePreview
    version: int
    handed_off: bool
    acknowledged: bool


def _detail(
    request: SchedulingReadRequest, notice_id: UUID, *, personal: bool
) -> ProgrammeChangeNotice:
    _identifier(notice_id)
    record = _record(request, notice_id, personal=personal)
    notice = record.notice
    if personal and record.state.review is not ChangeNoticeReview.APPROVED:
        raise SchedulingUnavailableError
    preview = _fresh_preview(
        request,
        release_id=notice.release_id,
        occurrence_id=notice.occurrence_id,
        recipient=_selection(notice),
        personal=personal,
    )
    if (
        preview.recipient_id != notice.recipient_id
        or preview.snapshot_digest != notice.snapshot_digest
        or preview.pointer_version != notice.pointer_version
        or preview.source_state.value != notice.source_state
    ):
        raise SchedulingVersionConflictError
    if _record(request, notice_id, personal=personal).state != record.state:
        raise SchedulingUnavailableError
    return ProgrammeChangeNotice(
        notice.id, preview, record.state, "" if personal else notice.reason
    )


def load_programme_change_notice(
    request: SchedulingReadRequest, *, notice_id: UUID
) -> ProgrammeChangeNotice:
    """Read one current notice under independent restricted sender field authority.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actual actor and exact tenant/edition attribution.
    notice_id : UUID
        Exact retained package, not permission to discover foreign records.

    Returns
    -------
    ProgrammeChangeNotice
        Independently reauthorized current source and restricted preparation facts.

    Notes
    -----
    Normal validation, denial, stale-source and unavailable errors propagate.
    Historical existence cannot restore revoked purpose or stale content.
    Independent owner proof, final policy and mandatory audit precede disclosure.
    """
    return _read(
        request,
        capability=VIEW_CHANGE_NOTICES,
        fields=frozenset({"change_notices"}),
        purpose="programme_change_notice",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=lambda _scope: _detail(request, notice_id, personal=False),
    )


def load_personal_programme_change_notice(
    request: SchedulingReadRequest, *, notice_id: UUID
) -> PersonalProgrammeChangeNotice:
    """Read only one's own approved notice after genuine current owner admission.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted authenticated person, tenant, edition and correlation.
    notice_id : UUID
        Exact own package; no recipient account selector exists.

    Returns
    -------
    PersonalProgrammeChangeNotice
        Minimized current change and explicit acknowledgement/handoff state.

    Notes
    -----
    Missing, foreign and unapproved packages share an unavailable result.
    Normal validation, denial and stale-source errors propagate. Real self
    Scheduling and owner permissions are independent of sender/history grants.
    No organizer reason, reviewer identity or personal explanation is disclosed.
    Mandatory actual-person audit precedes release of the minimized result.
    """

    def load(_scope: object) -> PersonalProgrammeChangeNotice:
        detail = _detail(request, notice_id, personal=True)
        return PersonalProgrammeChangeNotice(
            detail.notice_id,
            detail.preview,
            detail.state.version,
            handed_off=detail.state.handed_off_by_id is not None,
            acknowledged=detail.state.acknowledged_by_id is not None,
        )

    return _read(
        request,
        capability=VIEW_CHANGE_SELF,
        fields=frozenset({"own_change_notices"}),
        purpose="personal_programme_change_notice",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=load,
    )
