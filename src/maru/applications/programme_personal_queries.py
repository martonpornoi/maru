"""Explicit self-owned workflow context without managed-call disclosure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from . import programme_queries as projections
from .models import (
    ProgrammeProposalRevision,
    ProgrammeProposalRevisionAnswer,
    ProgrammeProposalRevisionContributor,
)
from .programme_authorization import (
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    ApplicationsProgrammeAuthorizer,
    AuthorizedProgrammeProposalScope,
    authorize_programme_proposal_scope,
)
from .programme_inputs import require_programme_uuid
from .programme_queries import (
    _append_sensitive_read,
    _audit_inputs,
    _bounded_tuple,
    _format,
    _profile_value,
    _proposal_query,
    _proposal_summary,
    _question,
    _track,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

_WORKFLOW_FIELDS = frozenset({"proposal_summary", "workflow_context"})
_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ProgrammePersonalWorkflow:
    """Describe one current self task without supplying mutation authority.

    Attributes
    ----------
    summary : projections.ProgrammeProposalSummaryProjection
        Exact proposal, current relationship and sole aggregate version.
    call_version : int
        Current call aggregate version for source revalidation.
    definition_version : int
        Immutable source schema version.
    call_status : str
        Closed lifecycle status of the source definition.
    opens_at : datetime
        Inclusive opening instant.
    edit_until : datetime
        Inclusive editing deadline, independent of submission closing.
    closes_at : datetime
        Exclusive acknowledgement and submission closing instant.
    planning : bool
        Current edition private-planning availability, not a capability grant.
    tracks : tuple[projections.ProgrammeTrackProjection, ...]
        Complete bounded labelled catalog for a lead, empty for other roles.
    formats : tuple[projections.ProgrammeFormatProjection, ...]
        Complete bounded duration choices for a lead, empty for other roles.
    maximum_collaborators : int | None
        Lead-visible configured roster limit, absent for other roles.
    """

    summary: projections.ProgrammeProposalSummaryProjection
    call_version: int
    definition_version: int
    call_status: str
    opens_at: datetime
    edit_until: datetime
    closes_at: datetime
    planning: bool
    tracks: tuple[projections.ProgrammeTrackProjection, ...]
    formats: tuple[projections.ProgrammeFormatProjection, ...]
    maximum_collaborators: int | None


def _same_scope(
    summary: projections.ProgrammeProposalSummaryProjection,
    admitted: AuthorizedProgrammeProposalScope,
) -> None:
    for name in (
        "proposal_id",
        "submission_id",
        "call_id",
        "aggregate_version",
        "state",
        "relationship",
    ):
        if getattr(summary, name) != getattr(admitted, name):
            raise ApplicationsProgrammeAuthorizationDeniedError


@transaction.atomic
def get_self_programme_workflow(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammePersonalWorkflow:
    """Read minimal existing-proposal context independently of new-call entry.

    Parameters
    ----------
    actor_id : UUID
        Exact current verified person.
    organization_id : UUID
        Expected proposal organization.
    edition_id : UUID
        Exact event edition.
    proposal_id : UUID
        Current relationship-owned proposal.
    correlation_id : UUID
        Protected-read audit correlation.
    source_channel : str
        Registered calling surface identifier.
    now : datetime | None, default=None
        Optional aware instant for deterministic invitation expiry.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Complete-decision adapter; not caller-supplied permission flags.

    Returns
    -------
    ProgrammePersonalWorkflow
        Bounded exact-self task context without manager policies or questions.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If identity, relationship, lifecycle source or audit inputs are invalid.

    Notes
    -----
    The bounded collection helper propagates a projection-overflow error if
    either complete choice catalog exceeds its supported bound.
    """
    ids = {
        name: require_programme_uuid(value, field=name)
        for name, value in {
            "actor_id": actor_id,
            "organization_id": organization_id,
            "edition_id": edition_id,
            "proposal_id": proposal_id,
        }.items()
    }
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id, source_channel=source_channel
    )
    effective_now = now or timezone.now()
    if not timezone.is_aware(effective_now):
        raise ApplicationsProgrammeAuthorizationDeniedError

    def authorize() -> AuthorizedProgrammeProposalScope:
        return authorize_programme_proposal_scope(
            actor_id=ids["actor_id"],
            organization_id=ids["organization_id"],
            edition_id=ids["edition_id"],
            proposal_id=ids["proposal_id"],
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=_WORKFLOW_FIELDS,
            authorizer=authorizer,
            now=effective_now,
        )

    scope = authorize()
    query = _proposal_query(
        organization_id=ids["organization_id"], edition_id=ids["edition_id"]
    ).filter(id=ids["proposal_id"])
    proposal = query.first()
    if proposal is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    summary = _proposal_summary(proposal=proposal, relationship=scope.relationship)
    _same_scope(summary, scope)
    call = proposal.call
    definition = call.definition
    tracks: tuple[projections.ProgrammeTrackProjection, ...] = ()
    formats: tuple[projections.ProgrammeFormatProjection, ...] = ()
    if scope.relationship == "lead":
        tracks = _bounded_tuple(
            (_track(row) for row in call.tracks.order_by("position", "id")[:101]),
            maximum=100,
        )
        formats = _bounded_tuple(
            (_format(row) for row in call.formats.order_by("position", "id")[:101]),
            maximum=100,
        )
    result = ProgrammePersonalWorkflow(
        summary=summary,
        call_version=definition.aggregate_version,
        definition_version=definition.version,
        call_status=definition.status,
        opens_at=definition.opens_at,
        edit_until=definition.applicant_edit_until,
        closes_at=definition.closes_at,
        planning=scope.accepts_private_planning_writes,
        tracks=tracks,
        formats=formats,
        maximum_collaborators=call.max_collaborators
        if scope.relationship == "lead"
        else None,
    )
    current = query.first()
    if current is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    current_definition = current.call.definition
    source_fields = (
        "aggregate_version",
        "version",
        "status",
        "opens_at",
        "closes_at",
        "applicant_edit_until",
    )
    if any(
        getattr(definition, key) != getattr(current_definition, key)
        for key in source_fields
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    fresh = authorize()
    _same_scope(summary, fresh)
    if fresh.accepts_private_planning_writes != result.planning:
        raise ApplicationsProgrammeAuthorizationDeniedError
    _append_sensitive_read(
        scope=fresh,
        operation="applications.programme.query.self_workflow_context",
        target_id=proposal_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
        occurred_at=effective_now,
    )
    return result


@dataclass(frozen=True, slots=True)
class ProgrammePersonalFrozenRevision:
    """Expose reviewed shared content and only the actor's included profile.

    Attributes
    ----------
    summary : projections.ProgrammeProposalSummaryProjection
        Current relationship and proposal state/version for late revalidation.
    revision : projections.ProgrammeRevisionProjection
        Exact immutable seal identity, sequence and digest.
    selection : projections.ProgrammeSelectionProjection
        Selection revision actually frozen in this seal.
    answers : tuple[projections.ProgrammeAnswerProjection, ...]
        Complete frozen applicant-answer set, never latest mutable answers.
    own_contributor_id : UUID
        Actor's exact included revision-contributor identity.
    own_profile : projections.ProgrammeOwnProfileProjection
        Actor's included frozen profile only, not another contributor's values.
    """

    summary: projections.ProgrammeProposalSummaryProjection
    revision: projections.ProgrammeRevisionProjection
    selection: projections.ProgrammeSelectionProjection
    answers: tuple[projections.ProgrammeAnswerProjection, ...]
    own_contributor_id: UUID
    own_profile: projections.ProgrammeOwnProfileProjection


def _frozen_answers(
    *, revision: ProgrammeProposalRevision, definition_id: UUID, submission_id: UUID
) -> tuple[projections.ProgrammeAnswerProjection, ...]:
    scoped = ProgrammeProposalRevisionAnswer.objects.filter(
        organization_id=revision.organization_id,
        edition_id=revision.edition_id,
        revision=revision,
    )
    ids = _bounded_tuple(
        scoped.order_by("question_key", "id").values_list("id", flat=True)[:501],
        maximum=500,
    )
    safe = scoped.filter(
        id__in=ids,
        question__definition_id=definition_id,
        question__applicant_visible=True,
        question__applicant_writable=True,
        question__source_binding="",
        question_key=F("question__key"),
        question_type=F("question__field_type"),
        question__staff_visible=False,
        question__staff_writable=False,
        question__reviewer_visible=False,
        question__public_after_approval=False,
        question__api_projection=False,
    ).filter(
        Q(answer_revision__isnull=True)
        | Q(
            answer_revision__submission_id=submission_id,
            answer_revision__submission__organization_id=revision.organization_id,
            answer_revision__submission__edition_id=revision.edition_id,
            answer_revision__question_id=F("question_id"),
            answer_revision__resulting_version__lte=revision.source_version,
        )
    )
    rows = tuple(
        safe.select_related("question", "answer_revision").order_by(
            "question__section__position", "question__position", "id"
        )
    )
    if {row.id for row in rows} != set(ids):
        raise projections.ApplicationsProgrammeProjectionError
    return tuple(
        projections.ProgrammeAnswerProjection(
            question=_question(row.question),
            answer_revision_id=row.answer_revision_id,
            value=row.answer_revision.value
            if row.answer_revision is not None
            else None,
            actor_id=row.answer_revision.actor_id
            if row.answer_revision is not None
            else None,
            resulting_version=row.answer_revision.resulting_version
            if row.answer_revision is not None
            else None,
        )
        for row in rows
    )


@transaction.atomic
def get_self_programme_frozen_revision(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    revision_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammePersonalFrozenRevision:
    """Project one current exact seal and the actor's own frozen profile.

    Parameters
    ----------
    actor_id : UUID
        Current verified person who must be included in the selected seal.
    organization_id : UUID
        Exact proposal organization.
    edition_id : UUID
        Exact event edition.
    proposal_id : UUID
        Current relationship-owned proposal.
    revision_id : UUID
        Exact current sealed revision selected for review.
    correlation_id : UUID
        Protected-read audit correlation.
    source_channel : str
        Registered surface identifier.
    now : datetime | None, default=None
        Optional aware instant for exact current relationship checks.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammePersonalFrozenRevision
        Immutable shared content and subject-only included profile.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If relationship, inclusion, scope or the current selected seal is invalid.

    Notes
    -----
    Projection helpers propagate a projection error if complete bounded frozen
    evidence cannot be safely assembled; no partial result is returned.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(organization_id, field="organization_id")
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    proposal_id = require_programme_uuid(proposal_id, field="proposal_id")
    revision_id = require_programme_uuid(revision_id, field="revision_id")
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id, source_channel=source_channel
    )
    effective_now = now or timezone.now()
    if not timezone.is_aware(effective_now):
        raise ApplicationsProgrammeAuthorizationDeniedError

    def authorize() -> AuthorizedProgrammeProposalScope:
        return authorize_programme_proposal_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=proposal_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=frozenset({"proposal_summary", "frozen_revision"}),
            authorizer=authorizer,
            now=effective_now,
        )

    scope = authorize()
    if scope.relationship not in {"lead", "collaborator"}:
        raise ApplicationsProgrammeAuthorizationDeniedError
    proposal_query = _proposal_query(
        organization_id=organization_id, edition_id=edition_id
    ).filter(id=proposal_id, sealed_revision_id=revision_id)
    proposal = proposal_query.first()
    if proposal is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    summary = _proposal_summary(proposal=proposal, relationship=scope.relationship)
    _same_scope(summary, scope)
    revision = (
        ProgrammeProposalRevision.objects.filter(
            id=revision_id,
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=proposal_id,
            definition_version=proposal.call.definition.version,
            resulting_version__lte=proposal.submission.aggregate_version,
            selection_revision__proposal_id=proposal_id,
            selection_revision__organization_id=organization_id,
            selection_revision__edition_id=edition_id,
            selection_revision__track__call_id=proposal.call_id,
            selection_revision__format__call_id=proposal.call_id,
        )
        .select_related("selection_revision__track", "selection_revision__format")
        .first()
    )
    if revision is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    contributor = (
        ProgrammeProposalRevisionContributor.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            revision=revision,
            account_id=actor_id,
            role=scope.relationship,
            profile_revision__account_id=actor_id,
            profile_revision__proposal_id=proposal_id,
            profile_revision__organization_id=organization_id,
            profile_revision__edition_id=edition_id,
            profile_revision__resulting_version__lte=revision.source_version,
        )
        .select_related("profile_revision")
        .first()
    )
    if contributor is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    selection = revision.selection_revision
    profile = contributor.profile_revision
    configured = _bounded_tuple(
        proposal.call.contributor_fields.order_by("position", "id")[:5], maximum=4
    )
    visible = tuple(
        row
        for row in configured
        if (
            row.lead_requirement
            if scope.relationship == "lead"
            else row.collaborator_requirement
        )
        != "hidden"
    )
    result = ProgrammePersonalFrozenRevision(
        summary=summary,
        revision=projections.ProgrammeRevisionProjection(
            revision.id,
            revision.sequence,
            revision.predecessor_id,
            revision.definition_version,
            revision.selection_revision_id,
            revision.resulting_version,
            revision.digest,
            revision.sealed_at,
            current=True,
            submitted=proposal.submitted_revision_id == revision.id,
        ),
        selection=projections.ProgrammeSelectionProjection(
            selection.id,
            selection.track_id,
            selection.track.code,
            selection.track.label,
            selection.format_id,
            selection.format.code,
            selection.format.label,
            selection.requested_duration_minutes,
            selection.resulting_version,
        ),
        answers=_frozen_answers(
            revision=revision,
            definition_id=proposal.submission.definition_id,
            submission_id=proposal.submission_id,
        ),
        own_contributor_id=contributor.id,
        own_profile=projections.ProgrammeOwnProfileProjection(
            profile.id,
            tuple(
                (row.field_code, _profile_value(profile, field_code=row.field_code))
                for row in visible
            ),
            profile.proposed_for_publication,
            profile.consent_acknowledged,
            profile.consent_policy_code,
            profile.resulting_version,
        ),
    )
    fresh = authorize()
    _same_scope(summary, fresh)
    current = proposal_query.first()
    if (
        current is None
        or current.call.definition.aggregate_version
        != proposal.call.definition.aggregate_version
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    _append_sensitive_read(
        scope=fresh,
        operation="applications.programme.query.self_frozen_revision",
        target_id=revision_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
        occurred_at=effective_now,
    )
    return result


__all__ = [
    "ProgrammePersonalFrozenRevision",
    "ProgrammePersonalWorkflow",
    "get_self_programme_frozen_revision",
    "get_self_programme_workflow",
]
