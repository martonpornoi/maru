"""Complete minimized Scheduling stop impact, with exact release withdrawal status."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.programme_stop_authorization import (
    require_programme_stop_controller,
)
from maru.authorization.services import AuthorizationDenied
from maru.events.programme_stop_inventory import (
    MAX_STOP_SOURCE_ROWS,
    ProgrammeStopInventory,
    ProgrammeStopMetadataSource,
    build_programme_stop_inventory,
)

from . import models
from .authorization import (
    WITHDRAW_RELEASE,
    SchedulingAuthorizationDeniedError,
    authorize_scheduling_scope,
)
from .readiness import scheduling_database_integrity_is_ready

# Direct edition inventory; global/shared dependency keys remain outside this scope.
STOP_METADATA_SOURCES = (
    ("SchedulingEditionControl", "", None, ("aggregate_version",)),
    ("SchedulingServiceDay", "", "lifecycle", ("aggregate_version",)),
    ("SchedulingServiceDayRevision", "", "lifecycle", ("sequence", "edition_version")),
    ("SchedulingOccurrence", "", "lifecycle", ("aggregate_version",)),
    ("SchedulingOccurrenceRevision", "", "lifecycle", ("sequence",)),
    ("SchedulingCandidate", "", "lifecycle", ("aggregate_version",)),
    ("SchedulingCandidateRevision", "", None, ("sequence", "placement_count")),
    ("SchedulingPlacementRevision", "", None, ("host_presence_count",)),
    ("SchedulingCandidateMember", "", None, ()),
    ("SchedulingPlacementHostPresence", "", None, ()),
    ("SchedulingEvaluation", "", None, ("conflict_count", "is_complete")),
    ("SchedulingConflict", "", "severity", ()),
    ("SchedulingWarningAcknowledgement", "", None, ()),
    ("SchedulingReservationIntent", "", None, ("expected_booking_version",)),
    ("SchedulingCommandReceipt", "", None, ("control_version", "resulting_version")),
    ("SchedulingChangeNotice", "", "source_state", ("pointer_version",)),
    ("SchedulingChangeNoticeEvidence", "", "action", ("sequence",)),
    ("SchedulingReleaseDependencyKey", "", None, ("generation",)),
    ("SchedulingReleaseDependencyChange", "", None, ("generation",)),
    ("SchedulingReleaseWarningAcknowledgement", "", None, ()),
    ("SchedulingReleaseApproval", "", None, ("placement_count", "dependency_count")),
    ("SchedulingReleaseApprovalPlacement", "", None, ()),
    ("SchedulingReleaseApprovalDependency", "", None, ("captured_generation",)),
    ("SchedulingRelease", "", None, ("pointer_version",)),
    ("SchedulingReleaseArtifact", "", None, ("byte_length",)),
    ("SchedulingReleaseWithdrawal", "", None, ("pointer_version",)),
    ("SchedulingReleasePointer", "", None, ("version", "active_release_id")),
)


@dataclass(frozen=True, slots=True)
class ProgrammeStopSchedulingImpact:
    """Expose exact pointer state separately from current withdrawal permission.

    Attributes
    ----------
    inventory
        Complete minimized edition-owned planning/output metadata.
    active_release_id, pointer_version
        Exact stored pointer, including an invalidated but not withdrawn release.
        Version zero means never published; a withdrawn pointer keeps its version.
    withdrawal_authorized
        Whether the actual stop requester currently has independent withdrawal
        permission. False with no active pointer means no withdrawal is needed.
    """

    inventory: ProgrammeStopInventory
    active_release_id: UUID | None
    pointer_version: int
    withdrawal_authorized: bool


def _withdrawal_is_authorized(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    active_release_id: UUID | None,
) -> bool:
    if active_release_id is None:
        return False
    try:
        authorize_scheduling_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code=WITHDRAW_RELEASE,
        )
    except SchedulingAuthorizationDeniedError:
        return False
    return True


def load_programme_stop_scheduling(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> ProgrammeStopSchedulingImpact:
    """Count retained planning and output evidence at the explicit stop ceiling.

    Parameters
    ----------
    actor_id : UUID
        Current ordinary accountable controller with Events transition authority.
    organization_id, edition_id : UUID
        Exact independently selected Programme context, never inferred from a file.
    correlation_id : UUID
        Trusted non-nil trace for mandatory minimized disclosure evidence.

    Returns
    -------
    ProgrammeStopSchedulingImpact
        Complete counts, source fingerprint and explicit current release pointer,
        without private planning labels, notices, hosts or artifact bytes.

    Raises
    ------
    ValidationError
        If the audit trace or native source integrity is unavailable.
    AuthorizationDenied
        If the actual controller lacks either independent stop prerequisite.

    Notes
    -----
    Overflow, source failure or audit failure returns no partial inventory. The
    composer must retain its outer canonical ownership/person transaction and
    rebuild this projection before stop. This purpose admits no source detail,
    export, review, retirement, withdrawal or payload-disposal command.
    """
    if type(correlation_id) is not UUID or not correlation_id.int:
        raise ValidationError("Use an exact audit trace.", code="programme_stop_trace")
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }

    def audit(*, allowed: bool) -> None:
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="events.transition",
                operation="scheduling.query.programme_stop",
                target_type="events.event_edition",
                target_id=edition_id if allowed else None,
                outcome="allow" if allowed else "deny",
                reason_code="programme_stop_impact"
                if allowed
                else "programme_stop_unavailable",
                correlation_id=correlation_id,
                source_channel="programme-stop",
                obligations=("audit_sensitive_read",),
                retention_class="programme-restricted",
            )
        )

    try:
        with transaction.atomic():
            require_programme_stop_controller(**scope)
            if not scheduling_database_integrity_is_ready():
                raise ValidationError(
                    "Programme stop source is unavailable.",
                    code="programme_stop_source",
                )

            def sources() -> Iterator[ProgrammeStopMetadataSource]:
                for name, parent, state_field, versions in STOP_METADATA_SOURCES:
                    model = getattr(models, name)
                    fields = (
                        "id",
                        "updated_at",
                        *((state_field,) if state_field else ()),
                        *versions,
                    )
                    rows = tuple(
                        model.objects.filter(
                            **{
                                f"{parent}organization_id": organization_id,
                                f"{parent}edition_id": edition_id,
                            }
                        )
                        .order_by("id")
                        .values_list(*fields)[: MAX_STOP_SOURCE_ROWS + 1]
                    )
                    yield (
                        ProgrammeStopMetadataSource(
                            name.lower(), fields, rows, state_field
                        )
                    )

            result = build_programme_stop_inventory(
                owner="scheduling",
                organization_id=organization_id,
                edition_id=edition_id,
                sources=sources(),
            )
            pointer = (
                models.SchedulingReleasePointer.objects.filter(
                    organization_id=organization_id, edition_id=edition_id
                )
                .values_list("active_release_id", "version")
                .first()
            )
            active_release_id, pointer_version = pointer or (None, 0)
            can_withdraw = _withdrawal_is_authorized(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                active_release_id=active_release_id,
            )
            require_programme_stop_controller(**scope)
            audit(allowed=True)
            return ProgrammeStopSchedulingImpact(
                result, active_release_id, pointer_version, can_withdraw
            )
    except AuthorizationDenied:
        audit(allowed=False)
        raise
