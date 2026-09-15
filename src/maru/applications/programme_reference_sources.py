"""Shared exact-answer source admission and intent inputs without target I/O."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from django.utils import timezone

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

if TYPE_CHECKING:
    from uuid import UUID

    from .programme_authorization import (
        ApplicationsProgrammeAuthorizer,
        AuthorizedProgrammeProposalScope,
    )

_FIELDS = frozenset({"proposal_summary", "answers"})
_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ProgrammeAnswerReferenceRequest:
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
        Immutable question identifier, never a selected target identifier.
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
class ProgrammeAnswerReferenceIntent:
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


def _values(request: ProgrammeAnswerReferenceRequest) -> dict[str, Any]:
    values = asdict(request)
    for key in values.keys() - {"source_channel"}:
        require_programme_uuid(values[key], field=key)
    values.pop("question_id")
    return values


def _intent(intent: ProgrammeAnswerReferenceIntent) -> None:
    require_programme_uuid(intent.retry_key, field="retry_key")
    if any(
        type(value) is not int or not 1 <= value <= 2**63 - 1
        for key, value in asdict(intent).items()
        if key != "retry_key"
    ):
        raise Denied


def _binding(request: ProgrammeAnswerReferenceRequest) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in asdict(request).items()
        if key not in {"correlation_id", "source_channel"}
    }


def _scope(
    request: ProgrammeAnswerReferenceRequest,
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


def _source(
    request: ProgrammeAnswerReferenceRequest,
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
    context: personal.ProgrammePersonalWorkflow, intent: ProgrammeAnswerReferenceIntent
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
