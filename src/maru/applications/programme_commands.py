"""Transactional commands for Applications-owned Programme calls and proposals.

The service is deliberately separate from the generic Applications command
surface.  It is the only runtime writer for the ``programme_item`` target and
keeps every aggregate mutation, receipt, audit record, domain event, and outbox
message in one transaction.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from contextlib import suppress
from dataclasses import asdict, dataclass
from functools import wraps
from typing import TYPE_CHECKING, Any, Final, Protocol, cast
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max, Q
from django.utils import timezone

from maru.applications.answer_values import condition_matches, normalize_answer_value
from maru.applications.models import (
    AnswerSource,
    ApplicationAnswerRevision,
    ApplicationCommandReceipt,
    ApplicationDefinition,
    ApplicationDefinitionStatus,
    ApplicationOwnerDepartment,
    ApplicationQuestion,
    ApplicationSection,
    ApplicationState,
    ApplicationSubmission,
    ApplicationTargetKind,
    ProgrammeCall,
    ProgrammeCallContributorField,
    ProgrammeCallFormat,
    ProgrammeCallTrack,
    ProgrammeCollaboratorState,
    ProgrammeCommandAction,
    ProgrammeCommandAggregateKind,
    ProgrammeCommandReceipt,
    ProgrammeCommandResultKind,
    ProgrammeContributorFieldCode,
    ProgrammeContributorRequirement,
    ProgrammeContributorRole,
    ProgrammeImportCommandReceipt,
    ProgrammeProposal,
    ProgrammeProposalCollaborator,
    ProgrammeProposalCollaboratorTransition,
    ProgrammeProposalContributorProfileRevision,
    ProgrammeProposalRevision,
    ProgrammeProposalRevisionAnswer,
    ProgrammeProposalRevisionContributor,
    ProgrammeProposalRevisionResponse,
    ProgrammeProposalSelectionRevision,
    ProgrammeProposalState,
    ProgrammeReviewReceipt,
    ProgrammeRevisionResponseKind,
)
from maru.applications.programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP,
    APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
    APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    ApplicationsProgrammeAuthorizer,
    AuthorizedProgrammeCallScope,
    AuthorizedProgrammeProposalScope,
    AuthorizedProgrammeRecoveryScope,
    AuthorizedProgrammeSelfEntryScope,
    authorize_programme_call_scope,
    authorize_programme_proposal_scope,
    authorize_programme_recovery_retry_scope,
    authorize_programme_recovery_scope,
    authorize_programme_retry_scope,
    authorize_programme_self_entry_scope,
)
from maru.applications.programme_events import (
    APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
    APPLICATIONS_PROGRAMME_EVENT_SCHEMA_VERSION,
    APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
    programme_call_changed_payload,
    programme_proposal_changed_payload,
)
from maru.applications.programme_inputs import (
    ProgrammeCallConfigurationInput,
    ProgrammeCallDefinitionInput,
    ProgrammeProposalContributorProfileInput,
    ProgrammeProposalInvitationInput,
    ProgrammeProposalRevisionResponseDecision,
    ProgrammeProposalRevisionResponseInput,
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
from maru.applications.programme_writer_boundary import (
    programme_application_database_writer,
)
from maru.applications.retry_namespace import lock_applications_retry_namespace
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.queries import (
    resolve_active_verified_person_reference,
    resolve_active_verified_person_reference_by_email,
)
from maru.workforce.queries import resolve_current_department_reference

_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime

_SOURCE_CHANNEL_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_-]*$")
_MAX_SOURCE_CHANNEL_LENGTH: Final = 32
_CALL_RESULT_KINDS: Final = {
    ProgrammeCommandAction.CALL_CREATED: ProgrammeCommandResultKind.CALL,
    ProgrammeCommandAction.CALL_CONFIGURED: ProgrammeCommandResultKind.CALL,
    ProgrammeCommandAction.CALL_REASSIGNED: ProgrammeCommandResultKind.CALL,
    ProgrammeCommandAction.CALL_ACTIVATED: ProgrammeCommandResultKind.CALL,
    ProgrammeCommandAction.CALL_RETIRED: ProgrammeCommandResultKind.CALL,
    ProgrammeCommandAction.RECOVERY_CALL_REASSIGNED: ProgrammeCommandResultKind.CALL,
    ProgrammeCommandAction.RECOVERY_CALL_RETIRED: ProgrammeCommandResultKind.CALL,
    ProgrammeCommandAction.CALL_SUCCESSOR_CREATED: ProgrammeCommandResultKind.CALL,
}
_APPLICATIONS_PROGRAMME_INPUT_VALIDATION_CODES: Final = frozenset(
    {
        "application_answer_too_large",
        "application_file_unavailable",
        "applications_programme_closed_value_invalid",
        "applications_programme_collaborator_limit_invalid",
        "applications_programme_collection_invalid",
        "applications_programme_collection_order_invalid",
        "applications_programme_condition_dependency_invalid",
        "applications_programme_condition_invalid",
        "applications_programme_condition_semantics_invalid",
        "applications_programme_condition_value_invalid",
        "applications_programme_consent_choice_invalid",
        "applications_programme_contributor_field_unused",
        "applications_programme_control_character",
        "applications_programme_datetime_invalid",
        "applications_programme_duration_order_invalid",
        "applications_programme_email_invalid",
        "applications_programme_hidden_profile_value",
        "applications_programme_input_invalid",
        "applications_programme_invitation_expiry_invalid",
        "applications_programme_lead_public_name_required",
        "applications_programme_length_bound_invalid",
        "applications_programme_maximum_choices_invalid",
        "applications_programme_numeric_bound_invalid",
        "applications_programme_policy_code_invalid",
        "applications_programme_positive_integer_invalid",
        "applications_programme_public_consent_required",
        "applications_programme_publication_choice_invalid",
        "applications_programme_question_classification_invalid",
        "applications_programme_question_graph_invalid",
        "applications_programme_question_options_invalid",
        "applications_programme_reference_kind_invalid",
        "applications_programme_required_choice_invalid",
        "applications_programme_sensitive_policy_required",
        "applications_programme_slug_invalid",
        "applications_programme_text_invalid",
        "applications_programme_unpublished_profile_not_blank",
        "applications_programme_uuid_invalid",
        "applications_programme_value_required",
        "applications_programme_value_too_long",
        "applications_programme_version_invalid",
        "applications_programme_window_order_invalid",
        "invalid_application_address",
        "invalid_application_answer_length",
        "invalid_application_answer_type",
        "invalid_application_boolean",
        "invalid_application_choice",
        "invalid_application_choices",
        "invalid_application_date",
        "invalid_application_decimal",
        "invalid_application_instant",
        "invalid_application_integer",
        "invalid_application_phone",
        "invalid_application_reference",
        "invalid_application_time",
        "invalid_programme_application_source_channel",
        "invalid_programme_requested_duration",
        "unknown_application_question_type",
    }
)


class ApplicationsProgrammeCommandError(RuntimeError):
    """Base class for non-disclosing Programme command failures."""

    reason_code = "applications_programme_command_conflict"


class ApplicationsProgrammeUnavailableError(ApplicationsProgrammeCommandError):
    """Hide absent, foreign-scope, and otherwise unavailable aggregates."""

    reason_code = "applications_programme_unavailable"


class ApplicationsProgrammeStateConflictError(ApplicationsProgrammeCommandError):
    """Signal a lifecycle or relationship conflict without foreign detail."""

    reason_code = "applications_programme_state_conflict"


class ApplicationsProgrammeVersionConflictError(ApplicationsProgrammeCommandError):
    """Signal one stale aggregate cursor."""

    reason_code = "applications_programme_version_conflict"


class ApplicationsProgrammeIdempotencyConflictError(
    ApplicationsProgrammeCommandError,
):
    """Signal retry-key reuse for a different normalized request."""

    reason_code = "applications_programme_idempotency_conflict"


class ApplicationsProgrammeCompletenessError(ApplicationsProgrammeCommandError):
    """Signal a proposal that is not ready for seal or submission."""

    reason_code = "applications_programme_incomplete"


@dataclass(frozen=True, slots=True)
class ProgrammeCommandResult:
    """Return retained evidence and the exact resulting aggregate cursor.

    Attributes
    ----------
    receipt_id : UUID
        Immutable command receipt identifier.
    action : str
        Closed Programme command action.
    definition_id : UUID
        Applications definition affected by the command.
    submission_id : UUID | None
        Applications submission for a proposal command, otherwise ``None``.
    target_id : UUID
        Exact call or proposal-domain result identifier.
    result_kind : str
        Closed result-kind discriminator for ``target_id``.
    resulting_version : int
        Aggregate version after the successful command.
    replayed : bool
        Whether the result came from an exact retained receipt replay.
    """

    receipt_id: UUID
    action: str
    definition_id: UUID
    submission_id: UUID | None
    target_id: UUID
    result_kind: str
    resulting_version: int
    replayed: bool


class _ProgrammeCommandDecorator(Protocol):
    """Preserve any Programme command signature through failure auditing."""

    def __call__[**ParametersT](
        self,
        command: Callable[ParametersT, ProgrammeCommandResult],
    ) -> Callable[ParametersT, ProgrammeCommandResult]: ...


def _safe_audit_uuid(value: object) -> UUID | None:
    return value if isinstance(value, UUID) else None


def _safe_audit_source_channel(value: object) -> str:
    if (
        isinstance(value, str)
        and len(value) <= _MAX_SOURCE_CHANNEL_LENGTH
        and _SOURCE_CHANNEL_PATTERN.fullmatch(value) is not None
    ):
        return value
    return "service"


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


def _failure_reason_code(error: Exception) -> str:
    if isinstance(error, ValidationError):
        codes = _validation_error_codes(error)
        if codes and codes <= _APPLICATIONS_PROGRAMME_INPUT_VALIDATION_CODES:
            return "applications_programme_input_invalid"
        return "applications_programme_dependency_error"
    if isinstance(error, ApplicationsProgrammeCommandError):
        return error.reason_code
    return "applications_programme_dependency_error"


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
    break_glass: bool = False,
) -> None:
    denial = isinstance(error, ApplicationsProgrammeAuthorizationDeniedError)
    safe_correlation_id = _safe_audit_uuid(correlation_id) or uuid4()
    with suppress(Exception):
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=_safe_audit_uuid(actor_id),
                principal_context_id=None,
                organization_id=_safe_audit_uuid(organization_id),
                event_edition_id=_safe_audit_uuid(edition_id),
                capability_code=capability_code,
                operation=f"applications.programme.command.{operation}",
                target_type="applications.programme.scope",
                target_id=None,
                outcome="deny" if denial else "error",
                reason_code=(
                    ApplicationsProgrammeAuthorizationDeniedError.reason_code
                    if denial
                    else _failure_reason_code(error)
                ),
                correlation_id=safe_correlation_id,
                request_id=safe_correlation_id,
                source_channel=_safe_audit_source_channel(source_channel),
                obligations=("audit",),
                break_glass=break_glass,
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="applications-programme-restricted",
            )
        )


def _audit_command_errors(
    *,
    capability_code: str,
    operation: str,
    break_glass: bool = False,
) -> _ProgrammeCommandDecorator:
    """Audit minimized command failures after the atomic mutation rolls back.

    Parameters
    ----------
    capability_code : str
        Capability attempted by the command.
    operation : str
        Stable operation suffix recorded in minimized audit evidence.
    break_glass : bool, default=False
        Whether the attempted command belongs to the closed recovery surface.

    Returns
    -------
    _ProgrammeCommandDecorator
        Decorator that preserves the command signature and return type.
    """

    def decorate[**ParametersT](
        command: Callable[ParametersT, ProgrammeCommandResult],
    ) -> Callable[ParametersT, ProgrammeCommandResult]:
        @wraps(command)
        def wrapped(
            *args: ParametersT.args,
            **kwargs: ParametersT.kwargs,
        ) -> ProgrammeCommandResult:
            try:
                return command(*args, **kwargs)
            except Exception as error:
                _append_failure_audit_best_effort(
                    error=error,
                    actor_id=kwargs.get("actor_id"),
                    organization_id=kwargs.get("organization_id"),
                    edition_id=kwargs.get("edition_id"),
                    capability_code=capability_code,
                    operation=operation,
                    correlation_id=kwargs.get("correlation_id"),
                    source_channel=kwargs.get("source_channel"),
                    break_glass=break_glass,
                )
                raise

        return wrapped

    return decorate


@dataclass(frozen=True, slots=True)
class _AccountIdentifier:
    """Provide only the identifier required by typed answer normalization."""

    id: UUID


def _result(
    receipt: ProgrammeCommandReceipt,
    *,
    replayed: bool,
) -> ProgrammeCommandResult:
    return ProgrammeCommandResult(
        receipt_id=receipt.id,
        action=receipt.action,
        definition_id=cast("UUID", receipt.definition_id),
        submission_id=receipt.submission_id,
        target_id=receipt.target_id,
        result_kind=receipt.result_kind,
        resulting_version=receipt.resulting_version,
        replayed=replayed,
    )


def _common_identifiers(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    reason: str,
) -> tuple[UUID, UUID, UUID, UUID, UUID, str, str]:
    normalized_source = normalized_programme_text(
        source_channel,
        field="source_channel",
        maximum=32,
        required=True,
    )
    if _SOURCE_CHANNEL_PATTERN.fullmatch(normalized_source) is None:
        raise ValidationError(
            {
                "source_channel": ValidationError(
                    "Use a registered lower-case source channel.",
                    code="invalid_programme_application_source_channel",
                )
            },
        )
    normalized_reason = normalized_programme_text(
        reason,
        field="reason",
        maximum=500,
        required=True,
        collapse=True,
    )
    return (
        require_programme_uuid(actor_id, field="actor_id"),
        require_programme_uuid(organization_id, field="organization_id"),
        require_programme_uuid(edition_id, field="edition_id"),
        require_programme_uuid(retry_key, field="retry_key"),
        require_programme_uuid(correlation_id, field="correlation_id"),
        normalized_source,
        normalized_reason,
    )


def _effective_now(value: datetime | None) -> datetime:
    effective = value or timezone.now()
    if not timezone.is_aware(effective):
        raise ValidationError(
            {
                "now": ValidationError(
                    "Use a timezone-aware command time.",
                    code="applications_programme_datetime_invalid",
                )
            },
        )
    return effective


def _request_digest(
    *,
    action: str,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    target_id: UUID | None,
    expected_version: int,
    reason: str,
    source_channel: str,
    values: Mapping[str, object] | None = None,
) -> str:
    payload: dict[str, object] = {
        "action": action,
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "target_id": target_id,
        "expected_version": expected_version,
        "reason": reason,
        "source_channel": source_channel,
        "values": dict(values or {}),
    }
    return canonical_programme_digest(payload)


def _replay(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    retry_key: UUID,
    request_digest: str,
    authorizer: ApplicationsProgrammeAuthorizer,
    recovery: bool = False,
) -> ProgrammeCommandResult | None:
    if recovery:
        authorize_programme_recovery_retry_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            authorizer=authorizer,
        )
    else:
        authorize_programme_retry_scope(
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
        ProgrammeCommandReceipt.objects.select_for_update()
        .filter(
            edition_id=edition_id,
            actor_id=actor_id,
            retry_key=retry_key,
        )
        .first()
    )
    if receipt is not None:
        if receipt.request_digest != request_digest:
            raise ApplicationsProgrammeIdempotencyConflictError
        return _result(receipt, replayed=True)
    if (
        ApplicationCommandReceipt.objects.select_for_update()
        .filter(
            edition_id=edition_id,
            actor_id=actor_id,
            retry_key=retry_key,
        )
        .exists()
        or ProgrammeImportCommandReceipt.objects.select_for_update()
        .filter(
            edition_id=edition_id,
            actor_id=actor_id,
            retry_key=retry_key,
        )
        .exists()
        or ProgrammeReviewReceipt.objects.select_for_update()
        .filter(edition_id=edition_id, actor_id=actor_id, retry_key=retry_key)
        .exists()
    ):
        raise ApplicationsProgrammeIdempotencyConflictError
    return None


def _lock_programme_write_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_ids: tuple[UUID, ...],
) -> None:
    """Acquire the retirement-safe edition scope without exposing misses.

    Parameters
    ----------
    actor_id : UUID
        Exact command actor locked after the Department set.
    organization_id : UUID
        Organization expected to own the entire scope.
    edition_id : UUID
        Exact edition serialized with Workforce retirement.
    department_ids : tuple[UUID, ...]
        Complete source and destination Department identifier set.

    Raises
    ------
    ApplicationsProgrammeUnavailableError
        If any scope component is absent or incoherent.
    """
    try:
        lock_programme_edition_write_scope(
            organization_id=organization_id,
            edition_id=edition_id,
            department_ids=department_ids,
            actor_id=actor_id,
        )
    except ApplicationsProgrammeWriteScopeUnavailableError as error:
        raise ApplicationsProgrammeUnavailableError from error


def _require_version(*, actual: int, expected: int) -> None:
    if actual != expected:
        raise ApplicationsProgrammeVersionConflictError


def _require_private_writes(
    scope: AuthorizedProgrammeCallScope
    | AuthorizedProgrammeProposalScope
    | AuthorizedProgrammeSelfEntryScope,
) -> None:
    if not scope.accepts_private_planning_writes:
        raise ApplicationsProgrammeStateConflictError


def _idempotency_hash(retry_key: UUID) -> str:
    return hashlib.sha256(str(retry_key).lower().encode("ascii")).hexdigest()


def _record_success(
    *,
    scope: AuthorizedProgrammeCallScope
    | AuthorizedProgrammeProposalScope
    | AuthorizedProgrammeRecoveryScope
    | AuthorizedProgrammeSelfEntryScope,
    action: ProgrammeCommandAction,
    definition: ApplicationDefinition,
    target_id: UUID,
    result_kind: ProgrammeCommandResultKind | str,
    expected_version: int,
    resulting_version: int,
    request_digest: str,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    changed_fields: tuple[str, ...],
    call: ProgrammeCall | None = None,
    proposal: ProgrammeProposal | None = None,
    submission: ApplicationSubmission | None = None,
    source_department_id: UUID | None = None,
    destination_department_id: UUID | None = None,
    capability_code: str | None = None,
    break_glass: bool = False,
    occurred_at: datetime,
) -> ProgrammeCommandResult:
    aggregate_kind = (
        ProgrammeCommandAggregateKind.PROPOSAL
        if submission is not None
        else ProgrammeCommandAggregateKind.CALL
    )
    receipt = ProgrammeCommandReceipt.objects.create(
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
        definition=definition,
        submission=submission,
        source_department_id=source_department_id,
        destination_department_id=destination_department_id,
        target_id=target_id,
        result_kind=result_kind,
        expected_version=expected_version,
        resulting_version=resulting_version,
    )
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=capability_code
            or (
                APPLICATIONS_MANAGE_PROGRAMME_CALLS
                if submission is None
                else _capability_for_action(action)
            ),
            operation=f"applications.programme.command.{action}",
            target_type=(
                "applications.programme_proposal"
                if submission is not None
                else "applications.programme_call"
            ),
            target_id=(
                proposal.id if proposal is not None else cast("ProgrammeCall", call).id
            ),
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            changed_fields=changed_fields,
            idempotency_key_hash=_idempotency_hash(retry_key),
            break_glass=break_glass,
            retention_class="applications-programme-restricted",
        ),
        occurred_at=occurred_at,
    )
    if submission is None:
        current_call = cast("ProgrammeCall", call)
        publish_domain_event(
            DomainEventRecord(
                event_name=APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT,
                schema_version=APPLICATIONS_PROGRAMME_EVENT_SCHEMA_VERSION,
                organization_id=scope.organization_id,
                event_edition_id=scope.edition_id,
                aggregate_type="applications.programme_call",
                aggregate_id=current_call.id,
                aggregate_version=resulting_version,
                payload=programme_call_changed_payload(
                    action=action,
                    call_id=current_call.id,
                    lifecycle=definition.status,
                    resulting_version=resulting_version,
                ),
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor_kind="account",
                actor_id=scope.actor_id,
                retention_class="applications-programme-restricted",
            ),
            occurred_at=occurred_at,
        )
    else:
        current_proposal = cast("ProgrammeProposal", proposal)
        publish_domain_event(
            DomainEventRecord(
                event_name=APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT,
                schema_version=APPLICATIONS_PROGRAMME_EVENT_SCHEMA_VERSION,
                organization_id=scope.organization_id,
                event_edition_id=scope.edition_id,
                aggregate_type="applications.programme_proposal",
                aggregate_id=current_proposal.id,
                aggregate_version=resulting_version,
                payload=programme_proposal_changed_payload(
                    action=action,
                    proposal_id=current_proposal.id,
                    state=current_proposal.state,
                    resulting_version=resulting_version,
                ),
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor_kind="account",
                actor_id=scope.actor_id,
                retention_class="applications-programme-restricted",
            ),
            occurred_at=occurred_at,
        )
    return _result(receipt, replayed=False)


def _capability_for_action(action: ProgrammeCommandAction) -> str:
    if action in {
        ProgrammeCommandAction.PROPOSAL_STARTED,
        ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
        ProgrammeCommandAction.CONTRIBUTOR_PROFILE_REVISED,
        ProgrammeCommandAction.REVISION_ACKNOWLEDGED,
        ProgrammeCommandAction.REVISION_DECLINED,
        ProgrammeCommandAction.COLLABORATOR_LEFT,
    }:
        return APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF
    if action in {
        ProgrammeCommandAction.COLLABORATOR_ACCEPTED,
        ProgrammeCommandAction.COLLABORATOR_DECLINED,
    }:
        return APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF
    if action in {
        ProgrammeCommandAction.PROPOSAL_SUBMITTED,
        ProgrammeCommandAction.PROPOSAL_WITHDRAWN,
    }:
        return APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF
    return APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF


def _locked_call(
    *,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    owner_department_id: UUID,
) -> ProgrammeCall:
    call = (
        ProgrammeCall.objects.select_for_update()
        .select_related("definition")
        .filter(
            id=call_id,
            organization_id=organization_id,
            edition_id=edition_id,
            owner_department_id=owner_department_id,
            definition__organization_id=organization_id,
            definition__edition_id=edition_id,
            definition__target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
        )
        .first()
    )
    if call is None:
        raise ApplicationsProgrammeUnavailableError
    return call


def _definition_values(definition: ProgrammeCallDefinitionInput) -> dict[str, object]:
    return cast("dict[str, object]", asdict(definition))


def _configuration_values(
    configuration: ProgrammeCallConfigurationInput,
) -> dict[str, object]:
    return cast("dict[str, object]", asdict(configuration))


def _create_definition_graph(
    *,
    scope: AuthorizedProgrammeCallScope,
    definition_input: ProgrammeCallDefinitionInput,
    configuration: ProgrammeCallConfigurationInput,
    version: int,
) -> tuple[ApplicationDefinition, ProgrammeCall]:
    definition = ApplicationDefinition.objects.create(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        code=definition_input.code,
        version=version,
        aggregate_version=1,
        status=ApplicationDefinitionStatus.DRAFT,
        target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
        name=definition_input.name,
        description=definition_input.description,
        purpose=definition_input.purpose,
        classification=definition_input.classification,
        eligibility_kind=definition_input.eligibility_kind,
        max_submissions_per_person=definition_input.maximum_submissions_per_person,
        opens_at=definition_input.opens_at,
        closes_at=definition_input.closes_at,
        applicant_edit_until=definition_input.applicant_edit_until,
        minimum_age=definition_input.minimum_age,
        audience_policy_code=definition_input.audience_policy_code,
        retention_policy_code=definition_input.retention_policy_code,
        age_policy_code="",
        created_by_id=scope.actor_id,
    )
    call = ProgrammeCall.objects.create(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        definition=definition,
        owner_department_id=configuration.owner_department_id,
        max_collaborators=configuration.maximum_collaborators,
        content_policy_code=configuration.content_policy_code,
        contributor_consent_policy_code=(configuration.contributor_consent_policy_code),
        collaboration_retention_policy_code=(
            configuration.collaboration_retention_policy_code
        ),
    )
    ApplicationOwnerDepartment.objects.create(
        definition=definition,
        department_id=configuration.owner_department_id,
    )
    _replace_definition_children(
        definition=definition,
        call=call,
        definition_input=definition_input,
        configuration=configuration,
    )
    return definition, call


def _replace_definition_children(
    *,
    definition: ApplicationDefinition,
    call: ProgrammeCall,
    definition_input: ProgrammeCallDefinitionInput,
    configuration: ProgrammeCallConfigurationInput,
) -> None:
    definition.questions.all().delete()
    definition.sections.all().delete()
    call.tracks.all().delete()
    call.formats.all().delete()
    call.contributor_fields.all().delete()
    for section_input in definition_input.sections:
        section = ApplicationSection.objects.create(
            definition=definition,
            key=section_input.key,
            title=section_input.title,
            help_text=section_input.help_text,
            position=section_input.position,
        )
        for question_input in section_input.questions:
            ApplicationQuestion.objects.create(
                definition=definition,
                section=section,
                key=question_input.key,
                field_type=question_input.field_type,
                label=question_input.label,
                help_text=question_input.help_text,
                position=question_input.position,
                required=question_input.required,
                options=[asdict(option) for option in question_input.options],
                minimum_length=question_input.minimum_length,
                maximum_length=question_input.maximum_length,
                minimum_value=question_input.minimum_value,
                maximum_value=question_input.maximum_value,
                maximum_choices=question_input.maximum_choices,
                reference_kind=question_input.reference_kind,
                source_binding=question_input.source_binding,
                condition=(
                    asdict(question_input.condition)
                    if question_input.condition is not None
                    else {}
                ),
                purpose=question_input.purpose,
                classification=question_input.classification,
                applicant_visible=question_input.applicant_visible,
                applicant_writable=question_input.applicant_writable,
                staff_visible=question_input.staff_visible,
                staff_writable=question_input.staff_writable,
                reviewer_visible=question_input.reviewer_visible,
                public_after_approval=question_input.public_after_approval,
                api_projection=question_input.api_projection,
                retention_policy_code=question_input.retention_policy_code,
            )
    for track in configuration.tracks:
        ProgrammeCallTrack.objects.create(
            organization_id=definition.organization_id,
            edition_id=definition.edition_id,
            call=call,
            code=track.code,
            label=track.label,
            description=track.description,
            position=track.position,
        )
    for programme_format in configuration.formats:
        ProgrammeCallFormat.objects.create(
            organization_id=definition.organization_id,
            edition_id=definition.edition_id,
            call=call,
            code=programme_format.code,
            label=programme_format.label,
            description=programme_format.description,
            position=programme_format.position,
            min_duration_minutes=programme_format.minimum_duration_minutes,
            default_duration_minutes=programme_format.default_duration_minutes,
            max_duration_minutes=programme_format.maximum_duration_minutes,
        )
    for field in configuration.contributor_fields:
        ProgrammeCallContributorField.objects.create(
            organization_id=definition.organization_id,
            edition_id=definition.edition_id,
            call=call,
            field_code=field.field_code,
            lead_requirement=field.lead_requirement,
            collaborator_requirement=field.collaborator_requirement,
            position=field.position,
        )


def _update_definition_values(
    *,
    definition: ApplicationDefinition,
    call: ProgrammeCall,
    definition_input: ProgrammeCallDefinitionInput,
    configuration: ProgrammeCallConfigurationInput,
    resulting_version: int,
) -> None:
    if definition_input.code != definition.code:
        raise ApplicationsProgrammeStateConflictError
    definition.name = definition_input.name
    definition.description = definition_input.description
    definition.purpose = definition_input.purpose
    definition.classification = definition_input.classification
    definition.eligibility_kind = definition_input.eligibility_kind
    definition.max_submissions_per_person = (
        definition_input.maximum_submissions_per_person
    )
    definition.opens_at = definition_input.opens_at
    definition.closes_at = definition_input.closes_at
    definition.applicant_edit_until = definition_input.applicant_edit_until
    definition.minimum_age = definition_input.minimum_age
    definition.audience_policy_code = definition_input.audience_policy_code
    definition.retention_policy_code = definition_input.retention_policy_code
    definition.age_policy_code = ""
    definition.aggregate_version = resulting_version
    definition.save()
    call.max_collaborators = configuration.maximum_collaborators
    call.content_policy_code = configuration.content_policy_code
    call.contributor_consent_policy_code = configuration.contributor_consent_policy_code
    call.collaboration_retention_policy_code = (
        configuration.collaboration_retention_policy_code
    )
    call.save()
    _replace_definition_children(
        definition=definition,
        call=call,
        definition_input=definition_input,
        configuration=configuration,
    )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    operation=ProgrammeCommandAction.CALL_CREATED,
)
@transaction.atomic
def create_programme_call(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    definition_input: ProgrammeCallDefinitionInput,
    configuration: ProgrammeCallConfigurationInput,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Create a complete draft call from one typed immutable form graph.

    Parameters
    ----------
    actor_id : UUID
        Exact current call-manager account identifier.
    organization_id : UUID
        Organization expected to own the call.
    edition_id : UUID
        Exact event edition identifier.
    definition_input : ProgrammeCallDefinitionInput
        Typed definition metadata and immutable question graph.
    configuration : ProgrammeCallConfigurationInput
        Typed tracks, formats, and contributor-field configuration.
    expected_version : int
        Required initial aggregate version, which must be zero.
    reason : str
        Inspectable administrative rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for deterministic tests.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and resulting call cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the requested call code cannot begin a new lineage.
    ApplicationsProgrammeVersionConflictError
        If the initial expected version is not zero.
    ValidationError
        If the typed definition graph or configuration is invalid.
    """
    (
        actor_id,
        organization_id,
        edition_id,
        retry_key,
        correlation_id,
        source_channel,
        reason,
    ) = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    expected_version = require_programme_expected_version(expected_version)
    if expected_version != 0:
        raise ApplicationsProgrammeVersionConflictError
    if not isinstance(definition_input, ProgrammeCallDefinitionInput) or not isinstance(
        configuration,
        ProgrammeCallConfigurationInput,
    ):
        raise ValidationError(
            "Programme call commands require closed typed inputs.",
            code="applications_programme_input_invalid",
        )
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.CALL_CREATED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=None,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={
            "definition": _definition_values(definition_input),
            "configuration": _configuration_values(configuration),
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
    scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=configuration.owner_department_id,
        authorizer=authorizer,
    )
    _require_private_writes(scope)
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(configuration.owner_department_id,),
    )
    scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=configuration.owner_department_id,
        authorizer=authorizer,
        lock=True,
    )
    _require_private_writes(scope)
    if (
        ApplicationDefinition.objects.select_for_update()
        .filter(
            edition_id=edition_id,
            code=definition_input.code,
        )
        .exists()
    ):
        raise ApplicationsProgrammeStateConflictError
    with programme_application_database_writer():
        definition, call = _create_definition_graph(
            scope=scope,
            definition_input=definition_input,
            configuration=configuration,
            version=1,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.CALL_CREATED,
            definition=definition,
            call=call,
            target_id=call.id,
            result_kind=ProgrammeCommandResultKind.CALL,
            expected_version=0,
            resulting_version=1,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=(
                "definition",
                "owner",
                "sections",
                "questions",
                "tracks",
                "formats",
                "contributor_fields",
            ),
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    operation=ProgrammeCommandAction.CALL_CONFIGURED,
)
@transaction.atomic
def configure_programme_call(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    owner_department_id: UUID,
    definition_input: ProgrammeCallDefinitionInput,
    configuration: ProgrammeCallConfigurationInput,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Replace the complete configuration of one exact draft call.

    Parameters
    ----------
    actor_id : UUID
        Exact current call-manager account identifier.
    organization_id : UUID
        Organization expected to own the call.
    edition_id : UUID
        Exact event edition identifier.
    call_id : UUID
        Exact Programme call identifier.
    owner_department_id : UUID
        Exact current owner Department identifier.
    definition_input : ProgrammeCallDefinitionInput
        Replacement definition metadata and immutable question graph.
    configuration : ProgrammeCallConfigurationInput
        Replacement tracks, formats, and contributor fields.
    expected_version : int
        Optimistic call aggregate version.
    reason : str
        Inspectable administrative rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for deterministic tests.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and resulting call cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the call is not an editable draft.
    ValidationError
        If the replacement graph or stored call shape is invalid.
    """
    (
        actor_id,
        organization_id,
        edition_id,
        retry_key,
        correlation_id,
        source_channel,
        reason,
    ) = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    call_id = require_programme_uuid(call_id, field="call_id")
    owner_department_id = require_programme_uuid(
        owner_department_id,
        field="owner_department_id",
    )
    expected_version = require_programme_expected_version(expected_version)
    if not isinstance(definition_input, ProgrammeCallDefinitionInput) or not isinstance(
        configuration,
        ProgrammeCallConfigurationInput,
    ):
        raise ValidationError(
            "Programme call commands require closed typed inputs.",
            code="applications_programme_input_invalid",
        )
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.CALL_CONFIGURED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=call_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={
            "current_owner_department_id": owner_department_id,
            "definition": _definition_values(definition_input),
            "configuration": _configuration_values(configuration),
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
    if configuration.owner_department_id != owner_department_id:
        raise ApplicationsProgrammeStateConflictError
    old_scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=owner_department_id,
        authorizer=authorizer,
    )
    _require_private_writes(old_scope)
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(owner_department_id,),
    )
    old_scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=owner_department_id,
        authorizer=authorizer,
        lock=True,
    )
    _require_private_writes(old_scope)
    call = _locked_call(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
        owner_department_id=owner_department_id,
    )
    definition = call.definition
    _require_version(actual=definition.aggregate_version, expected=expected_version)
    if definition.status != ApplicationDefinitionStatus.DRAFT:
        raise ApplicationsProgrammeStateConflictError
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        _update_definition_values(
            definition=definition,
            call=call,
            definition_input=definition_input,
            configuration=configuration,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=old_scope,
            action=ProgrammeCommandAction.CALL_CONFIGURED,
            definition=definition,
            call=call,
            target_id=call.id,
            result_kind=ProgrammeCommandResultKind.CALL,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=(
                "definition",
                "sections",
                "questions",
                "tracks",
                "formats",
                "contributor_fields",
            ),
            occurred_at=effective_now,
        )


def _locked_call_owner_link(
    *,
    definition_id: UUID,
    source_department_id: UUID,
) -> ApplicationOwnerDepartment:
    owner_link = (
        ApplicationOwnerDepartment.objects.select_for_update()
        .filter(
            definition_id=definition_id,
            department_id=source_department_id,
        )
        .first()
    )
    if owner_link is None:
        raise ApplicationsProgrammeUnavailableError
    return owner_link


def _apply_call_reassignment(
    *,
    call: ProgrammeCall,
    owner_link: ApplicationOwnerDepartment,
    destination_department_id: UUID,
    resulting_version: int,
) -> None:
    definition = call.definition
    call.owner_department_id = destination_department_id
    call.save(update_fields=("owner_department", "updated_at"))
    owner_link.department_id = destination_department_id
    owner_link.save(update_fields=("department", "updated_at"))
    definition.aggregate_version = resulting_version
    definition.save(update_fields=("aggregate_version", "updated_at"))


def _require_orphaned_source_department(
    *,
    organization_id: UUID,
    edition_id: UUID,
    source_department_id: UUID,
) -> None:
    if (
        resolve_current_department_reference(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=source_department_id,
        )
        is not None
    ):
        raise ApplicationsProgrammeStateConflictError


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    operation=ProgrammeCommandAction.CALL_REASSIGNED,
)
@transaction.atomic
def reassign_programme_call(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    source_department_id: UUID,
    destination_department_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Move one draft call between two exact current Departments.

    The dedicated command is the only ordinary ownership-transition path.
    Both Departments require current exact-scope call-management authority,
    and the shared edition mutex serializes the transition with Workforce
    retirement before any Applications aggregate row is locked.

    Parameters
    ----------
    actor_id : UUID
        Exact current call-manager account identifier.
    organization_id : UUID
        Organization expected to own the call and both Departments.
    edition_id : UUID
        Exact private-planning edition containing the call.
    call_id : UUID
        Opaque draft-call identifier supplied by the caller.
    source_department_id : UUID
        Exact current Department expected to own the call.
    destination_department_id : UUID
        Exact current Department that will receive the call.
    expected_version : int
        Optimistic call aggregate version.
    reason : str
        Inspectable administrative rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for deterministic tests.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained transition receipt and resulting call cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the Departments match or the call is not an editable draft.
    """
    common = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    actor_id, organization_id, edition_id = common[:3]
    retry_key, correlation_id, source_channel, reason = common[3:]
    call_id = require_programme_uuid(call_id, field="call_id")
    source_department_id = require_programme_uuid(
        source_department_id,
        field="source_department_id",
    )
    destination_department_id = require_programme_uuid(
        destination_department_id,
        field="destination_department_id",
    )
    expected_version = require_programme_expected_version(expected_version)
    if source_department_id == destination_department_id:
        raise ApplicationsProgrammeStateConflictError
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.CALL_REASSIGNED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=call_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={
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
    scopes: dict[UUID, AuthorizedProgrammeCallScope] = {}
    for department_id in department_ids:
        scopes[department_id] = authorize_programme_call_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            authorizer=authorizer,
        )
        _require_private_writes(scopes[department_id])
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=department_ids,
    )
    for department_id in department_ids:
        scopes[department_id] = authorize_programme_call_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            authorizer=authorizer,
            lock=True,
        )
        _require_private_writes(scopes[department_id])

    call = _locked_call(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
        owner_department_id=source_department_id,
    )
    definition = call.definition
    _require_version(actual=definition.aggregate_version, expected=expected_version)
    if definition.status != ApplicationDefinitionStatus.DRAFT:
        raise ApplicationsProgrammeStateConflictError
    owner_link = _locked_call_owner_link(
        definition_id=definition.id,
        source_department_id=source_department_id,
    )
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        _apply_call_reassignment(
            call=call,
            owner_link=owner_link,
            destination_department_id=destination_department_id,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scopes[source_department_id],
            action=ProgrammeCommandAction.CALL_REASSIGNED,
            definition=definition,
            call=call,
            target_id=call.id,
            result_kind=ProgrammeCommandResultKind.CALL,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("owner_department", "aggregate_version"),
            source_department_id=source_department_id,
            destination_department_id=destination_department_id,
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP,
    operation=ProgrammeCommandAction.RECOVERY_CALL_REASSIGNED,
    break_glass=True,
)
@transaction.atomic
def recover_orphaned_programme_call_reassignment(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    source_department_id: UUID,
    destination_department_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Recover one exact orphaned draft by assigning a current Department.

    Recovery is lifecycle-neutral and exact-ID-only. The caller must prove the
    dormant Edition-scoped break-glass capability as well as ordinary current
    call-management authority for the destination. No list, search, preview,
    or Programme-content authority is introduced by this command.

    Parameters
    ----------
    actor_id : UUID
        Exact recovery-operator account identifier.
    organization_id : UUID
        Organization expected to own the call and both Departments.
    edition_id : UUID
        Exact edition containing the caller-supplied orphan target.
    call_id : UUID
        Opaque draft-call identifier supplied by the caller.
    source_department_id : UUID
        Exact retired Department expected to own the orphaned call.
    destination_department_id : UUID
        Exact current Department that will receive the call.
    expected_version : int
        Optimistic call aggregate version.
    reason : str
        Inspectable break-glass rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for deterministic tests.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed recovery and destination-authority adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained break-glass transition receipt and resulting call cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the source is current, the Departments match, or the call is not a
        draft.
    """
    common = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    actor_id, organization_id, edition_id = common[:3]
    retry_key, correlation_id, source_channel, reason = common[3:]
    call_id = require_programme_uuid(call_id, field="call_id")
    source_department_id = require_programme_uuid(
        source_department_id,
        field="source_department_id",
    )
    destination_department_id = require_programme_uuid(
        destination_department_id,
        field="destination_department_id",
    )
    expected_version = require_programme_expected_version(expected_version)
    if source_department_id == destination_department_id:
        raise ApplicationsProgrammeStateConflictError
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.RECOVERY_CALL_REASSIGNED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=call_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={
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
        recovery=True,
    )
    if replay is not None:
        return replay

    recovery_scope = authorize_programme_recovery_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )
    authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=destination_department_id,
        authorizer=authorizer,
    )
    department_ids = tuple(sorted((source_department_id, destination_department_id)))
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=department_ids,
    )
    recovery_scope = authorize_programme_recovery_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
        lock=True,
    )
    authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=destination_department_id,
        authorizer=authorizer,
        lock=True,
    )
    _require_orphaned_source_department(
        organization_id=organization_id,
        edition_id=edition_id,
        source_department_id=source_department_id,
    )
    call = _locked_call(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
        owner_department_id=source_department_id,
    )
    definition = call.definition
    _require_version(actual=definition.aggregate_version, expected=expected_version)
    if definition.status != ApplicationDefinitionStatus.DRAFT:
        raise ApplicationsProgrammeStateConflictError
    owner_link = _locked_call_owner_link(
        definition_id=definition.id,
        source_department_id=source_department_id,
    )
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        _apply_call_reassignment(
            call=call,
            owner_link=owner_link,
            destination_department_id=destination_department_id,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=recovery_scope,
            action=ProgrammeCommandAction.RECOVERY_CALL_REASSIGNED,
            definition=definition,
            call=call,
            target_id=call.id,
            result_kind=ProgrammeCommandResultKind.CALL,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("owner_department", "aggregate_version"),
            source_department_id=source_department_id,
            destination_department_id=destination_department_id,
            capability_code=APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP,
            break_glass=True,
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP,
    operation=ProgrammeCommandAction.RECOVERY_CALL_RETIRED,
    break_glass=True,
)
@transaction.atomic
def recover_orphaned_programme_call_retirement(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    source_department_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Retire one exact active call orphaned by historical Department state.

    Parameters
    ----------
    actor_id : UUID
        Exact recovery-operator account identifier.
    organization_id : UUID
        Organization expected to own the call and Department.
    edition_id : UUID
        Exact edition containing the caller-supplied orphan target.
    call_id : UUID
        Opaque active-call identifier supplied by the caller.
    source_department_id : UUID
        Exact retired Department expected to own the orphaned call.
    expected_version : int
        Optimistic call aggregate version.
    reason : str
        Inspectable break-glass rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for deterministic tests.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed recovery-capability adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained break-glass retirement receipt and resulting call cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the source is current or the call is not active.
    """
    common = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    actor_id, organization_id, edition_id = common[:3]
    retry_key, correlation_id, source_channel, reason = common[3:]
    call_id = require_programme_uuid(call_id, field="call_id")
    source_department_id = require_programme_uuid(
        source_department_id,
        field="source_department_id",
    )
    expected_version = require_programme_expected_version(expected_version)
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.RECOVERY_CALL_RETIRED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=call_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"source_department_id": source_department_id},
    )
    replay = _replay(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        request_digest=digest,
        authorizer=authorizer,
        recovery=True,
    )
    if replay is not None:
        return replay

    recovery_scope = authorize_programme_recovery_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
    )
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(source_department_id,),
    )
    recovery_scope = authorize_programme_recovery_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        authorizer=authorizer,
        lock=True,
    )
    _require_orphaned_source_department(
        organization_id=organization_id,
        edition_id=edition_id,
        source_department_id=source_department_id,
    )
    call = _locked_call(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
        owner_department_id=source_department_id,
    )
    definition = call.definition
    _require_version(actual=definition.aggregate_version, expected=expected_version)
    if definition.status != ApplicationDefinitionStatus.ACTIVE:
        raise ApplicationsProgrammeStateConflictError
    definition.status = ApplicationDefinitionStatus.RETIRED
    definition.retired_at = effective_now
    definition.retired_by_id = actor_id
    resulting_version = expected_version + 1
    definition.aggregate_version = resulting_version
    with programme_application_database_writer():
        definition.save()
        return _record_success(
            scope=recovery_scope,
            action=ProgrammeCommandAction.RECOVERY_CALL_RETIRED,
            definition=definition,
            call=call,
            target_id=call.id,
            result_kind=ProgrammeCommandResultKind.CALL,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=(
                "status",
                "retired_at",
                "retired_by",
                "aggregate_version",
            ),
            source_department_id=source_department_id,
            capability_code=APPLICATIONS_RECOVER_PROGRAMME_DEPARTMENT_OWNERSHIP,
            break_glass=True,
            occurred_at=effective_now,
        )


def _call_lifecycle_command(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    owner_department_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    action: ProgrammeCommandAction,
    effective_now: datetime,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> ProgrammeCommandResult:
    digest = _request_digest(
        action=action,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=call_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
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
    scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=owner_department_id,
        authorizer=authorizer,
    )
    _require_private_writes(scope)
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(owner_department_id,),
    )
    scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=owner_department_id,
        authorizer=authorizer,
        lock=True,
    )
    _require_private_writes(scope)
    call = _locked_call(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
        owner_department_id=owner_department_id,
    )
    definition = call.definition
    _require_version(actual=definition.aggregate_version, expected=expected_version)
    if action == ProgrammeCommandAction.CALL_ACTIVATED:
        if definition.status != ApplicationDefinitionStatus.DRAFT:
            raise ApplicationsProgrammeStateConflictError
        definition.status = ApplicationDefinitionStatus.ACTIVE
        definition.activated_at = effective_now
        definition.activated_by_id = actor_id
        changed_fields = ("status", "activated_at", "activated_by")
    elif action == ProgrammeCommandAction.CALL_RETIRED:
        if definition.status != ApplicationDefinitionStatus.ACTIVE:
            raise ApplicationsProgrammeStateConflictError
        definition.status = ApplicationDefinitionStatus.RETIRED
        definition.retired_at = effective_now
        definition.retired_by_id = actor_id
        changed_fields = ("status", "retired_at", "retired_by")
    else:
        raise RuntimeError("Unregistered Programme call lifecycle action.")
    resulting_version = expected_version + 1
    definition.aggregate_version = resulting_version
    with programme_application_database_writer():
        definition.save()
        return _record_success(
            scope=scope,
            action=action,
            definition=definition,
            call=call,
            target_id=call.id,
            result_kind=_CALL_RESULT_KINDS[action],
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=changed_fields,
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    operation=ProgrammeCommandAction.CALL_ACTIVATED,
)
@transaction.atomic
def activate_programme_call(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    owner_department_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Activate one complete draft without publishing or mounting it.

    Parameters
    ----------
    actor_id : UUID
        Exact current call-manager account identifier.
    organization_id : UUID
        Organization expected to own the call.
    edition_id : UUID
        Exact event edition identifier.
    call_id : UUID
        Exact Programme call identifier.
    owner_department_id : UUID
        Exact current owner Department identifier.
    expected_version : int
        Optimistic call aggregate version.
    reason : str
        Inspectable administrative rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for deterministic tests.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and resulting active-call cursor.
    """
    common = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    return _call_lifecycle_command(
        actor_id=common[0],
        organization_id=common[1],
        edition_id=common[2],
        retry_key=common[3],
        correlation_id=common[4],
        source_channel=common[5],
        reason=common[6],
        call_id=require_programme_uuid(call_id, field="call_id"),
        owner_department_id=require_programme_uuid(
            owner_department_id,
            field="owner_department_id",
        ),
        expected_version=require_programme_expected_version(expected_version),
        action=ProgrammeCommandAction.CALL_ACTIVATED,
        effective_now=_effective_now(now),
        authorizer=authorizer,
    )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    operation=ProgrammeCommandAction.CALL_RETIRED,
)
@transaction.atomic
def retire_programme_call(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    owner_department_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Retire one active call while preserving its immutable configuration.

    Parameters
    ----------
    actor_id : UUID
        Exact current call-manager account identifier.
    organization_id : UUID
        Organization expected to own the call.
    edition_id : UUID
        Exact event edition identifier.
    call_id : UUID
        Exact Programme call identifier.
    owner_department_id : UUID
        Exact current owner Department identifier.
    expected_version : int
        Optimistic call aggregate version.
    reason : str
        Inspectable administrative rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for deterministic tests.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and resulting retired-call cursor.
    """
    common = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    return _call_lifecycle_command(
        actor_id=common[0],
        organization_id=common[1],
        edition_id=common[2],
        retry_key=common[3],
        correlation_id=common[4],
        source_channel=common[5],
        reason=common[6],
        call_id=require_programme_uuid(call_id, field="call_id"),
        owner_department_id=require_programme_uuid(
            owner_department_id,
            field="owner_department_id",
        ),
        expected_version=require_programme_expected_version(expected_version),
        action=ProgrammeCommandAction.CALL_RETIRED,
        effective_now=_effective_now(now),
        authorizer=authorizer,
    )


def _copy_call_graph(
    *,
    scope: AuthorizedProgrammeCallScope,
    source: ProgrammeCall,
    version: int,
) -> tuple[ApplicationDefinition, ProgrammeCall]:
    source_definition = source.definition
    successor = ApplicationDefinition.objects.create(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        code=source_definition.code,
        version=version,
        aggregate_version=1,
        status=ApplicationDefinitionStatus.DRAFT,
        target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
        name=source_definition.name,
        description=source_definition.description,
        purpose=source_definition.purpose,
        classification=source_definition.classification,
        eligibility_kind=source_definition.eligibility_kind,
        max_submissions_per_person=source_definition.max_submissions_per_person,
        opens_at=source_definition.opens_at,
        closes_at=source_definition.closes_at,
        applicant_edit_until=source_definition.applicant_edit_until,
        minimum_age=source_definition.minimum_age,
        audience_policy_code=source_definition.audience_policy_code,
        retention_policy_code=source_definition.retention_policy_code,
        age_policy_code="",
        created_by_id=scope.actor_id,
    )
    successor_call = ProgrammeCall.objects.create(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        definition=successor,
        owner_department_id=source.owner_department_id,
        max_collaborators=source.max_collaborators,
        content_policy_code=source.content_policy_code,
        contributor_consent_policy_code=source.contributor_consent_policy_code,
        collaboration_retention_policy_code=(
            source.collaboration_retention_policy_code
        ),
    )
    ApplicationOwnerDepartment.objects.create(
        definition=successor,
        department_id=source.owner_department_id,
    )
    section_map: dict[UUID, ApplicationSection] = {}
    for section in source_definition.sections.order_by("position", "id"):
        section_map[section.id] = ApplicationSection.objects.create(
            definition=successor,
            key=section.key,
            title=section.title,
            help_text=section.help_text,
            position=section.position,
        )
    for question in source_definition.questions.order_by(
        "section__position",
        "position",
        "id",
    ):
        ApplicationQuestion.objects.create(
            definition=successor,
            section=section_map[question.section_id],
            key=question.key,
            field_type=question.field_type,
            label=question.label,
            help_text=question.help_text,
            position=question.position,
            required=question.required,
            options=question.options,
            minimum_length=question.minimum_length,
            maximum_length=question.maximum_length,
            minimum_value=question.minimum_value,
            maximum_value=question.maximum_value,
            maximum_choices=question.maximum_choices,
            reference_kind=question.reference_kind,
            source_binding=question.source_binding,
            condition=question.condition,
            purpose=question.purpose,
            classification=question.classification,
            applicant_visible=question.applicant_visible,
            applicant_writable=question.applicant_writable,
            staff_visible=question.staff_visible,
            staff_writable=question.staff_writable,
            reviewer_visible=question.reviewer_visible,
            public_after_approval=question.public_after_approval,
            api_projection=question.api_projection,
            retention_policy_code=question.retention_policy_code,
        )
    for track in source.tracks.order_by("position", "code", "id"):
        ProgrammeCallTrack.objects.create(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            call=successor_call,
            code=track.code,
            label=track.label,
            description=track.description,
            position=track.position,
        )
    for programme_format in source.formats.order_by("position", "code", "id"):
        ProgrammeCallFormat.objects.create(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            call=successor_call,
            code=programme_format.code,
            label=programme_format.label,
            description=programme_format.description,
            position=programme_format.position,
            min_duration_minutes=programme_format.min_duration_minutes,
            default_duration_minutes=programme_format.default_duration_minutes,
            max_duration_minutes=programme_format.max_duration_minutes,
        )
    for field in source.contributor_fields.order_by("position", "field_code", "id"):
        ProgrammeCallContributorField.objects.create(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            call=successor_call,
            field_code=field.field_code,
            lead_requirement=field.lead_requirement,
            collaborator_requirement=field.collaborator_requirement,
            position=field.position,
        )
    return successor, successor_call


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    operation=ProgrammeCommandAction.CALL_SUCCESSOR_CREATED,
)
@transaction.atomic
def create_programme_call_successor(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    owner_department_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Copy one retired call into its exact independent successor draft.

    Parameters
    ----------
    actor_id : UUID
        Exact current call-manager account identifier.
    organization_id : UUID
        Organization expected to own the call lineage.
    edition_id : UUID
        Exact event edition identifier.
    call_id : UUID
        Exact retired source-call identifier.
    owner_department_id : UUID
        Exact current owner Department identifier.
    expected_version : int
        Optimistic source-call aggregate version.
    reason : str
        Inspectable administrative rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for deterministic tests.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and resulting successor draft cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the source is not the exact retired end of its call lineage.
    """
    common = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    actor_id, organization_id, edition_id = common[:3]
    retry_key, correlation_id, source_channel, reason = common[3:]
    call_id = require_programme_uuid(call_id, field="call_id")
    owner_department_id = require_programme_uuid(
        owner_department_id,
        field="owner_department_id",
    )
    expected_version = require_programme_expected_version(expected_version)
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.CALL_SUCCESSOR_CREATED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=call_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
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
    scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=owner_department_id,
        authorizer=authorizer,
    )
    _require_private_writes(scope)
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(owner_department_id,),
    )
    scope = authorize_programme_call_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=owner_department_id,
        authorizer=authorizer,
        lock=True,
    )
    _require_private_writes(scope)
    source = _locked_call(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
        owner_department_id=owner_department_id,
    )
    _require_version(
        actual=source.definition.aggregate_version,
        expected=expected_version,
    )
    if source.definition.status != ApplicationDefinitionStatus.RETIRED:
        raise ApplicationsProgrammeStateConflictError
    lineage = ApplicationDefinition.objects.select_for_update().filter(
        edition_id=edition_id,
        code=source.definition.code,
    )
    next_version = source.definition.version + 1
    if (
        lineage.exclude(id=source.definition_id)
        .filter(version__gte=next_version)
        .exists()
    ):
        raise ApplicationsProgrammeStateConflictError
    with programme_application_database_writer():
        successor, successor_call = _copy_call_graph(
            scope=scope,
            source=source,
            version=next_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.CALL_SUCCESSOR_CREATED,
            definition=successor,
            call=successor_call,
            target_id=successor_call.id,
            result_kind=ProgrammeCommandResultKind.CALL,
            expected_version=0,
            resulting_version=1,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=(
                "successor",
                "definition",
                "owner",
                "sections",
                "questions",
                "tracks",
                "formats",
                "contributor_fields",
            ),
            occurred_at=effective_now,
        )


def _locked_available_call(
    *,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    lock: bool = True,
) -> ProgrammeCall:
    query = ProgrammeCall.objects.select_related("definition")
    if lock:
        query = query.select_for_update()
    call = query.filter(
        id=call_id,
        organization_id=organization_id,
        edition_id=edition_id,
        definition__organization_id=organization_id,
        definition__edition_id=edition_id,
        definition__target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
    ).first()
    if call is None:
        raise ApplicationsProgrammeUnavailableError
    return call


def _locked_proposal(
    *,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
) -> ProgrammeProposal:
    proposal = (
        ProgrammeProposal.objects.select_for_update()
        .select_related("submission", "call", "call__definition")
        .filter(
            id=proposal_id,
            organization_id=organization_id,
            edition_id=edition_id,
            submission__organization_id=organization_id,
            submission__edition_id=edition_id,
            call__organization_id=organization_id,
            call__edition_id=edition_id,
            call__definition_id=F("submission__definition_id"),
        )
        .first()
    )
    if proposal is None:
        raise ApplicationsProgrammeUnavailableError
    return proposal


def _require_proposal_scope_match(
    *,
    scope: AuthorizedProgrammeProposalScope,
    proposal: ProgrammeProposal,
) -> None:
    if (
        proposal.id != scope.proposal_id
        or proposal.submission_id != scope.submission_id
        or proposal.call_id != scope.call_id
    ):
        raise ApplicationsProgrammeUnavailableError


def _require_draft_edit_window(
    *,
    proposal: ProgrammeProposal,
    effective_now: datetime,
) -> None:
    if proposal.state != ProgrammeProposalState.DRAFT:
        raise ApplicationsProgrammeStateConflictError
    _require_active_edit_window(
        call=proposal.call,
        effective_now=effective_now,
    )


def _require_invitation_within_edit_window(
    *,
    proposal: ProgrammeProposal,
    invitation: ProgrammeProposalInvitationInput,
) -> None:
    if invitation.expires_at > proposal.call.definition.applicant_edit_until:
        raise ApplicationsProgrammeStateConflictError


def _require_active_edit_window(
    *,
    call: ProgrammeCall,
    effective_now: datetime,
) -> None:
    """Require the inclusive applicant-edit window of one active call.

    Parameters
    ----------
    call : ProgrammeCall
        Exact call owning the proposal workflow.
    effective_now : datetime
        Aware instant compared with the configured edit window.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the call is inactive or the edit window is not open.
    """
    definition = call.definition
    if (
        definition.status != ApplicationDefinitionStatus.ACTIVE
        or effective_now < definition.opens_at
        or effective_now > definition.applicant_edit_until
    ):
        raise ApplicationsProgrammeStateConflictError


def _require_current_call_owner(
    *,
    call: ProgrammeCall,
    lock: bool,
) -> None:
    if (
        resolve_current_department_reference(
            organization_id=call.organization_id,
            edition_id=call.edition_id,
            department_id=call.owner_department_id,
            lock=lock,
        )
        is None
    ):
        raise ApplicationsProgrammeUnavailableError


def _require_submission_window(
    *,
    proposal: ProgrammeProposal,
    effective_now: datetime,
) -> None:
    definition = proposal.call.definition
    if (
        definition.status != ApplicationDefinitionStatus.ACTIVE
        or effective_now < definition.opens_at
        or effective_now >= definition.closes_at
    ):
        raise ApplicationsProgrammeStateConflictError


def _advance_submission(
    submission: ApplicationSubmission,
    *,
    resulting_version: int,
) -> None:
    submission.aggregate_version = resulting_version
    submission.save()


def _selection_values(selection: ProgrammeProposalSelectionInput) -> dict[str, object]:
    return cast("dict[str, object]", asdict(selection))


def _profile_values(
    profile: ProgrammeProposalContributorProfileInput,
) -> dict[str, object]:
    return cast("dict[str, object]", asdict(profile))


def _validated_selection(
    *,
    proposal_call: ProgrammeCall,
    selection: ProgrammeProposalSelectionInput,
    lock: bool,
) -> tuple[ProgrammeCallTrack, ProgrammeCallFormat]:
    tracks = ProgrammeCallTrack.objects.all()
    formats = ProgrammeCallFormat.objects.all()
    if lock:
        tracks = tracks.select_for_update()
        formats = formats.select_for_update()
    track = tracks.filter(
        id=selection.track_id,
        organization_id=proposal_call.organization_id,
        edition_id=proposal_call.edition_id,
        call_id=proposal_call.id,
    ).first()
    programme_format = formats.filter(
        id=selection.format_id,
        organization_id=proposal_call.organization_id,
        edition_id=proposal_call.edition_id,
        call_id=proposal_call.id,
    ).first()
    if track is None or programme_format is None:
        raise ApplicationsProgrammeUnavailableError
    if not (
        programme_format.min_duration_minutes
        <= selection.requested_duration_minutes
        <= programme_format.max_duration_minutes
    ):
        raise ValidationError(
            {
                "requested_duration_minutes": ValidationError(
                    "Requested duration must fit the selected format bounds.",
                    code="invalid_programme_requested_duration",
                )
            },
        )
    return track, programme_format


def _require_profile_policy(
    *,
    call: ProgrammeCall,
    profile: ProgrammeProposalContributorProfileInput,
    role: ProgrammeContributorRole,
) -> None:
    if profile.consent_policy_code != call.contributor_consent_policy_code:
        raise ApplicationsProgrammeStateConflictError
    requirements = {
        row.field_code: (
            row.lead_requirement
            if role == ProgrammeContributorRole.LEAD
            else row.collaborator_requirement
        )
        for row in call.contributor_fields.all()
    }
    values = {
        ProgrammeContributorFieldCode.PUBLIC_NAME: profile.public_name,
        ProgrammeContributorFieldCode.BIOGRAPHY: profile.biography,
        ProgrammeContributorFieldCode.PRONOUNS: profile.pronouns,
        ProgrammeContributorFieldCode.WEBSITE: profile.website,
    }
    for field_code, value in values.items():
        requirement = requirements.get(
            field_code,
            ProgrammeContributorRequirement.HIDDEN,
        )
        if requirement == ProgrammeContributorRequirement.HIDDEN and value:
            raise ValidationError(
                {
                    str(field_code): ValidationError(
                        "Clear values hidden by the contributor-field policy.",
                        code="applications_programme_hidden_profile_value",
                    )
                },
            )


@_audit_command_errors(
    capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.PROPOSAL_STARTED,
)
@transaction.atomic
def start_programme_proposal(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
    selection: ProgrammeProposalSelectionInput,
    lead_profile: ProgrammeProposalContributorProfileInput,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Start one proposal with its initial selection and lead profile.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the call and proposal.
    edition_id : UUID
        Exact event edition identifier.
    call_id : UUID
        Exact active call identifier.
    selection : ProgrammeProposalSelectionInput
        Initial selected track, format, and requested duration.
    lead_profile : ProgrammeProposalContributorProfileInput
        Lead's initial proposal-scoped profile and publication intent.
    expected_version : int
        Required initial proposal version, which must be zero.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for the applicant edit window.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and resulting draft-proposal cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the call cannot accept a new proposal at the effective instant.
    ApplicationsProgrammeVersionConflictError
        If the initial expected version is not zero.
    ValidationError
        If the initial selection, profile, or stored form shape is invalid.
    """
    (
        actor_id,
        organization_id,
        edition_id,
        retry_key,
        correlation_id,
        source_channel,
        reason,
    ) = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    call_id = require_programme_uuid(call_id, field="call_id")
    expected_version = require_programme_expected_version(expected_version)
    if expected_version != 0:
        raise ApplicationsProgrammeVersionConflictError
    if not isinstance(selection, ProgrammeProposalSelectionInput) or not isinstance(
        lead_profile,
        ProgrammeProposalContributorProfileInput,
    ):
        raise ValidationError(
            "Proposal start requires closed typed inputs.",
            code="applications_programme_input_invalid",
        )
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.PROPOSAL_STARTED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=call_id,
        expected_version=0,
        reason=reason,
        source_channel=source_channel,
        values={
            "selection": _selection_values(selection),
            "lead_profile": _profile_values(lead_profile),
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
    scope = authorize_programme_self_entry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
    )
    _require_private_writes(scope)
    initial_call = _locked_available_call(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
        lock=False,
    )
    _require_current_call_owner(call=initial_call, lock=False)
    _lock_programme_write_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=(initial_call.owner_department_id,),
    )
    scope = authorize_programme_self_entry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        lock=True,
    )
    _require_private_writes(scope)
    call = _locked_available_call(
        organization_id=organization_id,
        edition_id=edition_id,
        call_id=call_id,
    )
    _require_current_call_owner(call=call, lock=True)
    definition = call.definition
    _require_active_edit_window(call=call, effective_now=effective_now)
    _require_profile_policy(
        call=call,
        profile=lead_profile,
        role=ProgrammeContributorRole.LEAD,
    )
    track, programme_format = _validated_selection(
        proposal_call=call,
        selection=selection,
        lock=True,
    )
    submissions = ApplicationSubmission.objects.select_for_update().filter(
        definition=definition,
        account_id=actor_id,
    )
    if submissions.count() >= definition.max_submissions_per_person:
        raise ApplicationsProgrammeStateConflictError
    ordinal = (submissions.aggregate(maximum=Max("ordinal"))["maximum"] or 0) + 1
    profile_digest = canonical_programme_digest(
        {
            "proposal_start": call.id,
            "account_id": actor_id,
            "profile": _profile_values(lead_profile),
            "sequence": 1,
        }
    )
    with programme_application_database_writer():
        submission = ApplicationSubmission.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            definition=definition,
            account_id=actor_id,
            ordinal=ordinal,
            state=ApplicationState.DRAFT,
            aggregate_version=1,
        )
        proposal = ProgrammeProposal.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            submission=submission,
            call=call,
            state=ProgrammeProposalState.DRAFT,
        )
        ProgrammeProposalSelectionRevision.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            proposal=proposal,
            sequence=1,
            track=track,
            format=programme_format,
            requested_duration_minutes=selection.requested_duration_minutes,
            actor_id=actor_id,
            source_version=0,
            resulting_version=1,
        )
        ProgrammeProposalContributorProfileRevision.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            proposal=proposal,
            account_id=actor_id,
            sequence=1,
            predecessor=None,
            public_name=lead_profile.public_name,
            biography=lead_profile.biography,
            pronouns=lead_profile.pronouns,
            website=lead_profile.website,
            proposed_for_publication=lead_profile.proposed_for_publication,
            consent_policy_code=lead_profile.consent_policy_code,
            consent_acknowledged=lead_profile.consent_acknowledged,
            actor_id=actor_id,
            digest=profile_digest,
            source_version=0,
            resulting_version=1,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.PROPOSAL_STARTED,
            definition=definition,
            call=call,
            proposal=proposal,
            submission=submission,
            target_id=proposal.id,
            result_kind=ProgrammeCommandResultKind.PROPOSAL,
            expected_version=0,
            resulting_version=1,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("proposal", "selection", "lead_profile"),
            occurred_at=effective_now,
        )


def _proposal_command_common(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> tuple[UUID, UUID, UUID, UUID, int, str, UUID, UUID, str]:
    common = _common_identifiers(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
        reason=reason,
    )
    return (
        common[0],
        common[1],
        common[2],
        require_programme_uuid(proposal_id, field="proposal_id"),
        require_programme_expected_version(expected_version),
        common[6],
        common[3],
        common[4],
        common[5],
    )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.PROPOSAL_SELECTION_REVISED,
)
@transaction.atomic
def revise_programme_proposal_selection(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    selection: ProgrammeProposalSelectionInput,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Append one lead-owned selection revision to a draft proposal.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    selection : ProgrammeProposalSelectionInput
        Replacement track, format, and requested duration.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for the applicant edit window.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and appended selection-revision cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the proposal is not an editable lead-owned draft.
    ValidationError
        If the selection or stored call configuration is invalid.
    """
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    if not isinstance(selection, ProgrammeProposalSelectionInput):
        raise ValidationError(
            "Selection revisions require a closed typed input.",
            code="applications_programme_input_invalid",
        )
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.PROPOSAL_SELECTION_REVISED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"selection": _selection_values(selection)},
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
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        now=effective_now,
    )
    if scope.relationship != "lead":
        raise ApplicationsProgrammeStateConflictError
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        lock=True,
        now=effective_now,
    )
    if scope.relationship != "lead":
        raise ApplicationsProgrammeStateConflictError
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_proposal_scope_match(scope=scope, proposal=proposal)
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    track, programme_format = _validated_selection(
        proposal_call=proposal.call,
        selection=selection,
        lock=True,
    )
    sequence = (
        ProgrammeProposalSelectionRevision.objects.filter(proposal=proposal).aggregate(
            maximum=Max("sequence")
        )["maximum"]
        or 0
    ) + 1
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        revision = ProgrammeProposalSelectionRevision.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            proposal=proposal,
            sequence=sequence,
            track=track,
            format=programme_format,
            requested_duration_minutes=selection.requested_duration_minutes,
            actor_id=actor_id,
            source_version=expected_version,
            resulting_version=resulting_version,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.PROPOSAL_SELECTION_REVISED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=revision.id,
            result_kind=ProgrammeCommandResultKind.SELECTION_REVISION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("selection",),
            occurred_at=effective_now,
        )


def _latest_answer_map(
    *,
    submission: ApplicationSubmission,
    through_version: int,
) -> dict[str, ApplicationAnswerRevision]:
    latest: dict[str, ApplicationAnswerRevision] = {}
    rows = ApplicationAnswerRevision.objects.filter(
        submission=submission,
        resulting_version__lte=through_version,
    ).order_by("question_key", "-resulting_version", "-sequence", "-id")
    for row in rows:
        latest.setdefault(row.question_key, row)
    return latest


def _question_is_applicable(
    *,
    question: ApplicationQuestion,
    answers: Mapping[str, ApplicationAnswerRevision],
) -> bool:
    values = {key: answer.value for key, answer in answers.items()}
    return condition_matches(question.condition, values)


@_audit_command_errors(
    capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
)
@transaction.atomic
def append_programme_proposal_answer(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    question_id: UUID,
    value: object,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Append one shared applicant-writable typed answer revision.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead or collaborator account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    question_id : UUID
        Exact question receiving the new answer revision.
    value : object
        Raw typed answer value normalized by the Applications engine.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for the applicant edit window.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and appended answer-revision cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the proposal or question is not currently editable.
    ApplicationsProgrammeUnavailableError
        If the selected answer cannot be normalized for the stored question.
    """
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    question_id = require_programme_uuid(question_id, field="question_id")
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"question_id": question_id, "value": value},
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
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        now=effective_now,
    )
    if scope.relationship not in {"lead", "collaborator"}:
        raise ApplicationsProgrammeStateConflictError
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        lock=True,
        now=effective_now,
    )
    if scope.relationship not in {"lead", "collaborator"}:
        raise ApplicationsProgrammeStateConflictError
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_proposal_scope_match(scope=scope, proposal=proposal)
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    question = (
        ApplicationQuestion.objects.select_for_update()
        .filter(
            id=question_id,
            definition_id=proposal.submission.definition_id,
            applicant_visible=True,
            applicant_writable=True,
            source_binding="",
            staff_visible=False,
            staff_writable=False,
            reviewer_visible=False,
            public_after_approval=False,
            api_projection=False,
        )
        .first()
    )
    if question is None:
        raise ApplicationsProgrammeUnavailableError
    latest = _latest_answer_map(
        submission=proposal.submission,
        through_version=expected_version,
    )
    if not _question_is_applicable(question=question, answers=latest):
        raise ApplicationsProgrammeStateConflictError
    normalized_value = normalize_answer_value(
        question=question,
        account=cast("Any", _AccountIdentifier(actor_id)),
        value=(
            unicodedata.normalize("NFC", value) if isinstance(value, str) else value
        ),
    )
    previous_sequence = (
        ApplicationAnswerRevision.objects.filter(
            submission=proposal.submission,
            question=question,
        ).aggregate(maximum=Max("sequence"))["maximum"]
        or 0
    )
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        answer = ApplicationAnswerRevision.objects.create(
            submission=proposal.submission,
            question=question,
            sequence=previous_sequence + 1,
            question_key=question.key,
            question_type=question.field_type,
            classification=question.classification,
            value=normalized_value,
            source=AnswerSource.APPLICANT,
            actor_id=actor_id,
            reason="",
            source_version=expected_version,
            resulting_version=resulting_version,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=answer.id,
            result_kind=ProgrammeCommandResultKind.ANSWER_REVISION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("answer",),
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.CONTRIBUTOR_PROFILE_REVISED,
)
@transaction.atomic
def revise_programme_contributor_profile(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    profile: ProgrammeProposalContributorProfileInput,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Append the actor's own proposal-scoped profile and consent revision.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified contributor account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    profile : ProgrammeProposalContributorProfileInput
        Actor-owned profile copy and publication intent.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for the applicant edit window.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and appended profile-revision cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the actor is not a current editable proposal contributor.
    ValidationError
        If public-copy fields conflict with the actor's publication intent.
    """
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    if not isinstance(profile, ProgrammeProposalContributorProfileInput):
        raise ValidationError(
            "Profile revisions require a closed typed input.",
            code="applications_programme_input_invalid",
        )
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.CONTRIBUTOR_PROFILE_REVISED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"profile": _profile_values(profile)},
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
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        now=effective_now,
    )
    if scope.relationship not in {"lead", "collaborator"}:
        raise ApplicationsProgrammeStateConflictError
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        lock=True,
        now=effective_now,
    )
    if scope.relationship not in {"lead", "collaborator"}:
        raise ApplicationsProgrammeStateConflictError
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_proposal_scope_match(scope=scope, proposal=proposal)
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    _require_profile_policy(
        call=proposal.call,
        profile=profile,
        role=(
            ProgrammeContributorRole.LEAD
            if scope.relationship == "lead"
            else ProgrammeContributorRole.COLLABORATOR
        ),
    )
    predecessor = (
        ProgrammeProposalContributorProfileRevision.objects.filter(
            proposal=proposal,
            account_id=actor_id,
        )
        .order_by("-sequence", "-id")
        .first()
    )
    sequence = (predecessor.sequence if predecessor is not None else 0) + 1
    resulting_version = expected_version + 1
    profile_digest = canonical_programme_digest(
        {
            "proposal_id": proposal.id,
            "account_id": actor_id,
            "predecessor_id": predecessor.id if predecessor is not None else None,
            "sequence": sequence,
            "profile": _profile_values(profile),
        }
    )
    with programme_application_database_writer():
        revision = ProgrammeProposalContributorProfileRevision.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            proposal=proposal,
            account_id=actor_id,
            sequence=sequence,
            predecessor=predecessor,
            public_name=profile.public_name,
            biography=profile.biography,
            pronouns=profile.pronouns,
            website=profile.website,
            proposed_for_publication=profile.proposed_for_publication,
            consent_policy_code=profile.consent_policy_code,
            consent_acknowledged=profile.consent_acknowledged,
            actor_id=actor_id,
            digest=profile_digest,
            source_version=expected_version,
            resulting_version=resulting_version,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.CONTRIBUTOR_PROFILE_REVISED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=revision.id,
            result_kind=ProgrammeCommandResultKind.PROFILE_REVISION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("own_contributor_profile", "own_consent"),
            occurred_at=effective_now,
        )


def _current_collaborator(
    *,
    proposal: ProgrammeProposal,
    account_id: UUID | None = None,
    collaborator_id: UUID | None = None,
    lock: bool,
) -> ProgrammeProposalCollaborator | None:
    query = ProgrammeProposalCollaborator.objects.filter(
        organization_id=proposal.organization_id,
        edition_id=proposal.edition_id,
        proposal=proposal,
    )
    if account_id is not None:
        query = query.filter(account_id=account_id)
    if collaborator_id is not None:
        query = query.filter(id=collaborator_id)
    if lock:
        query = query.select_for_update()
    return query.first()


def _roster_uses_capacity(
    *,
    proposal: ProgrammeProposal,
    effective_now: datetime,
    excluding_id: UUID | None = None,
) -> int:
    query = ProgrammeProposalCollaborator.objects.filter(
        proposal=proposal,
    ).filter(
        Q(state=ProgrammeCollaboratorState.ACCEPTED)
        | Q(
            state=ProgrammeCollaboratorState.INVITED,
            invite_expires_at__gt=effective_now,
        )
    )
    if excluding_id is not None:
        query = query.exclude(id=excluding_id)
    return query.count()


def _require_roster_capacity(
    *,
    proposal: ProgrammeProposal,
    effective_now: datetime,
    excluding_id: UUID | None = None,
) -> None:
    if (
        _roster_uses_capacity(
            proposal=proposal,
            effective_now=effective_now,
            excluding_id=excluding_id,
        )
        >= proposal.call.max_collaborators
    ):
        raise ApplicationsProgrammeStateConflictError


def _transition_collaborator(
    *,
    proposal: ProgrammeProposal,
    collaborator: ProgrammeProposalCollaborator,
    actor_id: UUID,
    to_state: ProgrammeCollaboratorState,
    generation: int,
    invite_expires_at: datetime | None,
    reason: str,
    source_version: int,
) -> ProgrammeProposalCollaboratorTransition:
    previous = (
        ProgrammeProposalCollaboratorTransition.objects.filter(
            collaborator=collaborator,
        )
        .order_by("-sequence", "-id")
        .first()
    )
    from_state = previous.to_state if previous is not None else None
    collaborator.state = to_state
    collaborator.generation = generation
    if invite_expires_at is not None:
        collaborator.invite_expires_at = invite_expires_at
    collaborator.save()
    return ProgrammeProposalCollaboratorTransition.objects.create(
        organization_id=proposal.organization_id,
        edition_id=proposal.edition_id,
        proposal=proposal,
        collaborator=collaborator,
        sequence=(previous.sequence if previous is not None else 0) + 1,
        generation=generation,
        from_state=from_state,
        to_state=to_state,
        actor_id=actor_id,
        reason=reason,
        invite_expires_at=(
            invite_expires_at
            if to_state == ProgrammeCollaboratorState.INVITED
            else None
        ),
        source_version=source_version,
        resulting_version=source_version + 1,
    )


def _proposal_preflight(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    capability_code: str,
    authorizer: ApplicationsProgrammeAuthorizer,
    relationship: str,
    lock: bool,
    effective_now: datetime,
) -> AuthorizedProgrammeProposalScope:
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=capability_code,
        authorizer=authorizer,
        lock=lock,
        now=effective_now,
    )
    if scope.relationship != relationship:
        raise ApplicationsProgrammeStateConflictError
    return scope


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.COLLABORATOR_INVITED,
)
@transaction.atomic
def invite_programme_proposal_collaborator(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    invitation: ProgrammeProposalInvitationInput,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Invite one existing active verified person without retaining email.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    invitation : ProgrammeProposalInvitationInput
        Normalized login email and bounded invitation expiry.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for expiry and edit-window checks.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and invitation-transition cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the draft cannot accept another current collaborator invitation.
    ApplicationsProgrammeUnavailableError
        If the email does not resolve to one active verified person.
    ValidationError
        If invitation evidence or the stored collaborator shape is invalid.
    """
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    if not isinstance(invitation, ProgrammeProposalInvitationInput):
        raise ValidationError(
            "Invitation commands require a closed typed input.",
            code="applications_programme_input_invalid",
        )
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.COLLABORATOR_INVITED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"invitation": asdict(invitation)},
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
    if invitation.expires_at <= effective_now:
        raise ApplicationsProgrammeStateConflictError
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    _require_invitation_within_edit_window(
        proposal=proposal,
        invitation=invitation,
    )
    invitee = resolve_active_verified_person_reference_by_email(
        email=invitation.invitee_email,
        lock=True,
    )
    if invitee is None or invitee.account_id == proposal.submission.account_id:
        raise ApplicationsProgrammeUnavailableError
    if (
        _current_collaborator(
            proposal=proposal,
            account_id=invitee.account_id,
            lock=True,
        )
        is not None
    ):
        raise ApplicationsProgrammeStateConflictError
    _require_roster_capacity(proposal=proposal, effective_now=effective_now)
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        collaborator = ProgrammeProposalCollaborator.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            proposal=proposal,
            account_id=invitee.account_id,
            state=ProgrammeCollaboratorState.INVITED,
            generation=1,
            invite_expires_at=invitation.expires_at,
        )
        transition = _transition_collaborator(
            proposal=proposal,
            collaborator=collaborator,
            actor_id=actor_id,
            to_state=ProgrammeCollaboratorState.INVITED,
            generation=1,
            invite_expires_at=invitation.expires_at,
            reason=reason,
            source_version=expected_version,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.COLLABORATOR_INVITED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=transition.id,
            result_kind=ProgrammeCommandResultKind.COLLABORATOR_TRANSITION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("collaborator_roster", "own_invitation"),
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.COLLABORATOR_REINVITED,
)
@transaction.atomic
def reinvite_programme_proposal_collaborator(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    invitation: ProgrammeProposalInvitationInput,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Append a new invitation generation while retaining prior evidence.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    invitation : ProgrammeProposalInvitationInput
        Normalized login email and new bounded invitation expiry.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for expiry and edit-window checks.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and reinvitation-transition cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the collaborator is not eligible for a new invitation generation.
    ApplicationsProgrammeUnavailableError
        If the email does not resolve to the retained collaborator account.
    ValidationError
        If invitation evidence or the stored collaborator shape is invalid.
    """
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    if not isinstance(invitation, ProgrammeProposalInvitationInput):
        raise ValidationError(
            "Invitation commands require a closed typed input.",
            code="applications_programme_input_invalid",
        )
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.COLLABORATOR_REINVITED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"invitation": asdict(invitation)},
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
    if invitation.expires_at <= effective_now:
        raise ApplicationsProgrammeStateConflictError
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    _require_invitation_within_edit_window(
        proposal=proposal,
        invitation=invitation,
    )
    invitee = resolve_active_verified_person_reference_by_email(
        email=invitation.invitee_email,
        lock=True,
    )
    if invitee is None or invitee.account_id == proposal.submission.account_id:
        raise ApplicationsProgrammeUnavailableError
    collaborator = _current_collaborator(
        proposal=proposal,
        account_id=invitee.account_id,
        lock=True,
    )
    if (
        collaborator is None
        or collaborator.state == ProgrammeCollaboratorState.ACCEPTED
    ):
        raise ApplicationsProgrammeStateConflictError
    if (
        collaborator.state == ProgrammeCollaboratorState.INVITED
        and collaborator.invite_expires_at > effective_now
    ):
        raise ApplicationsProgrammeStateConflictError
    _require_roster_capacity(
        proposal=proposal,
        effective_now=effective_now,
        excluding_id=collaborator.id,
    )
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        transition = _transition_collaborator(
            proposal=proposal,
            collaborator=collaborator,
            actor_id=actor_id,
            to_state=ProgrammeCollaboratorState.INVITED,
            generation=collaborator.generation + 1,
            invite_expires_at=invitation.expires_at,
            reason=reason,
            source_version=expected_version,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.COLLABORATOR_REINVITED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=transition.id,
            result_kind=ProgrammeCommandResultKind.COLLABORATOR_TRANSITION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("collaborator_roster", "own_invitation"),
            occurred_at=effective_now,
        )


def _respond_to_invitation(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    effective_now: datetime,
    action: ProgrammeCommandAction,
    to_state: ProgrammeCollaboratorState,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> ProgrammeCommandResult:
    digest = _request_digest(
        action=action,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
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
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
        authorizer=authorizer,
        relationship="invited",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
        authorizer=authorizer,
        relationship="invited",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    collaborator = _current_collaborator(
        proposal=proposal,
        account_id=actor_id,
        lock=True,
    )
    if (
        collaborator is None
        or collaborator.state != ProgrammeCollaboratorState.INVITED
        or collaborator.invite_expires_at <= effective_now
    ):
        raise ApplicationsProgrammeStateConflictError
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        transition = _transition_collaborator(
            proposal=proposal,
            collaborator=collaborator,
            actor_id=actor_id,
            to_state=to_state,
            generation=collaborator.generation,
            invite_expires_at=None,
            reason=reason,
            source_version=expected_version,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=action,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=transition.id,
            result_kind=ProgrammeCommandResultKind.COLLABORATOR_TRANSITION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("own_invitation", "collaborator_roster"),
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
    operation=ProgrammeCommandAction.COLLABORATOR_ACCEPTED,
)
@transaction.atomic
def accept_programme_proposal_invitation(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Accept only the actor's own current unexpired invitation.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified invitee account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for invitation expiry.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and accepted-collaborator cursor.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    return _respond_to_invitation(
        actor_id=common[0],
        organization_id=common[1],
        edition_id=common[2],
        proposal_id=common[3],
        expected_version=common[4],
        reason=common[5],
        retry_key=common[6],
        correlation_id=common[7],
        source_channel=common[8],
        effective_now=_effective_now(now),
        action=ProgrammeCommandAction.COLLABORATOR_ACCEPTED,
        to_state=ProgrammeCollaboratorState.ACCEPTED,
        authorizer=authorizer,
    )


@_audit_command_errors(
    capability_code=APPLICATIONS_RESPOND_PROGRAMME_INVITATION_SELF,
    operation=ProgrammeCommandAction.COLLABORATOR_DECLINED,
)
@transaction.atomic
def decline_programme_proposal_invitation(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Decline only the actor's own current unexpired invitation.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified invitee account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for invitation expiry.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and declined-invitation cursor.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    return _respond_to_invitation(
        actor_id=common[0],
        organization_id=common[1],
        edition_id=common[2],
        proposal_id=common[3],
        expected_version=common[4],
        reason=common[5],
        retry_key=common[6],
        correlation_id=common[7],
        source_channel=common[8],
        effective_now=_effective_now(now),
        action=ProgrammeCommandAction.COLLABORATOR_DECLINED,
        to_state=ProgrammeCollaboratorState.DECLINED,
        authorizer=authorizer,
    )


@_audit_command_errors(
    capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.COLLABORATOR_LEFT,
)
@transaction.atomic
def leave_programme_proposal(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Leave one draft proposal as its exact accepted collaborator.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified collaborator account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for relationship checks.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and departed-collaborator cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the proposal is not draft or the actor is not an accepted collaborator.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    actor_id, organization_id, edition_id, proposal_id = common[:4]
    expected_version, reason, retry_key, correlation_id, source_channel = common[4:]
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.COLLABORATOR_LEFT,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
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
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="collaborator",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="collaborator",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    collaborator = _current_collaborator(
        proposal=proposal,
        account_id=actor_id,
        lock=True,
    )
    if (
        collaborator is None
        or collaborator.state != ProgrammeCollaboratorState.ACCEPTED
    ):
        raise ApplicationsProgrammeStateConflictError
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        transition = _transition_collaborator(
            proposal=proposal,
            collaborator=collaborator,
            actor_id=actor_id,
            to_state=ProgrammeCollaboratorState.LEFT,
            generation=collaborator.generation,
            invite_expires_at=None,
            reason=reason,
            source_version=expected_version,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.COLLABORATOR_LEFT,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=transition.id,
            result_kind=ProgrammeCommandResultKind.COLLABORATOR_TRANSITION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("collaborator_roster",),
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.COLLABORATOR_REMOVED,
)
@transaction.atomic
def remove_programme_proposal_collaborator(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    collaborator_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Remove one currently invited or accepted collaborator as lead.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    collaborator_id : UUID
        Exact invited or accepted collaborator account identifier.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for relationship checks.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and removed-collaborator cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the proposal or collaborator is not removable by the lead.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    actor_id, organization_id, edition_id, proposal_id = common[:4]
    expected_version, reason, retry_key, correlation_id, source_channel = common[4:]
    collaborator_id = require_programme_uuid(
        collaborator_id,
        field="collaborator_id",
    )
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.COLLABORATOR_REMOVED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"collaborator_id": collaborator_id},
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
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    collaborator = _current_collaborator(
        proposal=proposal,
        collaborator_id=collaborator_id,
        lock=True,
    )
    if collaborator is None or collaborator.state not in {
        ProgrammeCollaboratorState.INVITED,
        ProgrammeCollaboratorState.ACCEPTED,
    }:
        raise ApplicationsProgrammeStateConflictError
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        transition = _transition_collaborator(
            proposal=proposal,
            collaborator=collaborator,
            actor_id=actor_id,
            to_state=ProgrammeCollaboratorState.REMOVED,
            generation=collaborator.generation,
            invite_expires_at=None,
            reason=reason,
            source_version=expected_version,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.COLLABORATOR_REMOVED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=transition.id,
            result_kind=ProgrammeCommandResultKind.COLLABORATOR_TRANSITION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("collaborator_roster",),
            occurred_at=effective_now,
        )


def _applicable_questions(
    *,
    proposal: ProgrammeProposal,
    through_version: int,
) -> tuple[
    tuple[ApplicationQuestion, ApplicationAnswerRevision | None],
    ...,
]:
    latest = _latest_answer_map(
        submission=proposal.submission,
        through_version=through_version,
    )
    rows: list[tuple[ApplicationQuestion, ApplicationAnswerRevision | None]] = []
    for question in proposal.call.definition.questions.order_by(
        "section__position",
        "position",
        "id",
    ):
        if not _question_is_applicable(question=question, answers=latest):
            continue
        answer = latest.get(question.key)
        if question.required and (
            answer is None or answer.value is None or answer.value in ("", [], {})
        ):
            raise ApplicationsProgrammeCompletenessError
        rows.append((question, answer))
    return tuple(rows)


def _profile_field_value(
    *,
    profile: ProgrammeProposalContributorProfileRevision,
    field_code: str,
) -> str:
    if field_code == ProgrammeContributorFieldCode.PUBLIC_NAME:
        return profile.public_name
    if field_code == ProgrammeContributorFieldCode.BIOGRAPHY:
        return profile.biography
    if field_code == ProgrammeContributorFieldCode.PRONOUNS:
        return profile.pronouns
    if field_code == ProgrammeContributorFieldCode.WEBSITE:
        return profile.website
    raise ApplicationsProgrammeCompletenessError


def _latest_profile(
    *,
    proposal: ProgrammeProposal,
    account_id: UUID,
    through_version: int,
) -> ProgrammeProposalContributorProfileRevision:
    profile = (
        ProgrammeProposalContributorProfileRevision.objects.filter(
            proposal=proposal,
            account_id=account_id,
            resulting_version__lte=through_version,
        )
        .order_by("-resulting_version", "-sequence", "-id")
        .first()
    )
    if (
        profile is None
        or profile.consent_policy_code != proposal.call.contributor_consent_policy_code
    ):
        raise ApplicationsProgrammeCompletenessError
    return profile


def _require_profile_complete(
    *,
    proposal: ProgrammeProposal,
    profile: ProgrammeProposalContributorProfileRevision,
    role: ProgrammeContributorRole,
) -> None:
    for field in proposal.call.contributor_fields.order_by("position", "id"):
        requirement = (
            field.lead_requirement
            if role == ProgrammeContributorRole.LEAD
            else field.collaborator_requirement
        )
        if requirement == ProgrammeContributorRequirement.REQUIRED and not (
            _profile_field_value(
                profile=profile,
                field_code=field.field_code,
            )
        ):
            raise ApplicationsProgrammeCompletenessError


def _snapshot_contributors(
    *,
    proposal: ProgrammeProposal,
    through_version: int,
) -> tuple[
    tuple[
        UUID,
        ProgrammeContributorRole,
        ProgrammeProposalCollaboratorTransition | None,
        ProgrammeProposalContributorProfileRevision,
    ],
    ...,
]:
    lead_id = proposal.submission.account_id
    lead_reference = resolve_active_verified_person_reference(
        account_id=lead_id,
        lock=True,
    )
    if lead_reference is None:
        raise ApplicationsProgrammeCompletenessError
    lead_profile = _latest_profile(
        proposal=proposal,
        account_id=lead_id,
        through_version=through_version,
    )
    _require_profile_complete(
        proposal=proposal,
        profile=lead_profile,
        role=ProgrammeContributorRole.LEAD,
    )
    contributors: list[
        tuple[
            UUID,
            ProgrammeContributorRole,
            ProgrammeProposalCollaboratorTransition | None,
            ProgrammeProposalContributorProfileRevision,
        ]
    ] = [
        (lead_id, ProgrammeContributorRole.LEAD, None, lead_profile),
    ]
    collaborators = (
        ProgrammeProposalCollaborator.objects.select_for_update()
        .filter(
            proposal=proposal,
            state=ProgrammeCollaboratorState.ACCEPTED,
        )
        .order_by("created_at", "id")
    )
    for collaborator in collaborators:
        person = resolve_active_verified_person_reference(
            account_id=collaborator.account_id,
            lock=True,
        )
        transition = (
            ProgrammeProposalCollaboratorTransition.objects.filter(
                collaborator=collaborator,
                resulting_version__lte=through_version,
            )
            .order_by("-resulting_version", "-sequence", "-id")
            .first()
        )
        if (
            person is None
            or transition is None
            or transition.to_state != ProgrammeCollaboratorState.ACCEPTED
        ):
            raise ApplicationsProgrammeCompletenessError
        profile = _latest_profile(
            proposal=proposal,
            account_id=collaborator.account_id,
            through_version=through_version,
        )
        _require_profile_complete(
            proposal=proposal,
            profile=profile,
            role=ProgrammeContributorRole.COLLABORATOR,
        )
        contributors.append(
            (
                collaborator.account_id,
                ProgrammeContributorRole.COLLABORATOR,
                transition,
                profile,
            )
        )
    return tuple(contributors)


def _latest_selection(
    *,
    proposal: ProgrammeProposal,
    through_version: int,
) -> ProgrammeProposalSelectionRevision:
    selection = (
        ProgrammeProposalSelectionRevision.objects.filter(
            proposal=proposal,
            resulting_version__lte=through_version,
        )
        .order_by("-resulting_version", "-sequence", "-id")
        .first()
    )
    if selection is None:
        raise ApplicationsProgrammeCompletenessError
    return selection


def _snapshot_digest(
    *,
    proposal: ProgrammeProposal,
    predecessor: ProgrammeProposalRevision | None,
    sequence: int,
    resulting_version: int,
    selection: ProgrammeProposalSelectionRevision,
    answers: Sequence[tuple[ApplicationQuestion, ApplicationAnswerRevision | None]],
    contributors: Sequence[
        tuple[
            UUID,
            ProgrammeContributorRole,
            ProgrammeProposalCollaboratorTransition | None,
            ProgrammeProposalContributorProfileRevision,
        ]
    ],
) -> str:
    definition = proposal.call.definition
    return canonical_programme_digest(
        {
            "proposal_id": proposal.id,
            "definition_id": definition.id,
            "definition_version": definition.version,
            "call_id": proposal.call_id,
            "sequence": sequence,
            "predecessor_id": predecessor.id if predecessor is not None else None,
            "resulting_version": resulting_version,
            "selection": {
                "revision_id": selection.id,
                "track_id": selection.track_id,
                "format_id": selection.format_id,
                "requested_duration_minutes": (selection.requested_duration_minutes),
            },
            "policies": {
                "audience": definition.audience_policy_code,
                "retention": definition.retention_policy_code,
                "content": proposal.call.content_policy_code,
                "contributor_consent": (proposal.call.contributor_consent_policy_code),
                "collaboration_retention": (
                    proposal.call.collaboration_retention_policy_code
                ),
            },
            "answers": [
                {
                    "question_id": question.id,
                    "question_key": question.key,
                    "question_type": question.field_type,
                    "classification": question.classification,
                    "answer_revision_id": answer.id if answer is not None else None,
                    "value": answer.value if answer is not None else None,
                }
                for question, answer in answers
            ],
            "contributors": [
                {
                    "account_id": account_id,
                    "role": role,
                    "accepted_transition_id": (
                        transition.id if transition is not None else None
                    ),
                    "profile_revision_id": profile.id,
                    "profile_digest": profile.digest,
                }
                for account_id, role, transition, profile in contributors
            ],
        }
    )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.PROPOSAL_SEALED,
)
@transaction.atomic
def seal_programme_proposal(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Seal one exact complete immutable revision as the proposal lead.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft proposal identifier.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for edit-window and expiry checks.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and immutable sealed-revision cursor.

    Raises
    ------
    ApplicationsProgrammeCompletenessError
        If required answers, profiles, contributors, or invitations are incomplete.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = common
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.PROPOSAL_SEALED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
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
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_draft_edit_window(proposal=proposal, effective_now=effective_now)
    if (
        ProgrammeProposalCollaborator.objects.select_for_update()
        .filter(
            proposal=proposal,
            state=ProgrammeCollaboratorState.INVITED,
            invite_expires_at__gt=effective_now,
        )
        .exists()
    ):
        raise ApplicationsProgrammeCompletenessError
    selection = _latest_selection(
        proposal=proposal,
        through_version=expected_version,
    )
    answers = _applicable_questions(
        proposal=proposal,
        through_version=expected_version,
    )
    contributors = _snapshot_contributors(
        proposal=proposal,
        through_version=expected_version,
    )
    predecessor = (
        ProgrammeProposalRevision.objects.filter(proposal=proposal)
        .order_by("-sequence", "-id")
        .first()
    )
    sequence = (predecessor.sequence if predecessor is not None else 0) + 1
    resulting_version = expected_version + 1
    snapshot_digest = _snapshot_digest(
        proposal=proposal,
        predecessor=predecessor,
        sequence=sequence,
        resulting_version=resulting_version,
        selection=selection,
        answers=answers,
        contributors=contributors,
    )
    with programme_application_database_writer():
        revision = ProgrammeProposalRevision.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            proposal=proposal,
            sequence=sequence,
            predecessor=predecessor,
            definition_version=proposal.call.definition.version,
            selection_revision=selection,
            source_version=expected_version,
            resulting_version=resulting_version,
            digest=snapshot_digest,
            created_by_id=actor_id,
            sealed_at=effective_now,
        )
        for question, answer in answers:
            ProgrammeProposalRevisionAnswer.objects.create(
                organization_id=organization_id,
                edition_id=edition_id,
                revision=revision,
                question=question,
                answer_revision=answer,
                question_key=question.key,
                question_type=question.field_type,
                classification=question.classification,
            )
        for account_id, role, transition, profile in contributors:
            ProgrammeProposalRevisionContributor.objects.create(
                organization_id=organization_id,
                edition_id=edition_id,
                revision=revision,
                account_id=account_id,
                role=role,
                accepted_transition=transition,
                profile_revision=profile,
            )
        proposal.state = ProgrammeProposalState.SEALED
        proposal.sealed_revision = revision
        proposal.submitted_revision = None
        proposal.save()
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.PROPOSAL_SEALED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=revision.id,
            result_kind=ProgrammeCommandResultKind.PROPOSAL_REVISION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("state", "sealed_revision"),
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.PROPOSAL_REOPENED,
)
@transaction.atomic
def reopen_programme_proposal(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Reopen a sealed or submitted proposal while retaining old evidence.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact sealed or submitted proposal identifier.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for the applicant edit window.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and reopened draft-proposal cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the proposal state or edit window does not permit reopening.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = common
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.PROPOSAL_REOPENED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
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
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_MANAGE_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    if proposal.state not in {
        ProgrammeProposalState.SEALED,
        ProgrammeProposalState.SUBMITTED,
    }:
        raise ApplicationsProgrammeStateConflictError
    _require_active_edit_window(
        call=proposal.call,
        effective_now=effective_now,
    )
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        proposal.state = ProgrammeProposalState.DRAFT
        proposal.sealed_revision = None
        proposal.submitted_revision = None
        proposal.save()
        submission = proposal.submission
        submission.state = ApplicationState.DRAFT
        submission.submitted_at = None
        submission.decided_at = None
        submission.withdrawn_at = None
        _advance_submission(submission, resulting_version=resulting_version)
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.PROPOSAL_REOPENED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=submission,
            target_id=proposal.id,
            result_kind=ProgrammeCommandResultKind.PROPOSAL,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=(
                "state",
                "sealed_revision",
                "submitted_revision",
            ),
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    operation="revision_response",
)
@transaction.atomic
def respond_to_programme_proposal_revision(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    response: ProgrammeProposalRevisionResponseInput,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Acknowledge or decline the actor's exact included sealed revision.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified included contributor account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact sealed proposal identifier.
    response : ProgrammeProposalRevisionResponseInput
        Exact revision, profile revision, and acknowledgement decision.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for submission-window checks.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and exact revision-response cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the proposal is not awaiting this exact contributor response.
    ApplicationsProgrammeUnavailableError
        If the response arrives outside the configured submission window.
    ValidationError
        If the exact revision, contributor, or profile evidence is invalid.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = common
    if not isinstance(response, ProgrammeProposalRevisionResponseInput):
        raise ValidationError(
            "Revision responses require a closed typed input.",
            code="applications_programme_input_invalid",
        )
    effective_now = _effective_now(now)
    action = (
        ProgrammeCommandAction.REVISION_ACKNOWLEDGED
        if response.decision == ProgrammeProposalRevisionResponseDecision.ACKNOWLEDGED
        else ProgrammeCommandAction.REVISION_DECLINED
    )
    response_kind = (
        ProgrammeRevisionResponseKind.ACKNOWLEDGED
        if action == ProgrammeCommandAction.REVISION_ACKNOWLEDGED
        else ProgrammeRevisionResponseKind.DECLINED
    )
    digest = _request_digest(
        action=action,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"response": asdict(response)},
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
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="collaborator",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="collaborator",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_submission_window(proposal=proposal, effective_now=effective_now)
    if (
        proposal.state != ProgrammeProposalState.SEALED
        or proposal.sealed_revision_id != response.revision_id
    ):
        raise ApplicationsProgrammeStateConflictError
    contributor = (
        ProgrammeProposalRevisionContributor.objects.select_for_update()
        .select_related("revision", "profile_revision")
        .filter(
            id=response.contributor_id,
            revision_id=response.revision_id,
            revision__proposal=proposal,
            account_id=actor_id,
            role=ProgrammeContributorRole.COLLABORATOR,
            profile_revision_id=response.profile_revision_id,
        )
        .first()
    )
    if contributor is None:
        raise ApplicationsProgrammeUnavailableError
    if ProgrammeProposalRevisionResponse.objects.filter(
        revision_id=response.revision_id,
        contributor=contributor,
    ).exists():
        raise ApplicationsProgrammeStateConflictError
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        response_row = ProgrammeProposalRevisionResponse.objects.create(
            organization_id=organization_id,
            edition_id=edition_id,
            revision_id=response.revision_id,
            contributor=contributor,
            account_id=actor_id,
            response=response_kind,
            profile_revision_id=response.profile_revision_id,
            actor_id=actor_id,
            source_version=expected_version,
            resulting_version=resulting_version,
            responded_at=effective_now,
        )
        _advance_submission(
            proposal.submission,
            resulting_version=resulting_version,
        )
        return _record_success(
            scope=scope,
            action=action,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=proposal.submission,
            target_id=response_row.id,
            result_kind=ProgrammeCommandResultKind.REVISION_RESPONSE,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("own_revision_response",),
            occurred_at=effective_now,
        )


def _require_revision_acknowledged(
    *,
    revision: ProgrammeProposalRevision,
) -> None:
    contributors = revision.contributors.filter(
        role=ProgrammeContributorRole.COLLABORATOR,
    ).order_by("account_id", "id")
    for contributor in contributors:
        if (
            resolve_active_verified_person_reference(
                account_id=contributor.account_id,
                lock=True,
            )
            is None
        ):
            raise ApplicationsProgrammeCompletenessError
        responses = ProgrammeProposalRevisionResponse.objects.filter(
            revision=revision,
            contributor=contributor,
            account_id=contributor.account_id,
            profile_revision_id=contributor.profile_revision_id,
        )
        response = responses.first()
        if (
            response is None
            or response.response != ProgrammeRevisionResponseKind.ACKNOWLEDGED
        ):
            raise ApplicationsProgrammeCompletenessError


@_audit_command_errors(
    capability_code=APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.PROPOSAL_SUBMITTED,
)
@transaction.atomic
def submit_programme_proposal(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    revision_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Submit exactly the current fully acknowledged sealed revision.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact sealed proposal identifier.
    revision_id : UUID
        Exact current sealed revision identifier.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware instant used for submission-window checks.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and submitted-proposal cursor.

    Raises
    ------
    ApplicationsProgrammeCompletenessError
        If any included collaborator has not acknowledged the exact revision.
    ApplicationsProgrammeStateConflictError
        If the proposal or revision is not the current sealed aggregate.
    ApplicationsProgrammeUnavailableError
        If the call no longer accepts submission.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = common
    revision_id = require_programme_uuid(revision_id, field="revision_id")
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.PROPOSAL_SUBMITTED,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
        values={"revision_id": revision_id},
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
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    _require_submission_window(proposal=proposal, effective_now=effective_now)
    if (
        proposal.state != ProgrammeProposalState.SEALED
        or proposal.sealed_revision_id != revision_id
        or proposal.submitted_revision_id is not None
    ):
        raise ApplicationsProgrammeStateConflictError
    revision = (
        ProgrammeProposalRevision.objects.select_for_update()
        .filter(id=revision_id, proposal=proposal)
        .first()
    )
    if revision is None:
        raise ApplicationsProgrammeUnavailableError
    if ProgrammeProposalCollaborator.objects.filter(
        proposal=proposal,
        state=ProgrammeCollaboratorState.INVITED,
        invite_expires_at__gt=effective_now,
    ).exists():
        raise ApplicationsProgrammeCompletenessError
    _require_revision_acknowledged(revision=revision)
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        proposal.state = ProgrammeProposalState.SUBMITTED
        proposal.submitted_revision = revision
        proposal.save()
        submission = proposal.submission
        submission.state = ApplicationState.SUBMITTED
        submission.submitted_at = effective_now
        submission.withdrawn_at = None
        _advance_submission(submission, resulting_version=resulting_version)
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.PROPOSAL_SUBMITTED,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=submission,
            target_id=revision.id,
            result_kind=ProgrammeCommandResultKind.PROPOSAL_REVISION,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("state", "submitted_revision", "submitted_at"),
            occurred_at=effective_now,
        )


@_audit_command_errors(
    capability_code=APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
    operation=ProgrammeCommandAction.PROPOSAL_WITHDRAWN,
)
@transaction.atomic
def withdraw_programme_proposal(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCommandResult:
    """Withdraw a draft, sealed, or submitted proposal while retaining history.

    Parameters
    ----------
    actor_id : UUID
        Exact active verified lead account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact draft, sealed, or submitted proposal identifier.
    expected_version : int
        Optimistic proposal aggregate version.
    reason : str
        Inspectable subject-provided rationale.
    retry_key : UUID
        Idempotency key in the shared Applications namespace.
    correlation_id : UUID
        Correlation identifier for receipt, audit, and event evidence.
    source_channel : str
        Registered channel that initiated the command.
    now : datetime | None, default=None
        Optional aware execution instant for retained evidence.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCommandResult
        Retained receipt and withdrawn-proposal cursor.

    Raises
    ------
    ApplicationsProgrammeStateConflictError
        If the proposal is already withdrawn or otherwise not withdrawable.
    """
    common = _proposal_command_common(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    (
        actor_id,
        organization_id,
        edition_id,
        proposal_id,
        expected_version,
        reason,
        retry_key,
        correlation_id,
        source_channel,
    ) = common
    effective_now = _effective_now(now)
    digest = _request_digest(
        action=ProgrammeCommandAction.PROPOSAL_WITHDRAWN,
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        target_id=proposal_id,
        expected_version=expected_version,
        reason=reason,
        source_channel=source_channel,
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
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=False,
        effective_now=effective_now,
    )
    scope = _proposal_preflight(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_SUBMIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        relationship="lead",
        lock=True,
        effective_now=effective_now,
    )
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
    )
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=expected_version,
    )
    if proposal.state not in {
        ProgrammeProposalState.DRAFT,
        ProgrammeProposalState.SEALED,
        ProgrammeProposalState.SUBMITTED,
    }:
        raise ApplicationsProgrammeStateConflictError
    resulting_version = expected_version + 1
    with programme_application_database_writer():
        proposal.state = ProgrammeProposalState.WITHDRAWN
        proposal.save()
        submission = proposal.submission
        submission.state = ApplicationState.WITHDRAWN
        submission.withdrawn_at = effective_now
        _advance_submission(submission, resulting_version=resulting_version)
        return _record_success(
            scope=scope,
            action=ProgrammeCommandAction.PROPOSAL_WITHDRAWN,
            definition=proposal.call.definition,
            call=proposal.call,
            proposal=proposal,
            submission=submission,
            target_id=proposal.id,
            result_kind=ProgrammeCommandResultKind.PROPOSAL,
            expected_version=expected_version,
            resulting_version=resulting_version,
            request_digest=digest,
            reason=reason,
            retry_key=retry_key,
            correlation_id=correlation_id,
            source_channel=source_channel,
            changed_fields=("state", "withdrawn_at"),
            occurred_at=effective_now,
        )


__all__ = [
    "ApplicationsProgrammeCommandError",
    "ApplicationsProgrammeCompletenessError",
    "ApplicationsProgrammeIdempotencyConflictError",
    "ApplicationsProgrammeStateConflictError",
    "ApplicationsProgrammeUnavailableError",
    "ApplicationsProgrammeVersionConflictError",
    "ProgrammeCommandResult",
    "accept_programme_proposal_invitation",
    "activate_programme_call",
    "append_programme_proposal_answer",
    "configure_programme_call",
    "create_programme_call",
    "create_programme_call_successor",
    "decline_programme_proposal_invitation",
    "invite_programme_proposal_collaborator",
    "leave_programme_proposal",
    "reassign_programme_call",
    "recover_orphaned_programme_call_reassignment",
    "recover_orphaned_programme_call_retirement",
    "reinvite_programme_proposal_collaborator",
    "remove_programme_proposal_collaborator",
    "reopen_programme_proposal",
    "respond_to_programme_proposal_revision",
    "retire_programme_call",
    "revise_programme_contributor_profile",
    "revise_programme_proposal_selection",
    "seal_programme_proposal",
    "start_programme_proposal",
    "submit_programme_proposal",
    "withdraw_programme_proposal",
]
