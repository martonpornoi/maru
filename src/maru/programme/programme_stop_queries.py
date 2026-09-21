"""Complete minimized Programme stop impact, including bounded archive custody."""

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

from . import models
from .readiness import programme_database_integrity_is_ready

# Literal owner inventory includes independently governed archive custody.
STOP_METADATA_SOURCES = (
    ("ProgrammeEditionControl", "", None, ("aggregate_version",)),
    ("ProgrammeItem", "", "lifecycle", ("aggregate_version",)),
    ("ProgrammeItemSourceBinding", "", None, ("source_version",)),
    ("ProgrammeWorkingRevision", "", None, ("sequence", "item_version")),
    ("ProgrammeDeliveryRevision", "", None, ("sequence", "item_version")),
    ("ProgrammeDepartmentDiscussionEntry", "", None, ("sequence", "item_version")),
    (
        "ProgrammeReadinessRequirement",
        "",
        "disposition",
        ("requirement_version", "dependency_version", "item_version"),
    ),
    (
        "ProgrammeReadinessRequirementRevision",
        "",
        "disposition",
        ("sequence", "item_version"),
    ),
    (
        "ProgrammeReadinessEvidence",
        "",
        "state",
        ("sequence", "item_version", "requirement_version", "dependency_version"),
    ),
    ("ProgrammePublicRendition", "", None, ("rendition_number", "source_item_version")),
    ("ProgrammePublicRenditionWithdrawal", "", None, ("item_version",)),
    (
        "ProgrammeCommandReceipt",
        "",
        None,
        ("resulting_control_version", "resulting_item_version"),
    ),
    (
        "ProgrammeHostRelationship",
        "",
        "state",
        ("version", "availability_state", "availability_version", "item_version"),
    ),
    ("ProgrammeHostInvitation", "", None, ("sequence", "host_version", "item_version")),
    (
        "ProgrammeHostRevision",
        "",
        "state",
        ("sequence", "availability_state", "availability_version", "period_count"),
    ),
    ("ProgrammeHostAvailabilityWindow", "", None, ("starts_at", "ends_at")),
    ("ProgrammeStaffingRequirement", "", "lifecycle", ("version", "item_version")),
    (
        "ProgrammeStaffingRevision",
        "",
        "lifecycle",
        ("sequence", "item_version", "occurrence_version"),
    ),
    ("ProgrammePlacementDecision", "", "state", ("sequence", "item_version")),
    (
        "ProgrammeArchiveTask",
        "",
        "state",
        ("version", "expires_at", "artifact_bytes", "chunk_count"),
    ),
    ("ProgrammeArchiveTaskEvent", "task__", "state", ("version",)),
    ("ProgrammeArchiveChunk", "task__", None, ("sequence", "size_bytes")),
)


def load_programme_stop_content(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> ProgrammeStopInventory:
    """Count content, hosting, staffing and archive custody without private text.

    Parameters
    ----------
    actor_id : UUID
        Current ordinary accountable controller with Events transition authority.
    organization_id : UUID
        Exact explicitly selected tenant, never discovered through private records.
    edition_id : UUID
        Exact independently selected Programme context, never inferred from a file.
    correlation_id : UUID
        Trusted non-nil trace for mandatory minimized disclosure evidence.

    Returns
    -------
    ProgrammeStopInventory
        Complete counts and metadata fingerprint, without row identities,
        working/delivery text, host identities, briefings, public copy or bytes.

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
    rebuild this projection before stop. Stored states are not effective permission
    or artifact availability. This
    purpose admits no content detail, archive download, host response or command.
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
                operation="programme.query.programme_stop",
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
            if not programme_database_integrity_is_ready():
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
                owner="programme",
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
