"""Exact retained Workforce obligations, without person calendars or documents."""

from collections.abc import Iterator
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
from maru.events.programme_stop_readiness import programme_stop_preparation_is_ready

from . import models
from .programme_starter_readiness import programme_starter_database_integrity_is_ready

# Literal edition-owned metadata only; shared catalogs remain independent.
STOP_METADATA_SOURCES = (
    ("ProgrammeStarterRequest", "", None, ("definition_version", "approval_deadline")),
    ("ProgrammeStarterDecision", "request__", "action", ()),
    ("Department", "", None, ("last_changed_in_structure_version", "retired_at")),
    ("EditionStructureControl", "", None, ("aggregate_version",)),
    ("EditionStructureCommandReceipt", "", None, ("resulting_version",)),
    ("OnboardingDocumentType", "", "status", ("version",)),
    ("Position", "", "status", ("last_changed_in_structure_version",)),
    ("PositionDocumentRequirement", "position__", None, ()),
    (
        "VolunteerOpportunity",
        "position__",
        "status",
        ("last_changed_in_structure_version",),
    ),
    ("VolunteerApplication", "opportunity__position__", "status", ()),
    ("OnboardingDocumentRequest", "", "status", ()),
    (
        "PositionAssignment",
        "",
        "status",
        ("command_version", "effective_from", "expires_at"),
    ),
    ("PositionAssignmentCommandReceipt", "", None, ("resulting_version",)),
    ("PersonAvailabilityPlan", "", "status", ("command_version", "window_count")),
    ("PersonAvailabilityWindow", "plan__", None, ("created_by_version",)),
    (
        "PersonAvailabilityCommandReceipt",
        "",
        "resulting_status",
        ("resulting_version", "window_count"),
    ),
    (
        "ShiftDemand",
        "",
        "status",
        ("command_version", "required_headcount", "locked_headcount"),
    ),
    ("ShiftDemandCommandReceipt", "", "resulting_status", ("resulting_version",)),
    ("ShiftCommitment", "", "status", ("command_version", "availability_version")),
    ("ShiftCommitmentCommandReceipt", "", "resulting_status", ("resulting_version",)),
    ("ProgrammeShiftBinding", "", None, ("version",)),
    (
        "ProgrammeShiftBindingRevision",
        "",
        None,
        ("sequence", "requirement_version", "occurrence_version", "demand_version"),
    ),
)


def load_programme_stop_workforce(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> ProgrammeStopInventory:
    """Count retained workforce obligations without operational or private access.

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
    ProgrammeStopInventory
        Complete counts and metadata fingerprint, without row identities, private
        labels, people, reasons, contact details, calendars or document bytes.

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
                operation="workforce.query.programme_stop",
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
            if not (
                programme_starter_database_integrity_is_ready()
                and programme_stop_preparation_is_ready()
            ):
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
                owner="workforce",
                organization_id=organization_id,
                edition_id=edition_id,
                sources=sources(),
            )
            require_programme_stop_controller(**scope)
            audit(allowed=True)
            return result
    except AuthorizationDenied:
        audit(allowed=False)
        raise
