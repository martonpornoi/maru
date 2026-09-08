"""Stable Programme occurrences with explicit grouping and retained retirement."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import F

from maru.programme.scheduling_queries import load_programme_scheduling_dependencies
from maru.venues.scheduling_invariants import require_no_active_scheduling_reservation

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, MANAGE_OCCURRENCES
from .catalogs import MAX_OCCURRENCES, MAX_REVISIONS, SchedulingOperation
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
    SchedulingOccurrenceInput,
    require_identifier,
    require_version,
)
from .models import SchedulingOccurrence, SchedulingOccurrenceRevision

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult


def _source(
    request: SchedulingCommandRequest, intent: SchedulingOccurrenceInput
) -> None:
    snapshot = load_programme_scheduling_dependencies(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        item_ids=(intent.item_id,),
        host_ids=(),
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
    )
    if len(snapshot.items) != 1 or snapshot.items[0].lifecycle != "active":
        raise SchedulingUnavailableError


def _payload(
    intent: SchedulingOccurrenceInput, expected_version: int, occurrence_id: UUID | None
) -> dict[str, object]:
    return {
        "item_id": str(intent.item_id),
        "group_key": str(intent.group_key) if intent.group_key else None,
        "group_sequence": intent.group_sequence,
        "expected_version": expected_version,
        "occurrence_id": str(occurrence_id) if occurrence_id else None,
    }


def _group_available(
    context: _CommandTransaction,
    intent: SchedulingOccurrenceInput,
    *,
    excluding: UUID | None = None,
) -> None:
    if (
        intent.group_key is not None
        and SchedulingOccurrenceRevision.objects.filter(
            **context.ownership(),
            sequence=F("occurrence__aggregate_version"),
            lifecycle="active",
            group_key=intent.group_key,
            group_sequence=intent.group_sequence,
        )
        .exclude(occurrence_id=excluding)
        .exists()
    ):
        raise SchedulingUnavailableError(
            "An active group sequence already names an occurrence."
        )


def _revision(
    context: _CommandTransaction,
    occurrence: SchedulingOccurrence,
    intent: SchedulingOccurrenceInput,
) -> None:
    SchedulingOccurrenceRevision.objects.create(
        **context.evidence(),
        occurrence=occurrence,
        sequence=occurrence.aggregate_version,
        group_key=intent.group_key,
        group_sequence=intent.group_sequence,
        lifecycle=occurrence.lifecycle,
    )


def _locked_occurrence(
    context: _CommandTransaction, occurrence_id: UUID, expected_version: int
) -> SchedulingOccurrence:
    occurrence = (
        SchedulingOccurrence.objects.select_for_update()
        .filter(
            **context.ownership(),
            id=occurrence_id,
        )
        .first()
    )
    if occurrence is None:
        raise SchedulingUnavailableError
    _require_current_version(occurrence.aggregate_version, expected_version)
    if occurrence.lifecycle != "active":
        raise SchedulingLifecycleConflictError
    return occurrence


def create_scheduling_occurrence(
    request: SchedulingCommandRequest,
    *,
    occurrence: SchedulingOccurrenceInput,
    expected_control_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Create one explicit occurrence without booking a room or confirming a host.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current authenticated attribution and explicit rationale.
    occurrence : SchedulingOccurrenceInput
        Programme source and optional explicit group/sequence pair.
    expected_control_version : int
        Exact current Scheduling control, or zero before the first command.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal Scheduling policy; Programme independently authorizes its source.

    Returns
    -------
    SchedulingCommandResult
        Stable occurrence identifier and first metadata revision.
    """

    def normalize() -> SchedulingOccurrenceInput:
        require_version(expected_control_version, initial=True)
        return occurrence.normalized()

    def write(
        context: _CommandTransaction, intent: SchedulingOccurrenceInput, _prepared: None
    ) -> tuple[UUID, int]:
        _require_current_version(
            context.prior_control_version, expected_control_version
        )
        if (
            SchedulingOccurrence.objects.filter(**context.ownership()).count()
            >= MAX_OCCURRENCES
        ):
            raise SchedulingLimitError
        _group_available(context, intent)
        record = SchedulingOccurrence.objects.create(
            **context.ownership(),
            programme_item_id=intent.item_id,
            aggregate_version=1,
        )
        _revision(context, record, intent)
        return record.id, 1

    return _execute(
        request,
        operation=SchedulingOperation.OCCURRENCE_CREATE,
        capability=MANAGE_OCCURRENCES,
        normalize=normalize,
        payload=lambda intent: _payload(intent, expected_control_version, None),
        prepare=lambda intent: _source(request, intent),
        write=write,
        authorizer=authorizer,
    )


def revise_scheduling_occurrence(
    request: SchedulingCommandRequest,
    *,
    occurrence_id: UUID,
    occurrence: SchedulingOccurrenceInput,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Correct explicit grouping without replacing the canonical Programme source.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current authenticated attribution and explicit correction rationale.
    occurrence_id : UUID
        Stable active occurrence being revised.
    occurrence : SchedulingOccurrenceInput
        Same Programme item and complete corrected group pair.
    expected_version : int
        Exact current occurrence metadata version.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal Scheduling policy; Programme independently authorizes its source.

    Returns
    -------
    SchedulingCommandResult
        Same occurrence identity with a new retained metadata revision.
    """

    def normalize() -> SchedulingOccurrenceInput:
        require_identifier(occurrence_id)
        require_version(expected_version)
        return occurrence.normalized()

    def write(
        context: _CommandTransaction, intent: SchedulingOccurrenceInput, _prepared: None
    ) -> tuple[UUID, int]:
        record = _locked_occurrence(context, occurrence_id, expected_version)
        if record.programme_item_id != intent.item_id:
            raise SchedulingUnavailableError("Occurrence source identity is immutable.")
        if record.aggregate_version >= MAX_REVISIONS:
            raise SchedulingLimitError
        _group_available(context, intent, excluding=occurrence_id)
        record.aggregate_version += 1
        record.save(update_fields=("aggregate_version", "updated_at"))
        _revision(context, record, intent)
        return record.id, record.aggregate_version

    return _execute(
        request,
        operation=SchedulingOperation.OCCURRENCE_REVISE,
        capability=MANAGE_OCCURRENCES,
        normalize=normalize,
        payload=lambda intent: _payload(intent, expected_version, occurrence_id),
        prepare=lambda intent: _source(request, intent),
        write=write,
        authorizer=authorizer,
    )


def retire_scheduling_occurrence(
    request: SchedulingCommandRequest,
    *,
    occurrence_id: UUID,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult:
    """Retain a retired occurrence so historical candidate membership stays meaningful.

    Parameters
    ----------
    request : SchedulingCommandRequest
        Current authenticated attribution and explicit retirement rationale.
    occurrence_id : UUID
        Stable active occurrence to retire.
    expected_version : int
        Exact current occurrence metadata version.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Normal policy or sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult
        Same occurrence identity with a final retirement revision.
    """

    def normalize() -> UUID:
        require_version(expected_version)
        return require_identifier(occurrence_id)

    def write(
        context: _CommandTransaction, identifier: UUID, _prepared: None
    ) -> tuple[UUID, int]:
        record = _locked_occurrence(context, identifier, expected_version)
        require_no_active_scheduling_reservation(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            occurrence_id=identifier,
        )
        latest = SchedulingOccurrenceRevision.objects.filter(
            **context.ownership(),
            occurrence_id=identifier,
            sequence=record.aggregate_version,
        ).first()
        if latest is None:
            raise SchedulingUnavailableError
        record.aggregate_version += 1
        record.lifecycle = "retired"
        record.save(update_fields=("aggregate_version", "lifecycle", "updated_at"))
        _revision(
            context,
            record,
            SchedulingOccurrenceInput(
                record.programme_item_id,
                latest.group_key,
                latest.group_sequence,
            ),
        )
        return record.id, record.aggregate_version

    return _execute(
        request,
        operation=SchedulingOperation.OCCURRENCE_RETIRE,
        capability=MANAGE_OCCURRENCES,
        normalize=normalize,
        payload=lambda identifier: {
            "occurrence_id": str(identifier),
            "expected_version": expected_version,
        },
        prepare=lambda _intent: None,
        write=write,
        authorizer=authorizer,
    )
