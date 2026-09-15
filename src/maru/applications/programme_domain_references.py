"""Question-scoped same-call choices and original-target confirmation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core import signing
from django.db import transaction
from django.utils import timezone

from . import programme_personal_queries as personal
from . import programme_queries as queries
from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
)
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_domain_targets import (
    DOMAIN_REFERENCE_KINDS,
    ProgrammeDomainOption,
    _domain_options,
    _domain_target,
)
from .programme_personal_queries import _same_scope
from .programme_queries import _append_sensitive_read, _audit_inputs
from .programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
    _binding,
    _fresh,
    _intent,
    _scope,
    _source,
    _values,
)

if TYPE_CHECKING:
    from .programme_authorization import ApplicationsProgrammeAuthorizer

_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_FIELDS = frozenset({"proposal_summary", "answers"})
_SALT = "applications.programme-domain-answer.v1"
MAX_DOMAIN_SELECTION_BYTES = 2300


@dataclass(frozen=True, slots=True)
class ProgrammeDomainChoices:
    """Keep a complete question-scoped catalog and its independently read source.

    Attributes
    ----------
    source : object
        Full source comparison evidence, never rendered wholesale.
    question : queries.ProgrammeQuestionProjection
        Independently admitted shared-answer question.
    options : tuple[ProgrammeDomainOption, ...]
        Complete same-call catalog, not a global directory.
    """

    source: object
    question: queries.ProgrammeQuestionProjection
    options: tuple[ProgrammeDomainOption, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeDomainSelection:
    """Retain one original target or deliberate clear through retries.

    Attributes
    ----------
    target_id : UUID | None
        Exact original target or explicit clear.
    kind : str
        Registered original catalog meaning.
    call_id : UUID
        Original immutable call, never a successor code match.
    option : ProgrammeDomainOption | None
        Exact available target, absent for clear or unavailable history.
    intent : ProgrammeAnswerReferenceIntent
        Original source versions and canonical retry identity.
    token : str
        Bounded purpose-signed integrity proof, never authority.
    """

    target_id: UUID | None
    kind: str
    call_id: UUID
    option: ProgrammeDomainOption | None
    intent: ProgrammeAnswerReferenceIntent
    token: str


@dataclass(frozen=True, slots=True)
class ProgrammeDomainReferenceView:
    """Expose only the exact answer's same-call target with full internal proof.

    Attributes
    ----------
    source : object
        Complete admitted answer/source facts for final comparison.
    question_label : str
        Authorized question label.
    kind : str
        Registered meaning, not a general model resolver.
    present : bool
        Whether the retained answer names a target.
    option : ProgrammeDomainOption | None
        Same-call source label/guidance, or no available target.
    """

    source: object
    question_label: str
    kind: str
    present: bool
    option: ProgrammeDomainOption | None


def _answer(
    answers: tuple[queries.ProgrammeAnswerProjection, ...] | None, question_id: UUID
) -> queries.ProgrammeAnswerProjection:
    rows = tuple(
        row for row in answers or () if row.question.question_id == question_id
    )
    if (
        len(rows) != 1
        or rows[0].question.field_type != "domain_reference"
        or (rows[0].question.reference_kind not in DOMAIN_REFERENCE_KINDS)
    ):
        raise Denied
    return rows[0]


def _audit(
    request: ProgrammeAnswerReferenceRequest,
    authorizer: ApplicationsProgrammeAuthorizer,
    fields: frozenset[str] = _FIELDS,
) -> None:
    correlation, channel = _audit_inputs(
        correlation_id=request.correlation_id, source_channel=request.source_channel
    )
    _append_sensitive_read(
        scope=_scope(request, authorizer, fields=fields),
        operation="applications.programme.query.domain_reference",
        target_id=request.proposal_id,
        correlation_id=correlation,
        source_channel=channel,
        occurred_at=timezone.now(),
    )


def _target_values(
    request: ProgrammeAnswerReferenceRequest, call_id: UUID, kind: str
) -> dict[str, Any]:
    return {
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
        "call_id": call_id,
        "kind": kind,
    }


@transaction.atomic
def get_programme_domain_choices(
    *,
    request: ProgrammeAnswerReferenceRequest,
    intent: ProgrammeAnswerReferenceIntent,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammeDomainChoices:
    """Read only the catalog needed by an authorized fresh shared question.

    Parameters
    ----------
    request : ProgrammeAnswerReferenceRequest
        Actual lead or accepted collaborator and exact question scope.
    intent : ProgrammeAnswerReferenceIntent
        Original aggregate, call, schema and retry fences.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Real admission or the established isolated-test adapter.

    Returns
    -------
    ProgrammeDomainChoices
        Complete bounded choices, with no widening of ordinary workflow fields.

    Raises
    ------
    Denied
        If the registered question, complete catalog or repeated source is invalid.
    """
    _intent(intent)
    source = _source(request, authorizer)
    answer = _answer(source[1].answers, request.question_id)
    _fresh(source[0], intent)
    options = _domain_options(
        **_target_values(
            request, source[0].summary.call_id, answer.question.reference_kind
        )
    )
    if (
        _source(request, authorizer) != source
        or _domain_options(
            **_target_values(
                request, source[0].summary.call_id, answer.question.reference_kind
            )
        )
        != options
    ):
        raise Denied
    _fresh(source[0], intent)
    _audit(request, authorizer)
    return ProgrammeDomainChoices(source, answer.question, options)


@transaction.atomic
def prepare_programme_domain_selection(
    *,
    request: ProgrammeAnswerReferenceRequest,
    intent: ProgrammeAnswerReferenceIntent,
    target_id: UUID | None,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammeDomainSelection:
    """Bind a labelled same-call choice or deliberate clear to original intent.

    Parameters
    ----------
    request : ProgrammeAnswerReferenceRequest
        Genuine current shared-answer editor and exact question.
    intent : ProgrammeAnswerReferenceIntent
        Original source and retry evidence, never regenerated on failure.
    target_id : UUID | None
        Exact displayed catalog choice or explicit clear.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Current real or isolated-test admission.

    Returns
    -------
    ProgrammeDomainSelection
        Original target/kind/call proof without labels or guidance in the token.

    Raises
    ------
    Denied
        If the target is absent from the complete admitted catalog.
    """
    choices = get_programme_domain_choices(
        request=request, intent=intent, authorizer=authorizer
    )
    source = _source(request, authorizer)
    if source != choices.source:
        raise Denied
    _fresh(source[0], intent)
    option = next((row for row in choices.options if row.target_id == target_id), None)
    if target_id is not None and option is None:
        raise Denied
    call_id, kind = source[0].summary.call_id, choices.question.reference_kind
    token = signing.dumps(
        _binding(request)
        | {
            key: str(value) if isinstance(value, UUID) else value
            for key, value in asdict(intent).items()
        }
        | {
            "target": str(target_id) if target_id else None,
            "kind": kind,
            "call": str(call_id),
        },
        salt=_SALT,
    )
    return ProgrammeDomainSelection(target_id, kind, call_id, option, intent, token)


def _decode(
    request: ProgrammeAnswerReferenceRequest,
    intent: ProgrammeAnswerReferenceIntent,
    token: str,
) -> tuple[UUID | None, str, UUID]:
    try:
        if (
            not isinstance(token, str)
            or not token
            or token.startswith(".")
            or len(token.encode("ascii")) > MAX_DOMAIN_SELECTION_BYTES
        ):
            raise Denied
        value = signing.loads(token, salt=_SALT)
        binding = _binding(request) | {
            key: str(item) if isinstance(item, UUID) else item
            for key, item in asdict(intent).items()
        }
        if (
            not isinstance(value, dict)
            or set(value) != {*binding, "target", "kind", "call"}
            or any(
                type(value[key]) is not type(item) or value[key] != item
                for key, item in binding.items()
            )
            or value["kind"] not in DOMAIN_REFERENCE_KINDS
        ):
            raise Denied
        call_id = _uuid(value["call"])
        target_id = _uuid(value["target"]) if value["target"] is not None else None
    except (signing.BadSignature, TypeError, ValueError) as error:
        raise Denied from error
    return target_id, value["kind"], call_id


def _uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise Denied
    try:
        target = UUID(value)
    except ValueError as error:
        raise Denied from error
    if not target.int or str(target) != value:
        raise Denied
    return target


@transaction.atomic
def read_programme_domain_selection(
    *,
    request: ProgrammeAnswerReferenceRequest,
    intent: ProgrammeAnswerReferenceIntent,
    token: str,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammeDomainSelection:
    """Reauthorize the original target without requiring fresh command applicability.

    Parameters
    ----------
    request : ProgrammeAnswerReferenceRequest
        Genuine current editor and exact answer scope.
    intent : ProgrammeAnswerReferenceIntent
        Original source and retry identity.
    token : str
        Bounded original purpose-specific proof.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Independently evaluated admission adapter.

    Returns
    -------
    ProgrammeDomainSelection
        Original selection for fresh dispatch or canonical receipt recovery.

    Raises
    ------
    Denied
        If binding, call ownership or repeated admission changes.
    """
    _intent(intent)
    source = _source(request, authorizer)
    target_id, kind, call_id = _decode(request, intent, token)
    if call_id != source[0].summary.call_id:
        raise Denied
    option = (
        _domain_target(**_target_values(request, call_id, kind), target_id=target_id)
        if target_id
        else None
    )
    if _source(request, authorizer) != source:
        raise Denied
    _audit(request, authorizer)
    return ProgrammeDomainSelection(target_id, kind, call_id, option, intent, token)


def _view(
    *,
    source: object,
    label: str,
    kind: str,
    value: object,
    organization_id: UUID,
    edition_id: UUID,
    call_id: UUID,
) -> ProgrammeDomainReferenceView:
    if kind not in DOMAIN_REFERENCE_KINDS:
        raise Denied
    option = None
    if value is not None:
        option = _domain_target(
            organization_id=organization_id,
            edition_id=edition_id,
            call_id=call_id,
            kind=kind,
            target_id=_uuid(value),
        )
    return ProgrammeDomainReferenceView(source, label, kind, value is not None, option)


@transaction.atomic
def get_self_programme_domain_reference(
    *,
    request: ProgrammeAnswerReferenceRequest,
    revision_id: UUID | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
) -> ProgrammeDomainReferenceView:
    """View only the same-call target in an independently admitted actual answer.

    Parameters
    ----------
    request : ProgrammeAnswerReferenceRequest
        Actual contributor and exact question, never a target identifier URL.
    revision_id : UUID | None, default=None
        Exact current seal for a genuine included contributor, or current answer.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Independently evaluated real or isolated-test admission.

    Returns
    -------
    ProgrammeDomainReferenceView
        Minimized target label/guidance and complete internal source evidence.

    Raises
    ------
    Denied
        If the exact registered answer or repeated source is unavailable.
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
    if original.summary is None:
        raise Denied
    answer = _answer(original.answers, request.question_id)
    result = _view(
        source=original,
        label=answer.question.label,
        kind=answer.question.reference_kind,
        value=answer.value,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        call_id=original.summary.call_id,
    )
    if source() != original:
        raise Denied
    _audit(request, authorizer, fields)
    return result
