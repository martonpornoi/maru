"""Edition closure reconciliation and immutable archive manifest."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.accreditation.models import OfflineCheckInOperation
from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.services import AuthorizationDenied
from maru.communications.models import NotificationDelivery
from maru.effects.models import OutboxMessage
from maru.events.models import (
    EditionClosureManifest,
    EditionReadinessGate,
    EventEdition,
)
from maru.identity.models import Account, AccountRestriction, RestrictionAppeal
from maru.privacyops.models import PostEditionCorrection
from maru.registration.models import (
    AttendeeFursuit,
    AttendeeRegistrationProfile,
    FinancialOperation,
    GuardianConsent,
    MediaReviewStatus,
    PaymentException,
    Registration,
    SettlementBatch,
)

REQUIRED_GATE_CODES = frozenset(EditionReadinessGate.Code.values)


def _require_closure_authority(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
) -> tuple[str, ...]:
    decision = decide(
        principal=actor,
        capability_code="events.transition",
        resource=ResourceScope(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "Edition closure management is unavailable.",
            reason_code=decision.reason_code,
        )
    return tuple(sorted(decision.obligations))


def review_readiness_gate(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    code: str,
    approve: bool,
    evidence_reference: str,
    summary: str,
    correlation_id: UUID,
) -> EditionReadinessGate:
    obligations = _require_closure_authority(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if code not in EditionReadinessGate.Code.values:
        raise ValidationError(
            "Choose a supported readiness gate.",
            code="readiness_gate_code_invalid",
        )
    normalized_evidence = evidence_reference.strip()
    normalized_summary = summary.strip()
    if not normalized_evidence or not normalized_summary:
        raise ValidationError(
            "A readiness decision requires evidence and a review summary.",
            code="readiness_gate_evidence_required",
        )
    reviewed_at = timezone.now()
    with transaction.atomic():
        edition = EventEdition.objects.get(
            id=edition_id,
            organization_id=organization_id,
        )
        gate, _ = EditionReadinessGate.objects.select_for_update().get_or_create(
            edition=edition,
            code=code,
            defaults={"organization_id": organization_id},
        )
        gate.status = (
            EditionReadinessGate.Status.APPROVED
            if approve
            else EditionReadinessGate.Status.REJECTED
        )
        gate.evidence_reference = normalized_evidence
        gate.review_summary = normalized_summary
        gate.reviewed_by_id = actor.id
        gate.reviewed_at = reviewed_at
        gate.full_clean()
        gate.save()
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor.id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="events.transition",
                operation="events.readiness_gate.review",
                target_type="events.edition_readiness_gate",
                target_id=gate.id,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=(
                    "readiness_gate_approved" if approve else "readiness_gate_rejected"
                ),
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="api",
                obligations=obligations,
                changed_fields=("readiness_gate",),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="security-extended",
            )
        )
        return gate


def closure_counts(*, organization_id: UUID, edition_id: UUID) -> dict[str, int]:
    now = timezone.now()
    return {
        "guardian_pending": Registration.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            state=Registration.State.GUARDIAN_PENDING,
        ).count(),
        "payment_pending": Registration.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            state=Registration.State.PAYMENT_PENDING,
        ).count(),
        "waitlisted": Registration.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            state=Registration.State.WAITLISTED,
        ).count(),
        "guardian_requests_open": GuardianConsent.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=GuardianConsent.Status.PENDING,
        ).count(),
        "payment_exceptions_open": PaymentException.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=PaymentException.Status.OPEN,
        ).count(),
        "financial_operations_open": FinancialOperation.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status__in=(
                FinancialOperation.Status.PROPOSED,
                FinancialOperation.Status.APPROVED,
                FinancialOperation.Status.PROVIDER_PENDING,
            ),
        ).count(),
        "settlements_open": SettlementBatch.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .exclude(status=SettlementBatch.Status.RECONCILED)
        .count(),
        "delivery_failures": NotificationDelivery.objects.filter(
            message__organization_id=organization_id,
            message__edition_id=edition_id,
            status=NotificationDelivery.Status.PERMANENT_FAILED,
        ).count(),
        "delivery_pending": NotificationDelivery.objects.filter(
            message__organization_id=organization_id,
            message__edition_id=edition_id,
            status=NotificationDelivery.Status.PENDING,
        ).count(),
        "profile_media_pending": (
            AttendeeRegistrationProfile.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                profile_photo_status=MediaReviewStatus.PENDING,
            ).count()
            + AttendeeFursuit.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
                photo_status=MediaReviewStatus.PENDING,
            ).count()
        ),
        "historical_corrections_open": PostEditionCorrection.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=PostEditionCorrection.Status.PROPOSED,
        ).count(),
        "restriction_consequences_due": AccountRestriction.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            status=AccountRestriction.Status.ACTIVE,
            effective_at__lte=now,
            consequences_applied_at__isnull=True,
        ).count(),
        "restriction_appeals_open": RestrictionAppeal.objects.filter(
            restriction__organization_id=organization_id,
            restriction__edition_id=edition_id,
            status=RestrictionAppeal.Status.OPEN,
        ).count(),
        "offline_conflicts": OfflineCheckInOperation.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            outcome__in=(
                OfflineCheckInOperation.Outcome.CONFLICT,
                OfflineCheckInOperation.Outcome.REJECTED,
            ),
        ).count(),
        "outbox_unfinished": OutboxMessage.objects.filter(
            organization_id=organization_id,
            event__event_edition_id=edition_id,
            status__in=(
                OutboxMessage.Status.PENDING,
                OutboxMessage.Status.PROCESSING,
                OutboxMessage.Status.QUARANTINED,
            ),
        ).count(),
    }


def _assert_gates(edition: EventEdition) -> None:
    approved = set(
        edition.readiness_gates.filter(
            status=EditionReadinessGate.Status.APPROVED
        ).values_list("code", flat=True)
    )
    missing = sorted(REQUIRED_GATE_CODES - approved)
    if missing:
        raise ValidationError(
            {
                "readiness_gates": (
                    "Closure requires approved gates: " + ", ".join(missing)
                )
            },
            code="edition_readiness_gates_incomplete",
        )


def generate_closure_manifest(
    *,
    edition: EventEdition,
    actor: Account,
    recovery_reference: str,
) -> EditionClosureManifest:
    _require_closure_authority(
        actor=actor,
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    normalized_recovery = recovery_reference.strip()
    if edition.lifecycle != EventEdition.Lifecycle.CLOSING:
        raise ValidationError(
            "Closure manifests are generated only while an edition is closing.",
            code="edition_not_closing",
        )
    if not normalized_recovery:
        raise ValidationError(
            "Record the restore/recovery exercise reference.",
            code="closure_recovery_reference_required",
        )
    _assert_gates(edition)
    counts = closure_counts(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    blockers = {name: count for name, count in counts.items() if count}
    if blockers:
        raise ValidationError(
            {
                "closure": (
                    "Closure has unresolved queues: "
                    + ", ".join(
                        f"{name}={count}" for name, count in sorted(blockers.items())
                    )
                )
            },
            code="edition_closure_blocked",
        )
    canonical = json.dumps(counts, sort_keys=True, separators=(",", ":")).encode()
    with transaction.atomic():
        EventEdition.objects.select_for_update().get(id=edition.id)
        if EditionClosureManifest.objects.filter(edition=edition).exists():
            raise ValidationError(
                "The immutable closure manifest already exists.",
                code="edition_closure_manifest_exists",
            )
        return EditionClosureManifest.objects.create(
            edition=edition,
            organization_id=edition.organization_id,
            generated_by_id=actor.id,
            generated_at=timezone.now(),
            counts=counts,
            manifest_digest=hashlib.sha256(canonical).hexdigest(),
            recovery_reference=normalized_recovery,
        )


def assert_archive_ready(edition: EventEdition) -> None:
    if not settings.ENFORCE_EDITION_CLOSURE_GATES:
        return
    _assert_gates(edition)
    manifest = EditionClosureManifest.objects.filter(edition=edition).first()
    if manifest is None:
        raise ValidationError(
            "Generate a closure manifest before archiving.",
            code="edition_closure_manifest_required",
        )
    current = closure_counts(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    if current != manifest.counts or any(current.values()):
        raise ValidationError(
            "Edition closure state changed after its manifest.",
            code="edition_closure_manifest_stale",
        )
