"""Independently authorized, label-free Workforce source for Programme staffing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.programme.inputs import canonical_digest
from maru.programme.staffing_inputs import ProgrammeStaffingExpectation

from .adoption import WORKFORCE_PROGRAMME_COVERAGE_ADAPTER
from .models import ShiftCommitment, ShiftDemand
from .programme_coverage import (
    StaffingCoverage,
    StaffingCoverageCounts,
    StaffingCoverageIntegrityError,
    StaffingSourceState,
    evaluate_staffing_coverage,
)
from .programme_references import lock_programme_staffing_scope
from .shift_queries import (
    MAX_SHIFT_COMMITMENTS,
    MAX_SHIFT_DEMANDS,
    _availability_is_current,
    _qualification_is_current,
    _with_availability_coverage,
)
from .structure_snapshot import repeatable_read_only_snapshot

if TYPE_CHECKING:
    from datetime import datetime

PROGRAMME_COVERAGE_FIELDS = frozenset(
    {"shift_demands", "coverage_states", "suitability_consequences"}
)


class ProgrammeCoverageDeniedError(RuntimeError):
    """Withhold source existence when independent coverage authority is absent."""


@dataclass(frozen=True, slots=True)
class ProgrammeDemandCoverage:
    """One minimized exact-demand dependency, not an authorization or binding.

    Attributes
    ----------
    demand_id
        Explicitly selected demand in the authorized edition.
    demand_version
        Exact current Workforce command version.
    position_id
        Exact work Position, without its holder labels.
    starts_at
        Inclusive accepted or draft work start.
    ends_at
        Exclusive accepted or draft work end.
    evidence_digest
        Digest of exact minimized owner versions and current suitability facts.
    coverage
        Coverage classification retaining unknown and underfill distinctions.
    """

    demand_id: UUID
    demand_version: int
    position_id: UUID
    starts_at: datetime
    ends_at: datetime
    evidence_digest: str
    coverage: StaffingCoverage


@dataclass(frozen=True, slots=True)
class ProgrammeBoundDemandCoverage:
    """Minimized work fingerprint and coverage from the same locked owner state.

    Attributes
    ----------
    demand
        Exact current demand, suitability digest and minimized coverage.
    work_terms_digest
        Exact work expectation fingerprint; no briefing or rationale is released.
    """

    demand: ProgrammeDemandCoverage
    work_terms_digest: str


def _authorize(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> PolicyDecision:
    decision = decide_verified_principal_exact_edition(
        principal_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        capability_code="workforce.view_shifts",
        requested_fields=PROGRAMME_COVERAGE_FIELDS,
    )
    if not decision.allowed or not decision.fields >= PROGRAMME_COVERAGE_FIELDS:
        raise ProgrammeCoverageDeniedError
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, WORKFORCE_PROGRAMME_COVERAGE_ADAPTER
    ):
        raise ProgrammeCoverageDeniedError
    return decision


def _identifiers(demand_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
    if (
        not isinstance(demand_ids, tuple)
        or not 1 <= len(demand_ids) <= MAX_SHIFT_DEMANDS
        or any(not isinstance(value, UUID) for value in demand_ids)
        or len(set(demand_ids)) != len(demand_ids)
    ):
        raise StaffingCoverageIntegrityError(
            "Use a complete bounded set of exact demand identifiers."
        )
    return tuple(sorted(demand_ids, key=str))


def authorize_programme_coverage(
    *, actor_id: UUID, organization_id: UUID, edition_id: UUID
) -> PolicyDecision:
    """Recheck the exact minimized coverage purpose without reading source rows.

    Parameters
    ----------
    actor_id : UUID
        Trusted current principal, independently verified by Workforce.
    organization_id : UUID
        Exact expected owner.
    edition_id : UUID
        Exact target edition whose profile must include the coverage adapter.

    Returns
    -------
    PolicyDecision
        Current field-aware decision, not portable authority for a later read.
    """
    return _authorize(
        actor_id=actor_id, organization_id=organization_id, edition_id=edition_id
    )


def _load_counts(
    *, organization_id: UUID, edition_id: UUID, demand_ids: tuple[UUID, ...]
) -> tuple[ProgrammeDemandCoverage, ...]:
    demands = tuple(
        ShiftDemand.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            id__in=demand_ids,
        )
        .only(
            "id",
            "organization_id",
            "edition_id",
            "position_id",
            "command_version",
            "starts_at",
            "ends_at",
            "status",
            "required_headcount",
        )
        .order_by("id")
    )
    if {d.id for d in demands} != set(demand_ids):
        raise StaffingCoverageIntegrityError(
            "Complete scoped staffing demand is unavailable."
        )
    rows = tuple(
        _with_availability_coverage(
            ShiftCommitment.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                demand_id__in=demand_ids,
            )
        )
        .select_related("demand", "position_assignment", "availability_plan")
        .only(
            "id",
            "organization_id",
            "edition_id",
            "demand_id",
            "account_id",
            "status",
            "command_version",
            "starts_at",
            "ends_at",
            "availability_version",
            "demand__id",
            "demand__position_id",
            "position_assignment__id",
            "position_assignment__account_id",
            "position_assignment__organization_id",
            "position_assignment__edition_id",
            "position_assignment__position_id",
            "position_assignment__command_version",
            "position_assignment__status",
            "position_assignment__effective_from",
            "position_assignment__expires_at",
            "availability_plan__id",
            "availability_plan__account_id",
            "availability_plan__organization_id",
            "availability_plan__edition_id",
            "availability_plan__command_version",
            "availability_plan__status",
        )
        .order_by("demand_id", "id")[: MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(rows) > MAX_SHIFT_COMMITMENTS:
        raise StaffingCoverageIntegrityError(
            "The complete staffing source exceeds its bound."
        )
    grouped: dict[UUID, list[ShiftCommitment]] = {d.id: [] for d in demands}
    for row in rows:
        grouped[row.demand_id].append(row)
    results = []
    for demand in demands:
        commitments = grouped[demand.id]
        claimed = confirmed = current = 0
        evidence: list[object] = [
            str(organization_id),
            str(edition_id),
            str(demand.id),
            demand.command_version,
        ]
        for row in commitments:
            assignment, plan = row.position_assignment, row.availability_plan
            if (
                row.starts_at != demand.starts_at
                or row.ends_at != demand.ends_at
                or assignment.organization_id != organization_id
                or plan.organization_id != organization_id
                or assignment.edition_id != edition_id
                or plan.edition_id != edition_id
                or assignment.account_id != row.account_id
                or plan.account_id != row.account_id
            ):
                raise StaffingCoverageIntegrityError(
                    "The staffing source contains inconsistent owner evidence."
                )
            availability = _availability_is_current(row)
            qualification = _qualification_is_current(row)
            claimed += row.status == ShiftCommitment.Status.CLAIMED
            confirmed += row.status == ShiftCommitment.Status.CONFIRMED
            current += (
                row.status == ShiftCommitment.Status.CONFIRMED
                and availability
                and qualification
            )
            evidence.append(
                (
                    str(row.id),
                    row.command_version,
                    plan.command_version,
                    assignment.command_version,
                    availability,
                    qualification,
                )
            )
        counts = StaffingCoverageCounts(
            demand.status,
            demand.required_headcount,
            claimed,
            confirmed,
            current,
            len(commitments),
        )
        coverage = evaluate_staffing_coverage(
            source_state=StaffingSourceState.CURRENT, counts=counts
        )
        results.append(
            ProgrammeDemandCoverage(
                demand.id,
                demand.command_version,
                demand.position_id,
                demand.starts_at,
                demand.ends_at,
                hashlib.sha256(
                    json.dumps(evidence, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                coverage,
            )
        )
    return tuple(results)


def load_programme_shift_coverage(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    demand_ids: tuple[UUID, ...],
    correlation_id: UUID,
) -> tuple[ProgrammeDemandCoverage, ...]:
    """Read complete minimized Workforce evidence behind an exact pinned adapter.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated person, independently authorized by Workforce.
    organization_id : UUID
        Exact organization expected to own the source.
    edition_id : UUID
        Exact edition expected to own every selected demand.
    demand_ids : tuple[UUID, ...]
        Complete distinct selection; parsed only after admission.
    correlation_id : UUID
        Trusted request correlation for mandatory sensitive-read evidence.

    Returns
    -------
    tuple[ProgrammeDemandCoverage, ...]
        Deterministically ordered exact-demand results without personnel data.

    Raises
    ------
    StaffingCoverageIntegrityError
        If scope or correlation identifiers are not typed UUIDs.

    Notes
    -----
    Both current profile manifests deliberately omit this adapter. Admission
    and post-snapshot authorization are independent of Programme authority.
    Missing, foreign or over-limit selections never return partial coverage.
    Audit failure propagates before any result is released. Consumers must
    compare the requirement and Scheduling source versions independently;
    this query neither establishes a binding nor approves Programme release.
    """
    if any(
        not isinstance(value, UUID)
        for value in (actor_id, organization_id, edition_id, correlation_id)
    ):
        raise StaffingCoverageIntegrityError(
            "Use typed staffing scope and correlation identifiers."
        )
    _authorize(
        actor_id=actor_id, organization_id=organization_id, edition_id=edition_id
    )
    identifiers = _identifiers(demand_ids)
    with repeatable_read_only_snapshot():
        _authorize(
            actor_id=actor_id, organization_id=organization_id, edition_id=edition_id
        )
        result = _load_counts(
            organization_id=organization_id,
            edition_id=edition_id,
            demand_ids=identifiers,
        )
    decision = _authorize(
        actor_id=actor_id, organization_id=organization_id, edition_id=edition_id
    )
    _audit_coverage(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=correlation_id,
        decision=decision,
    )
    return result


def _audit_coverage(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    decision: PolicyDecision,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor_id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="workforce.view_shifts",
            operation="workforce.programme_coverage.read",
            target_type="events.event_edition",
            target_id=edition_id,
            outcome="allow",
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel="service",
            obligations=tuple(
                sorted(set(decision.obligations) | {"audit_sensitive_read"})
            ),
            changed_fields=(),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-personal",
        ),
        occurred_at=timezone.now(),
    )


def load_programme_bound_demand_coverage(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    demand_ids: tuple[UUID, ...],
    correlation_id: UUID,
) -> tuple[ProgrammeBoundDemandCoverage, ...]:
    """Read exact work fingerprints and coverage under canonical composition locks.

    Parameters
    ----------
    actor_id : UUID
        Trusted current person, independently admitted by Workforce.
    organization_id : UUID
        Exact tenant owning every demand.
    edition_id : UUID
        Exact edition, locked before its owner aggregates.
    demand_ids : tuple[UUID, ...]
        Complete distinct bounded demand selection, parsed after admission.
    correlation_id : UUID
        Trusted trace identifier for the mandatory sensitive-read audit.

    Returns
    -------
    tuple[ProgrammeBoundDemandCoverage, ...]
        Complete exact work fingerprints and minimized coverage, never personnel.

    Raises
    ------
    StaffingCoverageIntegrityError
        If correlation or the complete scoped work evidence is unavailable.

    Notes
    -----
    This composable variant acquires the canonical owner lock chain and retains
    it until the surrounding transaction ends. A caller composing other owners
    must acquire that chain first. Unlike the standalone repeatable-read query,
    it internally reads explicit work terms to compute a fingerprint. Those
    terms never leave Workforce through this adapter. Ordinary demand lifecycle
    version changes do not change the work fingerprint. Private commitment
    reasons, holder labels and complete calendars are never selected.
    """
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    _authorize(**scope)
    if not isinstance(correlation_id, UUID):
        raise StaffingCoverageIntegrityError("Use a typed coverage correlation.")
    identifiers = _identifiers(demand_ids)
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        _authorize(**scope)
        demands = _load_counts(
            organization_id=organization_id,
            edition_id=edition_id,
            demand_ids=identifiers,
        )
        work_fields = tuple(
            field.name for field in fields(ProgrammeStaffingExpectation)
        )
        work_rows = ShiftDemand.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            id__in=identifiers,
        ).values("id", *work_fields)
        fingerprints = {
            row["id"]: canonical_digest(
                asdict(
                    ProgrammeStaffingExpectation(
                        **{field: row[field] for field in work_fields}
                    ).normalized()
                )
            )
            for row in work_rows
        }
        if set(fingerprints) != set(identifiers):
            raise StaffingCoverageIntegrityError("Complete bound work is unavailable.")
        result = tuple(
            ProgrammeBoundDemandCoverage(demand, fingerprints[demand.demand_id])
            for demand in demands
        )
        decision = _authorize(**scope)
        _audit_coverage(**scope, correlation_id=correlation_id, decision=decision)
        return result
