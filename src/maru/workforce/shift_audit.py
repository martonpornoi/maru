"""Value-minimized evidence for organizer reads of Shift coverage."""

from datetime import datetime
from uuid import UUID

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision
from maru.identity.models import Account

_SHIFT_AUDIT_HTTP_METHODS = frozenset({"GET", "HEAD", "POST"})


def append_shift_read_audit(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    decision: PolicyDecision,
    correlation_id: UUID,
    route_name: str,
    http_method: str,
    source_channel: str,
    occurred_at: datetime,
) -> AuditEvent:
    """Append evidence before names and suitability state are released.

    Parameters
    ----------
    actor : Account
        Authenticated organizer whose read is being evidenced.
    organization_id : UUID
        Exact organization owning the protected projection.
    edition_id : UUID
        Exact edition owning the protected projection.
    decision : PolicyDecision
        Fresh allowed policy decision with the required field ceiling.
    correlation_id : UUID
        Request correlation identifier.
    route_name : str
        Stable browser or API route name.
    http_method : str
        Supported request method that released or loaded the protected
        projection: ``GET``, ``HEAD``, or mutation-adjacent ``POST``.
    source_channel : str
        Registered trusted adapter channel.
    occurred_at : datetime
        Instant at which the decision was evaluated.

    Returns
    -------
    AuditEvent
        Persisted value-minimized allow evidence.

    Raises
    ------
    ValueError
        If the policy decision is denied or the method cannot load the
        protected Shift projection.
    """
    if not decision.allowed:
        raise ValueError("A denied Shift decision cannot produce an allow audit.")
    if http_method not in _SHIFT_AUDIT_HTTP_METHODS:
        raise ValueError("Use a supported Shift projection request method.")
    obligations = frozenset(decision.obligations) | {"audit_sensitive_read"}
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="workforce.view_shifts",
            operation="workforce.shift_coverage.read",
            target_type="events.event_edition",
            target_id=edition_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(obligations)),
            changed_fields=(),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "route_name": route_name,
                "http_method": http_method,
            },
            retention_class="workforce-personal",
        ),
        occurred_at=occurred_at,
    )
