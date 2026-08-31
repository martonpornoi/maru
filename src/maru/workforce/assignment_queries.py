"""Bounded read models for assignment management and self-service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.db import models
from django.utils import timezone

from maru.events.queries import adoption_profile_filter_for_adapter
from maru.identity.queries import (
    account_display_labels,
    active_person_account_display_labels,
)
from maru.organizations.queries import known_organization_person_account_ids
from maru.participation.models import Participation
from maru.workforce.adoption import WORKFORCE_SELF_ADAPTER
from maru.workforce.models import (
    OnboardingDocumentRequest,
    Position,
    PositionAssignment,
    PositionAssignmentCommandReceipt,
    PositionDocumentRequirement,
    VolunteerApplication,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime
    from uuid import UUID

    from django.db.models import QuerySet

    from maru.identity.models import Account

MAX_ASSIGNMENT_CANDIDATES = 512
MAX_ASSIGNMENT_RECORDS = 1_024
MAX_ASSIGNMENT_HISTORY = 64

_ONBOARDING_STATUS_LABELS = {
    "not_requested": "Not requested",
    OnboardingDocumentRequest.Status.REQUESTED: "Not submitted",
    OnboardingDocumentRequest.Status.SUBMITTED: "Awaiting review",
    OnboardingDocumentRequest.Status.APPROVED: "Approved",
    OnboardingDocumentRequest.Status.REJECTED: "Replacement needed",
}


class AssignmentReadLimitExceededError(RuntimeError):
    """Signal that a complete protected assignment projection is too large."""


@dataclass(frozen=True, slots=True)
class AssignmentRequirementStatus:
    """One Position requirement and the candidate's current readiness.

    Attributes
    ----------
    name
        Human onboarding-document name.
    status
        Stable current request state.
    status_label
        Human explanation of the current request state.
    approved
        Whether this requirement currently permits assignment approval.
    """

    name: str
    status: str
    status_label: str
    approved: bool


@dataclass(frozen=True, slots=True)
class AssignmentReadiness:
    """Complete onboarding readiness for one Position and account.

    Attributes
    ----------
    requirements
        Every Position requirement and the person's current evidence state.
    """

    requirements: tuple[AssignmentRequirementStatus, ...]

    @property
    def ready(self) -> bool:
        """Return whether every required onboarding item is approved."""
        return all(requirement.approved for requirement in self.requirements)

    @property
    def approved_count(self) -> int:
        """Return the number of approved requirements."""
        return sum(requirement.approved for requirement in self.requirements)


@dataclass(frozen=True, slots=True)
class AssignmentCandidate:
    """A minimized active person already related to the assignment scope.

    Attributes
    ----------
    account_id
        Active person account identifier accepted by the command.
    display_name
        Human label released after identity and relationship validation.
    known_via
        Minimized relationship sources that make this person selectable.
    readiness
        Position-specific onboarding readiness.
    """

    account_id: UUID
    display_name: str
    known_via: tuple[str, ...]
    readiness: AssignmentReadiness

    @property
    def choice_label(self) -> str:
        """Return a compact label suitable for an accessible select control."""
        relationship = ", ".join(self.known_via)
        if not self.readiness.requirements:
            readiness = "no onboarding documents required"
        elif self.readiness.ready:
            readiness = "onboarding ready"
        else:
            readiness = (
                f"{self.readiness.approved_count} of "
                f"{len(self.readiness.requirements)} onboarding items approved"
            )
        return f"{self.display_name} — {relationship}; {readiness}"


@dataclass(frozen=True, slots=True)
class AssignmentOverviewItem:
    """One management-facing assignment row with derived truthful state.

    Attributes
    ----------
    assignment
        Exact-edition assignment record.
    account_label
        Human person label released to the authorized manager.
    readiness
        Position-specific onboarding readiness.
    state_label
        Human state including explicit overdue-ending treatment.
    needs_another_approver
        Whether the current viewer proposed this still-pending assignment.
    """

    assignment: PositionAssignment
    account_label: str
    readiness: AssignmentReadiness
    state_label: str
    needs_another_approver: bool


@dataclass(frozen=True, slots=True)
class AssignmentHistoryItem:
    """One directly inspectable assignment command reason.

    Attributes
    ----------
    action_label
        Human assignment command action.
    reason
        Private organizer rationale retained by the command.
    actor_label
        Human label for the attributed command actor.
    occurred_at
        Time at which the immutable receipt was written.
    resulting_version
        Assignment version produced by the command.
    """

    action_label: str
    reason: str
    actor_label: str
    occurred_at: datetime
    resulting_version: int


@dataclass(frozen=True, slots=True)
class MyAssignmentItem:
    """One reason-minimized assignment state visible to its subject.

    Attributes
    ----------
    assignment
        Assignment owned by the signed-in person.
    state_label
        Human lifecycle state without organizer rationale or actor labels.
    """

    assignment: PositionAssignment
    state_label: str


def _bounded_ids(query: QuerySet[Any], *, limit: int) -> tuple[UUID, ...]:
    values = tuple(
        query.order_by("account_id").values_list("account_id", flat=True)[: limit + 1]
    )
    if len(values) > limit:
        raise AssignmentReadLimitExceededError
    return values


def _requirement_statuses(
    *,
    position: Position,
    account_ids: Iterable[UUID],
) -> dict[UUID, AssignmentReadiness]:
    bounded_account_ids = tuple(account_ids)
    requirements = tuple(
        position.document_requirements.select_related("document_type").order_by(
            "document_type__name", "document_type_id"
        )
    )
    if not requirements:
        return {
            account_id: AssignmentReadiness(requirements=())
            for account_id in bounded_account_ids
        }
    required_type_ids = tuple(
        requirement.document_type_id for requirement in requirements
    )
    request_states: dict[tuple[UUID, UUID], str] = {}
    for request in OnboardingDocumentRequest.objects.filter(
        organization_id=position.organization_id,
        edition_id=position.edition_id,
        account_id__in=bounded_account_ids,
        document_type_id__in=required_type_ids,
    ).order_by("account_id", "document_type_id", "-updated_at", "-id"):
        request_states.setdefault(
            (request.account_id, request.document_type_id),
            request.status,
        )
    return {
        account_id: AssignmentReadiness(
            requirements=tuple(
                AssignmentRequirementStatus(
                    name=requirement.document_type.name,
                    status=(
                        state := request_states.get(
                            (account_id, requirement.document_type_id),
                            "not_requested",
                        )
                    ),
                    status_label=_ONBOARDING_STATUS_LABELS[state],
                    approved=state == OnboardingDocumentRequest.Status.APPROVED,
                )
                for requirement in requirements
            )
        )
        for account_id in bounded_account_ids
    }


def _overview_readiness(
    assignments: tuple[PositionAssignment, ...],
) -> dict[UUID, AssignmentReadiness]:
    """Resolve every overview readiness state with two bounded bulk reads.

    Parameters
    ----------
    assignments : tuple[PositionAssignment, ...]
        Bounded exact-edition assignments in the management projection.

    Returns
    -------
    dict[UUID, AssignmentReadiness]
        Readiness keyed by assignment identifier.
    """
    if not assignments:
        return {}
    position_ids = {assignment.position_id for assignment in assignments}
    requirements_by_position: dict[UUID, list[PositionDocumentRequirement]] = {}
    all_document_type_ids: set[UUID] = set()
    for requirement in (
        PositionDocumentRequirement.objects.select_related("document_type")
        .filter(position_id__in=position_ids)
        .order_by("position_id", "document_type__name", "document_type_id")
    ):
        requirements_by_position.setdefault(requirement.position_id, []).append(
            requirement
        )
        all_document_type_ids.add(requirement.document_type_id)

    request_states: dict[tuple[UUID, UUID], str] = {}
    if all_document_type_ids:
        account_ids = {assignment.account_id for assignment in assignments}
        first = assignments[0]
        for request in OnboardingDocumentRequest.objects.filter(
            organization_id=first.organization_id,
            edition_id=first.edition_id,
            account_id__in=account_ids,
            document_type_id__in=all_document_type_ids,
        ).order_by("account_id", "document_type_id", "-updated_at", "-id"):
            request_states.setdefault(
                (request.account_id, request.document_type_id),
                request.status,
            )

    readiness: dict[UUID, AssignmentReadiness] = {}
    for assignment in assignments:
        requirements = requirements_by_position.get(assignment.position_id, [])
        readiness[assignment.id] = AssignmentReadiness(
            requirements=tuple(
                AssignmentRequirementStatus(
                    name=requirement.document_type.name,
                    status=(
                        state := request_states.get(
                            (assignment.account_id, requirement.document_type_id),
                            "not_requested",
                        )
                    ),
                    status_label=_ONBOARDING_STATUS_LABELS[state],
                    approved=state == OnboardingDocumentRequest.Status.APPROVED,
                )
                for requirement in requirements
            )
        )
    return readiness


def assignment_readiness(
    *,
    position: Position,
    account_id: UUID,
) -> AssignmentReadiness:
    """Return complete onboarding readiness for one proposed recipient.

    Parameters
    ----------
    position : Position
        Position whose document requirements define readiness.
    account_id : UUID
        Candidate person account identifier.

    Returns
    -------
    AssignmentReadiness
        Every Position requirement and its current candidate state.
    """
    return _requirement_statuses(
        position=position,
        account_ids=(account_id,),
    )[account_id]


def known_assignment_candidates(
    *, position: Position
) -> tuple[AssignmentCandidate, ...]:
    """Return bounded active people already related to the assignment scope.

    Parameters
    ----------
    position : Position
        Exact Position for which candidates are being selected.

    Returns
    -------
    tuple[AssignmentCandidate, ...]
        Ordered active known people with minimized relationship and readiness
        labels.

    """
    sources: dict[UUID, set[str]] = {}

    def remember(account_ids: Iterable[UUID], label: str) -> None:
        for account_id in account_ids:
            sources.setdefault(account_id, set()).add(label)
            if len(sources) > MAX_ASSIGNMENT_CANDIDATES:
                raise AssignmentReadLimitExceededError

    remember(
        known_organization_person_account_ids(
            organization_id=position.organization_id,
            limit=MAX_ASSIGNMENT_CANDIDATES,
        ),
        "organization relationship",
    )
    remember(
        _bounded_ids(
            Participation.objects.filter(edition_id=position.edition_id).exclude(
                status=Participation.Status.CANCELLED
            ),
            limit=MAX_ASSIGNMENT_CANDIDATES,
        ),
        "edition participant",
    )
    remember(
        _bounded_ids(
            VolunteerApplication.objects.filter(
                opportunity__position_id=position.id,
                status__in=(
                    VolunteerApplication.Status.SUBMITTED,
                    VolunteerApplication.Status.UNDER_REVIEW,
                    VolunteerApplication.Status.ACCEPTED,
                ),
            ),
            limit=MAX_ASSIGNMENT_CANDIDATES,
        ),
        "Position applicant",
    )
    remember(
        _bounded_ids(
            OnboardingDocumentRequest.objects.filter(
                organization_id=position.organization_id,
                edition_id=position.edition_id,
            ),
            limit=MAX_ASSIGNMENT_CANDIDATES,
        ),
        "onboarding relationship",
    )
    remember(
        _bounded_ids(
            PositionAssignment.objects.filter(
                organization_id=position.organization_id,
                edition_id=position.edition_id,
            ),
            limit=MAX_ASSIGNMENT_CANDIDATES,
        ),
        "Workforce history",
    )

    open_for_position = set(
        PositionAssignment.objects.filter(
            position_id=position.id,
            status__in=(
                PositionAssignment.Status.PROPOSED,
                PositionAssignment.Status.ACTIVE,
            ),
        ).values_list("account_id", flat=True)
    )
    candidate_ids = tuple(
        account_id for account_id in sources if account_id not in open_for_position
    )
    labels = active_person_account_display_labels(candidate_ids)
    readiness = _requirement_statuses(
        position=position,
        account_ids=labels,
    )
    source_order = {
        "Position applicant": 0,
        "onboarding relationship": 1,
        "edition participant": 2,
        "organization relationship": 3,
        "Workforce history": 4,
    }
    return tuple(
        sorted(
            (
                AssignmentCandidate(
                    account_id=account_id,
                    display_name=label,
                    known_via=tuple(
                        sorted(
                            sources[account_id],
                            key=lambda source: source_order[source],
                        )
                    ),
                    readiness=readiness[account_id],
                )
                for account_id, label in labels.items()
            ),
            key=lambda candidate: (
                candidate.display_name.casefold(),
                str(candidate.account_id),
            ),
        )
    )


def assignment_overview_items(
    *,
    organization_id: UUID,
    edition_id: UUID,
    actor: Account,
) -> tuple[AssignmentOverviewItem, ...]:
    """Return a complete bounded assignment queue for one authorized edition.

    Parameters
    ----------
    organization_id : UUID
        Organization that owns the queue.
    edition_id : UUID
        Exact event edition containing the assignments.
    actor : Account
        Authorized viewer used to identify self-proposed rows.

    Returns
    -------
    tuple[AssignmentOverviewItem, ...]
        Proposed-first assignment items with labels and readiness.

    Raises
    ------
    AssignmentReadLimitExceededError
        If the queue exceeds its complete-projection ceiling.
    """
    assignments = tuple(
        PositionAssignment.objects.select_related("position", "position__department")
        .filter(organization_id=organization_id, edition_id=edition_id)
        .alias(
            assignment_state_order=models.Case(
                models.When(
                    status=PositionAssignment.Status.PROPOSED,
                    then=models.Value(0),
                ),
                models.When(
                    status=PositionAssignment.Status.ACTIVE,
                    then=models.Value(1),
                ),
                default=models.Value(2),
                output_field=models.IntegerField(),
            )
        )
        .order_by("assignment_state_order", "position__title", "-created_at", "id")[
            : MAX_ASSIGNMENT_RECORDS + 1
        ]
    )
    if len(assignments) > MAX_ASSIGNMENT_RECORDS:
        raise AssignmentReadLimitExceededError
    labels = account_display_labels(
        tuple(assignment.account_id for assignment in assignments)
    )
    readiness = _overview_readiness(assignments)
    current_time = timezone.now()
    items = []
    for assignment in assignments:
        label = labels.get(assignment.account_id)
        if label is None:
            continue
        if assignment.status == PositionAssignment.Status.PROPOSED:
            state_label = "Waiting for independent approval"
        elif (
            assignment.status == PositionAssignment.Status.ACTIVE
            and assignment.expires_at is not None
            and assignment.expires_at <= current_time
        ):
            state_label = "Expired — ending required"
        else:
            state_label = assignment.get_status_display()
        items.append(
            AssignmentOverviewItem(
                assignment=assignment,
                account_label=label,
                readiness=readiness[assignment.id],
                state_label=state_label,
                needs_another_approver=(
                    assignment.status == PositionAssignment.Status.PROPOSED
                    and assignment.proposed_by_id == actor.id
                ),
            )
        )
    return tuple(items)


def assignment_history_items(
    *,
    assignment: PositionAssignment,
) -> tuple[AssignmentHistoryItem, ...]:
    """Return newest-first retained reasons for one authorized assignment.

    Parameters
    ----------
    assignment : PositionAssignment
        Assignment whose private command history is requested.

    Returns
    -------
    tuple[AssignmentHistoryItem, ...]
        Newest-first minimized command history with organizer reasons.

    Raises
    ------
    AssignmentReadLimitExceededError
        If retained history exceeds its complete-projection ceiling.
    """
    receipts = tuple(
        PositionAssignmentCommandReceipt.objects.filter(assignment=assignment).order_by(
            "-resulting_version", "-id"
        )[: MAX_ASSIGNMENT_HISTORY + 1]
    )
    if len(receipts) > MAX_ASSIGNMENT_HISTORY:
        raise AssignmentReadLimitExceededError
    labels = account_display_labels(tuple(receipt.actor_id for receipt in receipts))
    return tuple(
        AssignmentHistoryItem(
            action_label=receipt.get_action_display(),
            reason=receipt.reason,
            actor_label=labels.get(receipt.actor_id, "Maru account"),
            occurred_at=receipt.created_at,
            resulting_version=receipt.resulting_version,
        )
        for receipt in receipts
    )


def my_assignment_items(
    *,
    account: Account,
    permitted_scopes: frozenset[tuple[UUID, UUID]],
) -> tuple[MyAssignmentItem, ...]:
    """Return a bounded reason-minimized assignment history for its subject.

    Parameters
    ----------
    account : Account
        Signed-in person whose own assignments may be returned.
    permitted_scopes : frozenset[tuple[UUID, UUID]]
        Exact organization and edition pairs already permitted for the person.

    Returns
    -------
    tuple[MyAssignmentItem, ...]
        The subject's assignments without organizer reasons or actor labels.

    Raises
    ------
    AssignmentReadLimitExceededError
        If the personal projection exceeds its complete-record ceiling.
    """
    if not permitted_scopes:
        return ()
    scope_filter = None
    for organization_id, edition_id in permitted_scopes:
        candidate = models.Q(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        scope_filter = candidate if scope_filter is None else scope_filter | candidate
    if scope_filter is None:
        return ()
    assignments = tuple(
        PositionAssignment.objects.select_related(
            "organization",
            "edition",
            "position",
            "position__department",
        )
        .filter(
            adoption_profile_filter_for_adapter(
                WORKFORCE_SELF_ADAPTER,
                field_prefix="edition",
            ),
            scope_filter,
            account=account,
        )
        .order_by("-created_at", "id")[: MAX_ASSIGNMENT_RECORDS + 1]
    )
    if len(assignments) > MAX_ASSIGNMENT_RECORDS:
        raise AssignmentReadLimitExceededError
    current_time = timezone.now()
    return tuple(
        MyAssignmentItem(
            assignment=assignment,
            state_label=(
                "Expired — organizer follow-up needed"
                if assignment.status == PositionAssignment.Status.ACTIVE
                and assignment.expires_at is not None
                and assignment.expires_at <= current_time
                else assignment.get_status_display()
            ),
        )
        for assignment in assignments
    )
