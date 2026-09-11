"""Complete retained work dependencies; retirement never erases volunteer work."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, TypedDict

from django.db import transaction
from django.db.models import Count, F, Max, Min
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.inputs import canonical_digest, require_uuid
from maru.programme.staffing_inputs import MAX_STAFFING_REQUIREMENTS_PER_ITEM
from maru.programme.staffing_queries import (
    ProgrammeStaffingReadRequest,
    load_programme_staffing_requirements,
)
from maru.scheduling.staffing_references import resolve_staffing_occurrence_reference

from .adoption import WORKFORCE_PROGRAMME_RELEASE_SOURCE_ADAPTER
from .models import ProgrammeShiftBinding, ProgrammeShiftBindingRevision, ShiftDemand
from .programme_references import lock_programme_staffing_scope
from .programme_staffing_queries import ProgrammeStaffingUnavailableError
from .shift_queries import MAX_SHIFT_DEMANDS

if TYPE_CHECKING:
    from uuid import UUID

    from maru.programme.placement_queries import ProgrammePlacementReadRequest

RELEASE_FIELDS = frozenset({"programme_release_consequences"})


class ProgrammeReleaseSourceDeniedError(RuntimeError):
    """Withhold release-source existence without independent Workforce authority."""


class _BindingRow(TypedDict):
    id: UUID
    version: int
    requirement_id: UUID
    demand_id: UUID


class _DemandRow(TypedDict):
    id: UUID
    command_version: int
    status: str


@dataclass(frozen=True, slots=True)
class ProgrammeRetainedWorkSource:
    """Current applicability with complete retained demand identity, not approval.

    Attributes
    ----------
    occurrence_id
        Exact independently resolved Programme occurrence.
    item_version
        Current Programme owner version used for the inventory.
    occurrence_version
        Current Scheduling occurrence metadata version.
    active_requirement_ids
        Every active requirement for this occurrence, including unbound needs.
    demand_ids
        Every retained bound demand, including predecessor and closed work.
    operative_demand_ids
        Retained demands not cancelled or completed; never silently filtered out.
    evidence_digest
        Complete current inventory, binding history-head and demand-version proof.
    """

    occurrence_id: UUID
    item_version: int
    occurrence_version: int
    active_requirement_ids: tuple[UUID, ...]
    demand_ids: tuple[UUID, ...]
    operative_demand_ids: tuple[UUID, ...]
    evidence_digest: str


def _authorize(
    request: ProgrammeStaffingReadRequest | ProgrammePlacementReadRequest,
    *,
    fields: frozenset[str] = RELEASE_FIELDS,
) -> PolicyDecision:
    decision = decide_verified_principal_exact_edition(
        principal_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code="workforce.view_shifts",
        requested_fields=fields,
    )
    profile = edition_adoption_profile_reference(
        organization_id=request.organization_id, edition_id=request.edition_id
    )
    if (
        not decision.allowed
        or not decision.fields >= fields
        or profile is None
        or not profile_allows_adapter(
            profile.code, profile.version, WORKFORCE_PROGRAMME_RELEASE_SOURCE_ADAPTER
        )
    ):
        raise ProgrammeReleaseSourceDeniedError
    return decision


def authorize_programme_release_source(
    request: ProgrammeStaffingReadRequest | ProgrammePlacementReadRequest,
) -> PolicyDecision:
    """Recheck retained-work/person disclosure without rereading private rows.

    Parameters
    ----------
    request : ProgrammeStaffingReadRequest | ProgrammePlacementReadRequest
        Trusted actor and exact tenant/edition whose release-source field is needed.

    Returns
    -------
    PolicyDecision
        Fresh independently ceilinged Workforce decision, never portable authority.
    """
    return _authorize(request)


def _audit(request: ProgrammeStaffingReadRequest, decision: PolicyDecision) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code="workforce.view_shifts",
            operation="workforce.programme_release.retained_work",
            target_type="programme.item",
            target_id=request.item_id,
            outcome="allow",
            reason_code=decision.reason_code,
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel="service",
            obligations=tuple(
                sorted(set(decision.obligations) | {"audit_sensitive_read"})
            ),
            changed_fields=(),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-restricted",
        ),
        occurred_at=timezone.now(),
    )


def _retained_demands(
    request: ProgrammeStaffingReadRequest,
    occurrence_id: UUID,
    requirement_ids: set[UUID],
) -> tuple[list[_BindingRow], list[_DemandRow]]:
    bindings = list(
        ProgrammeShiftBinding.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id=request.item_id,
            occurrence_id=occurrence_id,
        )
        .order_by("id")
        .values("id", "version", "requirement_id", "demand_id")[
            : MAX_STAFFING_REQUIREMENTS_PER_ITEM + 1
        ]
    )
    if len(bindings) > MAX_STAFFING_REQUIREMENTS_PER_ITEM or any(
        row["requirement_id"] not in requirement_ids for row in bindings
    ):
        raise ProgrammeStaffingUnavailableError
    revisions = ProgrammeShiftBindingRevision.objects.filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        binding_id__in=[row["id"] for row in bindings],
    ).order_by()
    histories = {
        row["binding_id"]: row
        for row in revisions.values("binding_id").annotate(
            count=Count("id"), first=Min("sequence"), last=Max("sequence")
        )
    }
    heads = dict(
        revisions.filter(sequence=F("binding__version")).values_list(
            "binding_id", "demand_id"
        )
    )
    for binding in bindings:
        history = histories.get(binding["id"])
        if (
            history is None
            or history["first"] != 1
            or history["last"] != binding["version"]
            or history["count"] != binding["version"]
            or heads.get(binding["id"]) != binding["demand_id"]
        ):
            raise ProgrammeStaffingUnavailableError
    identifiers = tuple(
        revisions.values_list("demand_id", flat=True)
        .union(
            revisions.exclude(predecessor_id=None).values_list(
                "predecessor_id", flat=True
            )
        )
        .order_by("demand_id")[: MAX_SHIFT_DEMANDS + 1]
    )
    if len(identifiers) > MAX_SHIFT_DEMANDS:
        raise ProgrammeStaffingUnavailableError
    demands = list(
        ShiftDemand.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            id__in=identifiers,
        )
        .order_by("id")
        .values("id", "command_version", "status")
    )
    if {row["id"] for row in demands} != set(identifiers):
        raise ProgrammeStaffingUnavailableError
    return bindings, demands


def load_programme_retained_work_source(
    request: ProgrammeStaffingReadRequest,
    *,
    occurrence_id: UUID,
    authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeRetainedWorkSource:
    """Resolve complete staffing applicability under independent owner authority.

    Parameters
    ----------
    request : ProgrammeStaffingReadRequest
        Exact item scope and trusted sensitive-read attribution.
    occurrence_id : UUID
        Explicit occurrence, independently checked against the item before absence.
    authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Real Programme field policy; existing isolated-test replacement only.

    Returns
    -------
    ProgrammeRetainedWorkSource
        Complete minimized current and historical work dependencies, not a decision.

    Raises
    ------
    ProgrammeStaffingUnavailableError
        If exact occurrence ownership or the complete bounded source is unavailable.

    Notes
    -----
    Current profiles omit this exact adapter. This reader neither cancels work nor
    infers a no-staffing decision. It checks complete immutable history membership
    using aggregates and reads at most the bounded distinct demand set, not private
    binding reasons or work copy. Shared parent locks serialize owner changes;
    any later publication must repeat collection. Missing or foreign occurrences,
    incomplete history, excess bounds and audit failure never return empty success.
    """
    for field in (
        "actor_id",
        "organization_id",
        "edition_id",
        "item_id",
        "correlation_id",
    ):
        require_uuid(getattr(request, field), field=field)

    def admit() -> PolicyDecision:
        decision = _authorize(request)
        authorize_programme_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=PROGRAMME_VIEW_STAFFING,
            requested_fields=frozenset({"staffing_requirements"}),
            authorizer=authorizer,
        )
        return decision

    admit()
    require_uuid(occurrence_id, field="occurrence_id")
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        admit()
        occurrence = resolve_staffing_occurrence_reference(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            item_id=request.item_id,
            occurrence_id=occurrence_id,
        )
        if occurrence is None:
            raise ProgrammeStaffingUnavailableError
        overview = load_programme_staffing_requirements(request, authorizer=authorizer)
        requirements = tuple(
            row for row in overview.requirements if row.occurrence_id == occurrence_id
        )
        bindings, demands = _retained_demands(
            request, occurrence_id, {row.requirement_id for row in requirements}
        )
        result = ProgrammeRetainedWorkSource(
            occurrence_id,
            overview.item_version,
            occurrence.version,
            tuple(
                row.requirement_id for row in requirements if row.lifecycle == "active"
            ),
            tuple(row["id"] for row in demands),
            tuple(
                row["id"]
                for row in demands
                if row["status"] not in {"cancelled", "completed"}
            ),
            canonical_digest(
                {
                    "schema": "programme-retained-work@1",
                    "organization_id": request.organization_id,
                    "edition_id": request.edition_id,
                    "item_id": request.item_id,
                    "item_version": overview.item_version,
                    "item_lifecycle": overview.item_lifecycle,
                    "occurrence": asdict(occurrence),
                    "requirements": tuple(asdict(row) for row in requirements),
                    "bindings": bindings,
                    "demands": demands,
                }
            ),
        )
        _audit(request, admit())
        return result
