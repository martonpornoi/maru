"""Collect complete edition Applications exit scope without Department omission."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from django.db import transaction

from maru.audit.services import AuditRecord, append_audit
from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_EXPORT_ARCHIVE,
)
from maru.workforce.programme_references import lock_programme_staffing_scope

from .models import ProgrammeCall
from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    authorize_programme_call_scope,
)
from .programme_exit_department_queries import (
    ProgrammeExitDepartment,
    load_programme_exit_department,
)
from .programme_inputs import require_programme_uuid
from .programme_review_authorization import DECIDE, MANAGE_REVIEW, REVIEW_FIELDS
from .programme_review_queries import ProgrammeReviewReadRequest, _scope
from .programme_review_rules import ProgrammeReviewUnavailableError
from .programme_write_scope import lock_programme_edition_write_scope

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.authorization import (
        AuthorizedProgrammeScope,
        ProgrammeAuthorizer,
    )

    from .programme_authorization import ApplicationsProgrammeAuthorizer

MAX_EXIT_DEPARTMENTS: Final = 100
MAX_EXIT_CALLS: Final = 2_000
MAX_EXIT_OWNER_CASES: Final = 5_000
MAX_EXIT_OWNER_ENTRIES: Final = 200_000
MAX_EXIT_OWNER_FILES: Final = 2_000
MAX_EXIT_OWNER_FILE_BYTES: Final = 536_870_912
_DEFAULT = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ProgrammeExitApplications:
    """Complete declared reviewed-proposal owner scope for one exact edition.

    Attributes
    ----------
    organization_id, edition_id
        Independently authorized source scope, not user-selected inventory filters.
    departments
        Every retained call-owning Department, independently source-authorized.
    """

    organization_id: UUID = field(repr=False)
    edition_id: UUID = field(repr=False)
    departments: tuple[ProgrammeExitDepartment, ...] = field(repr=False)


def _inventory(
    organization_id: UUID, edition_id: UUID
) -> tuple[tuple[UUID, UUID], ...]:
    rows = tuple(
        ProgrammeCall.objects.filter(
            organization_id=organization_id, edition_id=edition_id
        )
        .order_by("id")
        .values_list("id", "owner_department_id")[: MAX_EXIT_CALLS + 1]
    )
    if len(rows) > MAX_EXIT_CALLS:
        raise ProgrammeReviewUnavailableError
    return rows


def _admit_sources(
    request: ProgrammeReviewReadRequest, authorizer: ApplicationsProgrammeAuthorizer
) -> None:
    if request.department_id is None:
        raise ProgrammeReviewUnavailableError
    authorize_programme_call_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        department_id=request.department_id,
        authorizer=authorizer,
    )
    _scope(request, authorizer)
    _scope(
        replace(
            request,
            capability_code=MANAGE_REVIEW,
            requested_fields=frozenset({"review_context", "review_setup"}),
        ),
        authorizer,
    )


def programme_exit_department_references(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> tuple[UUID, ...]:
    """Resolve opaque source-authorized Departments before any composer person lock.

    Parameters
    ----------
    actor_id : UUID
        Actual requester with independently checked owner and archive rights.
    organization_id : UUID
        Exact expected tenant.
    edition_id : UUID
        Exact source edition already held by the composer's canonical parent lock.
    correlation_id : UUID
        Server-generated collection trace, not a disclosure filter.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Independent Applications source authority.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional bulk-purpose admission.

    Returns
    -------
    tuple[UUID, ...]
        Sorted complete call-owning Department identifiers, never labels or counts.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If the retained complete Department closure exceeds the supported bound.

    Notes
    -----
    Internal composition reference only, not an HTTP listing. The caller holds
    the parent/edition fence until all owner reads complete. No person locks or
    child audits run here; the later complete owner read audits the actual output.
    """
    for value in (actor_id, organization_id, edition_id, correlation_id):
        require_programme_uuid(value, field="archive_scope")
    authorize_programme_archive_scope(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        requested_fields=frozenset({"source_lineage"}),
        authorizer=programme_authorizer,
    )
    departments = tuple(
        sorted(
            {
                department
                for _call, department in _inventory(organization_id, edition_id)
            }
        )
    )
    if len(departments) > MAX_EXIT_DEPARTMENTS:
        raise ProgrammeReviewUnavailableError
    for department in departments:
        _admit_sources(
            ProgrammeReviewReadRequest(
                actor_id,
                organization_id,
                edition_id,
                department,
                DECIDE,
                REVIEW_FIELDS,
                correlation_id,
                "programme-exit",
            ),
            authorizer,
        )
    return departments


@transaction.atomic
def load_programme_exit_applications(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeExitApplications:
    """Join all call-owning Departments after complete canonical Department locking.

    Parameters
    ----------
    actor_id : UUID
        Actual requester, never a borrowed contributor or background service person.
    organization_id : UUID
        Exact independently admitted tenant.
    edition_id : UUID
        Exact selected edition, without an optional partial Department filter.
    correlation_id : UUID
        Server-generated trace for all required sensitive owner reads.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT
        Independent current Applications purpose and source permissions.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional archive admission, never a substitute for owner fields.

    Returns
    -------
    ProgrammeExitApplications
        Complete bounded owner scope with purpose exclusions, or no result.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If inventory, closure, source coverage or aggregate resource bounds fail.

    Notes
    -----
    Identifier discovery is internal under the parent/edition fence; it releases
    no labels or private counts. All Departments precede any actor/audit lock.
    A full multi-owner composer must establish its larger closure first. No
    production profile, task, artifact or downloadable success is created here.
    """
    for name, value in (
        ("actor_id", actor_id),
        ("organization_id", organization_id),
        ("edition_id", edition_id),
        ("correlation_id", correlation_id),
    ):
        require_programme_uuid(value, field=name)

    def purpose() -> AuthorizedProgrammeScope:
        return authorize_programme_archive_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )

    purpose()
    lock_programme_staffing_scope(
        organization_id=organization_id, edition_id=edition_id
    )
    purpose()
    inventory = _inventory(organization_id, edition_id)
    department_ids = tuple(
        sorted({department_id for _call_id, department_id in inventory})
    )
    if len(department_ids) > MAX_EXIT_DEPARTMENTS:
        raise ProgrammeReviewUnavailableError
    requests = tuple(
        ProgrammeReviewReadRequest(
            actor_id,
            organization_id,
            edition_id,
            department_id,
            DECIDE,
            REVIEW_FIELDS,
            correlation_id,
            "programme-exit",
        )
        for department_id in department_ids
    )
    for request in requests:
        _admit_sources(request, authorizer)
    locked = lock_programme_edition_write_scope(
        organization_id=organization_id,
        edition_id=edition_id,
        department_ids=department_ids,
        actor_id=actor_id,
    )
    if locked.department_ids != department_ids:
        raise ProgrammeReviewUnavailableError
    departments = []
    case_count = entry_count = file_count = byte_count = 0
    collected: list[tuple[UUID, UUID]] = []
    for request in requests:
        _admit_sources(request, authorizer)
        department = load_programme_exit_department(
            request=request,
            authorizer=authorizer,
            programme_authorizer=programme_authorizer,
        )
        if department.configuration.department_id != request.department_id:
            raise ProgrammeReviewUnavailableError
        department_id = department.configuration.department_id
        collected.extend(
            (call.configuration.summary.call_id, department_id)
            for call in department.configuration.calls
        )
        case_count += len(department.cases)
        for case in department.cases:
            entry_count += len(case.review.evidence_lineage)
            file_count += len(case.files)
            byte_count += sum(len(file.data) for file in case.files)
        if (
            case_count > MAX_EXIT_OWNER_CASES
            or entry_count > MAX_EXIT_OWNER_ENTRIES
            or file_count > MAX_EXIT_OWNER_FILES
            or byte_count > MAX_EXIT_OWNER_FILE_BYTES
        ):
            raise ProgrammeReviewUnavailableError
        departments.append(department)
    if (
        tuple(sorted(collected)) != inventory
        or _inventory(organization_id, edition_id) != inventory
    ):
        raise ProgrammeReviewUnavailableError
    for request in requests:
        _admit_sources(request, authorizer)
    scope = purpose()
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code=PROGRAMME_EXPORT_ARCHIVE,
            operation="applications.programme.query.exit_owner",
            target_type="applications.programme_call.collection",
            target_id=edition_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="programme-exit",
            obligations=tuple(sorted(scope.decision.obligations)),
            retention_class="applications-programme-restricted",
        )
    )
    return ProgrammeExitApplications(organization_id, edition_id, tuple(departments))
