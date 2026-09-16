"""Authorize, scan and atomically use one exact private supporting PDF."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.db import connection, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import programme_commands as commands
from . import programme_file_preparation as preparation
from .models import (
    MAX_PROGRAMME_FILE_INTAKES,
    MAX_PROGRAMME_PROPOSAL_FILE_BYTES,
    ApplicationFileReceipt,
    ApplicationQuestion,
    ProgrammeCommandAction,
    ProgrammeFileContent,
    ProgrammeFileIntake,
)
from .programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    authorize_programme_proposal_scope,
    authorize_programme_retry_scope,
)
from .programme_commands import (
    _append_failure_audit_best_effort,
    _latest_answer_map,
    _locked_proposal,
    _proposal_command_common,
    _question_is_applicable,
    _request_digest,
    _require_draft_edit_window,
    _require_private_writes,
    _require_proposal_scope_match,
    _require_version,
)
from .programme_commands import (
    _replay as _answer_replay,
)
from .programme_file_preparation import _configuration as _scanner_configuration
from .programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
    _fresh,
    _intent,
    _source,
    _values,
)
from .programme_writer_boundary import programme_application_database_writer
from .retry_namespace import lock_applications_retry_namespace

if TYPE_CHECKING:
    from collections.abc import Callable

    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_Conflict = commands.ApplicationsProgrammeIdempotencyConflictError
_Unavailable = commands.ApplicationsProgrammeUnavailableError
_UPLOAD_REASON = "Upload and use this supporting file."


class ProgrammeFileQuotaError(commands.ApplicationsProgrammeStateConflictError):
    """Refuse overflow without discarding a retained supporting document."""


def _arguments(
    request: ProgrammeAnswerReferenceRequest, intent: ProgrammeAnswerReferenceIntent
) -> dict[str, Any]:
    if (
        type(request) is not ProgrammeAnswerReferenceRequest
        or type(intent) is not ProgrammeAnswerReferenceIntent
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    _intent(intent)
    values = _values(request)
    common = _proposal_command_common(
        **values,
        expected_version=intent.expected_version,
        reason=_UPLOAD_REASON,
        retry_key=intent.retry_key,
    )
    if intent.expected_version > 2**63 - 2:
        raise _Unavailable
    return {
        **values,
        "question_id": request.question_id,
        "expected_version": intent.expected_version,
        "reason": common[5],
        "retry_key": intent.retry_key,
        "source_channel": common[8],
        "expected_call_version": intent.expected_call_version,
        "expected_definition_version": intent.expected_definition_version,
    }


def _retry_values(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: arguments[key]
        for key in ("actor_id", "organization_id", "edition_id", "retry_key")
    }


def _digest(arguments: dict[str, Any], receipt_id: UUID) -> str:
    return _request_digest(
        action=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
        actor_id=arguments["actor_id"],
        organization_id=arguments["organization_id"],
        edition_id=arguments["edition_id"],
        target_id=arguments["proposal_id"],
        expected_version=arguments["expected_version"],
        reason=arguments["reason"],
        source_channel=arguments["source_channel"],
        values={
            "question_id": arguments["question_id"],
            "value": str(receipt_id),
            "expected_call_version": arguments["expected_call_version"],
            "expected_definition_version": arguments["expected_definition_version"],
        },
    )


def _replay(
    arguments: dict[str, Any],
    receipt_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> commands.ProgrammeCommandResult | None:
    return _answer_replay(
        **_retry_values(arguments),
        request_digest=_digest(arguments, receipt_id),
        authorizer=authorizer,
    )


def _capacity(arguments: dict[str, Any], *, additional_bytes: int) -> None:
    totals = ProgrammeFileIntake.objects.filter(
        organization_id=arguments["organization_id"],
        edition_id=arguments["edition_id"],
        proposal_id=arguments["proposal_id"],
    ).aggregate(count=Count("id"), size=Sum("file_receipt__size_bytes"))
    count, size = totals["count"], totals["size"] or 0
    if (
        count >= MAX_PROGRAMME_FILE_INTAKES
        or size + additional_bytes > MAX_PROGRAMME_PROPOSAL_FILE_BYTES
    ):
        raise ProgrammeFileQuotaError


def _question(
    arguments: dict[str, Any], call_id: UUID, *, lock: bool
) -> ApplicationQuestion:
    rows = ApplicationQuestion.objects.filter(
        id=arguments["question_id"],
        definition__programme_call__id=call_id,
        definition__organization_id=arguments["organization_id"],
        definition__edition_id=arguments["edition_id"],
        field_type="safe_file",
        applicant_visible=True,
        applicant_writable=True,
        source_binding="",
        staff_visible=False,
        staff_writable=False,
        reviewer_visible=False,
        public_after_approval=False,
        api_projection=False,
    )
    row = (rows.select_for_update() if lock else rows).first()
    if row is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    return row


@transaction.atomic
def _preflight(
    request: ProgrammeAnswerReferenceRequest,
    intent: ProgrammeAnswerReferenceIntent,
    arguments: dict[str, Any],
    authorizer: ApplicationsProgrammeAuthorizer,
) -> None:
    # A new server-only receipt identity deliberately cannot replay a used upload.
    # Used keys fail before any body read; the body-free result query is separate.
    if _replay(arguments, uuid4(), authorizer) is not None:
        raise _Conflict
    source = _source(request, authorizer)
    _fresh(source[0], intent)
    rows = tuple(
        row
        for row in source[1].answers or ()
        if row.question.question_id == request.question_id
    )
    if len(rows) != 1 or rows[0].question.field_type != "safe_file":
        raise ApplicationsProgrammeAuthorizationDeniedError
    _question(arguments, source[0].summary.call_id, lock=False)
    _capacity(arguments, additional_bytes=1)
    if _source(request, authorizer) != source:
        raise ApplicationsProgrammeAuthorizationDeniedError
    _fresh(source[0], intent)


def _lock_retry(
    arguments: dict[str, Any], authorizer: ApplicationsProgrammeAuthorizer
) -> None:
    scope = _retry_values(arguments)
    authorize_programme_retry_scope(
        **{key: value for key, value in scope.items() if key != "retry_key"},
        authorizer=authorizer,
    )
    lock_applications_retry_namespace(
        edition_id=arguments["edition_id"],
        actor_id=arguments["actor_id"],
        retry_key=arguments["retry_key"],
    )


def _retained(arguments: dict[str, Any]) -> ProgrammeFileIntake | None:
    row = (
        ProgrammeFileIntake.objects.select_related("file_receipt")
        .filter(
            **_retry_values(arguments),
        )
        .first()
    )
    if row is None:
        return None
    expected = {
        "proposal_id": arguments["proposal_id"],
        "question_id": arguments["question_id"],
        "source_version": arguments["expected_version"],
        "call_version": arguments["expected_call_version"],
        "definition_version": arguments["expected_definition_version"],
    }
    if any(getattr(row, field) != value for field, value in expected.items()):
        raise _Conflict
    receipt = row.file_receipt
    if (
        receipt.organization_id != arguments["organization_id"]
        or receipt.edition_id != arguments["edition_id"]
        or receipt.account_id != arguments["actor_id"]
        or receipt.status != "clean"
        or receipt.media_type != "application/pdf"
        or receipt.storage_key != f"programme-db/{row.id}"
        or receipt.scanner_receipt != "clamav-instream@1"
    ):
        raise _Unavailable
    return row


def _completed(
    arguments: dict[str, Any],
    retained: ProgrammeFileIntake,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> commands.ProgrammeCommandResult:
    result = _replay(arguments, retained.file_receipt_id, authorizer)
    if result is None:
        # Missing success evidence is corruption/unavailable, never a new write.
        raise _Unavailable
    return result


@transaction.atomic
def _persist(
    arguments: dict[str, Any],
    prepared: preparation.PreparedProgrammeFile,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> commands.ProgrammeCommandResult:
    _lock_retry(arguments, authorizer)
    retained = _retained(arguments)
    if retained is not None:
        if (
            retained.file_receipt.size_bytes != prepared.size_bytes
            or not hmac.compare_digest(retained.file_receipt.sha256, prepared.sha256)
        ):
            raise _Conflict
        return _completed(arguments, retained, authorizer)
    receipt_id = uuid4()
    if _replay(arguments, receipt_id, authorizer) is not None:
        raise _Conflict
    read_scope = authorize_programme_proposal_scope(
        actor_id=arguments["actor_id"],
        organization_id=arguments["organization_id"],
        edition_id=arguments["edition_id"],
        proposal_id=arguments["proposal_id"],
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=frozenset({"proposal_summary", "answers"}),
        authorizer=authorizer,
        lock=True,
    )
    scope = authorize_programme_proposal_scope(
        actor_id=arguments["actor_id"],
        organization_id=arguments["organization_id"],
        edition_id=arguments["edition_id"],
        proposal_id=arguments["proposal_id"],
        capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
        authorizer=authorizer,
        lock=True,
    )
    if scope.relationship not in {"lead", "collaborator"}:
        raise ApplicationsProgrammeAuthorizationDeniedError
    _require_private_writes(scope)
    proposal = _locked_proposal(
        organization_id=arguments["organization_id"],
        edition_id=arguments["edition_id"],
        proposal_id=arguments["proposal_id"],
    )
    _require_proposal_scope_match(scope=scope, proposal=proposal)
    _require_proposal_scope_match(scope=read_scope, proposal=proposal)
    _require_version(
        actual=proposal.submission.aggregate_version,
        expected=arguments["expected_version"],
    )
    _require_version(
        actual=proposal.call.definition.aggregate_version,
        expected=arguments["expected_call_version"],
    )
    _require_version(
        actual=proposal.call.definition.version,
        expected=arguments["expected_definition_version"],
    )
    _require_draft_edit_window(proposal=proposal, effective_now=timezone.now())
    question = _question(arguments, proposal.call_id, lock=True)
    if not _question_is_applicable(
        question=question,
        answers=_latest_answer_map(
            submission=proposal.submission,
            through_version=arguments["expected_version"],
        ),
    ):
        raise commands.ApplicationsProgrammeStateConflictError
    _capacity(arguments, additional_bytes=prepared.size_bytes)
    intake_id = uuid4()
    with programme_application_database_writer():
        receipt = ApplicationFileReceipt.objects.create(
            id=receipt_id,
            organization_id=arguments["organization_id"],
            edition_id=arguments["edition_id"],
            account_id=arguments["actor_id"],
            status="clean",
            sha256=prepared.sha256,
            size_bytes=prepared.size_bytes,
            media_type=prepared.media_type,
            storage_key=f"programme-db/{intake_id}",
            scanner_receipt=prepared.scanner_code,
        )
        intake = ProgrammeFileIntake.objects.create(
            id=intake_id,
            organization_id=arguments["organization_id"],
            edition_id=arguments["edition_id"],
            actor_id=arguments["actor_id"],
            proposal=proposal,
            question=question,
            file_receipt=receipt,
            source_version=arguments["expected_version"],
            call_version=arguments["expected_call_version"],
            definition_version=arguments["expected_definition_version"],
            retry_key=arguments["retry_key"],
            scanned_at=prepared.scanned_at,
        )
        ProgrammeFileContent.objects.create(intake=intake, payload=prepared.data)
        return commands.append_programme_proposal_answer(
            **arguments,
            value=str(receipt.id),
            authorizer=authorizer,
        )


def _read_body(reader: Callable[[], bytes]) -> bytes:
    data = reader()
    if connection.in_atomic_block:
        raise preparation.ProgrammeFileUnavailableError(
            "Programme uploads require a transaction-free transport boundary."
        )
    return data


def upload_and_use_programme_file(
    *,
    request: ProgrammeAnswerReferenceRequest,
    intent: ProgrammeAnswerReferenceIntent,
    read_bytes: Callable[[], bytes],
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> commands.ProgrammeCommandResult:
    """Authorize before reading, scan without locks and atomically select the PDF.

    Parameters
    ----------
    request : ProgrammeAnswerReferenceRequest
        Genuine contributor and exact immutable private question scope.
    intent : ProgrammeAnswerReferenceIntent
        Original proposal/call/schema versions and canonical retry key.
    read_bytes : Callable[[], bytes]
        Trusted transport reader that enforces the 10-MiB bound while reading;
        invoked once, only after admission. No filename or scan assertion is accepted.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Sealed production admission or the established isolated-test adapter.

    Returns
    -------
    commands.ProgrammeCommandResult
        The sole canonical first-answer receipt, or an exact concurrent replay.

    Raises
    ------
    preparation.ProgrammeFileUnavailableError
        If an enclosing transaction would retain locks while reading/scanning.
    Exception
        An existing admission, transport, scan or persistence failure is re-raised
        after its minimized failure audit; no partial custody is retained.

    Notes
    -----
    Denial, stale state, quota, conflicting retry and scanner errors propagate
    without durable custody. Failures receive the existing minimized answer-command
    audit after rollback. A consumed key never reads a new body: use the explicit
    body-free result check. No download permission or current profile is added.
    """
    if connection.in_atomic_block:
        raise preparation.ProgrammeFileUnavailableError(
            "Programme uploads require a transaction-free transport boundary."
        )
    try:
        arguments = _arguments(request, intent)
        _preflight(request, intent, arguments, authorizer)
        _scanner_configuration()
        data = _read_body(read_bytes)
        prepared = preparation.prepare_programme_pdf(data=data)
        return _persist(arguments, prepared, authorizer)
    except Exception as error:
        _append_failure_audit_best_effort(
            error=error,
            actor_id=getattr(request, "actor_id", None),
            organization_id=getattr(request, "organization_id", None),
            edition_id=getattr(request, "edition_id", None),
            capability_code=APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
            operation=ProgrammeCommandAction.PROPOSAL_ANSWER_REVISED,
            correlation_id=getattr(request, "correlation_id", None),
            source_channel=getattr(request, "source_channel", None),
        )
        raise


@transaction.atomic
def get_programme_file_upload_result(
    *,
    request: ProgrammeAnswerReferenceRequest,
    intent: ProgrammeAnswerReferenceIntent,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> commands.ProgrammeCommandResult | None:
    """Resolve only the original upload outcome without reading or scanning a body.

    Parameters
    ----------
    request : ProgrammeAnswerReferenceRequest
        Genuine original actor and exact original proposal/question scope.
    intent : ProgrammeAnswerReferenceIntent
        Original versions and retry identity, never freshly substituted cursors.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Complete existing retry-scope admission, not attachment-read authority.

    Returns
    -------
    commands.ProgrammeCommandResult | None
        Exact minimized retained result, or no completed upload for this intent.

    Raises
    ------
    _Conflict
        If the original retry identity belongs to a different canonical command.

    Notes
    -----
    Scope/version mismatches conflict; incomplete evidence is unavailable. This
    query never creates an answer, discloses bytes or grants later download access.
    """
    arguments = _arguments(request, intent)
    _lock_retry(arguments, authorizer)
    retained = _retained(arguments)
    if retained is None:
        if _replay(arguments, uuid4(), authorizer) is not None:
            raise _Conflict
        return None
    return _completed(arguments, retained, authorizer)
