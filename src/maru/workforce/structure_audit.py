"""Value-minimized audit evidence for workforce structure reads."""

from datetime import datetime
from uuid import UUID

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision
from maru.identity.models import Account

_STRUCTURE_AUDIT_HTTP_METHODS = frozenset({"GET", "HEAD", "POST"})


def append_structure_read_audit(
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
    """Append the required minimized evidence before releasing holder labels.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    decision : PolicyDecision
        The decision evaluated while append structure read audit.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    route_name : str
        The human-readable route name shown to authorized readers.
    http_method : str
        The http method evaluated while append structure read audit.
    source_channel : str
        The closed channel code identifying where the request originated.
    occurred_at : datetime
        The timezone-aware timestamp for occurred.

    Returns
    -------
    AuditEvent
        The updated AuditEvent after the transition is committed.

    Raises
    ------
    ValueError
        If the supplied value cannot satisfy the documented contract.
    """
    if not decision.allowed:
        raise ValueError("A denied structure decision cannot produce an allow audit.")
    if http_method not in _STRUCTURE_AUDIT_HTTP_METHODS:
        raise ValueError("Use an exact supported structure audit HTTP method.")
    obligations = frozenset(decision.obligations) | {"audit_sensitive_read"}
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="workforce.view_structure",
            operation="workforce.structure.read",
            target_type="workforce.edition_structure",
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
            retention_class="workforce-restricted",
        ),
        occurred_at=occurred_at,
    )
