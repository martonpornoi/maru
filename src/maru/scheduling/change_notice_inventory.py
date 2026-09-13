"""Bounded current-purpose notice discovery, never a recipient directory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import connection

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_CHANGE_NOTICES,
    VIEW_CHANGE_SELF,
    SchedulingAuthorizationDeniedError,
)
from .change_catalogs import MAX_CHANGE_NOTICE_INVENTORY
from .change_inputs import _identifier
from .change_notice_queries import (
    PersonalProgrammeChangeNotice,
    ProgrammeChangeNotice,
    load_personal_programme_change_notice,
    load_programme_change_notice,
)
from .command_support import (
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from .models import SchedulingChangeNotice
from .planning_queries import SchedulingReadRequest, _read

if TYPE_CHECKING:
    from uuid import UUID

type NoticeDetail = ProgrammeChangeNotice | PersonalProgrammeChangeNotice


def _identifiers(
    request: SchedulingReadRequest, *, personal: bool, release_id: UUID | None
) -> tuple[UUID, ...]:
    def load(_scope: object) -> tuple[UUID, ...]:
        if release_id is not None:
            _identifier(release_id)
        rows = SchedulingChangeNotice.objects.filter(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        if personal:
            rows = rows.filter(
                recipient_id=request.actor_id, evidence__action="approve"
            )
        if release_id is not None:
            rows = rows.filter(release_id=release_id)
        identifiers = tuple(
            rows.order_by("id").values_list("id", flat=True)[
                : MAX_CHANGE_NOTICE_INVENTORY + 1
            ]
        )
        if len(identifiers) > MAX_CHANGE_NOTICE_INVENTORY:
            raise SchedulingLimitError
        return identifiers

    return _read(
        request,
        capability=VIEW_CHANGE_SELF if personal else VIEW_CHANGE_NOTICES,
        fields=frozenset({"own_change_notices" if personal else "change_notices"}),
        purpose="programme_change_notice_inventory",
        authorizer=DEFAULT_SCHEDULING_AUTHORIZER,
        loader=load,
    )


def load_programme_change_notice_inventory(
    request: SchedulingReadRequest,
    *,
    personal: bool = False,
    release_id: UUID | None = None,
) -> tuple[NoticeDetail, ...]:
    """Discover bounded currently readable packages, not delivery completeness.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actual person, tenant, edition and audit attribution.
    personal : bool, default=False
        Use genuine-self policy and database recipient filtering, not a grant.
    release_id : UUID | None, default=None
        Optional exact release filter for a bounded inventory.

    Returns
    -------
    tuple[NoticeDetail, ...]
        Independently recomposed packages. Stale or denied packages are omitted
        without their identifiers, content or counts. This is not historical proof
        that no other notice exists or every affected recipient was notified.

    Raises
    ------
    SchedulingUnavailableError
        If the candidate inventory moves while its current details are checked.

    Notes
    -----
    Scope admission, validation, overflow and dependency errors propagate. Each
    detail uses its own complete owner transaction; do not wrap this composition
    in an outer transaction that accumulates differently ordered person locks.
    Final inventory admission and mandatory audit run again before disclosure.
    No organizer rationale is fetched by the personal projection.
    """
    if connection.in_atomic_block:
        raise SchedulingUnavailableError
    identifiers = _identifiers(request, personal=personal, release_id=release_id)
    results: list[NoticeDetail] = []
    for notice_id in identifiers:
        try:
            detail: NoticeDetail = (
                load_personal_programme_change_notice(request, notice_id=notice_id)
                if personal
                else load_programme_change_notice(request, notice_id=notice_id)
            )
        except (SchedulingAuthorizationDeniedError, SchedulingVersionConflictError):
            continue
        results.append(detail)
    if identifiers != _identifiers(request, personal=personal, release_id=release_id):
        raise SchedulingUnavailableError
    return tuple(results)
