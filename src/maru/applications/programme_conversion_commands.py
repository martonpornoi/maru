"""Atomic Applications-to-Programme conversion of exact effective acceptance."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final, TypedDict
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.applications.models import (
    ApplicationCommandReceipt,
    ProgrammeAcceptedTransition,
    ProgrammeCommandReceipt,
    ProgrammeImportCommandReceipt,
    ProgrammeReviewReceipt,
)
from maru.applications.programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeIdempotencyConflictError,
)
from maru.applications.programme_conversion_authorization import (
    CONVERT_PROGRAMME_ACCEPTANCE,
    authorize_programme_conversion_retry,
    authorize_programme_conversion_scope,
)
from maru.applications.programme_conversion_events import (
    PROGRAMME_CONVERSION_COMPLETED_EVENT,
)
from maru.applications.programme_conversion_inputs import ProgrammeConversionInput
from maru.applications.programme_conversion_sources import (
    ProgrammeConversionConflictError,
    ProgrammeConversionUnavailableError,
    _current_accepted_decision,
)
from maru.applications.programme_inputs import (
    canonical_programme_digest,
    normalized_programme_text,
    require_programme_uuid,
)
from maru.applications.programme_write_scope import lock_programme_edition_write_scope
from maru.applications.programme_writer_boundary import (
    programme_application_database_writer,
)
from maru.applications.retry_namespace import lock_applications_retry_namespace
from maru.audit.services import AuditRecord, append_audit
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_ITEMS,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from maru.programme.commands import create_accepted_programme_item

if TYPE_CHECKING:
    from maru.applications.programme_authorization import (
        ApplicationsProgrammeAuthorizer,
    )
    from maru.programme.authorization import ProgrammeAuthorizer


_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_MAX_SOURCE_CHANNEL_LENGTH: Final = 32


class _ScopeIds(TypedDict):
    actor_id: UUID
    organization_id: UUID
    edition_id: UUID


@dataclass(frozen=True, slots=True)
class ProgrammeConversionResult:
    """Return retained result identifiers without source or working content.

    Attributes
    ----------
    transition_id
        Immutable Applications conversion/retry receipt identifier.
    programme_item_id
        Exactly one Programme-owned target item for the source revision.
    programme_item_version
        Retained creation version, not a claim about the item's current state.
    programme_control_version
        Retained edition-control result of this conversion.
    replayed
        Whether the exact original actor-owned intent was returned unchanged.
    """

    transition_id: UUID
    programme_item_id: UUID
    programme_item_version: int
    programme_control_version: int
    replayed: bool


def _result(
    receipt: ProgrammeAcceptedTransition, *, replayed: bool
) -> ProgrammeConversionResult:
    return ProgrammeConversionResult(
        transition_id=receipt.id,
        programme_item_id=receipt.programme_item_id,
        programme_item_version=1,
        programme_control_version=receipt.resulting_programme_version,
        replayed=replayed,
    )


def _replay(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    retry_key: UUID,
    digest: str,
) -> ProgrammeConversionResult | None:
    lock_applications_retry_namespace(
        edition_id=edition_id, actor_id=actor_id, retry_key=retry_key
    )
    filters = {"edition_id": edition_id, "actor_id": actor_id, "retry_key": retry_key}
    receipt = ProgrammeAcceptedTransition.objects.filter(**filters).first()
    if receipt is not None:
        if (
            receipt.organization_id != organization_id
            or receipt.request_digest != digest
        ):
            raise ApplicationsProgrammeIdempotencyConflictError
        return _result(receipt, replayed=True)
    if any(
        model.objects.filter(**filters).exists()
        for model in (
            ApplicationCommandReceipt,
            ProgrammeCommandReceipt,
            ProgrammeImportCommandReceipt,
            ProgrammeReviewReceipt,
        )
    ):
        raise ApplicationsProgrammeIdempotencyConflictError
    return None


@transaction.atomic
def _execute(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    command: ProgrammeConversionInput,
    retry_key: UUID,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ApplicationsProgrammeAuthorizer,
    programme_authorizer: ProgrammeAuthorizer,
) -> ProgrammeConversionResult:
    identifiers: _ScopeIds = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    for name, value in (
        ("actor_id", actor_id),
        ("organization_id", organization_id),
        ("edition_id", edition_id),
        ("department_id", department_id),
        ("retry_key", retry_key),
        ("correlation_id", correlation_id),
    ):
        require_programme_uuid(value, field=name)
    authorize_programme_conversion_retry(**identifiers, authorizer=authorizer)
    if not isinstance(command, ProgrammeConversionInput):
        raise ValidationError(
            "Use the typed exact Programme conversion input.",
            code="applications_programme_conversion_input_invalid",
        )
    command = command.normalized()
    reason = normalized_programme_text(
        reason,
        field="reason",
        maximum=1_000,
        required=True,
        collapse=True,
    )
    if (
        not isinstance(source_channel, str)
        or not source_channel
        or len(source_channel) > _MAX_SOURCE_CHANNEL_LENGTH
        or not source_channel.isascii()
        or not source_channel[0].islower()
        or any(
            not (character.islower() or character.isdigit() or character in "-_")
            for character in source_channel
        )
    ):
        raise ValidationError(
            "Use a bounded registered caller channel.",
            code="applications_programme_conversion_input_invalid",
        )
    digest = canonical_programme_digest(
        {
            **identifiers,
            "department_id": department_id,
            "command": asdict(command),
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    replay = _replay(**identifiers, retry_key=retry_key, digest=digest)
    if replay is not None:
        return replay
    authorize_programme_conversion_scope(
        **identifiers,
        department_id=department_id,
        authorizer=authorizer,
    )
    authorize_programme_scope(
        **identifiers,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        authorizer=programme_authorizer,
    )
    lock_programme_edition_write_scope(
        **identifiers,
        department_ids=(department_id,),
    )
    scope = authorize_programme_conversion_scope(
        **identifiers,
        department_id=department_id,
        authorizer=authorizer,
    )
    authorize_programme_scope(
        **identifiers,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        authorizer=programme_authorizer,
    )
    decision = _current_accepted_decision(
        scope=scope,
        decision_id=command.decision_id,
        revision_id=command.revision_id,
        expected_review_version=command.expected_review_version,
    )
    if ProgrammeAcceptedTransition.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
        revision_id=command.revision_id,
    ).exists():
        raise ProgrammeConversionConflictError
    transition_id, item_id = uuid4(), uuid4()
    occurred_at = timezone.now()
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=CONVERT_PROGRAMME_ACCEPTANCE,
            operation="applications.programme_conversion.completed",
            target_type="applications.programme_conversion",
            target_id=transition_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            changed_fields=("accepted_transition",),
            idempotency_key_hash=hashlib.sha256(str(retry_key).encode()).hexdigest(),
            retention_class="applications-programme-restricted",
        ),
        occurred_at=occurred_at,
    )
    event, _outbox = publish_domain_event(
        DomainEventRecord(
            event_name=PROGRAMME_CONVERSION_COMPLETED_EVENT,
            schema_version=1,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            aggregate_type="applications.programme_conversion",
            aggregate_id=transition_id,
            aggregate_version=1,
            payload={
                "transition_id": str(transition_id),
                "programme_item_id": str(item_id),
            },
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=scope.actor_id,
            retention_class="applications-programme-restricted",
        ),
        occurred_at=occurred_at,
    )
    with programme_application_database_writer():
        receipt = ProgrammeAcceptedTransition.objects.create(
            id=transition_id,
            **identifiers,
            revision_id=command.revision_id,
            decision=decision,
            programme_item_id=item_id,
            review_version=command.expected_review_version,
            expected_programme_version=command.expected_programme_version,
            resulting_programme_version=command.expected_programme_version + 1,
            retry_key=retry_key,
            request_digest=digest,
            reason=reason,
            audit_event_id=audit.id,
            domain_event_id=event.id,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
    target = create_accepted_programme_item(
        **identifiers,
        department_id=department_id,
        transition_id=transition_id,
        internal_title=command.internal_title,
        working_summary=command.working_summary,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=programme_authorizer,
        applications_authorizer=authorizer,
    )
    if (
        target.item_id != item_id
        or target.resulting_item_version != 1
        or target.resulting_control_version != receipt.resulting_programme_version
        or target.replayed
    ):
        raise ProgrammeConversionUnavailableError
    return _result(receipt, replayed=False)


def convert_accepted_programme_proposal(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    command: ProgrammeConversionInput,
    retry_key: UUID,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeConversionResult:
    """Convert one effective acceptance with atomic reciprocal owner evidence.

    Parameters
    ----------
    actor_id : UUID
        Active verified person with separate Applications and Programme authority.
    organization_id : UUID
        Exact common organization of source, actor authority, and target.
    edition_id : UUID
        Exact edition whose private planning must remain open for fresh work.
    department_id : UUID
        Current exact source-owner Department, not an inherited ancestor scope.
    command : ProgrammeConversionInput
        Exact decision/seal, expected cursors, and deliberate private working copy.
    retry_key : UUID
        Actor-owned key in the shared Applications retry namespace.
    reason : str
        Nonblank bounded conversion rationale, never public content.
    correlation_id : UUID
        Shared evidence correlation, excluded from normalized retry intent.
    source_channel : str
        Bounded caller-channel code; not a permission or source discriminator.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real source policy or its independently guarded isolated-test seam.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real target policy or its independently guarded isolated-test seam.

    Returns
    -------
    ProgrammeConversionResult
        Exact retained creation identifiers and versions; no private content.

    Raises
    ------
    Exception
        Re-raises the original validation, authorization, conflict, or database
        failure after rolling back success and attempting minimized failure audit.

    Notes
    -----
    Denial and conflict exceptions carry stable non-disclosing reason codes.
    Any failure rolls back both owners' complete success. A separate best-effort
    failure audit records only validated caller scope, never source/result IDs.
    """
    try:
        return _execute(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            command=command,
            retry_key=retry_key,
            reason=reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
            authorizer=authorizer,
            programme_authorizer=programme_authorizer,
        )
    except Exception as error:
        denied = isinstance(
            error,
            (
                ApplicationsProgrammeAuthorizationDeniedError,
                ProgrammeAuthorizationDeniedError,
            ),
        )
        with suppress(Exception):
            append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=actor_id if isinstance(actor_id, UUID) else None,
                    principal_context_id=None,
                    organization_id=organization_id
                    if isinstance(organization_id, UUID)
                    else None,
                    event_edition_id=edition_id
                    if isinstance(edition_id, UUID)
                    else None,
                    capability_code=CONVERT_PROGRAMME_ACCEPTANCE,
                    operation="applications.programme_conversion.failed",
                    target_type="applications.programme_conversion",
                    target_id=None,
                    outcome="deny" if denied else "error",
                    reason_code="applications_programme_conversion_denied"
                    if denied
                    else (
                        "applications_programme_conversion_conflict"
                        if isinstance(
                            error,
                            (
                                ProgrammeConversionConflictError,
                                ApplicationsProgrammeIdempotencyConflictError,
                            ),
                        )
                        else "applications_programme_conversion_unavailable"
                    ),
                    correlation_id=correlation_id
                    if isinstance(correlation_id, UUID)
                    else uuid4(),
                    request_id=None,
                    source_channel="service",
                    retention_class="applications-programme-restricted",
                )
            )
        raise


__all__ = ["ProgrammeConversionResult", "convert_accepted_programme_proposal"]
