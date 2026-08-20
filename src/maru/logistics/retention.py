"""Bounded, idempotent disposal of expired restricted Logistics contacts."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.effects.services import DomainEventRecord, publish_domain_event

from .models import LogisticsNode, RestrictedLogisticsAddress
from .writer_boundary import logistics_writer

if TYPE_CHECKING:
    from datetime import datetime

MAX_RETENTION_DISPOSALS = 500


@transaction.atomic
def dispose_expired_restricted_addresses(
    *,
    organization_id: UUID,
    edition_id: UUID | None,
    correlation_id: UUID,
    limit: int = 100,
    now: datetime | None = None,
) -> tuple[UUID, ...]:
    """Redact one explicit tenant/edition batch; repeated runs are no-ops.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID | None
        The event edition identifier that scopes the operation.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    limit : int, default=100
        The maximum number of records to return.
    now : datetime | None, default=None
        The injectable timezone-aware instant used for deterministic evaluation.

    Returns
    -------
    tuple[UUID, ...]
        The matching dispose expired restricted addresses records in
        deterministic order.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not isinstance(organization_id, UUID) or (
        edition_id is not None and not isinstance(edition_id, UUID)
    ):
        raise ValidationError("Use canonical tenant and edition identifiers.")
    if not isinstance(correlation_id, UUID):
        raise ValidationError("Use a canonical correlation identifier.")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= MAX_RETENTION_DISPOSALS
    ):
        raise ValidationError(
            f"Dispose between 1 and {MAX_RETENTION_DISPOSALS} addresses per run."
        )
    evaluated_at = now or timezone.now()
    addresses = tuple(
        RestrictedLogisticsAddress.objects.select_for_update(skip_locked=True)
        .filter(
            organization_id=organization_id,
            edition_id=edition_id,
            lifecycle=RestrictedLogisticsAddress.Lifecycle.ACTIVE,
            retention_until__lte=evaluated_at,
        )
        .exclude(return_agreements__return_due_at__gte=evaluated_at)
        .exclude(equipment_offers__available_until__gte=evaluated_at)
        .exclude(equipment_offers__requested_return_at__gte=evaluated_at)
        .exclude(logistics_nodes__lifecycle=LogisticsNode.Lifecycle.ACTIVE)
        .order_by("retention_until", "id")[:limit]
    )
    disposed_ids: list[UUID] = []
    for address in addresses:
        prior_version = address.aggregate_version
        with logistics_writer():
            address.subject_account = None
            address.party = None
            address.label = "Disposed"
            address.recipient_name = ""
            address.contact_email = ""
            address.contact_phone = ""
            address.postal_address = ""
            address.access_instructions = ""
            address.lifecycle = RestrictedLogisticsAddress.Lifecycle.DISPOSED
            address.aggregate_version = prior_version + 1
            address.save(
                update_fields=(
                    "subject_account",
                    "party",
                    "label",
                    "recipient_name",
                    "contact_email",
                    "contact_phone",
                    "postal_address",
                    "access_instructions",
                    "lifecycle",
                    "aggregate_version",
                    "updated_at",
                )
            )
        audit = append_audit(
            AuditRecord(
                principal_kind="service",
                principal_id=None,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="logistics.retention.dispose",
                operation="logistics.restricted_address.dispose",
                target_type="logistics.restricted_address",
                target_id=address.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="retention_expired",
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="scheduler",
                changed_fields=(
                    "contact_values",
                    "lifecycle",
                    "subject_link",
                ),
                safe_metadata={
                    "policy_version": POLICY_VERSION,
                    "target_count": 1,
                },
                retention_class="logistics-retention-evidence",
            ),
            occurred_at=evaluated_at,
        )
        publish_domain_event(
            DomainEventRecord(
                event_name="logistics.record.changed.v1",
                schema_version=1,
                organization_id=organization_id,
                event_edition_id=edition_id,
                aggregate_type="logistics.restricted_address",
                aggregate_id=address.id,
                aggregate_version=address.aggregate_version,
                payload={
                    "action": "disposed",
                    "record_type": "logistics.restricted_address",
                    "record_id": str(address.id),
                },
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor_kind="service",
                actor_id=None,
                retention_class="logistics-retention-evidence",
            ),
            occurred_at=evaluated_at,
        )
        disposed_ids.append(address.id)
    return tuple(disposed_ids)
