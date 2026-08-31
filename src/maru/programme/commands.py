"""Transactional commands for private Programme items and readiness."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Final, Literal, overload
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_APPROVE_PUBLIC_COPY,
    PROGRAMME_MANAGE_DELIVERY,
    PROGRAMME_MANAGE_ITEMS,
    PROGRAMME_MANAGE_READINESS,
    AuthorizedProgrammeScope,
    ProgrammeAuthorizationDenied,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.catalogs import (
    MAX_PROGRAMME_DISCUSSION_ENTRIES,
    MAX_PROGRAMME_EVIDENCE_NOTE_LENGTH,
    MAX_PROGRAMME_ITEMS_PER_EDITION,
    MAX_PROGRAMME_LAYER_REVISIONS,
    MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
    MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH,
    MAX_PROGRAMME_PUBLIC_RENDITIONS,
    MAX_PROGRAMME_READINESS_EVIDENCE,
    MAX_PROGRAMME_SOURCE_CHANNEL_LENGTH,
    MAX_PROGRAMME_SUMMARY_LENGTH,
    MAX_PROGRAMME_TITLE_LENGTH,
    PROGRAMME_EVIDENCE_SOURCE_ALLOWED_CONCERNS,
    PROGRAMME_EVIDENCE_SOURCE_DEFINITIONS,
    PROGRAMME_OPERATOR_ATTESTATION_SOURCE,
    PROGRAMME_ORGANIZER_CORE_SOURCE,
    ProgrammeCommandOperation,
    ProgrammeItemKind,
    ProgrammeItemLifecycle,
    ProgrammeProvenanceKind,
    ProgrammeReadinessConcern,
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
)
from maru.programme.events import (
    PROGRAMME_ITEM_CHANGED_EVENT,
    PROGRAMME_ITEM_CHANGED_SCHEMA_VERSION,
    programme_item_changed_payload,
)
from maru.programme.inputs import (
    SOURCE_CHANNEL_PATTERN,
    canonical_digest,
    normalized_closed_code,
    normalized_reason,
    normalized_source_channel,
    normalized_text,
    require_expected_version,
    require_positive_version,
    require_uuid,
)
from maru.programme.models import (
    ProgrammeCommandReceipt,
    ProgrammeDeliveryRevision,
    ProgrammeDepartmentDiscussionEntry,
    ProgrammeEditionControl,
    ProgrammeItem,
    ProgrammeItemSourceBinding,
    ProgrammePublicRendition,
    ProgrammeReadinessEvidence,
    ProgrammeReadinessRequirement,
    ProgrammeReadinessRequirementRevision,
    ProgrammeWorkingRevision,
)
from maru.programme.writer_boundary import programme_writer

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
_DELIVERY_READINESS_CONCERNS: Final = frozenset(
    {
        ProgrammeReadinessConcern.TECHNICAL_NEEDS.value,
        ProgrammeReadinessConcern.ACCESSIBILITY_DELIVERY.value,
        ProgrammeReadinessConcern.MEDIA_CONSENT.value,
    }
)
_PROGRAMME_INPUT_VALIDATION_CODES: Final = frozenset(
    {
        "programme_closed_value_invalid",
        "programme_control_character",
        "programme_delivery_empty",
        "programme_digest_invalid",
        "programme_evidence_identity_forbidden",
        "programme_evidence_source_concern_invalid",
        "programme_evidence_source_shape_invalid",
        "programme_positive_version_invalid",
        "programme_source_channel_invalid",
        "programme_text_invalid",
        "programme_uuid_invalid",
        "programme_value_required",
        "programme_value_too_long",
        "programme_version_invalid",
    }
)


class ProgrammeCommandError(RuntimeError):
    """Base class for stable, non-content Programme command failures."""

    reason_code = "programme_command_conflict"


class ProgrammeUnavailableError(ProgrammeCommandError):
    """Hide whether a scoped Programme aggregate exists."""

    reason_code = "programme_unavailable"


class ProgrammeLifecycleConflictError(ProgrammeCommandError):
    """Signal an edition or item lifecycle that rejects the command."""

    reason_code = "programme_lifecycle_conflict"


class ProgrammeVersionConflictError(ProgrammeCommandError):
    """Signal optimistic state newer or older than the caller expected."""

    reason_code = "programme_version_conflict"


class ProgrammeIdempotencyConflictError(ProgrammeCommandError):
    """Signal reuse of an idempotency key for different normalized input."""

    reason_code = "programme_idempotency_conflict"


class ProgrammeLimitConflictError(ProgrammeCommandError):
    """Signal a configured hard evidence or aggregate ceiling."""

    reason_code = "programme_limit_conflict"


@dataclass(frozen=True, slots=True)
class ProgrammeCommandResult:
    """Return immutable receipt and aggregate identifiers after a command.

    Attributes
    ----------
    receipt_id
        Identifier of the immutable command receipt.
    item_id
        Identifier of the affected Programme item.
    result_object_id
        Identifier of the operation-specific immutable result.
    resulting_control_version
        Resulting edition-control version for creation, otherwise ``None``.
    resulting_item_version
        Item aggregate version represented by the receipt.
    replayed
        Whether the command returned an exact prior receipt.
    """

    receipt_id: UUID
    item_id: UUID
    result_object_id: UUID
    resulting_control_version: int | None
    resulting_item_version: int
    replayed: bool

    @property
    def resulting_version(self) -> int:
        """Return the resulting item version for generic command adapters."""
        return self.resulting_item_version


def _idempotency_hash(idempotency_key: UUID) -> str:
    return hashlib.sha256(str(idempotency_key).encode()).hexdigest()


def _result(
    receipt: ProgrammeCommandReceipt,
    *,
    replayed: bool,
) -> ProgrammeCommandResult:
    return ProgrammeCommandResult(
        receipt_id=receipt.id,
        item_id=receipt.item_id,
        result_object_id=receipt.result_object_id,
        resulting_control_version=receipt.resulting_control_version,
        resulting_item_version=receipt.resulting_item_version,
        replayed=replayed,
    )


def _append_denial_audit(
    *,
    actor_id: object,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    operation: str,
    correlation_id: UUID,
    source_channel: str,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=_safe_audit_uuid(actor_id),
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=capability_code,
            operation=f"programme.command.{operation}",
            target_type="programme.scope",
            target_id=None,
            outcome="deny",
            reason_code=ProgrammeAuthorizationDenied.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="programme-restricted",
        )
    )


def _validation_error_codes(error: ValidationError) -> frozenset[str]:
    error_dict = getattr(error, "error_dict", None)
    if error_dict is not None:
        return frozenset(
            nested.code
            for nested_errors in error_dict.values()
            for nested in nested_errors
            if nested.code is not None
        )
    return frozenset(
        nested.code
        for nested in getattr(error, "error_list", ())
        if nested.code is not None
    )


def _error_reason_code(error: Exception) -> str:
    if isinstance(error, ValidationError):
        codes = _validation_error_codes(error)
        if codes and codes <= _PROGRAMME_INPUT_VALIDATION_CODES:
            return "programme_input_invalid"
        return "programme_dependency_error"
    if isinstance(error, ProgrammeCommandError):
        return error.reason_code
    return "programme_dependency_error"


def _safe_audit_uuid(value: object) -> UUID | None:
    return value if isinstance(value, UUID) else None


def _append_error_audit_best_effort(
    *,
    error: Exception,
    actor_id: object,
    organization_id: object,
    edition_id: object,
    capability_code: str,
    operation: str,
    correlation_id: object,
    source_channel: object,
) -> None:
    safe_actor_id = _safe_audit_uuid(actor_id)
    safe_correlation_id = _safe_audit_uuid(correlation_id) or uuid4()
    safe_source_channel = (
        source_channel
        if isinstance(source_channel, str)
        and 0 < len(source_channel) <= MAX_PROGRAMME_SOURCE_CHANNEL_LENGTH
        and SOURCE_CHANNEL_PATTERN.fullmatch(source_channel) is not None
        else "service"
    )
    with suppress(Exception):
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=safe_actor_id,
                principal_context_id=None,
                organization_id=_safe_audit_uuid(organization_id),
                event_edition_id=_safe_audit_uuid(edition_id),
                capability_code=capability_code,
                operation=f"programme.command.{operation}",
                target_type="programme.scope",
                target_id=None,
                outcome="error",
                reason_code=_error_reason_code(error),
                correlation_id=safe_correlation_id,
                request_id=safe_correlation_id,
                source_channel=safe_source_channel,
                obligations=("audit",),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="programme-restricted",
            )
        )


def _audit_command_errors[**ParametersT](
    *,
    capability_code: str,
    operation: str,
) -> Callable[
    [Callable[ParametersT, ProgrammeCommandResult]],
    Callable[ParametersT, ProgrammeCommandResult],
]:
    def decorate(
        command: Callable[ParametersT, ProgrammeCommandResult],
    ) -> Callable[ParametersT, ProgrammeCommandResult]:
        @wraps(command)
        def wrapped(
            *args: ParametersT.args,
            **kwargs: ParametersT.kwargs,
        ) -> ProgrammeCommandResult:
            try:
                return command(*args, **kwargs)
            except ProgrammeAuthorizationDenied:
                raise
            except Exception as error:
                _append_error_audit_best_effort(
                    error=error,
                    actor_id=kwargs.get("actor_id"),
                    organization_id=kwargs.get("organization_id"),
                    edition_id=kwargs.get("edition_id"),
                    capability_code=capability_code,
                    operation=operation,
                    correlation_id=kwargs.get("correlation_id"),
                    source_channel=kwargs.get("source_channel"),
                )
                raise

        return wrapped

    return decorate


def _preauthorize(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    operation: str,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ProgrammeAuthorizer,
) -> None:
    try:
        authorize_programme_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            authorizer=authorizer,
        )
    except ProgrammeAuthorizationDenied:
        _append_denial_audit(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        raise


def _postauthorize(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    authorizer: ProgrammeAuthorizer,
) -> AuthorizedProgrammeScope:
    return authorize_programme_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=capability_code,
        authorizer=authorizer,
        lock=True,
    )


def _common_identifiers(
    *,
    organization_id: UUID,
    edition_id: UUID,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> tuple[UUID, UUID, UUID, UUID, str]:
    return (
        require_uuid(organization_id, field="organization_id"),
        require_uuid(edition_id, field="edition_id"),
        require_uuid(idempotency_key, field="idempotency_key"),
        require_uuid(correlation_id, field="correlation_id"),
        normalized_source_channel(source_channel),
    )


def _ensure_editable(scope: AuthorizedProgrammeScope) -> None:
    if not scope.accepts_private_planning_writes:
        raise ProgrammeLifecycleConflictError


@overload
def _locked_control(
    *,
    organization_id: UUID,
    edition_id: UUID,
    required: Literal[True],
) -> ProgrammeEditionControl: ...


@overload
def _locked_control(
    *,
    organization_id: UUID,
    edition_id: UUID,
    required: Literal[False],
) -> ProgrammeEditionControl | None: ...


def _locked_control(
    *,
    organization_id: UUID,
    edition_id: UUID,
    required: bool,
) -> ProgrammeEditionControl | None:
    control = (
        ProgrammeEditionControl.objects.select_for_update()
        .filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .first()
    )
    if control is None and required:
        raise ProgrammeUnavailableError
    return control


def _locked_item(
    *,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
) -> ProgrammeItem:
    item = (
        ProgrammeItem.objects.select_for_update()
        .filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .first()
    )
    if item is None:
        raise ProgrammeUnavailableError
    if item.lifecycle != ProgrammeItemLifecycle.ACTIVE.value:
        raise ProgrammeLifecycleConflictError
    return item


def _replay(
    *,
    actor_id: UUID,
    edition_id: UUID,
    idempotency_key: UUID,
    request_digest: str,
) -> ProgrammeCommandResult | None:
    receipt = (
        ProgrammeCommandReceipt.objects.select_for_update()
        .filter(
            edition_id=edition_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
        .first()
    )
    if receipt is None:
        return None
    if receipt.request_digest != request_digest:
        raise ProgrammeIdempotencyConflictError
    return _result(receipt, replayed=True)


def _require_version(*, actual: int, expected: int) -> None:
    if actual != expected:
        raise ProgrammeVersionConflictError


def _advance_item(item: ProgrammeItem, *, actor_id: UUID) -> int:
    resulting_version = item.aggregate_version + 1
    item.aggregate_version = resulting_version
    item.last_modified_by_id = actor_id
    item.save(update_fields=("aggregate_version", "last_modified_by", "updated_at"))
    return resulting_version


def _advance_dependency_versions(
    *,
    item: ProgrammeItem,
    actor_id: UUID,
    resulting_item_version: int,
    concerns: frozenset[str],
) -> None:
    requirements = tuple(
        ProgrammeReadinessRequirement.objects.select_for_update()
        .filter(item=item, concern__in=concerns)
        .order_by("concern", "id")
    )
    for requirement in requirements:
        requirement.dependency_version = resulting_item_version
        requirement.item_version = resulting_item_version
        requirement.last_modified_by_id = actor_id
        requirement.save(
            update_fields=(
                "dependency_version",
                "item_version",
                "last_modified_by",
                "updated_at",
            )
        )


def _initial_readiness_dependency_version(
    *,
    item: ProgrammeItem,
    concern: ProgrammeReadinessConcern,
) -> int:
    if concern is ProgrammeReadinessConcern.PUBLIC_COPY:
        working_source = (
            ProgrammeWorkingRevision.objects.filter(item=item)
            .order_by("-sequence", "-id")
            .only("item_version")
            .first()
        )
        return working_source.item_version if working_source is not None else 0
    if concern.value in _DELIVERY_READINESS_CONCERNS:
        delivery_source = (
            ProgrammeDeliveryRevision.objects.filter(item=item)
            .order_by("-sequence", "-id")
            .only("item_version")
            .first()
        )
        return delivery_source.item_version if delivery_source is not None else 0
    return 0


def _record_success(
    *,
    scope: AuthorizedProgrammeScope,
    control: ProgrammeEditionControl,
    item: ProgrammeItem,
    operation: ProgrammeCommandOperation,
    event_action: str,
    capability_code: str,
    reason: str,
    idempotency_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    source_channel: str,
    result_object_id: UUID,
    expected_version: int,
    resulting_item_version: int,
    resulting_control_version: int | None,
    changed_fields: tuple[str, ...],
    concern: str = "none",
    occurred_at: datetime,
    event_aggregate_type: str = "programme.item",
    event_aggregate_id: UUID | None = None,
    event_aggregate_version: int | None = None,
) -> ProgrammeCommandResult:
    receipt = ProgrammeCommandReceipt.objects.create(
        control=control,
        item=item,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        operation=operation.value,
        actor_id=scope.actor_id,
        reason=reason,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        correlation_id=correlation_id,
        source_channel=source_channel,
        result_object_id=result_object_id,
        expected_version=expected_version,
        resulting_control_version=resulting_control_version,
        resulting_item_version=resulting_item_version,
    )
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=capability_code,
            operation=f"programme.command.{operation.value}",
            target_type="programme.item",
            target_id=item.id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            changed_fields=changed_fields,
            idempotency_key_hash=_idempotency_hash(idempotency_key),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="programme-restricted",
        ),
        occurred_at=occurred_at,
    )
    publish_domain_event(
        DomainEventRecord(
            event_name=PROGRAMME_ITEM_CHANGED_EVENT,
            schema_version=PROGRAMME_ITEM_CHANGED_SCHEMA_VERSION,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            aggregate_type=event_aggregate_type,
            aggregate_id=event_aggregate_id or item.id,
            aggregate_version=(
                event_aggregate_version
                if event_aggregate_version is not None
                else resulting_item_version
            ),
            payload=programme_item_changed_payload(
                action=event_action,
                item_kind=item.kind,
                provenance=item.provenance_kind,
                lifecycle=item.lifecycle,
                concern=concern,
            ),
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=scope.actor_id,
            retention_class="programme-restricted",
        ),
        occurred_at=occurred_at,
    )
    return _result(receipt, replayed=False)


def _run_denial_safe[ResultT](
    *,
    action: Callable[[], ResultT],
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    capability_code: str,
    operation: str,
    correlation_id: UUID,
    source_channel: str,
) -> ResultT:
    try:
        return action()
    except ProgrammeAuthorizationDenied:
        _append_denial_audit(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=capability_code,
            operation=operation,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        raise


@_audit_command_errors(
    capability_code=PROGRAMME_MANAGE_ITEMS,
    operation=ProgrammeCommandOperation.ITEM_CREATE.value,
)
def create_organizer_core_item(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    kind: str | ProgrammeItemKind,
    internal_title: str,
    working_summary: str = "",
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeCommandResult:
    """Create one organizer-owned core item and its initial working revision.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact private-planning edition identifier.
    kind : str | ProgrammeItemKind
        The closed core item kind.
    internal_title : str
        The bounded private working title.
    working_summary : str, default=""
        Optional private working summary.
    expected_version : int
        The exact current edition-control version.
    reason : str
        The retained human rationale.
    idempotency_key : UUID
        The caller-generated retry key.
    correlation_id : UUID
        The trace identifier shared by success evidence.
    source_channel : str
        The normalized calling channel.
    now : datetime | None, default=None
        Optional authoritative timestamp for deterministic execution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Immutable receipt and resulting aggregate identifiers.
    """
    (
        organization_id,
        edition_id,
        idempotency_key,
        correlation_id,
        source_channel,
    ) = _common_identifiers(
        organization_id=organization_id,
        edition_id=edition_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    operation = ProgrammeCommandOperation.ITEM_CREATE.value
    _preauthorize(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )
    normalized_kind = normalized_closed_code(
        kind,
        field="kind",
        enum_type=ProgrammeItemKind,
    )
    normalized_title = normalized_text(
        internal_title,
        field="internal_title",
        maximum=MAX_PROGRAMME_TITLE_LENGTH,
        required=True,
        collapse=True,
    )
    normalized_summary = normalized_text(
        working_summary,
        field="working_summary",
        maximum=MAX_PROGRAMME_SUMMARY_LENGTH,
    )
    expected_version = require_expected_version(expected_version)
    reason = normalized_reason(reason)
    request_digest = canonical_digest(
        {
            "operation": operation,
            "kind": normalized_kind.value,
            "internal_title": normalized_title,
            "working_summary": normalized_summary,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    occurred_at = now or timezone.now()

    def mutate() -> ProgrammeCommandResult:
        with transaction.atomic(), programme_writer():
            scope = _postauthorize(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=PROGRAMME_MANAGE_ITEMS,
                authorizer=authorizer,
            )
            replay = _replay(
                actor_id=scope.actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay
            _ensure_editable(scope)
            control = _locked_control(
                organization_id=organization_id,
                edition_id=edition_id,
                required=False,
            )
            current_control_version = control.aggregate_version if control else 0
            _require_version(
                actual=current_control_version,
                expected=expected_version,
            )
            if (
                ProgrammeItem.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                ).count()
                >= MAX_PROGRAMME_ITEMS_PER_EDITION
            ):
                raise ProgrammeLimitConflictError
            resulting_control_version = expected_version + 1
            if control is None:
                control = ProgrammeEditionControl.objects.create(
                    organization_id=scope.organization_id,
                    edition_id=scope.edition_id,
                    aggregate_version=resulting_control_version,
                )
            else:
                control.aggregate_version = resulting_control_version
                control.save(update_fields=("aggregate_version", "updated_at"))
            item = ProgrammeItem.objects.create(
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                kind=normalized_kind.value,
                provenance_kind=ProgrammeProvenanceKind.ORGANIZER_CORE.value,
                lifecycle=ProgrammeItemLifecycle.ACTIVE.value,
                aggregate_version=1,
                created_by_id=scope.actor_id,
                last_modified_by_id=scope.actor_id,
            )
            ProgrammeItemSourceBinding.objects.create(
                item=item,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                binding_code=PROGRAMME_ORGANIZER_CORE_SOURCE,
                source_object_id=None,
                source_version=None,
            )
            ProgrammeWorkingRevision.objects.create(
                item=item,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                sequence=1,
                item_version=1,
                internal_title=normalized_title,
                working_summary=normalized_summary,
                actor_id=scope.actor_id,
                reason=reason,
                occurred_at=occurred_at,
            )
            return _record_success(
                scope=scope,
                control=control,
                item=item,
                operation=ProgrammeCommandOperation.ITEM_CREATE,
                event_action="create_core_item",
                capability_code=PROGRAMME_MANAGE_ITEMS,
                reason=reason,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
                result_object_id=item.id,
                expected_version=expected_version,
                resulting_item_version=1,
                resulting_control_version=resulting_control_version,
                changed_fields=("item", "provenance", "working_information"),
                occurred_at=occurred_at,
            )

    return _run_denial_safe(
        action=mutate,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


@_audit_command_errors(
    capability_code=PROGRAMME_MANAGE_ITEMS,
    operation=ProgrammeCommandOperation.WORKING_REVISE.value,
)
def revise_programme_working(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    internal_title: str,
    working_summary: str = "",
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeCommandResult:
    """Append private working copy and invalidate only public-copy evidence.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact private-planning edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    internal_title : str
        The bounded replacement private title.
    working_summary : str, default=""
        Optional replacement private summary.
    expected_version : int
        The exact current item version.
    reason : str
        The retained human rationale.
    idempotency_key : UUID
        The caller-generated retry key.
    correlation_id : UUID
        The trace identifier shared by success evidence.
    source_channel : str
        The normalized calling channel.
    now : datetime | None, default=None
        Optional authoritative timestamp for deterministic execution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Immutable receipt and resulting item version.
    """
    return _revise_text_layer(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        item_id=item_id,
        expected_version=expected_version,
        reason=reason,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        now=now,
        authorizer=authorizer,
        internal_title=internal_title,
        working_summary=working_summary,
    )


def _revise_text_layer(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None,
    authorizer: ProgrammeAuthorizer,
    internal_title: str,
    working_summary: str,
) -> ProgrammeCommandResult:
    (
        organization_id,
        edition_id,
        idempotency_key,
        correlation_id,
        source_channel,
    ) = _common_identifiers(
        organization_id=organization_id,
        edition_id=edition_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    item_id = require_uuid(item_id, field="item_id")
    operation = ProgrammeCommandOperation.WORKING_REVISE.value
    _preauthorize(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )
    normalized_title = normalized_text(
        internal_title,
        field="internal_title",
        maximum=MAX_PROGRAMME_TITLE_LENGTH,
        required=True,
        collapse=True,
    )
    normalized_summary = normalized_text(
        working_summary,
        field="working_summary",
        maximum=MAX_PROGRAMME_SUMMARY_LENGTH,
    )
    expected_version = require_expected_version(expected_version)
    reason = normalized_reason(reason)
    request_digest = canonical_digest(
        {
            "operation": operation,
            "item_id": item_id,
            "internal_title": normalized_title,
            "working_summary": normalized_summary,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    occurred_at = now or timezone.now()

    def mutate() -> ProgrammeCommandResult:
        with transaction.atomic(), programme_writer():
            scope = _postauthorize(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=PROGRAMME_MANAGE_ITEMS,
                authorizer=authorizer,
            )
            replay = _replay(
                actor_id=scope.actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay
            _ensure_editable(scope)
            control = _locked_control(
                organization_id=organization_id,
                edition_id=edition_id,
                required=True,
            )
            item = _locked_item(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id=item_id,
            )
            _require_version(actual=item.aggregate_version, expected=expected_version)
            latest_sequence = (
                ProgrammeWorkingRevision.objects.select_for_update()
                .filter(item=item)
                .aggregate(value=Max("sequence"))["value"]
                or 0
            )
            if latest_sequence >= MAX_PROGRAMME_LAYER_REVISIONS:
                raise ProgrammeLimitConflictError
            resulting_version = item.aggregate_version + 1
            _advance_item(item, actor_id=scope.actor_id)
            revision = ProgrammeWorkingRevision.objects.create(
                item=item,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                sequence=latest_sequence + 1,
                item_version=resulting_version,
                internal_title=normalized_title,
                working_summary=normalized_summary,
                actor_id=scope.actor_id,
                reason=reason,
                occurred_at=occurred_at,
            )
            _advance_dependency_versions(
                item=item,
                actor_id=scope.actor_id,
                resulting_item_version=resulting_version,
                concerns=frozenset({ProgrammeReadinessConcern.PUBLIC_COPY.value}),
            )
            return _record_success(
                scope=scope,
                control=control,
                item=item,
                operation=ProgrammeCommandOperation.WORKING_REVISE,
                event_action="revise_working",
                capability_code=PROGRAMME_MANAGE_ITEMS,
                reason=reason,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
                result_object_id=revision.id,
                expected_version=expected_version,
                resulting_item_version=resulting_version,
                resulting_control_version=None,
                changed_fields=("working_information",),
                occurred_at=occurred_at,
            )

    return _run_denial_safe(
        action=mutate,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


@_audit_command_errors(
    capability_code=PROGRAMME_MANAGE_DELIVERY,
    operation=ProgrammeCommandOperation.DELIVERY_REVISE.value,
)
def revise_programme_delivery(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    technical_requirements: str = "",
    accessibility_delivery: str = "",
    media_consent_notes: str = "",
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeCommandResult:
    """Append delivery facts separately from working and public content.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact private-planning edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    technical_requirements : str, default=""
        Optional private technical-delivery facts.
    accessibility_delivery : str, default=""
        Optional private accessibility-delivery facts.
    media_consent_notes : str, default=""
        Optional private media-consent delivery facts.
    expected_version : int
        The exact current item version.
    reason : str
        The retained human rationale.
    idempotency_key : UUID
        The caller-generated retry key.
    correlation_id : UUID
        The trace identifier shared by success evidence.
    source_channel : str
        The normalized calling channel.
    now : datetime | None, default=None
        Optional authoritative timestamp for deterministic execution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Immutable receipt and resulting item version.

    Raises
    ------
    ValidationError
        If every delivery field is empty after normalization.
    """
    (
        organization_id,
        edition_id,
        idempotency_key,
        correlation_id,
        source_channel,
    ) = _common_identifiers(
        organization_id=organization_id,
        edition_id=edition_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    item_id = require_uuid(item_id, field="item_id")
    operation = ProgrammeCommandOperation.DELIVERY_REVISE.value
    _preauthorize(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_DELIVERY,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )
    delivery = {
        "technical_requirements": normalized_text(
            technical_requirements,
            field="technical_requirements",
            maximum=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        ),
        "accessibility_delivery": normalized_text(
            accessibility_delivery,
            field="accessibility_delivery",
            maximum=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        ),
        "media_consent_notes": normalized_text(
            media_consent_notes,
            field="media_consent_notes",
            maximum=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        ),
    }
    if not any(delivery.values()):
        raise ValidationError(
            "Record at least one delivery fact.",
            code="programme_delivery_empty",
        )
    expected_version = require_expected_version(expected_version)
    reason = normalized_reason(reason)
    request_digest = canonical_digest(
        {
            "operation": operation,
            "item_id": item_id,
            **delivery,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    occurred_at = now or timezone.now()

    def mutate() -> ProgrammeCommandResult:
        with transaction.atomic(), programme_writer():
            scope = _postauthorize(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=PROGRAMME_MANAGE_DELIVERY,
                authorizer=authorizer,
            )
            replay = _replay(
                actor_id=scope.actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay
            _ensure_editable(scope)
            control = _locked_control(
                organization_id=organization_id,
                edition_id=edition_id,
                required=True,
            )
            item = _locked_item(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id=item_id,
            )
            _require_version(actual=item.aggregate_version, expected=expected_version)
            latest_sequence = (
                ProgrammeDeliveryRevision.objects.select_for_update()
                .filter(item=item)
                .aggregate(value=Max("sequence"))["value"]
                or 0
            )
            if latest_sequence >= MAX_PROGRAMME_LAYER_REVISIONS:
                raise ProgrammeLimitConflictError
            resulting_version = item.aggregate_version + 1
            _advance_item(item, actor_id=scope.actor_id)
            revision = ProgrammeDeliveryRevision.objects.create(
                item=item,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                sequence=latest_sequence + 1,
                item_version=resulting_version,
                actor_id=scope.actor_id,
                reason=reason,
                occurred_at=occurred_at,
                **delivery,
            )
            _advance_dependency_versions(
                item=item,
                actor_id=scope.actor_id,
                resulting_item_version=resulting_version,
                concerns=_DELIVERY_READINESS_CONCERNS,
            )
            return _record_success(
                scope=scope,
                control=control,
                item=item,
                operation=ProgrammeCommandOperation.DELIVERY_REVISE,
                event_action="revise_delivery",
                capability_code=PROGRAMME_MANAGE_DELIVERY,
                reason=reason,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
                result_object_id=revision.id,
                expected_version=expected_version,
                resulting_item_version=resulting_version,
                resulting_control_version=None,
                changed_fields=("delivery_information",),
                occurred_at=occurred_at,
            )

    return _run_denial_safe(
        action=mutate,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_DELIVERY,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


@_audit_command_errors(
    capability_code=PROGRAMME_MANAGE_ITEMS,
    operation=ProgrammeCommandOperation.DISCUSSION_APPEND.value,
)
def append_programme_discussion(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    body: str,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeCommandResult:
    """Append a retained Department discussion entry without public leakage.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact private-planning edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    body : str
        The bounded private Department discussion body.
    expected_version : int
        The exact current item version.
    reason : str
        The retained human rationale.
    idempotency_key : UUID
        The caller-generated retry key.
    correlation_id : UUID
        The trace identifier shared by success evidence.
    source_channel : str
        The normalized calling channel.
    now : datetime | None, default=None
        Optional authoritative timestamp for deterministic execution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Immutable receipt and resulting item version.
    """
    (
        organization_id,
        edition_id,
        idempotency_key,
        correlation_id,
        source_channel,
    ) = _common_identifiers(
        organization_id=organization_id,
        edition_id=edition_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    item_id = require_uuid(item_id, field="item_id")
    operation = ProgrammeCommandOperation.DISCUSSION_APPEND.value
    _preauthorize(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )
    body = normalized_text(
        body,
        field="body",
        maximum=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        required=True,
    )
    expected_version = require_expected_version(expected_version)
    reason = normalized_reason(reason)
    request_digest = canonical_digest(
        {
            "operation": operation,
            "item_id": item_id,
            "body": body,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    occurred_at = now or timezone.now()

    def mutate() -> ProgrammeCommandResult:
        with transaction.atomic(), programme_writer():
            scope = _postauthorize(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=PROGRAMME_MANAGE_ITEMS,
                authorizer=authorizer,
            )
            replay = _replay(
                actor_id=scope.actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay
            _ensure_editable(scope)
            control = _locked_control(
                organization_id=organization_id,
                edition_id=edition_id,
                required=True,
            )
            item = _locked_item(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id=item_id,
            )
            _require_version(actual=item.aggregate_version, expected=expected_version)
            latest_sequence = (
                ProgrammeDepartmentDiscussionEntry.objects.select_for_update()
                .filter(item=item)
                .aggregate(value=Max("sequence"))["value"]
                or 0
            )
            if latest_sequence >= MAX_PROGRAMME_DISCUSSION_ENTRIES:
                raise ProgrammeLimitConflictError
            resulting_version = item.aggregate_version + 1
            _advance_item(item, actor_id=scope.actor_id)
            entry = ProgrammeDepartmentDiscussionEntry.objects.create(
                item=item,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                sequence=latest_sequence + 1,
                item_version=resulting_version,
                body=body,
                actor_id=scope.actor_id,
                reason=reason,
                occurred_at=occurred_at,
            )
            return _record_success(
                scope=scope,
                control=control,
                item=item,
                operation=ProgrammeCommandOperation.DISCUSSION_APPEND,
                event_action="append_discussion",
                capability_code=PROGRAMME_MANAGE_ITEMS,
                reason=reason,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
                result_object_id=entry.id,
                expected_version=expected_version,
                resulting_item_version=resulting_version,
                resulting_control_version=None,
                changed_fields=("discussion_entries",),
                occurred_at=occurred_at,
            )

    return _run_denial_safe(
        action=mutate,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


@_audit_command_errors(
    capability_code=PROGRAMME_MANAGE_READINESS,
    operation=ProgrammeCommandOperation.READINESS_CONFIGURE.value,
)
def configure_programme_readiness(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    concern: str | ProgrammeReadinessConcern,
    disposition: str | ProgrammeReadinessDisposition,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeCommandResult:
    """Create or revise one explicit readiness requirement with history.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact private-planning edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    concern : str | ProgrammeReadinessConcern
        The closed readiness concern.
    disposition : str | ProgrammeReadinessDisposition
        Whether the concern is required or not applicable.
    expected_version : int
        The exact current item version.
    reason : str
        The retained human rationale.
    idempotency_key : UUID
        The caller-generated retry key.
    correlation_id : UUID
        The trace identifier shared by success evidence.
    source_channel : str
        The normalized calling channel.
    now : datetime | None, default=None
        Optional authoritative timestamp for deterministic execution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Immutable receipt and resulting requirement revision.
    """
    (
        organization_id,
        edition_id,
        idempotency_key,
        correlation_id,
        source_channel,
    ) = _common_identifiers(
        organization_id=organization_id,
        edition_id=edition_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    item_id = require_uuid(item_id, field="item_id")
    operation = ProgrammeCommandOperation.READINESS_CONFIGURE.value
    _preauthorize(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_READINESS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )
    concern = normalized_closed_code(
        concern,
        field="concern",
        enum_type=ProgrammeReadinessConcern,
    )
    disposition = normalized_closed_code(
        disposition,
        field="disposition",
        enum_type=ProgrammeReadinessDisposition,
    )
    expected_version = require_expected_version(expected_version)
    reason = normalized_reason(reason)
    request_digest = canonical_digest(
        {
            "operation": operation,
            "item_id": item_id,
            "concern": concern.value,
            "disposition": disposition.value,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    occurred_at = now or timezone.now()

    def mutate() -> ProgrammeCommandResult:
        with transaction.atomic(), programme_writer():
            scope = _postauthorize(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=PROGRAMME_MANAGE_READINESS,
                authorizer=authorizer,
            )
            replay = _replay(
                actor_id=scope.actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay
            _ensure_editable(scope)
            control = _locked_control(
                organization_id=organization_id,
                edition_id=edition_id,
                required=True,
            )
            item = _locked_item(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id=item_id,
            )
            _require_version(actual=item.aggregate_version, expected=expected_version)
            requirement = (
                ProgrammeReadinessRequirement.objects.select_for_update()
                .filter(item=item, concern=concern.value)
                .first()
            )
            initial_dependency_version = (
                _initial_readiness_dependency_version(item=item, concern=concern)
                if requirement is None
                else requirement.dependency_version
            )
            resulting_version = item.aggregate_version + 1
            _advance_item(item, actor_id=scope.actor_id)
            if requirement is None:
                requirement = ProgrammeReadinessRequirement.objects.create(
                    item=item,
                    organization_id=scope.organization_id,
                    edition_id=scope.edition_id,
                    concern=concern.value,
                    disposition=disposition.value,
                    requirement_version=1,
                    dependency_version=initial_dependency_version,
                    item_version=resulting_version,
                    last_modified_by_id=scope.actor_id,
                )
                revision_sequence = 1
            else:
                requirement.requirement_version += 1
                requirement.disposition = disposition.value
                requirement.item_version = resulting_version
                requirement.last_modified_by_id = scope.actor_id
                requirement.save(
                    update_fields=(
                        "requirement_version",
                        "disposition",
                        "item_version",
                        "last_modified_by",
                        "updated_at",
                    )
                )
                revision_sequence = (
                    ProgrammeReadinessRequirementRevision.objects.select_for_update()
                    .filter(requirement=requirement)
                    .aggregate(value=Max("sequence"))["value"]
                    or 0
                ) + 1
            revision = ProgrammeReadinessRequirementRevision.objects.create(
                requirement=requirement,
                item=item,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                sequence=revision_sequence,
                item_version=resulting_version,
                disposition=disposition.value,
                actor_id=scope.actor_id,
                reason=reason,
                occurred_at=occurred_at,
            )
            return _record_success(
                scope=scope,
                control=control,
                item=item,
                operation=ProgrammeCommandOperation.READINESS_CONFIGURE,
                event_action="configure_readiness",
                capability_code=PROGRAMME_MANAGE_READINESS,
                reason=reason,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
                result_object_id=revision.id,
                expected_version=expected_version,
                resulting_item_version=resulting_version,
                resulting_control_version=None,
                changed_fields=("readiness_summary", "readiness_history"),
                concern=concern.value,
                occurred_at=occurred_at,
            )

    return _run_denial_safe(
        action=mutate,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_READINESS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def _validate_evidence_source(
    *,
    item: ProgrammeItem,
    requirement: ProgrammeReadinessRequirement,
    concern: ProgrammeReadinessConcern,
    source_code: str,
    source_object_id: UUID | None,
    source_version: int | None,
) -> None:
    definition = PROGRAMME_EVIDENCE_SOURCE_DEFINITIONS[source_code]
    if concern.value not in PROGRAMME_EVIDENCE_SOURCE_ALLOWED_CONCERNS[source_code]:
        raise ValidationError(
            "This evidence source does not support the readiness concern.",
            code="programme_evidence_source_concern_invalid",
        )
    if not definition.requires_object:
        if source_object_id is not None or source_version is not None:
            raise ValidationError(
                "Operator attestation cannot carry an external identity.",
                code="programme_evidence_identity_forbidden",
            )
        return
    if source_object_id is None or source_version is None:
        raise ValidationError(
            "This evidence source requires a typed object and version.",
            code="programme_evidence_source_shape_invalid",
        )
    source_dependency_version: int | None = None
    if source_code == "programme.evidence.working-revision@1":
        working_source = (
            ProgrammeWorkingRevision.objects.filter(
                id=source_object_id,
                item=item,
                organization_id=item.organization_id,
                edition_id=item.edition_id,
                sequence=source_version,
            )
            .only("item_version")
            .first()
        )
        source_dependency_version = (
            working_source.item_version if working_source is not None else None
        )
    elif source_code == "programme.evidence.delivery-revision@1":
        delivery_source = (
            ProgrammeDeliveryRevision.objects.filter(
                id=source_object_id,
                item=item,
                organization_id=item.organization_id,
                edition_id=item.edition_id,
                sequence=source_version,
            )
            .only("item_version")
            .first()
        )
        source_dependency_version = (
            delivery_source.item_version if delivery_source is not None else None
        )
    elif source_code == "programme.evidence.public-rendition@1":
        public_source = (
            ProgrammePublicRendition.objects.filter(
                id=source_object_id,
                item=item,
                organization_id=item.organization_id,
                edition_id=item.edition_id,
                rendition_number=source_version,
            )
            .only("source_item_version")
            .first()
        )
        source_dependency_version = (
            public_source.source_item_version if public_source is not None else None
        )
    if source_dependency_version is None:
        raise ProgrammeUnavailableError
    if source_dependency_version != requirement.dependency_version:
        raise ProgrammeVersionConflictError


@_audit_command_errors(
    capability_code=PROGRAMME_MANAGE_READINESS,
    operation=ProgrammeCommandOperation.READINESS_RECORD.value,
)
def record_programme_readiness_evidence(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    concern: str | ProgrammeReadinessConcern,
    state: str | ProgrammeReadinessEvidenceState,
    evidence_note: str = "",
    source_code: str = PROGRAMME_OPERATOR_ATTESTATION_SOURCE,
    source_object_id: UUID | None = None,
    source_version: int | None = None,
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeCommandResult:
    """Append version-bound evidence for one configured readiness concern.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact private-planning edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    concern : str | ProgrammeReadinessConcern
        The closed configured readiness concern.
    state : str | ProgrammeReadinessEvidenceState
        The closed evidence state.
    evidence_note : str, default=""
        Optional bounded private evidence note.
    source_code : str, default=PROGRAMME_OPERATOR_ATTESTATION_SOURCE
        The closed typed evidence-source code.
    source_object_id : UUID | None, default=None
        Optional exact typed source identifier.
    source_version : int | None, default=None
        Optional source-owned sequence or rendition number.
    expected_version : int
        The exact current item version.
    reason : str
        The retained human rationale.
    idempotency_key : UUID
        The caller-generated retry key.
    correlation_id : UUID
        The trace identifier shared by success evidence.
    source_channel : str
        The normalized calling channel.
    now : datetime | None, default=None
        Optional authoritative timestamp for deterministic execution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Immutable receipt and resulting readiness-evidence identifier.

    Raises
    ------
    ValidationError
        If the evidence source code is not registered.
    """
    (
        organization_id,
        edition_id,
        idempotency_key,
        correlation_id,
        source_channel,
    ) = _common_identifiers(
        organization_id=organization_id,
        edition_id=edition_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    item_id = require_uuid(item_id, field="item_id")
    operation = ProgrammeCommandOperation.READINESS_RECORD.value
    _preauthorize(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_READINESS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
        authorizer=authorizer,
    )
    concern = normalized_closed_code(
        concern,
        field="concern",
        enum_type=ProgrammeReadinessConcern,
    )
    state = normalized_closed_code(
        state,
        field="state",
        enum_type=ProgrammeReadinessEvidenceState,
    )
    if source_code not in PROGRAMME_EVIDENCE_SOURCE_DEFINITIONS:
        raise ValidationError(
            {
                "source_code": ValidationError(
                    "Choose a registered Programme evidence source.",
                    code="programme_closed_value_invalid",
                )
            },
        )
    if source_object_id is not None:
        source_object_id = require_uuid(source_object_id, field="source_object_id")
    if source_version is not None:
        source_version = require_positive_version(
            source_version,
            field="source_version",
        )
    evidence_note = normalized_text(
        evidence_note,
        field="evidence_note",
        maximum=MAX_PROGRAMME_EVIDENCE_NOTE_LENGTH,
    )
    expected_version = require_expected_version(expected_version)
    reason = normalized_reason(reason)
    request_digest = canonical_digest(
        {
            "operation": operation,
            "item_id": item_id,
            "concern": concern.value,
            "state": state.value,
            "evidence_note": evidence_note,
            "source_code": source_code,
            "source_object_id": source_object_id,
            "source_version": source_version,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    occurred_at = now or timezone.now()

    def mutate() -> ProgrammeCommandResult:
        with transaction.atomic(), programme_writer():
            scope = _postauthorize(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=PROGRAMME_MANAGE_READINESS,
                authorizer=authorizer,
            )
            replay = _replay(
                actor_id=scope.actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay
            _ensure_editable(scope)
            control = _locked_control(
                organization_id=organization_id,
                edition_id=edition_id,
                required=True,
            )
            item = _locked_item(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id=item_id,
            )
            _require_version(actual=item.aggregate_version, expected=expected_version)
            requirement = (
                ProgrammeReadinessRequirement.objects.select_for_update()
                .filter(item=item, concern=concern.value)
                .first()
            )
            if requirement is None:
                raise ProgrammeUnavailableError
            _validate_evidence_source(
                item=item,
                requirement=requirement,
                concern=concern,
                source_code=source_code,
                source_object_id=source_object_id,
                source_version=source_version,
            )
            latest_sequence = (
                ProgrammeReadinessEvidence.objects.select_for_update()
                .filter(requirement=requirement)
                .aggregate(value=Max("sequence"))["value"]
                or 0
            )
            if latest_sequence >= MAX_PROGRAMME_READINESS_EVIDENCE:
                raise ProgrammeLimitConflictError
            resulting_version = item.aggregate_version + 1
            _advance_item(item, actor_id=scope.actor_id)
            evidence = ProgrammeReadinessEvidence.objects.create(
                requirement=requirement,
                item=item,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                sequence=latest_sequence + 1,
                item_version=resulting_version,
                requirement_version=requirement.requirement_version,
                dependency_version=requirement.dependency_version,
                state=state.value,
                source_code=source_code,
                source_object_id=source_object_id,
                source_version=source_version,
                evidence_note=evidence_note,
                actor_id=scope.actor_id,
                reason=reason,
                occurred_at=occurred_at,
            )
            return _record_success(
                scope=scope,
                control=control,
                item=item,
                operation=ProgrammeCommandOperation.READINESS_RECORD,
                event_action="record_readiness",
                capability_code=PROGRAMME_MANAGE_READINESS,
                reason=reason,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
                result_object_id=evidence.id,
                expected_version=expected_version,
                resulting_item_version=resulting_version,
                resulting_control_version=None,
                changed_fields=("readiness_summary", "readiness_history"),
                concern=concern.value,
                occurred_at=occurred_at,
            )

    return _run_denial_safe(
        action=mutate,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=PROGRAMME_MANAGE_READINESS,
        operation=operation,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


@_audit_command_errors(
    capability_code=PROGRAMME_APPROVE_PUBLIC_COPY,
    operation=ProgrammeCommandOperation.PUBLIC_RENDITION_RECORD.value,
)
def approve_programme_public_rendition(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    source_working_revision_id: UUID,
    public_title: str,
    public_summary: str = "",
    public_content_note: str = "",
    expected_version: int,
    reason: str,
    idempotency_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeCommandResult:
    """Approve one immutable public-copy rendition without publishing it.

    Parameters
    ----------
    actor_id : UUID
        The exact active, verified account identifier.
    organization_id : UUID
        The organization expected to own the edition.
    edition_id : UUID
        The exact private-planning edition identifier.
    item_id : UUID
        The exact Programme item identifier.
    source_working_revision_id : UUID
        The latest private working revision reviewed for this rendition.
    public_title : str
        The bounded approved public title.
    public_summary : str, default=""
        Optional approved public summary.
    public_content_note : str, default=""
        Optional approved public content note.
    expected_version : int
        The unchanged exact current item version.
    reason : str
        The retained review rationale.
    idempotency_key : UUID
        The caller-generated retry key.
    correlation_id : UUID
        The trace identifier shared by success evidence.
    source_channel : str
        The normalized calling channel.
    now : datetime | None, default=None
        Optional authoritative timestamp for deterministic execution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        The complete policy-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Immutable receipt and approved rendition identifier.
    """
    (
        organization_id,
        edition_id,
        idempotency_key,
        correlation_id,
        source_channel,
    ) = _common_identifiers(
        organization_id=organization_id,
        edition_id=edition_id,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    item_id = require_uuid(item_id, field="item_id")
    source_working_revision_id = require_uuid(
        source_working_revision_id,
        field="source_working_revision_id",
    )
    operation = ProgrammeCommandOperation.PUBLIC_RENDITION_RECORD.value
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
    public_title = normalized_text(
        public_title,
        field="public_title",
        maximum=MAX_PROGRAMME_TITLE_LENGTH,
        required=True,
        collapse=True,
    )
    public_summary = normalized_text(
        public_summary,
        field="public_summary",
        maximum=MAX_PROGRAMME_SUMMARY_LENGTH,
    )
    public_content_note = normalized_text(
        public_content_note,
        field="public_content_note",
        maximum=MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH,
    )
    expected_version = require_expected_version(expected_version)
    reason = normalized_reason(reason)
    request_digest = canonical_digest(
        {
            "operation": operation,
            "item_id": item_id,
            "source_working_revision_id": source_working_revision_id,
            "public_title": public_title,
            "public_summary": public_summary,
            "public_content_note": public_content_note,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    occurred_at = now or timezone.now()

    def mutate() -> ProgrammeCommandResult:
        with transaction.atomic(), programme_writer():
            scope = _postauthorize(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                capability_code=PROGRAMME_APPROVE_PUBLIC_COPY,
                authorizer=authorizer,
            )
            replay = _replay(
                actor_id=scope.actor_id,
                edition_id=edition_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if replay is not None:
                return replay
            _ensure_editable(scope)
            control = _locked_control(
                organization_id=organization_id,
                edition_id=edition_id,
                required=True,
            )
            item = _locked_item(
                organization_id=organization_id,
                edition_id=edition_id,
                item_id=item_id,
            )
            _require_version(actual=item.aggregate_version, expected=expected_version)
            source = (
                ProgrammeWorkingRevision.objects.select_for_update()
                .filter(
                    id=source_working_revision_id,
                    item=item,
                    organization_id=organization_id,
                    edition_id=edition_id,
                )
                .first()
            )
            latest_source = (
                ProgrammeWorkingRevision.objects.filter(item=item)
                .order_by("-sequence", "-id")
                .first()
            )
            if source is None or latest_source is None or source.id != latest_source.id:
                raise ProgrammeUnavailableError
            previous = (
                ProgrammePublicRendition.objects.select_for_update()
                .filter(item=item)
                .order_by("-rendition_number", "-id")
                .first()
            )
            rendition_number = previous.rendition_number + 1 if previous else 1
            if rendition_number > MAX_PROGRAMME_PUBLIC_RENDITIONS:
                raise ProgrammeLimitConflictError
            resulting_version = item.aggregate_version
            rendition = ProgrammePublicRendition.objects.create(
                item=item,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                rendition_number=rendition_number,
                source_item_version=source.item_version,
                source_working_revision=source,
                supersedes=previous,
                public_title=public_title,
                public_summary=public_summary,
                public_content_note=public_content_note,
                reviewed_by_id=scope.actor_id,
                reviewed_at=occurred_at,
                review_reason=reason,
            )
            return _record_success(
                scope=scope,
                control=control,
                item=item,
                operation=ProgrammeCommandOperation.PUBLIC_RENDITION_RECORD,
                event_action="approve_public_copy",
                capability_code=PROGRAMME_APPROVE_PUBLIC_COPY,
                reason=reason,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                correlation_id=correlation_id,
                source_channel=source_channel,
                result_object_id=rendition.id,
                expected_version=expected_version,
                resulting_item_version=resulting_version,
                resulting_control_version=None,
                changed_fields=("latest_public_rendition",),
                concern=ProgrammeReadinessConcern.PUBLIC_COPY.value,
                occurred_at=occurred_at,
                event_aggregate_type="programme.public_rendition",
                event_aggregate_id=item.id,
                event_aggregate_version=rendition.rendition_number,
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


__all__ = [
    "ProgrammeCommandError",
    "ProgrammeCommandResult",
    "ProgrammeIdempotencyConflictError",
    "ProgrammeLifecycleConflictError",
    "ProgrammeLimitConflictError",
    "ProgrammeUnavailableError",
    "ProgrammeVersionConflictError",
    "append_programme_discussion",
    "approve_programme_public_rendition",
    "configure_programme_readiness",
    "create_organizer_core_item",
    "record_programme_readiness_evidence",
    "revise_programme_delivery",
    "revise_programme_working",
]
