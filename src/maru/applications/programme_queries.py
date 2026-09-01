"""Bounded, authorization-safe projections for Programme calls and proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db import transaction
from django.db.models import Count, F, Q, QuerySet, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from maru.applications.answer_values import condition_matches
from maru.applications.models import (
    ApplicationAnswerRevision,
    ApplicationDefinitionStatus,
    ApplicationQuestion,
    ApplicationTargetKind,
    ProgrammeCall,
    ProgrammeCallFormat,
    ProgrammeCallTrack,
    ProgrammeCollaboratorState,
    ProgrammeContributorFieldCode,
    ProgrammeContributorRequirement,
    ProgrammeContributorRole,
    ProgrammeProposal,
    ProgrammeProposalCollaborator,
    ProgrammeProposalContributorProfileRevision,
    ProgrammeProposalRevision,
    ProgrammeProposalRevisionContributor,
    ProgrammeProposalRevisionResponse,
    ProgrammeProposalSelectionRevision,
    ProgrammeProposalState,
)
from maru.applications.programme_authorization import (
    APPLICATIONS_MANAGE_PROGRAMME_CALLS,
    APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    ApplicationsProgrammeAuthorizer,
    AuthorizedProgrammeCallScope,
    AuthorizedProgrammeProposalScope,
    AuthorizedProgrammeSelfEntryScope,
    authorize_programme_call_scope,
    authorize_programme_proposal_scope,
    authorize_programme_self_entry_scope,
)
from maru.applications.programme_inputs import (
    normalized_programme_text,
    require_programme_positive_integer,
    require_programme_uuid,
)
from maru.audit.services import AuditRecord, append_audit
from maru.identity.queries import active_verified_person_account_display_labels
from maru.workforce.queries import resolve_current_department_set_reference

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

MAX_PROGRAMME_CALL_PROJECTION = 100
MAX_PROGRAMME_PROPOSAL_PROJECTION = 100
MAX_PROGRAMME_ANSWER_PROJECTION = 500
MAX_PROGRAMME_CONTRIBUTOR_PROJECTION = 17
MAX_PROGRAMME_REVISION_PROJECTION = 100
MAX_PROGRAMME_RESPONSE_PROJECTION = 1_600
_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_SOURCE_CHANNEL_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_-]*$")
_AVAILABLE_CALL_FIELDS: Final = frozenset({"available_calls"})
_LIST_PROPOSAL_FIELDS: Final = frozenset(
    {"proposal_summary", "selection", "own_invitation"}
)
_FULL_PROPOSAL_FIELDS: Final = frozenset(
    {
        "proposal_summary",
        "selection",
        "answers",
        "contributors",
        "contributor_profiles",
        "revision_history",
        "revision_responses",
        "own_invitation",
    }
)


class ApplicationsProgrammeProjectionError(RuntimeError):
    """Base class for non-disclosing Programme projection failures."""


class ApplicationsProgrammeProjectionOverflowError(
    ApplicationsProgrammeProjectionError,
):
    """Refuse partial projection when a documented bound is exceeded."""


@dataclass(frozen=True, slots=True)
class ProgrammeCallSummary:
    """Project the bounded lifecycle identity of one Programme call.

    Attributes
    ----------
    call_id : UUID
        Exact Applications-owned Programme call identifier.
    definition_id : UUID
        Immutable typed Applications definition identifier.
    code : str
        Stable code shared by the call lineage.
    version : int
        Immutable definition version within the lineage.
    aggregate_version : int
        Current optimistic call aggregate version.
    status : str
        Current closed definition lifecycle.
    name : str
        Applicant-facing call name.
    description : str
        Applicant-facing call guidance.
    opens_at : datetime
        Inclusive proposal-opening instant.
    closes_at : datetime
        Exclusive response and submission closing instant.
    applicant_edit_until : datetime
        Inclusive draft-editing deadline.
    owner_department_id : UUID
        Exact current Department responsible for the call.
    """

    call_id: UUID
    definition_id: UUID
    code: str
    version: int
    aggregate_version: int
    status: str
    name: str
    description: str
    opens_at: datetime
    closes_at: datetime
    applicant_edit_until: datetime
    owner_department_id: UUID


@dataclass(frozen=True, slots=True)
class ProgrammeTrackProjection:
    """Project one ordered call track.

    Attributes
    ----------
    track_id : UUID
        Exact call-owned track identifier.
    code : str
        Stable lower-case track code.
    label : str
        Applicant-facing track label.
    description : str
        Applicant-facing track guidance.
    position : int
        One-based contiguous presentation position.
    """

    track_id: UUID
    code: str
    label: str
    description: str
    position: int


@dataclass(frozen=True, slots=True)
class ProgrammeFormatProjection:
    """Project one ordered call format and its duration bounds.

    Attributes
    ----------
    format_id : UUID
        Exact call-owned format identifier.
    code : str
        Stable lower-case format code.
    label : str
        Applicant-facing format label.
    description : str
        Applicant-facing format guidance.
    position : int
        One-based contiguous presentation position.
    minimum_duration_minutes : int
        Smallest selectable duration in whole minutes.
    default_duration_minutes : int
        Preselected duration within the format bounds.
    maximum_duration_minutes : int
        Largest selectable duration in whole minutes.
    """

    format_id: UUID
    code: str
    label: str
    description: str
    position: int
    minimum_duration_minutes: int
    default_duration_minutes: int
    maximum_duration_minutes: int


@dataclass(frozen=True, slots=True)
class ProgrammeContributorFieldProjection:
    """Project one fixed contributor-field policy.

    Attributes
    ----------
    field_code : str
        Closed proposed-public profile field.
    lead_requirement : str
        Visibility or requirement rule for the proposal lead.
    collaborator_requirement : str
        Visibility or requirement rule for collaborators.
    position : int
        One-based contiguous presentation position.
    """

    field_code: str
    lead_requirement: str
    collaborator_requirement: str
    position: int


@dataclass(frozen=True, slots=True)
class ProgrammeQuestionOptionProjection:
    """Project one immutable choice option.

    Attributes
    ----------
    code : str
        Stable code stored in normalized answer values.
    label : str
        Applicant-facing option label.
    """

    code: str
    label: str


@dataclass(frozen=True, slots=True)
class ProgrammeQuestionProjection:
    """Project one closed question without a live ORM object.

    Attributes
    ----------
    question_id : UUID
        Exact immutable Applications question identifier.
    key : str
        Stable lower-case question key.
    field_type : str
        Closed answer-value type.
    label : str
        Applicant-facing question label.
    help_text : str
        Optional applicant guidance.
    position : int
        One-based contiguous position within the section.
    required : bool
        Whether an applicable answer is required before sealing.
    options : tuple[ProgrammeQuestionOptionProjection, ...]
        Closed choice options, empty for non-choice questions.
    minimum_length : int | None
        Optional inclusive text-length minimum.
    maximum_length : int | None
        Optional inclusive text-length maximum.
    minimum_value : Decimal | None
        Optional inclusive numeric minimum.
    maximum_value : Decimal | None
        Optional inclusive numeric maximum.
    maximum_choices : int | None
        Optional maximum selections for a multiple-choice question.
    reference_kind : str
        Registered reference kind for reference-valued questions.
    condition : tuple[tuple[str, object], ...]
        Canonical immutable earlier-question condition entries.
    purpose : str
        Documented answer collection purpose.
    classification : str
        Closed information classification.
    retention_policy_code : str
        Exact answer-specific retention policy, if configured.
    """

    question_id: UUID
    key: str
    field_type: str
    label: str
    help_text: str
    position: int
    required: bool
    options: tuple[ProgrammeQuestionOptionProjection, ...]
    minimum_length: int | None
    maximum_length: int | None
    minimum_value: Decimal | None
    maximum_value: Decimal | None
    maximum_choices: int | None
    reference_kind: str
    condition: tuple[tuple[str, object], ...]
    purpose: str
    classification: str
    retention_policy_code: str


@dataclass(frozen=True, slots=True)
class ProgrammeSectionProjection:
    """Project one ordered section and its bounded question graph.

    Attributes
    ----------
    section_id : UUID
        Exact immutable Applications section identifier.
    key : str
        Stable lower-case section key.
    title : str
        Applicant-facing section title.
    help_text : str
        Optional applicant guidance.
    position : int
        One-based contiguous position in the definition.
    questions : tuple[ProgrammeQuestionProjection, ...]
        Complete ordered section question graph.
    """

    section_id: UUID
    key: str
    title: str
    help_text: str
    position: int
    questions: tuple[ProgrammeQuestionProjection, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeCallConfigurationProjection:
    """Project a full manager-visible call without any proposal content.

    Attributes
    ----------
    summary : ProgrammeCallSummary
        Bounded call identity and lifecycle summary.
    purpose : str
        Documented proposal collection purpose.
    classification : str
        Closed default information classification.
    eligibility_kind : str
        Closed person-eligibility rule.
    maximum_submissions_per_person : int
        Exact per-person proposal limit.
    audience_policy_code : str
        Exact policy controlling call audience eligibility.
    retention_policy_code : str
        Default exact proposal-content retention policy.
    maximum_collaborators : int
        Maximum non-lead collaborators per proposal.
    content_policy_code : str
        Exact policy governing submitted proposal content.
    contributor_consent_policy_code : str
        Exact contributor publication-consent policy.
    collaboration_retention_policy_code : str
        Exact collaboration-evidence retention policy.
    tracks : tuple[ProgrammeTrackProjection, ...]
        Complete ordered call track catalog.
    formats : tuple[ProgrammeFormatProjection, ...]
        Complete ordered call format catalog.
    contributor_fields : tuple[ProgrammeContributorFieldProjection, ...]
        Complete ordered contributor field policy.
    sections : tuple[ProgrammeSectionProjection, ...]
        Complete immutable form graph.
    """

    summary: ProgrammeCallSummary
    purpose: str
    classification: str
    eligibility_kind: str
    maximum_submissions_per_person: int
    audience_policy_code: str
    retention_policy_code: str
    maximum_collaborators: int
    content_policy_code: str
    contributor_consent_policy_code: str
    collaboration_retention_policy_code: str
    tracks: tuple[ProgrammeTrackProjection, ...]
    formats: tuple[ProgrammeFormatProjection, ...]
    contributor_fields: tuple[ProgrammeContributorFieldProjection, ...]
    sections: tuple[ProgrammeSectionProjection, ...]


@dataclass(frozen=True, slots=True)
class AvailableProgrammeCallProjection:
    """Project only the information needed to start an available call.

    Attributes
    ----------
    summary : ProgrammeCallSummary
        Bounded call identity, lifecycle, and availability window.
    purpose : str
        Documented proposal collection purpose.
    classification : str
        Closed default information classification.
    contributor_consent_policy_code : str
        Exact contributor publication-consent policy.
    contributor_fields : tuple[ProgrammeContributorFieldProjection, ...]
        Contributor fields the proposal will collect.
    tracks : tuple[ProgrammeTrackProjection, ...]
        Selectable ordered track catalog.
    formats : tuple[ProgrammeFormatProjection, ...]
        Selectable ordered format catalog.
    """

    summary: ProgrammeCallSummary
    purpose: str
    classification: str
    contributor_consent_policy_code: str
    contributor_fields: tuple[ProgrammeContributorFieldProjection, ...]
    tracks: tuple[ProgrammeTrackProjection, ...]
    formats: tuple[ProgrammeFormatProjection, ...]


@dataclass(frozen=True, slots=True)
class ProgrammeSelectionProjection:
    """Project one latest proposal selection.

    Attributes
    ----------
    revision_id : UUID
        Exact immutable selection-revision identifier.
    track_id : UUID
        Exact selected call-owned track identifier.
    track_code : str
        Stable selected track code.
    track_label : str
        Applicant-facing selected track label.
    format_id : UUID
        Exact selected call-owned format identifier.
    format_code : str
        Stable selected format code.
    format_label : str
        Applicant-facing selected format label.
    requested_duration_minutes : int
        Requested whole-minute duration.
    resulting_version : int
        Proposal aggregate version produced by this selection.
    """

    revision_id: UUID
    track_id: UUID
    track_code: str
    track_label: str
    format_id: UUID
    format_code: str
    format_label: str
    requested_duration_minutes: int
    resulting_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeInvitationProjection:
    """Project only the current actor's purpose invitation.

    Attributes
    ----------
    collaborator_id : UUID
        Exact proposal collaborator relationship identifier.
    state : str
        Current closed collaborator relationship state.
    generation : int
        Current append-only invitation generation.
    expires_at : datetime
        Aware invitation-expiry instant.
    expired : bool
        Whether the invitation is expired at projection time.
    """

    collaborator_id: UUID
    state: str
    generation: int
    expires_at: datetime
    expired: bool


@dataclass(frozen=True, slots=True)
class ProgrammeProposalSummaryProjection:
    """Project relationship-safe proposal lifecycle identity.

    Attributes
    ----------
    proposal_id : UUID
        Exact Applications-owned Programme proposal identifier.
    submission_id : UUID
        Underlying typed Applications submission identifier.
    call_id : UUID
        Exact call that owns the proposal.
    call_name : str
        Applicant-facing name of the owning call.
    state : str
        Current closed proposal lifecycle state.
    aggregate_version : int
        Current optimistic proposal aggregate version.
    relationship : str
        Actor's proven lead, invitee, or collaborator relationship.
    sealed_revision_id : UUID | None
        Current immutable sealed revision, if any.
    submitted_revision_id : UUID | None
        Exact submitted revision, if any.
    """

    proposal_id: UUID
    submission_id: UUID
    call_id: UUID
    call_name: str
    state: str
    aggregate_version: int
    relationship: str
    sealed_revision_id: UUID | None
    submitted_revision_id: UUID | None


@dataclass(frozen=True, slots=True)
class ProgrammeProposalListItem:
    """Project one bounded self-visible proposal list row.

    Attributes
    ----------
    summary : ProgrammeProposalSummaryProjection
        Relationship-safe proposal lifecycle identity.
    selection : ProgrammeSelectionProjection | None
        Latest selected track, format, and duration, if visible.
    own_invitation : ProgrammeInvitationProjection | None
        Actor's current invitation state, if invited.
    """

    summary: ProgrammeProposalSummaryProjection
    selection: ProgrammeSelectionProjection | None
    own_invitation: ProgrammeInvitationProjection | None


@dataclass(frozen=True, slots=True)
class ProgrammeAnswerProjection:
    """Project one latest shared applicant-writable answer.

    Attributes
    ----------
    question : ProgrammeQuestionProjection
        Immutable question metadata governing the answer.
    answer_revision_id : UUID | None
        Latest immutable answer-revision identifier, if answered.
    value : object
        Normalized typed answer value, or ``None`` when unanswered.
    actor_id : UUID | None
        Contributor who authored the latest answer, if any.
    resulting_version : int | None
        Proposal aggregate version produced by the answer, if any.
    """

    question: ProgrammeQuestionProjection
    answer_revision_id: UUID | None
    value: object
    actor_id: UUID | None
    resulting_version: int | None


@dataclass(frozen=True, slots=True)
class ProgrammeContributorProjection:
    """Project one relationship-safe contributor roster row.

    Attributes
    ----------
    account_id : UUID
        Exact contributor account identifier.
    display_label : str
        Bounded non-email identity display label.
    role : str
        Closed lead or collaborator role.
    collaborator_id : UUID | None
        Proposal collaborator relationship identifier for non-leads.
    state : str
        Current closed relationship state.
    generation : int | None
        Current invitation generation for a collaborator relationship.
    invitation_expired : bool
        Whether an invited relationship is expired at projection time.
    """

    account_id: UUID
    display_label: str
    role: str
    collaborator_id: UUID | None
    state: str
    generation: int | None
    invitation_expired: bool


@dataclass(frozen=True, slots=True)
class ProgrammeOwnProfileProjection:
    """Project only the actor's own configured proposed-public fields.

    Attributes
    ----------
    profile_revision_id : UUID
        Exact immutable subject-owned profile revision.
    values : tuple[tuple[str, str], ...]
        Configured proposed-public field codes and normalized values.
    proposed_for_publication : bool
        Subject's explicit publication intent for the values.
    consent_acknowledged : bool
        Whether the subject acknowledged the exact policy.
    consent_policy_code : str
        Exact versioned contributor policy acknowledged.
    resulting_version : int
        Proposal aggregate version produced by the profile revision.
    """

    profile_revision_id: UUID
    values: tuple[tuple[str, str], ...]
    proposed_for_publication: bool
    consent_acknowledged: bool
    consent_policy_code: str
    resulting_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeRevisionProjection:
    """Project immutable revision identity without proposal content.

    Attributes
    ----------
    revision_id : UUID
        Exact immutable sealed proposal revision identifier.
    sequence : int
        Contiguous one-based revision sequence.
    predecessor_id : UUID | None
        Exact prior sealed revision, if this is not the first.
    definition_version : int
        Immutable call-definition version frozen into the revision.
    selection_revision_id : UUID
        Exact selection revision frozen into the proposal revision.
    resulting_version : int
        Proposal aggregate version produced by sealing.
    digest : str
        Canonical lower-case SHA-256 content digest.
    sealed_at : datetime
        Aware instant when the immutable revision was sealed.
    current : bool
        Whether this is the proposal's current sealed revision.
    submitted : bool
        Whether this exact revision was submitted.
    """

    revision_id: UUID
    sequence: int
    predecessor_id: UUID | None
    definition_version: int
    selection_revision_id: UUID
    resulting_version: int
    digest: str
    sealed_at: datetime
    current: bool
    submitted: bool


@dataclass(frozen=True, slots=True)
class ProgrammeRevisionResponseProjection:
    """Project bounded acknowledgement state without response rationale.

    Attributes
    ----------
    revision_id : UUID
        Exact sealed proposal revision reviewed.
    contributor_id : UUID
        Exact included contributor relationship.
    account_id : UUID
        Exact contributor account identifier.
    response : str | None
        Closed acknowledgement or decline decision, if supplied.
    responded_at : datetime | None
        Aware response instant, if supplied.
    """

    revision_id: UUID
    contributor_id: UUID
    account_id: UUID
    response: str | None
    responded_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProgrammeProposalDetailProjection:
    """Project exactly the fields admitted by one complete self decision.

    Attributes
    ----------
    requested_fields : frozenset[str]
        Exact code-owned field ceiling applied to the projection.
    summary : ProgrammeProposalSummaryProjection | None
        Relationship-safe proposal lifecycle identity when requested.
    selection : ProgrammeSelectionProjection | None
        Latest proposal selection when requested and available.
    answers : tuple[ProgrammeAnswerProjection, ...] | None
        Complete bounded latest answer set when requested.
    contributors : tuple[ProgrammeContributorProjection, ...] | None
        Complete bounded relationship-safe roster when requested.
    own_profile_requirements : tuple[ProgrammeContributorFieldProjection, ...] | None
        Actor-role profile field policy when requested.
    contributor_consent_policy_code : str | None
        Exact contributor policy for the actor's profile, when requested.
    own_profile : ProgrammeOwnProfileProjection | None
        Actor's latest subject-owned profile revision when requested.
    revisions : tuple[ProgrammeRevisionProjection, ...] | None
        Bounded immutable revision identities when requested.
    responses : tuple[ProgrammeRevisionResponseProjection, ...] | None
        Bounded collaborator response states when requested.
    own_invitation : ProgrammeInvitationProjection | None
        Actor's current invitation state when applicable and requested.
    """

    requested_fields: frozenset[str]
    summary: ProgrammeProposalSummaryProjection | None
    selection: ProgrammeSelectionProjection | None
    answers: tuple[ProgrammeAnswerProjection, ...] | None
    contributors: tuple[ProgrammeContributorProjection, ...] | None
    own_profile_requirements: tuple[ProgrammeContributorFieldProjection, ...] | None
    contributor_consent_policy_code: str | None
    own_profile: ProgrammeOwnProfileProjection | None
    revisions: tuple[ProgrammeRevisionProjection, ...] | None
    responses: tuple[ProgrammeRevisionResponseProjection, ...] | None
    own_invitation: ProgrammeInvitationProjection | None


def _bounded_tuple[ItemT](
    values: Iterable[ItemT],
    *,
    maximum: int,
) -> tuple[ItemT, ...]:
    rows: list[ItemT] = []
    for value in values:
        if len(rows) >= maximum:
            raise ApplicationsProgrammeProjectionOverflowError
        rows.append(value)
    return tuple(rows)


def _summary(call: ProgrammeCall) -> ProgrammeCallSummary:
    definition = call.definition
    return ProgrammeCallSummary(
        call_id=call.id,
        definition_id=definition.id,
        code=definition.code,
        version=definition.version,
        aggregate_version=definition.aggregate_version,
        status=definition.status,
        name=definition.name,
        description=definition.description,
        opens_at=definition.opens_at,
        closes_at=definition.closes_at,
        applicant_edit_until=definition.applicant_edit_until,
        owner_department_id=call.owner_department_id,
    )


def _track(track: ProgrammeCallTrack) -> ProgrammeTrackProjection:
    return ProgrammeTrackProjection(
        track_id=track.id,
        code=track.code,
        label=track.label,
        description=track.description,
        position=track.position,
    )


def _format(programme_format: ProgrammeCallFormat) -> ProgrammeFormatProjection:
    return ProgrammeFormatProjection(
        format_id=programme_format.id,
        code=programme_format.code,
        label=programme_format.label,
        description=programme_format.description,
        position=programme_format.position,
        minimum_duration_minutes=programme_format.min_duration_minutes,
        default_duration_minutes=programme_format.default_duration_minutes,
        maximum_duration_minutes=programme_format.max_duration_minutes,
    )


def _question(question: ApplicationQuestion) -> ProgrammeQuestionProjection:
    options = tuple(
        ProgrammeQuestionOptionProjection(
            code=str(option["code"]),
            label=str(option["label"]),
        )
        for option in question.options
    )
    condition = tuple(sorted(question.condition.items()))
    return ProgrammeQuestionProjection(
        question_id=question.id,
        key=question.key,
        field_type=question.field_type,
        label=question.label,
        help_text=question.help_text,
        position=question.position,
        required=question.required,
        options=options,
        minimum_length=question.minimum_length,
        maximum_length=question.maximum_length,
        minimum_value=question.minimum_value,
        maximum_value=question.maximum_value,
        maximum_choices=question.maximum_choices,
        reference_kind=question.reference_kind,
        condition=condition,
        purpose=question.purpose,
        classification=question.classification,
        retention_policy_code=question.retention_policy_code,
    )


def _configuration(call: ProgrammeCall) -> ProgrammeCallConfigurationProjection:
    questions_by_section: dict[UUID, list[ProgrammeQuestionProjection]] = {}
    for question in call.definition.questions.order_by(
        "section__position",
        "position",
        "id",
    ):
        questions_by_section.setdefault(question.section_id, []).append(
            _question(question)
        )
    sections = [
        ProgrammeSectionProjection(
            section_id=section.id,
            key=section.key,
            title=section.title,
            help_text=section.help_text,
            position=section.position,
            questions=tuple(questions_by_section.get(section.id, ())),
        )
        for section in call.definition.sections.order_by("position", "id")
    ]
    definition = call.definition
    return ProgrammeCallConfigurationProjection(
        summary=_summary(call),
        purpose=definition.purpose,
        classification=definition.classification,
        eligibility_kind=definition.eligibility_kind,
        maximum_submissions_per_person=definition.max_submissions_per_person,
        audience_policy_code=definition.audience_policy_code,
        retention_policy_code=definition.retention_policy_code,
        maximum_collaborators=call.max_collaborators,
        content_policy_code=call.content_policy_code,
        contributor_consent_policy_code=call.contributor_consent_policy_code,
        collaboration_retention_policy_code=(call.collaboration_retention_policy_code),
        tracks=tuple(_track(row) for row in call.tracks.order_by("position", "id")),
        formats=tuple(_format(row) for row in call.formats.order_by("position", "id")),
        contributor_fields=tuple(
            ProgrammeContributorFieldProjection(
                field_code=row.field_code,
                lead_requirement=row.lead_requirement,
                collaborator_requirement=row.collaborator_requirement,
                position=row.position,
            )
            for row in call.contributor_fields.order_by("position", "id")
        ),
        sections=tuple(sections),
    )


def _require_limit(limit: int, *, maximum: int) -> int:
    return require_programme_positive_integer(
        limit,
        field="limit",
        maximum=maximum,
    )


def _call_query(
    *,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
) -> QuerySet[ProgrammeCall]:
    return ProgrammeCall.objects.select_related("definition").filter(
        organization_id=organization_id,
        edition_id=edition_id,
        owner_department_id=department_id,
        definition__organization_id=organization_id,
        definition__edition_id=edition_id,
        definition__target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
    )


def _append_managed_call_sensitive_read(
    *,
    scope: AuthorizedProgrammeCallScope,
    operation: str,
    target_type: str,
    target_id: UUID,
    target_count: int,
    correlation_id: UUID,
    source_channel: str,
    occurred_at: datetime,
) -> None:
    """Append mandatory audit evidence before releasing managed call data.

    The shared management capability requires ordinary audit for both commands
    and queries. This restricted query contract deliberately strengthens that
    complete decision with ``audit_sensitive_read`` only after enforcing its
    existing audit obligation; it does not manufacture authority or waive a
    policy requirement.

    Parameters
    ----------
    scope : AuthorizedProgrammeCallScope
        Reauthorized exact-Department read scope.
    operation : str
        Stable managed-read operation code.
    target_type : str
        Minimized collection or call target discriminator.
    target_id : UUID
        Exact Department collection or Programme call identifier.
    target_count : int
        Bounded number of projections prepared for release.
    correlation_id : UUID
        Request correlation identifier.
    source_channel : str
        Registered request channel.
    occurred_at : datetime
        Authoritative read-attempt instant.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the policy decision omitted its mandatory audit obligation.
    """
    if "audit" not in scope.decision.obligations:
        raise ApplicationsProgrammeAuthorizationDeniedError
    obligations = frozenset(scope.decision.obligations) | {"audit_sensitive_read"}
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(obligations)),
            safe_metadata={"target_count": target_count},
            retention_class="applications-programme-restricted",
        ),
        occurred_at=occurred_at,
    )


def _append_managed_call_read_denial(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    operation: str,
    correlation_id: UUID,
    source_channel: str,
    occurred_at: datetime,
) -> None:
    """Append value-minimized denial evidence without identifying a call.

    Parameters
    ----------
    actor_id : UUID
        Submitted canonical actor identifier.
    organization_id : UUID
        Submitted canonical organization scope.
    edition_id : UUID
        Submitted canonical edition scope.
    operation : str
        Stable managed-read operation code.
    correlation_id : UUID
        Request correlation identifier.
    source_channel : str
        Registered request channel.
    occurred_at : datetime
        Authoritative read-attempt instant.
    """
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=APPLICATIONS_MANAGE_PROGRAMME_CALLS,
            operation=operation,
            target_type="applications.programme_call.scope",
            target_id=None,
            outcome="deny",
            reason_code=(ApplicationsProgrammeAuthorizationDeniedError.reason_code),
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=("audit",),
            retention_class="applications-programme-restricted",
        ),
        occurred_at=occurred_at,
    )


def _require_managed_call(call: ProgrammeCall | None) -> ProgrammeCall:
    """Return one scoped call or raise the common non-disclosing denial.

    Parameters
    ----------
    call : ProgrammeCall | None
        Exact-tenant call candidate.

    Returns
    -------
    ProgrammeCall
        The scoped call prepared for projection.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If no call exists in the authorized exact scope.
    """
    if call is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    return call


def list_managed_programme_calls(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    limit: int = MAX_PROGRAMME_CALL_PROJECTION,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> tuple[ProgrammeCallSummary, ...]:
    """List exact-Department calls without joining or counting proposals.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the edition and Department.
    edition_id : UUID
        Exact event edition identifier.
    department_id : UUID
        Exact current Department identifier.
    correlation_id : UUID
        Request correlation identifier for audited disclosure.
    source_channel : str
        Registered request channel for audit evidence.
    limit : int, default=MAX_PROGRAMME_CALL_PROJECTION
        Maximum number of complete call summaries.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    tuple[ProgrammeCallSummary, ...]
        Bounded exact-Department call summaries.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the actor or exact Department scope is not authorized.
    ApplicationsProgrammeProjectionOverflowError
        If the requested scope exceeds the bounded projection.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    department_id = require_programme_uuid(
        department_id,
        field="department_id",
    )
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    limit = _require_limit(limit, maximum=MAX_PROGRAMME_CALL_PROJECTION)
    occurred_at = timezone.now()
    operation = "applications.programme.query.managed_call_list"
    try:
        authorize_programme_call_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            authorizer=authorizer,
        )
        with transaction.atomic():
            calls = tuple(
                _call_query(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    department_id=department_id,
                ).order_by("definition__code", "-definition__version", "id")[
                    : limit + 1
                ]
            )
            if len(calls) > limit:
                raise ApplicationsProgrammeProjectionOverflowError
            projections = tuple(_summary(call) for call in calls)
            scope = authorize_programme_call_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                department_id=department_id,
                authorizer=authorizer,
            )
            _append_managed_call_sensitive_read(
                scope=scope,
                operation=operation,
                target_type="applications.programme_call.collection",
                target_id=department_id,
                target_count=len(projections),
                correlation_id=correlation_id,
                source_channel=source_channel,
                occurred_at=occurred_at,
            )
            return projections
    except ApplicationsProgrammeAuthorizationDeniedError:
        _append_managed_call_read_denial(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            operation=operation,
            correlation_id=correlation_id,
            source_channel=source_channel,
            occurred_at=occurred_at,
        )
        raise


def get_managed_programme_call_configuration(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    call_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeCallConfigurationProjection:
    """Return one complete manager call graph without proposal content.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the call.
    edition_id : UUID
        Exact event edition identifier.
    department_id : UUID
        Exact current owner Department identifier.
    call_id : UUID
        Exact Programme call identifier.
    correlation_id : UUID
        Request correlation identifier for audited disclosure.
    source_channel : str
        Registered request channel for audit evidence.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeCallConfigurationProjection
        Complete typed call configuration without proposal content.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the call is absent from the authorized exact scope.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    department_id = require_programme_uuid(
        department_id,
        field="department_id",
    )
    call_id = require_programme_uuid(call_id, field="call_id")
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    occurred_at = timezone.now()
    operation = "applications.programme.query.managed_call_configuration"
    try:
        authorize_programme_call_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            authorizer=authorizer,
        )
        with transaction.atomic():
            call = _require_managed_call(
                _call_query(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    department_id=department_id,
                )
                .filter(id=call_id)
                .first()
            )
            projection = _configuration(call)
            scope = authorize_programme_call_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                department_id=department_id,
                authorizer=authorizer,
            )
            _append_managed_call_sensitive_read(
                scope=scope,
                operation=operation,
                target_type="applications.programme_call",
                target_id=call_id,
                target_count=1,
                correlation_id=correlation_id,
                source_channel=source_channel,
                occurred_at=occurred_at,
            )
            return projection
    except ApplicationsProgrammeAuthorizationDeniedError:
        _append_managed_call_read_denial(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            operation=operation,
            correlation_id=correlation_id,
            source_channel=source_channel,
            occurred_at=occurred_at,
        )
        raise


def _audit_inputs(
    *,
    correlation_id: UUID,
    source_channel: str,
) -> tuple[UUID, str]:
    correlation_id = require_programme_uuid(
        correlation_id,
        field="correlation_id",
    )
    source_channel = normalized_programme_text(
        source_channel,
        field="source_channel",
        maximum=32,
        required=True,
    )
    if _SOURCE_CHANNEL_PATTERN.fullmatch(source_channel) is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    return correlation_id, source_channel


def _append_sensitive_read(
    *,
    scope: AuthorizedProgrammeSelfEntryScope | AuthorizedProgrammeProposalScope,
    operation: str,
    target_id: UUID | None,
    correlation_id: UUID,
    source_channel: str,
    occurred_at: datetime,
) -> None:
    if "audit_sensitive_read" not in scope.decision.obligations:
        raise ApplicationsProgrammeAuthorizationDeniedError
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            operation=operation,
            target_type=(
                "applications.programme_proposal"
                if target_id is not None
                else "applications.programme_call.collection"
            ),
            target_id=target_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            retention_class="applications-programme-restricted",
        ),
        occurred_at=occurred_at,
    )


@transaction.atomic
def available_programme_calls(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    limit: int = MAX_PROGRAMME_CALL_PROJECTION,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> tuple[AvailableProgrammeCallProjection, ...]:
    """Discover active calls available to one exact verified person.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the edition.
    edition_id : UUID
        Exact event edition identifier.
    correlation_id : UUID
        Request correlation identifier for audited discovery.
    source_channel : str
        Registered request channel for audit evidence.
    limit : int, default=MAX_PROGRAMME_CALL_PROJECTION
        Maximum number of complete call projections.
    now : datetime | None, default=None
        Optional aware instant for deterministic window evaluation.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    tuple[AvailableProgrammeCallProjection, ...]
        Bounded calls available for a new self-owned proposal.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the actor, edition, Department set, time, or policy is invalid.
    ApplicationsProgrammeProjectionOverflowError
        If the available-call scope exceeds the bounded projection.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    limit = _require_limit(limit, maximum=MAX_PROGRAMME_CALL_PROJECTION)
    effective_now = now or timezone.now()
    if not timezone.is_aware(effective_now):
        raise ApplicationsProgrammeAuthorizationDeniedError
    scope = authorize_programme_self_entry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=_AVAILABLE_CALL_FIELDS,
        authorizer=authorizer,
    )
    departments = resolve_current_department_set_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if departments is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    candidates = tuple(
        ProgrammeCall.objects.select_related("definition")
        .prefetch_related("tracks", "formats", "contributor_fields")
        .filter(
            organization_id=organization_id,
            edition_id=edition_id,
            owner_department_id__in=departments.department_ids,
            definition__target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
            definition__status=ApplicationDefinitionStatus.ACTIVE,
            definition__opens_at__lte=effective_now,
            definition__applicant_edit_until__gte=effective_now,
        )
        .annotate(
            actor_submission_count=Count(
                "definition__submissions",
                filter=Q(definition__submissions__account_id=actor_id),
            )
        )
        .filter(actor_submission_count__lt=F("definition__max_submissions_per_person"))
        .order_by(
            "definition__applicant_edit_until",
            "definition__name",
            "id",
        )[: limit + 1]
    )
    if len(candidates) > limit:
        raise ApplicationsProgrammeProjectionOverflowError
    projections: list[AvailableProgrammeCallProjection] = []
    for call in candidates:
        contributor_fields = tuple(
            ProgrammeContributorFieldProjection(
                field_code=row.field_code,
                lead_requirement=row.lead_requirement,
                collaborator_requirement=row.collaborator_requirement,
                position=row.position,
            )
            for row in sorted(
                call.contributor_fields.all(),
                key=lambda item: (item.position, item.id),
            )
            if row.lead_requirement != ProgrammeContributorRequirement.HIDDEN
        )
        projections.append(
            AvailableProgrammeCallProjection(
                summary=_summary(call),
                purpose=call.definition.purpose,
                classification=call.definition.classification,
                contributor_consent_policy_code=(call.contributor_consent_policy_code),
                contributor_fields=contributor_fields,
                tracks=tuple(
                    _track(row)
                    for row in sorted(
                        call.tracks.all(),
                        key=lambda item: (item.position, item.id),
                    )
                ),
                formats=tuple(
                    _format(row)
                    for row in sorted(
                        call.formats.all(),
                        key=lambda item: (item.position, item.id),
                    )
                ),
            )
        )
    scope = authorize_programme_self_entry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=_AVAILABLE_CALL_FIELDS,
        authorizer=authorizer,
    )
    departments = resolve_current_department_set_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if departments is None or any(
        call.owner_department_id not in departments.department_ids
        for call in candidates
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    _append_sensitive_read(
        scope=scope,
        operation="applications.programme.query.available_calls",
        target_id=None,
        correlation_id=correlation_id,
        source_channel=source_channel,
        occurred_at=effective_now,
    )
    return tuple(projections)


def _proposal_query(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> QuerySet[ProgrammeProposal]:
    return ProgrammeProposal.objects.select_related(
        "submission",
        "call",
        "call__definition",
    ).filter(
        organization_id=organization_id,
        edition_id=edition_id,
        submission__organization_id=organization_id,
        submission__edition_id=edition_id,
        call__organization_id=organization_id,
        call__edition_id=edition_id,
        call__definition_id=F("submission__definition_id"),
        call__definition__target_adapter_kind=ApplicationTargetKind.PROGRAMME_ITEM,
    )


def _proposal_summary(
    *,
    proposal: ProgrammeProposal,
    relationship: str,
) -> ProgrammeProposalSummaryProjection:
    return ProgrammeProposalSummaryProjection(
        proposal_id=proposal.id,
        submission_id=proposal.submission_id,
        call_id=proposal.call_id,
        call_name=proposal.call.definition.name,
        state=proposal.state,
        aggregate_version=proposal.submission.aggregate_version,
        relationship=relationship,
        sealed_revision_id=proposal.sealed_revision_id,
        submitted_revision_id=proposal.submitted_revision_id,
    )


def _latest_selection_projection(
    *,
    proposal: ProgrammeProposal,
) -> ProgrammeSelectionProjection | None:
    row = (
        ProgrammeProposalSelectionRevision.objects.select_related(
            "track",
            "format",
        )
        .filter(
            organization_id=proposal.organization_id,
            edition_id=proposal.edition_id,
            proposal=proposal,
            resulting_version__lte=proposal.submission.aggregate_version,
        )
        .order_by("-resulting_version", "-sequence", "-id")
        .first()
    )
    if row is None:
        return None
    return ProgrammeSelectionProjection(
        revision_id=row.id,
        track_id=row.track_id,
        track_code=row.track.code,
        track_label=row.track.label,
        format_id=row.format_id,
        format_code=row.format.code,
        format_label=row.format.label,
        requested_duration_minutes=row.requested_duration_minutes,
        resulting_version=row.resulting_version,
    )


def _own_invitation_projection(
    *,
    proposal: ProgrammeProposal,
    actor_id: UUID,
    effective_now: datetime,
) -> ProgrammeInvitationProjection | None:
    row = (
        ProgrammeProposalCollaborator.objects.filter(
            organization_id=proposal.organization_id,
            edition_id=proposal.edition_id,
            proposal=proposal,
            account_id=actor_id,
        )
        .order_by("id")
        .first()
    )
    if row is None:
        return None
    return ProgrammeInvitationProjection(
        collaborator_id=row.id,
        state=row.state,
        generation=row.generation,
        expires_at=row.invite_expires_at,
        expired=(
            row.state == ProgrammeCollaboratorState.INVITED
            and row.invite_expires_at <= effective_now
        ),
    )


def _proposal_list_item(
    *,
    proposal: ProgrammeProposal,
    scope: AuthorizedProgrammeProposalScope,
    effective_now: datetime,
) -> ProgrammeProposalListItem:
    return ProgrammeProposalListItem(
        summary=_proposal_summary(
            proposal=proposal,
            relationship=scope.relationship,
        ),
        selection=_latest_selection_projection(proposal=proposal),
        own_invitation=_own_invitation_projection(
            proposal=proposal,
            actor_id=scope.actor_id,
            effective_now=effective_now,
        ),
    )


@transaction.atomic
def list_self_programme_proposals(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    limit: int = MAX_PROGRAMME_PROPOSAL_PROJECTION,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> tuple[ProgrammeProposalListItem, ...]:
    """List only current lead, accepted-collaborator, or live-invite rows.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the edition.
    edition_id : UUID
        Exact event edition identifier.
    correlation_id : UUID
        Request correlation identifier for audited discovery.
    source_channel : str
        Registered request channel for audit evidence.
    limit : int, default=MAX_PROGRAMME_PROPOSAL_PROJECTION
        Maximum number of proposal list items.
    now : datetime | None, default=None
        Optional aware instant for deterministic invitation expiry.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    tuple[ProgrammeProposalListItem, ...]
        Bounded proposals currently related to the actor.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the actor, edition, time, profile, or policy is invalid.
    ApplicationsProgrammeProjectionOverflowError
        If the related-proposal scope exceeds the bounded projection.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    limit = _require_limit(limit, maximum=MAX_PROGRAMME_PROPOSAL_PROJECTION)
    effective_now = now or timezone.now()
    if not timezone.is_aware(effective_now):
        raise ApplicationsProgrammeAuthorizationDeniedError
    authorize_programme_self_entry_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=_LIST_PROPOSAL_FIELDS,
        authorizer=authorizer,
    )
    candidate_ids = tuple(
        ProgrammeProposal.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            submission__organization_id=organization_id,
            submission__edition_id=edition_id,
            call__organization_id=organization_id,
            call__edition_id=edition_id,
            call__definition_id=F("submission__definition_id"),
            call__definition__target_adapter_kind=(
                ApplicationTargetKind.PROGRAMME_ITEM
            ),
        )
        .filter(
            Q(submission__account_id=actor_id)
            | Q(
                collaborators__account_id=actor_id,
                collaborators__state=ProgrammeCollaboratorState.ACCEPTED,
            )
            | Q(
                state=ProgrammeProposalState.DRAFT,
                collaborators__account_id=actor_id,
                collaborators__state=ProgrammeCollaboratorState.INVITED,
                collaborators__invite_expires_at__gt=effective_now,
            )
        )
        .order_by("-updated_at", "id")
        .values_list("id", flat=True)
        .distinct()[: limit + 1]
    )
    if len(candidate_ids) > limit:
        raise ApplicationsProgrammeProjectionOverflowError
    projected: list[
        tuple[ProgrammeProposalListItem, AuthorizedProgrammeProposalScope]
    ] = []
    for proposal_id in candidate_ids:
        try:
            scope = authorize_programme_proposal_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                proposal_id=proposal_id,
                capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
                requested_fields=_LIST_PROPOSAL_FIELDS,
                authorizer=authorizer,
                now=effective_now,
            )
        except ApplicationsProgrammeAuthorizationDeniedError:
            continue
        proposal = (
            _proposal_query(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .filter(id=proposal_id)
            .first()
        )
        if proposal is None:
            raise ApplicationsProgrammeAuthorizationDeniedError
        projected.append(
            (
                _proposal_list_item(
                    proposal=proposal,
                    scope=scope,
                    effective_now=effective_now,
                ),
                scope,
            )
        )
    final_scopes = tuple(
        authorize_programme_proposal_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            proposal_id=item.summary.proposal_id,
            capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
            requested_fields=_LIST_PROPOSAL_FIELDS,
            authorizer=authorizer,
            now=effective_now,
        )
        for item, _scope in projected
    )
    for (item, _scope), final_scope in zip(projected, final_scopes, strict=True):
        _append_sensitive_read(
            scope=final_scope,
            operation="applications.programme.query.self_proposal_list",
            target_id=item.summary.proposal_id,
            correlation_id=correlation_id,
            source_channel=source_channel,
            occurred_at=effective_now,
        )
    return tuple(item for item, _scope in projected)


def _latest_answer_rows(
    *,
    proposal: ProgrammeProposal,
) -> tuple[ApplicationAnswerRevision, ...]:
    rows = tuple(
        ApplicationAnswerRevision.objects.filter(
            submission=proposal.submission,
            resulting_version__lte=proposal.submission.aggregate_version,
        )
        .annotate(
            latest_rank=Window(
                expression=RowNumber(),
                partition_by=(F("question_id"),),
                order_by=(
                    F("resulting_version").desc(),
                    F("sequence").desc(),
                    F("id").desc(),
                ),
            )
        )
        .filter(latest_rank=1)
        .order_by("question_key", "id")[: MAX_PROGRAMME_ANSWER_PROJECTION + 1]
    )
    if len(rows) > MAX_PROGRAMME_ANSWER_PROJECTION:
        raise ApplicationsProgrammeProjectionOverflowError
    return rows


def _answer_projections(
    *,
    proposal: ProgrammeProposal,
) -> tuple[ProgrammeAnswerProjection, ...]:
    latest_rows = _latest_answer_rows(proposal=proposal)
    latest = {row.question_key: row for row in latest_rows}
    questions = tuple(
        proposal.call.definition.questions.filter(
            applicant_visible=True,
            applicant_writable=True,
            source_binding="",
        ).order_by("section__position", "position", "id")[
            : MAX_PROGRAMME_ANSWER_PROJECTION + 1
        ]
    )
    if len(questions) > MAX_PROGRAMME_ANSWER_PROJECTION:
        raise ApplicationsProgrammeProjectionOverflowError
    values = {key: answer.value for key, answer in latest.items()}
    return tuple(
        ProgrammeAnswerProjection(
            question=_question(question),
            answer_revision_id=(
                latest[question.key].id if question.key in latest else None
            ),
            value=(latest[question.key].value if question.key in latest else None),
            actor_id=(
                latest[question.key].actor_id if question.key in latest else None
            ),
            resulting_version=(
                latest[question.key].resulting_version
                if question.key in latest
                else None
            ),
        )
        for question in questions
        if condition_matches(question.condition, values)
    )


def _contributor_projections(
    *,
    proposal: ProgrammeProposal,
    scope: AuthorizedProgrammeProposalScope,
    effective_now: datetime,
) -> tuple[ProgrammeContributorProjection, ...]:
    collaborators = ProgrammeProposalCollaborator.objects.filter(
        organization_id=proposal.organization_id,
        edition_id=proposal.edition_id,
        proposal=proposal,
        state__in=(
            ProgrammeCollaboratorState.INVITED,
            ProgrammeCollaboratorState.ACCEPTED,
        ),
    )
    if scope.relationship != "lead":
        collaborators = collaborators.filter(
            account_id=scope.actor_id,
            state=ProgrammeCollaboratorState.ACCEPTED,
        )
    collaborator_rows = tuple(
        collaborators.order_by("created_at", "id")[
            :MAX_PROGRAMME_CONTRIBUTOR_PROJECTION
        ]
    )
    account_ids = {
        proposal.submission.account_id,
        *(row.account_id for row in collaborator_rows),
    }
    labels = active_verified_person_account_display_labels(account_ids)
    rows = [
        ProgrammeContributorProjection(
            account_id=proposal.submission.account_id,
            display_label=labels.get(
                proposal.submission.account_id,
                "Maru account",
            ),
            role=ProgrammeContributorRole.LEAD,
            collaborator_id=None,
            state="lead",
            generation=None,
            invitation_expired=False,
        )
    ]
    rows.extend(
        ProgrammeContributorProjection(
            account_id=row.account_id,
            display_label=labels.get(row.account_id, "Maru account"),
            role=ProgrammeContributorRole.COLLABORATOR,
            collaborator_id=row.id,
            state=row.state,
            generation=row.generation,
            invitation_expired=(
                row.state == ProgrammeCollaboratorState.INVITED
                and row.invite_expires_at <= effective_now
            ),
        )
        for row in collaborator_rows
    )
    return _bounded_tuple(rows, maximum=MAX_PROGRAMME_CONTRIBUTOR_PROJECTION)


def _profile_value(
    profile: ProgrammeProposalContributorProfileRevision,
    *,
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
    raise ApplicationsProgrammeProjectionError


def _own_profile_projection(
    *,
    proposal: ProgrammeProposal,
    scope: AuthorizedProgrammeProposalScope,
) -> tuple[
    tuple[ProgrammeContributorFieldProjection, ...],
    ProgrammeOwnProfileProjection | None,
]:
    role = (
        ProgrammeContributorRole.LEAD
        if scope.relationship == "lead"
        else ProgrammeContributorRole.COLLABORATOR
    )
    configured_fields = tuple(
        proposal.call.contributor_fields.order_by("position", "id")
    )
    visible_fields = tuple(
        row
        for row in configured_fields
        if (
            row.lead_requirement
            if role == ProgrammeContributorRole.LEAD
            else row.collaborator_requirement
        )
        != ProgrammeContributorRequirement.HIDDEN
    )
    requirements = tuple(
        ProgrammeContributorFieldProjection(
            field_code=row.field_code,
            lead_requirement=row.lead_requirement,
            collaborator_requirement=row.collaborator_requirement,
            position=row.position,
        )
        for row in visible_fields
    )
    profile = (
        ProgrammeProposalContributorProfileRevision.objects.filter(
            organization_id=proposal.organization_id,
            edition_id=proposal.edition_id,
            proposal=proposal,
            account_id=scope.actor_id,
            resulting_version__lte=proposal.submission.aggregate_version,
        )
        .order_by("-resulting_version", "-sequence", "-id")
        .first()
    )
    if profile is None:
        return requirements, None
    return requirements, ProgrammeOwnProfileProjection(
        profile_revision_id=profile.id,
        values=tuple(
            (
                row.field_code,
                _profile_value(profile, field_code=row.field_code),
            )
            for row in visible_fields
        ),
        proposed_for_publication=profile.proposed_for_publication,
        consent_acknowledged=profile.consent_acknowledged,
        consent_policy_code=profile.consent_policy_code,
        resulting_version=profile.resulting_version,
    )


def _revision_projections(
    *,
    proposal: ProgrammeProposal,
    scope: AuthorizedProgrammeProposalScope,
) -> tuple[ProgrammeRevisionProjection, ...]:
    revisions = ProgrammeProposalRevision.objects.filter(
        organization_id=proposal.organization_id,
        edition_id=proposal.edition_id,
        proposal=proposal,
    )
    if scope.relationship != "lead":
        revisions = revisions.filter(
            contributors__account_id=scope.actor_id,
            contributors__role=ProgrammeContributorRole.COLLABORATOR,
        ).distinct()
    rows = tuple(
        revisions.order_by("sequence", "id")[: MAX_PROGRAMME_REVISION_PROJECTION + 1]
    )
    if len(rows) > MAX_PROGRAMME_REVISION_PROJECTION:
        raise ApplicationsProgrammeProjectionOverflowError
    return tuple(
        ProgrammeRevisionProjection(
            revision_id=row.id,
            sequence=row.sequence,
            predecessor_id=row.predecessor_id,
            definition_version=row.definition_version,
            selection_revision_id=row.selection_revision_id,
            resulting_version=row.resulting_version,
            digest=row.digest,
            sealed_at=row.sealed_at,
            current=row.id == proposal.sealed_revision_id,
            submitted=row.id == proposal.submitted_revision_id,
        )
        for row in rows
    )


def _response_projections(
    *,
    proposal: ProgrammeProposal,
    scope: AuthorizedProgrammeProposalScope,
) -> tuple[ProgrammeRevisionResponseProjection, ...]:
    contributors = ProgrammeProposalRevisionContributor.objects.select_related(
        "revision"
    ).filter(
        organization_id=proposal.organization_id,
        edition_id=proposal.edition_id,
        revision__proposal=proposal,
        role=ProgrammeContributorRole.COLLABORATOR,
    )
    if scope.relationship != "lead":
        contributors = contributors.filter(account_id=scope.actor_id)
    contributor_rows = tuple(
        contributors.order_by("revision__sequence", "account_id", "id")[
            : MAX_PROGRAMME_RESPONSE_PROJECTION + 1
        ]
    )
    if len(contributor_rows) > MAX_PROGRAMME_RESPONSE_PROJECTION:
        raise ApplicationsProgrammeProjectionOverflowError
    responses = {
        row.contributor_id: row
        for row in ProgrammeProposalRevisionResponse.objects.filter(
            organization_id=proposal.organization_id,
            edition_id=proposal.edition_id,
            contributor_id__in=(row.id for row in contributor_rows),
        ).order_by("contributor_id", "id")
    }
    return tuple(
        ProgrammeRevisionResponseProjection(
            revision_id=contributor.revision_id,
            contributor_id=contributor.id,
            account_id=contributor.account_id,
            response=(
                responses[contributor.id].response
                if contributor.id in responses
                else None
            ),
            responded_at=(
                responses[contributor.id].responded_at
                if contributor.id in responses
                else None
            ),
        )
        for contributor in contributor_rows
    )


@transaction.atomic
def get_self_programme_proposal_detail(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    proposal_id: UUID,
    requested_fields: frozenset[str],
    correlation_id: UUID,
    source_channel: str,
    now: datetime | None = None,
    authorizer: ApplicationsProgrammeAuthorizer = (_DEFAULT_AUTHORIZER),
) -> ProgrammeProposalDetailProjection:
    """Project one proposal through an exact relationship and field ceiling.

    Parameters
    ----------
    actor_id : UUID
        Exact current person-account identifier.
    organization_id : UUID
        Organization expected to own the proposal.
    edition_id : UUID
        Exact event edition identifier.
    proposal_id : UUID
        Exact Programme proposal identifier.
    requested_fields : frozenset[str]
        Non-empty code-owned field ceiling for this projection.
    correlation_id : UUID
        Request correlation identifier for audited disclosure.
    source_channel : str
        Registered request channel for audit evidence.
    now : datetime | None, default=None
        Optional aware instant for deterministic invitation expiry.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Sealed complete-decision adapter.

    Returns
    -------
    ProgrammeProposalDetailProjection
        Relationship-filtered proposal detail within the requested ceiling.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If scope, relationship, fields, time, profile, or policy is invalid.
    """
    actor_id = require_programme_uuid(actor_id, field="actor_id")
    organization_id = require_programme_uuid(
        organization_id,
        field="organization_id",
    )
    edition_id = require_programme_uuid(edition_id, field="edition_id")
    proposal_id = require_programme_uuid(proposal_id, field="proposal_id")
    correlation_id, source_channel = _audit_inputs(
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    if (
        not isinstance(requested_fields, frozenset)
        or not requested_fields
        or not requested_fields.issubset(_FULL_PROPOSAL_FIELDS)
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    effective_now = now or timezone.now()
    if not timezone.is_aware(effective_now):
        raise ApplicationsProgrammeAuthorizationDeniedError
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=requested_fields,
        authorizer=authorizer,
        now=effective_now,
    )
    proposal = (
        _proposal_query(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .filter(id=proposal_id)
        .first()
    )
    if proposal is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    selection = (
        _latest_selection_projection(proposal=proposal)
        if "selection" in requested_fields
        else None
    )
    profile_requirements: tuple[ProgrammeContributorFieldProjection, ...] | None
    own_profile: ProgrammeOwnProfileProjection | None
    if "contributor_profiles" in requested_fields:
        profile_requirements, own_profile = _own_profile_projection(
            proposal=proposal,
            scope=scope,
        )
    else:
        profile_requirements, own_profile = None, None
    projection = ProgrammeProposalDetailProjection(
        requested_fields=requested_fields,
        summary=(
            _proposal_summary(proposal=proposal, relationship=scope.relationship)
            if "proposal_summary" in requested_fields
            else None
        ),
        selection=selection,
        answers=(
            _answer_projections(proposal=proposal)
            if "answers" in requested_fields
            else None
        ),
        contributors=(
            _contributor_projections(
                proposal=proposal,
                scope=scope,
                effective_now=effective_now,
            )
            if "contributors" in requested_fields
            else None
        ),
        own_profile_requirements=profile_requirements,
        contributor_consent_policy_code=(
            proposal.call.contributor_consent_policy_code
            if "contributor_profiles" in requested_fields
            else None
        ),
        own_profile=own_profile,
        revisions=(
            _revision_projections(proposal=proposal, scope=scope)
            if "revision_history" in requested_fields
            else None
        ),
        responses=(
            _response_projections(proposal=proposal, scope=scope)
            if "revision_responses" in requested_fields
            else None
        ),
        own_invitation=(
            _own_invitation_projection(
                proposal=proposal,
                actor_id=actor_id,
                effective_now=effective_now,
            )
            if "own_invitation" in requested_fields
            else None
        ),
    )
    scope = authorize_programme_proposal_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        proposal_id=proposal_id,
        capability_code=APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF,
        requested_fields=requested_fields,
        authorizer=authorizer,
        now=effective_now,
    )
    _append_sensitive_read(
        scope=scope,
        operation="applications.programme.query.self_proposal_detail",
        target_id=proposal_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
        occurred_at=effective_now,
    )
    return projection


__all__ = [
    "ApplicationsProgrammeProjectionError",
    "ApplicationsProgrammeProjectionOverflowError",
    "AvailableProgrammeCallProjection",
    "ProgrammeAnswerProjection",
    "ProgrammeCallConfigurationProjection",
    "ProgrammeCallSummary",
    "ProgrammeContributorFieldProjection",
    "ProgrammeContributorProjection",
    "ProgrammeFormatProjection",
    "ProgrammeInvitationProjection",
    "ProgrammeOwnProfileProjection",
    "ProgrammeProposalDetailProjection",
    "ProgrammeProposalListItem",
    "ProgrammeProposalSummaryProjection",
    "ProgrammeQuestionOptionProjection",
    "ProgrammeQuestionProjection",
    "ProgrammeRevisionProjection",
    "ProgrammeRevisionResponseProjection",
    "ProgrammeSectionProjection",
    "ProgrammeSelectionProjection",
    "ProgrammeTrackProjection",
    "available_programme_calls",
    "get_managed_programme_call_configuration",
    "get_self_programme_proposal_detail",
    "list_managed_programme_calls",
    "list_self_programme_proposals",
]
