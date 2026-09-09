"""Exact-source Programme binding through existing, independently governed Shifts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_MANAGE_STAFFING,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from maru.programme.inputs import canonical_digest
from maru.programme.staffing_sources import (
    ProgrammeStaffingSelection,
    load_programme_staffing_selection,
)
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizer,
)

from .models import ProgrammeShiftBinding, ProgrammeShiftBindingRevision
from .programme_impact import (
    ProgrammeStaffingAction,
    ProgrammeStaffingDemandState,
    ProgrammeStaffingImpact,
    evaluate_programme_staffing_impact,
)
from .programme_references import (
    lock_programme_staffing_scope,
    resolve_staffing_position_reference,
)
from .programme_staffing_inputs import ProgrammeStaffingBindingChange
from .programme_staffing_queries import (
    ProgrammeStaffingUnavailableError,
    authorize_programme_staffing_adapter,
    load_programme_staffing_demand,
)
from .programme_staffing_writer import programme_staffing_writer
from .shift_commands import (
    ShiftDemandCommandResult,
    ShiftRetryConflictError,
    ShiftVersionConflictError,
    cancel_shift_demand,
    create_shift_demand,
    update_shift_demand,
)
from .shift_inputs import normalize_shift_reason

if TYPE_CHECKING:
    from maru.identity.models import Account
    from maru.programme.staffing_queries import ProgrammeStaffingReadRequest

    from .edition_write_scope import LockedWorkforceEditionWriteScope


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingBindingPreview:
    """Complete authorized work impact, never a portable mutation permission.

    Attributes
    ----------
    selection
        Exact current independently authorized Programme/Scheduling source.
    demand
        Current explicit work and aggregate retained decisions, absent for creation.
    impact
        Deliberate operation and effects on retained/active work decisions.
    digest
        Actor/scope/source/work/version fingerprint to compare at commit.
    """

    selection: ProgrammeStaffingSelection
    demand: ProgrammeStaffingDemandState | None
    impact: ProgrammeStaffingImpact
    digest: str


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingBindingResult:
    """Return immutable command identity without private source or personnel content.

    Attributes
    ----------
    binding_id
        Stable requirement-to-work lineage.
    revision_id
        Exact immutable source revision and retry receipt.
    binding_version
        Resulting retained binding version.
    demand_id
        Exact linked or newly created draft demand.
    demand_version
        Workforce version at the original binding, not a later current-state claim.
    replayed
        Whether current authority returned a matching retained command result.
    """

    binding_id: UUID
    revision_id: UUID
    binding_version: int
    demand_id: UUID
    demand_version: int
    replayed: bool


def _admit(
    request: ProgrammeStaffingReadRequest, policy: ProgrammeAuthorizer, *, write: bool
) -> None:
    authorize_programme_staffing_adapter(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        purpose="write" if write else "read",
    )
    authorize_programme_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=PROGRAMME_MANAGE_STAFFING if write else PROGRAMME_VIEW_STAFFING,
        requested_fields=None if write else frozenset({"staffing_requirements"}),
        authorizer=policy,
    )


def _validate_request(request: ProgrammeStaffingReadRequest) -> None:
    if (
        any(
            not isinstance(value, UUID)
            for value in (
                request.actor_id,
                request.organization_id,
                request.edition_id,
                request.item_id,
                request.correlation_id,
            )
        )
        or not isinstance(request.source_channel, str)
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", request.source_channel) is None
    ):
        raise ValidationError(
            "Use exact staffing scope and trusted command attribution."
        )


def _binding(
    request: ProgrammeStaffingReadRequest, change: ProgrammeStaffingBindingChange
) -> ProgrammeShiftBinding | None:
    current = (
        ProgrammeShiftBinding.objects.select_for_update()
        .filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            requirement_id=change.source.requirement_id,
        )
        .first()
    )
    if change.binding_id is None:
        if current is not None:
            raise ShiftVersionConflictError(
                "The requirement already has retained work lineage."
            )
    elif current is None or (
        current.id,
        current.version,
        current.item_id,
        current.occurrence_id,
        current.demand_id,
    ) != (
        change.binding_id,
        change.expected_binding_version,
        request.item_id,
        change.source.occurrence_id,
        change.demand_id,
    ):
        raise ShiftVersionConflictError("Reload the exact current staffing binding.")
    return current


def _resolve(
    request: ProgrammeStaffingReadRequest,
    change: ProgrammeStaffingBindingChange,
    programme_authorizer: ProgrammeAuthorizer,
    scheduling_authorizer: SchedulingAuthorizer,
) -> ProgrammeStaffingBindingPreview:
    _admit(request, programme_authorizer, write=False)
    selection = load_programme_staffing_selection(
        request,
        source=change.source,
        programme_authorizer=programme_authorizer,
        scheduling_authorizer=scheduling_authorizer,
    )
    current = _binding(request, change)
    position = resolve_staffing_position_reference(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        position_id=selection.expectation.position_id,
    )
    if position is None or not position.accepts_staffing:
        raise ProgrammeStaffingUnavailableError
    demand = None
    if change.demand_id is not None:
        demand = load_programme_staffing_demand(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            demand_id=change.demand_id,
            correlation_id=request.correlation_id,
        )
        if demand.version != change.expected_demand_version:
            raise ShiftVersionConflictError("Reload the current work impact.")
        if current is None and (
            ProgrammeShiftBinding.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                demand_id=change.demand_id,
            ).exists()
            or ProgrammeShiftBindingRevision.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                demand_id=change.demand_id,
            ).exists()
        ):
            raise ProgrammeStaffingUnavailableError
    impact = evaluate_programme_staffing_impact(
        action=change.action, expectation=selection.expectation, demand=demand
    )
    _admit(request, programme_authorizer, write=False)
    digest = canonical_digest(
        {
            "actor_id": request.actor_id,
            "organization_id": request.organization_id,
            "edition_id": request.edition_id,
            "item_id": request.item_id,
            "change": asdict(change),
            "source": selection.evidence_digest,
            "demand": asdict(demand) if demand is not None else None,
            "impact": asdict(impact),
        }
    )
    return ProgrammeStaffingBindingPreview(selection, demand, impact, digest)


def preview_programme_staffing_binding(
    request: ProgrammeStaffingReadRequest,
    *,
    change: ProgrammeStaffingBindingChange,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeStaffingBindingPreview:
    """Preview one explicit exact-source action with independent read authority.

    Parameters
    ----------
    request : ProgrammeStaffingReadRequest
        Current trusted actor, exact scope and read-audit attribution.
    change : ProgrammeStaffingBindingChange
        Explicit source, operation and optimistic binding/demand identities.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent Programme work-field policy.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent policy for the explicitly selected private alternative.

    Returns
    -------
    ProgrammeStaffingBindingPreview
        Complete work impact or an exception; never a partial or implicit selection.

    Raises
    ------
    ValidationError
        If the supplied change is not an explicit typed binding intent.

    Notes
    -----
    This operation writes only mandatory read-audit evidence. The returned token
    proves neither user review nor authority. Apply resolves all sources again,
    checks both mutation authorities and compares the complete current impact.
    """
    _admit(request, programme_authorizer, write=False)
    _validate_request(request)
    if not isinstance(change, ProgrammeStaffingBindingChange):
        raise ValidationError("Use an explicit typed staffing change.")
    change.validated()
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        return _resolve(request, change, programme_authorizer, scheduling_authorizer)


class _ShiftAttribution(TypedDict):
    actor: Account
    organization_id: UUID
    series_id: UUID
    edition_id: UUID
    reason: str
    retry_key: UUID
    correlation_id: UUID
    source_channel: str


def _change_work(
    actor: Account,
    scope: LockedWorkforceEditionWriteScope,
    request: ProgrammeStaffingReadRequest,
    change: ProgrammeStaffingBindingChange,
    preview: ProgrammeStaffingBindingPreview,
    reason: str,
    retry_key: UUID,
) -> tuple[UUID, int, ShiftDemandCommandResult | None, ShiftDemandCommandResult | None]:
    attribution: _ShiftAttribution = {
        "actor": actor,
        "organization_id": scope.organization_id,
        "series_id": scope.series_id,
        "edition_id": scope.edition_id,
        "reason": reason,
        "retry_key": uuid5(retry_key, "programme-binding:work"),
        "correlation_id": request.correlation_id,
        "source_channel": request.source_channel,
    }
    if change.action == ProgrammeStaffingAction.LINK:
        if preview.demand is None:
            raise ProgrammeStaffingUnavailableError
        return preview.demand.demand_id, preview.demand.version, None, None
    cancellation = None
    if preview.impact.cancel_predecessor:
        cancellation = cancel_shift_demand(
            **{
                **attribution,
                "retry_key": uuid5(retry_key, "programme-binding:cancel"),
            },
            demand_id=change.demand_id,
            expected_version=change.expected_demand_version,
        )
    terms = asdict(preview.selection.expectation)
    if change.action == ProgrammeStaffingAction.RECONCILE:
        if change.demand_id is None:
            raise ProgrammeStaffingUnavailableError
        terms.pop("position_id")
        result = update_shift_demand(
            **attribution,
            demand_id=change.demand_id,
            expected_version=change.expected_demand_version,
            **terms,
        )
    else:
        result = create_shift_demand(**attribution, **terms)
    return result.demand_id, result.resulting_version, result, cancellation


def _result(
    revision: ProgrammeShiftBindingRevision, *, replayed: bool
) -> ProgrammeStaffingBindingResult:
    return ProgrammeStaffingBindingResult(
        revision.binding_id,
        revision.id,
        revision.sequence,
        revision.demand_id,
        revision.demand_version,
        replayed,
    )


def _record(
    request: ProgrammeStaffingReadRequest,
    change: ProgrammeStaffingBindingChange,
    preview: ProgrammeStaffingBindingPreview,
    *,
    demand_id: UUID,
    demand_version: int,
    shift_receipt: ShiftDemandCommandResult | None,
    cancellation: ShiftDemandCommandResult | None,
    reason: str,
    retry_key: UUID,
    request_digest: str,
) -> ProgrammeStaffingBindingResult:
    binding = _binding(request, change)
    version = change.expected_binding_version + 1
    if binding is None:
        binding = ProgrammeShiftBinding.objects.create(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            requirement_id=change.source.requirement_id,
            item_id=request.item_id,
            occurrence_id=change.source.occurrence_id,
            demand_id=demand_id,
            version=version,
            last_modified_by_id=request.actor_id,
        )
    else:
        binding.demand_id = demand_id
        binding.version = version
        binding.last_modified_by_id = request.actor_id
        binding.save()
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code="workforce.manage_shifts",
            operation=f"workforce.programme_binding.{change.action.value}",
            target_type="workforce.programme_binding",
            target_id=binding.id,
            outcome="allow",
            reason_code="explicit_staffing_binding",
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel=request.source_channel,
            obligations=("audit", "reason"),
            changed_fields=("source_binding",),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-restricted",
        ),
        occurred_at=timezone.now(),
    )
    event, _outbox = publish_domain_event(
        DomainEventRecord(
            event_name="workforce.programme_staffing.changed.v1",
            schema_version=1,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            aggregate_type="workforce.programme_binding",
            aggregate_id=binding.id,
            aggregate_version=version,
            payload={"action": change.action.value},
            correlation_id=request.correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=request.actor_id,
            retention_class="workforce-restricted",
        ),
        workload_pool="core",
    )
    revision = ProgrammeShiftBindingRevision.objects.create(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        binding=binding,
        sequence=version,
        requirement_revision_id=change.source.requirement_revision_id,
        requirement_version=change.source.requirement_version,
        occurrence_version=change.source.occurrence_version,
        candidate_id=change.source.candidate_id,
        candidate_revision_id=change.source.candidate_revision_id,
        placement_id=change.source.placement_id,
        demand_id=demand_id,
        demand_version=demand_version,
        predecessor_id=change.demand_id
        if change.action == ProgrammeStaffingAction.SUCCESSOR
        else None,
        operation=change.action.value,
        work_terms_digest=canonical_digest(asdict(preview.selection.expectation)),
        source_digest=preview.selection.evidence_digest,
        preview_digest=preview.digest,
        actor_id=request.actor_id,
        reason=reason,
        retry_key=retry_key,
        request_digest=request_digest,
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
        shift_receipt_id=shift_receipt.receipt_id if shift_receipt else None,
        cancellation_receipt_id=cancellation.receipt_id if cancellation else None,
        audit_event_id=audit.id,
        domain_event_id=event.id,
    )
    return _result(revision, replayed=False)


def apply_programme_staffing_binding(
    actor: Account,
    request: ProgrammeStaffingReadRequest,
    *,
    change: ProgrammeStaffingBindingChange,
    preview_digest: str,
    reason: str,
    retry_key: UUID,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeStaffingBindingResult:
    """Bind exact work atomically without transferring or reconfirming commitments.

    Parameters
    ----------
    actor : Account
        Trusted authenticated actor passed to existing Workforce commands.
    request : ProgrammeStaffingReadRequest
        Exact actor/scope and trusted evidence attribution; actor IDs must agree.
    change : ProgrammeStaffingBindingChange
        Deliberately selected operation, source and optimistic current versions.
    preview_digest : str
        Exact authorized impact token; recomputed under canonical locks.
    reason : str
        Explicit Workforce-visible rationale, including any successor cancellation.
    retry_key : UUID
        Actor/edition-bound key; matching retries retain original result identity.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Current independent Programme mutation and source-read policy.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent current read policy for the selected private alternative.

    Returns
    -------
    ProgrammeStaffingBindingResult
        Original immutable receipt and target work identity, not current coverage.

    Raises
    ------
    ValidationError
        If trusted attribution, retry identity or preview token is malformed.
    ShiftRetryConflictError
        If the retry key was retained for different exact intent.
    ShiftVersionConflictError
        If current source, work or retained-decision impact no longer matches.

    Notes
    -----
    All owner effects, binding history, audit and outbox work commit together.
    A successor cancels only through Workforce, preserves the old demand and
    every decision, and creates a separate draft without copied commitments.
    Neither success nor replay activates a profile, opens claims or locks work.
    """
    _admit(request, programme_authorizer, write=True)
    _admit(request, programme_authorizer, write=False)
    _validate_request(request)
    if not isinstance(change, ProgrammeStaffingBindingChange):
        raise ValidationError("Use an explicit typed staffing change.")
    change.validated()
    reason = normalize_shift_reason(reason)
    if (
        actor.id != request.actor_id
        or not isinstance(retry_key, UUID)
        or not isinstance(preview_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", preview_digest) is None
    ):
        raise ValidationError("Use exact actor, retry and preview evidence.")
    digest = canonical_digest(
        {
            "item_id": request.item_id,
            "change": asdict(change),
            "preview_digest": preview_digest,
            "reason": reason,
            "source_channel": request.source_channel,
        }
    )
    with transaction.atomic(), programme_staffing_writer():
        scope = lock_programme_staffing_scope(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        _admit(request, programme_authorizer, write=True)
        replay = ProgrammeShiftBindingRevision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            actor_id=request.actor_id,
            retry_key=retry_key,
        ).first()
        if replay is not None:
            _admit(request, programme_authorizer, write=False)
            if replay.request_digest != digest:
                raise ShiftRetryConflictError
            return _result(replay, replayed=True)
        preview = _resolve(request, change, programme_authorizer, scheduling_authorizer)
        if preview.digest != preview_digest:
            raise ShiftVersionConflictError(
                "The staffing impact changed; review a fresh preview."
            )
        _admit(request, programme_authorizer, write=True)
        demand_id, demand_version, receipt, cancellation = _change_work(
            actor, scope, request, change, preview, reason, retry_key
        )
        _admit(request, programme_authorizer, write=True)
        return _record(
            request,
            change,
            preview,
            demand_id=demand_id,
            demand_version=demand_version,
            shift_receipt=receipt,
            cancellation=cancellation,
            reason=reason,
            retry_key=retry_key,
            request_digest=digest,
        )
