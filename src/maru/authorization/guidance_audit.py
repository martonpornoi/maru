"""Content-free native audit and outbox records for Guidance responsibility commands."""

from uuid import UUID

from maru.audit.services import AuditRecord
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.models import Account


def guidance_authority_audit(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    operation: str,
    target_type: str,
    target_id: UUID,
    correlation_id: UUID,
    capability_code: str = "authorization.manage_guidance_access",
) -> AuditRecord:
    """Describe one closed mutation without copying people, text or human reasons.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.
    operation : str
        Closed workflow operation retained in the event or audit record.
    target_type : str
        Canonical audited owner record type.
    target_id : UUID
        Opaque owner record identity retained in the audit envelope.
    correlation_id : UUID
        Non-empty audit trace for this attempt.
    capability_code : str, default="authorization.manage_guidance_access"
        Exact capability used to admit the privileged operation.

    Returns
    -------
    AuditRecord
        The admitted immutable result; it grants no additional authority.
    """
    return AuditRecord(
        principal_kind="account",
        principal_id=actor.id,
        principal_context_id=None,
        organization_id=organization_id,
        event_edition_id=edition_id,
        capability_code=capability_code,
        operation=operation,
        target_type=target_type,
        target_id=target_id,
        outcome="allow",
        reason_code="accepted_guidance_responsibility",
        correlation_id=correlation_id,
        source_channel="service",
        obligations=("audit",),
        changed_fields=("responsibility",),
    )


def publish_guidance_authority_event(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    event_name: str,
    operation: str,
    aggregate_type: str,
    aggregate_id: UUID,
    correlation_id: UUID,
    audit_id: UUID,
) -> None:
    """Retain only the closed operation and existing event envelope.

    Parameters
    ----------
    actor : Account
        Actual authenticated person; a submitted identity cannot replace this actor.
    organization_id : UUID
        Exact organization owning the requested scope.
    edition_id : UUID
        Exact event edition within the organization.
    event_name : str
        Closed content-free domain-event name.
    operation : str
        Closed workflow operation retained in the event or audit record.
    aggregate_type : str
        Canonical owner type for the retained event envelope.
    aggregate_id : UUID
        Opaque identity of the original event aggregate.
    correlation_id : UUID
        Non-empty audit trace for this attempt.
    audit_id : UUID
        Actual privileged mutation audit record causing this event.
    """
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=organization_id,
            event_edition_id=edition_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=1,
            payload={"operation": operation},
            correlation_id=correlation_id,
            causation_id=audit_id,
            actor_kind="account",
            actor_id=actor.id,
        )
    )
