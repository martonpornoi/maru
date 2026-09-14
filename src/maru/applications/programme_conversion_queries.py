"""Minimal source choices for explicit conversion, never private review content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction
from django.db.models import F
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_ITEMS,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)

from .models import ProgrammeAcceptedTransition, ProgrammeReviewDecision
from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_conversion_authorization import (
    CONVERT_PROGRAMME_ACCEPTANCE,
    authorize_programme_conversion_scope,
)
from .programme_conversion_sources import (
    ProgrammeConversionConflictError,
    _current_accepted_decision,
)
from .programme_inputs import require_programme_uuid
from .programme_review_rules import load_review_case
from .programme_write_scope import (
    ApplicationsProgrammeWriteScopeUnavailableError,
    lock_programme_edition_write_scope,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from django.db.models import QuerySet

    from maru.programme.authorization import ProgrammeAuthorizer

    from .programme_authorization import ApplicationsProgrammeAuthorizer
    from .programme_conversion_authorization import AuthorizedProgrammeConversionScope

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_MAX_PAGE = 100


@dataclass(frozen=True, slots=True)
class ProgrammeConversionReadRequest:
    """Name trusted conversion scope without carrying permission or content fields.

    Attributes
    ----------
    actor_id : UUID
        Original authenticated person, reloaded by both owner authorizers.
    organization_id : UUID
        Exact common source and target organization.
    edition_id : UUID
        Exact common source and target edition.
    department_id : UUID
        Current owning Department for fresh source disclosure.
    correlation_id : UUID
        Server-generated minimized audit trace.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID
    correlation_id: UUID


@dataclass(frozen=True, slots=True)
class ProgrammeConversionChoice:
    """Label one historical acceptance without implying current eligibility.

    Attributes
    ----------
    decision_id : UUID
        Exact accepted decision, not an implicit latest selector.
    case_id : UUID
        Scoped review aggregate retaining that decision.
    revision_id : UUID
        Exact immutable accepted seal.
    call_name : str
        Owning call's label, never a proposal answer or private item title.
    sequence : int
        Human-readable submitted revision sequence.
    decided_at : datetime
        Immutable decision timestamp.
    decision_version : int
        Original decision's review-case version.
    review_version : int
        Currently inspected review cursor, including later retained actions.
    """

    decision_id: UUID
    case_id: UUID
    revision_id: UUID
    call_name: str
    sequence: int
    decided_at: datetime
    decision_version: int
    review_version: int


@dataclass(frozen=True, slots=True)
class ProgrammeConversionPage:
    """Return complete bounded source labels without hidden counts or people.

    Attributes
    ----------
    items : tuple[ProgrammeConversionChoice, ...]
        Exact-scope accepted references in ascending decision-identifier order.
    next_cursor : UUID | None
        Exclusive final returned decision identifier when another page exists.
    """

    items: tuple[ProgrammeConversionChoice, ...]
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class ProgrammeConversionSource:
    """Explain current eligibility separately from the historical acceptance label.

    Attributes
    ----------
    choice : ProgrammeConversionChoice
        Exact retained decision and immutable source labels.
    eligible : bool
        Existing canonical effective-source rule at inspection, not a write grant.
    consumed : bool
        Whether a retained conversion already owns this exact revision.
    writable : bool
        Source edition's planning state, independently rechecked by the command.
    """

    choice: ProgrammeConversionChoice
    eligible: bool
    consumed: bool
    writable: bool


def _ids(request: ProgrammeConversionReadRequest) -> dict[str, UUID]:
    return {
        name: getattr(request, name)
        for name in ("actor_id", "organization_id", "edition_id", "department_id")
    }


def _scope(
    request: ProgrammeConversionReadRequest,
    authorizer: ApplicationsProgrammeAuthorizer,
    programme_authorizer: ProgrammeAuthorizer,
) -> AuthorizedProgrammeConversionScope:
    for field in (*_ids(request), "correlation_id"):
        require_programme_uuid(getattr(request, field), field=field)
    scope = authorize_programme_conversion_scope(**_ids(request), authorizer=authorizer)
    authorize_programme_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=PROGRAMME_MANAGE_ITEMS,
        requested_fields=frozenset(),
        authorizer=programme_authorizer,
    )
    return scope


def _locked(
    request: ProgrammeConversionReadRequest,
    authorizer: ApplicationsProgrammeAuthorizer,
    programme_authorizer: ProgrammeAuthorizer,
) -> AuthorizedProgrammeConversionScope:
    _scope(request, authorizer, programme_authorizer)
    lock_programme_edition_write_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        department_ids=(request.department_id,),
    )
    return _scope(request, authorizer, programme_authorizer)


def can_use_programme_conversion(
    request: ProgrammeConversionReadRequest,
    *,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> bool:
    """Admit a navigation hint independently of decision or private-read authority.

    Parameters
    ----------
    request : ProgrammeConversionReadRequest
        Exact trusted actor, common tenant and owning Department.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Applications conversion policy boundary.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme item-management policy boundary.

    Returns
    -------
    bool
        Whether both current owner admissions allow offering the conversion task.
        This reads no source labels and grants no fresh command or private content.
    """
    try:
        _scope(request, authorizer, programme_authorizer)
    except (
        Denied,
        ProgrammeAuthorizationDeniedError,
        ApplicationsProgrammeWriteScopeUnavailableError,
        DatabaseError,
    ):
        return False
    return True


def _audit(
    request: ProgrammeConversionReadRequest,
    decision_id: UUID | None,
    authorizer: ApplicationsProgrammeAuthorizer,
    programme_authorizer: ProgrammeAuthorizer,
) -> None:
    scope = _scope(request, authorizer, programme_authorizer)
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code=CONVERT_PROGRAMME_ACCEPTANCE,
            operation="applications.programme_conversion.query.source",
            target_type="applications.programme_review_decision",
            target_id=decision_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel="programme-conversion",
            obligations=tuple(
                sorted(set(scope.decision.obligations) | {"audit_sensitive_read"})
            ),
            retention_class="applications-programme-restricted",
        ),
        occurred_at=timezone.now(),
    )


def _choices(
    request: ProgrammeConversionReadRequest,
) -> QuerySet[ProgrammeReviewDecision]:
    return ProgrammeReviewDecision.objects.select_related(
        "entry__case__proposal__call__definition", "revision"
    ).filter(
        outcome="accepted",
        entry__action="decided",
        revision__organization_id=request.organization_id,
        revision__edition_id=request.edition_id,
        entry__case__proposal__organization_id=request.organization_id,
        entry__case__proposal__edition_id=request.edition_id,
        entry__case__proposal__call__organization_id=request.organization_id,
        entry__case__proposal__call__edition_id=request.edition_id,
        entry__case__proposal__call__owner_department_id=request.department_id,
        entry__case__revision_id=F("revision_id"),
        revision__proposal_id=F("entry__case__proposal_id"),
        entry__case__policy__call_id=F("entry__case__proposal__call_id"),
        entry__version__lte=F("entry__case__version"),
    )


def _choice(decision: ProgrammeReviewDecision) -> ProgrammeConversionChoice:
    case = decision.entry.case
    return ProgrammeConversionChoice(
        decision.id,
        case.id,
        decision.revision_id,
        case.proposal.call.definition.name,
        decision.revision.sequence,
        decision.entry.created_at,
        decision.entry.version,
        case.version,
    )


@transaction.atomic
def list_programme_conversion_choices(
    *,
    request: ProgrammeConversionReadRequest,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeConversionPage:
    """Discover exact historical acceptances under both owners' current authority.

    Parameters
    ----------
    request : ProgrammeConversionReadRequest
        Exact actor, tenant, edition, Department and minimized trace.
    after_id : UUID | None, default=None
        Exclusive decision-identifier cursor, not an implicit latest source.
    limit : int, default=50
        Complete page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real Applications policy or the existing guarded test seam.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independently required Programme item-management policy.

    Returns
    -------
    ProgrammeConversionPage
        Audited labels; each selected source separately proves current eligibility.

    Raises
    ------
    Denied
        If the requested page bound is not a strict supported integer.
    """
    if type(limit) is not int or not 1 <= limit <= _MAX_PAGE:
        raise Denied
    if after_id is not None:
        require_programme_uuid(after_id, field="after_id")
    _locked(request, authorizer, programme_authorizer)
    query = _choices(request)
    if after_id is not None:
        query = query.filter(id__gt=after_id)
    rows = tuple(query.order_by("id")[: limit + 1])
    result = ProgrammeConversionPage(
        tuple(_choice(row) for row in rows[:limit]),
        rows[limit - 1].id if len(rows) > limit else None,
    )
    _audit(request, None, authorizer, programme_authorizer)
    return result


@transaction.atomic
def get_programme_conversion_source(
    *,
    request: ProgrammeConversionReadRequest,
    decision_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeConversionSource:
    """Inspect one exact source without copying review or proposal content.

    Parameters
    ----------
    request : ProgrammeConversionReadRequest
        Exact current actor, tenant, edition and owner Department.
    decision_id : UUID
        Original selected acceptance; never replaced with a newer decision.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real Applications policy or the existing guarded test seam.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme item-management policy.

    Returns
    -------
    ProgrammeConversionSource
        Audited current eligibility and consumption beside retained source labels.

    Raises
    ------
    Denied
        If the exact acceptance is missing, foreign or source-incoherent.
    """
    require_programme_uuid(decision_id, field="decision_id")
    scope = _locked(request, authorizer, programme_authorizer)
    decision = _choices(request).filter(id=decision_id).first()
    if decision is None:
        raise Denied
    case = load_review_case(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        case_id=decision.entry.case_id,
    )
    if case.proposal.call.owner_department_id != request.department_id:
        raise Denied
    try:
        _current_accepted_decision(
            scope=scope,
            decision_id=decision.id,
            revision_id=decision.revision_id,
            expected_review_version=case.version,
        )
    except ProgrammeConversionConflictError:
        eligible = False
    else:
        eligible = True
    consumed = ProgrammeAcceptedTransition.objects.filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        revision_id=decision.revision_id,
    ).exists()
    result = ProgrammeConversionSource(
        _choice(decision), eligible, consumed, scope.accepts_private_planning_writes
    )
    _audit(request, decision.id, authorizer, programme_authorizer)
    return result
