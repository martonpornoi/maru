"""Actual-actor, freshly recomposed change notices without sending authority."""

from __future__ import annotations

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
    SchedulingAuthorizationDeniedError,
)
from .change_inputs import ChangeRecipientSelection, _identifier
from .change_notice_sources import ProgrammeChangeNoticePreview, _sender_sources
from .command_support import SchedulingUnavailableError
from .planning_queries import SchedulingReadRequest, _read


def _fresh_sender_preview(
    request: SchedulingReadRequest,
    *,
    release_id: UUID,
    occurrence_id: UUID,
    recipient: ChangeRecipientSelection,
) -> ProgrammeChangeNoticePreview:
    # The composing read/command must authorize its own field first. Complete
    # owner-person locks inside the source query precede _read's actor-only lock.
    _identifier(release_id)
    _identifier(occurrence_id)
    if type(recipient) is not ChangeRecipientSelection:
        raise ValidationError("Select one exact Programme change recipient.")
    recipient.validated()
    try:
        first = _sender_sources(
            request,
            release_id=release_id,
            occurrence_id=occurrence_id,
            recipient=recipient,
        )
        current = _sender_sources(
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
        loader=lambda _scope: _fresh_sender_preview(
            request,
            release_id=release_id,
            occurrence_id=occurrence_id,
            recipient=recipient,
        ),
    )
