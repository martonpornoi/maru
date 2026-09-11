"""Exact reasoned public-copy withdrawal, independent from timetable replacement."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from maru.identity.queries import resolve_active_verified_person_reference

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_APPROVE_PUBLIC_COPY,
    ProgrammeAuthorizationDenied,
)
from .catalogs import ProgrammeCommandOperation as Operation
from .catalogs import ProgrammeReadinessConcern
from .commands import (
    ProgrammeUnavailableError,
    ProgrammeVersionConflictError,
    _audit_command_errors,
    _common_identifiers,
    _locked_control,
    _postauthorize,
    _preauthorize,
    _record_success,
    _replay,
    _require_version,
    _run_denial_safe,
)
from .inputs import (
    canonical_digest,
    normalized_reason,
    require_expected_version,
    require_uuid,
)
from .models import (
    ProgrammeItem,
    ProgrammePublicRendition,
    ProgrammePublicRenditionWithdrawal,
)
from .writer_boundary import programme_writer

if TYPE_CHECKING:
    from uuid import UUID

    import maru.programme.commands

    from .authorization import ProgrammeAuthorizer


@_audit_command_errors(
    capability_code=PROGRAMME_APPROVE_PUBLIC_COPY,
    operation=Operation.PUBLIC_RENDITION_WITHDRAW.value,
)
def withdraw_programme_public_rendition(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    rendition_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> maru.programme.commands.ProgrammeCommandResult:
    """Withdraw one exact public rendition and its retained release disclosure.

    Parameters
    ----------
    actor_id : UUID
        Current authenticated reviewer with explicit public-copy authority.
    organization_id : UUID
        Exact expected organizer scope, never proof of authority.
    edition_id : UUID
        Exact retained edition; ending operations does not prevent withdrawal.
    item_id : UUID
        Owning Programme item, including retained non-operational history.
    rendition_id : UUID
        Exact copy to withdraw; no implicit latest-copy or timetable selection.
    expected_version : int
        Observed current item version, preserved by the independent evidence stream.
    reason : str
        Mandatory normalized bounded rationale retained by the owner.
    idempotency_key : UUID
        Exact actor/edition retry identity, reauthorized on every retry.
    correlation_id : UUID
        Native command, Audit and event correlation.
    source_channel : str
        Normalized declared adapter origin.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Ordinary independent policy boundary; isolated dormant-profile test seam only.

    Returns
    -------
    maru.programme.commands.ProgrammeCommandResult
        Immutable withdrawal receipt and identifier; no copied public or private text.

    Notes
    -----
    The exact rendition remains immutable. Its native disclosure generation,
    withdrawal, receipt, Audit, event and outbox commit together, including for
    historical releases. Other renditions and active release pointers are untouched.
    Withdrawal cannot be undone; corrected public copy needs a newly reviewed
    rendition and separate independent timetable approval and publication.
    """
    organization_id, edition_id, idempotency_key, correlation_id, source_channel = (
        _common_identifiers(
            organization_id=organization_id,
            edition_id=edition_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
    )
    operation = Operation.PUBLIC_RENDITION_WITHDRAW.value
    _preauthorize(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_APPROVE_PUBLIC_COPY,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )
    item_id = require_uuid(item_id, field="item_id")
    rendition_id = require_uuid(rendition_id, field="rendition_id")
    expected_version = require_expected_version(expected_version)
    reason = normalized_reason(reason)
    digest = canonical_digest(
        {
            "operation": operation,
            "item_id": item_id,
            "rendition_id": rendition_id,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )

    def mutate() -> maru.programme.commands.ProgrammeCommandResult:
        with transaction.atomic(), programme_writer():
            scope = _postauthorize(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=PROGRAMME_APPROVE_PUBLIC_COPY,
                authorizer=authorizer,
            )
            if (
                resolve_active_verified_person_reference(account_id=scope.actor_id)
                is None
            ):
                raise ProgrammeAuthorizationDenied
            replay = _replay(
                actor_id=scope.actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=digest,
            )
            if replay is not None:
                return replay
            control = _locked_control(
                organization_id=organization_id, edition_id=edition_id, required=True
            )
            # Privacy/disclosure withdrawal must not reopen private planning and
            # must remain possible after the item or edition stops operating.
            item = (
                ProgrammeItem.objects.select_for_update()
                .filter(
                    id=item_id, organization_id=organization_id, edition_id=edition_id
                )
                .first()
            )
            if item is None:
                raise ProgrammeUnavailableError
            _require_version(actual=item.aggregate_version, expected=expected_version)
            rendition = ProgrammePublicRendition.objects.filter(
                id=rendition_id,
                item=item,
                organization_id=organization_id,
                edition_id=edition_id,
            ).first()
            if rendition is None:
                raise ProgrammeUnavailableError
            if ProgrammePublicRenditionWithdrawal.objects.filter(
                rendition=rendition
            ).exists():
                raise ProgrammeVersionConflictError
            occurred_at = timezone.now()
            withdrawal = ProgrammePublicRenditionWithdrawal.objects.create(
                rendition=rendition,
                item=item,
                organization_id=organization_id,
                edition_id=edition_id,
                actor_id=scope.actor_id,
                reason=reason,
                item_version=item.aggregate_version,
                occurred_at=occurred_at,
            )
            return _record_success(
                scope=scope,
                control=control,
                item=item,
                operation=Operation.PUBLIC_RENDITION_WITHDRAW,
                event_action="withdraw_public_copy",
                capability_code=PROGRAMME_APPROVE_PUBLIC_COPY,
                reason=reason,
                idempotency_key=idempotency_key,
                request_digest=digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
                result_object_id=withdrawal.id,
                expected_version=expected_version,
                resulting_item_version=item.aggregate_version,
                resulting_control_version=None,
                changed_fields=("public_rendition_withdrawal",),
                concern=ProgrammeReadinessConcern.PUBLIC_COPY.value,
                occurred_at=occurred_at,
                event_aggregate_type="programme.public_copy_withdrawal",
                event_aggregate_id=rendition.id,
                event_aggregate_version=1,
            )

    return _run_denial_safe(
        action=mutate,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_APPROVE_PUBLIC_COPY,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
