"""Exact-person proposal references, never relationships or directory authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core import signing
from django.db import transaction
from django.utils import timezone

from maru.identity.queries import (
    active_verified_person_account_display_labels,
    resolve_active_verified_person_reference_by_email,
)

from . import programme_personal_queries as personal
from . import programme_queries as queries
from .programme_authorization import (
    APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF,
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    authorize_programme_proposal_scope,
)
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_commands import ApplicationsProgrammeVersionConflictError as Conflict
from .programme_inputs import require_programme_uuid
from .programme_personal_queries import _same_scope
from .programme_queries import _append_sensitive_read, _audit_inputs

if TYPE_CHECKING:
    from .programme_authorization import (
        ApplicationsProgrammeAuthorizer,
        AuthorizedProgrammeProposalScope,
    )

PERSON_REFERENCE_KIND = "programme.person"
MAX_PERSON_SELECTION_BYTES = 2048
_SALT = "applications.programme-person-answer.v1"
_FIELDS = frozenset({"proposal_summary", "answers"})
_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ProgrammePersonReferenceRequest:
    """Identify an exact self-owned answer read, not caller-supplied authority.

    Attributes
    ----------
    actor_id : UUID
        Genuine current person requesting the task.
    organization_id : UUID
        Exact expected organization.
    edition_id : UUID
        Exact expected edition.
    proposal_id : UUID
        Exact relationship-owned proposal.
    question_id : UUID
        Immutable question identifier, never a selected account identifier.
    correlation_id : UUID
        Protected-read audit correlation.
    source_channel : str
        Registered calling surface, without request input.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    proposal_id: UUID
    question_id: UUID
    correlation_id: UUID
    source_channel: str


@dataclass(frozen=True, slots=True)
class ProgrammePersonReferenceIntent:
    """Retain original source cursors and retry identity through confirmation.

    Attributes
    ----------
    expected_version : int
        Original sole proposal aggregate version.
    expected_call_version : int
        Original call aggregate version.
    expected_definition_version : int
        Original immutable form schema version.
    retry_key : UUID
        Original command intent, not regenerated on retry.
    """

    expected_version: int
    expected_call_version: int
    expected_definition_version: int
    retry_key: UUID


@dataclass(frozen=True, slots=True)
class ProgrammePersonSelection:
    """Present one original person or explicit clear without contact information.

    Attributes
    ----------
    account_id : UUID | None
        Exact selected person, or explicit clear; never a replacement account.
    display_label : str
        Current minimized account label or neutral retained-reference feedback.
    person_current : bool
        Whether Identity currently admits this exact account's label.
    intent : ProgrammePersonReferenceIntent
        Unchanged original source and retry evidence.
    token : str
        Bounded identifier-only purpose-signed integrity proof, not authority.
    """

    account_id: UUID | None
    display_label: str
    person_current: bool
    intent: ProgrammePersonReferenceIntent
    token: str


def _values(request: ProgrammePersonReferenceRequest) -> dict[str, Any]:
    values = asdict(request)
    for key in values.keys() - {"source_channel"}:
        require_programme_uuid(values[key], field=key)
    values.pop("question_id")
    return values


def _intent(intent: ProgrammePersonReferenceIntent) -> None:
    require_programme_uuid(intent.retry_key, field="retry_key")
    if any(
        type(value) is not int or not 1 <= value <= 2**63 - 1
        for key, value in asdict(intent).items()
        if key != "retry_key"
    ):
        raise Denied


def _binding(request: ProgrammePersonReferenceRequest) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in asdict(request).items()
        if key not in {"correlation_id", "source_channel"}
    }


def _scope(
    request: ProgrammePersonReferenceRequest,
    authorizer: ApplicationsProgrammeAuthorizer,
    *,
    write: bool = False,
    fields: frozenset[str] = _FIELDS,
) -> AuthorizedProgrammeProposalScope:
    values = _values(request)
    values.pop("correlation_id")
    values.pop("source_channel")
    scope = authorize_programme_proposal_scope(
        **values,
        capability_code=(
            APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF
            if write
            else APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF
        ),
        requested_fields=None if write else fields,
        authorizer=authorizer,
    )
    if scope.relationship not in {"lead", "collaborator"}:
        raise Denied
    return scope


def _audit(
    request: ProgrammePersonReferenceRequest,
    authorizer: ApplicationsProgrammeAuthorizer,
    fields: frozenset[str] = _FIELDS,
) -> None:
    correlation, channel = _audit_inputs(
        correlation_id=request.correlation_id, source_channel=request.source_channel
    )
    _append_sensitive_read(
        scope=_scope(request, authorizer, fields=fields),
        operation="applications.programme.query.person_reference",
        target_id=request.proposal_id,
        correlation_id=correlation,
        source_channel=channel,
        occurred_at=timezone.now(),
    )


def _answer(
    answers: tuple[queries.ProgrammeAnswerProjection, ...] | None, question_id: UUID
) -> queries.ProgrammeAnswerProjection:
    rows = tuple(
        row for row in answers or () if row.question.question_id == question_id
    )
    if len(rows) != 1 or (
        rows[0].question.field_type,
        rows[0].question.reference_kind,
    ) != ("person_reference", PERSON_REFERENCE_KIND):
        raise Denied
    return rows[0]


def _source(
    request: ProgrammePersonReferenceRequest,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> tuple[
    personal.ProgrammePersonalWorkflow, queries.ProgrammeProposalDetailProjection
]:
    values = _values(request)
    context = personal.get_self_programme_workflow(**values, authorizer=authorizer)
    detail = queries.get_self_programme_proposal_detail(
        **values, requested_fields=_FIELDS, authorizer=authorizer
    )
    if (
        context.summary != detail.summary
        or detail.requested_fields != _FIELDS
        or context.summary.proposal_id != request.proposal_id
    ):
        raise Denied
    _same_scope(context.summary, _scope(request, authorizer))
    writer = _scope(request, authorizer, write=True)
    _same_scope(context.summary, writer)
    if writer.accepts_private_planning_writes != context.planning:
        raise Denied
    return context, detail


def _fresh(
    context: personal.ProgrammePersonalWorkflow, intent: ProgrammePersonReferenceIntent
) -> None:
    now = timezone.now()
    if (
        context.summary.aggregate_version != intent.expected_version
        or context.call_version != intent.expected_call_version
        or context.definition_version != intent.expected_definition_version
        or context.summary.state != "draft"
        or not context.planning
        or context.call_status != "active"
        or not context.opens_at <= now <= context.edit_until
    ):
        raise Conflict


def _projection(
    account_id: UUID | None, intent: ProgrammePersonReferenceIntent, token: str
) -> ProgrammePersonSelection:
    labels = (
        active_verified_person_account_display_labels((account_id,))
        if account_id is not None
        else {}
    )
    label = (
        labels.get(account_id, "Unavailable person; the original reference is retained")
        if account_id is not None
        else "Clear this answer"
    )
    return ProgrammePersonSelection(
        account_id, label, account_id in labels, intent, token
    )


@transaction.atomic
def prepare_programme_person_selection(
    *,
    request: ProgrammePersonReferenceRequest,
    intent: ProgrammePersonReferenceIntent,
    email: str | None,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammePersonSelection | None:
    """Prepare an audited exact known-person or explicit clear intent.

    Parameters
    ----------
    request : ProgrammePersonReferenceRequest
        Exact genuine contributor and question context.
    intent : ProgrammePersonReferenceIntent
        Original proposal, call, schema and retry evidence.
    email : str | None
        Exact known login email, or deliberate clear when None; never retained.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Real policy or established isolated-test admission seam.

    Returns
    -------
    ProgrammePersonSelection | None
        Audited minimized confirmation, or one non-disclosing empty lookup result.

    Raises
    ------
    Denied
        If the exact registered question or repeated source is not authorized.
    """
    _intent(intent)
    source = _source(request, authorizer)
    _answer(source[1].answers, request.question_id)
    _fresh(source[0], intent)
    account_id = None
    if email is not None:
        person = resolve_active_verified_person_reference_by_email(email=email)
        account_id = person.account_id if person is not None else None
    result = None
    if email is None or account_id is not None:
        token = signing.dumps(
            _binding(request)
            | {
                key: str(value) if isinstance(value, UUID) else value
                for key, value in asdict(intent).items()
            }
            | {"person": str(account_id) if account_id is not None else None},
            salt=_SALT,
        )
        selected = _projection(account_id, intent, token)
        if email is None or selected.person_current:
            result = selected
    if _source(request, authorizer) != source:
        raise Denied
    _fresh(source[0], intent)
    _audit(request, authorizer)
    return result


@dataclass(frozen=True, slots=True)
class ProgrammePersonReferenceView:
    """Keep complete authorized source for final comparison beside minimal text.

    Attributes
    ----------
    source : object
        Complete independently audited owner projection; never rendered wholesale.
    question_label : str
        Exact authorized question label.
    display_label : str
        Current minimized account label, or neutral empty/unavailable explanation.
    present : bool
        Whether the answer retains a person reference.
    person_current : bool
        Whether this exact account currently admits the displayed label.
    """

    source: object
    question_label: str
    display_label: str
    present: bool
    person_current: bool


def _view(source: object, label: str, value: object) -> ProgrammePersonReferenceView:
    if value is None:
        return ProgrammePersonReferenceView(
            source, label, "No person selected", present=False, person_current=False
        )
    if not isinstance(value, str):
        raise Denied
    try:
        account = UUID(value)
    except ValueError as error:
        raise Denied from error
    if not account.int or str(account) != value:
        raise Denied
    labels = active_verified_person_account_display_labels((account,))
    return ProgrammePersonReferenceView(
        source,
        label,
        labels.get(account, "Unavailable person; the original reference is retained"),
        present=True,
        person_current=account in labels,
    )


@transaction.atomic
def get_self_programme_person_reference(
    *,
    request: ProgrammePersonReferenceRequest,
    revision_id: UUID | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammePersonReferenceView:
    """Resolve only the person in an authorized current or sealed answer.

    Parameters
    ----------
    request : ProgrammePersonReferenceRequest
        Genuine current contributor and exact question, not an account URL.
    revision_id : UUID | None, default=None
        Exact current seal for an included contributor, or current draft answer.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Real policy or established isolated-test admission seam.

    Returns
    -------
    ProgrammePersonReferenceView
        Minimal current label and complete source evidence for final revalidation.

    Raises
    ------
    Denied
        If registered meaning, relationship or repeated source admission changes.
    """
    values = _values(request)
    fields = (
        _FIELDS
        if revision_id is None
        else frozenset({"proposal_summary", "frozen_revision"})
    )

    def source() -> (
        queries.ProgrammeProposalDetailProjection
        | personal.ProgrammePersonalFrozenRevision
    ):
        admitted = _scope(request, authorizer, fields=fields)
        if revision_id is None:
            result = queries.get_self_programme_proposal_detail(
                **values, requested_fields=fields, authorizer=authorizer
            )
            if result.summary is None or result.requested_fields != fields:
                raise Denied
            _same_scope(result.summary, admitted)
            return result
        frozen = personal.get_self_programme_frozen_revision(
            **values, revision_id=revision_id, authorizer=authorizer
        )
        _same_scope(frozen.summary, admitted)
        if frozen.revision.revision_id != revision_id:
            raise Denied
        return frozen

    original = source()
    answer = _answer(original.answers, request.question_id)
    result = _view(original, answer.question.label, answer.value)
    if source() != original:
        raise Denied
    _audit(request, authorizer, fields)
    return result


def _decode(
    request: ProgrammePersonReferenceRequest,
    intent: ProgrammePersonReferenceIntent,
    token: str,
) -> UUID | None:
    try:
        if (
            not isinstance(token, str)
            or not token
            or len(token.encode("ascii")) > MAX_PERSON_SELECTION_BYTES
            or token.startswith(".")
        ):
            raise Denied
        value = signing.loads(token, salt=_SALT)
        binding: dict[str, object] = _binding(request) | {
            key: str(item) if isinstance(item, UUID) else item
            for key, item in asdict(intent).items()
        }
        if (
            not isinstance(value, dict)
            or set(value) != {*binding, "person"}
            or any(
                type(value[key]) is not type(item) or value[key] != item
                for key, item in binding.items()
            )
        ):
            raise Denied
        if value["person"] is None:
            return None
        if not isinstance(value["person"], str):
            raise Denied
        account = UUID(value["person"])
        if not account.int or str(account) != value["person"]:
            raise Denied
    except (signing.BadSignature, TypeError, ValueError) as error:
        raise Denied from error
    return account


@transaction.atomic
def read_programme_person_selection(
    *,
    request: ProgrammePersonReferenceRequest,
    intent: ProgrammePersonReferenceIntent,
    token: str,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammePersonSelection:
    """Reauthorize original-person intent without email or fresh-version rebasing.

    Parameters
    ----------
    request : ProgrammePersonReferenceRequest
        Exact current contributor and original immutable question context.
    intent : ProgrammePersonReferenceIntent
        Original source and retry binding, including after a committed attempt.
    token : str
        Original bounded uncompressed purpose-signed identifier proof.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Real policy or established isolated-test admission seam.

    Returns
    -------
    ProgrammePersonSelection
        Current minimized label or neutral fallback with unchanged command intent.

    Raises
    ------
    Denied
        If repeated source admission changes before protected disclosure.
    """
    _intent(intent)
    source = _source(request, authorizer)
    account = _decode(request, intent, token)
    result = _projection(account, intent, token)
    if _source(request, authorizer) != source:
        raise Denied
    _audit(request, authorizer)
    return result
