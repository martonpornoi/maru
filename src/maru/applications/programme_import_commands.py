"""Preview-first orchestration for dormant Programme call and proposal imports."""

from __future__ import annotations

import hashlib
import hmac
import re
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict, dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, Final, Protocol, cast
from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Max, Q
from django.utils import timezone

from maru.applications.answer_values import condition_matches, normalize_answer_value
from maru.applications.models import (
    ApplicationCommandReceipt,
    ApplicationDefinition,
    ApplicationDefinitionStatus,
    ApplicationQuestion,
    ProgrammeCall,
    ProgrammeCallFormat,
    ProgrammeCallTrack,
    ProgrammeCommandAction,
    ProgrammeCommandReceipt,
    ProgrammeImportAggregateKind,
    ProgrammeImportAppliedCommand,
    ProgrammeImportBatch,
    ProgrammeImportBatchState,
    ProgrammeImportCommandAction,
    ProgrammeImportCommandReceipt,
    ProgrammeImportCommandResultKind,
    ProgrammeImportDependencyState,
    ProgrammeImportItem,
    ProgrammeImportItemKind,
    ProgrammeImportItemState,
    ProgrammeImportPreviewAction,
    ProgrammeImportPreviewItemResult,
    ProgrammeImportPreviewRevision,
    ProgrammeImportPreviewStatus,
    ProgrammeImportSourceBinding,
    ProgrammeProposal,
)
from maru.applications.programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    ApplicationsProgrammeAuthorizer,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeCommandError,
    append_programme_proposal_answer,
    create_programme_call,
    start_programme_proposal,
)
from maru.applications.programme_import_authorization import (
    APPLICATIONS_DISPOSE_PROGRAMME_IMPORT,
    APPLICATIONS_IMPORT_PROGRAMME,
    DEFAULT_APPLICATIONS_PROGRAMME_IMPORT_AUTHORIZER,
    ApplicationsProgrammeImportAuthorizationDeniedError,
    ApplicationsProgrammeImportAuthorizer,
    AuthorizedProgrammeImportScope,
    authorize_programme_import_department_scope,
    authorize_programme_import_disposal_scope,
    authorize_programme_import_retry_scope,
    authorize_programme_import_self_scope,
    require_current_programme_import_owner,
)
from maru.applications.programme_import_events import (
    APPLICATIONS_PROGRAMME_IMPORT_CHANGED_EVENT,
    APPLICATIONS_PROGRAMME_IMPORT_EVENT_SCHEMA_VERSION,
    programme_import_changed_payload,
)
from maru.applications.programme_import_inputs import (
    ParsedProgrammeImportDocument,
    ProgrammeImportCallItemInput,
    ProgrammeImportInputError,
    ProgrammeImportItemInput,
    ProgrammeImportProposalItemInput,
    parse_programme_import_document,
    parse_programme_import_item_payload,
)
from maru.applications.programme_import_retention import (
    DEFAULT_PROGRAMME_IMPORT_RETENTION_POLICY_PROVIDER,
    ProgrammeImportRetentionPolicyProvider,
)
from maru.applications.programme_import_writer_boundary import (
    programme_import_database_writer,
)
from maru.applications.programme_inputs import (
    ProgrammeProposalContributorProfileInput,
    ProgrammeProposalSelectionInput,
    canonical_programme_digest,
    normalized_programme_text,
    require_programme_expected_version,
    require_programme_uuid,
)
from maru.applications.programme_write_scope import (
    ApplicationsProgrammeWriteScopeUnavailableError,
    lock_programme_edition_write_scope,
)
from maru.applications.retry_namespace import lock_applications_retry_namespace
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.queries import resolve_active_verified_person_reference_by_email

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime


_SOURCE_SYSTEM = re.compile(r"^[a-z][a-z0-9_.:-]{0,79}$", flags=re.ASCII)
_SOURCE_CHANNEL = re.compile(r"^[a-z][a-z0-9_-]{0,31}$", flags=re.ASCII)
_MAX_SOURCE_CHANNEL_LENGTH: Final = 32
_NESTED_RETRY_PREFIX: Final = "maru:applications:programme-import:nested:v1"
_CLAIM_FIELDS: Final = frozenset({"programme_import_claim"})
_IMPORT_AUTHZ: Final = DEFAULT_APPLICATIONS_PROGRAMME_IMPORT_AUTHORIZER
_PROGRAMME_AUTHZ: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_RP: Final = (  # Short alias keeps the exact default readable in API docs.
    DEFAULT_PROGRAMME_IMPORT_RETENTION_POLICY_PROVIDER
)


class ApplicationsProgrammeImportCommandError(RuntimeError):
    """Base class for non-disclosing Programme import command failures."""

    reason_code = "applications_programme_import_error"


class ApplicationsProgrammeImportUnavailableError(
    ApplicationsProgrammeImportCommandError
):
    """Signal an absent, foreign, expired, or otherwise unavailable aggregate."""

    reason_code = "applications_programme_import_unavailable"


class ApplicationsProgrammeImportStateConflictError(
    ApplicationsProgrammeImportCommandError
):
    """Signal a valid import aggregate in a state that rejects the operation."""

    reason_code = "applications_programme_import_state_conflict"


class ApplicationsProgrammeImportVersionConflictError(
    ApplicationsProgrammeImportCommandError
):
    """Signal a stale batch, preview, or item cursor."""

    reason_code = "applications_programme_import_version_conflict"


class ApplicationsProgrammeImportIdempotencyConflictError(
    ApplicationsProgrammeImportCommandError
):
    """Signal reuse of a shared retry key for a different normalized intent."""

    reason_code = "applications_programme_import_idempotency_conflict"


class ApplicationsProgrammeImportPreviewStaleError(
    ApplicationsProgrammeImportCommandError
):
    """Signal that an organizer preview no longer describes the current item."""

    reason_code = "applications_programme_import_preview_stale"


class ApplicationsProgrammeImportClaimUnavailableError(
    ApplicationsProgrammeImportCommandError
):
    """Collapse every identity, dependency, or self-claim mismatch."""

    reason_code = "applications_programme_import_claim_unavailable"


class ApplicationsProgrammeImportOperationFailedError(
    ApplicationsProgrammeImportCommandError
):
    """Collapse every nested command or import-evidence write failure."""

    reason_code = "applications_programme_import_operation_failed"

    def __init__(self, *, correlation_id: UUID) -> None:
        """Retain only the safe request correlation for support.

        Parameters
        ----------
        correlation_id : UUID
            Validated caller correlation, or a generated safe fallback when the
            caller supplied no valid UUID.
        """
        self.correlation_id = correlation_id
        super().__init__(self.reason_code)


class _ApplicationsProgrammeImportEvidenceError(RuntimeError):
    """Hide corrupt or incompatible private persistence evidence."""


class _ProgrammeImportServiceDecorator(Protocol):
    """Preserve any Programme-import service signature during failure audit."""

    def __call__[**ParametersT, ResultT](
        self,
        service: Callable[ParametersT, ResultT],
    ) -> Callable[ParametersT, ResultT]: ...


@dataclass(frozen=True, slots=True)
class ProgrammeImportCommandResult:
    """Return only opaque outcome identifiers and the resulting cursor.

    Attributes
    ----------
    receipt_id : UUID
        Immutable receipt identifier for the requested import command.
    action : str
        Stable action recorded by the command receipt.
    batch_id : UUID
        Opaque identifier of the affected import batch.
    item_id : UUID | None
        Opaque affected item identifier for item-scoped commands.
    preview_revision_id : UUID | None
        Opaque preview revision consumed or produced by the command.
    result_kind : str
        Stable category describing the command result.
    resulting_version : int
        Optimistic concurrency cursor after the command completes.
    replayed : bool
        Whether the result was replayed from an existing receipt.
    """

    receipt_id: UUID
    action: str
    batch_id: UUID
    item_id: UUID | None
    preview_revision_id: UUID | None
    result_kind: str
    resulting_version: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class ProgrammeImportPreviewItem:
    """Expose one sanitized organizer preview result.

    Attributes
    ----------
    result_id : UUID
        Opaque identifier of the immutable preview result.
    item_id : UUID
        Opaque identifier of the staged import item.
    item_version : int
        Item concurrency cursor evaluated by the preview.
    kind : str
        Stable call-or-proposal item discriminator.
    status : str
        Sanitized preview evaluation status.
    action : str
        Sanitized action available for the item.
    dependency_state : str
        Sanitized state of the item's required dependency.
    safe_field_keys : tuple[str, ...]
        Fixed field keys that may be disclosed in organizer preview.
    reason_codes : tuple[str, ...]
        Stable, value-free reasons produced by preview evaluation.
    """

    result_id: UUID
    item_id: UUID
    item_version: int
    kind: str
    status: str
    action: str
    dependency_state: str
    safe_field_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeImportBatchPreview:
    """Return one immutable organizer preview without private source values.

    Attributes
    ----------
    receipt_id : UUID
        Immutable receipt identifier for the preview request.
    batch_id : UUID
        Opaque identifier of the previewed import batch.
    revision_id : UUID
        Opaque identifier of the immutable preview revision.
    revision_number : int
        Monotonic revision number within the import batch.
    items : tuple[ProgrammeImportPreviewItem, ...]
        Sanitized per-item preview results in source order.
    replayed : bool
        Whether the preview was replayed from an existing receipt.
    """

    receipt_id: UUID
    batch_id: UUID
    revision_id: UUID
    revision_number: int
    items: tuple[ProgrammeImportPreviewItem, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class ProgrammeImportProposalClaimAnswer:
    """Return one exact imported answer only to its transiently matched lead.

    Attributes
    ----------
    question_key : str
        Normalized key of the call question answered by the proposal.
    field_type : str
        Stable question field type used to interpret the answer value.
    value : object
        Normalized imported answer value authorized for exact-self disclosure.
    """

    question_key: str
    field_type: str
    value: object


@dataclass(frozen=True, slots=True)
class ProgrammeImportProposalClaimPreview:
    """Return the exact proposal values an authorized lead may claim.

    Attributes
    ----------
    item_id : UUID
        Opaque identifier of the staged proposal item.
    item_version : int
        Proposal item concurrency cursor evaluated by the preview.
    track_code : str
        Normalized track selected by the imported proposal.
    format_code : str
        Normalized format selected by the imported proposal.
    requested_duration_minutes : int
        Requested session duration in whole minutes.
    answers : tuple[ProgrammeImportProposalClaimAnswer, ...]
        Exact normalized answers authorized for the matched lead.
    adoption_digest : str
        Deterministic digest binding a later claim to this exact preview.
    """

    item_id: UUID
    item_version: int
    track_code: str
    format_code: str
    requested_duration_minutes: int
    answers: tuple[ProgrammeImportProposalClaimAnswer, ...]
    adoption_digest: str


@dataclass(frozen=True, slots=True)
class _AccountIdentifier:
    id: UUID


@dataclass(frozen=True, slots=True)
class _ResolvedProposal:
    call: ProgrammeCall
    selection: ProgrammeProposalSelectionInput
    answers: tuple[tuple[ApplicationQuestion, object], ...]


@dataclass(frozen=True, slots=True)
class _PreviewEvaluation:
    item: ProgrammeImportItem
    parsed: ProgrammeImportItemInput | None
    status: str
    action: str
    dependency_state: str
    dependency_digest: str
    dependency_version: int | None
    safe_field_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]
    result_digest: str


def _safe_audit_uuid(value: object) -> UUID | None:
    return value if isinstance(value, UUID) else None


def _safe_audit_source_channel(value: object) -> str:
    if (
        isinstance(value, str)
        and len(value) <= _MAX_SOURCE_CHANNEL_LENGTH
        and _SOURCE_CHANNEL.fullmatch(value) is not None
    ):
        return value
    return "service"


def _caused_by_authorization_denial(error: Exception) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(
            current,
            (
                ApplicationsProgrammeImportAuthorizationDeniedError,
                ApplicationsProgrammeAuthorizationDeniedError,
            ),
        ):
            return True
        current = current.__cause__ or current.__context__
    return isinstance(error, ApplicationsProgrammeImportClaimUnavailableError)


def _failure_reason_code(error: Exception) -> str:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ApplicationsProgrammeImportAuthorizationDeniedError):
            return current.reason_code
        if isinstance(current, ApplicationsProgrammeAuthorizationDeniedError):
            return current.reason_code
        current = current.__cause__ or current.__context__
    if isinstance(error, ProgrammeImportInputError):
        return error.code
    if isinstance(
        error,
        (ApplicationsProgrammeImportCommandError, ApplicationsProgrammeCommandError),
    ):
        return error.reason_code
    if isinstance(error, ValidationError):
        return "applications_programme_import_input_invalid"
    return "applications_programme_import_dependency_error"


def _append_failure_audit_best_effort(
    *,
    error: Exception,
    actor_id: object,
    organization_id: object,
    edition_id: object,
    capability_code: str,
    operation: str,
    correlation_id: object,
    source_channel: object,
) -> UUID:
    correlation = _safe_audit_uuid(correlation_id) or uuid4()
    with suppress(Exception):
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=_safe_audit_uuid(actor_id),
                principal_context_id=None,
                organization_id=_safe_audit_uuid(organization_id),
                event_edition_id=_safe_audit_uuid(edition_id),
                capability_code=capability_code,
                operation=f"applications.programme_import.{operation}",
                target_type="applications.programme_import.scope",
                target_id=None,
                outcome=("deny" if _caused_by_authorization_denial(error) else "error"),
                reason_code=_failure_reason_code(error),
                correlation_id=correlation,
                request_id=correlation,
                source_channel=_safe_audit_source_channel(source_channel),
                obligations=("audit",),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="applications-programme-import-restricted",
            )
        )
    return correlation


def _audit_import_errors(
    *,
    capability_code: str,
    operation: str,
) -> _ProgrammeImportServiceDecorator:
    """Audit minimized service failures after their atomic work rolls back.

    Parameters
    ----------
    capability_code : str
        Capability attempted by the protected import operation.
    operation : str
        Stable command or query suffix used by audit evidence.

    Returns
    -------
    _ProgrammeImportServiceDecorator
        Decorator preserving the wrapped service signature and result type.
    """

    def decorate[**ParametersT, ResultT](
        service: Callable[ParametersT, ResultT],
    ) -> Callable[ParametersT, ResultT]:
        @wraps(service)
        def wrapped(
            *args: ParametersT.args,
            **kwargs: ParametersT.kwargs,
        ) -> ResultT:
            failure_correlation: UUID | None = None
            try:
                return service(*args, **kwargs)
            except Exception as error:
                correlation = _append_failure_audit_best_effort(
                    error=error,
                    actor_id=kwargs.get("actor_id"),
                    organization_id=kwargs.get("organization_id"),
                    edition_id=kwargs.get("edition_id"),
                    capability_code=capability_code,
                    operation=operation,
                    correlation_id=kwargs.get("correlation_id"),
                    source_channel=kwargs.get("source_channel"),
                )
                if not isinstance(
                    error,
                    (
                        ProgrammeImportInputError,
                        ApplicationsProgrammeImportCommandError,
                        ApplicationsProgrammeImportAuthorizationDeniedError,
                    ),
                ):
                    failure_correlation = correlation
                else:
                    raise
            raise ApplicationsProgrammeImportOperationFailedError(
                correlation_id=failure_correlation,
            ) from None

        return wrapped

    return decorate


def _effective_now(value: datetime | None) -> datetime:
    if value is not None:
        database_name = connection.settings_dict.get("NAME")
        if (
            not getattr(
                settings,
                "MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_CLOCK",
                False,
            )
            or not isinstance(database_name, str)
            or not database_name.startswith("test_")
        ):
            raise ApplicationsProgrammeImportAuthorizationDeniedError
    effective = value or timezone.now()
    if timezone.is_naive(effective):
        raise ValidationError(
            "Use a timezone-aware import command time.",
            code="applications_programme_import_datetime_invalid",
        )
    return effective


def _require_retention_policy_provider(
    provider: ProgrammeImportRetentionPolicyProvider,
) -> None:
    """Reject runtime retention substitution outside an isolated test database.

    Parameters
    ----------
    provider : ProgrammeImportRetentionPolicyProvider
        Runtime provider requested by the staging caller.

    Raises
    ------
    ApplicationsProgrammeImportAuthorizationDeniedError
        If a nondefault provider is requested without both test guards.
    """
    if provider is DEFAULT_PROGRAMME_IMPORT_RETENTION_POLICY_PROVIDER:
        return
    database_name = connection.settings_dict.get("NAME")
    if (
        not getattr(
            settings,
            "MARU_ALLOW_APPLICATIONS_PROGRAMME_IMPORT_TEST_RETENTION_PROVIDER",
            False,
        )
        or not isinstance(database_name, str)
        or not database_name.startswith("test_")
    ):
        raise ApplicationsProgrammeImportAuthorizationDeniedError


def _normalize_source_system(value: str) -> str:
    normalized = normalized_programme_text(
        value,
        field="source_system",
        maximum=80,
        required=True,
    ).lower()
    if _SOURCE_SYSTEM.fullmatch(normalized) is None:
        raise ValidationError(
            "Use a registered lower-case source system.",
            code="applications_programme_import_source_invalid",
        )
    return normalized


def _normalize_source_channel(value: str) -> str:
    normalized = normalized_programme_text(
        value,
        field="source_channel",
        maximum=32,
        required=True,
    )
    if _SOURCE_CHANNEL.fullmatch(normalized) is None:
        raise ValidationError(
            "Use a registered lower-case source channel.",
            code="applications_programme_import_source_channel_invalid",
        )
    return normalized


def _normalize_reason(value: str) -> str:
    return normalized_programme_text(
        value,
        field="reason",
        maximum=500,
        required=True,
        collapse=True,
    )


def _request_digest(
    *,
    action: str,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    expected_version: int,
    reason: str,
    source_channel: str,
    values: dict[str, object],
) -> str:
    return canonical_programme_digest(
        {
            "action": action,
            "actor_id": actor_id,
            "organization_id": organization_id,
            "edition_id": edition_id,
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
            "values": values,
        }
    )


def _nested_retry_key(
    *,
    outer_retry_key: UUID,
    item_id: UUID,
    sequence: int,
    action: str,
) -> UUID:
    name = ":".join(
        (
            _NESTED_RETRY_PREFIX,
            str(outer_retry_key).lower(),
            str(item_id).lower(),
            str(sequence),
            action,
        )
    )
    return UUID(hashlib.md5(name.encode("ascii"), usedforsecurity=False).hexdigest())


def _lock_nested_retry_key(
    *,
    actor_id: UUID,
    edition_id: UUID,
    outer_retry_key: UUID,
    item_id: UUID,
    sequence: int,
    action: str,
) -> UUID:
    retry_key = _nested_retry_key(
        outer_retry_key=outer_retry_key,
        item_id=item_id,
        sequence=sequence,
        action=action,
    )
    lock_applications_retry_namespace(
        edition_id=edition_id,
        actor_id=actor_id,
        retry_key=retry_key,
    )
    return retry_key


def _source_lock(
    *,
    organization_id: UUID,
    edition_id: UUID,
    source_system: str,
    kind: str,
    source_key: str,
) -> None:
    namespace = ":".join(
        (
            "maru",
            "applications",
            "programme-import-source",
            str(organization_id).lower(),
            str(edition_id).lower(),
            source_system,
            kind,
            source_key,
        )
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock("
            "pg_catalog.hashtextextended(%s, 0))",
            [namespace],
        )


def _command_result(
    receipt: ProgrammeImportCommandReceipt,
    *,
    replayed: bool,
) -> ProgrammeImportCommandResult:
    return ProgrammeImportCommandResult(
        receipt_id=receipt.id,
        action=receipt.action,
        batch_id=receipt.batch_id,
        item_id=receipt.item_id,
        preview_revision_id=receipt.preview_revision_id,
        result_kind=receipt.result_kind,
        resulting_version=receipt.resulting_version,
        replayed=replayed,
    )


def _replay(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    retry_key: UUID,
    request_digest: str,
    authorizer: ApplicationsProgrammeImportAuthorizer,
) -> ProgrammeImportCommandResult | None:
    authorize_programme_import_retry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )
    lock_applications_retry_namespace(
        edition_id=edition_id,
        actor_id=actor_id,
        retry_key=retry_key,
    )
    receipt = (
        ProgrammeImportCommandReceipt.objects.select_for_update()
        .filter(
            edition_id=edition_id,
            actor_id=actor_id,
            retry_key=retry_key,
        )
        .first()
    )
    if receipt is not None:
        if receipt.request_digest != request_digest:
            raise ApplicationsProgrammeImportIdempotencyConflictError
        return _command_result(receipt, replayed=True)
    if (
        ApplicationCommandReceipt.objects.select_for_update()
        .filter(edition_id=edition_id, actor_id=actor_id, retry_key=retry_key)
        .exists()
        or ProgrammeCommandReceipt.objects.select_for_update()
        .filter(edition_id=edition_id, actor_id=actor_id, retry_key=retry_key)
        .exists()
    ):
        raise ApplicationsProgrammeImportIdempotencyConflictError
    return None


def _lock_batch(
    *,
    organization_id: UUID,
    edition_id: UUID,
    batch_id: UUID,
) -> ProgrammeImportBatch:
    batch = (
        ProgrammeImportBatch.objects.select_for_update()
        .filter(
            id=batch_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .first()
    )
    if batch is None:
        raise ApplicationsProgrammeImportUnavailableError
    return batch


def _batch_owner_department_id(
    *,
    organization_id: UUID,
    edition_id: UUID,
    batch_id: UUID,
) -> UUID:
    """Resolve only the candidate owner needed by the canonical lock boundary.

    Parameters
    ----------
    organization_id : UUID
        Organization expected to own the batch.
    edition_id : UUID
        Edition expected to own the batch.
    batch_id : UUID
        Exact candidate batch identifier.

    Returns
    -------
    UUID
        Retained owner Department identifier for lock discovery.

    Raises
    ------
    ApplicationsProgrammeImportUnavailableError
        If the exact retained batch cannot be found.
    """
    owner_department_id = (
        ProgrammeImportBatch.objects.filter(
            id=batch_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .order_by()
        .values_list("owner_department_id", flat=True)
        .first()
    )
    if owner_department_id is None:
        raise ApplicationsProgrammeImportUnavailableError
    return owner_department_id


def _lock_programme_write_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_ids: tuple[UUID, ...],
) -> None:
    """Acquire the retirement-safe Programme lock chain or fail opaquely.

    Parameters
    ----------
    actor_id : UUID
        Exact actor to lock after Departments.
    organization_id : UUID
        Exact organization owning the scope.
    edition_id : UUID
        Exact edition whose Programme state is protected.
    department_ids : tuple[UUID, ...]
        Complete Department set needed by the operation.

    Raises
    ------
    ApplicationsProgrammeImportUnavailableError
        If any exact scope component is absent or incoherent.
    """
    try:
        lock_programme_edition_write_scope(
            organization_id=organization_id,
            edition_id=edition_id,
            department_ids=department_ids,
            actor_id=actor_id,
        )
    except ApplicationsProgrammeWriteScopeUnavailableError as error:
        raise ApplicationsProgrammeImportUnavailableError from error


def _require_staged_batch(
    batch: ProgrammeImportBatch,
    *,
    expected_version: int,
    effective_now: datetime,
    allow_expired: bool = False,
) -> None:
    if batch.aggregate_version != expected_version:
        raise ApplicationsProgrammeImportVersionConflictError
    if batch.state != ProgrammeImportBatchState.STAGED:
        raise ApplicationsProgrammeImportStateConflictError
    if not allow_expired and batch.expires_at <= effective_now:
        raise ApplicationsProgrammeImportUnavailableError


def _binding_for_item(
    *,
    item: ProgrammeImportItem,
    lock: bool = False,
) -> ProgrammeImportSourceBinding | None:
    query = ProgrammeImportSourceBinding.objects.all()
    if lock:
        query = query.select_for_update(of=("self",))
    return (
        query.filter(
            organization_id=item.organization_id,
            edition_id=item.edition_id,
            source_system=item.batch.source_system,
            kind=item.kind,
            source_key=item.source_key,
        )
        .select_related("call__definition", "proposal__submission")
        .first()
    )


def _record_success(
    *,
    scope: AuthorizedProgrammeImportScope,
    action: str,
    aggregate_kind: str,
    result_kind: str,
    batch: ProgrammeImportBatch,
    expected_version: int,
    resulting_version: int,
    request_digest: str,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    changed_fields: tuple[str, ...],
    occurred_at: datetime,
    item: ProgrammeImportItem | None = None,
    preview_revision: ProgrammeImportPreviewRevision | None = None,
    preview_item_result: ProgrammeImportPreviewItemResult | None = None,
    source_binding: ProgrammeImportSourceBinding | None = None,
    adopted_preview_digest: str = "",
    applied_command_count: int = 0,
    source_department_id: UUID | None = None,
    destination_department_id: UUID | None = None,
) -> tuple[ProgrammeImportCommandResult, ProgrammeImportCommandReceipt]:
    receipt = ProgrammeImportCommandReceipt.objects.create(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        actor_id=scope.actor_id,
        aggregate_kind=aggregate_kind,
        action=action,
        retry_key=retry_key,
        request_digest=request_digest,
        reason=reason,
        correlation_id=correlation_id,
        source_channel=source_channel,
        batch=batch,
        item=item,
        preview_revision=preview_revision,
        preview_item_result=preview_item_result,
        source_binding=source_binding,
        source_department_id=source_department_id,
        destination_department_id=destination_department_id,
        adopted_preview_digest=adopted_preview_digest,
        result_kind=result_kind,
        expected_version=expected_version,
        resulting_version=resulting_version,
        applied_command_count=applied_command_count,
    )
    capability_code = APPLICATIONS_IMPORT_PROGRAMME
    if action == ProgrammeImportCommandAction.PROPOSAL_CLAIMED:
        capability_code = APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF
    elif action == ProgrammeImportCommandAction.BATCH_DISCARDED:
        capability_code = APPLICATIONS_DISPOSE_PROGRAMME_IMPORT
    target_id = item.id if item is not None else batch.id
    target_type = (
        "applications.programme_import_item"
        if item is not None
        else "applications.programme_import_batch"
    )
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=capability_code,
            operation=f"applications.programme_import.command.{action}",
            target_type=target_type,
            target_id=target_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            changed_fields=changed_fields,
            retention_class="applications-programme-import-restricted",
        ),
        occurred_at=occurred_at,
    )
    if item is not None:
        aggregate_type = "applications.programme_import_item"
        aggregate_id = item.id
        aggregate_version = item.aggregate_version
        item_state = item.state
        item_version = item.aggregate_version
    elif preview_revision is not None:
        aggregate_type = "applications.programme_import_preview"
        aggregate_id = preview_revision.id
        aggregate_version = preview_revision.revision_number
        item_state = ""
        item_version = 0
    else:
        aggregate_type = "applications.programme_import_batch"
        aggregate_id = batch.id
        aggregate_version = batch.aggregate_version
        item_state = ""
        item_version = 0
    publish_domain_event(
        DomainEventRecord(
            event_name=APPLICATIONS_PROGRAMME_IMPORT_CHANGED_EVENT,
            schema_version=APPLICATIONS_PROGRAMME_IMPORT_EVENT_SCHEMA_VERSION,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            payload=programme_import_changed_payload(
                action=action,
                batch_id=batch.id,
                batch_state=batch.state,
                batch_version=batch.aggregate_version,
                item_id=item.id if item is not None else None,
                item_state=item_state,
                item_version=item_version,
            ),
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=scope.actor_id,
            retention_class="applications-programme-import-restricted",
        ),
        occurred_at=occurred_at,
    )
    return _command_result(receipt, replayed=False), receipt


def _parsed_item(item: ProgrammeImportItem) -> ProgrammeImportItemInput:
    payload = item.canonical_payload
    if payload is None:
        raise _ApplicationsProgrammeImportEvidenceError
    try:
        parsed = parse_programme_import_item_payload(bytes(payload))
    except ProgrammeImportInputError:
        raise _ApplicationsProgrammeImportEvidenceError from None
    if (
        parsed.kind != item.kind
        or parsed.source_key != item.source_key
        or parsed.source_digest != item.source_digest
    ):
        raise _ApplicationsProgrammeImportEvidenceError
    return parsed


def _proposal_dependency_binding(
    *,
    item: ProgrammeImportItem,
    lock: bool,
) -> ProgrammeImportSourceBinding | None:
    query = ProgrammeImportSourceBinding.objects.all()
    if lock:
        query = query.select_for_update()
    return (
        query.filter(
            organization_id=item.organization_id,
            edition_id=item.edition_id,
            source_system=item.dependency_source_system,
            kind=ProgrammeImportItemKind.CALL,
            source_key=item.dependency_source_key,
            call__isnull=False,
        )
        .select_related("call__definition")
        .first()
    )


def _resolve_proposal_mapping(
    *,
    item: ProgrammeImportItem,
    parsed: ProgrammeImportProposalItemInput,
    actor_id: UUID,
    effective_now: datetime,
    lock: bool,
) -> _ResolvedProposal:
    dependency = _proposal_dependency_binding(item=item, lock=lock)
    if dependency is None or dependency.call is None:
        raise ApplicationsProgrammeImportStateConflictError
    call = dependency.call
    definition = call.definition
    if (
        definition.status != ApplicationDefinitionStatus.ACTIVE
        or definition.opens_at > effective_now
        or definition.applicant_edit_until < effective_now
        or definition.closes_at < effective_now
    ):
        raise ApplicationsProgrammeImportStateConflictError
    track_query = ProgrammeCallTrack.objects.filter(
        call=call,
        code=parsed.track_code,
    )
    format_query = ProgrammeCallFormat.objects.filter(
        call=call,
        code=parsed.format_code,
    )
    if lock:
        track_query = track_query.select_for_update()
        format_query = format_query.select_for_update()
    track = track_query.first()
    programme_format = format_query.first()
    if (
        track is None
        or programme_format is None
        or not (
            programme_format.min_duration_minutes
            <= parsed.requested_duration_minutes
            <= programme_format.max_duration_minutes
        )
    ):
        raise ApplicationsProgrammeImportStateConflictError
    imported_answers = {answer.question_key: answer for answer in parsed.answers}
    questions = list(
        ApplicationQuestion.objects.filter(
            definition=definition,
            key__in=imported_answers,
            applicant_visible=True,
            applicant_writable=True,
            source_binding="",
            staff_visible=False,
            staff_writable=False,
            reviewer_visible=False,
            public_after_approval=False,
            api_projection=False,
        )
        .select_related("section")
        .order_by("section__position", "position", "id")
    )
    if lock and questions:
        questions = list(
            ApplicationQuestion.objects.select_for_update()
            .filter(id__in=[question.id for question in questions])
            .select_related("section")
            .order_by("section__position", "position", "id")
        )
    if len(questions) != len(imported_answers):
        raise ApplicationsProgrammeImportStateConflictError
    normalized_values: dict[str, object] = {}
    resolved_answers: list[tuple[ApplicationQuestion, object]] = []
    account = cast("Any", _AccountIdentifier(actor_id))
    try:
        for question in questions:
            if not condition_matches(question.condition, normalized_values):
                raise ApplicationsProgrammeImportStateConflictError
            answer = imported_answers[question.key]
            if answer.field_type.value != question.field_type:
                raise ApplicationsProgrammeImportStateConflictError
            normalized = normalize_answer_value(
                question=question,
                account=account,
                value=answer.as_application_value(),
            )
            normalized_values[question.key] = normalized
            resolved_answers.append((question, normalized))
    except ValidationError as error:
        raise ApplicationsProgrammeImportStateConflictError from error
    return _ResolvedProposal(
        call=call,
        selection=ProgrammeProposalSelectionInput(
            track_id=track.id,
            format_id=programme_format.id,
            requested_duration_minutes=parsed.requested_duration_minutes,
        ),
        answers=tuple(resolved_answers),
    )


def _preview_digest_payload(
    *,
    item: ProgrammeImportItem,
    status: str,
    action: str,
    dependency_state: str,
    dependency_digest: str,
    dependency_version: int | None,
    safe_field_keys: tuple[str, ...],
    reason_codes: tuple[str, ...],
) -> str:
    return canonical_programme_digest(
        {
            "item_id": item.id,
            "item_version": item.aggregate_version,
            "item_digest": item.source_digest,
            "batch_version": item.batch.aggregate_version,
            "status": status,
            "action": action,
            "dependency_state": dependency_state,
            "dependency_digest": dependency_digest,
            "dependency_version": dependency_version,
            "safe_field_keys": safe_field_keys,
            "reason_codes": reason_codes,
        }
    )


def _evaluate_preview_item(  # noqa: PLR0912, PLR0915
    *,
    item: ProgrammeImportItem,
    actor_id: UUID,
    effective_now: datetime,
    lock: bool,
) -> _PreviewEvaluation:
    binding = _binding_for_item(item=item, lock=lock)
    parsed: ProgrammeImportItemInput | None
    status: str
    action: str
    dependency_state: str = ProgrammeImportDependencyState.NONE
    dependency_digest = ""
    dependency_version: int | None = None
    safe_field_keys: tuple[str, ...]
    reason_codes: tuple[str, ...]
    if item.state == ProgrammeImportItemState.APPLIED:
        if binding is None or binding.source_digest != item.source_digest:
            raise ApplicationsProgrammeImportUnavailableError
        parsed = None
        status = ProgrammeImportPreviewStatus.NO_OP
        action = ProgrammeImportPreviewAction.NONE
        safe_field_keys = ()
        reason_codes = ("source_already_applied",)
    elif item.state != ProgrammeImportItemState.STAGED:
        raise ApplicationsProgrammeImportStateConflictError
    else:
        parsed = _parsed_item(item)
    if item.state == ProgrammeImportItemState.STAGED and binding is not None:
        if binding.source_digest == item.source_digest:
            status = ProgrammeImportPreviewStatus.NO_OP
            reason_codes = ("source_already_applied",)
        else:
            status = ProgrammeImportPreviewStatus.CONFLICT
            reason_codes = ("source_digest_conflict",)
        action = ProgrammeImportPreviewAction.NONE
        safe_field_keys = ()
    elif item.state == ProgrammeImportItemState.STAGED and isinstance(
        parsed,
        ProgrammeImportCallItemInput,
    ):
        if ApplicationDefinition.objects.filter(
            edition_id=item.edition_id,
            code=parsed.definition.code,
        ).exists():
            status = ProgrammeImportPreviewStatus.CONFLICT
            action = ProgrammeImportPreviewAction.NONE
            safe_field_keys = ()
            reason_codes = ("definition_code_conflict",)
        else:
            status = ProgrammeImportPreviewStatus.READY
            action = ProgrammeImportPreviewAction.COMMIT_CALL
            safe_field_keys = ("configuration", "definition")
            reason_codes = ()
    elif item.state == ProgrammeImportItemState.STAGED:
        if not isinstance(parsed, ProgrammeImportProposalItemInput):
            raise ApplicationsProgrammeImportUnavailableError
        dependency = _proposal_dependency_binding(item=item, lock=lock)
        if dependency is None or dependency.call is None:
            status = ProgrammeImportPreviewStatus.BLOCKED
            action = ProgrammeImportPreviewAction.NONE
            dependency_state = ProgrammeImportDependencyState.MISSING
            safe_field_keys = ("answers", "lead_action_required", "selection")
            reason_codes = ("call_dependency_unavailable",)
        else:
            dependency_digest = dependency.source_digest
            dependency_version = dependency.call.definition.aggregate_version
            dependency_state = dependency.call.definition.status
            if dependency_state != ProgrammeImportDependencyState.ACTIVE:
                status = ProgrammeImportPreviewStatus.BLOCKED
                action = ProgrammeImportPreviewAction.NONE
                safe_field_keys = (
                    "answers",
                    "lead_action_required",
                    "selection",
                )
                reason_codes = ("call_dependency_not_active",)
            else:
                try:
                    _resolve_proposal_mapping(
                        item=item,
                        parsed=parsed,
                        actor_id=actor_id,
                        effective_now=effective_now,
                        lock=lock,
                    )
                except ApplicationsProgrammeImportStateConflictError:
                    status = ProgrammeImportPreviewStatus.BLOCKED
                    action = ProgrammeImportPreviewAction.NONE
                    safe_field_keys = (
                        "answers",
                        "lead_action_required",
                        "selection",
                    )
                    reason_codes = ("proposal_mapping_invalid",)
                else:
                    status = ProgrammeImportPreviewStatus.READY
                    action = ProgrammeImportPreviewAction.CLAIM_PROPOSAL
                    safe_field_keys = (
                        "answers",
                        "lead_action_required",
                        "selection",
                    )
                    reason_codes = ()
    result_digest = _preview_digest_payload(
        item=item,
        status=status,
        action=action,
        dependency_state=dependency_state,
        dependency_digest=dependency_digest,
        dependency_version=dependency_version,
        safe_field_keys=safe_field_keys,
        reason_codes=reason_codes,
    )
    return _PreviewEvaluation(
        item=item,
        parsed=parsed,
        status=status,
        action=action,
        dependency_state=dependency_state,
        dependency_digest=dependency_digest,
        dependency_version=dependency_version,
        safe_field_keys=safe_field_keys,
        reason_codes=reason_codes,
        result_digest=result_digest,
    )


def _batch_preview_projection(
    *,
    receipt_id: UUID,
    revision: ProgrammeImportPreviewRevision,
    replayed: bool,
) -> ProgrammeImportBatchPreview:
    results = tuple(
        ProgrammeImportPreviewItem(
            result_id=row.id,
            item_id=row.item_id,
            item_version=row.item_version,
            kind=row.item.kind,
            status=row.status,
            action=row.action,
            dependency_state=row.dependency_state,
            safe_field_keys=tuple(row.safe_field_keys),
            reason_codes=tuple(row.reason_codes),
        )
        for row in revision.item_results.select_related("item").order_by(
            "item__sequence",
            "item_id",
        )
    )
    return ProgrammeImportBatchPreview(
        receipt_id=receipt_id,
        batch_id=revision.batch_id,
        revision_id=revision.id,
        revision_number=revision.revision_number,
        items=results,
        replayed=replayed,
    )


@_audit_import_errors(
    capability_code=APPLICATIONS_IMPORT_PROGRAMME,
    operation="command.batch_staged",
)
@transaction.atomic
def stage_programme_import(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    owner_department_id: UUID,
    source_system: str,
    raw_payload: bytes,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _IMPORT_AUTHZ,
    retention_policy_provider: ProgrammeImportRetentionPolicyProvider = (_RP),
) -> ProgrammeImportCommandResult:
    """Stage one strict source document without applying a domain mutation.

    Parameters
    ----------
    actor_id : UUID
        Account requesting the import.
    organization_id : UUID
        Organization that owns the import batch.
    edition_id : UUID
        Edition in which the import will eventually be applied.
    owner_department_id : UUID
        Current Department responsible for the imported Programme work.
    source_system : str
        Registered lower-case identifier for the source system.
    raw_payload : bytes
        Untrusted UTF-8 JSON bytes in the closed import schema.
    expected_version : int
        Creation cursor, which must be zero.
    reason : str
        Inspectable administrative rationale for staging the batch.
    retry_key : UUID
        Edition-scoped idempotency key for this normalized intent.
    correlation_id : UUID
        Correlation identifier shared by audit and event evidence.
    source_channel : str
        Registered channel through which the command arrived.
    now : datetime | None, default=None
        Optional timezone-aware command time.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_IMPORT_AUTHZ
        Exact-scope authorization adapter.
    retention_policy_provider : ProgrammeImportRetentionPolicyProvider, default=_RP
        Server-side provider for the reviewed staging-retention policy.

    Returns
    -------
    ProgrammeImportCommandResult
        Opaque batch and receipt identifiers with the resulting cursor.

    Raises
    ------
    ApplicationsProgrammeImportStateConflictError
        If the edition cannot currently accept private planning writes.
    ApplicationsProgrammeImportVersionConflictError
        If the creation cursor is not zero.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    owner_department_id = require_programme_uuid(
        owner_department_id,
        field="owner_department_id",
    )
    retry_key = require_programme_uuid(retry_key, field="retry_key")
    correlation_id = require_programme_uuid(correlation_id, field="correlation_id")
    expected_version = require_programme_expected_version(expected_version)
    if expected_version != 0:
        raise ApplicationsProgrammeImportVersionConflictError
    source_system = _normalize_source_system(source_system)
    source_channel = _normalize_source_channel(source_channel)
    reason = _normalize_reason(reason)
    _require_retention_policy_provider(retention_policy_provider)
    authorize_programme_import_retry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )
    parsed: ParsedProgrammeImportDocument = parse_programme_import_document(raw_payload)
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeImportCommandAction.BATCH_STAGED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        expected_version=0,
        reason=reason,
        source_channel=source_channel,
        values={
            "owner_department_id": owner_department_id,
            "source_system": source_system,
            "schema_version": parsed.version,
            "source_digest": parsed.source_digest,
        },
    )
    replay = _replay(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=digest,
        authorizer=authorizer,
    )
    if replay is not None:
        return replay
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(owner_department_id,),
    )
    scope = authorize_programme_import_department_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=owner_department_id,
        authorizer=authorizer,
        lock=True,
    )
    if not scope.accepts_private_planning_writes:
        raise ApplicationsProgrammeImportStateConflictError
    retention = retention_policy_provider.resolve(staged_at=effective_now)
    with programme_import_database_writer():
        batch = ProgrammeImportBatch.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            owner_department_id=owner_department_id,
            source_system=source_system,
            schema_version=parsed.version,
            source_digest=parsed.source_digest,
            item_count=len(parsed.items),
            retention_policy_code=retention.policy_code,
            expires_at=retention.expires_at,
            state=ProgrammeImportBatchState.STAGED,
            aggregate_version=1,
            staged_by_id=actor_id,
        )
        for sequence, parsed_item in enumerate(parsed.items, start=1):
            if isinstance(parsed_item, ProgrammeImportProposalItemInput):
                dependency_source_system = source_system
                dependency_source_key = parsed_item.call_source_key
            else:
                dependency_source_system = ""
                dependency_source_key = ""
            ProgrammeImportItem.objects.create(
                batch=batch,
                organization_id=organization_id,
                edition_id=edition_id,
                sequence=sequence,
                kind=parsed_item.kind,
                source_key=parsed_item.source_key,
                source_digest=parsed_item.source_digest,
                canonical_payload=parsed_item.canonical_payload,
                payload_size_bytes=len(parsed_item.canonical_payload),
                dependency_source_system=dependency_source_system,
                dependency_source_key=dependency_source_key,
                state=ProgrammeImportItemState.STAGED,
                aggregate_version=1,
            )
        result, _receipt = _record_success(
            scope=scope,
            action=ProgrammeImportCommandAction.BATCH_STAGED,
            aggregate_kind=ProgrammeImportAggregateKind.BATCH,
            result_kind=ProgrammeImportCommandResultKind.BATCH,
            batch=batch,
            expected_version=0,
            resulting_version=1,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("batch", "items", "private_payload"),
            occurred_at=effective_now,
        )
    return result


@_audit_import_errors(
    capability_code=APPLICATIONS_IMPORT_PROGRAMME,
    operation="command.batch_reassigned",
)
@transaction.atomic
def reassign_programme_import_batch(  # noqa: DOC503
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    batch_id: UUID,
    source_department_id: UUID,
    destination_department_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _IMPORT_AUTHZ,
) -> ProgrammeImportCommandResult:
    """Move one pristine staged batch between two current Departments.

    Parameters
    ----------
    actor_id : UUID
        Account requesting the ownership transfer.
    organization_id : UUID
        Organization that owns the batch and both Departments.
    edition_id : UUID
        Exact private-planning edition containing the batch.
    batch_id : UUID
        Opaque staged-batch identifier.
    source_department_id : UUID
        Exact current Department expected to own the batch.
    destination_department_id : UUID
        Exact current Department that will receive the batch.
    expected_version : int
        Optimistic batch cursor to advance by one.
    reason : str
        Inspectable administrative rationale for the transfer.
    retry_key : UUID
        Edition-scoped idempotency key for this normalized intent.
    correlation_id : UUID
        Correlation identifier shared by audit and event evidence.
    source_channel : str
        Registered channel through which the command arrived.
    now : datetime | None, default=None
        Optional timezone-aware command time.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_IMPORT_AUTHZ
        Exact-Department authorization adapter.

    Returns
    -------
    ProgrammeImportCommandResult
        Opaque receipt and batch identifiers with the advanced cursor.

    Raises
    ------
    ApplicationsProgrammeImportStateConflictError
        If the batch is not pristine staging or planning is closed.
    ApplicationsProgrammeImportUnavailableError
        If the exact batch, owner, Department, or retained scope is unavailable.
    ApplicationsProgrammeImportVersionConflictError
        If the supplied batch cursor is stale.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    batch_id = require_programme_uuid(batch_id, field="batch_id")
    source_department_id = require_programme_uuid(
        source_department_id,
        field="source_department_id",
    )
    destination_department_id = require_programme_uuid(
        destination_department_id,
        field="destination_department_id",
    )
    retry_key = require_programme_uuid(retry_key, field="retry_key")
    correlation_id = require_programme_uuid(correlation_id, field="correlation_id")
    expected_version = require_programme_expected_version(expected_version)
    if source_department_id == destination_department_id:
        raise ApplicationsProgrammeImportStateConflictError
    reason = _normalize_reason(reason)
    source_channel = _normalize_source_channel(source_channel)
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeImportCommandAction.BATCH_REASSIGNED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={
            "batch_id": batch_id,
            "source_department_id": source_department_id,
            "destination_department_id": destination_department_id,
        },
    )
    replay = _replay(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=digest,
        authorizer=authorizer,
    )
    if replay is not None:
        return replay

    department_ids = tuple(sorted((source_department_id, destination_department_id)))
    try:
        for department_id in department_ids:
            authorize_programme_import_department_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                department_id=department_id,
                authorizer=authorizer,
            )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportUnavailableError from error

    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=department_ids,
    )
    locked_scopes: dict[UUID, AuthorizedProgrammeImportScope] = {}
    try:
        for department_id in department_ids:
            locked_scopes[department_id] = authorize_programme_import_department_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                department_id=department_id,
                authorizer=authorizer,
                lock=True,
            )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportUnavailableError from error
    if any(
        not scope.accepts_private_planning_writes for scope in locked_scopes.values()
    ):
        raise ApplicationsProgrammeImportStateConflictError

    batch = _lock_batch(
        organization_id=organization_id,
        edition_id=edition_id,
        batch_id=batch_id,
    )
    if batch.owner_department_id != source_department_id:
        raise ApplicationsProgrammeImportUnavailableError
    _require_staged_batch(
        batch,
        expected_version=expected_version,
        effective_now=effective_now,
    )
    items = list(
        ProgrammeImportItem.objects.select_for_update()
        .filter(batch=batch)
        .select_related("batch")
        .order_by("sequence", "id")
    )
    if len(items) != batch.item_count or any(
        item.state != ProgrammeImportItemState.STAGED
        or item.aggregate_version != 1
        or item.canonical_payload is None
        for item in items
    ):
        raise ApplicationsProgrammeImportStateConflictError
    for item in items:
        _parsed_item(item)
    if (
        ProgrammeImportSourceBinding.objects.select_for_update()
        .filter(item__batch=batch)
        .exists()
        or ProgrammeImportAppliedCommand.objects.select_for_update()
        .filter(binding__item__batch=batch)
        .exists()
        or ProgrammeImportCommandReceipt.objects.select_for_update()
        .filter(batch=batch)
        .filter(
            Q(
                action__in=(
                    ProgrammeImportCommandAction.CALL_COMMITTED,
                    ProgrammeImportCommandAction.PROPOSAL_CLAIMED,
                )
            )
            | Q(source_binding__isnull=False)
            | Q(applied_command_count__gt=0)
        )
        .exists()
    ):
        raise ApplicationsProgrammeImportStateConflictError

    resulting_version = expected_version + 1
    with programme_import_database_writer():
        batch.owner_department_id = destination_department_id
        batch.aggregate_version = resulting_version
        batch.save(
            update_fields=(
                "owner_department",
                "aggregate_version",
                "updated_at",
            )
        )
        result, _receipt = _record_success(
            scope=locked_scopes[source_department_id],
            action=ProgrammeImportCommandAction.BATCH_REASSIGNED,
            aggregate_kind=ProgrammeImportAggregateKind.BATCH,
            result_kind=ProgrammeImportCommandResultKind.BATCH,
            batch=batch,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("owner_department", "aggregate_version"),
            occurred_at=effective_now,
            source_department_id=source_department_id,
            destination_department_id=destination_department_id,
        )
    return result


@_audit_import_errors(
    capability_code=APPLICATIONS_IMPORT_PROGRAMME,
    operation="command.batch_previewed",
)
@transaction.atomic
def preview_programme_import(  # noqa: PLR0915
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    batch_id: UUID,
    expected_batch_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _IMPORT_AUTHZ,
) -> ProgrammeImportBatchPreview:
    """Persist a sanitized item-complete organizer preview revision.

    Parameters
    ----------
    actor_id : UUID
        Account requesting the preview.
    organization_id : UUID
        Organization that owns the staged batch.
    edition_id : UUID
        Edition that owns the staged batch.
    batch_id : UUID
        Opaque staged-batch identifier.
    expected_batch_version : int
        Optimistic cursor for the batch.
    reason : str
        Inspectable administrative rationale for creating the preview.
    retry_key : UUID
        Edition-scoped idempotency key for this normalized intent.
    correlation_id : UUID
        Correlation identifier shared by audit and event evidence.
    source_channel : str
        Registered channel through which the command arrived.
    now : datetime | None, default=None
        Optional timezone-aware command time.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_IMPORT_AUTHZ
        Exact-scope authorization adapter.

    Returns
    -------
    ProgrammeImportBatchPreview
        The immutable revision and sanitized result for every batch item.

    Raises
    ------
    ApplicationsProgrammeImportStateConflictError
        If the batch or edition cannot be previewed in its current state.
    ApplicationsProgrammeImportUnavailableError
        If replay evidence does not resolve to the requested preview.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    batch_id = require_programme_uuid(batch_id, field="batch_id")
    retry_key = require_programme_uuid(retry_key, field="retry_key")
    correlation_id = require_programme_uuid(correlation_id, field="correlation_id")
    expected_batch_version = require_programme_expected_version(expected_batch_version)
    reason = _normalize_reason(reason)
    source_channel = _normalize_source_channel(source_channel)
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeImportCommandAction.BATCH_PREVIEWED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        expected_version=expected_batch_version,
        reason=reason,
        source_channel=source_channel,
        values={"batch_id": batch_id},
    )
    replay = _replay(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=digest,
        authorizer=authorizer,
    )
    if replay is not None:
        if replay.preview_revision_id is None:
            raise ApplicationsProgrammeImportUnavailableError
        replay_batch = ProgrammeImportBatch.objects.filter(
            id=batch_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).first()
        if replay_batch is None:
            raise ApplicationsProgrammeImportUnavailableError
        try:
            replay_scope = authorize_programme_import_department_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                department_id=replay_batch.owner_department_id,
                authorizer=authorizer,
            )
        except ApplicationsProgrammeImportAuthorizationDeniedError as error:
            raise ApplicationsProgrammeImportUnavailableError from error
        if not replay_scope.accepts_private_planning_writes:
            raise ApplicationsProgrammeImportStateConflictError
        _require_staged_batch(
            replay_batch,
            expected_version=expected_batch_version,
            effective_now=effective_now,
        )
        revision = ProgrammeImportPreviewRevision.objects.filter(
            id=replay.preview_revision_id,
            batch=replay_batch,
        ).first()
        if revision is None:
            raise ApplicationsProgrammeImportUnavailableError
        return _batch_preview_projection(
            receipt_id=replay.receipt_id,
            revision=revision,
            replayed=True,
        )
    owner_department_id = _batch_owner_department_id(
        organization_id=organization_id,
        edition_id=edition_id,
        batch_id=batch_id,
    )
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(owner_department_id,),
    )
    try:
        scope = authorize_programme_import_department_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=owner_department_id,
            authorizer=authorizer,
            lock=True,
        )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportUnavailableError from error
    if not scope.accepts_private_planning_writes:
        raise ApplicationsProgrammeImportStateConflictError
    batch = _lock_batch(
        organization_id=organization_id,
        edition_id=edition_id,
        batch_id=batch_id,
    )
    if batch.owner_department_id != owner_department_id:
        raise ApplicationsProgrammeImportUnavailableError
    _require_staged_batch(
        batch,
        expected_version=expected_batch_version,
        effective_now=effective_now,
    )
    items = list(
        ProgrammeImportItem.objects.select_for_update()
        .filter(batch=batch)
        .select_related("batch")
        .order_by("sequence", "id")
    )
    if len(items) != batch.item_count or any(
        item.state
        not in {
            ProgrammeImportItemState.STAGED,
            ProgrammeImportItemState.APPLIED,
        }
        for item in items
    ):
        raise ApplicationsProgrammeImportStateConflictError
    evaluations = tuple(
        _evaluate_preview_item(
            item=item,
            actor_id=actor_id,
            effective_now=effective_now,
            lock=True,
        )
        for item in items
    )
    prior_revision = (
        ProgrammeImportPreviewRevision.objects.select_for_update()
        .filter(batch=batch)
        .aggregate(maximum=Max("revision_number"))["maximum"]
        or 0
    )
    preview_digest = canonical_programme_digest(
        {
            "batch_id": batch.id,
            "batch_version": batch.aggregate_version,
            "revision_number": prior_revision + 1,
            "results": [evaluation.result_digest for evaluation in evaluations],
        }
    )
    with programme_import_database_writer():
        revision = ProgrammeImportPreviewRevision.objects.create(
            batch=batch,
            organization_id=organization_id,
            edition_id=edition_id,
            revision_number=prior_revision + 1,
            source_batch_version=batch.aggregate_version,
            preview_digest=preview_digest,
            item_count=len(evaluations),
            actor_id=actor_id,
        )
        for evaluation in evaluations:
            ProgrammeImportPreviewItemResult.objects.create(
                preview=revision,
                item=evaluation.item,
                organization_id=organization_id,
                edition_id=edition_id,
                item_version=evaluation.item.aggregate_version,
                status=evaluation.status,
                action=evaluation.action,
                dependency_state=evaluation.dependency_state,
                dependency_digest=evaluation.dependency_digest,
                dependency_version=evaluation.dependency_version,
                safe_field_keys=list(evaluation.safe_field_keys),
                reason_codes=list(evaluation.reason_codes),
                result_digest=evaluation.result_digest,
            )
        result, _receipt = _record_success(
            scope=scope,
            action=ProgrammeImportCommandAction.BATCH_PREVIEWED,
            aggregate_kind=ProgrammeImportAggregateKind.PREVIEW,
            result_kind=ProgrammeImportCommandResultKind.PREVIEW,
            batch=batch,
            preview_revision=revision,
            expected_version=prior_revision,
            resulting_version=prior_revision + 1,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("preview_revision", "preview_results"),
            occurred_at=effective_now,
        )
    return _batch_preview_projection(
        receipt_id=result.receipt_id,
        revision=revision,
        replayed=False,
    )


def _claim_preview_digest(
    *,
    item: ProgrammeImportItem,
    parsed: ProgrammeImportProposalItemInput,
    resolved: _ResolvedProposal,
    actor_id: UUID,
    lock: bool,
) -> str:
    dependency = _proposal_dependency_binding(item=item, lock=lock)
    if dependency is None:
        raise ApplicationsProgrammeImportClaimUnavailableError
    return canonical_programme_digest(
        {
            "actor_id": actor_id,
            "organization_id": item.organization_id,
            "edition_id": item.edition_id,
            "item_id": item.id,
            "item_version": item.aggregate_version,
            "item_digest": item.source_digest,
            "batch_version": item.batch.aggregate_version,
            "schema_version": item.batch.schema_version,
            "source_system": item.batch.source_system,
            "kind": item.kind,
            "source_key": parsed.source_key,
            "dependency_binding_id": dependency.id,
            "dependency_digest": dependency.source_digest,
            "dependency_version": resolved.call.definition.aggregate_version,
            "selection": asdict(resolved.selection),
            "answers": tuple(
                {
                    "question_key": question.key,
                    "field_type": question.field_type,
                    "value": value,
                }
                for question, value in resolved.answers
            ),
        }
    )


def _require_claim_lead(
    *,
    actor_id: UUID,
    parsed: ProgrammeImportProposalItemInput,
    lock: bool,
) -> None:
    person = resolve_active_verified_person_reference_by_email(
        email=parsed.lead_email,
        lock=lock,
    )
    if person is None or person.account_id != actor_id:
        raise ApplicationsProgrammeImportClaimUnavailableError


@_audit_import_errors(
    capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    operation="query.proposal_claim_preview",
)
@transaction.atomic
def preview_programme_import_proposal_claim(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _IMPORT_AUTHZ,
) -> ProgrammeImportProposalClaimPreview:
    """Audit and return one proposal only to its exact current verified lead.

    Parameters
    ----------
    actor_id : UUID
        Account asking to inspect its proposed claim.
    organization_id : UUID
        Organization that owns the staged proposal.
    edition_id : UUID
        Edition that owns the staged proposal.
    item_id : UUID
        Opaque staged proposal-item identifier.
    correlation_id : UUID
        Correlation identifier for the protected-read audit outcome.
    source_channel : str
        Registered channel through which the protected read arrived.
    now : datetime | None, default=None
        Optional timezone-aware query time.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_IMPORT_AUTHZ
        Exact-self authorization adapter.

    Returns
    -------
    ProgrammeImportProposalClaimPreview
        The imported applicant-owned values visible to the matched lead.

    Raises
    ------
    ApplicationsProgrammeImportClaimUnavailableError
        If any identity, scope, item, dependency, or mapping check fails.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    item_id = require_programme_uuid(item_id, field="item_id")
    correlation_id = require_programme_uuid(correlation_id, field="correlation_id")
    source_channel = _normalize_source_channel(source_channel)
    effective_now = _effective_now(now)
    try:
        authorize_programme_import_self_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=_CLAIM_FIELDS,
            authorizer=authorizer,
        )
        authorize_programme_import_self_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
            authorizer=authorizer,
        )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    preflight_item = (
        ProgrammeImportItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=ProgrammeImportItemKind.PROPOSAL,
            state=ProgrammeImportItemState.STAGED,
        )
        .select_related("batch")
        .first()
    )
    if preflight_item is None:
        raise ApplicationsProgrammeImportClaimUnavailableError
    owner_department_id = preflight_item.batch.owner_department_id
    try:
        _lock_programme_write_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_ids=(owner_department_id,),
        )
        require_current_programme_import_owner(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=owner_department_id,
            lock=True,
        )
        batch = _lock_batch(
            organization_id=organization_id,
            edition_id=edition_id,
            batch_id=preflight_item.batch_id,
        )
    except (
        ApplicationsProgrammeImportAuthorizationDeniedError,
        ApplicationsProgrammeImportCommandError,
    ) as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    if batch.owner_department_id != owner_department_id:
        raise ApplicationsProgrammeImportClaimUnavailableError
    item = (
        ProgrammeImportItem.objects.select_for_update()
        .filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=ProgrammeImportItemKind.PROPOSAL,
            state=ProgrammeImportItemState.STAGED,
            batch=batch,
        )
        .select_related("batch")
        .first()
    )
    if item is None:
        raise ApplicationsProgrammeImportClaimUnavailableError
    try:
        _require_staged_batch(
            batch,
            expected_version=batch.aggregate_version,
            effective_now=effective_now,
        )
        parsed = _parsed_item(item)
    except ApplicationsProgrammeImportCommandError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    if not isinstance(parsed, ProgrammeImportProposalItemInput):
        raise ApplicationsProgrammeImportClaimUnavailableError
    try:
        scope = authorize_programme_import_self_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=_CLAIM_FIELDS,
            authorizer=authorizer,
            lock=True,
        )
        authorize_programme_import_self_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
            authorizer=authorizer,
            lock=True,
        )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    _require_claim_lead(actor_id=actor_id, parsed=parsed, lock=True)
    if _binding_for_item(item=item, lock=True) is not None:
        raise ApplicationsProgrammeImportClaimUnavailableError
    try:
        resolved = _resolve_proposal_mapping(
            item=item,
            parsed=parsed,
            actor_id=actor_id,
            effective_now=effective_now,
            lock=True,
        )
    except ApplicationsProgrammeImportCommandError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    adoption_digest = _claim_preview_digest(
        item=item,
        parsed=parsed,
        resolved=resolved,
        actor_id=actor_id,
        lock=True,
    )
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            operation="applications.programme_import.query.proposal_claim_preview",
            target_type="applications.programme_import_item",
            target_id=item.id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="applications-programme-import-restricted",
        ),
        occurred_at=effective_now,
    )
    return ProgrammeImportProposalClaimPreview(
        item_id=item.id,
        item_version=item.aggregate_version,
        track_code=parsed.track_code,
        format_code=parsed.format_code,
        requested_duration_minutes=parsed.requested_duration_minutes,
        answers=tuple(
            ProgrammeImportProposalClaimAnswer(
                question_key=question.key,
                field_type=question.field_type,
                value=deepcopy(value),
            )
            for question, value in resolved.answers
        ),
        adoption_digest=adoption_digest,
    )


@_audit_import_errors(
    capability_code=APPLICATIONS_IMPORT_PROGRAMME,
    operation="command.call_committed",
)
@transaction.atomic
def commit_programme_import_call(  # noqa: PLR0915
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    preview_item_result_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _IMPORT_AUTHZ,
    programme_authorizer: ApplicationsProgrammeAuthorizer = (_PROGRAMME_AUTHZ),
) -> ProgrammeImportCommandResult:
    """Adopt one fresh ready preview and create exactly one Draft call.

    Parameters
    ----------
    actor_id : UUID
        Account committing the imported call.
    organization_id : UUID
        Organization that owns the staged call.
    edition_id : UUID
        Edition that owns the staged call.
    item_id : UUID
        Opaque staged call-item identifier.
    preview_item_result_id : UUID
        Exact ready preview item being adopted.
    expected_version : int
        Optimistic cursor for the staged item.
    reason : str
        Inspectable administrative rationale for committing the call.
    retry_key : UUID
        Edition-scoped idempotency key for this normalized intent.
    correlation_id : UUID
        Correlation identifier shared by nested and import evidence.
    source_channel : str
        Registered channel through which the command arrived.
    now : datetime | None, default=None
        Optional timezone-aware command time.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_IMPORT_AUTHZ
        Import-scope authorization adapter.
    programme_authorizer : ApplicationsProgrammeAuthorizer, default=_PROGRAMME_AUTHZ
        Programme-call authorization adapter used by the nested command.

    Returns
    -------
    ProgrammeImportCommandResult
        Opaque batch, item, and receipt identifiers with the resulting cursor.

    Raises
    ------
    ApplicationsProgrammeImportPreviewStaleError
        If the adopted preview is absent or no longer exact.
    ApplicationsProgrammeImportStateConflictError
        If the edition cannot accept the call in its current state.
    ApplicationsProgrammeImportUnavailableError
        If the requested staged call is unavailable in the exact scope.
    ApplicationsProgrammeImportVersionConflictError
        If the item cursor is stale or the item is no longer staged.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    item_id = require_programme_uuid(item_id, field="item_id")
    preview_item_result_id = require_programme_uuid(
        preview_item_result_id,
        field="preview_item_result_id",
    )
    retry_key = require_programme_uuid(retry_key, field="retry_key")
    correlation_id = require_programme_uuid(correlation_id, field="correlation_id")
    expected_version = require_programme_expected_version(expected_version)
    reason = _normalize_reason(reason)
    source_channel = _normalize_source_channel(source_channel)
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeImportCommandAction.CALL_COMMITTED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={
            "item_id": item_id,
            "preview_item_result_id": preview_item_result_id,
        },
    )
    replay = _replay(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=digest,
        authorizer=authorizer,
    )
    if replay is not None:
        return replay
    nested_retry_key = _lock_nested_retry_key(
        actor_id=actor_id,
        edition_id=edition_id,
        outer_retry_key=retry_key,
        item_id=item_id,
        sequence=1,
        action=ProgrammeCommandAction.CALL_CREATED,
    )
    locked_batch_scope = (
        ProgrammeImportItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=ProgrammeImportItemKind.CALL,
        )
        .values_list("batch_id", "batch__owner_department_id")
        .first()
    )
    if locked_batch_scope is None:
        raise ApplicationsProgrammeImportUnavailableError
    locked_batch_id, owner_department_id = locked_batch_scope
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(owner_department_id,),
    )
    batch = _lock_batch(
        organization_id=organization_id,
        edition_id=edition_id,
        batch_id=locked_batch_id,
    )
    if batch.owner_department_id != owner_department_id:
        raise ApplicationsProgrammeImportUnavailableError
    item = (
        ProgrammeImportItem.objects.select_for_update()
        .filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=ProgrammeImportItemKind.CALL,
            batch=batch,
        )
        .select_related("batch")
        .first()
    )
    if item is None:
        raise ApplicationsProgrammeImportUnavailableError
    try:
        scope = authorize_programme_import_department_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=batch.owner_department_id,
            authorizer=authorizer,
            lock=True,
        )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportUnavailableError from error
    if not scope.accepts_private_planning_writes:
        raise ApplicationsProgrammeImportStateConflictError
    _require_staged_batch(
        batch,
        expected_version=batch.aggregate_version,
        effective_now=effective_now,
    )
    if (
        item.state != ProgrammeImportItemState.STAGED
        or item.aggregate_version != expected_version
    ):
        raise ApplicationsProgrammeImportVersionConflictError
    preview_result = (
        ProgrammeImportPreviewItemResult.objects.select_for_update()
        .filter(
            id=preview_item_result_id,
            item=item,
            organization_id=organization_id,
            edition_id=edition_id,
            preview__batch=batch,
            preview__source_batch_version=batch.aggregate_version,
            status=ProgrammeImportPreviewStatus.READY,
            action=ProgrammeImportPreviewAction.COMMIT_CALL,
        )
        .select_related("preview")
        .first()
    )
    if preview_result is None or preview_result.item_version != item.aggregate_version:
        raise ApplicationsProgrammeImportPreviewStaleError
    _source_lock(
        organization_id=organization_id,
        edition_id=edition_id,
        source_system=batch.source_system,
        kind=item.kind,
        source_key=item.source_key,
    )
    evaluation = _evaluate_preview_item(
        item=item,
        actor_id=actor_id,
        effective_now=effective_now,
        lock=True,
    )
    if (
        evaluation.status != ProgrammeImportPreviewStatus.READY
        or evaluation.action != ProgrammeImportPreviewAction.COMMIT_CALL
        or evaluation.result_digest != preview_result.result_digest
        or not isinstance(evaluation.parsed, ProgrammeImportCallItemInput)
    ):
        raise ApplicationsProgrammeImportPreviewStaleError
    with programme_import_database_writer():
        nested = create_programme_call(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            definition_input=evaluation.parsed.definition_input,
            configuration=evaluation.parsed.configuration_for_owner_department(
                batch.owner_department_id
            ),
            expected_version=0,
            reason=reason,
            retry_key=nested_retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            now=effective_now,
            authorizer=programme_authorizer,
        )
        call = ProgrammeCall.objects.select_for_update().get(
            id=nested.target_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        item.state = ProgrammeImportItemState.APPLIED
        item.aggregate_version = 2
        item.canonical_payload = None
        item.save(
            update_fields=(
                "state",
                "aggregate_version",
                "canonical_payload",
                "updated_at",
            )
        )
        binding = ProgrammeImportSourceBinding.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            source_system=batch.source_system,
            kind=ProgrammeImportItemKind.CALL,
            source_key=item.source_key,
            source_digest=item.source_digest,
            item=item,
            call=call,
            proposal=None,
            created_by_id=actor_id,
        )
        result, import_receipt = _record_success(
            scope=scope,
            action=ProgrammeImportCommandAction.CALL_COMMITTED,
            aggregate_kind=ProgrammeImportAggregateKind.ITEM,
            result_kind=ProgrammeImportCommandResultKind.CALL_BINDING,
            batch=batch,
            item=item,
            preview_revision=preview_result.preview,
            preview_item_result=preview_result,
            source_binding=binding,
            adopted_preview_digest=preview_result.result_digest,
            expected_version=expected_version,
            resulting_version=2,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("call_binding", "item_state", "private_payload"),
            occurred_at=effective_now,
            applied_command_count=1,
        )
        nested_receipt = ProgrammeCommandReceipt.objects.get(id=nested.receipt_id)
        ProgrammeImportAppliedCommand.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            binding=binding,
            import_receipt=import_receipt,
            sequence=1,
            programme_receipt=nested_receipt,
        )
    return result


@_audit_import_errors(
    capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    operation="command.proposal_claimed",
)
@transaction.atomic
def claim_programme_import_proposal(  # noqa: DOC503, PLR0912, PLR0915
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    item_id: UUID,
    lead_profile: ProgrammeProposalContributorProfileInput,
    adopted_preview_digest: str,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _IMPORT_AUTHZ,
    programme_authorizer: ApplicationsProgrammeAuthorizer = (_PROGRAMME_AUTHZ),
) -> ProgrammeImportCommandResult:
    """Let an exact current lead atomically claim one staged proposal draft.

    Parameters
    ----------
    actor_id : UUID
        Account claiming the imported proposal as its lead.
    organization_id : UUID
        Organization that owns the staged proposal.
    edition_id : UUID
        Edition that owns the staged proposal.
    item_id : UUID
        Opaque staged proposal-item identifier.
    lead_profile : ProgrammeProposalContributorProfileInput
        Current lead-owned profile and consent supplied at claim time.
    adopted_preview_digest : str
        Fresh digest returned by the exact lead-self preview being adopted.
    expected_version : int
        Optimistic cursor for the staged item.
    reason : str
        Inspectable rationale for adopting the staged proposal.
    retry_key : UUID
        Edition-scoped idempotency key for this normalized intent.
    correlation_id : UUID
        Correlation identifier shared by nested and import evidence.
    source_channel : str
        Registered channel through which the command arrived.
    now : datetime | None, default=None
        Optional timezone-aware command time.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_IMPORT_AUTHZ
        Exact-self import authorization adapter.
    programme_authorizer : ApplicationsProgrammeAuthorizer, default=_PROGRAMME_AUTHZ
        Proposal authorization adapter used by the nested commands.

    Returns
    -------
    ProgrammeImportCommandResult
        Opaque batch, item, and receipt identifiers with the resulting cursor.

    Raises
    ------
    ValidationError
        If the lead-owned contributor profile is not a closed typed input.
    ApplicationsProgrammeImportClaimUnavailableError
        If any identity, scope, item, dependency, or mapping check fails.
    ApplicationsProgrammeImportOperationFailedError
        If invalid command context or a nested/evidence dependency fails. The
        exception carries only the safe request correlation identifier.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    item_id = require_programme_uuid(item_id, field="item_id")
    retry_key = require_programme_uuid(retry_key, field="retry_key")
    correlation_id = require_programme_uuid(correlation_id, field="correlation_id")
    expected_version = require_programme_expected_version(expected_version)
    if not isinstance(lead_profile, ProgrammeProposalContributorProfileInput):
        raise ValidationError(
            "Proposal claim requires a closed lead-profile input.",
            code="applications_programme_import_profile_invalid",
        )
    if (
        not isinstance(adopted_preview_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", adopted_preview_digest, flags=re.ASCII) is None
    ):
        raise ApplicationsProgrammeImportClaimUnavailableError
    reason = _normalize_reason(reason)
    source_channel = _normalize_source_channel(source_channel)
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeImportCommandAction.PROPOSAL_CLAIMED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={
            "item_id": item_id,
            "lead_profile": asdict(lead_profile),
            "adopted_preview_digest": adopted_preview_digest,
        },
    )
    replay = _replay(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=digest,
        authorizer=authorizer,
    )
    if replay is not None:
        return replay
    try:
        authorize_programme_import_self_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=_CLAIM_FIELDS,
            authorizer=authorizer,
        )
        authorize_programme_import_self_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
            authorizer=authorizer,
        )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    preflight_item = (
        ProgrammeImportItem.objects.filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=ProgrammeImportItemKind.PROPOSAL,
            state=ProgrammeImportItemState.STAGED,
        )
        .select_related("batch")
        .first()
    )
    if preflight_item is None:
        raise ApplicationsProgrammeImportClaimUnavailableError
    try:
        require_current_programme_import_owner(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=preflight_item.batch.owner_department_id,
        )
        _require_staged_batch(
            preflight_item.batch,
            expected_version=preflight_item.batch.aggregate_version,
            effective_now=effective_now,
        )
        preflight_parsed = _parsed_item(preflight_item)
    except (
        ApplicationsProgrammeImportAuthorizationDeniedError,
        ApplicationsProgrammeImportCommandError,
    ) as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    if not isinstance(preflight_parsed, ProgrammeImportProposalItemInput):
        raise ApplicationsProgrammeImportClaimUnavailableError
    _require_claim_lead(
        actor_id=actor_id,
        parsed=preflight_parsed,
        lock=False,
    )
    nested_retry_keys = (
        _nested_retry_key(
            outer_retry_key=retry_key,
            item_id=item_id,
            sequence=1,
            action=ProgrammeCommandAction.PROPOSAL_STARTED,
        ),
        *(
            _nested_retry_key(
                outer_retry_key=retry_key,
                item_id=item_id,
                sequence=sequence,
                action=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
            )
            for sequence in range(2, len(preflight_parsed.answers) + 2)
        ),
    )
    for nested_retry_key in nested_retry_keys:
        lock_applications_retry_namespace(
            edition_id=edition_id,
            actor_id=actor_id,
            retry_key=nested_retry_key,
        )
    locked_batch_id = preflight_item.batch_id
    try:
        owner_department_id = _batch_owner_department_id(
            organization_id=organization_id,
            edition_id=edition_id,
            batch_id=locked_batch_id,
        )
        _lock_programme_write_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_ids=(owner_department_id,),
        )
        require_current_programme_import_owner(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=owner_department_id,
            lock=True,
        )
        batch = _lock_batch(
            organization_id=organization_id,
            edition_id=edition_id,
            batch_id=locked_batch_id,
        )
    except (
        ApplicationsProgrammeImportAuthorizationDeniedError,
        ApplicationsProgrammeImportCommandError,
    ) as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    if batch.owner_department_id != owner_department_id:
        raise ApplicationsProgrammeImportClaimUnavailableError
    item = (
        ProgrammeImportItem.objects.select_for_update()
        .filter(
            id=item_id,
            organization_id=organization_id,
            edition_id=edition_id,
            kind=ProgrammeImportItemKind.PROPOSAL,
            batch=batch,
        )
        .select_related("batch")
        .first()
    )
    if item is None:
        raise ApplicationsProgrammeImportClaimUnavailableError
    try:
        _require_staged_batch(
            batch,
            expected_version=batch.aggregate_version,
            effective_now=effective_now,
        )
    except ApplicationsProgrammeImportCommandError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    if (
        item.state != ProgrammeImportItemState.STAGED
        or item.aggregate_version != expected_version
    ):
        raise ApplicationsProgrammeImportClaimUnavailableError
    try:
        authorize_programme_import_self_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=_CLAIM_FIELDS,
            authorizer=authorizer,
            lock=True,
        )
        scope = authorize_programme_import_self_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
            authorizer=authorizer,
            lock=True,
        )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    if not scope.accepts_private_planning_writes:
        raise ApplicationsProgrammeImportClaimUnavailableError
    try:
        parsed = _parsed_item(item)
    except ApplicationsProgrammeImportCommandError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    if not isinstance(parsed, ProgrammeImportProposalItemInput):
        raise ApplicationsProgrammeImportClaimUnavailableError
    _require_claim_lead(actor_id=actor_id, parsed=parsed, lock=True)
    _source_lock(
        organization_id=organization_id,
        edition_id=edition_id,
        source_system=batch.source_system,
        kind=item.kind,
        source_key=item.source_key,
    )
    if _binding_for_item(item=item, lock=True) is not None:
        raise ApplicationsProgrammeImportClaimUnavailableError
    try:
        resolved = _resolve_proposal_mapping(
            item=item,
            parsed=parsed,
            actor_id=actor_id,
            effective_now=effective_now,
            lock=True,
        )
        current_preview_digest = _claim_preview_digest(
            item=item,
            parsed=parsed,
            resolved=resolved,
            actor_id=actor_id,
            lock=True,
        )
    except ApplicationsProgrammeImportCommandError as error:
        raise ApplicationsProgrammeImportClaimUnavailableError from error
    if not hmac.compare_digest(adopted_preview_digest, current_preview_digest):
        raise ApplicationsProgrammeImportClaimUnavailableError
    nested_results = []
    with programme_import_database_writer():
        start_sequence = 1
        started = start_programme_proposal(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            call_id=resolved.call.id,
            selection=resolved.selection,
            lead_profile=lead_profile,
            expected_version=0,
            reason=reason,
            retry_key=nested_retry_keys[start_sequence - 1],
            correlation_id=correlation_id,
            source_channel=source_channel,
            now=effective_now,
            authorizer=programme_authorizer,
        )
        nested_results.append(started)
        proposal = ProgrammeProposal.objects.select_for_update().get(
            id=started.target_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        current_version = started.resulting_version
        for sequence, (question, value) in enumerate(resolved.answers, start=2):
            answer_result = append_programme_proposal_answer(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                proposal_id=proposal.id,
                question_id=question.id,
                value=value,
                expected_version=current_version,
                reason=reason,
                retry_key=nested_retry_keys[sequence - 1],
                correlation_id=correlation_id,
                source_channel=source_channel,
                now=effective_now,
                authorizer=programme_authorizer,
            )
            nested_results.append(answer_result)
            current_version = answer_result.resulting_version
        item.state = ProgrammeImportItemState.APPLIED
        item.aggregate_version = 2
        item.canonical_payload = None
        item.save(
            update_fields=(
                "state",
                "aggregate_version",
                "canonical_payload",
                "updated_at",
            )
        )
        binding = ProgrammeImportSourceBinding.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            source_system=batch.source_system,
            kind=ProgrammeImportItemKind.PROPOSAL,
            source_key=item.source_key,
            source_digest=item.source_digest,
            item=item,
            call=None,
            proposal=proposal,
            created_by_id=actor_id,
        )
        result, import_receipt = _record_success(
            scope=scope,
            action=ProgrammeImportCommandAction.PROPOSAL_CLAIMED,
            aggregate_kind=ProgrammeImportAggregateKind.ITEM,
            result_kind=ProgrammeImportCommandResultKind.PROPOSAL_BINDING,
            batch=batch,
            item=item,
            source_binding=binding,
            adopted_preview_digest=current_preview_digest,
            expected_version=expected_version,
            resulting_version=2,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("item_state", "private_payload", "proposal_binding"),
            occurred_at=effective_now,
            applied_command_count=len(nested_results),
        )
        for sequence, nested_result in enumerate(nested_results, start=1):
            ProgrammeImportAppliedCommand.objects.create(
                organization_id=organization_id,
                edition_id=edition_id,
                binding=binding,
                import_receipt=import_receipt,
                sequence=sequence,
                programme_receipt_id=nested_result.receipt_id,
            )
    return result


@_audit_import_errors(
    capability_code=APPLICATIONS_DISPOSE_PROGRAMME_IMPORT,
    operation="command.batch_discarded",
)
@transaction.atomic
def discard_programme_import(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    batch_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeImportAuthorizer = _IMPORT_AUTHZ,
) -> ProgrammeImportCommandResult:
    """Dispose every remaining staged payload without deleting domain results.

    Parameters
    ----------
    actor_id : UUID
        Account requesting disposal.
    organization_id : UUID
        Organization that owns the import batch.
    edition_id : UUID
        Edition that owns the import batch.
    batch_id : UUID
        Opaque batch identifier.
    expected_version : int
        Optimistic cursor for the staged batch.
    reason : str
        Inspectable administrative rationale for disposal.
    retry_key : UUID
        Edition-scoped idempotency key for this normalized intent.
    correlation_id : UUID
        Correlation identifier shared by audit and event evidence.
    source_channel : str
        Registered channel through which the command arrived.
    now : datetime | None, default=None
        Optional timezone-aware command time.
    authorizer : ApplicationsProgrammeImportAuthorizer, default=_IMPORT_AUTHZ
        Exact-Edition disposal authorization adapter.

    Returns
    -------
    ProgrammeImportCommandResult
        Opaque batch and receipt identifiers with the disposal cursor.

    Raises
    ------
    ApplicationsProgrammeImportUnavailableError
        If the exact retained batch is absent, foreign, or unavailable.
    ApplicationsProgrammeImportStateConflictError
        If item completeness or state makes safe disposal impossible.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    batch_id = require_programme_uuid(batch_id, field="batch_id")
    retry_key = require_programme_uuid(retry_key, field="retry_key")
    correlation_id = require_programme_uuid(correlation_id, field="correlation_id")
    expected_version = require_programme_expected_version(expected_version)
    reason = _normalize_reason(reason)
    source_channel = _normalize_source_channel(source_channel)
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeImportCommandAction.BATCH_DISCARDED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"batch_id": batch_id},
    )
    replay = _replay(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=digest,
        authorizer=authorizer,
    )
    if replay is not None:
        return replay
    try:
        authorize_programme_import_disposal_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            authorizer=authorizer,
        )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportUnavailableError from error
    owner_department_id = _batch_owner_department_id(
        organization_id=organization_id,
        edition_id=edition_id,
        batch_id=batch_id,
    )
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(owner_department_id,),
    )
    try:
        scope = authorize_programme_import_disposal_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            authorizer=authorizer,
            lock=True,
        )
    except ApplicationsProgrammeImportAuthorizationDeniedError as error:
        raise ApplicationsProgrammeImportUnavailableError from error
    batch = _lock_batch(
        organization_id=organization_id,
        edition_id=edition_id,
        batch_id=batch_id,
    )
    if batch.owner_department_id != owner_department_id:
        raise ApplicationsProgrammeImportUnavailableError
    _require_staged_batch(
        batch,
        expected_version=expected_version,
        effective_now=effective_now,
        allow_expired=True,
    )
    items = list(
        ProgrammeImportItem.objects.select_for_update()
        .filter(batch=batch)
        .order_by("sequence", "id")
    )
    if len(items) != batch.item_count:
        raise ApplicationsProgrammeImportStateConflictError
    with programme_import_database_writer():
        for item in items:
            if item.state == ProgrammeImportItemState.STAGED:
                item.state = ProgrammeImportItemState.DISCARDED
                item.aggregate_version = 2
                item.canonical_payload = None
                item.save(
                    update_fields=(
                        "state",
                        "aggregate_version",
                        "canonical_payload",
                        "updated_at",
                    )
                )
            elif item.state != ProgrammeImportItemState.APPLIED:
                raise ApplicationsProgrammeImportStateConflictError
        batch.state = ProgrammeImportBatchState.DISCARDED
        resulting_version = expected_version + 1
        batch.aggregate_version = resulting_version
        batch.discarded_by_id = actor_id
        batch.discarded_at = effective_now
        batch.discard_reason = reason
        batch.save(
            update_fields=(
                "state",
                "aggregate_version",
                "discarded_by",
                "discarded_at",
                "discard_reason",
                "updated_at",
            )
        )
        result, _receipt = _record_success(
            scope=scope,
            action=ProgrammeImportCommandAction.BATCH_DISCARDED,
            aggregate_kind=ProgrammeImportAggregateKind.BATCH,
            result_kind=ProgrammeImportCommandResultKind.DISCARD,
            batch=batch,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("batch_state", "item_states", "private_payload"),
            occurred_at=effective_now,
        )
    return result


__all__ = [
    "ApplicationsProgrammeImportClaimUnavailableError",
    "ApplicationsProgrammeImportCommandError",
    "ApplicationsProgrammeImportIdempotencyConflictError",
    "ApplicationsProgrammeImportOperationFailedError",
    "ApplicationsProgrammeImportPreviewStaleError",
    "ApplicationsProgrammeImportStateConflictError",
    "ApplicationsProgrammeImportUnavailableError",
    "ApplicationsProgrammeImportVersionConflictError",
    "ProgrammeImportBatchPreview",
    "ProgrammeImportCommandResult",
    "ProgrammeImportPreviewItem",
    "ProgrammeImportProposalClaimAnswer",
    "ProgrammeImportProposalClaimPreview",
    "claim_programme_import_proposal",
    "commit_programme_import_call",
    "discard_programme_import",
    "preview_programme_import",
    "preview_programme_import_proposal_claim",
    "reassign_programme_import_batch",
    "stage_programme_import",
]
