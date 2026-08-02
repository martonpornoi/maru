"""Value-minimized audit evidence for workforce structure reads."""

from datetime import datetime
from uuid import UUID

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import PolicyDecision
from maru.identity.models import Account


def append_structure_read_audit(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    decision: PolicyDecision,
    correlation_id: UUID,
    route_name: str,
    source_channel: str,
    occurred_at: datetime,
) -> AuditEvent:
    """Append the required minimized evidence before releasing holder labels."""

    if not decision.allowed:
        raise ValueError("A denied structure decision cannot produce an allow audit.")
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
                "http_method": "GET",
            },
            retention_class="workforce-restricted",
        ),
        occurred_at=occurred_at,
    )
