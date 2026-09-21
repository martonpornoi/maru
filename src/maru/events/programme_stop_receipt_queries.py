"""Original-actor stop receipt detail at a minimized historical field ceiling."""

from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.services import AuthorizationDenied

from .models import ProgrammeStopReceipt
from .programme_stop_composition import _locked_stop_scope


@dataclass(frozen=True, slots=True)
class ProgrammeStopReceiptDetail:
    """Retain only one's own reason and immutable terminal outcome.

    Attributes
    ----------
    receipt_id, organization_id, edition_id
        Exact acknowledged receipt and its independently admitted context.
    reason
        Original actor's own accountable rationale, never a source record reason.
    aggregate_version, lifecycle_version
        Versions committed with the terminal transition.
    release_withdrawn
        Whether this command actually withdrew a stored release.
    """

    receipt_id: UUID
    organization_id: UUID
    edition_id: UUID
    reason: str
    aggregate_version: int
    lifecycle_version: int
    release_withdrawn: bool


def load_programme_stop_receipt(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    receipt_id: UUID,
    correlation_id: UUID,
) -> ProgrammeStopReceiptDetail:
    """Read one's exact acknowledged outcome after current controller admission.

    Parameters
    ----------
    actor_id : UUID
        Actual signed-in original requester with current stop prerequisites.
    organization_id, edition_id : UUID
        Independently selected exact adopted scope.
    receipt_id : UUID
        Previously acknowledged receipt; no enumeration or other-actor history.
    correlation_id : UUID
        Trusted non-nil disclosure audit trace.

    Returns
    -------
    ProgrammeStopReceiptDetail
        Immutable minimized historical result, never permission to reopen work.

    Raises
    ------
    ValidationError
        If trusted trace, scope readiness or complete native evidence is unavailable.
    AuthorizationDenied
        If current admission or the exact original-actor receipt is unavailable.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (receipt_id, correlation_id)
    ):
        raise ValidationError(
            "Use an exact receipt trace.", code="programme_stop_trace"
        )
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
                operation="events.programme_stop.receipt",
                target_type="events.programme_stop_receipt",
                target_id=receipt_id if allowed else None,
                outcome="allow" if allowed else "deny",
                reason_code="programme_stop_history"
                if allowed
                else "programme_stop_unavailable",
                correlation_id=correlation_id,
                source_channel="programme-stop",
                obligations=("audit_sensitive_read",),
                retention_class="programme-restricted",
            )
        )

    def require_row() -> ProgrammeStopReceipt:
        row = ProgrammeStopReceipt.objects.filter(id=receipt_id, **scope).first()
        if row is None:
            raise AuthorizationDenied(
                "Programme stop receipt unavailable.",
                reason_code="programme_stop_unavailable",
            )
        return row

    try:
        with _locked_stop_scope(**scope):
            row = require_row()
            result = ProgrammeStopReceiptDetail(
                row.id,
                row.organization_id,
                row.edition_id,
                row.reason,
                row.expected_aggregate_version + 1,
                row.expected_lifecycle_version + 1,
                row.impact_document["withdrawal"] is not None,
            )
            audit(allowed=True)
    except AuthorizationDenied:
        audit(allowed=False)
        raise
    return result
