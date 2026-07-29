"""Authorized application services for edition state transitions."""

from collections.abc import Collection
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION, require_capability
from maru.authorization.enforcement import (
    BulkTargetDeniedError,
    BulkTargetUnavailableError,
    freeze_bulk_targets,
)
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EditionLifecycleTransition, EventEdition
from maru.identity.models import Account

ALLOWED_TRANSITIONS: dict[str, Collection[str]] = {
    EventEdition.Lifecycle.DRAFT: {
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.CANCELLED,
    },
    EventEdition.Lifecycle.PREPARING: {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.CANCELLED,
    },
    EventEdition.Lifecycle.READY: {
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.LIVE,
        EventEdition.Lifecycle.CANCELLED,
    },
    EventEdition.Lifecycle.LIVE: {EventEdition.Lifecycle.CLOSING},
    EventEdition.Lifecycle.CLOSING: {EventEdition.Lifecycle.ARCHIVED},
    EventEdition.Lifecycle.ARCHIVED: set(),
    EventEdition.Lifecycle.CANCELLED: set(),
}


def _transition_audit_record(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    outcome: str,
    reason_code: str,
    obligations: tuple[str, ...] = (),
    changed_fields: tuple[str, ...] = (),
) -> AuditRecord:
    return AuditRecord(
        principal_kind="account",
        principal_id=actor.id,
        principal_context_id=None,
        organization_id=organization_id,
        event_edition_id=edition_id,
        capability_code="events.transition",
        operation="events.edition.transition",
        target_type="events.event_edition",
        target_id=edition_id,
        outcome=outcome,
        reason_code=reason_code,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=changed_fields,
        safe_metadata={"policy_version": POLICY_VERSION},
    )


def _bulk_transition_audit_record(
    *,
    actor: Account,
    organization_id: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    target_count: int,
    outcome: str,
    reason_code: str,
) -> AuditRecord:
    obligations = tuple(sorted(require_capability("events.transition").obligations))
    return AuditRecord(
        principal_kind="account",
        principal_id=actor.id,
        principal_context_id=None,
        organization_id=organization_id,
        event_edition_id=None,
        capability_code="events.transition",
        operation="events.edition.bulk_transition",
        target_type="events.event_edition_set",
        target_id=None,
        outcome=outcome,
        reason_code=reason_code,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=(
            ("lifecycle", "lifecycle_version")
            if outcome == AuditEvent.Outcome.ALLOW
            else ()
        ),
        safe_metadata={
            "policy_version": POLICY_VERSION,
            "target_count": target_count,
        },
    )


def _require_valid_transition(edition: EventEdition, *, to_state: str) -> None:
    allowed = ALLOWED_TRANSITIONS[edition.lifecycle]
    if to_state not in allowed:
        raise ValidationError(
            {
                "lifecycle": (
                    f"Cannot transition an edition from {edition.lifecycle} "
                    f"to {to_state}."
                )
            },
            code="invalid_transition",
        )


def transition_edition(
    *,
    organization_id: UUID,
    edition_id: UUID,
    to_state: str,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> EventEdition:
    decision = decide(
        principal=actor,
        capability_code="events.transition",
        resource=ResourceScope(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=decision.reason_code,
            )
        )
        raise AuthorizationDenied(
            "The edition lifecycle transition is not permitted.",
            reason_code=decision.reason_code,
        )

    normalized_reason = reason.strip()
    if not normalized_reason:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="reason_required",
                obligations=tuple(sorted(decision.obligations)),
            )
        )
        raise ValidationError(
            {"reason": "A transition reason is required."},
            code="reason_required",
        )

    try:
        with transaction.atomic():
            edition = EventEdition.objects.select_for_update().get(
                pk=edition_id,
                organization_id=organization_id,
            )
            _require_valid_transition(edition, to_state=to_state)

            previous_state = edition.lifecycle
            if to_state == EventEdition.Lifecycle.ARCHIVED:
                from maru.events.closure import assert_archive_ready  # noqa: PLC0415
                from maru.participation.services import (  # noqa: PLC0415
                    snapshot_participations_for_archive,
                )

                assert_archive_ready(edition)
                snapshot_participations_for_archive(edition_id=edition.id)

            edition.lifecycle = to_state
            edition.lifecycle_version += 1
            edition.save(update_fields=("lifecycle", "lifecycle_version", "updated_at"))
            EditionLifecycleTransition.objects.create(
                edition=edition,
                from_state=previous_state,
                to_state=to_state,
                actor_id=actor.id,
                reason=normalized_reason,
            )
            audit_event = append_audit(
                _transition_audit_record(
                    actor=actor,
                    organization_id=organization_id,
                    edition_id=edition_id,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                    outcome=AuditEvent.Outcome.ALLOW,
                    reason_code=decision.reason_code,
                    obligations=tuple(sorted(decision.obligations)),
                    changed_fields=("lifecycle", "lifecycle_version"),
                )
            )
            publish_domain_event(
                DomainEventRecord(
                    event_name="events.edition.lifecycle_transitioned.v1",
                    schema_version=1,
                    organization_id=edition.organization_id,
                    event_edition_id=edition.id,
                    aggregate_type="events.event_edition",
                    aggregate_id=edition.id,
                    aggregate_version=edition.lifecycle_version,
                    payload={
                        "from_state": previous_state,
                        "to_state": to_state,
                    },
                    correlation_id=correlation_id,
                    causation_id=audit_event.id,
                    actor_kind="account",
                    actor_id=actor.id,
                ),
                workload_pool="core",
            )
            return edition
    except EventEdition.DoesNotExist:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="edition_not_found",
                obligations=tuple(sorted(decision.obligations)),
            )
        )
        raise
    except ValidationError:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="invalid_transition",
                obligations=tuple(sorted(decision.obligations)),
            )
        )
        raise
    except Exception:
        append_audit(
            _transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="transition_failed",
                obligations=tuple(sorted(decision.obligations)),
            )
        )
        raise


def bulk_transition_editions(
    *,
    organization_id: UUID,
    edition_ids: tuple[UUID, ...],
    to_state: str,
    actor: Account,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> tuple[EventEdition, ...]:
    """Atomically transition an exact, locked, independently authorized set."""

    target_count = len(edition_ids)
    try:
        with transaction.atomic():
            targets = freeze_bulk_targets(
                trusted_queryset=EventEdition.objects.filter(
                    organization_id=organization_id
                ),
                target_ids=edition_ids,
                authorize=lambda edition: decide(
                    principal=actor,
                    capability_code="events.transition",
                    resource=ResourceScope(
                        organization_id=organization_id,
                        edition_id=edition.id,
                        state=edition.lifecycle,
                    ),
                ),
            )
            transitioned = tuple(
                transition_edition(
                    organization_id=organization_id,
                    edition_id=edition.id,
                    to_state=to_state,
                    actor=actor,
                    reason=reason,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                )
                for edition in targets
            )
            append_audit(
                _bulk_transition_audit_record(
                    actor=actor,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                    target_count=target_count,
                    outcome=AuditEvent.Outcome.ALLOW,
                    reason_code="bulk_targets_authorized",
                )
            )
            return transitioned
    except BulkTargetDeniedError as error:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=error.reason_code,
            )
        )
        raise
    except AuthorizationDenied as error:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.DENY,
                reason_code=error.reason_code,
            )
        )
        raise
    except BulkTargetUnavailableError:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="bulk_target_unavailable",
            )
        )
        raise
    except ValidationError:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="invalid_transition",
            )
        )
        raise
    except Exception:
        append_audit(
            _bulk_transition_audit_record(
                actor=actor,
                organization_id=organization_id,
                correlation_id=correlation_id,
                request_id=request_id,
                source_channel=source_channel,
                target_count=target_count,
                outcome=AuditEvent.Outcome.ERROR,
                reason_code="bulk_transition_failed",
            )
        )
        raise
