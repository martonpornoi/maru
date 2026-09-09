"""Bounded, field-scoped staffing terms and stable immutable-history pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import F

from maru.events.queries import resolve_private_planning_edition_reference

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
)
from .inputs import require_uuid
from .models import (
    ProgrammeItem,
    ProgrammeStaffingRequirement,
    ProgrammeStaffingRevision,
)
from .queries import ProgrammeQueryUnavailableError, _authorized_query
from .staffing_inputs import (
    MAX_STAFFING_REQUIREMENT_REVISIONS,
    MAX_STAFFING_REQUIREMENTS_PER_ITEM,
    ProgrammeStaffingExpectation,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from uuid import UUID

STAFFING_HISTORY_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingReadRequest:
    """Exact independently authorized read purpose and trace attribution.

    Attributes
    ----------
    actor_id
        Authenticated organizer, never a substitute for current authority.
    organization_id
        Expected exact tenant.
    edition_id
        Exact edition owning the requirement.
    item_id
        Programme item selected for this read.
    correlation_id
        Trusted server trace identifier.
    source_channel
        Closed adapter provenance.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    item_id: UUID
    correlation_id: UUID
    source_channel: str = "programme-staffing"


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingRequirementView:
    """Explicit Programme work terms without personnel, candidates or shift status.

    Attributes
    ----------
    requirement_id
        Stable retained staffing need.
    occurrence_id
        Exact opaque Scheduling occurrence, not its placement.
    version
        Historical requirement revision version.
    revision_id
        Immutable terms or retirement evidence.
    item_version
        Programme source version at this revision.
    occurrence_version
        Scheduling metadata version at this revision.
    lifecycle
        Active or retained retired state at this revision.
    expectation
        Deliberate work terms; never inferred from private Programme copy.
    """

    requirement_id: UUID
    occurrence_id: UUID
    version: int
    revision_id: UUID
    item_version: int
    occurrence_version: int
    lifecycle: str
    expectation: ProgrammeStaffingExpectation


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingOverview:
    """Complete current requirement set at one locked Programme item version.

    Attributes
    ----------
    item_id
        Exact Programme owner.
    item_version
        Current aggregate version for explicit later command preconditions.
    requirements
        Complete bounded set, including retained retired requirements.
    item_lifecycle
        Current item lifecycle; retained needs do not make withdrawn work active.
    """

    item_id: UUID
    item_version: int
    requirements: tuple[ProgrammeStaffingRequirementView, ...]
    item_lifecycle: str


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingHistoryEntry:
    """One independently ceilinged historical decision with its original terms.

    Attributes
    ----------
    requirement
        Work expectation and lifecycle exactly as recorded.
    operation
        Closed creation, revision or retirement action.
    actor_id
        Opaque historical actor reference; not a personnel directory projection.
    reason
        Restricted retained decision rationale.
    occurred_at
        Server-owned timestamp of the historical action.
    """

    requirement: ProgrammeStaffingRequirementView
    operation: str
    actor_id: UUID
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingHistoryPage:
    """Stable bounded history page that cannot silently follow later revisions.

    Attributes
    ----------
    through_version
        Fixed inclusive history ceiling selected from an authorized view.
    entries
        At most fifty immutable revisions in ascending sequence.
    next_after_version
        Exclusive continuation cursor, or ``None`` when the ceiling was reached.
    """

    through_version: int
    entries: tuple[ProgrammeStaffingHistoryEntry, ...]
    next_after_version: int | None


def _view(
    revision: ProgrammeStaffingRevision, *, occurrence_id: UUID
) -> ProgrammeStaffingRequirementView:
    return ProgrammeStaffingRequirementView(
        revision.requirement_id,
        occurrence_id,
        revision.sequence,
        revision.id,
        revision.item_version,
        revision.occurrence_version,
        revision.lifecycle,
        ProgrammeStaffingExpectation(
            **{
                field: getattr(revision, field)
                for field in ProgrammeStaffingExpectation.__dataclass_fields__
            }
        ),
    )


def _read[ResultT](
    request: ProgrammeStaffingReadRequest,
    *,
    fields: frozenset[str],
    operation: str,
    loader: Callable[[ProgrammeItem], ResultT],
    authorizer: ProgrammeAuthorizer,
) -> ResultT:
    for field in (
        "actor_id",
        "organization_id",
        "edition_id",
        "item_id",
        "correlation_id",
    ):
        require_uuid(getattr(request, field), field=field)

    def load() -> ResultT:
        if (
            resolve_private_planning_edition_reference(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                lock=True,
            )
            is None
        ):
            raise ProgrammeQueryUnavailableError
        item = (
            ProgrammeItem.objects.filter(
                id=request.item_id,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
            )
            .only("id", "aggregate_version", "lifecycle")
            .first()
        )
        if item is None:
            raise ProgrammeQueryUnavailableError
        return loader(item)

    return _authorized_query(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=PROGRAMME_VIEW_STAFFING,
        requested_fields=fields,
        operation=operation,
        loader=load,
        target_type="programme.item",
        target_id=request.item_id,
        target_count=lambda _: 1,
        reason="Explicit Programme staffing-purpose read",
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
        authorizer=authorizer,
    )


def load_programme_staffing_requirements(
    request: ProgrammeStaffingReadRequest,
    *,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeStaffingOverview:
    """Return a complete current set without history rationale or worker identities.

    Parameters
    ----------
    request : ProgrammeStaffingReadRequest
        Exact item scope and audit attribution.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real field-aware policy; replacement is guarded by isolated-test settings.

    Returns
    -------
    ProgrammeStaffingOverview
        Complete bounded current work terms, or an exception rather than partial data.
    """

    def load(item: ProgrammeItem) -> ProgrammeStaffingOverview:
        requirements = tuple(
            ProgrammeStaffingRequirement.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                item_id=item.id,
            )
            .order_by("id")
            .values_list("id", "occurrence_id")[
                : MAX_STAFFING_REQUIREMENTS_PER_ITEM + 1
            ]
        )
        if len(requirements) > MAX_STAFFING_REQUIREMENTS_PER_ITEM:
            raise ProgrammeQueryUnavailableError
        revisions = ProgrammeStaffingRevision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id=item.id,
            requirement_id__in=[row[0] for row in requirements],
            sequence=F("requirement__version"),
        ).defer("reason", "actor_id", "occurred_at")
        by_requirement = {revision.requirement_id: revision for revision in revisions}
        if len(by_requirement) != len(requirements):
            raise ProgrammeQueryUnavailableError
        return ProgrammeStaffingOverview(
            item.id,
            item.aggregate_version,
            tuple(
                _view(by_requirement[identifier], occurrence_id=occurrence_id)
                for identifier, occurrence_id in requirements
            ),
            item.lifecycle,
        )

    return _read(
        request,
        fields=frozenset({"staffing_requirements"}),
        operation="programme.staffing.read",
        loader=load,
        authorizer=authorizer,
    )


def load_programme_staffing_history(
    request: ProgrammeStaffingReadRequest,
    *,
    requirement_id: UUID,
    through_version: int,
    after_version: int = 0,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeStaffingHistoryPage:
    """Read a fixed historical interval with independent history-field authority.

    Parameters
    ----------
    request : ProgrammeStaffingReadRequest
        Exact item scope and trusted audit attribution.
    requirement_id : UUID
        Stable requirement within that item, not a discovery filter.
    through_version : int
        Fixed inclusive ceiling from one authorized requirement view.
    after_version : int, default=0
        Exclusive sequence cursor; zero begins the history.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independently verified field-aware Programme policy.

    Returns
    -------
    ProgrammeStaffingHistoryPage
        At most fifty retained revisions and an explicit bounded continuation.
    """

    def load(item: ProgrammeItem) -> ProgrammeStaffingHistoryPage:
        require_uuid(requirement_id, field="requirement_id")
        requirement = ProgrammeStaffingRequirement.objects.filter(
            id=requirement_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id=item.id,
        ).first()
        if (
            requirement is None
            or type(through_version) is not int
            or type(after_version) is not int
        ):
            raise ProgrammeQueryUnavailableError
        if (
            not 0
            <= after_version
            < through_version
            <= requirement.version
            <= MAX_STAFFING_REQUIREMENT_REVISIONS + 1
        ):
            raise ProgrammeQueryUnavailableError
        rows = tuple(
            ProgrammeStaffingRevision.objects.filter(
                requirement_id=requirement.id,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                item_id=item.id,
                sequence__gt=after_version,
                sequence__lte=through_version,
            ).order_by("sequence")[: STAFFING_HISTORY_PAGE_SIZE + 1]
        )
        expected = min(through_version - after_version, STAFFING_HISTORY_PAGE_SIZE + 1)
        if len(rows) != expected or any(
            row.sequence != after_version + index + 1 for index, row in enumerate(rows)
        ):
            raise ProgrammeQueryUnavailableError
        page = rows[:STAFFING_HISTORY_PAGE_SIZE]
        return ProgrammeStaffingHistoryPage(
            through_version,
            tuple(
                ProgrammeStaffingHistoryEntry(
                    _view(row, occurrence_id=requirement.occurrence_id),
                    row.operation,
                    row.actor_id,
                    row.reason,
                    row.occurred_at,
                )
                for row in page
            ),
            page[-1].sequence if len(rows) > STAFFING_HISTORY_PAGE_SIZE else None,
        )

    return _read(
        request,
        fields=frozenset({"staffing_history"}),
        operation="programme.staffing.history",
        loader=load,
        authorizer=authorizer,
    )
