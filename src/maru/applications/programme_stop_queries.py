"""Complete minimized Applications stop impact, without answer or file access."""

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
from .readiness import applications_database_integrity_is_ready

# Literal owner inventory. Fields never expand automatically with model metadata.
# Each row names (model, exact parent path, closed state, additional source versions).
STOP_METADATA_SOURCES = (
    ("ApplicationDefinition", "", "status", ("aggregate_version", "version")),
    ("ApplicationOwnerDepartment", "definition__", None, ("department_id",)),
    ("ApplicationReviewerRole", "definition__", None, ()),
    ("ApplicationReviewerPerson", "definition__", None, ()),
    ("ApplicationSection", "definition__", None, ()),
    ("ApplicationQuestion", "definition__", None, ()),
    ("ApplicationSubmission", "", "state", ("aggregate_version",)),
    ("ApplicationFileReceipt", "", "status", ()),
    (
        "ApplicationAnswerRevision",
        "submission__",
        None,
        ("sequence", "resulting_version"),
    ),
    ("ApplicationReviewDecision", "submission__", None, ("sequence",)),
    ("ApplicationTargetRecord", "submission__", None, ()),
    ("ApplicationCommandReceipt", "", None, ("resulting_version",)),
    ("ProgrammeCall", "", None, ("definition_id", "owner_department_id")),
    ("ProgrammeCallTrack", "", None, ()),
    ("ProgrammeCallFormat", "", None, ()),
    ("ProgrammeCallContributorField", "", None, ()),
    ("ProgrammeProposal", "", "state", ("sealed_revision_id", "submitted_revision_id")),
    ("ProgrammeProposalSelectionRevision", "", None, ("sequence", "resulting_version")),
    ("ProgrammeProposalCollaborator", "", "state", ("generation", "invite_expires_at")),
    (
        "ProgrammeProposalCollaboratorTransition",
        "",
        None,
        ("sequence", "resulting_version"),
    ),
    (
        "ProgrammeProposalContributorProfileRevision",
        "",
        None,
        ("sequence", "resulting_version"),
    ),
    ("ProgrammeProposalRevision", "", None, ("sequence", "resulting_version")),
    ("ProgrammeProposalRevisionAnswer", "", None, ()),
    ("ProgrammeProposalRevisionContributor", "", None, ()),
    ("ProgrammeProposalRevisionResponse", "", None, ("resulting_version",)),
    ("ProgrammeCommandReceipt", "", None, ("resulting_version",)),
    ("ProgrammeImportBatch", "", "state", ("aggregate_version", "expires_at")),
    ("ProgrammeImportItem", "", "state", ("aggregate_version",)),
    ("ProgrammeImportPreviewRevision", "", None, ("revision_number",)),
    ("ProgrammeImportPreviewItemResult", "", "status", ("item_version",)),
    ("ProgrammeImportSourceBinding", "", None, ()),
    ("ProgrammeImportAppliedCommand", "", None, ("sequence",)),
    ("ProgrammeImportCommandReceipt", "", None, ("resulting_version",)),
    ("ProgrammeReviewPolicy", "call__", None, ("version",)),
    ("ProgrammeReviewCase", "proposal__", "state", ("version", "stage")),
    ("ProgrammeReviewAssignment", "case__proposal__", "state", ("version",)),
    ("ProgrammeReviewEntry", "case__proposal__", None, ("version", "stage")),
    ("ProgrammeReviewDecision", "entry__case__proposal__", None, ()),
    ("ProgrammeDecisionAcknowledgement", "decision__entry__case__proposal__", None, ()),
    ("ProgrammeReviewReceipt", "", None, ("resulting_version",)),
    (
        "ProgrammeFileIntake",
        "",
        None,
        ("source_version", "call_version", "definition_version"),
    ),
    ("ProgrammeFileContent", "intake__", None, ()),
    ("ProgrammeAcceptedTransition", "", None, ("resulting_programme_version",)),
)


def load_programme_stop_applications(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> ProgrammeStopInventory:
    """Count every adopted Applications relation at its minimized stop ceiling.

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
        Complete counts and metadata fingerprint, without row identities, proposal
        text, reviews, applicant profiles, configuration labels or file bytes.

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
                operation="applications.query.programme_stop",
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
            if not applications_database_integrity_is_ready():
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
                owner="applications",
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
