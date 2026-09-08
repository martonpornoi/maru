"""Govern explicit overnight-capable service days and retained corrections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import F

from maru.events.queries import (
    EditionTimeEnvelopeReference,
    resolve_edition_time_envelope_reference,
)

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, MANAGE_DAYS
from .catalogs import (
    MAX_RETAINED_SERVICE_DAYS,
    MAX_REVISIONS,
    MAX_SERVICE_DAYS,
    SchedulingOperation,
)
from .command_support import (
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    _CommandTransaction,
    _execute,
    _require_current_version,
)
from .inputs import (
    SchedulingCommandRequest,
    SchedulingServiceDayInput,
    require_identifier,
    require_version,
)
from .models import SchedulingServiceDay, SchedulingServiceDayRevision
from .time_rules import SchedulingWindow, scheduling_windows_overlap

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult


def _payload(
    day: SchedulingServiceDayInput, expected_version: int, day_id: UUID | None
) -> dict[str, object]:
    return {
        "day_id": str(day_id) if day_id else None,
        "expected_version": expected_version,
        "label": day.label,
        "starts_at": day.window.starts_at.isoformat(),
        "ends_at": day.window.ends_at.isoformat(),
        "precision_minutes": day.precision_minutes,
    }


def _prepare_day(request: SchedulingCommandRequest) -> EditionTimeEnvelopeReference:
    envelope = resolve_edition_time_envelope_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if envelope is None:
        raise SchedulingUnavailableError
    return envelope


def _validate_current_day(
    context: _CommandTransaction,
    intent: SchedulingServiceDayInput,
    envelope: EditionTimeEnvelopeReference,
    *,
    excluding: UUID | None = None,
) -> None:
    if (
        intent.window.starts_at < envelope.starts_at
        or intent.window.ends_at > envelope.ends_at
    ):
        raise SchedulingUnavailableError(
            "Service days must stay within current edition dates."
        )
    current = tuple(
        SchedulingServiceDayRevision.objects.filter(
            **context.ownership(),
            sequence=F("day__aggregate_version"),
            lifecycle="active",
        )
        .exclude(day_id=excluding)
        .order_by("day_id")[: MAX_SERVICE_DAYS + 1]
    )
    if len(current) >= MAX_SERVICE_DAYS:
        raise SchedulingLimitError
    if any(
        scheduling_windows_overlap(
            intent.window, SchedulingWindow(row.starts_at, row.ends_at)
        )
        for row in current
    ):
        raise SchedulingUnavailableError("Explicit service-day windows cannot overlap.")


def _day_revision(
    context: _CommandTransaction,
    day: SchedulingServiceDay,
    intent: SchedulingServiceDayInput,
    *,
    edition_version: int,
) -> None:
    SchedulingServiceDayRevision.objects.create(
        **context.evidence(),
        day=day,
        sequence=day.aggregate_version,
        label=intent.label,
        starts_at=intent.window.starts_at,
        ends_at=intent.window.ends_at,
        precision_minutes=intent.precision_minutes,
        edition_version=edition_version,
        lifecycle=day.lifecycle,
    )


def create_scheduling_service_day(
    request: SchedulingCommandRequest,
    *,
    day: SchedulingServiceDayInput,
    expected_control_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Create one exact day after checking current bounds and non-overlap.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution, explicit rationale and stable retry key.
    day : SchedulingServiceDayInput
        Complete explicit day label, interval and grid.
    expected_control_version : int
        Current Scheduling edition control, zero only before its first command.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy or sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult
        Stable day identifier and immutable first-revision evidence.
    """

    def normalize() -> SchedulingServiceDayInput:
        require_version(expected_control_version, initial=True)
        return day.normalized()

    def write(
        context: _CommandTransaction,
        intent: SchedulingServiceDayInput,
        envelope: EditionTimeEnvelopeReference,
    ) -> tuple[UUID, int]:
        _require_current_version(
            context.prior_control_version, expected_control_version
        )
        _validate_current_day(context, intent, envelope)
        if (
            SchedulingServiceDay.objects.filter(**context.ownership()).count()
            >= MAX_RETAINED_SERVICE_DAYS
        ):
            raise SchedulingLimitError
        record = SchedulingServiceDay.objects.create(
            **context.ownership(), aggregate_version=1
        )
        _day_revision(context, record, intent, edition_version=envelope.version)
        return record.id, 1

    return _execute(
        request,
        operation=SchedulingOperation.DAY_CREATE,
        capability=MANAGE_DAYS,
        normalize=normalize,
        payload=lambda intent: _payload(intent, expected_control_version, None),
        prepare=lambda _intent: _prepare_day(request),
        write=write,
        authorizer=authorizer,
    )


def revise_scheduling_service_day(
    request: SchedulingCommandRequest,
    *,
    day_id: UUID,
    day: SchedulingServiceDayInput,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Retain a corrected day revision without rewriting any candidate placement.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution, explicit rationale and stable retry key.
    day_id : UUID
        Exact active Scheduling service day.
    day : SchedulingServiceDayInput
        Complete corrected day intent.
    expected_version : int
        Exact current day version, independent of unrelated candidate changes.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy or sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult
        Same day identity with a new immutable source revision.
    """

    def normalize() -> SchedulingServiceDayInput:
        require_identifier(day_id)
        require_version(expected_version)
        return day.normalized()

    def write(
        context: _CommandTransaction,
        intent: SchedulingServiceDayInput,
        envelope: EditionTimeEnvelopeReference,
    ) -> tuple[UUID, int]:
        record = _locked_day(context, day_id, expected_version)
        if record.aggregate_version >= MAX_REVISIONS:
            raise SchedulingLimitError
        _validate_current_day(context, intent, envelope, excluding=day_id)
        record.aggregate_version += 1
        record.save(update_fields=("aggregate_version", "updated_at"))
        _day_revision(context, record, intent, edition_version=envelope.version)
        return record.id, record.aggregate_version

    return _execute(
        request,
        operation=SchedulingOperation.DAY_REVISE,
        capability=MANAGE_DAYS,
        normalize=normalize,
        payload=lambda intent: _payload(intent, expected_version, day_id),
        prepare=lambda _intent: _prepare_day(request),
        write=write,
        authorizer=authorizer,
    )


def _locked_day(
    context: _CommandTransaction, day_id: UUID, expected: int
) -> SchedulingServiceDay:
    day = (
        SchedulingServiceDay.objects.select_for_update()
        .filter(
            **context.ownership(),
            id=day_id,
        )
        .first()
    )
    if day is None:
        raise SchedulingUnavailableError
    _require_current_version(day.aggregate_version, expected)
    if day.lifecycle != "active":
        raise SchedulingLifecycleConflictError
    return day


def retire_scheduling_service_day(
    request: SchedulingCommandRequest,
    *,
    day_id: UUID,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Retire a mistaken day while retaining its history and stale placements.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Authenticated attribution and explicit human rationale.
    day_id : UUID
        Exact active day to retire.
    expected_version : int
        Current day version, including the last ordinary metadata revision.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy or sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult
        Stable retained day and a final retirement revision.
    """

    def normalize() -> UUID:
        require_version(expected_version)
        return require_identifier(day_id)

    def write(
        context: _CommandTransaction, identifier: UUID, _prepared: None
    ) -> tuple[UUID, int]:
        record = _locked_day(context, identifier, expected_version)
        latest = SchedulingServiceDayRevision.objects.filter(
            **context.ownership(), day_id=identifier, sequence=record.aggregate_version
        ).first()
        if latest is None:
            raise SchedulingUnavailableError
        record.aggregate_version += 1
        record.lifecycle = "retired"
        record.save(update_fields=("aggregate_version", "lifecycle", "updated_at"))
        _day_revision(
            context,
            record,
            SchedulingServiceDayInput(
                latest.label,
                SchedulingWindow(latest.starts_at, latest.ends_at),
                latest.precision_minutes,
            ),
            edition_version=latest.edition_version,
        )
        return record.id, record.aggregate_version

    return _execute(
        request,
        operation=SchedulingOperation.DAY_RETIRE,
        capability=MANAGE_DAYS,
        normalize=normalize,
        payload=lambda identifier: {
            "day_id": str(identifier),
            "expected_version": expected_version,
        },
        prepare=lambda _intent: None,
        write=write,
        authorizer=authorizer,
    )
